#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations layer's dispatcher: it walks the `ops` stage of the table of the order in which a line is claimed (package S41-3; runtime/turn_order.py) and runs the code of each row.

WHAT IT HOLDS. The order of who takes a plain line in the operations layer is data, the rows of the stage `ops` of `turn_order.ORDER`, on every shell: the messaging bridge, the page, the terminal, the
MCP mode, the conversation's own shell and the queue's drain all pass through `ops_say.say` (or the drain, `ops_say.route_queued`) and so through this module; there is no second path. This module holds
the code of every row, in `ROWS`, and `dispatch`, which runs the rows in the table's order, skips a row whose `channels` excludes the shell that carries the line, and stops at the first row that says it
took the line. A row is a function `row(project, ctx, said, channel, sender, extras, state) -> tuple | None`: the tuple is what `ops_say._turn` returned (`reply, request_id, pending_id, ran, run_id,
proposal`) and ends the dispatch; None goes on. The conditions and the calls are those of `_turn` and of `ops_natural.take` before the table existed, copied and not changed (the order of the reads
and the side effects in between included: the draft of the sender dropped by any other line, the plan dropped, the frame of the router's question); the claimers' own bodies (`ops_natural.run`,
`event_lookup.take`, `ops_file_read.take`, `ops_natural_writes.answer` and `open_line`, `ops_interpret.turn`, `ops_say._say_command`, `_say_route`, `state_reply`, ...) stay where they were, and a row only
calls them, at call time, through their module, so that a test that patches one patches what the row calls. Package S41-11 removes rows; this package changes no outcome (the entry replay,
runtime/tests/test_entry_replay.py, proves it on the corpus, page and terminal lines included).

THE ROWS THAT DO NOT TAKE A LINE WHERE THEY STAND. `confirmed-plan` runs first and out of `dispatch`, in `confirmed`: the OK of a plan is read before the line is stored or queued (`say`'s order of work is
the hooks, the confirmed plan, the queue decision, the deferred store, the turn, the plan drop, the stored reply). `router-question` takes no line: it binds the router's open question to the sender and sets
the frame in the state (a line that code recognises is a new request, never the answer: LIVE-2, S4); the line it binds is taken by `planning-agent` at the end of the order, which the trace names
`router-question` for that line, as the kit's trace does. `interpreter` is a row of the messaging shell only: it is the documentation of `ops_interpret.enabled`, which stays the home of L63(1) (the
interpreter reads a messaging line only); a page or a terminal line never reaches it, by the table and by `enabled`.

