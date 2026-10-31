#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The one dispatcher of the natural requests (package NR-2): it executes what a tier chose, checked exactly as the typed command is.

A line in the person's own words reaches an operation by two ways: a tier-1 form (runtime/natural.py `match`: code, no model) or the router's
`Route: none (operation)` outcome (runtime/router.py, read and believed by code against the line). Whichever chose, THIS file executes, and the order is
fixed (contracts/runtime.md, "Natural requests", limit L54):

  1. The operation has a class in runtime/natural.py `CLASSES`.
  2. The operation's row lists the channel that carries the line (else the typed command's sentence), and `operations.refusal(op, channel, policy,
     sender=sender)` has no refusal: the sentence the typed command gets, and no call. A decision (D) asks it for the operation AND for `pending`.
  2b. D5 (package BL2a, limit L65; `plan_confirm.ACTIVE`): on a messaging app a read or an act is not run until the person said yes to the sentence code wrote from the call: `run`
     returns "I understood: ... Shall I go ahead?" (`plan_confirm.ask`) unless the call is `confirmed` (`ops_say._confirmed`, from the bridge's `plan_ok`), and a decision (reject, release)
     is asked about only when it is open (`_decision`). The number rule of step 4 stays whatever the person says.
  3. By class: R is called with the channel and sender as `_say_command` calls it and its result is written by code; N (a reminder) is asked first when the
     router chose it (below); W runs nothing (the reply is the exact command to send); D decides nothing (the reply points to the card, which the messaging
     bridge sends again); E and G run nothing (the reply is the exact operation or command and the place: an E operation ends in a card the person approves);
     `ask` is called with the person's WHOLE line.
     On a messaging app (slice S20) a command with a typed form is run BY that typed form, so that the words and the line `/cancel 9` have the same policy check, the same
     refusals and the same effect: the commands the table answers (`/cancel`, `/stop-task`, `/retry`, `/attachments`) are called here as `ops_say._say_command` calls them, and
     the ones the messaging bridge answers itself (`/pending`, `/reject`, `/release`, `/add`, `/discard`) are handed to the bridge as `extras["typed"]`, the typed line, which
     it handles as if the person had typed it. A decision is the exception on the side of the effect: `approve` is never run from words, its card is sent again (below).
  4. Every argument is a number written in the line, a piece of it, a span of it or, for a time, the router's `When:` slot, which no code can check
     against the line: an operation that receives one is NEVER executed at once.

What the router chose and no code can check against the line (a reminder in a language no table knows, a reminder to forget) is not done: it is SHOWN and
confirmed, by the rules of the reminders' own conversation (runtime/natural.py: a reminder in free text is made only after a yes to the full reading shown,
a pick is never a yes, and the moment shown is the moment made). The question is a draft in the one store of drafts (runtime/drafts.py, memory only, ten
minutes, one per channel and sender, never logged, never in the store), where the messaging bridge's own questions wait too. The same store holds the
choice of a file for a question to `ask`. The next line of that sender that answers the draft completes it; any other line drops the draft and is handled as
new. A reminder's words are in the draft and in the `reminders` table once made, and nowhere else (limit L51): the conversation stores a neutral word.

Sibling of runtime/ops_say.py, which calls `peek`, `recognises` and `run`; the order in which a line is taken (the answer to a draft, a number after a list, a write form, a tier-1 form: what `take` was) is the table of runtime/turn_order.py, dispatched by runtime/ops_turn.py, whose rows call the helpers here; it reaches an operation of ops.py through ops_facade.py (at call time) and ops_say.py at call time, never at import. Standard library
only. Runs on Python 3.9: python3 runtime/ops_natural.py --help
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import os
import re
import sys
import time
import unicodedata

import drafts
import item_refs
import line_stage
import messaging_guard as guard
import ops_core as core
import ops_facade
import natural
import operations
import ops_actor
import ops_items
import ops_reminders
import phone_errors
import phone_refusal
import phrases
import plan_confirm
import reminders
import turn_gate

DRAFT_TTL = drafts.TTL       # seconds a question waits for its answer (this spec's choice, not measured)
RENDER_MAX = 1800            # characters of a read written for a messaging app
RENDER_LONG = 6000           # ... and for any other channel
LIST_MAX = 12                # rows of a list a read writes
FIELD_MAX = 120              # characters of one value in a row
monotonic = time.monotonic   # the clock of a question's age (a test replaces it)
BRIDGE_FORMS = {"attachment-add": "/add {attachment_id}", "attachment-discard": "/discard {attachment_id}"}   # the commands a messaging app has for these
PATH = re.compile(r"(?:^|[\s'\"(])(?:/[\w.-]+/|~/|[A-Za-z]:\\)[^\s]*")      # a path of this machine, not a typed command such as /approve 12
# S20: the typed command of an operation on a messaging app: (the line, the parameter that fills it or None, whether the messaging bridge answers it itself). The line is the typed
# one; an operation here is run BY it (`_typed`), never by a second path, so that the words and the line have one policy check, one set of refusals and one effect.
TYPED = {"pending": ("/pending", None, True), "attachments": ("/attachments", None, False), "progress": ("/progress", None, False),
         "cancel": ("/cancel {n}", "request_id", False), "stop-task": ("/stop-task {n}", "task_id", False), "retry": ("/retry {n}", "task_id", False),
         "attachment-add": ("/add {n}", "attachment_id", True), "attachment-discard": ("/discard {n}", "attachment_id", True),
         "reject": ("/reject {n}", "pending_id", True), "release": ("/release {n}", "pending_id", True)}
ROUTINE_BRAKES = {"routine-pause": "CMD_ROUTINE_PAUSED"}      # S20: no typed form on a phone; the call is the operation's own, after the same policy check. `routine-cancel` is final, so it is not done from words: PHONE_ROUTINE_CANCEL
# The parameter that names the decision or the act in the arguments of a call, for every operation that a model or the router may choose and that is vetted against the line (`turn_gate.number_believed`)
VETTED = {"approve": "pending_id", "reject": "pending_id", "release": "pending_id", "cancel": "request_id", "stop-task": "task_id", "retry": "task_id",
          "attachment-add": "attachment_id", "attachment-discard": "attachment_id", "routine-pause": "routine_id"}


def _say():
    return importlib.import_module("ops_say")


# --- the drafts --------------------------------------------------------------------------------------------------------------------------------


