"""A stand-in for the Google Drive API and the Google token endpoint on 127.0.0.1, for the offline tests of
providers/documents/gdrive.py and gdrive_auth.py. Not a test file, and never a copy of the live service: it serves exactly the
calls the provider's docstring names, keeps a few fictional files in memory, and refuses what the reference says the service
refuses (a missing or wrong bearer token, a file the app was not given, an export format a Google type does not offer, an
export over 10 MB). No real account, key or file is ever involved: the credentials of a test are made-up strings.

What it records, for the assertions: `requests` (method, path, query, whether a bearer token came), `token_forms` (every form
posted to the token endpoint) and `methods` (every HTTP method the API saw: the provider must send GET only).

Usage (from a test):
  fake = fake_drive.FakeDrive()          # starts on a free loopback port in a daemon thread
  fake.base, fake.token_url              what the provider's environment names
  fake.record_json()                     a GDRIVE_SOURCES_TOKEN value that this fake accepts
  fake.add("doc1...", "Weekly notes", fake_drive.DOC, exports={"text/markdown": b"# Notes\\n"})
  fake.edit(id, content=...)             a person's edit: the version moves
  fake.close()
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOGLE = "application/vnd.google-apps."
DOC, SHEET, SLIDES, FOLDER = GOOGLE + "document", GOOGLE + "spreadsheet", GOOGLE + "presentation", GOOGLE + "folder"
DRAWING = GOOGLE + "drawing"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_LIMIT = 10 * 1024 * 1024
SCOPE = "https://www.googleapis.com/auth/drive.file"
CLIENT_ID = "123456789012-fakeclientid.apps.example"
CLIENT_SECRET = "fake-client-secret-not-real"
REFRESH_TOKEN = "fake-refresh-token-not-real"
API_KEY = "fake-picker-api-key-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
CODE = "fake-authorization-code"


class FakeDrive:
    def __init__(self):
        self.files = {}
        self.requests, self.token_forms, self.methods = [], [], []
        self.scope_granted = SCOPE          # what the token endpoint says it granted
        self.token_status = 200             # set 400 and token_error to answer an OAuth error
        self.token_error = {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
        self.code = CODE
        self.redirect_next = False
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _json(self, status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _bytes(self, body):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status, reason, message):
                self._json(status, {"error": {"code": status, "message": message, "errors": [{"reason": reason, "message": message}]}})

            def do_POST(self):   # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/token":
                    with owner.lock:
                        owner.methods.append("POST")
                    return self._error(405, "methodNotAllowed", "no write is served")
                length = int(self.headers.get("Content-Length", "0"))
                form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
                with owner.lock:
                    owner.token_forms.append(form)
                if owner.token_status != 200:
                    return self._json(owner.token_status, owner.token_error)
                if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
                    return self._json(401, {"error": "invalid_client", "error_description": "Unauthorized"})
                if form.get("grant_type") == "refresh_token":
                    if form.get("refresh_token") != REFRESH_TOKEN:
                        return self._json(400, {"error": "invalid_grant", "error_description": "Bad Request"})
                    return self._json(200, {"access_token": ACCESS_TOKEN, "expires_in": 3599, "scope": owner.scope_granted,
                                            "token_type": "Bearer"})
                if form.get("grant_type") == "authorization_code":
                    if form.get("code") != owner.code or not form.get("code_verifier"):
                        return self._json(400, {"error": "invalid_grant", "error_description": "Malformed auth code."})
                    return self._json(200, {"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN, "expires_in": 3599,
                                            "scope": owner.scope_granted, "token_type": "Bearer"})
                return self._json(400, {"error": "unsupported_grant_type"})

            def _other(self):
                with owner.lock:
                    owner.methods.append(self.command)
                self._error(405, "methodNotAllowed", "no write is served")

            do_PUT = do_PATCH = do_DELETE = _other   # noqa: N815

            def do_GET(self):   # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                auth = self.headers.get("Authorization", "")
                with owner.lock:
                    owner.methods.append("GET")
                    owner.requests.append(("GET", parsed.path, query, bool(auth)))
                    if owner.redirect_next:
                        owner.redirect_next = False
                        self.send_response(302)
                        self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                if auth != f"Bearer {ACCESS_TOKEN}":
                    return self._error(401, "authError", "Invalid Credentials")
                path = parsed.path
                if not path.startswith("/drive/v3/files/"):
                    return self._error(404, "notFound", "not served")
                rest = path[len("/drive/v3/files/"):]
                exporting = rest.endswith("/export")
                ident = rest[:-len("/export")] if exporting else rest
                f = owner.files.get(ident)
                if f is None:
                    return self._error(404, "notFound", f"File not found: {ident}.")
                if exporting:
                    return self._export(f, query)
                if query.get("alt") == "media":
                    if f["mimeType"].startswith(GOOGLE):
                        return self._error(403, "fileNotDownloadable", "Only files with binary content can be downloaded.")
                    return self._bytes(f["content"])
                meta = {"id": ident, "name": f["name"], "mimeType": f["mimeType"], "version": str(f["version"]),
                        "modifiedTime": f["modifiedTime"], "trashed": f["trashed"]}
                if f["content"] is not None:
                    meta["size"] = str(len(f["content"]))
                    meta["md5Checksum"] = f.get("md5") or hashlib.md5(f["content"]).hexdigest()
                self._json(200, meta)

            def _export(self, f, query):
                if not f["mimeType"].startswith(GOOGLE) or f["mimeType"] == FOLDER:
                    return self._error(403, "fileNotExportable", "Export only supports Docs Editors files.")
                wanted = query.get("mimeType")
                if wanted not in f["exports"]:
                    return self._error(400, "badRequest", "Export format is not supported for this file type.")
                body = f["exports"][wanted]
                if len(body) > EXPORT_LIMIT:
                    return self._error(403, "exportSizeLimitExceeded", "This file is too large to be exported.")
                self._bytes(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.token_url = f"{self.base}/token"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def add(self, ident, name, mime, content=None, exports=None, trashed=False):
        """A file the app was given. A Google file carries `exports` ({mime: bytes}); any other carries `content` (bytes)."""
        self.files[ident] = {"name": name, "mimeType": mime, "content": content, "exports": dict(exports or {}), "version": 1,
                             "modifiedTime": "2026-10-15T09:00:00.000Z", "trashed": trashed}
        return ident

    def edit(self, ident, content=None, exports=None):
        """A person's edit: new bytes, the version and the modified time move."""
        f = self.files[ident]
        if content is not None:
            f["content"] = content
        if exports is not None:
            f["exports"] = dict(exports)
        f["version"] += 1
        f["modifiedTime"] = f"2026-10-15T09:{f['version']:02d}:00.000Z"

    def touch(self, ident):
        """A change that moves the version and not the bytes (a share, a star)."""
        f = self.files[ident]
        f["version"] += 1
        f["modifiedTime"] = f"2026-10-15T09:{f['version']:02d}:00.000Z"

    def record(self, **over):
        record = {"refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "api_key": API_KEY,
                  "project_number": CLIENT_ID.split("-")[0], "scope": SCOPE, "obtained_at": "2026-10-15T08:00:00Z"}
        record.update(over)
        return record

    def record_json(self, **over):
        return json.dumps(self.record(**over))

    def env(self, **over):
        """What the provider's process needs to talk to this fake and find its authorization in the environment."""
        return {"INTEGRATION_DOCUMENTS_GDRIVE_API_BASE": self.base, "INTEGRATION_DOCUMENTS_GDRIVE_TOKEN_URL": self.token_url,
                "GDRIVE_SOURCES_TOKEN": self.record_json(**over)}

    def api_requests(self):
        return [r for r in self.requests if r[1].startswith("/drive/")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
