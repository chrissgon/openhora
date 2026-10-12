#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The plan of a request: the tasks code builds from a route, which the person approves before any task exists.

The planning agent creates no task (limit L19): the router returns a route, or the person names a flow, and this
module turns it into the tasks of a plan, from the flow file (runtime/flow_files.py) or, for a route to one skill, a
plan of one task. The plan is shown to the person as a pending decision of kind `plan`; its tasks are created only
when the person approves it (runtime/ops.py, approve), and only the approved tasks, by their hash.

Functions:
  pack_skills(project_cfg, root)            the names of the skills in scope: the union of the packs of the enabled
                                            area agents of the project's configuration, else the pack `default`
  from_flow(flow, root, pack)               the tasks of a loaded flow file, as plan tasks
  from_skill(skill, title, root)            a plan of one task, with an empty text: its prompt is the plain request
  plan_hash(tasks)                          the sha256 of the tasks, the hash the person approves
  title_of(text, title=None)                the title of a request: the one given, else the first sentence of the
                                            text when it fits TITLE_CHARS, else the first line cut at a word
  request_title(row)                        the title shown for a request row of the store, whatever rule made its
                                            stored title (the plan's first line and the rows of `status` use it)
  scope_refusal(flow, outside, root)        the sentence of a flow whose skills no enabled area agent has
  build(request, tasks, route, source, limits, past, flow=None, deliveries=None, unrouted=None)
                                            the title, the body and the payload of the plan

Stage 6 (several deliveries, the brief, sub-tasks):
  split(text)                               {"preamble", "items"}: the lines of a request that start with "- " are its
                                            deliveries (fewer than two: one delivery, the whole text); at most
                                            MAX_DELIVERIES, each costs one run of the router
  resolve_pack(pack, root)                  the skills of one pack, by scripts/select_skills.py
  agent_skills(project_cfg, root)           {"<agent>": [skills of its pack]} for every enabled area agent
  agent_of(skill, agent_skills)             the one enabled agent other than planning whose pack holds the skill (the
                                            planning agent when only its pack does); none or several: ValueError
  owner_of(path, root)                      the skill whose declared outputs hold path, or None
  delivery_tasks(route, k, flows, root, pack, prefix)   the tasks of one routed delivery
  combine(request, routed, flows, agent_skills, root, *, pack, limits, past)   one plan from the routes of the
                                            deliveries, in the order listed: {"plan": build() or None, "tasks",
                                            "deliveries", "unrouted"}
  backlog_tasks(backlog_path, root=None)    the product backlog's `todo` tasks as proposed sub-tasks, each read by one
                                            run of the sub-task skill's script task.py (runtime/isolated.py: an
                                            isolated subprocess, never loaded into this process)
  subtasks(limits, existing_count, proposed, known=())   {"create", "ask"}: what the approved plan's limits cover

Derived waits (A-29: the runtime knows by itself which task waits for which, from the artifact contract):
  skill_facts(root)                         {skill: {"inputs", "outputs", "required"}} of every skill folder: the
                                            frontmatter lists, and the inputs whose row of the skill's inputs table says
                                            Required: yes (flow_files.required_inputs)
  owners_of(index, path)                    the skills whose declared outputs are path (placeholders read as wildcards)
  derive(nodes, facts, exists, ...)         {"waits", "missing", "cycles"}: for each task not yet started, the open task of
                                            another request that writes an input the project does not have yet; the
                                            required inputs nothing writes; the waits left out because they would wait
                                            in a circle. Pure: the project is read through the exists function it is given
  wait_lines(waits, missing, cycles, titles)   the lines a plan's body adds for them

A plan task is {"key", "skill", "title", "text", "depends_on": [keys], "milestone", "mandatory_milestone", "web"}:
milestone is true when the flow file says so or the skill's runtime manifest makes it a mandatory milestone; web is
whether the skill requires the web. No cost in money is written: the estimate counts runs.

Usage (a library; the shell is runtime/cli.py, verbs route, approve, reject): python3 runtime/plan.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autonomy  # noqa: E402  (the same folder)
import flow_files  # noqa: E402  (the one reader of a skill's Required column: what scripts/validate.py reads)
import isolated  # noqa: E402
import manifest  # noqa: E402
import roles  # noqa: E402
import skill_meta  # noqa: E402

