#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Calendar writer for Outlook (Microsoft 365 and outlook.com): an implementation of the class writer:calendar (package W1, SPEC-SECRETARY-WRITES; the removal,
slice S21). It creates, changes and removes one event of one calendar of the person's own Microsoft account through Microsoft Graph, and reads one event back. It is
called only by the effect module runtime/effect_calendar.py (the write verbs, after the person approved the exact request) and by one read-only seam of the runtime
(`event-get`, and the dry run of the others); never by a skill, a run or a handler. No attendee is ever sent. THE REMOVAL (`event-delete`) IS ONE DELETE, AND IT MAY NOT
BE UNDONE: Microsoft does not say where a removed event goes (the page of the removal call), and nobody has checked that it lands in Deleted Items. The maintainer chose
the plain removal on 2026-10-22 (it reverses Q12 of SPEC-SECRETARY-WRITES: docs/decisions.md), so the card the person approves says that Outlook may keep no copy.

Sources (Microsoft's own documentation, accessed 2026-10-18; what is not read there is listed under "To verify" in providers/writer/README.md):
- Create event (POST /me/calendar/events and /me/calendars/{id}/events; "Graph sends invitations to all attendees", which this writer never sets), update event
  (PATCH /me/events/{id}; only the properties in the body change; there is no documented If-Match) and the event resource (changeKey, isOrganizer, attendees, type,
  seriesMasterId, isReminderOn, reminderMinutesBeforeStart, body, location, start, end, isAllDay): https://learn.microsoft.com/en-us/graph/api/user-post-events,
  https://learn.microsoft.com/en-us/graph/api/event-update and https://learn.microsoft.com/en-us/graph/api/resources/event
- Delete event (DELETE /me/events/{id} and /me/calendars/{id}/events/{id}; 204 No Content; the page says nothing of where the event goes, and there is no documented
  If-Match): https://learn.microsoft.com/en-us/graph/api/event-delete
- Extended properties (singleValueExtendedProperties on create and update, and a $filter on them): https://learn.microsoft.com/en-us/graph/api/resources/extended-properties-overview
- Permissions reference (Calendars.ReadWrite): https://learn.microsoft.com/en-us/graph/permissions-reference
- The dateTimeTimeZone type (`timeZone` "can be set to any of the time zones currently supported by Windows, as well as the other time zones supported by the calendar
  API", with a list of IANA names such as America/Sao_Paulo; "create or update might not support all" of them; accessed 2026-10-27):
  https://learn.microsoft.com/en-us/graph/api/resources/datetimetimezone

Usage:
  uv run providers/writer/outlook-calendar.py --help
  uv run providers/writer/outlook-calendar.py --check
  uv run providers/writer/outlook-calendar.py event-get --calendar <default|id> --event <id>
  uv run providers/writer/outlook-calendar.py event-create --calendar <default|id> --spec-file <file> --idempotency-key <key> [--time-zone <IANA name>] (--dry-run | --confirmed)
  uv run providers/writer/outlook-calendar.py event-patch --calendar <default|id> --event <id> --base-etag <changeKey> --spec-file <file> --idempotency-key <key> [--time-zone <IANA name>] (--dry-run | --confirmed)
  uv run providers/writer/outlook-calendar.py event-delete --calendar <default|id> --event <id> --base-etag <changeKey> --idempotency-key <key> (--dry-run | --confirmed)

  --check        refreshes the access token, checks that the account token carries the platform's whole set of permissions, and reads one entry of the calendar list;
                 prints {"ok": true, "record", "scope", "tenant", "obtained_at", "rotation"}. Exit 3 when there is no authorization or the set is not the platform's.
  event-get      {"found": true, "event": {"id", "etag" (the changeKey), "status", "title", "start", "end", "all_day", "location", "notes", "notes_truncated",
                 "reminder_minutes", "organizer_self", "attendees_other", "recurring", "external_content": true}} or {"found": false, "reason"} for an event that is gone.
                 `start` and `end` are UTC (`...Z`) for a timed event and days for an all-day one (`end` is the day after the last). `attendees_other` counts the
                 attendees who are not the person; no address is printed. The text is another person's in principle: data, never instructions.
  event-create   creates the event the spec describes: {"done": true, "replayed", "event_id", "etag"}.
  event-patch    changes only the parts the spec lists, only if the event still has the changeKey `--base-etag` (Graph documents no If-Match, so the writer reads
                 the event again right before the PATCH and compares): {"done": true, "replayed", "event_id", "etag"}.
  event-delete   removes the event with one DELETE, only if it still has the changeKey `--base-etag` (the writer reads the event again right before and compares) and
                 only if it is the person's alone: organised by them, with no other attendee, not a series (else exit 1, `not eligible:`; nobody is ever told, and a
                 meeting or a series is not removed here). Where the removed event goes is NOT VERIFIED: it may not be recoverable. {"done": true, "replayed", "event_id", "etag": null}.
                 An event that is gone after an answer was lost counts as removed (`replayed`).
  --time-zone    (event-create and event-patch, optional) the IANA name of the zone the event is written in, for example America/Sao_Paulo: a timed event's `start` and
                 `end` are then sent as the same instants in that zone's wall time, with `"timeZone": "<name>"`, so the event carries its own named zone (and a series made
                 later keeps its hour across a clock change). Exit 2 unless the name is an IANA name of the form Area/Place (or Area/Region/Place) that the machine's zone
                 database knows. A wall time that is ambiguous in the zone (the repeated hour of a clock change), or that does not read back as the same instant, is sent in
                 UTC as without the flag. An all-day event, and a run without the flag, send what they always sent. The name is a flag, not a spec key: it is not the person's
                 words (the runtime passes the host's zone). Reads stay in UTC (`Prefer: outlook.timezone="UTC"`): Graph converts, and the same instant comes back.
                 Microsoft's page lists only some IANA names; a name Graph does not accept is refused by Graph, nothing is written, and the error is reported.
  --dry-run      reads no credential, opens no connection and prints {"dry_run": true, "would": {"method", "path", "query", "headers", "body"}, "would_sha256",
                 "ledger"}: the exact request `--confirmed` sends, and its hash.
  --confirmed    sends exactly that request. The key is recorded `pending` in the ledger first and `done` after the answer; a key that is `done` is not sent again
                 (`replayed`), and one left `pending` by an answer that was lost is looked up in the calendar (by the extended property `openhora_key` the request
                 carries) before anything is sent.

The spec (a file, never a flag: it holds the person's words): the whole event for event-create, {"title", "all_day", "start_at", "end_at", "location",
"reminder_minutes", "notes"}; for event-patch the parts to change, the three times together. event-delete takes no spec. `start_at` and `end_at` are an instant with its offset (sent to Graph
in UTC), or, for an all-day event, the first day and the day after the last.

Credentials (never from a flag or a file; contracts/secrets.md):
  MICROSOFT_ACCOUNT_TOKEN  the account record (providers/accounts/microsoft_auth.py), read through providers/secrets/resolver.py. There is no legacy record for a
                           writer: a token that lacks one permission of the platform's set, or carries another, is refused (exit 3) before any call. Microsoft
                           replaces the refresh token on every use; as the readers do, this writer writes the new one back to the record it used, only if it still
                           holds the token this process used (providers/_msgraph.py store_rotation).
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read or written):
  WRITER_CALENDAR_OUTLOOK_API_BASE    replaces https://graph.microsoft.com/v1.0
  WRITER_CALENDAR_OUTLOOK_TOKEN_URL   replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token

