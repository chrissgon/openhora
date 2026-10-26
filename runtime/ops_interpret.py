#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The natural-language interpreter on a messaging line (slice S1): what the conversation does with a plain line that no list of code took.

A sibling of runtime/ops_say.py, which calls `enabled` and `turn` at its one seam (runtime/ops_turn.py, the row `interpreter` of the table of runtime/turn_order.py: after every row of code returned None and the sender may talk) and
imports this file at call time. It reaches nothing of ops.py. Page, terminal and chat never get here; neither does a line that code claims (a typed command, a
question about the state, a tier-1 form, a reminder or a write in the words of the pt/en tables, the answer to a draft): the order is the hybrid the maintainer
confirmed on 2026-10-21, so the interpreter reads only the rest.

  enabled(ctx, channel, sender)   messaging, the sender holds the group `interpret`, and the newest entry of runtime/interpreter_enable.json is in force for the project's language
  turn(project, ctx, said, sender, extras)
                                  the reply tuple of ops_say (reply, request_id, pending_id, ran, run_id), or None when the line is to be routed to the planning agent as today
                                  or answers the sender's bound router question (`extras["frame"]`, below)
  decide(line, text, now, zone, allowed, frame=None)   the decision for a model's text: `parse` then `check`, exactly as the measured pipeline does (pure; a test compares them)

