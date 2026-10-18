#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["keyring==25.7.0"]
# ///
"""Calendar provider for Outlook (Microsoft 365 and outlook.com): an implementation of the class integration:calendar. It lists the person's
calendars and reads the events of one calendar in a window, through Microsoft Graph, read only. The runtime turns what it prints into a dated
snapshot a task can be given (SPEC-SECRETARY-INTEGRATIONS, sections 1 to 3); nothing here writes to a calendar.

The OAuth permission is the delegated Microsoft Graph permission `Calendars.ReadBasic` (and `offline_access`, for the refresh token) and
nothing else. It reads events "except for properties such as body, attachments, and extensions" (the permissions reference), so no event
description, attachment or extension can reach this provider; it still reads EVERY event of every calendar the account can see, and changes
none. Narrowing to one calendar and a window is this runtime's, not the service's. Say so to anyone who asks what the token can do.

Sources (Microsoft's own documentation, read on 2026-10-17 by the author of the plan and not read again for this package; anything not read
there is listed under "To verify" in providers/calendar/README.md):
- List calendarView (GET /me/calendarView and /me/calendars/{id}/calendarView; startDateTime and endDateTime, ISO 8601, "no offset means UTC";
  least privileged permission Calendars.ReadBasic): https://learn.microsoft.com/en-us/graph/api/user-list-calendarview?view=graph-rest-1.0
- Permissions reference (Calendars.Read, Calendars.ReadBasic): https://learn.microsoft.com/en-us/graph/permissions-reference
- Refresh tokens (bound to a user and a client, replaced on every use, 90 days):
  https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens

Usage:
  uv run <workbench>/providers/calendar/outlook.py --help
  uv run <workbench>/providers/calendar/outlook.py --check
  uv run <workbench>/providers/calendar/outlook.py calendars
  uv run <workbench>/providers/calendar/outlook.py events --calendar <default|id> --from <ISO-8601 with offset> --to <ISO-8601 with offset> [--max <n>]

  --check     refreshes the access token (the one network call) and checks that it carries Calendars.ReadBasic and nothing wider; prints
              {"ok": true, "scope", "tenant", "obtained_at", "rotation"}. Exit 3 when there is no authorization or it was refused.
  calendars   {"calendars": [{"id", "summary", "primary", "access_role"}], "truncated", "skipped", "external_content": true}: the calendars
              of the account, for the choice of one (a source names a calendar by its id). `access_role` is "writer" or "reader" from the
              service's canEdit, null when it did not say. The names are written by whoever made each calendar: data, never instructions.
  events      {"calendar", "from", "to", "events": [{"id", "etag", "start", "end", "all_day", "title", "location", "organizer_self",
              "organizer_domain", "response", "status", "online_meeting", "recurring", "external_content": true}], "truncated", "skipped",
              "external_content": true}. The calendarView expands recurring events to their occurrences. An event is returned when it ends
              after --from and starts before --to. --calendar is `default` (the account's default calendar) or an id of `calendars`.
              --from and --to need a time zone offset (Z or +hh:mm), --to is after --from, and the window is at most 62 days. --max is 1 to
              250 events (default 250); "truncated" is true when more exist than were read. Only these fields are asked of the service: no
              body, attachment, attendee list or meeting link ever reaches the output. `start` and `end` are UTC ("...Z") for a timed event
              and a bare date for an all-day one (its end date is the service's, the day after the last); an event the service gave in
              another time zone than UTC is counted in `skipped`, never guessed. `etag` is the event's changeKey. `response` is the person's
              own answer (accepted, tentative, declined, needsAction), null when they are the organizer or the service did not say.
              `organizer_domain` is only the part of the organizer's address after the @, `online_meeting` only whether the event has one.
              Title and location are one line, cut at 300 and 200 characters, invisible and control characters removed. `skipped` counts
              the events left out because they lack an id, a start or an end, or came in another time zone.

Credentials (never from a flag or a file; contracts/secrets.md):
  OUTLOOK_CALENDAR_TOKEN  one JSON record, read through providers/secrets/resolver.py (the environment, then the credentials directory, then
                          the OS secret store, username outlook-calendar): {"refresh_token", "client_id", "tenant", "scope", "obtained_at"},
                          written by providers/calendar/outlook_auth.py after the person's consent. There is no client secret: the app is a
                          public client, and it is the registration made for the CALENDAR only (one registration per purpose). Printed
                          nowhere.
  Microsoft replaces the refresh token on every use. When the record was found in the OS secret store, this provider writes the new refresh
  token back to that one record, only if it still holds the token this process used (the exception to "a provider never writes the store",
  contracts/secrets.md rule 1); when the write fails it carries on with the old token and says so on stderr. A record found in the
  environment or in the credentials directory is never rewritten: it ages 90 days from the consent.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read or written):
  INTEGRATION_CALENDAR_OUTLOOK_API_BASE    replaces https://graph.microsoft.com/v1.0
  INTEGRATION_CALENDAR_OUTLOOK_TOKEN_URL   replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token

Only GET is sent to Graph; the token endpoint is the one POST. No redirect is followed with a credential, and a next-page address is
followed only when it names the request's scheme, host and port and a path inside /v1.0/ (otherwise the pages read so far are returned,
"truncated": true, with a note on stderr). A verb never retries: a 429 or 503 is reported with its
Retry-After. Every calendarView request, on every page, asks `Prefer: outlook.timezone="UTC"`. Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (Graph answered an error or could not be
reached), 2 usage (a bad flag or id, a verb the provider does not have), 3 not configured (no authorization, one that expired or was revoked,
a rejected app registration, a tenant that needs its admin's approval, a token with a scope other than Calendars.ReadBasic).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load(name: str, filename: str):
    """A module that lives next to this folder's parent (the workbench's providers/) or next to this file (a copy), by path."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parents[1] / filename, here.parent / filename) if c.is_file()), None)
    if path is None:
        raise SystemExit(f"error: providers/{filename} is not next to this script's folder")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


