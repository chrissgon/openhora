"""Tests of the milestones a skill's runtime manifest makes mandatory (mandatory_milestone): the plan, the stored
task and the review of the delivery. The stand-in tree and adapter (standin_tree.py), no container, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_milestones.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
plan = st.load("plan")
flow_files = st.load("flow_files")

PACK = ["demo-asks", "demo-writes"]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(ops.plan, "pack_skills", lambda cfg, root: list(PACK))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    return built


def mandatory(tree, skill, value=True):
    path = tree["tree"] / "skills" / skill / "evals" / "runtime-manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mandatory_milestone"] = value
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_manifest_makes_a_task_a_milestone_whatever_the_flow_file_says(tree):
    root = str(tree["tree"])
    mandatory(tree, "demo-asks")
    flow = flow_files.load("demo", root)
    assert flow["tasks"][0]["milestone"] is False  # the flow file does not make the market task a milestone
    tasks = plan.from_flow(flow, root, PACK)
    assert [(t["milestone"], t["mandatory_milestone"]) for t in tasks] == [(True, True), (True, False)]
    project = str(tree["project"])
    request = ops.request(project, "Find the first market.")["request"]
    opened = ops.route(project, request, flow="demo")
    body = ops.pending(project, opened["pending_id"])["body"]
    assert "| 1 | Market | demo-asks | - | yes, mandatory | no |" in body
    assert "| 2 | Profile | demo-writes | 1 | yes | no |" in body
    created = ops.approve(project, opened["pending_id"])["tasks"]
    ctx = ops_core.context(project)
    assert [ctx["store"].task_get(ctx["conn"], t["id"])["milestone"] for t in created] == [1, 1]
    named = ops.request(project, "Find the first market again.", flow="demo")["tasks"]
    assert [ctx["store"].task_get(ctx["conn"], t["id"])["milestone"] for t in named] == [1, 1]


def test_the_review_of_a_mandatory_milestone_says_so_and_carries_the_flag(tree):
    mandatory(tree, "demo-asks")
    project = str(tree["project"])
    ops.request(project, "Find the first market.", flow="demo")
    asked = ops.run_next(project)
    question = ops.pending(project, asked["pending_id"])
    assert question["kind"] == "question" and "mandatory_milestone" not in question["payload"]
    assert ops.MANDATORY_LINE not in question["body"]
    ops.answer(project, asked["pending_id"], "Clinics in Portugal.")
    delivered = ops.run_next(project)
    review = ops.pending(project, delivered["pending_id"])
    assert delivered["ending"] == "done" and review["kind"] == "review"
    assert review["payload"]["mandatory_milestone"] is True
    assert review["body"].endswith("\n\nThis delivery is a mandatory milestone: the next task accepts it only with your "
                                   "approval written in the document. Write it there, then release.")
    ops.release(project, delivered["pending_id"])
    profile = ops.pending(project, ops.run_next(project)["pending_id"])
    assert "mandatory_milestone" not in profile["payload"] and ops.MANDATORY_LINE not in profile["body"]


def test_a_task_without_a_manifest_is_never_mandatory(tree):
    root = str(tree["tree"])
    (tree["tree"] / "skills" / "demo-writes" / "evals" / "runtime-manifest.json").unlink()
    assert plan.mandatory("demo-writes", root) is False and plan.mandatory("demo-asks", root) is False
    tasks = plan.from_flow(flow_files.load("demo", root), root, PACK)
    assert [(t["milestone"], t["mandatory_milestone"]) for t in tasks] == [(False, False), (True, False)]
    alone = plan.from_skill("demo-writes", "Profile", root)
    assert (alone[0]["milestone"], alone[0]["mandatory_milestone"]) == (False, False)
