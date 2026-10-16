#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The language of a deliverable in the operations layer: the check of the person's choice on a request, and the line a run gets
(runtime/language.py holds the rule, the order and the words).

A sibling of runtime/ops.py; no shell imports this file. The shared names come from ops_core (read as `core.<name>`, at call time).

  checked(value)               the tag a request carries, None for none; a bad tag is a refusal (code 2) before anything is recorded
  run_line(cfg, row)           the paragraph of a task run's or the router's prompt: the language of the task (or of the request,
                               for the router's run) as the row records it, else the project's key, else `en`
  of_plan(approved, request)   the language the sub-tasks of a request take (its own choice, else the approved plan's)
  project_of(cfg)              the project's setting for a plan's line (None: not set)

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import language
import ops_core as core


def checked(value):
    """The tag a request carries (language.check), or None; a text that is not a tag is a refusal that names the rule."""
    try:
        return language.check(value)
    except language.LanguageError as e:
        raise core.OpsError(str(e), 2) from None


def run_line(cfg: dict, row: dict) -> str:
    """The language paragraph for a run of the task row (or of the request row, for the router): `tasks.language` of the row, else
    the project's `language`, else `en` (language.effective). Only code gives it to a run, never a run's text."""
    return language.line((row or {}).get("language"), cfg.get("language"))


def of_plan(approved, request: dict):
    """The language a request's later tasks (the backlog's sub-tasks) take: the request's own choice, else the one the approved plan's
    tasks carry (the router's proposal the person saw on the card), else None."""
    if (request or {}).get("language"):
        return request["language"]
    return next((t["language"] for t in (approved or {}).get("tasks") or [] if isinstance(t, dict) and t.get("language")), None)


def project_of(cfg: dict):
    """The key `language` of the project's configuration, None when it is not set."""
    return cfg.get("language")
