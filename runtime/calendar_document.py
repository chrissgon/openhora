#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of a change to the person's own calendar, and nothing that writes (package W1): what the step kind `calendar-event` builds and the effect kind
`calendar` approves. The effect document (its keys, its checks, the credential scan of the words the person gave), the card the person reads, the one line that
says what is approved, the closed facts a decision's payload records, and the arguments of the writer's verbs. It holds no function that calls a provider or
executes an effect: that is runtime/effect_calendar.py, reached from the operation `approve` only. The step kind imports this module and not that one, so a step
kind has no function in reach that could write (limit L30; limit L55).

The document. `effect` ("calendar"), `task` (the step task that prepared it), `account` (`google` or `microsoft`), `implementation` (the calendar writer
of that account, a provider of providers/writer/: `google-calendar` or `outlook-calendar`), `address` (the account's address as the project's `accounts` lists it), `calendar` (the
name the project's `accounts` gives the calendar) and `calendar_id` (its id there), `operation` (`create`, `change`, `cancel`, `cancel-series` or `cancel-occurrence`), `event_id` and `base_etag` (the
event a change or a cancel is about and the version of it the task read: Google's etag, Graph's changeKey; both null for a create; for a series cancel the series
master's, for an occurrence cancel the instance's), `read_at` (when the task read it, null for a create), `zone` (the host's zone, the one every wall time of the document is written in), `send_updates` (always `none`: nobody is told),
`event` (the event as it will be, null for a cancel), `before` (the event as it was read, null for a create), `changed` (the fields a change touches, from
CHANGEABLE), `idempotency_key` (derived from everything above: one request is done once) and `dry_run_sha256` (the hash of what the writer's dry run printed: the
exact request it would send).

Two keys are present only when they apply, so that no other document changes by a byte (CB-7): `recurrence` of a create ({"freq": "daily"} or {"freq": "weekly", "byday": "MO".."SU"}, the
weekday of the start in `zone`; a timed event only, and `zone` is an IANA name), and `series` of `cancel-series` and `cancel-occurrence` ({"id": the series master's id, "rule": `daily` or
`weekly:MO`.., "start": null for the whole series, for one occurrence the instant it starts at as it was read}). They are part of the hash the person approves, and of the key.

An event is {title, all_day, start, end, start_at, end_at, location, reminder_minutes, notes}: `start` and `end` are wall times in `zone` (`YYYY-MM-DDTHH:MM`, or a
day `YYYY-MM-DD` for an all-day event, whose `end` is the last day it covers); `start_at` and `end_at` are what the request carries (an instant with its offset,
or, for an all-day event, the first day and the day after the last). Nobody is invited: v1 sends no invitation and no e-mail (SPEC-SECRETARY-WRITES Q4).

Standard library only, plus the credential scan of runtime/workcopy.py, the error class of runtime/effects.py and the phrase table. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import phrases  # noqa: E402
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "calendar"
OPERATIONS = ("create", "change", "cancel", "cancel-series", "cancel-occurrence")
CANCELS = ("cancel", "cancel-series", "cancel-occurrence")      # the operations that remove or cancel and carry no new event
SERIES_CANCELS = ("cancel-series", "cancel-occurrence")      # the two that name a series (CB-7): the whole of it, or one occurrence
ACCOUNTS = ("google", "microsoft")
IMPLEMENTATION = {"google": "google-calendar", "microsoft": "outlook-calendar"}      # the writer of each account (providers/writer/)
SECRET = {"google": "GOOGLE_ACCOUNT_TOKEN", "microsoft": "MICROSOFT_ACCOUNT_TOKEN"}   # the one secret a writer of that account is started with
# The verb of each operation in each writer (providers/writer/README.md).
VERBS = {"google": {"create": "event-insert", "change": "event-patch", "cancel": "event-delete", "cancel-series": "event-delete", "cancel-occurrence": "event-cancel-occurrence"},
         "microsoft": {"create": "event-create", "change": "event-patch", "cancel": "event-delete", "cancel-series": "event-cancel-series", "cancel-occurrence": "event-cancel-occurrence"}}
TITLE_KEY = {"create": "TITLE_CAL_CREATE", "change": "TITLE_CAL_CHANGE", "cancel": "TITLE_CAL_CANCEL", "cancel-series": "TITLE_CAL_CANCEL_SERIES",
             "cancel-occurrence": "TITLE_CAL_CANCEL_OCCURRENCE"}
CHANGEABLE = ("title", "when", "location", "reminder_minutes", "notes")      # the parts of an event a change can touch (`when` is start, end and all_day together)
EVENT_KEYS = ("title", "all_day", "start", "end", "start_at", "end_at", "location", "reminder_minutes", "notes")
KEYS = ("effect", "task", "account", "implementation", "address", "calendar", "calendar_id", "operation", "event_id", "base_etag", "read_at", "zone", "send_updates",
        "event", "before", "changed", "reference", "asker", "idempotency_key", "dry_run_sha256")
OPTIONAL_KEYS = ("recurrence", "series")      # present only for a series (CB-7); a document without them is what it always was, key and hash included
SERIES_KEYS = ("id", "rule", "start")
RULE_WORD = re.compile(r"daily|weekly:(?:MO|TU|WE|TH|FR|SA|SU)")
BYDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")      # datetime.weekday() order
ASKER = re.compile(r"(?:terminal|page|[a-z][a-z0-9-]{0,31}:[A-Za-z0-9_.@+=-]{1,128})")      # who asked: a channel of the person's own, or a messaging sender (<platform>:<id>)
REFERENCE = {"source": re.compile(r"[a-z0-9][a-z0-9-]{0,39}"), "read_at": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")}
TITLE_MAX = 200
LOCATION_MAX = 200
NOTES_MAX = 2000
REMINDER_MAX = 40320            # minutes: four weeks, the most both services take
DEFAULT_MINUTES = 60            # a timed event with no end lasts an hour
SPAN_MAX_DAYS = 31              # no event, timed or all-day, covers more than this
YEARS = (2000, 2100)
SHA256 = re.compile(r"[0-9a-f]{64}")
KEY = re.compile(r"cal-[0-9a-f]{32}")      # (ids below never start with a hyphen: a flag would read it)
NAME = re.compile(r"[a-z0-9-]{1,32}")
CALENDAR_ID = re.compile(r"(?!\.{1,2}$)(?!-)[A-Za-z0-9._@+=-]{1,300}")
EVENT_ID = re.compile(r"(?!-)[A-Za-z0-9=_+-]{1,600}")
ETAG = re.compile(r"(?!-)[A-Za-z0-9_=+/.\"-]{1,200}")
ZONE = re.compile(r"[A-Za-z0-9_+/:-]{1,64}")
OUTLOOK_ZONE = re.compile(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+){1,2}")      # the form the Outlook writer accepts for --time-zone (its ZONE_NAME_RE): an IANA name, never an offset
WALL = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})")
READ_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")      # fixed English abbreviations: a field value is never translated
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")      # control, format (a right-to-left override, a zero-width character), separators, surrogate, private use


def sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _usage(reason: str):
    return effects.EffectError("usage", reason)


# --- the words and the times the person gives ----------------------------------------------------------------------------------------------------------------


def line(value, what: str, maximum: int, required: bool = False) -> str:
    """A one-line text of the person's: at most `maximum` characters, no control, format or separator character, no space around it. EffectError usage otherwise."""
    if not isinstance(value, str):
        raise _usage(f"{what} is a text")
    if required and not value.strip():
        raise _usage(f"{what} is not empty")
    if len(value) > maximum or value != value.strip() or any(unicodedata.category(c) in HIDDEN for c in value):
        raise _usage(f"{what} is one line of at most {maximum} characters, with no space around it and no hidden or control character")
    return value


def notes_text(value) -> str:
    """The notes of an event: at most NOTES_MAX characters, line ends written \\n, no control or hidden character but \\n and a tab, no space around it."""
    if not isinstance(value, str):
        raise _usage("the notes are a text")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > NOTES_MAX or text != text.strip() or any(c not in "\n\t" and unicodedata.category(c) in HIDDEN for c in text):
        raise _usage(f"the notes are at most {NOTES_MAX} characters, with no space around them and no hidden or control character")
    return text


def reminder(value):
    """A reminder in minutes before the start (0 to REMINDER_MAX), or None for the calendar's own default."""
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= REMINDER_MAX:
        raise _usage(f"the reminder is a whole number of minutes from 0 to {REMINDER_MAX}")
    return value


def parse_when(value, what: str):
    """(a datetime for a timed moment or a date for a day, whether it is a day) of `YYYY-MM-DDTHH:MM` or `YYYY-MM-DD`; EffectError usage otherwise."""
    if isinstance(value, str) and WALL.fullmatch(value):
        try:
            moment = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M")
        except ValueError:
            moment = None
        if moment is not None and YEARS[0] <= moment.year <= YEARS[1]:
            return moment, False
    if isinstance(value, str) and DAY.fullmatch(value):
        try:
            day = datetime.datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            day = None
        if day is not None and YEARS[0] <= day.year <= YEARS[1]:
            return day, True
    raise _usage(f"{what} is a day (YYYY-MM-DD) or a day and a time (YYYY-MM-DDTHH:MM), between the years {YEARS[0]} and {YEARS[1]}")


def local_at(naive: datetime.datetime) -> datetime.datetime:
    """The aware datetime of a local wall time, by the rules of the machine's zone on that day (a clock change included). A test replaces it with the rules of the
    zone it stands for."""
    return naive.astimezone()


def instant_of(naive: datetime.datetime) -> str:
    """`YYYY-MM-DDTHH:MM:SS+HH:MM` of a local wall time. EffectError usage when that wall time does not exist (the clock jumps over it)."""
    aware = local_at(naive)
    offset = aware.utcoffset()
    if aware.replace(tzinfo=None) != naive or offset is None or offset.total_seconds() % 60:
        raise _usage("that time does not exist on that day in this machine's zone (the clock changes then): give another time")
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{naive.strftime('%Y-%m-%dT%H:%M:%S')}{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def parse_instant(text: str) -> datetime.datetime:
    """An aware datetime from an instant `...Z` or `...+HH:MM` (seconds required; fractions are cut)."""
    if not isinstance(text, str) or not INSTANT.fullmatch(text):
        raise _usage("a time of an event is an instant with its offset")
    return datetime.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)