The typed frame (slice S4). When the sender has a router question bound to them (runtime/ops_say.py `_bound_question`, decision 229 (1)), ops_say puts its age in `extras["frame_age"]` and the
frame is the one item `{"id": "i1", "kind": "router-question", "need": "text", "age_s": <seconds>}` built by `interpreter.typed_frame`: the id, the kind, the need and the age
and nothing else, so that neither the question's words nor its number ever reach the model. A decision `answer` of `i1` sets `extras["frame"] = "answer"` and returns None (the
line is the answer to the question); a decision `route` sets `extras["frame"] = "new"` and returns None (a new request). `check` refuses any other item id (E_ITEM_UNKNOWN), and
the sentence is IX_ASK_AGAIN with the question still open. Without a bound question the frame is none, as in S1. A sender with a live "Shall I go ahead?" (BL2a, limit L65: runtime/plan_confirm.py) has a second kind of item, `plan-confirm` (`frame_for`):
its id (`i2` beside the router's `i1`, else `i1`), its need (`confirm`), the operation and the age and nothing else, and `last` holds the plan's own words (the spans code checked in the person's
line), so that a correction ("no, for tomorrow") is a new turn that states a new plan or inherits a span of the old words. A decision `answer` of the plan item with `confirm` `no` that carries a new detail (BL5B) is the corrected request and asks a NEW plan (`interpreter._plan_correction`; the prompt's rule 9
asks the model for an op object); a bare no, a no with a courtesy ("no, thanks") or a no that changes nothing drops the plan; with `yes`
it runs nothing and says to reply to the question (`PLAN_NOT_LAST`): only code's reading of the person's yes, passed by the bridge as `plan_ok`, runs a plan.

The steps of `turn`: `interpreter.precheck`; the limits below; `interpreter.build_messages` (the user turn is five lines made
of the date, the time, the zone, the frame and the person's own collapsed line: nothing of any third party); one call to the daily route; `parse`; `check` against the line;
then the decision is carried out by the call that already exists for it (`ops_natural.run`, `ops_natural_writes.open_line`) or answered by a fixed sentence. Nothing
the model wrote in this call is ever shown, and nothing here approves, sends or writes: a card is opened by `open_line` and approved on its button by its hash. One exception,
by the maintainer's decision of 2026-10-20 (slice S7): a new e-mail (`mail-send`, `mail-draft` with no message) opens its card through the seed of `mail_compose.seed`, and the
text on that card may be worded by a second call (runtime/mail_compose.py), validated by code, with the person's own words as the fallback.

A decision the model names (slice S20). The catalog lists `approve`, `reject`, `release`, `answer` and `go-ahead` as refused; the model names one and never gives its number, and code reads the number
from the line (`natural.decision_numbers`: the one whole number written in it, none in a line that says a date or a time). `reject` and `release` are then the typed commands (`ops_natural.run` hands
the bridge the typed line), `approve` sends the decision's card again and approves nothing, and `answer` and `go-ahead` have words of their own. No operation was added to the catalog.

The call. It is the gate's (`turn_gate.call`, runtime/turn_gate.py): the route is taken from `interpreter_route.daily_routes()` (kind http only) and its kind is checked again
there, so a route of any other kind cannot be called from here; the entry that enables the interpreter names the route and the hashes it was decided on (runtime/interpreter_enable.py).

The limits live in `turn_gate` (counts in memory, this slice's choice, not measured): `turn_gate.admit` allows RATE_MAX calls per sender in RATE_WINDOW seconds, DAY_MAX per project
per local day, and an open breaker for BREAKER_OPEN seconds after BREAKER_FAILS failed calls in a row (`turn_gate.record`); no state lives in this file. When there is no call (entry off, a limit reached, a failed call, a zone that cannot be
named) a line that is not private and a project in pt-BR or en go to the planning agent as before; any other gets the sentence IX_OUTAGE.

Privacy (limit L63): no line, span, model text or exception message is logged, printed or kept here. The conversation stores the person's line only after the decision,
and as a neutral word unless the line was sent to the planning agent (`extras["interpreted"]`, read by ops_say.say); this file stores nothing.

Standard library only. Runs on Python 3.9: python3 runtime/ops_interpret.py --help
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from zoneinfo import ZoneInfo

import event_lookup
import interpreter
import interpreter_enable
import language as language_rules
import line_stage
import mail_compose
import natural
import operations
import ops_natural
import phone_refusal
import phrases
import plan_confirm
import turn_gate

CHANNEL = "messaging"
ROUTE_LANGUAGES = ("pt-BR", "en")      # the project languages whose tables detect a private line: only there a model failure may route a line to the agent
ZONE_NAME = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*")
WHY_SENTENCE = {"time-ask": "IX_ASK_TIME", "time-gap": "IX_ASK_TIME", "time-fold": "IX_ASK_TIME", "weekday": "IX_ASK_TIME", "time-past": "IX_ASK_PAST",
                "time-far": "IX_ASK_FAR", "long-line": "IX_LONG_LINE"}      # every other why (model, invalid, private-route) is IX_ASK_AGAIN


def forget_all() -> None:
    """Kept for the tests that reset a process; no state lives here: the counts and the breaker are the gate's (runtime/turn_gate.py)."""
    turn_gate.forget_all()


def _tag(cfg: dict) -> str:
    return language_rules.effective(None, cfg.get("language"))[0]


def enabled(ctx: dict, channel, sender) -> bool:
    """Whether a plain line of this sender is read by the interpreter: messaging, the group `interpret`, and the enabling entry in force for the project's language."""
    if channel != CHANNEL:
        return False
    cfg = ctx["cfg"]
    return operations.holds("interpret", CHANNEL, cfg["channels"], sender) and interpreter_enable.active(_tag(cfg)) is not None


# --- the call and the decision -------------------------------------------------------------------------------------------------------------------------


def _zone(now) -> str:
    """The IANA name of the machine's zone (TZ, else where the local-time file points), the zone the reminders and the calendar read their wall times in. ValueError when
    none can be named: the interpreter then makes no call."""
    for found in (os.environ.get("TZ", "").lstrip(":"), os.path.realpath("/etc/localtime").partition("zoneinfo/")[2]):
        if found and ZONE_NAME.fullmatch(found) and ".." not in found:
            try:
                ZoneInfo(found)
            except Exception:      # noqa: BLE001 - a name no zone database knows
                continue
            return found
    raise ValueError("no zone")


def decide(line: str, text, now, zone: str, allowed, frame=None) -> dict:
    """The decision for a model's text about a line: the measured pipeline's own two calls, `parse` and `check` (with the typed frame of the bound router question, or none)."""
    obj, _, error = interpreter.parse(text)
    if obj is None:
        return {"kind": "clarify", "error": error, "why": "invalid", "slot": None, "ops": None}
    return interpreter.check(obj, line, frame, interpreter.SERVED, now, zone, allowed)


ASK_AGAIN_WHY = {"E_INT": "slot not a number written in the line", "E_SPAN": "span not in the line", "E_SLOT_UNKNOWN": "slot the op does not have", "E_OP_UNKNOWN": "unknown op",
                 "E_JSON": "parse invalid", "E_SIZE": "parse invalid", "E_SHAPE": "parse invalid", "E_VERSION": "parse invalid", "E_TIME_FORMAT": "parse invalid",
                 "E_WEEKDAY": "time and weekday disagree", "E_INHERIT": "inherit refused", "E_ITEM_UNKNOWN": "unknown frame item"}      # closed words: the reason an ask-again is said in the log, never a value of the line


def ask_again_reason(decision: dict) -> str:
    """The closed reason a decision ends in the sentence IX_ASK_AGAIN, for the service log: a word of ASK_AGAIN_WHY or of the few below, never the line, a span, a slot value or the
    model's text (limit L63)."""
    kind, why = decision.get("kind"), decision.get("why")
    if kind == "refuse_policy":
        return "policy refuses the op with no sentence"
    if kind != "clarify":
        return "decision not understood"
    if why == "invalid":
        return ASK_AGAIN_WHY.get(decision.get("error"), "decision invalid")
    if why == "private-route":
        return "private line sent to the model's route"
    if why == "model":
        return "model asked for a slot" if decision.get("slot") else "model asked between ops"
    return "clarify"


def _log_ask_again(decision: dict) -> None:
    """One line on stderr (the service log) for each line answered with IX_ASK_AGAIN: the closed reason only."""
    try:
        print(f"interpreter: ask-again ({ask_again_reason(decision)})", file=sys.stderr, flush=True)
    except Exception:      # noqa: BLE001 - a closed stream is no reason to fail the turn
        pass


def _event_slots_fixed(obj: dict, line: str):
    """The object of an event to change or cancel with the slots the check cannot believe left out, or None when nothing is left out (slice S16). The event of such a line is found
    from the words of the line (runtime/event_lookup.py), so a number slot that is not a number written in the line (the model wrote the event's name there), and, for a removal, any
    slot the operation does not have (a title, a time) are dropped, while the event's name (`target`) and day (`day`) a removal does have are kept (BL5C); a time or a title of a change
    that does not pass stays refused as before."""
    slots = dict(obj["slots"])
    fixed = {k: v for k, v in slots.items() if not (k == "event" and not natural.check_operation(obj["op"], {"event": v}, None, line)["ok"])}
    if obj["op"] == "event-cancel":
        fixed = {k: v for k, v in fixed.items() if k in ("event", "target", "day")}
    if fixed == slots:
        return None
    out = {k: v for k, v in obj.items() if k != "slots"}
    out["slots"] = fixed
    if obj["op"] == "event-cancel":
        out.pop("time_iso", None)
        out.pop("weekday", None)
        out.pop("inherit", None)
    return out


def _by_verb(line: str, strict: dict, now, zone: str, allowed, frame, obj) -> dict:
    """The decision for a line that asks to change or cancel an event by its name when the model's answer cannot be believed (slices S16b): the operation is the one the line's own
    leading verb names, the time is what the time engine reads without doubt (`event_lookup._code_time`), and the event is found by the closest name afterwards. It applies only when ALL
    hold: (a) the model's answer is garbage (nothing parses), or a clarify of the slot `event`; (b) the line names no other object (a mail, a file, a reminder, a routine, a task, a
    folder, a request, an address) and is no question, no condition and no two verbs; (c) a verb that changes or cancels leads the line. A model that named an operation (an event
    one of the other kind is never swapped, and a refused op of another family stays refused) or asked about another slot keeps its refusal."""
    op = event_lookup.verb_op(line)          # (c)
    if op is None or event_lookup.names_other_object(line) or event_lookup.asks_again(line):          # (b)
        return strict
    if obj is not None and not (obj.get("kind") == "clarify" and obj.get("slot") == "event"):          # (a)
        return strict
    again = interpreter.check({"v": 1, "kind": "op", "op": op, "slots": {}}, line, frame, interpreter.SERVED, now, zone, allowed)
    if again.get("kind") == "op" and op == "event-change":
        again = dict(again, time=event_lookup._code_time(line, now))
    return again if again.get("kind") in ("op", "refuse_policy") else strict


def lenient(line: str, text, strict: dict, now, zone: str, allowed, frame=None) -> dict:
    """`strict`, the decision `decide` gave, or the decision for the line read as the event it describes (slices S16, S16b). Only a refused decision is read again, and only for a
    line whose leading verb asks to change or cancel an event (`event_lookup.verb_op`) and that names no other object, is no question, carries no condition and has one such verb.
    When the model named the same operation as that verb, an op object whose `event` slot is not a number of the line (or, for a removal, that has a slot the operation lacks) is
    checked again without those slots. A model that named the other event operation, or any other operation, keeps the refusal: it is never swapped for the verb's. Garbage, or a
    clarify of the slot `event`, gets the operation of the verb and the event is found by the name in the line (`_by_verb`). The event is always found from the person's own words
    by code afterwards, never from the model's."""
    if strict.get("kind") != "clarify" or strict.get("why") not in ("invalid", "model"):
        return strict
    obj, _, _ = interpreter.parse(text)
    if obj is not None and obj.get("kind") == "op":
        if obj.get("op") not in event_lookup.OPS or event_lookup.verb_op(line) != obj["op"] or event_lookup.names_other_object(line) or event_lookup.asks_again(line):
            return strict
        fixed = _event_slots_fixed(obj, line)
        if fixed is None:
            return strict
        again = interpreter.check(fixed, line, frame, interpreter.SERVED, now, zone, allowed)
        return again if again.get("kind") in ("op", "refuse_policy") else strict
    return _by_verb(line, strict, now, zone, allowed, frame, obj)


def frame_for(age_s, plan=None):
    """The typed frame for what the sender has open (BL2a): the router question bound to them (one item: `i1`, kind, need and age, none of its words), and their live plan, the
    "Shall I go ahead?" code asked (a `plan-confirm` item: its operation and age, id `i2` when the router's item is there, else `i1`; `last` holds the plan's own words, the spans code
    checked in their line, so that a correction may inherit one). None when nothing is open. A plan the frame cannot hold (an operation the catalog lacks) is left out."""
    items = []
    if age_s is not None:
        items.append({"id": "i1", "kind": "router-question", "need": "text", "age_s": age_s})
    last = None
    if plan is not None:
        item, last = plan_confirm.frame_parts(plan)
        items.append(dict(item, id=plan_item_id(age_s)))
    if not items:
        return None
    for attempt in ((items, last), (items, dict(last, own_words={})) if last else None, (items[:1], None) if age_s is not None else None):      # the plan with its words, the plan with none, the router's item alone
        if attempt is None:
            continue
        try:
            return interpreter.typed_frame(attempt[0], attempt[1], {})
        except ValueError:
            continue
    return None


def plan_item_id(age_s) -> str:
    """The id the plan's item has in the frame: `i2` after the router's `i1`, else `i1`."""
    return "i1" if age_s is None else "i2"


def router_frame(age_s):
    """The typed frame for a router question bound to the sender: one item, the question's id (`i1`), kind, need and age, and none of its words (None: no question is bound)."""
    return frame_for(age_s, None)


def _allowed(ctx: dict, sender) -> set:
    """The operations of the served catalog this sender may ask from a phone under the project's policy (the check also re-runs when the operation is carried out)."""
    policy = ctx["cfg"]["channels"]
    return {row["op"] for row in interpreter.SERVED["ops"] if operations.permitted(row["op"], CHANNEL, policy, None, sender)}


def _ask_model(ctx: dict, entry: dict, said: str, sender, admission, frame=None):
    """The decision for the line, or None when no call could be made or it failed. The call is the gate's (`turn_gate.call`) and needs the `admission` `turn_gate.admit` gave this line."""
    line_stage.publish("think")      # S19: the stage a phone is told if the line is still unanswered after a while
    try:
        now = ops_natural._clock()
        zone = _zone(now)
        system, user = interpreter.build_messages(interpreter.SERVED, now, zone, frame, said)
        protocol = interpreter.PROTOCOL
        got = turn_gate.call(admission, entry, system, user, deadline_ms=protocol["deadline_ms"], params=protocol["params"])
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the line
        got = {"ok": False}
    if got.get("code") != "E_GATE":      # no usable admission is a fault of the caller, not of the provider: no call was made, so nothing is counted against the breaker
        turn_gate.record(bool(got.get("ok")))
    if not got.get("ok"):
        return None
    try:
        allowed = _allowed(ctx, sender)
        return lenient(said, got.get("text"), decide(said, got.get("text"), now, zone, allowed, frame), now, zone, allowed, frame)
    except Exception:      # noqa: BLE001
        return {"kind": "clarify", "error": "E_SHAPE", "why": "invalid", "slot": None, "ops": None}


# --- the turn ------------------------------------------------------------------------------------------------------------------------------------------


def _said(text: str, extras: dict) -> tuple:
    return text, None, None, False, extras.get("run_id")


def _no_decision(ctx: dict, said: str, extras: dict):
    """No decision (entry off, a limit, a failed call): a line that is not private, in a project whose tables detect private lines, goes to the planning agent as before;
    any other gets the sentence."""
    if _tag(ctx["cfg"]) in ROUTE_LANGUAGES and not natural.private(said):
        extras["interpreted"] = False
        return None
    return _said(phrases.text("IX_OUTAGE", ctx["cfg"]), extras)


def _refusal(ctx: dict, op: str, sender) -> str:
    """The sentence the typed command gets when the policy refuses the operation to this sender (a phone is told where, never a command)."""
    try:
        listed = CHANNEL in operations.by_name(op)["channels"]
    except KeyError:
        listed = False
    if not listed:
        return ops_natural.phone_sentence(ctx, op)
    refused = operations.refusal(op, CHANNEL, ctx["cfg"]["channels"], sender=sender)
    if refused:
        return phone_refusal.said(refused, CHANNEL, ctx["cfg"])
    _log_ask_again({"kind": "refuse_policy"})
    return phrases.text("IX_ASK_AGAIN", ctx["cfg"])      # S10: a phone is told in one plain sentence, never "error:" or a command


MAIL_TARGET_OPS = ("mail-reply", "mail-draft", "mail-archive", "mail-trash", "mail-move", "mail-mark")      # B''-lite: the mail operations whose message the person names by its words (target, day)
CANNOT = {"event-create": "IX_CANNOT_EVENT_CREATE"}      # every other write: IX_CANNOT_WRITE (an event to change or cancel is answered by runtime/event_lookup.py)


def _cannot(ctx: dict, op: str) -> str:
    """The sentence for a write that could not be prepared. IX_WRITE_LANGUAGE is true only for a project language with no write forms (the tables detect them in pt-BR and en
    alone); in those two the sentence says what was understood and what is missing, never a language."""
    if _tag(ctx["cfg"]) not in ROUTE_LANGUAGES:
        return phrases.text("IX_WRITE_LANGUAGE", ctx["cfg"])
    return phrases.text(CANNOT.get(op, "IX_CANNOT_WRITE"), ctx["cfg"])


def _day_read(span: str, now) -> dict:
    """The day a verified `day` span names, read by code for the mail family, which reads no calendar and no clock (runtime/ops_natural_mail.py `_on_day`): {"kind": "day" | "weekday" |
    "none" | "unread", "value" (an ISO date, a weekday number 0-6 or None), "today" (an ISO date), "zone" (the machine's IANA zone name, or None when none can be named)}."""
    kind, value = event_lookup._day_named(span, now)
    try:
        zone = _zone(now)
    except ValueError:
        zone = None
    return {"kind": kind, "value": value.isoformat() if kind == "day" else value, "today": now.date().isoformat(), "zone": zone}


def _carry_out(project: str, ctx: dict, decision: dict, said: str, sender, extras: dict) -> tuple:
    """An operation the check believed: a write opens its card through its family (a seed of the time when the model gave one; an event to change or cancel found by the
    words of the line, runtime/event_lookup.py), every other class goes through the dispatcher of the natural requests, which asks the policy again. Nothing is executed here."""
    op, time_ = decision["op"], decision.get("time")
    if natural.class_of(op) == "E":
        writes = importlib.import_module("ops_natural_writes")
        if op == "event-create" and time_:
            local = time_["local"]
            seed = {"op": op, "reading": {"date": local[:10], "time": local[11:16]}, "text": decision["spans"].get("title") or ""}
            sentence = event_lookup.seed_service(ctx, decision, said, extras, seed)          # S11: "no outlook" chooses the service; one that is not set up is one sentence
            if sentence:
                return _said(sentence, extras)
            opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed=seed)
        elif (mail := mail_compose.seed(op, decision, said)) is not None:          # a new e-mail: the card is opened from the verified spans, never from the closed forms (slice S7)
            opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed=mail)
        elif op in event_lookup.OPS and _tag(ctx["cfg"]) in ROUTE_LANGUAGES:
            opened = event_lookup.open_event(project, ctx, decision, said, sender, extras, writes, ops_natural._clock())
        elif op == "file-trash":          # R2-A: the file is found by the words of the line, by the search of `file-read`, and its card opens (runtime/ops_file_trash.py)
            opened = importlib.import_module("ops_file_trash").reply(project, ctx, decision["args"], said, CHANNEL, sender, extras)
        elif (op in MAIL_TARGET_OPS and _tag(ctx["cfg"]) in ROUTE_LANGUAGES and (decision["spans"].get("target") or decision["spans"].get("day"))
              and "message" not in decision["args"] and "messages" not in decision["args"]):          # B''-lite: a message named by its words (target, day), found by code in the index (runtime/ops_natural_mail.py)
            spans = decision["spans"]
            seed = importlib.import_module("ops_natural_mail").mail_target_seed(op, decision, _day_read(spans["day"], ops_natural._clock()) if spans.get("day") else None, said)
            opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed=seed) if seed is not None else None
        else:
            opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, hint=op)
        return _said(opened if opened is not None else _cannot(ctx, op), extras)
    when = time_["local"].replace("T", " ") if time_ else None
    reply = ops_natural.run(project, ctx, op, decision["args"], said, CHANNEL, sender, extras, when=when, routed=True)
    return _said(reply, extras)


