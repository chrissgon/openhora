#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Calendar writer for Google Calendar: an implementation of the class writer:calendar (package W1, SPEC-SECRETARY-WRITES). It creates, changes and removes one
event of one calendar of the person's own Google account, and reads one event back. It is called only by the effect module runtime/effect_calendar.py (the three
write verbs, after the person approved the exact request) and by one read-only seam of the runtime (`event-get`, and the dry run of the others); never by a
skill, a run or a handler. Nobody is told: every write sends `sendUpdates=none`, and no attendee is ever sent.

Sources (Google's own documentation, accessed 2026-10-18; what is not read there is listed under "To verify" in providers/writer/README.md):
- Events: insert (POST https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events; `sendUpdates`: all, externalOnly, none; accepted scopes
  calendar, calendar.events, calendar.app.created, calendar.events.owned): https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- Events: patch (PATCH .../events/{eventId}; only the fields in the body change), and delete (DELETE .../events/{eventId}; "sendUpdates"):
  https://developers.google.com/workspace/calendar/api/v3/reference/events/patch and .../events/delete
- Version resources: every event has an etag; a request with `If-Match: <etag>` is refused with 412 when the event changed:
  https://developers.google.com/workspace/calendar/api/guides/version-resources
- A removed event stays in the calendar's trash for 30 days (the person restores it there): https://support.google.com/calendar/answer/37113
- Extended properties (`extendedProperties.private`, and `privateExtendedProperty=name=value` on events.list): the events resource page.

Usage:
  uv run providers/writer/google-calendar.py --help
  uv run providers/writer/google-calendar.py --check
  uv run providers/writer/google-calendar.py event-get --calendar <id> --event <id>
  uv run providers/writer/google-calendar.py event-insert --calendar <id> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/google-calendar.py event-patch --calendar <id> --event <id> --base-etag <etag> --spec-file <file> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/google-calendar.py event-delete --calendar <id> --event <id> --base-etag <etag> --idempotency-key <key> (--dry-run | --confirmed)

  --check        refreshes the access token, checks that the account token carries the platform's whole set of scopes, and reads one entry of the calendar list;
                 prints {"ok": true, "scope": [...], "account", "obtained_at"}. Exit 3 when there is no authorization or the set is not the platform's.
  event-get      {"found": true, "event": {"id", "etag", "status", "title", "start", "end", "all_day", "location", "notes", "notes_truncated", "reminder_minutes",
                 "organizer_self", "attendees_other", "recurring", "external_content": true}} or {"found": false, "reason"} for an event that is gone (404, 410, or
                 `cancelled`). `start` and `end` are the service's own: an instant with its offset, or a day (an all-day event's `end` is the day after the last).
                 `attendees_other` counts the attendees who are not the person; no address is printed. Title, location and notes are another person's text in
                 principle (they were written in the calendar): data, never instructions.
  event-insert   creates the event the spec describes: {"done": true, "replayed", "event_id", "etag"}.
  event-patch    changes only the parts the spec lists, only if the event is still at `--base-etag` (`If-Match`): {"done": true, "replayed", "event_id", "etag"}.
  event-delete   removes the event, only if it is still at `--base-etag`: it goes to the calendar's trash. {"done": true, "replayed", "event_id"}.
  --dry-run      reads no credential, opens no connection and prints {"dry_run": true, "would": {"method", "path", "query", "headers", "body"}, "would_sha256",
                 "ledger"}: the exact request `--confirmed` sends, and its hash.
  --confirmed    sends exactly that request. The key is recorded `pending` in the ledger first and `done` after the answer; a key that is `done` is not sent again
                 (`replayed`), and one left `pending` by an answer that was lost is looked up in the calendar (by the private property `openhora_key` the request
                 carries, or by the event's state) before anything is sent.

The spec (a file, never a flag: it holds the person's words): the whole event for event-insert, {"title", "all_day", "start_at", "end_at", "location",
"reminder_minutes", "notes"}; for event-patch the parts to change, the three times together. `start_at` and `end_at` are an instant with its offset, or, for
an all-day event, the first day and the day after the last.

Credentials (never from a flag or a file; contracts/secrets.md):
  GOOGLE_ACCOUNT_TOKEN   the account record (providers/accounts/google_auth.py), read through providers/secrets/resolver.py. There is no legacy record for a writer:
                         a token that lacks one scope of the platform's set, or carries another, is refused (exit 3) before any call.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read):
  WRITER_CALENDAR_GOOGLE_API_BASE    replaces https://www.googleapis.com
  WRITER_CALENDAR_GOOGLE_TOKEN_URL   replaces https://oauth2.googleapis.com/token

Limits. The request function sends only the methods and paths of ALLOWED, and refuses anything else (limits L57, L58); the one removal is an event's, which Google
sends to the calendar's trash for 30 days; no event, calendar or file is ever removed for good. No redirect is followed. A verb never retries: a 429 or 503 is
reported with its Retry-After and nothing is changed. Every request has a 60-second timeout. Prints one JSON object on stdout; diagnostics on stderr. Exit codes:
0 ok, 1 refused with nothing changed (the service said no, or the event changed since it was read: the message starts with `changed:`), 2 usage, 3 not configured,
4 unknown (the request may have landed: send the same key again).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException    # by name: this module's own http() function shadows the module
from pathlib import Path

SERVES = "writer:calendar"
IMPLEMENTATION = "google-calendar"
DEFAULT_API_BASE = "https://www.googleapis.com"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
ENV_BASE = "WRITER_CALENDAR_GOOGLE_API_BASE"
ENV_TOKEN_URL = "WRITER_CALENDAR_GOOGLE_TOKEN_URL"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
HTTP_TIMEOUT_SECONDS = 60
ANSWER_LIMIT_BYTES = 1024 * 1024
KEY_PROPERTY = "openhora_key"        # the private extended property every request writes: a lost answer is looked up by it
# The only requests this writer sends (limits L57 and L58): a method and a full-match pattern of the path, as the request function sees it (ids are percent-encoded).
ALLOWED = (("GET", r"/calendar/v3/users/me/calendarList"),
           ("GET", r"/calendar/v3/calendars/[^/]+/events"),
           ("GET", r"/calendar/v3/calendars/[^/]+/events/[^/]+"),
           ("POST", r"/calendar/v3/calendars/[^/]+/events"),
           ("PATCH", r"/calendar/v3/calendars/[^/]+/events/[^/]+"),
           ("DELETE", r"/calendar/v3/calendars/[^/]+/events/[^/]+"))
LIST_CALENDARS, LIST_EVENTS, GET_EVENT, INSERT, PATCH, REMOVE = ALLOWED[0], ALLOWED[1], ALLOWED[2], ALLOWED[3], ALLOWED[4], ALLOWED[5]
GET_FIELDS = ("id,etag,status,summary,description,location,start,end,reminders(useDefault,overrides),organizer(self),attendees(self),recurrence,"
              "recurringEventId,extendedProperties(private)")
RESULT_FIELDS = "id,etag,status"
NOTES_SHOWN = 2000

_SECRET_VALUES: list = []   # every credential this process held: scrubbed from any text before it is printed


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


_google = _shared("providers_google_account", "_google.py")
_calendar = _shared("providers_writer_calendar", "_writer_calendar.py")
ProviderError = _calendar.WriterError
EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_calendar.EXIT_OK, _calendar.EXIT_REFUSED, _calendar.EXIT_USAGE,
                                                                        _calendar.EXIT_NOT_CONFIGURED, _calendar.EXIT_UNKNOWN)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
