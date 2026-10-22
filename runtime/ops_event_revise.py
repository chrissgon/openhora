#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Change the card of an event by words (slice S13): the title or the time of a card that waits, with no search of the calendar and no prompt of its own.

The maintainer's live test (2026-10-22): after the card of a new event ("Título: evento social, Quando: sáb 24/10 08:00-09:00") he wrote `Mude o título do evento para "Evento Coders 26K"`
and the line went to the lookup of an event of the calendar (runtime/event_lookup.py), which found no calendar source. When the last message of the chat is a card that waits, a
change request is about THAT card.

  revise(project, ctx, pending_id, entry, line, doc, channel, sender)   {"say", "resend"}, or {"pass": True} when the line is not a change of an event
                                                                        (the decision is kept for the turn that follows: ops_card_revise.decided)

How. The line is read by the interpreter exactly as any plain line is (runtime/ops_interpret.py: the same entry, the same limits, the same checks of the spans against the line and the
same time checks, TIME-GUARD included, with all their questions). Only a decision `event-change` is a change of the card; a question the checks ask (a time that needs a day, a time that
is not clear) is asked as it is asked for any line, and every other decision goes on to the turn that reads the line. The title span replaces the title (a pair of quotation marks
around it is taken off); the time span replaces the start, on the day of the card when the span names no day, and the end keeps the length the card has; the account word of the line
(runtime/event_lookup.py `account_named`) changes the account of a card that CREATES an event (and then the calendar is the account's first, not the old account's), and nothing else.
A card that changes an event found in a snapshot is made again with the same event (`<source>#<n>`) and the part the person named replaced; the event of the calendar is not touched by
a card that creates one, and the calendar is never searched.

The new card is opened by the operation the person's own command would run (`event_create`, `event_change`), checked equal to the old card in everything the line did not name, and then the
old card is ended as rejected, so its hash is never approvable again. Nothing is written to a calendar here; the new card is approved by its own hash.

Privacy (limit L63): the line is read by the model service exactly as the interpreter reads it. Nothing is logged, printed or stored here.

Standard library only. Runs on Python 3.9: python3 runtime/ops_event_revise.py --help
"""
from __future__ import annotations

import datetime
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ops_card_revise as base  # noqa: E402
import ops_core as core  # noqa: E402
import phrases  # noqa: E402

STAMP = "%Y-%m-%dT%H:%M"
QUOTES = {'"': '"', "“": "”"}


def _unquote(span: str) -> str:
    one = " ".join(str(span).split())
    return one[1:-1].strip() if len(one) > 2 and QUOTES.get(one[0]) == one[-1] else one


def _times(event: dict, local: str, named: str):
    """(start, end) after the time said: the day of the card unless the span named one, the length the card has. None when the card is an all-day event or its times are not plain."""
    try:
        old_start, old_end = datetime.datetime.strptime(event["start"], STAMP), datetime.datetime.strptime(event["end"], STAMP)
        new_start = datetime.datetime.strptime((local[:10] if named != "none" else event["start"][:10]) + "T" + local[11:16], STAMP)
    except (KeyError, TypeError, ValueError):
        return None
    return new_start.strftime(STAMP), (new_start + (old_end - old_start)).strftime(STAMP)


def _arguments(doc: dict, title, time_, named: str, account):
    """(function name, arguments) of the operation that makes the new card, the old card's parts copied and the named ones replaced; None when this card cannot be made again."""
    event, creating = doc["event"], doc["operation"] == "create"
    start, end = event.get("start"), event.get("end")
    if time_:
        got = _times(event, time_["local"], named)
        if got is None:
            return None
        start, end = got
    if creating:
        same = account in (None, doc["account"])
        return "event_create", {"account": doc["account"] if same else account, "title": title or event["title"], "start": start, "end": end,
                                "calendar": doc.get("calendar") if same else None, "location": event.get("location") or None,
                                "reminder_minutes": event.get("reminder_minutes"), "notes": event.get("notes") or None}
    reference, changed = doc["reference"], doc.get("changed") or []
    args = {"account": doc["account"], "event": f"{reference['source']}#{reference['n']}"}
    if title or "title" in changed:
        args["title"] = title or event["title"]
    if time_ or "when" in changed:
        args["start"], args["end"] = start, end
    for part in ("location", "reminder_minutes", "notes"):
        if part in changed:
            args[part] = event.get(part)
    return "event_change", args


def revise(project: str, ctx: dict, pending_id, entry, line: str, doc: dict, channel, sender) -> dict:
    """See the module's text."""
    interpreter = importlib.import_module("interpreter")
    interpret = importlib.import_module("ops_interpret")
    lookup = importlib.import_module("event_lookup")
    ops = importlib.import_module("ops")
    if interpreter.precheck(line) is not None or not interpret._admit(ctx, sender):
        return {"pass": True}
    decision = interpret._ask_model(ctx, entry, line, sender)
    if decision is None:
        return {"pass": True}
    if decision.get("kind") == "clarify":
        return base.say(ctx, interpret.WHY_SENTENCE.get(decision.get("why")) or "IX_ASK_AGAIN")
    if decision.get("kind") != "op" or decision.get("op") != "event-change":
        base.remember(sender, line, decision)
        return {"pass": True}
    spans, time_ = decision.get("spans") or {}, decision.get("time")
    title = _unquote(spans["title"]) if spans.get("title") else None
    if title is not None and (not title or title == doc["event"].get("title")):
        title = None
    account = lookup.account_named(line, spans.get("title")) if doc["operation"] == "create" else None
    account = None if account == doc["account"] else account
    if title is None and not time_ and account is None:
        return base.say(ctx, "EV_CHANGE_WHAT")
    named = lookup._day_named(spans.get("time") or "", importlib.import_module("ops_natural")._clock())[0] if time_ else "none"
    made = _arguments(doc, title, time_, named, account)
    if made is None:
        return base.say(ctx, "RV_FAILED")
    name, args = made
    try:
        started = getattr(ops, name)(project, **{k: v for k, v in args.items() if v is not None}, channel=channel, sender=sender)
    except core.OpsError:
        return base.say(ctx, "RV_FAILED")
    new_id = started.get("pending")
    grants = importlib.import_module("ops_grants")
    try:
        item = core._stored(ctx, ctx["store"].pending_get, new_id)
        found = grants.effect_document(ctx, item) or {}
    except core.OpsError:
        item, found = {}, {}
    event = found.get("event") or {}
    wanted = (args["account"], args["title"] if "title" in args else doc["event"]["title"], args["start"] if "start" in args else doc["event"]["start"],
              args["end"] if "end" in args else doc["event"]["end"])
    if (not isinstance(new_id, int) or new_id == pending_id or item.get("kind") != "effect" or item.get("status", "open") != "open" or found.get("operation") != doc["operation"]
            or (found.get("account"), event.get("title"), event.get("start"), event.get("end")) != wanted):
        if isinstance(new_id, int) and new_id != pending_id:
            base.drop(project, new_id, channel, sender)
        return base.say(ctx, "RV_FAILED")
    return base.replace(project, ctx, pending_id, new_id, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
