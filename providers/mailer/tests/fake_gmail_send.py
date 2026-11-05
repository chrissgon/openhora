"""A stand-in for Gmail on 127.0.0.1, for the tests of the Gmail mailer (providers/mailer/gmail.py; package W2): the token endpoint, the profile of the account, the
search of its sent mail, the metadata of a message, and `messages.send`. It keeps what was sent in memory (the decoded message, a service id, the labels it carries),
and RECORDS every request (method, path, query, body) so that a test can assert the exact list. A method or a path the mailer should never send is answered 405 and
recorded too, and `unexpected()` lists it.

  fake = FakeGmail()                          # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                    # a GOOGLE_ACCOUNT_TOKEN value this fake accepts
  fake.env()                                  # the test overrides of the mailer (both URLs, set together)
  fake.lose_answer_once = True                # the next send is APPLIED and the connection is closed with no answer (a lost answer)
  fake.refuse_next = (status, reason)         # the next send is answered with that status and nothing is sent
  fake.redirect_next = True                   # the next send is answered 307 to another address
  fake.fail_get_next = 500                    # the next read is answered with that status
  fake.fail_search_next = 500                 # the next search of the sent mail is answered with that status
  fake.send_status = 201                      # the next send is applied and answered with that 2xx instead of 200 (an answer the documentation does not give)
  fake.profile_address                        # what the profile names (default: ACCOUNT)
  fake.rewrite_message_id = True              # Gmail gives a sent message another Message-ID than the one in the raw message
  fake.refresh_scope                          # what a refresh says the token carries (default: the platform's set)
  fake.sent                                   # [{"id", "threadId", "labelIds", "raw" (bytes), "headers" (a dict of the Message-ID the service holds)}]

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
PREFIX = "/gmail/v1/users/me"


class FakeGmail:
    def __init__(self):
        self.requests: list = []
        self.sent: list = []
        self.counter = 0
        self.refresh_scope = " ".join(PLATFORM_SET)
        self.profile_address = ACCOUNT
        self.rewrite_message_id = False
        self.lose_answer_once = False
        self.refuse_next = None
        self.redirect_next = False
        self.fail_get_next = None
        self.fail_search_next = None
        self.send_status = None
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
                entry = {"method": self.command, "path": urllib.parse.unquote(parsed.path), "raw_path": parsed.path,
                         "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}, "body": body,
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"}
                owner.requests.append(entry)
                if self.command == "POST" and parsed.path == "/token":
                    return self._send(*owner.token(urllib.parse.parse_qs(raw.decode())))
                if not entry["bearer"]:
                    return self._send(401, {"error": {"status": "UNAUTHENTICATED", "message": "no bearer token"}})
                if self.command == "POST" and owner.redirect_next:
                    owner.redirect_next = False
                    return self._send(307, None, {"Location": "http://127.0.0.1:1/elsewhere"})
                if self.command == "GET" and owner.fail_get_next:
                    status, owner.fail_get_next = owner.fail_get_next, None
                    return self._send(status, {"error": {"code": status, "message": "stand-in failure"}})
                status, answer, headers, apply = owner.api(entry)
                if status == 405:
                    return self._send(405, answer)
                if self.command == "POST" and owner.lose_answer_once and apply:
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

    def unexpected(self):
        """The requests that are not one of the mailer's allow-list (a method or a path it should never send)."""
        found = []
        for entry in self.requests:
            path, method = entry["path"], entry["method"]
            ok = path == "/token" and method == "POST" or method == "GET" and path in (f"{PREFIX}/profile", f"{PREFIX}/messages") \
                or method == "GET" and path.startswith(f"{PREFIX}/messages/") and "/" not in path[len(PREFIX) + 10:] and path != f"{PREFIX}/messages/send" \
                or method == "POST" and path == f"{PREFIX}/messages/send"
            if not ok:
                found.append((method, path))
        return found

    def message_id_of(self, raw: bytes) -> str:
        return str(email.message_from_bytes(raw, policy=email.policy.default)["Message-ID"])

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes what was sent (called after the answer is decided, before it is sent)."""
        method, path, query = entry["method"], entry["path"], entry["query"]
        if method == "GET" and path == f"{PREFIX}/profile":
            return 200, {"emailAddress": self.profile_address}, {}, None
        if method == "GET" and path == f"{PREFIX}/messages":
            if self.fail_search_next:
                status, self.fail_search_next = self.fail_search_next, None
                return status, {"error": {"code": status, "message": "stand-in failure"}}, {}, None
            wanted = query.get("q", "")
            hits = [{"id": m["id"]} for m in self.sent if f"rfc822msgid:{m['search_id'].strip('<>')}" in wanted and "in:sent" in wanted]
            return 200, ({"messages": hits} if hits else {"resultSizeEstimate": 0}), {}, None
        if method == "GET" and path.startswith(f"{PREFIX}/messages/") and path != f"{PREFIX}/messages/send":
            ident = path[len(f"{PREFIX}/messages/"):]
            found = next((m for m in self.sent if m["id"] == ident), None)
            if found is None:
                return 404, {"error": {"code": 404, "message": "Not Found"}}, {}, None
            return 200, {"id": found["id"], "labelIds": found["labelIds"], "payload": {"headers": [{"name": "Message-ID", "value": found["held_id"]}]}}, {}, None
        if method == "POST" and path == f"{PREFIX}/messages/send":
            if self.refuse_next:
                status, reason = self.refuse_next
                self.refuse_next = None
                return status, {"error": {"code": status, "message": reason, "errors": [{"reason": reason}]}}, ({"Retry-After": "30"} if status in (429, 503) else {}), None
            self.counter += 1
            ident = f"18f{self.counter:013d}"
            raw = base64.urlsafe_b64decode(entry["body"]["raw"].encode("ascii"))
            wire_id = self.message_id_of(raw)
            held = f"<CA+rewritten{self.counter}@mail.gmail.example>" if self.rewrite_message_id else wire_id
            item = {"id": ident, "threadId": entry["body"].get("threadId") or ident, "labelIds": ["SENT"], "raw": raw, "held_id": held, "search_id": held}

            def apply():
                self.sent.append(item)
            status, self.send_status = self.send_status or 200, None
            return status, {"id": ident, "threadId": item["threadId"]}, {}, apply
        return 405, {"error": {"message": "this stand-in takes only the mailer's requests"}}, {}, None

    # --- what a test hands to the mailer -------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "scope": " ".join(PLATFORM_SET), "account": ACCOUNT, "obtained_at": "2026-10-18T09:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self) -> dict:
        return {"MAILER_GMAIL_API_BASE": self.base, "MAILER_GMAIL_TOKEN_URL": self.token_url}

    def calls(self) -> list:
        """Every request after the token POSTs, as (method, path, query, body)."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.requests if r["path"] != "/token"]
