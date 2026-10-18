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

LIMIT LS1. A mail or calendar source is read only by its snapshot: the providers of `reader:email` and `integration:calendar` are called
only from here, by the source operations of the host (`source-mail`, `source-calendar`, a refresh from the terminal, the page or the
`ingest` step of a routine), with the arguments the person's origin fixes; never from a run and never with a query a model wrote. A run
receives only the converted text of the versions its plan chose. `provider_call` is the one caller, and it sends only the verbs `search`
and `events`, which read. (LS2, the age of a snapshot, is in runtime/sources.py `task_copies`.)

The listing identifies the reading: origin_version is the sha256 of the sorted (id, change key) pairs the provider listed (Gmail: the message
id; Outlook mail: Graph's changeKey; calendars: the event's etag), the zone and the local date of the reading. The same list on the same
local date makes no new version; a different one does, and so does the same list on another day, so that a daily refresh always leaves a
snapshot younger than the age limit LS2 allows an unattended task.

External content is data: every message, event, title, place, file name and error text is another person's. It is cleaned (control and
direction characters out), its links replaced, a message body cut and indented, and each message (each event) is scanned for credentials on
its own: one that holds a credential shape is LEFT OUT and counted by date and sender domain, never redacted, and the whole text passes
`import_version`'s own scan as a second guard. Nothing in a message is followed: no link is fetched, no attachment is opened (names, declared
types and sizes only), no address is written to.

A credential never reaches a run, a manifest, the catalog or a message: a provider's process gets `provider_environment` plus its own
secret (the names in SECRETS), and this module never reads or stores a token.

