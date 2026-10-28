"""The gold overlay of CB-9 (OPEN-CB9-4): two golds files, `evals/interpreter/golds-catalog-v2-dev.jsonl` (for the frozen `dev.jsonl`) and `golds-catalog-v2-dev-long-v2.jsonl` (for `dev-long-v2.jsonl`),
each a full copy of its frozen corpus whose `also` is widened by one written rule: an item whose gold is `items {}` also accepts `items` with any non-empty subset of the slots `target`, `day`
and `state`, each a span of the line (every run of whole words of the line, edge punctuation stripped). The catalog of version 2 gives `items` three slots, and the frozen golds were written
when it had none, so an honest `items {day: "amanha"}` is not a wrong read. A file is applied at 0 calls with `interpreter_measure.py --replay <answers> --golds <file>` (a re-score, never evidence);
neither the scorer nor the pipeline is touched; the raw and the overlay figures are both published.

What is checked, with this test's own literals: each file holds the corpus's ids and, for each, every key but `gold` and `also` equal (the harness's own `load_golds` accepts it); exactly the
literal ids are widened, each with its own `also` kept first and seven alternatives after it, each an `items` op with a non-empty subset of the three slots and spans that are pieces of the line; every
other item is byte for byte the corpus item; both files pass the corpus tool's check; an honest `items {day}` is `correct` under the overlay and `wrong_read` under the raw gold, and a span that is
not in the line is not accepted. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_golds_overlay.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

import standin_tree as st

interpreter_measure = st.load("interpreter_measure")
score = st.load("interpreter_score")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
DEV_GOLDS = FOLDER / "golds-catalog-v2-dev.jsonl"          # evals/interpreter/golds-catalog-v2-dev.jsonl
LONG_GOLDS = FOLDER / "golds-catalog-v2-dev-long-v2.jsonl"          # evals/interpreter/golds-catalog-v2-dev-long-v2.jsonl
PAIRS = ((DEV_GOLDS, FOLDER / "dev.jsonl", ["dev-de-00012", "dev-fr-00002", "dev-fr-00015"], 310),
         (LONG_GOLDS, FOLDER / "dev-long-v2.jsonl", ["dev-de-50002", "dev-en-50005", "dev-en-50008", "dev-pt-br-50012", "dev-pt-br-50013", "dev-pt-br-50016"], 46))
SLOTS = {"target", "day", "state"}
SUBSETS = [{"target"}, {"day"}, {"state"}, {"target", "day"}, {"target", "state"}, {"day", "state"}, {"target", "day", "state"}]


def rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tool(name="interpreter_corpus"):
    spec = importlib.util.spec_from_file_location(f"{name}_golds_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("golds,corpus,widened,count", PAIRS)
def test_the_file_is_accepted_by_the_harness_and_holds_the_corpus_ids(golds, corpus, widened, count):
    items = rows(corpus)
    assert len(items) == count == len(rows(golds))
    got, sha = interpreter_measure.load_golds(str(golds), items)
    assert len(sha) == 64 and [i["id"] for i in got] == [i["id"] for i in items]


@pytest.mark.parametrize("golds,corpus,widened,count", PAIRS)
def test_exactly_the_items_whose_gold_is_items_with_no_slot_are_widened_and_nothing_else_changes(golds, corpus, widened, count):
    raw = {i["id"]: i for i in rows(corpus)}
    new = {i["id"]: i for i in rows(golds)}
    assert sorted(i for i, item in raw.items() if item["gold"].get("op") == "items" and item["gold"].get("slots") == {} and item["gold"].get("outcome") == "op") == widened
    for item_id, item in raw.items():
        if item_id not in widened:
            assert new[item_id] == item, f"{item_id} must be the corpus item byte for byte"
            continue
        mine = new[item_id]
        assert mine["gold"] == item["gold"] and {k: v for k, v in mine.items() if k != "also"} == {k: v for k, v in item.items() if k != "also"}
        assert mine["also"][:len(item["also"])] == item["also"], "the corpus item's own `also` stays first"
        extra = mine["also"][len(item["also"]):]
        assert len(extra) == 7
        assert [set(alt["slots"]) for alt in extra] == SUBSETS
        for alt in extra:
            assert set(alt) == {"op", "outcome", "slots"} and alt["op"] == "items" and alt["outcome"] == "op"
            for slot, spans in alt["slots"].items():
                assert slot in SLOTS and spans and len(set(spans)) == len(spans)
                assert all(s in item["line"] and s == s.strip() for s in spans), (item_id, slot)


@pytest.mark.parametrize("golds,corpus,widened,count", PAIRS)
def test_the_corpus_tool_finds_no_problem_in_the_file(golds, corpus, widened, count):
    catalog = tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")
    assert tool().check_items(rows(golds), catalog) == []


def read_of(slots):
    return {"op": "items", "slots": slots}


def test_an_honest_items_with_a_day_is_wrong_under_the_raw_gold_and_correct_under_the_overlay():
    raw = next(i for i in rows(FOLDER / "dev-long-v2.jsonl") if i["id"] == "dev-pt-br-50012")
    new = next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50012")
    assert raw["line"] == "me mostra o que tenho na agenda amanhã, por favor"      # validate: allow english-only -- the Portuguese line under test
    detail = read_of({"day": "amanhã"})      # validate: allow english-only -- the Portuguese line under test
    assert score.categorize(raw["gold"], raw["also"], "full", "read", detail) == "wrong_read"
    assert score.categorize(new["gold"], new["also"], "full", "read", detail) == "correct"
    both = read_of({"target": "agenda", "day": "amanhã"})      # validate: allow english-only -- the Portuguese line under test
    assert score.categorize(new["gold"], new["also"], "full", "read", both) == "correct"
    assert score.categorize(new["gold"], new["also"], "full", "read", read_of({})) == "correct", "the gold itself still holds"


def test_the_overlay_does_not_accept_a_span_that_is_not_in_the_line_or_a_slot_that_is_not_listed():
    new = next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50012")
    assert score.categorize(new["gold"], new["also"], "full", "read", read_of({"day": "sexta"})) == "wrong_read", "a day the line does not hold"
    assert score.categorize(new["gold"], new["also"], "full", "read", read_of({"place": "agenda"})) == "wrong_read", "a slot items does not have"
    other = next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50000")
    assert other["gold"]["op"] == "event-cancel"
    assert score.categorize(other["gold"], other["also"], "full", "read", read_of({"day": "amanhã"})) == "wrong_read", "an item that is not an items read is not widened"      # validate: allow english-only -- the Portuguese line under test


def test_the_checks_are_not_vacuous(tmp_path):
    items = rows(FOLDER / "dev-long-v2.jsonl")
    planted = [copy.deepcopy(i) for i in rows(LONG_GOLDS)]
    planted[0]["line"] = planted[0]["line"] + " x"          # a key but gold and also differs from the corpus
    path = tmp_path / "planted.jsonl"
    path.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for i in planted), encoding="utf-8")
    with pytest.raises(interpreter_measure.Refused):
        interpreter_measure.load_golds(str(path), items)
    short = tmp_path / "short.jsonl"
    short.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for i in rows(LONG_GOLDS)[1:]), encoding="utf-8")
    with pytest.raises(interpreter_measure.Refused):
        interpreter_measure.load_golds(str(short), items)
    outside = copy.deepcopy(next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50012"))
    outside["also"][-1]["slots"]["day"].append("nunca escrito na linha")          # a span that is not in the line
    assert any("not in the line" in p for p in tool().check_items([outside], tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")))
    assert re.fullmatch(r"[0-9a-f]{64}", interpreter_measure.load_golds(str(LONG_GOLDS), items)[1])
