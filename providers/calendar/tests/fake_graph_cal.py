"""A stand-in for the calendar side of Microsoft Graph (and the Microsoft identity token endpoint), on 127.0.0.1, for the offline tests of
providers/calendar/outlook.py and outlook_auth.py. Not a test file, and never a copy of the live service: it serves exactly the calls the
provider's docstring names, keeps a few fictional calendars and events in memory, and refuses what the reference says the service refuses (a
calendarView without its two bounds, a missing or wrong bearer token, an unknown calendar) and, like the permission the provider holds
(Calendars.ReadBasic), never returns an event's body, its attachments or its extensions, and answers 403 to a `$select` that names them. Every
address is on a `.example` domain and every credential is a made-up string.

The token side is the one the mail suite uses (providers/mailbox/tests/fake_microsoft.py), loaded from there.

Usage (from a test):
  fake = FakeGraphCal()
  fake.add("e1", "2026-10-17T12:00:00Z", "2026-10-17T13:00:00Z", "Dentist", location="Rua Exemplo 10")
  fake.add("h1", "2026-10-17", "2026-10-18", "Holiday", all_day=True)
  fake.close()
"""
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mailbox" / "tests"))
import fake_microsoft  # noqa: E402
from fake_microsoft import ACCESS_TOKEN, REFRESH_TOKEN, CODE, TENANT  # noqa: E402,F401  (re-exported for the tests)

CLIENT_ID = "66666666-7777-8888-9999-000000000000"
SCOPE = "Calendars.ReadBasic"
DEFAULT_CALENDAR = "CAL-default-1"
FORBIDDEN_SELECT = ("body", "bodypreview", "attachments", "extensions", "attendees", "onlinemeeting", "singlevalueextendedproperties")


def graph_time(value, zone="UTC"):
    return {"dateTime": value.rstrip("Z") + (".0000000" if "T" in value else "T00:00:00.0000000"), "timeZone": zone}


