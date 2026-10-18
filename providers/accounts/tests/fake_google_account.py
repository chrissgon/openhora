"""A stand-in for Google on 127.0.0.1, for the tests of the account token (package ACCT-G): the token endpoint (the authorization code and the
refresh), the Gmail profile and messages, the Calendar list and events, and the Drive file and its export, all read only. It records every
request (method, path, query, body, whether it carried the bearer token) so that a test can assert the exact list, and it answers 405 to any
method other than GET (and the token POST), so a provider that wrote would be seen.

  fake = FakeGoogleAccount()                 # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                   # a GOOGLE_ACCOUNT_TOKEN value this fake accepts
  fake.gmail_env(), calendar_env(), drive_env(), auth_env()    # the test overrides of each script (both URLs, set together)
  fake.legacy_gmail_env(), legacy_calendar_env(), legacy_drive_env()   # the old records the three readers still read for one cycle
  fake.refresh_scope = None                  # the refresh response omits `scope`; a string replaces it; "auto" (default) is what the token's
                                             # consent was: the platform set for the account record, each legacy scope for its legacy one
  fake.consent_scope                         # what an authorization code grants (a string, or None to omit)
  fake.expected_challenge                    # when set, the code exchange must present a verifier that hashes to it (S256)

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.parse
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCOUNT = "pat@example.com"
CLIENT_ID = "stand-in-client-id.example"
CLIENT_SECRET = "fake-client-secret-not-real-4f2a"
REFRESH_TOKEN = "fake-refresh-token-not-real-9b1c"
ACCESS_TOKEN = "fake-access-token-not-real-7d3e"
CODE = "fake-code-not-real-5a6f"
LEGACY_GMAIL_REFRESH = "fake-legacy-gmail-refresh-not-real-2c8d"
LEGACY_CALENDAR_REFRESH = "fake-legacy-calendar-refresh-not-real-3e9a"
LEGACY_DRIVE_REFRESH = "fake-legacy-drive-refresh-not-real-6b0f"
SECRETS = (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN, CODE, LEGACY_GMAIL_REFRESH, LEGACY_CALENDAR_REFRESH, LEGACY_DRIVE_REFRESH)

GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
CALENDAR_EVENTS = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
DRIVE = "https://www.googleapis.com/auth/drive"
PLATFORM_SET = (GMAIL_MODIFY, CALENDAR_EVENTS, CALENDAR_LIST, DRIVE)
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_EVENTS_READONLY = "https://www.googleapis.com/auth/calendar.events.readonly"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
MAIL_ALL = "https://mail.google.com/"

DOC_ID = "1AbCdEfGhIjKlMnOp"
DOC_TEXT = "# Weekly notes\n\nThe stand-in text of a document.\n"
DOC_MODIFIED = "2026-10-17T09:00:00.000Z"
EVENT_START, EVENT_END = "2026-10-20T13:00:00-03:00", "2026-10-20T14:00:00-03:00"

# The scope a refresh token was granted, when the fake answers a refresh with "auto": the account token carries the platform's set, a legacy
# record only what its own authorization asked.
GRANTED = {REFRESH_TOKEN: " ".join(PLATFORM_SET), LEGACY_GMAIL_REFRESH: GMAIL_READONLY,
           LEGACY_CALENDAR_REFRESH: f"{CALENDAR_EVENTS_READONLY} {CALENDAR_LIST}", LEGACY_DRIVE_REFRESH: DRIVE_FILE}


def raw_message() -> str:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "Sam <sam@example.org>", ACCOUNT, "Lunch on Friday"
    msg["Message-ID"], msg["Date"] = "<m1@example.org>", "Mon, 19 Oct 2026 10:00:00 +0000"
    msg.set_content("Are you free for lunch on Friday?\n")
    return base64.urlsafe_b64encode(bytes(msg)).decode()


class FakeGoogleAccount:
    def __init__(self):
        self.requests: list = []
        self.consent_scope = " ".join(PLATFORM_SET)
        self.refresh_scope = "auto"
        self.expected_challenge = None
        self.token_error = None
        self.redirect_token = False      # the token endpoint answers 302 to another address
        self.calendar_id = ACCOUNT
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, body, content_type="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _record(self, body=b""):
                parsed = urllib.parse.urlparse(self.path)
                entry = {"method": self.command, "path": parsed.path, "query": urllib.parse.parse_qs(parsed.query), "body": body,
                         "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"}
                owner.requests.append(entry)
                return entry

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                entry = self._record(body)
                if entry["path"] == "/token" and owner.redirect_token:
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if entry["path"] == "/token":
                    return self._send(*owner.token(urllib.parse.parse_qs(body.decode())))
                self._send(405, {"error": {"message": "this stand-in takes only the token POST"}})

            def do_GET(self):  # noqa: N802
                entry = self._record()
                if not entry["bearer"]:
                    return self._send(401, {"error": {"status": "UNAUTHENTICATED", "message": "no bearer token"}})
                self._send(*owner.api(entry["path"], entry["query"]))

            def _refuse(self):
                self._record(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                self._send(405, {"error": {"message": "this stand-in is read only"}})

            do_PUT = do_PATCH = do_DELETE = _refuse   # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.token_url = f"{self.base}/token"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # --- the services -----------------------------------------------------------------------------------------------------------

    def token(self, form):
        first = lambda key: (form.get(key) or [""])[0]   # noqa: E731
        if self.token_error:
            return 400, {"error": self.token_error, "error_description": "stand-in refusal"}
        if first("client_id") != CLIENT_ID or first("client_secret") != CLIENT_SECRET:
            return 401, {"error": "invalid_client", "error_description": "stand-in: unknown client"}
        grant = first("grant_type")
        if grant == "authorization_code":
            verifier = first("code_verifier")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if first("code") != CODE or (self.expected_challenge and challenge != self.expected_challenge):
                return 400, {"error": "invalid_grant", "error_description": "bad code or verifier"}
            answer = {"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN, "expires_in": 3599, "token_type": "Bearer"}
            if self.consent_scope is not None:
                answer["scope"] = self.consent_scope
            return 200, answer
        if grant == "refresh_token":
            refresh = first("refresh_token")
            if refresh not in GRANTED:
                return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
            answer = {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer"}
            scope = GRANTED[refresh] if self.refresh_scope == "auto" else self.refresh_scope
            if scope is not None:
                answer["scope"] = scope
            return 200, answer
        return 400, {"error": "unsupported_grant_type"}

    def api(self, path, query):
        if path == "/gmail/v1/users/me/profile":
            return 200, {"emailAddress": ACCOUNT, "messagesTotal": 1}
        if path == "/gmail/v1/users/me/messages":
            return 200, {"messages": [{"id": "msg1", "threadId": "thr1"}]}
        if path == "/gmail/v1/users/me/messages/msg1":
            return 200, {"id": "msg1", "threadId": "thr1", "internalDate": "1792404000000", "raw": raw_message()}
        if path == "/calendar/v3/users/me/calendarList":
            return 200, {"items": [{"id": self.calendar_id, "summary": "Personal", "primary": True, "accessRole": "owner"}]}
        if path == f"/calendar/v3/calendars/{urllib.parse.quote(self.calendar_id, safe='')}/events":
            return 200, {"items": [{"id": "ev1", "etag": "\"e1\"", "status": "confirmed", "summary": "Haircut",
                                    "start": {"dateTime": EVENT_START}, "end": {"dateTime": EVENT_END},
                                    "organizer": {"email": ACCOUNT, "self": True}}]}
        if path == f"/drive/v3/files/{DOC_ID}":
            return 200, {"id": DOC_ID, "name": "Weekly notes", "mimeType": "application/vnd.google-apps.document", "version": "3",
                         "modifiedTime": DOC_MODIFIED}
        if path == f"/drive/v3/files/{DOC_ID}/export":
            return 200, DOC_TEXT.encode(), "text/markdown"
        return 404, {"error": {"status": "NOT_FOUND", "message": "stand-in: unknown path"}}

    # --- what a test hands to a script ------------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "scope": " ".join(PLATFORM_SET), "account": ACCOUNT, "obtained_at": "2026-10-18T09:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def legacy_gmail_env(self, **over) -> dict:
        env = {"GMAIL_REFRESH_TOKEN": LEGACY_GMAIL_REFRESH, "GMAIL_CLIENT_ID": CLIENT_ID, "GMAIL_CLIENT_SECRET": CLIENT_SECRET}
        env.update(over)
        return env

    def legacy_calendar_env(self, **over) -> dict:
        record = {"refresh_token": LEGACY_CALENDAR_REFRESH, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "scope": f"{CALENDAR_EVENTS_READONLY} {CALENDAR_LIST}", "account": ACCOUNT, "obtained_at": "2026-10-17T09:00:00Z"}
        record.update(over)
        return {"GOOGLE_CALENDAR_TOKEN": json.dumps(record)}

    def legacy_drive_env(self, **over) -> dict:
        record = {"refresh_token": LEGACY_DRIVE_REFRESH, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "scope": DRIVE_FILE,
                  "obtained_at": "2026-10-16T09:00:00Z"}
        record.update(over)
        return {"GDRIVE_SOURCES_TOKEN": json.dumps(record)}

    def gmail_env(self) -> dict:
        return {"GMAIL_API_BASE": self.base, "GOOGLE_TOKEN_URL": self.token_url}

    def calendar_env(self) -> dict:
        return {"INTEGRATION_CALENDAR_GOOGLE_API_BASE": self.base, "INTEGRATION_CALENDAR_GOOGLE_TOKEN_URL": self.token_url}

    def drive_env(self) -> dict:
        return {"INTEGRATION_DOCUMENTS_GDRIVE_API_BASE": self.base, "INTEGRATION_DOCUMENTS_GDRIVE_TOKEN_URL": self.token_url}

    def auth_env(self) -> dict:
        return {"GOOGLE_ACCOUNT_API_BASE": self.base, "GOOGLE_ACCOUNT_TOKEN_URL": self.token_url}

    # --- what a test asks of the record ------------------------------------------------------------------------------------------------

    def methods(self) -> list:
        return [(r["method"], r["path"]) for r in self.requests]

    def api_requests(self) -> list:
        return [r for r in self.requests if r["path"] != "/token"]