def zone_name() -> str:
    """The name of the machine's zone: TZ when it is a zone name, else the zone the machine's local-time file points to, else the offset. Display only."""
    for found in (os.environ.get("TZ", "").lstrip(":"), os.path.realpath("/etc/localtime").partition("zoneinfo/")[2]):
        if found and ZONE.fullmatch(found) and "/" in found and ".." not in found:
            return found
    offset = datetime.datetime.now().astimezone().utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    return f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def times(start, end, current=None) -> dict:
    """{all_day, start, end, start_at, end_at} of the times given, or EffectError usage. A create gives `start` and may give `end`. A change gives `current` (the
    event as it was read) and either or both: a start alone moves the event and keeps how long it lasts; an end alone keeps the start; neither keeps the times;
    changing between a timed event and an all-day one needs the start (the end then defaults as a create's does)."""
    if current is not None and start is None and end is None:
        return {k: current[k] for k in ("all_day", "start", "end", "start_at", "end_at")}
    if start is None and current is None:
        raise _usage("an event needs a start")
    shown = start if start is not None else end
    first, all_day = parse_when(shown, "the start" if start is not None else "the end")
    if current is not None and all_day != current["all_day"] and start is None:
        raise _usage("to change an event between a timed one and an all-day one, give its start")
    if start is None:      # an end alone: the start stays
        first, _ = parse_when(current["start"], "the start")
    last = None
    if end is not None:
        last, end_day = parse_when(end, "the end")
        if end_day != all_day:
            raise _usage("the start and the end are both days or both a day and a time")
    elif current is not None and all_day == current["all_day"] and start is not None:      # a start alone moves the event
        if all_day:
            last = first + (parse_when(current["end"], "the end")[0] - parse_when(current["start"], "the start")[0])
        else:
            last = first + (parse_instant(current["end_at"]) - parse_instant(current["start_at"]))
    if last is None:
        last = first if all_day else first + datetime.timedelta(minutes=DEFAULT_MINUTES)
    if all_day:
        if last < first or (last - first).days + 1 > SPAN_MAX_DAYS:
            raise _usage(f"an all-day event ends on or after its start and covers at most {SPAN_MAX_DAYS} days")
        return {"all_day": True, "start": first.isoformat(), "end": last.isoformat(), "start_at": first.isoformat(),
                "end_at": (last + datetime.timedelta(days=1)).isoformat()}
    if last <= first or last - first > datetime.timedelta(days=SPAN_MAX_DAYS):
        raise _usage(f"an event ends after its start and lasts at most {SPAN_MAX_DAYS} days")
    return {"all_day": False, "start": first.strftime("%Y-%m-%dT%H:%M"), "end": last.strftime("%Y-%m-%dT%H:%M"), "start_at": instant_of(first),
            "end_at": instant_of(last)}


def _wall_of(aware: datetime.datetime) -> datetime.datetime:
    """The local wall time (naive) of an aware instant, in the machine's zone."""
    return aware.astimezone().replace(tzinfo=None, second=0, microsecond=0)


def event_of(title, location, reminder_minutes, notes, when: dict) -> dict:
    """An event of the document, from its checked pieces."""
    return {"title": title, "all_day": when["all_day"], "start": when["start"], "end": when["end"], "start_at": when["start_at"], "end_at": when["end_at"],
            "location": location, "reminder_minutes": reminder_minutes, "notes": notes}


def from_service(got: dict) -> dict:
    """The event of the document for an event the writer's `event-get` printed: its times are the service's own (an instant with its offset, or the days of an
    all-day event with the day after the last as `end`), shown in the machine's zone. EffectError usage when the service's answer is not in its form."""
    if not isinstance(got, dict) or not isinstance(got.get("all_day"), bool):
        raise _usage("the event the writer read is not in its form")
    if got["all_day"]:
        first, last_exclusive = parse_when(got.get("start"), "the start")[0], parse_when(got.get("end"), "the end")[0]
        last = last_exclusive - datetime.timedelta(days=1)
        if last < first:
            raise _usage("the event the writer read ends before it starts")
        start, end, start_at, end_at = first.isoformat(), last.isoformat(), first.isoformat(), last_exclusive.isoformat()
    else:
        low, high = parse_instant(got.get("start")), parse_instant(got.get("end"))
        if high <= low:
            raise _usage("the event the writer read ends before it starts")
        start, end = _wall_of(low).strftime("%Y-%m-%dT%H:%M"), _wall_of(high).strftime("%Y-%m-%dT%H:%M")
        start_at, end_at = got["start"], got["end"]
    return {"title": line_or_blank(got.get("title"), TITLE_MAX), "all_day": got["all_day"], "start": start, "end": end, "start_at": start_at, "end_at": end_at,
            "location": line_or_blank(got.get("location"), LOCATION_MAX), "reminder_minutes": got.get("reminder_minutes") if type(got.get("reminder_minutes")) is int
            else None, "notes": notes_or_blank(got.get("notes"))}


