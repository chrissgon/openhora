"""A stand-in for Google Calendar on 127.0.0.1, for the tests of the calendar writer (package W1): the token endpoint, the calendar list, and the events of one
calendar (get, list by a private property, insert, patch with `If-Match`, delete, and the instances of a series: CB-6). It keeps its events in memory, gives each a version (the etag) that moves with
every change, and RECORDS every request (method, path, query, headers that matter, body) so that a test can assert the exact list. A method or a path the writer
should never send is answered 405 and recorded too, and `unexpected()` lists it.

  fake = FakeGoogleCalendar()                 # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                    # a GOOGLE_ACCOUNT_TOKEN value this fake accepts
  fake.env()                                  # the test overrides of the writer (both URLs, set together)
  fake.add_event(id, summary, start, end, **more)   # an event that is already there; returns it
  fake.lose_answer_once = True                # the next write is APPLIED and the connection is closed with no answer (a lost answer)
  fake.refuse_next = (status, reason)         # the next write is answered with that status and changes nothing
  fake.redirect_next = True                   # the next write is answered 307 to another address
  fake.fail_get_next = 500                    # the next read is answered with that status
  fake.refresh_scope                          # what a refresh says the token carries (default: the platform's set)

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import datetime
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACCOUNT = "pat@example.com"
CALENDAR = "pat@example.com"
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

EVENTS_PREFIX = f"/calendar/v3/calendars/{urllib.parse.quote(CALENDAR, safe='')}/events"


class FakeGoogleCalendar:
    def __init__(self):
        self.requests: list = []
        self.events: dict = {}
        self.removed: dict = {}
        self.version = 0
        self.counter = 0
        self.refresh_scope = " ".join(PLATFORM_SET)
        self.lose_answer_once = False
        self.refuse_next = None
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
                entry = {"method": self.command, "path": parsed.path, "query": {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()},
                         "body": body, "if_match": self.headers.get("If-Match"), "bearer": self.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}",
                         "raw_body": raw}
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

    def next_etag(self):
        self.version += 1
        return f'"{3181161784712000 + self.version}"'

    def add_event(self, event_id, summary, start, end, **more):
        item = {"id": event_id, "etag": self.next_etag(), "status": "confirmed", "summary": summary, "start": start, "end": end,
                "organizer": {"email": ACCOUNT, "self": True}}
        item.update(more)
        self.events[event_id] = item
        return item

    def unexpected(self):
        """The requests that are not one of the writer's allow-list (a method or a path it should never send)."""
        allowed = []
        for entry in self.requests:
            path, method = entry["path"], entry["method"]
            ok = path == "/token" and method == "POST" or path == "/calendar/v3/users/me/calendarList" and method == "GET" or \
                path == EVENTS_PREFIX and method in ("GET", "POST") or \
                path.startswith(EVENTS_PREFIX + "/") and "/" not in path[len(EVENTS_PREFIX) + 1:] and method in ("GET", "PATCH", "DELETE") or \
                path.startswith(EVENTS_PREFIX + "/") and path.endswith("/instances") and "/" not in path[len(EVENTS_PREFIX) + 1:-len("/instances")] and method == "GET"
            if not ok:
                allowed.append((method, path))
        return allowed

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes the events (called after the answer is decided, before it is sent)."""
        method, path, query = entry["method"], entry["path"], entry["query"]
        if path == "/calendar/v3/users/me/calendarList" and method == "GET":
            return 200, {"items": [{"id": CALENDAR}]}, {}, None
        if path == EVENTS_PREFIX and method == "GET":
            wanted = query.get("privateExtendedProperty", "")
            name, _, value = wanted.partition("=")
            items = [{"id": e["id"], "etag": e["etag"]} for e in self.events.values()
                     if not wanted or ((e.get("extendedProperties") or {}).get("private") or {}).get(name) == value]
            return 200, {"items": items}, {}, None
        if method in ("POST", "PATCH", "DELETE") and self.refuse_next:
            status, reason = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": status, "message": reason, "errors": [{"reason": reason}]}}, ({"Retry-After": "30"} if status in (429, 503) else {}), None
        if path == EVENTS_PREFIX and method == "POST":
            self.counter += 1
            new_id = f"ev{self.counter:04d}"
            item = dict(entry["body"], id=new_id, status="confirmed", organizer={"email": ACCOUNT, "self": True})
            item["etag"] = self.next_etag()

            def apply():
                self.events[new_id] = item
            return 200, {"id": new_id, "etag": item["etag"], "status": "confirmed"}, {}, apply
        if path.startswith(EVENTS_PREFIX + "/") and path.endswith("/instances") and "/" not in path[len(EVENTS_PREFIX) + 1:-len("/instances")] and method == "GET":
            master = urllib.parse.unquote(path[len(EVENTS_PREFIX) + 1:-len("/instances")])
            if master not in self.events or not self.events[master].get("recurrence"):
                return 404, {"error": {"code": 404, "message": "Not Found"}}, {}, None
            return 200, {"items": self.instances_of(master, query)[:int(query.get("maxResults") or 250)]}, {}, None
        if path.startswith(EVENTS_PREFIX + "/") and "/" not in path[len(EVENTS_PREFIX) + 1:]:
            event_id = urllib.parse.unquote(path[len(EVENTS_PREFIX) + 1:])
            item = self.events.get(event_id)
            if method == "GET":
                if event_id in self.removed:
                    return 200, dict(self.removed[event_id], status="cancelled"), {}, None
                return (200, item, {}, None) if item else (404, {"error": {"code": 404, "message": "Not Found"}}, {}, None)
            if item is None:
                return 404, {"error": {"code": 404, "message": "Not Found"}}, {}, None
            if entry["if_match"] != item["etag"]:
                return 412, {"error": {"code": 412, "message": "Precondition Failed", "errors": [{"reason": "conditionNotMet"}]}}, {}, None
            if method == "PATCH":
                def apply():
                    for key, value in entry["body"].items():
                        if isinstance(value, dict) and isinstance(item.get(key), dict):
                            for k, v in value.items():
                                if v is None:
                                    item[key].pop(k, None)
                                else:
                                    item[key][k] = v
                        else:
                            item[key] = value
                    item["etag"] = self.next_etag()
                return 200, {"id": event_id, "etag": "(new)", "status": "confirmed"}, {}, apply
            if method == "DELETE":
                def apply():
                    self.removed[event_id] = self.events.pop(event_id)
                    for other in [i for i, e in self.events.items() if e.get("recurringEventId") == event_id]:      # the series goes with its master: every instance
                        self.removed[other] = self.events.pop(other)
                return 204, None, {}, apply
        return 405, {"error": {"message": "this stand-in takes only the writer's requests"}}, {}, None

    def instances_of(self, master, query):
        """The instances of a series that meet the window: `timeMin` filters on the end, `timeMax` is exclusive on the start; a cancelled one only with showDeleted."""
        def at(text):
            return datetime.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        low, high = at(query["timeMin"]), at(query["timeMax"])
        found = []
        for item in self.events.values():
            if item.get("recurringEventId") != master or (item.get("status") == "cancelled" and query.get("showDeleted") != "true"):
                continue
            if at(item["start"]["dateTime"]) < high and at(item["end"]["dateTime"]) > low:
                found.append(item)
        return sorted(found, key=lambda e: at(e["start"]["dateTime"]))

    def add_series(self, master_id, summary, first_start, first_end, rule="RRULE:FREQ=DAILY", days=3, zone="America/Sao_Paulo", **more):
        """A series that is already there: its master (carrying `recurrence`) and `days` instances one day apart from the first; returns (master, [instances])."""
        master = self.add_event(master_id, summary, {"dateTime": first_start, "timeZone": zone}, {"dateTime": first_end, "timeZone": zone}, recurrence=[rule], **more)
        step = datetime.timedelta(days=7 if "WEEKLY" in rule else 1)
        instances = []
        for n in range(days):
            def shift(text):
                moved = datetime.datetime.fromisoformat(text) + step * n
                return moved.isoformat()
            instances.append(self.add_event(f"{master_id}_{n}", summary, {"dateTime": shift(first_start)}, {"dateTime": shift(first_end)}, recurringEventId=master_id,
                                            originalStartTime={"dateTime": shift(first_start)}, **{k: v for k, v in more.items() if k != "recurrence"}))
        return master, instances

    # --- what a test hands to the writer -------------------------------------------------------------------------------------------

    def record_json(self, **over) -> str:
        record = {"slot": "main", "refresh_token": REFRESH_TOKEN, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "scope": " ".join(PLATFORM_SET), "account": ACCOUNT, "obtained_at": "2026-10-18T09:00:00Z"}
        record.update(over)
        return json.dumps({k: v for k, v in record.items() if v is not None})

    def env(self) -> dict:
        return {"WRITER_CALENDAR_GOOGLE_API_BASE": self.base, "WRITER_CALENDAR_GOOGLE_TOKEN_URL": self.token_url}

    def writes(self) -> list:
        """The requests that are not reads: [(method, path, query, body)]."""
        return [(r["method"], r["path"], r["query"], r["body"]) for r in self.requests if r["method"] not in ("GET",) and r["path"] != "/token"]