THE STATE is what the rows share, the locals of `_turn`: `talks` (whether the sender may talk, read once), `asked` (the router's open question this line may answer), `framed` (the line is the answer
of a question the interpreter tells from a new line), `took` (the name the trace gives the taking row when it is not the row's own) and the line's id. The flag of a dropped draft is
`extras["discarded"]`, as it was.

THE CYCLE. `ops_say.py` and `ops_natural.py` reach `ops.py` and each other at call time. This module imports at module level only `turn_order` (pure data), modules that `ops_say` or `ops_natural`
already import at module level (`natural`, `operations`, `ops_natural`, `phone_refusal`, `phrases`, `plan_confirm`) and three pure leaves of the standard library alone (`drafts`, `greeting`,
`phone_delete`); none of them imports `ops_say` or this module. It reaches `ops_say`, the interpreter, the lookups and the trash through `importlib` at call time, and `ops_say` reaches it at call time too.

`dispatch_rows(names, ...)` runs only the named rows, in the table's order, and answers None when none takes the line: a helper for tests (the five rows that were `ops_natural.take`), never called by
production. TRACE is None; a test may set it to a function that receives `(name, state)` for the row that took a line. Production never sets it.

Standard library only. Runs on Python 3.9: python3 runtime/ops_turn.py --help
"""
from __future__ import annotations

import importlib
import sys

import drafts
import greeting
import natural
import operations
import ops_natural
import phone_delete
import phone_refusal
import phrases
import plan_confirm
import turn_order

TRACE = None      # None, or a function that a test sets to receive `(name, state)` of the row that took a line
EARLY = "confirmed-plan"      # the row `confirmed` runs; `dispatch` does not
TAKE_ROWS = ("draft-answer", "event-list-number", "file-list-number", "write-form-ops", "tier-1-form")      # what `ops_natural.take` was: for `dispatch_rows`, in tests


def _say():
    """runtime/ops_say.py, found at call time (it imports this module at call time too)."""
    return importlib.import_module("ops_say")


class State:
    """What the rows of one dispatch share (see the module text). `can_send` and `plan_ok` are the messaging arguments of `say`, read by `confirmed-plan` only."""

    def __init__(self, project: str, ctx: dict, said: str, channel: str, line_id, sender, extras: dict, can_send=None, plan_ok=None):
        self.project, self.ctx, self.said, self.channel, self.line_id, self.sender, self.extras = project, ctx, said, channel, line_id, sender, extras
        self.natural_channel = _say()._natural_channel(channel)      # the channel a natural request is checked under: the queue's drain acts as the page
        self.can_send, self.plan_ok = can_send, plan_ok
        self.talks = None
        self.asked, self.framed, self.took = None, False, None


def _talks(state: State) -> bool:
    """Whether the sender may talk to the planning agent, read once, by the first row that needs it (`_turn` read it after the command row)."""
    if state.talks is None:
        state.talks = _say().may_talk(state.ctx, state.channel, state.sender)
    return state.talks


def _out(extras: dict, reply) -> tuple:
    """The turn's tuple for a reply that code wrote (the answer run an `ask` made, if any, is `extras["run_id"]`)."""
    return reply, None, None, False, extras.get("run_id"), None


def _plain(reply) -> tuple:
    return reply, None, None, False, None, None


# --- the rows -------------------------------------------------------------------------------------------------------------------------------------------


def confirmed_plan(project, ctx, said, channel, sender, extras, state):
    if state.plan_ok is None:
        return None
    return _say()._say_confirmed(project, ctx, said, sender, state.can_send, state.plan_ok)      # a dict, `say`'s own return: the one row that ends the turn before the line is stored


def command(project, ctx, said, channel, sender, extras, state):
    if not said.startswith("/"):
        return None
    out = _say()._say_command(project, ctx, said, channel, state.line_id, sender)
    parsed = operations.parse_chat(said)
    if parsed is not None and ops_natural.keeps_private(ctx, parsed[0], channel, sender):      # the card's private lines were drawn for this sender: the conversation keeps a word
        extras["stored"] = phrases.text("NAT_READ_REPLY", ctx["cfg"])
    return (*out, None)


def greeting_row(project, ctx, said, channel, sender, extras, state):
    if _talks(state) and greeting.is_greeting(said, helps=channel == "messaging"):      # S5: a greeting, or a plain request for help, is answered by code before any open question and any model: never the answer to the router's question
        return _plain(_say()._greeting_reply(ctx, channel, sender))
    return None


def plan_bare_word(project, ctx, said, channel, sender, extras, state):
    if channel == "messaging" and plan_confirm.live(project, sender) is not None:      # D5: a bare yes or no that the bridge did not take as the answer to the question it was shown for (it was not the last message, or no reply to it): never an OK, and no model reads it
        kind = natural.confirm_kind(said)
        if kind == "yes":
            extras["plan_keep"] = True
            return _plain(phrases.text("PLAN_NOT_LAST", ctx["cfg"]))
        if kind == "no":
            plan_confirm.drop(project, sender)
            return _plain(phrases.text("PLAN_DROPPED", ctx["cfg"]))
    return None


def delete_file(project, ctx, said, channel, sender, extras, state):
    if _talks(state) and channel == "messaging" and phone_delete.asks(said):      # a file is not deleted from a message (S14, S14b): one plain sentence, no card, no request, no model, before an open question (a request to delete is never its answer), the lists of code and the interpreter
        trash = importlib.import_module("ops_file_trash")
        if not trash.permitted(ctx, channel, sender):
            return _plain(phrases.text("PHONE_NO_FILE_DELETE", ctx["cfg"]))
        moved = trash.line(project, ctx, said, channel, sender, extras)      # R2-A: a sender who may move a file to the trash gets the card of the file (or the list, or one sentence); never a delete for good
        if moved is not None:
            return _plain(moved)
    return None


def router_question(project, ctx, said, channel, sender, extras, state):
    state.asked = _say()._open_question(ctx, channel, sender) if _talks(state) else None      # a sender who may not talk never answers the router's question; on a phone it is the question bound to this sender (S4)
    if state.asked is not None and ops_natural.recognises(ctx, said, state.natural_channel, sender):      # a request code recognises is a new line, never the answer (LIVE-2), for the interpreter's senders too
        state.asked = None
    state.framed = state.asked is not None and bool(extras.get("deferred"))      # S4: of the lines no list of code claims, the interpreter tells the answer from a new line, by a typed frame (decision 229 (1))
    return None      # it sets the frame and takes no line: `planning-agent` takes the line it binds


def state_question(project, ctx, said, channel, sender, extras, state):
    ops_say = _say()
    if state.asked is None and ops_say.state_question(said):
        if channel == "messaging" and not operations.permitted("status", channel, ctx["cfg"]["channels"], None, sender):
            return _plain(phone_refusal.said(operations.not_enabled('status', channel), channel, ctx["cfg"]))      # the state is read, so a profile that reads nothing is not told it
        if plan_confirm.needed(ctx, "status", channel, sender, False):      # D5: the state is a read like any other on a messaging app
            return _plain(plan_confirm.ask(project, ctx, "status", {}, said, sender, extras, state_question=True))
        return _plain(ops_say.state_reply(project, cfg=ctx["cfg"]))
    return None


def draft_answer(project, ctx, said, channel, sender, extras, state):
    if state.asked is not None:
        return None
    channel = state.natural_channel
    slot = ops_natural._slot(channel, sender)
    draft = ops_natural._live(slot)
    if draft is None:
        return None
    owner = ops_natural._owner(draft)
    if owner == "write":      # a question about a write to the person's accounts (package NR-5): the answer, or the draft is dropped and the line is new
        reply = ops_natural._writes().answer(project, ctx, draft, said, channel, sender, extras) if channel != "mcp" else None
        if reply is not None:
            return _out(extras, reply)
        extras["discarded"] = True
    else:
        answer = ops_natural._answers(ctx, draft, said, owner)
        drafts.drop(*slot)
        if answer is not None:
            return _out(extras, ops_natural._complete(project, ctx, draft, answer, said, channel, sender, extras))
        extras["discarded"] = True          # a question this line asks (a write's, NR-5) says the previous one was discarded
    return None


def event_list_number(project, ctx, said, channel, sender, extras, state):
    if state.asked is not None or state.natural_channel != "messaging":
        return None
    listed = importlib.import_module("event_lookup").take(project, ctx, said, sender, extras, ops_natural._writes(), ops_natural._clock())      # S11: a number after a list of events ("cancela o 2", "o 2") means that entry, as "cancela o evento 2" does
    return None if listed is None else _out(extras, listed)


def file_list_number(project, ctx, said, channel, sender, extras, state):
    if state.asked is not None or state.natural_channel != "messaging":
        return None
    picked = importlib.import_module("ops_file_read").take(project, ctx, said, state.natural_channel, sender, extras)      # S17: a number after a list of files ("o 2") picks that file
    return None if picked is None else _out(extras, picked)


def write_form_ops(project, ctx, said, channel, sender, extras, state):
    if state.asked is not None or state.natural_channel == "mcp":
        return None
    opened = ops_natural._writes().open_line(project, ctx, said, state.natural_channel, sender, extras)      # a write form opens the card of its exact content (limit L61), never a write
    return None if opened is None else _out(extras, opened)


def tier_1_form(project, ctx, said, channel, sender, extras, state):
    if state.asked is not None:
        return None
    found = natural.match(said)
    if found is None:
        return None
    return _out(extras, ops_natural.run(project, ctx, found["op"], found["args"], said, state.natural_channel, sender, extras))      # a tier-1 form is checked exactly as the typed command is (limit L54)


def talk_refusal(project, ctx, said, channel, sender, extras, state):
    if not _talks(state):      # admitted under another group, and no form of it took the line: it is not a model's, so it is refused as the typed `talk` is
        return _plain(phone_refusal.said(operations.refusal('say', channel, ctx['cfg']['channels'], sender=sender), channel, ctx["cfg"]))
    return None


def interpreter(project, ctx, said, channel, sender, extras, state):
    if not extras.get("deferred"):      # S1 (limit L63): a plain line of a sender the interpreter reads, which no list of code took (the hybrid order of 2026-10-21)
        return None
    if channel == "messaging":
        live_plan = plan_confirm.live(project, sender)      # D5: the sender's plan is a typed item of the frame (its operation and age; `last` holds the plan's own words)
        if live_plan is not None:
            extras["plan_frame"] = live_plan
    if state.framed:
        extras["frame_age"] = _say()._question_age(ctx, sender)      # the typed frame's one item is built from this age alone (runtime/ops_interpret.py `router_frame`)
    read = importlib.import_module("ops_interpret").turn(project, ctx, said, sender, extras)
    if read is not None:
        return (*read, None)
    if state.framed and extras.get("frame") == "new":
        state.asked = None      # S4: the model said `route`: a new request
    return None


def planning_agent(project, ctx, said, channel, sender, extras, state):
    asked = state.asked
    out = _say()._say_route(project, ctx, said, state.line_id, channel, answer_to=asked, sender=sender, extras=extras)
    if asked is not None and channel == "messaging":      # the person is told what their line was taken for
        out = (phrases.text("ANSWER_TAKEN", ctx["cfg"], id=asked) + "\n\n" + out[0], *out[1:])
    offered = importlib.import_module("ops_instructions").proposal(ctx, out[1], said, channel) if asked is not None else None
    state.took = "router-question" if asked is not None else "planning-agent"
    return (out[0] + "\n\n" + offered["text"], *out[1:], offered) if offered else (*out, None)


ROWS = {
    "confirmed-plan": confirmed_plan, "command": command, "greeting": greeting_row, "plan-bare-word": plan_bare_word, "delete-file": delete_file, "router-question": router_question,
    "state-question": state_question, "draft-answer": draft_answer, "event-list-number": event_list_number, "file-list-number": file_list_number, "write-form-ops": write_form_ops,
    "tier-1-form": tier_1_form, "talk-refusal": talk_refusal, "interpreter": interpreter, "planning-agent": planning_agent,
}


# --- the dispatchers ---------------------------------------------------------------------------------------------------------------------------------


def _walk(order: tuple, state: State):
    """The result of the first row of `order` that takes the line (a tuple, or `say`'s dict for `confirmed-plan`), or None. A row whose `channels` excludes the shell is skipped."""
    for name in order:
        shells = turn_order.channels(name)
        if shells == turn_order.MESSAGING and state.channel != "messaging":      # a row of the messaging shell is out of reach of every other name, a name the table does not know included: fail closed (L63(1))
            continue
        if state.channel in turn_order.SHELLS and state.channel not in shells:      # any other row: a name that is no shell of the table is left to the rows' own conditions, as it always was
            continue
        done = ROWS[name](state.project, state.ctx, state.said, state.channel, state.sender, state.extras, state)
        if done is not None:
            if TRACE is not None:
                TRACE(state.took or name, state)
            return done
    return None


def confirmed(project: str, ctx: dict, said: str, sender, can_send, plan_ok) -> "dict | None":
    """The row `confirmed-plan`: `say`'s own return when `plan_ok` names the sender's plan (the plan runs once, no model reads the line), else None (the row is gone, or `plan_ok` is None)."""
    state = State(project, ctx, said, "messaging", None, sender, {}, can_send, plan_ok)
    return _walk(tuple(name for name in turn_order.names("ops") if name == EARLY), state)


def dispatch(project: str, ctx: dict, said: str, channel: str, line_id, sender=None, extras=None) -> tuple:
    """(reply, request_id, pending_id, ran, run_id, proposal) of one stored line of the person: the first row of the stage `ops`, in the table's order, that takes it (`planning-agent`, the last, always
    does). `line_id` is the line's message id: the memory the router is given is the messages before it. An exception of a row propagates, as it did when the rows were a chain."""
    extras = extras if extras is not None else {}
    state = State(project, ctx, said, channel, line_id, sender, extras)
    done = _walk(tuple(name for name in turn_order.names("ops") if name != EARLY), state)
    if done is None:
        raise RuntimeError("no row of the stage ops took the line")
    return done


def dispatch_rows(names, project: str, ctx: dict, said: str, channel: str, line_id=None, sender=None, extras=None):
    """For tests only: the rows named, in the table's order, and None when none takes the line (`TAKE_ROWS`: the five rows that were `ops_natural.take`). `channel` is the shell that carries the line."""
    wanted = set(names)
    unknown = wanted - set(ROWS)
    if unknown:
        raise ValueError(f"no row {sorted(unknown)}")
    extras = extras if extras is not None else {}
    return _walk(tuple(name for name in turn_order.names("ops") if name in wanted), State(project, ctx, said, channel, line_id, sender, extras))


# --- the claims of the queue decision ---------------------------------------------------------------------------------------------------------------


def _form_or_draft(ctx, said, channel, sender, plan_before) -> bool:
    ops_say = _say()
    return ops_say.asks_natural(ctx, said, channel, sender) and not ops_natural.peek_model(ctx, said, ops_say._natural_channel(channel), sender)      # a tier-1 form, a write form or the answer to the sender's draft, unless it completes a draft that calls a model


def _greets(ctx, said, channel, sender, plan_before) -> bool:
    return _say()._greets(ctx, said, channel, sender)      # S5: a greeting is answered by code too, never queued


def _deletes_a_file(ctx, said, channel, sender, plan_before) -> bool:
    ops_say = _say()
    return channel == "messaging" and ops_say.may_talk(ctx, channel, sender) and importlib.import_module("ops_file_trash").catches(ctx, said, channel, sender)      # S14b: a request to delete a file is answered by code, so it waits for no run and no queue (R2-A: for a sender who may move a file to the trash, when the name can be read by code)


def _bare_plan_word(ctx, said, channel, sender, plan_before) -> bool:
    return bool(plan_before and natural.confirm_kind(said) is not None)      # D5: a yes or a no with a live plan is answered by code (`plan-bare-word`), never queued


# `_form_or_draft` stands for THREE rows at once (`draft-answer`, `write-form-ops`, `tier-1-form`) because it asks `ops_natural.peek`, which answers for the three together (a tier-1 form, a write form, the
# answer to the sender's live draft). A package that removes one of those rows must first split `peek`, or the claim keeps answering for a row that is gone: `code_claims` drops the claim only when ALL
# of its rows have left the table.
CLAIMS = (      # (the rows whose lines the claim stands for, the claim), in the order the queue decision always read them
    (("draft-answer", "write-form-ops", "tier-1-form"), _form_or_draft), (("greeting",), _greets), (("delete-file",), _deletes_a_file), (("plan-bare-word",), _bare_plan_word),
)


def code_claims(ctx: dict, said: str, channel: str, sender, plan_before: bool) -> bool:
    """Whether code answers this plain line by itself, with no model: such a line takes no route lock and is never queued (`say`'s queue decision, `handled`). It is computed from the claims of the rows
    that answer by code, and a claim goes with its rows: when every row it stands for has left the table, it is not asked. `plan_before` is whether a plan of the sender was live when the line came."""
    names = set(turn_order.names("ops"))
    return any(claim(ctx, said, channel, sender, plan_before) for rows, claim in CLAIMS if names & set(rows))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