def line_or_blank(value, maximum: int) -> str:
    """Another person's text on one line for the card: hidden characters removed, the space folded, cut at `maximum`."""
    text = "".join(c for c in str(value if value is not None else "") if unicodedata.category(c) not in HIDDEN or c == " ")
    return " ".join(text.split())[:maximum]


def notes_or_blank(value) -> str:
    text = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in HIDDEN).strip()[:NOTES_MAX]


def apply(before: dict, *, title=None, start=None, end=None, location=None, reminder_minutes=None, notes=None) -> dict:
    """The event as it will be after a change: `before` with the parts given replaced (a part left None stays; an empty location or notes clears it). The times
    follow `times`. EffectError usage when a part is not in its form."""
    new_title = before["title"] if title is None else line(title, "the title", TITLE_MAX, True)
    new_location = before["location"] if location is None else line(location, "the location", LOCATION_MAX)
    new_notes = before["notes"] if notes is None else notes_text(notes)
    new_reminder = before["reminder_minutes"] if reminder_minutes is None else reminder(reminder_minutes)
    return event_of(new_title, new_location, new_reminder, new_notes, times(start, end, before))


def utc_text(stamp) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` of an ISO-8601 time with or without an offset (a time without one is read as UTC); EffectError usage when it is not a time."""
    try:
        moment = datetime.datetime.fromisoformat(stamp[:-1] + "+00:00" if isinstance(stamp, str) and stamp.endswith("Z") else stamp)
    except (ValueError, TypeError):
        raise _usage("the time of a reading is an ISO-8601 time") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def same_when(a: dict, b: dict) -> bool:
    """Whether two events happen at the same time (instants, not text: `13:00-03:00` and `16:00Z` are the same)."""
    if a["all_day"] != b["all_day"]:
        return False
    if a["all_day"]:
        return (a["start_at"], a["end_at"]) == (b["start_at"], b["end_at"])
    return parse_instant(a["start_at"]) == parse_instant(b["start_at"]) and parse_instant(a["end_at"]) == parse_instant(b["end_at"])


def changed_fields(before: dict, after: dict) -> list:
    """The parts of CHANGEABLE that differ between two events, in that order."""
    found = []
    for name in CHANGEABLE:
        if name == "when":
            if not same_when(before, after):
                found.append(name)
        elif before[name] != after[name]:
            found.append(name)
    return found


# --- the document ---------------------------------------------------------------------------------------------------------------------------------


def key_of(doc: dict) -> str:
    """`cal-` and 32 hex digits: the key of one request, from everything the person approves of it (the key and the dry-run hash are not content)."""
    said = {k: doc[k] for k in KEYS + OPTIONAL_KEYS if k in doc and k not in ("idempotency_key", "dry_run_sha256")}
    return "cal-" + sha(json.dumps(said, sort_keys=True, ensure_ascii=True, separators=(",", ":")))[:32]


def document(*, task_id: int, account: str, address: str, calendar: str, calendar_id: str, operation: str, event_id=None, base_etag=None, read_at=None,
             zone: str, event=None, before=None, changed=None, reference=None, asker: str = "terminal", dry_run_sha256: str, recurrence=None, series=None) -> dict:
    """The effect document, checked. EffectError usage when a piece is not in its form, a limit is passed, or the words hold what looks like a credential."""
    doc = {"effect": WORD, "task": task_id, "account": account, "implementation": IMPLEMENTATION.get(account, ""), "address": address, "calendar": calendar,
           "calendar_id": calendar_id, "operation": operation, "event_id": event_id, "base_etag": base_etag, "read_at": read_at, "zone": zone,
           "send_updates": "none", "event": event, "before": before, "changed": list(changed or []), "reference": reference, "asker": asker, "idempotency_key": "", "dry_run_sha256": dry_run_sha256}
    if recurrence is not None:
        doc["recurrence"] = recurrence
    if series is not None:
        doc["series"] = series
    doc["idempotency_key"] = key_of(doc)
    check(doc)
    return doc


def _check_event(event, what: str, operation: str, changed=()) -> None:
    if not isinstance(event, dict) or set(event) != set(EVENT_KEYS):
        raise _usage(f"{what} has exactly the keys of an event")
    if what == "event":      # the event as it will be: the person's words, held to the limits of a create
        line(event["title"], "the title", TITLE_MAX, operation == "create" or "title" in changed)
        line(event["location"], "the location", LOCATION_MAX)
        if notes_text(event["notes"]) != event["notes"]:
            raise _usage("the notes are in their normal form")
    if not isinstance(event["title"], str) or not isinstance(event["location"], str) or not isinstance(event["notes"], str):
        raise _usage(f"{what}: the title, location and notes are texts")
    reminder(event["reminder_minutes"])
    if not isinstance(event["all_day"], bool):
        raise _usage(f"{what}: all_day is true or false")
    if event["all_day"]:
        first, last = parse_when(event["start"], "the start")[0], parse_when(event["end"], "the end")[0]
        if not (type(first) is datetime.date and type(last) is datetime.date and event["start_at"] == event["start"] and event["end_at"] == (last + datetime.timedelta(days=1)).isoformat()
                and last >= first and (last - first).days + 1 <= SPAN_MAX_DAYS):
            raise _usage(f"{what}: the days of an all-day event are consistent and cover at most {SPAN_MAX_DAYS} days")
    else:
        first, last = parse_when(event["start"], "the start")[0], parse_when(event["end"], "the end")[0]
        low, high = parse_instant(event["start_at"]), parse_instant(event["end_at"])
        if not (isinstance(first, datetime.datetime) and isinstance(last, datetime.datetime) and high > low and high - low <= datetime.timedelta(days=SPAN_MAX_DAYS)):
            raise _usage(f"{what}: a timed event ends after it starts and lasts at most {SPAN_MAX_DAYS} days")


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the write."""
    if not isinstance(doc, dict) or not set(KEYS) <= set(doc) <= set(KEYS) | set(OPTIONAL_KEYS) or doc["effect"] != WORD:
        raise _usage("the effect document of a calendar change has exactly its keys")
    if not isinstance(doc["task"], int) or isinstance(doc["task"], bool) or doc["task"] < 1:
        raise _usage("task is a task id")
    if doc["account"] not in ACCOUNTS or doc["implementation"] != IMPLEMENTATION[doc["account"]]:
        raise _usage("the account is google or microsoft, with the writer that serves it")
    if doc["operation"] not in OPERATIONS:
        raise _usage(f"the operation is one of {', '.join(OPERATIONS)}")
    if not isinstance(doc["address"], str) or not 3 <= len(doc["address"]) <= 254 or "@" not in doc["address"]:
        raise _usage("address is the account's address")
    if not isinstance(doc["calendar"], str) or not NAME.fullmatch(doc["calendar"]) or not isinstance(doc["calendar_id"], str) \
            or not CALENDAR_ID.fullmatch(doc["calendar_id"]):
        raise _usage("the calendar is a name and an id the project lists")
    if doc["send_updates"] != "none":
        raise _usage("nobody is told of a change: send_updates is none")
    if not isinstance(doc["zone"], str) or not ZONE.fullmatch(doc["zone"]):
        raise _usage("zone is the name of the machine's zone")
    create, cancel = doc["operation"] == "create", doc["operation"] in CANCELS
    if create:
        if doc["event_id"] is not None or doc["base_etag"] is not None or doc["read_at"] is not None or doc["before"] is not None or doc["changed"]:
            raise _usage("a new event has no earlier event, version, reading or changes")
    else:
        if not isinstance(doc["event_id"], str) or not EVENT_ID.fullmatch(doc["event_id"]) or not isinstance(doc["base_etag"], str) \
                or not ETAG.fullmatch(doc["base_etag"]) or not isinstance(doc["read_at"], str) or not READ_AT.fullmatch(doc["read_at"]):
            raise _usage("a change or a removal names the event, the version of it that was read, and when")
        _check_event(doc["before"], "before", doc["operation"])
    if not isinstance(doc["asker"], str) or not ASKER.fullmatch(doc["asker"]):
        raise _usage("asker is terminal, page or the messaging sender who asked")
    ref = doc["reference"]      # the snapshot a `<source>#<n>` reference was read from (None for a new event and for a `created:` reference)
    if ref is not None and (create or not isinstance(ref, dict) or set(ref) != {"source", "n", "read_at"} or not isinstance(ref["source"], str)
                            or not REFERENCE["source"].fullmatch(ref["source"]) or type(ref["n"]) is not int or not 1 <= ref["n"] <= 9999
                            or not isinstance(ref["read_at"], str) or not REFERENCE["read_at"].fullmatch(ref["read_at"])):
        raise _usage("the snapshot a reference was read from is its source, the number of the item and the time it was read")
    if cancel:
        if doc["event"] is not None or doc["changed"]:
            raise _usage("a removal has no new event and no changes")
    else:
        _check_event(doc["event"], "event", doc["operation"], doc["changed"] if isinstance(doc["changed"], list) else ())
    _check_series(doc)
    if doc["operation"] == "change":
        if not doc["changed"] or doc["changed"] != changed_fields(doc["before"], doc["event"]):
            raise _usage("the changes listed are the differences between the event as read and the event as it will be")
    elif doc["changed"]:
        raise _usage("only a change lists changes")
    if not isinstance(doc["dry_run_sha256"], str) or not SHA256.fullmatch(doc["dry_run_sha256"]):
        raise _usage("dry_run_sha256 is the hash of what the writer's dry run printed")
    if not isinstance(doc["idempotency_key"], str) or not KEY.fullmatch(doc["idempotency_key"]) or doc["idempotency_key"] != key_of(doc):
        raise _usage("the key is the one the content derives")
    if doc["event"] is not None:
        why = workcopy.scan("\n".join((doc["event"]["title"], doc["event"]["location"], doc["event"]["notes"])).encode("utf-8"))
        if why:
            raise _usage(f"the title, the location or the notes {why}: it is not written anywhere")
    return doc


