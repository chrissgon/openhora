#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The events this platform itself created in the person's calendar (slice S16): the ledger read behind "remove the haircut for tomorrow" when no calendar source holds it.

A calendar write is a card the person approves by its hash (runtime/step_calendar_event.py). The approved card of a new event is kept by the store as a decision whose payload holds the
step (`calendar-event`), the recorded result (the provider's event id, the account, the calendar and its id: runtime/calendar_document.py `facts`) and the hash of the effect document;
the document itself (runtime/effect_calendar.py) holds the event as it was approved (title, start, end) in the runtime's data folder, 0600, read only with its hash checked
(`ops_step_seams.EffectFiles.read`). This file reads those and nothing else; it calls no provider and writes nothing, except `live`, which reads one event back.

  created(ctx)                  [row] for each event an approved create made, newest state: a later approved change of that event replaces its times and title, a later approved removal
                                takes it out. A row is {"source": "created", "pending": the card that created it, "account", "calendar", "calendar_id", "event_id", "title", "start",
                                "end" (wall times, `YYYY-MM-DDTHH:MM` or a day), "day": the date, "time": "13:00-14:00" or "all day", "all_day"}. Rows are in the order of their start.
  by_pending(ctx, pending)      the row of one create card, or None (removed since, or no such card)
  live(ctx, row)                True only when the provider still holds the event, at the times the ledger says: the read the card's own preparation makes (`CalendarReader.event_get`), made
                                once more here so that a moved or deleted event is dropped from the search instead of being named. Any failure is False.

Reading the event back by its id, for an event the platform wrote, is a read the right to read the calendar covers (contracts/runtime.md, limit L52); the card that follows reads it again
and pins its version (L56), so nothing here decides what is written. Privacy (L63): titles of the person's own calendar are returned to the caller and never logged, printed or kept here.
Standard library only. Runs on Python 3.9: python3 runtime/event_created.py --help
"""
from __future__ import annotations

import datetime
import importlib
import sys

SOURCE = "created"          # the `source` word of a row (not a source id: the registry's ids are never this word followed by a number)
SCAN_MAX = 2000             # decisions read, newest first: the ledger of a long-lived project is not walked for ever


def _seams():
    return importlib.import_module("ops_step_seams")


def _document(ctx: dict, item: dict):
    """The effect document of an approved card, hash checked, or None when it cannot be read."""
    payload = item["payload"]
    try:
        return _seams().EffectFiles(ctx["cfg"]).read(item["task_id"], int(payload.get("cycle", 0)), item["payload_sha256"])
    except Exception:      # noqa: BLE001 - a missing or changed file is no event; nothing of the fault is kept
        return None


def _row(pending: int, doc: dict) -> dict:
    event = doc["event"]
    first, last = event["start"], event["end"]
    day = datetime.date.fromisoformat(first[:10])
    if event["all_day"]:
        shown = "all day"
    elif first[:10] == last[:10]:
        shown = f"{first[11:16]}-{last[11:16]}"
    else:
        shown = f"{first[11:16]}-{last[11:16]} ({last[:10]})"
    return {"source": SOURCE, "pending": pending, "account": doc["account"], "calendar": doc["calendar"], "calendar_id": doc["calendar_id"], "event_id": doc["event_id"],
            "title": event["title"], "start": first, "end": last, "day": day, "time": shown, "all_day": event["all_day"]}


def _effects(ctx: dict) -> list:
    """The approved calendar-event decisions, oldest first (the newest SCAN_MAX of them)."""
    store = ctx["store"]
    try:
        listed = store.pending_list(ctx["conn"], "all")
    except Exception:      # noqa: BLE001 - the store's refusal is no event
        return []
    out = []
    for item in listed[-SCAN_MAX:]:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        step, result = payload.get("step") or {}, payload.get("result")
        if item.get("kind") == "effect" and item.get("resolution") == "approved" and step.get("kind") == "calendar-event" and isinstance(result, dict) \
                and isinstance(result.get("event_id"), str) and result.get("operation") in ("create", "change", "cancel") and isinstance(item.get("payload_sha256"), str):
            out.append(item)
    return out


def created(ctx: dict) -> list:
    """The events the platform created and has not removed since, in the order of their start (see the module's text)."""
    kept = {}
    for item in _effects(ctx):
        result = item["payload"]["result"]
        key = (result.get("account"), result["event_id"])
        operation = result["operation"]
        if operation == "cancel":
            kept.pop(key, None)
            continue
        if operation == "change" and key not in kept:
            continue          # an event the platform did not create: its change is no record of one
        doc = _document(ctx, item)
        if not isinstance(doc, dict) or not isinstance(doc.get("event"), dict):
            continue
        try:
            if operation == "create":
                kept[key] = _row(item["id"], dict(doc, event_id=result["event_id"]))          # the document of a create holds no event id: the result has the provider's
            else:
                before = kept[key]
                kept[key] = _row(before["pending"], dict(doc, event_id=before["event_id"], calendar=before["calendar"], calendar_id=before["calendar_id"]))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(kept.values(), key=lambda r: (r["start"], r["pending"]))


def by_pending(ctx: dict, pending) -> "dict | None":
    return next((r for r in created(ctx) if r["pending"] == pending), None)


def live(ctx: dict, row: dict) -> bool:
    """Whether the provider holds the event at the times of the row (see the module's text)."""
    try:
        seams = _seams()
        reader = seams.CalendarReader(ctx)
        if not reader.enabled(row["account"]):
            return False
        got = reader.event_get(row["account"], row["calendar_id"], row["event_id"])
        raw = got.get("event") if isinstance(got, dict) and got.get("found") is True else None
        if raw is None:
            return False
        document = importlib.import_module("calendar_document")
        event = document.from_service(raw)
        return (event["start"], event["end"], event["all_day"]) == (row["start"], row["end"], row["all_day"])
    except Exception:      # noqa: BLE001 - no read, no event: the search drops it and says nothing of the fault
        return False


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
