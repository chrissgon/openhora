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


WRITES = {"prd": "docs/product/prd.md", "spec": "docs/product/specs/website.md", "flows": "docs/design/flows.md",
          "system": "docs/design/design-system.md", "brief": "docs/design/briefs/website.md",
          "execute": "docs/design/results/website.md", "handoff": "docs/design/handoff/website.md",
          "implement": "site/"}
# A path of the artifact contract a text may name in words: the file name holds the skill's name, which no text may
# carry (test_skill_text_binding), so the text says "the design system document".
SAID = {"docs/design/design-system.md": "the design system document"}


def named(text, path):
    return path in text or SAID.get(path, "\0") in text


def test_each_task_names_the_exact_file_it_writes():
    flow = flow_files.load("website", ROOT)
    for task in flow["tasks"]:
        assert named(task["text"], WRITES[task["key"]]) or task["key"] == "system", task["key"]
    text = {t["key"]: t["text"] for t in flow["tasks"]}
    assert "docs/design/design-system.md" not in text["system"] and "in docs/design/" in text["system"]
    assert "docs/design/handoff/website/export/" in text["handoff"] and "docs/design/handoff/website/export/" in text["implement"]
    assert "docs/product/specs/website.md" in text["implement"]


def test_each_task_names_every_required_input_that_an_earlier_task_writes():
    flow = flow_files.load("website", ROOT)
    outputs = {}  # artifact (placeholders as wildcards) -> the key of the task that writes it
    checked = []
    for task in flow["tasks"]:
        folder = st.REPO / "skills" / task["skill"]
        meta = skill_meta.declared(str(folder))
        required = flow_files.required_inputs((folder / "SKILL.md").read_text(encoding="utf-8"), meta["inputs"])
        for path in required:
            earlier = [k for art, k in outputs.items() if flow_files._artifact(art) == flow_files._artifact(path)]
            for _ in earlier:
                concrete = re.sub(r"<[^<>/]+>", "website", path)
                assert named(task["text"], concrete), (task["key"], concrete)
                checked.append((task["key"], concrete))
        for path in meta["outputs"]:
            outputs[path] = task["key"]
    # the check above is not empty: the hand-off alone reads five files that earlier tasks write
    assert {c for k, c in checked if k == "handoff"} >= {"docs/design/results/website.md", "docs/design/briefs/website.md",
                                                       "docs/design/flows.md", "docs/design/design-system.md"}


def test_the_prd_says_the_website_is_the_product_and_the_person_is_asked():
    text = {t["key"]: t["text"] for t in flow_files.load("website", ROOT)["tasks"]}
    assert "The website is the product this PRD describes" in text["prd"]
    assert re.search(r"Ask the person what only they can answer", text["prd"])
    assert "Ask the person which direction to keep" in text["execute"]
    assert re.search(r"Round 1: one run for each direction.*Round 2: the chosen direction complete", text["execute"])
    assert "SCREEN" in text["brief"] and "1280" in text["spec"] and "375" in text["spec"]
    assert "a test you write first" in text["implement"] and "quote the failing line" in text["implement"]
    assert "no horizontal scroll appears at 1280 and 375" in text["implement"]


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
