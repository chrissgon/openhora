"""The checks every standard flow file shares (flows/<name>.json of the engineering flows: build-feature, improve-code,
new-project, fix-bug), so that each flow's test file states only its own specification. Not a test file. Offline: the
packs, the skills and the validator are the repository's own, and no model is called.

A specification is a list of rows (key, skill, depends_on, milestone). The checks:

  loads_in_order        the file loads and lists exactly the specification, in order
  plan_equals_spec      choosing the flow builds a plan whose tasks, skills, order, depends_on and milestones equal it
  scope_is_checked      a scope that lacks a skill of the flow refuses the plan (plan.PlanError), as the runtime does
  one_owner_each        every task has exactly one owning area agent of the shipped ones (runtime/roles.json), the expected one
  router_accepts        the router accepts `flow-<name>` as a route
  passes_validator      the dependency rule and the validator's three flow checks pass
  names_what_it_writes  each task's text names the file its skill writes, and every required input an earlier task writes
  names_nothing         the file names no project, no person, no skill and no AI tool
"""
from __future__ import annotations

import importlib.util
import json
import re

import pytest

import standin_tree as st

plan = st.load("plan")
flow_files = st.load("flow_files")
router = st.load("router")
skill_meta = st.load("skill_meta")
ROOT = str(st.REPO)

def pack(name):
    return plan.resolve_pack(name, ROOT)


# The enabled area agents the runtime ships with (runtime/roles.json, packs_in_use) and the packs of each.
AGENT_PACKS = ("planning", "design", "code", "content")


def agents():
    return {name: pack(name) for name in AGENT_PACKS}


def scope():
    """The skills of the shipped agents together: the scope a project that enables them all plans in."""
    return sorted({skill for skills in agents().values() for skill in skills})


def loads_in_order(name, title, spec):
    flow = flow_files.load(name, ROOT)
    assert flow["title"] == title and name in flow_files.names(ROOT)
    assert [(t["key"], t["skill"], t["depends_on"], t["milestone"]) for t in flow["tasks"]] == spec
    assert all(set(t) == {"key", "skill", "title", "text", "depends_on", "milestone"} for t in flow["tasks"])


def plan_equals_spec(name, spec):
    flow = flow_files.load(name, ROOT)
    tasks = plan.from_flow(flow, ROOT, scope())
    assert [(t["key"], t["skill"], t["depends_on"]) for t in tasks] == [(k, s, d) for k, s, d, _ in spec]
    for task, (key, _, _, milestone) in zip(tasks, spec):
        assert task["key"] == key
        if milestone:   # a mandatory milestone of a skill's manifest may add one, never remove one
            assert task["milestone"] is True
    assert [t["text"] for t in tasks] == [t["text"] for t in flow["tasks"]]


def scope_is_checked(name):
    flow = flow_files.load(name, ROOT)
    with pytest.raises(plan.PlanError):   # a scope with none of the flow's skills
        plan.from_flow(flow, ROOT, ["demo-skill"])
    missing = [t["skill"] for t in flow["tasks"]][0]
    with pytest.raises(plan.PlanError):
        plan.from_flow(flow, ROOT, [s for s in scope() if s != missing])


def one_owner_each(name, owners):
    """Every task of the flow has exactly one owning area agent, and it is the one `owners` says (skill -> agent)."""
    flow = flow_files.load(name, ROOT)
    found = {t["skill"]: plan.agent_of(t["skill"], agents()) for t in flow["tasks"]}
    assert found == owners


def router_accepts(name):
    route = {"name": f"flow-{name}", "shape": "flow", "state": "ready"}
    assert router.check_route(route, flow_files.names(ROOT), scope()) == {"ok": True, "flow": name}


def skill_info(flow):
    info = {}
    for task in flow["tasks"]:
        folder = st.REPO / "skills" / task["skill"]
        meta = skill_meta.declared(str(folder))
        info[task["skill"]] = {"inputs": meta["inputs"], "outputs": meta["outputs"],
                               "skill_md": (folder / "SKILL.md").read_text(encoding="utf-8")}
    return info


def passes_validator(name):
    flow = flow_files.load(name, ROOT)
    assert flow_files.dependency_problems(flow, skill_info(flow)) == []
    spec = importlib.util.spec_from_file_location(f"validate_under_{name.replace('-', '_')}_test", st.REPO / "scripts" / "validate.py")
    validate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate)
    report = validate.Report()
    skills = []
    for folder in sorted((st.REPO / "skills").iterdir()):
        if (folder / "SKILL.md").is_file():
            meta = skill_meta.declared(str(folder))
            skills.append({"name": folder.name, "where": f"skills/{folder.name}", "inputs": meta["inputs"],
                           "outputs": meta["outputs"], "updates": meta["updates"]})
    validate.check_flows(skills, report, str(st.REPO))
    assert report.errors == []


def named(text, path):
    """A text names a path when it holds it, or, for a file whose name the request decides, the folder it is in."""
    return path in text or (re.search(r"<[^<>/]+>", path) is not None and path.rsplit("/", 1)[0] + "/" in text)


def names_what_it_writes(name, writes):
    """`writes` maps a task key to the path its skill writes that its text must name."""
    flow = flow_files.load(name, ROOT)
    for task in flow["tasks"]:
        if task["key"] in writes:
            assert named(task["text"], writes[task["key"]]), (task["key"], writes[task["key"]])
    outputs = {}   # artifact (placeholders as wildcards) -> the key of the task that writes it
    checked = []
    for task in flow["tasks"]:
        folder = st.REPO / "skills" / task["skill"]
        meta = skill_meta.declared(str(folder))
        required = flow_files.required_inputs((folder / "SKILL.md").read_text(encoding="utf-8"), meta["inputs"])
        for path in required:
            if any(flow_files._artifact(art) == flow_files._artifact(path) for art in outputs):
                assert named(task["text"], path), (task["key"], path)
                checked.append((task["key"], path))
        for path in meta["outputs"]:
            outputs[path] = task["key"]
    return checked


def names_nothing(name):
    raw = (st.REPO / "flows" / f"{name}.json").read_text(encoding="utf-8")
    assert re.search(r"/Users/|/home/|\.workbench-local", raw) is None
    terms_file = st.REPO / ".private-terms"
    if terms_file.is_file():   # git-ignored; absent on CI and on other machines, as for scripts/validate.py
        for line in terms_file.read_text(encoding="utf-8").splitlines():
            term = line.strip()
            if not term or term.startswith(("#", "!")):
                continue
            pattern = re.compile(term[3:] if term.startswith("re:") else re.escape(term), re.I)
            assert pattern.search(raw) is None, "a private term appears in the flow file"
    skills = sorted(p.name for p in (st.REPO / "skills").iterdir() if (p / "SKILL.md").is_file())
    for task in json.loads(raw)["tasks"]:
        for skill in skills:
            assert re.search(r"(?<![\w/-])" + re.escape(skill) + r"(?![\w-]|\.md)", task["text"]) is None, (task["key"], skill)
        assert re.search(r"\b(claude|anthropic|opus|sonnet|haiku|gpt|figma|cursor|codex)\b", task["text"], re.I) is None
