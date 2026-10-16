#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Ending a run that is in progress (R18, limit L41): the process mechanics of a cancel or a stop, with no knowledge of
what a request or a task is. The operations (runtime/ops_cancel.py) write the stop request into the store first and
call this module to end what is running; this module signals, waits, and cleans up what the lab left.

Two kinds of run, two ways to end them:

  A task's run (run-task, run-step, a run-next typed in a terminal) is a process of its own, and the lock it holds
  (task-<id>.lock) says "<pid> <pgid>". `stop_tasks`: a lock nobody holds is never signalled (its text is stale); for a held
  one the process tree below the holder is read first (`snapshot`: `ps`, then the lab run ids that its `docker run` command
  lines name), then the holder gets TERM as ops_runs._signal_owner sends it (its group only when it leads it, never this
  process), the lab's own handler ends the containers of the run and the process exits; if the lock is still held after
  STOP_GRACE seconds the same holder gets KILL (read again just before: only the very process that got TERM), and whatever the
  snapshot named that is still there (the run container, the key proxy, the network) is removed through the container tool,
  each shared object checked again before its removal (runtime/orphans.py `remove_runs`). The descendants are never signalled
  by pid: a pid read from a listing can be another process by the time it is used.

  The router's run happens inside the calling process (runtime/ops.py `_router_call`), so nothing is signalled: `watch` runs a
  thread beside the lab call that reads the request's stop request every STOP_POLL seconds and ends the lab's runs of this
  process (lab.stop_runs), which is safe because the lab guard makes the router the only lab session of the process.

