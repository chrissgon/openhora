#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Cancel a request, or stop a task, at any moment (R18, limit L41): the two operations `cancel` and `stop-task`, and what the
runs and the shells ask of them.

A sibling of runtime/ops.py, which exposes `cancel` and `stop_task` under their names; no shell imports this file. The names
every module of the layer shares are read as `core.<name>` (runtime/ops_core.py). The process mechanics (the signals, the
snapshot of a holder's tree, the container clean-up, the router's watcher) are runtime/run_stop.py.

The order of a call, which is the contract:

  1. The request's effect lock (`effect-<request>.lock`) is taken, and held for the whole call. An effect that is executing
     holds it, so the call waits as `_effect_lock` waits and is then refused with nothing written and nothing signalled
     (limit L41: a cancel or a stop never signals a process while an effect of its request executes).
  2. The stop request is written first, in one transaction (the store's `request_stop` or `task_stop`), holding the project's
     write lock: a run that returns its files into the project holds the same lock from its check of the stop request to its
     finish, so a stopped run returns nothing, whatever the timing. In that transaction every task of the request that is not
     running and not final is cancelled, so nothing new is claimed.
  3. What is running is ended: the holders of the task locks get TERM, then KILL after the grace (run_stop.stop_tasks); the
     router's run, which runs inside a process that is never signalled, is ended by its own watcher and waited for (ROUTER_WAIT).
  4. Whatever a dead holder left running is finished here, under the store's rule: the run row `cancelled` with what it
     reported, the task cancelled (a cancel) or blocked with a note for `retry` (a stop), the request cancelled once none of its
     runs is running.

A second call finds the stop request written, writes nothing new, repeats 3 and 4 and answers with "already": true.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ops_core as core  # noqa: E402
import ops_flows  # noqa: E402
import ops_waits  # noqa: E402
import run_stop  # noqa: E402

DEAD_NOTE = "the run was ended by a stop request"


def _who(by: str, channel) -> str:
    """The label the stop request carries: the person (or the board), and the channel that carried the call."""
    return by if channel in (None, "", by) else f"{by} from {channel}"


def _hold_effect_lock(stack: contextlib.ExitStack, cfg: dict, request_id: int) -> None:
    try:
        stack.enter_context(core._effect_lock(cfg, request_id))
    except core.OpsError:
        raise core.OpsError(f"an effect of request {request_id} is executing; nothing was stopped; cancel again when it ends",
                            1) from None


def _usage(ctx: dict, row: dict) -> dict:
    """What a run row's folder reported, as the store takes it: {"tokens", "cost_usd" (a metered credential only), "run_dir"}."""
    ops, lab = importlib.import_module("ops"), importlib.import_module("lab")
    dest = row.get("run_dir") or os.path.join(ctx["cfg"]["data_dir"], core.RUNS_DIR, str(row["id"]))
    got = ops._reported_usage(lab.reported_usage(dest), {"billing": row.get("billing")})
    return {**got, **({"run_dir": dest} if os.path.isdir(dest) else {})}


def _usages(ctx: dict, task_ids) -> dict:
    """{run id: usage} of the run rows of these tasks that are still `running`."""
    out = {}
    for task_id in task_ids:
        for row in core._stored(ctx, ctx["store"].task_runs_list, task_id):
            if row["status"] == "running":
                out[row["id"]] = _usage(ctx, row)
    return out


def _cancelled_pending(ctx: dict, request_id: int) -> set:
    store = ctx["store"]
    found = set()
    for task in core._stored(ctx, store.tasks_list, request_id):
        found.update(p["id"] for p in core._stored(ctx, store.pending_list, "cancelled", task["id"]))
    return found


def _finish_router(ctx: dict, run_id: int, wait: float | None = None, poll: float = 0.2) -> str:
    """Wait for the router's run row to end (its own process finishes it, reading the stop request): `ended`; when the route
    lock is free while the row is still `running` its owner is dead, and the row is finished here: `dead`; `stopping` when
    the wait is spent."""
    store, cfg = ctx["store"], ctx["cfg"]
    deadline = time.monotonic() + (run_stop.ROUTER_WAIT if wait is None else wait)
    while True:
        row = core._stored(ctx, store.task_run_get, run_id)
        if row["status"] != "running":
            return "ended"
        fd = core._try_lock(cfg, "route.lock")
        if fd is not None:
            try:
                core._stored(ctx, store.task_fail_orphans, [], [run_id], DEAD_NOTE, usage={run_id: _usage(ctx, row)})
            finally:
                os.close(fd)
            return "dead"
        if time.monotonic() >= deadline:
            return "stopping"
        time.sleep(poll)


def _end(ctx: dict, first: dict) -> list:
    """Step 3 and 4 for what request_stop or task_stop found running (first["running"]: [{"task", "run", "step"}], and the
    router's first["router_run"]). Returns [{"task" or "run", "run", "state": "cancelled" | "stopping"}]."""
    store, cfg = ctx["store"], ctx["cfg"]
    running = first.get("running") or []
    answers = []
    if running:
        found = run_stop.stop_tasks(cfg, [r["task"] for r in running])
        for item in running:
            task_id = item["task"]
            if found[task_id]["state"] != "stopping":   # the holder is gone: finish what it left, under the store's rule
                core._stored(ctx, store.task_stopped, task_id, usage=_usages(ctx, [task_id]))
            row = core._stored(ctx, store.task_get, task_id)
            ended = row["state"] != "running"
            answers.append({"task": task_id, "run": item["run"], "state": "cancelled" if ended else "stopping",
                            **({"why": found[task_id]["why"]} if not ended and found[task_id]["why"] else {})})
    if first.get("router_run") is not None:
        state = _finish_router(ctx, first["router_run"])
        answers.append({"run": first["router_run"], "state": "stopping" if state == "stopping" else "cancelled"})
    return answers


def cancel_request(ctx: dict, request_id: int, *, by: str = "user", channel=None) -> dict:
    """Cancel a request at any moment (the sequence in the module's text). Returns {"request", "cancelled": [the ids of the
    tasks and the request cancelled], "stopped": [{"task" and/or "run", "state": "cancelled" | "stopping"}], "pending": [the
    pending decisions cancelled], "already"}; "stopping" is a run that did not end within the waits: the request keeps its stop
    request, and its owner (or the next recovery) finishes it."""
    cfg, store, who = ctx["cfg"], ctx["store"], _who(by, channel)
    if core._stored(ctx, store.task_get, request_id)["parent_id"] is not None:   # asked before any lock is taken: a task's id makes no lock file
        raise core.OpsError(f"task {request_id} is not a request: cancel the request it belongs to", 1)
    with contextlib.ExitStack() as stack:
        _hold_effect_lock(stack, cfg, request_id)
        before = _cancelled_pending(ctx, request_id)
        with core._write_lock(cfg):   # the stop request and a run's return into the project exclude each other
            first = core._stored(ctx, store.request_stop, request_id, by=who)
        stopped = _end(ctx, first)
        states = {t["id"]: t["state"] for t in core._stored(ctx, store.tasks_list, request_id)}
        ended = [a["task"] for a in stopped if "task" in a and states.get(a["task"]) == "cancelled"]
        late = [request_id] if states.get(request_id) == "cancelled" and not first["already"] else []
        cancelled = sorted({*first["cancelled"], *ended, *late})
        pending = sorted(_cancelled_pending(ctx, request_id) - before)
    ops_flows.discard_staged(ctx, request_id)      # the files handed over for its plan go with it
    return ops_waits.settled(ctx, {"request": request_id, "cancelled": cancelled, "stopped": stopped, "pending": pending,
                                   "already": first["already"]})


def stop_one(ctx: dict, task_id: int, *, by: str = "user", channel=None) -> dict:
    """Stop one running task at any moment: its run ends `cancelled` and the task `blocked` with the note "stopped by <who>:
    retry it or cancel the request", so that `retry` resumes it (a step task at its step) and its dependents stay planned. The
    other tasks of the request follow the request. Returns the shape of cancel for the task's request, "cancelled" and "pending"
    empty."""
    cfg, store, who = ctx["cfg"], ctx["store"], _who(by, channel)
    task = core._stored(ctx, store.task_get, task_id)
    request_id = task["parent_id"]
    if request_id is None:
        raise core.OpsError(f"task {task_id} is a request: cancel it", 1)
    with contextlib.ExitStack() as stack:
        _hold_effect_lock(stack, cfg, request_id)
        with core._write_lock(cfg):
            first = core._stored(ctx, store.task_stop, task_id, by=who)
        running = [{"task": task_id, "run": first["run"], "step": first["step"]}] \
            if core._stored(ctx, store.task_get, task_id)["state"] == "running" else []
        stopped = _end(ctx, {"running": running})
    return ops_waits.settled(ctx, {"request": request_id, "task": task_id, "cancelled": [], "stopped": stopped,
                                   "pending": [], "already": first["already"]})


def cancel(project: str, request_id: int, channel: str | None = None) -> dict:
    """The operation `cancel`: cancel a request, its tasks that are not done and their open pending decisions, at any moment; a run in
    progress is ended and returns nothing (limit L41). Returns {"request", "cancelled", "stopped", "pending", "already"}."""
    return cancel_request(core.context(project), request_id, channel=channel)


def stop_task(project: str, task_id: int, channel: str | None = None) -> dict:
    """The operation `stop-task`: stop one running task; its run ends cancelled and the task blocked, for `retry`."""
    return stop_one(core.context(project), task_id, channel=channel)


def watch(ctx: dict, request_id: int):
    """The router's watcher around its lab call (run_stop.watch), reached from ops.py through this module."""
    return run_stop.watch(ctx, request_id)


def after_sync(ctx: dict, out: dict) -> dict:
    """What `sync` does after it let the write lock go: the requests a person cancelled on the board (board.pull with defer, "cancel_later")
    are cancelled now, each as anywhere else, and the board is written again so that the cancelled state reaches it. A cancel that is refused
    (an effect of the request executes) is listed under the board's "refused". Returns out."""
    shown = out.get("board")
    later = shown.pop("cancel_later", []) if isinstance(shown, dict) else []
    if not later:
        return out
    board = importlib.import_module("board")
    for request_id in later:
        try:
            cancel_request(ctx, request_id, by="board", channel="board")
        except core.OpsError as e:
            shown["refused"].append({"task": request_id, "state": "cancelled", "reason": str(e)})
    try:
        with core._write_lock(ctx["cfg"]):
            again = board.push(ctx)
        shown["pushed"] = sorted({*shown["pushed"], *again["pushed"]})
        shown["failed"] += again["failed"]
    except board.BoardError as e:
        shown["failed"].append({"task": later[0], "reason": str(e)})
    return out


def stop_requested(ctx: dict, task_id: int) -> bool:
    """Whether a stop request reaches this task (its own, or its request's). A run asks it, holding the project's write lock,
    just before it returns anything into the project (limit L41)."""
    return ctx["store"].stop_of(ctx["conn"], task_id) is not None


def cancelled_run(out: dict, done: dict) -> bool:
    """When the store recorded a run cancelled (done["cancelled"]), say so in the result of the run, which keeps no file it
    would have returned and no decision it would have opened; returns True. Otherwise leaves out alone and returns False."""
    if not done.get("cancelled"):
        return False
    out.update(status="cancelled", ending=None, failure=None, pending_id=None)
    if done.get("task_state") is not None:
        out["task_state"] = done["task_state"]
    for key in ("returned", "kept"):
        if key in out:
            out[key] = []
    return True


def step_stopped(ctx: dict, task_id: int) -> bool:
    """A step task's process was told to stop: when a stop request is why, the task ends as it says (cancelled for a cancel,
    blocked with the note for a stop) and this returns True; otherwise False and the caller fails the task as before."""
    store = ctx["store"]
    if store.stop_of(ctx["conn"], task_id) is None:
        return False
    core._stored(ctx, store.task_stopped, task_id)
    return True


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
