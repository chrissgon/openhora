#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Flow files: flows/<name>.json, one data file per flow, with its tasks and their dependencies written out.

A flow file is data the runtime's code reads; it is not a skill and no model reads it (a `flow-` skill is the
other thing of that name: a SKILL.md a person runs in a tool). Its form:

  {"flow": "<name>",                  the file's name without .json: lowercase words joined by hyphens
   "title": "<one line>",
   "tasks": [                         in the order they are planned
     {"key": "<name>",                unique in the file; lowercase words joined by hyphens
      "skill": "<skill name>",        a folder of skills/
      "title": "<one line>",
      "text": "<the task's own text, added to the request in the run's prompt>",
      "depends_on": ["<key>", ...],   keys of tasks earlier in the list (so there is no cycle); [] or absent for none
      "milestone": true | false}      absent means false
   ]}

No other key is read today. Reserved for later stages of the platform plan: a top-level "include" (a flow
that includes another) and a task with "writer": "user" in place of "skill" (a document the person writes).

Dependencies are written, never computed: scripts/validate.py checks them against the skills' required inputs
and their declared outputs (dependency_problems): a task that requires, without a condition, a path another
task's skill of the same flow writes must reach that task through depends_on. required_inputs is a lower bound
on purpose: a requirement with a condition ("yes for a person") is not computed.

Usage:
  python3 runtime/flow_files.py --help
  python3 runtime/flow_files.py --check [<name>...]     check the named flow files (every file of flows/ when
                                                        none is named); prints {"flows", "problems"} as JSON

Exit codes: 0 ok, 1 a flow file has a problem, 2 usage error. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
TOP_KEYS = {"flow", "title", "tasks"}
TASK_KEYS = {"key", "skill", "title", "text", "depends_on", "milestone"}


class FlowError(Exception):
    """A flow file is missing or not well formed; the message lists every problem."""


def names(root: str = ROOT) -> list:
    folder = os.path.join(root, "flows")
    if not os.path.isdir(folder):
        return []
    return sorted(n[:-len(".json")] for n in os.listdir(folder) if n.endswith(".json"))


def problems(data, name: str, root: str = ROOT) -> list:
    """Why a loaded flow file is not well formed; [] when it is."""
    if not isinstance(data, dict):
        return ["the file must hold a JSON object"]
    out = [f"unknown key {k!r}" for k in sorted(set(data) - TOP_KEYS)]
    if data.get("flow") != name:
        out.append(f"\"flow\" must be {name!r}, the file's name")
    if not isinstance(data.get("title"), str) or not data["title"].strip() or "\n" in data["title"]:
        out.append("\"title\" must be one line of text")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return out + ["\"tasks\" must be a list with at least one task"]
    seen = []
    for i, task in enumerate(tasks, 1):
        where = f"task {i}"
        if not isinstance(task, dict):
            out.append(f"{where} must be an object")
            continue
        out += [f"{where}: unknown key {k!r}" for k in sorted(set(task) - TASK_KEYS)]
        key = task.get("key")
        if not isinstance(key, str) or not NAME.fullmatch(key):
            out.append(f"{where}: \"key\" must be lowercase words joined by hyphens")
        elif key in seen:
            out.append(f"{where}: the key {key!r} is used twice")
        where = f"task {key!r}" if isinstance(key, str) else where
        skill = task.get("skill")
        if not isinstance(skill, str) or not NAME.fullmatch(skill):
            out.append(f"{where}: \"skill\" must be a skill name")
        elif not os.path.isfile(os.path.join(root, "skills", skill, "SKILL.md")):
            out.append(f"{where}: the skill {skill!r} is not under skills/")
        for field in ("title", "text"):
            if not isinstance(task.get(field), str) or not task[field].strip():
                out.append(f"{where}: \"{field}\" must be text")
        depends = task.get("depends_on", [])
        if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
            out.append(f"{where}: \"depends_on\" must be a list of keys")
        else:
            out += [f"{where}: depends on {d!r}, which is not a task earlier in the list" for d in depends if d not in seen]
        if not isinstance(task.get("milestone", False), bool):
            out.append(f"{where}: \"milestone\" must be true or false")
        if isinstance(key, str):
            seen.append(key)
    return out


