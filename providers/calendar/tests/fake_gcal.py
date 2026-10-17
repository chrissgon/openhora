"""A stand-in for the Google Calendar API and the Google token endpoint on 127.0.0.1, for the offline tests of
providers/calendar/google.py and google_auth.py. Not a test file, and never a copy of the live service: it serves exactly the two
calls the provider's docstring names (calendarList list, events list), keeps a few fictional calendars in memory, and refuses what the
reference says the service refuses (a missing or wrong bearer token, a timeMin or timeMax without a time zone offset, orderBy=startTime
without singleEvents=true, a calendar the account does not hold). No real account, key or event is ever involved: the credentials of a
test are made-up strings and every address is a `.example` one.

The fake returns the WHOLE event, on purpose: the description, the full attendee list with addresses and the conference link are
all there, so that a test can show that the provider's output holds none of them (it asks for a `fields` mask and reads only what it
renders; the fake ignores the mask and the provider must not depend on it).

What it records, for the assertions: `requests` (method, raw path as sent, query, whether a bearer token came), `token_forms` (every
form posted to the token endpoint) and `methods` (every HTTP method the API saw: the provider must send GET only).

Usage (from a test):
  fake = fake_gcal.FakeGoogleCalendar()      # starts on a free loopback port in a daemon thread
  fake.env()                                 # what the provider's process needs, the authorization record included
  fake.add_calendar("primary-id@example.com", "Personal", primary=True)
  fake.add_event(cal, fake_gcal.event("e1", "Dentist", "2026-10-17T09:00:00-03:00", "2026-10-17T10:00:00-03:00"))
  fake.close()
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
BOTH_SCOPES = f"{EVENTS_SCOPE} {LIST_SCOPE}"
CLIENT_ID = "123456789012-fakeclientid.apps.example"
CLIENT_SECRET = "fake-client-secret-not-real"
REFRESH_TOKEN = "fake-refresh-token-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
CODE = "fake-authorization-code"
ACCOUNT = "alex.sample@example.com"
RFC3339 = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def event(ident, summary, start, end, **more):
    """A Google-shaped event. `start` and `end` are RFC 3339 date-times, or `YYYY-MM-DD` for an all-day event. Anything in `more`
    (location, status, organizer, attendees, description, hangoutLink, conferenceData, recurringEventId, ...) is added as it is."""
    def moment(value):
        return {"date": value} if len(value) == 10 else {"dateTime": value, "timeZone": "America/Sao_Paulo"}
    out = {"kind": "calendar#event", "etag": f"\"etag-{ident}\"", "id": ident, "status": "confirmed", "summary": summary,
           "start": moment(start), "end": moment(end),
           "organizer": {"email": ACCOUNT, "self": True},
           "description": "PRIVATE-DESCRIPTION-NOT-FOR-A-RUN: call back on +00 000 000 000"}
    out.update(more)
    return out


def instant(moment):
    """A moment of an event or a query as an aware datetime (a date means midnight UTC); a missing one is the far future."""
    if not moment:
        return datetime.max.replace(tzinfo=timezone.utc)
    if "date" in moment:
        return datetime.fromisoformat(moment["date"]).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(moment["dateTime"].replace("Z", "+00:00"))


class FakeGoogleCalendar:
    def __init__(self):
        self.calendars = {}                  # id -> {"summary", "primary", "accessRole", "events": [...]}
        self.requests, self.token_forms, self.methods = [], [], []
        self.scope_granted = BOTH_SCOPES     # what the token endpoint says it granted
        self.omit_scope = False              # answer a token with no scope field at all
        self.token_status = 200              # set 400 and token_error to answer an OAuth error
        self.token_error = {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
        self.code = CODE
        self.expected_challenge = None       # when set, the code is exchanged only with the verifier of this S256 challenge
        self.redirect_next = False
        self.fail_next = None                # (status, body dict, headers) answered once to the next API call
        self.fail_always = None              # the same, to every API call
        self.page_cap = None                 # a page never holds more than this many items, whatever maxResults says
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _json(self, status, obj, headers=None):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status, reason, message, headers=None):
                self._json(status, {"error": {"code": status, "message": message, "errors": [{"reason": reason, "message": message}]}},
                           headers)

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
                    answer = {"access_token": ACCESS_TOKEN, "expires_in": 3599, "scope": owner.scope_granted, "token_type": "Bearer"}
                    if owner.omit_scope:
                        del answer["scope"]
                    return self._json(200, answer)
                if form.get("grant_type") == "authorization_code":
                    verifier = form.get("code_verifier") or ""
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                    if form.get("code") != owner.code or not verifier or (owner.expected_challenge and challenge != owner.expected_challenge):
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
                    failure, owner.fail_next = owner.fail_next or owner.fail_always, None
                if auth != f"Bearer {ACCESS_TOKEN}":
                    return self._error(401, "authError", "Invalid Credentials")
                if failure:
                    return self._error(failure[0], failure[1], f"injected {failure[0]}", failure[2] if len(failure) > 2 else None)
                path = parsed.path
                if path == "/calendar/v3/users/me/calendarList":
                    return self._calendar_list(query)
                match = re.fullmatch(r"/calendar/v3/calendars/([^/]+)/events", path)
                if match:
                    return self._events(urllib.parse.unquote(match.group(1)), query)
                self._error(404, "notFound", "not served")

            def _page(self, items, query, default_size, max_size):
                try:
                    size = int(query.get("maxResults", default_size))
                except ValueError:
                    size = -1
                if not 1 <= size <= max_size:
                    return None, None, False
                if owner.page_cap:
                    size = min(size, owner.page_cap)
                start = int(query["pageToken"][1:]) if query.get("pageToken", "").startswith("p") else 0
                chunk = items[start:start + size]
                more = start + size < len(items)
                return chunk, (f"p{start + size}" if more else None), True

            def _calendar_list(self, query):
                items = [{"kind": "calendar#calendarListEntry", "id": cid, "summary": c["summary"], "primary": c["primary"],
                          "accessRole": c["accessRole"], "timeZone": "America/Sao_Paulo"}
                         for cid, c in owner.calendars.items()]
                chunk, token, ok = self._page(items, query, 100, 250)
                if not ok:
                    return self._error(400, "badRequest", "maxResults out of range")
                answer = {"kind": "calendar#calendarList", "items": chunk}
                if token:
                    answer["nextPageToken"] = token
                self._json(200, answer)

            def _events(self, cid, query):
                cal = owner.calendars.get(cid)
                if cal is None:
                    return self._error(404, "notFound", "Not Found")
                for key in ("timeMin", "timeMax"):
                    if key in query and not RFC3339.match(query[key]):
                        return self._error(400, "badRequest", f"Bad Request: {key} must be an RFC3339 timestamp with a time zone offset")
                if query.get("orderBy") == "startTime" and query.get("singleEvents") != "true":
                    return self._error(400, "badRequest", "The requested ordering is not available for the particular query.")
                low = datetime.fromisoformat(query["timeMin"].replace("Z", "+00:00")) if "timeMin" in query else None
                high = datetime.fromisoformat(query["timeMax"].replace("Z", "+00:00")) if "timeMax" in query else None
                found = [e for e in cal["events"] if "start" not in e or "end" not in e
                         or ((low is None or instant(e["end"]) > low) and (high is None or instant(e["start"]) < high))]
                if query.get("orderBy") == "startTime":
                    found.sort(key=lambda e: instant(e.get("start")))
                chunk, token, ok = self._page(found, query, 250, 2500)
                if not ok:
                    return self._error(400, "badRequest", "maxResults out of range")
                answer = {"kind": "calendar#events", "summary": cal["summary"], "timeZone": "America/Sao_Paulo", "items": chunk}
                if token:
                    answer["nextPageToken"] = token
                self._json(200, answer)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.token_url = f"{self.base}/token"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def add_calendar(self, cid, summary, primary=False, access_role="owner"):
        self.calendars[cid] = {"summary": summary, "primary": primary, "accessRole": access_role, "events": []}
        return cid

    def add_event(self, cid, ev):
        self.calendars[cid]["events"].append(ev)
        return ev

    def record(self, **over):
        record = {"refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "scope": BOTH_SCOPES,
                  "account": ACCOUNT, "obtained_at": "2026-10-17T08:00:00Z"}
        record.update(over)
        return record

    def record_json(self, **over):
        return json.dumps(self.record(**over))

    def env(self, **over):
        """What the provider's process needs to talk to this fake and find its authorization in the environment."""
        return {"INTEGRATION_CALENDAR_GOOGLE_API_BASE": self.base, "INTEGRATION_CALENDAR_GOOGLE_TOKEN_URL": self.token_url,
                "GOOGLE_CALENDAR_TOKEN": self.record_json(**over)}

    def api_requests(self):
        return [r for r in self.requests if r[1].startswith("/calendar/")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