class FakeGraphCal(fake_microsoft.FakeMicrosoft):
    SCOPE = SCOPE
    CLIENT_ID = CLIENT_ID

    def __init__(self):
        self.calendars = {DEFAULT_CALENDAR: {"id": DEFAULT_CALENDAR, "name": "Calendar", "isDefaultCalendar": True, "canEdit": True,
                                             "owner": {"name": "Sam Sample", "address": "sam@mail.example"}}}
        self.events = {}                     # calendar id -> list of event dicts (Graph shaped, plus "_hidden")
        self.link_base = None                # the base of every @odata.nextLink; default: this listener
        self.link_path = None
        self.page_cap = None                 # at most this many events in a page
        self.calendars_status = 200          # what GET /me/calendars answers
        super().__init__()

    # --- what a test sets up -----------------------------------------------------------------------------------------------------

    def add_calendar(self, cid, name, primary=False, can_edit=False):
        self.calendars[cid] = {"id": cid, "name": name, "isDefaultCalendar": primary, "canEdit": can_edit}
        return cid

    def add(self, eid, start, end, subject, calendar=DEFAULT_CALENDAR, all_day=False, location=None, organizer="boss@corp.example", mine=False,
            response="accepted", cancelled=False, online=False, kind="singleInstance", series=None, zone="UTC", change_key=None, body="secret agenda"):
        """A fictional event. `start` and `end` are UTC ('...Z') or, for an all-day event, a date. `body` is stored and never served."""
        self.events.setdefault(calendar, []).append({
            "id": eid, "changeKey": change_key or f"CK-{eid}", "subject": subject, "start": graph_time(start, zone), "end": graph_time(end, zone),
            "isAllDay": all_day, "location": {"displayName": location or ""}, "organizer": {"emailAddress": {"name": "Org", "address": organizer}},
            "isOrganizer": mine, "responseStatus": {"response": response, "time": "0001-01-01T00:00:00Z"}, "isCancelled": cancelled,
            "isOnlineMeeting": online, "type": kind, "seriesMasterId": series, "_hidden": {"body": {"contentType": "text", "content": body},
                                                                                       "attachments": [{"name": "plan.pdf"}], "attendees": [{"emailAddress": {"address": "guest@x.example"}}]}})
        return eid

    # --- the Graph calls ---------------------------------------------------------------------------------------------------------

    def shown(self, event, select):
        full = {k: v for k, v in event.items() if k != "_hidden"}
        if select:
            wanted = {"id", *select.split(",")}
            full = {k: v for k, v in full.items() if k in wanted}
        return full

    @staticmethod
    def spelled(rest):
        """The path as the service reads it: the fixed words without case, `/users/<id>/` as `/me/`, no trailing slash (an id keeps its case)."""
        rest = rest.rstrip("/")
        if rest.lower().startswith("/users/"):
            rest = "/me/" + rest.split("/", 3)[3]
        parts = rest.split("/")
        return "/".join(p if i == 3 else p.lower() for i, p in enumerate(parts))

    def route(self, handler, rest, query):
        rest = self.spelled(rest)
        select = query.get("$select", "")
        if any(name.strip().lower() in FORBIDDEN_SELECT for name in select.split(",")):
            return handler.error(403, "ErrorAccessDenied", "Access is denied. Check credentials and try again.")
        if rest == "/me/calendars":
            if self.calendars_status != 200:
                return handler.error(self.calendars_status, "ErrorAccessDenied", "Access is denied.")
            return self.paged(handler, rest, query, [self.shown(c, select) for c in self.calendars.values()])
        if rest.lower() == "/me/calendarview":
            return self.view(handler, rest, query, DEFAULT_CALENDAR)
        parts = rest.split("/")      # ["", "me", "calendars", id, "calendarView"]
        if len(parts) == 5 and parts[1:3] == ["me", "calendars"] and parts[4] == "calendarview":
            if parts[3] not in self.calendars:
                return handler.error(404, "ErrorItemNotFound", "The specified object was not found in the store.")
            return self.view(handler, rest, query, parts[3])
        handler.error(404, "notFound", "not served")

    def view(self, handler, rest, query, calendar):
        if "startDateTime" not in query or "endDateTime" not in query:
            return handler.error(400, "ErrorInvalidRequest", "The parameter startDateTime is missing.")
        start, end = query["startDateTime"], query["endDateTime"]
        def stamp(event, key):   # the first 19 characters of a date-time, None for a value of the wrong shape (the service is made to send those)
            value = event[key]
            return value["dateTime"][:19] if isinstance(value, dict) and isinstance(value.get("dateTime"), str) else None

        found = [e for e in self.events.get(calendar, [])
                 if stamp(e, "end") is None or stamp(e, "start") is None or (stamp(e, "end") > start[:19].rstrip("Z") and stamp(e, "start") < end[:19].rstrip("Z"))]
        found.sort(key=lambda e: stamp(e, "start") or "")
        self.paged(handler, rest, query, [self.shown(e, query.get("$select")) for e in found])

    def paged(self, handler, rest, query, items):
        top = int(query.get("$top", "10"))
        if self.page_cap:
            top = min(top, self.page_cap)
        skip = int(query.get("$skip", "0"))
        out = {"value": items[skip:skip + top]}
        if skip + top < len(items):
            following = {**query, "$skip": str(skip + top)}
            out["@odata.nextLink"] = f"{self.link_base or self.root}{self.link_path or '/v1.0' + rest}?" + urllib.parse.urlencode(following)
        handler.json(200, out)

    # --- what a test reads -------------------------------------------------------------------------------------------------------

    def env(self, **over):
        """What the provider's process needs to talk to this fake and find its authorization in the environment."""
        return {"INTEGRATION_CALENDAR_OUTLOOK_API_BASE": self.base, "INTEGRATION_CALENDAR_OUTLOOK_TOKEN_URL": self.token_url,
                "OUTLOOK_CALENDAR_TOKEN": self.record_json(**over)}
