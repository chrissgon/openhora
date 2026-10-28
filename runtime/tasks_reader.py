#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The reader of the person's own task lists (package CB-5): the class `integration:tasks` (providers/tasks/google.py and microsoft.py, CB-4), read only. It is the one place of the
runtime that starts those providers. A provider of that class sends GET only (limit L58); this module offers two verbs of it and no other, and checks every answer against the shape
it is documented to have before any other module sees it: a task's title is another person's text in principle, so it is cleaned again here and travels as data, never as
an instruction.

  provider_call(root, account, verb, args, timeout)   the one JSON object the provider printed, started by providers/resolve.py with the minimum environment plus the account's
                                                      one token; ReaderError otherwise. A test replaces this function and nothing else
  lists(root, account)                                [{"id", "name", "default"}]: the person's lists of that account
  open_tasks(root, account, list_id, maximum)         {"list": the id read, "tasks": [{"id", "title", "updated", "etag"}], "truncated"}: the open tasks of one list
  default_list(root, account)                         the id the writer is handed for the account's default list: Google's `default` as it is (the service takes it), Microsoft's
                                                      resolved by a read of the lists, because the To Do writer refuses `default` (a dry run reads no credential)

ReaderError carries a closed `code` (`not_configured`, `provider_failed`) and a `reason` that never holds a title. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project_config  # noqa: E402
import tasks_document  # noqa: E402

CLASS = "integration:tasks"
IMPLEMENTATION = {"google": "google", "microsoft": "microsoft"}      # the reader of each account (providers/tasks/)
VERBS = ("lists", "open")      # the only verbs of a tasks reader this module starts: both are reads
TIMEOUT = 90
TASKS_MAX = 100      # the reader's own cap (providers/tasks/google.py `open --max`)
LISTS_MAX = 100


class ReaderError(Exception):
    """A read that failed in a way a caller turns into a closed code: `code` is a word, `reason` never holds a person's words."""

    def __init__(self, code: str, reason: str = ""):
        super().__init__(f"{code} {reason}".strip())
        self.code, self.reason = code, reason


def provider_call(root: str, account: str, verb: str, args, timeout: int = TIMEOUT) -> dict:
    """One verb of the tasks reader of `account`, started by providers/resolve.py. ReaderError `not_configured` when no authorization serves it (the provider's exit code 3, or no
    provider), `provider_failed` for anything else."""
    if account not in IMPLEMENTATION or verb not in VERBS:
        raise ReaderError("refused", f"the tasks reader serves google and microsoft and reads with {', '.join(VERBS)} and nothing else")
    resolve = project_config.resolver(root)
    try:
        return resolve.call(CLASS, verb, [str(a) for a in args], root=root, implementation=IMPLEMENTATION[account], timeout=timeout,
                            env=resolve.provider_environment(CLASS, None, (tasks_document.SECRET[account],)))
    except resolve.ProviderCallError as e:
        raise ReaderError("not_configured" if e.kind == "not-configured" or e.exit_code == 3 else "provider_failed", f"{verb}: {str(e.reason)[:120]}") from None


def _text(value, maximum: int = tasks_document.TITLE_MAX) -> str:
    return tasks_document.line_or_blank(value, maximum) if isinstance(value, str) else ""


def lists(root: str, account: str) -> list:
    """The person's lists of the account: [{"id", "name", "default"}], `default` true or false (Google's reader says null for every list: false here)."""
    got = provider_call(root, account, "lists", [])
    rows = got.get("lists") if isinstance(got, dict) else None
    if not isinstance(rows, list) or len(rows) > LISTS_MAX:
        raise ReaderError("provider_failed", "the reader's answer about the lists is not one this code understands")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not tasks_document.LIST_ID.fullmatch(row["id"]):
            raise ReaderError("provider_failed", "a list the reader gave has no usable id")
        out.append({"id": row["id"], "name": _text(row.get("name")), "default": row.get("default") is True})
    return out


def open_tasks(root: str, account: str, list_id: str, maximum: int = TASKS_MAX) -> dict:
    """The open tasks of one list: {"list": the id read, "tasks": [{"id", "title", "updated", "etag"}], "truncated"}. Titles are clean, one line, at most 200 characters."""
    if not isinstance(list_id, str) or not tasks_document.LIST_ID.fullmatch(list_id):
        raise ReaderError("refused", "a list is named by its id")
    got = provider_call(root, account, "open", ["--list", list_id, "--max", str(max(1, min(int(maximum), TASKS_MAX)))])
    rows = got.get("tasks") if isinstance(got, dict) else None
    if not isinstance(rows, list) or len(rows) > TASKS_MAX or not isinstance(got.get("list"), str) or not tasks_document.LIST_ID.fullmatch(got["list"]):
        raise ReaderError("provider_failed", "the reader's answer about the tasks is not one this code understands")
    tasks = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not tasks_document.TASK_ID.fullmatch(row["id"]) \
                or not isinstance(row.get("etag"), str) or not tasks_document.ETAG.fullmatch(row["etag"]):
            raise ReaderError("provider_failed", "a task the reader gave has no usable id or version")
        tasks.append({"id": row["id"], "title": _text(row.get("title")), "updated": _text(row.get("updated"), 40), "etag": row["etag"]})
    return {"list": got["list"], "tasks": tasks, "truncated": got.get("truncated") is True}


def default_list(root: str, account: str) -> str:
    """The id the writer is handed for the account's default list (see the module's text). ReaderError when Microsoft marks none."""
    if account != "microsoft":
        return "default"
    found = [row["id"] for row in lists(root, account) if row["default"]]
    if len(found) != 1:
        raise ReaderError("provider_failed", "the account has no list the service marks as its default one")
    return found[0]


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
