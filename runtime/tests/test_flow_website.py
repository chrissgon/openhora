"""Tests of the website flow file (flows/website.json): the chain from a PRD to a static site, its dependencies, the
agent that owns each task, the route to it and the rules of scripts/validate.py it must pass. Offline; the packs and
the skills are the repository's own.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_website.py
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

CHAIN = [
    ("prd", "product-prd", [], True),
    ("spec", "product-feature-spec", ["prd"], False),
    ("flows", "design-ux-flows", ["spec"], False),
    ("system", "design-system", ["flows"], False),
    ("brief", "design-brief", ["system"], True),
    ("execute", "design-execute", ["brief"], True),
    ("handoff", "design-handoff", ["execute"], False),
    ("implement", "eng-implement", ["handoff"], True),
]


def pack(name):
    return plan.resolve_pack(name, ROOT)


def agents():
    """The enabled area agents the runtime ships with: the design pack and the code pack, one agent each."""
    return {"design": pack("design"), "code": pack("code")}


def test_the_website_flow_file_loads_and_lists_the_chain_in_order():
    flow = flow_files.load("website", ROOT)
    assert flow["title"] == "Website" and "website" in flow_files.names(ROOT)
    assert [(t["key"], t["skill"], t["depends_on"], t["milestone"]) for t in flow["tasks"]] == CHAIN


def test_the_plan_of_the_flow_has_eight_tasks_in_the_scope_of_the_design_and_code_packs():
    flow = flow_files.load("website", ROOT)
    tasks = plan.from_flow(flow, ROOT, pack("design") + pack("code"))
    assert [(t["key"], t["skill"], t["depends_on"]) for t in tasks] == [(k, s, d) for k, s, d, _ in CHAIN]
    for key in ("prd", "brief", "execute", "implement"):
        assert next(t for t in tasks if t["key"] == key)["milestone"] is True
    with pytest.raises(plan.PlanError):  # with the design pack alone, the last task is outside the scope
        plan.from_flow(flow, ROOT, pack("design"))


def test_every_task_has_exactly_one_owning_agent_of_the_design_or_code_pack():
    owners = {}
    for key, skill, _, _ in CHAIN:
        owners[key] = plan.agent_of(skill, agents())
    assert {k: v for k, v in owners.items() if k != "implement"} == {k: "design" for k, *_ in CHAIN[:-1]}
    assert owners["implement"] == "code"


def test_the_router_accepts_the_website_flow_as_a_route():
    route = {"name": "flow-website", "shape": "flow", "state": "ready"}
    checked = router.check_route(route, flow_files.names(ROOT), pack("design") + pack("code"))
    assert checked == {"ok": True, "flow": "website"}


def test_the_flow_passes_the_dependency_rule_of_the_validator():
    flow = flow_files.load("website", ROOT)
    info = {}
    for task in flow["tasks"]:
        folder = st.REPO / "skills" / task["skill"]
        meta = skill_meta.declared(str(folder))
        info[task["skill"]] = {"inputs": meta["inputs"], "outputs": meta["outputs"],
                               "skill_md": (folder / "SKILL.md").read_text(encoding="utf-8")}
    assert flow_files.dependency_problems(flow, info) == []


def test_each_task_names_the_file_it_writes_and_what_was_done_before_it():
    flow = flow_files.load("website", ROOT)
    text = {t["key"]: t["text"] for t in flow["tasks"]}
    writes = {"prd": "docs/product/prd.md", "spec": "docs/product/specs/website.md", "flows": "docs/design/flows.md",
              "system": "the design system document", "brief": "docs/design/briefs/website.md",
              "execute": "docs/design/results/website.md", "handoff": "docs/design/handoff/",
              "implement": "site/"}
    for key, path in writes.items():
        assert path in text[key], key
    for task in flow["tasks"][1:]:
        assert re.search(r"\b(is|are) done\b", task["text"]), task["key"]
        for before in task["depends_on"]:  # it names the file the task before it wrote
            assert writes[before] in task["text"], (task["key"], before)
    assert "1280" in text["spec"] and "375" in text["spec"] and "1280" in text["execute"] and "375" in text["execute"]
    assert "ask" in text["prd"].lower()


def test_the_flow_names_no_project_no_person_and_no_tool():
    flow = (st.REPO / "flows" / "website.json").read_text(encoding="utf-8")
    assert re.search(r"openhora-brand|btj|telar|kyrios|chrissgon|/Users/|\.workbench-local", flow, re.I) is None
    data = json.loads(flow)
    for task in data["tasks"]:
        assert re.search(r"(?<![\w/-])" + re.escape(task["skill"]) + r"(?![\w-]|\.md)", task["text"]) is None  # no skill named
        assert re.search(r"\b(claude|anthropic|opus|sonnet|haiku|gpt|figma|cursor|codex)\b", task["text"], re.I) is None


def test_the_validator_passes_the_flow_files_of_the_repository():
    spec = importlib.util.spec_from_file_location("validate_under_website_test", st.REPO / "scripts" / "validate.py")
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