INSTANT_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})")


def scrub(text: str) -> str:
    for value in _SECRET_VALUES:
        text = text.replace(value, "<hidden>")
    return _google.scrub(text)


def one_line(text, limit: int = 300) -> str:
    """Third-party text on one line: control characters removed, the space folded, cut at `limit`, no credential in it."""
    return scrub(" ".join(CONTROL_RE.sub(" ", str(text if text is not None else "")).split()))[:limit]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


# --- configuration -----------------------------------------------------------------------------------------------------------


def endpoints() -> tuple:
    """(API base, token URL, test mode). The overrides are for tests and must be loopback URLs, both set together."""
    api, token = os.environ.get(ENV_BASE), os.environ.get(ENV_TOKEN_URL)
    if not api and not token:
        return DEFAULT_API_BASE, DEFAULT_TOKEN_URL, False
    if not (api and token):
        raise ProviderError(f"{ENV_BASE} and {ENV_TOKEN_URL} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((ENV_BASE, api), (ENV_TOKEN_URL, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise ProviderError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    return api.rstrip("/"), token, True


def secret_resolver():
    """The workbench's one secret resolver, by path: next to this file first (a copy run from a job folder), then providers/secrets/resolver.py."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py") if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def open_session():
    """(the API base, an access token) from the account record: the whole platform set, or exit 3. There is no legacy record for a writer."""
    base, token_url, test_mode = endpoints()
    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=None, error=ProviderError)
    _google.hold(*(loaded.record[k] for k in _google.RECORD_TEXTS))
    data = _google.refresh_access_token(token_url, loaded.record, ProviderError)
    _SECRET_VALUES.append(data["access_token"])
    return base, data["access_token"], loaded.record


# --- HTTP --------------------------------------------------------------------------------------------------------------------


class Lost(ProviderError):
    """The request may have reached the service and its answer was lost: exit 4."""

    def __init__(self, message):
        super().__init__(message, EXIT_UNKNOWN)


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries a credential to an address that was checked."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        lost = Lost if req.get_method() != "GET" else ProviderError      # a write that was answered with a redirect reached the service: its outcome is not known
        raise lost(f"refusing to follow a {code} redirect on {req.get_method()} {urllib.parse.urlparse(req.full_url).path}; the request carries a credential")


OPENER = urllib.request.build_opener(RefuseRedirect)


def http(method: str, url: str, headers: dict, body, sent_on_error: bool) -> tuple:
    """One request; (status, at most ANSWER_LIMIT_BYTES + 1 bytes of the body, the Retry-After header or "") for any HTTP answer. A failure before the request
    could have reached the service is ProviderError (exit 1); one after it may have is Lost (exit 4) when `sent_on_error`."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    path = urllib.parse.urlparse(url).path
    unknown = Lost if sent_on_error else ProviderError
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(ANSWER_LIMIT_BYTES + 1), ""
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(65536), one_line(exc.headers.get("Retry-After"), 40)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError) or "Name or service not known" in str(exc.reason):
            raise ProviderError(f"cannot reach Google on {method} {path}: nothing was sent") from None
        raise unknown(f"the connection to Google failed on {method} {path} ({one_line(exc.reason, 80)}): the request may or may not have landed") from None
    except TimeoutError:
        raise unknown(f"Google timed out on {method} {path} after {HTTP_TIMEOUT_SECONDS} s: the request may or may not have landed") from None
    except OSError as exc:
        raise unknown(f"the connection to Google failed on {method} {path} ({type(exc).__name__}): the request may or may not have landed") from None
    except (ValueError, HTTPException) as exc:
        raise unknown(f"the request {method} {path} could not be made or read ({type(exc).__name__})") from None


