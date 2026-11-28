#!/usr/bin/env python3
"""The one-time move of the old data and cache folders of the workbench to the folders named openhora (T47).

Usage:
  python3 scripts/rename_move.py [--project <dir>]... [--yes] [--platform darwin|other]

Without --yes it lists what it would do and changes nothing. With --yes it plans again, refuses when anything blocks, and
then moves, deletes and removes the empty old folders, in that order. Run it again after an error: it continues from
what is left.

The folders (--platform defaults to the one this machine runs):
  data   darwin: ~/Library/Application Support/ai-workbench -> openhora
         other:  $XDG_DATA_HOME (an absolute path) or ~/.local/share, then ai-workbench -> openhora
  cache  $XDG_CACHE_HOME or ~/.cache, then ai-workbench -> openhora
  The agent files ($SCHEDULER_AGENTS_DIR or ~/Library/LaunchAgents) and the unit files ($SCHEDULER_UNITS_DIR, or
  $XDG_CONFIG_HOME/systemd/user, or ~/.config/systemd/user) are looked at, never changed.

The plan:
  1. delete  an old Notion ledger (documents-notion.json or issue-tracker-notion.json, with its lock files) in the old data folder
             (decision 13) only when it reads as a ledger and holds no pending key (a pending key guards against a duplicate page);
             any other is moved like a file. The plan lists, for each, its counts of done, pending and other entries, never its content;
  2. ledgers the cache folder still holds (publisher-linkedin.json and vcs-github.json, with their lock files): moved to the
             new data folder when neither data folder holds that name, else to the new cache folder like any other entry;
  3. move    every other entry of each old folder to the same place in its new folder; a folder present in both is merged
             entry by entry;
  4. remove  each old folder, and each folder the merge emptied, once it is empty.

What blocks (nothing is moved, exit 1; each blocker has a path, why and fix):
  a job still scheduled under the old name; a job record in the old home that is scheduled or running; a lock a process
  holds (checked again right before the renames); a file present in both folders; an old folder that is a symbolic link or
  cannot be read; an old and a new folder on different devices; a project data folder under the old runtime/ that no
  --project names (there is no way to skip one); a --project with no readable docs/workbench/runtime.json; a --project
  whose runtime.json holds, at any depth, a path (relative, ~ and $HOME expanded) into an old folder.
A move that fails part way (a nested mount, a full disk) can be run again: it continues from what is left.

Output: JSON on stdout (mode, folders, move, delete, remove_empty, blockers, done, next); a summary on stderr.
Exit 0: nothing blocks (the list) or the move finished. 1: something blocks, or an error stopped the move. 2: usage.
It never runs launchctl or systemctl and writes nothing outside the folders named above.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import sys
from pathlib import Path

OLD_NAME = "ai-workbench"
NEW_NAME = "openhora"
OLD_LABEL_PREFIX = "dev.ai-workbench.scheduler."
NOTION_LEDGERS = ("documents-notion.json", "issue-tracker-notion.json")
CACHE_LEDGERS = ("publisher-linkedin.json", "vcs-github.json")
UNFINISHED = ("scheduled", "running")
NEXT = [
    "accept again the configuration of each project whose runtime.json you changed",
    "schedule each job you still want again, through its dry run and the gate",
    "if a move fails part way (a nested mount, a full disk), run this command again: it continues from what is left",
]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def device_of(path: Path) -> int:
    """The device of `path`, or of its nearest parent that exists."""
    current = Path(os.path.abspath(path))
    while not os.path.lexists(current) and current != current.parent:
        current = current.parent
    return os.stat(current).st_dev


def is_dir(path: Path) -> bool:
    return os.path.isdir(path) and not os.path.islink(path)


def folder_pairs(platform: str) -> list:
    home = Path.home()
    if platform == "darwin":
        data_base = home / "Library" / "Application Support"
    else:
        data = os.environ.get("XDG_DATA_HOME")
        data_base = Path(data) if data and os.path.isabs(data) else home / ".local" / "share"
    cache = os.environ.get("XDG_CACHE_HOME")
    cache_base = Path(cache) if cache else home / ".cache"
    return [("data", data_base / OLD_NAME, data_base / NEW_NAME), ("cache", cache_base / OLD_NAME, cache_base / NEW_NAME)]


def scheduler_dirs() -> list:
    """(kind, folder) of the agent and unit folders that exist."""
    home = Path.home()
    agents = os.environ.get("SCHEDULER_AGENTS_DIR")
    units = os.environ.get("SCHEDULER_UNITS_DIR")
    config = os.environ.get("XDG_CONFIG_HOME")
    found = [("launchd", Path(agents) if agents else home / "Library" / "LaunchAgents"),
             ("systemd", Path(units) if units else (Path(config) if config else home / ".config") / "systemd" / "user")]
    return [(kind, folder) for kind, folder in found if is_dir(folder)]


def is_notion_ledger_file(name: str) -> bool:
    return any(name == ledger or name.startswith(ledger + ".") for ledger in NOTION_LEDGERS)


def cache_ledger_of(name: str):
    for ledger in CACHE_LEDGERS:
        if name == ledger or name.startswith(ledger + "."):
            return ledger
    return None


def ledger_counts(path: Path):
    """{"done", "pending", "other"} entry counts of a Notion ledger file, or None when it is not a readable ledger (not JSON, not an
    object with an "entries" object). Only counts leave this function: never a key, never an entry."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return None
    counts = {"done": 0, "pending": 0, "other": 0}
    for entry in data["entries"].values():
        status = entry.get("status") if isinstance(entry, dict) else None
        counts[status if status in ("done", "pending") else "other"] += 1
    return counts