The numbers: STOP_GRACE 30 s (the lab's handler ends containers with `docker rm -f`, releases the key proxy, which has up to
10 s to write its count, and waits its own 5 s grace: about 20 s in the worst case), ROUTER_WAIT 30 s (what the canceller waits
for the router's run row to end), STOP_POLL 1 s.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ops_core as core  # noqa: E402
import ops_runs  # noqa: E402  (_signal_owner: the one way a holder of a task lock is signalled)
import orphans  # noqa: E402

STOP_GRACE = 30.0     # seconds a holder gets after TERM before KILL
ROUTER_WAIT = 30.0      # seconds the canceller waits for the router's run row to end
STOP_POLL = 1.0       # seconds between two reads of the stop request by the watcher
STOP_AGAIN = 10.0     # seconds after which the watcher ends the lab's runs again while the router's call has not returned
NAMES = re.compile(r"wb-eval-(?:run|keys|held)-[0-9a-f]{16}(?![0-9a-f])")   # a run's own objects, as the lab names them


def processes() -> list:
    """[(pid, ppid, pgid, command)] of every process, from `ps` (the one seam a test replaces); [] when it cannot be asked."""
    try:
        done = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,ppid=,pgid=,command="], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in done.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3] if len(parts) > 3 else ""))
    return rows


def snapshot(owner_pid: int, rows=None) -> dict:
    """What runs below a process now: {"pids": the pids of its descendants, "runs": the lab run ids their command lines name}.
    A run id is read from a `wb-eval-run-<id>`, `wb-eval-keys-<id>` or `wb-eval-held-<id>` word of exactly 16 hexadecimal
    characters (orphans.run_of_name); the harness's shared objects carry a 12-character tag and match none."""
    rows = processes() if rows is None else rows
    below, commands = {}, {}
    for pid, ppid, _pgid, command in rows:
        below.setdefault(ppid, []).append(pid)
        commands[pid] = command
    seen, queue = set(), [owner_pid]
    while queue:
        for child in below.get(queue.pop(), ()):
            if child not in seen and child != owner_pid:
                seen.add(child)
                queue.append(child)
    runs = set()
    for pid in seen:
        for name in NAMES.findall(commands.get(pid, "")):
            run = orphans.run_of_name("network" if name.startswith("wb-eval-held-") else "container", name)
            if run:
                runs.add(run)
    return {"pids": sorted(seen), "runs": sorted(runs)}


def held(cfg: dict, task_id: int) -> bool:
    """Whether a live process holds the task's lock: it is taken without waiting and let go at once."""
    fd = core._try_lock(cfg, f"task-{task_id}.lock")
    if fd is None:
        return True
    os.close(fd)
    return False


def stop_tasks(cfg: dict, task_ids, *, tool=None, rows=None, grace: float | None = None, poll: float = 0.05) -> dict:
    """End the runs of these tasks, together. Returns {task id: {"state", "owner", "runs", "removed", "problem"}}: state is
    `free` (nobody held the lock: nothing was signalled), `ended` (the holder exited after TERM), `killed` (it needed KILL) or
    `stopping` (the lock is still held after the grace, e.g. the holder is this process, which is never signalled); owner is
    (pid, pgid) as the holder wrote it or None; runs are the lab run ids the process tree named before TERM; removed lists what
    the container tool removed for them. tool is the container tool (default: the lab facade's); rows is the process listing."""
    grace = STOP_GRACE if grace is None else grace   # read when called, so that a test can shorten it
    ids = sorted({int(t) for t in task_ids})
    out = {t: {"state": "free", "owner": None, "runs": [], "removed": [], "problem": None} for t in ids}
    live = [t for t in ids if held(cfg, t)]
    if not live:
        return out
    owners = {t: core._lock_owner(cfg, t) for t in live}
    listing = processes() if rows is None else rows
    for t in live:   # the tree is read before TERM: afterwards its processes are reparented and can no longer be told apart
        if owners[t] is not None:
            out[t]["owner"] = owners[t]
            out[t]["runs"] = snapshot(owners[t][0], listing)["runs"]
    termed = {t: owners[t] for t in live if owners[t] is not None and ops_runs._signal_owner(owners[t], signal.SIGTERM)}
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(held(cfg, t) for t in live):
        time.sleep(poll)
    for t in live:
        if not held(cfg, t):
            out[t]["state"] = "ended"
            continue
        out[t]["state"] = "stopping"
        if t in termed and core._lock_owner(cfg, t) == termed[t]:   # read again just before: only the process that got TERM
            ops_runs._signal_owner(termed[t], signal.SIGKILL)
            end = time.monotonic() + 5.0
            while time.monotonic() < end and held(cfg, t):
                time.sleep(poll)
            out[t]["state"] = "stopping" if held(cfg, t) else "killed"
    named = sorted({r for t in live for r in out[t]["runs"]})
    if named:
        if tool is None:
            import lab
            tool = lab.container_tool
        cleaned = orphans.remove_runs(tool, named)
        for t in live:
            mine = set(out[t]["runs"])
            out[t]["removed"] = [r for r in cleaned["removed"] if r["run"] in mine]
            out[t]["problem"] = cleaned["problem"]
    return out


@contextlib.contextmanager
def watch(ctx: dict, request_id: int, *, poll: float = STOP_POLL, stop=None):
    """Around the lab call of a router run in this process: a thread reads the request's stop request every `poll` seconds
    (the first read is at once) and, when it is set, ends the lab's runs of this process (`stop`, default lab.stop_runs), again
    every STOP_AGAIN seconds while the call has not returned. The router's call fails then, and its finish reads the stop request
    itself. The thread has a connection of its own and never raises into the call."""
    store, cfg = ctx["store"], ctx["cfg"]
    done = threading.Event()

    def end_lab_runs():
        if stop is not None:
            stop()
            return
        import lab
        lab.stop_runs()

    def loop():
        try:
            conn = store.open_db(cfg["store_db"])
        except Exception:
            return
        last = None
        try:
            while not done.is_set():
                try:
                    if store.stop_of(conn, request_id) is not None and (last is None or time.monotonic() - last >= STOP_AGAIN):
                        last = time.monotonic()
                        end_lab_runs()
                except Exception:   # a read that fails is read again at the next turn
                    pass
                done.wait(poll)
        finally:
            conn.close()

    thread = threading.Thread(target=loop, name=f"stop-watch-{request_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=poll + 10.0)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