PLACEHOLDER = re.compile(r"<[^<>/]+>")


def _cells(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def required_inputs(skill_md: str, declared_inputs: list) -> list:
    """The declared input paths a skill requires without a condition: in the table under `## Inputs`, a row
    whose `Required` cell, stripped and lowercased, is exactly `yes`; from it, every path of declared_inputs
    that occurs literally in its `Artifact` cell. A cell such as `yes for a person` is a condition and is not
    computed, so this is a lower bound."""
    lines = skill_md.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Inputs")
    except StopIteration:
        return []
    header, artifact, required, out = None, None, None, []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            if header is not None:
                break
            continue
        cells = _cells(line)
        if header is None:
            header = [c.lower() for c in cells]
            if "artifact" not in header or "required" not in header:
                return []
            artifact, required = header.index("artifact"), header.index("required")
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        if len(cells) <= max(artifact, required) or cells[required].strip().lower() != "yes":
            continue
        out += [p for p in declared_inputs if p in cells[artifact] and p not in out]
    return out


def _artifact(path: str) -> str:
    """Two declared paths are the same artifact when they are equal once each placeholder is a wildcard."""
    return PLACEHOLDER.sub("*", path)


def dependency_problems(flow: dict, skills: dict) -> list:
    """Each task T that requires (required_inputs) a path P which the skill of another task U of the same flow
    owns (lists in its outputs) must reach U through depends_on. `skills` maps a skill name to {"inputs",
    "outputs", "skill_md"}. One text per miss; a task whose skill is not in `skills` is skipped."""
    tasks = [t for t in flow.get("tasks", []) if isinstance(t, dict) and isinstance(t.get("key"), str)]
    by_key = {t["key"]: t for t in tasks}

    def reachable(key: str) -> set:
        seen, todo = set(), list(by_key[key].get("depends_on") or [])
        while todo:
            k = todo.pop()
            if k in seen or k not in by_key:
                continue
            seen.add(k)
            todo += list(by_key[k].get("depends_on") or [])
        return seen

    out = []
    for t in tasks:
        info = skills.get(t.get("skill"))
        if not info:
            continue
        reached = reachable(t["key"])
        for path in required_inputs(info.get("skill_md", ""), info.get("inputs", [])):
            for u in tasks:
                if u is t or u["key"] in reached:
                    continue
                owned = (skills.get(u.get("skill")) or {}).get("outputs", [])
                if any(_artifact(o) == _artifact(path) for o in owned):
                    out.append(f"task {t['key']} reads {path}, which task {u['key']} writes: "
                               f"add \"{u['key']}\" to its depends_on")
    return out


def load(name: str, root: str = ROOT) -> dict:
    """The flow file flows/<name>.json, checked: {"flow", "title", "tasks": [{"key", "skill", "title", "text",
    "depends_on", "milestone"}]}, every task with all six keys. Raises FlowError."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise FlowError(f"{name!r} is not a flow name: lowercase words joined by hyphens")
    file = os.path.join(root, "flows", name + ".json")
    try:
        with open(file, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        raise FlowError(f"no flow file flows/{name}.json (flows there: {', '.join(names(root)) or 'none'})") from None
    except ValueError as e:
        raise FlowError(f"flows/{name}.json is not valid JSON: {e}") from None
    found = problems(data, name, root)
    if found:
        raise FlowError(f"flows/{name}.json: " + "; ".join(found))
    return {"flow": name, "title": data["title"].strip(),
            "tasks": [{"key": t["key"], "skill": t["skill"], "title": t["title"].strip(), "text": t["text"].strip(),
                       "depends_on": list(t.get("depends_on", [])), "milestone": bool(t.get("milestone", False))}
                      for t in data["tasks"]]}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "--check" or any(a.startswith("-") for a in argv[1:]):
        print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
        return 0 if argv in (["--help"], ["-h"]) else 2
    wanted, found = argv[1:] or names(), {}
    for name in wanted:
        try:
            load(name)
        except FlowError as e:
            found[name] = str(e)
    print(json.dumps({"flows": wanted, "problems": found}, indent=1))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