def _check_series(doc: dict) -> None:
    """The two optional keys (CB-7): `recurrence` only on a create of a timed event written in a named zone, daily or weekly on the weekday the start has; `series` only on a series
    cancel, naming the master (the whole series) or another event, the instance, that starts at the instant the document's `before` has (one occurrence)."""
    operation = doc["operation"]
    if "recurrence" in doc:
        rec, event = doc["recurrence"], doc["event"]
        if operation != "create" or not isinstance(rec, dict) or event is None or event["all_day"] is not False or not OUTLOOK_ZONE.fullmatch(doc["zone"]):
            raise _usage("a repetition belongs to a new timed event written in a named zone (an IANA name)")
        if rec != {"freq": "daily"} and not (set(rec) == {"freq", "byday"} and rec["freq"] == "weekly" and rec["byday"] in BYDAY):
            raise _usage("a repetition is daily, or weekly on one weekday, and nothing else")
        if rec["freq"] == "weekly" and rec["byday"] != BYDAY[parse_when(event["start"], "the start")[0].weekday()]:
            raise _usage("a weekly repetition is on the weekday the event starts on")
    if "series" in doc and operation not in SERIES_CANCELS:
        raise _usage("only the cancel of a series or of one of its occurrences names a series")
    if operation in SERIES_CANCELS:
        series = doc.get("series")
        if not isinstance(series, dict) or set(series) != set(SERIES_KEYS) or not isinstance(series["id"], str) or not EVENT_ID.fullmatch(series["id"]) \
                or not isinstance(series["rule"], str) or not RULE_WORD.fullmatch(series["rule"]) or doc["before"]["all_day"] is not False:
            raise _usage("the cancel of a series names the series: its id, its rule (daily or weekly on a weekday) and a timed event")
        if operation == "cancel-series" and (series["id"] != doc["event_id"] or series["start"] is not None):
            raise _usage("the cancel of a whole series is made on the series' own id and names no start")
        if operation == "cancel-occurrence" and (series["id"] == doc["event_id"] or series["start"] != doc["before"]["start_at"]):
            raise _usage("the cancel of one occurrence is made on the occurrence's id and names the instant it starts at, as it was read")


