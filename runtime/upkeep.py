#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Upkeep of a runtime meant to run for weeks: retention of what it leaves on disk, and the orphans a crash leaves in docker
(package P-OPS, finding I6). A sibling of the operations layer; the dispatcher's round calls `run_quietly` at its start
(runtime/ops_runs.py), so the work happens on recovery and tick, never in the middle of a task.

What it does, once an hour at most (UPKEEP_EVERY_SECONDS; `<data_dir>/upkeep.json` holds the time of the last pass, and the lock
`upkeep.lock` keeps two processes from running it together):

  1. Run folders. `<data_dir>/task-runs/<run id>/` and `<data_dir>/contained-runs/<n>/` older than `run_retention_days` (a key of
     runtime.json, default 30, 1 to 3650) are removed. Never removed: the folder of a run whose row is `running` or whose task's lock
     is held by a live process (task-<id>.lock, probed shared), a folder younger than the age (its age is the newest modification
     time of the folder and of its entries), the `children` folder (the dispatcher's output files have their own 14 days), a link, and
     the newest `contained-runs` folder (the next number is read from the highest one). The cost and the tokens of a run are rows of
     the store; only what the run left on disk goes, so the usage that costs recompute from a run's own files is unknown for a run
     older than the retention.
  2. Source versions. In the sources folder each source keeps its newest `source_versions_kept` versions (default 5, 2 to 1000: with
     two, a task that is copying the newest while one more is imported still finds it); older version folders
     `<source id>/<n>/` are removed EXCEPT a version a task that is not finished (not `done`, not `cancelled`) received, which the
     rows `task_sources` record with its id, version and sha256 (decision D29). The rows stay: the store never deletes a version's row
     (limit L13), and the number of the next import is the highest recorded one plus one; a pruned version has a row and no folder, and
     nothing reads an old version (a task receives the newest). It runs under the sources lock, takes this host's lease like any
     other writer of the folder (limit L28: a live lease of another host skips it, naming that host), and reaches the folder only
     through the descriptor of `sources.Folder`, with O_NOFOLLOW at every step and a device and inode check before a removal.
  3. Orphan containers, by runtime/orphans.py: containers and networks of runs that no live process holds a lock for, by label or by
     name. The shared proxies are never touched. Skipped without docker, or when OPENHORA_UPKEEP_CONTAINERS is `off`.

Limit L29: this module deletes only inside `data_dir` (run folders) and the sources folder (old versions), never follows a symbolic
link (each folder is opened from its parent's descriptor with O_NOFOLLOW and compared with `os.path.samestat`), and never removes a
run that is live, a version a task that is not finished received, or a shared container.

Standard library only. Runs on Python 3.9: python3 runtime/upkeep.py --help
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orphans  # noqa: E402  (the same folder: the sweep of orphan containers)
import sources  # noqa: E402  (the same folder: the sources folder, its lease and its lock)

UPKEEP_EVERY_SECONDS = 3600
STATE_FILE = "upkeep.json"
LOCK_FILE = "upkeep.lock"
RUNS_DIR, CONTAINED_DIR, CHILDREN_DIR = "task-runs", "contained-runs", "children"   # as runtime/ops_core.py and ops_runs.py name them
FINISHED = ("done", "cancelled")           # the states of a task that cannot run again: a version it received may go
HELD_LOCKS = re.compile(r"(task-\d+|effect-\d+|route)\.lock")
TOTAL_SLOT = re.compile(r"total-\d+\.lock")
CONTAINERS_ENV = "OPENHORA_UPKEEP_CONTAINERS"   # `off`: the sweep of orphan containers is skipped
DAY = 86400.0


# --- descriptors: nothing is followed, nothing is removed that is not what was looked at ----------------------------------------


def _open_dir(parent_fd, name: str, expected=None) -> int:
    """Open a folder by name from its parent's descriptor without following a link, and (with `expected`, the lstat taken before)
    check that it is the same folder: OSError when it is not, or not a folder."""
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or (expected is not None and not os.path.samestat(info, expected)):
            raise OSError("not the folder that was looked at")
    except BaseException:
        os.close(fd)
        raise
    return fd


def remove_in(parent_fd: int, name: str) -> bool:
    """Remove a file, a link (the link itself) or a folder tree by name from the folder `parent_fd`, never following a link; a folder is
    opened with O_NOFOLLOW and compared with its lstat (os.path.samestat) before anything in it is touched. True when it is gone."""
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        try:
            os.unlink(name, dir_fd=parent_fd)
            return True
        except OSError:
            return False
    try:
        sub = _open_dir(parent_fd, name, info)
    except OSError:
        return False
    clean = True
    try:
        try:
            os.fchmod(sub, 0o700)
        except OSError:
            pass
        for child in os.listdir(sub):
            clean = remove_in(sub, child) and clean
    finally:
        os.close(sub)
    if not clean:
        return False
    try:
        os.rmdir(name, dir_fd=parent_fd)
        return True
    except OSError:
        return False


def newest_mtime(parent_fd: int, name: str, info) -> float:
    """The newest modification time of a folder and of its entries (not deeper): a run writes its outputs there."""
    newest = info.st_mtime
    try:
        sub = _open_dir(parent_fd, name, info)
    except OSError:
        return newest
    try:
        for child in os.listdir(sub):
            try:
                newest = max(newest, os.stat(child, dir_fd=sub, follow_symlinks=False).st_mtime)
            except OSError:
                continue
    finally:
        os.close(sub)
    return newest


# --- who holds a lock ------------------------------------------------------------------------------------------------------------


def lock_held(path: str) -> bool:
    """Whether a live process holds the lock file `path` (taken exclusively): probed with a shared lock that is let go at once. A
    file that is not there, or cannot be opened, is not held. Nothing is written in it."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def task_lock_held(data_dir: str, task_id) -> bool:
    return lock_held(os.path.join(data_dir, "locks", f"task-{int(task_id)}.lock"))


def busy(data_dir: str, lab_lock_dir=None) -> bool:
    """Whether any run of this project or any model call of the lab on this machine is in progress, by the locks they hold: a task,
    effect or router lock of the project's locks folder, or a place of the lab's `total` lock (evals/execution.py Slots, around every
    attempt). When the lab's lock folder cannot be found, the answer is True: in doubt, a run is live."""
    folder = os.path.join(data_dir, "locks")
    try:
        if any(HELD_LOCKS.fullmatch(n) and lock_held(os.path.join(folder, n)) for n in os.listdir(folder)):
            return True
    except OSError:
        pass
    if lab_lock_dir is None:
        return True
    try:
        return any(TOTAL_SLOT.fullmatch(n) and lock_held(os.path.join(lab_lock_dir, n)) for n in os.listdir(lab_lock_dir))
    except OSError:
        return True


def lab_lock_dir():
    """The lab's lock folder (through the facade), or None when it cannot be found here."""
    try:
        import lab
        return lab.lock_folder()
    except Exception:  # a checkout without the lab: the caller reads None as busy
        return None


# --- 1. run folders ----------------------------------------------------------------------------------------------------------


def sweep_runs(ctx: dict, *, now: float, days: int, dry_run: bool = False) -> dict:
    """Remove the run folders older than `days`. Returns {"removed": [path], "kept": [{"path", "why"}]} (only the folders that were old
    enough to be looked at are listed in "kept")."""
    cfg, out = ctx["cfg"], {"removed": [], "kept": []}
    try:
        base_fd = os.open(cfg["data_dir"], os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return out
    try:
        for base, numbered in ((RUNS_DIR, True), (CONTAINED_DIR, False)):
            _sweep_base(ctx, base_fd, base, numbered, now, days, dry_run, out)
    finally:
        os.close(base_fd)
    return out


def _sweep_base(ctx, data_fd, base: str, store_rows: bool, now: float, days: int, dry_run: bool, out: dict) -> None:
    cfg = ctx["cfg"]
    try:
        before = os.stat(base, dir_fd=data_fd, follow_symlinks=False)
        base_fd = _open_dir(data_fd, base, before)
    except OSError:
        return
    try:
        names = sorted((n for n in os.listdir(base_fd) if n.isdigit()), key=int)
        newest_number = names[-1] if names else None
        for name in names:
            path = os.path.join(cfg["data_dir"], base, name)
            try:
                info = os.stat(name, dir_fd=base_fd, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISDIR(info.st_mode):
                continue   # a link or a stray file is not a run folder, and is not followed
            if now - newest_mtime(base_fd, name, info) < days * DAY:
                continue
            why = _live(ctx, name) if store_rows else None
            if why is None and not store_rows and name == newest_number:
                why = "the highest number: the next folder is numbered after it"
            if why is not None:
                out["kept"].append({"path": path, "why": why})
            elif dry_run:
                out["removed"].append(path)
            elif remove_in(base_fd, name):
                out["removed"].append(path)
            else:
                out["kept"].append({"path": path, "why": "it could not be removed completely"})
    finally:
        os.close(base_fd)


def _live(ctx: dict, name: str):
    """Why the folder of run `name` must stay (a sentence), or None. A run whose row is `running`, or whose task's lock a live
    process holds, is live; a store that cannot be asked keeps the folder."""
    store, conn = ctx["store"], ctx["conn"]
    try:
        row = store.task_run_get(conn, int(name))
    except store.StoreError:
        return None   # no row: nothing to wait for, the age decides
    except Exception as e:  # a store that does not answer: in doubt, keep
        return f"the store could not be asked ({type(e).__name__})"
    if row.get("status") == "running":
        return "the run is running"
    if task_lock_held(ctx["cfg"]["data_dir"], row["task_id"]):
        return "a live process holds the task's lock"
    return None


# --- 2. source versions ------------------------------------------------------------------------------------------------------


def protected_versions(ctx: dict) -> set:
    """{(source id, version)} that a task which is not finished received (the rows task_sources, decision D29)."""
    store, conn = ctx["store"], ctx["conn"]
    keep = set()
    for task in store.tasks_list(conn):
        if task["state"] in FINISHED:
            continue
        for row in store.task_sources_of(conn, task["id"]):
            keep.add((row["source_id"], row["version"]))
    return keep


def sweep_versions(ctx: dict, *, kept: int, dry_run: bool = False, clock=None) -> dict:
    """Remove the old version folders of every source, keeping the newest `kept` of each and every version a task that is not finished
    received. Returns {"removed": [{"source", "version"}], "kept": [{"source", "version", "why"}], "problem"}. problem is a sentence
    when nothing could be done (no folder, another host's lease, the sources lock busy)."""
    cfg, store, conn = ctx["cfg"], ctx["store"], ctx["conn"]
    out = {"removed": [], "kept": [], "problem": None}
    try:
        with sources.intake.Lock(sources.sources_lock_path(cfg), blocking=False):
            protected = protected_versions(ctx)
            with sources.Folder(cfg) as folder:
                if not dry_run:
                    sources.take_lease(folder, cfg, clock)
                for source in store.sources_list(conn):
                    versions = [v["version"] for v in store.source_versions(conn, source["id"])]
                    old = versions[:-kept] if len(versions) > kept else []
                    if not old:
                        continue
                    try:
                        source_fd = folder.subdir([source["id"]])
                    except sources.SourcesError:
                        continue   # no folder for this source: nothing to remove
                    try:
                        for version in old:
                            if (source["id"], version) in protected:
                                out["kept"].append({"source": source["id"], "version": version,
                                                    "why": "a task that is not finished received it"})
                                continue
                            try:
                                info = os.stat(str(version), dir_fd=source_fd, follow_symlinks=False)
                            except OSError:
                                continue   # already gone
                            if not stat.S_ISDIR(info.st_mode):
                                continue
                            if dry_run or remove_in(source_fd, str(version)):
                                out["removed"].append({"source": source["id"], "version": version})
                            else:
                                out["kept"].append({"source": source["id"], "version": version,
                                                    "why": "it could not be removed completely"})
                    finally:
                        os.close(source_fd)
    except BlockingIOError:
        out["problem"] = "the sources lock is held by an import: versions are looked at on the next pass"
    except sources.SourcesError as e:
        out["problem"] = f"the sources folder was not touched: {e}"
    return out


# --- 3. the whole pass -------------------------------------------------------------------------------------------------------


def _state_path(cfg: dict) -> str:
    return os.path.join(cfg["data_dir"], STATE_FILE)


def last_pass(cfg: dict):
    """The POSIX time of the last pass, or None."""
    try:
        with open(_state_path(cfg), encoding="utf-8") as f:
            value = json.load(f).get("at")
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    except (OSError, ValueError, AttributeError):
        return None


def _write_state(cfg: dict, now: float, summary: dict) -> None:
    temporary = f"{_state_path(cfg)}.{os.getpid()}.new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"at": now, **summary}, f)
    os.replace(temporary, _state_path(cfg))


def containers_enabled() -> bool:
    return os.environ.get(CONTAINERS_ENV, "").strip().lower() not in ("off", "0", "no", "false")


def run(ctx: dict, *, now=None, force: bool = False, tool=None, lab_locks="auto", clock=None) -> dict:
    """One pass of upkeep for the project of `ctx`. Returns {"skipped": why} when it is too soon or another process is at it, else
    {"runs", "versions", "containers", "at"}; a part that failed reports {"problem"}. It raises nothing (a pass that fails is tried again
    at the next hour). `tool` is the container tool (None: docker, if there is one and the sweep is enabled), `lab_locks` the lab's lock
    folder ("auto": asked of the lab)."""
    cfg = ctx["cfg"]
    now = time.time() if now is None else now
    try:
        os.makedirs(os.path.join(cfg["data_dir"], "locks"), mode=0o700, exist_ok=True)
        lock = sources.intake.Lock(os.path.join(cfg["data_dir"], "locks", LOCK_FILE), blocking=False)
        lock.__enter__()
    except BlockingIOError:
        return {"skipped": "another process is doing the upkeep"}
    except OSError as e:
        return {"skipped": f"the upkeep lock cannot be taken: {e.strerror}"}
    try:
        previous = last_pass(cfg)
        if not force and previous is not None and 0 <= now - previous < UPKEEP_EVERY_SECONDS:
            return {"skipped": "done less than an hour ago"}
        summary = {}
        for key, part in (("runs", lambda: sweep_runs(ctx, now=now, days=cfg.get("run_retention_days", 30))),
                          ("versions", lambda: sweep_versions(ctx, kept=cfg.get("source_versions_kept", 5), clock=clock)),
                          ("containers", lambda: _containers(cfg, now, tool, lab_locks))):
            try:
                summary[key] = part()
            except Exception as e:  # one failing part does not stop the others
                summary[key] = {"problem": f"{type(e).__name__}: {e}"}
        _write_state(cfg, now, {k: _counts(v) for k, v in summary.items()})
        return {**summary, "at": now}
    except OSError as e:
        return {"skipped": f"the upkeep could not record its pass: {e.strerror}"}
    finally:
        lock.release()


def _counts(part: dict) -> dict:
    return {"removed": len(part.get("removed") or []), "kept": len(part.get("kept") or []), "problem": part.get("problem")}


def _containers(cfg: dict, now: float, tool, lab_locks) -> dict:
    if tool is None:
        if not containers_enabled():
            return {"removed": [], "kept": [], "problem": None, "disabled": True}
        import shutil
        if shutil.which("docker") is None:
            return {"removed": [], "kept": [], "problem": None, "disabled": True}
        import lab
        tool = lab.container_tool
    locks = lab_lock_dir() if lab_locks == "auto" else lab_locks
    return orphans.sweep(tool, now=now, busy=busy(cfg["data_dir"], locks))


def run_quietly(ctx: dict) -> dict:
    """run() for the dispatcher's round: anything it raises is returned as a skip, never to the round."""
    try:
        return run(ctx)
    except Exception as e:  # the round must never fail for upkeep
        return {"skipped": f"{type(e).__name__}: {e}"}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0
    print("error: upkeep is run by the dispatcher's round (runtime/ops_runs.py); see --help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
