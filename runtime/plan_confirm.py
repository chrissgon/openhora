#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The "Shall I go ahead?" question of a plan code stated (package BL2a, D5, limit L65, "Posso?" in Portuguese): it is asked before a read or an act asked in words runs on a messaging app.

A line in the person's words that reaches a read or an act (a tier-1 form, the router's operation, the interpreter's decision) is not run at once. Code writes ONE sentence from the
typed call, in the project's language (`understood`: the phrase keys `UNDERSTOOD_*`, no word the model wrote but a span code checked in the line), and asks "Posso?". Only the
person's yes runs the call, and only code reads that yes (`natural.confirm_kind`, under L64's conditions, which the messaging bridge checks: the last message the platform sent to
the private chat is the question, or the line replies to it, and it is not forwarded) or the question's own Yes button. A model's "yes" never runs a plan.

  needed(ctx, name, channel, sender, confirmed)   whether this call asks first (never for a call already confirmed, a page, a terminal, a greeting or a help)
  incomplete(name, args)                          whether the call lacks what it needs (the number of an act, the question of a search): it asks for that, not "Posso?"
  ask(project, ctx, name, args, said, sender, extras, ...)   keeps the plan in memory and returns the sentence and the question; `extras["plan_confirm"]` carries {item, sha256, op}
  understood(ctx, name, args, said)               the sentence's `{what}` piece, by code
  live / take / drop (project, sender)            the sender's live plan; `take` pops it only for its id AND its sha256 (the bridge's `plan_ok`), within PLAN_TTL
  frame_parts(item)                               the typed frame's `plan-confirm` item and its `last` (the plan's own words, for a correction: "no, for tomorrow")
  stop_form(line), STOP_WORDS                     whether a whole line is a stop word of the closed lists (the research brake: ops_research.stop)

What is asked (the maintainer's decisions of 2026-10-24):
  ALWAYS   the reads that leave the host or spend, whatever the policy says: derived from the registry (cost `model` or privacy `off-host`; today research and `ask`);
  ACTS     the acts that run from words (cancel, stop-task, retry, routine-pause, attachment-add, attachment-discard, reject, release): whatever the policy says;
  reads    every other read of the table but the help (NOT_ASKED), unless the sender holds the group `confirm-reads-off` (a widening: `accept-config --widen`).
Never asked: a greeting or the help, the answer to the platform's own question (a draft, the router's question, a number after a list), a button, a slash command, a card (it is the OK of
an effect), a notice (a reminder keeps its own confirmation) and a routine or a fired reminder.

THE SWITCH. `ACTIVE` was False in the package that added this module (BL2a) because the messaging bridge could not yet take a "sim" to a question; the bridge's package (BL2b) sets it True with the
dispatcher that can (the kind `plan-confirm` of runtime/messaging_turn.py), and dropped the S20 verb lists of the vet of decision numbers (now `turn_gate.number_believed`) in the same change. With it False `needed` is False (nothing is asked), which a test may use.

Privacy: the plan lives in memory for at most PLAN_TTL seconds, in the store of runtime/pending_items.py; `said` and the person's spans are in it and nowhere else. Nothing here logs,
prints or writes them; `repr` of an item shows its kind and id only. Standard library only. Runs on Python 3.9: python3 runtime/plan_confirm.py --help
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import command_words  # noqa: E402
import interpreter  # noqa: E402
import natural  # noqa: E402
import operations  # noqa: E402
import pending_items  # noqa: E402
import phrases  # noqa: E402
import registry  # noqa: E402
import snapshot_text  # noqa: E402

ACTIVE = True       # the switch between BL2a and BL2b (see the module's text): on since BL2b; a test may set it False with monkeypatch
PLAN_TTL = 600      # seconds a plan waits for its OK: the lifetime of a write draft and of a card list (ops_natural.DRAFT_TTL, messaging_bridge.LIST_SECONDS)
VALUE_MAX = 80      # characters of one value of the person's words in the sentence
ALWAYS = registry.always()      # derived (CB-0): the served reads whose cost is a model call or whose privacy is off-host: `research` and `ask` while the catalog is at version 1
ACTS = ("cancel", "stop-task", "retry", "routine-pause", "attachment-add", "attachment-discard", "reject", "release")
NOT_ASKED = ("commands",)
NUMBER = {"cancel": "request_id", "stop-task": "task_id", "retry": "task_id", "routine-pause": "routine_id", "attachment-add": "attachment_id",
          "attachment-discard": "attachment_id", "reject": "pending_id", "release": "pending_id"}      # the parameter that names the act's object