DEFAULT_PACK = "default"
CATCH_ALL_PACKS = ("default", "all")  # packs that hold nearly every skill: never the pack a refusal tells the person to add
PACKS_DIR = "packs"
TITLE_CHARS = 120                # the longest title a request gets from its text, the ellipsis included
SENTENCE_ENDS = (". ", "! ", "? ", "\n")
SELECT_TIMEOUT = 60
PLANNING = "planning"            # the planning agent: the entry of area_agents with this name (part 0, F.6)
MAX_DELIVERIES = 8               # each delivery costs one run of the router
BRIEF_SKILL = roles.load()["brief"]  # runtime/roles.json: a route to it plans one brief task, and the delivery is routed again after it
BRIEFS_DIR = "docs/workbench/briefs/"
BACKLOG = "docs/product/backlog.md"
SUBTASK_SKILL = roles.load()["subtask"]  # runtime/roles.json: the one skill a sub-task runs in this stage (a product-backlog task)
SUBTASKS_PER_PLAN = 20
DELIVERIES_FLOW = "deliveries"   # the flow label of a plan of several deliveries: no flow file has this name
RUNS_PER_TASK = 2
ESTIMATE_FORMULA = "2 runs per task (consolidated plan, section 4)"
BACKLOG_ID = re.compile(r"T-[a-z0-9]+-\d+")
BACKLOG_TASK_LINE = re.compile(r"^- (" + BACKLOG_ID.pattern + r"):", re.M)  # where the backlog defines a task
BACKLOG_TIMEOUT = 30   # seconds for one read of one task
BACKLOG_JOBS = 8       # the reads are independent: they run at the same time
CHECKOUT = os.path.dirname(HERE)
WAIT_INPUT = "input"             # a derived wait: a path another request's task writes
WAIT_AFTER = "after"             # the person's override: after request #n
PLACEHOLDER = re.compile(r"<[^<>/]*>")


class PlanError(Exception):
    """No plan can be built: a pack that does not resolve, a task whose skill is outside the pack."""


def pack_skills(project_cfg: dict, root: str) -> list:
    """The sorted names of the skills in scope. project_cfg is project_config.load() of the project (or its raw
    object). With `area_agents`, the union of the packs of the enabled entries, as runtime/autonomy.py reads them (an
    entry without `enabled` is enabled); without it, the pack `default`. A pack is resolved by
    scripts/select_skills.py of the workbench checkout."""
    raw = project_cfg.get("raw", project_cfg) if isinstance(project_cfg, dict) else {}
    if raw.get("area_agents") is None:
        return sorted(resolve_pack(DEFAULT_PACK, root))
    return sorted({name for names in agent_skills(project_cfg, root).values() for name in names})