# --- what the person reads -------------------------------------------------------------------------------------------------------------------------


def _day_text(moment) -> str:
    return f"{WEEKDAYS[moment.weekday()]} {moment.day:02d}/{moment.month:02d}/{moment.year}"


def when_text(event: dict, zone: str) -> str:
    """The time of an event as the card says it, e.g. `Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)` or `all day Mon 19/10/2026`."""
    first, last = parse_when(event["start"], "the start")[0], parse_when(event["end"], "the end")[0]
    if event["all_day"]:
        return f"all day {_day_text(first)}" + (f" - {_day_text(last)}" if last != first else "")
    if first.date() == last.date():
        return f"{_day_text(first)} {first:%H:%M}-{last:%H:%M} ({zone})"
    return f"{_day_text(first)} {first:%H:%M} - {_day_text(last)} {last:%H:%M} ({zone})"


def etag_short(etag: str) -> str:
    return "".join(c for c in etag if c not in '"')[:12]


def title(doc: dict) -> str:
    """The title of the pending decision: a sentence of the phrase table, written by code (the person's words are never in it)."""
    return phrases.en(TITLE_KEY[doc["operation"]])


def describe(doc: dict) -> str:
    """What is approved, in one line. It holds none of the person's words: the state file is versioned."""
    verb = {"create": "create an event in", "change": "change an event in", "cancel": "remove an event from", "cancel-series": "cancel a whole series of events in",
            "cancel-occurrence": "cancel one occurrence of a series in"}[doc["operation"]]
    return f"{verb} the calendar '{doc['calendar']}' of the {doc['account']} account {doc['address']}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the person's words."""
    return {"operation": doc["operation"], "account": doc["account"], "calendar": doc["calendar"], "all_day": (doc["event"] or doc["before"])["all_day"],
            "changed": len(doc["changed"]), "has_notes": bool((doc["event"] or doc["before"])["notes"])}


def facts(doc: dict, kind: str, got: dict) -> dict:
    """What the execution records of a write that landed: `kind` is "done" or "replayed"; `got` is what the writer printed."""
    return {"done": True, "replayed": kind == "replayed", "operation": doc["operation"], "account": doc["account"], "calendar": doc["calendar"],
            "calendar_id": doc["calendar_id"], "asker": doc["asker"], "event_id": got.get("event_id") or doc["event_id"], "etag": got.get("etag"),
            "idempotency_key": doc["idempotency_key"]}


def _event_lines(event: dict, zone: str, current: bool = False) -> list:
    """The lines of an event. `current` is an event as the service holds it (the one a removal is about): its title, place and notes are under the keys of
    phrases.CARD_PRIVATE, which a messaging app draws only for a sender who may read the person's own mail and calendar."""
    prefix = "DROP" if current else None
    key = lambda word: f"CARD_CAL_{prefix}_{word}" if prefix else f"CARD_CAL_{word}"      # noqa: E731
    out = [[key("TITLE"), {"title": event["title"]}], ["CARD_CAL_WHEN", {"when": when_text(event, zone)}]]
    if event["location"]:
        out.append([key("WHERE"), {"location": event["location"]}])
    if event["reminder_minutes"] is not None:
        out.append(["CARD_CAL_REMIND", {"minutes": str(event["reminder_minutes"])}])
    if event["notes"]:
        out.append([key("NOTES"), {"notes": event["notes"]}])
    return out


