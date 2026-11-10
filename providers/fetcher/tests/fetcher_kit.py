"""A fake docker, a reference store and a planted platform fetch file for the fetcher's host-side tests. Fictional names only
("Aster Lane", `.example` hosts); nothing here reaches a network or starts a container."""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from pathlib import Path

FETCHER = Path(__file__).resolve().parents[1]
PROVIDERS = FETCHER.parent
for folder in (str(FETCHER), str(PROVIDERS)):
    if folder not in sys.path:
        sys.path.insert(0, folder)

import _fetcher_image  # noqa: E402
import ytdlp  # noqa: E402

REFERENCE = "0123456789abcdef"
LINK = "https://www.aster.example/v/4242"
FETCH_FILE = {"platform": "asterlane", "link": {"hosts": ["www.aster.example"], "path_pattern": "/v/[0-9]{1,12}", "keep_query": ["t"]},
              "fetch_hosts": ["media.aster.example"], "fetch_suffixes": [".cdn.aster.example"], "extractors": ["AsterVideo"],
              "subtitles": {"by_language": "{lang}.*", "original": "aster-orig"}, "checked": "planted by a test"}
PIN = {"tool": "yt-dlp", "version": "2099.01.01", "asset": "yt-dlp", "url": "https://download.example/yt-dlp", "size": 123, "sha256": "ab" * 32,
       "published_at": "2099-01-01T00:00:00Z", "redirect_hosts": ["objects.example"], "read_on": "2099-01-02", "source": "a test", "js_runtime": None}
WHEEL_PIN = {"note": "planted by a test", "source": "a test", "read_on": "2099-01-02", "download_hosts": ["files.example"], "redirect_hosts": [],
             "wheels": [{"name": "asterlane_kit", "version": "1.2.3", "arch": arch, "size": 1234, "sha256": "cd" * 32,
                         "filename": "asterlane_kit-1.2.3-%s.whl" % tag, "url": "https://files.example/packages/ab/cd/asterlane_kit-1.2.3-%s.whl" % tag}
                        for arch, tag in (("amd64", "cp310-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64"),
                                          ("arm64", "cp310-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64"))]
             + [{"name": "plain_kit", "version": "4.5", "arch": "any", "size": 99, "sha256": "ef" * 32, "filename": "plain_kit-4.5-py3-none-any.whl",
                 "url": "https://files.example/packages/ef/01/plain_kit-4.5-py3-none-any.whl"}]}
INFO = {"id": "4242", "extractor_key": "AsterVideo", "duration": 42.5, "width": 720, "height": 1280, "fps": 30, "upload_date": "20990101",
        "title": "Aster Lane opens the shop", "description": "Bram Hollow says hello", "view_count": 10, "like_count": 2, "comment_count": 1,
        "subtitles": "auto"}

