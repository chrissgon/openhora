"""The outcome `question` in the interpreter's harness (package ANY-QUESTION Q0): the gold and the observed word, the scorer's matching and its nine rules over a question, the pipeline's
mapping of a decision of the kind, the counter of the questions that stole another gold, the corpus format's check of a question gold, the evidence validator's closed lists and the
report line. The oracle is this file's own literal lists. Offline: no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_question_scoring.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import standin_tree as st

score = st.load("interpreter_score")
pipeline = st.load("interpreter_pipeline")
measure = st.load("interpreter_measure")

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = json.loads((ROOT / "evals" / "interpreter" / "taxonomy.json").read_text(encoding="utf-8"))
CATALOG = ROOT / "runtime" / "interpreter_catalog.json"

SEVERITY = ["wrong_effect_unconfirmed", "wrong_card", "wrong_reminder_reading", "wrong_item_binding", "wrong_read", "wrong_route", "missed", "clarify", "correct"]
RULES = [      # the nine texts of the pin: the package adds no rule and no category
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

ASK_WHEN = {"outcome": "question", "about": "card", "field": "when"}
ASK_DONE_REMIND = {"outcome": "question", "about": "done", "op": "remind"}
ASK_DONE = {"outcome": "question", "about": "done"}
ASK_CAN = {"outcome": "question", "about": "can", "op": "mail-send"}
ASK_OTHER = {"outcome": "question", "about": "other"}
WHEN_SEEN = {"about": "card", "field": "when", "op": None}


def by_path(rel, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


lines_module = by_path("evals/evidence_lines.py", "workbench_evidence_lines_for_question")
corpus_format = by_path("scripts/interpreter_corpus_format.py", "workbench_corpus_format_for_question")


# 1 ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_taxonomy_ends_its_observed_words_with_question_and_keeps_its_severity_and_rules():
    assert TAXONOMY["observed"][-1] == "question" and TAXONOMY["observed"].count("question") == 1
    assert TAXONOMY["severity"] == SEVERITY
    assert score.rules_text() == RULES
    assert score.SEVERITY == tuple(SEVERITY) and score.OBSERVED[-1] == "question"


# 2 ---------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("gold, seen, expected", [
    (ASK_WHEN, WHEN_SEEN, True),
    (ASK_WHEN, {"about": "card", "field": "place", "op": None}, False),
    (ASK_WHEN, {"about": "done", "field": "when", "op": None}, False),
    (ASK_DONE_REMIND, {"about": "done", "field": None, "op": None}, False),
    (ASK_DONE, {"about": "done", "field": None, "op": None}, True),
    (ASK_DONE, {"about": "done", "field": None, "op": "remind"}, False),
    (ASK_CAN, {"about": "can", "field": None, "op": "mail-send"}, True),
    (ASK_OTHER, {"about": "other", "field": None, "op": None}, True),
])
def test_a_question_matches_when_about_field_and_op_are_equal(gold, seen, expected):
    assert score.matches(gold, "question", seen) is expected


# 3 ---------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("gold, also, observed, detail, expected", [
    (ASK_WHEN, [], "question", WHEN_SEEN, "correct"),
    (ASK_WHEN, [], "card", {"op": "event-change", "slots": {}}, "wrong_card"),
    (ASK_WHEN, [], "read", {"op": "items", "slots": {}}, "wrong_read"),
    (ASK_WHEN, [], "route", {}, "wrong_route"),
    (ASK_WHEN, [], "clarify", {}, "clarify"),
    (ASK_WHEN, [], "none", {}, "missed"),
    ({"outcome": "op", "op": "items", "slots": {}}, [], "question", {"about": "other", "field": None, "op": None}, "missed"),
    ({"outcome": "none"}, [], "question", {"about": "other", "field": None, "op": None}, "missed"),
    (ASK_DONE_REMIND, [{"outcome": "op", "op": "reminders", "slots": {}}], "read", {"op": "reminders", "slots": {}}, "correct"),
    (ASK_DONE_REMIND, [], "question", {"about": "done", "field": None, "op": "event-create"}, "missed"),
])
def test_a_question_gold_and_a_question_observed_fall_under_the_nine_rules_as_they_are(gold, also, observed, detail, expected):
    assert score.categorize(gold, also, "full", observed, detail) == expected


# 4 ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_pipeline_maps_a_question_decision_to_the_word_question_with_its_about_field_and_op():
    decision = {"kind": "question", "error": None, "about": "can", "field": None, "op": "mail-send"}
    assert pipeline.observe(decision) == ("question", {"about": "can", "field": None, "op": "mail-send"})
    assert pipeline.observe({"kind": "question", "error": None, "about": "card", "field": "to", "op": None}) == ("question", {"about": "card", "field": "to", "op": None})
    assert "question" in pipeline.OUTCOMES


# 5 ---------------------------------------------------------------------------------------------------------------------------------------------------

def row(item, gold, observed, category="missed", run=1):
    return {"item": item, "run": run, "lang": "en", "gold": gold, "category": category, "observed": observed, "parse": "none", "called": False, "latency_ms": None,
            "cost_usd": None, "error": None, "stage": "model", "why": None, "time_disagree": False}


THRESHOLDS = json.loads((ROOT / "evals" / "interpreter" / "thresholds.json").read_text(encoding="utf-8"))


def test_the_summary_counts_the_items_whose_gold_is_not_question_and_one_run_observed_question():
    rows = [row("a", "op", "question"), row("a", "op", "read", "correct", run=2),
            row("b", "none", "question"), row("b", "none", "question", run=2),
            row("c", "question", "question", "correct"), row("c", "question", "question", "correct", run=2)]
    assert score.summary(rows, THRESHOLDS)["question_on_other_golds"] == {"none": 1, "op": 1}
    quiet = [row("a", "op", "read", "correct"), row("c", "question", "question", "correct")]
    assert score.summary(quiet, THRESHOLDS)["question_on_other_golds"] == {}


# 6 ---------------------------------------------------------------------------------------------------------------------------------------------------

def an_item(gold):
    return {"id": "dev-en-62000", "split": "dev", "lang": "en", "hard": False, "clock": "2026-11-03T09:30", "zone": "America/New_York", "channel": "messaging",
            "forwarded": False, "frame": None, "line": "where is this event?", "gold": gold, "also": []}


GOOD_GOLDS = [ASK_WHEN, ASK_DONE, ASK_DONE_REMIND, {"outcome": "question", "about": "done", "op": "approve"}, ASK_CAN, ASK_OTHER]
BAD_GOLDS = [
    ("field on done", {"outcome": "question", "about": "done", "field": "when"}),
    ("op on card", {"outcome": "question", "about": "card", "field": "when", "op": "mail-send"}),
    ("card with no field", {"outcome": "question", "about": "card"}),
    ("can with no op", {"outcome": "question", "about": "can"}),
    ("op outside the catalog", {"outcome": "question", "about": "can", "op": "fly-to-moon"}),
    ("about weather", {"outcome": "question", "about": "weather"}),
    ("an extra key", {"outcome": "question", "about": "other", "span": ["x"]}),
    ("a scope", {"outcome": "question", "about": "other", "scope": "op"}),
    ("a field outside the eight", {"outcome": "question", "about": "card", "field": "colour"}),
    ("field on other", {"outcome": "question", "about": "other", "field": "when"}),
]


def test_the_item_form_and_the_corpus_format_accept_the_four_shapes_of_a_question_gold():
    cat = corpus_format.load_catalog(CATALOG)
    for gold in GOOD_GOLDS:
        assert pipeline.item_problems(an_item(gold)) == [], gold
        assert corpus_format.gold_problems(gold, an_item(gold), cat) == [], gold


@pytest.mark.parametrize("name, gold", BAD_GOLDS)
def test_the_corpus_format_refuses_a_question_gold_that_is_not_one_of_the_four_shapes(name, gold):
    cat = corpus_format.load_catalog(CATALOG)
    found = corpus_format.gold_problems(gold, an_item(gold), cat)
    assert found, name
    assert not any("moon" in text or "weather" in text for text in found), "a message never holds a value"


# 7 ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_evidence_validator_accepts_an_item_line_whose_gold_and_observed_are_question():
    line = {"record": "item", "test": "20261103T093000Z-0a1b2c3d", "item": "test-en-00001", "run": 1, "lang": "en", "hard": False, "gold": "question",
            "category": "correct", "observed": "question", "parse": "ok", "error": None, "time_source": None, "latency_ms": 800,
            "usage": {"input": 900, "output": 40, "cache_read": 0, "cache_write": 0}, "cost_usd": 0.001, "upstream": "hostone"}
    assert lines_module.interpreter_item_problems(line) == []
    assert lines_module.IX_OBSERVED[-1] == "question" and lines_module.IX_GOLDS[-1] == "question"
    assert list(lines_module.IX_OBSERVED) == TAXONOMY["observed"]


# 8 ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_text_report_prints_the_questions_that_stole_a_line():
    rows = [row("a", "op", "question"), row("b", "op", "question"), row("c", "question", "question", "correct")]
    result = score.summary(rows, THRESHOLDS)
    result["question_on_other_golds"] = {"op": 2}
    text = measure.text_report(result, {"test": "x"})
    assert 'question on other golds: {"op": 2}' in text.splitlines()


# 9 ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_vacuity_a_scorer_without_the_question_mapping_does_not_find_the_question_correct(monkeypatch):
    assert score.categorize(ASK_WHEN, [], "full", "question", WHEN_SEEN) == "correct"
    monkeypatch.setattr(score, "OUTCOME_OF", {k: v for k, v in score.OUTCOME_OF.items() if k != "question"})
    assert score.categorize(ASK_WHEN, [], "full", "question", WHEN_SEEN) != "correct"
