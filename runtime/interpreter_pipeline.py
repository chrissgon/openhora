#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The B-prime arm of the interpreter experiment for ONE corpus item (package IX-2c, plan `PLAN-NL-INTERPRETER-FINAL.md`): what the platform would do with a line, from the
forward check to the word `observed` the scorer reads. Measurement only: nothing here executes, stores, sends or writes; no model is called here either (the caller passes a
`call`, so that a recorded answer, a stand-in or the real route are the same code).

The stages, in order; the first that decides ends the item (`run_item`):
  1. forward      a messaging item that is a forward (`forwarded` anything but absent or false: the fail-closed reading of runtime/messaging_inbound.py)  -> forwarded
  0. precheck     a line over `max_line_chars` is never sent (`interpreter.precheck`)                                                                -> route / clarify
  2. closed       with a frame, the newest open item and a line that code reads as the same yes or no (`natural.confirm_kind`), or one digit      -> answer
  3. tier 1       with no open item: a line that starts with `/` is a typed command (the same in both arms) -> none; else `natural.match`          -> the operation
  4. model        `interpreter.build_messages`, `call(system, user)`, `interpreter.parse`, `interpreter.check` (the sender holds every group: `ALLOWED`)
  5. mapping      the decision to `observed` (`observe`, `OBSERVED_OF`): a measurement-only table. It never gives `executed`: nothing is executed
The forward is first because a forward is never a request, whatever its length.

Resolution always succeeds here (an account, a calendar, a folder, a source, a file, a mail number, an attachment, a task, a routine or a request that a decision names
is taken to exist): the stubs of both arms. The mapping cannot measure the families' seed builders, resolution failures, the card's rendering, the per-sender policy, the
rate limit or the circuit breaker, nor approval by word: `confirm` and `card` mean "code would show this exact operation with these spans", not "this card was sent".

  run_item(item, run, call)    the Outcome: {"observed", "detail", "stage", "parse", "error", "time_source", "call": {latency_ms, usage, upstream} | None, "notes", "why",
                               "time_disagree"}; `call(system, user)` returns what `interpreter_route.complete` returns, or a stand-in's
  pre_model(item)              the Outcome of stages 1 to 3, or None when the item reaches the model (pure code; no call)
  item_problems(item)          the names of the fields of a corpus item that are not in the form of the corpus (never a value), [] when it is valid
  observe(decision)            (observed, detail) of a decision of `interpreter.check`