FAKE = r'''#!{python}
import json, os, subprocess, sys, time
CONFIG = os.environ["DOCKER_CONFIG"]
CFG = json.load(open(os.path.join(CONFIG, "fake.json")))
ARGV = sys.argv[1:]
with open(os.path.join(CONFIG, "calls.jsonl"), "a") as log:
    log.write(json.dumps({{"argv": ARGV, "env": sorted(os.environ)}}) + "\n")
WITH_VALUE = {{"--name", "--label", "--network", "--cap-drop", "--security-opt", "--pids-limit", "--memory", "--memory-swap", "--cpus", "--tmpfs",
              "--user", "-v", "--pull", "-e", "--env-file", "--mount", "--platform", "--shm-size"}}
def out(text=""):
    sys.stdout.write(text); sys.stdout.flush()
cmd = ARGV[0] if ARGV else ""
if cmd == "version":
    if CFG.get("down"):
        sys.exit(1)
    out("27.0.0\n")
elif cmd == "context":
    out(CFG.get("context", "unix:///var/run/docker.sock") + "\n")
elif cmd == "image" and ARGV[1] == "inspect":
    for tag, img in CFG.get("images", {{}}).items():
        if ARGV[2] in (tag, img["Id"]):
            out(json.dumps([{{"Id": img["Id"], "Config": {{"Labels": img["Labels"]}}}}])); sys.exit(0)
    sys.exit(1)
elif cmd == "build":
    sys.exit(CFG.get("build_rc", 0))
elif cmd == "network":
    sys.exit(CFG.get("network_rc", {{}}).get(ARGV[1], 0))
elif cmd in ("rm", "ps"):
    sys.exit(0)
elif cmd == "run":
    i, mounts = 1, {{}}
    while i < len(ARGV):
        a = ARGV[i]
        if a in WITH_VALUE:
            if a == "-v":
                src, dst, mode = ARGV[i + 1].rsplit(":", 2); mounts[dst] = src
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            break
    inner = ARGV[i + 1:]
    verb = inner[2] if inner[:1] == ["--result"] else inner[0]
    def write_files(dest, files):
        for name, spec in files.items():
            path = os.path.join(dest, name)
            kind = spec.get("kind", "text")
            if kind == "text":
                open(path, "w").write(spec["text"])
            elif kind == "big":
                with open(path, "wb") as fh:
                    fh.truncate(spec["size"])
            elif kind == "link":
                os.symlink(spec["target"], path)
            elif kind == "fifo":
                os.mkfifo(path)
    if verb == "proxy":
        dest = mounts["/out"]
        open(os.path.join(dest, "ready"), "w").write("1")
        end = time.time() + 30
        while time.time() < end and not os.path.exists(os.path.join(dest, "stop")):
            time.sleep(0.02)
        json.dump(CFG.get("proxy_report", {{"allowed": 1, "refused": 0, "refused_hosts": [], "sni_refused": 0, "bytes": 1000}}), open(os.path.join(dest, "proxy.json"), "w"))
        write_files(dest, CFG.get("proxy_files", {{}}))
        sys.exit(0)
    if verb == "fetch":
        if CFG.get("fetch_sleep"):
            time.sleep(CFG["fetch_sleep"])
        dest = mounts["/out"]
        write_files(dest, CFG.get("fetch_files", {{}}))
        if "fetch_result" in CFG:
            if CFG["fetch_result"] is not None:
                json.dump(CFG["fetch_result"], open(os.path.join(dest, "result.json"), "w"))
        else:
            json.dump({{"ok": True, "code": None, "exit": 0, "seconds": CFG.get("fetch_seconds")}}, open(os.path.join(dest, "result.json"), "w"))
        sys.exit(CFG.get("fetch_rc", 0))
    if verb == "measure":
        dest = mounts["/out"]
        if CFG.get("measure_execute"):
            mapped = [a.replace("/in", mounts["/in"]).replace("/out", dest) if a.startswith("/") else a for a in inner]
            mapped += ["--in", mounts["/in"], "--out", dest]
            done = subprocess.run([sys.executable, "-I", CFG["inner"]] + mapped, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sys.exit(done.returncode)
        write_files(dest, CFG.get("measure_files", {{}}))
        if "measure_result" in CFG:
            json.dump(CFG["measure_result"], open(os.path.join(dest, "result.json"), "w"))
        else:
            json.dump({{"ok": True, "code": None, "exit": 0, "seconds": None}}, open(os.path.join(dest, "result.json"), "w"))
        sys.exit(0)
    sys.exit(1)
else:
    sys.exit(1)
'''


