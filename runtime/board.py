#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The mirror of tasks to and from the project's task board (class integration:issue-tracker).

The board is where a person sees the tasks and edits them. It owns what a person edits on an item: its title, its
text, its state and its comments. Everything else stays in the store and is only shown on the item ("shown"
fields, written by the runtime and never read back). Only code talks to the board: a run never sees it.

  pull(ctx)                   the board to the store. Each item whose version changed is read once: a title or a
                              text the person edited reaches the store (store.task_edit); a state the person set is
                              taken only when it is one of three moves (below), any other is refused and written back
                              by the next push; open comments are saved (store.comments_save) and change nothing by
                              themselves. The version covers the content and a comment may not move it, so an item
                              whose version did not change has its own comments listed (the provider's `comments`,
                              one call) and the new ones saved. An item no task knows becomes a request waiting for
                              the person's acceptance (store.request_from_board). An "after #n" in its title or text
                              is the override "run this after request #n" (n naming a task: that task's request),
                              kept on the request; one added to the text of a request later is taken the same way.
  push(ctx, dry_run=False)    the store to the board, oldest first: an item is written only when what would be
                              written changed since the last write; a title and a text are written only when the item
                              is created, never after (they are the person's). The item's note says what the task
                              waits for (the store's waits), before the task's own note. With dry_run, every write is
                              printed by the provider (upsert --dry-run) and nothing changes.

Only what is still open when the board is configured is mirrored: a task that was already final (done or cancelled)
at the first sync that writes to the board never gets an item (left_out()). That sync records its time in the
store's cursor board:configured. A task that becomes final later keeps its item, and the item moves.

The three moves a person may make on the board:
  ready      on a task that is failed or blocked: it is retried (store.task_retry)
  cancelled  on a request that is not final: it is cancelled with what is open under it (store.request_cancel)
  done       on a task waiting on a review: the review is released (store.pending_resolve, by "board")

The bounds of the writes: they are the project configuration's task_board object, inside the file whose hash the
person accepted (every operation checks it). A provider other than `local` is written to only until the day its
`expires` names (UTC), included.

Usage (a library; the shell is runtime/cli.py sync): python3 runtime/board.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project_config  # noqa: E402  (the same folder: the resolver is loaded, and the bounds read, from here)

CLASS = "integration:issue-tracker"
TIMEOUT = 120
SHOWN_CHARS = 300
FINAL = ("done", "cancelled")
# "after #12": the override of a request, only where a person wrote it as an instruction: at the start of a text, or on a
# line of its own (a trailing full stop allowed). Inside a sentence ("thereafter #3", "do it after #12 please") it is prose.
WORDS = r"after[ \t]+(?:(?:request|task)[ \t]+)?#(\d+)"
AFTER_FIRST = re.compile(r"\A\s*" + WORDS, re.I)                                   # the start of a text
AFTER_LINE = re.compile(r"^[ \t]*" + WORDS + r"[ \t]*[.;]?[ \t]*$", re.I | re.M)  # a line of its own
WAITS_SHOWN = 2  # the awaited tasks a note names; the rest is counted
CONFIGURED = "board:configured"  # the store's cursor: when the first sync wrote to the board (UTC, the store's form)


class BoardError(Exception):
    """A call to the task-board provider failed: kind is "not configured" (exit 3), "failed" or "bounds"."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def enabled(cfg: dict) -> bool:
    return cfg.get("task_board") is not None


def call(cfg: dict, root: str, verb: str, args: list, timeout: int = TIMEOUT, key: str = "task_board",
         cls: str = CLASS) -> dict:
    """Run one verb of the provider the configuration's object `key` names (task_board unless the documents' mirror
    asks for documents) through providers/resolve.py, with that object as its configuration file (mode 0600,
    deleted after), and return the one JSON object it prints."""
    try:
        resolve = project_config.resolver(root)
    except project_config.ConfigError as e:
        raise BoardError("not configured", str(e)) from None
    try:
        return resolve.call(cls, verb, args, root=root, implementation=cfg[key]["provider"], config=cfg[key],
                            timeout=timeout)
    except resolve.ProviderCallError as e:
        raise BoardError("not configured" if e.kind == "not-configured" else "failed", e.reason) from None


def _line(value) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.split())[:SHOWN_CHARS]


def after_of(*texts):
    """The number n of the first "after #n" in these texts (an item's title and text), or None: the person's override
    "run this after request #n", written in the item's own words."""
    for text in texts:
        found = AFTER_FIRST.search(text or "") or AFTER_LINE.search(text or "")
        if found:
            return int(found.group(1))
    return None


def _waiting_note(waits) -> str:
    """"waiting for #10, #12 (+1)": the awaited tasks (a request as "request #n"), at most WAITS_SHOWN named, the rest
    counted, so that the task's own note after it is never pushed out of the line."""
    named = [f"request #{w['awaited_id']}" if w.get("kind") == "after" else f"#{w['awaited_id']}" for w in waits]
    more = f" (+{len(named) - WAITS_SHOWN})" if len(named) > WAITS_SHOWN else ""
    return "waiting for " + ", ".join(named[:WAITS_SHOWN]) + more


def item_payload(task: dict, pending, create: bool = False, waits=()) -> dict:
    """What the runtime writes to a task's item: {"state", "shown": {...}}, every shown value one line of text;
    with create (the item does not exist yet), also its title and text, which are never written again. waits are the
    task's open waits (the store's waits_list rows): the item's note says what it waits for, before the task's own note."""
    waiting = f"{pending['kind']} {pending['id']}" if pending else ""
    note = "; ".join(filter(None, [_waiting_note(waits) if waits else "", task.get("note")]))
    payload = {"state": task["state"], "shown": {
        "task": _line(task["id"]), "request": _line(task.get("parent_id")), "flow": _line(task.get("flow")),
        "key": _line(task.get("key")), "skill": _line(task.get("skill")),
        "depends_on": _line(", ".join(str(d) for d in task.get("depends_on") or [])),
        "milestone": "yes" if task.get("milestone") else "no", "waiting_for": waiting, "note": _line(note)}}
    if create:
        payload["title"] = task["title"]
        payload["text"] = task["text"]
    return payload


def payload_hash(payload: dict) -> str:
    """The sha256 of what the runtime owns on an item (its state and shown fields): a title and a text, written
    once at creation, are left out, so that an unchanged task is never written again."""
    owned = {k: payload[k] for k in ("state", "shown")}
    return hashlib.sha256(json.dumps(owned, sort_keys=True).encode("utf-8")).hexdigest()


def _now() -> str:
    """The current time in the store's form, which compares correctly as text with a task's updated_at."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def left_out(ctx: dict, tasks=None) -> list:
    """The ids of the tasks that are never mirrored: no item, final, and last changed at or before the time the
    board was configured (the cursor CONFIGURED; now, while no sync has written to the board)."""
    configured = ctx["store"].cursor_get(ctx["conn"], CONFIGURED) or _now()
    tasks = ctx["store"].tasks_list(ctx["conn"]) if tasks is None else tasks
    return [t["id"] for t in tasks
            if not t.get("remote_id") and t["state"] in FINAL and t["updated_at"] <= configured]


def _open_pending(ctx: dict, task_id: int):
    found = ctx["store"].pending_list(ctx["conn"], "open", task_id)
    return found[0] if found else None


def pull(ctx: dict) -> dict:
    """The board to the store (see the module's text). Returns {"pulled", "created", "edited", "refused", "gone",
    "comments", "left_out_final"}: "comments" is the number of comments saved that were not saved before;
    "left_out_final" the number of tasks never mirrored because they were final when the board was configured."""
    cfg, store, conn, root = ctx["cfg"], ctx["store"], ctx["conn"], ctx["root"]
    out = {"pulled": [], "created": [], "edited": [], "refused": [], "gone": [], "comments": 0, "left_out_final": 0}
    listed = {item["id"]: item for item in call(cfg, root, "list", []).get("items", [])}
    tasks = store.tasks_list(conn)
    out["left_out_final"] = len(left_out(ctx, tasks))
    known = {t["remote_id"]: t for t in tasks if t.get("remote_id")}
    for remote_id, task in known.items():
        item = listed.get(remote_id)
        if item is None or item.get("archived"):
            out["gone"].append(task["id"])
            continue
        if item.get("version") == task.get("remote_version"):
            # Not read: the version covers the content, and a comment may not move it (measured, N3).
            try:
                said = call(cfg, root, "comments", ["--id", remote_id])
            except BoardError as e:
                out["refused"].append({"task": task["id"], "reason": str(e)})
                continue
            out["comments"] += _save_comments(ctx, task["id"], said.get("comments"))
            continue
        try:
            got = call(cfg, root, "get", ["--id", remote_id])
        except BoardError as e:
            out["refused"].append({"task": task["id"], "reason": str(e)})
            continue
        out["pulled"].append(task["id"])
        written = task.get("remote_written_sha256")
        edit = {}
        if got.get("title") and got["title"] != task["title"]:
            edit["title"] = got["title"]
        if got.get("text") and got["text"] != task["text"]:
            edit["text"] = got["text"]
        if edit:
            try:
                store.task_edit(conn, task["id"], by="board", **edit)
                out["edited"].append(task["id"])
                if task.get("parent_id") is None and task["state"] not in FINAL:  # "after #n" added or taken out later
                    wrote = after_of(edit.get("title", task["title"]), edit.get("text", task["text"]))
                    wanted = _after_request(tasks, wrote, out, remote_id)
                    if wanted is not None and wanted != task["id"] and wanted != task.get("after_request"):
                        store.request_after_set(conn, task["id"], wanted)
                    elif wrote is None and after_of(task["title"], task["text"]) is not None:
                        store.request_after_set(conn, task["id"], None)  # the words that said it are gone
            except store.StoreError as e:
                out["refused"].append({"task": task["id"], "reason": str(e)})
        state = got.get("state")
        if state != task["state"]:
            reason = _take_state(ctx, task, state)
            if reason:
                out["refused"].append({"task": task["id"], "state": state, "reason": reason})
                written = None  # the next push writes the store's state back
        out["comments"] += _save_comments(ctx, task["id"], got.get("comments"))
        store.task_remote_set(conn, task["id"], remote_id=remote_id, remote_version=got.get("version"),
                              written_sha256=written)
    for remote_id, item in listed.items():
        if remote_id in known or item.get("archived"):
            continue
        try:
            got = call(cfg, root, "get", ["--id", remote_id])
            title = got.get("title") or remote_id
            after = _after_request(tasks, after_of(title, got.get("text")), out, remote_id)
            made = store.request_from_board(conn, title=title, text=got.get("text") or title, remote_id=remote_id,
                                            remote_version=got.get("version"), by="board", after=after)
        except (BoardError, store.StoreError) as e:
            out["refused"].append({"item": remote_id, "reason": str(e)})
            continue
        out["created"].append({"request": made["request"], "pending_id": made["pending_id"], "item": remote_id})
    return out


def _after_request(tasks: list, number, out: dict, item):
    """The request an item's "after #n" names: n itself when it is a request, the request of task n when it is a task;
    None (and a refusal listed under `refused`) when n is neither."""
    if number is None:
        return None
    row = next((t for t in tasks if t["id"] == number), None)
    if row is None:
        out["refused"].append({"item": item, "reason": f"after #{number} names no request or task of this project"})
        return None
    return row["parent_id"] or row["id"]


def _save_comments(ctx: dict, task_id: int, comments) -> int:
    if not comments:
        return 0
    return ctx["store"].comments_save(ctx["conn"], comments, provider=ctx["cfg"]["task_board"]["provider"],
                                      subject="task", task_id=task_id)["saved"]


def _take_state(ctx: dict, task: dict, state):
    """Take a state a person set on the board when it is one of the three moves; else the reason it is refused."""
    store, conn = ctx["store"], ctx["conn"]
    try:
        if state == "ready" and task["state"] in ("failed", "blocked"):
            store.task_retry(conn, task["id"])
            return None
        if state == "cancelled" and task.get("parent_id") is None and task["state"] not in FINAL:
            store.request_cancel(conn, task["id"], by="board")
            return None
        if state == "done" and task["state"] == "waiting":
            pending = _open_pending(ctx, task["id"])
            if pending and pending["kind"] == "review":
                store.pending_resolve(conn, pending["id"], resolution="released", by="board")
                return None
    except store.StoreError as e:
        return str(e)
    return (f"the board moved task {task['id']} from {task['state']} to {state}: only ready (a failed or blocked "
            "task), cancelled (a request) and done (a task waiting on a review) are taken from the board")


def _key(cfg: dict, task_id: int, digest: str) -> str:
    store_hash = hashlib.sha256(cfg["store_db"].encode("utf-8")).hexdigest()[:12]
    return f"task:{store_hash}:{task_id}:{digest[:16]}"


def push(ctx: dict, dry_run: bool = False) -> dict:
    """The store to the board (see the module's text). Returns {"pushed", "failed"}, and with dry_run "would":
    what the provider printed for each write it would make."""
    cfg, store, conn, root = ctx["cfg"], ctx["store"], ctx["conn"], ctx["root"]
    out = {"pushed": [], "failed": []}
    if dry_run:
        out["would"] = []
    bounds = None if dry_run else project_config.bounds_problem(cfg)
    tasks = store.tasks_list(conn)
    if not dry_run and store.cursor_get(conn, CONFIGURED) is None:
        store.cursor_set(conn, CONFIGURED, _now())  # the board is configured: what is final now is never mirrored
    never = set(left_out(ctx, tasks))
    waiting = {}
    for w in store.waits_list(conn):
        waiting.setdefault(w["task_id"], []).append(w)
    for task in tasks:
        if task["id"] in never:
            continue
        exists = bool(task.get("remote_id"))
        payload = item_payload(task, _open_pending(ctx, task["id"]), create=not exists, waits=waiting.get(task["id"], ()))
        digest = payload_hash(payload)
        if exists and digest == task.get("remote_written_sha256"):
            continue
        if bounds:
            out["failed"].append({"task": task["id"], "reason": bounds})
            continue
        fd, item_file = tempfile.mkstemp(prefix="item-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            args = (["--id", task["remote_id"]] if exists else []) + [
                "--item-file", item_file, "--idempotency-key", _key(cfg, task["id"], digest),
                "--dry-run" if dry_run else "--confirmed"]
            done = call(cfg, root, "upsert", args)
        except BoardError as e:
            out["failed"].append({"task": task["id"], "reason": str(e)})
            continue
        finally:
            try:
                os.unlink(item_file)
            except OSError:
                pass
        if dry_run:
            out["would"].append({"task": task["id"], **done})
            continue
        try:
            store.task_remote_set(conn, task["id"], remote_id=done["id"], remote_version=done.get("version"),
                                  written_sha256=digest)
        except (KeyError, store.StoreError) as e:
            out["failed"].append({"task": task["id"], "reason": f"written, and not recorded: {e}"})
            continue
        out["pushed"].append(task["id"])
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
