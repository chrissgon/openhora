"""The scorer of the interpreter experiment (package IX-2c; runtime/interpreter_score.py): the nine rules of evals/interpreter/taxonomy.json as code. The oracle is this file's own
literal lists: the texts of the rules, a hand-written case for each rule and each matching clause, and the numbers the measures must give. Every example row of the taxonomy file
is run too, so that a re-freeze that changes a row is noticed. Planted faulty scorers (a rule removed, `also` ignored, a span compared where the gold has none) are built from the
module's own source and must each fail at least one case. Offline, no model; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_score.py
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

import standin_tree as st

score = st.load("interpreter_score")

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = json.loads((ROOT / "evals" / "interpreter" / "taxonomy.json").read_text(encoding="utf-8"))
THRESHOLDS = json.loads((ROOT / "evals" / "interpreter" / "thresholds.json").read_text(encoding="utf-8"))

RULES = [      # the taxonomy's nine rules, as the test holds them: a re-freeze that changes one is noticed here
    "executed -> wrong_effect_unconfirmed",
    "card or confirm not matching -> wrong_card",
    "remind_confirm not matching -> wrong_reminder_reading",
    "answer not matching, or gold answer with observed read or route -> wrong_item_binding",
    "read not matching -> wrong_read",
    "route with gold other than route -> wrong_route",
    "clarify with gold other than clarify -> clarify",
    "matching -> correct",
    "anything else (none, outage, refusals, forwarded on a non-forward, a clarify gold met by none) -> missed",
]
SEVERITY = ["wrong_effect_unconfirmed", "wrong_card", "wrong_reminder_reading", "wrong_item_binding", "wrong_read", "wrong_route", "missed", "clarify", "correct"]

REMIND = {"outcome": "op", "op": "remind", "slots": {"text": ["call Bob", "to call Bob"], "when": ["tomorrow at 9", "at 9"]}, "time": ["2026-10-23T09:00"]}
MAIL = {"outcome": "op", "op": "mail-send", "slots": {"to": ["ana@mail.example"], "subject": ["lunch"], "body": ["see you at noon"]}}
TRASH = {"outcome": "op", "op": "mail-trash", "slots": {"messages": ["3 4"]}}
TASK = {"outcome": "op", "op": "task", "slots": {"id": ["4"]}}
STATUS = {"outcome": "op", "op": "status", "slots": {}}
WHEN_ANSWER = {"outcome": "answer", "item": "i1", "slot": "when", "span": ["at 10"], "time": ["2026-10-23T10:00"]}
TIME_ONLY_ANSWER = {"outcome": "answer", "item": "i1", "slot": "when", "time": ["2026-10-23T13:00"]}
CLARIFY, ROUTE, NONE, FORWARDED = {"outcome": "clarify"}, {"outcome": "route"}, {"outcome": "none"}, {"outcome": "forwarded"}


def remind_seen(text="call Bob", when="tomorrow at 9", time="2026-10-23T09:00"):
    return {"op": "remind", "slots": {"text": text, "when": when}, "time": time}


# (id, gold, also, scope, observed, detail, expected category): written by hand, one reason each
CASES = [
    ("r1-executed-on-a-clarify-gold", CLARIFY, [], "full", "executed", {"op": "cancel", "slots": {"id": "7"}}, "wrong_effect_unconfirmed"),
    ("r1-executed-even-when-it-matches", STATUS, [], "full", "executed", {"op": "status", "slots": {}}, "wrong_effect_unconfirmed"),
    ("r2-card-other-recipient", MAIL, [], "full", "card", {"op": "mail-send", "slots": {"to": "bia@mail.example", "subject": "lunch", "body": "see you at noon"}}, "wrong_card"),
    ("r2-card-extra-slot", MAIL, [], "full", "card", {"op": "mail-send", "slots": {"to": "ana@mail.example", "subject": "lunch", "body": "see you at noon", "x": "y"}}, "wrong_card"),
    ("r2-card-missing-slot", MAIL, [], "full", "card", {"op": "mail-send", "slots": {"to": "ana@mail.example", "subject": "lunch"}}, "wrong_card"),
    ("r2-confirm-on-a-refuse-gold", {"outcome": "refuse", "class": "D"}, [], "full", "confirm", {"op": "cancel", "slots": {"id": "4"}}, "wrong_card"),
    ("r2-card-on-a-route-gold", ROUTE, [], "full", "card", {"op": "mail-send", "slots": {}}, "wrong_card"),
    ("r2-other-op", MAIL, [], "full", "card", {"op": "mail-draft", "slots": {"to": "ana@mail.example", "subject": "lunch", "body": "see you at noon"}}, "wrong_card"),
    ("r3-reminder-other-hour", REMIND, [], "full", "remind_confirm", remind_seen(time="2026-10-23T21:00"), "wrong_reminder_reading"),
    ("r3-reminder-other-words", REMIND, [], "full", "remind_confirm", remind_seen(text="call Rob"), "wrong_reminder_reading"),
    ("r3-reminder-on-a-clarify-gold", CLARIFY, [], "full", "remind_confirm", remind_seen(when="at 9"), "wrong_reminder_reading"),
    ("r3-reminder-with-no-time-where-the-gold-has-one", REMIND, [], "full", "remind_confirm", remind_seen(time=None), "wrong_reminder_reading"),
    ("r4-answer-other-option", {"outcome": "answer", "item": "i1", "option": 2}, [], "full", "answer", {"item": "i1", "option": 3}, "wrong_item_binding"),
    ("r4-answer-other-item", {"outcome": "answer", "item": "i1", "confirm": "yes"}, [], "full", "answer", {"item": "i2", "confirm": "yes"}, "wrong_item_binding"),
    ("r4-answer-on-an-op-gold", STATUS, [], "full", "answer", {"item": "i1", "confirm": "yes"}, "wrong_item_binding"),
    ("r4-gold-answer-met-by-route", WHEN_ANSWER, [], "full", "route", {}, "wrong_item_binding"),
    ("r4-gold-answer-met-by-read", WHEN_ANSWER, [], "full", "read", {"op": "status", "slots": {}}, "wrong_item_binding"),
    ("r5-read-other-id", TASK, [], "full", "read", {"op": "task", "slots": {"id": "5"}}, "wrong_read"),
    ("r5-read-on-a-clarify-gold", CLARIFY, [], "full", "read", {"op": "status", "slots": {}}, "wrong_read"),
    ("r5-read-other-op", STATUS, [], "full", "read", {"op": "costs", "slots": {}}, "wrong_read"),
    ("r6-route-on-an-op-gold", STATUS, [], "full", "route", {}, "wrong_route"),
    ("r6-route-on-a-clarify-gold", CLARIFY, [], "full", "route", {}, "wrong_route"),
    ("r6-route-on-a-refuse-gold", {"outcome": "refuse", "class": "G"}, [], "full", "route", {}, "wrong_route"),
    ("r7-clarify-on-an-op-gold", TASK, [], "full", "clarify", {"slot": "id"}, "clarify"),
    ("r7-clarify-on-a-route-gold", ROUTE, [], "full", "clarify", {"slot": "to"}, "clarify"),
    ("r8-read-correct", STATUS, [], "full", "read", {"op": "status", "slots": {}}, "correct"),
    ("r8-route-correct", ROUTE, [], "full", "route", {}, "correct"),
    ("r8-the-clarify-pair-is-correct", CLARIFY, [], "full", "clarify", {"slot": "when"}, "correct"),
    ("r8-the-clarify-pair-with-ops-is-correct", CLARIFY, [], "full", "clarify", {"ops": ["remind", "event-create"]}, "correct"),
    ("r8-none-correct", NONE, [], "full", "none", {}, "correct"),
    ("r8-forwarded-correct", FORWARDED, [], "full", "forwarded", {}, "correct"),
    ("r8-refuse-d-correct", {"outcome": "refuse", "class": "D"}, [], "full", "refuse_d", {"class": "D"}, "correct"),
    ("r8-refuse-g-correct", {"outcome": "refuse", "class": "G"}, [], "full", "refuse_g", {"class": "G"}, "correct"),
    ("r9-none-on-a-clarify-gold", CLARIFY, [], "full", "none", {}, "missed"),
    ("r9-outage", STATUS, [], "full", "outage", {}, "missed"),
    ("r9-forwarded-on-a-request", REMIND, [], "full", "forwarded", {}, "missed"),
    ("r9-refuse-d-on-a-g-gold", {"outcome": "refuse", "class": "G"}, [], "full", "refuse_d", {"class": "D"}, "missed"),
    ("r9-refuse-policy-matches-nothing", {"outcome": "refuse", "class": "G"}, [], "full", "refuse_policy", {"op": "give-consent"}, "missed"),
    ("r9-none-on-an-op-gold", STATUS, [], "full", "none", {}, "missed"),
    ("r9-refuse-on-an-op-gold", STATUS, [], "full", "refuse_g", {"class": "G"}, "missed"),
    # the matching clauses
    ("m-values-are-normal-equal-case-and-accents", REMIND, [], "full", "remind_confirm", remind_seen(text="  Call   BOB ", when="Tomorrow at 9"), "correct"),
    ("m-an-accepted-alternative-of-a-slot", REMIND, [], "full", "remind_confirm", remind_seen(text="to call Bob", when="at 9"), "correct"),
    ("m-accents-are-ignored", {"outcome": "op", "op": "remind", "slots": {"text": ["ligar para a avó"], "when": ["amanhã às 9"]}, "time": ["2026-10-23T09:00"]},  # validate: allow english-only -- a fictional Portuguese line or word, the input under test
     [], "full", "remind_confirm", remind_seen(text="ligar para a avo", when="amanha as 9"), "correct"),
    ("m-an-int-is-compared-as-a-number", TASK, [], "full", "read", {"op": "task", "slots": {"id": "04"}}, "correct"),
    ("m-an-int-that-is-not-a-number-is-not-equal", TASK, [], "full", "read", {"op": "task", "slots": {"id": "four"}}, "wrong_read"),
    ("m-ints-compared-as-lists", TRASH, [], "full", "card", {"op": "mail-trash", "slots": {"messages": "3,4"}}, "correct"),
    ("m-ints-order-matters", TRASH, [], "full", "card", {"op": "mail-trash", "slots": {"messages": "4,3"}}, "wrong_card"),
    ("m-a-time-the-gold-does-not-list", REMIND, [], "full", "remind_confirm", remind_seen(time="2026-10-23T09:30"), "wrong_reminder_reading"),
    ("m-a-time-where-the-gold-has-none", {"outcome": "op", "op": "event-create", "slots": {"title": ["dentist"], "time": ["friday at 3pm"]}},
     [], "full", "card", {"op": "event-create", "slots": {"title": "dentist", "time": "friday at 3pm"}, "time": "2026-10-23T15:00"}, "wrong_card"),
    ("m-same-slot-names-needed-not-a-subset", REMIND, [], "full", "remind_confirm", {"op": "remind", "slots": {"text": "call Bob"}, "time": "2026-10-23T09:00"}, "wrong_reminder_reading"),
    ("m-an-op-with-no-slots", {"outcome": "op", "op": "reminders", "slots": {}}, [], "full", "read", {"op": "reminders", "slots": {}}, "correct"),
    # also: alternative golds that also count
    ("a-an-also-op-counts", STATUS, [{"outcome": "op", "op": "progress", "slots": {}}], "full", "read", {"op": "progress", "slots": {}}, "correct"),
    ("a-an-also-clarify-counts", STATUS, [CLARIFY], "full", "clarify", {"slot": "id"}, "correct"),
    ("a-an-also-does-not-excuse-another-op", STATUS, [{"outcome": "op", "op": "progress", "slots": {}}], "full", "read", {"op": "costs", "slots": {}}, "wrong_read"),
    ("a-an-also-route-counts", ROUTE, [CLARIFY], "full", "clarify", {}, "correct"),
    ("a-an-also-answer-counts", {"outcome": "answer", "item": "i1", "option": 1}, [{"outcome": "answer", "item": "i1", "option": 2}], "full", "answer", {"item": "i1", "option": 2}, "correct"),
    # scopes: scope op judges the op alone
    ("s-op-scope-ignores-the-slots", {"outcome": "op", "op": "event-create", "scope": "op"}, [], "op", "card", {"op": "event-create", "slots": {"title": "x"}, "time": "2026-10-23T15:00"}, "correct"),
    ("s-op-scope-still-judges-the-op", {"outcome": "op", "op": "event-create", "scope": "op"}, [], "op", "card", {"op": "event-change", "slots": {}}, "wrong_card"),
    ("s-op-scope-of-a-route-gold-is-the-route", ROUTE, [], "op", "route", {}, "correct"),
    # answers: the key set, the time and the missing-span rule
    ("w-answer-with-span-and-time", WHEN_ANSWER, [], "full", "answer", {"item": "i1", "slot": "when", "span": "At 10", "time": "2026-10-23T10:00"}, "correct"),
    ("w-answer-other-time", WHEN_ANSWER, [], "full", "answer", {"item": "i1", "slot": "when", "span": "at 10", "time": "2026-10-23T11:00"}, "wrong_item_binding"),
    ("w-answer-other-span", WHEN_ANSWER, [], "full", "answer", {"item": "i1", "slot": "when", "span": "at 11", "time": "2026-10-23T10:00"}, "wrong_item_binding"),
    ("w-answer-with-an-extra-key", {"outcome": "answer", "item": "i1", "confirm": "yes"}, [], "full", "answer", {"item": "i1", "confirm": "yes", "slot": "when", "span": "x"}, "wrong_item_binding"),
    ("w-answer-with-a-missing-key", WHEN_ANSWER, [], "full", "answer", {"item": "i1", "slot": "when", "span": "at 10"}, "wrong_item_binding"),
    ("w-answer-confirm", {"outcome": "answer", "item": "i2", "confirm": "no"}, [], "full", "answer", {"item": "i2", "confirm": "no"}, "correct"),
    ("w-answer-confirm-other", {"outcome": "answer", "item": "i2", "confirm": "no"}, [], "full", "answer", {"item": "i2", "confirm": "yes"}, "wrong_item_binding"),
    ("w-missing-span-rule-the-observed-span-is-not-compared", TIME_ONLY_ANSWER, [], "full", "answer",
     {"item": "i1", "slot": "when", "span": "1pm", "time": "2026-10-23T13:00"}, "correct"),
    ("w-missing-span-rule-the-time-still-is", TIME_ONLY_ANSWER, [], "full", "answer",
     {"item": "i1", "slot": "when", "span": "1pm", "time": "2026-10-23T14:00"}, "wrong_item_binding"),
    ("w-missing-span-rule-without-a-span-observed", TIME_ONLY_ANSWER, [], "full", "answer", {"item": "i1", "slot": "when", "time": "2026-10-23T13:00"}, "correct"),
]


@pytest.mark.parametrize("name,gold,also,scope,observed,detail,expected", CASES, ids=[c[0] for c in CASES])
def test_each_case_gets_the_category_written_beside_it(name, gold, also, scope, observed, detail, expected):
    assert score.categorize(gold, also, scope, observed, detail) == expected


def test_the_taxonomy_rules_are_the_ones_this_scorer_was_written_for():
    assert [r["text"] for r in TAXONOMY["rules"]] == RULES, "the taxonomy was re-frozen: read the rules again and change the scorer and this list together"
    assert score.rules_text() == RULES
    assert list(score.SEVERITY) == SEVERITY and TAXONOMY["severity"] == SEVERITY


def test_there_are_at_least_two_hand_written_cases_for_each_rule():
    for prefix in ("r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9"):
        assert sum(1 for c in CASES if c[0].startswith(prefix + "-")) >= 2, prefix


def test_every_example_of_the_taxonomy_gets_its_category():
    examples = TAXONOMY["examples"]
    assert len(examples) >= 30
    for row in examples:
        assert score.categorize(row["gold"], row.get("also", []), row.get("scope", "full"), row["observed"], row["observed_detail"]) == row["category"], row
    assert {row["category"] for row in examples} == set(SEVERITY), "the examples reach every category"


def test_an_item_of_scope_time_is_not_categorized():
    with pytest.raises(ValueError):
        score.categorize(REMIND, [], "time", "remind_confirm", remind_seen())
    with pytest.raises(ValueError):
        score.categorize(REMIND, [], "full", "not-a-word", {})


# --- the time scope --------------------------------------------------------------------------------------------------------------------------------------

TIME_GOLD = {"outcome": "op", "op": None, "scope": "time", "time": ["2026-10-19T10:00"]}


@pytest.mark.parametrize("gold,also,observed,detail,expected", [
    (TIME_GOLD, [], "remind_confirm", {"op": "remind", "slots": {}, "time": "2026-10-19T10:00"}, "ok"),
    (TIME_GOLD, [], "card", {"op": "event-create", "slots": {}, "time": "2026-10-19T10:00"}, "ok"),
    (TIME_GOLD, [], "remind_confirm", {"op": "remind", "slots": {}, "time": "2026-10-19T22:00"}, "wrong"),
    (TIME_GOLD, [], "remind_confirm", {"op": "remind", "slots": {}, "time": None}, "wrong"),
    (TIME_GOLD, [], "clarify", {"slot": "when"}, "asked"),
    (TIME_GOLD, [], "route", {}, "wrong"),
    ({"outcome": "clarify", "scope": "time"}, [], "clarify", {}, "ok"),
    ({"outcome": "clarify", "scope": "time"}, [], "remind_confirm", {"op": "remind", "slots": {}, "time": "2026-10-19T09:00"}, "wrong"),
    (TIME_GOLD, [{"outcome": "op", "op": None, "scope": "time", "time": ["2026-10-19T11:00"]}], "remind_confirm", {"op": "remind", "slots": {}, "time": "2026-10-19T11:00"}, "ok"),
])
def test_the_time_scope_is_judged_by_the_time_alone(gold, also, observed, detail, expected):
    assert score.time_result(gold, also, observed, detail) == expected


# --- the measures ----------------------------------------------------------------------------------------------------------------------------------------

def row(item, category, gold="op", lang="en", **more):
    base = {"item": item, "run": 1, "lang": lang, "gold": gold, "category": category, "observed": "read", "parse": "none", "called": False, "latency_ms": None,
            "cost_usd": None, "error": None, "stage": "model", "why": None, "time_disagree": False}
    base.update(more)
    return base


def test_the_worst_of_the_runs_of_an_item_is_the_one_that_counts():
    rows = [row("a", "correct"), row("a", "wrong_read", run=2), row("b", "clarify"), row("b", "correct", run=2), row("c", "missed"), row("c", "missed", run=2)]
    worst = score.worst_of_runs(rows)
    assert {k: v["category"] for k, v in worst.items()} == {"a": "wrong_read", "b": "clarify", "c": "missed"}
    assert worst["a"]["run"] == 2


def test_the_measures_use_the_denominators_of_the_taxonomy():
    rows = ([row(f"c{n}", "correct") for n in range(6)] + [row("k1", "correct", gold="clarify"), row("k2", "clarify", gold="op"), row("k3", "wrong_card"),
                                                          row("k4", "wrong_read"), row("k5", "missed", gold="clarify")])
    m = score.measures(rows, 1.96)
    assert m["n"] == 11 and m["direct"] == 9, "two golds are clarifications"
    assert m["correct_direct"] == pytest.approx(6 / 9) and m["clarify_rate"] == pytest.approx(1 / 9)
    assert m["counts"]["wrong_card"] == 1 and m["rate"]["wrong_card"] == pytest.approx(1 / 11)
    assert m["wilson"]["wrong_item_binding"] == pytest.approx(score.wilson_upper(0, 11, 1.96))
    assert score.measures([], 1.96)["correct_direct"] is None


def test_the_wilson_upper_bound_is_the_published_one():
    assert score.wilson_upper(0, 800) == pytest.approx(0.004779, abs=5e-7)
    assert score.wilson_upper(16, 800) == pytest.approx(0.032240, abs=5e-7)
    assert score.wilson_upper(3, 100) == pytest.approx(0.084521, abs=5e-7)
    assert score.wilson_upper(0, 0) == 1.0


def test_the_percentile_and_the_median():
    assert score.p95(list(range(1, 101))) == 95 and score.p95([7]) == 7 and score.p95([]) is None
    assert score.p95([10, 20, 30]) == 30, "of fewer than 20 values the 95th percentile is the maximum"
    assert score.median([3, 1, 2]) == 2 and score.median([1, 2, 3, 4]) == 2.5 and score.median([]) is None


def test_the_summary_counts_what_the_harness_prints():
    rows = [row("a", "correct", called=True, parse="ok", latency_ms=900, cost_usd=0.001, stage="model"),
            row("b", "wrong_route", called=True, parse="invalid", latency_ms=1500, cost_usd=0.003, stage="model", why="invalid"),
            row("c", "correct", called=False, parse="none", stage="tier1"),
            row("d", "missed", called=True, parse="none", latency_ms=6000, observed="outage", error="E_TIMEOUT", stage="model"),
            row("e", "clarify", called=True, parse="ok", latency_ms=700, cost_usd=0.002, stage="model", why="private-route", time_disagree=True, lang="pt-BR")]
    live = score.summary(rows, THRESHOLDS, sequential=False, time_rows=["ok", "wrong", "ok"])
    seq = score.summary(rows, THRESHOLDS, sequential=True, time_rows=[])
    assert live["items"] == 5 and live["calls"] == 4 and live["p95_latency_ms"] is None and live["median_cost_usd"] is None, "latency and cost are read from sequential events only"
    assert seq["p95_latency_ms"] == 6000 and seq["median_cost_usd"] == pytest.approx(0.002)
    assert seq["parse_failure_rate"] == pytest.approx(1 / 3), "of the three calls the model answered, one did not parse (the failed call has no answer)"
    assert seq["wrong_route_cost_usd"] == pytest.approx(THRESHOLDS["router_line_cost_usd"])
    assert seq["stages"] == {"model": 4, "tier1": 1} and seq["errors"] == {"E_TIMEOUT": 1}
    assert seq["private_route"] == 1 and seq["time_disagree"] == 1 and live["scope_time"] == {"ok": 2, "wrong": 1}
    assert set(seq["by_language"]) == {"en", "pt-BR"} and seq["by_language"]["pt-BR"]["n"] == 1


# --- vacuity: a planted wrong scorer is caught ----------------------------------------------------------------------------------------------------------

SOURCE = (Path(score.__file__)).read_text(encoding="utf-8")


def mutant(old, new):
    """The scorer's own source with one line changed, as a module of its own (the replaced text must occur exactly once, so that a mutation cannot silently do nothing)."""
    assert SOURCE.count(old) == 1, old
    module = types.ModuleType("interpreter_score_planted")
    module.__file__ = score.__file__
    exec(compile(SOURCE.replace(old, new), score.__file__, "exec"), module.__dict__)  # security-scan: allow dynamic-eval -- the scorer's own source with one planted fault, compiled by a test to prove the cases catch it
    return module


