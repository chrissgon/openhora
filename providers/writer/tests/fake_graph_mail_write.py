"""A stand-in for Microsoft on 127.0.0.1, for the tests of the Outlook mailbox writer (package W3): the Microsoft identity token endpoint (a public client, a new
refresh token on every refresh, the old one left valid) and the mail of one mailbox through Graph: folders (well-known names and one named folder), a message (get),
the messages of a folder (with a filter on the internetMessageId or on the private property), a new draft, `createReply`, `move` (the moved message gets a NEW id and a
new changeKey) and `PATCH`. It keeps everything in memory and RECORDS every request (method, path, query, body) so that a test can assert the exact list. It serves
no removal, no send, no reply, no forward: such a request is answered 405 and recorded, and `unexpected()` lists it with any other request the writer should never send.

  fake = FakeGraphMail()                      # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                    # a MICROSOFT_ACCOUNT_TOKEN value this fake accepts
  fake.env()                                  # the test overrides of the writer (both URLs, set together)
  fake.add_message(id, subject, sender, folder="inbox", **more)   # a message that is already there; returns it
  fake.lose_answer_once = True                # the next write is APPLIED and the connection is closed with no answer
  fake.refuse_next = (status, code)           # the next write is answered with that status and changes nothing
  fake.fail_write_number = (n, status)        # the n-th write from now (1-based) is answered with that status and changes nothing
  fake.redirect_next = True                   # the next write is answered 307 to another address
  fake.fail_from_write = (n, status)          # every write from the n-th on is answered with that status and changes nothing
  fake.ignore_reply_body = True               # createReply ignores the message it is given
  fake.fail_get_next = 500                    # the next read is answered with that status
  fake.scope_granted                          # what a refresh says the token carries (default: the platform's set and the words that grant nothing)

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ADDRESS = "casey.rivera@mail.example"
CLIENT_ID = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
TENANT = "common"
REFRESH_TOKEN = "fake-refresh-token-0-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
SECRETS = (REFRESH_TOKEN, ACCESS_TOKEN)
PLATFORM = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
PREFIX = "https://graph.microsoft.com/"
GRANTED = " ".join(PREFIX + name for name in PLATFORM) + " offline_access openid profile"
GRAPH = "/v1.0"
KEY_PROPERTY = "String {c1a7e5d2-9b34-4f68-8a1e-3d5f7b2c9e41} Name openhora_key"
FOLDERS = {"inbox": "AAMkInbox0001=", "archive": "AAMkArchive001=", "deleteditems": "AAMkDeleted001=", "drafts": "AAMkDrafts0001=", "junkemail": "AAMkJunk00001="}
NAMED = "AAMkFolderBills1="           # a folder the person made


class FakeGraphMail:
    def __init__(self):
        self.requests: list = []
        self.token_forms: list = []
        self.messages: dict = {}
        self.folders = dict(FOLDERS)
        self.known_folder_ids = set(FOLDERS.values()) | {NAMED}
        self.version = 0
        self.counter = 0
        self.rotations = 0
        self.write_count = 0
        self.valid_refresh = {REFRESH_TOKEN}
        self.scope_granted = GRANTED
        self.lose_answer_once = False
        self.refuse_next = None
        self.fail_write_number = None
        self.redirect_next = False
        self.fail_get_next = None
        self.fail_from_write = None      # (n, status): every write from the n-th on is answered with that status and changes nothing
        self.ignore_reply_body = False      # createReply ignores the message it is given (as Graph may)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                return

            def _send(self, status, body, headers=None):
                data = b"" if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                parsed = urllib.parse.urlparse(self.path)
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.command == "POST" and parsed.path == "/token":
                    form = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode()).items()}
                    owner.token_forms.append(form)
                    return self._send(*owner.token(form))
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = {"unreadable": True}
                entry = {"method": self.command, "path": urllib.parse.unquote(parsed.path), "raw_path": parsed.path,
                         "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}, "body": body,
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"}
                owner.requests.append(entry)
                if not entry["bearer"]:
                    return self._send(401, {"error": {"code": "InvalidAuthenticationToken", "message": "Access token is empty or invalid."}})
                if self.command != "GET" and owner.redirect_next:
                    owner.redirect_next = False
                    return self._send(307, None, {"Location": "http://127.0.0.1:1/elsewhere"})
                if self.command == "GET" and owner.fail_get_next:
                    status, owner.fail_get_next = owner.fail_get_next, None
                    return self._send(status, {"error": {"code": "generalException", "message": "stand-in failure"}})
                status, answer, headers, apply = owner.api(entry)
                if self.command != "GET" and owner.lose_answer_once and apply:
                    owner.lose_answer_once = False
                    apply()
                    self.connection.close()      # the request landed and the answer is lost
                    return None
                if apply:
                    answer = apply() or answer
                return self._send(status, answer, headers)

            do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _handle   # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.root = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.base = self.root + GRAPH
        self.token_url = f"{self.root}/token"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # --- the service -------------------------------------------------------------------------------------------------------------

    def token(self, form):
        if form.get("client_id") != CLIENT_ID or "client_secret" in form:
            return 401, {"error": "invalid_client", "error_description": "AADSTS700016: Application not found."}
        if form.get("grant_type") == "refresh_token" and form.get("refresh_token") in self.valid_refresh:
            self.rotations += 1
            rotated = f"fake-refresh-token-{self.rotations}-not-real"
            self.valid_refresh.add(rotated)
            return 200, {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer", "scope": self.scope_granted, "refresh_token": rotated}
        return 400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad refresh token"}

    def next_key(self):
        self.version += 1
        return f"CQAAABYAAAB{self.version:08d}"

    def folder_id(self, name_or_id):
        return self.folders.get(name_or_id) or (name_or_id if name_or_id in self.known_folder_ids else None)

    def add_message(self, message_id, subject, sender, folder="inbox", **more):
        item = {"id": message_id, "changeKey": self.next_key(), "parentFolderId": self.folder_id(folder) or folder, "isRead": False, "isDraft": False, "subject": subject,
                "from": {"emailAddress": {"name": "Display Name", "address": sender}}, "receivedDateTime": "2026-10-17T09:00:00Z",
                "internetMessageId": more.pop("internet_id", f"<{message_id}@mail.example>"), "conversationId": more.pop("conversation", f"AAQkConv{message_id}"),
                "singleValueExtendedProperties": []}
        item.update(more)
        self.messages[message_id] = item
        return item

    def unexpected(self):
        """The requests that are not one of the writer's allow-list (a method or a path it should never send)."""
        found = []
        for entry in self.requests:
            path, method = entry["path"], entry["method"]
            rest = path[len(GRAPH):] if path.startswith(GRAPH + "/") else path
            ok = (rest == "/token" and method == "POST"
                  or rest == "/me/mailFolders" and method == "GET"
                  or re.fullmatch(r"/me/mailFolders/[^/]+(/messages)?", rest) is not None and method == "GET"
                  or re.fullmatch(r"/me/messages/[^/]+", rest) is not None and method in ("GET", "PATCH")
                  or rest == "/me/messages" and method == "POST"
                  or re.fullmatch(r"/me/messages/[^/]+/(createReply|move)", rest) is not None and method == "POST")
            if not ok:
                found.append((method, path))
        return found

    def _refusal(self):
        self.write_count += 1
        if self.refuse_next:
            status, code = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": code, "message": f"stand-in refusal {code}"}}, ({"Retry-After": "30"} if status in (429, 503) else {})
        if self.fail_from_write and self.write_count >= self.fail_from_write[0]:
            return self.fail_from_write[1], {"error": {"code": "generalException", "message": "stand-in failure"}}, {}
        if self.fail_write_number and self.fail_write_number[0] == self.write_count:
            status = self.fail_write_number[1]
            return status, {"error": {"code": "generalException", "message": "stand-in failure"}}, {}
        return None

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes the mailbox and may return the answer to send."""
        method, rest = entry["method"], entry["path"][len(GRAPH):]
        not_served = (405, {"error": {"code": "methodNotAllowed", "message": "this stand-in serves only the writer's requests"}}, {}, None)
        if rest == "/me/mailFolders" and method == "GET":
            return 200, {"value": [{"id": FOLDERS["inbox"]}]}, {}, None
        found = re.fullmatch(r"/me/mailFolders/([^/]+)(/messages)?", rest)
        if found and method == "GET":
            folder = self.folder_id(found.group(1))
            if folder is None:
                return 404, {"error": {"code": "ErrorItemNotFound", "message": "The specified folder could not be found in the store."}}, {}, None
            if not found.group(2):
                return 200, {"id": folder}, {}, None
            query = entry["query"].get("$filter", "")
            wanted_id = re.search(r"internetMessageId eq '((?:[^']|'')*)'", query)
            wanted_key = re.search(r"ep/value eq '([^']*)'", query)
            hits = [m for m in self.messages.values() if m["parentFolderId"] == folder
                    and (not wanted_id or m["internetMessageId"] == wanted_id.group(1).replace("''", "'"))
                    and (not wanted_key or any(p["value"] == wanted_key.group(1) for p in m["singleValueExtendedProperties"]))]
            return 200, {"value": [{"id": m["id"]} for m in hits]}, {}, None
        if method not in ("GET", "POST", "PATCH"):
            return not_served
        if method in ("POST", "PATCH"):
            refused = self._refusal()
            if refused:
                return (*refused, None)
        if rest == "/me/messages" and method == "POST":
            body = entry["body"] or {}

            def apply():
                self.counter += 1
                item = self.add_message(f"AAMkDraft{self.counter:04d}=", "", ADDRESS, folder="drafts", isDraft=True)
                self.merge(item, body)
                return item
            return 201, {"id": "(new)"}, {}, apply
        found = re.fullmatch(r"/me/messages/([^/]+)(/createReply|/move)?", rest)
        if not found:
            return not_served
        item = self.messages.get(urllib.parse.unquote(found.group(1)))
        tail = found.group(2)
        if item is None:
            return 404, {"error": {"code": "ErrorItemNotFound", "message": "The specified object was not found in the store."}}, {}, None
        if method == "GET" and tail is None:
            shown = dict(item)
            if "singleValueExtendedProperties" not in entry["query"].get("$expand", ""):
                shown.pop("singleValueExtendedProperties", None)
            return 200, shown, {}, None
        if method == "PATCH" and tail is None:
            def apply():
                self.merge(item, entry["body"])
                return item
            return 200, item, {}, apply
        if method == "POST" and tail == "/move":
            destination = self.folder_id((entry["body"] or {}).get("destinationId"))
            if destination is None:
                return 404, {"error": {"code": "ErrorItemNotFound", "message": "The destination folder could not be found."}}, {}, None

            def apply():
                self.counter += 1
                moved = dict(item, id=f"AAMkMoved{self.counter:04d}=", parentFolderId=destination, changeKey=self.next_key())
                del self.messages[item["id"]]
                self.messages[moved["id"]] = moved
                return moved
            return 201, {"id": "(new)"}, {}, apply
        if method == "POST" and tail == "/createReply":
            body = {} if self.ignore_reply_body else (entry["body"] or {}).get("message") or {}

            def apply():
                self.counter += 1
                reply = self.add_message(f"AAMkReply{self.counter:04d}=", "RE: " + item["subject"], ADDRESS, folder="drafts", isDraft=True,
                                         toRecipients=[{"emailAddress": {"address": "reply-to-by-graph@mail.example"}}], conversationId=item["conversationId"])
                reply["body"] = {"contentType": "html", "content": "<p>quoted original</p>"}
                self.merge(reply, body)
                return reply
            return 201, {"id": "(new)"}, {}, apply
        return not_served

    def merge(self, item, body):
        for key, value in body.items():
            if key == "singleValueExtendedProperties":
                item[key] = [dict(p) for p in value]
            else:
                item[key] = value
        item["changeKey"] = self.next_key()

    # --- what a test hands to the writer -------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "tenant": TENANT, "scope": " ".join(PLATFORM),
                  "account_kind": "personal", "account": ADDRESS, "obtained_at": "2026-10-18T08:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self) -> dict:
        return {"WRITER_MAIL_OUTLOOK_API_BASE": self.base, "WRITER_MAIL_OUTLOOK_TOKEN_URL": self.token_url}

    def graph_requests(self):
        return [r for r in self.requests if r["path"].startswith(GRAPH + "/")]

    def writes(self) -> list:
        """The requests that are not reads: [(method, path, query, body)]."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.graph_requests() if r["method"] != "GET"]
