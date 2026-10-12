#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The file drop: how a person hands a file to one task (a logo made elsewhere, a spreadsheet), since the runtime
has no image provider.

A file handed over is copied into <project>/.workbench-local/drop/<task id>/ (DROP_DIR). It enters the run copy of
that task, at the same relative path, and of no other task (runtime/workcopy.py, limit L2); the run's prompt lists
it (ops.task_prompt, handed=); whatever a run leaves in the drop folder is dropped on the way back (the folder is
staged for the path rule), so a run cannot change what the person handed over.

  hand_over(project, task, source, web_allowed)   copy one file into the task's folder; refused, each with its own
                                                  message (DropError), when: the source is a link or not a regular
                                                  file; its name does not match NAME; it is larger than MAX_BYTES; a
                                                  file of that name is already there (a hand-over never replaces
                                                  one); the task is done, cancelled or running; the file is text
                                                  and holds what looks like a credential (limit L6); the project is
                                                  a git repository that does not ignore the drop (a handed-over file
                                                  must never reach a commit); the task's skill uses the web and
                                                  web_allowed is false (limit L3)
  files(project, task_id)                         the regular files of a task's folder, sorted

WEB_TASK_TAKES_DROP is True (the maintainer's decision of 2026-10-09, on the review card that sends a task back with
his own files): a file handed over enters a task whose skill uses the web too, because the file is the person's own
choice, and the answer to the hand-over says so (`web: true` and WEB_LINE), for the page to show before the send. The
rest of what enters a web task is unchanged: only the artifacts its skill declares (limit L3). Set to False, a web task
refuses the drop with WEB_REFUSAL and a file already in its folder is left out of the run.

Usage (a library; the shell is runtime/cli.py hand-over): python3 runtime/drop.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import path_rule  # noqa: E402  (the same folder)
import workcopy  # noqa: E402

DROP_DIR = path_rule.DROP_DIR
MAX_BYTES = 25 * 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
WEB_TASK_TAKES_DROP = True
NOT_NOW = ("done", "cancelled", "running")
GIT_TIMEOUT = 60
WEB_REFUSAL = "this task's skill uses the web, and a web task receives only the artifacts its skill declares"
WEB_LINE = "this file will be visible to a run with the open network"


class DropError(Exception):
    """A hand-over that was refused; the message says why."""


def folder(project: str, task_id: int) -> str:
    """<project>/.workbench-local/drop/<task id>"""
    return os.path.join(project, *DROP_DIR.split("/"), str(task_id))


def _ignored(project: str, rel: str) -> bool:
    try:
        done = subprocess.run(["git", "-C", project, "check-ignore", "-q", rel], capture_output=True,
                              timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def hand_over(project: str, task: dict, source: str, web_allowed: bool) -> dict:
    """Copy one file into the task's folder: {"task", "path", "bytes", "sha256"} (and, on a web task when
    web_allowed, "web": true with "note"). task is the store's row of the task with "web": whether its skill uses
    the web."""
    project = os.path.realpath(project)
    if task.get("state") in NOT_NOW:
        raise DropError(f"task {task['id']} is {task['state']}: a file is handed only to a task that has not ended "
                        "and is not running")
    if os.path.islink(source) or not os.path.isfile(source):
        raise DropError(f"{source} is a link or not a regular file: hand over one regular file")
    name = os.path.basename(source)
    if not NAME.fullmatch(name):
        raise DropError(f"the name {name!r} is refused: letters, digits, '.', '_' and '-', starting with a letter "
                        "or a digit, at most 100 characters")
    size = os.path.getsize(source)
    if size > MAX_BYTES:
        raise DropError(f"{name} is {size} bytes, larger than {MAX_BYTES}")
    target_dir = folder(project, task["id"])
    target = os.path.join(target_dir, name)
    rel = "/".join([DROP_DIR, str(task["id"]), name])
    if os.path.lexists(target):
        raise DropError(f"{rel} is already there: a hand-over never replaces a file; give the new one another name")
    if task.get("web") and not web_allowed:
        raise DropError(WEB_REFUSAL)
    with open(source, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None and workcopy.credential_findings(text):
        raise DropError(f"{name} holds what looks like a credential "
                        f"({', '.join(sorted(set(workcopy.credential_findings(text))))}): a credential never enters a run")
    if os.path.exists(os.path.join(project, ".git")) and not _ignored(project, rel):
        raise DropError("the project's git does not ignore the drop: add .workbench-local/ to .gitignore, so that a "
                        "handed-over file never reaches a commit")
    os.makedirs(target_dir, mode=0o700, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    out = {"task": task["id"], "path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if task.get("web"):
        out.update(web=True, note=WEB_LINE)
    return out


def files(project: str, task_id: int) -> list:
    """[(absolute path, relative path)] of the regular files of the task's folder (no link), sorted."""
    project = os.path.realpath(project)
    top = folder(project, task_id)
    if not os.path.isdir(top) or os.path.islink(top):
        return []
    out = []
    for name in sorted(os.listdir(top)):
        path = os.path.join(top, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        out.append((path, "/".join([DROP_DIR, str(task_id), name])))
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
