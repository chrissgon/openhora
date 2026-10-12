"""Tests of scripts/select_skills.py: the pack format (globs, area: patterns, ! exclusions, exact names), the
--areas and --skills filters, and a warning for what selects nothing (the report's test gaps for packs).

Run: uv run --with pytest pytest scripts/tests/test_select_skills.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "select_skills.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("select_skills_under_test", SCRIPT)
select = importlib.util.module_from_spec(spec)
spec.loader.exec_module(select)

CATALOG = {"eng-unit-tests": "engineering", "eng-refactor": "engineering", "mkt-publish": "marketing",
           "asst-inbox": "assistant", "biz-market-analysis": "business"}


@pytest.fixture()
def packs(tmp_path, monkeypatch):
    monkeypatch.setattr(select, "all_skills", lambda: dict(CATALOG))
    monkeypatch.setattr(select, "PACKS", str(tmp_path))

    def write(name, text):
        (tmp_path / f"{name}.txt").write_text(text, encoding="utf-8")
    return write


def test_globs_area_patterns_exclusions_and_exact_names(packs):
    packs("mix", "# a comment\narea:engineering\nmkt-*\nbiz-market-analysis\n!eng-refactor\n")
    assert select.resolve("mix") == ["biz-market-analysis", "eng-unit-tests", "mkt-publish"]
    packs("default", "*\n!asst-*\n")
    assert "asst-inbox" not in select.resolve("default") and len(select.resolve("default")) == 4


def test_filters_intersect_with_the_pack(packs):
    packs("all", "*\n")
    assert select.resolve("all", areas={"engineering"}) == ["eng-refactor", "eng-unit-tests"]
    assert select.resolve("all", skills={"mkt-publish", "eng-refactor"}) == ["eng-refactor", "mkt-publish"]
    assert select.resolve("all", areas={"marketing"}, skills={"eng-refactor"}) == []
    assert select.resolve(None, areas={"business"}) == ["biz-market-analysis"]


def test_what_selects_nothing_is_named(packs):
    # A pattern or a name that matched nothing was silent: a typo installed less than asked, and nobody was told.
    packs("typo", "eng-*\nmtk-*\narea:enginering\n")
    found = select.unmatched("typo", areas={"marketng"}, skills={"mkt-publsh", "mkt-publish"})
    assert found == ["pattern 'mtk-*' of pack 'typo' matches no skill",
                     "pattern 'area:enginering' of pack 'typo' matches no skill",
                     "no skill has the area 'marketng'", "no skill is named 'mkt-publsh'"]
    packs("fine", "eng-*\n!eng-refactor\n")
    assert select.unmatched("fine") == []


def test_the_command_line_warns_and_still_prints_the_selection():
    r = subprocess.run([sys.executable, str(SCRIPT), "--skills", "no-such-skill-x"], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0 and json.loads(r.stdout) == []
    assert "warning: no skill is named 'no-such-skill-x'" in r.stderr
    r = subprocess.run([sys.executable, str(SCRIPT), "--pack", "../default"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


# --- the area packs of the repository (A-36 part 1) -------------------------------------------------------------------------------

AREA_PACKS = ("business", "brand", "design", "marketing", "planning", "code")


def _repo_pack(name):
    r = subprocess.run([sys.executable, str(SCRIPT), "--pack", name, "--lines"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stderr == "", f"pack {name}: {r.stderr}"
    return r.stdout.split()


def test_the_design_pack_holds_the_design_chain_and_no_skill_is_in_two_area_packs():
    """`design-ux-flows` stops without `docs/product/prd.md`, and `design-execute` and `design-handoff` follow the brief: all three are in the design agent's scope, so that `plan.agent_of`
    finds an owner for each. A skill is in one pack only."""
    design = _repo_pack("design")
    assert {"product-prd", "product-feature-spec", "design-ux-flows", "design-system", "design-brief", "design-execute", "design-handoff"} <= set(design)
    seen = {}
    for pack in AREA_PACKS:
        for skill in _repo_pack(pack):
            assert skill not in seen, f"{skill} is in the packs {seen[skill]} and {pack}: exactly one enabled agent must own it"
            seen[skill] = pack
    assert {seen[s] for s in ("product-prd", "design-execute", "design-handoff")} == {"design"}
