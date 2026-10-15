#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The runs of tasks: one task run (`run_task`), the person's verb that picks one (`run_next`), the dispatcher's round
(`dispatch`), and the processes the round starts.

A sibling of runtime/ops.py, which exposes `run_next`, `run_task`, `dispatch` and `reap` under their names; no shell
imports this file. The names every module of the layer shares are read as `core.<name>` (runtime/ops_core.py); the
helpers of a run that stay in runtime/ops.py (`_prepare_run`, `_run_start`, `_run_body`, `_snapshot`, ...) are reached at
call time through `_ops()`, never imported at module level.

Every task run is its own OS process: `run-task --project <dir> --task <id>` (runtime/cli.py). The lab's session ends
every container of its process and `ops._key_in_environment` writes the environment, so two runs in one process would
end each other. A run holds the task's lock (task-<id>.lock) from before its claim to after its finish: a task that is
`running` in the store whose lock can be taken is an orphan (`_recover`). Admission, the claim and the run row happen
under the claim lock (`_start`), by one pure function, runtime/parallel.py `admit`. The dispatcher decides a list of
starts and starts each as a child process with its output in files; with `wait` it keeps reaping and deciding until no
child of its own is alive (a scheduler's job kills what it leaves), without it the caller (the local service) returns
at once and reaps on every tick.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

import ops_core as core
import ops_waits
import autonomy
import dispatcher
import documents
import lab
import parallel
import skill_meta
import upkeep

REFUSED_CURSOR = "dispatch:refused"    # the store's cursor: {task id: {"reason", "at"}}, the children that were refused or crashed
REPORTED_CURSOR = "dispatch:reported"  # the store's cursor: {"low": run id, "seen": [run ids]}, the finished runs already reported
REFUSED_FOR = 120.0                    # seconds a task a child could not start is held `could not start`
CHILDREN_DIR = "children"              # <data_dir>/task-runs/children/: the output files of the children
CHILDREN_KEPT_DAYS = 14                # days the output files of the children are kept
WAIT_RECHECK = 30.0                    # seconds after which a waiting round decides again although no child ended
WAIT_STEP = 0.5                        # seconds between two looks at the children of a waiting round
STOP_GRACE = 30.0                      # seconds the children get after TERM before KILL: their own clean-up (containers) takes a few
EXIT_REFUSED = 4                       # the exit code of `run-task` for a task that was refused and not run

SPAWNED = []                           # [(project, task id, Popen)] this process started
SPAWNED_LOCK = threading.RLock()       # every access holds it (re-entrant: a signal handler may arrive while it is held)
STOPPING = threading.Event()           # set: no child starts any more (stop_runs, a signal on a waiting round)


def _ops():
    """runtime/ops.py, found at call time: the helpers of a run and of the round stay there."""
    return importlib.import_module("ops")


def _same(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


# --- what a task is, for the rules of the slots -------------------------------------------------------------------------


def skill_facts(skill, cache: dict) -> tuple:
    """(footprint, code) of a skill: the files its tasks may write (runtime/parallel.py footprint) and whether its tasks are
    code tasks (ops.code_task). A skill that cannot be read has an empty footprint and is no code task; the run fails to
    start with its reason later. Kept in `cache` for one call."""
    if skill not in cache:
        found = (frozenset(), False)
        if skill:
            folder = os.path.join(core.ROOT, "skills", skill)
            try:
                found = (parallel.footprint(folder), bool(_ops().code_task(skill_meta.declared(folder))))
            except skill_meta.SkillError:
                pass
        cache[skill] = found
    return cache[skill]


def item_of(task: dict, cache: dict) -> dict:
    """The task as runtime/parallel.py reads it: {"id", "agent", "request_id", "code", "footprint"}."""
    footprint, code = skill_facts(task.get("skill"), cache)
    return {"id": task["id"], "agent": task.get("agent"), "request_id": task.get("parent_id"), "code": code,
            "footprint": footprint}


def running_items(ctx: dict, cache: dict) -> list:
    """Every task in state `running`, as item_of gives it."""
    return [item_of(row["task"], cache) for row in core._stored(ctx, ctx["store"].task_running_list)]


def effect_items(ctx: dict) -> list:
    """The effects that execute now, as items of `running` that admit reads: a code entry of the request, with no footprint
    and no slot (`"effect": True`). A code task of that request waits for the effect to end (PAR-6)."""
    return [{"id": -rid, "agent": None, "request_id": rid, "code": True, "footprint": frozenset(), "effect": True}
            for rid in sorted(core._effects_running(ctx["cfg"]))]


def running_and_effects(ctx: dict, cache: dict) -> list:
    """running_items plus effect_items: what admit weighs a task against."""
    return running_items(ctx, cache) + effect_items(ctx)


def code_running(ctx: dict, request_id) -> bool:
    """Whether a code task of this request is `running` now."""
    return any(i["code"] and i["request_id"] == request_id for i in running_items(ctx, {}))


# --- the liveness of a run: recovery ------------------------------------------------------------------------------------

ORPHAN_NOTE = "the run was interrupted before it ended; retry the task"


def _drop_task_locks(ctx: dict) -> list:
    """Delete the lock file of every task or request that ended `done` or `cancelled` (or that the store no longer has; an `effect-<request id>.lock` goes with its request), under its own
    lock: a file whose lock is held (a process still finishing the task) stays, and `_try_lock` locks again a file that was
    deleted between its open and its lock. A task that can run again (`ready`, `running`, `waiting`, `failed`...) keeps its
    file. Returns the task ids whose file went (PAR-6: the files were never deleted before)."""
    cfg = ctx["cfg"]
    try:
        names = [n for n in os.listdir(core._locks_dir(cfg)) if re.fullmatch(r"(task|effect)-\d+\.lock", n)]
    except OSError:
        return []
    if not names:
        return []
    states = {t["id"]: t["state"] for t in core._stored(ctx, ctx["store"].tasks_list)}
    dropped = []
    for name in names:
        task_id = int(name[name.index("-") + 1:-len(".lock")])  # a task's id, or a request's for an effect lock
        if states.get(task_id) not in (None, "done", "cancelled"):
            continue
        fd = core._try_lock(cfg, name)
        if fd is None:
            continue
        try:
            # INVARIANT: the unlink is the holder's last action before it closes the descriptor (`_try_lock` relies on it)
            os.unlink(os.path.join(core._locks_dir(cfg), name))
            dropped.append(task_id)
        except OSError:
            pass
        finally:
            os.close(fd)
    return dropped


def _recover(ctx: dict, holding_route: bool = False) -> dict:
    """End what dead processes left. A task `running` in the store whose lock (task-<id>.lock) can be taken has no live
    holder: it is an orphan, and so is every run row of the router in progress when route.lock can be taken (or when the
    caller holds it itself: holding_route). The descriptors taken stay open until the store has ended them, so that no
    process claims a task meanwhile. Returns {"tasks": [ids], "runs": [ids]} as the store ended them; the waits are
    derived again after."""
    cfg, store = ctx["cfg"], ctx["store"]
    held, tasks, runs = [], [], []
    _drop_task_locks(ctx)
    try:
        for row in core._stored(ctx, store.task_running_list):
            fd = core._try_lock(cfg, f"task-{row['task']['id']}.lock")
            if fd is not None:
                held.append(fd)
                tasks.append(row["task"]["id"])
        router = [r["id"] for r in core._stored(ctx, store.task_runs_running)
                  if core._stored(ctx, store.task_get, r["task_id"])["parent_id"] is None]
        if router:
            if holding_route:
                runs = router
            else:
                fd = core._try_lock(cfg, "route.lock")
                if fd is not None:
                    held.append(fd)
                    runs = router
        if not tasks and not runs:
            return ops_waits.settled(ctx, {"tasks": [], "runs": []})
        return ops_waits.settled(ctx, core._stored(ctx, store.task_fail_orphans, tasks, runs, ORPHAN_NOTE))
    finally:
        for fd in held:
            os.close(fd)


# --- one task run -----------------------------------------------------------------------------------------------------


def run_task(project: str, task_id: int, requested=None, checked: bool = True) -> dict:
    """Run one named task in this process: take its lock, end what dead processes left, admit and claim it under the claim
    lock, run it, write back the documents it returned. What it returns is what `run_next` returns; a refusal is
    {"ran": None, "reason", "held"} (held: the reason is one of the words of the held tasks, not an error). `checked`
    false is the person's own start: the daily caps are not asked, the rest is. `requested` is the model the person asked
    for this run (a checked id or "auto", ops_models.check_word), which wins over the request's, the task's, the agent's and the
    project's default."""
    ctx = core.context(project)
    cfg = ctx["cfg"]
    with core._task_lock(cfg, task_id):
        recovered = _recover(ctx)
        started = _start(ctx, task_id, requested, checked)
        if started.get("ran", True) is None:
            return {**started, "recovered": recovered["tasks"], "pending": len(core._stored(ctx, ctx["store"].pending_list))}
        out = {**_ops()._run_body(ctx, started), "recovered": recovered["tasks"]}
        if documents.enabled(cfg):
            with core._write_lock(cfg, wait=None):
                out["documents"] = _ops()._push_after_run(ctx, out)
        return out


def _start(ctx: dict, task_id: int, requested, checked: bool) -> dict:
    """Admit, claim and open the run row of one task, under the claim lock. The slow work (the task, its skill, the secret
    store, the routing) is done before the lock. Returns the run's start (what ops._run_body takes), or a refusal
    {"ran": None, "reason", "held"}."""
    ops, cfg, store = _ops(), ctx["cfg"], ctx["store"]
    try:
        task = store.task_get(ctx["conn"], task_id)
    except store.StoreError:
        task = None
    keys = core._keys()
    prepared, failure = None, None
    if task is not None and task["parent_id"] is not None and task.get("skill") and task["state"] == "ready":
        try:
            prepared = ops._prepare_run(ctx, task, requested, keys)
        except ops.PREPARE_ERRORS as e:
            failure = e
    with core._claim_lock(cfg):
        if task is not None and task.get("skill") and documents.enabled(cfg):
            try:
                stopped = documents.blocked(ctx, skill_meta.declared(os.path.join(core.ROOT, "skills", task["skill"])))
            except skill_meta.SkillError:
                stopped = []  # the run fails to start below, with its reason
            if stopped:
                return {"ran": None, "reason": "a document was edited on the platform and was not taken", "held": False,
                        "task": task_id, "documents": stopped}
        if task is not None and task["state"] == "ready" and task["parent_id"] is not None:
            cache = {}
            running = [r for r in running_and_effects(ctx, cache) if r["id"] != task_id]
            holders = core._stored(ctx, store.task_slot_holders)
            if checked and prepared is not None and task.get("agent") in cfg["area_agents"]:
                found = ops._agents_of_the_day(ctx, keys).get(task["agent"])
                if found is not None:
                    ok, why = autonomy.may_start(task["agent"], cfg["area_agents"], found["facts"], found["spent"],
                                                 prepared["routing"]["billing"])
                    if not ok:
                        return {"ran": None, "reason": why, "held": True, "task": task_id}
            ok, why = parallel.admit(item_of(task, cache), running, holders, cfg["area_agents"], cfg["max_running"])
            if not ok:
                return {"ran": None, "reason": why, "held": True, "task": task_id}
        claimed = core._stored(ctx, store.task_claim, task_id)
        claim = claimed["task"]
        if claim is None:
            reason = "no task is ready" if claimed.get("reason") in (None, "not-ready") else f"task {task_id} is {claimed['reason']}"
            return {"ran": None, "reason": ops_waits.explain(ctx, task_id, reason), "held": False, "task": task_id}
        started = None
        if failure is None:
            try:
                started = ops._run_start(ctx, claim, prepared)
            except ops.PREPARE_ERRORS as e:
                failure = e
        if failure is not None:
            core._stored(ctx, store.task_fail_orphans, [claim["id"]], [], ops._note(f"the run could not start: {failure}"))
            raise core.OpsError(f"task {claim['id']} ({claim['skill']}) could not start: {failure}", 1)
        return {**started, "unattended": checked}   # a task the dispatcher starts is unattended; run-next is the person's own start


def run_next(project: str, requested=None) -> dict:
    """The person's verb: end what dead processes left, read the documents platform, pick the oldest ready task that the
    rules of the slots let in (only to choose; the real check is made under the claim lock) and run it in this process.
    Nothing admissible: {"ran": None, "reason"} naming why. Works on a project with no area agents."""
    ctx = core.context(project)
    cfg, store = ctx["cfg"], ctx["store"]
    recovered = _recover(ctx)
    pulled = None
    if documents.enabled(cfg):
        # Before the task is claimed, so that a refusal leaves no task running (decision D11).
        try:
            with core._write_lock(cfg):
                pulled = documents.pull(ctx)
        except documents.DocumentsError as e:
            return {"ran": None, "reason": "the documents platform could not be read", "detail": str(e),
                    "recovered": recovered["tasks"]}
        except store.StoreError as e:
            raise core.OpsError(str(e), e.code) from None
    cache, waits = {}, ops_waits.waiting_for(ctx)
    ready = [t for t in core._stored(ctx, store.tasks_list) if t["state"] == "ready" and t["parent_id"] is not None
             and t["id"] not in waits]
    chosen, why = None, []
    if ready:
        running = running_and_effects(ctx, cache)
        holders = core._stored(ctx, store.task_slot_holders)
        for task in sorted(ready, key=lambda t: t["id"]):
            ok, word = parallel.admit(item_of(task, cache), running, holders, cfg["area_agents"], cfg["max_running"])
            if ok:
                chosen = task["id"]
                break
            why.append(f"task {task['id']}: {word}")
    if chosen is None:
        reason = "no task is ready" if not ready else "nothing may start now: " + "; ".join(why)
        out = {"ran": None, "reason": ops_waits.explain(ctx, None, reason) if not ready else reason,
               "recovered": recovered["tasks"], "pending": len(core._stored(ctx, store.pending_list))}
        return {**out, "documents": pulled} if pulled is not None else out
    out = run_task(project, chosen, requested=requested, checked=False)
    out["recovered"] = list(dict.fromkeys(recovered["tasks"] + list(out.get("recovered") or [])))
    if pulled is not None:
        if out.get("ran") is None:
            out["pulled"] = pulled  # a refusal keeps its own "documents": the ones not taken
        else:
            out["documents"] = documents.merged(pulled, out.get("documents"))
    return out


# --- the children of a round ------------------------------------------------------------------------------------------------


def _prune(folder: str) -> None:
    """Delete the output files of the children older than CHILDREN_KEPT_DAYS."""
    oldest = time.time() - CHILDREN_KEPT_DAYS * 86400
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and not os.path.islink(path) and os.stat(path).st_mtime < oldest:
                os.unlink(path)
        except OSError:
            pass


def spawn(cfg: dict, project: str, task_id: int):
    """Start `run-task` for one task as a child process in a session of its own, its output in two files of
    <data_dir>/task-runs/children/, and keep it in SPAWNED. The one seam a test replaces. The environment is this
    process's, with every variable a router call is injecting at this moment put back as it was before: a child never
    inherits a key a router call put in, and does inherit one the person exported."""
    folder = os.path.join(cfg["data_dir"], core.RUNS_DIR, CHILDREN_DIR)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    _prune(folder)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    files = []
    try:
        for ext in ("out", "err"):
            files.append(os.open(os.path.join(folder, f"{task_id}-{stamp}.{ext}"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
        with core._ENV_LOCK:
            env = dict(os.environ)
            for name, before in core.ENV_INJECTED.items():
                if before is None:
                    env.pop(name, None)
                else:
                    env[name] = before
        proc = subprocess.Popen([sys.executable, os.path.join(core.ROOT, "runtime", "cli.py"), "run-task", "--project", project,
                                 "--task", str(task_id)], stdout=files[0], stderr=files[1], stdin=subprocess.DEVNULL,
                                start_new_session=True, close_fds=True, env=env)
    finally:
        for fd in files:
            os.close(fd)
    with SPAWNED_LOCK:
        SPAWNED.append((project, task_id, proc))
    return proc


def _refused_read(ctx: dict) -> dict:
    try:
        found = json.loads(core._stored(ctx, ctx["store"].cursor_get, REFUSED_CURSOR) or "{}")
    except ValueError:
        found = {}
    return found if isinstance(found, dict) else {}


def _refused_write(ctx: dict, additions: dict) -> None:
    now = time.time()
    with core._claim_lock(ctx["cfg"]):  # read-then-write: the service and a scheduled job both write it (PAR-6)
        kept = {k: v for k, v in _refused_read(ctx).items()
                if isinstance(v, dict) and now - float(v.get("at") or 0) <= REFUSED_FOR}
        kept.update({str(k): v for k, v in additions.items()})
        core._stored(ctx, ctx["store"].cursor_set, REFUSED_CURSOR, json.dumps(kept, separators=(",", ":")))


def refused_now(ctx: dict) -> dict:
    """{task id: reason} of the children refused or crashed in the last REFUSED_FOR seconds."""
    now = time.time()
    out = {}
    for key, value in _refused_read(ctx).items():
        if isinstance(value, dict) and now - float(value.get("at") or 0) <= REFUSED_FOR and str(key).isdigit():
            out[int(key)] = value.get("reason")
    return out


def reap(project=None) -> list:
    """Drop the children of this process that ended (of one project when given) and return the entries dropped. A child
    that exited 4 (refused, not run), or whose task is still `ready` whatever its exit (it was held by a word under the
    claim lock, or crashed before its claim), is recorded in the cursor `dispatch:refused`, so that the next rounds hold
    the task `could not start` for a while and a waiting round cannot start it again at once. The cursor is written under the claim lock
    by whichever process started the child (the service and a scheduled job both do), so neither loses the other's entries."""
    ended = []
    with SPAWNED_LOCK:
        keep = []
        for entry in SPAWNED:
            if (project is None or _same(entry[0], project)) and entry[2].poll() is not None:
                ended.append(entry)
            else:
                keep.append(entry)
        SPAWNED[:] = keep
    by_project = {}
    for where, task_id, proc in ended:
        code = proc.returncode
        try:
            ctx = core.context(where)
            if code != EXIT_REFUSED and core._stored(ctx, ctx["store"].task_get, task_id)["state"] != "ready":
                continue
            by_project.setdefault(where, (ctx, {}))[1][task_id] = {
                "reason": {EXIT_REFUSED: "refused", 0: "held"}.get(code, "crashed"), "at": time.time()}
        except core.OpsError:
            continue
    returned = ended
    for where, (ctx, additions) in by_project.items():
        try:
            _refused_write(ctx, additions)
        except core.OpsError:  # the claim lock stayed busy: keep the entries for the next reap, never lose a refusal
            back = [e for e in ended if e[0] == where and e[1] in additions]
            with SPAWNED_LOCK:
                SPAWNED.extend(back)
            returned = [e for e in returned if e not in back]
    return returned


def alive(project=None) -> list:
    """The children of this process still running (of one project when given): [(project, task id, Popen)]."""
    with SPAWNED_LOCK:
        return [e for e in SPAWNED if (project is None or _same(e[0], project)) and e[2].poll() is None]


def parallel_state(ctx: dict, tasks: list, cache: dict) -> dict:
    """What a snapshot of the dispatcher adds for the rules of the slots: the tasks `running` and the children started
    and not yet claimed (still `ready`), the slot holders, and the tasks refused or crashed lately. `tasks` are the
    store's rows, as the snapshot read them."""
    store = ctx["store"]
    reap(ctx["cfg"]["project"])  # a child that ended since the last reap is no longer counted as starting
    running = running_and_effects(ctx, cache)
    holding = list(core._stored(ctx, store.task_slot_holders))
    by_id = {t["id"]: t for t in tasks}
    starting = set()
    for _where, task_id, _proc in alive(ctx["cfg"]["project"]):
        task = by_id.get(task_id)
        if task is not None and task["state"] == "ready":
            starting.add(task_id)
            running.append(item_of(task, cache))
            if not any(h["id"] == task_id for h in holding):
                holding.append({"id": task_id, "agent": task.get("agent")})
    return {"running": running, "holding": holding, "refused": refused_now(ctx), "starting": starting}


# --- stopping ---------------------------------------------------------------------------------------------------------------


def _kill_group(pgid: int, sig: int) -> bool:
    """Signal a process group; False when it is gone, or when it is this process's own."""
    if pgid == os.getpgrp():
        return False
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _signal_owner(owner, sig: int) -> bool:
    """Signal the holder of a task lock, (pid, pgid) as it wrote them: its whole group only when it leads it (a child of
    the dispatcher does; a `run-next` started from a shell shares the shell's group, which is never signalled), else its
    pid alone. Never this process's own pid or group."""
    pid, pgid = owner
    if pid == os.getpid():
        return False
    if pid == pgid:
        return _kill_group(pgid, sig)
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def stop_children(only_mine: bool = True, cfg=None, grace: float = STOP_GRACE) -> list:
    """End task runs. only_mine: the children this process started (SPAWNED), each by its own group (the child is the
    leader of its session, so its pid is the group id and cannot be reused before it is reaped). Otherwise, for the
    project of cfg, the process group of every task whose lock is held by a live process (the group id its holder wrote:
    a lock that is free is never signalled). TERM first; after `grace` seconds KILL only those still alive. Returns the
    task ids signalled."""
    signalled = []
    if only_mine:
        with SPAWNED_LOCK:
            mine = [e for e in SPAWNED if e[2].poll() is None]
        for _where, task_id, proc in mine:
            if _kill_group(proc.pid, signal.SIGTERM):
                signalled.append(task_id)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and any(e[2].poll() is None for e in mine):
            time.sleep(0.05)
        for _where, _task_id, proc in mine:
            if proc.poll() is None:
                _kill_group(proc.pid, signal.SIGKILL)
        return signalled
    folder = os.path.join(cfg["data_dir"], core.LOCKS_DIR)
    holders = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not (name.startswith("task-") and name.endswith(".lock") and name[5:-5].isdigit()):
            continue
        task_id = int(name[5:-5])
        fd = core._try_lock(cfg, name)
        if fd is not None:  # nobody holds it: its pgid is stale and is never signalled
            os.close(fd)
            continue
        owner = core._lock_owner(cfg, task_id)
        if owner is not None and _signal_owner(owner, signal.SIGTERM):
            holders[task_id] = owner
            signalled.append(task_id)

    def still_held(task_id: int) -> bool:
        fd = core._try_lock(cfg, f"task-{task_id}.lock")
        if fd is None:
            return True
        os.close(fd)
        return False

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(still_held(t) for t in holders):
        time.sleep(0.05)
    for task_id, termed in sorted(holders.items()):
        # read again just before: KILL only a lock that is still held by the very process that got the TERM
        if still_held(task_id) and core._lock_owner(cfg, task_id) == termed:
            _signal_owner(termed, signal.SIGKILL)
    return signalled


def stop(project=None, every: bool = False) -> dict:
    """What `stop_runs` does: set STOPPING (no child starts any more), end the children this process started and the runs
    of the lab in this process. With every and a project, also every task run of the project that a live process holds
    (by its lock), whoever started it."""
    STOPPING.set()
    stop_children(only_mine=True)
    if not every:
        return lab.stop_runs()
    if project is None:
        raise core.OpsError("--all names a project", 2)
    ended = stop_children(only_mine=False, cfg=core.context(project)["cfg"])
    return {**lab.stop_runs(), "tasks": ended}


# --- the dispatcher's round -----------------------------------------------------------------------------------------------


def _reported(ctx: dict) -> list:
    """The runs of tasks that ended since the last report, each once: the cursor `dispatch:reported` holds the lowest run id
    that may still end (`low`) and the ids at or above it already reported (`seen`). The first call after an upgrade
    reports no history. Each entry is the dispatcher's `ran` entry, and, for a failed run, its failure as the round reads it."""
    store = ctx["store"]
    try:
        cursor = json.loads(core._stored(ctx, store.cursor_get, REPORTED_CURSOR) or "null")
    except ValueError:
        cursor = None
    if not isinstance(cursor, dict) or not isinstance(cursor.get("low"), int):
        rows = core._stored(ctx, store.task_runs_since, 0)
        core._stored(ctx, store.cursor_set, REPORTED_CURSOR,
                     json.dumps({"low": max([r["id"] for r in rows] or [0]) + 1, "seen": []}, separators=(",", ":")))
        return []
    rows = core._stored(ctx, store.task_runs_since, cursor["low"])
    seen = set(cursor.get("seen") or [])
    fresh = [r for r in rows if r["status"] != "running" and r["id"] not in seen]
    out = []
    for r in fresh:
        entry = {"task_id": r["task_id"], "run_id": r["id"], "status": r["status"], "ending": r.get("ending"), "model": r.get("model")}
        if r["status"] == "failed":
            entry["failure"] = {"kind": r.get("failure"), "reason": r.get("error")}
        out.append(entry)
    if rows:
        running = [r["id"] for r in rows if r["status"] == "running"]
        low = min(running) if running else max(r["id"] for r in rows) + 1
        kept = sorted(i for i in seen | {r["id"] for r in fresh} if i >= low)
        if low != cursor["low"] or kept != sorted(seen):
            core._stored(ctx, store.cursor_set, REPORTED_CURSOR, json.dumps({"low": low, "seen": kept}, separators=(",", ":")))
    return out


def dispatch(project: str, budget_seconds=None, wait: bool = True) -> dict:
    """One round of the dispatcher (see ops.dispatch). Returns {"handlers", "released", "started", "ran", "held",
    "stopped"}; "started" lists the children this round started, "ran" the runs that ended since the last report."""
    ops = _ops()
    ctx = core.context(project)
    cfg = ctx["cfg"]
    with core._dispatch_lock(cfg):
        upkeep.run_quietly(ctx)   # retention and orphan containers, once an hour, before any run of this round (package P-OPS)
        if not cfg["area_agents"]:
            rows = core._stored(ctx, ctx["store"].tasks_list)
            ops._record_held(ctx, [{"task_id": t["id"], "agent": t.get("agent"), "reason": dispatcher.NO_AGENT}
                                   for t in rows if t["state"] == "ready" and t["parent_id"] is not None], [])
            return {"stopped": "no area agent is configured"}
        out = {"handlers": ops._ticks(ctx, project), "released": [], "started": [], "ran": [], "held": [], "stopped": None}
        if wait:
            STOPPING.clear()
        return _round(ctx, project, ops.DISPATCH_BUDGET if budget_seconds is None else budget_seconds, wait, out)


def _round(ctx: dict, project: str, budget: float, wait: bool, out: dict) -> dict:
    ops = _ops()
    began = time.monotonic()
    state = {"keys": core._keys(), "checked": {}, "held": [], "missing": [], "released": [], "first": True}
    mine = []
    previous = _install_handlers() if wait else {}
    try:
        while True:
            started = 0
            reap(project)
            alive_then = len([p for p in mine if p.poll() is None])  # a child that ends after this look is reported by the next pass
            for entry in _reported(ctx):
                out["ran"].append(entry)
                if out["stopped"] is None:
                    out["stopped"] = ops._stops_the_round(entry)
            if out["stopped"] is None and STOPPING.is_set():
                out["stopped"] = "the dispatcher was stopped: no new run starts"
            if out["stopped"] is None:
                started, idle = _pass(ctx, project, out, state, began, budget, mine)
                if started == 0 and out["stopped"] is None and not [p for p in mine if p.poll() is None]:
                    out["stopped"] = idle
            if not wait:
                break
            running = [p for p in mine if p.poll() is None]
            if not running:
                if started or alive_then:
                    continue  # the children ended before they were looked at: report them and decide again
                break
            recheck = time.monotonic() + WAIT_RECHECK  # decide again now and then, whether or not a child ended
            while all(p.poll() is None for p in running) and time.monotonic() < recheck:
                time.sleep(WAIT_STEP)
        return out
    except BaseException:
        if wait:  # a scheduled job never returns while its children are alive
            while [p for p in mine if p.poll() is None]:
                time.sleep(WAIT_STEP)
        raise
    finally:
        _restore_handlers(previous)
        try:
            ops._record_held(ctx, state["held"], state["missing"])
        except core.OpsError:
            pass


def _pass(ctx: dict, project: str, out: dict, state: dict, began: float, budget: float, mine: list) -> tuple:
    """One decision and its starts. Returns (children started, the reason nothing more starts when none did)."""
    ops, cfg = _ops(), ctx["cfg"]
    if ops._configuration_moved(ctx):  # accepted again, or edited, since the round began: a mode may have been narrowed
        out["stopped"] = ("the configuration changed during the round (a mode, a cap or an agent): no new run "
                          "starts; the next round reads it")
        return 0, None
    if state["first"]:
        state["first"] = False
        _recover(ctx)
        if documents.enabled(cfg):
            try:
                with core._write_lock(cfg):
                    documents.pull(ctx)
            except documents.DocumentsError as e:
                out["stopped"] = f"the documents platform could not be read: {e}"
                return 0, None
            except ctx["store"].StoreError as e:
                raise core.OpsError(str(e), e.code) from None
    while True:
        snapshot = ops._snapshot(ctx, state["keys"])
        decided = dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start, parallel.admit)
        out["held"] = decided["held"]
        state["held"] = dispatcher.held_of(snapshot, decided)
        did = ops._mode_releases(ctx, state["released"], snapshot, decided)
        out["released"] += did
        if not decided["start"] and did:
            continue  # a release may have made a task ready
        break
    if not decided["start"]:
        return 0, "nothing may start" if decided["held"] or snapshot["ready"] else "no task is ready"
    started, blocked, first = 0, {}, None
    for position, task_id in enumerate(decided["start"]):
        if STOPPING.is_set():
            out["stopped"] = "the dispatcher was stopped: no new run starts"
            break
        if time.monotonic() - began > budget:
            out["stopped"] = f"the round's budget of {budget} s is spent: no new run starts"
            break
        model, checked = snapshot["model"].get(task_id), state["checked"]
        if model is not None and ("credential", model) not in checked:
            checked[("credential", model)] = ops._credential_stop(model)
        if "image" not in checked:
            checked["image"] = ops._image_stop()
        if checked["image"]:  # no run starts without the image: the rest of the round is held with it
            reason, out["stopped"], state["missing"] = checked["image"]
            state["held"] = dispatcher.held_of(snapshot, decided, {t: reason for t in decided["start"][position:]})
            break
        lacks = checked[("credential", model)] if model is not None else None
        if lacks:  # no run of this model starts; the tasks of the models that have their key go on
            blocked[task_id] = lacks[0]
            first = first or lacks
            continue
        try:
            proc = spawn(cfg, project, task_id)
        except OSError as e:
            out["stopped"] = f"task {task_id} could not be started: {e}"
            break
        mine.append(proc)
        out["started"].append({"task_id": task_id, "started_at": ops._now_iso()})
        started += 1
    if blocked:
        state["held"] = dispatcher.held_of(snapshot, decided, blocked)
        state["missing"] = list(first[2])
        if not started and out["stopped"] is None:
            out["stopped"] = first[1]
    return started, None


def _install_handlers() -> dict:
    """On the main thread: SIGTERM, SIGINT and SIGHUP stop the round's children and the round (the scheduler's job is
    killed with its control group, which would take the children with it: they are ended here, in order). Returns the
    handlers that were there. On any other thread nothing is installed."""
    if threading.current_thread() is not threading.main_thread():
        return {}

    def on_signal(_signum, _frame):
        STOPPING.set()
        stop_children(only_mine=True)

    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[sig] = signal.signal(sig, on_signal)
    return previous


def _restore_handlers(previous: dict) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)
