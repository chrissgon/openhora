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
  files(project, task_id)                         the regular files of a task's folder, sorted; empty when a link is
                                                  anywhere on the way

The folder is never opened by its path string (limit L2). open_folder() opens the project root, then `.workbench-local`,
`drop` and `<task id>` one at a time with O_RDONLY | O_DIRECTORY | O_NOFOLLOW from the descriptor of the one before (with
`create`, each missing part is made with mkdir(0o700, dir_fd) and opened the same way), so a link at any of the three levels
is a DropError that names it. A file in the folder is read with read_file() (O_NOFOLLOW | O_NONBLOCK, a regular file by
fstat, at most a cap) and written with write_new() (O_EXCL | O_NOFOLLOW), both from that descriptor. folder() only builds
the string for a message and a prompt.

WEB_TASK_TAKES_DROP is True (the maintainer's decision of 2026-10-09, on the review card that sends a task back with
his own files): a file handed over enters a task whose skill uses the web too, because the file is the person's own
choice, and the answer to the hand-over says so (`web: true` and WEB_LINE), for the page to show before the send. The
rest of what enters a web task is unchanged: only the artifacts its skill declares (limit L3). Set to False, a web task
refuses the drop with WEB_REFUSAL and a file already in its folder is left out of the run.

Usage (a library; the shell is runtime/cli.py hand-over): python3 runtime/drop.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
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
    """<project>/.workbench-local/drop/<task id>, as a string for a message: no caller opens it (open_folder does)."""
    return os.path.join(project, *DROP_DIR.split("/"), str(task_id))