SENTENCES = {      # the phrase key of each operation's sentence; the ones that take a number or a value are handled in `understood`
    "status": "UNDERSTOOD_STATUS", "progress": "UNDERSTOOD_PROGRESS", "pending": "UNDERSTOOD_PENDING", "task": "UNDERSTOOD_TASK", "agents": "UNDERSTOOD_AGENTS",
    "skills": "UNDERSTOOD_SKILLS", "costs": "UNDERSTOOD_COSTS", "artifacts": "UNDERSTOOD_ARTIFACTS", "artifact": "UNDERSTOOD_ARTIFACT", "instructions": "UNDERSTOOD_INSTRUCTIONS",
    "routines": "UNDERSTOOD_ROUTINES", "sources": "UNDERSTOOD_SOURCES", "attachments": "UNDERSTOOD_ATTACHMENTS", "reminders": "UNDERSTOOD_REMINDERS", "flows": "UNDERSTOOD_FLOWS",
    "flow-check": "UNDERSTOOD_FLOW_CHECK", "connections": "UNDERSTOOD_CONNECTIONS", "items": "UNDERSTOOD_ITEMS", "file-read": "UNDERSTOOD_FILE_READ", "file-ask": "UNDERSTOOD_FILE_ASK", "research": "UNDERSTOOD_RESEARCH",
    "mail-read": "UNDERSTOOD_MAIL_READ_N", "todo-list": "UNDERSTOOD_TODO_LIST", "ask": "UNDERSTOOD_ASK", "cancel": "UNDERSTOOD_CANCEL", "stop-task": "UNDERSTOOD_STOP_TASK", "retry": "UNDERSTOOD_RETRY", "routine-pause": "UNDERSTOOD_ROUTINE_PAUSE",
    "attachment-add": "UNDERSTOOD_ATTACHMENT_ADD", "attachment-discard": "UNDERSTOOD_ATTACHMENT_DISCARD", "reject": "UNDERSTOOD_REJECT", "release": "UNDERSTOOD_RELEASE"}
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")      # the English abbreviation the operations layer writes (phrases.localize_dates turns it into the language's)

# The stop words of a research that is running: the closed lists, and `stop_form`, live in runtime/command_words.py (a pure reading of one line, which the messaging bridge may import: the layer map
# allows it that module and not this one) and are named here, where BL2a's interface has them. The research acknowledgement tells the person to send 'Pare' (pt-BR) or 'Stop' (the other languages): a
# test of the package that owns that text holds its word to be in the list of its language, so a word of the lists is struck only with that text.
STOP_WORDS = command_words.STOP_WORDS
stop_form = command_words.stop_form


def _ops_natural():
    return importlib.import_module("ops_natural")


def needed(ctx: dict, name: str, channel, sender, confirmed: bool) -> bool:
    """Whether the call `name` asks "Posso?" first (see the module's text). False while ACTIVE is False, off a messaging app, for a call already confirmed and for an operation with no
    sentence; True for ALWAYS and ACTS; for a read of the table (class R, not NOT_ASKED) unless the sender holds `confirm-reads-off`."""
    if not ACTIVE or channel != "messaging" or confirmed or name not in SENTENCES:
        return False
    if name in ALWAYS + ACTS:
        return True
    if natural.class_of(name) != "R" or name in NOT_ASKED:
        return False
    return not operations.holds("confirm-reads-off", "messaging", ctx["cfg"]["channels"], sender)


def incomplete(name: str, args: dict) -> bool:
    """Whether the call lacks what its sentence is about: the number of an act or of a task (the line's own answer is the sentence that asks for it), or the question of a search."""
    if name in NUMBER or name == "task":
        return args.get(NUMBER.get(name, "task_id")) is None
    if name == "mail-read":      # CB-3: no number, no words and no day: the reply asks which message (a sentence of its own), not "Shall I go ahead?"
        return not (args.get("number") is not None or any(isinstance(args.get(key), str) and args[key].strip() for key in ("match", "day")))
    if name == "file-ask":      # FA-1: no name of a file: the line is asked again, not "Shall I go ahead?" about nothing
        return not (isinstance(args.get("file"), str) and args["file"].strip())
    return name == "research" and not (isinstance(args.get("question"), str) and args["question"].strip())


def _key(project: str, sender) -> tuple:
    return (_ops_natural().project_key(project), "messaging", sender or "")


