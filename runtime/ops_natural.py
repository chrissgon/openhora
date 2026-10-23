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
  3. By class: R is called with the channel and sender as `_say_command` calls it and its result is written by code; N (a reminder) is asked first when the
     router chose it (below); W runs nothing (the reply is the exact command to send); D decides nothing (the reply points to the card, which the messaging
     bridge sends again); E and G run nothing (the reply is the exact operation or command and the place: an E operation ends in a card the person approves);
     `ask` is called with the person's WHOLE line.
  4. Every argument is a number written in the line, a piece of it, a span of it or, for a time, the router's `When:` slot, which no code can check
     against the line: an operation that receives one is NEVER executed at once.

What the router chose and no code can check against the line (a reminder in a language no table knows, a reminder to forget) is not done: it is SHOWN and
confirmed, by the rules of the reminders' own conversation (runtime/natural.py: a reminder in free text is made only after a yes to the full reading shown,
a pick is never a yes, and the moment shown is the moment made). The question is a draft in the one store of drafts (runtime/drafts.py, memory only, ten
minutes, one per channel and sender, never logged, never in the store), where the messaging bridge's own questions wait too. The same store holds the
choice of a file for a question to `ask`. The next line of that sender that answers the draft completes it; any other line drops the draft and is handled as
new. A reminder's words are in the draft and in the `reminders` table once made, and nowhere else (limit L51): the conversation stores a neutral word.

Sibling of runtime/ops_say.py, which calls `peek` and `take`; it reaches ops.py and ops_say.py at call time, never at import. Standard library
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
import line_stage
import messaging_guard as guard
import ops_core as core
import natural
import operations
import ops_actor
import phone_errors
import phone_refusal
import phrases

DRAFT_TTL = drafts.TTL       # seconds a question waits for its answer (this spec's choice, not measured)
RENDER_MAX = 1800            # characters of a read written for a messaging app
RENDER_LONG = 6000           # ... and for any other channel
LIST_MAX = 12                # rows of a list a read writes
FIELD_MAX = 120              # characters of one value in a row
monotonic = time.monotonic   # the clock of a question's age (a test replaces it)
BRIDGE_FORMS = {"attachment-add": "/add {attachment_id}", "attachment-discard": "/discard {attachment_id}"}   # the commands a messaging app has for these
PATH = re.compile(r"(?:^|[\s'\"(])(?:/[\w.-]+/|~/|[A-Za-z]:\\)[^\s]*")      # a path of this machine, not a typed command such as /approve 12


def _ops():
    return importlib.import_module("ops")


def natural_writes():
    return importlib.import_module("natural_writes")


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
    return importlib.import_module("ops_reminders").now()


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
    return natural.complete(draft, said, _clock())


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


def peek(ctx: dict, said: str, channel, sender) -> bool:
    """Whether a plain line is handled here: a tier-1 form, or the answer to this sender's live draft. Reads, changes nothing."""
    if natural.match(said) is not None:
        return True
    slot = _slot(channel, sender)
    draft = _live(slot)
    if draft is not None and _owner(draft) == "write":
        return channel != "mcp" and _writes().answers(ctx, draft, said)
    if channel != "mcp" and natural_writes().candidate(said) is not None:      # a write form (package NR-5): code, no model, no route lock
        return True
    if draft is None:
        return False
    owner = _owner(draft)
    return drafts.get(*slot, owner) is not None and _answers(ctx, draft, said, owner) is not None


def recognises(ctx: dict, said: str, channel, sender) -> bool:
    """Whether a plain line is a request of its own that code recognises: any tier-1 form (a list or any other read included, S4b), a reminder, a write to the person's accounts (a
    save of a file included), or the answer to this sender's live draft. Such a line is NEW, never the answer to a question the router left open (package LIVE-2, slice S4b);
    only a question about the state ("progress"), a plain sentence and a reply to the question's own message may be the answer. Reads, changes nothing."""
    return peek(ctx, said, channel, sender) or natural.candidate(said) is not None


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
    written = natural_writes().candidate(said) if channel != "mcp" else None
    if written is not None:      # a write form needs the group of its operation, never `talk` (package NR-5)
        return written["op"] if channel in operations.by_name(written["op"])["channels"] else None
    group = natural.needs(said)
    if group is not None and channel in operations.by_name(group)["channels"]:
        return group
    return None


