#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The one dispatcher of the natural requests (package NR-2): it executes what a tier chose, checked exactly as the typed command is.

A line in the person's own words reaches an operation by two ways: a tier-1 form (runtime/natural.py `match`: code, no model) or the router's
`Route: none (operation)` outcome (runtime/router.py, read and believed by code against the line). Whichever chose, THIS file executes, and the order is
fixed (contracts/runtime.md, "Natural requests", limit L54):

  1. The operation has a row of runtime/natural.py and a class; a planned effect (class E, not built) answers "not built yet (planned)" and runs nothing.
  2. The operation's row lists the channel that carries the line (else the typed command's sentence), and `operations.refusal(op, channel, policy,
     sender=sender)` has no refusal: the sentence the typed command gets, and no call. A decision (D) asks it for the operation AND for `pending`.
  3. By class: R is called with the channel and sender as `_say_command` calls it and its result is written by code; N (a reminder) is made, or asks
     first when its time came from the router (a draft in this process's memory); W and G run nothing (the reply is the exact command and the place);
     D decides nothing (the reply points to the card, which the messaging bridge sends again); `ask` is called with the person's WHOLE line.
  4. Every argument is a number written in the line, a piece of it, a span of it or, for a time, the router's `When:` slot, which no code can check
     against the line: an operation that receives one is NEVER executed at once, it asks for a one-line confirmation, exactly like a tier-2 pick.

Drafts (one per project, channel and sender, ten minutes, lost on restart, never logged, never in the store): a reminder that waits for its "yes", and
the question that waits for the choice of a file. The next line of that sender that answers the draft completes it; any other line drops the draft and is
handled as new. A reminder's words are in the draft and in the `reminders` table once made, and nowhere else (limit L51): the conversation stores a
neutral word for the line and the reply (`stored`).

Sibling of runtime/ops_say.py, which calls `peek` and `take`; it reaches ops.py and ops_say.py at call time, never at import. Standard library
only. Runs on Python 3.9: python3 runtime/ops_natural.py --help
"""
from __future__ import annotations

import importlib
import inspect
import re
import sys
import threading
import time
import unicodedata

import ops_core as core
import natural
import operations
import ops_actor
import phrases

DRAFT_TTL = 600.0            # seconds a draft waits for its answer (this spec's choice, not measured)
DRAFTS_MAX = 50              # drafts in memory: the oldest goes first
RENDER_MAX = 1800            # characters of a read written for a messaging app
RENDER_LONG = 6000           # ... and for any other channel
LIST_MAX = 12                # rows of a list a read writes
FIELD_MAX = 120              # characters of one value in a row
monotonic = time.monotonic   # a test replaces it
YES = frozenset(("yes", "y", "ok", "okay", "sure", "confirm", "sim", "s", "claro", "confirma", "confirmo", "pode", "si", "oui", "ja", "да", "はい", "是", "네"))  # validate: allow english-only -- the closed list of words that confirm, in several languages
NO = frozenset(("no", "n", "cancel", "nope", "nao", "cancela", "non", "nein", "нет", "いいえ", "否", "아니요"))  # validate: allow english-only -- the closed list of words that decline, in several languages
BRIDGE_FORMS = {"attachment-add": "/add {attachment_id}", "attachment-discard": "/discard {attachment_id}"}   # the commands a messaging app has for these
_DRAFTS = {}
_LOCK = threading.Lock()
PATH = re.compile(r"(?:^|[\s'\"(])(?:/[\w.-]+/|~/|[A-Za-z]:\\)[^\s]*")      # a path of this machine, not a typed command such as /approve 12


def _ops():
    return importlib.import_module("ops")


def _say():
    return importlib.import_module("ops_say")


# --- the drafts --------------------------------------------------------------------------------------------------------------------------------


def _key(ctx: dict, channel, sender) -> tuple:
    return (ctx["cfg"]["project"], channel or "chat", sender or "")


def _put(key: tuple, draft: dict) -> None:
    with _LOCK:
        now = monotonic()
        for old in [k for k, d in _DRAFTS.items() if d["expires"] <= now]:
            del _DRAFTS[old]
        while len(_DRAFTS) >= DRAFTS_MAX:
            del _DRAFTS[min(_DRAFTS, key=lambda k: _DRAFTS[k]["expires"])]
        _DRAFTS[key] = dict(draft, expires=now + DRAFT_TTL)


def _live(key: tuple):
    with _LOCK:
        draft = _DRAFTS.get(key)
        return draft if draft is not None and draft["expires"] > monotonic() else None


def _pop(key: tuple):
    with _LOCK:
        draft = _DRAFTS.pop(key, None)
    return draft if draft is not None and draft["expires"] > monotonic() else None


def forget_all() -> None:
    """Drop every draft (a test, and a process that stops)."""
    with _LOCK:
        _DRAFTS.clear()


def _word(said: str) -> str:
    return natural.normal(said)


def _answers(draft: dict, said: str):
    """What a line says to a draft: "yes", "no", an integer (the choice among the listed files) or None for a line that is not an answer."""
    word = _word(said)
    if draft["kind"] == "confirm":
        return "yes" if word in YES else ("no" if word in NO else None)
    if draft["kind"] == "which":
        digits = unicodedata.normalize("NFKC", word)
        if digits.isdigit() and 1 <= int(digits) <= len(draft["ids"]):
            return int(digits)
        listed = [natural.normal(i) for i in draft["ids"]]      # an id is written with hyphens; the line is compared as every line is
        return listed.index(word) + 1 if word in listed else None
    return None


def peek(ctx: dict, said: str, channel, sender) -> bool:
    """Whether a plain line is handled here: a tier-1 form, or the answer to this sender's live draft. Reads, changes nothing."""
    if natural.match(said) is not None:
        return True
    draft = _live(_key(ctx, channel, sender))
    return draft is not None and _answers(draft, said) is not None


def stored_line(ctx: dict, said: str) -> str:
    """The text the conversation stores for the person's line: the line, but a neutral word for the words of a reminder (limit L51)."""
    return phrases.text("NAT_PRIVATE_LINE", ctx["cfg"]) if natural.private(said) else said


def is_placeholder(text) -> bool:
    return isinstance(text, str) and text in phrases.every("NAT_PRIVATE_LINE") + phrases.every("NAT_PRIVATE_REPLY")


# --- the entry points --------------------------------------------------------------------------------------------------------------------------


def take(project: str, ctx: dict, said: str, channel, sender, extras: dict):
    """The reply of a plain line handled here, or None when it is not (the draft of this sender, if any, is dropped: any other line is new).
    `channel` is the carrying channel (the queue's drain already acts as the page). Fills `extras` with `stored` (the text the conversation keeps for
    the reply), `resend` (the decision whose card the bridge sends again) and `run_id` (the answer run an `ask` made)."""
    key = _key(ctx, channel, sender)
    draft = _pop(key)
    if draft is not None:
        answer = _answers(draft, said)
        if answer is not None:
            return _complete(project, ctx, draft, answer, channel, sender, extras)
    found = natural.match(said)
    if found is None:
        return None
    return run(project, ctx, found["op"], found["args"], said, channel, sender, extras)


def run(project: str, ctx: dict, name: str, args: dict, said: str, channel, sender, extras: dict, when=None) -> str:
    """Execute one operation chosen by a tier, and return the reply (see the module's text for the order). `args` are the arguments natural.py checked:
    {parameter: value}; `when` is the router's normalised time, which makes an N operation ask first."""
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    cls = natural.class_of(name)
    if cls is None:
        return f"error: {name} is not an operation of the table of natural requests"
    if name in natural.PLANNED:
        return t("NAT_PLANNED", what=t("NAT_E_" + name.upper().replace("-", "_")))
    if name == "commands":      # the help is public: what can be asked, never a read of the project
        return t("HELP") if channel == "messaging" else operations.chat_help()
    row = operations.by_name(name)
    if channel not in row["channels"]:
        extra = _command(ctx, name, args, "terminal") if cls == "G" else None
        return f"error: /{name} is done in the terminal or on the page" + (f". {extra}" if extra else "")
    policy = cfg["channels"]
    refused = operations.refusal(name, channel, policy, sender=sender)
    if refused:
        return f"error: {refused}"
    if cls == "D":
        refused = operations.refusal("pending", channel, policy, sender=sender)
        if refused:
            return f"error: {refused}"
    if cls == "R":
        return _read(project, ctx, name, row, args, channel, sender)
    if cls == "N":
        return _notice(project, ctx, name, row, args, said, channel, sender, extras, when)
    if cls == "W":
        return t("NAT_TYPE_IT", command=_command(ctx, name, args, channel))
    if cls == "D":
        return _decision(project, ctx, name, args, channel, sender, extras)
    if cls == "G":
        return _gated(ctx, name, args)
    if name == "ask":
        return _ask(project, ctx, row, said, channel, sender, extras)
    return f"error: {name} is not reached from a line"


def run_routed(project: str, ctx: dict, operation: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply for an operation the router named (router.read_route kind `operation`, already believed against the person's line): the dispatcher
    believes it against the line AGAIN, with the line the request holds, and executes it. A router-normalised time makes the reply a question."""
    checked = natural.check_operation(operation.get("name"), _slots_of(operation), operation.get("when"), said)
    if not checked["ok"]:
        return phrases.text("NAT_NOT_BELIEVED", ctx["cfg"])
    return run(project, ctx, checked["name"], checked["args"], said, channel, sender, extras, when=checked["when"])


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
    try:
        out = _call(project, row, args, channel, sender)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    return _clip(_render(name, out, cfg, channel), channel)


def _error(cfg: dict, error, channel) -> str:
    """An error of the operations layer as a person is told: its message in the project's language where a table has it; on a messaging app a message with a path
    in it, or a problem of this machine, is a fixed sentence."""
    text = str(error)
    if channel == "messaging" and (PATH.search(text) or getattr(error, "code", 1) == 3):
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
        if _scalar(value):
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


def _notice(project: str, ctx: dict, name: str, row: dict, args: dict, said: str, channel, sender, extras: dict, when) -> str:
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    if name == "remind":
        extras["stored"] = t("NAT_PRIVATE_REPLY")
        if channel != "messaging":      # a reminder is sent to a chat of a messaging app: elsewhere it is the terminal's command, which names the listed sender
            return t("NAT_TYPE_IT", command=_command(ctx, name, dict(args, to="<platform:id>", **({"when": when} if when else {})), "terminal"))
    if name == "reminder-forget":
        if _missing(row, args):
            return t("NAT_ASK_ID")
        try:
            done = _call(project, row, args, channel, sender)
        except core.OpsError as e:
            return _error(cfg, e, channel)
        return phrases.localize(done["reply"], cfg)
    text = args.get("text")
    if not text:
        return t("NAT_ASK_TEXT")
    if when is None:
        return t("NAT_ASK_WHEN")
    reminders = importlib.import_module("ops_reminders")
    rm = importlib.import_module("reminders")
    try:
        words = rm.clean_text(text)
        clock = reminders.now()
        found = rm.resolve(when, clock, reminders.local_at, reminders.local_of)
    except ValueError as e:
        return _error(cfg, core.OpsError(str(e), 2), channel)
    # the router's time cannot be checked against the line by code: the person confirms it, in a human date, before anything is made
    _put(_key(ctx, channel, sender), {"kind": "confirm", "when": when, "text": words})
    shown = f": {words}" if reminders._notices_text(cfg) else ""
    return t("NAT_CONFIRM_REMIND", when=_human(found["due"], clock, cfg), words=shown)


def _human(due, clock, cfg: dict) -> str:
    """The reading of a moment for a person, in the project's language: relative word first (today, tomorrow), the weekday, the date and the time."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    days = t("NAT_WEEKDAYS").split(",")
    delta = (due.date() - clock.date()).days
    head = f"{t('NAT_TODAY')}, " if delta == 0 else (f"{t('NAT_TOMORROW')}, " if delta == 1 else "")
    day = f"{days[due.weekday()]} {due.day:02d}/{due.month:02d}"
    return f"{head}{day}{',' if head else ''} {t('NAT_AT')} {due.hour:02d}:{due.minute:02d}"


def _complete(project: str, ctx: dict, draft: dict, answer, channel, sender, extras: dict) -> str:
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    if draft["kind"] == "which":
        refused = operations.refusal("ask", channel, cfg["channels"], sender=sender)      # the policy again, now, as for any operation a line reaches
        if refused:
            return f"error: {refused}"
        text = draft["line"] + " @" + draft["ids"][answer - 1]
        return _ask(project, ctx, operations.by_name("ask"), text, channel, sender, extras)
    extras["stored"] = t("NAT_PRIVATE_REPLY")
    if answer == "no":
        return t("NAT_DROPPED")
    row = operations.by_name("remind")
    refused = operations.refusal("remind", channel, cfg["channels"], sender=sender)      # the policy again, now: the profile may have changed since the question
    if refused:
        return f"error: {refused}"
    try:
        done = _call(project, row, {"when": draft["when"], "text": draft["text"]}, channel, sender)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    return phrases.localize(done["reply"], cfg)


# --- D: decisions, W: writes, G: gated ---------------------------------------------------------------------------------------------------------


def _decision(project: str, ctx: dict, name: str, args: dict, channel, sender, extras: dict) -> str:
    cfg = ctx["cfg"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    number = args.get("pending_id")
    command = _command(ctx, name, args, channel)
    if number is None or name == "go-ahead":
        return t("NAT_DECISION_TYPED", command=command)
    try:
        item = _ops().pending(project, pending_id=number)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    if item.get("status", "open") != "open":
        return t("NOT_OPEN", number=number, status=phrases.status(item.get("status"), cfg))
    if channel == "messaging":
        extras["resend"] = number      # the bridge sends the decision's card again, to this chat, under the rules of any card
        return t("NAT_DECISION_CARD", id=number)
    return t("NAT_DECISION_TYPED", command=command)


def _gated(ctx: dict, name: str, args: dict) -> str:
    cfg = ctx["cfg"]
    row = operations.by_name(name)
    where = ("NAT_PLACE_BOTH" if "terminal" in row["channels"] and "page" in row["channels"] else
             "NAT_PLACE_TERMINAL" if "terminal" in row["channels"] else "NAT_PLACE_PAGE")
    command = _command(ctx, name, args, "terminal") if "terminal" in row["channels"] else None
    return phrases.text("NAT_GATED", cfg, place=phrases.text(where, cfg), command=f": {command}" if command else ".")


def _command(ctx: dict, name: str, args: dict, channel) -> str:
    """The exact command of an operation: the line to send where the conversation has the command (a messaging app's own forms first), else the terminal's
    command, with `<name>` where the line gave no value. The one place that spells it is operations (chat_line, command_line)."""
    row = operations.by_name(name)
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
    if "terminal" in row["channels"]:
        return operations.command_line(name, ctx["cfg"]["project"], checkout=core.ROOT, **filled)
    return "/" + name


# --- ask: the answer from sources ---------------------------------------------------------------------------------------------------------------


def keep_which(ctx: dict, channel, sender, line: str, out: dict) -> None:
    """When an `ask` answered with a list of files to choose from (refusal `which-source`), keep the question as this sender's draft: the next line that is
    the number of a file, or its id, asks it again about that file only. The typed /ask keeps it too (ops_say)."""
    if out.get("refusal") == "which-source" and out.get("candidates"):
        _put(_key(ctx, channel, sender), {"kind": "which", "line": line, "ids": list(out["candidates"])})


def _ask(project: str, ctx: dict, row: dict, line: str, channel, sender, extras: dict) -> str:
    """`ask` with the person's WHOLE line as the question (never a model's rewrite, never the router's `Sources:` line): the sources are chosen by code in
    the operation itself, and a mail or calendar snapshot only as it decides (ops_ask)."""
    cfg = ctx["cfg"]
    try:
        out = _call(project, row, {"text": line}, channel, sender)
    except core.OpsError as e:
        return _error(cfg, e, channel)
    keep_which(ctx, channel, sender, line, out)
    if out.get("run_id") is not None:
        extras["run_id"] = out["run_id"]      # the answer is stored with its run and no request: only the asker reads it back (limit L50)
    return out["reply"]


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