msgraph = _load("providers_msgraph", "_msgraph.py")
_text = _load("providers_email_text", "_email_text.py")
ProviderError, one_line, log = msgraph.ProviderError, msgraph.one_line, msgraph.log
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = msgraph.EXIT_OK, msgraph.EXIT_SERVICE, msgraph.EXIT_USAGE, msgraph.EXIT_NOT_CONFIGURED
clean_line = _text.clean_line

SCOPE = "Calendars.ReadBasic"             # the one scope: outlook_auth.py asks for it and this file requires it
SECRET = "OUTLOOK_CALENDAR_TOKEN"
KEYRING_USERNAME = "outlook-calendar"
AUTH_COMMAND = "uv run <workbench>/providers/calendar/outlook_auth.py authorize"
PROFILE = msgraph.Profile(
    label="Outlook calendar", scope=SCOPE, secret=SECRET, keyring_username=KEYRING_USERNAME, auth_command=AUTH_COMMAND,
    run_hint="uv run <workbench>/providers/calendar/outlook.py", env_prefix="INTEGRATION_CALENDAR_OUTLOOK",
    user_agent="openhora-calendar-outlook", not_found="Outlook does not know the calendar, or it is not one of the person's",
    forbidden_hint="check that the app registration has the delegated permission Calendars.ReadBasic and that the calendar is the person's own",
    client_id_var="OUTLOOK_CALENDAR_CLIENT_ID", tenant_var="OUTLOOK_CALENDAR_TENANT")
