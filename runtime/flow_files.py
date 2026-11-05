#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Flow files: one data file per flow, with its tasks and their dependencies written out. A flow of the workbench is
flows/<name>.json; a flow of a project is docs/workbench/flows/<name>.json of the project (package P6a).

A flow file is data the runtime's code reads; it is not a skill and no model reads it (a `flow-` skill is the
other thing of that name: a SKILL.md a person runs in a tool). Its form:

  {"flow": "<name>",                  the file's name without .json: lowercase words joined by hyphens
   "title": "<one line>",
   "params": {                        optional: what the request fills in (see "Parameters" below)
     "<name>": {"description": "<one line>", "type": "text" | "file", "default": "<text>"}},
   "tasks": [                         in the order they are planned; each is a skill task or a step task
     {"key": "<name>",                unique in the file; lowercase words joined by hyphens
      "skill": "<skill name>",        a folder of skills/
      "title": "<one line>",
      "text": "<the task's own text, added to the request in the run's prompt>",
      "depends_on": ["<key>", ...],   keys of tasks earlier in the list (so there is no cycle); [] or absent for none
      "milestone": true | false,      absent means false
      "sources": ["<source id>", ...],   optional: the sources the task receives (the flow pins the id, never a version)
      "web": false},                  optional, only false: run a skill that requires the web without it

     {"key": "<name>",                a step task: code runs it, no model (runtime/steps.py, the engine's kinds)
      "step": "<kind>",               a kind of the engine's registry (the plan builder checks it, not this file)
      "args": {...},                  the kind's arguments, checked by the kind when the plan is built
      "title": "<one line>", "text": "<optional; the title when absent>",
      "depends_on": [...], "milestone": ...}
   ]}

A task has `skill` or `step`, never both. A skill task receives the sources it lists and the sources of every `ingest`
step it depends on, directly or through other tasks (sources_of): the plan shows them, and the flow check
(runtime/flow_check.py) refuses a task that requires the web and receives any.

Parameters. A flow declares what the request fills in. A parameter has a name (lowercase letters, digits and
underscores), a one-line description, a type (`text`, the default, or `file`) and, for a text, an optional default. Any
string of a task (its title, its text, a source id, a string inside `args`) may hold `{name}`: bind() replaces it with
the value the request gave. A `file` parameter is the plain name of a file the person handed over for the request
(runtime/ops_flows.py, stage-file), and `{name.sha256}` is the hash of its bytes, so a plan that names a file carries
the hash of exactly that file. The plan's hash covers the bound tasks, so the values given are what the person approves.

Date variables. `{today}` (the ISO date) and `{week}` (the ISO week, YYYY-Www) are filled by bind() from the clock it is
given, in the time zone of that clock (dates() says which). A name that is neither declared nor one of these is a
problem, so a literal brace group around a lowercase word cannot sit in a flow's text. template_sha256() hashes the flow
with its placeholders unfilled: the hash a routine's approval covers (the template, never the values the dates take).

No other key is read today. Reserved for later stages of the platform plan: a top-level "include" (a flow that includes
another) and a task with "writer": "user" in place of "skill" (a document the person writes).

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

import copy
import datetime
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
TOP_KEYS = {"flow", "title", "params", "tasks"}
SKILL_TASK_KEYS = {"key", "skill", "title", "text", "depends_on", "milestone", "sources", "web"}
STEP_TASK_KEYS = {"key", "step", "args", "title", "text", "depends_on", "milestone"}
TASK_KEYS = SKILL_TASK_KEYS | STEP_TASK_KEYS
PARAM_KEYS = {"description", "type", "default"}
PARAM_NAME = re.compile(r"[a-z][a-z0-9_]{0,29}")
PARAM_TYPES = ("text", "file")
DATE_VARIABLES = ("today", "week")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)(\.sha256)?\}")
FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")      # runtime/drop.py NAME: a test holds them equal
SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")              # runtime/sources.py SOURCE_ID: a test holds them equal
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")                # a tab and a newline are text; no other control character is
MAX_PARAM = 8000          # characters of one parameter's value (or default)
PROJECT_DIR = "docs/workbench/flows"
PROJECT_FILE_BYTES = 128 * 1024
INGEST = "ingest"         # the step kind whose `source` argument names a source the tasks after it receive (runtime/step_ingest.py)


