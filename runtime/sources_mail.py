#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Mail and calendar as sources of a project (package RT-1, SPEC-SECRETARY-INTEGRATIONS sections 1 to 3 and 6): the origin check, the window,
the calls to the providers, the per-message credential scan, the import and the refresh. It is the block beside runtime/sources.py that the
OneDrive block (runtime/sources_onedrive.py) is the pattern of; the text itself is built by runtime/snapshot_text.py.

A mail or calendar source is a WINDOW the person chose, read as a SNAPSHOT and kept as an immutable, dated version; never a live read.
What a task sees is the converted text of the newest version its plan chose, hashed and recorded like any other source (D29). The types are
`mail` and `calendar` (the registry's type column admits them since migration 21). The origin is one closed line (checked here, by
`register`):

  mail      gmail:box=<inbox|important|starred|unread>;days=<1-31>;max=<1-100>
            outlook:box=<inbox|unread>;days=<1-31>;max=<1-100>
  calendar  google:calendar=<id>;past=<0-7>;ahead=<0-31>
            outlook:calendar=<default|id>;past=<0-7>;ahead=<0-31>

The box is a fixed query of the provider, never free text (a free query is a later decision); a calendar source reads one calendar, several
calendars are several sources. The implementation named in the origin is handed to providers/resolve.py as the explicit implementation, so
the choice between two readers is never "auto". One account per implementation per machine.

LIMIT L52. A mail or calendar source is read only by its snapshot: the providers of `reader:email` and `integration:calendar` are called
only from here, by the source operations of the host (`source-mail`, `source-calendar`, a refresh from the terminal, the page or the
`ingest` step of a routine), with the arguments the person's origin fixes; never from a run and never with a query a model wrote. A run
receives only the converted text of the versions its plan chose. `provider_call` is the one caller, and it sends only the verbs `search`
and `events`, which read. (L53, the age of a snapshot, is in runtime/sources.py `task_copies`.)

The listing identifies the reading: origin_version is the sha256 of the sorted (id, change key) pairs the provider listed (Gmail: the message
id; Outlook mail: Graph's changeKey; calendars: the event's etag), the zone and the local date of the reading. The same list on the same
local date makes no new version; a different one does, and so does the same list on another day, so that a daily refresh always leaves a
snapshot younger than the age limit L53 allows an unattended task.

External content is data: every message, event, title, place, file name and error text is another person's. It is cleaned (control and
direction characters out), its links replaced, a message body cut and indented, and each message (each event) is scanned for credentials on
its own: one that holds a credential shape is LEFT OUT and counted by date and sender domain, never redacted, and the whole text passes
`import_version`'s own scan as a second guard. Nothing in a message is followed: no link is fetched, no attachment is opened (names, declared
types and sizes only), no address is written to.

A credential never reaches a run, a manifest, the catalog or a message: a provider's process gets `provider_environment` plus its own
secret (the names in SECRETS), and this module never reads or stores a token.

THE INDEX (package SNAP-IDX, SPEC-SECRETARY-WRITES 3.4). Beside the text, each version's manifest keeps `index`: one entry for each item the
text lists, in the order the text lists it, numbered from 1, so that `<source id>#<n>` names one message or one event by code and never by the
words of the text (runtime/item_refs.py reads it). A mail entry is {n, id, thread_id, message_id, from_address, reply_to_address, subject,
change_key, received} (`received`: the moment the message came in UTC, `YYYY-MM-DDTHH:MM:SSZ`, or null; S16C-REPLY-DATE);
a calendar entry is {n, id, etag, calendar, organizer_self, attendees_other, recurring}. It holds no body, no sender's name, no
token; a subject is cleaned and cut at INDEX_SUBJECT_CHARS characters; an id, key or address that is not shaped as the service prints it
is null, and the entry stays so that the numbers do not move. A message left out of the text for a credential has no entry and no number. A mail
text numbers its messages (`## 3. ...`); a calendar text numbers its event lines (`3. 09:00-10:00 · ...`) in the order of
snapshot_text.calendar_order, which is the order of the index. The index is in the manifest, which no run receives (L26, L52). Its sha256 is a line of
the text (the third), and the store records the text's hash (L25), so an index changed outside the runtime no longer matches its version
(runtime/item_refs.py checks it). The readers print the sender's address alone (`from_address`) and the Reply-To of one mailbox (`reply_to`); the index
never picks an address out of the words of a `from` field. The format of the index is part of the reading's signature (SIGNATURE_MARK), so the
first refresh after the index existed always makes a version that has one.