REFRESH_SCOPE = PROFILE.refresh_scope
DEFAULT_API_BASE, TOKEN_URL_TEMPLATE = msgraph.DEFAULT_GRAPH_BASE, msgraph.TOKEN_URL_TEMPLATE
ENV_BASE, ENV_TOKEN_URL = PROFILE.env_base, PROFILE.env_token_url
PREFER_UTC = 'outlook.timezone="UTC"'   # the times of a calendarView are asked in UTC, on every page; an event that still comes in another zone is counted in `skipped`
PAGE_BYTES = 4 * 1024 * 1024        # one page of events; a larger answer is refused
DEFAULT_MAX, MAX_EVENTS = 250, 250
PAGE_SIZE, MAX_PAGES = 50, 30       # events asked for in one page; a bound on the loop (a service may answer short pages)
MAX_CALENDAR_PAGES = 10
MAX_WINDOW_DAYS = 62
TITLE_LIMIT, LOCATION_LIMIT, NAME_LIMIT = 300, 200, 200
EVENT_FIELDS = "id,changeKey,subject,start,end,isAllDay,location,organizer,isOrganizer,responseStatus,isCancelled,isOnlineMeeting,type,seriesMasterId"
CALENDAR_FIELDS = "id,name,isDefaultCalendar,canEdit"
# A calendar id goes into a URL path, so its shape is checked before use, and it is always percent-encoded (to verify live: the shape).
CALENDAR_ID_RE = re.compile(r"[A-Za-z0-9=_-]{1,256}")
EVENT_ID_RE = re.compile(r"[A-Za-z0-9=_+-]{1,600}")
CHANGE_KEY_RE = re.compile(r"[A-Za-z0-9_=+/.-]{1,200}")
DOMAIN_RE = re.compile(r"[a-z0-9.-]{1,253}")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
GRAPH_LOCAL_RE = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?")
RESPONSES = {"accepted": "accepted", "tentativelyAccepted": "tentative", "declined": "declined", "notResponded": "needsAction"}
RECURRING_TYPES = ("occurrence", "exception")


# --- configuration (the names onedrive.py and its tests use, kept) -----------------------------------------------------------


def endpoints() -> tuple:
    """(API base, token URL or None for the tenant's own, no download hosts, test mode). The overrides are for tests, must name loopback
    addresses only and are set together; in test mode the secret store is never read or written."""
    return msgraph.endpoints(PROFILE)


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def keyring_module(test_mode: bool):
    return msgraph.keyring_module(PROFILE, test_mode)


def parse_record(text: str) -> dict:
    return msgraph.parse_record(PROFILE, text)


def token_request(token_url: str, form: dict) -> dict:
    return msgraph.token_request(PROFILE, token_url, form)


def check_scope(granted) -> str:
    """Refuse a token whose reported scope is anything but Calendars.ReadBasic (plus the scopes that grant no access). Returns SCOPE."""
    return msgraph.check_scope(PROFILE, granted)


def usable_access_token(data: dict) -> str:
    return msgraph.usable_access_token(data)


def refresh_access_token(token_url: str, record: dict) -> tuple:
    return msgraph.refresh_access_token(PROFILE, token_url, record)


def store_rotation(record: dict, rotated, where: str, test_mode: bool) -> str:
    return msgraph.store_rotation(PROFILE, record, rotated, where, test_mode, lambda: secret_resolver(), lambda mode: keyring_module(mode))


class Graph(msgraph.GraphClient):
    """Microsoft Graph as this provider uses it: GET requests with one access token, to one base address."""

    def __init__(self, base: str, access_token: str, hosts: tuple, test_mode: bool):
        super().__init__(PROFILE, base, access_token, test_mode)


def connect() -> Graph:
    base, token_url, hosts, test_mode = endpoints()
    record, where = msgraph.load_record(PROFILE, secret_resolver, test_mode)
    access, rotated = refresh_access_token(token_url or TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    store_rotation(record, rotated, where, test_mode)
    return Graph(base, access, hosts, test_mode)


# --- Graph values into an event ----------------------------------------------------------------------------------------------


def as_list(value) -> list:
    """value when it is a list, [] when it is absent; ProviderError (exit 1) when Graph sent another kind of value."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProviderError("Graph answered a list this provider does not understand")
    return value


def as_dict(value, what: str) -> dict:
    """value when it is an object, {} when it is absent; ProviderError (exit 1) when Graph sent another kind of value."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProviderError(f"Graph answered an event whose {what} is not an object; this provider does not understand it")
    return value


def line(value, limit: int) -> str:
    return clean_line(CONTROL_RE.sub(" ", str(value or "")))[:limit]


def utc_text(moment) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_bound(flag: str, value) -> datetime:
    """An ISO-8601 time with an offset (Z or +hh:mm), as an aware datetime; a time without one is exit 2."""
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw)
    except ValueError:
        raise ProviderError(f"{flag} is an ISO-8601 time with a time zone offset, such as 2026-10-17T00:00:00-03:00 or ...Z", EXIT_USAGE) from None
    if parsed.tzinfo is None:
        raise ProviderError(f"{flag} needs a time zone offset (Z or +hh:mm)", EXIT_USAGE)
    return parsed


