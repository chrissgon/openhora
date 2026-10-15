"""Tests of what the model pickers show (package P3, spec item 8; review): the agent's picker lists each model with its band over
the skills of the agent's pack and its expected cost, the request's picker the same over every skill in scope with a
recommendation (the cheapest reliable pair), and a pair that is reliable only through community evidence is marked "output
reviewed". Offline; the stand-in tree of test_model_choice; every name and price is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_model_pickers.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_model_choice import BUSINESS, PACKS, configure, tree  # noqa: F401  (autonomous business agent; "m" reliable, "fm" without evidence)

ops = st.load("ops")
lab = st.load("lab")
ops_models = st.load("ops_models")
prices = st.load("prices")

USAGE = {"input": 1000.0, "output": 200.0, "cache_read": 0.0, "cache_write": 0.0}
FM = {"band": "reliable", "cause": None, "score": 0.9, "mean": 0.95, "runs": 6, "web_measured": False, "usage_mean": USAGE}


def cheaper_fm(monkeypatch, source="lab"):
    """The model "fm" is reliable on every skill through `source`, with a measured usage and a price a tenth of "m"'s."""
    real = lab.standing

    def standing(skill):
        found = real(skill)
        if source == "community":
            found["community"] = {"fm": dict(FM, source="community", community_only=True, images=[])}
        else:
            found["models"]["fm"] = dict(FM, source=source)
        return found

    monkeypatch.setattr(lab, "standing", standing)
    table = prices.load()
    table["models"]["fm"] = dict(table["models"]["m"], input_usd_per_mtok=0.1, output_usd_per_mtok=0.5)
    monkeypatch.setattr(prices, "load", lambda path=None: table)


def test_the_agents_picker_lists_each_model_with_its_band_over_the_agents_skills_and_its_expected_cost(tree):
    [agent] = ops.agents(str(tree["project"]))["agents"]
    lines = {c["model"]: c for c in agent["model_commands"]}
    assert (lines["m"]["skills"], lines["m"]["reliable"], lines["m"]["band"], lines["m"]["community_only"]) == (2, 2, "reliable", 0)
    assert lines["m"]["expected_cost"] == pytest.approx((1000 * 1.0 + 200 * 5.0) / 1e6)
    assert lines["m"]["price"]["stale"] is False and lines["m"]["price"]["source"] == "https://prices.example/models"
    assert (lines["fm"]["skills"], lines["fm"]["reliable"], lines["fm"]["band"]) == (2, 0, "needs a test")
    assert lines["fm"]["expected_cost"] is None and lines["fm"]["price"] is None
    assert "skills" not in lines["auto"] and "skills" not in lines["default"], "auto and default are ways of choosing, not models"
    assert agent["recommended_model"] == "m", "the cheapest model reliable for every skill of the pack"


def test_the_recommendation_is_the_cheapest_model_reliable_for_every_skill_and_a_dearer_one_is_not_recommended(tree, monkeypatch):
    cheaper_fm(monkeypatch)
    [agent] = ops.agents(str(tree["project"]))["agents"]
    assert agent["recommended_model"] == "fm"
    lines = {c["model"]: c for c in agent["model_commands"]}
    assert lines["fm"]["expected_cost"] < lines["m"]["expected_cost"] and lines["fm"]["band"] == "reliable"
    found = ops.skills(str(tree["project"]))
    assert found["recommended_model"] == "fm"
    assert {m["model"]: m["band"] for m in found["models"]} == {"m": "reliable", "fm": "reliable"}


def test_a_pair_reliable_only_through_community_evidence_is_counted_and_marked_for_review(tree, monkeypatch):
    cheaper_fm(monkeypatch, source="community")
    found = ops.skills(str(tree["project"]))
    fm = next(m for m in found["models"] if m["model"] == "fm")
    assert (fm["reliable"], fm["community_only"], fm["band"]) == (found["models"][1]["skills"], found["models"][1]["skills"], "reliable")
    m = next(m for m in found["models"] if m["model"] == "m")
    assert m["community_only"] == 0
    [agent] = ops.agents(str(tree["project"]))["agents"]
    line = next(c for c in agent["model_commands"] if c["model"] == "fm")
    assert line["community_only"] == 2 and line["reliable"] == 2
    # it is ranked: auto would choose it; the page says its output is reviewed (the label is the page's, models.js)
    assert found["recommended_model"] == "fm"


def test_recommend_has_no_model_when_nothing_is_reliable_or_priced():
    assert ops_models.recommend([]) is None
    assert ops_models.recommend([{"model": "a", "skills": 3, "reliable": 0, "expected_cost": 0.1}]) is None
    assert ops_models.recommend([{"model": "a", "skills": 3, "reliable": 3, "expected_cost": None}]) is None
    lines = [{"model": "dear", "skills": 3, "reliable": 3, "expected_cost": 0.5}, {"model": "cheap", "skills": 3, "reliable": 3, "expected_cost": 0.1},
             {"model": "half", "skills": 3, "reliable": 2, "expected_cost": 0.01}]
    assert ops_models.recommend(lines) == "cheap", "a model reliable for fewer skills is not recommended while one is reliable for all"
    assert ops_models.recommend(lines[2:]) == "half", "with none reliable for all, the one reliable for the most"
    assert ops_models.band_word({"skills": 0, "reliable": 0}) == "needs a test" and ops_models.band_word({"skills": 3, "reliable": 1}) == "partial"
