#!/usr/bin/env python3
"""Compute unit economics and the hours a goal needs, refusing any number without a source.

Usage:
  python3 unit_economics.py < inputs.json
  python3 unit_economics.py --input inputs.json [--label M1]

Input, JSON (on standard input, or a file with --input):
  {"currency": "BRL", "unit": "teacher per month", "billing": "recurring",
   "prices": [{"value": 39.0, "source": "proposed"}],
   "variable_costs": [{"name": "model usage", "value": 4.2, "source": "M2"}],
   "fees_percent": [{"name": "card processor", "value": 4.99, "source": "7"}],
   "tax_percent": {"value": null, "source": "unknown"},
   "fixed_costs": [{"name": "hosting and tools", "value": 120.0, "source": "user"}],
   "hours_per_unit": {"value": 0.5, "source": "assumed"},
   "hours_per_new_unit": {"value": 1.0, "source": "assumed"},
   "hours_per_week": {"value": 10, "source": "state file"},
   "goal": {"kind": "customers", "value": 10, "source": "state file"}}

  billing: "recurring" (units are active customers per month; amounts are per unit per month) or
    "one-off" (units are sales per month; amounts are per sale).
  source: a source number ("7", "2b"), a command label ("M2"), "user", "state file", "proposed"
    (prices only), "assumed", or "unknown" (then value is null). Anything else, a number with no
    source, a negative value, or fees plus tax at or above 100%: exit 1, naming the field.
  goal.kind: "customers" (active paying customers, or sales per month for one-off) or "revenue"
    (per month, in the currency). 1 to 3 prices. A month is 52/12 weeks.

Per price the results are: fee_and_tax_per_unit, variable_cost_per_unit, contribution_per_unit,
contribution_margin_percent, cost_floor_price, contribution_before_tax_per_unit (price minus fees
minus variable cost, so a price can be judged while the tax is unknown), cost_floor_before_tax,
units_to_cover_fixed, units_for_goal, revenue_at_goal,
contribution_at_goal, profit_at_goal, hours_available_per_month, hours_at_goal_per_month,
onboarding_hours_total (recurring only), capacity_ceiling_units, goal_within_capacity. A result that
needs an input whose source is unknown is the string "unknown", and "missing" lists the unknown inputs
it needed; zero is never substituted for an unknown.

Output: JSON on stdout: {"ok": true, "inputs", "results", "assumed", "unknown", "table"}; the table is
Markdown, one column per price and a From column. --label sets the command label shown in From
(default M1). Exit 0 ok, 1 content refused (JSON with "findings" on stdout, the reason on stderr),
2 bad argument or unreadable JSON. No network; standard library only.
"""
import argparse
import json
import math
import re
import sys

SOURCE_NUMBER = re.compile(r"^(\d+[a-z]?|M\d+)$")
WORD_SOURCES = ("user", "state file", "assumed", "unknown", "proposed")
MONTH_WEEKS = 52.0 / 12.0


def usage_error(message):
    print(f"unit_economics.py: {message}", file=sys.stderr)
    sys.exit(2)


def source_ok(source, allow_proposed):
    if not isinstance(source, str):
        return False
    s = source.strip()
    if s == "proposed":
        return allow_proposed
    return bool(SOURCE_NUMBER.match(s)) or s in WORD_SOURCES


def read_item(field, item, findings, allow_proposed=False, minimum=0.0):
    """Validate {"value", "source"}; return (value or None, source) and append findings."""
    if not isinstance(item, dict) or "source" not in item or "value" not in item:
        findings.append({"field": field, "problem": 'must be an object with "value" and "source"'})
        return None, "unknown"
    value, source = item["value"], item["source"]
    if not source_ok(source, allow_proposed):
        findings.append({"field": field, "problem": f"source {source!r} is not a source number, an M label, "
                         "user, state file, assumed, unknown" + (", proposed" if allow_proposed else "")})
        return None, "unknown"
    source = source.strip()
    if source == "unknown":
        if value is not None:
            findings.append({"field": field, "problem": 'source "unknown" needs "value": null'})
        return None, "unknown"
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        findings.append({"field": field, "problem": "a number with a source is required, or source unknown "
                         "with value null"})
        return None, source
    if value < minimum or (minimum > 0 and value <= 0):
        findings.append({"field": field, "problem": f"value {value} is below the allowed minimum"})
        return None, source
    return float(value), source