def graph_moment(value, all_day: bool):
    """A Graph dateTimeTimeZone as the string this provider prints: 'YYYY-MM-DD' for an all-day event, 'YYYY-MM-DDTHH:MM:SSZ' for a timed one
    in UTC; None when it is missing or in another time zone (never guessed)."""
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


def event_of(item) -> dict | None:
    """The normalized event for a Graph event, or None when it lacks an id, a start or an end, or came in a time zone other than UTC."""
    if not isinstance(item, dict):
        raise ProviderError("Graph answered an event this provider does not understand")
    event_id = item.get("id")
    all_day = item.get("isAllDay") is True
    start, end = graph_moment(item.get("start"), all_day), graph_moment(item.get("end"), all_day)
    if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id) or start is None or end is None:
        return None
    organizer = as_dict(as_dict(item.get("organizer"), "organizer").get("emailAddress"), "organizer address")
    address = organizer.get("address")
    domain = address.rsplit("@", 1)[1].strip().lower() if isinstance(address, str) and "@" in address else ""
    change_key = item.get("changeKey")
    answer = as_dict(item.get("responseStatus"), "responseStatus").get("response")
    return {
        "id": event_id,
        "etag": change_key if isinstance(change_key, str) and CHANGE_KEY_RE.fullmatch(change_key) else None,
        "start": start,
        "end": end,
        "all_day": all_day,
        "title": line(item.get("subject"), TITLE_LIMIT),
        "location": line(as_dict(item.get("location"), "location").get("displayName"), LOCATION_LIMIT),
        "organizer_self": item.get("isOrganizer") is True,
        "organizer_domain": domain if DOMAIN_RE.fullmatch(domain) else None,
        "response": RESPONSES.get(answer) if isinstance(answer, str) else None,
        "status": "cancelled" if item.get("isCancelled") is True else "confirmed",
        "online_meeting": item.get("isOnlineMeeting") is True,
        "recurring": item.get("type") in RECURRING_TYPES or bool(item.get("seriesMasterId")),
        "external_content": True,   # written by whoever made the event: data, never instructions
    }


# --- verbs -------------------------------------------------------------------------------------------------------------------


