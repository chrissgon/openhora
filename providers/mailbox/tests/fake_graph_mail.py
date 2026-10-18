"""A stand-in for the mail side of Microsoft Graph (and the Microsoft identity token endpoint), on 127.0.0.1, for the offline tests of
providers/mailbox/outlook.py and outlook_auth.py. Not a test file, and never a copy of the live service: it serves exactly the calls the
provider's docstring names, keeps a few fictional messages in memory, and refuses what the reference says the service refuses (a missing or
wrong bearer token, an unknown message, a `$filter` that does not list the `$orderby` property first). Every address is on a `.example`
domain and every credential is a made-up string.

Usage (from a test):
  fake = FakeGraphMail()                    # starts on a free loopback port in a daemon thread
  fake.base, fake.token_url                 what the provider's environment names
  fake.record_json()                        an OUTLOOK_MAIL_TOKEN value that this fake accepts
  fake.add("m1", "2026-10-17T07:12:03Z", "Ana Lima", "ana@clinic.example", "Appointment confirmed", html="<p>Hello</p>")
  fake.link_base = "https://evil.example"   # the next-page address names another host
  fake.close()
"""
from __future__ import annotations

import urllib.parse

import fake_microsoft
from fake_microsoft import ACCESS_TOKEN, REFRESH_TOKEN, CODE, TENANT  # noqa: F401  (re-exported for the tests)

CLIENT_ID = fake_microsoft.FakeMicrosoft.CLIENT_ID
SCOPE = "Mail.Read"
MESSAGE_PREFIX = "/me/messages/"
INBOX = "/me/mailFolders/inbox/messages"
FIELDS = ("id", "conversationId", "changeKey", "receivedDateTime", "sentDateTime", "from", "toRecipients", "subject", "body",
          "hasAttachments", "internetMessageId", "internetMessageHeaders", "isRead", "bodyPreview", "ccRecipients")


def recipient(name, address):
    return {"emailAddress": {"name": name, "address": address}}


class FakeGraphMail(fake_microsoft.FakeMicrosoft):
    SCOPE = SCOPE

    def __init__(self):
        self.messages = {}                  # id -> dict (Graph shaped, plus "_attachments")
        self.link_base = None               # the base of every @odata.nextLink; default: this listener
        self.link_path = None               # the path of every @odata.nextLink; default: the request's own
        self.page_cap = None                # at most this many messages in a page, whatever $top says
        self.attachments_status = 200       # what the attachments listing answers
        super().__init__()

    # --- what a test sets up -----------------------------------------------------------------------------------------------------

    def add(self, mid, received, sender_name, sender_address, subject, html=None, text=None, to=(("Sam Sample", "sam@mail.example"),),
            unread=False, attachments=None, headers=None, change_key=None, sent=None, thread="conv-1", message_id=None):
        """A fictional message. `html` or `text` is the body (an HTML one by default); `attachments` is a list of (name, type, size, bytes)."""
        body = {"contentType": "html", "content": html} if html is not None else {"contentType": "text", "content": text or ""}
        self.messages[mid] = {
            "id": mid, "conversationId": thread, "changeKey": change_key or f"CK-{mid}", "receivedDateTime": received,
            "sentDateTime": sent or received, "from": recipient(sender_name, sender_address),
            "toRecipients": [recipient(n, a) for n, a in to], "subject": subject, "body": body,
            "hasAttachments": bool(attachments), "internetMessageId": message_id or f"<{mid}@mail.example>", "isRead": not unread,
            "internetMessageHeaders": [{"name": k, "value": v} for k, v in (headers or {}).items()],
            "bodyPreview": "a preview", "ccRecipients": [], "_attachments": list(attachments or [])}
        return mid

    # --- the Graph calls ---------------------------------------------------------------------------------------------------------

    def shown(self, message, select):
        full = {k: v for k, v in message.items() if k != "_attachments"}
        if select:
            wanted = {"id", *select.split(",")}
            full = {k: v for k, v in full.items() if k in wanted}
        else:
            full.pop("internetMessageHeaders", None)
        return full

    def route(self, handler, rest, query):
        if rest == INBOX:
            return self.listing(handler, rest, query)
        if rest.startswith(MESSAGE_PREFIX):
            parts = rest[len(MESSAGE_PREFIX):].split("/")
            message = self.messages.get(parts[0])
            if message is None:
                return handler.error(404, "ErrorItemNotFound", "The specified object was not found in the store.")
            if len(parts) == 1:
                return handler.json(200, self.shown(message, query.get("$select")))
            if parts[1:] == ["attachments"]:
                return self.attachments(handler, message, query)
        handler.error(404, "notFound", "not served")

    def listing(self, handler, rest, query):
        orderby = query.get("$orderby", "")
        clauses = [c.strip() for c in query.get("$filter", "").split(" and ") if c.strip()]
        if orderby and (not clauses or not clauses[0].startswith(orderby.split()[0])):
            return handler.error(400, "InefficientFilter", "The restriction or sort order is too complex for this operation.")
        found = list(self.messages.values())
        for clause in clauses:
            property_, operator, value = clause.split(" ", 2)
            if property_ == "receivedDateTime" and operator in ("ge", "lt"):
                found = [m for m in found if (m["receivedDateTime"] >= value if operator == "ge" else m["receivedDateTime"] < value)]
            elif clause == "isRead eq false":
                found = [m for m in found if not m["isRead"]]
            else:
                return handler.error(400, "ErrorInvalidProperty", "the filter is not served")
        found.sort(key=lambda m: m["receivedDateTime"], reverse=orderby.endswith("desc"))
        top = int(query.get("$top", "10"))
        if self.page_cap:
            top = min(top, self.page_cap)
        skip = int(query.get("$skip", "0"))
        page = found[skip:skip + top]
        out = {"value": [self.shown(m, query.get("$select")) for m in page]}
        if skip + top < len(found):
            following = {**query, "$skip": str(skip + top)}
            out["@odata.nextLink"] = f"{self.link_base or self.root}{self.link_path or '/v1.0' + rest}?" + urllib.parse.urlencode(following)
        handler.json(200, out)

    def attachments(self, handler, message, query):
        if self.attachments_status != 200:
            return handler.error(self.attachments_status, "ErrorAccessDenied", "Access is denied.")
        select = query.get("$select")
        listed = []
        for index, (name, ctype, size, data) in enumerate(message["_attachments"]):
            full = {"@odata.type": "#microsoft.graph.fileAttachment", "id": f"att-{index}", "name": name, "contentType": ctype, "size": size,
                    "isInline": False, "contentBytes": data}
            if select:
                wanted = {"id", *select.split(",")}
                full = {k: v for k, v in full.items() if k in wanted}
            listed.append(full)
        handler.json(200, {"value": listed})

    # --- what a test reads -------------------------------------------------------------------------------------------------------

    def env(self, **over):
        """What the provider's process needs to talk to this fake and find its authorization in the environment."""
        return {"MAILBOX_OUTLOOK_API_BASE": self.base, "MAILBOX_OUTLOOK_TOKEN_URL": self.token_url, "OUTLOOK_MAIL_TOKEN": self.record_json(**over)}