Python 3.9, standard library only. `python3 runtime/interpreter_pipeline.py --help` prints this text.
"""
from __future__ import annotations

import datetime
import os
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import interpreter  # noqa: E402  (the same folder: the protocol, the validator and the served catalog)
import natural  # noqa: E402  (the same folder: tier 1, the classes, the confirm reading)

SERVED = interpreter.SERVED
# The sender holds every group (the labelling guide's L1: gold is what the platform should do for the owner): every operation of the served catalog is allowed.
ALLOWED = frozenset(row["op"] for row in SERVED["ops"])
STAGES = ("forwarded", "precheck", "closed", "tier1", "typed", "model")
# Measurement only: the observed word of an operation by its class (`ask` is class "work"). Class G is `confirm` when the catalog serves it (the operational ones) and
# `refuse_g` otherwise; `remind` is the one N operation that shows its reading (`remind_confirm`). `executed` is not in the image.
OBSERVED_OF = {"R": "read", "work": "read", "N": "confirm", "W": "confirm", "E": "card", "D": "refuse_d"}
CALL_ERRORS = ("E_USAGE", "E_KEY", "E_ROUTE", "E_TIMEOUT", "E_NETWORK", "E_RATE", "E_UPSTREAM", "E_HTTP", "E_PIN", "E_RESPONSE", "E_INTERNAL", "E_UNKNOWN")
OUTCOMES = ("op", "answer", "clarify", "route", "none", "refuse", "forwarded")
CHANNELS = ("messaging", "page", "terminal", "chat")
ITEM_WORD = "item"
LANG_CODES = {"pt-BR": "pt-br", "en": "en", "es": "es", "fr": "fr", "de": "de", "it": "it", "ja": "ja", "mixed": "mx"}          # a language and the code its ids carry (evals/evidence_lines.py IX_LANG_CODES)
ITEM_KEYS = ("id", "split", "lang", "hard", "clock", "zone", "channel", "forwarded", "frame", "line", "gold", "also")


def _is_forward(item: dict) -> bool:
    """Whether the item is a forward: on the messaging channel (the only one whose providers set the mark, as the current arm reads it) anything but absent or false, the fail-closed
    reading of messaging_provider.forwarded_of."""
    return item.get("channel") == "messaging" and "forwarded" in item and item["forwarded"] is not False


def now_of(item: dict) -> datetime.datetime:
    return datetime.datetime.fromisoformat(item["clock"])          # naive: the wall clock of the item's zone (interpreter._local_now)


def item_problems(item) -> list:
    """The names of the fields that are not in the form of a corpus item (SPEC-IX-PHASE1 1.7), never a value: [] for a valid item."""
    if not isinstance(item, dict):
        return [ITEM_WORD]
    out = [key for key in ITEM_KEYS if key not in item]
    if out:
        return out
    if not isinstance(item["id"], str) or not isinstance(item["hard"], bool):
        out.append("id/hard")
    elif item["lang"] not in LANG_CODES:
        out.append("lang")
    elif not item["id"].startswith("local-") and item["id"].split("-", 1)[-1].rsplit("-", 1)[0] != LANG_CODES[item["lang"]]:
        out.append("id/lang")          # the id carries the language's code (the validator refuses a line where they differ)
    if not isinstance(item["line"], str) or not item["line"].strip():
        out.append("line")
    if item["channel"] not in CHANNELS:
        out.append("channel")
    try:
        ZoneInfo(item["zone"])
        now_of(item)
    except Exception:          # noqa: BLE001 - the field is named, never the value
        out.append("clock/zone")
    gold = item["gold"]
    if not isinstance(gold, dict) or gold.get("outcome") not in OUTCOMES:
        out.append("gold")
    elif gold.get("scope", "full") not in ("full", "op", "time"):
        out.append("gold.scope")
    if not isinstance(item["also"], list) or not all(isinstance(g, dict) for g in item["also"]):
        out.append("also")
    try:
        if interpreter.frame_problems(item["frame"], SERVED):
            out.append("frame")
    except Exception:          # noqa: BLE001
        out.append("frame")
    return out


# --- the mapping ------------------------------------------------------------------------------------------------------------------------------------------

def observed_of_op(op: str) -> str:
    """The observed word of an operation a decision names (module docstring, stage 5)."""
    cls = natural.class_of(op)
    if op == "remind":
        return "remind_confirm"
    if cls == "G":
        return "confirm" if op in ALLOWED else "refuse_g"
    return OBSERVED_OF[cls]


def observe(decision: dict) -> tuple:
    """(observed, detail) of a decision of `interpreter.check` (or of the synthetic ones of stages 1 to 3). The detail is the scorer's input."""
    kind = decision["kind"]
    if kind == "op":
        op, spans = decision["op"], {slot: str(value) for slot, value in (decision.get("spans") or {}).items()}
        observed = observed_of_op(op)
        if observed in ("refuse_d", "refuse_g"):
            return observed, {"class": "D" if observed == "refuse_d" else "G"}
        time = decision["time"]["local"] if decision.get("time") else None
        detail = {"op": op, "slots": spans}
        if observed in ("card", "remind_confirm"):
            detail["time"] = time
        return observed, detail
    if kind == "answer":
        detail = {"item": decision["item"]}
        for key in ("option", "confirm", "slot", "span"):
            if decision.get(key) is not None:
                detail[key] = decision[key]
        if decision.get("time"):
            detail["time"] = decision["time"]["local"]
        return "answer", detail
    if kind == "clarify":
        if decision.get("slot") is not None:
            return "clarify", {"slot": decision["slot"]}
        if decision.get("ops") is not None:
            return "clarify", {"ops": list(decision["ops"])}
        return "clarify", {}
    if kind in ("route", "none", "forwarded"):
        return kind, {}
    if kind == "refuse":
        return ("refuse_d" if decision["class"] == "D" else "refuse_g"), {"class": decision["class"]}
    if kind == "refuse_policy":
        return "refuse_policy", {"op": decision["op"]}
    raise ValueError("a decision of an unknown kind")