def project_key(project: str) -> str:
    """The id a project has in the shells (runtime/shell_kit.py `project_id`: the first 12 hexadecimal characters of the sha256 of its real path), which the bridge's
    questions carry as their `project`; a test ties the two."""
    return hashlib.sha256(os.path.realpath(project).encode("utf-8")).hexdigest()[:12]


def forget_all() -> None:
    """Drop every draft (a test, and a process that stops)."""
    drafts.clear()


def _slot(channel, sender):
    return channel or "chat", sender or ""


def _clock():
    return ops_reminders.now()


def _answers(ctx: dict, draft: dict, said: str, owner: str):
    """What a line says to a draft, or None for a line that is not an answer. The choice of a file: its number in the list, or its id (an integer). A question about a
    reminder: the reminders' own rules decide (natural.complete); the line answers it when they say anything but 'not an answer'."""
    if owner == "ops":
        if draft.get("project") != project_key(ctx["cfg"]["project"]):      # the store is of the process: a choice offered in another project is never answered in this one
            return None
        word = natural.normal(said)
        digits = unicodedata.normalize("NFKC", word)
        if digits.isdigit() and 1 <= int(digits) <= len(draft["ids"]):
            return int(digits)
        listed = [natural.normal(i) for i in draft["ids"]]      # an id is written with hyphens; the line is compared as every line is
        return listed.index(word) + 1 if word in listed else None
    if draft.get("project") not in (None, project_key(ctx["cfg"]["project"])):
        return None
    if draft.get("at") is not None and monotonic() - draft["at"] > DRAFT_TTL:      # a question about a reminder waits ten minutes (the bridge sweeps its own on the tick)
        return None
    if said.lstrip().startswith("/"):
        return None
    return turn_gate.complete_reminder(draft, said, _clock())


def _expired(draft: dict) -> bool:
    return draft.get("at") is not None and monotonic() - draft["at"] > DRAFT_TTL


def _writes():
    return importlib.import_module("ops_natural_writes")


def _owner(draft: dict) -> str:
    """Who keeps a draft: the choice of a file for an `ask` ("ops"), a write to the person's accounts ("write", package NR-5), or a question about a reminder ("remind")."""
    return "ops" if draft.get("kind") == "which" else "write" if draft.get("kind") == "write" else "remind"


def _live(slot: tuple):
    """This sender's draft, or None; a question about a reminder that waited more than ten minutes outside a messaging app (the page, the conversation: nothing else
    sweeps it) is dropped here. On a messaging app the bridge sweeps its own on its tick and tells the sender a late yes is late."""
    draft = drafts.get(*slot)
    if draft is not None and slot[0] != "messaging" and _owner(draft) == "remind" and _expired(draft):
        drafts.drop(*slot)
        return None
    return draft


def peek(ctx: dict, said: str, channel, sender, claim: bool = True) -> bool:
    """Whether a plain line is handled here: a decision said in words (S41-11: the one closed form code keeps), or the answer to this sender's live draft. Reads, changes nothing. `claim`
    is kept for the callers that pass it: no write form is read here any more (a write said in words is read by the interpreter, L63)."""
    if natural.decision(said) is not None:
        return True
    slot = _slot(channel, sender)
    draft = _live(slot)
    if draft is not None and _owner(draft) == "write":
        return channel != "mcp" and _writes().answers(ctx, draft, said)
    if draft is None:
        return False
    owner = _owner(draft)
    return drafts.get(*slot, owner) is not None and _answers(ctx, draft, said, owner) is not None


def recognises(ctx: dict, said: str, channel, sender) -> bool:
    """Whether a plain line is a request of its own that code recognises: a decision said in words, a reminder or a write to the person's accounts (the private words of
    `turn_gate.private_kind`: S41-9's data, no table of lines), or the answer to this sender's live draft. Such a line is NEW, never the answer to a question the router left open (package
    LIVE-2); only a question about the state ("progress"), a plain sentence and a reply to the question's own message may be the answer. Reads, changes nothing."""
    return peek(ctx, said, channel, sender, claim=False) or turn_gate.private_kind(said) is not None


def peek_model(ctx: dict, said: str, channel, sender) -> bool:
    """Whether the line answers a draft whose completion calls a model (the choice of a file for an `ask`): it takes the route lock like any model call, so
    it waits in the queue (the page) or is kept by the bridge when the router is busy, and the draft is not lost."""
    draft = drafts.get(*_slot(channel, sender), "ops")
    return draft is not None and _answers(ctx, draft, said, "ops") is not None


def needs(ctx: dict, said: str, channel, sender):
    """The operation whose group a sender must hold for this plain line to be handled here, or None (the line needs `talk`, as every plain line does): the
    group of a tier-1 form that the channel's rows list (a read or a notice its own, a decision `pending`), `ask` for the choice of a file, `remind` for the
    answer to a question about a reminder. Never an operation whose row does not list the channel: its refusal would say that a configuration turns on what none can."""
    draft = _live(_slot(channel, sender))
    if draft is not None:
        owner = _owner(draft)
        if owner == "write":
            return draft["op"] if _writes().answers(ctx, draft, said) else None
        if _answers(ctx, draft, said, owner) is not None:
            return "ask" if owner == "ops" else "remind"
    group = line_group(said)
    if group is not None and channel in operations.by_name(group)["channels"]:
        return group
    return None


def line_group(said: str):
    """The group a messaging sender must hold for a plain line that code reads whole: `pending` for a decision said in words (`natural.decision`: a decision is a read of its card), else None (the line needs `talk`)."""
    return "pending" if natural.decision(said) is not None else None


def stored_line(ctx: dict, said: str, channel=None, sender=None) -> str:
    """The text the conversation stores for the person's line: the line, but a neutral word for the words of a reminder (limit L51) and for a line that asks for a write to the
    person's accounts or answers the question of one (limit L61)."""
    if channel is not None or sender is not None:
        draft = drafts.get(*_slot(channel, sender), "write")
        if draft is not None:
            return phrases.text("NW_PRIVATE_LINE", ctx["cfg"])
    kind = turn_gate.private_kind(said)
    if kind == "write":      # a line the gate reads as a write to the person's accounts that no family read whole: stored as a request to the accounts, never as "a reminder"
        return phrases.text("NW_PRIVATE_LINE", ctx["cfg"])
    return phrases.text("NAT_PRIVATE_LINE", ctx["cfg"]) if kind == "reminder" else said


