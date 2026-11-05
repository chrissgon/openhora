"""A stand-in for Gmail on 127.0.0.1, for the tests of the mailbox writer (package W3): the token endpoint, the profile, one message (minimal and metadata
formats), a list of messages by `rfc822msgid:`, `messages.batchModify`, `messages.trash` and `drafts.create`. It keeps its messages in memory and RECORDS every
request (method, path, query, body) so that a test can assert the exact list. A method or a path the writer should never send (a removal for good, a send, the
trash emptied) is answered 405 and recorded too, and `unexpected()` lists it.

  fake = FakeGmail()                           # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                     # a GOOGLE_ACCOUNT_TOKEN value this fake accepts
  fake.env()                                   # the test overrides of the writer (both URLs, set together)
  fake.add_message(mail_id, subject, sender, labels, **more)   # a message that is already there; returns it
  fake.lose_answer_once = True                 # the next write is APPLIED and the connection is closed with no answer (a lost answer)
  fake.refuse_next = (status, reason)          # the next write is answered with that status and changes nothing
  fake.fail_write_number = (n, status)         # the n-th write from now (1-based) is answered with that status and changes nothing
  fake.redirect_next = True                    # the next write is answered 307 to another address
  fake.fail_get_next = 500                     # the next read is answered with that status
  fake.refresh_scope                           # what a refresh says the token carries (default: the platform's set)

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import base64
import email
import email.policy
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCOUNT = "pat@example.com"
CLIENT_ID = "stand-in-client-id.example"
CLIENT_SECRET = "fake-client-secret-not-real-4f2a"
REFRESH_TOKEN = "fake-refresh-token-not-real-9b1c"
ACCESS_TOKEN = "fake-access-token-not-real-7d3e"
SECRETS = (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN)

GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
DRIVE = "https://www.googleapis.com/auth/drive"
PLATFORM_SET = (GMAIL_MODIFY, CALENDAR_EVENTS, CALENDAR_LIST, DRIVE)

MESSAGES = "/gmail/v1/users/me/messages"
DRAFTS = "/gmail/v1/users/me/drafts"


class FakeGmail:
    def __init__(self):
        self.requests: list = []
        self.messages: dict = {}
        self.drafts: dict = {}
        self.counter = 0
        self.write_count = 0
        self.refresh_scope = " ".join(PLATFORM_SET)
        self.lose_answer_once = False
        self.refuse_next = None
        self.fail_write_number = None
        self.redirect_next = False
        self.fail_get_next = None
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
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = {"unreadable": True}
                pairs = urllib.parse.parse_qs(parsed.query)
                entry = {"method": self.command, "path": parsed.path, "query": {k: v[0] if len(v) == 1 else v for k, v in pairs.items()}, "body": body,
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}", "raw_body": raw}
                owner.requests.append(entry)
                if self.command == "POST" and parsed.path == "/token":
                    return self._send(*owner.token(urllib.parse.parse_qs(raw.decode())))
                if not entry["bearer"]:
                    return self._send(401, {"error": {"status": "UNAUTHENTICATED", "message": "no bearer token"}})
                if self.command != "GET" and owner.redirect_next:
                    owner.redirect_next = False
                    return self._send(307, None, {"Location": "http://127.0.0.1:1/elsewhere"})
                if self.command == "GET" and owner.fail_get_next:
                    status, owner.fail_get_next = owner.fail_get_next, None
                    return self._send(status, {"error": {"code": status, "message": "stand-in failure"}})
                status, answer, headers, apply = owner.api(entry)
                if status == 405:
                    return self._send(405, answer)
                if self.command != "GET" and owner.lose_answer_once and apply:
                    owner.lose_answer_once = False
                    apply()
                    self.connection.close()      # the request landed and the answer is lost
                    return None
                if apply:
                    apply()
                return self._send(status, answer, headers)

            do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _handle   # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.token_url = f"{self.base}/token"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # --- the service -------------------------------------------------------------------------------------------------------------

    def token(self, form):
        first = lambda key: (form.get(key) or [""])[0]   # noqa: E731
        if first("client_id") != CLIENT_ID or first("client_secret") != CLIENT_SECRET:
            return 401, {"error": "invalid_client", "error_description": "stand-in: unknown client"}
        if first("grant_type") == "refresh_token" and first("refresh_token") == REFRESH_TOKEN:
            answer = {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer"}
            if self.refresh_scope is not None:
                answer["scope"] = self.refresh_scope
            return 200, answer
        return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}

    def add_message(self, mail_id, subject, sender, labels, **more):
        self.counter += 1
        item = {"id": mail_id, "threadId": more.pop("thread", f"t{mail_id}"), "labelIds": list(labels), "internalDate": more.pop("internal_date", "1792400000000"),
                "headers": {"Subject": subject, "From": sender, "Date": "Sat, 17 Oct 2026 09:00:00 +0000", "Message-ID": more.pop("message_id", f"<{mail_id}@mail.example>")}}
        item.update(more)
        self.messages[mail_id] = item
        return item

    def unexpected(self):
        """The requests that are not one of the writer's allow-list (a method or a path it should never send)."""
        found = []
        for entry in self.requests:
            path, method = entry["path"], entry["method"]
            ok = (path == "/token" and method == "POST") or (path == "/gmail/v1/users/me/profile" and method == "GET") or (path == MESSAGES and method == "GET") \
                or (path == f"{MESSAGES}/batchModify" and method == "POST") or (path == DRAFTS and method == "POST") \
                or (path.startswith(MESSAGES + "/") and path.count("/") == MESSAGES.count("/") + 1 and method == "GET") \
                or (path.startswith(MESSAGES + "/") and path.endswith("/trash") and path.count("/") == MESSAGES.count("/") + 2 and method == "POST")
            if not ok:
                found.append((method, path))
        return found

    def _write_refusal(self):
        self.write_count += 1
        if self.refuse_next:
            status, reason = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": status, "message": reason, "errors": [{"reason": reason}]}}, ({"Retry-After": "30"} if status in (429, 503) else {})
        if self.fail_write_number and self.fail_write_number[0] == self.write_count:
            status = self.fail_write_number[1]
            return status, {"error": {"code": status, "message": "stand-in failure"}}, {}
        return None

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes the messages (called after the answer is decided, before it is sent)."""
        method, path, query = entry["method"], entry["path"], entry["query"]
        if path == "/gmail/v1/users/me/profile" and method == "GET":
            return 200, {"emailAddress": ACCOUNT}, {}, None
        if path == MESSAGES and method == "GET":
            wanted = str(query.get("q", "")).replace("rfc822msgid:", "")
            hits = [{"id": m["id"], "threadId": m["threadId"]} for m in self.messages.values()
                    if wanted and m["headers"].get("Message-ID", "").strip("<>") == wanted and (query.get("labelIds") in (None, "") or query.get("labelIds") in m["labelIds"])]
            return 200, {"messages": hits} if hits else {}, {}, None
        if method == "POST" and path == f"{MESSAGES}/batchModify":
            refused = self._write_refusal()
            if refused:
                return (*refused, None)
            body = entry["body"] or {}
            unknown = [i for i in body.get("ids", []) if i not in self.messages]
            if unknown:
                return 404, {"error": {"code": 404, "message": "Requested entity was not found."}}, {}, None

            def apply():
                for i in body.get("ids", []):
                    labels = set(self.messages[i]["labelIds"]) - set(body.get("removeLabelIds") or [])
                    self.messages[i]["labelIds"] = sorted(labels | set(body.get("addLabelIds") or []))
            return 204, None, {}, apply
        if method == "POST" and path.startswith(MESSAGES + "/") and path.endswith("/trash") and path.count("/") == MESSAGES.count("/") + 2:
            refused = self._write_refusal()
            if refused:
                return (*refused, None)
            message_id = urllib.parse.unquote(path[len(MESSAGES) + 1:-len("/trash")])
            if message_id not in self.messages:
                return 404, {"error": {"code": 404, "message": "Requested entity was not found."}}, {}, None

            def apply():
                labels = set(self.messages[message_id]["labelIds"]) - {"INBOX"}
                self.messages[message_id]["labelIds"] = sorted(labels | {"TRASH"})
            return 200, {"id": message_id, "labelIds": ["TRASH"]}, {}, apply
        if method == "POST" and path == DRAFTS:
            refused = self._write_refusal()
            if refused:
                return (*refused, None)
            message = (entry["body"] or {}).get("message") or {}
            if message.get("threadId") == "tmissing":
                return 404, {"error": {"code": 404, "message": "Requested entity was not found."}}, {}, None
            raw = base64.urlsafe_b64decode(message.get("raw", "").encode("ascii"))
            parsed = email.message_from_bytes(raw, policy=email.policy.default)
            self.counter += 1
            draft_id, message_id = f"r{self.counter:04d}", f"d{self.counter:04d}"

            def apply():
                headers = {k: str(parsed[k]) for k in ("Subject", "From", "To", "Cc", "Bcc", "Message-ID", "In-Reply-To", "References") if parsed[k] is not None}
                self.drafts[draft_id] = {"id": draft_id, "raw": raw, "thread": message.get("threadId"), "headers": headers,
                                         "text": parsed.get_body(("plain",)).get_content() if parsed.get_body(("plain",)) else ""}
                self.messages[message_id] = {"id": message_id, "threadId": message.get("threadId") or f"t{message_id}", "labelIds": ["DRAFT"], "internalDate": "1792400000000",
                                             "headers": headers}
            return 200, {"id": draft_id, "message": {"id": message_id, "threadId": message.get("threadId") or f"t{message_id}", "labelIds": ["DRAFT"]}}, {}, apply
        if method == "GET" and path.startswith(MESSAGES + "/") and "/" not in path[len(MESSAGES) + 1:]:
            item = self.messages.get(urllib.parse.unquote(path[len(MESSAGES) + 1:]))
            if item is None:
                return 404, {"error": {"code": 404, "message": "Requested entity was not found."}}, {}, None
            if query.get("format") == "metadata":
                wanted = query.get("metadataHeaders") or []
                wanted = [wanted] if isinstance(wanted, str) else wanted
                return 200, {"id": item["id"], "threadId": item["threadId"], "labelIds": item["labelIds"], "internalDate": item["internalDate"],
                             "payload": {"headers": [{"name": k, "value": v} for k, v in item["headers"].items() if k in wanted]}}, {}, None
            return 200, {"id": item["id"], "threadId": item["threadId"], "labelIds": item["labelIds"]}, {}, None
        return 405, {"error": {"message": "this stand-in takes only the writer's requests"}}, {}, None

    # --- what a test hands to the writer -------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "scope": " ".join(PLATFORM_SET), "account": ACCOUNT, "obtained_at": "2026-10-18T09:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self) -> dict:
        return {"WRITER_MAIL_GOOGLE_API_BASE": self.base, "WRITER_MAIL_GOOGLE_TOKEN_URL": self.token_url}

    def writes(self) -> list:
        """The requests that are not reads: [(method, path, query, body)]."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.requests if r["method"] not in ("GET",) and r["path"] != "/token"]
