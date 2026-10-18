"""A stand-in for Microsoft Graph's OneDrive on 127.0.0.1, for the tests of the OneDrive writer (package W4a, providers/writer/onedrive.py): the token
endpoint, the item reads (by id, by name in a folder, by path), the create (`PUT .../content` with conflictBehavior=fail), the upload session with its
`If-Match` precondition and the pre-authenticated upload address. Not a test file, and never a copy of the live service: it serves exactly the requests the
writer's docstring names and answers 405 to anything else, recording it in `violations`. The upload address is served at /upload/<token> and refuses a
request that carries an Authorization header (the address carries the permission; a credential sent there would be seen).

It records every Graph request (method, path as sent and decoded, query, body, headers that matter, whether it carried the bearer token) in `requests`, in
order, every upload in `uploads`, and every form posted to the token endpoint in `token_forms`. State: `items` (id -> item, with `content`), a drive
`b!FakeDrive_1` whose root folder is `ROOT_ID`, a folder `FOLDER_ID` named openhora under `/Documents`, and a clock that moves a second at every change.

Knobs: `lose_answer` ("PUT" or "UPLOAD": the write is made and then the connection is closed with no answer), `fail_write` (a status for the next write),
`edit_during` (a function called just before the next write), `scope`, `upload_host` (the host the upload address names), `no_upload_url`.

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import datetime
import json
import re
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADDRESS = "casey.rivera@mail.example"
CLIENT_ID = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
REFRESH_TOKEN = "fake-refresh-token-0-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
SECRETS = (REFRESH_TOKEN, ACCESS_TOKEN)
PLATFORM = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
PREFIX = "https://graph.microsoft.com/"
DRIVE = "b!FakeDrive_1"
ROOT_ID = "01ROOT00000!100"
FOLDER_ID = "01FOLDER0000!101"
FILE_ID = "01FILE000001!102"
PACKAGE_ID = "01PACKAGE001!103"


class FakeOneDriveWrite:
    def __init__(self):
        self.requests, self.token_forms, self.violations, self.uploads = [], [], [], []
        self.items = {}
        self.sessions = {}
        self.clock = 0
        self.counter = 0
        self.lose_answer = None
        self.fail_write = None
        self.edit_during = None
        self.scope = " ".join(PREFIX + n for n in PLATFORM) + " offline_access openid profile"
        self.upload_host = "127.0.0.1"
        self.no_upload_url = False
        self.lock = threading.Lock()
        self.add_folder(ROOT_ID, "root", None)
        self.add_folder("01DOCS0000000!104", "Documents", ROOT_ID)
        self.add_folder(FOLDER_ID, "openhora", "01DOCS0000000!104")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, body=b"", headers=None):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def error(self, status, code, message, headers=None):
                self._send(status, {"error": {"code": code, "message": message}}, headers)

            def _drop(self):
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            def _entry(self, body):
                parsed = urllib.parse.urlparse(self.path)
                entry = {"method": self.command, "raw_path": parsed.path, "path": urllib.parse.unquote(parsed.path),
                         "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}, "body": body,
                         "if_match": self.headers.get("If-Match"), "content_type": self.headers.get("Content-Type"),
                         "content_range": self.headers.get("Content-Range"), "auth": self.headers.get("Authorization"),
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"}
                return entry

            def _read(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def do_POST(self):  # noqa: N802
                body = self._read()
                entry = self._entry(body)
                if entry["path"] == "/token":
                    with owner.lock:
                        owner.token_forms.append({k: v[0] for k, v in urllib.parse.parse_qs(body.decode()).items()})
                    return self._send(*owner.token(owner.token_forms[-1]))
                with owner.lock:
                    owner.requests.append(entry)
                if not entry["bearer"]:
                    return self.error(401, "InvalidAuthenticationToken", "no bearer token")
                found = re.fullmatch(r"/v1\.0/drives/([^/]+)/items/([^/]+)/createUploadSession", entry["path"])
                if found:
                    return owner.write(self, entry, "SESSION", lambda: owner.session(found.group(1), found.group(2), entry))
                owner.violate(self, entry)

            def do_PUT(self):  # noqa: N802
                body = self._read()
                entry = self._entry(body)
                found = re.fullmatch(r"/upload/([A-Za-z0-9]+)", entry["path"])
                if found:
                    with owner.lock:
                        owner.uploads.append(entry)
                    if entry["auth"] is not None:
                        return self.error(400, "badRequest", "an upload address takes no Authorization header")
                    return owner.write(self, entry, "UPLOAD", lambda: owner.upload(found.group(1), entry))
                with owner.lock:
                    owner.requests.append(entry)
                if not entry["bearer"]:
                    return self.error(401, "InvalidAuthenticationToken", "no bearer token")
                if entry["path"].endswith(":/content"):
                    return owner.write(self, entry, "PUT", lambda: owner.create(entry))
                owner.violate(self, entry)

            def do_GET(self):  # noqa: N802
                entry = self._entry(b"")
                with owner.lock:
                    owner.requests.append(entry)
                if not entry["bearer"]:
                    return self.error(401, "InvalidAuthenticationToken", "no bearer token")
                item = owner.lookup(entry["path"])
                if item == "unserved":
                    return owner.violate(self, entry)
                if item is None:
                    return self.error(404, "itemNotFound", "not found")
                self._send(200, owner.resource(item))

            def do_PATCH(self):  # noqa: N802
                owner.violate(self, self._entry(self._read()))

            def do_DELETE(self):  # noqa: N802
                owner.violate(self, self._entry(self._read()))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.root = f"http://127.0.0.1:{self.port}"
        self.base = self.root + "/v1.0"
        self.token_url = f"{self.root}/token"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # --- the service -----------------------------------------------------------------------------------------------------------

    def token(self, form):
        if form.get("client_id") != CLIENT_ID or "client_secret" in form:
            return 401, {"error": "invalid_client", "error_description": "AADSTS700016: Application not found."}
        if form.get("grant_type") != "refresh_token" or form.get("refresh_token") != REFRESH_TOKEN:
            return 400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad refresh token"}
        return 200, {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer", "scope": self.scope, "refresh_token": REFRESH_TOKEN}

    def violate(self, handler, entry):
        with self.lock:
            self.violations.append((entry["method"], entry["path"]))
        handler.error(405, "methodNotAllowed", "this stand-in serves only the requests of the OneDrive writer")

    def tick(self) -> str:
        """The service's clock: the real time (the writer compares a time of the service with the time it claimed a key)."""
        self.clock += 1
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def new_id(self) -> str:
        self.counter += 1
        return f"01NEW{self.counter:07d}!{200 + self.counter}"

    def add_folder(self, ident, name, parent):
        self.items[ident] = {"id": ident, "name": name, "parent": parent, "folder": True, "content": b"", "n": 1, "created": "2026-10-01T08:00:00Z",
                             "modified": "2026-10-01T08:00:00Z"}

    def add_file(self, ident, name, data: bytes, parent=FOLDER_ID, mime="text/markdown", package=False):
        self.items[ident] = {"id": ident, "name": name, "parent": parent, "folder": False, "content": data, "n": 3, "mime": mime, "package": package,
                             "created": "2026-10-10T09:00:00Z", "modified": "2026-10-10T09:00:00Z"}
        return self.items[ident]

    def etag(self, item):
        return '"{%s},%d"' % (item["id"].replace("!", "-"), item["n"])

    def ctag(self, item):
        return '"c:{%s},%d"' % (item["id"].replace("!", "-"), item["n"])

    def resource(self, item):
        out = {"id": item["id"], "name": item["name"], "eTag": self.etag(item), "cTag": self.ctag(item), "size": len(item["content"]),
               "parentReference": {"driveId": DRIVE, "id": item["parent"]}, "createdDateTime": item["created"], "lastModifiedDateTime": item["modified"]}
        if item["folder"]:
            out["folder"] = {"childCount": 1}
        else:
            out["file"] = {"mimeType": item.get("mime", "text/markdown")}
            if item.get("package"):
                out["package"] = {"type": "oneNote"}
        return out

    def child(self, parent, name):
        found = [i for i in self.items.values() if i["parent"] == parent and i["name"].casefold() == name.casefold()]
        return found[0] if found else None

    def lookup(self, path):
        """The item a GET path names; None for no such item; "unserved" for a path this stand-in does not serve at all."""
        found = re.fullmatch(r"/v1\.0/me/drive/items/([^/:]+)", path)
        if found:
            return self.items.get(found.group(1))
        found = re.fullmatch(r"/v1\.0/me/drive/items/([^/:]+):/([^/:]+)", path)
        if found:
            return self.child(found.group(1), found.group(2)) if found.group(1) in self.items else None
        found = re.fullmatch(r"/v1\.0/drives/([^/]+)/items/([^/]+)", path)
        if found:
            return self.items.get(found.group(2)) if found.group(1) == DRIVE else None
        found = re.fullmatch(r"/v1\.0/me/drive/root:((?:/[^/:]+)+)", path)
        if found:
            current = ROOT_ID
            for segment in found.group(1)[1:].split("/"):
                item = self.child(current, segment)
                if item is None:
                    return None
                current = item["id"]
            return self.items[current]
        return "unserved"

    def write(self, handler, entry, kind, make):
        with self.lock:
            failing, self.fail_write = self.fail_write, None
            edit, self.edit_during = self.edit_during, None
        if failing:
            return handler.error(failing, "generalException", "stand-in refusal", {"Retry-After": "7"} if failing in (429, 503) else None)
        if edit:
            edit()
        with self.lock:
            status, answer = make()
        if self.lose_answer == kind:
            return handler._drop()
        handler._send(status, answer)

    def create(self, entry):
        found = re.fullmatch(r"/v1\.0/me/drive/items/([^/:]+):/([^/:]+):/content", entry["path"])
        if found:
            parent, name = found.group(1), found.group(2)
        else:
            found = re.fullmatch(r"/v1\.0/me/drive/root:((?:/[^/:]+)+):/content", entry["path"])
            if not found:
                return 400, {"error": {"code": "invalidRequest", "message": "stand-in: unserved path"}}
            segments = found.group(1)[1:].split("/")
            parent = ROOT_ID
            for segment in segments[:-1]:
                step = self.child(parent, segment)
                parent = step["id"] if step else None
                if parent is None:
                    return 404, {"error": {"code": "itemNotFound", "message": "no such folder"}}
            name = segments[-1]
        if parent not in self.items or not self.items[parent]["folder"]:
            return 404, {"error": {"code": "itemNotFound", "message": "no such folder"}}
        if entry["query"].get("@microsoft.graph.conflictBehavior") != "fail":
            return 400, {"error": {"code": "invalidRequest", "message": "stand-in: this writer always asks for conflictBehavior=fail"}}
        if self.child(parent, name):
            return 409, {"error": {"code": "nameAlreadyExists", "message": "The specified item name already exists."}}
        ident = self.new_id()
        stamp = self.tick()
        self.items[ident] = {"id": ident, "name": name, "parent": parent, "folder": False, "content": entry["body"], "n": 1, "mime": entry["content_type"],
                             "created": stamp, "modified": stamp}
        return 201, self.resource(self.items[ident])

    def session(self, drive, ident, entry):
        item = self.items.get(ident)
        if drive != DRIVE or item is None:
            return 404, {"error": {"code": "itemNotFound", "message": "not found"}}
        if entry["if_match"] is not None and entry["if_match"] != self.etag(item):
            return 412, {"error": {"code": "preconditionFailed", "message": "The request cannot be completed because the resource has changed."}}
        if json.loads(entry["body"]) != {"item": {"@microsoft.graph.conflictBehavior": "replace"}}:
            return 400, {"error": {"code": "invalidRequest", "message": "stand-in: unexpected session body"}}
        token = f"S{len(self.sessions) + 1:04d}ession"
        self.sessions[token] = ident
        if self.no_upload_url:
            return 200, {"expirationDateTime": "2026-10-19T10:00:00Z"}
        return 200, {"uploadUrl": f"http://{self.upload_host}:{self.port}/upload/{token}", "expirationDateTime": "2026-10-19T10:00:00Z"}

    def upload(self, token, entry):
        item = self.items.get(self.sessions.get(token))
        if item is None:
            return 404, {"error": {"code": "itemNotFound", "message": "no such session"}}
        found = re.fullmatch(r"bytes 0-(\d+)/(\d+)", entry["content_range"] or "")
        if not found or int(found.group(2)) != len(entry["body"]) or int(found.group(1)) != len(entry["body"]) - 1:
            return 416, {"error": {"code": "invalidRange", "message": "stand-in: the range is not the whole body"}}
        item["content"] = entry["body"]
        item["n"] += 1
        item["modified"] = self.tick()
        return 200, self.resource(item)

    # --- what a test hands to a script ---------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "tenant": "common", "scope": " ".join(PLATFORM),
                  "account_kind": "personal", "account": ADDRESS, "obtained_at": "2026-10-18T08:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self, **over) -> dict:
        return {"WRITER_ONEDRIVE_API_BASE": self.base, "WRITER_ONEDRIVE_TOKEN_URL": self.token_url, "WRITER_ONEDRIVE_UPLOAD_HOSTS": "127.0.0.1",
                "MICROSOFT_ACCOUNT_TOKEN": self.record_json(), **over}

    def listing(self) -> list:
        return [(r["method"], r["path"], r["query"]) for r in self.requests]