def string_values(value, trail=""):
    """(path of the key, string) for every non-empty string in a JSON value, nested objects and lists included: a.b, a.list[1].c."""
    if isinstance(value, str):
        if value:
            yield trail, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from string_values(item, f"{trail}.{key}" if trail else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from string_values(item, f"{trail}[{index}]")


def lock_held(path: Path) -> bool:
    """Whether a process holds an exclusive lock on `path`. The file is opened read-only and never created."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            return exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


class Plan:
    def __init__(self, platform: str, projects: list):
        self.pairs = folder_pairs(platform)
        self.platform = platform
        self.projects = projects
        self.moves: list = []
        self.deletes: list = []
        self.remove_empty: list = []
        self.blockers: list = []
        self.ledgers: list = []
        self.notes: list = []
        self.ledger_action: dict = {}
        self.referenced: list = []
        self.cross_device_checked: set = set()

    def blocker(self, path, why: str, fix: str) -> None:
        self.blockers.append({"path": str(path), "why": why, "fix": fix})

    def old_of(self, kind: str) -> Path:
        return next(old for k, old, _ in self.pairs if k == kind)

    def new_of(self, kind: str) -> Path:
        return next(new for k, _, new in self.pairs if k == kind)

    # --- the plan -------------------------------------------------------------------------------

    def names(self, folder: Path) -> list:
        """The sorted names in a folder; a folder that cannot be read is a blocker and holds no names."""
        try:
            return sorted(os.listdir(folder))
        except OSError:
            self.blocker(folder, "this folder cannot be read", "fix its permissions, then run this again")
            return []

    def build(self) -> "Plan":
        for kind, old, new in self.pairs:
            if os.path.islink(old):
                self.blocker(old, "the old folder is a symbolic link",
                             f"replace it with the real folder (or move what it points to by hand), then run this again; {new} is where it goes")
            elif is_dir(old):
                self.check_device(old, new)
                self.walk(kind, old, new, top=True)
                self.remove_empty.append(str(old))
        self.check_schedulers()
        self.check_jobs()
        self.blockers.extend(self.lock_blockers())
        self.check_projects()
        self.check_runtime_folders()
        return self

    def check_device(self, old: Path, new: Path) -> None:
        key = (str(old), str(new))
        if key in self.cross_device_checked:
            return
        self.cross_device_checked.add(key)
        if device_of(old) != device_of(new):
            self.blocker(old, "a rename cannot cross devices",
                         f"put {new} on the same device as {old}, or move the folder by hand, then run this again")

    def notion_ledger_action(self, old: Path, base: str) -> str:
        """"delete" or "move" for a Notion ledger and its locks: delete only a ledger that reads as one and holds no pending key."""
        if base in self.ledger_action:
            return self.ledger_action[base]
        path = old / base
        if not os.path.isfile(path) or os.path.islink(path):
            action = "delete"          # locks with no ledger beside them hold nothing
        else:
            counts = ledger_counts(path)
            if counts is None:
                self.ledgers.append({"path": str(path), "unreadable": True, "action": "move"})
                self.notes.append(f"{base} is not a readable ledger: it is moved, not deleted")
                action = "move"
            else:
                action = "delete" if counts["pending"] == 0 else "move"
                self.ledgers.append({"path": str(path), **counts, "action": action})
                if action == "move":
                    self.notes.append(f"{base} holds {counts['pending']} pending key(s) that guard against a duplicate page: it is moved, not deleted")
        self.ledger_action[base] = action
        return action

    def walk(self, kind: str, old: Path, new: Path, top: bool) -> None:
        for name in self.names(old):
            src, dst = old / name, new / name
            if top and kind == "data" and is_notion_ledger_file(name):
                base = next(l for l in NOTION_LEDGERS if name == l or name.startswith(l + "."))
                if os.path.isfile(src) and not os.path.islink(src) and self.notion_ledger_action(old, base) == "delete":
                    self.deletes.append({"path": str(src), "why": "the old Notion test ledger holds no pending key (decision 13)"})
                    continue
            if top and kind == "cache" and cache_ledger_of(name):
                target = self.cache_ledger_target(name)
                if target is not None:
                    self.check_device(old, target.parent)
                    self.add_move(src, target)
                    continue
            if is_dir(src) and is_dir(dst):
                self.walk(kind, src, dst, top=False)
                self.remove_empty.append(str(src))
            else:
                self.add_move(src, dst)

    def cache_ledger_target(self, name: str):
        """The new data folder's path of a cache ledger file, or None when it goes to the new cache folder."""
        ledger = cache_ledger_of(name)
        old_data, new_data = self.old_of("data"), self.new_of("data")
        if os.path.lexists(old_data / ledger) or os.path.lexists(new_data / ledger):
            return None
        return new_data / name

    def add_move(self, src: Path, dst: Path) -> None:
        if os.path.lexists(dst):
            self.blocker(dst, "both folders hold this file", "compare the two copies and keep one, then run this again")
            return
        self.moves.append({"from": str(src), "to": str(dst)})

    # --- what blocks ----------------------------------------------------------------------------

    def check_schedulers(self) -> None:
        for kind, folder in scheduler_dirs():
            for name in self.names(folder):
                if not name.startswith(OLD_LABEL_PREFIX):
                    continue
                path = folder / name
                job_id = name[len(OLD_LABEL_PREFIX):].rsplit(".", 1)[0]
                label = name.rsplit(".", 1)[0]
                cancel = (f"cancel it with the scheduler of a checkout before this change (python3 providers/scheduler/{kind}.py "
                          f"cancel --id {job_id} --confirmed), or remove it: ")
                if kind == "launchd":
                    fix = cancel + f"launchctl bootout gui/<uid>/{label} and delete {path}"
                else:
                    fix = cancel + (f"systemctl --user disable --now {label}.timer, delete the .service and .timer files, "
                                    "systemctl --user daemon-reload")
                self.blocker(path, "a job is still scheduled under the old name", fix)

    def check_jobs(self) -> None:
        jobs = self.old_of("data") / "scheduler"
        if not is_dir(jobs):
            return
        for name in self.names(jobs):
            record = jobs / name / "job.json"
            if not os.path.isfile(record):
                continue
            fix = "cancel or resolve it with the scheduler of a checkout before this change, then run this again"
            try:
                status = json.loads(record.read_text(encoding="utf-8")).get("status")
            except (OSError, ValueError, AttributeError):
                self.blocker(record, "a job record in the old home cannot be read", fix)
                continue
            if status in UNFINISHED:
                self.blocker(record, "a job record in the old home is not finished", fix)

    def lock_blockers(self) -> list:
        """A blocker for each lock a process holds now: the ones directly in an old folder and each job's run.lock."""
        candidates = []
        for kind in ("data", "cache"):
            old = self.old_of(kind)
            if is_dir(old):
                candidates += [old / n for n in self.names(old) if n.endswith(".lock")]
        jobs = self.old_of("data") / "scheduler"
        if is_dir(jobs):
            candidates += [jobs / n / "run.lock" for n in self.names(jobs)]
        found = []
        for path in candidates:
            if os.path.isfile(path) and not os.path.islink(path) and lock_held(path):
                found.append({"path": str(path), "why": "a process holds this lock",
                              "fix": "stop the service, the messaging bridge and any provider run, then run this again"})
        return found

    def check_runtime_folders(self) -> None:
        """Every project data folder under the old runtime/ must be named by a --project (some value of its runtime.json is that folder or
        inside it), or the move would leave that project pointing at an empty folder."""
        runtime = self.old_of("data") / "runtime"
        if not os.path.lexists(runtime):
            return
        fix = "pass --project <dir> for the project whose docs/workbench/runtime.json names it (there is no way to skip one)"
        why = "the old folder holds a project data folder that no --project names"
        if not is_dir(runtime):
            self.blocker(runtime, why, fix)
            return
        base = os.path.normpath(str(runtime))
        for name in self.names(runtime):
            folder = os.path.join(base, name)
            if not any(ref == base or ref == folder or ref.startswith(folder + os.sep) for ref in self.referenced):
                self.blocker(folder, why, fix)

    def check_projects(self) -> None:
        olds = {kind: self.old_of(kind) for kind in ("data", "cache")}
        for project in self.projects:
            record = Path(project) / "docs" / "workbench" / "runtime.json"
            if not os.path.isfile(record):
                self.blocker(project, "this project has no readable docs/workbench/runtime.json",
                             "give the project folder that holds docs/workbench/runtime.json")
                continue
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if not isinstance(data, dict):
                self.blocker(record, "this project's runtime.json cannot be read", "fix or restore it, then run this again")
                continue
            for key, value in string_values(data):
                expanded = os.path.expanduser(os.path.expandvars(value))
                resolved = os.path.normpath(expanded if os.path.isabs(expanded) else os.path.join(str(project), expanded))
                for kind, old in olds.items():
                    new_base = os.path.normpath(str(self.new_of(kind)))
                    if resolved == new_base or resolved.startswith(new_base + os.sep):   # already updated: it names the folder all the same
                        self.referenced.append(os.path.normpath(str(old)) + resolved[len(new_base):])
                    base = os.path.normpath(str(old))
                    if resolved == base or resolved.startswith(base + os.sep):
                        self.referenced.append(resolved)
                        new_path = str(self.new_of(kind)) + resolved[len(base):]
                        self.blocker(value, f"{key} of this project points into the old folder",
                                     f"stop the service, set {key} to {new_path}, run this again, then accept the "
                                     "configuration again as the service asks")

    # --- the report -----------------------------------------------------------------------------

    def report(self, mode: str) -> dict:
        return {
            "mode": mode,
            "folders": [{"kind": kind, "from": str(old), "to": str(new), "exists": os.path.lexists(old)} for kind, old, new in self.pairs],
            "move": self.moves,
            "delete": self.deletes,
            "ledgers": self.ledgers,
            "notes": self.notes,
            "remove_empty": self.remove_empty,
            "blockers": self.blockers,
            "next": list(NEXT),
        }


def execute(plan: Plan, report: dict) -> int:
    held = plan.lock_blockers()      # a lock may have been taken since the plan was made: look again right before the renames
    if held:
        report["blockers"].extend(held)
        return 1
    done: list = []
    report["done"] = done
    try:
        for move in plan.moves:
            dst = Path(move["to"])
            os.makedirs(dst.parent, mode=0o700, exist_ok=True)
            os.rename(move["from"], dst)
            done.append({"step": "move", "path": move["from"]})
        for item in plan.deletes:
            os.remove(item["path"])
            done.append({"step": "delete", "path": item["path"]})
        for folder in plan.remove_empty:
            if is_dir(Path(folder)) and not os.listdir(folder):
                os.rmdir(folder)
                done.append({"step": "rmdir", "path": folder})
    except OSError as exc:
        report["mode"] = "error"
        report["error"] = " ".join(str(exc).split())
        return 1
    report["mode"] = "moved"
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rename_move.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", action="append", default=[], metavar="DIR",
                        help="a project whose docs/workbench/runtime.json may point into an old folder; repeat for several")
    parser.add_argument("--yes", action="store_true", help="move, delete and remove; without it nothing is changed")
    parser.add_argument("--platform", choices=["darwin", "other"], default="darwin" if sys.platform == "darwin" else "other",
                        help="which data folder to use (default: this machine's)")
    args = parser.parse_args(argv)

    plan = Plan(args.platform, args.project).build()
    report = plan.report("list")
    code = 0
    if plan.blockers:
        code = 1
    elif args.yes:
        code = execute(plan, report)
        if report["blockers"]:
            plan.blockers = report["blockers"]
    print(json.dumps(report, indent=2))
    if "error" in report:
        log(f"error: {report['error']}; run this again to continue from what is left")
    elif plan.blockers:
        log(f"{len(plan.blockers)} blocker(s): nothing was moved")
    elif args.yes:
        log(f"moved {len(plan.moves)} entries, deleted {len(plan.deletes)}, removed {len(plan.remove_empty)} folder(s) when empty")
    else:
        log(f"would move {len(plan.moves)} entries and delete {len(plan.deletes)}; run again with --yes to do it")
    return code


if __name__ == "__main__":
    sys.exit(main())