def _part_lines(prefix: str, event: dict, zone: str, only=None) -> list:
    """The lines of the parts of an event named by `only` (all when None), under `prefix` (BEFORE, AFTER or KEPT); an empty value is a dash."""
    parts = (("title", "TITLE", event["title"]), ("when", "WHEN", when_text(event, zone)), ("location", "WHERE", event["location"]),
             ("reminder_minutes", "REMIND", "" if event["reminder_minutes"] is None else str(event["reminder_minutes"])), ("notes", "NOTES", event["notes"]))
    field = {"TITLE": "title", "WHEN": "when", "WHERE": "location", "REMIND": "minutes", "NOTES": "notes"}
    return [[f"CARD_CAL_{prefix}_{word}", {field[word]: value or "-"}] for name, word, value in parts if only is None or name in only]


def card_lines(doc: dict, digest: str) -> list:
    """The card, line by line: [[key, {field: text}], ...], every key of the family CARD_ (runtime/phrases.py card_valid). The account and the calendar first, then
    the event, and for a change each part as it was and as it will be; nothing in v1 invites anyone, and the card says so."""
    zone, operation = doc["zone"], doc["operation"]
    head = [["CARD_ACCOUNT", {"account": doc["account"], "address": doc["address"]}], ["CARD_CAL_CALENDAR", {"calendar": doc["calendar"]}]]
    if operation == "create":
        again = [[repeat_key(rule_of(doc["recurrence"])), {}], ["CARD_CAL_REPEAT_NOTE", {}]] if "recurrence" in doc else []      # the series in words, and where to change or cancel it
        return [["CARD_CAL_CREATE", {}]] + head + _event_lines(doc["event"], zone) + again + [["CARD_CAL_NOBODY", {}]]
    # The event as the calendar holds it NOW (read in the preparation): its id and its time are always on the card, so that whoever approves in the terminal or on the page sees which event
    # it is and a renumbered snapshot cannot make them approve another one. A phone is not shown the id, the snapshot or the version (runtime/messaging_cards.py PHONE_DROPPED; the hash still
    # covers them): it is shown the account, the calendar, the title and the time as read now, which name the event. Title, place and notes are under the keys of phrases.CARD_PRIVATE.
    head.append(["CARD_CAL_EVENT", {"event_id": doc["event_id"]}])
    if operation != "cancel-series":      # a whole series has no "time now": it says when it began, below
        head.append(["CARD_CAL_NOW_WHEN", {"when": when_text(doc["before"], zone)}])
    head.append(["CARD_CAL_NOW_TITLE", {"title": doc["before"]["title"] or "-"}])
    if doc["reference"]:
        head.append(["CARD_CAL_SNAPSHOT", {"reference": f"{doc['reference']['source']}#{doc['reference']['n']}", "read_at": doc["reference"]["read_at"]}])
    base = [["CARD_CAL_BASE", {"etag_short": etag_short(doc["base_etag"])}]]
    if operation in SERIES_CANCELS:
        # CB-7: the card says in words which it is (the whole series, or only this time with the series staying) and what the series is; the series' own id and the instance's are the event line
        # a phone does not show. Where a cancelled event goes is the account's own: Google is expected to keep a trash, Outlook moves it to Deleted Items (CB-6: not verified live).
        outlook = doc["account"] != "google"
        rule = [[repeat_key(doc["series"]["rule"]), {}]]
        kept = [line for line in _event_lines(doc["before"], zone, current=True) if line[0] in ("CARD_CAL_DROP_WHERE", "CARD_CAL_DROP_NOTES")]
        if operation == "cancel-series":
            return [["CARD_CAL_SERIES_CANCEL_OUTLOOK" if outlook else "CARD_CAL_SERIES_CANCEL", {}]] + head + rule + [["CARD_CAL_SERIES_SINCE", {"when": when_text(doc["before"], zone)}]] + kept + base
        return [["CARD_CAL_OCCURRENCE_CANCEL_OUTLOOK" if outlook else "CARD_CAL_OCCURRENCE_CANCEL", {}]] + head + rule + [["CARD_CAL_OCCURRENCE_STAYS", {}]] + kept + base
    if operation == "cancel":
        # the line about where a removed event goes is the account's own: Google is expected to keep it in a trash, Outlook may keep no copy (not verified)
        return [["CARD_CAL_CANCEL" if doc["account"] == "google" else "CARD_CAL_CANCEL_OUTLOOK", {}]] + head + _event_lines(doc["before"], zone, current=True) + base
    changed, out = doc["changed"], [["CARD_CAL_CHANGE", {"read_at": doc["read_at"]}]] + head
    before, after = doc["before"], doc["event"]
    out += _part_lines("BEFORE", before, zone, changed) + _part_lines("AFTER", after, zone, changed)
    kept = [name for name in CHANGEABLE if name not in changed and (name in ("title", "when") or (after[name] not in ("", None)))]
    return out + _part_lines("KEPT", after, zone, kept) + base + [["CARD_CAL_NOBODY", {}]]


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving, in English: the lines of the card (runtime/phrases.py card_text). A messaging app says the same lines in the
    project's language; the hash on the card is the effect's own, in every language."""
    return phrases.card_text(card_lines(doc, digest))


# --- the writer's verbs ------------------------------------------------------------------------------------------------------------------------------


def spec_of(doc: dict) -> dict:
    """What the writer is handed as a file: the whole event for a create, the changed parts for a change, nothing for a removal."""
    if doc["operation"] in CANCELS:
        return {}
    event = doc["event"]
    if doc["operation"] == "create":
        out = {k: event[k] for k in ("title", "all_day", "start_at", "end_at", "location", "reminder_minutes", "notes")}
        if "recurrence" in doc:      # a series is written in the zone it is expanded in (CB-6): the document's own, the host's
            out.update(recurrence=doc["recurrence"], time_zone=doc["zone"])
        return out
    out = {}
    for name in doc["changed"]:
        if name == "when":
            out.update({k: event[k] for k in ("all_day", "start_at", "end_at")})
        else:
            out[name] = event[name]
    return out


def verb_of(doc: dict) -> str:
    return VERBS[doc["account"]][doc["operation"]]


def provider_args(doc: dict, spec_file) -> list:
    """The flags of the writer's verb for this document, without --dry-run or --confirmed. `spec_file` is the private path of the spec (None for a removal)."""
    args = ["--calendar", doc["calendar_id"]]
    if doc["operation"] != "create":
        args += ["--event", doc["event_id"], "--base-etag", doc["base_etag"]]
    if spec_file:
        args += ["--spec-file", spec_file]
    args += ["--idempotency-key", doc["idempotency_key"]]
    args += series_args(doc)
    return args + outlook_zone_args(doc)


