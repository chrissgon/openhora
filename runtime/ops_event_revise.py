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
A card that changes an event found in a snapshot is made again with the same event (`<source>#<n>`, the same calendar) and the part the person named replaced, and the new card is refused unless it names the same event id on the same calendar (a snapshot refreshed meanwhile numbers the events differently); the event of the calendar is not touched by
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
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mail_revise  # noqa: E402
import ops_card_revise as base  # noqa: E402
import ops_core as core  # noqa: E402

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


def _arguments(doc: dict, title, start, end, account):
    """(function name, arguments) of the operation that makes the new card, the old card's parts copied and the named ones replaced."""
    event, creating = doc["event"], doc["operation"] == "create"
    if creating:
        same = account in (None, doc["account"])
        return "event_create", {"account": doc["account"] if same else account, "title": title or event["title"], "start": start, "end": end,
                                "calendar": doc.get("calendar") if same else None, "location": event.get("location") or None,
                                "reminder_minutes": event.get("reminder_minutes"), "notes": event.get("notes") or None}
    reference, changed = doc["reference"], doc.get("changed") or []
    args = {"account": doc["account"], "event": f"{reference['source']}#{reference['n']}", "calendar": doc.get("calendar")}
    if title or "title" in changed:
        args["title"] = title or event["title"]
    if start != event.get("start") or end != event.get("end") or "when" in changed:
        args["start"], args["end"] = start, end
    for part in ("location", "reminder_minutes", "notes"):
        if part in changed:
            args[part] = event.get(part)
    return "event_change", args


# Words that are not the name of another event, folded: the words that ask for a change, the small words of the six languages and the words that name what is changed. What is left of a line
# once its title span, its time span, these words and the words of the card's own title are taken out is the name of ANOTHER event; the card is then left alone.
STOP = frozenset(("o a os as um uma uns umas de do da dos das no na nos nas em para pra por com e ou que se me meu minha meus minhas ate ao aos pro la ja so tambem mais "      # validate: allow english-only -- the closed small words of six languages, Portuguese among them
                  "titulo nome horario hora horas dia evento eventos agenda compromisso card cartao novo nova chama chamar renomeia renomeie "
                  "the an of to for at on in and or my it this that its from by title name time hour day event calendar appointment "
                  "el los las una unos unas del al con y mi mis hora dia titulo nombre evento cambia cambiar "
                  "le les une des du au aux pour par avec et mon ma mes titre heure jour evenement "
                  "der die das ein eine von zu fur mit und oder mein meine titel zeit uhr tag termin "
                  "il lo gli di della dello al per con mio mia titolo ora giorno "
                  "outlook google gmail microsoft hotmail").split())


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", mail_revise._fold(text or "")))


def names_another(line: str, spans: dict, doc: dict) -> bool:
    """Whether the line, outside its title and time spans, the closed words and the words of the card's own title, names something else: another event (see STOP)."""
    own = _words(doc["event"].get("title")) | _words((doc.get("before") or {}).get("title"))
    left = _words(line) - _words(spans.get("title")) - _words(spans.get("time")) - own - STOP - mail_revise.CHANGE_WORDS
    return any(not any(c.isdigit() for c in word) for word in left)


def _unchanged(old: dict, new: dict) -> bool:
    """Whether the parts of an event the line did not name are the old card's (an empty text is none)."""
    return all((new.get(k) or None) == (old.get(k) or None) for k in ("location", "notes", "reminder_minutes"))


CARD_SLOTS = ("title", "time")      # the slots of an answer that mean something for the card of an event: the card itself names the event, so every other slot is dropped


