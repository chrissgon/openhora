"""A stand-in for Microsoft on 127.0.0.1, for the tests of the Outlook calendar writer (package W1): the Microsoft identity token endpoint (a public client, a new
refresh token on every refresh, the old one left valid) and the events of the default calendar and of one named calendar through Graph (get, list with a filter on
the private property, create, patch, and the removal of one event: a 204, the event moved to `removed`; like Graph it takes no If-Match; and, for a series (CB-6), the instances of a master in a window and the
`cancel` action: a 202 that moves the event, or the master and every occurrence, to `removed`, a 400 for an event the person does not organise). It keeps its events in
memory, gives each a changeKey that moves with every change, and RECORDS every request (method, path, query, headers that matter, body) so that a test can assert the
exact list. `unexpected()` lists any request the writer should never send.

  fake = FakeGraphCalendar()                  # starts on a free loopback port in a daemon thread; fake.close() stops it
  fake.record_json(**over)                    # a MICROSOFT_ACCOUNT_TOKEN value this fake accepts
  fake.env()                                  # the test overrides of the writer (both URLs, set together)
  fake.add_event(id, subject, first, last, **more)   # an event that is already there (first and last: UTC times as Graph prints them); returns it.
                                              # `_calendar=<id>` puts it in that calendar (default: the default calendar). Like Graph, an event is found only through the
                                              # path of its own calendar: through another calendar's path it answers 404 (a list of that calendar does not hold it either)
  fake.lose_answer_once = True                # the next write is APPLIED and the connection is closed with no answer
  fake.refuse_next = (status, code)           # the next write is answered with that status and changes nothing
  fake.redirect_next = True                   # the next write is answered 307 to another address
  fake.fail_get_next = 500                    # the next read is answered with that status
  fake.scope_granted                          # what a refresh says the token carries (default: the platform's set and the words that grant nothing)

Every value is a stand-in made up for the tests; none is a credential.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

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
KEY_PROPERTY = "String {c1a7e5d2-9b34-4f68-8a1e-3d5f7b2c9e40} Name openhora_key"
NAMED = "AAMkNamedCalendar_1="


def utc_form(moment: dict) -> dict:
    """A dateTimeTimeZone in an IANA zone as the same instant in UTC (`.0000000` fraction, as Graph prints it); one already in UTC, or in a name this stand-in does not
    know (a Windows name), is returned as it is."""
    zone = moment.get("timeZone")
    if zone in ("UTC", None) or "/" not in zone:
        return moment
    wall = datetime.strptime(moment["dateTime"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZoneInfo(zone))
    return {"dateTime": wall.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".0000000", "timeZone": "UTC"}


class FakeGraphCalendar:
    def __init__(self):
        self.requests: list = []
        self.token_forms: list = []
        self.events: dict = {}
        self.removed: dict = {}      # the events a removal took out of the calendar, by id
        self.cancelled: list = []    # the ids a `cancel` action was answered for, in order
        self.home: dict = {}         # the calendar each event lives in, by id ("default" or a calendar id)
        self.version = 0
        self.counter = 0
        self.rotations = 0
        self.valid_refresh = {REFRESH_TOKEN}
        self.scope_granted = GRANTED
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
                         "prefer": self.headers.get("Prefer"), "if_match": self.headers.get("If-Match"),
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

    def add_series(self, master_id, subject, first, last, pattern=None, days=3, step=1, **more):
        """A series that is already there: its master (`type` seriesMaster, with a `recurrence`) and `days` occurrences `step` days apart from the first (first and last: UTC
        times as Graph prints them); returns (master, [occurrences])."""
        pattern = pattern or {"type": "daily", "interval": 1}
        master = self.add_event(master_id, subject, first, last, type="seriesMaster", recurrence={"pattern": pattern, "range": {"type": "noEnd", "startDate": first[:10]}}, **more)
        occurrences = []
        for n in range(days):
            def shift(text):
                return (datetime.fromisoformat(text) + timedelta(days=step * n)).strftime("%Y-%m-%dT%H:%M:%S")
            occurrences.append(self.add_event(f"{master_id[:-1]}Occ{n}=", subject, shift(first), shift(last), type="occurrence", seriesMasterId=master_id,
                                              originalStart=shift(first) + "Z", **{k: v for k, v in more.items() if k != "recurrence"}))
        return master, occurrences

    def add_event(self, event_id, subject, first, last, **more):
        item = {"id": event_id, "changeKey": self.next_key(), "subject": subject, "start": {"dateTime": first + ".0000000", "timeZone": "UTC"},
                "end": {"dateTime": last + ".0000000", "timeZone": "UTC"}, "isAllDay": False, "location": {"displayName": ""},
                "body": {"contentType": "text", "content": ""}, "isReminderOn": False, "isOrganizer": True, "isCancelled": False, "attendees": [],
                "type": "singleInstance", "singleValueExtendedProperties": []}
        self.home[event_id] = more.pop("_calendar", "default")
        item.update(more)
        self.events[event_id] = item
        return item

    def unexpected(self):
        """The requests that are not one of the writer's allow-list (a method or a path it should never send)."""
        found = []
        for entry in self.requests:
            path, method = entry["path"], entry["method"]
            rest = path[len(GRAPH):] if path.startswith(GRAPH + "/") else path
            ok = (rest == "/me/calendars" and method == "GET"
                  or re.fullmatch(r"/me/calendars?(/[^/]+)?/events", rest) is not None and method in ("GET", "POST") and not rest.startswith("/me/calendars/events")
                  or re.fullmatch(r"/me/calendars?(/[^/]+)?/events/[^/]+", rest) is not None and method in ("GET", "PATCH", "DELETE")
                  or re.fullmatch(r"/me/calendars?(/[^/]+)?/events/[^/]+/instances", rest) is not None and method == "GET"
                  or re.fullmatch(r"/me/calendars?(/[^/]+)?/events/[^/]+/cancel", rest) is not None and method == "POST")
            if not ok:
                found.append((method, path))
        return found

    def scope_of(self, rest):
        """(the id of the events' calendar or "default", the rest of the path after /events) of a path under /me, or None."""
        found = re.fullmatch(r"/me/calendar(?:s/([^/]+))?/events(?:/([^/]+))?", rest)
        return (found.group(1) or "default", found.group(2)) if found else None

    def api(self, entry):
        """(status, answer, headers, apply) where apply() changes the events and may return the answer to send."""
        method, rest = entry["method"], entry["path"][len(GRAPH):]
        if rest == "/me/calendars" and method == "GET":
            return 200, {"value": [{"id": NAMED}]}, {}, None
        action = re.fullmatch(r"/me/calendar(?:s/([^/]+))?/events/([^/]+)/(cancel|instances)", rest)
        if action:
            return self.series_api(entry, method, action.group(1) or "default", urllib.parse.unquote(action.group(2)), action.group(3))
        where = self.scope_of(rest)
        if where is None:
            return 405, {"error": {"code": "methodNotAllowed", "message": "this stand-in serves only the writer's requests"}}, {}, None
        calendar, event_id = where
        if method == "GET" and event_id is None:
            wanted = re.search(r"ep/value eq '([^']*)'", entry["query"].get("$filter", ""))
            items = [e for e in self.events.values() if self.home.get(e["id"], "default") == calendar
                     and (not wanted or any(p["value"] == wanted.group(1) for p in e["singleValueExtendedProperties"]))]
            return 200, {"value": [{"id": e["id"], "changeKey": e["changeKey"]} for e in items]}, {}, None
        if method in ("POST", "PATCH", "DELETE") and self.refuse_next:
            status, code = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": code, "message": f"stand-in refusal {code}"}}, ({"Retry-After": "30"} if status in (429, 503) else {}), None
        if method == "POST" and event_id is None:
            body = entry["body"]

            def apply():
                self.counter += 1
                new_id = f"AAMkEvent{self.counter:04d}="
                item = self.add_event(new_id, body.get("subject", ""), "1970-01-01T00:00:00", "1970-01-01T00:00:00", _calendar=calendar)
                self.merge(item, body)
                return item
            created = {"id": "(new)", "changeKey": "(new)"}
            return 201, created, {}, apply
        item = self.events.get(urllib.parse.unquote(event_id or ""))
        if item is not None and self.home.get(item["id"], "default") != calendar:
            item = None      # an event is found only through the path of its own calendar
        if item is None:
            return 404, {"error": {"code": "ErrorItemNotFound", "message": "The specified object was not found in the store."}}, {}, None
        if method == "GET":
            shown = dict(item)
            own = shown.pop("_own", None)      # an all-day event's own zone: asked in UTC (a Prefer header) Graph shifts its midnight, asked with none it does not
            if own and "outlook.timezone" not in (entry["prefer"] or ""):
                shown["start"], shown["end"] = own["start"], own["end"]
            if "outlook.timezone=\"UTC\"" in (entry["prefer"] or ""):      # asked in UTC, Graph converts an event written in another zone, as the real service does
                for edge in ("start", "end"):
                    shown[edge] = utc_form(shown[edge])
            if "singleValueExtendedProperties" not in entry["query"].get("$expand", ""):
                shown.pop("singleValueExtendedProperties", None)
            return 200, shown, {}, None
        if method == "PATCH":
            def apply():
                self.merge(item, entry["body"])
                return item
            return 200, item, {}, apply
        if method == "DELETE":
            def apply():
                self.removed[item["id"]] = self.events.pop(item["id"])
                return None
            return 204, None, {}, apply
        return 405, {"error": {"code": "methodNotAllowed", "message": "not served"}}, {}, None

    def series_api(self, entry, method, calendar, event_id, action):
        """`GET .../events/{master}/instances` (the occurrences and exceptions that meet the window; none cancelled) and `POST .../events/{id}/cancel` (202; the event, and a
        master's occurrences, move to `removed`; 400 for an event the person does not organise, as Graph answers an attendee)."""
        if method == "POST" and self.refuse_next:
            status, code = self.refuse_next
            self.refuse_next = None
            return status, {"error": {"code": code, "message": f"stand-in refusal {code}"}}, ({"Retry-After": "30"} if status in (429, 503) else {}), None
        item = self.events.get(event_id)
        if item is None or self.home.get(event_id, "default") != calendar:
            return 404, {"error": {"code": "ErrorItemNotFound", "message": "The specified object was not found in the store."}}, {}, None
        if action == "instances" and method == "GET":
            low, high = entry["query"].get("startDateTime"), entry["query"].get("endDateTime")
            if not low or not high or item.get("type") != "seriesMaster":
                return 400, {"error": {"code": "ErrorInvalidRequest", "message": "stand-in: a window and a series master are required"}}, {}, None
            def at(text):
                return datetime.fromisoformat(text.replace("Z", "+00:00")[:19] + "+00:00")
            found = [e for e in self.events.values() if e.get("seriesMasterId") == event_id and e.get("isCancelled") is not True
                     and at(e["start"]["dateTime"]) < at(high) and at(e["end"]["dateTime"]) > at(low)]
            found.sort(key=lambda e: e["start"]["dateTime"])
            top = int(entry["query"].get("$top") or 250)
            return 200, {"value": [dict(e, **{"@odata.etag": f'W/"{e["changeKey"]}"'}) for e in found[:top]]}, {}, None
        if action == "cancel" and method == "POST":
            if item.get("isOrganizer") is not True:
                return 400, {"error": {"code": "ErrorInvalidRequest", "message": "Your request can't be completed. You need to be an organizer to cancel a meeting."}}, {}, None

            def apply():
                self.removed[event_id] = self.events.pop(event_id)
                self.cancelled.append(event_id)
                if item.get("type") == "seriesMaster":      # the series goes with its master: every occurrence and exception
                    for other in [i for i, e in self.events.items() if e.get("seriesMasterId") == event_id]:
                        self.removed[other] = self.events.pop(other)
                return None
            return 202, None, {}, apply
        return 405, {"error": {"code": "methodNotAllowed", "message": "not served"}}, {}, None

    def merge(self, item, body):
        if "recurrence" in body:      # an event created with a recurrence is a series master
            item["type"] = "seriesMaster"
        for key, value in body.items():
            if key in ("start", "end"):
                item[key] = {"dateTime": value["dateTime"] + ".0000000", "timeZone": value["timeZone"]}
            elif key == "singleValueExtendedProperties":
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
        return {"WRITER_CALENDAR_OUTLOOK_API_BASE": self.base, "WRITER_CALENDAR_OUTLOOK_TOKEN_URL": self.token_url}

    def graph_requests(self):
        return [r for r in self.requests if r["path"].startswith(GRAPH + "/")]
