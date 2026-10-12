#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The rules of tasks that run at once, decided by pure functions: whether a ready task may start beside the ones that
run (a slot of its agent, a slot of the project, no code task of its request, no artifact in use), and what a skill's
footprint is. Two tasks run together only when the files their skills declare do not overlap (decision of 2026-10-12,
docs/decisions.md).

Pure: no store, no file except the skill folders `footprint` reads, no clock.

  footprint(skill_dir) -> frozenset: the declared outputs and updates, minus the state file (merged line by line)
  overlap(a, b) -> bool: whether two declared paths can name the same file; a placeholder is a wildcard
  conflicts(fp, others) -> [paths of fp that overlap a path of any footprint of others], sorted
  admit(task, running, holding, agents, max_running) -> (True, "") or (False, reason), the first failure wins

The caller (runtime/ops_runs.py, PAR-4) calls admit under the project's claim lock, so two processes cannot pass the
same check.

Usage (a library): python3 runtime/parallel.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import path_rule  # noqa: E402  (the same folder)
import skill_meta  # noqa: E402

# The words of the held-reasons vocabulary (runtime/dispatcher.py copies them by value; a test holds them equal).
PROJECT_FULL = "project at max_running"
AGENT_FULL = "agent at max_parallel"
CODE_IN_REQUEST = "a code task of the request runs"
IN_USE = "artifact in use"
RETRY_SOON = "could not start, tried again shortly"


def footprint(skill_dir: str) -> frozenset:
    """The files a task of this skill may write: its declared outputs and updates, without the state file. A SkillError
    propagates."""
    meta = skill_meta.declared(skill_dir)
    return frozenset(p for p in list(meta["outputs"]) + list(meta["updates"]) if p != path_rule.STATE)


def norm(p: str) -> str:
    """A declared path with each placeholder read as a wildcard."""
    return skill_meta.PLACEHOLDER.sub("*", p)


def _sample(segment: str) -> str:
    return skill_meta.PLACEHOLDER.sub("x", segment)


def _segments_match(sa: str, sb: str) -> bool:
    if sa == sb:
        return True
    whole = skill_meta.PLACEHOLDER.fullmatch
    if whole(sa) or whole(sb):
        return True
    return bool(skill_meta.pattern(sa).match(_sample(sb)) or skill_meta.pattern(sb).match(_sample(sa)))


def overlap(a: str, b: str) -> bool:
    """Whether two declared paths can name the same file. In order: equal once normalised; a folder (ending in "/") and
    a path under it; the same number of segments and every pair of segments matching (equal, a whole placeholder, or a
    pattern that matches the other's sample). Anything else: False."""
    na, nb = norm(a), norm(b)
    if na == nb:
        return True
    if (na.endswith("/") and nb.startswith(na)) or (nb.endswith("/") and na.startswith(nb)):
        return True
    sa, sb = a.split("/"), b.split("/")
    return len(sa) == len(sb) and all(_segments_match(x, y) for x, y in zip(sa, sb))


def conflicts(fp: frozenset, others: list) -> list:
    """The paths of fp that overlap a path of any footprint in others, sorted."""
    return sorted(p for p in fp if any(overlap(p, q) for other in others for q in other))


def admit(task: dict, running: list, holding: list, agents: dict, max_running: int) -> tuple:
    """(True, "") or (False, reason). task and each item of running: {"id", "agent", "request_id", "code", "footprint"};
    holding: {"id", "agent"} of every slot holder (the running ones included); agents: name -> normalised entry with
    "max_parallel". First failure wins: the project is full; the agent is full (skipped for a task that already holds a
    slot and for a task with no configured agent); a code task, or an effect that executes, of the same request runs (an
    effect is an item with "effect": True, "code": True and no footprint); the footprint is in use."""
    # an executing effect (item "effect": True) is not a task run: it fills no slot, only keeps a code task of its request out
    if sum(1 for r in running if not r.get("effect")) >= max_running:
        return False, PROJECT_FULL
    held_ids = {h["id"] for h in holding}
    if task["id"] not in held_ids and task.get("agent") in agents:
        taken = sum(1 for h in holding if h["agent"] == task["agent"])
        if taken >= agents[task["agent"]]["max_parallel"]:
            return False, AGENT_FULL
    if task.get("code") and any(r.get("code") and r["request_id"] == task["request_id"] for r in running):
        return False, CODE_IN_REQUEST
    if conflicts(task["footprint"], [r["footprint"] for r in running]):
        return False, IN_USE
    return True, ""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