class World:
    """One test's machine: a fake docker on PATH, a state folder, a copy of the provider's folder with a filled pin, a reference store."""

    def __init__(self, tmp: Path, monkeypatch, pin=True, image=True, **cfg):
        self.tmp = tmp
        self.bin, self.config, self.state = tmp / "bin", tmp / "dockerconfig", tmp / "state"
        for folder in (self.bin, self.config):
            folder.mkdir()
        self.state.mkdir(mode=0o700)
        fake = self.bin / "docker"
        fake.write_text(FAKE.format(python=sys.executable))
        fake.chmod(0o755)
        self.folder = tmp / "fetcher"
        shutil.copytree(FETCHER, self.folder, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        if pin:
            (self.folder / "tool-pin.json").write_text(json.dumps(PIN))
            (self.folder / "wheel-pin.json").write_text(json.dumps(WHEEL_PIN))
        else:   # the committed pin is filled since the pin commit: a test of a null pin writes the null form itself
            null = {k: None for k in ("version", "url", "size", "sha256", "published_at", "read_on", "js_runtime")}
            (self.folder / "tool-pin.json").write_text(json.dumps({"tool": "yt-dlp", "asset": "yt-dlp", "redirect_hosts": [], **null}))
        self.cfg = {"images": {}, "inner": str(FETCHER / "_fetcher_inner.py")}
        self.cfg.update(cfg)
        self.refs = tmp / "refs"
        self.refs.mkdir(mode=0o700)
        marker = self.refs / ".openhora-reference"
        marker.write_text("reference store\n")
        marker.chmod(0o400)
        self.ref = self.refs / REFERENCE
        self.ref.mkdir(mode=0o700)
        self.platform_file = tmp / "asterlane.fetch.json"
        self.platform_file.write_text(json.dumps(FETCH_FILE))
        monkeypatch.setattr(ytdlp, "FOLDER", str(self.folder))
        monkeypatch.setenv("PATH", "%s:%s" % (self.bin, os.environ["PATH"]))
        monkeypatch.setenv("DOCKER_CONFIG", str(self.config))
        monkeypatch.setenv("OPENHORA_STATE_DIR", str(self.state))
        monkeypatch.delenv("DOCKER_HOST", raising=False)
        if image and pin:
            self.install_image()
        self.save()

    def install_image(self, definition=None):
        tag, h = _fetcher_image.image_tag(str(self.folder)), _fetcher_image.definition_hash(str(self.folder))
        self.cfg["images"][tag] = {"Id": "sha256:" + "cd" * 32, "Labels": {"org.openhora.definition": definition or h, "org.openhora.tool.version": PIN["version"]}}
        own = self.state / "fetcher"
        own.mkdir(mode=0o700, exist_ok=True)
        (own / "image.json").write_text(json.dumps({"image_tag": tag, "image_id": "sha256:" + "cd" * 32}))

    def save(self):
        (self.config / "fake.json").write_text(json.dumps(self.cfg))

    def calls(self):
        path = self.config / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def runs(self):
        return [c["argv"] for c in self.calls() if c["argv"][:1] == ["run"]]

    def networks(self):
        return [c["argv"] for c in self.calls() if c["argv"][:1] == ["network"]]

    def fetch(self, *extra, url=LINK, stage="meta", language="en", out=None):
        argv = ["fetch", "--url", url, "--platform", "asterlane", "--platform-file", str(self.platform_file), "--stage", stage,
                "--out", str(out or self.ref), "--language", language] + [str(x) for x in extra]
        return run_main(argv)


class Server:
    """A loopback http server answering `routes` {path: (status, headers, body)}; `PORT` in a header value is replaced by its port."""

    def __init__(self, routes):
        import http.server
        import threading
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status, headers, body = routes[self.path]
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v.replace("PORT", str(outer.port)))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


def run_main(argv):
    """(exit code, stdout JSON or None, stderr) of ytdlp.main(argv)."""
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ytdlp.main(argv)
    try:
        value = json.loads(out.getvalue()) if out.getvalue().strip() else None
    except ValueError:
        value = None
    return code, value, err.getvalue()


def text(value):
    return {"kind": "text", "text": value if isinstance(value, str) else json.dumps(value)}


def private_folder(path: Path) -> Path:
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path
