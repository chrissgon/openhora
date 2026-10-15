#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The flow check: what a workflow may not hold, decided by code when it is created or changed (decisions D27 and D31, P6a).

A task that requires the web never receives sources. The reason is the one of D16: what a run reads of a source is visible to a
run with the open network, and a workflow that runs again on its own (a routine, P6b) has no person at the plan card to decide.
So when a workflow is saved, or checked, every skill task is looked at:

  - its skill requires the web (`requires` holds `search:web`) and the task does not say `"web": false`, and
  - it receives sources: the ones it lists, and the ones of the `ingest` steps it depends on (flow_files.sources_of).

Both together is a finding. For a finding the check says whether a split made by code is offered:

  - The skill accepts a research brief (an input under docs/workbench/research/, as `biz-market-analysis` and
    `biz-icp-positioning` declare): the split replaces the task with two. A research task (`core-research`, the web, no sources, and
    none of the steps that bring a source in among what it depends on) writes the brief; the skill's task then runs without the web
    (`"web": false`), with the sources, after the research task, so the brief is one of the artifacts it reads. apply_split() makes
    it and checks the result again.
  - Any other skill: no automatic split. The finding asks the person which of three ways to take (take the sources from the task,
    give the sources to another task, or run it without the web on purpose).

A skill that requires the web and a task that has no source are left alone. In manual use (a plan the router or the person named)
D16 stands: the plan card highlights a web task that receives sources and the person decides; this check runs when a workflow is
created or changed (runtime/ops_flows.py: flow-save, flow-check, flows), never when a plan is built.

  check(flow, root)             {"ok", "findings": [{"task", "skill", "sources", "sentence", "split", "ask"}]}
  apply_split(flow, root)       the flow with every offered split made; FlowError when a finding has none or the result still fails
  requires_web(skill, root)     whether a skill folder declares `search:web`

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import flow_files  # noqa: E402
import skill_meta  # noqa: E402
import steps  # noqa: E402  (the kinds that bring a source in)

BRIEF_DIR = "docs/workbench/research/"      # the brief a research task writes (core-research's output); a skill that reads one lists a path here
RESEARCH_SKILL = "core-research"
TITLE_MAX = 120
ASK = ("Choose one: take the sources off this task; give the sources to a task that does not need the web, and let this one search "
       "alone; or run it without the web on purpose (add \"web\": false to the task: the skill then works from what it is given).")


def _meta(skill: str, root: str):
    try:
        return skill_meta.declared(os.path.join(root, "skills", skill))
    except skill_meta.SkillError:
        return None


def requires_web(skill: str, root: str) -> bool:
    meta = _meta(skill, root)
    return bool(meta and meta["web"])


def accepts_brief(skill: str, root: str) -> bool:
    """Whether the skill lists a research brief among its inputs (a path under docs/workbench/research/)."""
    meta = _meta(skill, root)
    return bool(meta and any(p.startswith(BRIEF_DIR) for p in meta["inputs"]))


def can_research(root: str) -> bool:
    return requires_web(RESEARCH_SKILL, root)


def check(flow: dict, root: str = flow_files.ROOT) -> dict:
    """The findings of a loaded flow (flow_files.load / normalise). {"ok": bool, "findings": [...]}; a finding is {"task": key,
    "skill", "sources": [ids], "sentence": why, "split": whether apply_split would split it, "ask": the question for the person
    when it would not (None when it would)}."""
    received = flow_files.sources_of(flow, steps.sourcing_kinds())
    findings = []
    for task in flow["tasks"]:
        if "skill" not in task or task.get("web") is False:
            continue
        ids = received.get(task["key"]) or []
        if not ids or not requires_web(task["skill"], root):
            continue
        split = accepts_brief(task["skill"], root) and can_research(root)
        findings.append({
            "task": task["key"], "skill": task["skill"], "sources": ids,
            "sentence": (f"task {task['key']} ({task['skill']}) requires the web and receives the source"
                         f"{'s' if len(ids) > 1 else ''} {', '.join(ids)}: a workflow never gives sources to a task that uses "
                         "the web"),
            "split": split,
            "ask": None if split else ASK})
    return {"ok": not findings, "findings": findings}


def _reaches_ingest(flow: dict, key: str) -> bool:
    """Whether the task, or something it depends on, is a step that brings a source in."""
    by_key = {t["key"]: t for t in flow["tasks"]}
    seen, todo = set(), [key]
    while todo:
        k = todo.pop()
        if k in seen or k not in by_key:
            continue
        seen.add(k)
        if by_key[k].get("step") in steps.sourcing_kinds():
            return True
        todo += list(by_key[k].get("depends_on") or [])
    return False


def _free_key(flow: dict, base: str) -> str:
    keys = {t["key"] for t in flow["tasks"]}
    key, n = base, 1
    while key in keys:
        n += 1
        key = f"{base}-{n}"
    return key


def apply_split(flow: dict, root: str = flow_files.ROOT) -> dict:
    """The flow with the split made for every finding that offers one: before the task, a research task (`core-research`, the web,
    no sources, depending on the tasks the original depended on that bring no source); the task itself keeps its sources and its
    place, depends on the research task too, and runs without the web. FlowError when a finding offers no split or when the result
    still has a finding (a flow that the check refuses is never returned as if it passed)."""
    found = check(flow, root)
    asked = [f for f in found["findings"] if not f["split"]]
    if asked:
        raise flow_files.FlowError(asked[0]["sentence"] + ". " + asked[0]["ask"])
    out = copy.deepcopy(flow)
    for finding in found["findings"]:
        at = next(i for i, t in enumerate(out["tasks"]) if t["key"] == finding["task"])
        task = out["tasks"][at]
        key = _free_key(out, f"{task['key']}-research")
        before = [d for d in task.get("depends_on") or [] if not _reaches_ingest(out, d)]
        brief = {"key": key, "skill": RESEARCH_SKILL, "title": f"Research for {task['title']}"[:TITLE_MAX],
                 "text": (f"Research what the task \"{task['title']}\" needs, with the web and with no source of this project, "
                          f"and write the brief under {BRIEF_DIR}. {task['text']}").strip(),
                 "depends_on": before, "milestone": False}
        task["depends_on"] = list(task.get("depends_on") or []) + [key]
        task["web"] = False
        out["tasks"].insert(at, brief)
    again = check(out, root)
    if not again["ok"]:
        raise flow_files.FlowError("the split did not clear the finding: " + again["findings"][0]["sentence"])
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