DECIDED = ("approve", "reject", "release")      # the decisions a line names by a number written in it (slice S20); `answer` and `go-ahead` have words of their own


def _decided(project: str, ctx: dict, op: str, said: str, sender, extras: dict) -> tuple:
    """The reply for a decision the model named (slice S20). The number is the one number WRITTEN in the line, read by code (never the model's); a line with none, or with two,
    asks which. `reject` and `release` are run as their typed lines are, `approve` sends the decision's card again and approves nothing (all of it is `ops_natural.run`, which
    asks the policy as the typed command is asked); an `answer` is a reply to the question, and `go-ahead` is not done from a message."""
    if op not in DECIDED:
        if op == "answer":
            return _said(phrases.text("IX_ANSWER_ON_QUESTION", ctx["cfg"]), extras)
        return _said(ops_natural.phone_sentence(ctx, op), extras)
    numbers = natural.decision_numbers(said)
    if len(numbers) != 1:
        return _said(phrases.text("NAT_WHICH_DECISION", ctx["cfg"]), extras)
    return _said(ops_natural.run(project, ctx, op, {"pending_id": numbers[0]}, said, CHANNEL, sender, extras, routed=True), extras)


def _unchanged(decision: dict, state: dict, said: str) -> bool:
    """Whether the corrected call (`decision["corrects"]`) is the live plan's own call, so that the "no" changed nothing. A list is compared as the dispatcher would ask it (its arguments read
    from the line with the old plan's), every other call by its arguments."""
    if decision["op"] == "items":
        return importlib.import_module("ops_items").items_args(said, ops_natural._clock(), state["args"]) == dict(state["args"])
    return dict(decision.get("args") or {}) == dict(state["args"])


