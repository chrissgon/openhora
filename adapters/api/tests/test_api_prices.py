"""Offline test of the API adapter's price: it reads the workbench's one price table (runtime/prices.json, the table the runtime
reads too, decision D36) by a model's id or one of its aliases, and keeps no table of its own.

Run: uv run --with pytest==9.1.1 pytest -q adapters/api/tests/test_api_prices.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "run_agent.py"


def adapter():
    spec = importlib.util.spec_from_file_location("api_run_agent_for_the_price_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_price_is_read_from_the_workbenchs_one_table_by_id_or_alias(tmp_path):
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"models": {
        "acme/swift-1": {"aliases": ["swift"], "input_usd_per_mtok": 0.2, "output_usd_per_mtok": 1.0, "cache_read_usd_per_mtok": 0.05,
                         "source": "https://prices.example/models", "accessed": "2026-10-01"},
        "acme/half-2": {"input_usd_per_mtok": 3.0, "source": "https://prices.example/models", "accessed": "2026-10-01"}}}))
    mod = adapter()
    mod.PRICES = table
    lines = []
    assert mod.load_price("acme/swift-1", lines.append) == {"input_per_mtok": 0.2, "output_per_mtok": 1.0, "cache_read_per_mtok": 0.05}
    assert mod.load_price("swift", lines.append) == mod.load_price("acme/swift-1", lines.append), "an alias finds the same entry"
    assert mod.load_price("acme/half-2", lines.append) is None, "no output price: no price"
    assert mod.load_price("acme/unknown", lines.append) is None
    mod.PRICES = tmp_path / "missing.json"
    assert mod.load_price("swift", lines.append) is None and "unreadable" in lines[-1]


def test_the_adapter_points_at_the_runtimes_table_and_keeps_none_of_its_own():
    mod = adapter()
    assert Path(mod.PRICES).name == "prices.json" and Path(mod.PRICES).parent.name == "runtime"
    assert not (HERE / "prices.json").exists()
    committed = json.loads(Path(mod.PRICES).read_text(encoding="utf-8"))["models"]
    assert mod.load_price(next(iter(committed)), lambda line: None) is not None, "the committed table gives a price to its first model"


def test_the_adapter_and_the_runtimes_reader_give_the_same_figures_from_the_same_file(tmp_path):
    spec = importlib.util.spec_from_file_location("runtime_prices_for_the_adapter_test", HERE.parents[1] / "runtime" / "prices.py")
    runtime_prices = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runtime_prices
    spec.loader.exec_module(runtime_prices)
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"models": {"acme/swift-1": {"aliases": ["swift"], "input_usd_per_mtok": 0.2, "output_usd_per_mtok": 1.0,
                                                             "cache_read_usd_per_mtok": 0.05, "cache_write_usd_per_mtok": 0.25,
                                                             "source": "https://prices.example/models", "accessed": "2026-10-01"}}}))
    mod = adapter()
    mod.PRICES = table
    ours = mod.load_price("swift", lambda line: None)
    entry = runtime_prices.price_of(runtime_prices.load(str(table)), ["swift"])
    assert (ours["input_per_mtok"], ours["output_per_mtok"], ours["cache_read_per_mtok"], ours["cache_write_per_mtok"]) == (
        entry["input_usd_per_mtok"], entry["output_usd_per_mtok"], entry["cache_read_usd_per_mtok"], entry["cache_write_usd_per_mtok"])
    # the same usage costs the same through the adapter's own arithmetic and the runtime's
    usage = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 500, "cache_creation_input_tokens": 100}
    tokens, cost = mod.usage_cost("anthropic", usage, ours, lambda line: None)
    assert cost == pytest.approx(runtime_prices.expected_cost({"input": 1000, "output": 200, "cache_read": 500, "cache_write": 100}, entry))