def _ignored(project: str, rel: str) -> bool:
    try:
        done = subprocess.run(["git", "-C", project, "check-ignore", "-q", rel], capture_output=True,
                              timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


# --- the folder, one descriptor at a time (limit L2) -----------------------------------------------------------------------------------

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_LINK_ERRORS = (errno.ELOOP, errno.ENOTDIR, getattr(errno, "EMLINK", errno.ELOOP))


def _link_refusal(part: str) -> DropError:
    return DropError(f"{part!r} on the way to the file drop is a link or not a folder: the drop is never reached through a link")


def _step(parent: int, part: str, create: bool) -> int:
    """The descriptor of the folder `part` of the folder `parent`, opened without following a link and checked to be a folder."""
    try:
        try:
            fd = os.open(part, _DIRECTORY, dir_fd=parent)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(part, 0o700, dir_fd=parent)
            except FileExistsError:
                pass  # made between the two calls: opened below, the same way
            fd = os.open(part, _DIRECTORY, dir_fd=parent)
    except OSError as e:
        if e.errno in _LINK_ERRORS:
            raise _link_refusal(part) from None
        raise
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise _link_refusal(part)
    return fd


TASK_PART = re.compile(r"[0-9]{1,18}|request-[0-9]{1,18}")   # a task's folder is its id; a request's staging folder is request-<id>


def open_folder(project: str, task_id, create: bool = False) -> int:
    """The descriptor of <project>/.workbench-local/drop/<task id>, opened from the project's root one part at a time (each with
    O_DIRECTORY | O_NOFOLLOW from the one before). A link at any part is a DropError that names the part; a part that does not exist
    is FileNotFoundError (with create, it is made, mode 0700). The task id is a whole number or `request-<n>`; anything else (empty, a
    `..`, a `/`) is a DropError before anything is opened. The caller closes the descriptor."""
    if isinstance(task_id, bool) or not TASK_PART.fullmatch(str(task_id)):
        raise DropError(f"{str(task_id)!r} is not a task id of the file drop: a whole number, or request-<n>")
    fd = os.open(os.path.realpath(project), os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in DROP_DIR.split("/") + [str(task_id)]:
            following = _step(fd, part, create)
            os.close(fd)
            fd = following
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_file(dir_fd: int, name: str, cap: int = MAX_BYTES) -> bytes:
    """At most cap + 1 bytes of the file `name` of the folder. It is looked at through the descriptor before it is opened (a pipe or a
    device is refused without being opened: opening a FIFO waits for a writer), opened with O_NOFOLLOW | O_NONBLOCK, and looked at
    again through the open descriptor (the same file, a regular one). DropError when it is a link or not a regular file;
    FileNotFoundError when it is not there. The caller compares the length with cap."""
    if "/" in name or name in ("", ".", ".."):
        raise DropError(f"{name!r} is not a name of the folder")
    before = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise DropError(f"{name} is a link or not a regular file")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError as e:
        if e.errno in _LINK_ERRORS:
            raise DropError(f"{name} is a link or not a regular file") from None
        raise
    with os.fdopen(fd, "rb") as f:
        after = os.fstat(f.fileno())
        if not stat.S_ISREG(after.st_mode) or not os.path.samestat(before, after):
            raise DropError(f"{name} changed while it was opened")
        return f.read(cap + 1)


def write_new(dir_fd: int, name: str, data: bytes) -> None:
    """Write a new file `name` in the folder (mode 0600): O_EXCL, so a file or a link of that name is never replaced, and O_NOFOLLOW."""
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def read_dropped(project: str, rel: str, cap: int = MAX_BYTES) -> bytes:
    """The bytes of the file the relative path `rel` (.workbench-local/drop/<task id>/<name>) names, read through open_folder() and
    read_file(). DropError for a path of another shape or a link on the way; FileNotFoundError when something is not there."""
    parts, prefix = rel.split("/"), DROP_DIR.split("/")
    if len(parts) != len(prefix) + 2 or parts[:len(prefix)] != prefix:
        raise DropError(f"{rel} is not a path of the file drop")
    dir_fd = open_folder(project, parts[-2])
    try:
        return read_file(dir_fd, parts[-1], cap)
    finally:
        os.close(dir_fd)


def discard(project: str, task_id) -> None:
    """Remove the files of a task's folder and the folder, through descriptors and without following a link (a link inside is removed
    as a link, one on the way leaves everything alone). Never fails: what cannot be removed stays."""
    try:
        fd = open_folder(project, task_id)
    except (DropError, OSError):
        return
    try:
        for name in os.listdir(fd):
            try:
                os.unlink(name, dir_fd=fd)
            except OSError:
                pass
    except OSError:
        pass
    finally:
        os.close(fd)
    try:
        parent = os.open(os.path.realpath(project), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        for part in DROP_DIR.split("/"):
            following = _step(parent, part, False)
            os.close(parent)
            parent = following
        os.rmdir(str(task_id), dir_fd=parent)
    except (DropError, OSError):
        pass
    finally:
        os.close(parent)


def hand_over(project: str, task: dict, source: str, web_allowed: bool) -> dict:
    """Copy one file into the task's folder: {"task", "path", "bytes", "sha256"} (and, on a web task when
    web_allowed, "web": true with "note"). task is the store's row of the task with "web": whether its skill uses
    the web."""
    project = os.path.realpath(project)
    if task.get("state") in NOT_NOW:
        raise DropError(f"task {task['id']} is {task['state']}: a file is handed only to a task that has not ended "
                        "and is not running")
    name = os.path.basename(source)
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise DropError(f"{source} is a link or not a regular file: hand over one regular file") from None
    info = os.fstat(source_fd)   # looked at by its descriptor, not by its path
    if not stat.S_ISREG(info.st_mode):
        os.close(source_fd)
        raise DropError(f"{source} is a link or not a regular file: hand over one regular file")
    with os.fdopen(source_fd, "rb") as f:
        if not NAME.fullmatch(name):
            raise DropError(f"the name {name!r} is refused: letters, digits, '.', '_' and '-', starting with a letter "
                            "or a digit, at most 100 characters")
        if info.st_size > MAX_BYTES:
            raise DropError(f"{name} is {info.st_size} bytes, larger than {MAX_BYTES}")
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:   # the file grew after its size was read
        raise DropError(f"{name} is larger than {MAX_BYTES} bytes")
    rel = "/".join([DROP_DIR, str(task["id"]), name])
    try:   # a link on the way refuses the hand-over here, before anything is written; a folder not made yet holds nothing
        existing = open_folder(project, task["id"])
    except FileNotFoundError:
        existing = None
    if existing is not None:
        try:
            os.stat(name, dir_fd=existing, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise DropError(f"{rel} is already there: a hand-over never replaces a file; give the new one another name")
        finally:
            os.close(existing)
    if task.get("web") and not web_allowed:
        raise DropError(WEB_REFUSAL)
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
    target = open_folder(project, task["id"], create=True)
    try:
        try:
            write_new(target, name, data)
        except FileExistsError:
            raise DropError(f"{rel} is already there: a hand-over never replaces a file; give the new one another name") from None
    finally:
        os.close(target)
    out = {"task": task["id"], "path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if task.get("web"):
        out.update(web=True, note=WEB_LINE)
    return out


def files(project: str, task_id) -> list:
    """[(path as a string, relative path)] of the regular files of the task's folder (no link), sorted. The folder is read through its
    descriptors (open_folder); a link at any part, or a part that is not there, gives []. The path is for a message: read a file with
    read_dropped(), which opens it through the descriptors again."""
    try:
        dir_fd = open_folder(project, task_id)
    except (DropError, OSError):
        return []
    try:
        out = []
        for name in sorted(os.listdir(dir_fd)):
            try:
                info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                out.append((os.path.join(folder(os.path.realpath(project), task_id), name), "/".join([DROP_DIR, str(task_id), name])))
        return out
    except OSError:
        return []
    finally:
        os.close(dir_fd)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
