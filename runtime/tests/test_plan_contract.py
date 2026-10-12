"""Tests of the order of the deliveries of one request (PAR-3): a delivery starts after an earlier one only when it
reads what that one writes (the artifact contract), and the plan text says how many tasks run at a time.
Offline; the skills are the repository's own.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_contract.py
"""
from __future__ import annotations

import standin_tree as st

plan = st.load("plan")
ROOT = str(st.REPO)
REQUEST = {"id": 7, "title": "Two jobs", "text": "Do two jobs."}
LIMITS = {"one_task_at_a_time": True, "timeout_seconds": 1800, "retries": 2}


def routed(*skills: str) -> list:
    return [{"item": f"job {n}", "reply": "", "route": {"kind": "route", "line": f"Route: {s} (capability, ready)",
                                                       "checked": {"ok": True, "skill": s}}}
            for n, s in enumerate(skills, 1)]


def combined(skills: tuple, limits=LIMITS) -> dict:
    return plan.combine(REQUEST, routed(*skills), {}, {}, ROOT, pack=None, limits=limits, past=[])


def test_unrelated_deliveries_are_not_chained():
    # biz-market-analysis writes docs/business/market.md; brand-voice neither reads it nor any other output of it.
    out = combined(("biz-market-analysis", "brand-voice"))
    assert [(t["key"], t["depends_on"]) for t in out["tasks"]] == [
        ("d1-biz-market-analysis", []), ("d2-brand-voice", [])]


def test_a_delivery_that_reads_an_earlier_ones_output_depends_on_its_writer():
    """biz-market-analysis writes docs/business/market.md and biz-icp-positioning lists it among its inputs."""
    out = combined(("biz-market-analysis", "biz-icp-positioning"))
    assert [(t["key"], t["depends_on"]) for t in out["tasks"]] == [
        ("d1-biz-market-analysis", []), ("d2-biz-icp-positioning", ["d1-biz-market-analysis"])]
    # The other way round, the reader comes first: nothing waits for a later delivery.
    back = combined(("biz-icp-positioning", "biz-market-analysis"))
    assert [t["depends_on"] for t in back["tasks"]] == [[], []]


def test_owners_of_and_contract_deps_share_one_matching():
    assert plan.same_artifact("docs/business/market.md", "docs/business/market.md")
    assert plan.same_artifact("docs/research/<topic>.md", "docs/research/<name>.md")
    assert plan.same_artifact("docs/business/", "docs/business/market.md")
    assert not plan.same_artifact("docs/business/market.md", "docs/business/icp.md")
    assert not plan.same_artifact("docs/business/market.md", "docs/business/")
    facts = {"a": {"outputs": ["docs/business/market.md", "docs/x/<topic>.md"]}, "b": {"outputs": ["docs/other.md"]}}
    for path in ("docs/business/market.md", "docs/business/", "docs/x/<name>.md", "docs/other.md", "docs/none.md"):
        assert plan.owners_of(facts, path) == sorted(
            n for n, f in facts.items() if any(plan.same_artifact(path, o) for o in f["outputs"]))
    # A dependency is added exactly when owners_of would name the earlier skill as the owner of the input.
    deliveries = [[{"key": "u", "skill": "a", "depends_on": []}], [{"key": "t", "skill": "b", "depends_on": []}]]
    plan._contract_deps(deliveries, {"a": {"inputs": [], "outputs": ["docs/business/"]},
                                     "b": {"inputs": ["docs/business/market.md"], "outputs": []}})
    assert deliveries[1][0]["depends_on"] == []      # a folder output is not a file input: same matching as owners_of
    deliveries[1][0]["depends_on"] = []
    plan._contract_deps(deliveries, {"a": {"inputs": [], "outputs": ["docs/business/market.md"]},
                                     "b": {"inputs": ["docs/business/market.md", "docs/business/"], "outputs": []}})
    assert deliveries[1][0]["depends_on"] == ["u"]


def test_the_plan_text_names_the_ceiling_when_the_limits_carry_it():
    plain = combined(("biz-market-analysis", "brand-voice"))["plan"]["body"]
    assert "One task at a time" not in plain and "Up to " not in plain
    assert "Deliveries (a delivery starts after an earlier one only when it reads what that one writes):" in plain
    assert "each starts after the one before it" not in plain
    capped = combined(("biz-market-analysis", "brand-voice"), dict(LIMITS, max_running=3))["plan"]["body"]
    assert "Up to 3 tasks at a time; each run at most 1800 s, retried at most 2 times. At least 2 runs." in capped