def _cleaned(obj, line: str, lookup):
    """The model's object read as a change of the card, or None: an `event-change` or an `event-create` (only when the line's own leading verb is a verb that changes) keeps its title and
    time slots and loses `event`, `calendar`, `service` and every other slot; a clarify of `event` is a change with no slot. The check of the interpreter then decides, as for any line."""
    if not isinstance(obj, dict):
        return None
    if obj.get("kind") == "op" and obj.get("op") in ("event-change", "event-create") and isinstance(obj.get("slots"), dict):
        if obj["op"] == "event-create" and lookup.verb_op(line) != "event-change":
            return None
        slots = {k: v for k, v in obj["slots"].items() if k in CARD_SLOTS}
        out = {"v": obj.get("v"), "kind": "op", "op": "event-change", "slots": slots}
        if "time" in slots:
            out.update({k: obj[k] for k in ("time_iso", "weekday") if k in obj})
        return out
    if obj.get("kind") == "clarify" and obj.get("slot") == "event" and lookup.verb_op(line) == "event-change":
        return {"v": obj.get("v"), "kind": "op", "op": "event-change", "slots": {}}
    return None


def _from_code(line: str, now, zone: str, interpreter, lookup):
    """The decision for a line whose leading verb changes an event and whose time code reads by itself (the natural time engine, through the interpreter's own rule for who may decide a
    time), or a clarify when the engine asks, or None when the line holds no time code can read. Only the time: the card names the event."""
    if lookup.verb_op(line) != "event-change":
        return None
    nt = importlib.import_module("natural_time")
    local = interpreter._local_now(now, zone)
    parsed = nt.parse(" ".join(line.split()), local)
    if not parsed or not parsed.get("spans") or parsed.get("vague"):
        return None
    collapsed = " ".join(line.split())
    span = collapsed[parsed["spans"][0][0]:parsed["spans"][-1][1]].strip()
    source, reading = interpreter._classify(span, collapsed, local)
    if source == "ask":
        return {"kind": "clarify", "error": None, "why": "time-ask", "slot": "time", "ops": None}
    if source != "code":
        return None
    return {"kind": "op", "error": None, "op": "event-change", "args": {}, "spans": {"time": span}, "time": {"local": f"{reading['date']}T{reading['time']}", "source": "code"},
            "inherited": [], "time_disagree": False}


def card_decision(ctx: dict, entry: dict, line: str, sender, doc: dict):
    """The decision for a line sent after the card of an event, or None when no call could be made. The model is called once, as the interpreter calls it, but its answer is read FOR the
    card: the card names the event, so the slot `event` (a title, a day, a number the line does not hold), an answer `event-create`, extra slots and a clarify of `event` do not make the
    line a new request. What cannot be read from the model's answer is read by code from the line (`_from_code`). The same checks decide, as for any line."""
    interpreter = importlib.import_module("interpreter")
    interpret = importlib.import_module("ops_interpret")
    lookup = importlib.import_module("event_lookup")
    ops_natural = importlib.import_module("ops_natural")
    importlib.import_module("line_stage").publish("think")
    try:
        now = ops_natural._clock()
        zone = interpret._zone(now)
        system, user = interpreter.build_messages(interpreter.SERVED, now, zone, None, line)
        got = interpret._daily_call(entry, system, user)
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the line
        got = {"ok": False}
    interpret._record(bool(got.get("ok")))
    if not got.get("ok"):
        return None
    try:
        allowed = interpret._allowed(ctx, sender)
        strict = interpret.decide(line, got.get("text"), now, zone, allowed)
        if strict.get("kind") == "op" and strict.get("op") == "event-change":
            return strict
        if strict.get("kind") not in ("clarify",):
            if strict.get("kind") == "op" and strict.get("op") == "event-create" and lookup.verb_op(line) == "event-change":
                pass      # read below as a change
            else:
                return strict      # a route, a none, a refusal, another operation: not for the card
        obj = interpreter.parse(got.get("text"))[0]
        cleaned = _cleaned(obj, line, lookup)
        if cleaned is not None:
            again = interpreter.check(cleaned, line, None, interpreter.SERVED, now, zone, allowed)
            if again.get("kind") == "op" and (again.get("spans") or again.get("time")):
                return again
            if again.get("kind") == "clarify" and str(again.get("why", "")).startswith("time"):
                return again
        coded = _from_code(line, now, zone, interpreter, lookup)
        return coded if coded is not None else interpret.lenient(line, got.get("text"), strict, now, zone, allowed)      # what is not a change of the card is read as any line is (S16)
    except Exception:      # noqa: BLE001
        return {"kind": "clarify", "error": "E_SHAPE", "why": "invalid", "slot": None, "ops": None}


