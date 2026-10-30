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
     is held by a live process (task-<id>.lock, probed shared), the folder of a run whose task or request is not finished or that an open pending
     decision references (a run that ended at a confirmation gate keeps its effect document and its change set here), a folder younger than the age (its age is the newest modification
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
     other writer of the folder, right before the first removal and only when there is one (limit L28: a live lease of another host skips it, naming that host; a pass that removes nothing writes nothing and takes none), and reaches the folder only
     through the descriptor of `sources.Folder`, with O_NOFOLLOW at every step and a device and inode check before a removal.
  3. Held attachments (ATT-1). A file a messaging app brought that waited HELD_DAYS (7) for an answer is deleted and its row ends `expired`; an incoming
     folder (where a fetch is written) older than 24 hours is a crash's leftover and is removed, and so is a folder of `held/` that no held row names and that
     is older than 24 hours. Only inside `<data_dir>/attachments/`, through descriptors with O_NOFOLLOW, and under the attachments lock (an add or a discard
     in progress is not interrupted: the pass looks again an hour later). Limit L48.
  4. Orphan containers, by runtime/orphans.py, in its conservative mode only: a run container that has ended, a key proxy whose run
     container is gone, a network nothing of its run is on, past 30 minutes. A running run container is never removed by a pass; the
     explicit command `python3 runtime/upkeep.py containers --include-running` is the one way, for a stuck one older than 6 hours.
     The harness's shared proxies are never touched. Skipped without docker, when the project's `sweep_orphan_containers` is false in
     runtime.json (a setting a person accepts in the terminal; an environment variable would never reach a scheduler's job), or when
     OPENHORA_UPKEEP_CONTAINERS is `off` (the tests').

Limit L29: this module deletes only inside `data_dir` (run folders and the attachments folder) and the sources folder (old versions), never follows a symbolic
link (each folder is opened from its parent's descriptor with O_NOFOLLOW and compared with `os.path.samestat`), and never removes a
run that is live, a version a task that is not finished received, or a shared container.

Standard library only. Runs on Python 3.9: python3 runtime/upkeep.py --help
"""
from __future__ import annotations

import datetime
import fcntl
import json
import os
import re
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import attachments  # noqa: E402  (the same folder: the hold of the files a messaging app brought)
import lab  # noqa: E402  (the same folder: the lab facade's container tool)
import orphans  # noqa: E402  (the same folder: the sweep of orphan containers)
import sources  # noqa: E402  (the same folder: the sources folder, its lease and its lock)

UPKEEP_EVERY_SECONDS = 3600
STATE_FILE = "upkeep.json"
LOCK_FILE = "upkeep.lock"
RUNS_DIR, CONTAINED_DIR, CHILDREN_DIR = "task-runs", "contained-runs", "children"   # as runtime/ops_core.py and ops_runs.py name them
FINISHED = ("done", "cancelled")           # the states of a task that cannot run again: a version it received may go
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
        open_runs = _open_pending_runs(ctx) if store_rows and names else None
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
            why = _live(ctx, name, open_runs) if store_rows else None
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


def _open_pending_runs(ctx: dict):
    """The run ids that an open pending decision references (a plan, an effect, a review waits on what the run left), or None when the
    store cannot be asked."""
    store, conn = ctx["store"], ctx["conn"]
    try:
        return {p["run_id"] for p in store.pending_list(conn, "open") if p.get("run_id") is not None}
    except Exception:  # a store that does not answer: the caller keeps every folder
        return None


def _live(ctx: dict, name: str, open_runs=None):
    """Why the folder of run `name` must stay (a sentence), or None. A folder stays while anything can still need what the run left in it:
    the run is `running`; a live process holds its task's lock; its task is not finished (not `done` or `cancelled`: a task that waits at a
    confirmation gate keeps its effect document and its change set here, and approving needs them); its request is not finished (a later
    code task of the request builds on the change sets of the earlier runs); an open pending decision references the run. A store that
    cannot be asked keeps the folder. A run with no row has nothing waiting for it: the age decides."""
    store, conn = ctx["store"], ctx["conn"]
    try:
        row = store.task_run_get(conn, int(name))
    except store.StoreError:
        return None
    except Exception as e:  # a store that does not answer: in doubt, keep
        return f"the store could not be asked ({type(e).__name__})"
    if row.get("status") == "running":
        return "the run is running"
    if task_lock_held(ctx["cfg"]["data_dir"], row["task_id"]):
        return "a live process holds the task's lock"
    try:
        task = store.task_get(conn, row["task_id"])
        if task["state"] not in FINISHED:
            return f"its task is {task['state']}, not finished"
        if task.get("parent_id") is not None and store.task_get(conn, task["parent_id"])["state"] not in FINISHED:
            return "its request is not finished"
    except Exception as e:
        return f"the store could not be asked ({type(e).__name__})"
    if open_runs is None:
        open_runs = _open_pending_runs(ctx)
    if open_runs is None:
        return "the store could not be asked about pending decisions"
    if int(name) in open_runs:
        return "an open pending decision references the run"
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
            leased = None
            with sources.Folder(cfg) as folder:
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
                            if not dry_run and leased is None:   # right before the first write, and only when there is one
                                leased = sources.take_lease(folder, cfg, clock)
                                if leased.get("took_over"):
                                    out["lease_took_over"] = leased["took_over"]
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


# --- 3. held attachments (ATT-1) ---------------------------------------------------------------------------------------------


def sweep_attachments(ctx: dict, *, now: float, dry_run: bool = False) -> dict:
    """Delete the files a messaging app brought that waited too long, and the leftovers of a crash. Returns {"expired": [attachment id], "removed":
    [folder name], "kept": [{"name", "why"}], "problem"}. A held row older than HELD_DAYS is decided `expired` (the row stays, the sender's id with it,
    in the store) and its folder deleted; an `incoming/` folder older than INCOMING_KEPT_SECONDS and a `held/` folder no held row names (and as old) are
    removed. Run under the attachments lock, taken without waiting."""
    cfg, store, conn = ctx["cfg"], ctx["store"], ctx["conn"]
    out = {"expired": [], "removed": [], "kept": [], "problem": None}
    try:
        with sources.intake.Lock(attachments.lock_path(cfg), blocking=False):
            cutoff = attachments.iso(datetime.datetime.fromtimestamp(now - attachments.HELD_DAYS * DAY, datetime.timezone.utc))
            for row in store.attachments_list(conn, ["held"], older_than=cutoff):
                if dry_run:
                    out["expired"].append(row["id"])
                    continue
                try:
                    store.attachment_decide(conn, row["id"], "expired")
                except store.StoreError:
                    continue      # decided by someone else meanwhile
                attachments.delete_held(cfg["data_dir"], row["id"])
                out["expired"].append(row["id"])
            waiting = {str(r["id"]) for r in store.attachments_list(conn, ["held"])}
            try:
                data_fd = os.open(cfg["data_dir"], os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            except OSError:
                return out
            try:
                for name, keep in ((attachments.INCOMING, set()), (attachments.HELD, waiting)):
                    _sweep_attachment_folder(data_fd, name, keep, now, dry_run, out)
            finally:
                os.close(data_fd)
    except BlockingIOError:
        out["problem"] = "an add or a discard of an attachment is in progress: the files are looked at on the next pass"
    return out


def _sweep_attachment_folder(data_fd: int, name: str, keep: set, now: float, dry_run: bool, out: dict) -> None:
    """Remove the entries of <data_dir>/attachments/<name> that are not in `keep` and are older than a day (a link or a stray file is removed as itself)."""
    try:
        base_info = os.stat(attachments.FOLDER, dir_fd=data_fd, follow_symlinks=False)
        base_fd = _open_dir(data_fd, attachments.FOLDER, base_info)
    except OSError:
        return
    try:
        folder_info = os.stat(name, dir_fd=base_fd, follow_symlinks=False)
        folder_fd = _open_dir(base_fd, name, folder_info)
    except OSError:
        os.close(base_fd)
        return
    try:
        for entry in sorted(os.listdir(folder_fd)):
            if entry in keep:
                continue
            try:
                info = os.stat(entry, dir_fd=folder_fd, follow_symlinks=False)
            except OSError:
                continue
            newest = newest_mtime(folder_fd, entry, info) if stat.S_ISDIR(info.st_mode) else info.st_mtime
            if now - newest < attachments.INCOMING_KEPT_SECONDS:
                continue
            if dry_run or remove_in(folder_fd, entry):
                out["removed"].append(f"{name}/{entry}")
            else:
                out["kept"].append({"name": f"{name}/{entry}", "why": "it could not be removed completely"})
    finally:
        os.close(folder_fd)
        os.close(base_fd)


# --- 4. the whole pass -------------------------------------------------------------------------------------------------------


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


def run(ctx: dict, *, now=None, force: bool = False, tool=None, clock=None) -> dict:
    """One pass of upkeep for the project of `ctx`. Returns {"skipped": why} when it is too soon or another process is at it, else
    {"runs", "versions", "attachments", "containers", "at"}; a part that failed reports {"problem"}. It raises nothing (a pass that fails is tried again
    at the next hour). `tool` is the container tool (None: docker, if there is one and the sweep is enabled)."""
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
                          ("attachments", lambda: sweep_attachments(ctx, now=now)),
                          ("containers", lambda: _containers(cfg, now, tool))):
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
    out = {"removed": len(part.get("removed") or []), "kept": len(part.get("kept") or []), "problem": part.get("problem")}
    if "expired" in part:
        out["expired"] = len(part["expired"])
    if part.get("lease_took_over"):
        out["lease_took_over"] = part["lease_took_over"]
    return out


def _containers(cfg: dict, now: float, tool, include_running: bool = False, dry_run: bool = False, explicit: bool = False) -> dict:
    """The sweep of orphan containers. The automatic pass (explicit False) is skipped when the project turned it off or the environment says
    `off`; the explicit command (explicit True) is the person's own and always runs. Without a tool: docker, through the lab facade, if it
    is on the PATH."""
    if tool is None:
        if not explicit and (not cfg.get("sweep_orphan_containers", True) or not containers_enabled()):
            return {"removed": [], "kept": [], "problem": None, "disabled": True}
        import shutil
        if shutil.which("docker") is None:
            return {"removed": [], "kept": [], "problem": None, "disabled": True}
        tool = lab.container_tool
    return orphans.sweep(tool, now=now, dry_run=dry_run, include_running=include_running)


def run_quietly(ctx: dict) -> dict:
    """run() for the dispatcher's round: anything it raises is returned as a skip, never to the round."""
    try:
        return run(ctx)
    except Exception as e:  # the round must never fail for upkeep
        return {"skipped": f"{type(e).__name__}: {e}"}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__ + """
Command:
  python3 runtime/upkeep.py containers [--dry-run] [--include-running]
      Sweep the orphan containers of the eval harness now (what the dispatcher's round does by itself, without waiting an hour). With
      --include-running it also removes a RUNNING run container older than 6 hours (a stuck one); nothing else removes a running
      container. --dry-run lists and removes nothing. Prints one JSON object. Exit 0, or 1 when the container tool could not list.
""")
        return 0 if argv else 2
    if argv[0] == "containers" and set(argv[1:]) <= {"--dry-run", "--include-running"}:
        result = _containers({}, time.time(), None, include_running="--include-running" in argv, dry_run="--dry-run" in argv, explicit=True)
        print(json.dumps(result, indent=1))
        return 1 if result.get("problem") or result.get("disabled") else 0
    print("error: unknown arguments; see --help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