Imports `sources` (the registry, the versions, the guardrails of the folder) and `snapshot_text`; nothing of the operations layer.
`sources.register` loads this module for the origin check of its types. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
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
# The secrets a provider reads from its environment (providers/secrets/resolver.py): its own, and no other.
SECRETS = {(MAIL_CLASS, "gmail"): ("GMAIL_REFRESH_TOKEN", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"),
           (MAIL_CLASS, "outlook"): ("OUTLOOK_MAIL_TOKEN",),
           (CALENDAR_CLASS, "google"): ("GOOGLE_CALENDAR_TOKEN",),
           (CALENDAR_CLASS, "outlook"): ("OUTLOOK_CALENDAR_TOKEN",)}
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


# --- the one caller of the providers (limit LS1) -----------------------------------------------------------------------------------


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
    return hashlib.sha256(f"{listed}\n{label}\n{local_date}".encode("utf-8")).hexdigest()


def read_snapshot(cfg: dict, source_type: str, origin: str, *, call=None, clock=None, zone=None) -> dict:
    """Read what a mail or calendar origin names: the provider's items of the window, nothing built yet. Returns {"type", "parts", "now",
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
                            ["--query", parts["query"], "--since", text.utc_stamp(start), "--limit", str(parts["max"]), "--own-words"], call=call)
        listed, key, limit = got.get("messages"), "change_key", parts["max"]
        first = last = None
    else:
        start, end, first, last = calendar_window(now, parts["past"], parts["ahead"], zone)
        got = provider_call(cfg, CALENDAR_CLASS, parts["implementation"], "events",
                            ["--calendar", parts["calendar"], "--from", start.isoformat(), "--to", end.isoformat(), "--max", str(EVENTS_MAX)], call=call)
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


def build_mail(source_id: str, snap: dict, *, scan=None) -> tuple:
    """(text, kept, left out) of a mail snapshot. Each message is scanned on its own; one that holds a credential shape is left out and counted by
    date and sender domain. The oldest messages are dropped, with a counted line, past the size one source may hold."""
    scan = scan or _scan
    parts, zone = snap["parts"], snap["zone"]
    views = [text.message_view(m, zone) for m in snap["items"]]
    views.sort(key=lambda v: (v["moment"] is not None, v["moment"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)), reverse=True)
    kept, left_out = [], []
    for view in views:
        if scan(text.message_block(0, view).encode("utf-8")):
            left_out.append({"date": view["date"], "domain": view["domain"], "why": WHY_CREDENTIAL})
        else:
            kept.append(view)
    blocks, used, budget = [], 0, sources.CONVERTED_CAP - SIZE_MARGIN
    for view in kept:
        block = text.message_block(len(blocks) + 1, view)
        used += len(block.encode("utf-8"))
        if used > budget:
            break
        blocks.append(block)
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
                                blocks, left_out, notes)
    return rendered, len(blocks), left_out


def build_calendar(source_id: str, snap: dict, *, scan=None) -> tuple:
    """(text, kept, left out) of a calendar snapshot. Each event (its title and place) is scanned on its own; one that holds a credential shape
    is left out and counted by date."""
    scan = scan or _scan
    zone = snap["zone"]
    kept, left_out, unreadable = [], [], 0
    for event in snap["items"]:
        view = text.event_view(event, zone)
        if view is None:
            unreadable += 1
        elif scan(text.event_block(view).encode("utf-8")):
            left_out.append({"date": view["day"].isoformat(), "why": WHY_CREDENTIAL})
        else:
            kept.append(view)
    notes = []
    if snap["truncated"]:
        notes.append(f"More events exist than the {EVENTS_MAX} read: the later ones are not in this snapshot.")
    unreadable += snap["skipped"]
    if unreadable:
        notes.append(f"{unreadable} event{' was' if unreadable == 1 else 's were'} left out: the provider's description of "
                     f"{'it' if unreadable == 1 else 'them'} could not be read.")
    rendered = text.render_calendar(source_id, snap["first"], snap["last"], snap["label"], text.utc_stamp(snap["now"]), kept, left_out, notes)
    return rendered, len(kept), left_out


def catalog_name(parts: dict, source_type: str) -> str:
    """What the catalog calls a snapshot: closed words and the numbers of the origin, no third-party text."""
    if source_type == "mail":
        return f"Mail snapshot: {parts['implementation']} {parts['box']}, {parts['days']} days"
    return f"Calendar snapshot: {parts['implementation']} calendar, {parts['past']} days back, {parts['ahead']} days ahead"


# --- import and refresh -----------------------------------------------------------------------------------------------------------


def snapshot_make(ctx, source: dict, snap: dict, *, label: str, evidence_base=None) -> dict:
    """Build the text of a reading and import it as a version of `source`. The reading time is the version's date. Returns import_version's
    answer plus {"read": True, "items": the messages or events in the text, "left_out": how many were left out}. SourcesError on any refusal,
    with nothing kept."""
    source_type = source["type"]
    builder = build_mail if source_type == "mail" else build_calendar
    rendered, kept, left_out = builder(source["id"], snap)
    start, end = (text.to_zone(m, snap["zone"]).isoformat() for m in snap["window"])
    extra = {"window_start": start, "window_end": end, "zone": snap["label"], "read_at": text.utc_stamp(snap["now"]),
             "messages" if source_type == "mail" else "events": kept, "left_out": len(left_out)}
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


def snapshot_refresh(ctx, source: dict, *, convert, call=None, clock=None, zone=None, evidence_base=None) -> dict:
    """A refresh of a mail or calendar source: the provider is read for the window as it is now. When the listing is the one recorded with the
    newest version (same ids and change keys, same local date), no version is made and the files in the folder are still checked against
    the record (limit L25); otherwise a new version is imported. Returns {"imported", "unchanged", "read", "source", "version", ...}."""
    if source.get("type") not in ("mail", "calendar"):
        raise SourcesError(f"{source.get('id')} is not a mail or calendar source", "usage")
    cfg = ctx["cfg"]
    sources.check_folder(cfg, evidence_base)
    snap = read_snapshot(cfg, source["type"], source["origin"], call=call, clock=clock, zone=zone)
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
