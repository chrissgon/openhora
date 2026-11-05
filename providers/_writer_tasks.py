#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the two tasks writers share (package CB-4): providers/writer/google-tasks.py and providers/writer/microsoft-todo.py. A name with an underscore is never listed as an
implementation by providers/resolve.py, so this file is a module, not a provider. It holds no HTTP, no credential and no request: only the parts that must be the same in
both writers so that they cannot drift apart. The ledger, the hash of a request and the exit codes are the calendar writers' own (providers/_writer_calendar.py, loaded by
path and re-exported here), so that every writer of the person's own accounts keeps one ledger format.

  WriterError, EXIT_*             an error with an exit code and a one-line message (the writers print "error: <message>" and exit with the code)
  canonical, sha, claim, settle, ledger_peek   the hash of a request and the ledger of a writer: <state>/writer-<implementation>/ledger.json, the key of a request
                                  recorded `pending` before the call and `done` after the answer
  KEY, ETAG, LIST_ID, TASK_ID, ADDRESS   the full-match patterns of what enters a path, a header-free request or a comparison
  read_spec                       the spec file a writer is handed for a new task: exactly {"title"}, one line of 1 to 200 characters with no hidden or control
                                  character, read without following a link (the person's words, in a private file, never on a command line)
  lost_insert_verdict             after an answer that was lost: from the open tasks of the list, whether the insert of `title` landed (OPEN-CB-12)

No due date, no note, no parent and no list change is in the spec: the maintainer decided on 2026-10-27 that v1 has none of them (OPEN-CB-11).

Standard library only. Runs on Python 3.9. It sends nothing: no method, no path, no URL is in this file (limits L57 and L58 are each writer's own).
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path


def _calendar_module():
    """providers/_writer_calendar.py, by path: next to this file (the workbench's providers/ folder, or a copy of both)."""
    path = Path(__file__).resolve().parent / "_writer_calendar.py"
    if not path.is_file():
        raise SystemExit("error: providers/_writer_calendar.py is not next to providers/_writer_tasks.py")
    spec = importlib.util.spec_from_file_location("providers_writer_calendar_for_tasks", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_calendar = _calendar_module()
WriterError = _calendar.WriterError
EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = (_calendar.EXIT_OK, _calendar.EXIT_REFUSED, _calendar.EXIT_USAGE,
                                                                        _calendar.EXIT_NOT_CONFIGURED, _calendar.EXIT_UNKNOWN)
canonical, sha, claim, settle, ledger_peek, one_line = _calendar.canonical, _calendar.sha, _calendar.claim, _calendar.settle, _calendar.ledger_peek, _calendar.one_line
SPEC_MAX_BYTES = _calendar.SPEC_MAX_BYTES
KEY, ETAG = _calendar.KEY, _calendar.ETAG
LIST_ID = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")      # an id never starts with a hyphen: a flag would read it
TASK_ID = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")
ADDRESS = re.compile(r"[^@\s\x00-\x1f\x7f]{1,64}@[^@\s\x00-\x1f\x7f]{1,253}")
TITLE_MAX = 200
CREATE_KEYS = ("title",)
SKEW_SECONDS = 5      # the clock of this machine and the service's may differ a little: a task updated this long before the pending time still counts as after it


def account_flag(value) -> str:
    if not isinstance(value, str) or not ADDRESS.fullmatch(value) or value.count("@") != 1:
        raise WriterError("--account is the plain address of the account the document names", EXIT_USAGE)
    return value


def read_spec(path) -> dict:
    """The spec of a new task, handed in a file: exactly {"title"}. Usage error (exit 2) when the file cannot be read, is not one JSON object, holds another key, or the
    title is not one line of 1 to TITLE_MAX characters with no hidden or control character."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, TypeError):
        raise WriterError("--spec-file cannot be read (missing, or a link)", EXIT_USAGE) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise WriterError("--spec-file is not a regular file", EXIT_USAGE)
        with os.fdopen(os.dup(fd), "rb") as f:
            data = f.read(SPEC_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > SPEC_MAX_BYTES:
        raise WriterError("--spec-file is too large", EXIT_USAGE)
    try:
        spec = json.loads(data.decode("utf-8"))
    except ValueError:
        spec = None
    if not isinstance(spec, dict):
        raise WriterError("--spec-file is one JSON object", EXIT_USAGE)
    if set(spec) != set(CREATE_KEYS):
        raise WriterError(f"the spec of a new task has exactly the key {', '.join(CREATE_KEYS)}: no due date, note or list change in this version", EXIT_USAGE)
    one_line(spec["title"], "the title", TITLE_MAX, True)
    return spec


def stamp(value):
    """The aware UTC datetime of an RFC 3339 time that ends in Z (fractions allowed), or None."""
    if not isinstance(value, str):
        return None
    found = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z", value)
    if not found:
        return None
    try:
        return datetime.datetime.fromisoformat(found.group(1)).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def lost_insert_verdict(tasks, title: str, since: str) -> tuple:
    """After an answer that was lost (OPEN-CB-12): ("found", task) when exactly one open task of the list has exactly `title` and was updated after the time the key went
    pending (`since`, the ledger's `created_at`, less SKEW_SECONDS), ("none", None) when no task does (the request may be sent again), ("ambiguous", None) when more than one
    does (nothing is sent: the person is asked). `tasks` are the open tasks as the writer read them: dicts with "title" and "updated"; one whose time cannot be read does not count."""
    began = stamp(since)
    if began is None:
        return "ambiguous", None      # a pending time that cannot be read cannot show that a task is the one this key made: never guess
    floor = began - datetime.timedelta(seconds=SKEW_SECONDS)
    same = [t for t in tasks if isinstance(t, dict) and t.get("title") == title and (stamp(t.get("updated")) or began - datetime.timedelta(days=1)) >= floor]
    if len(same) == 1:
        return "found", same[0]
    return ("none", None) if not same else ("ambiguous", None)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