class FlowError(Exception):
    """A flow file is missing or not well formed; the message lists every problem."""


def names(root: str = ROOT) -> list:
    """The names of the workbench's flows (flows/*.json of the checkout)."""
    folder = os.path.join(root, "flows")
    if not os.path.isdir(folder):
        return []
    return sorted(n[:-len(".json")] for n in os.listdir(folder) if n.endswith(".json"))


def project_folder(project: str) -> str:
    return os.path.join(project, *PROJECT_DIR.split("/"))


def project_names(project: str) -> list:
    """The names of the project's flows (docs/workbench/flows/*.json): a plain file whose name is a flow name."""
    folder = project_folder(project)
    if not os.path.isdir(folder) or os.path.islink(folder):
        return []
    return sorted(n[:-len(".json")] for n in os.listdir(folder)
                  if n.endswith(".json") and NAME.fullmatch(n[:-len(".json")]) and not os.path.islink(os.path.join(folder, n)))


def all_names(root: str = ROOT, project=None) -> list:
    """[(name, origin)] of the workbench's flows and then the project's: origin is `workbench` or `project`. A project
    flow with the name of a workbench flow is listed (so that the problem can be said) after it."""
    out = [(n, "workbench") for n in names(root)]
    return out + [(n, "project") for n in project_names(project)] if project else out


def _list(value, where: str, out: list, what: str) -> bool:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        out.append(f"{where}: \"{what}\" must be a list of text")
        return False
    return True


