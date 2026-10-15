"""Offline tests of scripts/update_prices.py (package P3, decision D36): the price table is written from OpenRouter's models API,
read here from a saved answer, never from the network. Every model and price below is invented.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_update_prices.py
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "update_prices.py"
ROOT = SCRIPT.parent.parent
URL = "https://openrouter.ai/api/v1/models"

ANSWER = {"data": [
    {"id": "acme/swift-1", "pricing": {"prompt": "0.0000002", "completion": "0.000001", "input_cache_read": "0.00000005"}},
    {"id": "acme/slow-2", "pricing": {"prompt": "0.000003", "completion": "0.000015", "input_cache_read": "0.0000003",
                                      "input_cache_write": "0.00000375", "overrides": [{"hours": "0-6"}]}},
    {"id": "acme/free-3", "pricing": {"prompt": "not a number", "completion": "-1"}},
]}


def run(*args, table=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


@pytest.fixture
def files(tmp_path):
    answer = tmp_path / "models.json"
    answer.write_text(json.dumps(ANSWER), encoding="utf-8")
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"models": {
        "kept-model": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0, "source": "https://prices.example/models", "accessed": "2026-07-01"},
    }}), encoding="utf-8")
    return answer, table


def test_a_model_of_the_answer_is_written_per_million_tokens_with_its_source_and_todays_date(files):
    answer, table = files
    out = run("--from-file", str(answer), "--table", str(table), "--model", "openrouter/acme/swift-1")
    assert out.returncode == 0, out.stderr
    summary = json.loads(out.stdout)
    assert summary["written"] == ["openrouter/acme/swift-1"] and summary["kept"] == [] and summary["missing"] == []
    entry = json.loads(table.read_text(encoding="utf-8"))["models"]["openrouter/acme/swift-1"]
    assert entry["input_usd_per_mtok"] == pytest.approx(0.2) and entry["output_usd_per_mtok"] == pytest.approx(1.0)
    assert entry["cache_read_usd_per_mtok"] == pytest.approx(0.05) and "cache_write_usd_per_mtok" not in entry, "a kind the list does not price is left out"
    assert entry["source"] == URL and entry["accessed"] == datetime.date.today().isoformat() == summary["accessed"]


def test_an_entry_the_table_already_holds_is_kept_exactly_unless_refresh_is_given(files):
    answer, table = files
    data = json.loads(table.read_text(encoding="utf-8"))
    data["models"]["openrouter/acme/slow-2"] = {"input_usd_per_mtok": 9.0, "output_usd_per_mtok": 9.0, "source": URL, "accessed": "2026-01-01",
                                                "aliases": ["slow-2"]}
    table.write_text(json.dumps(data), encoding="utf-8")
    before = table.read_text(encoding="utf-8")
    out = json.loads(run("--from-file", str(answer), "--table", str(table), "--model", "openrouter/acme/slow-2").stdout)
    assert out["kept"] == ["openrouter/acme/slow-2"] and out["written"] == [] and table.read_text(encoding="utf-8") == before
    out = json.loads(run("--from-file", str(answer), "--table", str(table), "--model", "openrouter/acme/slow-2", "--refresh").stdout)
    assert out["written"] == ["openrouter/acme/slow-2"]
    entry = json.loads(table.read_text(encoding="utf-8"))["models"]["openrouter/acme/slow-2"]
    assert entry["input_usd_per_mtok"] == pytest.approx(3.0) and entry["cache_write_usd_per_mtok"] == pytest.approx(3.75)
    assert entry["aliases"] == ["slow-2"], "the aliases the workbench wrote are kept"
    assert "by time of day" in entry["notes"], "a time-of-day price is written at its base price and says so"
    assert "kept-model" in json.loads(table.read_text(encoding="utf-8"))["models"], "an entry nobody asked for is not touched"


def test_a_model_the_list_does_not_hold_or_cannot_price_is_missing_and_exits_1_and_nothing_is_invented(files):
    answer, table = files
    before = table.read_text(encoding="utf-8")
    out = run("--from-file", str(answer), "--table", str(table), "--model", "openrouter/acme/unknown-9", "--model", "openrouter/acme/free-3")
    assert out.returncode == 1
    assert json.loads(out.stdout)["missing"] == ["openrouter/acme/unknown-9", "openrouter/acme/free-3"]
    assert table.read_text(encoding="utf-8") == before


def test_a_dry_run_writes_nothing_and_a_model_of_another_provider_is_a_usage_error(files):
    answer, table = files
    before = table.read_text(encoding="utf-8")
    out = run("--from-file", str(answer), "--table", str(table), "--model", "openrouter/acme/swift-1", "--dry-run")
    assert out.returncode == 0 and json.loads(out.stdout)["written"] == ["openrouter/acme/swift-1"] and table.read_text(encoding="utf-8") == before
    refused = run("--from-file", str(answer), "--table", str(table), "--model", "anthropic/claude-x")
    assert refused.returncode == 2 and "openrouter/<id>" in refused.stderr


def test_an_unreadable_source_or_table_and_an_unknown_option_fail_with_a_reason(files, tmp_path):
    answer, table = files
    assert run("--from-file", str(tmp_path / "missing.json"), "--table", str(table), "--model", "openrouter/acme/swift-1").returncode == 1
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert run("--from-file", str(answer), "--table", str(broken), "--model", "openrouter/acme/swift-1").returncode == 2
    assert run("--nope").returncode == 2
    assert "Usage" in run("--help").stdout


def test_without_a_model_it_prices_the_openrouter_models_of_the_gate_file(files):
    answer, table = files
    gate = json.loads((ROOT / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    wanted = sorted(m for m, e in gate["models"].items() if isinstance(e, dict) and e.get("route") == "openrouter")
    out = json.loads(run("--from-file", str(answer), "--table", str(table), "--dry-run").stdout)
    assert sorted(out["written"] + out["kept"] + out["missing"]) == wanted and wanted, "the gate file's models, and no other"


def test_the_committed_table_has_a_source_and_a_date_for_every_entry():
    table = json.loads((ROOT / "runtime" / "prices.json").read_text(encoding="utf-8"))["models"]
    assert table
    for name, entry in table.items():
        assert str(entry.get("source", "")).startswith("https://"), name
        datetime.date.fromisoformat(entry["accessed"])
        assert isinstance(entry.get("input_usd_per_mtok"), (int, float)) and isinstance(entry.get("output_usd_per_mtok"), (int, float)), name


# --- a model pinned to one provider is priced at that provider, never at the cheapest endpoint (review of P3) -----------------


def pinned():
    """(model id, provider pin) of a gate-file model that is on OpenRouter and pinned to one provider."""
    gate = json.loads((ROOT / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    for name, entry in gate["models"].items():
        if isinstance(entry, dict) and entry.get("route") == "openrouter" and entry.get("provider_pin"):
            return name, entry["provider_pin"]
    raise AssertionError("the gate file pins no OpenRouter model")


def endpoint(tag, prompt, completion, **more):
    return {"name": f"{tag} | invented", "provider_name": tag.split("/")[0].title(), "tag": tag,
            "pricing": {"prompt": prompt, "completion": completion, **more}}


def endpoints_file(tmp_path, model, endpoints):
    path = tmp_path / "endpoints.json"
    path.write_text(json.dumps({model[len("openrouter/"):]: {"data": {"id": model[len("openrouter/"):], "endpoints": endpoints}}}), encoding="utf-8")
    return path


def test_a_pinned_model_is_priced_at_its_pin_and_not_at_the_cheapest_endpoint(tmp_path):
    model, pin = pinned()
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"models": {model: {"input_usd_per_mtok": 0.02, "output_usd_per_mtok": 0.7, "source": URL, "accessed": "2026-10-01"}}}), encoding="utf-8")
    answer = endpoints_file(tmp_path, model, [
        endpoint("cheap-host/fp4", "0.00000002", "0.0000007"),                                           # the cheapest of the model, not the pin
        endpoint(f"{pin}/fp8", "0.00000014", "0.00000042", input_cache_read="0.0000000042", discount=0.3),
        endpoint("dear-host", "0.000001", "0.000004")])
    out = run("--endpoints-file", str(answer), "--table", str(table), "--model", model)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["written"] == [model], "an entry priced before the pin was read is written again, without --refresh"
    entry = json.loads(table.read_text(encoding="utf-8"))["models"][model]
    assert entry["input_usd_per_mtok"] == pytest.approx(0.14) and entry["output_usd_per_mtok"] == pytest.approx(0.42)
    assert entry["cache_read_usd_per_mtok"] == pytest.approx(0.0042)
    assert entry["provider"] == pin and entry["source"] == f"{URL}/{model[len('openrouter/'):]}/endpoints"
    assert entry["accessed"] == datetime.date.today().isoformat()
    assert "30%" in entry["notes"] and pin in entry["notes"]
    again = json.loads(run("--endpoints-file", str(answer), "--table", str(table), "--model", model).stdout)
    assert again["kept"] == [model] and again["written"] == [], "an entry priced at its pin is left as it is"


def test_the_dearest_endpoint_of_the_pin_is_written_when_it_has_several_quantizations(tmp_path):
    model, pin = pinned()
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"models": {}}), encoding="utf-8")
    answer = endpoints_file(tmp_path, model, [endpoint(f"{pin}/fp8", "0.0000002", "0.0000008"), endpoint(f"{pin}/fp4", "0.0000001", "0.0000004")])
    assert run("--endpoints-file", str(answer), "--table", str(table), "--model", model).returncode == 0
    entry = json.loads(table.read_text(encoding="utf-8"))["models"][model]
    assert entry["input_usd_per_mtok"] == pytest.approx(0.2) and entry["output_usd_per_mtok"] == pytest.approx(0.8)


def test_a_pin_with_no_endpoint_is_missing_and_no_other_providers_price_is_written(tmp_path):
    model, pin = pinned()
    table = tmp_path / "prices.json"
    before = json.dumps({"models": {model: {"input_usd_per_mtok": 0.02, "output_usd_per_mtok": 0.7, "source": URL, "accessed": "2026-10-01"}}})
    table.write_text(before, encoding="utf-8")
    answer = endpoints_file(tmp_path, model, [endpoint("other-host", "0.00000001", "0.00000001"), endpoint(f"{pin}-other/fp8", "0.0000001", "0.0000002")])
    out = run("--endpoints-file", str(answer), "--table", str(table), "--model", model)
    assert out.returncode == 1 and json.loads(out.stdout)["missing"] == [model]
    assert table.read_text(encoding="utf-8") == before, "the cheaper entry that was there is not replaced by another provider's price"
    empty = tmp_path / "none.json"
    empty.write_text(json.dumps({}), encoding="utf-8")
    assert json.loads(run("--endpoints-file", str(empty), "--table", str(table), "--model", model).stdout)["missing"] == [model]
    assert run("--endpoints-file", str(tmp_path / "nowhere.json"), "--table", str(table), "--model", model).returncode == 1


def test_a_model_without_a_pin_is_still_priced_from_the_models_list(files):
    answer, table = files
    out = run("--from-file", str(answer), "--table", str(table), "--model", "openrouter/acme/swift-1")
    assert out.returncode == 0 and json.loads(out.stdout)["written"] == ["openrouter/acme/swift-1"]
    entry = json.loads(table.read_text(encoding="utf-8"))["models"]["openrouter/acme/swift-1"]
    assert entry["source"] == URL and "provider" not in entry


def test_the_committed_price_of_a_pinned_model_is_the_pins_with_its_source_and_date():
    model, pin = pinned()
    entry = json.loads((ROOT / "runtime" / "prices.json").read_text(encoding="utf-8"))["models"][model]
    assert entry["provider"] == pin and entry["source"].endswith("/endpoints")
    datetime.date.fromisoformat(entry["accessed"])