def plan_sha256(project_key: str, sender, name: str, args: dict, when, routed, said: str) -> str:
    """The hash a plan is bound to: the operation, its arguments, the sender, the project and the line (hashed, so the line is never in the document)."""
    return hashlib.sha256(interpreter.canonical({"v": 1, "project": project_key, "sender": sender or "", "op": name, "args": args, "when": when, "routed": bool(routed),
                                                 "said": hashlib.sha256(said.encode("utf-8")).hexdigest()})).hexdigest()


def _clip(value) -> str:
    """One value of the person's own words for the sentence: on one line, at most VALUE_MAX characters. A value is never a model's text: it is a span `natural` checked in the line."""
    return snapshot_text.one_line(value if isinstance(value, str) else str(value), VALUE_MAX)


def _number(value) -> str:
    return str(int(value)) if isinstance(value, int) and not isinstance(value, bool) else "?"


def _day(ctx: dict, said: str, args=None) -> str:
    """The day (or week) a list of items is asked for, written as the operations layer writes a date (`Wed 28/10/2026`), or "" for no range. The range is the call's own (`args`, BL5B:
    a corrected list may keep the range of the plan it corrects) when it has one, else the line's."""
    ops_items = importlib.import_module("ops_items")
    found = args if isinstance(args, dict) and args.get("first") and args.get("last") else ops_items._line_args(said, _ops_natural()._clock())
    if "first" not in found:
        return ""
    days = [datetime.date.fromisoformat(found[key]) for key in ("first", "last")]
    written = [f"{WEEKDAYS[d.weekday()]} {d.strftime('%d/%m/%Y')}" for d in days]
    return written[0] if written[0] == written[1] else f"{written[0]}–{written[1]}"


def understood(ctx: dict, name: str, args: dict, said: str) -> str:
    """The `{what}` piece of the sentence for the typed call, rendered by code in the project's language (limit L65). Values are the person's own words or numbers: a span is cut to one
    line of at most VALUE_MAX characters; a number is `#<n>` by the phrase. A project in es, fr, de or it gets the English sentence with the values quoted (the phrase table's fallback)."""
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    key = SENTENCES[name]
    if name in NUMBER_OF and args.get(NUMBER_OF[name][0]) is not None:
        return t(NUMBER_OF[name][1], id=_number(args[NUMBER_OF[name][0]]))
    if name == "task":
        return t(key, id=_number(args.get("task_id")))
    if name in NUMBER:
        return t(key, id=_number(args.get(NUMBER[name])))
    if name in ("progress", "costs"):
        return t(key) + (t("UNDERSTOOD_SINCE", since=_clip(args["since"])) if args.get("since") else "")
    if name == "artifact":
        return t(key, path=_clip(args.get("path") or "")) if args.get("path") else t("UNDERSTOOD_ARTIFACTS")
    if name == "flow-check":
        return t(key, flow=_clip(args.get("flow") or "")) if args.get("flow") else t("UNDERSTOOD_FLOWS")
    if name == "file-read":
        return t(key, file=_clip(args.get("file") or ""))
    if name == "file-ask":      # FA-1: the name of the file (a span of the person's line) and the cap of the run, as for a research
        cap = ((ctx.get("cfg") or {}).get("file_ask") or {}).get("max_cost_usd")
        return t(key, file=_clip(args.get("file") or ""), cap=phrases.decimal(f"{float(cap):.2f}", cfg) if isinstance(cap, (int, float)) else "?")
    if name == "mail-read":      # CB-3: the number, or the words and the day of the person's own line (a span `natural` checked), never a word of the message
        words, day = _clip(args.get("match") or ""), _clip(args.get("day") or "")
        if args.get("number") is not None:
            return t("UNDERSTOOD_MAIL_READ_N", n=_number(args["number"]))
        return t("UNDERSTOOD_MAIL_READ_WORDS_DAY", words=words, day=day) if words and day else t("UNDERSTOOD_MAIL_READ_WORDS", words=words) if words else t("UNDERSTOOD_MAIL_READ_DAY", day=day)
    if name == "research":
        cap = ((ctx.get("cfg") or {}).get("research") or {}).get("max_cost_usd")
        return t(key, question=_clip(args.get("question") or ""), cap=phrases.decimal(f"{float(cap):.2f}", cfg) if isinstance(cap, (int, float)) else "?")
    if name == "items":
        kind = args.get("kind") or importlib.import_module("natural_writes").items_kind(said)      # BL5B: the call's own kind (a corrected list keeps the old plan's), else the line's
        words = " ".join(w for w in (args.get("match") or []) if isinstance(w, str))      # CB-1: the words code read from the person's target (a list of none says nothing: the reply says so)
        key = {"mail": "UNDERSTOOD_ITEMS_MAIL_MATCH" if words else "UNDERSTOOD_ITEMS_MAIL", "calendar": "UNDERSTOOD_ITEMS_CALENDAR_MATCH" if words else "UNDERSTOOD_ITEMS_CALENDAR"}.get(kind, "UNDERSTOOD_ITEMS")
        sentence = t(key, words=_clip(words))
        day = _day(ctx, said, args)
        return sentence + (" " + t("UNDERSTOOD_ITEMS_UNREAD") if args.get("unread") is True and kind == "mail" else "") + (phrases.localize_dates(t("UNDERSTOOD_ON_DAY", day=day), cfg) if day else "")
    return t(key)


