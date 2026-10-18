"""A question answered from the sources is not mirrored to the task board (package AQ-1; runtime/board.py `asked`): its request has no task
and a run of the answer skill, its title and text are the person's question, and the board's host is not where a question goes. A request
a plan made is mirrored as before. The local board provider on a temporary folder, the stand-in tree; no network, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ask_board.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from sources_fixture import standin_convert
from test_board_mirror import accept, configure, items, planned, project_of, tree as board_tree  # noqa: F401  (the board world of test_board_mirror.py)

ops = st.load("ops")
ops_core = st.load("ops_core")
board = st.load("board")
plan = st.load("plan")
roles = st.load("roles")
sources = st.load("sources")

ANSWER = "demo-answers"


@pytest.fixture
def tree(board_tree, monkeypatch):
    st.answer_skill(board_tree["tree"])
    monkeypatch.setattr(roles, "answer", lambda root=None, file=None: ANSWER)
    monkeypatch.setattr(ops_core, "_own_key", lambda variable: (None, None))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: [ANSWER, "demo-asks", "demo-writes"] if pack == "assist" else [])
    monkeypatch.setattr(ops.plan, "pack_skills", lambda cfg, root: [ANSWER, "demo-asks", "demo-writes"])
    configure(board_tree, {"provider": "local", "dir": str(board_tree["board"])},
              area_agents={"assistant": {"pack": "assist", "max_runs_per_day": 10}})
    accept(project_of(board_tree))
    ctx = ops_core.context(project_of(board_tree))
    path = board_tree["tmp_source"] = board_tree["data"].parent / "lease.txt"
    path.write_text("# Lease\n\nThe term of the contract is 12 months.\n", encoding="utf-8")
    sources.import_version(ctx, sources.register(ctx, "lease-contract", "file", "lease.txt"), str(path), convert=standin_convert)
    return board_tree


def test_a_question_is_never_pushed_to_the_board_and_the_requests_of_plans_still_are(tree):
    ids = planned(tree)
    out = ops.ask(project_of(tree), "what is the term of the contract?", channel="terminal")
    assert out["ran"] is True and out["answer"] == "found"
    ctx = ops_core.context(project_of(tree))
    assert board.asked(ctx) == [out["request_id"]]
    pushed = ops.sync(project_of(tree))["board"]["pushed"]
    assert sorted(pushed) == sorted(ids.values()) and out["request_id"] not in pushed and len(items(tree)) == 3
    assert ctx["store"].task_get(ctx["conn"], out["request_id"]).get("remote_id") is None
    again = ops.sync(project_of(tree))["board"]
    assert again["pushed"] == [] and again["failed"] == []                            # and the next sync writes nothing either


def test_a_question_is_marked_by_what_the_store_holds_and_not_by_the_answer_skill_the_configuration_names_now(tree, monkeypatch):
    out = ops.ask(project_of(tree), "what is the term of the contract?", channel="terminal")
    planned(tree)
    ctx = ops_core.context(project_of(tree))
    for named in (None, "renamed-answer-skill"):
        monkeypatch.setattr(roles, "answer", lambda root=None, file=None, named=named: named)
        assert board.asked(ctx) == [out["request_id"]]                 # a plan's request (router runs, tasks) is never one
    assert [r for r in ops.sync(project_of(tree))["board"]["pushed"] if r == out["request_id"]] == []


def test_a_request_is_a_question_for_the_board_when_it_has_a_run_of_a_skill_other_than_the_routers_and_the_router_is_named_by_roles(tree):
    """board.asked relies on one fact: the only runs a request has are the router's and an answer run. This pins the naming it reads."""
    router = st.load("router")
    assert router.ROUTER_SKILL == roles.load()["router"]
    ctx = ops_core.context(project_of(tree))
    store, conn = ctx["store"], ctx["conn"]
    routed = ops.request(project_of(tree), "A request the router works on")["request"]
    started = store.route_run_start(conn, routed, skill=router.ROUTER_SKILL, model="m", adapter="h")
    assert board.asked(ctx) == []                                                  # a router run, running
    store.route_run_finish(conn, started["run_id"], status="failed", failure="timeout")
    assert board.asked(ctx) == []                                                  # a router run, ended
    other = ops.request(project_of(tree), "A request with an answer run")["request"]
    store.route_run_start(conn, other, skill="some-answer-skill", model="m", adapter="h")
    assert board.asked(ctx) == [other]                                             # the name of the answer skill does not matter
    planned_ids = planned(tree)
    assert board.asked(ctx) == [other] and planned_ids["request"] not in board.asked(ctx)
