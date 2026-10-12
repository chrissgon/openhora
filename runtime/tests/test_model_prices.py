"""Tests of the key model_prices of the project's configuration (runtime/project_config.py): the prices a person types from a
provider's page so that a run's cost can be recomputed from its token counts. Invented model ids and prices.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_model_prices.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
project_config = st.load("project_config")

ENTRY = {"input_usd_per_mtok": 3, "output_usd_per_mtok": 15.5, "cache_read_usd_per_mtok": 0, "cache_write_usd_per_mtok": 3.75,
         "source": "https://prices.example/models", "date": "2026-10-01"}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def prices_of(tree, value=...) -> dict:
    """Write the configuration with model_prices = value (left out for ...), and load it."""
    path = str(tree["project"])
    file = project_config.path(path)
    raw = {k: v for k, v in json.loads(open(file, encoding="utf-8").read()).items() if k != "model_prices"}
    if value is not ...:
        raw["model_prices"] = value
    with open(file, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    return project_config.load(path)["model_prices"]


def refused(tree, value) -> str:
    with pytest.raises(project_config.ConfigError) as raised:
        prices_of(tree, value)
    return str(raised.value)


def test_model_prices_is_absent_empty_or_an_object_of_checked_entries(tree):
    assert prices_of(tree) == {}
    assert prices_of(tree, {}) == {}
    got = prices_of(tree, {"model-alpha": ENTRY, "model-beta": dict(ENTRY, source="  the page  ")})
    assert got["model-alpha"] == ENTRY and got["model-beta"]["source"] == "the page"
    assert got["model-alpha"]["cache_read_usd_per_mtok"] == 0  # a price of 0 is a price


def test_a_price_that_is_not_a_number_of_zero_or_more_is_refused_by_its_model_and_name(tree):
    for key in ("input_usd_per_mtok", "output_usd_per_mtok", "cache_read_usd_per_mtok", "cache_write_usd_per_mtok"):
        for bad in (-0.01, "3", True, None, float("inf"), [1]):
            message = refused(tree, {"model-alpha": dict(ENTRY, **{key: bad})})
            assert f"model_prices.model-alpha.{key} must be a number, 0 or more" in message, (key, bad)


def test_an_entry_with_a_missing_or_unknown_key_or_empty_text_is_refused(tree):
    for key in ENTRY:
        short = {k: v for k, v in ENTRY.items() if k != key}
        assert f"missing key {key}" in refused(tree, {"model-alpha": short})
    assert "unknown key price_per_token" in refused(tree, {"model-alpha": dict(ENTRY, price_per_token=1)})
    for key in ("source", "date"):
        for bad in ("", "   ", 7, None):
            assert f"model_prices.model-alpha.{key} must be non-empty text" in refused(tree, {"model-alpha": dict(ENTRY, **{key: bad})})
    assert "must be an object of model ids" in refused(tree, [ENTRY])
    assert "model_prices.model-alpha must be an object" in refused(tree, {"model-alpha": 3})
    assert "a model id is non-empty text" in refused(tree, {"": ENTRY})


def test_the_prices_are_in_the_hash_the_person_accepts(tree):
    path = str(tree["project"])
    first = project_config.load(path)["sha256"]
    ops.accept_config(path, first)
    assert ops.status(path)["config"]["sha256"] == first
    prices_of(tree, {"model-alpha": ENTRY})  # typing a price changes the file, so the hash
    with pytest.raises(ops.OpsError) as raised:
        ops.status(path)
    assert raised.value.code == 3 and "accept-config" in str(raised.value)