def _outcome(decision: dict, stage: str, parse: str = "none", error=None, call=None, notes=()) -> dict:
    observed, detail = observe(decision)
    time = decision.get("time") if decision["kind"] in ("op", "answer") else None
    why = decision.get("why") if decision["kind"] == "clarify" else None
    disagree = bool(decision.get("time_disagree"))
    marks = list(notes) + ([why] if why else []) + (["time-disagree"] if disagree else [])
    return {"observed": observed, "detail": detail, "stage": stage, "parse": parse, "error": error,
            "time_source": time["source"] if time else None, "call": call, "notes": marks, "why": why, "time_disagree": disagree}


def _outage(code, call) -> dict:
    return {"observed": "outage", "detail": {}, "stage": "model", "parse": "none", "error": code if code in CALL_ERRORS else "E_UNKNOWN",
            "time_source": None, "call": call, "notes": [], "why": None, "time_disagree": False}


# --- the stages ---------------------------------------------------------------------------------------------------------------------------------------------

def _closed_answer(frame, line: str):
    """The decision for a line that answers the newest open item in a closed way, else None (stage 2)."""
    items = (frame or {}).get("items") or []
    if not items:
        return None
    _, newest = min(enumerate(items), key=lambda pair: (pair[1]["age_s"], -pair[0]))          # the smallest age; a tie goes to the later item
    if newest["need"] == "confirm":
        said = natural.confirm_kind(line)
        if said in ("yes", "no"):
            return {"kind": "answer", "error": None, "item": newest["id"], "need": "confirm", "confirm": said}
    elif newest["need"] == "option":
        word = line.strip()
        if len(word) == 1 and word in "123456789" and int(word) <= (newest.get("options") or 0):
            return {"kind": "answer", "error": None, "item": newest["id"], "need": "option", "option": int(word)}
    return None


def _tier1(line: str):
    """The decision for a line that is one closed form of exactly one operation (`natural.match`), spans rebuilt from its slots; else None."""
    found = natural.match(line)
    if found is None:
        return None
    op, args = found["op"], found["args"]
    spans = {slot: str(args[spec[1]]) for slot, spec in natural.NATURAL[op]["slots"].items() if spec[1] in args}
    return {"kind": "op", "error": None, "op": op, "args": args, "spans": spans, "time": None, "inherited": [], "time_disagree": False}


def pre_model(item: dict):
    """The Outcome of stages 1 to 3 when one of them decides, else None (the item reaches the model). Pure code: no call, the same for every run."""
    line, frame = item["line"], item["frame"]
    if _is_forward(item):
        return _outcome({"kind": "forwarded"}, "forwarded")
    early = interpreter.precheck(line)
    if early is not None:
        return _outcome(early, "precheck")
    closed = _closed_answer(frame, line)
    if closed is not None:
        return _outcome(closed, "closed")
    if not (frame or {}).get("items"):
        if line.strip().startswith("/"):
            return _outcome({"kind": "none", "error": None}, "typed", notes=["typed"])
        found = _tier1(line)
        if found is not None:
            return _outcome(found, "tier1", notes=["tier1"])
    return None


def run_item(item: dict, run: int, call) -> dict:
    """The Outcome of one run of one item. `call(system, user)` makes the model call (stage 4) and returns {"ok": True, "text", "finish", "usage", "latency_ms",
    "upstream"} or {"ok": False, "code", ("latency_ms")}. `run` is for the caller's bookkeeping: the arm is deterministic given the model's answer."""
    early = pre_model(item)
    if early is not None:
        return early
    line, frame, zone, now = item["line"], item["frame"], item["zone"], now_of(item)
    system, user = interpreter.build_messages(SERVED, now, zone, frame, line)
    got = call(system, user)
    if not got.get("ok"):
        return _outage(got.get("code"), {"latency_ms": got.get("latency_ms"), "usage": None, "upstream": None})
    info = {"latency_ms": got.get("latency_ms"), "usage": got.get("usage"), "upstream": got.get("upstream")}
    obj, parse, error = interpreter.parse(got.get("text"))
    if obj is None:
        decision = {"kind": "clarify", "error": error, "why": "invalid", "slot": None, "ops": None}
    else:
        decision = interpreter.check(obj, line, frame, SERVED, now, zone, ALLOWED)
    return _outcome(decision, "model", parse=parse, call=info)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
