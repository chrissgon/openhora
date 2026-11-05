"""A stand-in for Google Drive on 127.0.0.1, for the tests of the Drive writer (package W4a, providers/writer/gdrive.py): the token endpoint, the file and
list reads, the multipart create and update, and the revision update. Not a test file, and never a copy of the live service: it serves exactly the
requests the writer's docstring names and answers 405 to anything else, recording it in `violations`, so a writer that sent a DELETE, a PUT, a
metadata PATCH or any other request would be seen twice (here and in the allow-list test).

It records every API request (method, path as sent, query, body, content type, whether it carried the bearer token) in `requests`, in order, and every
form posted to the token endpoint in `token_forms`, so that a test asserts the exact list. State: `files` (id -> resource, with `content` and a list of
`revisions`), a folder `Folder_ID_01` that exists, and a clock that moves a second at every change.

Knobs a test sets to make it misbehave: `lose_answer` (a method name: the write is made and then the connection is closed with no answer), `fail_write`
(a status: the next write is refused with it and changes nothing), `edit_during` (a function called just before the next write is made, to move the
file between the writer's read and its write), `scope` (what the token answers say they granted), `redirect_token`.

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import hashlib
import json
import re
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCOUNT = "pat@example.com"
CLIENT_ID = "stand-in-client-id.example"
CLIENT_SECRET = "fake-client-secret-not-real-4f2a"
REFRESH_TOKEN = "fake-refresh-token-not-real-9b1c"
ACCESS_TOKEN = "fake-access-token-not-real-7d3e"
SECRETS = (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN)
SCOPES = ("https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.calendarlist.readonly", "https://www.googleapis.com/auth/drive")
FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"
FOLDER_ID = "Folder_ID_01"
FILE_ID = "File_ID_0001"
NATIVE_ID = "Native_ID_001"


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def split_multipart(body: bytes, content_type: str) -> list:
    """[(headers dict, bytes)] of a multipart/related body."""
    boundary = re.search(r"boundary=([^;\s]+)", content_type).group(1).encode("ascii")
    parts = []
    for chunk in body.split(b"--" + boundary):
        if chunk in (b"", b"--\r\n", b"--") or chunk.startswith(b"--"):
            continue
        head, _, rest = chunk.partition(b"\r\n\r\n")
        headers = {}
        for line in head.decode("ascii").split("\r\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        parts.append((headers, rest[:-2] if rest.endswith(b"\r\n") else rest))
    return parts


class FakeDriveWrite:
    def __init__(self):
        self.requests, self.token_forms, self.violations = [], [], []
        self.files = {}
        self.clock = 0
        self.lose_answer = None
        self.fail_write = None
        self.edit_during = None
        self.scope = " ".join(SCOPES)
        self.redirect_token = False
        self.keep_cap = False
        self.counter = 0
        self.lock = threading.Lock()
        self.add_folder(FOLDER_ID, "openhora")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, body, headers=None):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _drop(self):
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            def _body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _entry(self, body):
                parsed = urllib.parse.urlparse(self.path)
                entry = {"method": self.command, "path": parsed.path, "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()},
                         "body": body, "content_type": self.headers.get("Content-Type"),
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"}
                if parsed.path != "/token":
                    with owner.lock:
                        owner.requests.append(entry)
                return entry

            def do_POST(self):  # noqa: N802
                body = self._body()
                entry = self._entry(body)
                if entry["path"] == "/token":
                    if owner.redirect_token:
                        self.send_response(302)
                        self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    return self._send(*owner.token(urllib.parse.parse_qs(body.decode())))
                if not entry["bearer"]:
                    return self._send(401, {"error": {"message": "no bearer token"}})
                if entry["path"] == "/upload/drive/v3/files":
                    return owner.write(self, entry, "POST", lambda: owner.create(entry))
                owner.violate(self, entry)

            def do_PATCH(self):  # noqa: N802
                body = self._body()
                entry = self._entry(body)
                if not entry["bearer"]:
                    return self._send(401, {"error": {"message": "no bearer token"}})
                found = re.fullmatch(r"/upload/drive/v3/files/([^/]+)", entry["path"])
                if found:
                    return owner.write(self, entry, "PATCH", lambda: owner.update(found.group(1), entry))
                found = re.fullmatch(r"/drive/v3/files/([^/]+)", entry["path"])
                if found:      # R2-A: the one metadata PATCH of the writer, the move of a file to the trash
                    return owner.write(self, entry, "TRASH", lambda: owner.trash(found.group(1), entry))
                found = re.fullmatch(r"/drive/v3/files/([^/]+)/revisions/([^/]+)", entry["path"])
                if found:
                    return owner.write(self, entry, "REVISION", lambda: owner.keep(found.group(1), found.group(2), entry))
                owner.violate(self, entry)

            def do_GET(self):  # noqa: N802
                entry = self._entry(b"")
                if not entry["bearer"]:
                    return self._send(401, {"error": {"message": "no bearer token"}})
                found = re.fullmatch(r"/drive/v3/files/([^/]+)", entry["path"])
                if found:
                    meta = owner.files.get(found.group(1))
                    return self._send(*((200, owner.resource(meta)) if meta else (404, {"error": {"message": "File not found"}})))
                if entry["path"] == "/drive/v3/files":
                    return self._send(200, {"files": owner.find(entry["query"].get("q", ""))})
                owner.violate(self, entry)

            def do_PUT(self):  # noqa: N802
                owner.violate(self, self._entry(self._body()))

            def do_DELETE(self):  # noqa: N802
                owner.violate(self, self._entry(self._body()))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.token_url = f"{self.base}/token"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # --- the service -----------------------------------------------------------------------------------------------------------

    def token(self, form):
        first = lambda key: (form.get(key) or [""])[0]   # noqa: E731
        with self.lock:
            self.token_forms.append({k: v[0] for k, v in form.items()})
        if first("client_id") != CLIENT_ID or first("client_secret") != CLIENT_SECRET:
            return 401, {"error": "invalid_client", "error_description": "stand-in: unknown client"}
        if first("grant_type") != "refresh_token" or first("refresh_token") != REFRESH_TOKEN:
            return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
        return 200, {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer", "scope": self.scope}

    def violate(self, handler, entry):
        with self.lock:
            self.violations.append((entry["method"], entry["path"]))
        handler._send(405, {"error": {"message": "this stand-in serves only the requests of the Drive writer"}})

    def tick(self) -> str:
        self.clock += 1
        return f"2026-10-18T10:00:{self.clock:02d}.000Z"

    def new_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_{self.counter:04d}_stand_in"

    def add_folder(self, ident, name, parents=()):
        self.files[ident] = {"id": ident, "name": name, "mimeType": FOLDER, "parents": list(parents), "version": "1", "modifiedTime": "2026-10-01T08:00:00.000Z",
                             "trashed": False, "appProperties": {}, "content": b"", "revisions": []}

    def add_file(self, ident, name, data: bytes, mime="text/markdown", parents=(FOLDER_ID,), native=False, trashed=False, owned=True, can_edit=True):
        revision = self.new_id("rev")
        self.files[ident] = {"id": ident, "name": name, "mimeType": DOC if native else mime, "parents": list(parents), "version": "3",
                             "modifiedTime": "2026-10-10T09:00:00.000Z", "trashed": trashed, "appProperties": {}, "content": data,
                             "revisions": [] if native else [{"id": revision, "keepForever": False}], "owned": owned, "can_edit": can_edit}
        return self.files[ident]

    def resource(self, meta):
        out = {k: meta[k] for k in ("id", "name", "mimeType", "parents", "version", "modifiedTime", "trashed", "appProperties")}
        out["ownedByMe"] = meta.get("owned", True)
        out["capabilities"] = {"canEdit": meta.get("can_edit", True)}
        if meta["mimeType"] != FOLDER and not meta["mimeType"].startswith("application/vnd.google-apps."):
            out["md5Checksum"] = md5(meta["content"])
            out["size"] = str(len(meta["content"]))
            out["headRevisionId"] = meta["revisions"][-1]["id"]
        return out

    def find(self, q: str) -> list:
        found = re.fullmatch(r"'([^']*)' in parents and name = '((?:[^'\\]|\\.)*)' and trashed = false", q)
        if not found:
            return []
        folder, name = found.group(1), found.group(2).replace("\\'", "'").replace("\\\\", "\\")
        return [{"id": m["id"], "name": m["name"], "appProperties": m["appProperties"]} for m in self.files.values()
                if folder in m["parents"] and m["name"] == name and not m["trashed"]]

    def write(self, handler, entry, kind, make):
        """A write: refused by `fail_write`, preceded by `edit_during`, answered or not (`lose_answer`)."""
        with self.lock:
            failing, self.fail_write = self.fail_write, None
            edit, self.edit_during = self.edit_during, None
        if failing:
            return handler._send(failing, {"error": {"message": "stand-in refusal"}}, {"Retry-After": "7"} if failing in (429, 503) else None)
        if edit:
            edit()
        with self.lock:
            status, answer = make()
        if self.lose_answer == kind:
            return handler._drop()
        handler._send(status, answer)

    def create(self, entry):
        parts = split_multipart(entry["body"], entry["content_type"])
        meta, media = json.loads(parts[0][1]), parts[1]
        ident = self.new_id("File")
        native = meta.get("mimeType") == DOC
        self.files[ident] = {"id": ident, "name": meta["name"], "mimeType": meta["mimeType"], "parents": meta.get("parents", []), "version": "1",
                             "modifiedTime": self.tick(), "trashed": False, "appProperties": meta.get("appProperties", {}), "content": media[1],
                             "revisions": [] if native else [{"id": self.new_id("rev"), "keepForever": False}], "media_type": media[0].get("content-type")}
        return 200, self.resource(self.files[ident])

    def update(self, ident, entry):
        meta = self.files.get(ident)
        if meta is None:
            return 404, {"error": {"message": "File not found"}}
        parts = split_multipart(entry["body"], entry["content_type"])
        patch, media = json.loads(parts[0][1]), parts[1]
        meta["content"], meta["media_type"] = media[1], media[0].get("content-type")
        meta["version"] = str(int(meta["version"]) + 1)
        meta["modifiedTime"] = self.tick()
        meta["appProperties"] = {**meta["appProperties"], **patch.get("appProperties", {})}
        if meta["revisions"]:
            meta["revisions"].append({"id": self.new_id("rev"), "keepForever": False})
        return 200, self.resource(meta)

    def trash(self, ident, entry):
        meta = self.files.get(ident)
        if meta is None:
            return 404, {"error": {"message": "File not found"}}
        if json.loads(entry["body"]) != {"trashed": True}:
            return 400, {"error": {"message": "stand-in: the only metadata change served is trashed=true"}}
        meta["trashed"] = True
        meta["version"] = str(int(meta["version"]) + 1)
        meta["modifiedTime"] = self.tick()
        return 200, self.resource(meta)

    def keep(self, ident, revision, entry):
        meta = self.files.get(ident)
        found = [r for r in (meta or {}).get("revisions", []) if r["id"] == revision]
        if not found:
            return 404, {"error": {"message": "Revision not found"}}
        if self.keep_cap:
            return 403, {"error": {"message": "The maximum number of revisions that can be kept forever was reached.", "errors": [{"reason": "revisionLimitExceeded"}]}}
        found[0]["keepForever"] = json.loads(entry["body"]).get("keepForever") is True
        return 200, {"id": revision, "keepForever": found[0]["keepForever"]}

    # --- what a test hands to a script ---------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "scope": " ".join(SCOPES),
                  "account": ACCOUNT, "obtained_at": "2026-10-18T09:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self, **over) -> dict:
        return {"WRITER_GDRIVE_API_BASE": self.base, "WRITER_GDRIVE_TOKEN_URL": self.token_url, "GOOGLE_ACCOUNT_TOKEN": self.record_json(), **over}

    def listing(self) -> list:
        """The (method, path, query, bearer) of every API request, in order: what a test asserts as the exact list."""
        return [(r["method"], r["path"], r["query"]) for r in self.requests]