def stored_line(ctx: dict, said: str, channel=None, sender=None) -> str:
    """The text the conversation stores for the person's line: the line, but a neutral word for the words of a reminder (limit L51) and for a line that asks for a write to the
    person's accounts or answers the question of one (limit L61)."""
    if channel is not None or sender is not None:
        draft = drafts.get(*_slot(channel, sender), "write")
        if draft is not None:
            return phrases.text("NW_PRIVATE_LINE", ctx["cfg"])
    if natural_writes().candidate(said) is not None:
        return phrases.text("NW_PRIVATE_LINE", ctx["cfg"])
    return phrases.text("NAT_PRIVATE_LINE", ctx["cfg"]) if natural.private(said) else said


PRIVATE_READS = ("pending", "task")      # the reads that draw a decision's card or a task's pending list: the private lines of a card are drawn for a holder of ask-mail


def keeps_private(ctx: dict, name, channel, sender) -> bool:
    """Whether the reply of this read, drawn for THIS sender, may hold lines that only a holder of `ask-mail` reads (the recipient, the subject, the text of a mail or
    an event): such a reply goes to the chat that asked and the conversation, which the MCP mode reads, keeps a neutral word (limit L51), typed command or words."""
    return channel == "messaging" and name in PRIVATE_READS and bool(sender) and importlib.import_module("item_refs").may_read(ctx, "messaging", sender)


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


def take(project: str, ctx: dict, said: str, channel, sender, extras: dict):
    """The reply of a plain line handled here, or None when it is not (the draft of this sender, if any, is dropped: any other line is new).
    `channel` is the carrying channel (the queue's drain already acts as the page). Fills `extras` with `stored` (the text the conversation keeps for
    the reply), `resend` (the decision whose card the bridge sends again) and `run_id` (the answer run an `ask` made)."""
    slot = _slot(channel, sender)
    draft = _live(slot)
    if draft is not None:
        owner = _owner(draft)
        if owner == "write":      # a question about a write to the person's accounts (package NR-5): the answer, or the draft is dropped and the line is new
            reply = _writes().answer(project, ctx, draft, said, channel, sender, extras) if channel != "mcp" else None
            if reply is not None:
                return reply
            extras["discarded"] = True
        else:
            answer = _answers(ctx, draft, said, owner)
            drafts.drop(*slot)
            if answer is not None:
                return _complete(project, ctx, draft, answer, said, channel, sender, extras)
            extras["discarded"] = True          # a question this line asks (a write's, NR-5) says the previous one was discarded
    if channel == "messaging":      # S11: a number after a list of events ("cancela o 2", "o 2") means that entry, as "cancela o evento 2" does (runtime/event_lookup.py)
        listed = importlib.import_module("event_lookup").take(project, ctx, said, sender, extras, _writes(), _clock())
        if listed is not None:
            return listed
        picked = importlib.import_module("ops_file_read").take(project, ctx, said, channel, sender, extras)      # S17: a number after a list of files ("o 2") picks that file
        if picked is not None:
            return picked
    if channel != "mcp":      # a write form opens the card of its exact content (limit L61), never a write
        opened = _writes().open_line(project, ctx, said, channel, sender, extras)
        if opened is not None:
            return opened
    found = natural.match(said)
    if found is None:
        return None
    return run(project, ctx, found["op"], found["args"], said, channel, sender, extras)


