#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `tasks-item`: add a task to a list of the person's own task service, or mark one as completed, as an external effect the person approves (package CB-5).
The kind prepares; it never writes. Two steps, as in a calendar change:

  prepare   checks the arguments, takes the account's address and the list from the project's `accounts` (a list the project does not list under `task_lists` is refused: limit
            L55), resolves Microsoft's default list to its id, and, for a completion, reads the task from the service through the read-only tasks seam (its title, its status and
            its version) and refuses a task that is gone or completed already. Then it asks the writer for a dry run of the request (nothing is sent, no credential is read, no
            connection is opened), checks that what the writer would send is what the arguments say (the method, the body, the version a completion requires, nothing else), and
            writes the effect document (runtime/tasks_document.py) through the effect-files service to <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a 0700 folder.
  tasks     the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the effect document and whose body is the card: the account,
            the list and the task; the task waits. The person approves the hash in the terminal or on the page (a messaging app only when the project's policy grants it the word
            `tasks`), and then runtime/ops_step_effects.py calls the effect module (runtime/effect_tasks.py), which reads the task again, writes once, and tells nobody. A task
            changed meanwhile answers the decision, writes nothing and sends the task back to `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will be asked about):

  {"account": "google" | "microsoft", "operation": "add" | "complete"
   [, "list": "<a name of accounts.<a>.task_lists>" (the first one when absent)]
   add:       "title"
   complete:  "task" (the id the service gave, found by the operation from a live read of the list)}

Nothing else is a task's part in v1: no due date, no note, no parent (OPEN-CB-11). The account is never an argument of the effect's target: the list is the project's name for it.

Limit L30, in the structure of this file: it imports no module that calls a provider. What it needs of the accounts, of the list and of the data folder it asks of `ctx.services`
(runtime/ops_step_seams.py), where `tasks_read` has a task read, the default list's id and a dry run and no way to write, and `effect_files` writes and reads the effect document and
does not execute it. The only code that writes is runtime/effect_tasks.py `execute`, which this file cannot reach.

The kind is not `unattended`: a task change starts when the person starts it and ends at the person's approval. It writes no file of the project (its footprint is empty).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import steps  # noqa: E402
import tasks_document  # noqa: E402

KEYS = ("account", "operation", "list", "title", "task", "channel", "sender")
CHANNELS = ("terminal", "page", "messaging")      # who asked: written by the operation, never by a person's words
SENDER = re.compile(r"[a-z][a-z0-9-]{0,31}:[A-Za-z0-9_.@+=-]{1,128}")
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed", "refused": "refused"}
GATE_STEP = "tasks"
NAME = re.compile(r"[a-z0-9-]{1,32}")
METHOD = {"add": "POST", "complete": "PATCH"}
PRINTED = ("method", "path", "query", "headers", "body", "requires")      # what a writer's dry run prints of the request (providers/writer/README.md)
EXTRA_PARTS = ("due", "due_date_time", "notes", "body", "parent", "previous", "categories", "deleted", "reminder_date_time", "status_details")      # a request that carries one is not v1's


def _bad(field: str, hint: str = ""):
    return steps.StepFailure("bad_args", field, "", hint[:200])


def _checked(call, *a, field: str):
    """A check of the document module whose refusal is a bad argument: the sentence names the rule, never the content."""
    try:
        return call(*a)
    except Exception as e:      # an EffectError of the document, with its `reason`
        raise _bad(field, str(getattr(e, "reason", ""))) from None


def check(args) -> dict:
    """The arguments of a tasks-item, checked and normalised."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise _bad("args")
    if args.get("account") not in tasks_document.ACCOUNTS:
        raise _bad("account", "give google or microsoft")
    operation = args.get("operation")
    if operation not in tasks_document.OPERATIONS:
        raise _bad("operation", "give add or complete")
    out = {"account": args["account"], "operation": operation}
    if args.get("list") is not None:
        if not isinstance(args["list"], str) or not NAME.fullmatch(args["list"]):
            raise _bad("list", "a list is named as the project's accounts name it: lowercase letters, digits and hyphens")
        out["list"] = args["list"]
    if args.get("channel") is not None:
        if args["channel"] not in CHANNELS:
            raise _bad("channel", "the channel is terminal, page or messaging")
        out["channel"] = args["channel"]
    if args.get("sender") is not None:
        if not isinstance(args["sender"], str) or not SENDER.fullmatch(args["sender"]) or args.get("channel") != "messaging":
            raise _bad("sender", "a sender is <platform>:<id> and goes with the channel messaging")
        out["sender"] = args["sender"]
    if operation == "add":
        if args.get("task") is not None:
            raise _bad("task", "a new task names no earlier task")
        if args.get("title") is None:
            raise _bad("title", "a new task needs a title")
        _checked(tasks_document.line, args["title"], "the title", tasks_document.TITLE_MAX, True, field="title")
        out["title"] = args["title"]
    else:
        if args.get("title") is not None:
            raise _bad("title", "completing a task takes no title: the task is the one the list holds")
        if not isinstance(args.get("task"), str) or not tasks_document.TASK_ID.fullmatch(args["task"]):
            raise _bad("task", "name the task by the id the service gave")
        out["task"] = args["task"]
    return out


def _service(ctx: steps.Context, name: str):
    found = ctx.services.get(name)
    if found is None:
        raise steps.StepFailure("not_configured", name)
    return found


def _asked(call, *args, field="list"):
    """A service call whose failure is a closed code of the step; `field` is the argument the sentence is about."""
    try:
        return call(*args)
    except steps.StepFailure:
        raise
    except Exception as e:      # the services raise errors that carry a `code`; anything else is a provider failure
        code = SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed")
        raise steps.StepFailure(code, field, "writer", str(getattr(e, "reason", ""))[:200] if code != "provider_failed" else "") from None


def _keys(found):
    """Every key of every object inside `found` (a request as the writer's dry run prints it), so that the words of a title are never mistaken for a key."""
    if isinstance(found, dict):
        for key, value in found.items():
            yield key
            yield from _keys(value)
    elif isinstance(found, list):
        for value in found:
            yield from _keys(value)


def _same(doc: dict, would: dict) -> bool:
    """Whether what the writer's dry run says it would send is what the document says: the method of the operation, the body of an add (the title and nothing else) or of a
    completion (the status and nothing else), the version a completion requires, and no part a task has beyond its title."""
    body, path = would.get("body"), would.get("path")
    if would.get("method") != METHOD[doc["operation"]] or not isinstance(path, str) or "/tasks" not in path or set(would) - set(PRINTED) or set(_keys(body)) & set(EXTRA_PARTS):
        return False
    if doc["operation"] == "add":
        return body == {"title": doc["title"]} and would.get("requires") is None and path.endswith("/tasks")
    parts = path.split("/")      # a completion is aimed at one task: .../tasks/<id>, never at the list's tasks
    return body == {"status": "completed"} and would.get("requires") == {"etag": doc["base_etag"]} and len(parts) >= 2 and parts[-2] == "tasks" and bool(parts[-1])


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    reader, files = _service(ctx, "tasks_read"), _service(ctx, "effect_files")
    account, operation = args["account"], args["operation"]
    if not reader.enabled(account):
        raise steps.StepFailure("not_configured", "account", "", "list the account in docs/workbench/runtime.json (the key accounts) and accept the file")
    name = reader.list_name(account, args.get("list"))
    list_id, why = reader.target(account, name)
    if why:
        raise steps.StepFailure("target_refused", "list", "", why[:200])
    address = reader.address(account)
    resolved = _asked(reader.resolve_list, account, list_id)
    pieces = dict(task_id=ctx.task_id, account=account, address=address, list_name=name, list_id=resolved, operation=operation, default_list=(list_id == "default" and resolved != "default"))      # the flag: the id was resolved from `default` (Microsoft), and the effect resolves it again
    try:
        if operation == "add":
            pieces.update(title=args["title"])
        else:
            read = _asked(reader.task_get, account, address, resolved, args["task"], field="task")
            task = read.get("task") if isinstance(read, dict) and read.get("found") is True else None
            if not isinstance(task, dict):
                raise steps.StepFailure("task_gone", "task", "writer", "that task is not in this list any more (it was completed, or it is in another list)")
            if task.get("status") != "open":
                raise steps.StepFailure("nothing_to_change", "task", "writer", "that task is completed already")
            if not isinstance(task.get("etag"), str) or not isinstance(task.get("id"), str):
                raise steps.StepFailure("provider_failed", "task", "writer", "the service gave no version of the task, so nothing is changed")
            if state.get("pinned_task") not in (None, task["id"]):
                raise steps.StepFailure("not_eligible", "task", "", "the task now named is not the one the card you were asked about showed: name the task again and start over")
            pieces.update(remote_id=task["id"], base_etag=task["etag"], read_at=tasks_document.utc_text(ctx.now()), title=tasks_document.line_or_blank(task.get("title")))
        pieces.update(asker=args["sender"] if args.get("channel") == "messaging" and args.get("sender") else (args.get("channel") or "terminal"))
        draft = tasks_document.document(**pieces, dry_run_sha256="0" * 64)
    except steps.StepFailure:
        raise
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "args", "", str(getattr(e, "reason", ""))[:200]) from None
    shown = _asked(reader.dry_run, draft)
    would, digest = shown.get("would") if isinstance(shown, dict) else None, shown.get("would_sha256") if isinstance(shown, dict) else None
    if not isinstance(would, dict) or not isinstance(digest, str) or not tasks_document.SHA256.fullmatch(digest) or not _same(draft, would):
        raise steps.StepFailure("preview_mismatch", "writer", "writer", "the writer would send something other than the arguments say: nothing is asked about it")
    doc = tasks_document.document(**pieces, dry_run_sha256=digest)
    written = _asked(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)
    if operation == "complete":
        state["pinned_task"] = doc["task_id"]      # a start over after a stale prepares the same task, or refuses
    return {"effect_sha256": written, "operation": operation, "account": account, "list": name}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its card, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    tasks_document.check(doc)
    return {"title": tasks_document.title(doc), "body": tasks_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": tasks_document.summary(doc), "card": tasks_document.card_lines(doc, recorded)}}


KIND = steps.register(steps.Kind(
    name="tasks-item",
    order=("prepare", GATE_STEP),
    executors={"prepare": _prepare},
    gates={GATE_STEP: steps.Gate(word=tasks_document.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