def _strings(value):
    """Every string inside a JSON value (the keys of an object are not read)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _task_strings(task: dict):
    """The strings of a task a placeholder may stand in: its title, its text, its sources and the strings of its args."""
    for field in ("title", "text"):
        if isinstance(task.get(field), str):
            yield task[field]
    if isinstance(task.get("sources"), list):
        yield from _strings(task["sources"])
    if isinstance(task.get("args"), dict):
        yield from _strings(task["args"])


def _param_problems(params, out: list) -> dict:
    """The declared parameters, checked; problems are appended to out. Returns the ones that are well formed."""
    if params is None:
        return {}
    if not isinstance(params, dict):
        out.append("\"params\" must be an object of parameters")
        return {}
    good = {}
    for name, spec in params.items():
        where = f"parameter {name!r}"
        if not isinstance(name, str) or not PARAM_NAME.fullmatch(name) or name in DATE_VARIABLES:
            out.append(f"{where}: a name is a lowercase letter then letters, digits or underscores, at most 30, and not "
                       f"{' or '.join(DATE_VARIABLES)} (the date variables)")
            continue
        if not isinstance(spec, dict):
            out.append(f"{where} must be an object")
            continue
        found = [f"{where}: unknown key {k!r}" for k in sorted(set(spec) - PARAM_KEYS)]
        text = spec.get("description")
        if not isinstance(text, str) or not text.strip() or "\n" in text:
            found.append(f"{where}: \"description\" must be one line of text")
        kind = spec.get("type", "text")
        if kind not in PARAM_TYPES:
            found.append(f"{where}: \"type\" must be text or file")
        default = spec.get("default")
        if default is not None:
            if kind == "file":
                found.append(f"{where}: a file parameter has no default")
            elif not isinstance(default, str) or not default.strip() or len(default) > MAX_PARAM or CONTROL.search(default):
                found.append(f"{where}: \"default\" must be text of at most {MAX_PARAM} characters")
        out += found
        if not found:
            good[name] = spec
    return good


def placeholders(flow: dict) -> set:
    """The names of the placeholders the tasks of a flow (file form or loaded form) use, `.sha256` kept as part of the
    name: {"topic", "survey.sha256", "today"}."""
    found = set()
    for task in flow.get("tasks") or []:
        if isinstance(task, dict):
            for text in _task_strings(task):
                found.update(m.group(1) + (m.group(2) or "") for m in PLACEHOLDER.finditer(text))
    return found


def problems(data, name: str, root: str = ROOT) -> list:
    """Why a loaded flow file is not well formed; [] when it is."""
    if not isinstance(data, dict):
        return ["the file must hold a JSON object"]
    out = [f"unknown key {k!r}" for k in sorted(set(data) - TOP_KEYS)]
    if data.get("flow") != name:
        out.append(f"\"flow\" must be {name!r}, the file's name")
    if not isinstance(data.get("title"), str) or not data["title"].strip() or "\n" in data["title"]:
        out.append("\"title\" must be one line of text")
    declared = _param_problems(data.get("params"), out)
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
        is_step = "step" in task
        if is_step and "skill" in task:
            out.append(f"{where}: a task has \"skill\" or \"step\", not both")
        elif is_step:
            out += [f"{where}: a step task has no key {k!r}" for k in sorted(set(task) & (SKILL_TASK_KEYS - STEP_TASK_KEYS))]
            if not isinstance(task["step"], str) or not NAME.fullmatch(task["step"]):
                out.append(f"{where}: \"step\" must be the name of a step kind")
            if not isinstance(task.get("args", {}), dict):
                out.append(f"{where}: \"args\" must be an object")
        else:
            out += [f"{where}: a skill task has no key {k!r}" for k in sorted(set(task) & (STEP_TASK_KEYS - SKILL_TASK_KEYS))]
            skill = task.get("skill")
            if not isinstance(skill, str) or not NAME.fullmatch(skill):
                out.append(f"{where}: \"skill\" must be a skill name")
            elif not os.path.isfile(os.path.join(root, "skills", skill, "SKILL.md")):
                out.append(f"{where}: the skill {skill!r} is not under skills/")
            if "web" in task and task["web"] is not False:
                out.append(f"{where}: \"web\" is only ever false (run a skill that requires the web without it)")
            if "sources" in task and _list(task["sources"], where, out, "sources"):
                for ident in task["sources"]:
                    if not PLACEHOLDER.search(ident) and not SOURCE_ID.fullmatch(ident):
                        out.append(f"{where}: {ident!r} is not a source id (lowercase letters, digits and hyphens, at most 40)")
        if not isinstance(task.get("title"), str) or not task["title"].strip():
            out.append(f"{where}: \"title\" must be text")
        if not (is_step and "text" not in task) and (not isinstance(task.get("text"), str) or not task["text"].strip()):
            out.append(f"{where}: \"text\" must be text")
        depends = task.get("depends_on", [])
        if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
            out.append(f"{where}: \"depends_on\" must be a list of keys")
        else:
            out += [f"{where}: depends on {d!r}, which is not a task earlier in the list" for d in depends if d not in seen]
        if not isinstance(task.get("milestone", False), bool):
            out.append(f"{where}: \"milestone\" must be true or false")
        if isinstance(key, str):
            seen.append(key)
    used = placeholders({"tasks": [t for t in tasks if isinstance(t, dict)]})
    for token in sorted(used):
        base, dotted = (token[:-len(".sha256")], True) if token.endswith(".sha256") else (token, False)
        if base in DATE_VARIABLES:
            if dotted:
                out.append(f"{{{token}}}: a date variable has no .sha256")
        elif base not in (data.get("params") or {}):
            out.append(f"{{{token}}} is used, and the flow declares no parameter {base!r} (the date variables are "
                       f"{' and '.join('{' + d + '}' for d in DATE_VARIABLES)})")
        elif dotted and (data["params"][base] or {}).get("type") != "file":
            out.append(f"{{{token}}}: only a file parameter has a hash")
    for name_, spec in declared.items():
        if name_ not in {t.split(".")[0] for t in used}:
            out.append(f"parameter {name_!r} is declared and no task uses it")
    return out


_PLACEHOLDER_LOOSE = re.compile(r"<[^<>/]+>")


def _cells(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def required_inputs(skill_md: str, declared_inputs: list) -> list:
    """The declared input paths a skill requires without a condition: in the table under `## Inputs`, a row
    whose `Required` cell, stripped and lowercased, is exactly `yes`; from it, every path of declared_inputs
    that occurs literally in its `Artifact` cell. A cell such as `yes for a person` is a condition and is not
    computed, so this is a lower bound. The paths of all the rows, once each (required_rows keeps the rows)."""
    out = []
    for row in required_rows(skill_md, declared_inputs):
        out += [p for p in row if p not in out]
    return out


def required_rows(skill_md: str, declared_inputs: list) -> list:
    """The rows of required_inputs, one list of declared paths each (a row that names none is left out). A row that
    lists several paths lists alternatives ("a task, or a fix plan, or a review finding"): one of them is enough."""
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
        row = [p for p in declared_inputs if p in cells[artifact]]
        if row:
            out.append(row)
    return out


def _artifact(path: str) -> str:
    """Two declared paths are the same artifact when they are equal once each placeholder is a wildcard."""
    return _PLACEHOLDER_LOOSE.sub("*", path)


def dependency_problems(flow: dict, skills: dict) -> list:
    """Each task T that requires (required_rows) a path which the skill of another task U of the same flow writes
    must be run after U, and reach U through depends_on. `skills` maps a skill name to {"inputs", "outputs",
    "skill_md"} and, optionally, "updates" (a task that updates a file after another created it also makes it exist).
    A required row that lists several paths lists alternatives: it is met when one of them is written, or updated, by
    a task T reaches; otherwise every path of the row that a task of the flow writes is a miss, and the text says
    whether the writer is unrelated to T (add it to depends_on) or comes after T (reorder: only a later task writes
    it). One text per miss; a task whose skill is not in `skills` (a step task has none) is skipped."""
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

    def writes(u: dict, path: str, kinds=("outputs",)) -> bool:
        info = skills.get(u.get("skill")) or {}
        return any(_artifact(o) == _artifact(path) for kind in kinds for o in info.get(kind, []))

    out = []
    for t in tasks:
        info = skills.get(t.get("skill"))
        if not info:
            continue
        reached = reachable(t["key"])
        for row in required_rows(info.get("skill_md", ""), info.get("inputs", [])):
            if any(writes(by_key[k], path, ("outputs", "updates")) for k in reached for path in row):
                continue
            for path in row:
                for u in tasks:
                    if u is t or u["key"] in reached or not writes(u, path):
                        continue
                    if t["key"] in reachable(u["key"]):
                        out.append(f"task {t['key']} reads {path}, which only a later task {u['key']} writes: "
                                   f"reorder the tasks")
                    else:
                        out.append(f"task {t['key']} reads {path}, which task {u['key']} writes: "
                                   f"add \"{u['key']}\" to its depends_on")
    return out


def normalise(data: dict, name: str, root: str = ROOT, where=None) -> dict:
    """A flow file that passed problems(), in the loaded form: every task with its defaults. Skill task: {"key", "skill",
    "title", "text", "depends_on", "milestone"} and, only when the file has them, "sources" and "web" (false). Step task:
    {"key", "step", "args", "title", "text", "depends_on", "milestone"}. Top level: {"flow", "title", "params", "tasks"}."""
    found = problems(data, name, root)
    if found:
        raise FlowError(f"{where or name}: " + "; ".join(found))
    tasks = []
    for t in data["tasks"]:
        one = {"key": t["key"]}
        if "step" in t:
            one.update(step=t["step"], args=copy.deepcopy(t.get("args") or {}))
        else:
            one["skill"] = t["skill"]
        one.update(title=t["title"].strip(), text=(t["text"] if "text" in t else t["title"]).strip(),
                   depends_on=list(t.get("depends_on", [])), milestone=bool(t.get("milestone", False)))
        if t.get("sources"):
            one["sources"] = list(t["sources"])
        if t.get("web") is False:
            one["web"] = False
        tasks.append(one)
    params = {n: {"description": s["description"].strip(), "type": s.get("type", "text"),
                  **({"default": s["default"]} if s.get("default") is not None else {})}
              for n, s in (data.get("params") or {}).items()}
    return {"flow": name, "title": data["title"].strip(), "params": params, "tasks": tasks}


def _read_project(name: str, project: str) -> dict:
    """The JSON object of docs/workbench/flows/<name>.json: a plain file inside the project, opened without following a
    link, at most PROJECT_FILE_BYTES. FlowError otherwise."""
    folder = project_folder(project)
    where = f"{PROJECT_DIR}/{name}.json"
    real = os.path.realpath(folder)
    if os.path.islink(folder) or not (real + os.sep).startswith(os.path.realpath(project) + os.sep):
        raise FlowError(f"{PROJECT_DIR} is a link out of the project: no project flow is read from it")
    try:
        fd = os.open(os.path.join(folder, name + ".json"), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise FlowError(f"no flow file {where}") from None
    with os.fdopen(fd, "rb") as f:
        raw = f.read(PROJECT_FILE_BYTES + 1)
    if len(raw) > PROJECT_FILE_BYTES:
        raise FlowError(f"{where} is larger than {PROJECT_FILE_BYTES} bytes")
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise FlowError(f"{where} is not valid JSON: {e}") from None


def load(name: str, root: str = ROOT, project=None) -> dict:
    """The flow of that name, checked, in the loaded form of normalise(), with "origin": `workbench` (flows/<name>.json of the
    checkout) or, when a project is given and the workbench has no such flow, `project` (docs/workbench/flows/<name>.json of
    it). A project flow with the name of a workbench flow is never read: the workbench's wins and the project's is a problem
    of the flow check. Raises FlowError."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise FlowError(f"{name!r} is not a flow name: lowercase words joined by hyphens")
    file = os.path.join(root, "flows", name + ".json")
    origin = "workbench"
    if os.path.isfile(file):
        try:
            with open(file, encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            raise FlowError(f"no flow file flows/{name}.json") from None
        except ValueError as e:
            raise FlowError(f"flows/{name}.json is not valid JSON: {e}") from None
        where = f"flows/{name}.json"
    elif project:
        origin, where = "project", f"{PROJECT_DIR}/{name}.json"
        try:
            data = _read_project(name, project)
        except FlowError as e:
            raise FlowError(f"{e} (flows there: {', '.join(n for n, _ in all_names(root, project)) or 'none'})") from None
    else:
        raise FlowError(f"no flow file flows/{name}.json (flows there: {', '.join(names(root)) or 'none'})")
    return {**normalise(data, name, root, where), "origin": origin}


def to_file(flow: dict) -> dict:
    """A loaded flow as the object its file holds (no origin; params only when declared), ready to be written as JSON."""
    out = {"flow": flow["flow"], "title": flow["title"]}
    if flow.get("params"):
        out["params"] = copy.deepcopy(flow["params"])
    out["tasks"] = copy.deepcopy(flow["tasks"])
    return out


def needs_plan(flow: dict) -> bool:
    """Whether a flow is started only through a plan the person approves by its hash: a project flow, a flow with a step, with
    parameters, with a task that lists sources or says `web: false` (the plan carries them, and the plan card and the flow check read
    them). (The request that names a workbench flow of skills and no parameter plans it and starts it, as it
    always did.)"""
    return flow.get("origin") == "project" or bool(flow.get("params")) or any(
        "step" in t or t.get("sources") or "web" in t for t in flow["tasks"])


def file_params(flow: dict) -> list:
    """The names of the flow's file parameters, in the order declared."""
    return [n for n, s in (flow.get("params") or {}).items() if s.get("type") == "file"]


# --- the sources a task receives ---------------------------------------------------------------------------------------------


def sources_of(flow: dict, bringing=(INGEST,)) -> dict:
    """{task key: [source ids]} for every skill task: the ids it lists, then the `source` argument of every step it depends on,
    directly or through other tasks, whose kind is one of `bringing` (the kinds that declare Kind.brings_source: runtime/steps.py
    sourcing_kinds(); `ingest` when none is given), once each, in that order. A task that receives none has an empty list. What a
    task receives through an artifact (a task that depends on a task that received a source) is not followed: D16 speaks of what a
    task receives."""
    by_key = {t["key"]: t for t in flow["tasks"]}

    def ingested(key: str) -> list:
        found, seen, todo = [], set(), list(by_key[key].get("depends_on") or [])
        while todo:
            k = todo.pop(0)
            if k in seen or k not in by_key:
                continue
            seen.add(k)
            t = by_key[k]
            if t.get("step") in bringing and isinstance((t.get("args") or {}).get("source"), str):
                found.append(t["args"]["source"])
            todo += list(t.get("depends_on") or [])
        return found

    out = {}
    for t in flow["tasks"]:
        if "skill" not in t:
            continue
        ids = []
        for ident in list(t.get("sources") or []) + ingested(t["key"]):
            if ident not in ids:
                ids.append(ident)
        out[t["key"]] = ids
    return out


# --- parameters and dates ----------------------------------------------------------------------------------------------------


def dates(now) -> dict:
    """{"today", "week", "zone"} for a clock reading. `now` is a timezone-aware datetime (a naive one is a ValueError: the date
    of a moment depends on the zone, and the plan says which zone it used). today is the ISO date in now's own zone; week the ISO
    week of that date, YYYY-Www; zone its name and offset from UTC, "CET (UTC+01:00)"."""
    if not isinstance(now, datetime.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("the clock reading has no time zone")
    iso = now.isocalendar()
    minutes = int(now.utcoffset().total_seconds() // 60)
    sign, minutes = ("-" if minutes < 0 else "+"), abs(minutes)
    offset = f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"
    name = now.tzname()
    return {"today": now.date().isoformat(), "week": f"{iso[0]}-W{iso[1]:02d}",
            "zone": f"{name} ({offset})" if name and not name.startswith("UTC") else offset}


def check_value(name: str, spec: dict, value) -> str:
    """A parameter's value, checked: text of 1 to MAX_PARAM characters with no control character but a tab and a newline; for
    a file parameter, a plain file name. FlowError names the parameter."""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_PARAM or CONTROL.search(value):
        raise FlowError(f"parameter {name}: a value is text of 1 to {MAX_PARAM} characters with no control character")
    if spec.get("type") == "file" and not FILE_NAME.fullmatch(value):
        raise FlowError(f"parameter {name}: a file is a plain name (letters, digits, '.', '_' and '-', at most 100 characters)")
    return value


def _fill(text: str, values: dict, single_line: bool) -> str:
    def one(match):
        token = match.group(1) + (match.group(2) or "")
        if token not in values:
            raise FlowError(f"{{{token}}} has no value")
        return " ".join(values[token].split()) if single_line else values[token]
    return PLACEHOLDER.sub(one, text)


def _fill_value(value, values: dict):
    if isinstance(value, str):
        return _fill(value, values, False)
    if isinstance(value, dict):
        return {k: _fill_value(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill_value(v, values) for v in value]
    return value


def bind(flow: dict, params, now, files=None) -> dict:
    """The flow with its placeholders filled: {"flow": the flow, with no placeholder left, "bound": {"params": {name: value},
    "files": {name: {"name", "sha256"}}, "dates": dates(now)}}. `params` is {name: text}: a name the flow does not declare, a
    required parameter (no default) that is missing and a value that fails check_value are FlowErrors, each naming the
    parameter and the parameters there are. `files` is {file name: sha256 of its bytes} for the files handed over; a file
    parameter whose file is not in it is a FlowError. Only the title, the text, the sources and the strings of `args` are
    filled; a placeholder in a title is filled with the value's words on one line."""
    declared = flow.get("params") or {}
    given = dict(params or {})
    unknown = sorted(set(given) - set(declared))
    if unknown:
        raise FlowError(f"the flow {flow['flow']} has no parameter {', '.join(unknown)}; it has: {', '.join(declared) or 'none'}")
    clock = dates(now)
    values, shown, handed = {d: clock[d] for d in DATE_VARIABLES}, {}, {}
    missing = []
    for name, spec in declared.items():
        value = given.get(name, spec.get("default"))
        if value is None:
            missing.append(name)
            continue
        value = check_value(name, spec, value)
        values[name], shown[name] = value, value
        if spec.get("type") == "file":
            digest = (files or {}).get(value)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise FlowError(f"parameter {name}: no file {value!r} is handed over for this request: hand it over first")
            values[name + ".sha256"] = digest
            handed[name] = {"name": value, "sha256": digest}
    if missing:
        raise FlowError(f"the flow {flow['flow']} needs a value for {', '.join(missing)} (--param name=value)")
    tasks = []
    for t in flow["tasks"]:
        one = copy.deepcopy(t)
        one["title"], one["text"] = _fill(t["title"], values, True), _fill(t["text"], values, False)
        if "args" in one:
            one["args"] = _fill_value(one["args"], values)
        if "sources" in one:
            one["sources"] = _fill_value(one["sources"], values)
        tasks.append(one)
    return {"flow": {**flow, "tasks": tasks}, "bound": {"params": shown, "files": handed, "dates": clock}}


def template_sha256(flow: dict) -> str:
    """The sha256 of the flow's template: its name, its parameters as declared and its tasks, with every placeholder as it is
    written (nothing filled), as JSON with sorted keys and no spaces. Neither the title, nor the origin, nor the values a
    request or a clock gives are in it: it moves only when the flow itself changes."""
    body = {"flow": flow["flow"], "params": flow.get("params") or {}, "tasks": flow["tasks"]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


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