def read_list(data, key, findings):
    items = data.get(key)
    if items is None:
        findings.append({"field": key, "problem": 'missing; use an empty list "[]" when there are none'})
        return []
    if not isinstance(items, list):
        findings.append({"field": key, "problem": "must be a list"})
        return []
    out = []
    for i, item in enumerate(items):
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            findings.append({"field": f"{key}[{i}]", "problem": 'every row needs a non-empty "name"'})
            name = f"row{i}"
        value, source = read_item(f"{key}.{name}", item, findings)
        out.append({"name": name.strip(), "value": value, "source": source})
    return out


def read_input(data):
    findings = []
    if not isinstance(data, dict):
        findings.append({"field": "input", "problem": "must be a JSON object"})
        return None, findings
    for key in ("currency", "unit"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            findings.append({"field": key, "problem": "missing or empty"})
    billing = data.get("billing")
    if billing not in ("recurring", "one-off"):
        findings.append({"field": "billing", "problem": 'must be "recurring" or "one-off"'})
    prices_raw = data.get("prices")
    prices = []
    if not isinstance(prices_raw, list) or not 1 <= len(prices_raw) <= 3:
        findings.append({"field": "prices", "problem": "must be a list of 1 to 3 prices"})
    else:
        for i, item in enumerate(prices_raw):
            value, source = read_item(f"prices[{i}]", item, findings, allow_proposed=True, minimum=1e-12)
            if value is None and source == "unknown":
                findings.append({"field": f"prices[{i}]", "problem": "a price cannot be unknown"})
            prices.append({"value": value, "source": source})
    variable = read_list(data, "variable_costs", findings)
    fees = read_list(data, "fees_percent", findings)
    fixed = read_list(data, "fixed_costs", findings)
    scalars = {}
    for key in ("tax_percent", "hours_per_unit", "hours_per_new_unit", "hours_per_week"):
        if key not in data:
            findings.append({"field": key, "problem": 'missing; give a value with a source, or "unknown"'})
            scalars[key] = (None, "unknown")
        else:
            scalars[key] = read_item(key, data[key], findings)
    goal_raw = data.get("goal")
    goal = (None, "unknown")
    kind = None
    if not isinstance(goal_raw, dict):
        findings.append({"field": "goal", "problem": "missing"})
    else:
        kind = goal_raw.get("kind")
        if kind not in ("customers", "revenue"):
            findings.append({"field": "goal.kind", "problem": 'must be "customers" or "revenue"'})
        goal = read_item("goal", goal_raw, findings, minimum=1e-12)
    # fees plus tax must stay under 100%, checked on the values that are known
    pct = sum(f["value"] for f in fees if f["value"] is not None)
    if scalars["tax_percent"][0] is not None:
        pct += scalars["tax_percent"][0]
    if pct >= 100:
        findings.append({"field": "fees_percent", "problem": f"fees plus tax are {pct}%, at or above 100%"})
    if findings:
        return None, findings
    return {
        "currency": data["currency"].strip(), "unit": data["unit"].strip(), "billing": billing,
        "prices": prices, "variable_costs": variable, "fees_percent": fees, "fixed_costs": fixed,
        "tax_percent": {"value": scalars["tax_percent"][0], "source": scalars["tax_percent"][1]},
        "hours_per_unit": {"value": scalars["hours_per_unit"][0], "source": scalars["hours_per_unit"][1]},
        "hours_per_new_unit": {"value": scalars["hours_per_new_unit"][0],
                               "source": scalars["hours_per_new_unit"][1]},
        "hours_per_week": {"value": scalars["hours_per_week"][0], "source": scalars["hours_per_week"][1]},
        "goal": {"kind": kind, "value": goal[0], "source": goal[1]},
    }, []


def unknown_fields(inp):
    """The input fields whose value is unknown, by the names a result's `missing` list uses."""
    out = []
    for key in ("variable_costs", "fees_percent", "fixed_costs"):
        out += [f"{key}.{row['name']}" for row in inp[key] if row["value"] is None]
    for key in ("tax_percent", "hours_per_unit", "hours_per_new_unit", "hours_per_week", "goal"):
        if inp[key]["value"] is None:
            out.append(key)
    return out


def assumed_fields(inp):
    out = [f"prices[{i}]" for i, p in enumerate(inp["prices"]) if p["source"] == "assumed"]
    for key in ("variable_costs", "fees_percent", "fixed_costs"):
        out += [f"{key}.{row['name']}" for row in inp[key] if row["source"] == "assumed"]
    for key in ("tax_percent", "hours_per_unit", "hours_per_new_unit", "hours_per_week", "goal"):
        if inp[key]["source"] == "assumed":
            out.append(key)
    return out


def ceil_int(x):
    return int(math.ceil(round(x, 9)))


def compute(inp):
    unknown = set(unknown_fields(inp))
    group = {
        "var": [f"variable_costs.{r['name']}" for r in inp["variable_costs"]],
        "fee": [f"fees_percent.{r['name']}" for r in inp["fees_percent"]] + ["tax_percent"],
        "fixed": [f"fixed_costs.{r['name']}" for r in inp["fixed_costs"]],
    }
    var_total = sum(r["value"] or 0.0 for r in inp["variable_costs"])
    pct = sum(r["value"] or 0.0 for r in inp["fees_percent"]) + (inp["tax_percent"]["value"] or 0.0)
    fixed_total = sum(r["value"] or 0.0 for r in inp["fixed_costs"])
    recurring = inp["billing"] == "recurring"
    hpu = inp["hours_per_unit"]["value"]
    hpn = inp["hours_per_new_unit"]["value"]
    hpw = inp["hours_per_week"]["value"]
    goal = inp["goal"]
    results = []
    for price in inp["prices"]:
        p = price["value"]
        res, missing = {"price": round(p, 2)}, {}

        def put(key, needs, fn):
            gone = sorted(n for n in needs if n in unknown)
            if gone:
                res[key] = "unknown"
                missing[key] = gone
            else:
                res[key] = fn()

        fee_needs = group["fee"]
        nontax = group["fee"][:-1] + group["var"]
        fees_only = sum(r["value"] or 0.0 for r in inp["fees_percent"])
        contrib_needs = group["fee"] + group["var"]
        put("fee_and_tax_per_unit", fee_needs, lambda: round(p * pct / 100.0, 2))
        put("variable_cost_per_unit", group["var"], lambda: round(var_total, 2))
        put("contribution_per_unit", contrib_needs, lambda: round(p - p * pct / 100.0 - var_total, 2))
        put("contribution_margin_percent", contrib_needs,
            lambda: round((p - p * pct / 100.0 - var_total) / p * 100.0, 1))
        put("cost_floor_price", contrib_needs, lambda: round(var_total / (1 - pct / 100.0), 2))
        put("contribution_before_tax_per_unit", nontax,
            lambda: round(p - p * fees_only / 100.0 - var_total, 2))
        put("cost_floor_before_tax", nontax, lambda: round(var_total / (1 - fees_only / 100.0), 2))

        def cover():
            contribution = p - p * pct / 100.0 - var_total
            if contribution <= 1e-9:
                return "never"
            return ceil_int(fixed_total / contribution)
        put("units_to_cover_fixed", contrib_needs + group["fixed"], cover)

        def units():
            return ceil_int(goal["value"]) if goal["kind"] == "customers" else ceil_int(goal["value"] / p)
        put("units_for_goal", ["goal"], units)
        n = res["units_for_goal"]
        put("revenue_at_goal", ["goal"], lambda: round(n * p, 2))
        put("contribution_at_goal", ["goal"] + contrib_needs,
            lambda: round(n * (p - p * pct / 100.0 - var_total), 2))
        put("profit_at_goal", ["goal"] + contrib_needs + group["fixed"],
            lambda: round(n * (p - p * pct / 100.0 - var_total) - fixed_total, 2))
        put("hours_available_per_month", ["hours_per_week"], lambda: round(hpw * MONTH_WEEKS, 1))
        per_unit_needs = ["hours_per_unit"] if recurring else ["hours_per_unit", "hours_per_new_unit"]

        def per_unit_hours():
            return hpu if recurring else hpu + hpn
        put("hours_at_goal_per_month", ["goal"] + per_unit_needs, lambda: round(n * per_unit_hours(), 1))
        if recurring:
            put("onboarding_hours_total", ["goal", "hours_per_new_unit"], lambda: round(n * hpn, 1))

        def ceiling():
            per_unit = per_unit_hours()
            if per_unit <= 0:
                return "no hours limit"
            return int(math.floor(round(hpw * MONTH_WEEKS / per_unit, 9)))
        put("capacity_ceiling_units", ["hours_per_week"] + per_unit_needs, ceiling)
        put("goal_within_capacity", ["goal", "hours_per_week"] + per_unit_needs,
            lambda: round(n * per_unit_hours(), 9) <= round(hpw * MONTH_WEEKS, 9))
        res["missing"] = missing
        results.append(res)
    return results


def money(value, currency):
    return value if isinstance(value, str) else f"{value:.2f} {currency}"


def table(inp, results, label):
    cur = inp["currency"]
    recurring = inp["billing"] == "recurring"

    def sources(rows):
        found = sorted({r["source"] for r in rows})
        return ", ".join(found) if found else "none"
    fee_rows = inp["fees_percent"] + [dict(inp["tax_percent"], name="tax")]
    head = ["Metric"] + [f"Price {i + 1}" for i in range(len(results))] + ["From"]
    rows = [
        ("Price per " + inp["unit"], [money(r["price"], cur) for r in results],
         f"{label}; inputs: " + ", ".join(sorted({p['source'] for p in inp['prices']}))),
        ("Fees and tax per unit", [money(r["fee_and_tax_per_unit"], cur) for r in results],
         f"{label}; inputs: {sources(fee_rows)}"),
        ("Variable cost per unit", [money(r["variable_cost_per_unit"], cur) for r in results],
         f"{label}; inputs: {sources(inp['variable_costs'])}"),
        ("Contribution per unit", [money(r["contribution_per_unit"], cur) for r in results], label),
        ("Contribution margin", [r["contribution_margin_percent"] if isinstance(
            r["contribution_margin_percent"], str) else f"{r['contribution_margin_percent']:.1f}%"
            for r in results], label),
        ("Cost floor price (contribution zero)", [money(r["cost_floor_price"], cur) for r in results], label),
        ("Contribution per unit before tax", [money(r["contribution_before_tax_per_unit"], cur)
                                              for r in results], label),
        ("Cost floor price before tax", [money(r["cost_floor_before_tax"], cur) for r in results], label),
        ("Units to cover fixed costs", [str(r["units_to_cover_fixed"]) for r in results],
         f"{label}; inputs: {sources(inp['fixed_costs'])}"),
        ("Units for the goal", [str(r["units_for_goal"]) for r in results],
         f"{label}; inputs: {inp['goal']['source']}"),
        ("Revenue at the goal", [money(r["revenue_at_goal"], cur) for r in results], label),
        ("Contribution at the goal", [money(r["contribution_at_goal"], cur) for r in results], label),
        ("Profit at the goal (after fixed costs)", [money(r["profit_at_goal"], cur) for r in results], label),
        ("Hours available per month", [str(r["hours_available_per_month"]) for r in results],
         f"{label}; inputs: {inp['hours_per_week']['source']}"),
        ("Hours at the goal per month", [str(r["hours_at_goal_per_month"]) for r in results],
         f"{label}; inputs: {inp['hours_per_unit']['source']}"),
    ]
    if recurring:
        rows.append(("Onboarding hours in total (one time)", [str(r["onboarding_hours_total"]) for r in results],
                     f"{label}; inputs: {inp['hours_per_new_unit']['source']}"))
    rows.append(("Capacity ceiling (units per month)", [str(r["capacity_ceiling_units"]) for r in results], label))
    rows.append(("Goal within capacity", [("yes" if r["goal_within_capacity"] is True else
                                           "no" if r["goal_within_capacity"] is False else "unknown")
                                          for r in results], label))
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, cells, frm in rows:
        lines.append("| " + " | ".join([name] + cells + [frm]) + " |")
    assumed = assumed_fields(inp)
    last = "Assumed inputs: " + (", ".join(assumed) if assumed else "none")
    lines.append("| " + " | ".join([last] + [""] * (len(results) + 1)) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", metavar="PATH", help="read the JSON from this file instead of standard input")
    ap.add_argument("--label", default="M1", help="the command label shown in the From column (default M1)")
    args = ap.parse_args()
    if not SOURCE_NUMBER.match(args.label) or not args.label.startswith("M"):
        usage_error(f"--label must look like M1, M2; got {args.label!r}")
    try:
        raw = open(args.input, encoding="utf-8").read() if args.input else sys.stdin.read()
        data = json.loads(raw)
    except OSError as exc:
        usage_error(f"cannot read {args.input}: {exc}")
    except json.JSONDecodeError as exc:
        usage_error(f"the input is not valid JSON: {exc}")
    inp, findings = read_input(data)
    if findings:
        for f in findings:
            print(f"unit_economics.py: {f['field']}: {f['problem']}", file=sys.stderr)
        json.dump({"ok": False, "findings": findings}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        sys.exit(1)
    results = compute(inp)
    report = {"ok": True, "inputs": inp, "results": results, "assumed": assumed_fields(inp),
              "unknown": unknown_fields(inp), "table": table(inp, results, args.label)}
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
