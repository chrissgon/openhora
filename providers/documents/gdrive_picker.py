"""The one-shot loopback page that runs the Google Picker (a module of gdrive_auth.py, not a provider: its name has an underscore).

The Picker is a script and frames served from Google's hosts. The runtime's own page forbids that (`default-src 'self'`,
runtime/service.py) and loads nothing from another host (interface/README.md), so the Picker never runs there. It runs on
the page this module serves instead, for the minutes one authorization or one pick takes, and then the server is gone.

What the server is:
  - bound to 127.0.0.1 on a random port; every request must carry `Host: 127.0.0.1:<that port>`, or it is refused with
    403 (a page on the internet cannot reach it through a rebinding of its own name);
  - the OAuth callback (`GET /?code=...&state=...`) is served ONCE: a second request, or one with a state that does not
    match (constant-time compare), gets nothing and ends the session with nothing stored. The authorization asks for the
    scope drive.file alone, with PKCE (S256);
  - the page, the token and the picks are guarded by a random nonce the server made, which only the page that was
    redirected to carries (a different page in the browser cannot read /token or post /picked); a POST must also carry
    no Origin, or this server's own;
  - /picked is served once. After it (or after a cancel, a failed callback or the timeout) the server stops. Nothing is
    kept on disk by this module: the access token lives in memory, and is handed to the page only to open the Picker.

What it does not do: write to Drive, ask for another scope, set a Content-Security-Policy that restricts scripts (the
Picker needs hosts of Google's that cannot be checked offline; the page sets frame-ancestors 'none', no referrer and no
caching), log a request (a request line can carry the OAuth code).

Standard library only. Runs on Python 3.9 and later.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
HANDLER_TIMEOUT_SECONDS = 15        # a connection that sends nothing is dropped
TOKEN_SERVED_MAX = 5                # the page asks for the token once; a few more allow a reload
PICKS_MAX = 50                      # files one pick may name
NAME_MAX = 200
BODY_MAX = 64 * 1024
FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,100}")
MIME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_/-]{2,119}")
FOLDER_MIME = "application/vnd.google-apps.folder"
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def same(a, b) -> bool:
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def clean_picks(documents) -> list:
    """The picks the page posted, checked one by one: [{"id", "name", "mime_type"}], at most PICKS_MAX. A pick with an id of an
    unexpected shape, a folder, or a type that is not text of the right shape is dropped, not trusted. ValueError when `documents`
    is not a list."""
    if not isinstance(documents, list):
        raise ValueError("the picks are a list")
    out, seen = [], set()
    for d in documents[:PICKS_MAX]:
        if not isinstance(d, dict):
            continue
        ident, mime, name = d.get("id"), d.get("mimeType"), d.get("name")
        if not isinstance(ident, str) or not FILE_ID.fullmatch(ident) or ident in seen:
            continue
        if not isinstance(mime, str) or not MIME.fullmatch(mime) or mime == FOLDER_MIME:
            continue
        name = " ".join(CONTROL.sub(" ", name if isinstance(name, str) else "").split())[:NAME_MAX]
        seen.add(ident)
        out.append({"id": ident, "name": name, "mime_type": mime})
    return out


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>openhora: pick files from Google Drive</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}
button{font:inherit;padding:.5rem 1rem}pre{white-space:pre-wrap;word-break:break-word;background:#f3f3f3;padding:1rem}</style>
</head><body>
<h1>Pick files from Google Drive</h1>
<p>Choose one or more files (hold Shift or Ctrl to pick several). Folders open to show their files; a folder itself cannot be
picked. Each file you pick becomes a source of your project, and this app is given access to it, and nothing else.</p>
<p><button id="open" disabled>Open the Picker</button></p>
<pre id="out">Loading the Google Picker...</pre>
<script>
const N = __NONCE__;
const out = document.getElementById('out');
const btn = document.getElementById('open');
let cfg = null, sent = false;
function say(t) { out.textContent = t; }
async function init() {
  const r = await fetch('/token?n=' + encodeURIComponent(N), {cache: 'no-store'});
  if (!r.ok) { say('Could not get the session from the local server (status ' + r.status + ').'); return; }
  cfg = await r.json();
  gapi.load('picker', () => { btn.disabled = false; say('Ready.'); openPicker(); });
}
function openPicker() {
  const view = new google.picker.DocsView(google.picker.ViewId.DOCS)
    .setIncludeFolders(true).setSelectFolderEnabled(false);
  new google.picker.PickerBuilder()
    .addView(view).enableFeature(google.picker.Feature.MULTISELECT_ENABLED)
    .setOAuthToken(cfg.token).setDeveloperKey(cfg.apiKey).setAppId(cfg.appId)
    .setCallback(onPick).build().setVisible(true);
}
async function onPick(data) {
  const action = data[google.picker.Response.ACTION];
  if (sent || (action !== google.picker.Action.PICKED && action !== google.picker.Action.CANCEL)) return;
  sent = true;
  let body = {n: N, cancelled: true, documents: []};
  if (action === google.picker.Action.PICKED) {
    body = {n: N, cancelled: false, documents: data[google.picker.Response.DOCUMENTS].map(d => ({
      id: d[google.picker.Document.ID], name: d[google.picker.Document.NAME], mimeType: d[google.picker.Document.MIME_TYPE]}))};
  }
  say('Sending your choice to the terminal...');
  const r = await fetch('/picked', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  say(r.ok ? 'Done. You can close this tab; the terminal has your choice.' : 'The local server did not take it (status ' + r.status + ').');
}
btn.addEventListener('click', () => { if (!sent) openPicker(); });
window.onApiLoad = init;
</script>
<script async defer src="https://apis.google.com/js/api.js" onload="onApiLoad()"></script>
</body></html>
"""