NUMBER_OF = {"pending": ("pending_id", "UNDERSTOOD_PENDING_ONE"), "routines": ("routine_id", "UNDERSTOOD_ROUTINE_ONE")}      # the reads that take an optional number


def ask(project: str, ctx: dict, name: str, args: dict, said: str, sender, extras: dict, *, when=None, routed: bool = False, words=None, state_question: bool = False) -> str:
    """Keep the plan of this call for this sender (replacing their live plan) and return the question: "I understood: <what>. Shall I go ahead?". `extras["plan_confirm"]` is
    {item, sha256, op} for the bridge's question; `extras["stored"]` is what the conversation keeps instead of the question (a neutral word)."""
    cfg = ctx["cfg"]
    key = _key(project, sender)
    kept = dict(args)
    spans = {slot: value for slot, value in (words or {}).items() if isinstance(slot, str) and isinstance(value, str)}
    # A correction may inherit a span of the person's earlier words ("no, for tomorrow" keeps the question of the search): the call checks its span against the line it runs with, so
    # the plan's line is the person's line followed by those earlier words of theirs that the line does not hold. Nothing else is added to it, and the hash binds it.
    carried = [value for value in spans.values() if natural.normal(value) not in natural.normal(said)]
    bound = said + "".join(" " + value for value in carried)
    state = {"op": name, "args": kept, "when": when, "routed": bool(routed), "said": bound, "words": spans, "state_question": bool(state_question), "sha256": None}
    state["sha256"] = plan_sha256(key[0], sender, name, kept, when, routed, bound)
    item = pending_items.new_item("plan-confirm", *key, state=state)
    pending_items.put(item)
    extras["plan_confirm"] = {"item": item["id"], "sha256": state["sha256"], "op": name}
    extras["stored"] = phrases.text("PLAN_STORED", cfg)
    return phrases.text("PLAN_HEAD", cfg, what=understood(ctx, name, args, said)) + " " + phrases.text("PLAN_ASK", cfg)


def _age(item: dict) -> float:
    return pending_items.clock() - item["asked_at"]


def live(project: str, sender):
    """The sender's live plan (an item of kind `plan-confirm` younger than PLAN_TTL), or None."""
    item = pending_items.find(_key(project, sender), "plan-confirm")
    return item if item is not None and _age(item) < PLAN_TTL else None


def take(project: str, sender, plan_ok):
    """Pop the sender's live plan when `plan_ok` ({"item", "sha256"}) names its id AND the hash the plan's own state gives now; else None and nothing is popped. A plan whose state
    changed since the question was drawn no longer has the hash the question carries."""
    item = live(project, sender)
    if item is None or not isinstance(plan_ok, dict) or plan_ok.get("item") != item["id"]:
        return None
    s = item["state"]
    want = plan_sha256(_key(project, sender)[0], sender, s["op"], s["args"], s["when"], s["routed"], s["said"])
    given = plan_ok.get("sha256")
    if not isinstance(given, str) or not hmac.compare_digest(given, want) or not hmac.compare_digest(s["sha256"], want):
        return None
    return pending_items.pop(item["id"])


def drop(project: str, sender) -> bool:
    """Forget the sender's plan (a no, or any other line); True when one was there."""
    return bool(pending_items.drop_key(_key(project, sender), "plan-confirm"))


def frame_parts(item: dict) -> tuple:
    """(the typed frame's item without its id, `last`) for a live plan: the operation and the age, and, for `last`, the person's own words of the plan (runtime/interpreter.py
    `typed_frame` reads `own_words`)."""
    age = int(max(0, _age(item)))
    return ({"kind": "plan-confirm", "need": "confirm", "op": item["state"]["op"], "age_s": age},
            {"op": item["state"]["op"], "own_words": item["state"]["words"], "age_s": age})


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