def request(entry: tuple, base: str, token: str, path: str, query: dict, headers: dict, body=None, sent_on_error: bool = False) -> tuple:
    """The one function that sends a request to the Calendar API. `entry` must be a pair of ALLOWED and `path` must match its pattern; anything else is refused
    before a connection is opened. Returns (status, body bytes, Retry-After)."""
    method, pattern = entry
    if entry not in ALLOWED or not re.fullmatch(pattern, path):
        raise ProviderError(f"this writer does not send {method} {path}: it is not a request of its allow-list", EXIT_USAGE)
    url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
    sent = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "openhora-writer-calendar-google", **headers}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json; charset=utf-8"
    return http(method, url, sent, data, sent_on_error)


def failure(status: int, body: bytes, retry: str, what: str) -> ProviderError:
    reasons, message = "", ""
    try:
        error = json.loads(body).get("error")
        if isinstance(error, dict):
            message = one_line(error.get("message"), 200)
            listed = error.get("errors")
            reasons = ",".join(one_line(e.get("reason"), 40) for e in (listed if isinstance(listed, list) else []) if isinstance(e, dict))
    except (ValueError, AttributeError):
        pass
    detail = f": {message}{f' [{reasons}]' if reasons else ''}" if message or reasons else ""
    if status == 401:
        return ProviderError(f"Google rejected the access token ({what}){detail}; run: {_google.AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
    if status in (412, 404, 410):
        return ProviderError(f"changed: the event is not as it was read ({what}, {status}){detail}", EXIT_REFUSED, status)
    if status in (429, 503) or (status == 403 and "ateLimit" in reasons):
        after = f" Retry-After: {retry}." if retry else ""
        return ProviderError(f"Google asked to slow down ({status} on {what}){detail}.{after} Nothing was changed or retried", EXIT_REFUSED, status)
    if status == 403:
        return ProviderError(f"Google refused the request ({what}){detail}; check that the Google Calendar API is enabled and that the calendar is the person's own",
                             EXIT_REFUSED, status)
    if status >= 500:
        return Lost(f"Google answered {status} ({what}){detail}: the request may or may not have landed")
    return ProviderError(f"Google returned {status} ({what}){detail}", EXIT_REFUSED, status)


# --- checking the ids and the arguments ---------------------------------------------------------------------------------------


def calendar_id(value) -> str:
    if not isinstance(value, str) or not _calendar.CALENDAR_ID.fullmatch(value):
        raise ProviderError("--calendar is a Google calendar id (letters, digits and . _ % + @ = -, at most 300 characters)", EXIT_USAGE)
    return value


def event_id(value) -> str:
    if not isinstance(value, str) or not _calendar.EVENT_ID.fullmatch(value):
        raise ProviderError("--event is an event id (letters, digits and = _ + -)", EXIT_USAGE)
    return value


def base_etag(value) -> str:
    if not isinstance(value, str) or not _calendar.ETAG.fullmatch(value):
        raise ProviderError("--base-etag is the etag the event had when it was read", EXIT_USAGE)
    return value


def idempotency_key(value) -> str:
    if not isinstance(value, str) or not _calendar.KEY.fullmatch(value):
        raise ProviderError("--idempotency-key is letters, digits, dots, hyphens and underscores, at most 128 characters", EXIT_USAGE)
    return value


def events_path(calendar: str, event=None) -> str:
    base = f"/calendar/v3/calendars/{urllib.parse.quote(calendar, safe='')}/events"
    return base if event is None else f"{base}/{urllib.parse.quote(event, safe='')}"


# --- the requests, built without a connection -----------------------------------------------------------------------------------


def moment(spec: dict, name: str, patch: bool) -> dict:
    """A start or an end. In a patch the other form is set to null, so that a timed event turned all-day (or the other way) keeps no part of the old form."""
    if spec["all_day"]:
        return {"date": spec[name], **({"dateTime": None} if patch else {})}
    return {"dateTime": spec[name], **({"date": None} if patch else {})}


def reminders_of(minutes) -> dict:
    return {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes}]}


