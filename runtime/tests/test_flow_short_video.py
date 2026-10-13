"""Tests of the short-video flow file (flows/short-video.json): one task, the script and the caption of a short video
post, owned by the content area agent and a milestone; the route to it; the rules of scripts/validate.py it must
pass; and its stated benefit, that choosing it in the request form plans the task at once with no run of the router.
Offline; the packs and the skills are the repository's own, except in the last test, which runs on the stand-in tree.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_short_video.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil

import pytest

import standin_tree as st

plan = st.load("plan")
flow_files = st.load("flow_files")
router = st.load("router")
skill_meta = st.load("skill_meta")
manifest = st.load("manifest")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ROOT = str(st.REPO)
SKILL = "mkt-social-copy"


def pack(name):
    return plan.resolve_pack(name, ROOT)


def test_the_short_video_flow_file_loads_with_one_milestone_task_of_the_copy_skill():
    flow = flow_files.load("short-video", ROOT)
    assert "short-video" in flow_files.names(ROOT) and flow["title"] == "Script and caption of a short video post"
    assert [(t["key"], t["skill"], t["depends_on"], t["milestone"]) for t in flow["tasks"]] == [("script", SKILL, [], True)]


def test_the_plan_of_the_flow_is_inside_the_content_pack_and_outside_the_marketing_pack():
    flow = flow_files.load("short-video", ROOT)
    tasks = plan.from_flow(flow, ROOT, pack("content"))
    assert [(t["key"], t["skill"], t["milestone"]) for t in tasks] == [("script", SKILL, True)]
    with pytest.raises(plan.PlanError):  # with the marketing pack alone, the task is outside the scope
        plan.from_flow(flow, ROOT, pack("marketing"))


def test_the_content_agent_owns_the_task_and_the_marketing_agent_does_not():
    agents = {"content": pack("content"), "marketing": pack("marketing"), "design": pack("design"), "code": pack("code")}
    assert plan.agent_of(SKILL, agents) == "content"
    assert SKILL in manifest.skills_in_use(ROOT)


def test_the_router_accepts_the_short_video_flow_as_a_route():
    route = {"name": "flow-short-video", "shape": "flow", "state": "ready"}
    checked = router.check_route(route, flow_files.names(ROOT), pack("content"))
    assert checked == {"ok": True, "flow": "short-video"}


def test_the_flow_passes_the_dependency_rule_of_the_validator():
    flow = flow_files.load("short-video", ROOT)
    info = {}
    for task in flow["tasks"]:
        folder = st.REPO / "skills" / task["skill"]
        meta = skill_meta.declared(str(folder))
        info[task["skill"]] = {"inputs": meta["inputs"], "outputs": meta["outputs"],
                               "skill_md": (folder / "SKILL.md").read_text(encoding="utf-8")}
    assert flow_files.dependency_problems(flow, info) == []


def test_the_task_names_the_folder_and_the_calendar_it_reads_and_asks_for_what_it_lacks():
    [task] = flow_files.load("short-video", ROOT)["tasks"]
    text = task["text"]
    assert "docs/marketing/content/" in text and "docs/marketing/calendar.md" in text
    assert "Text only: nothing is recorded, edited or published" in text
    assert re.search(r"ask the person for the material and the platform", text) and "never invent either" in text


def test_the_flow_names_no_project_no_person_and_no_tool():
    flow = (st.REPO / "flows" / "short-video.json").read_text(encoding="utf-8")
    assert re.search(r"/Users/|/home/(?!demo\b)|\.workbench-local", flow) is None
    terms_file = st.REPO / ".private-terms"
    if terms_file.is_file():  # git-ignored; absent on CI and on other machines, as for scripts/validate.py
        for raw in terms_file.read_text(encoding="utf-8").splitlines():
            term = raw.strip()
            if not term or term.startswith(("#", "!")):
                continue
            pattern = re.compile(term[3:] if term.startswith("re:") else re.escape(term), re.I)
            assert pattern.search(flow) is None, "a private term appears in the flow file"
    for task in json.loads(flow)["tasks"]:
        assert re.search(r"(?<![\w/-])" + re.escape(task["skill"]) + r"(?![\w-]|\.md)", task["text"]) is None  # no skill named
        assert re.search(r"\b(claude|anthropic|opus|sonnet|haiku|gpt|figma|cursor|codex)\b", task["text"], re.I) is None


def test_the_validator_passes_the_flow_files_of_the_repository():
    spec = importlib.util.spec_from_file_location("validate_under_short_video_test", st.REPO / "scripts" / "validate.py")
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


def test_choosing_the_flow_in_the_form_plans_the_task_at_once_with_no_run_of_the_router(tmp_path, monkeypatch):
    """The stated benefit: a request made with the flow named (the form's "Route it" select) is planned from the flow
    file, with no model run at all, so a script costs the one run of the copy skill. The tree is the stand-in one, with
    the repository's own flow file and a stand-in copy skill; the adapter's call log stays empty."""
    built = st.build(tmp_path, monkeypatch, lab)
    root = built["tree"]
    st.skill(root, SKILL, "docs/workbench/state.md", "docs/marketing/content/<post>.md", area="marketing")
    shutil.copyfile(st.REPO / "flows" / "short-video.json", root / "flows" / "short-video.json")
    monkeypatch.setattr(ops_core, "ROOT", str(root))
    packs = {"content": [SKILL], "marketing": []}
    monkeypatch.setattr(plan, "resolve_pack", lambda name, _root: list(packs[name]))
    config = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(config.read_text(encoding="utf-8"))
    raw["area_agents"] = {"content": {"pack": "content", "mode": "supervised", "max_runs_per_day": 6, "max_usd_per_day": 2.0}}
    config.write_text(json.dumps(raw), encoding="utf-8")
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    request = ops.request(project, "A Reels script for the new release.", title="Reels script")["request"]
    opened = ops.route(project, request, flow="short-video")
    assert opened["routed"] is True and opened["source"] == "named" and opened["flow"] == "short-video"
    item = ops.pending(project, opened["pending_id"])
    assert [(t["key"], t["skill"], t["agent"], t["milestone"]) for t in item["payload"]["tasks"]] == [
        ("script", SKILL, "content", True)]
    assert st.calls(built["adapter"]) == [], "no run of any skill, the router's included"