Limits. The request function sends only the methods and paths of ALLOWED, and refuses anything else (limits L57, L58); its one removal is the event's. No redirect is
followed. A verb never retries: a 429, or a 503 on a read, is reported with its Retry-After and nothing is changed; a 503 or another server error on a write is exit 4 (it may have landed) and the key stays pending. Every request has a 60-second timeout. Prints one JSON object
on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 refused with nothing changed (the service said no, or the event changed since it was read: the message starts
with `changed:`; or the event is not the person's alone: it starts with `not eligible:`), 2 usage (a bad flag, id or spec, a verb this writer does not have), 3 not configured, 4 unknown (the request may have landed: send the same key again).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def _shared(name: str, filename: str):
    """providers/<filename>, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parents[1] / filename, here.parent / filename) if c.is_file()), None)
    if path is None:
        raise SystemExit(f"error: providers/{filename} is not next to this script's folder")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


msgraph = _shared("providers_msgraph", "_msgraph.py")
_calendar = _shared("providers_writer_calendar", "_writer_calendar.py")
GraphError, WriterError = msgraph.ProviderError, _calendar.WriterError
EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_calendar.EXIT_OK, _calendar.EXIT_REFUSED, _calendar.EXIT_USAGE,
                                                                        _calendar.EXIT_NOT_CONFIGURED, _calendar.EXIT_UNKNOWN)

SERVES = "writer:calendar"
IMPLEMENTATION = "outlook-calendar"
# The only requests this writer sends (limits L57 and L58): a method and a full-match pattern of the path, as the request function sees it (ids are percent-encoded).
# An id in a path is what the builders let through, percent-encoded as they send it: letters, digits, `_` and `-`, and the encodings of `=` (%3D) and, for an event, `+`
# (%2B). No dot, so `.` and `..` are not a segment, and no `/`, so a path cannot leave the calendar's events (L57: this is the guard of the one removal).
ALLOWED = (("GET", r"/me/calendars"),
           ("GET", r"/me/calendar/events"),
           ("GET", r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events"),
           ("GET", r"/me/calendar/events/(?:[A-Za-z0-9_-]|%3D|%2B)+"),
           ("GET", r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events/(?:[A-Za-z0-9_-]|%3D|%2B)+"),
           ("POST", r"/me/calendar/events"),
           ("POST", r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events"),
           ("PATCH", r"/me/calendar/events/(?:[A-Za-z0-9_-]|%3D|%2B)+"),
           ("PATCH", r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events/(?:[A-Za-z0-9_-]|%3D|%2B)+"),
           ("DELETE", r"/me/calendar/events/(?:[A-Za-z0-9_-]|%3D|%2B)+"),
           ("DELETE", r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events/(?:[A-Za-z0-9_-]|%3D|%2B)+"))
(LIST_CALENDARS, LIST_DEFAULT, LIST_IN, GET_DEFAULT, GET_IN, POST_DEFAULT, POST_IN, PATCH_DEFAULT, PATCH_IN, REMOVE_DEFAULT, REMOVE_IN) = ALLOWED
KEY_PROPERTY = "String {c1a7e5d2-9b34-4f68-8a1e-3d5f7b2c9e40} Name openhora_key"   # the private property every request writes: a lost answer is looked up by it
PROFILE = msgraph.account_profile(
    run_hint="uv run <workbench>/providers/writer/outlook-calendar.py", env_prefix="WRITER_CALENDAR_OUTLOOK", user_agent="openhora-writer-calendar-outlook",
    not_found="Outlook does not know the calendar or the event, or it is not one of the person's",
    forbidden_hint="check that the account token carries the platform's whole set and that the calendar is one of the person's own")
SELECT = ("id,changeKey,subject,body,start,end,isAllDay,location,isReminderOn,reminderMinutesBeforeStart,isOrganizer,isCancelled,attendees,type,"
          "seriesMasterId")
PAGE_BYTES = 1024 * 1024
NOTES_SHOWN = 2000
RECURRING_TYPES = ("seriesMaster", "occurrence", "exception")
GRAPH_LOCAL_RE = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?")
ZONE_NAME_RE = re.compile(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+){1,2}")      # an IANA name: Area/Place or Area/Region/Place (no dot, so no `..`)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
CHANGE_KEY_RE = re.compile(r"(?!-)[A-Za-z0-9_=+/.-]{1,200}")


class Lost(WriterError):
    """The request may have reached the service and its answer was lost: exit 4."""

    def __init__(self, message):
        super().__init__(message, EXIT_UNKNOWN)


def log(message: str) -> None:
    print(message, file=sys.stderr)


def one_line(text, limit: int = 300) -> str:
    return " ".join(CONTROL_RE.sub(" ", str(text if text is not None else "")).split())[:limit]


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


# --- the account token ---------------------------------------------------------------------------------------------------------------------------


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def keyring_module(test_mode: bool):
    return msgraph.keyring_module(PROFILE, test_mode)


class Session:
    """What a verb that talks to Graph holds: the base address, an access token, and the record's address."""

    def __init__(self, client, record: dict):
        self.client, self.record = client, record


def open_session() -> Session:
    """An access token from the account record: the whole platform set, or exit 3. There is no legacy record for a writer."""
    base, token_url, _, test_mode = msgraph.endpoints(PROFILE)
    found = msgraph.find_account_record(secret_resolver(), PROFILE, test_mode)
    if found is None:
        raise GraphError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = msgraph.parse_account_record(PROFILE, found[0])
    access, rotated = msgraph.refresh_access_token(PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    record["rotation"] = msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, secret_resolver, keyring_module)
    return Session(msgraph.GraphClient(PROFILE, base, access, test_mode), record)


# --- HTTP --------------------------------------------------------------------------------------------------------------------------


def request(entry: tuple, session: Session, path: str, query: dict, headers: dict, body=None, write: bool = False) -> tuple:
    """The one function that sends a request to Graph. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused before a
    connection is opened. Returns (status, response headers, body bytes). A failure of a write after the request could have reached Graph is Lost (exit 4)."""
    method, pattern = entry
    if entry not in ALLOWED or not re.fullmatch(pattern, path):
        raise WriterError(f"this writer does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    client = session.client
    sent = {"Authorization": f"Bearer {client.token}", "Accept": "application/json", "User-Agent": PROFILE.user_agent, **headers}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json; charset=utf-8"
    try:
        return msgraph.http(method, client.url_for(path, query), sent, data, PAGE_BYTES, what="Microsoft Graph")
    except GraphError as exc:
        if write:
            raise Lost(f"{exc}: the request may or may not have landed") from None
        raise


def failure(session: Session, status: int, headers, body: bytes, what: str):
    """The error for an answer that is not the one wanted. A write answered with a redirect or a server error may have landed (Lost)."""
    if status == 404 or status == 409 or status == 410:
        return WriterError(f"changed: the event is not as it was read ({what}, {status})", EXIT_REFUSED, status)
    if not what.startswith("GET") and (status in msgraph.REDIRECT_STATUSES or status >= 500):      # a read changes nothing: only a write may have landed
        return Lost(f"Graph answered {status} ({what}): the request may or may not have landed")
    problem = session.client.failure(status, headers, body, what)
    return WriterError(str(problem), problem.code, status)


# --- checking the ids and the arguments ---------------------------------------------------------------------------------------


def calendar_id(value) -> str:
    if value != "default" and (not isinstance(value, str) or not re.fullmatch(r"(?!-)[A-Za-z0-9=_-]{1,300}", value)):
        raise WriterError("--calendar is `default` or an Outlook calendar id (letters, digits, = _ and -)", EXIT_USAGE)
    return value


def event_id(value) -> str:
    if not isinstance(value, str) or not _calendar.EVENT_ID.fullmatch(value):
        raise WriterError("--event is an event id (letters, digits and = _ + -)", EXIT_USAGE)
    return value


def base_etag(value) -> str:
    if not isinstance(value, str) or not CHANGE_KEY_RE.fullmatch(value):
        raise WriterError("--base-etag is the changeKey the event had when it was read", EXIT_USAGE)
    return value


def idempotency_key(value) -> str:
    if not isinstance(value, str) or not _calendar.KEY.fullmatch(value):
        raise WriterError("--idempotency-key is letters, digits, dots, hyphens and underscores, at most 128 characters", EXIT_USAGE)
    return value


def events_path(calendar: str, event=None) -> str:
    """The path of the events of a calendar, or of one event of it: the default calendar by its name, another by its percent-encoded id."""
    root = "/me/calendar/events" if calendar == "default" else f"/me/calendars/{urllib.parse.quote(calendar, safe='')}/events"
    return root if event is None else f"{root}/{urllib.parse.quote(event, safe='')}"


def entry_for(method: str, calendar: str, item: bool):
    table = {("GET", True): (GET_DEFAULT, GET_IN), ("GET", False): (LIST_DEFAULT, LIST_IN), ("POST", False): (POST_DEFAULT, POST_IN),
             ("PATCH", True): (PATCH_DEFAULT, PATCH_IN)}
    default, named = table[(method, item)]
    return default if calendar == "default" else named


# --- the requests, built without a connection -----------------------------------------------------------------------------------


def utc_of(instant: str) -> str:
    return datetime.fromisoformat(instant[:-1] + "+00:00" if instant.endswith("Z") else instant).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def time_zone_of(value):
    """The IANA name of --time-zone, checked, or None when the flag is absent. Usage error (exit 2) unless it is an Area/Place name the machine's zone database loads."""
    if value is None:
        return None
    if not isinstance(value, str) or not ZONE_NAME_RE.fullmatch(value):
        raise WriterError("--time-zone is an IANA zone name such as America/Sao_Paulo", EXIT_USAGE)
    try:
        ZoneInfo(value)
    except Exception:
        raise WriterError(f"--time-zone {value}: this machine's zone database does not know that zone", EXIT_USAGE) from None
    return value


def zoned(instant: str, zone: str):
    """{"dateTime": the instant's wall time in `zone`, "timeZone": zone}, or None when that wall time is ambiguous in the zone (a repeated hour: `fold`) or does not
    read back as the same instant: the caller then sends UTC, as it does without the flag."""
    moment_utc = datetime.fromisoformat(instant[:-1] + "+00:00" if instant.endswith("Z") else instant).astimezone(timezone.utc)
    info = ZoneInfo(zone)
    wall = moment_utc.astimezone(info).replace(tzinfo=None)
    first, second = wall.replace(tzinfo=info, fold=0), wall.replace(tzinfo=info, fold=1)
    if first.utcoffset() != second.utcoffset() or first.astimezone(timezone.utc) != moment_utc:
        return None
    return {"dateTime": wall.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": zone}


def moment(spec: dict, name: str, zone=None) -> dict:
    """A Graph dateTimeTimeZone: midnight for an all-day event; for a timed one the wall time in `zone` when it is given and the instant is not ambiguous in it, else UTC."""
    if spec["all_day"]:
        return {"dateTime": f"{spec[name]}T00:00:00", "timeZone": "UTC"}
    return (zone and zoned(spec[name], zone)) or {"dateTime": utc_of(spec[name]), "timeZone": "UTC"}


def body_of(spec: dict, key: str, whole: bool, zone=None) -> dict:
    """The body of a create (the whole event) or of a patch (the parts in the spec). The private property `openhora_key` is in both. No attendee, ever."""
    out = {}
    if "title" in spec:
        out["subject"] = spec["title"]
    if "start_at" in spec:
        out["isAllDay"], out["start"], out["end"] = spec["all_day"], moment(spec, "start_at", zone), moment(spec, "end_at", zone)
    if "location" in spec and (spec["location"] or not whole):
        out["location"] = {"displayName": spec["location"]}
    if "notes" in spec and (spec["notes"] or not whole):
        out["body"] = {"contentType": "text", "content": spec["notes"]}
    if spec.get("reminder_minutes") is not None:
        out["isReminderOn"], out["reminderMinutesBeforeStart"] = True, spec["reminder_minutes"]
    out["singleValueExtendedProperties"] = [{"id": KEY_PROPERTY, "value": key}]
    return out


def build(verb: str, args) -> dict:
    """The request a verb sends, as {"entry", "method", "path", "query", "headers", "body"}: checked arguments in, no credential, no connection."""
    calendar, key = calendar_id(args.calendar), idempotency_key(args.idempotency_key)
    zone = time_zone_of(getattr(args, "time_zone", None))
    if verb == "event-create":
        spec = _calendar.read_spec(args.spec_file, "create")
        entry, path, body = entry_for("POST", calendar, False), events_path(calendar), body_of(spec, key, True, zone)
    elif verb == "event-patch":
        spec = _calendar.read_spec(args.spec_file, "change")
        base_etag(args.base_etag)
        entry, path, body = entry_for("PATCH", calendar, True), events_path(calendar, event_id(args.event)), body_of(spec, key, False, zone)
    else:
        base_etag(args.base_etag)
        entry, path, body = REMOVE_DEFAULT if calendar == "default" else REMOVE_IN, events_path(calendar, event_id(args.event)), None
    return {"entry": entry, "method": entry[0], "path": path, "query": {}, "headers": {}, "body": body}


def would_of(built: dict) -> dict:
    return {k: built[k] for k in ("method", "path", "query", "headers", "body")}


# --- the event as Graph printed it ---------------------------------------------------------------------------------------------


def graph_moment(value, all_day: bool):
    """A Graph dateTimeTimeZone as the string this writer prints: `YYYY-MM-DD` for an all-day event, `YYYY-MM-DDTHH:MM:SSZ` for a timed one in UTC; None when it is
    missing or in another time zone (never guessed)."""
    if not isinstance(value, dict) or not isinstance(value.get("dateTime"), str):
        return None
    found = GRAPH_LOCAL_RE.fullmatch(value["dateTime"])
    if not found:
        return None
    if all_day:
        return found.group(1)
    if str(value.get("timeZone") or "").upper() not in ("UTC", "ETC/UTC"):
        return None
    return f"{found.group(1)}T{found.group(2)}Z"


def attendees_other(item, own_address) -> list:
    """The attendees of an event who are not the person."""
    attendees = item.get("attendees") if isinstance(item.get("attendees"), list) else []
    mine = (own_address or "").casefold()
    return [a for a in attendees if not (isinstance(a, dict) and mine and str(((a.get("emailAddress") or {}).get("address")) or "").casefold() == mine)]


def not_eligible(item, own_address):
    """Why an event may not be removed here, or None: it is the person's alone when they organise it, nobody else is an attendee and it is not a series (Q3).
    A meeting would tell other people and a series would take every occurrence, so neither is removed; an unknown organiser is not the person."""
    if item.get("isOrganizer") is not True:
        return "the event is organised by someone else"
    if attendees_other(item, own_address):
        return "the event has other attendees"
    if item.get("type") in RECURRING_TYPES or item.get("seriesMasterId"):
        return "the event is part of a series"
    return None


def read_event(item, own_address) -> dict:
    """The event as `event-get` prints it. WriterError (exit 1) when it is not in a form this writer understands."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not _calendar.EVENT_ID.fullmatch(item["id"]):
        raise WriterError("Graph answered an event this writer does not understand")
    all_day = item.get("isAllDay") is True
    start, end = graph_moment(item.get("start"), all_day), graph_moment(item.get("end"), all_day)
    if start is None or end is None:
        raise WriterError("Graph answered an event whose times this writer does not understand (another time zone than UTC, or no time)")
    others = attendees_other(item, own_address)
    body = item.get("body") if isinstance(item.get("body"), dict) else {}
    notes = str(body.get("content") or "").replace("\r\n", "\n").replace("\r", "\n")
    key = item.get("changeKey")
    reminder = item.get("reminderMinutesBeforeStart")
    return {"id": item["id"], "etag": key if isinstance(key, str) and CHANGE_KEY_RE.fullmatch(key) else None,
            "status": "cancelled" if item.get("isCancelled") is True else "confirmed", "title": one_line(item.get("subject"), 300), "start": start, "end": end,
            "all_day": all_day, "location": one_line((item.get("location") or {}).get("displayName") if isinstance(item.get("location"), dict) else "", 200),
            "notes": "".join(c for c in notes if c in "\n\t" or not CONTROL_RE.match(c)).strip()[:NOTES_SHOWN], "notes_truncated": len(notes.strip()) > NOTES_SHOWN,
            "reminder_minutes": reminder if item.get("isReminderOn") is True and type(reminder) is int else None,
            "organizer_self": item.get("isOrganizer") is True, "attendees_other": len(others),
            "recurring": item.get("type") in RECURRING_TYPES or bool(item.get("seriesMasterId")), "external_content": True}


def json_body(body: bytes):
    try:
        found = json.loads(body)
    except ValueError:
        found = None
    return found if isinstance(found, dict) else None


def read_once(session: Session, calendar: str, event: str, prefer: dict):
    status, headers, body = request(entry_for("GET", calendar, True), session, events_path(calendar, event), {"$select": SELECT}, prefer)
    if status == 404:
        return None
    if status != 200:
        raise failure(session, status, headers, body, "GET event")
    item = json_body(body)
    if item is None:
        raise WriterError("Graph answered something this writer does not understand")
    return item


def fetch_event(session: Session, calendar: str, event: str):
    """The event as Graph holds it, or None when it is gone (404 or cancelled). A timed event is read in UTC. An all-day event is read AGAIN in its own zone:
    asked in UTC, Graph shifts its midnight and the date can come out a day off east or west of UTC."""
    item = read_once(session, calendar, event, {"Prefer": 'outlook.timezone="UTC", outlook.body-content-type="text"'})
    if item is not None and item.get("isAllDay") is True:
        own = read_once(session, calendar, event, {"Prefer": 'outlook.body-content-type="text"'})
        item = own if own is not None else None
    return None if item is None or item.get("isCancelled") is True else item


# --- the verbs -----------------------------------------------------------------------------------------------------------------


def cmd_check(args) -> int:
    session = open_session()
    status, headers, body = request(LIST_CALENDARS, session, "/me/calendars", {"$select": "id", "$top": "1"}, {})
    if status != 200:
        raise failure(session, status, headers, body, "GET calendars")
    record = session.record
    return emit({"ok": True, "record": "account", "scope": " ".join(PROFILE.scopes), "tenant": record["tenant"], "obtained_at": record.get("obtained_at"),
                 "rotation": record["rotation"]})


def cmd_event_get(args) -> int:
    calendar, event = calendar_id(args.calendar), event_id(args.event)
    session = open_session()
    item = fetch_event(session, calendar, event)
    if item is None:
        return emit({"found": False, "reason": "gone"})
    return emit({"found": True, "event": read_event(item, session.record.get("account"))})


def landed(session: Session, verb: str, args, key: str):
    """After an answer that was lost: whether the request of `key` is in the calendar. The facts of the event ({"event_id", "etag"}) when it is, else None."""
    calendar = calendar_id(args.calendar)
    if verb == "event-create":
        wanted = f"singleValueExtendedProperties/any(ep: ep/id eq '{KEY_PROPERTY}' and ep/value eq '{key}')"
        status, headers, body = request(entry_for("GET", calendar, False), session, events_path(calendar), {"$filter": wanted, "$select": "id,changeKey", "$top": "2"}, {})
        if status != 200:
            raise failure(session, status, headers, body, "GET events")
        items = (json_body(body) or {}).get("value") or []
        return {"event_id": items[0].get("id"), "etag": items[0].get("changeKey")} if items and isinstance(items[0], dict) else None
    if verb == "event-delete":      # removed: the event is gone (or cancelled). Not gone: the removal was not made, and the request is sent again.
        gone = fetch_event(session, calendar, event_id(args.event)) is None
        return {"event_id": args.event, "etag": None} if gone else None
    status, headers, body = request(entry_for("GET", calendar, True), session, events_path(calendar, event_id(args.event)),
                                    {"$select": "id,changeKey,isCancelled", "$expand": f"singleValueExtendedProperties($filter=id eq '{KEY_PROPERTY}')"}, {})
    if status == 404:
        return None
    if status != 200:
        raise failure(session, status, headers, body, "GET event")
    item = json_body(body) or {}
    found = [p for p in item.get("singleValueExtendedProperties") or [] if isinstance(p, dict) and p.get("id") == KEY_PROPERTY and p.get("value") == key]
    return {"event_id": item.get("id"), "etag": item.get("changeKey")} if found else None


def write(verb: str, args) -> int:
    built = build(verb, args)
    would, key = would_of(built), args.idempotency_key
    digest = _calendar.sha(_calendar.canonical(would))
    operation = {"event-create": "create", "event-patch": "change", "event-delete": "cancel"}[verb]
    if args.dry_run:
        peeked = _calendar.ledger_peek(IMPLEMENTATION, key)
        return emit({"dry_run": True, "would": would, "would_sha256": digest, "ledger": (peeked or {}).get("status", "absent")})
    state, entry = _calendar.claim(IMPLEMENTATION, key, digest, operation)
    if state == "done":
        return emit({"done": True, "replayed": True, "event_id": entry.get("event_id"), "etag": entry.get("etag")})
    fresh = state == "new"      # this attempt made the key: until something may have been sent, a failure frees it. A key an earlier attempt left pending stays pending.
    try:
        session = open_session()
    except BaseException:
        if fresh:
            _calendar.settle(IMPLEMENTATION, key, "released")
        raise
    if not fresh:               # an earlier attempt's answer was lost: look in the calendar before anything is sent
        try:
            found = landed(session, verb, args, key)
        except (WriterError, GraphError) as exc:
            raise Lost(f"an earlier attempt with this key did not say whether it landed, and the calendar cannot be looked up now ({exc}): the key stays "
                       "pending; send it again later") from None
        if found is not None:
            _record_done(key, found)
            return emit({"done": True, "replayed": True, **found})
    try:
        if verb in ("event-patch", "event-delete"):      # Graph documents no If-Match: read the event again right before the change and compare its changeKey
            item = fetch_event(session, calendar_id(args.calendar), event_id(args.event))
            if item is None or item.get("changeKey") != args.base_etag:
                raise WriterError("changed: the event is not as it was read (it is gone, or its changeKey moved)", EXIT_REFUSED)
            if verb == "event-delete" and (why := not_eligible(item, session.record.get("account"))):
                raise WriterError(f"not eligible: {why}; nothing was removed", EXIT_REFUSED)
        status, headers, body = request(built["entry"], session, built["path"], built["query"], built["headers"], built["body"], write=True)
    except Lost:
        raise          # the key stays pending: sending it again looks in the calendar first
    except BaseException:
        _calendar.settle(IMPLEMENTATION, key, "released")      # nothing was sent (and, for a key an earlier attempt left pending, the calendar was looked up: it did not land)
        raise
    if status not in (200, 201, 204):
        problem = failure(session, status, headers, body, f"{built['method']} event")
        if not isinstance(problem, Lost):
            _calendar.settle(IMPLEMENTATION, key, "released")      # Graph said no: nothing changed, the key is free
        raise problem
    answer = json_body(body) or {}
    done = {"event_id": answer.get("id") or getattr(args, "event", None), "etag": answer.get("changeKey")}      # a removal answers 204: no body
    _record_done(key, done)
    return emit({"done": True, "replayed": False, **done})


def _record_done(key: str, facts: dict) -> None:
    """Record the key done. A ledger that cannot be written after the request landed does not turn it into a failure: the key stays pending, and the next
    request with it finds the event in the calendar."""
    try:
        _calendar.settle(IMPLEMENTATION, key, "done", **{k: v for k, v in facts.items() if isinstance(v, str)})
    except (WriterError, OSError) as exc:
        log(f"warning: the request landed, and the ledger could not record it ({one_line(exc, 200)}): the key {key} stays pending")


VERBS = ("event-get", "event-create", "event-patch", "event-delete")
FLAG_NAMES = {"calendar": "--calendar", "event": "--event", "base_etag": "--base-etag", "spec_file": "--spec-file", "idempotency_key": "--idempotency-key",
              "time_zone": "--time-zone"}
VERB_FLAGS = {"event-get": {"calendar", "event"}, "event-create": {"calendar", "spec_file", "idempotency_key"},
              "event-patch": {"calendar", "event", "base_etag", "spec_file", "idempotency_key"},
              "event-delete": {"calendar", "event", "base_etag", "idempotency_key"}, None: set()}
OPTIONAL_FLAGS = {"event-create": {"time_zone"}, "event-patch": {"time_zone"}}      # accepted, never required


def check_flags(args) -> None:
    """A flag given to a verb that does not read it is a usage error, a required one that is missing too; --check takes no verb."""
    if args.check and args.verb:
        raise WriterError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if args.check:
        return
    if not args.verb:
        raise WriterError("give a verb (event-get, event-create, event-patch, event-delete) or --check; see --help", EXIT_USAGE)
    wanted = VERB_FLAGS[args.verb]
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in wanted | OPTIONAL_FLAGS.get(args.verb, set())]
    if extra:
        raise WriterError(f"{', '.join(extra)}: not a flag of {args.verb} (see --help)", EXIT_USAGE)
    missing = [FLAG_NAMES[dest] for dest in wanted if getattr(args, dest) is None]
    if missing:
        raise WriterError(f"{args.verb} needs {', '.join(sorted(missing))}", EXIT_USAGE)
    if args.verb != "event-get" and bool(args.dry_run) == bool(args.confirmed):
        raise WriterError(f"{args.verb} needs exactly one of --dry-run and --confirmed", EXIT_USAGE)
    if args.verb == "event-get" and (args.dry_run or args.confirmed):
        raise WriterError("event-get is a read: it takes neither --dry-run nor --confirmed", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outlook-calendar.py", description=__doc__.split("\n\n")[0], epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read one calendar entry; prints no secret")
    parser.add_argument("--calendar", help="`default`, or the calendar id")
    parser.add_argument("--event", help="the event id")
    parser.add_argument("--base-etag", dest="base_etag", help="the changeKey the event had when it was read")
    parser.add_argument("--spec-file", dest="spec_file", help="the file that holds the event, or the parts to change, as JSON")
    parser.add_argument("--idempotency-key", dest="idempotency_key", help="the key of this one request")
    parser.add_argument("--time-zone", dest="time_zone", help="event-create and event-patch: the IANA zone name the timed event is written in (optional; default UTC)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the exact request and its hash; read no credential, open no connection")
    parser.add_argument("--confirmed", action="store_true", help="send exactly that request")
    return parser


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)
    check_flags(args)
    if args.check:
        return cmd_check(args)
    if args.verb == "event-get":
        return cmd_event_get(args)
    return write(args.verb, args)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(argv)
    except (WriterError, GraphError) as exc:
        log(f"error: {exc}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a body; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was changed")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