def body_of(spec: dict, key: str, whole: bool) -> dict:
    """The body of an insert (the whole event) or of a patch (the parts in the spec). The private property `openhora_key` is in both."""
    out = {}
    if "title" in spec:
        out["summary"] = spec["title"]
    if "start_at" in spec:
        out["start"], out["end"] = moment(spec, "start_at", not whole), moment(spec, "end_at", not whole)
    if "location" in spec and (spec["location"] or not whole):
        out["location"] = spec["location"]
    if "notes" in spec and (spec["notes"] or not whole):
        out["description"] = spec["notes"]
    if spec.get("reminder_minutes") is not None:
        out["reminders"] = reminders_of(spec["reminder_minutes"])
    out["extendedProperties"] = {"private": {KEY_PROPERTY: key}}
    return out


def build(verb: str, args) -> dict:
    """The request a verb sends, as {"entry", "method", "path", "query", "headers", "body"}: checked arguments in, no credential, no connection."""
    calendar, key = calendar_id(args.calendar), idempotency_key(args.idempotency_key)
    if verb == "event-insert":
        spec = _calendar.read_spec(args.spec_file, "create")
        entry, path, headers, body = INSERT, events_path(calendar), {}, body_of(spec, key, True)
    elif verb == "event-patch":
        spec = _calendar.read_spec(args.spec_file, "change")
        entry, path, headers, body = PATCH, events_path(calendar, event_id(args.event)), {"If-Match": base_etag(args.base_etag)}, body_of(spec, key, False)
    else:
        entry, path, headers, body = REMOVE, events_path(calendar, event_id(args.event)), {"If-Match": base_etag(args.base_etag)}, None
    return {"entry": entry, "method": entry[0], "path": path, "query": {"sendUpdates": "none", "fields": RESULT_FIELDS} if verb != "event-delete"
            else {"sendUpdates": "none"}, "headers": headers, "body": body}