def failures(module):
    return [c[0] for c in CASES if module.categorize(c[1], c[2], c[3], c[4], c[5]) != c[6]]


def test_the_unplanted_scorer_fails_no_case():
    assert failures(mutant("RANK = ", "RANK = ")) == []


def test_a_scorer_without_rule_two_is_caught():
    bad = failures(mutant('if observed in ("card", "confirm") and not ok:', "if False:"))
    assert "r2-card-other-recipient" in bad and "r2-confirm-on-a-refuse-gold" in bad, bad


def test_a_scorer_that_ignores_also_is_caught():
    bad = failures(mutant("ok = any(matches(g, observed, detail, scope) for g in [gold] + _list(also))", "ok = matches(gold, observed, detail, scope)"))
    assert "a-an-also-op-counts" in bad and "a-an-also-clarify-counts" in bad, bad


def test_a_scorer_that_compares_a_span_the_gold_does_not_have_is_caught():
    bad = failures(mutant('if "slot" in gold and "span" not in gold:', "if False:"))
    assert "w-missing-span-rule-the-observed-span-is-not-compared" in bad, bad


def test_a_scorer_that_lets_a_clarify_gold_met_by_a_clarification_fall_to_clarify_is_caught():
    bad = failures(mutant('if observed == "clarify" and not ok:\n        return "clarify"', 'if observed == "clarify":\n        return "clarify"'))
    assert "r8-the-clarify-pair-is-correct" in bad