def resolve_pack(pack: str, root: str) -> list:
    """The names of the skills of one pack, by scripts/select_skills.py of the workbench checkout."""
    try:
        done = subprocess.run([sys.executable, os.path.join(root, "scripts", "select_skills.py"), "--pack", pack],
                              capture_output=True, text=True, timeout=SELECT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise PlanError(f"the pack {pack} could not be resolved: {type(e).__name__}") from None
    try:
        found = json.loads(done.stdout) if done.returncode == 0 else None
    except ValueError:
        found = None
    if not isinstance(found, list):
        reason = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
        raise PlanError(f"the pack {pack} could not be resolved: {reason}")
    return list(found)


def agent_skills(project_cfg: dict, root: str) -> dict:
    """{"<agent>": [sorted skills of its pack]} for every enabled entry of area_agents (an entry without `enabled` is
    enabled, as runtime/autonomy.py reads them); {} without the key. Each pack is resolved as pack_skills resolves
    one."""
    raw = project_cfg.get("raw", project_cfg) if isinstance(project_cfg, dict) else {}
    if raw.get("area_agents") is None:
        return {}
    try:
        agents = autonomy.agents(raw.get("area_agents"))
    except ValueError as e:
        raise PlanError(str(e)) from None
    resolved, out = {}, {}
    for name in sorted(agents):
        if agents[name]["enabled"]:
            pack = agents[name]["pack"]
            if pack not in resolved:
                resolved[pack] = sorted(resolve_pack(pack, root))
            out[name] = resolved[pack]
    return out


def agent_of(skill: str, agents: dict) -> str:
    """The area agent that owns a task of this skill: the one enabled agent, other than planning, whose pack holds it;
    the planning agent when only its pack holds it (the brief). None or several: ValueError naming the skill and the
    agents."""
    owners = [name for name, skills in sorted(agents.items()) if name != PLANNING and skill in skills]
    if not owners and skill in agents.get(PLANNING, ()):
        owners = [PLANNING]
    if len(owners) != 1:
        raise ValueError(f"the skill {skill} is in the pack of {len(owners)} enabled area agents "
                         f"({', '.join(owners) or 'none'}): exactly one must own its task")
    return owners[0]


def owner_of(path: str, root: str):
    """The skill whose metadata.outputs holds path (the artifact contract: one owner), read with skill_meta; None when
    no skill of the checkout declares it."""
    folder = os.path.join(root, "skills")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not os.path.isfile(os.path.join(folder, name, "SKILL.md")):
            continue
        try:
            outputs = skill_meta.declared(os.path.join(folder, name))["outputs"]
        except skill_meta.SkillError:
            continue
        if path in outputs:
            return name
    return None


def mandatory(skill: str, root: str) -> bool:
    """Whether a task of this skill is a milestone in every mode: mandatory_milestone of its runtime manifest, the
    one source; False for a skill with no manifest."""
    if not os.path.isfile(manifest.path(root, skill)):
        return False
    return bool(manifest.load(root, skill).get("mandatory_milestone"))


def _task_facts(skill: str, root: str) -> dict:
    meta = skill_meta.declared(os.path.join(root, "skills", skill))
    return {"mandatory_milestone": mandatory(skill, root), "web": bool(meta["web"])}


def _packs_holding(skills: list, root: str) -> dict:
    """{skill: the narrowest pack of <root>/packs/*.txt that holds it, or None}: the pack with the fewest skills
    (then the first by name), the catch-all packs `default` and `all` left out. A pack that does not resolve is
    skipped: the refusal is worded with the packs that do."""
    folder = os.path.join(root, PACKS_DIR)
    names = sorted(f[:-4] for f in os.listdir(folder) if f.endswith(".txt")) if os.path.isdir(folder) else []
    sized = []
    for name in names:
        if name in CATCH_ALL_PACKS:
            continue
        try:
            sized.append((name, set(resolve_pack(name, root))))
        except PlanError:
            continue
    out = {}
    for skill in skills:
        holding = [(len(held), name) for name, held in sized if skill in held]
        out[skill] = min(holding)[1] if holding else None
    return out


def scope_refusal(flow_name: str, outside: list, root: str) -> str:
    """The sentence of a flow whose skills (outside, in the flow's order) no enabled area agent has: the pack each
    one belongs to, the skills of each pack, and the line to add to runtime.json. A skill in no pack of packs/ is
    said to be in none. The pack is read from <root>/packs/*.txt through resolve_pack, the resolver the plan uses."""
    found = _packs_holding(outside, root)
    by_pack = {}
    for skill in outside:
        if found[skill] is not None:
            by_pack.setdefault(found[skill], []).append(skill)
    orphans = [skill for skill in outside if found[skill] is None]
    parts = []
    if by_pack:
        named = [f"{pack} (skills {', '.join(skills)})" for pack, skills in by_pack.items()]
        needs = (f"needs the pack {named[0]}" if len(named) == 1
                 else f"needs the packs {', '.join(named[:-1])} and {named[-1]}")
        quoted = [f'"pack": "{pack}"' for pack in by_pack]
        add = (f"add an area agent with {quoted[0]}" if len(quoted) == 1
               else f"add area agents with {', '.join(quoted[:-1])} and {quoted[-1]}")
        parts.append(f"the flow {flow_name} {needs}, and no enabled area agent of runtime.json has "
                     f"{'it' if len(named) == 1 else 'them'}; {add} to area_agents and accept the configuration")
    if orphans:
        one = len(orphans) == 1
        parts.append(f"in the flow {flow_name}, {', '.join(orphans)} {'is' if one else 'are'} in no pack of packs/: add "
                     f"{'it' if one else 'them'} to a pack, give an area agent that pack and accept the configuration")
    return "; and ".join(parts)


def from_flow(flow: dict, root: str, pack) -> list:
    """The tasks of a flow file (flow_files.load()) as plan tasks, in its order. A task whose skill is not in pack
    raises PlanError saying which pack of packs/ holds the skills and what to add to runtime.json (scope_refusal)."""
    outside = [t["skill"] for t in flow["tasks"] if t["skill"] not in list(pack)]
    if outside:
        raise PlanError(scope_refusal(flow["flow"], outside, root))
    tasks = []
    for t in flow["tasks"]:
        try:
            facts = _task_facts(t["skill"], root)
        except (skill_meta.SkillError, manifest.ManifestError) as e:
            raise PlanError(str(e)) from None
        tasks.append({"key": t["key"], "skill": t["skill"], "title": t["title"], "text": t["text"],
                      "depends_on": list(t["depends_on"]), "milestone": bool(t["milestone"]) or facts["mandatory_milestone"],
                      **facts})
    return tasks


def from_skill(skill: str, title: str, root: str) -> list:
    """A plan of one task: the key is the skill's name, the text is empty (the run's prompt is the plain request),
    no dependency."""
    try:
        facts = _task_facts(skill, root)
    except (skill_meta.SkillError, manifest.ManifestError) as e:
        raise PlanError(str(e)) from None
    return [{"key": skill, "skill": skill, "title": title, "text": "", "depends_on": [],
             "milestone": facts["mandatory_milestone"], **facts}]


def title_of(text: str, title=None) -> str:
    """The title of a request. The one given, when there is one; else the first sentence of the text (up to the first
    ". ", "! ", "? " or line end, its closing mark kept) when it is at most TITLE_CHARS characters; else the first
    line cut at the last word that fits, with "…" (TITLE_CHARS in all). A word longer than the limit is cut inside."""
    if isinstance(title, str) and title.strip():
        return " ".join(title.split())
    text = (text or "").strip()
    ends = [(text.find(mark), len(mark.strip())) for mark in SENTENCE_ENDS if text.find(mark) >= 0]
    sentence = text
    if ends:
        at, mark = min(ends)
        sentence = text[:at + mark]
    sentence = " ".join(sentence.split())
    if len(sentence) <= TITLE_CHARS:
        return sentence
    line = " ".join(text.split("\n", 1)[0].split())
    room = TITLE_CHARS - 1
    cut = line[:room]
    if line[room:room + 1] != " ":
        boundary = cut.rfind(" ")
        cut = cut[:boundary] if boundary > 0 else cut
    return cut.rstrip(" ,;:-") + "…"


def request_title(row: dict) -> str:
    """The title shown for a request row of the store ({"title", "text"}). A row whose stored title is the first line
    of its text cut at TITLE_CHARS is one that no person titled (the rule before title_of): it is titled again by
    title_of. Any other stored title was given, or is a flow's, and is kept."""
    stored, text = row.get("title") or "", row.get("text") or ""
    if text and stored == text.split("\n", 1)[0][:TITLE_CHARS].strip():
        return title_of(text)
    return stored


def plan_hash(tasks: list) -> str:
    """The sha256 of the tasks as JSON with sorted keys and no spaces: what the person approves."""
    return hashlib.sha256(json.dumps(tasks, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build(request: dict, tasks: list, route, source: str, limits: dict, past: list, flow=None, deliveries=None,
          unrouted=None) -> dict:
    """{"title", "body", "payload"} of the pending decision of kind `plan`. request is the request's row; route the
    route read from the router's reply (None for a flow the person named); source `router` or `named`; limits from
    the gate file; past the rows of task_runs of the plan's skills in this store. deliveries and unrouted (stage 6,
    combine) add the plan's deliveries, what was not routed, and the estimate's runs and formula."""
    if source not in ("router", "named"):
        raise PlanError("a plan's source is router or named")
    skills = list(dict.fromkeys(t["skill"] for t in tasks))
    estimate_past = []
    for skill in skills:
        runs = [r for r in past if r.get("skill") == skill]
        durations = [r["duration_ms"] for r in runs if isinstance(r.get("duration_ms"), int)]
        estimate_past.append({"skill": skill, "runs": len(runs),
                              "mean_duration_ms": round(sum(durations) / len(durations)) if durations else None})
    digest = plan_hash(tasks)
    payload = {"source": source, "route": route, "flow": flow, "tasks": tasks, "limits": limits,
               "estimate": {"tasks": len(tasks), "runs_at_least": len(tasks), "past": estimate_past},
               "plan_sha256": digest}
    several = deliveries is not None and len(deliveries) + len(unrouted or []) > 1
    if deliveries is not None:
        payload.update(deliveries=deliveries, unrouted=list(unrouted or []))
        payload["estimate"].update(runs=RUNS_PER_TASK * len(tasks), formula=ESTIMATE_FORMULA)
    keys = {t["key"]: n for n, t in enumerate(tasks, 1)}
    if several:
        said = f"the router, once per delivery ({len(deliveries) + len(unrouted or [])} listed)"
    else:
        said = ('the router, ' + route['line'] if source == 'router' and route else 'the flow you named') + \
               (f"; flow file flows/{flow}.json" if flow and flow != DELIVERIES_FLOW else "")
    lines = [f"Plan for request {request['id']}: {request_title(request)}", f"Source: {said}", ""]
    if several:
        lines += ["Deliveries, in the order listed (each starts after the one before it):"]
        lines += [f"- {d['item']}: {d['route']} -> {', '.join(d['tasks'])}"
                  + (f" (routed again after {d['reroute_after']})" if d.get("reroute_after") else "") for d in deliveries]
        lines += [""]
    lines += ["| # | Task | Skill | After | Milestone | Web |", "|---|---|---|---|---|---|"]
    for n, t in enumerate(tasks, 1):
        after = ", ".join(str(keys[d]) for d in t["depends_on"]) or "-"
        milestone = "yes, mandatory" if t.get("mandatory_milestone") else "yes" if t["milestone"] else "no"
        lines.append(f"| {n} | {t['title']} | {t['skill']} | {after} | {milestone} | "
                     f"{'yes' if t['web'] else 'no'} |")
    lines += ["", f"One task at a time; each run at most {limits.get('timeout_seconds')} s, retried at most "
                  f"{limits.get('retries')} times. At least {len(tasks)} runs.",
              "Past runs of these skills here: " + "; ".join(
                  f"{p['skill']} {p['runs']}" + (f" (mean {p['mean_duration_ms']} ms)" if p["mean_duration_ms"] is not None else "")
                  for p in estimate_past) + ".",
              f"Plan hash: {digest}"]
    if deliveries is not None:
        lines.insert(-1, f"Estimate: {RUNS_PER_TASK * len(tasks)} runs ({ESTIMATE_FORMULA}).")
    for n, u in enumerate(unrouted or [], 1):
        lines += ["", f"Not planned {n}: {u['item']} ({u['why']}). The router's reply, whole:", "", u["reply"].rstrip("\n")]
    count = f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}"
    title = f"Plan: {len(deliveries)} deliveries ({count})" if several else f"Plan: {flow or tasks[0]['skill']} ({count})"
    return {"title": title, "body": "\n".join(lines), "payload": payload}


# --- derived waits between requests (A-29) -------------------------------------------------------------------------


def skill_facts(root: str) -> dict:
    """{skill: {"inputs", "outputs", "required"}} for every skill folder of the checkout: the declared lists
    (runtime/skill_meta.py) and, as `required`, flow_files.required_inputs: the rows of the `## Inputs` table whose Required
    cell is exactly `yes`, the same reading scripts/validate.py makes. A folder that does not parse is left out."""
    folder = os.path.join(root, "skills")
    out = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        path = os.path.join(folder, name)
        if not os.path.isfile(os.path.join(path, "SKILL.md")):
            continue
        try:
            meta = skill_meta.declared(path)
        except skill_meta.SkillError:
            continue
        try:
            with open(os.path.join(path, "SKILL.md"), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        out[name] = {"inputs": meta["inputs"], "outputs": meta["outputs"],
                     "required": set(flow_files.required_inputs(text, meta["inputs"]))}
    return out


def normal(path: str) -> str:
    """A declared path with each placeholder read as a wildcard: two paths are the same artifact when these are equal."""
    return PLACEHOLDER.sub("*", path)


def owners_of(facts: dict, path: str) -> list:
    """The skills whose declared outputs are path, sorted: the artifact contract has one owner, so one name in
    practice. A path that ends in "/" is a folder: the skills with an output under it."""
    wanted = normal(path)
    if wanted.endswith("/"):
        return sorted(name for name, f in facts.items() if any(normal(o).startswith(wanted) for o in f["outputs"]))
    return sorted(name for name, f in facts.items() if any(normal(o) == wanted for o in f["outputs"]))


def _order(ref):
    return (0, ref, "") if isinstance(ref, int) else (1, 0, str(ref))


def derive(nodes: list, facts: dict, exists, *, after_of=None, open_requests=(), only=None, fixed=None) -> dict:
    """The waits of the tasks not yet started. Pure: the project is read only through exists(path).

    nodes     every task that is not final, as {"ref", "request", "skill", "candidate", "depends_on": [refs]}: ref is
              the task's id (or any other hashable name for a task of a plan not created yet), request the id of its
              request (or a name for a plan's), candidate whether it can still wait (it is planned or ready)
    facts     skill_facts()
    exists    exists(path) -> whether the project has the file
    after_of  {request: the request it is to run after} (the person's override)
    open_requests   the requests that are not done or cancelled
    only      refs to derive for (default: every candidate)
    fixed     {ref: {refs}}: edges that already hold (waits the store has), for the circle check

    A candidate waits, for each declared input the project does not have, for the oldest task of another request whose
    skill owns that input (the artifact contract); an input a task of its own request writes is that flow's business;
    an input nothing writes makes no wait, and when its skill requires it, a `missing` entry; a skill that reads its
    own output (a plan it keeps up, a log it appends to) waits for no one and misses nothing for that path: it starts it. A wait that would close a
    circle with the dependencies and the waits already made (candidates are taken oldest first) is not made and is
    listed in `cycles`.
    Returns {"waits": [{"ref", "kind", "awaited", "path", "reason"}], "missing": [{"ref", "skill", "path", "owner",
    "sentence"}], "cycles": [{"ref", "kind", "awaited", "path", "sentence"}]}; for an `after` wait awaited is the request."""
    edges = {n["ref"]: set(n.get("depends_on") or []) for n in nodes}
    for ref, awaited in (fixed or {}).items():
        edges.setdefault(ref, set()).update(awaited)

    def reaches(start, goal) -> bool:
        seen, todo = set(), [start]
        while todo:
            at = todo.pop()
            if at == goal:
                return True
            if at not in seen:
                seen.add(at)
                todo.extend(edges.get(at, ()))
        return False

    waits, missing, cycles = [], [], []
    chosen = sorted((n for n in nodes if n.get("candidate") and (only is None or n["ref"] in only)),
                    key=lambda n: _order(n["ref"]))
    for n in chosen:
        ref, skill = n["ref"], n.get("skill")
        target = (after_of or {}).get(n["request"])
        if target is not None and target in open_requests and target != n["request"]:
            theirs = [m["ref"] for m in nodes if m["request"] == target]
            if any(reaches(t, ref) for t in theirs):
                cycles.append({"ref": ref, "kind": WAIT_AFTER, "awaited": target, "path": None,
                               "sentence": f"{skill} would wait for request #{target}, which waits for it: no wait was made"})
            else:
                edges.setdefault(ref, set()).update(theirs)
                waits.append({"ref": ref, "kind": WAIT_AFTER, "awaited": target, "path": None,
                              "reason": f"after request #{target}"})
        meta = facts.get(skill)
        if not meta:
            continue
        for path in meta["inputs"]:
            if exists(path):
                continue
            owners = owners_of(facts, path)
            if skill in owners:
                continue  # the skill reads what it writes itself: no task waits for another of its own skill
            if any(m["skill"] in owners and m["request"] == n["request"] and m["ref"] != ref for m in nodes):
                continue
            writers = sorted((m for m in nodes if m["skill"] in owners and m["request"] != n["request"]),
                             key=lambda m: _order(m["ref"]))
            if writers:
                free = [m for m in writers if not reaches(m["ref"], ref)]
                if not free:
                    cycles.append({"ref": ref, "kind": WAIT_INPUT, "awaited": writers[0]["ref"], "path": path,
                                   "sentence": f"{skill} would wait for task #{writers[0]['ref']} ({path}), which waits "
                                               "for it: no wait was made"})
                    continue
                edges.setdefault(ref, set()).add(free[0]["ref"])
                waits.append({"ref": ref, "kind": WAIT_INPUT, "awaited": free[0]["ref"], "path": path,
                              "reason": f"{path}, written by task #{free[0]['ref']}"})
            elif path in meta["required"]:
                owner = owners[0] if owners else None
                how = f"run {owner} first" if owner else "add the file"
                missing.append({"ref": ref, "skill": skill, "path": path, "owner": owner,
                                "sentence": f"{skill} needs {path}; nothing writes it: {how} or go ahead and it will stop"})
    return {"waits": waits, "missing": missing, "cycles": cycles}


def wait_lines(waits: list, missing: list, cycles: list, titles: dict) -> list:
    """The lines a plan's body adds for its waits, its required inputs nothing writes and its waits left out as a
    circle (empty when there are none). titles maps a ref to the task's title."""
    lines = []
    if waits:
        lines += ["", "Waits (derived from what each skill reads; approve with go ahead on a task to drop its wait):"]
        lines += [f"- {titles.get(w['ref'], w['ref'])} waits: {w['reason']}" for w in waits]
    if missing:
        lines += ["", "Inputs nothing writes:"]
        lines += [f"- {titles.get(m['ref'], m['ref'])}: {m['sentence']}" for m in missing]
    if cycles:
        lines += ["", "Waits left out, because they would wait in a circle:"]
        lines += [f"- {titles.get(c['ref'], c['ref'])}: {c['sentence']}" for c in cycles]
    return lines


# --- stage 6: several deliveries, the brief, sub-tasks -------------------------------------------------------------


def split(text: str) -> dict:
    """The deliveries of a request: {"preamble", "items"}. A line is an item when, after leading spaces, it starts
    with "- ". Fewer than two such lines: one item, the whole text, and no preamble. Otherwise the preamble is every
    other line joined, and each item is its line without the "- ". More than MAX_DELIVERIES items: ValueError."""
    lines = (text or "").splitlines()
    items = [line.lstrip()[2:].strip() for line in lines if line.lstrip().startswith("- ")]
    if len(items) < 2:
        return {"preamble": "", "items": [text]}
    if len(items) > MAX_DELIVERIES:
        raise ValueError(f"the request lists {len(items)} deliveries and the limit is {MAX_DELIVERIES}: each costs one run "
                         "of the router; split it into several requests")
    preamble = "\n".join(line for line in lines if not line.lstrip().startswith("- ")).strip()
    return {"preamble": preamble, "items": items}


def delivery_tasks(route: dict, k: int, flows: dict, root: str, pack, prefix: bool) -> list:
    """The plan tasks of one routed delivery k (route: router.read_route() with "checked": router.check_route()).
    A flow route: its tasks as from_flow gives them; a capability: the one task from_skill gives, keyed by the skill;
    the brief skill: one task keyed "brief", a milestone. With prefix, every key and dependency gets "d<k>-"."""
    checked = route["checked"]
    if "flow" in checked:
        tasks = from_flow(flows[checked["flow"]], root, pack)
    elif checked["skill"] == BRIEF_SKILL:
        tasks = [dict(from_skill(BRIEF_SKILL, "Brief", root)[0], key="brief", milestone=True)]
    else:
        tasks = from_skill(checked["skill"], route.get("title") or checked["skill"], root)
    if prefix:
        tasks = [dict(t, key=f"d{k}-{t['key']}", depends_on=[f"d{k}-{d}" for d in t["depends_on"]]) for t in tasks]
    return tasks


def combine(request: dict, routed: list, flows: dict, agent_skills: dict, root: str, *, pack, limits: dict,
            past: list) -> dict:
    """One plan from the routes of the deliveries, in the order listed (decision P3). routed is [{"item", "route",
    "reply"}], route None when the router asked or gave no route line, else read_route() with "checked". A delivery
    whose route is not valid goes to "unrouted" with the whole reply and gets no task. The first tasks of a delivery
    depend on the last task of the delivery before it. Each task gets its agent (agent_of; None for every task when no
    area agent is configured). Returns {"plan": build(...) or None when no task, "tasks", "deliveries", "unrouted"}."""
    several = len(routed) > 1
    tasks, deliveries, unrouted, last, routes = [], [], [], None, []
    for k, entry in enumerate(routed, 1):
        route = entry.get("route")
        checked = (route or {}).get("checked") or {}
        if route is None or route.get("kind") != "route" or not checked.get("ok"):
            why = checked.get("why") or (route or {}).get("why") or "the router asked or named no route"
            unrouted.append({"item": entry["item"], "why": why, "reply": entry.get("reply") or ""})
            continue
        route = dict(route, title=request_title(request) if not several else title_of(entry["item"]))
        mine = delivery_tasks(route, k, flows, root, pack, prefix=several)
        inside = {t["key"] for t in mine}
        for t in mine:
            if last is not None and not [d for d in t["depends_on"] if d in inside]:
                t["depends_on"] = [last] + list(t["depends_on"])
            t["agent"] = agent_of(t["skill"], agent_skills) if agent_skills else None
        brief = mine[0]["key"] if "skill" in checked and checked["skill"] == BRIEF_SKILL else None
        deliveries.append({"item": entry["item"], "route": route["line"], "tasks": [t["key"] for t in mine],
                           "reroute_after": brief})
        tasks += mine
        routes.append(route)
        last = mine[-1]["key"]
    owner = owner_of(BACKLOG, root)
    full = dict(limits, max_subtasks=SUBTASKS_PER_PLAN,
                subtask_skills=[SUBTASK_SKILL] if owner and any(t["skill"] == owner for t in tasks) else [])
    flow = routes[0]["checked"].get("flow") if len(routes) == 1 else DELIVERIES_FLOW if routes else None
    shown = None if several or not routes else {k: v for k, v in routes[0].items() if k not in ("checked", "title")}
    built = None
    if tasks:
        built = build(request, tasks, shown, "router", full, past, flow=flow, deliveries=deliveries, unrouted=unrouted)
    return {"plan": built, "tasks": tasks, "deliveries": deliveries, "unrouted": unrouted, "limits": full}


def _read_task(script: str, backlog_path: str, ident: str):
    """The JSON task.py prints for one task, or None when the backlog has no such task (exit 1). Any other failure:
    ValueError."""
    try:
        done = isolated.run_script(script, ["--backlog", backlog_path, "--id", ident], cwd=os.path.dirname(backlog_path),
                                   timeout=BACKLOG_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f"task {ident} of the backlog could not be read: {type(e).__name__}") from None
    if done.returncode == 1:
        return None
    try:
        found = json.loads(done.stdout) if done.returncode == 0 else None
    except ValueError:
        found = None
    if not isinstance(found, dict):
        said = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
        raise ValueError(f"task {ident} of the backlog could not be read: {said}")
    return found


def backlog_tasks(backlog_path: str, root=None) -> list:
    """The product backlog's tasks as proposed sub-tasks, in file order: each id whose status is `todo`, as a
    sub-task of the role `subtask` (runtime/roles.json). The ids are the lines of the backlog's text that define a
    task (BACKLOG_ID); each is read by one run of <root>/skills/<subtask skill>/scripts/task.py, which prints its title,
    status and dependencies as JSON, through runtime/isolated.py, so that no code of the skill runs in this process.
    A dependency is kept when it is an id of the file whose task is not done. The Milestone field is not read: it is
    not a review milestone. An unreadable file or a script that fails: ValueError."""
    try:
        with open(backlog_path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"the backlog {backlog_path} cannot be read: {type(e).__name__}") from None
    script = isolated.skill_script(CHECKOUT if root is None else root, SUBTASK_SKILL, "task.py")
    ids = list(dict.fromkeys(BACKLOG_TASK_LINE.findall(text)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=BACKLOG_JOBS) as pool:
        read = list(pool.map(lambda ident: _read_task(script, backlog_path, ident), ids))
    found = {ident: t for ident, t in zip(ids, read) if t is not None}
    out = []
    for ident, t in found.items():
        if t.get("status") != "todo":
            continue
        needs = [d for d, status in (t.get("dependencies") or {}).items() if d in found and status != "done"]
        out.append({"key": ident.lower(), "skill": SUBTASK_SKILL, "title": f"{ident}: {t['title']}",
                    "text": f"implement task {ident} of {BACKLOG}.", "depends_on": [d.lower() for d in needs],
                    "milestone": False})
    return out


def subtasks(limits: dict, existing_count: int, proposed: list, known=()) -> dict:
    """{"create": [...], "ask": [...]}. A proposed sub-task is created when its skill is in limits["subtask_skills"],
    the sub-tasks already added plus those put in create stay below limits["max_subtasks"], and every dependency is a
    task the request has (known) or one put in create; every other one goes to ask, and so does each of its
    dependents. limits come from the approved plan: absent keys allow nothing."""
    allowed, cap = list(limits.get("subtask_skills") or []), limits.get("max_subtasks") or 0
    create, ask = [], []
    for t in proposed:
        made = {c["key"] for c in create}
        deps_ok = all(d in made or d in set(known) for d in t["depends_on"])
        if t["skill"] in allowed and deps_ok and existing_count + len(create) < cap:
            create.append(t)
        else:
            ask.append(t)
    return {"create": create, "ask": ask}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
