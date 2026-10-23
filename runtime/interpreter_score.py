#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The scorer of the interpreter experiment (package IX-2c): the rules of evals/interpreter/taxonomy.json as code, and the measures of a run.

Pure: nothing is called, stored or printed here. The taxonomy and the thresholds are read as data (evals/interpreter/*.json); the pipeline that produced the
`observed` word and its `detail` is not this module's business (runtime/interpreter_pipeline.py for the interpreter, the current-pipeline test for today's code):
both arms are scored by the same function, so that a comparison between them is a comparison of the pipelines and never of two scorers.

  categorize(gold, also, scope, observed, detail)   the category of one run of one item: the first rule of the taxonomy that applies
  matches(gold, observed, detail, scope="full")     whether what the pipeline did is what one gold says (the taxonomy's "matching")
  time_result(gold, also, observed, detail)         "ok" | "wrong" | "asked" for an item of scope `time` (the time reading alone; such an item writes no line)
  worst_of_runs(rows)                               {item: the row of its worst category} (taxonomy severity order)
  measures(rows, z)                                 counts, rates, Wilson upper bounds, correct_direct and the clarify rate of rows that are one per item
  summary(rows, thresholds, ...)                    everything the harness prints: overall and per-language measures, parse failures, p95 latency, median cost, counters

`detail` is {"op", "slots": {slot: span}, "time": "YYYY-MM-DDTHH:MM" | None} for an operation, {"item", "option", "confirm", "slot", "span", "time"} (the keys that
apply) for an answer, {"class"} for a refusal, {"slot"} or {"ops"} for a clarification and {} otherwise.

The bands and the go decision are computed only by `python3 evals/eval_status.py interpreter --go` (package IX-E); the summary here is a convenience.
Python 3.9, standard library only. `python3 runtime/interpreter_score.py --help` prints this text.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import natural  # noqa: E402  (the same folder: `normal`, the rule a text is compared by, and the slot kinds of the table)

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "evals", "interpreter")
TAXONOMY_FILE = os.path.join(DATA, "taxonomy.json")
THRESHOLDS_FILE = os.path.join(DATA, "thresholds.json")


def _read(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


TAXONOMY = _read(TAXONOMY_FILE)
SEVERITY = tuple(TAXONOMY["severity"])
OBSERVED = tuple(TAXONOMY["observed"])
WRONG = ("wrong_card", "wrong_read", "wrong_reminder_reading", "wrong_item_binding")      # the four whose bound the thresholds name
RANK = {name: n for n, name in enumerate(SEVERITY)}

# What the pipeline did, as the outcome word of a gold that can match it.
OUTCOME_OF = {"card": "op", "confirm": "op", "remind_confirm": "op", "read": "op", "executed": "op", "answer": "answer", "clarify": "clarify",
              "route": "route", "none": "none", "forwarded": "forwarded", "refuse_d": "refuse", "refuse_g": "refuse"}
CLASS_OF_REFUSAL = {"refuse_d": "D", "refuse_g": "G"}
ANSWER_KEYS = ("option", "confirm", "slot", "span", "time")


def rules_text() -> list:
    """The texts of the taxonomy's nine rules, in order (a test keeps them equal to its own literal list, so that a re-freeze is noticed)."""
    return [rule["text"] for rule in TAXONOMY["rules"]]


# --- matching ---------------------------------------------------------------------------------------------------------------------------------------------

def _list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _ints(text) -> list:
    return [int(n) for n in re.findall(r"[0-9]+", unicodedata.normalize("NFKC", str(text)))]


def _same_value(kind: str, observed, accepted) -> bool:
    """Whether an observed slot value is an accepted one: numbers as numbers, the rest by `natural.normal`."""
    if kind in ("int", "ints"):
        got = sorted(set(_ints(observed)))          # a list of numbers is a set: order and repeats do not matter
        return bool(got) and got == sorted(set(_ints(accepted)))
    return natural.normal(observed) == natural.normal(accepted) and natural.normal(accepted) != ""


def _op_matches(gold: dict, detail: dict, scope: str) -> bool:
    if gold.get("op") != detail.get("op"):
        return False
    if scope == "op":
        return True
    wanted, seen = gold.get("slots") or {}, detail.get("slots") or {}
    if set(wanted) != set(seen):
        return False
    row = natural.NATURAL.get(gold.get("op"), {}).get("slots", {})
    for slot, accepted in wanted.items():
        kind = row.get(slot, ("span",))[0]
        if not any(_same_value(kind, seen[slot], a) for a in _list(accepted)):
            return False
    if gold.get("time") or detail.get("time"):
        return detail.get("time") in _list(gold.get("time"))
    return True


def _answer_matches(gold: dict, detail: dict) -> bool:
    if gold.get("item") != detail.get("item"):
        return False
    wanted = {k for k in ANSWER_KEYS if k in gold}
    seen = {k for k in ANSWER_KEYS if detail.get(k) is not None}
    if "slot" in gold and "span" not in gold:
        seen.discard("span")          # a relabelled time-only answer has no span: the span is not compared
    if wanted != seen:
        return False
    for key in ("option", "confirm", "slot"):
        if key in wanted and gold[key] != detail[key]:
            return False
    if "span" in wanted and not any(natural.normal(detail["span"]) == natural.normal(a) != "" for a in _list(gold["span"])):
        return False
    if "time" in wanted and detail["time"] not in _list(gold["time"]):
        return False
    return True


def matches(gold: dict, observed: str, detail: dict, scope: str = "full") -> bool:
    """Whether what the pipeline did (`observed`, `detail`) is what `gold` says: equal outcome and, by outcome, the operation with its slots and time, the answer's item
    and keys, the refusal's class. `refuse_policy` and `outage` match nothing."""
    outcome = OUTCOME_OF.get(observed)
    if outcome is None or gold.get("outcome") != outcome:
        return False
    detail = detail or {}
    if outcome == "op":
        return _op_matches(gold, detail, scope)
    if outcome == "answer":
        return _answer_matches(gold, detail)
    if outcome == "refuse":
        return gold.get("class") == CLASS_OF_REFUSAL[observed]
    return True          # clarify, route, none, forwarded: equal outcome (a clarification's informational slot or ops is not scored)


def categorize(gold: dict, also, scope: str, observed: str, detail: dict) -> str:
    """The category of one run: the first rule of the taxonomy that applies (their texts: `rules_text`). `scope` is "full" or "op"; an item of scope `time` is not
    categorized (`time_result`)."""
    if scope == "time":
        raise ValueError("an item of scope time is scored by time_result")
    if observed not in OBSERVED:
        raise ValueError("not an observed word")
    if observed == "executed":
        return "wrong_effect_unconfirmed"
    ok = any(matches(g, observed, detail, scope) for g in [gold] + _list(also))
    if observed in ("card", "confirm") and not ok:
        return "wrong_card"
    if observed == "remind_confirm" and not ok:
        return "wrong_reminder_reading"
    if (observed == "answer" or (gold.get("outcome") == "answer" and observed in ("read", "route"))) and not ok:
        return "wrong_item_binding"
    if observed == "read" and not ok:
        return "wrong_read"
    if observed == "route" and not ok:
        return "wrong_route"
    if observed == "clarify" and not ok:
        return "clarify"
    return "correct" if ok else "missed"


def time_result(gold: dict, also, observed: str, detail: dict) -> str:
    """The result of an item of scope `time` (a relabelled reminder line whose gold is the time alone): "ok" when the time the pipeline read is one the gold lists (or, for
    a gold that asks, when it asked), "asked" when it asked and the gold has a time, "wrong" otherwise. Nothing else of the run is judged."""
    golds = [gold] + _list(also)
    asks = any(g.get("outcome") == "clarify" for g in golds)
    if observed == "clarify":
        return "ok" if asks else "asked"
    if asks:
        return "wrong"
    seen = (detail or {}).get("time")
    return "ok" if seen is not None and any(seen in _list(g.get("time")) for g in golds) else "wrong"


# --- the measures -------------------------------------------------------------------------------------------------------------------------------------------

def worst_of_runs(rows) -> dict:
    """{item id: the row of its worst category} (the first run of the worst category)."""
    worst = {}
    for row in rows:
        held = worst.get(row["item"])
        if held is None or RANK[row["category"]] < RANK[held["category"]]:
            worst[row["item"]] = row
    return worst


def wilson_upper(k: int, n: int, z: float = 1.96) -> float:
    """The upper end of the Wilson score interval of k out of n at z."""
    if n <= 0:
        return 1.0
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def p95(values):
    """The nearest-rank 95th percentile, or None for no value."""
    ordered = sorted(values)
    return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)] if ordered else None


def median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def measures(rows, z: float = 1.96) -> dict:
    """The measures of rows that are one per item (the worst run): counts per category, `rate` of the four bounded categories, their Wilson upper bound at z,
    `correct_direct` and `clarify_rate` (their denominators leave out the items whose gold is a clarification)."""
    counts = {c: 0 for c in SEVERITY}
    for row in rows:
        counts[row["category"]] += 1
    n = len(rows)
    direct = n - sum(1 for row in rows if row["gold"] == "clarify")
    correct_direct = sum(1 for row in rows if row["category"] == "correct" and row["gold"] != "clarify")
    return {"n": n, "counts": counts, "direct": direct,
            "rate": {c: (counts[c] / n if n else None) for c in WRONG},
            "wilson": {c: wilson_upper(counts[c], n, z) for c in WRONG},
            "correct_direct": (correct_direct / direct if direct else None),
            "clarify_rate": (counts["clarify"] / direct if direct else None)}


def summary(rows, thresholds: dict, sequential: bool = False, time_rows=(), extra=None) -> dict:
    """Everything the harness prints for a run. `rows` are the scored runs, one dict per (item, run): item, lang, gold (the outcome word), category, observed, parse,
    called, latency_ms, cost_usd, error, stage, why, time_disagree. `time_rows` are the results of the items of scope time. The latency and the cost are read from the
    runs of a sequential event only (one call at a time); in any other run they are null."""
    z = thresholds["wilson_z"]
    worst = list(worst_of_runs(rows).values())
    calls = [row for row in rows if row["called"]]
    answered = [row for row in calls if row["parse"] != "none"]          # the calls the model answered: a failed call has no answer to parse
    seq = calls if sequential else []
    out = {"items": len(worst), "runs": len(rows), "measures": measures(worst, z),
           "by_language": {lang: measures([row for row in worst if row["lang"] == lang], z) for lang in sorted({row["lang"] for row in worst})},
           "parse_failure_rate": (sum(1 for row in answered if row["parse"] == "invalid") / len(answered) if answered else None),
           "calls": len(calls), "p95_latency_ms": p95([row["latency_ms"] for row in seq if row["latency_ms"] is not None]),
           "median_cost_usd": median([row["cost_usd"] for row in seq if row["cost_usd"] is not None]),
           "wrong_route_cost_usd": sum(1 for row in worst if row["category"] == "wrong_route") * thresholds["router_line_cost_usd"],
           "stages": _count(row["stage"] for row in rows), "observed": _count(row["observed"] for row in rows),
           "errors": _count(row["error"] for row in rows if row["error"]),
           "time_disagree": sum(1 for row in rows if row.get("time_disagree")),
           "private_route": sum(1 for row in rows if row.get("why") == "private-route"),
           "scope_time": _count(time_rows)}
    out.update(extra or {})
    return out


def _count(values) -> dict:
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