def would_of(built: dict) -> dict:
    return {k: built[k] for k in ("method", "path", "query", "headers", "body")}


# --- the event as a service printed it -----------------------------------------------------------------------------------------


def instant(text) -> str | None:
    found = INSTANT_RE.fullmatch(text) if isinstance(text, str) else None
    return found.group(1) + found.group(2) if found else None


def read_event(item) -> dict:
    """The event as `event-get` prints it. ProviderError (exit 1) when its times are not in a form this writer understands."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise ProviderError("Google answered an event this writer does not understand")
    start, end = (item.get(k) if isinstance(item.get(k), dict) else {} for k in ("start", "end"))
    all_day = "date" in start
    if all_day:
        first, last = start.get("date"), end.get("date")
        ok = all(isinstance(v, str) and _calendar.DAY.fullmatch(v) for v in (first, last))
    else:
        first, last = instant(start.get("dateTime")), instant(end.get("dateTime"))
        ok = first is not None and last is not None
    if not ok:
        raise ProviderError("Google answered an event whose times this writer does not understand")
    attendees = item.get("attendees") if isinstance(item.get("attendees"), list) else []
    reminders = item.get("reminders") if isinstance(item.get("reminders"), dict) else {}
    popup = next((o.get("minutes") for o in (reminders.get("overrides") or []) if isinstance(o, dict) and o.get("method") == "popup"
                  and type(o.get("minutes")) is int), None)
    notes = str(item.get("description") or "").replace("\r\n", "\n").replace("\r", "\n")
    return {"id": item["id"], "etag": one_line(item.get("etag"), 200) or None, "status": one_line(item.get("status"), 20) or "confirmed",
            "title": one_line(item.get("summary"), 300), "start": first, "end": last, "all_day": all_day, "location": one_line(item.get("location"), 200),
            "notes": scrub("".join(c for c in notes if c in "\n\t" or not CONTROL_RE.match(c)))[:NOTES_SHOWN], "notes_truncated": len(notes) > NOTES_SHOWN,
            "reminder_minutes": popup if reminders.get("useDefault") is False else None,
            "organizer_self": (item.get("organizer") or {}).get("self") is True if isinstance(item.get("organizer"), dict) else False,
            "attendees_other": sum(1 for a in attendees if not (isinstance(a, dict) and a.get("self") is True)),
            "recurring": bool(item.get("recurrence")) or bool(item.get("recurringEventId")), "external_content": True}


def fetch_event(base: str, token: str, calendar: str, event: str):
    """The event as the service holds it, or None when it is gone (404, 410, or cancelled)."""
    status, body, retry = request(GET_EVENT, base, token, events_path(calendar, event), {"fields": GET_FIELDS}, {})
    if status in (404, 410):
        return None
    if status != 200:
        raise failure(status, body, retry, "GET event")
    try:
        item = json.loads(body)
    except ValueError:
        item = None
    if isinstance(item, dict) and item.get("status") == "cancelled":
        return None
    return item if isinstance(item, dict) else read_event(None)


# --- the verbs -----------------------------------------------------------------------------------------------------------------


def cmd_check(args) -> int:
    base, token, record = open_session()
    status, body, retry = request(LIST_CALENDARS, base, token, "/calendar/v3/users/me/calendarList", {"maxResults": 1, "fields": "items(id)"}, {})
    if status != 200:
        raise failure(status, body, retry, "GET calendarList")
    return emit({"ok": True, "scope": sorted(_google.PLATFORM_SCOPES), "account": record.get("account"), "obtained_at": record.get("obtained_at")})


def cmd_event_get(args) -> int:
    calendar, event = calendar_id(args.calendar), event_id(args.event)
    base, token, _ = open_session()
    item = fetch_event(base, token, calendar, event)
    if item is None:
        return emit({"found": False, "reason": "gone"})
    return emit({"found": True, "event": read_event(item)})


def landed(base: str, token: str, verb: str, args, key: str):
    """After an answer that was lost: whether the request of `key` is in the calendar. The facts of the event ({"event_id", "etag"}) when it is, else None."""
    calendar = calendar_id(args.calendar)
    if verb == "event-insert":
        status, body, retry = request(LIST_EVENTS, base, token, events_path(calendar),
                                      {"privateExtendedProperty": f"{KEY_PROPERTY}={key}", "maxResults": 2, "fields": "items(id,etag)"}, {})
        if status != 200:
            raise failure(status, body, retry, "GET events")
        items = (json.loads(body or b"{}").get("items") or [])
        return {"event_id": items[0].get("id"), "etag": items[0].get("etag")} if items and isinstance(items[0], dict) else None
    item = fetch_event(base, token, calendar, event_id(args.event))
    if verb == "event-delete":
        return {"event_id": args.event, "etag": None} if item is None else None
    if item is not None and ((item.get("extendedProperties") or {}).get("private") or {}).get(KEY_PROPERTY) == key:
        return {"event_id": item.get("id"), "etag": item.get("etag")}
    return None


def write(verb: str, args) -> int:
    built = build(verb, args)
    would, key = would_of(built), args.idempotency_key
    digest = _calendar.sha(_calendar.canonical(would))
    operation = {"event-insert": "create", "event-patch": "change", "event-delete": "cancel"}[verb]
    if args.dry_run:
        peeked = _calendar.ledger_peek(IMPLEMENTATION, key)
        return emit({"dry_run": True, "would": would, "would_sha256": digest, "ledger": (peeked or {}).get("status", "absent")})
    state, entry = _calendar.claim(IMPLEMENTATION, key, digest, operation)
    if state == "done":
        return emit({"done": True, "replayed": True, "event_id": entry.get("event_id"), "etag": entry.get("etag")})
    fresh = state == "new"      # this attempt made the key: until something may have been sent, a failure frees it. A key an earlier attempt left pending stays pending.
    try:
        base, token, _ = open_session()
    except BaseException:
        if fresh:
            _calendar.settle(IMPLEMENTATION, key, "released")
        raise
    if not fresh:               # an earlier attempt's answer was lost: look in the calendar before anything is sent
        try:
            found = landed(base, token, verb, args, key)
        except ProviderError as exc:
            raise Lost(f"an earlier attempt with this key did not say whether it landed, and the calendar cannot be looked up now ({exc}): the key stays "
                       "pending; send it again later") from None
        if found is not None:
            _record_done(key, found)
            return emit({"done": True, "replayed": True, **found})
    try:
        status, body, retry = request(built["entry"], base, token, built["path"], built["query"], built["headers"], built["body"], sent_on_error=True)
    except Lost:
        raise          # the key stays pending: sending it again looks in the calendar first
    except BaseException:
        _calendar.settle(IMPLEMENTATION, key, "released")      # nothing was sent (and, for a key an earlier attempt left pending, the calendar was looked up: it did not land)
        raise
    if status not in (200, 204):
        problem = failure(status, body, retry, f"{built['method']} event")
        if not isinstance(problem, Lost):
            _calendar.settle(IMPLEMENTATION, key, "released")      # the service said no: nothing changed, the key is free
        raise problem
    try:
        answer = json.loads(body) if body else {}
    except ValueError:
        answer = {}
    answer = answer if isinstance(answer, dict) else {}
    done = {"event_id": answer.get("id") or getattr(args, "event", None), "etag": answer.get("etag")}
    _record_done(key, done)
    return emit({"done": True, "replayed": False, **done})


def _record_done(key: str, facts: dict) -> None:
    """Record the key done. A ledger that cannot be written after the request landed does not turn it into a failure: the key stays pending, and the next
    request with it finds the event in the calendar."""
    try:
        _calendar.settle(IMPLEMENTATION, key, "done", **{k: v for k, v in facts.items() if isinstance(v, str)})
    except (ProviderError, OSError) as exc:
        log(f"warning: the request landed, and the ledger could not record it ({one_line(exc, 200)}): the key {key} stays pending")


VERBS = ("event-get", "event-insert", "event-patch", "event-delete")
FLAG_NAMES = {"calendar": "--calendar", "event": "--event", "base_etag": "--base-etag", "spec_file": "--spec-file", "idempotency_key": "--idempotency-key"}
VERB_FLAGS = {"event-get": {"calendar", "event"}, "event-insert": {"calendar", "spec_file", "idempotency_key"},
              "event-patch": {"calendar", "event", "base_etag", "spec_file", "idempotency_key"}, "event-delete": {"calendar", "event", "base_etag", "idempotency_key"},
              None: set()}


def check_flags(args) -> None:
    """A flag given to a verb that does not read it is a usage error, a required one that is missing too; --check takes no verb."""
    if args.check and args.verb:
        raise ProviderError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if args.check:
        return
    if not args.verb:
        raise ProviderError("give a verb (event-get, event-insert, event-patch, event-delete) or --check; see --help", EXIT_USAGE)
    wanted = VERB_FLAGS[args.verb]
    extra = [flag for dest, flag in FLAG_NAMES.items() if getattr(args, dest) is not None and dest not in wanted]
    if extra:
        raise ProviderError(f"{', '.join(extra)}: not a flag of {args.verb} (see --help)", EXIT_USAGE)
    missing = [FLAG_NAMES[dest] for dest in wanted if getattr(args, dest) is None]
    if missing:
        raise ProviderError(f"{args.verb} needs {', '.join(sorted(missing))}", EXIT_USAGE)
    if args.verb != "event-get" and bool(args.dry_run) == bool(args.confirmed):
        raise ProviderError(f"{args.verb} needs exactly one of --dry-run and --confirmed", EXIT_USAGE)
    if args.verb == "event-get" and (args.dry_run or args.confirmed):
        raise ProviderError("event-get is a read: it takes neither --dry-run nor --confirmed", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="google-calendar.py", description=__doc__.split("\n\n")[0], epilog=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verb", nargs="?", choices=list(VERBS), help="the action to run")
    parser.add_argument("--check", action="store_true", help="refresh a token, check its scope and read one calendar entry; prints no secret")
    parser.add_argument("--calendar", help="the calendar id")
    parser.add_argument("--event", help="the event id")
    parser.add_argument("--base-etag", dest="base_etag", help="the etag the event had when it was read")
    parser.add_argument("--spec-file", dest="spec_file", help="the file that holds the event, or the parts to change, as JSON")
    parser.add_argument("--idempotency-key", dest="idempotency_key", help="the key of this one request")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the exact request and its hash; read no credential, open no connection")
    parser.add_argument("--confirmed", action="store_true", help="send exactly that request")
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        check_flags(args)
        if args.check:
            return cmd_check(args)
        if args.verb == "event-get":
            return cmd_event_get(args)
        return write(args.verb, args)
    except ProviderError as exc:
        log(f"error: {scrub(str(exc))}")
        return exc.code
    except Exception as exc:     # last resort: no traceback, which can hold a header or a body; only the kind of the failure
        log(f"error: unexpected {type(exc).__name__}; nothing was changed")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
