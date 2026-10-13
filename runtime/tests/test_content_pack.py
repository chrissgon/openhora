"""Tests that the content pack (packs/content.txt) and the marketing pack (packs/marketing.txt) do not overlap, and that
no skill is in two packs of the area agents enabled together: plan.agent_of raises when a skill is in the packs of two
enabled agents (the planning agent apart), so the packs must be disjoint wherever their agents are enabled. Offline: the
repository's own packs and skills, the synthetic configuration of every area agent a project can enable at once, and
the area agents of the interface's demo (scripts/demo_fixtures.py).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_content_pack.py
"""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest

import standin_tree as st

plan = st.load("plan")
manifest = st.load("manifest")
roles = st.load("roles")
ROOT = str(st.REPO)
CONTENT = ["mkt-content-plan", "mkt-messaging", "mkt-social-copy"]
MARKETING = ["mkt-engage", "mkt-vote-round"]
# The area agents a project can enable together: one for each pack of the runtime's packs, the marketing and the
# content agents among them.
SYNTHETIC = {name: {"pack": name, "mode": "supervised", "max_runs_per_day": 6, "max_usd_per_day": 2.0}
             for name in ("planning", "business", "brand", "design", "code", "marketing", "content")}


def owners(agent_skills: dict) -> dict:
    """{skill: [the agents, the planning agent apart, whose pack holds it]}"""
    out = {}
    for agent, skills in agent_skills.items():
        for skill in skills:
            out.setdefault(skill, []).append(agent)
    return out


def test_the_content_pack_and_the_marketing_pack_hold_exactly_the_skills_named_for_them():
    assert plan.resolve_pack("content", ROOT) == CONTENT
    assert plan.resolve_pack("marketing", ROOT) == MARKETING
    assert "mkt-publish" not in CONTENT + MARKETING + [s for p in roles.load()["packs_in_use"]
                                                       for s in plan.resolve_pack(p, ROOT)]


def test_the_content_pack_is_in_use_and_every_skill_of_it_has_a_whole_manifest():
    assert "content" in manifest.PACKS_IN_USE and "marketing" not in manifest.PACKS_IN_USE
    assert set(CONTENT) <= set(manifest.skills_in_use(ROOT))
    for skill in CONTENT:
        assert manifest.load(ROOT, skill)["skill"] == skill


def test_no_skill_is_in_two_packs_of_the_agents_a_project_enables_together():
    held = plan.agent_skills({"area_agents": SYNTHETIC}, ROOT)
    assert sorted(held) == sorted(SYNTHETIC)
    by_skill = {skill: agents for skill, agents in owners(held).items()}
    twice = {skill: agents for skill, agents in by_skill.items() if len([a for a in agents if a != plan.PLANNING]) > 1}
    assert twice == {}, twice
    for skill in CONTENT:
        assert plan.agent_of(skill, held) == "content"
    for skill in MARKETING:
        assert plan.agent_of(skill, held) == "marketing"


def test_an_agent_whose_pack_held_every_mkt_skill_beside_the_content_agent_is_refused():
    """The guard the split exists for: the pack as it was (`mkt-*`) and the content pack together name one skill twice."""
    old = {"marketing": sorted(CONTENT + MARKETING + ["mkt-publish"]), "content": CONTENT}
    with pytest.raises(ValueError) as e:
        plan.agent_of("mkt-social-copy", old)
    assert "mkt-social-copy" in str(e.value) and "content" in str(e.value) and "marketing" in str(e.value)


def demo_module():
    spec = importlib.util.spec_from_file_location("demo_fixtures_under_content_pack_test", st.REPO / "scripts" / "demo_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_skill_is_in_two_packs_of_the_demos_enabled_agents():
    demo = demo_module()
    held = {name: sorted(demo.PACKS.get(entry["pack"], [])) for name, entry in demo.AGENTS.items()}
    twice = {s: a for s, a in owners(held).items() if len([x for x in a if x != plan.PLANNING]) > 1}
    assert twice == {}, twice
    assert demo.AGENTS["content"]["pack"] == "content" and "marketing" not in demo.AGENTS
    fixture = json.loads((st.REPO / "interface" / "demo" / "fixtures" / "agents.json").read_text(encoding="utf-8"))
    packs = [(a["name"], a["pack"]) for a in fixture["agents"]]
    assert ("content", "content") in packs and all(n == p for n, p in packs if n in ("content", "planning"))
    assert len({pack for _, pack in packs}) == len(packs), "one agent for each pack"
