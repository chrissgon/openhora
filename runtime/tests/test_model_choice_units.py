"""Unit tests of the small parts of package P3 that the larger tests only pass through: the price table's reader
(runtime/prices.py), the project's keys default_model and price_max_age_days and the retired model_prices
(runtime/project_config.py), and the check of a model word (runtime/ops_models.py). Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_model_choice_units.py
"""
from __future__ import annotations

import datetime
import json

import pytest

import standin_tree as st

lab = st.load("lab")
prices = st.load("prices")
ops_core = st.load("ops_core")
ops_models = st.load("ops_models")
project_config = st.load("project_config")

TABLE = {"models": {
    "acme/swift-1": {"aliases": ["swift"], "input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0, "cache_read_usd_per_mtok": 0.2,
                     "source": "https://prices.example/models", "accessed": "2026-10-01"},
    "acme/odd-2": {"input_usd_per_mtok": -1, "output_usd_per_mtok": True, "source": "s", "accessed": "not a date"},
    "acme/bad-3": "not an entry"}}


def test_load_keeps_entries_drops_fields_that_are_not_prices_and_survives_a_bad_file(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(TABLE), encoding="utf-8")
    loaded = prices.load(str(path))
    assert set(loaded["models"]) == {"acme/swift-1", "acme/odd-2"}, "a value that is not an entry is left out"
    odd = loaded["models"]["acme/odd-2"]
    assert "input_usd_per_mtok" not in odd and "output_usd_per_mtok" not in odd, "unknown, not zero"
    path.write_text("{not json", encoding="utf-8")
    assert prices.load(str(path)) == {"models": {}} and prices.load(str(tmp_path / "missing.json")) == {"models": {}}
    assert prices.load()["models"], "the committed table is read when no path is given"


def test_find_matches_an_id_then_an_alias_and_otherwise_nothing(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(TABLE), encoding="utf-8")
    table = prices.load(str(path))
    assert prices.find(table, ["acme/swift-1"])[0] == "acme/swift-1"
    assert prices.find(table, ["nothing", "swift"])[0] == "acme/swift-1"
    assert prices.find(table, ["nothing"]) == (None, None) and prices.price_of(table, []) is None


def test_expected_cost_is_arithmetic_a_kind_without_tokens_costs_nothing_and_an_unpriced_kind_is_unknown():
    entry = TABLE["models"]["acme/swift-1"]
    assert prices.expected_cost({"input": 1000, "output": 200}, entry) == pytest.approx((1000 * 2.0 + 200 * 10.0) / 1e6)
    assert prices.expected_cost({"input": 1000, "output": 0, "cache_write": 0}, entry) == pytest.approx(1000 * 2.0 / 1e6), "no tokens of a kind, no price needed"
    assert prices.expected_cost({"input": 1000, "cache_write": 5}, entry) is None, "tokens of a kind the entry does not price"
    assert prices.expected_cost(None, entry) is None and prices.expected_cost({"input": 1}, None) is None


def test_age_and_staleness_follow_the_accessed_date_and_a_missing_date_is_not_fresh():
    entry = TABLE["models"]["acme/swift-1"]
    assert prices.age_days(entry, "2026-10-15") == 14 and prices.age_days(entry, datetime.date(2026, 10, 1)) == 0
    assert prices.is_stale(entry, "2026-10-15", 13) is True and prices.is_stale(entry, "2026-10-15", 14) is False
    assert prices.is_stale({"accessed": "?"}, "2026-10-15") is True and prices.age_days({"accessed": "?"}, "2026-10-15") is None
    assert prices.summary(entry, "2026-10-15", 90) == {"source": "https://prices.example/models", "accessed": "2026-10-01", "age_days": 14, "stale": False}
    assert prices.summary(None, "2026-10-15") is None


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def configure(tree, **extra) -> str:
    path = str(tree["project"])
    file = project_config.path(path)
    with open(file, encoding="utf-8") as f:
        good = json.load(f)
    for key in ("default_model", "price_max_age_days", "model_prices"):
        good.pop(key, None)
    with open(file, "w", encoding="utf-8") as f:
        json.dump({**good, **extra}, f)
    return path


def test_default_model_and_price_max_age_days_have_their_defaults_and_are_known_keys(tree):
    assert {"default_model", "price_max_age_days"} <= set(project_config.TASK_RUNTIME_KEYS)
    cfg = project_config.load(configure(tree))
    assert cfg["default_model"] is None and cfg["price_max_age_days"] == 90
    cfg = project_config.load(configure(tree, default_model="auto", price_max_age_days=30))
    assert cfg["default_model"] == "auto" and cfg["price_max_age_days"] == 30


@pytest.mark.parametrize("key, bad", [("default_model", ""), ("default_model", " m"), ("default_model", 3), ("default_model", ["m"]),
                                      ("price_max_age_days", 0), ("price_max_age_days", 3651), ("price_max_age_days", 2.5),
                                      ("price_max_age_days", True), ("price_max_age_days", "90")])
def test_a_bad_value_of_either_key_is_refused_by_name(tree, key, bad):
    path = configure(tree, **{key: bad})
    with pytest.raises(project_config.ConfigError) as raised:
        project_config.load(path)
    assert key in str(raised.value)


def test_model_prices_is_retired_still_accepted_ignored_and_warned_about(tree):
    entry = {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0, "cache_read_usd_per_mtok": 0.1, "cache_write_usd_per_mtok": 1.0,
             "source": "https://prices.example/models", "date": "2026-10-01"}
    cfg = project_config.load(configure(tree, model_prices={"m": entry}))
    (warning,) = project_config.price_warnings(cfg)
    assert "retired" in warning and "runtime/prices.json" in warning
    assert project_config.price_warnings(project_config.load(configure(tree))) == []


def test_a_model_word_is_none_auto_or_a_listed_id_and_an_alias_is_written_as_its_id(monkeypatch):
    def resolve(word):
        if word in ("m", "alias-m"):
            return "m"
        raise lab.LabError("config", f"{word} is not a model of the gate file")

    monkeypatch.setattr(lab, "resolve_model", resolve)
    assert ops_models.check_word(None) is None and ops_models.check_word("") is None
    assert ops_models.check_word("auto") == "auto"
    assert ops_models.check_word("m") == "m" and ops_models.check_word("alias-m") == "m"
    for bad in ("nope", 3, ["m"]):
        with pytest.raises(ops_core.OpsError) as raised:
            ops_models.check_word(bad)
        assert raised.value.code == 2