def series_args(doc: dict) -> list:
    """The flags that name the series (CB-7), the same on the dry run and on the confirmed run because both are built from the approved document: for one occurrence `--series <the
    master's id> --expect-start <the instant it starts at, as it was read>`; for the whole series on Google the switch `--series` of `event-delete` (Outlook's own verb needs none);
    nothing for any other operation. The ids and the instant are read by code from the provider, never from a line."""
    flags = []
    if doc["operation"] == "cancel-occurrence":
        flags += ["--series", doc["series"]["id"], "--expect-start", doc["series"]["start"]]
    elif doc["operation"] == "cancel-series" and doc["account"] == "google":
        flags.append("--series")
    return flags


def outlook_zone_args(doc: dict) -> list:
    """`--time-zone <name>` for an Outlook timed create, or a change that carries times, when the document's zone is an IANA name (it has a `/` and is of the writer's
    own form); else nothing (UTC, as before). The name is only ever `doc["zone"]`, the host's zone: never the person's line or a model's. It is part of the dry run, so
    the hash the person approves covers it. Google, a removal, an all-day event and an offset zone (`UTC-03:00`) get none."""
    if doc["account"] != "microsoft" or doc["operation"] in CANCELS or doc["event"]["all_day"]:
        return []
    if doc["operation"] == "change" and "when" not in doc["changed"]:
        return []
    named = OUTLOOK_ZONE.fullmatch(doc["zone"])
    return list(("--time-zone", doc["zone"])) if named else []


def instances_args(calendar_id: str, series_id: str, first: str, last: str) -> list:
    """The flags of the writer's `event-instances` read: the instances of the series `series_id` between two instants (an instant with its offset each; at most two days wide)."""
    args = ["--calendar", calendar_id, "--series", series_id, "--from", first, "--to", last]
    return args


def day_window(day: datetime.date, days: int = 1) -> tuple:
    """(the first instant, the last instant) as `YYYY-MM-DDTHH:MM:SS+HH:MM` of the `days` local days from the start of `day`, in the machine's zone (the zone every wall time of a
    document is written in). A window of at most two days is what the writer reads."""
    first = datetime.datetime.combine(day, datetime.time.min).astimezone()
    last = datetime.datetime.combine(day + datetime.timedelta(days=days), datetime.time.min).astimezone()
    return first.isoformat(timespec="seconds"), last.isoformat(timespec="seconds")


def rule_of(recurrence) -> str:
    """The closed word of a repetition: `daily` or `weekly:MO`.."""
    if recurrence == {"freq": "daily"}:
        return "daily"
    return f"weekly:{recurrence['byday']}"


def repeat_key(rule: str) -> str:
    """The key of the card line that says a repetition in words (the phrase table's CARD_CAL_REPEAT_ family)."""
    return "CARD_CAL_REPEAT_DAILY" if rule == "daily" else f"CARD_CAL_REPEAT_WEEKLY_{rule[-2:]}"


def event_get_args(doc: dict) -> list:
    """The flags of the writer's `event-get` for the event a document (or {"calendar_id", "event_id"}) names."""
    args = ["--calendar", doc["calendar_id"], "--event", doc["event_id"]]
    return args


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