def turn(project: str, ctx: dict, said: str, sender, extras: dict):
    """The reply tuple of a plain line read by the interpreter, or None when the line goes to the planning agent as today. `extras["interpreted"]` says what the
    conversation stores for the line: True (the default from here on) a neutral word, False the line itself (it was sent to the agent). With `extras["frame_age"]` (the sender
    has a bound router question) a None can also mean, by `extras["frame"]`, that the line answers it ("answer") or is a new request ("new"); with no `frame` the model said nothing."""
    extras["interpreted"] = True
    age_s = extras.get("frame_age")
    cfg = ctx["cfg"]
    entry = interpreter_enable.active(_tag(cfg))
    decision = interpreter.precheck(said)
    if decision is None:
        decision = importlib.import_module("ops_card_revise").decided(project, CHANNEL, sender, said)      # S13: the decision made while the line was checked as a change of a waiting card, once
    plan = extras.get("plan_frame")      # D5: the sender's live "Shall I go ahead?" (runtime/ops_say.py), a typed item of the frame beside the router's question
    frame = frame_for(age_s, plan)
    plan_id = next((item["id"] for item in (frame or {"items": []})["items"] if item["kind"] == "plan-confirm"), None)
    if decision is None:
        admission = turn_gate.admit(ctx, sender) if entry is not None else None
        decision = _ask_model(ctx, entry["entry"], said, sender, admission, frame) if admission is not None else None
    if decision is None:
        return _no_decision(ctx, said, extras)
    kind = decision.get("kind")
    if kind == "route":
        extras["interpreted"] = False
        extras["frame"] = "new"
        return None
    if kind == "answer" and plan_id is not None and decision.get("item") == plan_id:
        if decision.get("confirm") == "no":      # D5: a model's no drops the plan; a model's yes never runs it (only code's reading of the person's yes does: runtime/ops_say.py `_confirmed`)
            plan_confirm.drop(project, sender)
            return _said(phrases.text("PLAN_DROPPED", cfg), extras)
        extras["plan_keep"] = True
        return _said(phrases.text("PLAN_NOT_LAST", cfg), extras)
    if kind == "answer":
        extras["interpreted"] = False      # the line is sent to the planning agent as the answer to its question: the conversation keeps it
        extras["frame"] = "answer"
        return None
    if kind == "op":
        state = (plan or {}).get("state") if plan_id is not None else None      # BL5B: the sender's own live plan, nobody else's
        if state is not None and state["op"] == decision["op"]:
            if decision.get("corrects") and _unchanged(decision, state, said):
                plan_confirm.drop(project, sender)      # a correction that changes nothing is a no
                return _said(phrases.text("PLAN_DROPPED", cfg), extras)
            if decision.get("corrects") or interpreter.starts_with_no(said):
                extras["plan_previous"] = dict(state["args"])      # a CORRECTION's inheritance (it opens with a no): the old plan's arguments, so that a corrected list keeps what the old line said and the new one does not; a new request inherits nothing (never logged, never sent anywhere)
        extras["plan_words"] = dict(decision.get("spans") or {})      # D5: the spans code checked in the line become the new plan's own words (a correction may inherit one)
        return _carry_out(project, ctx, decision, said, sender, extras)
    if kind == "none":
        return _said(phrases.text("IX_NONE", cfg), extras)
    if kind == "refuse" and decision.get("class") != "D":
        return _said(ops_natural.phone_sentence(ctx, decision["op"]), extras)
    if kind == "refuse":
        return _decided(project, ctx, decision["op"], said, sender, extras)
    if kind == "refuse_policy":
        return _said(_refusal(ctx, decision["op"], sender), extras)
    key = WHY_SENTENCE.get(decision.get("why")) if kind == "clarify" else None
    if key is None:
        _log_ask_again(decision)
    return _said(phrases.text(key or "IX_ASK_AGAIN", cfg), extras)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
