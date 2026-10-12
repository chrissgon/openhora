"""Tests of two sentences the plan gives the person (WP-9.14, items A-2 and A-3 of the maintainer's live test): the
refusal of a flow whose skills no enabled area agent has, which names the pack and what to add, and the title of a
request and of its plan, cut at a sentence or a word and never in the middle of one. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_wording.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_dispatcher import AGENTS, configure, tree  # noqa: F401  (the stand-in project of the dispatcher's tests)

plan = st.load("plan")
flow_files = st.load("flow_files")
ops = st.load("ops")
ops_core = st.load("ops_core")
ROOT = str(st.REPO)


def flow(name: str, *skills: str) -> dict:
    return {"flow": name, "title": name, "tasks": [
        {"key": f"k{n}", "skill": s, "title": s, "text": "do it.", "depends_on": [], "milestone": False}
        for n, s in enumerate(skills, 1)]}


# --- A-2: the scope error names what is missing --------------------------------------------------------------------


def test_a_flow_outside_the_scope_names_the_pack_the_skills_and_what_to_add():
    with pytest.raises(plan.PlanError) as refused:
        plan.from_flow(flow_files.load("market-positioning", ROOT), ROOT, ["core-orchestrator"])
    assert str(refused.value) == (
        "the flow market-positioning needs the pack business (skills biz-market-analysis, biz-icp-positioning), and no "
        'enabled area agent of runtime.json has it; add an area agent with "pack": "business" to area_agents and accept '
        "the configuration")


def test_the_pack_named_is_the_narrowest_one_and_never_a_catch_all_pack():
    with pytest.raises(plan.PlanError) as refused:
        plan.from_flow(flow("mixed", "brand-voice", "biz-market-analysis"), ROOT, [])
    said = str(refused.value)
    assert "the packs brand (skills brand-voice) and business (skills biz-market-analysis)" in said
    assert 'with "pack": "brand" and "pack": "business"' in said
    assert "default" not in said and "pack all" not in said


def test_a_skill_that_is_in_no_pack_is_said_to_be_in_none(monkeypatch):
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: [])
    with pytest.raises(plan.PlanError) as refused:
        plan.from_flow(flow("orphan", "biz-market-analysis"), ROOT, [])
    assert "biz-market-analysis is in no pack of packs/" in str(refused.value)
    assert "needs the pack" not in str(refused.value)


def test_a_flow_inside_the_scope_still_plans():
    tasks = plan.from_flow(flow_files.load("market-positioning", ROOT), ROOT, ["biz-icp-positioning", "biz-market-analysis"])
    assert [t["skill"] for t in tasks] == ["biz-market-analysis", "biz-icp-positioning"]


def test_the_operation_that_routes_a_flow_returns_the_sentence(tree):
    (tree["tree"] / "packs").mkdir()
    (tree["tree"] / "packs" / "code.txt").write_text("demo-code\n", encoding="utf-8")
    path = str(tree["project"])
    request = ops.request(path, "Invented request.", title="Invented")["request"]
    with pytest.raises(ops.OpsError) as refused:
        ops.route(path, request, "code-demo")
    assert refused.value.code == 1
    assert str(refused.value).startswith("no plan can be built: the flow code-demo needs the pack code (skills demo-code")
    assert 'add an area agent with "pack": "code" to area_agents and accept the configuration' in str(refused.value)


# --- A-3: the title ------------------------------------------------------------------------------------------------

LONG = ("Northwind is a family shop that sells ceramic cups and plates and wants its first digital solution to be a "
        "small online catalogue with a booking page for visits to the workshop")


def test_a_title_the_person_gave_is_the_title():
    assert plan.title_of("Some text. More text.", "  A name I chose ") == "A name I chose"


def test_without_a_title_the_first_sentence_is_the_title():
    assert plan.title_of("Plan the launch of the catalogue. Then the booking page.") == "Plan the launch of the catalogue."
    assert plan.title_of("Can we sell abroad? Say how.") == "Can we sell abroad?"
    assert plan.title_of("One idea per line\nand a second line that is not the title") == "One idea per line"
    assert plan.title_of("A single short request") == "A single short request"


def test_a_sentence_over_the_limit_is_cut_at_a_word_with_an_ellipsis():
    got = plan.title_of(LONG)
    assert len(got) <= 120 and got.endswith("…") and "  " not in got
    assert got == "Northwind is a family shop that sells ceramic cups and plates and wants its first digital solution to be a small online…"
    assert LONG.startswith(got[:-1].rstrip()) and LONG[len(got[:-1]):len(got[:-1]) + 1] == " "  # a whole word was left out, none was split
    word = "x" * 300
    assert plan.title_of(word) == "x" * 119 + "…"
    fits = ("word " * 24).strip()  # 119 characters, then one more word: the first sentence is over the limit
    assert plan.title_of(fits + " more words here") == fits + "…"
    whole = ("word " * 24).strip() + "!"  # 120 characters exactly: kept whole
    assert plan.title_of(whole) == whole and len(whole) == 120


def test_a_request_row_is_titled_by_the_same_function_whatever_rule_made_its_title(tree):
    path = str(tree["project"])
    made = ops.request(path, LONG)["request"]
    given = ops.request(path, LONG, title="Catalogue")["request"]
    ctx = ops_core.context(path)
    old = ctx["store"].request_add(ctx["conn"], title=LONG[:120].strip(), text=LONG)["request"]  # a row an earlier version stored
    rows = {r["id"]: r["title"] for r in ops.status(path)["requests"]}
    assert rows[made] == plan.title_of(LONG) and rows[old] == plan.title_of(LONG) and rows[given] == "Catalogue"
    assert not rows[made].endswith("soluti") and "…" in rows[made]


def test_the_plan_card_and_the_plan_as_text_carry_the_request_number_and_the_title(tree):
    path = str(tree["project"])
    request = ops.request(path, LONG)["request"]
    pending_id = ops.route(path, request, "single")["pending_id"]
    item = ops.pending(path, pending_id)
    first = item["body"].splitlines()[0]
    assert first == f"Plan for request {request}: {plan.title_of(LONG)}"
    assert "soluti…" not in first and "online…" in first