class OneShotServer:
    """One session on 127.0.0.1. `access_token` is given when the token is already held (a later pick); otherwise `authorize_url`
    (a function of the redirect URI, the state and the challenge) and `exchange(code, redirect_uri)` (-> the token response, or
    raises) run the OAuth callback. `on_token(response)` is called with the response once, before the Picker opens (the caller
    stores the refresh token there). `scope` is the one scope the response must carry."""

    def __init__(self, *, api_key: str, project_number: str, scope: str, access_token=None, authorize_url=None, exchange=None,
                 on_token=None, state=None):
        if access_token is None and (authorize_url is None or exchange is None):
            raise ValueError("a session without a token needs authorize_url and exchange")
        self.api_key, self.project_number, self.scope = api_key, project_number, scope
        self.access_token, self._authorize_url, self._exchange, self._on_token = access_token, authorize_url, exchange, on_token
        self.state = state or secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.callback_used = self.picked_used = False
        self.token_served = 0
        self.done = threading.Event()
        self.error = None                  # why the session ended without picks, or None
        self.cancelled = False
        self.picks = []
        self.response = None               # the token response of the callback (for the caller to read after), never printed
        owner = self

        class Handler(BaseHTTPRequestHandler):
            timeout = HANDLER_TIMEOUT_SECONDS

            def log_message(self, *args):   # a request line can carry the OAuth code
                return

            def _send(self, status, body=b"", ctype="text/html; charset=utf-8", location=None):
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def _note(self, status, text):
                self._send(status, f"<!doctype html><title>openhora</title><p>{text}</p>".encode())

            def _host_ok(self):
                return self.headers.get("Host", "") == f"{HOST}:{owner.port}"

            def do_GET(self):   # noqa: N802
                if not self._host_ok():
                    return self._send(403)
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/start":
                    return owner._start(self)
                if parsed.path == "/":
                    return owner._callback(self, query) if query else self._send(404)
                if parsed.path == "/picker":
                    if not owner._nonce_ok(query.get("n", [""])[0]) or owner.access_token is None:
                        return self._send(403)
                    return self._send(200, PAGE.replace("__NONCE__", json.dumps(owner.nonce)).encode())
                if parsed.path == "/token":
                    return owner._token(self, query)
                return self._send(404)

            def do_POST(self):   # noqa: N802
                if not self._host_ok() or self.path != "/picked":
                    return self._send(403)
                origin = self.headers.get("Origin")
                if origin is not None and origin != f"http://{HOST}:{owner.port}":
                    return self._send(403)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > BODY_MAX:
                        return self._send(413)
                    data = json.loads(self.rfile.read(length))
                except (ValueError, OSError):
                    return self._send(400)
                owner._picked(self, data)

        self.server = ThreadingHTTPServer((HOST, 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.redirect_uri = f"http://{HOST}:{self.port}"
        self.start_url = f"{self.redirect_uri}/start"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)

    # --- the session ---------------------------------------------------------------------------------------------------

    def serve(self) -> None:
        self._thread.start()

    def _nonce_ok(self, given) -> bool:
        return same(given, self.nonce)

    def _fail(self, why: str) -> None:
        self.error = why
        self.done.set()

    def _start(self, handler) -> None:
        if self.access_token is not None:
            return handler._send(302, location="/picker?n=" + urllib.parse.quote(self.nonce))
        return handler._send(302, location=self._authorize_url(self.redirect_uri, self.state))

    def _callback(self, handler, query) -> None:
        with self.lock:
            if self.callback_used or self.access_token is not None:
                return handler._send(404)
            self.callback_used = True
        if not same(query.get("state", [""])[0], self.state):
            handler._note(401, "State mismatch. Nothing was stored. You can close this tab.")
            return self._fail("the state parameter does not match; possible CSRF, nothing stored")
        if "error" in query:
            handler._note(400, "Authorization was not granted. You can close this tab.")
            return self._fail("Google returned an error instead of an authorization; nothing stored")
        if not query.get("code"):
            handler._note(400, "No authorization code received. You can close this tab.")
            return self._fail("the callback carried no code")
        try:
            response = self._exchange(query["code"][0], self.redirect_uri)
            scopes = set(str(response.get("scope") or "").split())
            if scopes != {self.scope}:
                raise ValueError(f"the consent granted {' '.join(sorted(scopes)) or 'no scope'} where only {self.scope} is wanted"
                                 "; was the Drive box left unticked? nothing stored")
            if self._on_token is not None:
                self._on_token(response)
        except Exception as exc:   # a failed exchange or store ends the session; the reason is the caller's to print
            handler._note(400, "The sign-in did not give what is needed. See the terminal. You can close this tab.")
            return self._fail(str(exc) or type(exc).__name__)
        self.access_token, self.response = response["access_token"], response
        handler._send(302, location="/picker?n=" + urllib.parse.quote(self.nonce))

    def _token(self, handler, query) -> None:
        with self.lock:
            ok = self._nonce_ok(query.get("n", [""])[0]) and self.access_token is not None and self.token_served < TOKEN_SERVED_MAX \
                and not self.picked_used
            if ok:
                self.token_served += 1
        if not ok:
            return handler._send(403)
        payload = {"token": self.access_token, "apiKey": self.api_key, "appId": self.project_number}
        handler._send(200, json.dumps(payload).encode(), "application/json")

    def _picked(self, handler, data) -> None:
        if not isinstance(data, dict) or not self._nonce_ok(data.get("n", "")) or self.access_token is None:
            return handler._send(403)
        with self.lock:
            if self.picked_used:
                return handler._send(409)
            self.picked_used = True
        if data.get("cancelled"):
            self.cancelled = True
        else:
            try:
                self.picks = clean_picks(data.get("documents"))
            except ValueError:
                handler._send(400)
                return self._fail("the page sent picks that are not a list")
        handler._send(200, json.dumps({"ok": True, "picked": len(self.picks)}).encode(), "application/json")
        self.done.set()

    def wait(self, timeout: float) -> bool:
        """True when the session ended (picks, cancel or a failure) before `timeout` seconds."""
        return self.done.wait(timeout)

    def close(self) -> None:
        self.access_token = None   # the token was in memory only
        self.server.shutdown()
        self.server.server_close()
