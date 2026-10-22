#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The natural-language interpreter on a messaging line (slice S1): what the conversation does with a plain line that no list of code took.

A sibling of runtime/ops_say.py, which calls `enabled` and `turn` at its one seam (`_turn`, after `ops_natural.take` returned None and the sender may talk) and
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
the sentence is IX_ASK_AGAIN with the question still open. Without a bound question the frame is none, as in S1.

The steps of `turn`: `interpreter.precheck`; the limits below; `interpreter.build_messages` (the user turn is five lines made
of the date, the time, the zone, the frame and the person's own collapsed line: nothing of any third party); one call to the daily route; `parse`; `check` against the line;
then the decision is carried out by the call that already exists for it (`ops_natural.run`, `ops_natural_writes.open_line`) or answered by a fixed sentence. Nothing
the model wrote in this call is ever shown, and nothing here approves, sends or writes: a card is opened by `open_line` and approved on its button by its hash. One exception,
by the maintainer's decision of 2026-10-20 (slice S7): a new e-mail (`mail-send`, `mail-draft` with no message) opens its card through the seed of `mail_compose.seed`, and the
text on that card may be worded by a second call (runtime/mail_compose.py), validated by code, with the person's own words as the fallback.

The call. The route is taken from `interpreter_route.daily_routes()` (kind http only) and its kind is checked again in `_daily_call`, so a route of any other kind
cannot be called from here; the entry that enables the interpreter names the route and the hashes it was decided on (runtime/interpreter_enable.py).

The limits (counts in memory, this slice's choice, not measured): RATE_MAX calls per sender in RATE_WINDOW seconds, DAY_MAX per project per local day, and an open
breaker for BREAKER_OPEN seconds after BREAKER_FAILS failed calls in a row. When there is no call (entry off, a limit reached, a failed call, a zone that cannot be
named) a line that is not private and a project in pt-BR or en go to the planning agent as before; any other gets the sentence IX_OUTAGE.

Privacy (limit L63): no line, span, model text or exception message is logged, printed or kept here. The conversation stores the person's line only after the decision,
and as a neutral word unless the line was sent to the planning agent (`extras["interpreted"]`, read by ops_say.say); this file stores nothing.

Standard library only. Runs on Python 3.9: python3 runtime/ops_interpret.py --help
"""
from __future__ import annotations

import collections
import importlib
import os
import re
import sys
import threading
import time
from zoneinfo import ZoneInfo

import event_lookup
import interpreter
import interpreter_enable
import interpreter_route
import language as language_rules
import mail_compose
import natural
import operations
import ops_natural
import phone_refusal
import phrases

CHANNEL = "messaging"
RATE_MAX = 10          # calls per sender in RATE_WINDOW seconds
RATE_WINDOW = 60.0
DAY_MAX = 300          # calls per project per local day
BREAKER_FAILS = 3        # failed calls in a row that open the breaker
BREAKER_OPEN = 300.0     # seconds it stays open
ROUTE_LANGUAGES = ("pt-BR", "en")      # the project languages whose tables detect a private line: only there a model failure may route a line to the agent
ZONE_NAME = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*")
WHY_SENTENCE = {"time-ask": "IX_ASK_TIME", "time-gap": "IX_ASK_TIME", "time-fold": "IX_ASK_TIME", "weekday": "IX_ASK_TIME", "time-past": "IX_ASK_PAST",
                "time-far": "IX_ASK_FAR", "long-line": "IX_LONG_LINE"}      # every other why (model, invalid, private-route) is IX_ASK_AGAIN
clock = time.monotonic   # the clock of the rate window and of the breaker (a test replaces it)

_lock = threading.Lock()
_calls = {}              # sender -> times of its calls inside the window
_days = {}               # (project key, local day) -> calls
_breaker = {"fails": 0, "until": 0.0}


def forget_all() -> None:
    """Drop the counts and close the breaker (a test, and a process that stops)."""
    with _lock:
        _calls.clear()
        _days.clear()
        _breaker.update(fails=0, until=0.0)


def _tag(cfg: dict) -> str:
    return language_rules.effective(None, cfg.get("language"))[0]


def enabled(ctx: dict, channel, sender) -> bool:
    """Whether a plain line of this sender is read by the interpreter: messaging, the group `interpret`, and the enabling entry in force for the project's language."""
    if channel != CHANNEL:
        return False
    cfg = ctx["cfg"]
    return operations.holds("interpret", CHANNEL, cfg["channels"], sender) and interpreter_enable.active(_tag(cfg)) is not None


# --- the limits ------------------------------------------------------------------------------------------------------------------------------------


def _admit(ctx: dict, sender) -> bool:
    """Whether one more call may be made now (the breaker is closed and neither limit is reached); the call is counted when it may."""
    now = clock()
    day = (ops_natural.project_key(ctx["cfg"]["project"]), ops_natural._clock().date().isoformat())
    with _lock:
        if now < _breaker["until"]:
            return False
        window = _calls.setdefault(sender or "", collections.deque())
        while window and now - window[0] >= RATE_WINDOW:
            window.popleft()
        if len(window) >= RATE_MAX or _days.get(day, 0) >= DAY_MAX:
            return False
        window.append(now)
        for old in [k for k in _days if k[1] != day[1]]:
            del _days[old]
        _days[day] = _days.get(day, 0) + 1
    return True


def _record(ok: bool) -> None:
    with _lock:
        if ok:
            _breaker["fails"] = 0
        else:
            _breaker["fails"] += 1
            if _breaker["fails"] >= BREAKER_FAILS:
                _breaker["until"] = clock() + BREAKER_OPEN


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


def _daily_call(entry: dict, system: str, user: str) -> dict:
    """The one model call: the entry's route, taken from the daily routes (kind http) and checked again here, with the hash the entry was decided on as the only
    one accepted and the protocol's own settings. Any other route is E_ROUTE and no request is made."""
    rows = [r for r in interpreter_route.daily_routes() if r["id"] == entry["route"]]
    if len(rows) != 1 or rows[0].get("kind") != "http" or interpreter_route.route_sha256(rows[0]) != entry["route_sha256"]:
        return {"ok": False, "code": "E_ROUTE"}
    protocol = interpreter.PROTOCOL
    return interpreter_route.complete(rows[0]["id"], system, user, accepted=[entry["route_sha256"]], deadline_ms=protocol["deadline_ms"], **protocol["params"])


def decide(line: str, text, now, zone: str, allowed, frame=None) -> dict:
    """The decision for a model's text about a line: the measured pipeline's own two calls, `parse` and `check` (with the typed frame of the bound router question, or none)."""
    obj, _, error = interpreter.parse(text)
    if obj is None:
        return {"kind": "clarify", "error": error, "why": "invalid", "slot": None, "ops": None}
    return interpreter.check(obj, line, frame, interpreter.SERVED, now, zone, allowed)


def router_frame(age_s):
    """The typed frame for a router question bound to the sender: one item, the question's id (`i1`), kind, need and age, and none of its words (None: no question is bound)."""
    if age_s is None:
        return None
    return interpreter.typed_frame([{"id": "i1", "kind": "router-question", "need": "text", "age_s": age_s}], None, {})


def _allowed(ctx: dict, sender) -> set:
    """The operations of the served catalog this sender may ask from a phone under the project's policy (the check also re-runs when the operation is carried out)."""
    policy = ctx["cfg"]["channels"]
    return {row["op"] for row in interpreter.SERVED["ops"] if operations.permitted(row["op"], CHANNEL, policy, None, sender)}


def _ask_model(ctx: dict, entry: dict, said: str, sender, frame=None):
    """The decision for the line, or None when no call could be made or it failed."""
    try:
        now = ops_natural._clock()
        zone = _zone(now)
        system, user = interpreter.build_messages(interpreter.SERVED, now, zone, frame, said)
        got = _daily_call(entry, system, user)
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the line
        got = {"ok": False}
    _record(bool(got.get("ok")))
    if not got.get("ok"):
        return None
    try:
        return decide(said, got.get("text"), now, zone, _allowed(ctx, sender), frame)
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
    return phone_refusal.said(refused, CHANNEL, ctx["cfg"]) if refused else phrases.text("IX_ASK_AGAIN", ctx["cfg"])      # S10: a phone is told in one plain sentence, never "error:" or a command


CANNOT = {"event-create": "IX_CANNOT_EVENT_CREATE"}      # every other write: IX_CANNOT_WRITE (an event to change or cancel is answered by runtime/event_lookup.py)


def _cannot(ctx: dict, op: str) -> str:
    """The sentence for a write that could not be prepared. IX_WRITE_LANGUAGE is true only for a project language with no write forms (the tables detect them in pt-BR and en
    alone); in those two the sentence says what was understood and what is missing, never a language."""
    if _tag(ctx["cfg"]) not in ROUTE_LANGUAGES:
        return phrases.text("IX_WRITE_LANGUAGE", ctx["cfg"])
    return phrases.text(CANNOT.get(op, "IX_CANNOT_WRITE"), ctx["cfg"])


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
        else:
            opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, hint=op)
        return _said(opened if opened is not None else _cannot(ctx, op), extras)
    when = time_["local"].replace("T", " ") if time_ else None
    reply = ops_natural.run(project, ctx, op, decision["args"], said, CHANNEL, sender, extras, when=when, routed=True)
    return _said(reply, extras)


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
        decision = _ask_model(ctx, entry["entry"], said, sender, router_frame(age_s)) if entry is not None and _admit(ctx, sender) else None
    if decision is None:
        return _no_decision(ctx, said, extras)
    kind = decision.get("kind")
    if kind == "route":
        extras["interpreted"] = False
        extras["frame"] = "new"
        return None
    if kind == "answer":
        extras["interpreted"] = False      # the line is sent to the planning agent as the answer to its question: the conversation keeps it
        extras["frame"] = "answer"
        return None
    if kind == "op":
        return _carry_out(project, ctx, decision, said, sender, extras)
    if kind == "none":
        return _said(phrases.text("IX_NONE", cfg), extras)
    if kind == "refuse" and decision.get("class") != "D":
        return _said(ops_natural.phone_sentence(ctx, decision["op"]), extras)
    if kind == "refuse":
        return _said(phrases.text("IX_USE_CARD", cfg), extras)
    if kind == "refuse_policy":
        return _said(_refusal(ctx, decision["op"], sender), extras)
    key = WHY_SENTENCE.get(decision.get("why")) if kind == "clarify" else None
    return _said(phrases.text(key or "IX_ASK_AGAIN", cfg), extras)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