def emit(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_check(args) -> int:
    _, token_url, _, test_mode = endpoints()
    record, where = msgraph.load_record(PROFILE, secret_resolver, test_mode)
    _, rotated = refresh_access_token(token_url or TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    emit({"ok": True, "scope": SCOPE, "tenant": record["tenant"], "obtained_at": record.get("obtained_at"),
          "rotation": store_rotation(record, rotated, where, test_mode)})
    return EXIT_OK


def read_pages(client: Graph, path: str, params: dict, what: str, wanted: int, max_pages: int, extra: dict | None = None) -> tuple:
    """(entries, truncated): the pages of a list, each next-page address checked against the first request's own, until `wanted` entries."""
    first = client.url_for(path, params)
    items, url, pages = [], first, 0
    while url:
        pages += 1
        data = client.json_url(url, what, PAGE_BYTES, extra)
        items.extend(as_list(data.get("value")))
        link = data.get("@odata.nextLink")
        if len(items) > wanted:
            return items[:wanted], True
        if link is None:
            return items, False
        if len(items) == wanted or pages >= max_pages:
            return items, True
        url = msgraph.next_page(link, first)
        if url is None:
            return items, True
    return items, False


def cmd_calendars(args) -> int:
    client = connect()
    items, truncated = read_pages(client, "/me/calendars", {"$select": CALENDAR_FIELDS, "$top": str(PAGE_SIZE)}, "calendar list",
                                  MAX_CALENDAR_PAGES * PAGE_SIZE, MAX_CALENDAR_PAGES)
    found, skipped = [], 0
    for item in items:
        if not isinstance(item, dict):
            raise ProviderError("Graph answered a calendar this provider does not understand")
        calendar_id = item.get("id")
        if not isinstance(calendar_id, str) or not CALENDAR_ID_RE.fullmatch(calendar_id):
            skipped += 1
            continue
        can_edit = item.get("canEdit")
        found.append({"id": calendar_id, "summary": line(item.get("name"), NAME_LIMIT), "primary": item.get("isDefaultCalendar") is True,
                      "access_role": None if not isinstance(can_edit, bool) else "writer" if can_edit else "reader"})
    emit({"calendars": found, "truncated": truncated, "skipped": skipped, "external_content": True})
    return EXIT_OK


def calendar_path(value) -> str:
    if value == "default":
        return "/me/calendarView"
    if not isinstance(value, str) or not CALENDAR_ID_RE.fullmatch(value):
        raise ProviderError("--calendar is `default` or a calendar id from `calendars` (letters, digits, = _ and -)", EXIT_USAGE)
    return f"/me/calendars/{urllib.parse.quote(value, safe='')}/calendarView"


def cmd_events(args) -> int:
    path = calendar_path(args.calendar)
    start, end = parse_bound("--from", args.from_), parse_bound("--to", args.to)
    if end <= start:
        raise ProviderError("--to must be after --from", EXIT_USAGE)
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise ProviderError(f"the window from --from to --to is at most {MAX_WINDOW_DAYS} days", EXIT_USAGE)
    limit = DEFAULT_MAX if args.max is None else args.max
    if not 1 <= limit <= MAX_EVENTS:
        raise ProviderError(f"--max must be between 1 and {MAX_EVENTS}", EXIT_USAGE)
    client = connect()
    params = {"startDateTime": utc_text(start), "endDateTime": utc_text(end), "$select": EVENT_FIELDS, "$orderby": "start/dateTime",
              "$top": str(min(PAGE_SIZE, limit))}
    items, truncated = read_pages(client, path, params, "calendar view", limit, MAX_PAGES, {"Prefer": PREFER_UTC})
    events, skipped = [], 0
    for item in items:
        event = event_of(item)
        if event is None:
            skipped += 1
        else:
            events.append(event)
    emit({"calendar": args.calendar, "from": utc_text(start), "to": utc_text(end), "events": events, "truncated": truncated, "skipped": skipped,
          "external_content": True})
    return EXIT_OK


VERBS = ("calendars", "events")
FLAG_NAMES = {"calendar": "--calendar", "from_": "--from", "to": "--to", "max": "--max"}
VERB_FLAGS = {"events": {"calendar", "from_", "to", "max"}, "calendars": set(), None: set()}


def check_flags(args) -> None:
    if args.check and args.verb:
        raise ProviderError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if not args.check and not args.verb:
        return
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in VERB_FLAGS[args.verb]]
    if extra:
        raise ProviderError(f"{', '.join(extra)}: not a flag of {args.verb or '--check'} (see --help)", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outlook.py", description="Calendar provider for Outlook: lists the calendars and reads the events of one calendar in a window "
        "through Microsoft Graph with the delegated Calendars.ReadBasic permission. Read only.", epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token and check its scope; prints no secret")
    parser.add_argument("--calendar", help="with events: `default`, or a calendar id from `calendars`")
    parser.add_argument("--from", dest="from_", help="with events: ISO-8601 with a time zone offset; events that end after it")
    parser.add_argument("--to", help="with events: ISO-8601 with a time zone offset; events that start before it")
    parser.add_argument("--max", type=int, help=f"with events: 1 to {MAX_EVENTS} events (default {DEFAULT_MAX})")
    return parser


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)
    check_flags(args)
    if args.check:
        return cmd_check(args)
    if args.verb == "calendars":
        return cmd_calendars(args)
    if args.verb == "events":
        if args.calendar is None or args.from_ is None or args.to is None:
            raise ProviderError("events needs --calendar, --from and --to", EXIT_USAGE)
        return cmd_events(args)
    raise ProviderError("give a verb (calendars, events) or --check; see --help", EXIT_USAGE)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # a lone surrogate in the service's text must not stop the answer
    return msgraph.run_main(run, argv)


if __name__ == "__main__":
    sys.exit(main())