def run(project: str, ctx: dict, name: str, args: dict, said: str, channel, sender, extras: dict, when=None, routed: bool = False) -> str:
    """Execute one operation chosen by a tier, and return the reply (see the module's text for the order). `args` are the arguments natural.py checked:
    {parameter: value}; `when` is the router's normalised time; `routed` says the router chose the operation: a notice or an own write it chose (a time
    it normalised, a reminder to forget) always asks first, because no code can check the choice against the line."""
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
    if name == "file-read":      # S8: the text of a file found by its name; code writes the reply and the conversation keeps a neutral word (runtime/ops_file_read.py)
        return importlib.import_module("ops_file_read").reply(project, ctx, args, said, channel, sender, extras)
    if name == "research":      # R2-F1: a question of general information answered by a web search; code runs the research skill, writes the reply and the conversation keeps a neutral word (runtime/ops_research.py)
        return importlib.import_module("ops_research").reply(project, ctx, args, said, channel, sender, extras)
    if cls == "R":
        if "mcp" not in row["channels"] or keeps_private(ctx, name, channel, sender):      # the MCP mode reads the conversation: what it could not read itself (reminders, files people sent, the private lines of a card drawn for a holder of ask-mail) is stored as a neutral word (limits L50, L51)
            extras["stored"] = t("NAT_READ_REPLY")
        return _read(project, ctx, name, row, dict(args, kind=natural_writes().items_kind(said), **importlib.import_module("ops_items")._line_args(said)) if name == "items" else args, channel, sender)      # NR-5: the noun of the line says which items; S15: an account it names narrows them
    if cls == "N":
        return _notice(project, ctx, name, row, args, said, channel, sender, extras, when, routed)
    if cls == "W":
        command = _command(ctx, name, args, channel, channel)
        return t("NAT_TYPE_IT", command=command) if command else phone_sentence(ctx, name)
    if cls == "D":
        return _decision(project, ctx, name, args, channel, sender, extras)
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
    function = getattr(_ops(), row["call"])
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
    if name == "items":      # S15: with nothing to list, the reply says what to add and where (a phone: no command)
        return _clip(importlib.import_module("ops_items").reply(project, ctx, out, channel), channel)
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
        return importlib.import_module("ops_items").render(out, cfg)
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
        line = f"{args.get('text', '')} {when or ''}".strip()
        try:
            asked = _call(project, row, {"said": line, "how": "command"}, channel, sender)
        except core.OpsError as e:
            return _error(cfg, e, channel)
        return _ask_draft(ctx, asked, channel, sender, "command")
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
        return _error(cfg, e, channel)
    sentence, draft = natural.forget_question([shown], cfg, channel != "messaging" or _notices_text(cfg))
    extras["stored"] = t("NAT_PRIVATE_REPLY")      # the question shows the reminder's words: the conversation keeps a neutral word (limit L51)
    drafts.put(*_slot(channel, sender), dict(draft, project=project_key(ctx["cfg"]["project"]), at=monotonic(), message_id=None), "remind")
    return sentence


def _notices_text(cfg: dict) -> bool:
    return importlib.import_module("ops_reminders")._notices_text(cfg)


def _ask_draft(ctx: dict, asked: dict, channel, sender, how: str) -> str:
    """The reply to what the engine gave back for a router-chosen reminder: a question (kept for the sender's next line) or a refusal sentence."""
    cfg = ctx["cfg"]
    if "ask" not in asked:
        return phrases.text("NAT_NOT_BELIEVED", cfg)
    draft = asked["ask"]
    sentence, keep = natural.question(draft, cfg, channel != "messaging" or _notices_text(cfg), how)
    if keep:
        drafts.put(*_slot(channel, sender), dict(draft, project=project_key(ctx["cfg"]["project"]), at=monotonic(), message_id=None), "remind")
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


def _decision(project: str, ctx: dict, name: str, args: dict, channel, sender, extras: dict) -> str:
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    number = args.get("pending_id")
    command = _command(ctx, name, args, channel, channel)
    if number is None or name == "go-ahead":
        return t("NAT_DECISION_TYPED", command=command) if command else phone_sentence(ctx, name)
    try:
        item = _ops().pending(project, pending_id=number)
    except core.OpsError:
        item = None
    if item is None or item.get("status", "open") != "open":
        return t("NAT_NO_DECISION", id=number)      # the same sentence for one that does not exist and one that is closed: a sender learns nothing of another's decisions
    if channel == "messaging":
        extras["resend"] = number      # the bridge sends the decision's card again, to this chat, under the rules of any card; it says so only when it did
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
              "file-create", "file-replace", "file-save"):
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
