"""Minimal Chrome DevTools Protocol client over --remote-debugging-pipe, standard library only.

The overlay driver of the renderer (amendment A1 of the short-video plan, as reviewed):
  - the browser is started headless with its sandbox ON, in its own session, and stopped with killpg; every host is mapped
    to "not found". Only inside the renderer's own container image (see container_mode) is the sandbox off, with the container
    as the boundary, and the render's facts say so. A failed start is a failure, never a retry;
  - nothing is ever navigated to file://: the Fetch domain answers every request of every page from memory under ONE
    synthetic origin, and every other request is failed and recorded;
  - the pipe is fds 3 (commands in) and 4 (replies out), NUL-delimited JSON;
  - a Content-Security-Policy is set on every served page, and a violation fails the render.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import fcntl

ORIGIN = "https://render.invalid"

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'")

# Freezes the clocks and the random source and makes timers throw (determinism contract).
FREEZE_JS = r"""
(() => {
  const boom = (n) => () => { throw new Error(n + ' is forbidden in a template'); };
  Date.now = boom('Date.now');
  window.Date = function () { throw new Error('Date is forbidden in a template'); };
  performance.now = boom('performance.now');
  Math.random = boom('Math.random');
  window.setTimeout = boom('setTimeout');
  window.setInterval = boom('setInterval');
  window.requestAnimationFrame = boom('requestAnimationFrame');
  window.fetch = boom('fetch');
  window.XMLHttpRequest = function () { throw new Error('XMLHttpRequest is forbidden'); };
  window.WebSocket = function () { throw new Error('WebSocket is forbidden'); };
  window.Worker = function () { throw new Error('Worker is forbidden'); };
  window.__csp = [];
  window.addEventListener('securitypolicyviolation', (e) => { window.__csp.push(e.blockedURI + ' ' + e.violatedDirective); }, true);
})();
"""

# Sets the colour tokens (CSSOM setProperty, values validated in Python), registers the fonts,
# awaits document.fonts.ready, checks every declared family and decodes every image before frame 0.
SETUP_JS = r"""
window.__setup = async (cfg) => {
  const rs = document.documentElement.style;
  for (const [k, v] of Object.entries(cfg.colors)) rs.setProperty('--c-' + k, v);
  for (const [role, f] of Object.entries(cfg.fonts)) {
    rs.setProperty('--weight-' + role, String(f.weight));
    if (f.url) {
      const face = new FontFace('pv-' + role, 'url(' + f.url + ')', { weight: String(f.weight) });
      await face.load();
      document.fonts.add(face);
      rs.setProperty('--font-' + role, 'pv-' + role + ', ' + f.fallback);
    } else {
      rs.setProperty('--font-' + role, f.fallback);
    }
  }
  await document.fonts.ready;
  for (const [role, f] of Object.entries(cfg.fonts)) {
    if (f.url && !document.fonts.check(String(f.weight) + ' 20px pv-' + role)) throw new Error('font missing: ' + role);
  }
  window.__imgs = {};
  for (const [slot, url] of Object.entries(cfg.images)) {
    const im = new Image();
    im.src = url;
    await im.decode();
    window.__imgs[slot] = im;
  }
  // One pixel at the top-left corner is cut out of the page, so that it is transparent. Chrome writes a frame with no
  // transparent pixel (a full-frame cutaway) as an RGB PNG and every other frame as RGBA; when the format changes in the
  // middle of the sequence ffmpeg reconfigures its whole graph, and the render stalls.
  document.documentElement.style.clipPath = 'polygon(1px 0, 100% 0, 100% 100%, 0 100%, 0 1px, 1px 1px)';
  if (typeof window.renderAt !== 'function') throw new Error('template has no renderAt');
  return true;
};
window.__frame = (t, data) => {
  if (window.__csp.length) throw new Error('blocked by policy: ' + window.__csp[0]);
  window.renderAt(t, data);
  if (document.getAnimations().length !== 0) throw new Error('animation running after renderAt');
  // the boxes of every drawn card and caption (an element a template marks with data-zone), for the face-box check
  const boxes = [];
  document.querySelectorAll('[data-zone]').forEach((el) => {
    const r = el.getBoundingClientRect();
    boxes.push({ zone: el.dataset.zone, x: r.left, y: r.top, w: r.width, h: r.height });
  });
  return { html: document.documentElement.outerHTML, boxes: boxes };
};
"""


IMAGE_MARKER = "/etc/openhora-renderer-image"


def container_mode() -> bool:
    """True only inside the renderer's own image: the image's environment says so AND the marker file its definition writes
    exists. This is the one place that lets the browser run without its own sandbox, and nothing else turns it on: a
    process on the host never has that file, whatever its environment says."""
    return os.environ.get("RENDERER_IN_CONTAINER") == "1" and os.path.isfile(IMAGE_MARKER)


class CDPError(RuntimeError):
    pass


class RenderBlocked(RuntimeError):
    """A page asked for something that is not served from memory."""


def browser_version(path):
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


# The browser reads its commands from fd 3 and writes its replies to fd 4 (--remote-debugging-pipe). No shell is involved:
# a small interpreter step puts the two pipe ends there and replaces itself with the browser, so the launch does not depend
# on which /bin/sh the machine has (the image's is dash, which rejects redirections to fd numbers above 9).
LAUNCHER = (
    "import os, sys\n"
    "b, r, w = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])\n"
    "os.dup2(r, 3); os.dup2(w, 4)\n"
    "os.close(r); os.close(w)\n"
    "try:\n"
    "    os.execv(b, [b] + sys.argv[4:])\n"
    "except OSError as e:\n"
    "    import errno\n"
    "    print('exec failed: ' + errno.errorcode.get(e.errno, 'UNKNOWN'), file=sys.stderr)\n"
    "    os._exit(127)\n"
)


class Chrome:
    """One browser process, one pipe. Pages are CDP sessions; all share the served-from-memory table."""

    def __init__(self, browser, serve, workdir, headless_flag="--headless", time_limit=1800, log_path=None, extra_flags=None):
        self.browser = browser
        self.serve = serve          # url path -> (bytes, mime)
        self.workdir = workdir
        self.blocked = []
        self.page_errors = []     # what the browser itself refused (a file: URL, a blocked local resource) and logged as an error
        self.proc = None
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending = {}
        self._events = queue.Queue()
        self._closed = False
        self._time_limit = time_limit
        self.log_path = log_path or os.path.join(workdir, "chrome.log")
        self._timer = None
        self.headless_flag = headless_flag
        self.extra_flags = list(extra_flags or [])

    # ---- process
    def start(self):
        os.makedirs(self.workdir, exist_ok=True)
        profile = os.path.join(self.workdir, "profile")
        os.makedirs(profile, exist_ok=True)
        cmd_r, cmd_w = os.pipe()
        rep_r, rep_w = os.pipe()
        # move our ends above 9 so the launcher's dup2 onto 3 and 4 cannot clobber them
        cmd_r2 = fcntl.fcntl(cmd_r, fcntl.F_DUPFD, 10)
        rep_w2 = fcntl.fcntl(rep_w, fcntl.F_DUPFD, 10)
        os.close(cmd_r)
        os.close(rep_w)
        flags = [
            "--remote-debugging-pipe",
            "--user-data-dir=" + profile,
            "--host-resolver-rules=MAP * ~NOTFOUND",
            "--hide-scrollbars", "--mute-audio", "--force-color-profile=srgb",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--disable-component-update", "--disable-sync",
            "--disable-default-apps", "--font-render-hinting=none", "--disable-lcd-text",
            "--allow-pre-commit-input", "--disable-gpu", "--disable-gpu-rasterization", "--disable-partial-raster",
        ]
        # The browser's own sandbox is ON everywhere except inside the renderer's image, where the container is the boundary
        # (no network, a read-only root, no capability, a non-root user, no new privileges) and Chrome's sandbox cannot start
        # without the user namespaces those limits remove. There is no retry: a browser that fails to start is a render failure.
        self.sandbox = "off" if container_mode() else "on"
        if self.sandbox == "off":
            flags += ["--no-sandbox", "--disable-dev-shm-usage", "--disable-crash-reporter"]
        flags += self.extra_flags
        if self.headless_flag:
            flags.insert(0, self.headless_flag)
        log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-I", "-c", LAUNCHER, self.browser, str(cmd_r2), str(rep_w2)] + flags,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            pass_fds=(cmd_r2, rep_w2), start_new_session=True)
        os.close(cmd_r2)
        os.close(rep_w2)
        log.close()
        self._wfd, self._rfd = cmd_w, rep_r
        atexit.register(self.close)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._handler = threading.Thread(target=self._event_loop, daemon=True)
        self._handler.start()
        self._timer = threading.Timer(self._time_limit, self._kill_group)
        self._timer.daemon = True
        self._timer.start()
        ver = self.send("Browser.getVersion")
        return ver

    def _kill_group(self):
        if self.proc is not None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._timer:
            self._timer.cancel()
        if self.proc is not None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._kill_group()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            # the rest of the group (renderer, GPU, network helpers)
            self._kill_group()
        for fd in (getattr(self, "_wfd", None), getattr(self, "_rfd", None)):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._events.put(None)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- wire
    def _read_loop(self):
        buf = b""
        while True:
            try:
                chunk = os.read(self._rfd, 1 << 20)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if "id" in msg:
                    slot = self._pending.get(msg["id"])
                    if slot:
                        slot[1] = msg
                        slot[0].set()
                else:
                    self._events.put(msg)
        for slot in list(self._pending.values()):
            slot[1] = {"error": {"message": "pipe closed"}}
            slot[0].set()

    def _event_loop(self):
        while True:
            msg = self._events.get()
            if msg is None:
                return
            if msg.get("method") == "Fetch.requestPaused":
                try:
                    self._on_request(msg["params"], msg.get("sessionId"))
                except CDPError:
                    pass
            elif msg.get("method") == "Log.entryAdded":
                entry = msg.get("params", {}).get("entry", {})
                if entry.get("level") == "error":
                    self.page_errors.append("%s: %s" % (entry.get("source", "?"), str(entry.get("text", ""))[:120]))

    def _on_request(self, p, sid):
        url = p["request"]["url"]
        path = url[len(ORIGIN):].split("?", 1)[0] if url.startswith(ORIGIN + "/") else None
        hit = self.serve.get(path) if path is not None else None
        if hit is None:
            self.blocked.append(url[:200])
            self.send("Fetch.failRequest", {"requestId": p["requestId"], "errorReason": "BlockedByClient"}, sid)
            return
        body, mime = hit
        headers = [{"name": "Content-Type", "value": mime}, {"name": "Cache-Control", "value": "no-store"}]
        if mime.startswith("text/html"):
            headers.append({"name": "Content-Security-Policy", "value": CSP})
        self.send("Fetch.fulfillRequest", {"requestId": p["requestId"], "responseCode": 200,
                  "responseHeaders": headers, "body": base64.b64encode(body).decode("ascii")}, sid)

    def send(self, method, params=None, session=None, timeout=60):
        with self._id_lock:
            self._next_id += 1
            mid = self._next_id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        slot = [threading.Event(), None]
        self._pending[mid] = slot
        data = json.dumps(msg).encode("utf-8") + b"\0"
        with self._write_lock:
            view = memoryview(data)
            while view:
                n = os.write(self._wfd, view)
                view = view[n:]
        if not slot[0].wait(timeout):
            self._pending.pop(mid, None)
            raise CDPError("timeout: %s" % method)
        self._pending.pop(mid, None)
        reply = slot[1]
        if "error" in reply:
            raise CDPError("%s: %s" % (method, reply["error"].get("message", "error")))
        return reply.get("result", {})

    # ---- pages
    def new_page(self, width, height):
        tid = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        return Page(self, tid, sid, width, height)


class Page:
    def __init__(self, chrome, target_id, session, width, height):
        self.c = chrome
        self.target_id = target_id
        self.sid = session
        s = self.sid
        send = chrome.send
        send("Page.enable", {}, s)
        send("Runtime.enable", {}, s)
        send("Log.enable", {}, s)
        send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, s)
        send("Emulation.setDeviceMetricsOverride",
             {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, s)
        send("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}}, s)
        send("Page.addScriptToEvaluateOnNewDocument", {"source": FREEZE_JS}, s)

    def set_backdrop(self, color):
        """Draw the page over an opaque colour ("#RRGGBB") instead of a transparent one (the storyboard's stills)."""
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        self.c.send("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": r, "g": g, "b": b, "a": 1}}, self.sid)

    def evaluate(self, expression, await_promise=False, timeout=60):
        r = self.c.send("Runtime.evaluate", {"expression": expression, "awaitPromise": await_promise,
                                             "returnByValue": True}, self.sid, timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            text = (d.get("exception") or {}).get("description") or d.get("text", "script error")
            raise CDPError("page: %s" % text.splitlines()[0][:300])
        return r["result"].get("value")

    def open(self, path, setup_cfg):
        """Navigate to a served path (never file://), run the setup, fail on any blocked request."""
        before = len(self.c.blocked)
        self.c.send("Page.navigate", {"url": ORIGIN + path}, self.sid)
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)
        else:
            raise CDPError("page did not load: %s" % path)
        self.evaluate(SETUP_JS)
        self.evaluate("window.__setup(%s)" % json.dumps(setup_cfg), await_promise=True)
        time.sleep(0.15)   # let late subresource requests reach the Fetch handler
        csp = self.evaluate("window.__csp")
        if csp:
            raise RenderBlocked("blocked by the page policy: %s" % csp[:3])
        if self.c.page_errors:
            raise RenderBlocked("the browser refused a request: %s" % self.c.page_errors[:2])
        if len(self.c.blocked) > before:
            raise RenderBlocked("blocked requests: %s" % self.c.blocked[before:before + 3])

    def frame(self, t, data):
        """Call renderAt(t, data) and assert no animation runs; returns {html (a state signature), boxes (the data-zone boxes)}."""
        if self.c.page_errors:
            raise RenderBlocked("the browser refused a request: %s" % self.c.page_errors[:2])
        return self.evaluate("window.__frame(%r, %s)" % (float(t), json.dumps(data)))

    def screenshot(self, optimize_for_speed=False):
        params = {"format": "png", "fromSurface": True, "captureBeyondViewport": False}
        if optimize_for_speed:
            params["optimizeForSpeed"] = True
        r = self.c.send("Page.captureScreenshot", params, self.sid)
        return base64.b64decode(r["data"])
