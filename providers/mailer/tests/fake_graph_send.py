"""A stand-in for Microsoft on 127.0.0.1, for the tests of the Outlook mailer (providers/mailer/outlook.py; package W2): the Microsoft identity token endpoint (a public
client, a new refresh token on every refresh, the old one left valid), `GET /me`, the drafts of the mailbox (create, create a reply in the conversation, update),
`send`, `move` to Deleted Items and the search of Sent Items by internetMessageId. It keeps drafts, sent items and deleted items in memory, gives every draft the
internetMessageId a service would, and RECORDS every request (method, path, query, headers that matter, body) so that a test can assert the exact list. A method or a
path the mailer should never send (a DELETE above all) is answered 405 and recorded too, and `unexpected()` lists it.

  fake = FakeGraphSend()                      # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                    # a MICROSOFT_ACCOUNT_TOKEN value this fake accepts
  fake.env()                                  # the test overrides of the mailer (both URLs, set together)
  fake.add_message(id, from_address, subject, reply_to=None)   # a message of the inbox that a reply may answer; returns it
  fake.lose_answer_once = True                # the next send is APPLIED (the message goes to Sent Items) and the connection is closed with no answer
  fake.refuse_next = (kind, status)           # the next request of that kind ("create", "createReply", "patch", "send", "move") is answered with that status, changes nothing
  fake.redirect_next = True                   # the next send is answered 307 to another address
  fake.fail_get_next = 500                    # the next read is answered with that status
  fake.send_status = 201                      # the next send is applied and answered with that 2xx instead of 202
  fake.claim_attachments = True               # a draft is answered with hasAttachments true although it holds none
  fake.body_as_html = True                    # a draft's body is answered as html (the service did not keep plain text)
  fake.ignore_recipients = True               # an update leaves the recipients as they were (the draft is then not the approved message)
  fake.reply_to_reply_to = True               # createReply addresses the draft to the message's Reply-To instead of its sender
  fake.address, fake.principal                # what GET /me names as `mail` and `userPrincipalName`
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
PRINCIPAL = "casey.rivera@work.example"
CLIENT_ID = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
TENANT = "common"
REFRESH_TOKEN = "fake-refresh-token-0-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
SECRETS = (REFRESH_TOKEN, ACCESS_TOKEN)
PLATFORM = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
PREFIX = "https://graph.microsoft.com/"
GRANTED = " ".join(PREFIX + name for name in PLATFORM) + " offline_access openid profile"
GRAPH = "/v1.0"


def recipient(address):
    return {"emailAddress": {"address": address}}


class FakeGraphSend:
    def __init__(self):
        self.requests: list = []
        self.token_forms: list = []
        self.messages: dict = {}
        self.drafts: dict = {}
        self.sent: list = []
        self.deleted: list = []
        self.counter = 0
        self.rotations = 0
        self.valid_refresh = {REFRESH_TOKEN}
        self.scope_granted = GRANTED
        self.address, self.principal = ADDRESS, PRINCIPAL
        self.lose_answer_once = False
        self.refuse_next = None
        self.redirect_next = False
        self.fail_get_next = None
        self.body_as_html = False
        self.send_status = None
        self.claim_attachments = False
        self.ignore_recipients = False
        self.reply_to_reply_to = False
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
                    owner.requests.append({"method": "POST", "path": "/token", "raw_path": "/token", "query": {}, "body": form, "prefer": None, "bearer": False})
                    return self._send(*owner.token(form))
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = {"unreadable": True}
                entry = {"method": self.command, "path": urllib.parse.unquote(parsed.path), "raw_path": parsed.path,
                         "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}, "body": body, "prefer": self.headers.get("Prefer"),
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"}
                owner.requests.append(entry)
                if not entry["bearer"]:
                    return self._send(401, {"error": {"code": "InvalidAuthenticationToken", "message": "Access token is empty or invalid."}})
                if entry["path"].endswith("/send") and owner.redirect_next:
                    owner.redirect_next = False
                    return self._send(307, None, {"Location": "http://127.0.0.1:1/elsewhere"})
                if self.command == "GET" and owner.fail_get_next:
                    status, owner.fail_get_next = owner.fail_get_next, None
                    return self._send(status, {"error": {"code": "generalException", "message": "stand-in failure"}})
                status, answer, headers, apply = owner.api(entry)
                if status == 405:
                    return self._send(405, answer)
                if entry["path"].endswith("/send") and owner.lose_answer_once and apply:
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
            fresh = f"fake-refresh-token-{self.rotations}-not-real"
            self.valid_refresh.add(fresh)
            return 200, {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer", "scope": self.scope_granted, "refresh_token": fresh}
        return 400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad refresh token"}

    def add_message(self, ident, from_address, subject, reply_to=None):
        item = {"id": ident, "from": from_address, "subject": subject, "reply_to": reply_to}
        self.messages[ident] = item
        return item

    def unexpected(self):
        """The requests that are not one of the mailer's allow-list (a method or a path it should never send)."""
        allowed = (("POST", r"/token"), ("GET", GRAPH + r"/me"), ("GET", GRAPH + r"/me/mailFolders/sentitems/messages"), ("POST", GRAPH + r"/me/messages"),
                   ("PATCH", GRAPH + r"/me/messages/[^/]+"), ("POST", GRAPH + r"/me/messages/[^/]+/(send|move|createReply)"))
        return [(e["method"], e["path"]) for e in self.requests if not any(e["method"] == m and re.fullmatch(p, e["path"]) for m, p in allowed)]

    def view(self, draft):
        """A draft as Graph prints it."""
        body = {"contentType": "html" if self.body_as_html else "text", "content": draft["body_content"] if not self.body_as_html else f"<html><body>{draft['body_content']}</body></html>"}
        return {"id": draft["id"], "internetMessageId": draft["internetMessageId"], "subject": draft["subject"], "body": body,
                "toRecipients": [recipient(a) for a in draft["to"]], "ccRecipients": [recipient(a) for a in draft["cc"]],
                "bccRecipients": [recipient(a) for a in draft["bcc"]], "hasAttachments": bool(draft["attachments"]) or self.claim_attachments, "isDraft": True}

    def next_id(self, prefix):
        self.counter += 1
        return f"{prefix}{self.counter:04d}="

    def refused(self, kind):
        if self.refuse_next and self.refuse_next[0] == kind:
            _, status = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": "ErrorRefused", "message": "stand-in refusal"}}, ({"Retry-After": "30"} if status in (429, 503) else {}), None
        return None

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes the mailbox (called after the answer is decided, before it is sent)."""
        method, path, query, body = entry["method"], entry["path"], entry["query"], entry["body"]
        rest = path[len(GRAPH):] if path.startswith(GRAPH + "/") else ""
        if method == "GET" and rest == "/me":
            answer = {"displayName": "Casey Rivera"}
            if self.address:
                answer["mail"] = self.address
            if self.principal:
                answer["userPrincipalName"] = self.principal
            return 200, answer, {}, None
        if method == "GET" and rest == "/me/mailFolders/sentitems/messages":
            wanted = query.get("$filter", "")
            hits = [{"id": m["id"], "internetMessageId": m["internetMessageId"]} for m in self.sent if f"internetMessageId eq '{m['internetMessageId']}'" in wanted]
            return 200, {"value": hits}, {}, None
        if method == "POST" and rest == "/me/messages":
            refused = self.refused("create")
            if refused:
                return refused
            ident = self.next_id("AAMkDraft")
            draft = {"id": ident, "internetMessageId": f"<AM{self.counter:04d}@draft.graph.example>", "subject": body.get("subject"),
                     "body_content": (body.get("body") or {}).get("content", ""), "to": [r["emailAddress"]["address"] for r in body.get("toRecipients", [])],
                     "cc": [r["emailAddress"]["address"] for r in body.get("ccRecipients", [])], "bcc": [r["emailAddress"]["address"] for r in body.get("bccRecipients", [])],
                     "attachments": body.get("attachments") or []}

            def apply():
                self.drafts[ident] = draft
            return 201, self.view(draft), {}, apply
        parts = rest.split("/")      # ["", "me", "messages", "<id>", "<verb>"]
        if len(parts) >= 4 and parts[1:3] == ["me", "messages"]:
            ident = parts[3]
            verb = parts[4] if len(parts) > 4 else None
            if method == "POST" and verb == "createReply":
                refused = self.refused("createReply")
                if refused:
                    return refused
                original = self.messages.get(ident)
                if original is None:
                    return 404, {"error": {"code": "ErrorItemNotFound", "message": "not found"}}, {}, None
                new_id = self.next_id("AAMkReply")
                to = original["reply_to"] if self.reply_to_reply_to and original["reply_to"] else original["from"]
                draft = {"id": new_id, "internetMessageId": f"<AM{self.counter:04d}@draft.graph.example>", "subject": "RE: " + original["subject"],
                         "body_content": "<quoted original>", "to": [to], "cc": [], "bcc": [], "attachments": []}

                def apply():
                    self.drafts[new_id] = draft
                return 201, self.view(draft), {}, apply
            draft = self.drafts.get(ident)
            if method == "PATCH" and verb is None:
                refused = self.refused("patch")
                if refused:
                    return refused
                if draft is None:
                    return 404, {"error": {"code": "ErrorItemNotFound", "message": "not found"}}, {}, None

                def apply():
                    if "subject" in body:
                        draft["subject"] = body["subject"]
                    if "body" in body:
                        draft["body_content"] = body["body"]["content"]
                    if not self.ignore_recipients:
                        for key, field in (("toRecipients", "to"), ("ccRecipients", "cc"), ("bccRecipients", "bcc")):
                            if key in body:
                                draft[field] = [r["emailAddress"]["address"] for r in body[key]]
                    return self.view(draft)
                return 200, self.view(draft), {}, apply
            if method == "POST" and verb == "send":
                refused = self.refused("send")
                if refused:
                    return refused
                if draft is None:
                    return 404, {"error": {"code": "ErrorItemNotFound", "message": "not found"}}, {}, None

                def apply():
                    self.sent.append(dict(self.drafts.pop(ident), id=self.next_id("AAMkSent"), draft_id=ident))
                status, self.send_status = self.send_status or 202, None
                return status, None, {}, apply
            if method == "POST" and verb == "move":
                refused = self.refused("move")
                if refused:
                    return refused
                if draft is None:
                    return 404, {"error": {"code": "ErrorItemNotFound", "message": "not found"}}, {}, None
                if (body or {}).get("destinationId") != "deleteditems":
                    return 400, {"error": {"code": "ErrorInvalidIdMalformed", "message": "this stand-in moves to Deleted Items only"}}, {}, None

                def apply():
                    self.deleted.append(self.drafts.pop(ident))
                return 201, {"id": ident + "moved"}, {}, apply
        return 405, {"error": {"code": "methodNotAllowed", "message": "this stand-in takes only the mailer's requests"}}, {}, None

    # --- what a test hands to the mailer -------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "tenant": TENANT, "scope": " ".join(PLATFORM),
                  "account_kind": "personal", "account": ADDRESS, "obtained_at": "2026-10-18T08:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self) -> dict:
        return {"MAILER_OUTLOOK_API_BASE": self.base, "MAILER_OUTLOOK_TOKEN_URL": self.token_url}

    def calls(self) -> list:
        """Every request after the token POSTs, as (method, path, query, body)."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.requests if r["path"] != "/token"]
