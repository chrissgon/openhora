#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The run of a step task (package P5): the one operation `run_step`, and what a process that runs a step task does around the engine
of runtime/steps.py.

A step task is a task of a request that runs no skill: its kind is a word of the engine's registry, its arguments and footprint are
columns of the task (providers/store/sqlite.py, "the step task"), and its owner is the runtime's own pseudo-agent (`runtime`, which has
a running cap of its own and no model, no daily cap and no mode: runtime/parallel.py, runtime/dispatcher.py). It runs in a process of
its own, as a task run does:

  python3 runtime/cli.py run-step --project <dir> --task <id>

which the dispatcher starts for every ready step task (runtime/ops_runs.py), and which a person may start by hand. The process takes
the task's lock (task-<id>.lock) before it claims the task and holds it until the task has left `running`: that lock is the proof the
task is alive. A task that is `running` in the store whose lock nobody holds is an orphan, and the next dispatcher round, run-next or
run-step ends it `failed` (runtime/ops_runs.py `_recover`), so a killed process never leaves a task `running`. `stop-runs` signals the
process group the lock names, as it does for a task run; this process turns the TERM into a clean end (the task `failed`, the note
saying it was stopped) and a KILL is left to the recovery.

  run_step(project, task_id)   admit and claim the task under the claim lock, run its steps, and return {"ran": task id, "step": the
                               kind, "task_state", "ok", ...} (the engine's result); a refusal is {"ran": None, "reason", "held"}

A sibling of runtime/ops.py, which exposes `run_step` under its name; no shell imports this file. The names every module of the layer
shares are read as `core.<name>`. It reaches the runs' helpers of runtime/ops_runs.py and no operation of ops.py.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import datetime
import os
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ops_core as core  # noqa: E402
import ops_runs  # noqa: E402
import ops_step_seams  # noqa: E402
import ops_waits  # noqa: E402
import dispatcher  # noqa: E402
import operations  # noqa: E402
import parallel  # noqa: E402
import sources  # noqa: E402
import steps  # noqa: E402

MODE_CURSOR = "steps:mode"              # the store's cursor that holds the brake: absent or "autonomous", or "stopped"
MODES = ("stopped", "autonomous")       # the two modes of the runtime's own pseudo-agent (set-mode --agent runtime)
STOP_NOTE = "stopped: the run was ended by stop-runs; retry the task"
INTERNAL_NOTE = "internal error ({kind}); retry the task, and tell the maintainer if it happens again"


class Stopped(BaseException):
    """The process was asked to stop (TERM): raised by the signal handler, so that the task can end `failed` before the process
    exits. A BaseException, so that no `except Exception` of an executor swallows it."""


@contextlib.contextmanager
def _stop_signals():
    """On the main thread, TERM ends the step by raising Stopped; the handler that was there is put back. On any other thread nothing
    is installed."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def on_term(_signum, _frame):
        raise Stopped()

    previous = signal.signal(signal.SIGTERM, on_term)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _stored_state(ctx: dict, task_id: int):
    try:
        return ctx["store"].task_get(ctx["conn"], task_id)["state"]
    except ctx["store"].StoreError:
        return None


def _context(ctx: dict, task: dict) -> steps.Context:
    """The engine's Context for this task: its moves and saves go through the store's step functions, a cancelled request becomes
    Cancelled, and the pending decisions of the task are read as the engine finds its stops again."""
    store, task_id = ctx["store"], task["id"]

    def cancelled(error) -> Exception:
        if _stored_state(ctx, task_id) == "cancelled":
            return steps.Cancelled()
        return core.OpsError(str(error), error.code)

    def move(word, note, pending, resolve, state):
        try:
            return store.step_task_move(ctx["conn"], task_id, state=word, note=note, pending=pending, resolve=resolve,
                                        step_state=state, by="user" if resolve else "code")
        except store.StoreError as e:
            raise cancelled(e) from None

    def save(state):
        try:
            store.step_state_save(ctx["conn"], task_id, state)
        except store.StoreError as e:
            raise cancelled(e) from None

    def alive():
        if _stored_state(ctx, task_id) == "cancelled":
            raise steps.Cancelled()

    def decisions():
        return [{"id": d["id"], "status": d["status"], "resolution": d.get("resolution"), "answer": d.get("answer"),
                 "payload": d.get("payload") or {}} for d in core._stored(ctx, store.pending_list, "all", task_id)]

    return steps.Context(task_id=task_id, request_id=task["parent_id"], project=ctx["cfg"]["project"],
                         args=task.get("step_args") or {}, move=move, save=save, alive=alive, decisions=decisions, now=_now,
                         footprint=tuple(task.get("step_footprint") or ()), protected=lambda path: sources.inside(ctx["cfg"], path),
                         services=ops_step_seams.services(ctx))


def _start(ctx: dict, task_id: int, unattended: bool = False) -> dict:
    """Admit and claim one step task, under the claim lock (the same lock and the same pure function, runtime/parallel.py `admit`,
    as a task run). `unattended`: the dispatcher started this process, so what it decided on a snapshot is asked again under the lock,
    where the person's brake or a kind that is not unattended may have changed meanwhile: the task is held with that word and left
    `ready`. The person's own start (run-next, run-step by hand) asks neither. Returns {"task": the claimed task}, or a refusal
    {"ran": None, "reason", "held"} (held: the reason is one of the words of the held tasks, not an error)."""
    cfg, store = ctx["cfg"], ctx["store"]
    try:
        task = store.task_get(ctx["conn"], task_id)
    except store.StoreError:
        task = None
    with core._claim_lock(cfg):
        if task is not None and not store.is_step_task(task):
            return {"ran": None, "reason": f"task {task_id} is not a step task: run-task runs it", "held": False, "task": task_id}
        if unattended and task is not None and task["state"] == "ready":
            why = held_reason(ctx, task)
            if why:
                return {"ran": None, "reason": why, "held": True, "task": task_id}
        if task is not None and task["state"] == "ready":
            cache = {}
            running = [r for r in ops_runs.running_and_effects(ctx, cache) if r["id"] != task_id]
            holders = core._stored(ctx, store.task_slot_holders)
            ok, why = parallel.admit(ops_runs.item_of(task, cache), running, holders, cfg["area_agents"], cfg["max_running"])
            if not ok:
                return {"ran": None, "reason": why, "held": True, "task": task_id}
        claimed = core._stored(ctx, store.task_claim, task_id)
        if claimed["task"] is None:
            reason = "no task is ready" if claimed.get("reason") in (None, "not-ready") else f"task {task_id} is {claimed['reason']}"
            return {"ran": None, "reason": ops_waits.explain(ctx, task_id, reason), "held": False, "task": task_id}
        return {"task": claimed["task"]}


def _fail(ctx: dict, task: dict, note: str) -> None:
    """End a task `failed` with a note when the engine could not: a store that refuses (the task moved meanwhile) is left alone."""
    try:
        ctx["store"].step_task_move(ctx["conn"], task["id"], state="failed", note=note, by="code")
    except ctx["store"].StoreError:
        pass


def _body(ctx: dict, task: dict) -> dict:
    """Run the claimed task's steps. Whatever ends the engine (an unknown kind, a state that cannot be read, a stop signal, a
    bug) leaves the task `failed` with a note, never `running`."""
    task_id = task["id"]
    out = {"ran": task_id}
    try:
        kind = steps.kind_of(task["step_kind"])
        out["step"] = kind.name
        state = steps.state_of(kind, task.get("step_state"))
        with _stop_signals():
            out.update(steps.run(_context(ctx, task), kind, state))
    except steps.StepFailure as e:   # the kind is not in this checkout, or the stored state is not this kind's
        _fail(ctx, task, steps.note_of("start", e))
        out.update({"ok": False, "failed": "start", "code": e.code, "field": e.field, "next": e.next})
    except Stopped:
        _fail(ctx, task, STOP_NOTE)
        out.update({"ok": False, "failed": None, "code": "stopped", "field": "", "next": ""})
    except Exception as e:           # a bug in a kind: the task must not stay running
        _fail(ctx, task, INTERNAL_NOTE.format(kind=type(e).__name__))
        out.update({"ok": False, "failed": None, "code": "internal", "field": "", "next": ""})
    out["task_state"] = _stored_state(ctx, task_id)
    return out


def run_step(project: str, task_id: int, unattended: bool = False) -> dict:
    """Run one named step task in this process: take its lock, end what dead processes left, admit and claim it under the claim
    lock, run its steps until a stop, a failure or the end. What it returns: {"ran": the task id, "step": the kind, "task_state",
    "ok", and the engine's result ("done", or "stopped" and "pending", or "failed", "code", "field", "next")}; a refusal is
    {"ran": None, "reason", "held"}, as run_task's. The process that starts it (the dispatcher) reads the exit code: 4 for a refusal
    that is not one of the words of the held tasks. `unattended` is the dispatcher's flag (`run-step --unattended`): the brake and the
    kind's flag are checked again under the claim lock."""
    ctx = core.context(project)
    with core._task_lock(ctx["cfg"], task_id):
        recovered = ops_runs._recover(ctx)
        started = _start(ctx, task_id, unattended)
        if started.get("ran", True) is None:    # a refusal; a claim is {"task": the claimed row}
            return {**started, "recovered": recovered["tasks"]}
        return {**_body(ctx, started["task"]), "recovered": recovered["tasks"]}


# --- the brake, and what the dispatcher may start on its own ---------------------------------------------------------------------


def steps_mode(ctx: dict) -> str:
    """`stopped` or `autonomous`: the runtime pseudo-agent's mode, kept in the store's cursor `steps:mode` (absent means autonomous)."""
    return "stopped" if core._stored(ctx, ctx["store"].cursor_get, MODE_CURSOR) == "stopped" else "autonomous"


def unattended(kind_name) -> bool:
    """Whether the dispatcher may start a task of this kind on its own. A kind this checkout does not have is not."""
    try:
        return bool(steps.kind_of(kind_name).unattended)
    except steps.StepFailure:
        return False


def may_dispatch(ctx: dict, task: dict) -> bool:
    """Whether the dispatcher may start this step task now: the runtime is not stopped and its kind is unattended."""
    return steps_mode(ctx) != "stopped" and unattended(task.get("step_kind"))


def held_reason(ctx: dict, task: dict):
    """Why the dispatcher will not start this step task, as one word of the dispatcher's list (`stopped`: the person's brake;
    `start it by hand`: its kind is not unattended), or None when it may."""
    if steps_mode(ctx) == "stopped":
        return "stopped"
    return None if unattended(task.get("step_kind")) else dispatcher.BY_HAND


def annotate(ctx: dict, snapshot: dict) -> None:
    """Add to the dispatcher's snapshot what it needs to decide a step task (runtime/dispatcher.py): `steps_stopped`, and `unattended`
    on every ready step task. The person's own start (run-next, run-step) reads neither."""
    snapshot["steps_stopped"] = steps_mode(ctx) == "stopped"
    for task in snapshot.get("ready") or []:
        if task.get("step_kind"):
            task["unattended"] = unattended(task["step_kind"])


def set_steps_mode(project: str, mode: str, channel=None) -> dict:
    """The brake of the step tasks: `set-mode --agent runtime --mode stopped|autonomous` (ops_config.set_mode hands the runtime agent to
    this). While the runtime is `stopped` the dispatcher starts no step task; the person's own start still runs one. Like an area agent's
    mode, a move down (to `stopped`) is never withheld, from the terminal or the page; a move up is the terminal's, and the page's only
    when its policy lists the group `set-mode`. The mode is not configuration: it is a cursor of the store, so no hash is accepted.
    Returns {"agent", "mode", "unchanged"}."""
    if mode not in MODES:
        raise core.OpsError(f"the runtime's mode is one of {', '.join(MODES)}", 2)
    ctx = core.context(project)
    old = steps_mode(ctx)
    if channel == "page" and old != mode and mode == "autonomous" \
            and not operations.policy_allows("set-mode", channel, ctx["cfg"]["channels"]):
        raise core.OpsError(operations.not_enabled("set-mode", channel), 1)
    if old != mode:
        core._stored(ctx, ctx["store"].cursor_set, MODE_CURSOR, mode)
    return {"agent": steps.OWNER, "mode": mode, "unchanged": old == mode}