Imports `sources` (the registry, the versions, the guardrails of the folder) and `snapshot_text`; nothing of the operations layer.
`sources.register` loads this module for the origin check of its types. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snapshot_text as text  # noqa: E402
import sources  # noqa: E402
from sources import SourcesError, _clean  # noqa: E402

MAIL_CLASS = "reader:email"
CALENDAR_CLASS = "integration:calendar"
VERBS = {MAIL_CLASS: ("search",), CALENDAR_CLASS: ("events",)}   # what the runtime asks a provider: the verbs that read the box or the window
# The secrets a provider reads from its environment (providers/secrets/resolver.py): its own, and no other. Each provider reads the account
# token of its service first (GOOGLE_ACCOUNT_TOKEN, MICROSOFT_ACCOUNT_TOKEN: one record per account, the platform's whole scope set) and, for one
# cycle (backlog ACCT-LEGACY), the old record of its own purpose when there is no account record.
GOOGLE_ACCOUNT_SECRET, MICROSOFT_ACCOUNT_SECRET = "GOOGLE_ACCOUNT_TOKEN", "MICROSOFT_ACCOUNT_TOKEN"
SECRETS = {(MAIL_CLASS, "gmail"): (GOOGLE_ACCOUNT_SECRET, "GMAIL_REFRESH_TOKEN", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"),
           (MAIL_CLASS, "outlook"): (MICROSOFT_ACCOUNT_SECRET, "OUTLOOK_MAIL_TOKEN"),
           (CALENDAR_CLASS, "google"): (GOOGLE_ACCOUNT_SECRET, "GOOGLE_CALENDAR_TOKEN"),
           (CALENDAR_CLASS, "outlook"): (MICROSOFT_ACCOUNT_SECRET, "OUTLOOK_CALENDAR_TOKEN")}
LABELS = {MAIL_CLASS: "mail", CALENDAR_CLASS: "calendar"}
BOXES = {"gmail": {"inbox": "in:inbox", "important": "is:important", "starred": "is:starred", "unread": "in:inbox is:unread"},
         "outlook": {"inbox": "in:inbox", "unread": "in:inbox is:unread"}}
CALENDAR_ID = {"google": re.compile(r"[A-Za-z0-9._%+#@-]{1,254}"), "outlook": re.compile(r"[A-Za-z0-9=_-]{1,256}")}
MAIL_ORIGIN = re.compile(r"(gmail|outlook):box=([a-z]{1,12});days=([0-9]{1,2});max=([0-9]{1,3})")
CALENDAR_ORIGIN = re.compile(r"(google|outlook):calendar=([^;]{1,256});past=([0-9]{1,2});ahead=([0-9]{1,2})")
DAYS_MAX, ITEMS_MAX, PAST_MAX, AHEAD_MAX = 31, 100, 7, 31
EVENTS_MAX = 250
PROVIDER_TIMEOUT = 300
SIZE_MARGIN = 16 * 1024               # kept free under the converted cap for the heading, the notes and the left-out lines
WHY_CREDENTIAL = "it holds what looks like a credential"
INDEX_SUBJECT_CHARS = 120        # the longest subject the index keeps (cleaned, links replaced; a cut one ends with an ellipsis)
# What an entry of the index may hold, checked by full match: an id as a service prints it (it goes into a path later), a key (a change key or an
# etag, printable characters with no space), a Message-ID header, a plain address. Anything else is null.
INDEX_ID = re.compile(r"[A-Za-z0-9_=+.-]{1,700}")
INDEX_KEY = re.compile(r"[\x21-\x7e]{1,200}")
INDEX_MESSAGE_ID = re.compile(r"[\x21-\x7e]{1,998}")
SIGNATURE_MARK = "\nindex 1"    # the format of the index, part of the reading's signature: a version made before the index existed has another signature, so the first refresh makes one that has it
CLOCK = None      # a callable returning an aware datetime, or None for the machine's clock (a seam for tests)
ZONE = None       # a tzinfo, or None for the machine's own zone (a seam for tests)


# --- the origins ------------------------------------------------------------------------------------------------------------------


def mail_origin(value) -> dict:
    """The parts of a mail origin: {"implementation", "box", "days", "max", "query"}. SourcesError (usage) for anything else: the grammar is closed."""
    raw = value.strip() if isinstance(value, str) else ""
    found = MAIL_ORIGIN.fullmatch(raw)
    if found:
        implementation, box, days, most = found.group(1), found.group(2), int(found.group(3)), int(found.group(4))
        if box in BOXES[implementation] and 1 <= days <= DAYS_MAX and 1 <= most <= ITEMS_MAX and found.group(3) == str(days) and found.group(4) == str(most):
            return {"implementation": implementation, "box": box, "days": days, "max": most, "query": BOXES[implementation][box], "origin": raw}
    raise SourcesError("a mail source's origin is gmail:box=<inbox|important|starred|unread>;days=<1-31>;max=<1-100> or "
                       "outlook:box=<inbox|unread>;days=<1-31>;max=<1-100> (for example gmail:box=inbox;days=7;max=50): the box is one of the "
                       "fixed ones, never a free query", "usage")


def calendar_origin(value) -> dict:
    """The parts of a calendar origin: {"implementation", "calendar", "past", "ahead"}. SourcesError (usage) for anything else."""
    raw = value.strip() if isinstance(value, str) else ""
    found = CALENDAR_ORIGIN.fullmatch(raw)
    if found:
        implementation, calendar, past, ahead = found.group(1), found.group(2), int(found.group(3)), int(found.group(4))
        ok_id = CALENDAR_ID[implementation].fullmatch(calendar) and set(calendar) != {"."}
        if ok_id and 0 <= past <= PAST_MAX and 0 <= ahead <= AHEAD_MAX and found.group(3) == str(past) and found.group(4) == str(ahead):
            return {"implementation": implementation, "calendar": calendar, "past": past, "ahead": ahead, "origin": raw}
    raise SourcesError("a calendar source's origin is google:calendar=<id>;past=<0-7>;ahead=<0-31> or outlook:calendar=<default|id>;past=<0-7>;"
                       "ahead=<0-31> (for example google:calendar=primary;past=0;ahead=14): one calendar, the id as the provider's `calendars` "
                       "verb prints it", "usage")


def origin_of(source_type: str, value) -> dict:
    """The parts of the origin of a source of the type `mail` or `calendar`."""
    if source_type == "mail":
        return mail_origin(value)
    if source_type == "calendar":
        return calendar_origin(value)
    raise SourcesError(f"{source_type} is not a mail or calendar source", "usage")


# --- the one caller of the providers (limit L52) -----------------------------------------------------------------------------------


def provider_call(cfg: dict, cls: str, implementation: str, verb: str, args: list, *, call=None, timeout: int = PROVIDER_TIMEOUT) -> dict:
    """One read verb of a mail or calendar provider, through providers/resolve.py, in a process that has the minimum environment and the
    provider's own secret. The implementation is explicit (never "auto"). Only the verbs of VERBS are sent. `call(cls, verb, args, root=,
    implementation=, timeout=, env=)` is the seam a test replaces. SourcesError (mail or calendar) on any failure, with the provider's
    reason cleaned to one line (it is another service's text)."""
    secrets = SECRETS.get((cls, implementation))
    if secrets is None or verb not in VERBS.get(cls, ()):
        raise SourcesError(f"the runtime does not ask {implementation} for {verb}", "usage")
    code = LABELS[cls]
    resolver = None
    if call is None:
        resolver = sources._lazy("workbench_sources_resolve", os.path.join(cfg["workbench"], "providers", "resolve.py"))
        call = resolver.call
    extra = {"env": sources._provider_env(cfg, cls, secrets)} if resolver is not None else {}
    try:
        out = call(cls, verb, args, root=cfg["workbench"], implementation=implementation, timeout=timeout, **extra)
    except Exception as e:
        kind = getattr(e, "kind", None)
        reason = getattr(e, "reason", None) or str(e)
        raise SourcesError(f"the {code} could not be read ({kind or type(e).__name__}): {_clean(reason, 300)}", code) from None
    if not isinstance(out, dict):
        raise SourcesError(f"the {code} provider answered no object", code)
    return out


# --- the window and the reading ---------------------------------------------------------------------------------------------------


def moment_now(clock=None):
    """The reading time as an aware UTC datetime."""
    use = clock or CLOCK
    now = use() if use else datetime.datetime.now(datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc).replace(microsecond=0)


def _midnight(day, zone):
    if zone is None:
        return datetime.datetime(day.year, day.month, day.day).astimezone()
    return datetime.datetime(day.year, day.month, day.day, tzinfo=zone)


def mail_window(now, days: int) -> tuple:
    """(start, end) of a mail window: `days` back from the reading time, to it (aware UTC datetimes)."""
    return now - datetime.timedelta(days=days), now


def calendar_window(now, past: int, ahead: int, zone=None) -> tuple:
    """(start, end, first day, last day) of a calendar window: from local midnight `past` days before today to local midnight after the day
    `ahead` days from today. The first and last days are dates in the zone."""
    today = text.to_zone(now, zone).date()
    first, last = today - datetime.timedelta(days=past), today + datetime.timedelta(days=ahead)
    return _midnight(first, zone), _midnight(last + datetime.timedelta(days=1), zone), first, last


def _signature(pairs, label: str, local_date: str) -> str:
    listed = "\n".join(sorted(f"{i}\t{k}" for i, k in pairs))
    return hashlib.sha256(f"{listed}\n{label}\n{local_date}{SIGNATURE_MARK}".encode("utf-8")).hexdigest()


def read_snapshot(cfg: dict, source_type: str, origin: str, *, call=None, clock=None, zone=None, timeout=None) -> dict:
    """Read what a mail or calendar origin names: the provider's items of the window, nothing built yet. `timeout` (seconds) bounds the provider's answer; None keeps
    PROVIDER_TIMEOUT (300), which every caller but the one line that asks for less (BL5E, runtime/mail_refresh.py) uses. Returns {"type", "parts", "now",
    "zone", "label", "window", "items", "truncated", "skipped", "signature", "first", "last"}. Items that are not shaped as the provider
    prints them are counted in "skipped"."""
    parts = origin_of(source_type, origin)
    now = moment_now(clock)
    zone = ZONE if zone is None else zone
    label = text.zone_label(text.to_zone(now, zone))
    local_date = text.to_zone(now, zone).date().isoformat()
    if source_type == "mail":
        start, end = mail_window(now, parts["days"])
        got = provider_call(cfg, MAIL_CLASS, parts["implementation"], "search",
                            ["--query", parts["query"], "--since", text.utc_stamp(start), "--limit", str(parts["max"]), "--own-words"], call=call,
                            timeout=timeout or PROVIDER_TIMEOUT)
        listed, key, limit = got.get("messages"), "change_key", parts["max"]
        first = last = None
    else:
        start, end, first, last = calendar_window(now, parts["past"], parts["ahead"], zone)
        got = provider_call(cfg, CALENDAR_CLASS, parts["implementation"], "events",
                            ["--calendar", parts["calendar"], "--from", start.isoformat(), "--to", end.isoformat(), "--max", str(EVENTS_MAX)], call=call,
                            timeout=timeout or PROVIDER_TIMEOUT)
        listed, key, limit = got.get("events"), "etag", EVENTS_MAX
    if not isinstance(listed, list):
        raise SourcesError(f"the {source_type} provider's list is not one this runtime reads", source_type)
    items, pairs, skipped = [], [], 0
    for item in listed[:limit]:
        item_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(item_id, str) or not item_id or len(item_id) > 700:
            skipped += 1
            continue
        change = item.get(key) if isinstance(item.get(key), str) else ""
        items.append(item)
        pairs.append((item_id, change[:200]))
    skipped += max(0, len(listed) - limit)
    return {"type": source_type, "parts": parts, "now": now, "zone": zone, "label": label, "window": (start, end), "items": items,
            "truncated": bool(got.get("truncated")), "skipped": skipped, "signature": _signature(pairs, label, local_date),
            "first": first, "last": last}


# --- the text ---------------------------------------------------------------------------------------------------------------------


def _scan(data: bytes):
    return sources._workcopy().scan(data)


def _shaped(pattern, value):
    """`value` when it is a string the pattern matches whole, else None."""
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def mail_index_entry(n: int, message: dict, scan=None, moment=None) -> dict:
    """The index entry of the message the text numbers `n`: {n, id, thread_id, message_id, from_address, reply_to_address, subject, change_key, received}.
    Every value is a closed shape or null (INDEX_*); the subject is cleaned, its links replaced and cut at INDEX_SUBJECT_CHARS; no body, no name.
    `received` is the moment the message came (`moment`, the aware datetime of the message's view, which comes from the provider's received time: Outlook's `receivedDateTime`, Gmail's `internalDate`, else the sender's own `Date` header, a well-shaped time the sender chose; it injects no text and chooses no recipient) in UTC, `YYYY-MM-DDTHH:MM:SSZ`, null when the
    message has none: a reply card shows it beside the message answered, and it chooses nothing (S16C-REPLY-DATE). The entry is scanned for
    credentials as a whole (the Reply-To address was not part of the message's scan): a hit empties the entry's words and its time, never its number."""
    headers = message.get("headers") if isinstance(message.get("headers"), dict) else {}
    from_address = text.plain_address(message.get("from_address"))     # the readers print the address alone; this is not picked out of the `from` words
    reply = text.plain_address(message.get("reply_to"))
    if reply is not None and from_address is not None and reply.lower() == from_address.lower():
        reply = None
    entry = {"n": n, "id": _shaped(INDEX_ID, message.get("id")), "thread_id": _shaped(INDEX_ID, message.get("thread_id")),
             "message_id": _shaped(INDEX_MESSAGE_ID, headers.get("Message-ID")), "from_address": from_address, "reply_to_address": reply,
             "subject": text.one_line(message.get("subject") or "", INDEX_SUBJECT_CHARS), "change_key": _shaped(INDEX_KEY, message.get("change_key")),
             "received": text.utc_stamp(moment) if moment else None}
    if scan is not None and scan(json.dumps(entry).encode("utf-8")):
        entry.update(message_id=None, from_address=None, reply_to_address=None, subject="", received=None)
    return entry


def event_index_entry(n: int, event: dict, calendar: str) -> dict:
    """The index entry of the event the text lists `n`-th: {n, id, etag, calendar, organizer_self, attendees_other, recurring}. `attendees_other` is the
    number of attendees other than the person when the provider printed it, else null (unknown: the readers do not print it today, and a change
    reads the event again before it is prepared)."""
    others = event.get("attendees_other")
    return {"n": n, "id": _shaped(INDEX_ID, event.get("id")), "etag": _shaped(INDEX_KEY, event.get("etag")), "calendar": calendar,
            "organizer_self": event.get("organizer_self") is True,
            "attendees_other": others if type(others) is int and others >= 0 else None, "recurring": event.get("recurring") is True}


def build_mail(source_id: str, snap: dict, *, scan=None) -> tuple:
    """(text, kept, left out, index) of a mail snapshot. Each message is scanned on its own; one that holds a credential shape is left out and counted by
    date and sender domain, and has no entry in the index. The oldest messages are dropped, with a counted line, past the size one source may hold;
    the index has an entry for each message the text numbers, in its order."""
    scan = scan or _scan
    parts, zone = snap["parts"], snap["zone"]
    pairs = [(text.message_view(m, zone), m) for m in snap["items"]]
    pairs.sort(key=lambda p: (p[0]["moment"] is not None, p[0]["moment"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)), reverse=True)
    kept, left_out = [], []
    for view, message in pairs:
        if scan(view["whole"].encode("utf-8")) or scan(text.message_block(0, view).encode("utf-8")):   # the whole fields before any cut, then what is written
            item = {"date": view["date"], "domain": view["domain"], "why": WHY_CREDENTIAL}
            if scan(text.left_out_line(item).encode("utf-8")):    # a sender's domain is a stranger's word too: one that looks like a key is not written
                item["domain"] = None
            left_out.append(item)
        else:
            kept.append((view, message))
    blocks, used, budget = [], 0, sources.CONVERTED_CAP - SIZE_MARGIN
    for view, _message in kept:
        block = text.message_block(len(blocks) + 1, view)
        used += len(block.encode("utf-8"))
        if used > budget:
            break
        blocks.append(block)
    index = [mail_index_entry(number, message, scan, view["moment"]) for number, (view, message) in enumerate(kept[:len(blocks)], 1)]
    dropped = len(kept) - len(blocks)
    notes = []
    if snap["truncated"]:
        notes.append(f"More messages matched than the {parts['max']} read: the older ones are not in this snapshot.")
    if dropped:
        notes.append(f"{dropped} older message{' was' if dropped == 1 else 's were'} left out: the text would pass the "
                     f"{sources.CONVERTED_CAP // 1024} KiB one source may hold.")
    if snap["skipped"]:
        notes.append(f"{snap['skipped']} message{' was' if snap['skipped'] == 1 else 's were'} left out: the provider's description of "
                     f"{'it' if snap['skipped'] == 1 else 'them'} could not be read.")
    start, end = (text.to_zone(m, snap["zone"]) for m in snap["window"])
    rendered = text.render_mail(source_id, parts["box"], (text._stamp(start), text._stamp(end)), snap["label"], text.utc_stamp(snap["now"]),
                                blocks, left_out, notes, digest=text.index_digest(index))
    return rendered, len(blocks), left_out, index


def build_calendar(source_id: str, snap: dict, *, scan=None) -> tuple:
    """(text, kept, left out, index) of a calendar snapshot. Each event (its title and place) is scanned on its own; one that holds a credential
    shape is left out and counted by date, and has no entry in the index. The index has an entry for each event the text lists, in the order it
    lists them (snapshot_text.calendar_order), numbered from 1."""
    scan = scan or _scan
    zone = snap["zone"]
    kept, left_out, unreadable, source_events = [], [], 0, {}
    for event in snap["items"]:
        view = text.event_view(event, zone)
        if view is None:
            unreadable += 1
        elif scan(view["whole"].encode("utf-8")) or scan(text.event_block(view).encode("utf-8")):
            left_out.append({"date": view["day"].isoformat(), "why": WHY_CREDENTIAL})
        else:
            kept.append(view)
            source_events[id(view)] = event
    calendar = snap["parts"]["calendar"]
    index = [event_index_entry(number, source_events[id(view)], calendar) for number, view in enumerate(text.calendar_order(kept, snap["first"]), 1)]
    notes = []
    if snap["truncated"]:
        notes.append(f"More events exist than the {EVENTS_MAX} read: the later ones are not in this snapshot.")
    unreadable += snap["skipped"]
    if unreadable:
        notes.append(f"{unreadable} event{' was' if unreadable == 1 else 's were'} left out: the provider's description of "
                     f"{'it' if unreadable == 1 else 'them'} could not be read.")
    rendered = text.render_calendar(source_id, snap["first"], snap["last"], snap["label"], text.utc_stamp(snap["now"]), kept, left_out, notes,
                                    digest=text.index_digest(index))
    return rendered, len(kept), left_out, index


def catalog_name(parts: dict, source_type: str) -> str:
    """What the catalog calls a snapshot: closed words and the numbers of the origin, no third-party text."""
    if source_type == "mail":
        return f"Mail snapshot: {parts['implementation']} {parts['box']}, {parts['days']} days"
    return f"Calendar snapshot: {parts['implementation']} calendar, {parts['past']} days back, {parts['ahead']} days ahead"


# --- import and refresh -----------------------------------------------------------------------------------------------------------


def snapshot_make(ctx, source: dict, snap: dict, *, label: str, evidence_base=None) -> dict:
    """Build the text of a reading and import it as a version of `source`, with the index of its items in the version's manifest. The reading
    time is the version's date. Returns import_version's answer plus {"read": True, "items": the messages or events in the text, "left_out":
    how many were left out}. SourcesError on any refusal, with nothing kept."""
    source_type = source["type"]
    builder = build_mail if source_type == "mail" else build_calendar
    rendered, kept, left_out, index = builder(source["id"], snap)
    start, end = (text.to_zone(m, snap["zone"]).isoformat() for m in snap["window"])
    extra = {"window_start": start, "window_end": end, "zone": snap["label"], "read_at": text.utc_stamp(snap["now"]),
             "messages" if source_type == "mail" else "events": kept, "left_out": len(left_out), "index": index}
    now = snap["now"]
    done = sources.import_version(ctx, source, rendered.encode("utf-8"), convert=None, kind=source_type, label=label,
                                  origin_version=snap["signature"], clock=lambda: now, evidence_base=evidence_base,
                                  name=catalog_name(snap["parts"], source_type), manifest_extra=extra)
    return {**done, "read": True, "items": kept, "left_out": len(left_out)}


def snapshot_new(ctx, source_id: str, source_type: str, origin: str, description=None, *, call=None, clock=None, zone=None, evidence_base=None) -> dict:
    """The first snapshot of a source that is not registered yet: the origin is checked, the provider is read, and only then the source is
    registered and the version imported, so that a provider that fails leaves no source behind. Returns {"source_row", ...snapshot_make}."""
    sources.check_id(source_id)
    parts = origin_of(source_type, origin)
    sources.check_folder(ctx["cfg"], evidence_base)
    snap = read_snapshot(ctx["cfg"], source_type, parts["origin"], call=call, clock=clock, zone=zone)
    row = sources.register(ctx, source_id, source_type, parts["origin"], description)
    return {**snapshot_make(ctx, row, snap, label="import", evidence_base=evidence_base), "source_row": row}


def snapshot_refresh(ctx, source: dict, *, convert, call=None, clock=None, zone=None, evidence_base=None, timeout=None) -> dict:
    """A refresh of a mail or calendar source: the provider is read for the window as it is now (`timeout` as in read_snapshot: None keeps 300 seconds). When the listing is the one recorded with the
    newest version (same ids and change keys, same local date), no version is made and the files in the folder are still checked against
    the record (limit L25); otherwise a new version is imported. Returns {"imported", "unchanged", "read", "source", "version", ...}."""
    if source.get("type") not in ("mail", "calendar"):
        raise SourcesError(f"{source.get('id')} is not a mail or calendar source", "usage")
    cfg = ctx["cfg"]
    sources.check_folder(cfg, evidence_base)
    snap = read_snapshot(cfg, source["type"], source["origin"], call=call, clock=clock, zone=zone, timeout=timeout)
    latest = sources._stored(ctx, "source_latest", source["id"])
    if latest is not None and latest.get("origin_version") == snap["signature"]:
        done = sources.recheck(ctx, source, convert=convert, clock=(lambda: snap["now"]), evidence_base=evidence_base)
        if done.get("changed"):
            return {**done, "read": True}
        return {"imported": False, "unchanged": True, "read": True, "source": source["id"], "version": latest["version"]}
    return snapshot_make(ctx, source, snap, label="refresh" if latest else "import", evidence_base=evidence_base)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
