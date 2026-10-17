"""A stand-in for Microsoft Graph (OneDrive), the Microsoft identity token endpoint and the preauthenticated download host, all on
127.0.0.1, for the offline tests of providers/documents/onedrive.py and onedrive_auth.py. Not a test file, and never a copy of the
live service: it serves exactly the calls the provider's docstring names, keeps a few fictional items in memory, and refuses what the
reference says the service refuses (a missing or wrong bearer token, an unknown item, a `$select` that does not name a facet the
provider needs to see). No real account, tenant, key or file is ever involved: every credential of a test is a made-up string.

What it records, for the assertions: `requests` (method, path, query, whether a bearer token came) for the Graph calls,
`downloads` (the headers of every request that reached the download path), `token_forms` (every form posted to the token endpoint)
and `methods` (every HTTP method the Graph API saw: the provider must send GET only).

The download is a second address on the same listener (`/dl/<ticket>`), the way Graph's `/content` answers 302 to a preauthenticated
URL on another host; `download_base` is the base of that Location and a test can point it at a host outside the provider's list.

Usage (from a test):
  fake = fake_graph.FakeGraph()           # starts on a free loopback port in a daemon thread
  fake.base, fake.token_url               what the provider's environment names
  fake.record_json()                      an ONEDRIVE_SOURCES_TOKEN value that this fake accepts
  fake.add_file("b!drive1", "ITEM1!101", "Notes.docx", b"PK...")
  fake.edit(drive, item, content=...)     a person's edit: cTag and eTag move
  fake.touch(drive, item)                 a change of metadata only (a share, a rename): eTag moves, cTag does not
  fake.close()
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCOPE_URL_PREFIX = "https://graph.microsoft.com/"
SCOPE = "Files.Read"
REFRESH_SCOPE = SCOPE_URL_PREFIX + "Files.Read offline_access"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "common"
REFRESH_TOKEN = "fake-refresh-token-0-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
CODE = "fake-authorization-code"
DOWNLOAD_TICKET = "fake-download-ticket-not-real"
DOWNLOAD_TEMPAUTH = "fake-tempauth-not-real"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PDF = "application/pdf"
DRIVE = "b!Fake-Drive_1"
GRAPH_PREFIX = "/v1.0"


class FakeGraph:
    def __init__(self):
        self.items = {}                     # (drive id, item id) -> dict
        self.requests, self.downloads, self.token_forms, self.methods = [], [], [], []
        self.scope_granted = REFRESH_SCOPE  # what the token endpoint says it granted
        self.omit_scope = False             # answer a token with no scope field at all
        self.token_status = 200             # set 400 and token_error to answer an OAuth error
        self.token_error = {"error": "invalid_grant", "error_description": "AADSTS70008: The refresh token has expired."}
        self.code = CODE
        self.no_refresh_token = False       # answer an authorization code with no refresh token
        self.rotate = True                  # every refresh answers a new refresh token; the old one stays valid
        self.valid_refresh = {REFRESH_TOKEN}
        self.rotations = 0
        self.drive_type = "personal"
        self.fail_next = None               # (status, headers, body obj): answer the next Graph GET with it
        self.redirect_next = False          # answer the next Graph GET (not /content) with a 302 elsewhere
        self.download_base = None           # the base of the Location /content answers; default: this listener
        self.download_status = 200          # what the download path answers
        self.redirect_download = False      # the download path answers a 302 to elsewhere
        self.change_on_download = False     # a person edits the file right after its bytes were served
        self.report_size = {}               # (drive, item) -> a size the metadata claims, different from the bytes
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, body=b"", ctype="application/json", headers=None):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status, obj, headers=None):
                self._send(status, json.dumps(obj).encode(), headers=headers)

            def _error(self, status, code, message, headers=None):
                self._json(status, {"error": {"code": code, "message": message, "innerError": {"request-id": "fake"}}}, headers)

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
                    return self._token(form)

            def _token(self, form):
                if owner.token_status != 200:
                    return self._json(owner.token_status, owner.token_error)
                if form.get("client_id") != CLIENT_ID:
                    return self._json(401, {"error": "invalid_client", "error_description": "AADSTS700016: Application not found."})
                if "client_secret" in form:
                    return self._json(400, {"error": "invalid_client", "error_description": "a public client sends no secret"})
                answer = {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer", "scope": owner.scope_granted}
                if owner.omit_scope:
                    del answer["scope"]
                if form.get("grant_type") == "refresh_token":
                    if form.get("refresh_token") not in owner.valid_refresh:
                        return self._json(400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad refresh token"})
                    if owner.rotate:
                        owner.rotations += 1
                        answer["refresh_token"] = f"fake-refresh-token-{owner.rotations}-not-real"
                        owner.valid_refresh.add(answer["refresh_token"])
                    else:
                        answer["refresh_token"] = form["refresh_token"]
                    return self._json(200, answer)
                if form.get("grant_type") == "authorization_code":
                    if form.get("code") != owner.code or not form.get("code_verifier") or not form.get("redirect_uri"):
                        return self._json(400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad code"})
                    answer["refresh_token"] = REFRESH_TOKEN
                    if owner.no_refresh_token:
                        del answer["refresh_token"]
                    return self._json(200, answer)
                return self._json(400, {"error": "unsupported_grant_type"})

            def _other(self):
                with owner.lock:
                    owner.methods.append(self.command)
                self._error(405, "methodNotAllowed", "no write is served")

            do_PUT = do_PATCH = do_DELETE = _other   # noqa: N815

            def do_GET(self):   # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                path = urllib.parse.unquote(parsed.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                if path.startswith("/dl/"):
                    return self._download(path, query)
                auth = self.headers.get("Authorization", "")
                with owner.lock:
                    owner.methods.append("GET")
                    owner.requests.append({"method": "GET", "path": path, "query": query, "auth": bool(auth)})
                    redirect, failure = owner.redirect_next and not path.endswith("/content"), owner.fail_next
                    if redirect:
                        owner.redirect_next = False
                    if failure:
                        owner.fail_next = None
                if redirect:
                    return self._send(302, headers={"Location": "http://127.0.0.1:1/elsewhere"})
                if auth != f"Bearer {ACCESS_TOKEN}":
                    return self._error(401, "InvalidAuthenticationToken", "Access token is empty or invalid.")
                if failure:
                    status, headers, body = failure
                    return self._json(status, body, headers)
                if not path.startswith(GRAPH_PREFIX + "/"):
                    return self._error(404, "notFound", "not served")
                self._route(path[len(GRAPH_PREFIX):], query)

            def _route(self, rest, query):
                if rest == "/me/drive":
                    return self._json(200, {"id": DRIVE, "driveType": owner.drive_type})
                if rest.startswith("/me/drive/root/search(q='") and rest.endswith("')"):
                    text = rest[len("/me/drive/root/search(q='"):-2].replace("''", "'")
                    found = [k for k, v in owner.items.items() if text.lower() in v["name"].lower()]
                    return self._listing(found, query)
                if rest == "/me/drive/root/children":
                    return self._listing(owner.children_of(""), query)
                if rest.startswith("/me/drive/root:/") and rest.endswith(":/children"):
                    return self._listing(owner.children_of("/" + rest[len("/me/drive/root:/"):-len(":/children")].strip("/")), query)
                parts = rest.split("/")      # ["", "drives", d, "items", i, ("content")]
                if len(parts) >= 5 and parts[1] == "drives" and parts[3] == "items":
                    key = (parts[2], parts[4])
                    item = owner.items.get(key)
                    if item is None:
                        return self._error(404, "itemNotFound", "The resource could not be found.")
                    if len(parts) == 6 and parts[5] == "content":
                        return self._content(key, item)
                    if len(parts) == 5:
                        return self._json(200, owner.describe(key, query.get("$select")))
                self._error(404, "notFound", "not served")

            def _listing(self, keys, query):
                top = int(query.get("$top", "200"))
                out = {"value": [owner.describe(k, query.get("$select")) for k in keys[:top]]}
                if len(keys) > top:
                    out["@odata.nextLink"] = "https://graph.example/next?token=fake-skip"
                self._json(200, out)

            def _content(self, key, item):
                if item["content"] is None:
                    return self._error(400, "invalidRequest", "Cannot download a folder.")
                base = owner.download_base or owner.root
                ticket = urllib.parse.quote(f"{DOWNLOAD_TICKET}~{key[0]}~{key[1]}", safe="")
                self._send(302, headers={"Location": f"{base}/dl/{ticket}?tempauth={DOWNLOAD_TEMPAUTH}"})

            def _download(self, path, query):
                with owner.lock:
                    owner.downloads.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "path": path, "query": query})
                if owner.redirect_download:
                    return self._send(302, headers={"Location": "http://127.0.0.1:1/elsewhere"})
                if owner.download_status != 200:
                    return self._send(owner.download_status, b"expired")
                _, drive, item = path[len("/dl/"):].split("~", 2)
                found = owner.items.get((drive, item))
                if found is None or query.get("tempauth") != DOWNLOAD_TEMPAUTH:
                    return self._send(403, b"denied")
                self._send(200, found["content"], ctype="application/octet-stream")
                if owner.change_on_download:
                    owner.change_on_download = False
                    owner.edit(drive, item, content=found["content"] + b" (edited meanwhile)")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.root = f"http://127.0.0.1:{self.port}"
        self.base = self.root + GRAPH_PREFIX
        self.token_url = f"{self.root}/token"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    # --- what a test sets up ---------------------------------------------------------------------------------------------------

    def _add(self, drive, item, name, folder_path="/Documents", **fields):
        self.items[(drive, item)] = {"name": name, "folder_path": folder_path, "content": None, "mime": None, "version": 1, "etag_extra": 0,
                                     "modified": "2026-10-15T09:00:00Z", "facets": {}, **fields}
        return f"{drive}/{item}"

    def add_file(self, drive, item, name, content, mime=None, folder_path="/Documents", **facets):
        """A file of the person's own OneDrive. Extra keyword arguments are facets of the item (e.g. malware={})."""
        return self._add(drive, item, name, folder_path, content=content, mime=mime or "application/octet-stream", facets=facets)

    def add_folder(self, drive, item, name, folder_path="/Documents"):
        return self._add(drive, item, name, folder_path, facets={"folder": {"childCount": 2}})

    def add_package(self, drive, item, name, folder_path="/Documents"):
        return self._add(drive, item, name, folder_path, facets={"package": {"type": "oneNote"}})

    def add_remote(self, drive, item, name, folder_path="/Documents"):
        return self._add(drive, item, name, folder_path,
                         facets={"remoteItem": {"id": "REMOTE1!5", "parentReference": {"driveId": "b!Other-Drive_9"}}, "file": {"mimeType": PDF}})

    def edit(self, drive, item, content):
        """A person's edit: new bytes; the cTag and the eTag move."""
        found = self.items[(drive, item)]
        found["content"] = content
        found["version"] += 1
        found["modified"] = f"2026-10-15T09:{found['version']:02d}:00Z"

    def touch(self, drive, item):
        """A change of metadata only (a share, a rename): the eTag moves, the cTag does not."""
        self.items[(drive, item)]["etag_extra"] += 1

    def lie_about_size(self, drive, item, size):
        self.report_size[(drive, item)] = size

    def children_of(self, folder_path):
        return [k for k, v in self.items.items() if v["folder_path"] == folder_path]

    def describe(self, key, select=None):
        """The item as Graph answers it: only the fields `$select` names (and `id`), the way the live API narrows a response."""
        item = self.items[key]
        full = {"id": key[1], "name": item["name"], "cTag": f"c:{{FAKE-{key[1]}}},{item['version']}",
                "eTag": f"\"{{FAKE-{key[1]}}},{item['version']}.{item['etag_extra']}\"", "lastModifiedDateTime": item["modified"],
                "parentReference": {"driveId": key[0], "path": "/drive/root:" + item["folder_path"]}}
        if item["content"] is not None:
            full["size"] = self.report_size.get(key, len(item["content"]))
            full["file"] = {"mimeType": item["mime"]}
        full.update(item["facets"])
        if select:
            wanted = {"id", *select.split(",")}
            full = {k: v for k, v in full.items() if k in wanted}
        return full

    # --- what a test reads ------------------------------------------------------------------------------------------------------

    def record(self, **over):
        record = {"refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "tenant": TENANT, "scope": SCOPE, "account_kind": "personal",
                  "obtained_at": "2026-10-15T08:00:00Z"}
        record.update(over)
        return record

    def record_json(self, **over):
        return json.dumps(self.record(**over))

    def env(self, **over):
        """What the provider's process needs to talk to this fake and find its authorization in the environment."""
        return {"INTEGRATION_DOCUMENTS_ONEDRIVE_API_BASE": self.base, "INTEGRATION_DOCUMENTS_ONEDRIVE_TOKEN_URL": self.token_url,
                "INTEGRATION_DOCUMENTS_ONEDRIVE_DOWNLOAD_HOSTS": "127.0.0.1", "ONEDRIVE_SOURCES_TOKEN": self.record_json(**over)}

    def api_requests(self):
        return [r for r in self.requests if r["path"].startswith(GRAPH_PREFIX + "/")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