PRIVATE_READS = ("pending", "task")      # the reads that draw a decision's card or a task's pending list: the private lines of a card are drawn for a holder of ask-mail


def keeps_private(ctx: dict, name, channel, sender) -> bool:
    """Whether the reply of this read, drawn for THIS sender, may hold lines that only a holder of `ask-mail` reads (the recipient, the subject, the text of a mail or
    an event): such a reply goes to the chat that asked and the conversation, which the MCP mode reads, keeps a neutral word (limit L51), typed command or words."""
    return channel == "messaging" and name in PRIVATE_READS and bool(sender) and bool(item_refs.private_groups(ctx, "messaging", sender))


def private_ids(rows: list) -> set:
    """{id: the phrase key of the neutral word} for the lines of the person that were followed, in the conversation, by the neutral reply of a reminder (the reply stored for
    a reminder asked in words or a reminder to forget) or of a write to the person's accounts (NR-5): a line in a language no table ships is recognised only after the
    router named it, so its line was stored as written, and every reader but the person's own shell is shown the neutral word instead (limits L51 and L61)."""
    replies = set(phrases.every("NAT_PRIVATE_REPLY"))
    writes = set(phrases.every("NW_PRIVATE_REPLY"))
    return {a["id"]: ("NW_PRIVATE_LINE" if b["text"] in writes else "NAT_PRIVATE_LINE") for a, b in zip(rows, rows[1:])
            if a.get("id") is not None and a["role"] == "user" and b["role"] == "assistant" and b["text"] in replies | writes}


def is_placeholder(text) -> bool:
    return isinstance(text, str) and text in phrases.every("NAT_PRIVATE_LINE") + phrases.every("NAT_PRIVATE_REPLY") + phrases.every("NW_PRIVATE_LINE") + phrases.every("NW_PRIVATE_REPLY") + phrases.every("IX_PRIVATE_LINE")


# --- the entry points --------------------------------------------------------------------------------------------------------------------------


def run(project: str, ctx: dict, name: str, args: dict, said: str, channel, sender, extras: dict, when=None, routed: bool = False, confirmed: bool = False) -> str:
    """Execute one operation chosen by a tier, and return the reply (see the module's text for the order). `args` are the arguments natural.py checked:
    {parameter: value}; `when` is the router's normalised time; `routed` says the router chose the operation: a notice or an own write it chose (a time
    it normalised, a reminder to forget) always asks first, because no code can check the choice against the line. `confirmed` (D5, limit L65) says the person said yes
    to the sentence code wrote from this very call (runtime/ops_say.py `_confirmed`, from the sender's `plan_ok`): on a messaging app a call that is not confirmed asks
    "Posso?" instead of running (`plan_confirm.needed`), after the policy and the number have been checked."""
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    cls = natural.class_of(name)
    if cls is None:
        return f"error: {name} is not an operation of the table of natural requests"
    if name == "commands":      # the help is public: what can be asked, never a read of the project
        return t("HELP") if channel == "messaging" else operations.chat_help()
    row = operations.by_name(name)
    where = "terminal" if channel == "chat" else channel      # the conversation's own shell is the terminal's equal, not a channel of its own
    if where not in row["channels"]:
        if channel == "messaging":      # a phone has no terminal: what and where, never a command (limit L62)
            return phone_sentence(ctx, name)
        extra = _command(ctx, name, args, "terminal", channel) if cls in ("G", "E") else None
        return f"error: /{name} is done in the terminal or on the page" + (f". {extra}" if extra else "")
    policy = cfg["channels"]
    refused = operations.refusal(name, where, policy, sender=sender)
    if refused:
        return phone_refusal.said(refused, channel, cfg)
    if cls == "D":
        refused = operations.refusal("pending", where, policy, sender=sender)
        if refused:
            return phone_refusal.said(refused, channel, cfg)
    if channel == "messaging" and routed and name in VETTED:      # S20 (review round): a decision or an act that a MODEL or the router chose is believed only for the number the line writes (what it means is the person's OK of the plan, L65)
        if not turn_gate.number_believed(said, args.get(VETTED[name])):
            return phrases.text("NAT_WHICH_DECISION" if cls == "D" else "NAT_ASK_ID", cfg)
    if name == "items" and "kind" not in args:      # BL5B: the list's kind, account and range are part of the call, so that the plan's hash binds them and the question says what will be read; a correction keeps what the plan it corrects had (`extras["plan_previous"]`, the sender's own plan)
        spans = ops_items.span_args_of(args)      # CB-1 (catalog version 2): the spans of the line the interpreter verified for the target, the day and the state; the list reads them as code, and they never reach `items` as they are
        args = {key: value for key, value in args.items() if key not in ops_items.SPAN_PARAMS.values()}
        said_no = ops_items.unreadable_filter(spans, _clock())      # a day or a state the person stated and code cannot read is a sentence: never a list that looks filtered
        if said_no:
            return phrases.text(said_no, cfg)
        spans = ops_items.without_named_account(ctx, spans, said)      # mail-list-account: a target that is only the plain name of the account the line names is that account, not a word filter
        box = ops_items.mailbox_target(ctx, spans)      # CB-9: a target that names a mailbox is that source, or a question: never a word filter that looks like one
        if box and box[0] == "ask":
            return phrases.text("NW_ITEMS_MAILBOX", cfg, names=box[1])
        if box:
            spans = {key: value for key, value in spans.items() if key != "target"}
        args = dict(args, **ops_items.items_args(said, _clock(), extras.get("plan_previous"), spans), **({"source": box[1]} if box else {}))
    if name == "mail-read" and not confirmed and args.get("number") is not None and not (args.get("message") or args.get("account") or args.get("service")) and not ops_items._named_account(said):
        listed = item_refs.listed_source(ctx, channel, sender)      # N1 of mail-list-account: the line right after a reply that listed ONE mail source means that list; bound here, so the plan's hash binds it
        if listed:
            args = dict(args, message=f"{listed}#{args['number']}")
    if name not in ("reject", "release") and plan_confirm.needed(ctx, name, channel, sender, confirmed) and not plan_confirm.incomplete(name, args):      # D5: the sentence of the call, and the person's OK, before it runs (a decision that is no open one gets its own sentence first: `_decision`)
        if name == "mail-ask":      # MAIL-SUMMARY: the plan binds the mailbox snapshots the number or the words name, so that a yes reads the message that was meant (runtime/ops_mail_ask.py `pin`)
            args = dict(args, pin=importlib.import_module("ops_mail_ask").pin(ctx, args, said, channel, sender))
        asked = {"choices": ops_items.account_choices(ctx, args), "named": ops_items.account_named_words(ctx, args)} if name == "items" else {}      # mail-list-account: a list of mail with no account asks which one, in place of "Shall I go ahead?"
        return plan_confirm.ask(project, ctx, name, args, said, sender, extras, when=when, routed=routed, words=extras.get("plan_words"), **asked)
    if channel == "messaging" and cls != "D":      # S20: a command with a typed form is run by it; a routine's brake is called here
        done = _typed(project, ctx, name, args, sender, extras, row)
        if done is not None:
            return done
    if name == "file-read":      # S8: the text of a file found by its name; code writes the reply and the conversation keeps a neutral word (runtime/ops_file_read.py)
        return importlib.import_module("ops_file_read").reply(project, ctx, args, said, channel, sender, extras)
    if name == "file-ask":      # FA-1: a question about one file of the person's Drive or OneDrive; the file's text goes only to the quarantined reader (one contained run of the answer skill), code checks its quotes and writes the reply, and the conversation keeps a neutral word (runtime/ops_file_ask.py)
        return importlib.import_module("ops_file_ask").reply(project, ctx, args, said, channel, sender, extras)
    if name == "mail-read":      # CB-3: the text of one message of the mail snapshots; code writes the reply, no model reads it, and the conversation keeps a neutral word (runtime/ops_mail_read.py)
        return importlib.import_module("ops_mail_read").reply(project, ctx, args, said, channel, sender, extras)
    if name == "mail-ask":      # MAIL-SUMMARY: a question about one message of the mail snapshots; its text goes only to the quarantined reader, code checks its quotes and writes the reply (runtime/ops_mail_ask.py)
        return importlib.import_module("ops_mail_ask").reply(project, ctx, args, said, channel, sender, extras)
    if name == "todo-list":      # CB-5: the open tasks of the person's own to-do list, read live; code writes the reply and the conversation keeps a neutral word (runtime/ops_todo.py)
        return importlib.import_module("ops_todo").reply_list(project, ctx, args, channel, sender, extras)
    if name == "research":      # R2-F1: a question of general information answered by a web search; code runs the research skill, writes the reply and the conversation keeps a neutral word (runtime/ops_research.py)
        return importlib.import_module("ops_research").reply(project, ctx, args, said, channel, sender, extras)
    if cls == "R":
        if "mcp" not in row["channels"] or keeps_private(ctx, name, channel, sender):      # the MCP mode reads the conversation: what it could not read itself (reminders, files people sent, the private lines of a card drawn for a holder of ask-mail) is stored as a neutral word (limits L50, L51)
            extras["stored"] = t("NAT_READ_REPLY")
        return _read(project, ctx, name, row, args, channel, sender)      # NR-5: the noun of the line says which items; S15: an account it names narrows them (both were read into `args` above; a confirmed plan re-reads nothing from its line)
    if cls == "N":
        return _notice(project, ctx, name, row, args, said, channel, sender, extras, when, routed)
    if cls == "W":
        command = _command(ctx, name, args, channel, channel)
        return t("NAT_TYPE_IT", command=command) if command else phone_sentence(ctx, name)
    if cls == "D":
        return _decision(project, ctx, name, args, channel, sender, extras, said, when, routed, confirmed)
    if cls in ("G", "E"):      # run nothing: the place and the exact command (an E operation, run there, ends in a card of the exact content)
        return _gated(ctx, name, args, channel)
    if name == "ask":
        return _ask(project, ctx, row, said, channel, sender, extras)
    return f"error: {name} is not reached from a line"