def revise(project: str, ctx: dict, pending_id, entry, line: str, doc: dict, channel, sender) -> dict:
    """See the module's text."""
    interpreter = importlib.import_module("interpreter")
    interpret = importlib.import_module("ops_interpret")
    lookup = importlib.import_module("event_lookup")
    ops = importlib.import_module("ops")
    ops_natural = importlib.import_module("ops_natural")
    if interpreter.precheck(line) is not None or not interpret._admit(ctx, sender):
        return {"pass": True}
    decision = card_decision(ctx, entry, line, sender, doc)
    if decision is None:
        return {"pass": True}
    if decision.get("kind") == "clarify":
        return base.say(ctx, interpret.WHY_SENTENCE.get(decision.get("why")) or "IX_ASK_AGAIN", pending_id)
    spans, time_ = decision.get("spans") or {}, decision.get("time")
    if decision.get("kind") in ("route", "none") and mail_revise.names_object(line):
        return base.say(ctx, "RV_NOT_UNDERSTOOD_CARD", pending_id)      # it names the card and no decision is for it: told so, with the card again, never the conversation (S13b)
    if decision.get("kind") != "op" or decision.get("op") != "event-change" or names_another(line, spans, doc):
        base.remember(project, channel, sender, line, decision)      # not a change of this card: the turn that follows reads the decision that was made
        return {"pass": True}
    title = _unquote(spans["title"]) if spans.get("title") else None
    if title is not None and (not title or title == doc["event"].get("title")):
        title = None
    account = lookup.account_named(line, spans.get("title")) if doc["operation"] == "create" else None
    account = None if account == doc["account"] else account
    if title is None and not time_ and account is None:
        return base.say(ctx, "EV_CHANGE_WHAT", pending_id)
    event = doc["event"]
    start, end = event.get("start"), event.get("end")
    if time_:
        named = lookup._day_named(spans.get("time") or "", ops_natural._clock())[0]
        got = _times(event, time_["local"], named)
        if got is None:
            return base.say(ctx, "RV_FAILED", pending_id)
        start, end = got
        try:      # the moment the card will have goes through the same guard as the moment of a typed line: a time in the past, or too far, is asked
            now = ops_natural._clock()
            zone = interpret._zone(now)
            why = interpreter._instant_problem(datetime.datetime.strptime(start, STAMP), importlib.import_module("zoneinfo").ZoneInfo(zone), interpreter._local_now(now, zone))
        except (ValueError, KeyError, OSError):
            return base.say(ctx, "RV_FAILED", pending_id)
        if why:
            return base.say(ctx, interpret.WHY_SENTENCE.get(why) or "IX_ASK_AGAIN", pending_id)
    name, args = _arguments(doc, title, start, end, account)
    wanted = (args["account"], args["title"] if "title" in args else event["title"], args["start"] if "start" in args else event["start"],
              args["end"] if "end" in args else event["end"])
    grants = importlib.import_module("ops_grants")

    def open_new():
        return getattr(ops, name)(project, **{k: v for k, v in args.items() if v is not None}, channel=channel, sender=sender).get("pending")

    def matches(new_id) -> bool:
        try:
            item = core._stored(ctx, ctx["store"].pending_get, new_id)
            found = grants.effect_document(ctx, item) or {}
        except core.OpsError:
            return False
        made = found.get("event") or {}
        return (item.get("kind") == "effect" and item.get("status", "open") == "open" and found.get("operation") == doc["operation"]
                and (found.get("account"), made.get("title"), made.get("start"), made.get("end")) == wanted and _unchanged(event, made)
                and (doc["operation"] == "create" or (found.get("event_id") == doc.get("event_id") and found.get("calendar_id") == doc.get("calendar_id"))))
    return base.swap(project, ctx, pending_id, open_new, matches, "RV_DONE_EVENT", channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
