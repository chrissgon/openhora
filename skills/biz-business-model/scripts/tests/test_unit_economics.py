"""Tests for skills/biz-business-model/scripts/unit_economics.py. Offline; every name and number is fictional.

Run: uv run --with pytest pytest skills/biz-business-model/scripts/tests/test_unit_economics.py
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills/biz-business-model/scripts/unit_economics.py"

RECURRING = {
    "currency": "BRL",
    "unit": "teacher per month",
    "billing": "recurring",
    "prices": [{"value": 40.0, "source": "proposed"}, {"value": 60.0, "source": "proposed"}],
    "variable_costs": [{"name": "model usage", "value": 4.0, "source": "M2"}],
    "fees_percent": [{"name": "card processor", "value": 5.0, "source": "7"}],
    "tax_percent": {"value": 10.0, "source": "user"},
    "fixed_costs": [{"name": "hosting and tools", "value": 100.0, "source": "user"}],
    "hours_per_unit": {"value": 0.5, "source": "assumed"},
    "hours_per_new_unit": {"value": 1.0, "source": "assumed"},
    "hours_per_week": {"value": 12, "source": "state file"},
    "goal": {"kind": "customers", "value": 10, "source": "state file"},
}

ONE_OFF = {
    "currency": "BRL",
    "unit": "setup project",
    "billing": "one-off",
    "prices": [{"value": 3000.0, "source": "proposed"}],
    "variable_costs": [],
    "fees_percent": [],
    "tax_percent": {"value": 6.0, "source": "user"},
    "fixed_costs": [],
    "hours_per_unit": {"value": 25.0, "source": "assumed"},
    "hours_per_new_unit": {"value": 5.0, "source": "assumed"},
    "hours_per_week": {"value": 20, "source": "state file"},
    "goal": {"kind": "customers", "value": 3, "source": "state file"},
}


def run(data, *args, raw=None):
    stdin = raw if raw is not None else json.dumps(data)
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True,
                          timeout=60)


def ok(data, *args):
    r = run(data, *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_recurring_case_matches_numbers_worked_by_hand():
    out = ok(RECURRING)
    first, second = out["results"]
    # 40 BRL: fees and tax 15% = 6.00; contribution 40 - 6 - 4 = 30.00; margin 75.0%
    assert first["fee_and_tax_per_unit"] == 6.0
    assert first["variable_cost_per_unit"] == 4.0
    assert first["contribution_per_unit"] == 30.0
    assert first["contribution_margin_percent"] == 75.0
    assert first["cost_floor_price"] == 4.71  # 4 / 0.85
    assert first["contribution_before_tax_per_unit"] == 34.0  # 40 - 2 - 4
    assert first["cost_floor_before_tax"] == 4.21  # 4 / 0.95
    assert first["units_to_cover_fixed"] == 4  # ceil(100 / 30)
    assert first["units_for_goal"] == 10
    assert first["revenue_at_goal"] == 400.0
    assert first["contribution_at_goal"] == 300.0
    assert first["profit_at_goal"] == 200.0
    assert first["hours_available_per_month"] == 52.0  # 12 * 52 / 12
    assert first["hours_at_goal_per_month"] == 5.0
    assert first["onboarding_hours_total"] == 10.0  # reported apart
    assert first["capacity_ceiling_units"] == 104
    assert first["goal_within_capacity"] is True
    assert first["missing"] == {}
    # 60 BRL: contribution 60 - 9 - 4 = 47.00; the cost floor is the same for every price
    assert second["contribution_per_unit"] == 47.0
    assert second["cost_floor_price"] == first["cost_floor_price"]
    assert out["assumed"] == ["hours_per_unit", "hours_per_new_unit"]
    assert out["unknown"] == []


def test_one_off_service_does_not_fit_the_hours():
    out = ok(ONE_OFF)
    res = out["results"][0]
    assert res["fee_and_tax_per_unit"] == 180.0
    assert res["contribution_per_unit"] == 2820.0
    assert res["hours_available_per_month"] == 86.7  # 20 * 52 / 12
    assert res["hours_at_goal_per_month"] == 90.0  # 3 sales x (25 + 5)
    assert res["capacity_ceiling_units"] == 2  # floor(86.67 / 30)
    assert res["goal_within_capacity"] is False
    assert "onboarding_hours_total" not in res
    assert res["units_to_cover_fixed"] == 0  # no fixed costs


def test_revenue_goal_is_turned_into_units():
    data = copy.deepcopy(RECURRING)
    data["prices"] = [{"value": 50.0, "source": "proposed"}]
    data["goal"] = {"kind": "revenue", "value": 480.0, "source": "user"}
    res = ok(data)["results"][0]
    assert res["units_for_goal"] == 10  # ceil(480 / 50) = 10
    assert res["revenue_at_goal"] == 500.0


def test_no_hours_limit_when_a_unit_takes_no_hours():
    data = copy.deepcopy(ONE_OFF)
    data["hours_per_unit"] = {"value": 0, "source": "user"}
    data["hours_per_new_unit"] = {"value": 0, "source": "user"}
    res = ok(data)["results"][0]
    assert res["capacity_ceiling_units"] == "no hours limit"
    assert res["goal_within_capacity"] is True


def test_contribution_never_positive_means_never_covers_fixed():
    data = copy.deepcopy(RECURRING)
    data["prices"] = [{"value": 4.0, "source": "proposed"}]
    res = ok(data)["results"][0]
    assert res["contribution_per_unit"] < 0
    assert res["units_to_cover_fixed"] == "never"


def test_unknown_tax_makes_every_dependent_result_unknown():
    data = copy.deepcopy(RECURRING)
    data["tax_percent"] = {"value": None, "source": "unknown"}
    out = ok(data)
    res = out["results"][0]
    for key in ("fee_and_tax_per_unit", "contribution_per_unit", "contribution_margin_percent", "cost_floor_price",
                "units_to_cover_fixed", "contribution_at_goal", "profit_at_goal"):
        assert res[key] == "unknown", key
        assert "tax_percent" in res["missing"][key], key
    # what does not need the tax is still computed, and never from a zero substituted for the tax
    assert res["variable_cost_per_unit"] == 4.0
    assert res["revenue_at_goal"] == 400.0
    assert res["hours_at_goal_per_month"] == 5.0
    assert res["contribution_before_tax_per_unit"] == 34.0
    assert "tax_percent" in out["unknown"]
    assert "Assumed inputs: hours_per_unit, hours_per_new_unit" in out["table"]


def test_unknown_goal_and_hours_are_unknown_too():
    data = copy.deepcopy(RECURRING)
    data["goal"] = {"kind": "customers", "value": None, "source": "unknown"}
    data["hours_per_week"] = {"value": None, "source": "unknown"}
    res = ok(data)["results"][0]
    assert res["units_for_goal"] == "unknown"
    assert res["goal_within_capacity"] == "unknown"
    assert res["hours_available_per_month"] == "unknown"
    assert res["missing"]["goal_within_capacity"] == ["goal", "hours_per_week"]


def test_a_number_without_source_is_refused():
    for bad in ("", None, "guess"):
        data = copy.deepcopy(RECURRING)
        data["variable_costs"][0]["source"] = bad
        r = run(data)
        assert r.returncode == 1
        assert "variable_costs.model usage" in r.stderr
        assert json.loads(r.stdout)["ok"] is False


def test_proposed_is_for_prices_only_and_unknown_needs_null():
    data = copy.deepcopy(RECURRING)
    data["fixed_costs"][0]["source"] = "proposed"
    assert run(data).returncode == 1
    data = copy.deepcopy(RECURRING)
    data["tax_percent"] = {"value": 10.0, "source": "unknown"}
    assert run(data).returncode == 1
    data = copy.deepcopy(RECURRING)
    data["tax_percent"] = {"value": None, "source": "user"}
    assert run(data).returncode == 1


def test_negative_value_and_missing_field_are_refused():
    data = copy.deepcopy(RECURRING)
    data["fixed_costs"][0]["value"] = -5
    assert run(data).returncode == 1
    data = copy.deepcopy(RECURRING)
    del data["tax_percent"]
    r = run(data)
    assert r.returncode == 1 and "tax_percent" in r.stderr
    data = copy.deepcopy(RECURRING)
    data["prices"] = [{"value": None, "source": "unknown"}]
    assert run(data).returncode == 1


def test_fees_plus_tax_at_or_above_100_percent_is_refused():
    data = copy.deepcopy(RECURRING)
    data["fees_percent"] = [{"name": "platform", "value": 90.0, "source": "3"}]
    data["tax_percent"] = {"value": 10.0, "source": "user"}
    r = run(data)
    assert r.returncode == 1
    assert "100%" in r.stderr


def test_bad_json_and_bad_arguments_exit_2():
    assert run(None, raw="{not json").returncode == 2
    assert run(None, "--input", "/no/such/file.json", raw="").returncode == 2
    assert run(RECURRING, "--label", "first").returncode == 2


def test_table_has_a_column_per_price_and_a_from_column():
    out = ok(RECURRING, "--label", "M3")
    rows = out["table"].splitlines()
    assert rows[0] == "| Metric | Price 1 | Price 2 | From |"
    assert all(r.count("|") == rows[0].count("|") for r in rows)
    assert "| Contribution per unit | 30.00 BRL | 47.00 BRL | M3 |" in rows
    assert rows[-1].startswith("| Assumed inputs: hours_per_unit, hours_per_new_unit")
    one = ok(ONE_OFF)["table"].splitlines()
    assert one[0] == "| Metric | Price 1 | From |"


def test_input_file_works_and_help_exits_zero(tmp_path):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(RECURRING), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--input", str(path)], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0 and json.loads(r.stdout)["ok"] is True
    h = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert h.returncode == 0 and "unit economics" in h.stdout.lower()
