"""Tests of the router step (runtime/router.py) and of the operations route, approve and reject (runtime/ops.py):
code reads only the route line and the question lines of the router's reply, a valid route becomes a plan the
person approves, and nothing the router's run left comes back. The replies read are the router's own, from the
classifier's corpus (runtime/tests/corpus/endings.jsonl); the runs are offline, on the stand-in tree.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_router_step.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
router = st.load("router")
CORPUS = st.REPO / "runtime" / "tests" / "corpus" / "endings.jsonl"
ROUTE_LINE = re.compile(r"^Route: ", re.M)


def corpus_replies() -> list:
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r["response"] for r in rows if r.get("skill") == router.ROUTER_SKILL]


REPLIES = corpus_replies()
WITH_QUESTIONS = [r for r in REPLIES if re.search(r"^(Next: )?Q[0-9]+: ", r, re.M)]
ROUTES = [r for r in REPLIES if r not in WITH_QUESTIONS
          and sum(1 for line in r.splitlines() if router.ROUTE_RE.match(line)) == 1]
NO_ROUTE = [r for r in REPLIES if r not in WITH_QUESTIONS and not ROUTE_LINE.search(r)]


def test_the_corpus_holds_replies_of_the_router():
    assert len(REPLIES) >= 80 and len(WITH_QUESTIONS) >= 30 and len(ROUTES) >= 40 and NO_ROUTE


def test_the_route_line_is_read_only_when_the_reply_holds_exactly_one():
    for reply in ROUTES:
        line = next(line for line in reply.splitlines() if router.ROUTE_RE.match(line))
        read = router.read_route(reply)
        assert read["kind"] == "route" and read["line"] == line, line
        assert line == f"Route: {read['name']} ({read['shape']}, {read['status']})"
    twice = ROUTES[0] + "\n" + next(line for line in ROUTES[0].splitlines() if line.startswith("Route: "))
    assert router.read_route(twice) == {"kind": "unclassified", "why": "2 route lines"}


def test_a_reply_with_questions_is_a_question_whatever_its_route_line_says():
    for reply in WITH_QUESTIONS:
        assert router.read_route(reply) == {"kind": "question"}
    assert any(not re.search(r"^Q[0-9]+: ", r, re.M) for r in WITH_QUESTIONS)  # the `Next: Q1: ...` form is there
    assert router.read_route(ROUTES[0] + "\nQ1: Which project? Recommended: this one, because it is open.") == {
        "kind": "question"}


def test_route_none_a_name_in_prose_and_two_route_lines_are_unclassified():
    for reply in NO_ROUTE:
        assert router.read_route(reply)["kind"] == "unclassified"
    for reply in ("Route: none (capability, pending)\nWhy: nothing fits.",
                  "Route: none\nWhy: nothing installed handles this.",
                  "The flow flow-brand would handle this, once it is built.",
                  "Route: `flow-new-product` (flow, pending — not built)",
                  "Route: flow-brand (flow, pending)\nRoute: brand-strategy (capability, ready)",
                  "  Route: flow-brand (flow, pending)", ""):
        assert router.read_route(reply)["kind"] == "unclassified", reply


def test_a_flow_route_is_valid_only_when_its_flow_file_exists():
    route = {"name": "flow-brand", "shape": "flow", "status": "pending"}
    assert router.check_route(route, ["brand", "market-positioning"], []) == {"ok": True, "flow": "brand"}
    refused = router.check_route(route, ["market-positioning"], ["flow-brand"])
    assert refused["ok"] is False and "flows/brand.json" in refused["why"]
    assert router.check_route({**route, "name": "brand"}, ["brand"], [])["ok"] is False


def test_a_skill_route_is_valid_only_when_the_skill_is_in_the_pack():
    route = {"name": "core-critique", "shape": "capability", "status": "ready"}
    assert router.check_route(route, [], ["core-critique"]) == {"ok": True, "skill": "core-critique"}
    assert router.check_route(route, ["core-critique"], ["biz-market-analysis"])["ok"] is False
    assert router.check_route({**route, "shape": "direct"}, [], ["core-critique"])["ok"] is False


def test_the_route_task_text_is_what_the_added_eval_case_measures():
    cases = json.loads((st.REPO / "skills" / router.ROUTER_SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))
    prompts = [c["prompt"] for c in cases["evals"]]
    assert any(p.endswith("For this task: " + router.ROUTE_TASK_TEXT) for p in prompts)


def test_router_and_plan_never_name_the_lab():
    for name in ("router.py", "plan.py"):
        text = (st.REPO / "runtime" / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(lab|ops|evals)\b", text, re.M), name
        assert "evals/" not in text and "sqlite" not in text and "store_module" not in text, name


# --- the operations, on the stand-in tree -------------------------------------------------------------------------

ROUTER_BRANCH = r'''
if [ "$skill" = core-orchestrator ]; then
  reply="$here/router-reply.md"
  if grep -q "the user's answer" "$prompt" && [ -f "$here/router-reply-2.md" ]; then reply="$here/router-reply-2.md"; fi
  cp "$reply" "$out/response.md"
  [ -f "$cwd/docs/workbench/state.md" ] && echo "- 2026-10-05: flow-demo is not installed here. (core-orchestrator)" >> "$cwd/docs/workbench/state.md"
  exit 0
fi
'''
FLOW_REPLY = ("Route: flow-demo (flow, pending)\nWhy: a market question -> business -> flow-demo\n"
              "Context: found none; missing none\nRequirements: none\nAutonomy: milestones\nAssumptions: none\n"
              "Next: the market task.\n")
SKILL_REPLY = FLOW_REPLY.replace("Route: flow-demo (flow, pending)", "Route: demo-writes (capability, ready)")
ASKING_REPLY = FLOW_REPLY.replace("Next: the market task.\n", "Next: Q1: Which project? Recommended: this one, because "
                                                                "it is open.\n")
PROSE_REPLY = "This sounds like a market question; the demo flow would fit once you confirm the project.\n"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    st.skill(built["tree"], router.ROUTER_SKILL, "docs/workbench/state.md", "")
    script = built["adapter"] / "run-prompt.sh"
    text = st.ADAPTER.replace("for name in demo-asks demo-writes;", "for name in demo-asks demo-writes core-orchestrator;")
    script.write_text(text.replace('case "$skill" in', ROUTER_BRANCH + 'case "$skill" in', 1), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(ops.plan, "pack_skills", lambda cfg, root: ["core-orchestrator", "demo-asks", "demo-writes"])
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    return built


def reply(tree, text: str, name: str = "router-reply.md") -> None:
    (tree["adapter"] / name).write_text(text, encoding="utf-8")


def requested(tree) -> dict:
    out = ops.request(str(tree["project"]), "Tell me which market to go after first.\nWe sell to clinics.")
    assert out == {"request": out["request"], "state": "requested", "next": "route"}
    return out


def test_the_router_step_is_a_run_of_the_unmodified_skill_and_returns_no_file(tree):
    path, state = str(tree["project"]), tree["project"] / "docs" / "workbench" / "state.md"
    before = state.read_text(encoding="utf-8")
    request = requested(tree)
    reply(tree, FLOW_REPLY)
    out = ops.route(path, request["request"])
    assert st.calls(tree["adapter"]) == ["core-orchestrator 1"]  # the one skill staged is the router
    prompt = open(os.path.join(out["run_dir"], "prompt.md"), encoding="utf-8").read()
    assert prompt.rstrip("\n").endswith("For this task: " + router.ROUTE_TASK_TEXT)
    assert prompt.startswith("Tell me which market to go after first.\nWe sell to clinics.\n")
    assert state.read_text(encoding="utf-8") == before  # the line the router added did not come back
    assert out["kept"] == [{"path": "docs/workbench/state.md", "class": "state", "reason": ops.ROUTE_KEPT}]
    assert out["routing"]["model"] == "m" and out["entered"]["kind"] == "general"
    run = ops_core.context(path)["store"].task_run_get(ops_core.context(path)["conn"], out["run_id"])
    assert (run["task_id"], run["skill"], run["web"], run["status"]) == (request["request"], router.ROUTER_SKILL, 0, "ok")
    assert ops.status(path)["requests"][0]["state"] == "requested" and ops.status(path)["requests"][0]["tasks"] == []


def test_a_valid_route_opens_a_plan_and_approving_it_creates_the_tasks(tree):
    path = str(tree["project"])
    request = requested(tree)
    reply(tree, FLOW_REPLY)
    out = ops.route(path, request["request"])
    assert (out["routed"], out["ending"], out["kind"]) == (True, "done", "plan")
    item = ops.pending(path, out["pending_id"])
    payload = item["payload"]
    assert item["kind"] == "plan" and payload["source"] == "router" and payload["flow"] == "demo"
    assert payload["route"]["line"] == "Route: flow-demo (flow, pending)"
    assert [(t["key"], t["skill"], t["milestone"]) for t in payload["tasks"]] == [("market", "demo-asks", False),
                                                                                  ("profile", "demo-writes", True)]
    # The gate file's limits, and (stage 6, WP-6.5) the sub-task limits the plan's approval covers: none here, since
    # no task of the plan owns the product backlog.
    assert payload["limits"] == {"one_task_at_a_time": True, "timeout_seconds": 60, "retries": 2,
                                 "max_subtasks": 20, "subtask_skills": []}
    listed = ops.pending(path)["pending"][0]
    assert listed["plan"] == {"tasks": [{"key": "market", "skill": "demo-asks"}, {"key": "profile", "skill": "demo-writes"}],
                              "plan_sha256": payload["plan_sha256"]}
    assert ops.status(path)["pending"][0]["plan"]["plan_sha256"] == payload["plan_sha256"]
    assert ops.run_next(path)["reason"] == "no task is ready"  # no task exists before the approval
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(path, out["pending_id"], "0" * 64)
    assert refused.value.code == 1 and payload["plan_sha256"] in str(refused.value)
    approved = ops.approve(path, out["pending_id"], payload["plan_sha256"])
    assert [(t["key"], t["state"]) for t in approved["tasks"]] == [("market", "ready"), ("profile", "planned")]
    assert ops.status(path)["requests"][0]["state"] == "planned"
    ran = ops.run_next(path)
    assert ran["skill"] == "demo-asks"
    prompt = open(os.path.join(ran["run_dir"], "prompt.md"), encoding="utf-8").read()
    assert "For this task: do the market analysis." in prompt and router.ROUTE_TASK_TEXT not in prompt
    with pytest.raises(ops.OpsError) as wrong:
        ops.approve(path, ran["pending_id"])
    assert wrong.value.code == 2
    # A route to one skill: a plan of one task, whose prompt is the plain request.
    second = ops.request(path, "Write the profile.", title="Profile")
    reply(tree, SKILL_REPLY)
    routed = ops.route(path, second["request"])
    tasks = ops.pending(path, routed["pending_id"])["payload"]["tasks"]
    assert [(t["key"], t["skill"], t["text"]) for t in tasks] == [("demo-writes", "demo-writes", "")]


def test_an_unrecognised_reply_reaches_the_person_whole_and_naming_the_flow_bypasses_the_router(tree):
    path = str(tree["project"])
    request = requested(tree)
    reply(tree, PROSE_REPLY)
    out = ops.route(path, request["request"])
    assert (out["routed"], out["ending"], out["kind"]) == (False, "unclassified", "question")
    item = ops.pending(path, out["pending_id"])
    # A-25: the body is one sentence; the reply whole is in the payload, with the two actions the page draws.
    assert item["title"] == "The route was not recognised"
    assert item["body"] == f"The planning agent did not name a flow or a skill for request {request['request']}"
    assert item["payload"]["raw"] == PROSE_REPLY and item["payload"]["actions"] == ["choose-flow", "cancel"]
    assert item["payload"]["why"] == "no route line"
    reply(tree, "Route: flow-missing (flow, pending)\n")
    other = ops.request(path, "Something else.")
    missing = ops.route(path, other["request"])
    assert missing["ending"] == "unclassified" and "flows/missing.json" in ops.pending(path, missing["pending_id"])["payload"]["why"]
    calls = len(st.calls(tree["adapter"]))
    named = ops.route(path, request["request"], "demo")
    assert named["routed"] is True and named["source"] == "named" and named["cancelled"] == [out["pending_id"]]
    assert len(st.calls(tree["adapter"])) == calls  # no run
    assert ops.pending(path, out["pending_id"])["status"] == "cancelled"
    assert ops.pending(path, named["pending_id"])["payload"]["source"] == "named"
    with pytest.raises(ops.OpsError) as no_flow:
        ops.route(path, other["request"], "no-such-flow")
    assert no_flow.value.code == 2
    rejected = ops.reject(path, named["pending_id"], "Not this flow.")
    assert rejected["request"] == request["request"]
    assert [r["state"] for r in ops.status(path)["requests"]][0] == "cancelled"


def test_a_question_of_the_router_is_answered_and_the_next_router_run_carries_the_answer(tree):
    path = str(tree["project"])
    state = tree["project"] / "docs" / "workbench" / "state.md"
    before = state.read_text(encoding="utf-8")
    request = requested(tree)
    reply(tree, ASKING_REPLY)
    reply(tree, FLOW_REPLY, "router-reply-2.md")
    asked = ops.route(path, request["request"])
    assert (asked["ending"], asked["kind"]) == ("question", "question")
    assert ops.pending(path, asked["pending_id"])["body"].startswith("Route: flow-demo")
    with pytest.raises(ops.OpsError):
        ops.route(path, request["request"])  # the question is open: answer it or name the flow
    answered = ops.answer(path, asked["pending_id"], "This one, the clinic project.")
    assert answered["task_state"] == "requested" and answered["state"]["written"] is False
    assert state.read_text(encoding="utf-8") == before
    again = ops.route(path, request["request"])
    assert again["kind"] == "plan"
    prompt = open(os.path.join(again["run_dir"], "prompt.md"), encoding="utf-8").read()
    assert "--- your reply 1 ---\nRoute: flow-demo" in prompt
    assert "--- the user's answer 1 ---\nThis one, the clinic project." in prompt
    assert st.calls(tree["adapter"]) == ["core-orchestrator 1", "core-orchestrator 2"]


def test_a_failed_router_run_leaves_the_request_requested(tree):
    path = str(tree["project"])
    request = requested(tree)
    reply(tree, FLOW_REPLY)
    st.fail(tree["adapter"], "adapter", 9)
    out = ops.route(path, request["request"])
    assert out["routed"] is False and out["failure"]["kind"] == "adapter" and out["pending_id"] is None
    assert ops.status(path)["requests"][0]["state"] == "requested" and ops.pending(path)["pending"] == []
    (tree["adapter"] / "fail-times").write_text("0\n")
    assert ops.route(path, request["request"])["kind"] == "plan"


def test_the_shell_routes_approves_and_rejects(tree, capsys):
    path = str(tree["project"])
    cli = st.load("cli")
    assert cli.main(["request", "--project", path, "--text", "Which market first?"]) == 0
    request = json.loads(capsys.readouterr().out)["request"]
    assert cli.main(["route", "--project", path, "--request", str(request), "--flow", "demo"]) == 0
    pending_id = json.loads(capsys.readouterr().out)["pending_id"]
    digest = ops.pending(path, pending_id)["payload"]["plan_sha256"]
    assert cli.main(["approve", "--project", path, "--id", str(pending_id), "--sha256", "f" * 64]) == 1
    capsys.readouterr()
    assert cli.main(["approve", "--project", path, "--id", str(pending_id), "--sha256", digest]) == 0
    assert json.loads(capsys.readouterr().out)["ready"]
    assert cli.main(["reject", "--project", path, "--id", str(pending_id)]) == 1  # resolved already
    assert cli.main(["route", "--project", path]) == 2
    capsys.readouterr()
    for verb in ("route", "approve", "reject"):
        assert cli.main([verb, "--help"]) == 0 and verb in capsys.readouterr().out
    for name in ("router", "plan"):
        script = str(st.REPO / "runtime" / f"{name}.py")
        assert subprocess.run([sys.executable, script, "--help"], capture_output=True, timeout=60).returncode == 0
        assert subprocess.run([sys.executable, script, "--no-such-flag"], capture_output=True, timeout=60).returncode == 2