def run_routed(project: str, ctx: dict, operation: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply for an operation the router named (router.read_route kind `operation`, already believed against the person's line): the dispatcher
    believes it against the line AGAIN, with the line the request holds, and executes it. A router-normalised time makes the reply a question. A write is read again by
    the family's own parse and the router's time is never used for it: a time the line's words do not give is asked."""
    checked = natural.check_operation(operation.get("name"), _slots_of(operation), operation.get("when"), said)
    if not checked["ok"]:
        return phrases.text("NAT_NOT_BELIEVED", ctx["cfg"])
    if natural.class_of(checked["name"]) == "E" and channel != "mcp":      # the router named a write: the line is read again by the family's own parse, the name is only a hint (limit L61)
        opened = _writes().open_line(project, ctx, said, channel, sender, extras, hint=checked["name"])
        if opened is not None:
            return opened
    return run(project, ctx, checked["name"], checked["args"], said, channel, sender, extras, when=checked["when"], routed=True)


def _slots_of(operation: dict) -> dict:
    """The router's slots back as `Argument` words (natural.check_operation reads slots by their router name): the arguments are already by
    parameter, so the slot of a parameter is found in the row; the words are the person's own."""
    row = natural.NATURAL.get(operation.get("name"), {"slots": {}})["slots"]
    by_param = {spec[1]: slot for slot, spec in row.items()}
    return {by_param[p]: str(v) for p, v in (operation.get("args") or {}).items() if p in by_param}


# --- R: reads ----------------------------------------------------------------------------------------------------------------------------------


def _call(project: str, row: dict, found: dict, channel, sender):
    """Call the operation of a row as `_say_command` calls a typed command: the channel is `messaging` or `chat` (recorded as the carrying channel), and a
    messaging call names the sender."""
    function = ops_facade.function(row["call"])
    found = dict(found)
    if row.get("channel_arg"):
        found["channel"] = channel if channel == "messaging" else "chat"
        if channel == "messaging":
            if "sender" not in inspect.signature(function).parameters:
                raise core.OpsError(f"/{row['name']} is not done from a messaging app", 1)
            found["sender"] = sender
    with ops_actor.carried_by(channel):
        return function(project, **found)


def _missing(row: dict, args: dict) -> list:
    return [a["name"] for a in row["args"] if a.get("required") and a["name"] not in args]


def _read(project: str, ctx: dict, name: str, row: dict, args: dict, channel, sender) -> str:
    cfg = ctx["cfg"]
    if _missing(row, args):
        return phrases.text("NAT_ASK_ID", cfg)
    if name in ("status", "progress"):
        return _say().state_reply(project, cfg=cfg)
    if name == "items":      # S19: the mail or the calendar is read
        if args.get("kind") == "calendar":
            line_stage.publish("calendar")
        else:
            line_stage.publish("mail")
    try:
        out = _call(project, row, args, channel, sender)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    if name == "items":      # S11: the numbers this list shows are what the sender may point to next (runtime/event_lookup.py)
        importlib.import_module("event_lookup").remember_items(ctx, channel, sender, out)
        ops_items.remember_listed(ctx, channel, sender, out)      # N1 of mail-list-account: the one mail source this reply listed is what the next line's number means
    if name == "items":      # S15: with nothing to list, the reply says what to add and where (a phone: no command)
        return _clip(ops_items.reply(project, ctx, out, channel), channel)
    return _clip(_render(name, out, cfg, channel), channel)


def _error(cfg: dict, error, channel) -> str:
    """An error of the operations layer as a person is told: its message in the project's language where a table has it; on a messaging app a message with a path
    in it, or a problem of this machine, is a fixed sentence."""
    text = str(error)
    if channel == "messaging" and getattr(error, "phone", None):      # a sentence the operation wrote for a phone: plain words, what failed and what to check (messaging_failure); made safe in a language that is not English (S14b)
        return phone_errors.safe(str(error.phone), cfg)
    if channel == "messaging" and (PATH.search(text) or guard.find(text) or getattr(error, "code", 1) == 3):
        return phrases.text("ATT_MACHINE", cfg)
    return "error: " + phrases.localize(text, cfg)


def _clip(text: str, channel) -> str:
    limit = RENDER_MAX if channel == "messaging" else RENDER_LONG
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _scalar(value) -> bool:
    return isinstance(value, (str, int, float, bool)) and not isinstance(value, bytes)


def _short(value) -> str:
    one = " ".join(str(value).split())
    return one if len(one) <= FIELD_MAX else one[:FIELD_MAX - 1].rstrip() + "…"


HIDDEN_KEYS = ("command", "path", "folder", "dir", "warning")      # a field that names this machine or carries a command is not written into a message


REFUSAL_KEYS = ("error", "refused", "reason", "why")      # the fields of a result that tell why something was not done


def _hidden(key) -> bool:
    return any(word in str(key).lower() for word in HIDDEN_KEYS)


def _row_line(row: dict, keys=None) -> str:
    keys = keys or [k for k, v in row.items() if _scalar(v) and v not in ("", None) and not _hidden(k)][:5]
    return ", ".join(f"{k} {_short(row[k])}" for k in keys if k in row and _scalar(row[k]) and row[k] not in ("", None))


def _render(name: str, out, cfg: dict, channel) -> str:
    """A read's result as lines of text, written by code from the result's own fields: no model, and only scalar fields of the rows (a catalog's sample values
    and headings, a task's long text, a path of this machine are never copied into it)."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    if name == "pending" and "pending" in out:
        rows = out["pending"]
        if not rows:
            return t("NAT_NOTHING_WAITS")
        return "\n".join(f"#{r['id']} {phrases.kind_word(r['kind'], cfg)}: {phrases.heading(r['title'], cfg)}" for r in rows[:LIST_MAX])
    if name == "sources":
        rows = out.get("sources") or []
        if not rows:
            return t("NAT_NO_SOURCES")
        lines = []
        for r in rows[:LIST_MAX]:
            entry = r.get("catalog") or {}
            lines.append(f"- {r['id']} ({r.get('type') or 'file'}, {entry.get('date') or '?'})" + (f": {_short(r['description'])}" if r.get("description") else ""))
        return "\n".join(lines)
    if name == "reminders":
        return _reminders(out, cfg)
    if name == "items":
        return ops_items.render(out, cfg)
    if name == "artifacts":
        rows = out.get("artifacts") or []
        return "\n".join(f"- {r['path']}" for r in rows[:LIST_MAX * 3]) or t("NAT_NOTHING")
    if name == "artifact":
        return str(out.get("text") or t("NAT_NOTHING"))
    if name == "instructions":
        return str(out.get("text") or t("NAT_NOTHING"))
    lines = []
    for key, value in out.items():
        if _hidden(key):
            continue
        if channel == "messaging" and key in REFUSAL_KEYS and isinstance(value, str) and not phone_errors.english(cfg):      # a refusal a result carries is told in the language on a phone (S14b)
            lines.append(phone_errors.safe(value, cfg))
        elif _scalar(value):
            lines.append(f"{key}: {_short(value)}")
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            lines.append(f"{key}:")
            lines += [f"- {_row_line(v)}" for v in value[:LIST_MAX]]
        elif isinstance(value, dict):
            inner = _row_line(value)
            if inner:
                lines.append(f"{key}: {inner}")
    return "\n".join(lines) or t("NAT_NOTHING")


def _reminders(out: dict, cfg: dict) -> str:
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    why = {"late": "RM_WHY_LATE", "sender removed": "RM_WHY_SENDER_REMOVED", "not permitted": "RM_WHY_NOT_PERMITTED"}
    lines = [f"#{r['id']} {r['due']}" + (f" {r['text']}" if "text" in r else "") for r in out["open"]]
    gone = [f"#{r['id']} {r['due']}" + (f" {r['text']}" if "text" in r else "") + f" ({t(why.get(r.get('why'), 'RM_WHY_OTHER'))})" for r in out["not_sent"]]
    if not lines and not gone:
        return t("RM_NONE_WAIT")
    head = [t("RM_WAITING_HEAD", zone=out["zone"]) if lines else t("RM_NONE_WAIT")]
    return "\n".join(head + lines + ([t("RM_NOT_SENT_HEAD")] + gone if gone else []))


# --- N: a notice and the person's own writes --------------------------------------------------------------------------------------------------


def _notice(project: str, ctx: dict, name: str, row: dict, args: dict, said: str, channel, sender, extras: dict, when, routed: bool = False) -> str:
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    if name == "remind":
        extras["stored"] = t("NAT_PRIVATE_REPLY")
        if channel != "messaging":      # a reminder is sent to a chat of a messaging app: elsewhere it is the terminal's command, which names the listed sender
            return t("NAT_TYPE_IT", command=_command(ctx, name, dict(args, to="<platform:id>", **({"when": when} if when else {})), "terminal", channel))
        # The router chose it, and no code can check the choice against the line: the reading is SHOWN and the reminder is made only after the person's yes (the
        # reminders' own rules, runtime/natural.py: the words are the person's span, the time is the one the router wrote, parsed by the same engine and checked by
        # `reminders.resolve`; a pick is never a yes; the moment shown is the moment made). The words reach the engine as a line of the `/remind` kind.
        line = _reminder_line(args, when)
        try:
            asked = _call(project, row, {"said": line, "how": "command"}, channel, sender)
        except core.OpsError as e:
            return _error(cfg, e, channel)
        return _ask_draft(ctx, asked, channel, sender, "command", extras)
    if name == "reminder-forget" and isinstance(args.get("matching"), str):      # CB-8 (catalog version 2): the reminder is named by words, found by code among the sender's own waiting ones
        return _forget_by_words(project, ctx, row, args["matching"], channel, sender, extras)
    if _missing(row, args):
        return t("NAT_ASK_ID")
    if name == "reminder-restore" and routed:      # the router chose it and no code can check the choice against the line: nothing is brought back from it, the reply is the command
        command = _command(ctx, name, args, channel, channel)
        return t("NAT_TYPE_IT", command=command) if command else phone_sentence(ctx, name)
    if not routed:
        try:
            done = _call(project, row, args, channel, sender)
        except core.OpsError as e:
            return _error(cfg, e, channel)
        return phrases.localize(done["reply"], cfg) if "reply" in done else t("RM_NOTHING_TO_RESTORE") if name == "reminder-restore" else t("NAT_NOTHING")      # {"none": True}: nothing to bring back
    # a reminder to forget that the router chose: shown with what it is, and cancelled only on a yes
    try:
        shown = _call(project, row, dict(args, preview=True), channel, sender)
    except core.OpsError as e:
        return _plain_error(cfg, e, channel) or _error(cfg, e, channel)
    sentence, draft = natural.forget_question([shown], cfg, channel != "messaging" or _notices_text(cfg))
    extras["stored"] = t("NAT_PRIVATE_REPLY")      # the question shows the reminder's words: the conversation keeps a neutral word (limit L51)
    drafts.put(*_slot(channel, sender), dict(draft, project=project_key(ctx["cfg"]["project"]), at=monotonic(), message_id=None), "remind")
    if channel == "messaging":
        extras["ask_yes"] = True      # review C2-d: a forget question has the Yes button too
    return sentence


def _forget_by_words(project: str, ctx: dict, row: dict, span: str, channel, sender, extras: dict) -> str:
    """CB-8: "cancela o lembrete da florista" read by the interpreter or the router: the words of the span (`reminders.forget_words`) find the sender's waiting reminders (`reminders.matching`, the one rule
    the bridge's own form uses too). One: shown with what it is and cancelled only on the person's yes (the same question as a reminder named by a number, `natural.forget_question`). Several: a
    numbered list that asks which, the words shown only when the project's notices carry text (limit L51). None, or no word to look for: one sentence. Another sender's reminder never matches, and
    nothing is cancelled here."""
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    extras["stored"] = t("NAT_PRIVATE_REPLY")      # the reply shows the reminder's words: the conversation keeps a neutral word (limit L51)
    words = reminders.forget_words(span)
    if not words:
        return t("RM_FORGET_WORDS_NONE")
    try:
        found = _call(project, row, {"matching": words, "preview": True}, channel, sender)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    with_text = channel != "messaging" or _notices_text(cfg)
    if found.get("none"):
        return t("RM_FORGET_WORDS_NONE")
    if found.get("choose"):
        today = ops_reminders.now().date()
        lines = [f"#{r['id']} " + natural.describe(natural.info_of(r["due"][:10], r["due"][11:16], today), cfg) + (f": {r['text']}" if "text" in r else "") for r in found["choose"]]
        return "\n".join([t("RM_FORGET_WORDS_WHICH")] + lines)
    sentence, draft = natural.forget_question([found], cfg, with_text)
    drafts.put(*_slot(channel, sender), dict(draft, project=project_key(ctx["cfg"]["project"]), at=monotonic(), message_id=None), "remind")
    return sentence


def _notices_text(cfg: dict) -> bool:
    return ops_reminders._notices_text(cfg)


def _reminder_line(args: dict, when) -> str:
    """The line the reminders' engine reads for a reminder the interpreter chose: the moment first, as the typed /remind is written (review C2-f: BL7-4's deadline rule reads the moment before the words),
    and the words only when they are more than the trigger words ("me lembra" alone is no text: review C2-g, the words are asked)."""
    words = "" if natural.only_trigger(args.get("text", "")) else args.get("text", "")
    return f"{when or ''} {words}".strip()


def _plain_error(cfg: dict, e, channel):
    """The plain sentence of an error of the routed forget preview on a messaging app ("no reminder N waits for you"), or None: an error with a phone sentence of its own, a path or a problem of this
    machine keeps `_error`'s rules (review C2-e: never behind "error:")."""
    if channel == "messaging" and not getattr(e, "phone", None) and not (PATH.search(str(e)) or guard.find(str(e))):
        return phrases.localize(str(e), cfg)
    return None


def _ask_draft(ctx: dict, asked: dict, channel, sender, how: str, extras=None) -> str:
    """The reply to what the engine gave back for a router-chosen reminder: a question (kept for the sender's next line) or a refusal sentence."""
    cfg = ctx["cfg"]
    if "ask" not in asked:
        return phrases.text("NAT_NOT_BELIEVED", cfg)
    draft = asked["ask"]
    sentence, keep = natural.question(draft, cfg, channel != "messaging" or _notices_text(cfg), how)
    if keep:
        drafts.put(*_slot(channel, sender), dict(draft, project=project_key(ctx["cfg"]["project"]), at=monotonic(), message_id=None), "remind")
        if extras is not None and channel == "messaging" and draft.get("need") in ("confirm", "forget"):
            extras["ask_yes"] = True      # review C2-d: the bridge sends this question with the one-tap Yes button and binds it in the ledger, as it does for a typed /remind
    return sentence


def _complete(project: str, ctx: dict, draft: dict, answer, said: str, channel, sender, extras: dict) -> str:
    cfg = ctx["cfg"]
    where = "terminal" if channel == "chat" else channel      # the conversation's own shell is the terminal's equal (as in `run`)
    if draft.get("kind") == "which":
        refused = operations.refusal("ask", where, cfg["channels"], sender=sender)      # the policy again, now, as for any operation a line reaches
        if refused:
            return phone_refusal.said(refused, channel, cfg)
        text = draft["line"] + " @" + draft["ids"][answer - 1]
        return _ask(project, ctx, operations.by_name("ask"), text, channel, sender, extras, again=draft)
    # a question about a reminder, answered: the engine's rules decide (a yes makes it, a no keeps nothing, anything else is asked again or is a new line)
    extras["stored"] = phrases.text("NAT_PRIVATE_REPLY", cfg)
    name = "reminder-forget" if answer.get("forget") is not None else "remind"
    refused = operations.refusal(name, where, cfg["channels"], sender=sender)      # the policy again, now: the profile may have changed since the question
    if refused:
        return phone_refusal.said(refused, channel, cfg)
    text = channel != "messaging" or _notices_text(cfg)
    if answer.get("cancel"):
        return phrases.text("NT_KEPT" if answer.get("kept") else "NT_CANCELLED", cfg)
    try:
        if "forget" in answer:
            return "\n".join(natural.forgot_sentence(_call(project, operations.by_name("reminder-forget"), {"reminder_id": n}, channel, sender), cfg, text)
                             for n in answer["forget"])
        if "ask" in answer:
            return _ask_draft(ctx, answer, channel, sender, draft.get("how", "command"))
        made = _call(project, operations.by_name("remind"), {"when": answer["when"], "text": answer["text"]}, channel, sender)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    return natural.made_sentence(made, cfg, text)


# --- D: decisions, W: writes, G: gated ---------------------------------------------------------------------------------------------------------


def hand_over(project: str, ctx: dict, line: str, by_bridge: bool, sender, extras: dict) -> str:
    """S20: the typed line a command in words stands for, run as the person's typed line is. `extras["typed"]` carries it to the bridge, which answers it as it answers
    the typed line (`command_sentence` for a table command; the bridge's own handling of `/pending`, `/reject`, `/release`, `/add` and `/discard`). A command the table answers is
    called here exactly as `ops_say._say_command` calls it (its policy check, its refusal, its effect) and its reply is returned; one the bridge answers itself returns no reply
    and the bridge does the rest. The conversation keeps the typed line as the reply it stores for the second kind (a command and a number, nothing the person wrote)."""
    extras["typed"] = line
    if by_bridge:
        extras["stored"] = line
        return ""
    return _say()._say_command(project, ctx, line, "messaging", None, sender)[0]


def _typed(project: str, ctx: dict, name: str, args: dict, sender, extras: dict, row: dict):
    """The reply of a command that has a typed form (TYPED) or a routine's brake, on a messaging app; None for any other operation or a read that carries an argument the
    typed command has no word for (`/pending 5` is the list on a phone; "pending decision 5 whole" is the read)."""
    cfg = ctx["cfg"]
    if name == "routine-cancel":      # final: not done from words (the page, or the terminal's command, does it)
        return phrases.phone("PHONE_ROUTINE_CANCEL", cfg)
    if name in ROUTINE_BRAKES:
        number = args.get("routine_id")
        if number is None:
            return phrases.text("NAT_ASK_ID", cfg)
        try:
            _call(project, row, {"routine_id": number}, "messaging", sender)
        except core.OpsError as e:
            return _error(cfg, e, "messaging")
        return phrases.text(ROUTINE_BRAKES[name], cfg, n=number)
    found = TYPED.get(name)
    if found is None:
        return None
    template, parameter, by_bridge = found
    if parameter is None:
        return _stored_apart(hand_over(project, ctx, template, by_bridge, sender, extras), cfg, row, by_bridge, extras) if not args else None
    number = args.get(parameter)
    if number is None:
        return phrases.text("NAT_ASK_ID", cfg)
    return _stored_apart(hand_over(project, ctx, template.format(n=number), by_bridge, sender, extras), cfg, row, by_bridge, extras)


def _stored_apart(reply: str, cfg: dict, row: dict, by_bridge: bool, extras: dict) -> str:
    """The reply of a command the table answered, with the conversation keeping a neutral word when the MCP mode, which reads the conversation, is not a channel of the operation's row
    (limits L50 and L51: the list of the files people sent is shown where it was asked, as when it was asked by a read in words)."""
    if not by_bridge and "mcp" not in row["channels"]:
        extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    return reply


def _decision(project: str, ctx: dict, name: str, args: dict, channel, sender, extras: dict, said: str = "", when=None, routed: bool = False, confirmed: bool = False) -> str:
    """A decision named in words. `approve` is never made from words: on a messaging app the decision's card is sent again (S20: the sentence says so, and that the card is approved
    with its button or by the word that follows it); `reject` and `release` (the safe direction: nothing is sent, written or spent) are run by their typed lines (`hand_over`), so that
    the card the person was sent, the policy and the refusals are the typed command's own. A number that is not an open decision gets the one sentence NAT_NO_DECISION."""
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    number = args.get("pending_id")
    command = _command(ctx, name, args, channel, channel)
    if number is None and channel == "messaging" and name in ("approve", "reject", "release"):
        return t("NAT_WHICH_DECISION")
    if number is None or name == "go-ahead":
        return t("NAT_DECISION_TYPED", command=command) if command else phone_sentence(ctx, name)
    try:
        item = ops_facade.function("pending")(project, pending_id=number)
    except core.OpsError:
        item = None
    if item is None or item.get("status", "open") != "open":
        return t("NAT_NO_DECISION", id=number)      # the same sentence for one that does not exist and one that is closed: a sender learns nothing of another's decisions
    if channel == "messaging":
        if name in ("reject", "release"):
            if plan_confirm.needed(ctx, name, channel, sender, confirmed):      # D5: asked only about a decision that is open (above), never about one that does not exist or is closed
                return plan_confirm.ask(project, ctx, name, args, said, sender, extras, when=when, routed=routed, words=extras.get("plan_words"))
            return hand_over(project, ctx, TYPED[name][0].format(n=number), True, sender, extras)
        extras["resend"] = number      # the bridge sends the decision's card again, to this chat, under the rules of any card; it says so only when it did
        extras["resend_forced"] = True      # S20: the sentence says the card was sent again, so it is sent again whatever was sent before (the bridge's flood rule is for lines nobody asked twice)
        return t("NAT_DECISION_CARD", id=number)
    return t("NAT_DECISION_TYPED", command=command)


# What a phone is told of an operation that is not done from a line (limit L62): one plain sentence of the family the operation belongs to, and where it is done. The
# default is PHONE_ELSEWHERE; a test ties each name to an operation of the table.
PHONE_FAMILY = {
    "give-consent": "PHONE_SETTINGS", "set-mode": "PHONE_SETTINGS", "set-model": "PHONE_SETTINGS", "config": "PHONE_SETTINGS", "accept-config": "PHONE_SETTINGS",
    "approve-policy": "PHONE_SETTINGS", "revoke-policy": "PHONE_SETTINGS", "standing": "PHONE_SETTINGS", "execute-under-policy": "PHONE_SETTINGS",
    "instructions-set": "PHONE_INSTRUCTIONS", "instructions-add": "PHONE_INSTRUCTIONS",
    "source-add": "PHONE_SOURCES", "source-import": "PHONE_SOURCES", "source-refresh": "PHONE_SOURCES", "source-describe": "PHONE_SOURCES", "source-drive": "PHONE_SOURCES",
    "source-onedrive": "PHONE_SOURCES", "source-mail": "PHONE_SOURCES", "source-calendar": "PHONE_SOURCES", "stage-file": "PHONE_SOURCES", "sync": "PHONE_SOURCES",
    "hand-over": "PHONE_SOURCES", "attachment-hold": "PHONE_SOURCES",
    "routine-create": "PHONE_ROUTINES", "routine-change": "PHONE_ROUTINES", "routine-approve": "PHONE_ROUTINES", "routine-resume": "PHONE_ROUTINES",
    "routine-pause": "PHONE_ROUTINES", "routine-cancel": "PHONE_ROUTINES",
    "reminder-restore": "PHONE_RESTORE",
}
for _name in ("event-create", "event-change", "event-cancel", "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash",
              "file-create", "file-replace", "file-save", "file-trash", "todo-add", "todo-done"):
    PHONE_FAMILY[_name] = "PHONE_ACCOUNT_WRITE"


def phone_sentence(ctx: dict, name: str, retry: bool = False) -> str:
    """The one sentence a phone gets for an operation it cannot do from a line: what is done and where, in the project's language, with the page link when the project has
    one (`messaging.page_url`), else "on the platform's page". Never a command, a path or a hash (limit L62). `retry` is for a write to the person's accounts that a line
    named but the code did not read as a write: the person is asked to say it again, with an example, since a phone can ask it in words."""
    if retry and natural.class_of(name) == "E":      # a write the person can ask in words, named but not read as one: say it again, with an example
        return phrases.phone("PHONE_EVENT_AGAIN" if name.startswith("event-") else "PHONE_WRITE_AGAIN", ctx["cfg"])
    return phrases.phone(PHONE_FAMILY.get(name, "PHONE_ELSEWHERE"), ctx["cfg"])


def _gated(ctx: dict, name: str, args: dict, channel=None) -> str:
    cfg = ctx["cfg"]
    if channel == "messaging":
        return phone_sentence(ctx, name, retry=True)
    row = operations.by_name(name)
    where = ("NAT_PLACE_BOTH" if "terminal" in row["channels"] and "page" in row["channels"] else
             "NAT_PLACE_TERMINAL" if "terminal" in row["channels"] else "NAT_PLACE_PAGE")
    command = _command(ctx, name, args, "terminal", channel) if "terminal" in row["channels"] else None
    return phrases.text("NAT_GATED", cfg, place=phrases.text(where, cfg), command=f": {command}" if command else ".")


def _command(ctx: dict, name: str, args: dict, channel, carried=None) -> str:
    """The exact command of an operation: the line to send where the conversation has the command (a messaging app's own forms first), else the terminal's
    command, with `<name>` where the line gave no value. The one place that spells it is operations (chat_line, command_line). For the MCP mode (`carried`) the
    terminal's command is the relative form with `<project>`: a model client is never told a path of this machine."""
    row = operations.by_name(name)
    if carried == "messaging" and channel == "terminal":      # a phone is never given the terminal's command (limit L62): the caller says where it is done
        return None
    filled = dict(args)
    for arg in row["args"]:
        if arg.get("required") and arg["name"] not in filled:
            filled[arg["name"]] = f"<{arg['name']}>"
    if channel == "messaging" and name in BRIDGE_FORMS:
        return BRIDGE_FORMS[name].format(**{k: v for k, v in filled.items()})
    if "chat" in row["channels"] and channel != "terminal":
        try:
            return operations.chat_line(name, **filled)
        except ValueError:
            pass
    if carried == "messaging":      # no slash form of its own: none
        return None
    if "terminal" in row["channels"]:
        if carried == "mcp":
            return operations.command_line(name, "<project>", checkout=None, **filled)
        return operations.command_line(name, ctx["cfg"]["project"], checkout=core.ROOT, **filled)
    return "/" + name


# --- ask: the answer from sources ---------------------------------------------------------------------------------------------------------------


def keep_which(ctx: dict, channel, sender, line: str, out: dict) -> None:
    """When an `ask` answered with a list of files to choose from (refusal `which-source`), keep the question as this sender's draft: the next line that is
    the number of a file, or its id, asks it again about that file only. The typed /ask keeps it too (ops_say)."""
    if out.get("refusal") == "which-source" and out.get("candidates"):
        drafts.put(*_slot(channel, sender), {"kind": "which", "line": line, "ids": list(out["candidates"]), "project": project_key(ctx["cfg"]["project"])}, "ops",
                   ttl=DRAFT_TTL)


def _ask(project: str, ctx: dict, row: dict, line: str, channel, sender, extras: dict, again=None) -> str:
    """`ask` with the person's WHOLE line as the question (never a model's rewrite, never the router's `Sources:` line): the sources are chosen by code in
    the operation itself, and a mail or calendar snapshot only as it decides (ops_ask)."""
    cfg = ctx["cfg"]
    try:
        out = _call(project, row, {"text": line}, channel, sender)
    except core.RunBusy:
        if again is not None:      # the router answers another request: the choice is kept, not lost
            drafts.put(*_slot(channel, sender), again, "ops", ttl=DRAFT_TTL)
        return phrases.text("RUN_BUSY", cfg)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    keep_which(ctx, channel, sender, line, out)
    if out.get("run_id") is not None:
        extras["run_id"] = out["run_id"]      # the answer is stored with its run and no request: only the asker reads it back (limit L50)
    return out["reply"]


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
