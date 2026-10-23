#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The person's standing instructions in the operations layer: the three operations over the file, the block a run's prompt
receives, the check a routine's task makes, and the proposal that follows an answer (runtime/instructions.py holds the file
and its checks).

A sibling of runtime/ops.py, which exposes `instructions_read`, `instructions_set`, `instructions_add` and
`answer_proposing` under their names; no shell imports this file. An operation that stays in runtime/ops.py is reached at
call time, never imported at module level.

  instructions   (read, with the terminal, the page, the MCP mode and messaging) the path, whether the file is there, its
                 sha256, its characters, the cap, the problem if any, and the text. It writes nothing.
  instructions-set / instructions-add   (group `instructions-write`, the terminal and the page only: operations.INSTRUCTIONS_CHANNELS,
                 by default, and no policy of today widens it; limit L40) replace the whole text, or append one line `- <text>`. No model
                 call, an atomic write (a temporary file, then os.replace) under the project's write lock, and a
                 compare-and-set on the sha256 of the file the person read (`none` for a file that was not there): a file
                 changed meanwhile, by hand or by the other operation, is never overwritten.
  answer         the proposal. The `answer` row calls `answer_proposing`: the answer is recorded as ever, and an answer to a
                 question may end with one proposal to add the person's own line to the instructions, on the channels that show the
                 whole result (DISPLAYS), and through `say` on every channel but a messaging app, where an answer is never proposed
                 (NO_PROPOSAL_CHANNELS; the request's one proposal is not spent). Its sentences are the phrase table's, in the project's
                 language (INSTR_PROPOSAL_ASK, INSTR_WHERE_SAYS, INSTR_WHERE_ELSEWHERE); the line and the command are not changed. The proposal is made
                 by code: no model, no word list. It is offered only when the line is the person's own stored text (the
                 line they typed; never a model's reply, a source, a document of the mirror, an e-mail, a ticket or a
                 notification), one line of 20 to 300 characters, passes the checks of the file together with the file as
                 it is, is not a line of the file, and no proposal was made for this request. Only `instructions-add`
                 writes it, and only from the terminal or the page.
  prompts        `guard` (a task run), `for_run` (the router's run) and `contained_prompt` (a contained run) give the block of
                 a run, or the sentence that refuses it: a run does not start without the instructions the person wrote.
                 `guard` also compares, for a task of a routine's fire, the file's sha256 with the one the routine was
                 approved with.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import importlib
import os
import re
import sys

import ops_core as core
import instructions as standing
import operations
import phrases

PROPOSAL_MIN = 20          # characters: an answer shorter than this is a choice ("yes", "the second one"), not a standing rule
PROPOSAL_MAX = 300         # characters of the one line a proposal offers
PROPOSED = "instructions:proposed:"      # the store's cursor <this><request id>: a proposal was made for the request
PROPOSAL_ASK = phrases.en("INSTR_PROPOSAL_ASK")      # the English sentences; the proposal says them in the project's language (runtime/phrases.py)
# Where a proposal is shown to the person: the terminal and the conversation print the whole result of an answer, MCP returns it to its client,
# and `say` shows it in the reply on every channel that is not a messaging app. The page's inbox and a messaging app's reply to a card show "Answered #N."
# and nothing of the result, so an answer through them proposes nothing and spends no request's one proposal where it would not be seen. A line typed on
# a messaging app is never proposed either (NO_PROPOSAL_CHANNELS): the file is written from the terminal or the page, the person is on a phone, and the
# proposal's text is a command with a path and a hash.
DISPLAYS = ("terminal", "chat", "mcp")
NO_PROPOSAL_CHANNELS = ("messaging",)
WHERE_SAYS = phrases.en("INSTR_WHERE_SAYS")
WHERE_ELSEWHERE = phrases.en("INSTR_WHERE_ELSEWHERE")
BASE = re.compile(r"none|[0-9a-f]{64}")
NOT_HERE = "the standing instructions are written from the terminal or from the page, by default, and no channel policy widens it yet (limit L40)"
ROUTINE_CHANGED = ("the project's instructions changed after the routine {name} was approved: approve the routine again "
                   "(routine-approve --id {id}; the preview names the project's instructions)")


def _ops():
    return importlib.import_module("ops")


# --- what a run's prompt receives ---------------------------------------------------------------------------------------------


def for_run(project: str) -> tuple:
    """(block, why): the block of the project's standing instructions for a run's prompt ("" when the file is absent or blank),
    or ("", the sentence) when the file fails a check; the run does not start then."""
    try:
        return standing.block(project), None
    except standing.Refused as e:
        return "", str(e)


def _routine_of(ctx: dict, task):
    """The routine whose fire made the request a task belongs to, or None (a store that cannot say is not a routine's, as in ops_models)."""
    try:
        return importlib.import_module("ops_routines").routine_of_task(ctx, task)
    except Exception:
        return None


def guard(ctx: dict, task: dict) -> str:
    """The block for a task run's prompt, read once at the run's start, or OpsError (code 3) with the sentence: the file fails a
    check, or the task belongs to a routine whose approved content names other instructions than the file holds now (the
    routine's hash covers the file; the gap between the fire and the run is closed here). The routine's tasks of a project with
    no file are not touched: no file is the value the old approvals hold."""
    project = ctx["cfg"]["project"]
    found = standing.state(project)
    if found["problem"]:
        raise core.OpsError(found["problem"], 3)
    mine = _routine_of(ctx, task)
    if mine is not None and (mine.get("approved_content") or {}).get("instructions") != found["sha256"]:
        raise core.OpsError(ROUTINE_CHANGED.format(name=mine["name"], id=mine["id"]), 3)
    return standing.block(project, found)


def contained_prompt(project: str, prompt: str) -> str:
    """The prompt of a contained run (a handler's agent run) with the block appended after the caller's text, or the prompt as it is
    when the project has no instructions; OpsError (code 3) with the sentence when the file fails a check."""
    held, why = for_run(project)
    if why:
        raise core.OpsError(why, 3)
    return prompt.rstrip("\n") + "\n\n" + held + "\n" if held else prompt


def hash_of(project: str):
    """The sha256 of the file's bytes for a routine's content, or None when there is no file (the content then has no key)."""
    return standing.state(project)["sha256"]


# --- the operations -------------------------------------------------------------------------------------------------------


def instructions_read(project: str) -> dict:
    """The operation `instructions`: {"path", "present", "sha256", "characters", "cap", "problem", "text"} (runtime/instructions.py state)."""
    return standing.state(core.context(project)["cfg"]["project"])


def _base(value) -> str:
    base = str(value or "").strip().lower()
    if not BASE.fullmatch(base):
        raise core.OpsError("base_sha256 is the sha256 of the file you read, or the word none for a file that was not there", 2)
    return base


def _write(ctx: dict, channel, base, make) -> dict:
    """The one writer of the file. make(current text) gives the new text. Refused: a channel outside INSTRUCTIONS_CHANNELS, a file
    that changed since it was read, a path that is a link or leaves the project, a text that fails a check. Atomic."""
    if channel not in operations.INSTRUCTIONS_CHANNELS:
        raise core.OpsError(NOT_HERE, 1)
    base = _base(base)
    project = ctx["cfg"]["project"]
    target = os.path.join(project, *standing.PATH.split("/"))
    with core._write_lock(ctx["cfg"]):
        found = standing.read(project)
        if found["present"] and found["data"] is None:
            raise core.OpsError(found["problem"] or standing.sentence("cannot be read"), 1)
        current = standing.sha256(found["data"]) if found["present"] else None
        if (current or "none") != base:
            raise core.OpsError(f"{standing.PATH} changed since you read it (its sha256 is now {current or 'none'}, not {base}): "
                                "read it again and repeat the change; nothing was written", 1)
        text = make(found["data"].decode("utf-8", errors="replace") if found["present"] else "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.rstrip("\n") + "\n" if text.strip() else ""
        why = standing.check(text)
        if why:
            raise core.OpsError(why, 2)
        folder, root = os.path.dirname(target), os.path.realpath(project)
        nearest = folder
        while not os.path.exists(nearest):
            nearest = os.path.dirname(nearest)
        if not (os.path.realpath(nearest) + os.sep).startswith(root + os.sep) or os.path.islink(target):
            raise core.OpsError(standing.sentence("sit in a folder that leaves the project, or are a link"), 1)
        os.makedirs(folder, exist_ok=True)
        data = text.encode("utf-8")
        temporary = f"{target}.{os.getpid()}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, target)
        except BaseException:
            if os.path.lexists(temporary):
                os.unlink(temporary)
            raise
    return {"path": standing.PATH, "sha256": standing.sha256(data), "characters": standing.length(text), "cap": standing.CAP,
            "written": True}


def instructions_set(project: str, text: str, base_sha256: str, channel=None) -> dict:
    """The operation `instructions-set`: replace the whole text of the file (an empty text leaves an empty file, which gives no
    block). Only from the terminal and the page; refused when the file is not the one whose hash was given."""
    if not isinstance(text, str):
        raise core.OpsError("the text is text", 2)
    return _write(core.context(project), channel, base_sha256, lambda _current: text)


def instructions_add(project: str, line: str, base_sha256: str, channel=None) -> dict:
    """The operation `instructions-add`: append one line `- <text>` to the file. Only from the terminal and the page."""
    one = " ".join(line.split()) if isinstance(line, str) else ""
    if not one or "\n" in line.strip() or "\r" in line.strip():
        raise core.OpsError("the line is one non-empty line of text", 2)
    return _write(core.context(project), channel, base_sha256, lambda current: (current.rstrip("\n") + "\n" if current.strip() else "") + f"- {one}")


# --- the proposal ------------------------------------------------------------------------------------------------------------


def _request_of(ctx: dict, task_id):
    """The request a task belongs to (the task itself when it is a request)."""
    task = core._stored(ctx, ctx["store"].task_get, task_id)
    return task["parent_id"] if task["parent_id"] is not None else task["id"]


def proposal(ctx: dict, request_id, line, channel=None):
    """None, or {"line", "text", "command", "base_sha256"} when the person's own line is offered for the instructions (the module's
    text lists the conditions). The cursor of the request is written when it is offered, so a request gets one proposal. `line` is
    the text the person typed; a caller never passes a reply of a model or any other text."""
    if request_id is None or not isinstance(line, str) or channel in NO_PROPOSAL_CHANNELS:      # a messaging app's answer is never proposed, and the request's one proposal is not spent
        return None
    one = line.strip()
    if "\n" in one or "\r" in one or not PROPOSAL_MIN <= len(one) <= PROPOSAL_MAX:
        return None
    project = ctx["cfg"]["project"]
    found = standing.state(project)
    if found["problem"]:
        return None
    lines = [re.sub(r"^[-*]\s+", "", x.strip()) for x in found["text"].splitlines()]
    if one in lines or standing.check(found["text"].rstrip("\n") + "\n- " + one) is not None:
        return None
    name = PROPOSED + str(request_id)
    if core._stored(ctx, ctx["store"].cursor_get, name) is not None:
        return None
    core._stored(ctx, ctx["store"].cursor_set, name, standing.sha256(one.encode("utf-8")))
    base = found["sha256"] or "none"
    command = core._command("instructions-add", project, line=one, base_sha256=base)
    say = lambda key: phrases.text(key, ctx["cfg"])  # noqa: E731      # the frames are the phrase table's, in the project's language; the line and the command are not changed
    where = say("INSTR_WHERE_SAYS") if channel in ("terminal", "page") else say("INSTR_WHERE_ELSEWHERE")      # a channel that cannot write the file is told where to accept it
    return {"line": one, "base_sha256": base, "command": command,
            "text": f'{say("INSTR_PROPOSAL_ASK")} "{one}"\n{command}\n{where}'}


def answer_proposing(project: str, pending_id: int, text: str, with_comments: bool = False, channel=None, sender=None) -> dict:
    """The operation `answer`: ops.answer, and, for the answer to a question, the proposal of proposal() under "instruction_proposal"
    ({"line", ...}) when one is offered. The answer is recorded first; nothing here can undo it."""
    ctx = core.context(project)
    item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    out = _ops().answer(project, pending_id, text, with_comments=with_comments, channel=channel, sender=sender)
    if item["kind"] == "question" and channel in DISPLAYS:
        offered = proposal(ctx, _request_of(ctx, item["task_id"]), text, channel)
        if offered:
            out = {**out, "instruction_proposal": offered}
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
