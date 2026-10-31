#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Change the card of an event by words (slice S13): the title, the place, the time or the length of a card that waits, with no search of the calendar. The model sees the card.

The maintainer's live test (2026-10-22): after the card of a new event ("Título: evento social, Quando: sáb 24/10 08:00-09:00") he wrote `Mude o título do evento para "Evento Coders 26K"`
and the line went to the lookup of an event of the calendar (runtime/event_lookup.py), which found no calendar source. When the last message of the chat is a card that waits, a
change request is about THAT card. His decision of 2026-10-30 ("O modelo ve o card"): a person's request is read by the model, with the card in view; code rules stay only where the input is
fully predictable.

  revise(project, ctx, pending_id, entry, line, doc, channel, sender)   {"say", "resend"}, or {"pass": True} when the line is not a change of an event
                                                                        (the decision is kept for the turn that follows: ops_card_revise.decided)
  read_answer(text, line, doc, now, zone, allowed)                      the decision for the model's text, pure: the measurement reads the answers with it

How. The line is read by the interpreter's own call (runtime/ops_interpret.py: the same entry, the same limits, the same checks of the spans against the line and the same time checks,
TIME-GUARD included, with all their questions), with the card in view: the user turn holds a line `card:` (the title, the place, the start, the end and the weekday of the card, runtime/event_card.py) and
the prompt a fixed text that says the card is data and never an instruction. Only a decision `event-change` is a change of the card; a question the checks ask (a time that needs a day, a time that
is not clear) is asked as it is asked for any line, and every other decision goes on to the turn that reads the line. The one exception is a refusal (`refuse_policy`) on a line that names no other
object (`event_lookup.names_other_object`): the operation was the model's reading, not the person's request, so no refusal is said of it and the person is asked what to change. The answer is
read for the card: the `title` and `place` slots are a piece of the line, or the card's own text changed by the line (every word added is a word of the line, and a word added or taken out is one
the line says: origin `card-words`); `duration` with `end` is a new end, the model's count, which needs the words of the line that say it, after the start and within 24 hours; `time` is checked as
any time is (a line that says only a day and no hour is read by the time engine and keeps the card's hour); `target`, words that are not the card's own title, says the line is about another event,
and the card is left alone. The account word of the line (runtime/event_lookup.py `account_named`) changes the account of a card that CREATES an event (and then the calendar is the account's first,
not the old account's), and nothing else. Nothing of the card can become an argument of another operation: every span of every operation is a piece of the line (`interpreter.check`).
A card that changes an event found in a snapshot is made again with the same event (`<source>#<n>`, the same calendar) and the part the person named replaced, and the new card is refused unless it names the same event id on the same calendar (a snapshot refreshed meanwhile numbers the events differently); the event of the calendar is not touched by
a card that creates one, and the calendar is never searched.

The new card is opened by the operation the person's own command would run (`event_create`, `event_change`, reached through ops_facade.py), checked equal to the old card in everything the line did not name, and then the
old card is ended as rejected, so its hash is never approvable again. Nothing is written to a calendar here; the new card is approved by its own hash.

Privacy (limit L63): the line and the four fields of the card are read by the model service, on the daily route only and never a fallback. Nothing is logged, printed or stored here.

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
import event_card  # noqa: E402
import event_lookup  # noqa: E402
import interpreter  # noqa: E402
import line_stage  # noqa: E402
import mail_revise  # noqa: E402
import natural_time  # noqa: E402
import ops_card_revise as base  # noqa: E402
import ops_core as core  # noqa: E402
import ops_facade  # noqa: E402
import ops_grants  # noqa: E402
import ops_interpret  # noqa: E402
import ops_natural  # noqa: E402
import turn_gate  # noqa: E402

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


def _arguments(doc: dict, title, start, end, account, place=None):
    """(function name, arguments) of the operation that makes the new card, the old card's parts copied and the named ones replaced."""
    event, creating = doc["event"], doc["operation"] == "create"
    if creating:
        same = account in (None, doc["account"])
        return "event_create", {"account": doc["account"] if same else account, "title": title or event["title"], "start": start, "end": end,
                                "calendar": doc.get("calendar") if same else None, "location": place or event.get("location") or None,
                                "reminder_minutes": event.get("reminder_minutes"), "notes": event.get("notes") or None,
                                "repeat": (doc.get("recurrence") or {}).get("freq")}      # CB-7: a series stays a series when its waiting card is revised (weekly follows the new start's weekday); the card says it
    reference, changed = doc["reference"], doc.get("changed") or []
    args = {"account": doc["account"], "event": f"{reference['source']}#{reference['n']}", "calendar": doc.get("calendar")}
    if title or "title" in changed:
        args["title"] = title or event["title"]
    if start != event.get("start") or end != event.get("end") or "when" in changed:
        args["start"], args["end"] = start, end
    for part in ("location", "reminder_minutes", "notes"):
        if part in changed:
            args[part] = event.get(part)
    if place:
        args["location"] = place
    return "event_change", args


def _refused(ctx: dict, doc: dict, name: str, args: dict, title, time_, parts=None) -> bool:
    """Whether the gate refuses the new card (S41-7): every argument of it says where it came from, and a part the line did not name is the old card's own (`card-copy`); the title the line
    gave is its own words, the start and the end it moved are the time's reading (the engine's or the model's), and the account a line named for a card that creates an event is the person's word. One line on
    stderr names the operation and the arguments, never a value."""
    given = {k: v for k, v in args.items() if v is not None}
    parts = parts or {}
    origins = {key: "card-copy" for key in given}
    if title and "title" in given:
        origins["title"] = parts.get("title_origin") or "line-span"      # the person's own words, or the card's own words changed by the person's (`card-words`)
    if parts.get("place") and "location" in given:
        origins["location"] = parts["place_origin"]
    if time_:
        origins.update({key: turn_gate.time_origin(time_) for key in ("start", "end") if key in given})      # the engine's reading (source "code") or the model's (source "model"), as the interpreter said
    if parts.get("end") and "end" in given:
        origins["end"] = "time-model"      # the model's count of the length, after the start (checked in `revise`: words of the line say it, 0 < length <= 24 h)
    if given.get("account") != doc["account"]:
        origins["account"] = "line-span"
    op = "event-create" if name == "event_create" else "event-change"
    problems = turn_gate.provenance(op, given, origins)
    if problems:
        print(turn_gate.refusal_line(op, problems), file=sys.stderr)
    return bool(problems)


# Words that are not the name of another event, folded: the words that ask for a change, the small words of the six languages and the words that name what is changed. What is left of a line
# once its title span, its time span, these words and the words of the card's own title are taken out is the name of ANOTHER event; the card is then left alone. Since the model sees the card
# the model says it (`target`, see `target_is_another`); this closed reading stays only where code alone read the time (`_from_code`), a line the model's answer did not help.
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
    left = _words(line) - _words(spans.get("title")) - _words(spans.get("time")) - own - STOP - mail_revise.ORIGINAL_WORDS      # the words that have always asked for a change, not the verbs S13b added: an event called "Sign Day" is still another event's name
    return any(not any(c.isdigit() for c in word) for word in left)


def target_is_another(spans: dict, doc: dict) -> bool:
    """Whether the model named, as `target`, words that are not the card's own title: another event."""
    own = _words(doc["event"].get("title")) | _words((doc.get("before") or {}).get("title"))
    return any(not any(c.isdigit() for c in word) for word in _words(spans.get("target")) - own - STOP)


def day_is_another(spans: dict, doc: dict, now) -> bool:
    """Whether the model gave a `day` (the day the event is on now) that is not the card's own date: another event. A day the time engine cannot read counts as another: the line then goes on and is asked."""
    span = spans.get("day")
    if not isinstance(span, str) or not span.strip():
        return False
    try:
        card_day = datetime.date.fromisoformat(str(doc["event"].get("start"))[:10])
    except ValueError:
        return False
    kind, value = event_lookup._day_named(span, now)
    if kind == "day":
        return value != card_day
    if kind == "weekday":
        return value != card_day.weekday()
    return True


def _unchanged(old: dict, new: dict, place=None) -> bool:
    """Whether the parts of an event the line did not name are the old card's (an empty text is none); the place is the old card's unless the line gave a new one."""
    return ((new.get("location") or None) == (place or old.get("location") or None)
            and all((new.get(k) or None) == (old.get(k) or None) for k in ("notes", "reminder_minutes")))


def _grounded(value, line: str, old) -> bool:
    """Whether a text the line does not hold as written is the old text changed by the line: every word it adds and every word it takes out is a word of the line, and one of them is a word the line says
    that is not a small word of `STOP` ("muda para as 10h" does not take "para" out of "Consulta para Ana")."""
    new, was, said = _words(value), _words(old), _words(line)
    added, removed = new - was, was - new
    return bool(new) and added <= said and removed <= said and bool((added | removed) & (said - STOP))


def _only_small_words(text) -> bool:
    """Whether a span is made of the small words of `STOP` alone: no title, no place and no length."""
    return not (_words(text) - STOP)


def _text_part(value, line: str, old):
    """(the text without its quotation marks and stray punctuation, its origin) of a new title or place: a piece of the line is `line-span`; else `card-words` when `_grounded`; else None."""
    text = _unquote(value).strip(" :;,-") if isinstance(value, str) else ""
    if not text or len(text) > 200 or _only_small_words(text):
        return None
    if text in " ".join(line.split()):
        return text, "line-span"
    return (text, "card-words") if _grounded(text, line, old) else None


def _parts(slots: dict, line: str, doc: dict):
    """{"title", "title_origin", "place", "place_origin", "end"} of the parts the answer names, or None when one of them cannot be believed: then none is."""
    out = {}
    for name, old in (("title", doc["event"].get("title")), ("place", doc["event"].get("location"))):
        got = _text_part(slots[name], line, old) if name in slots else (None, None)
        if got is None:
            return None
        if got[0]:
            out[name], out[name + "_origin"] = got
    if ("duration" in slots) != ("end" in slots):
        return None
    if "end" in slots and not (isinstance(slots["duration"], str) and isinstance(slots["end"], str) and not _only_small_words(slots["duration"]) and interpreter._span_in_line(slots["duration"], line) and interpreter.TIME_RE.fullmatch(slots["end"])):
        return None
    return dict(out, end=slots["end"]) if "end" in slots else out


def _cleaned(obj, line: str, lookup, doc: dict):
    """(the model's object read as a change of the card, its parts), or None: an `event-change` or an `event-create` (only when the line's own leading verb is a verb that changes) keeps its
    `time`, `target` and `day` slots and loses `event`, `calendar`, `service` and every other slot (its title, place and end are the parts, checked by `_parts`); a clarify of `event` is a change with no
    slot. The check of the interpreter then decides, as for any line."""
    if not isinstance(obj, dict):
        return None
    if obj.get("kind") == "op" and obj.get("op") in ("event-change", "event-create") and isinstance(obj.get("slots"), dict):
        if obj["op"] == "event-create" and lookup.verb_op(line) != "event-change":
            return None
        slots = {k: v for k, v in obj["slots"].items() if k in ("time", "target", "day")}
        parts = _parts(obj["slots"], line, doc)
        if parts is None:
            return None
        out = {"v": obj.get("v"), "kind": "op", "op": "event-change", "slots": slots}
        if "time" in slots:
            out.update({k: obj[k] for k in ("time_iso", "weekday") if k in obj})
        return out, parts
    if obj.get("kind") == "clarify" and obj.get("slot") == "event" and lookup.verb_op(line) == "event-change":
        return {"v": obj.get("v"), "kind": "op", "op": "event-change", "slots": {}}, {}
    return None


RELATIVE = re.compile(r"(?<![a-z])(?:daqui|dentro de|em|in|en|dans|fra|tra|binnen|nach|apos|depois de|after)\s+(?:a\s+)?(?:\d+|um|uma|one|una|un|une|ein|eine|dois|duas|two|meia|half)(?![a-z])")


def is_relative(line: str) -> bool:
    """Whether the line gives its time as a distance from now ("daqui 2 horas", "em 30 minutos", "in 2 hours", "dentro de uma hora", "dans 2 heures"...): the natural time engine says so,
    or one of the closed forms of the six languages does. Such a time is never put on the day of the card: it is a moment counted from the clock, and it is asked."""
    collapsed = " ".join(line.split())
    return any(hit.get("kind") == "relative" for hit in natural_time.find(collapsed)["hits"]) or bool(RELATIVE.search(mail_revise._fold(collapsed)))


def _from_code(line: str, now, zone: str, interpreter, lookup):
    """The decision for a line whose leading verb changes an event and whose time code reads by itself (the natural time engine, through the interpreter's own rule for who may decide a
    time), or a clarify when the engine asks, or None when the line holds no time code can read. Only the time: the card names the event."""
    if lookup.verb_op(line) != "event-change" or line.rstrip().endswith("?"):
        return None      # a question is no change; asked again
    if is_relative(line):
        return {"kind": "clarify", "error": None, "why": "time-ask", "slot": "time", "ops": None}      # a distance from now never takes the card's day: asked
    local = interpreter._local_now(now, zone)
    parsed = natural_time.parse(" ".join(line.split()), local)
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
            "inherited": [], "time_disagree": False, "from_code": True}


def _day_only(span, line: str, doc: dict, now):
    """{"local", "source": "code"}: the day the time engine reads in a span that says a day and no hour, at the hour of the card; None for any other span. Only a plain date: no clock, no doubt."""
    if not isinstance(span, str) or not span.strip() or span not in " ".join(line.split()):
        return None
    seen = " ".join(line.split())
    found = natural_time.find(seen)
    if not found["hits"] or any(hit.get("kind") != "date" for hit in found["hits"]) or natural_time.doubt(seen):
        return None
    kind, value = event_lookup._day_named(span, now)
    start = doc["event"].get("start")
    if kind != "day" or not isinstance(start, str) or len(start) != 16:
        return None
    return {"local": value.isoformat() + "T" + start[11:], "source": "code"}


BARE_CLOCK = re.compile(r"(?:(?:as|a|ao|at|to|las|alle|um|le|la|para|pra)\s+)?(?:[1-9]|1[0-2])(?:(?::|h)(?:[0-5][0-9])?)?")      # a clock of 1 to 12 with no leading zero, no am or pm, no part of the day, no word for the hour: the only form that is ambiguous by itself; validate: allow english-only -- the small words of six languages


def _bare_clock(span) -> bool:
    return isinstance(span, str) and bool(BARE_CLOCK.fullmatch(mail_revise._fold(span).strip()))


def _model_clock(decision: dict, obj, doc: dict, now) -> dict:
    """A bare clock with no am or pm ("muda para as 9h" on a card at 19:00): when the engine's reading and the model's `time_iso` differ by exactly 12 hours on the clock, the model's reading wins, because the
    model saw the card; the day stays the card's (a line that names no day) or the engine's. It applies only when the engine's hour is 1 to 12 and the span is a closed bare-clock form (`BARE_CLOCK`): a
    time the person stated ("9am", "9pm", "as 21h", "as 09:00", "9h da noite", "meia-noite") is never overridden by the model. Any other disagreement stays as the checks left it, `time_disagree` included."""
    time_ = decision.get("time")
    if not (decision.get("time_disagree") and isinstance(time_, dict) and time_.get("source") == "code" and isinstance(obj, dict)):
        return decision
    if not _bare_clock((decision.get("spans") or {}).get("time")):
        return decision
    iso, local = obj.get("time_iso"), time_.get("local")
    if not (isinstance(iso, str) and isinstance(local, str) and interpreter.TIME_RE.fullmatch(iso) and interpreter.TIME_RE.fullmatch(local)):
        return decision
    if abs((int(iso[11:13]) * 60 + int(iso[14:16])) - (int(local[11:13]) * 60 + int(local[14:16]))) != 720 or not 1 <= int(local[11:13]) <= 12:
        return decision
    named = event_lookup._day_named((decision.get("spans") or {}).get("time") or "", now)[0]
    day = str((doc["event"].get("start") or ""))[:10] if named == "none" else local[:10]
    if len(day) != 10:
        return decision
    return dict(decision, time={"local": day + iso[10:16], "source": "model"}, time_disagree=False)


def read_answer(text, line: str, doc: dict, now, zone: str, allowed) -> dict:
    """The decision for the model's text about a line sent after the card of an event: pure (no call, no clock, no store), so that the measurement reads the answers with the product's own code.
    The card names the event, so the slot `event` (a title, a day, a number the line does not hold), an answer `event-create`, extra slots and a clarify of `event` do not make the line a new
    request. The title, the place and the end are the parts (`_parts`); what cannot be read from the model's answer is read by code from the line (`_from_code`, `_day_only`). The same checks decide,
    as for any line."""
    obj = interpreter.parse(text)[0]
    strict = ops_interpret.decide(line, text, now, zone, allowed)
    if strict.get("kind") == "op" and strict.get("op") == "event-change":
        slots = obj.get("slots") if isinstance(obj, dict) else None
        return dict(_model_clock(strict, obj, doc, now), parts=(_parts(slots, line, doc) if isinstance(slots, dict) else None) or {})
    if strict.get("kind") not in ("clarify",):
        if strict.get("kind") == "op" and strict.get("op") == "event-create" and event_lookup.verb_op(line) == "event-change":
            pass      # read below as a change
        else:
            return strict      # a route, a none, a refusal, another operation: not for the card
    if isinstance(obj, dict) and obj.get("kind") in ("route", "none", "answer"):
        return strict      # the model said the line is not for an operation (a private line it routes is a clarify here): the line is not read for the card by code either
    cleaned = _cleaned(obj, line, event_lookup, doc)
    if cleaned is not None:
        again = interpreter.check(cleaned[0], line, None, interpreter.SERVED, now, zone, allowed)
        if again.get("kind") == "op" and (again.get("spans") or again.get("time") or cleaned[1]):
            return dict(_model_clock(again, obj, doc, now), parts=cleaned[1])
        if again.get("kind") == "clarify" and str(again.get("why", "")).startswith("time"):
            day = _day_only(cleaned[0]["slots"].get("time"), line, doc, now)
            if day is None or target_is_another(cleaned[0]["slots"], doc) or day_is_another(cleaned[0]["slots"], doc, now):
                return again      # a day alone on a line about another event would take THIS card's hour for the other event: asked
            return {"kind": "op", "error": None, "op": "event-change", "args": {}, "spans": dict(cleaned[0]["slots"]), "time": day, "inherited": [], "time_disagree": False, "parts": cleaned[1]}      # the slots kept are `time` and `target`: a day alone on a line about another event must not move this card
    coded = _from_code(line, now, zone, interpreter, event_lookup)
    return coded if coded is not None else ops_interpret.lenient(line, text, strict, now, zone, allowed)      # what is not a change of the card is read as any line is (S16)


def card_decision(ctx: dict, entry: dict, line: str, sender, doc: dict, admission):
    """The decision for a line sent after the card of an event, or None when no call could be made. The model is called once, as the interpreter calls it, with the card in view
    (runtime/event_card.py: the fixed text and the line `card:`), and its answer is read FOR the card (`read_answer`). The same checks decide, as for any line."""
    line_stage.publish("think")
    try:
        now = ops_natural._clock()
        zone = ops_interpret._zone(now)
        system, user = event_card.messages(interpreter.SERVED, now, zone, doc, line)
        got = turn_gate.call(admission, entry, system, user, deadline_ms=interpreter.PROTOCOL["deadline_ms"], params=interpreter.PROTOCOL["params"])
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the line
        got = {"ok": False}
    if got.get("code") != "E_GATE":      # no usable admission is a fault of the caller, not of the provider: no call was made, so nothing is counted against the breaker
        turn_gate.record(bool(got.get("ok")))
    if not got.get("ok"):
        return None
    try:
        return read_answer(got.get("text"), line, doc, now, zone, ops_interpret._allowed(ctx, sender))
    except Exception:      # noqa: BLE001
        return {"kind": "clarify", "error": "E_SHAPE", "why": "invalid", "slot": None, "ops": None}


LEFT_TO_CODE_WHY = ("model", "invalid", "private-route")      # the reasons of a clarify that mean "the model did not read this line as a change of the card" (the generic ask-again); a question about a time stays asked


def left_to_code(decision: dict, by_code: bool) -> bool:
    """Whether a line that code owned before the model saw the card (`ops_card_revise.owned_by_code`: a reminder, a bare time, a write said in words) goes on to that path, unread and unremembered,
    because the card call answered a `route`, a `none`, an `answer` or a clarify that is not a question about a time. A private line the model routes comes back as the clarify `private-route`: it ends
    here, as the reminder path takes it, never as a lost line and never as the sentence "I was not sure what you meant" for a reminder that code can make."""
    kind = decision.get("kind")
    return bool(by_code) and (kind in ("route", "none", "answer") or (kind == "clarify" and decision.get("why") in LEFT_TO_CODE_WHY))


def change_of(decision: dict, line: str, doc: dict, now, zone: str):
    """Pure (no call, no store, no clock of its own): what a decision that is not a question makes of the card. ("pass", None) when it is not a change of THIS card (the turn that follows reads it),
    ("say", the phrase key) when the person is asked or told, ("change", {"title", "place", "start", "end", "account", "time", "parts"}) with the parts that change (None for a part that stays).
    The order of the checks is the order in which a card is made: the measurement reads the same function."""
    spans, time_, parts = decision.get("spans") or {}, decision.get("time"), decision.get("parts") or {}
    if (decision.get("kind") != "op" or decision.get("op") != "event-change" or target_is_another(spans, doc) or day_is_another(spans, doc, now)
            or (decision.get("from_code") and names_another(line, spans, doc))):
        return "pass", None
    title = parts.get("title") or (_unquote(spans["title"]) if spans.get("title") else None)
    if title is not None and (not title or title == doc["event"].get("title")):
        title = None
    seen = line
    for key in ("title", "place"):
        if parts.get(key):
            seen = seen.replace(parts[key], " ")      # the brand of a service inside a new title or place ("o escritorio no Outlook") is not the account word of the line
    account = event_lookup.account_named(seen, spans.get("title")) if doc["operation"] == "create" else None
    account = None if account == doc["account"] else account
    place = parts.get("place")
    place = None if place == doc["event"].get("location") else place
    if title is None and not time_ and account is None and place is None and not parts.get("end"):
        return "say", "EV_CHANGE_WHAT"
    event = doc["event"]
    start, end = event.get("start"), event.get("end")
    if time_ and is_relative(line):
        return "say", ops_interpret.WHY_SENTENCE["time-ask"]      # "daqui 2 horas" is a moment counted from now, not an hour of the card's day: asked, whoever read it
    if time_:
        named = event_lookup._day_named(spans.get("time") or "", now)[0]
        got = _times(event, time_["local"], "model" if time_.get("source") == "model" else named)
        if got is None:
            return "say", "RV_FAILED"
        start, end = got
        try:      # the moment the card will have goes through the same guard as the moment of a typed line: a time in the past, or too far, is asked
            why = interpreter._instant_problem(datetime.datetime.strptime(start, STAMP), importlib.import_module("zoneinfo").ZoneInfo(zone), interpreter._local_now(now, zone))
        except (ValueError, KeyError, OSError):
            return "say", "RV_FAILED"
        if why:
            return "say", ops_interpret.WHY_SENTENCE.get(why) or "IX_ASK_AGAIN"
    if parts.get("end"):
        try:
            length = datetime.datetime.strptime(parts["end"], STAMP) - datetime.datetime.strptime(start, STAMP)
        except (TypeError, ValueError):
            return "say", "RV_FAILED"
        if not datetime.timedelta(0) < length <= datetime.timedelta(hours=24):
            return "say", "IX_ASK_AGAIN"
        end = parts["end"]
    return "change", {"title": title, "place": place, "start": start, "end": end, "account": account, "time": time_, "parts": parts}


def revise(project: str, ctx: dict, pending_id, entry, line: str, doc: dict, channel, sender) -> dict:
    """See the module's text."""
    admission = None if interpreter.precheck(line) is not None else turn_gate.admit(ctx, sender)
    if admission is None:
        return {"pass": True}
    decision = card_decision(ctx, entry, line, sender, doc, admission)
    if decision is None:
        return {"pass": True}
    by_code = base.owned_by_code(ctx, line, sender)
    if left_to_code(decision, by_code):
        return {"pass": True}      # a reminder, a bare time or a write said in words that the card call did not read as a change of the card: it takes the path it would have taken, unread and unremembered
    if decision.get("kind") == "clarify":
        return base.say(ctx, ops_interpret.WHY_SENTENCE.get(decision.get("why")) or "IX_ASK_AGAIN", pending_id)
    if decision.get("kind") == "refuse_policy" and not by_code and not event_lookup.names_other_object(line):
        return base.say(ctx, "EV_CHANGE_WHAT", pending_id)      # the model named an operation the sender may not ask and the line names no other object: the operation was the model's reading, not the person's request, so no refusal is said of it; the card is sent again
    now = ops_natural._clock()
    verdict, made = change_of(decision, line, doc, now, ops_interpret._zone(now))
    if verdict == "pass":
        base.remember(project, channel, sender, line, decision)      # not a change of this card: the turn that follows reads the decision that was made
        return {"pass": True}
    if verdict == "say":
        return base.say(ctx, made, pending_id)
    title, place, start, end, account, time_, parts = (made[k] for k in ("title", "place", "start", "end", "account", "time", "parts"))
    event = doc["event"]
    name, args = _arguments(doc, title, start, end, account, place)
    refused = _refused(ctx, doc, name, args, title, time_, parts)
    if refused:
        return base.say(ctx, "RV_FAILED", pending_id)          # nothing was ended and nothing opened: the card stays as it was
    wanted = (args["account"], args["title"] if "title" in args else event["title"], args["start"] if "start" in args else event["start"],
              args["end"] if "end" in args else event["end"])

    def open_new():
        return ops_facade.function(name)(project, **{k: v for k, v in args.items() if v is not None}, channel=channel, sender=sender).get("pending")

    def matches(new_id) -> bool:
        try:
            item = core._stored(ctx, ctx["store"].pending_get, new_id)
            found = ops_grants.effect_document(ctx, item) or {}
        except core.OpsError:
            return False
        made = found.get("event") or {}
        return (item.get("kind") == "effect" and item.get("status", "open") == "open" and found.get("operation") == doc["operation"]
                and (found.get("account"), made.get("title"), made.get("start"), made.get("end")) == wanted and _unchanged(event, made, place)
                and (doc["operation"] == "create" or (found.get("event_id") == doc.get("event_id") and found.get("calendar_id") == doc.get("calendar_id"))))
    return base.swap(project, ctx, pending_id, open_new, matches, "RV_DONE_EVENT", channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
