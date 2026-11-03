"""The question dev arm of the interpreter experiment (package ANY-QUESTION Q2): `evals/interpreter/question-dev-v1.jsonl`, 50 fictional lines written by the specification (not labelled blind), the lines
the outcome `question` is meant for with their confusables. It is dev evidence, never the gate's split, and a NEW file: the frozen corpora and the other dev files are not touched. No blind set of this
measurement is in the repository, and this test does not read one.

What it holds, each oracle with this test's own literals: the file is canonical (the bytes the corpus tool writes) and sorted; the ids are unique, in the 62000 range and carry their language; the counts by
language and by kind of line (the four things a question is about, an existing operation, a greeting that stays none) and by operation are literals; every gold passes the corpus tool's own check (spans
pieces of their line, ops of the served catalog, the question shape of Q0.1); no line is claimed by stages 0 to 3 (code), so every line reaches the model; no line is a line of another set and no line
holds an address or a phone-like run; an echo model that answers each gold is `correct` on every item. Offline, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_question_dev_set.py
"""
from __future__ import annotations

import collections
import copy
import importlib.util
import json
import re
from pathlib import Path

import standin_tree as st
from test_interpreter_echo import run as echo_run

interpreter_measure = st.load("interpreter_measure")
interpreter_pipeline = st.load("interpreter_pipeline")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
FILE = FOLDER / "question-dev-v1.jsonl"      # evals/interpreter/question-dev-v1.jsonl, named literally so the test selector picks this test when the file changes
CARD_SET = "card-question-dev-v1.jsonl"      # the one set the lines of this file may repeat (the card arm of the same measurement)

IDS_BY_LANG = {"pt-BR": "dev-pt-br-62", "en": "dev-en-62", "es": "dev-es-62", "fr": "dev-fr-62", "de": "dev-de-62", "it": "dev-it-62"}
ZONES = {"pt-BR": "America/Sao_Paulo", "en": "America/New_York", "es": "Europe/Madrid", "fr": "Europe/Paris", "de": "Europe/Berlin", "it": "Europe/Rome"}
LANG_COUNTS = {"pt-BR": 24, "en": 14, "es": 3, "fr": 3, "de": 3, "it": 3}
KIND_COUNTS = {"question/card": 8, "question/done": 10, "question/can": 8, "question/other": 6, "op": 14, "none": 4}
OP_COUNTS = {"items": 3, "research": 3, "reminders": 2, "file-ask": 2, "todo-list": 2, "pending": 1, "mail-ask": 1}
CLOCK = "2026-11-03T09:30"      # a Tuesday, as the other dev files


def tool(name="interpreter_corpus"):
    """A file of the tooling (scripts/ is loaded by path, never imported from runtime/ code)."""
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normal(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def kind_of(item) -> str:
    gold = item["gold"]
    if gold["outcome"] == "question":
        return "question/" + gold["about"]
    return "op" if gold["outcome"] == "op" else gold["outcome"]


ITEMS = rows(FILE)
CATALOG = tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")


def test_the_file_is_canonical_sorted_and_loads_in_the_harness():
    raw = FILE.read_text(encoding="utf-8")
    assert raw.endswith("\n") and "\r" not in raw
    lines = raw.split("\n")[:-1]
    assert len(lines) == 50 == len(ITEMS)
    assert lines == [canon(item) for item in ITEMS], "every line is the canonical JSON of its item"
    ids = [item["id"] for item in ITEMS]
    assert ids == sorted(ids) and len(set(ids)) == 50
    for item in ITEMS:
        assert re.fullmatch(r"dev-(pt-br|en|es|fr|de|it)-62[0-9]{3}", item["id"]), item["id"]
        assert item["id"].startswith(IDS_BY_LANG[item["lang"]]), item["id"]
    loaded, data = interpreter_measure.load_corpus(str(FILE))
    assert len(loaded) == 50 and data == FILE.read_bytes()


def test_every_item_is_a_dev_line_with_the_clock_of_the_spec_and_the_zone_of_its_language():
    for item in ITEMS:
        assert item["split"] == "dev" and item["channel"] == "messaging" and item["author"] == "opus"
        assert item["forwarded"] is False and item["frame"] is None and item["tags"] == [] and item["hard"] is False
        assert item["clock"] == CLOCK, item["id"]
        assert item["zone"] == ZONES[item["lang"]], item["id"]


def test_the_counts_by_language_by_kind_of_line_and_by_operation_are_literals():
    assert dict(collections.Counter(item["lang"] for item in ITEMS)) == LANG_COUNTS
    assert dict(collections.Counter(kind_of(item) for item in ITEMS)) == KIND_COUNTS
    assert dict(collections.Counter(item["gold"]["op"] for item in ITEMS if item["gold"]["outcome"] == "op")) == OP_COUNTS
    assert sum(LANG_COUNTS.values()) == sum(KIND_COUNTS.values()) == sum(OP_COUNTS.values()) + 36 == 50
    for about in ("card", "done", "can", "other"):
        langs = {item["lang"] for item in ITEMS if item["gold"]["outcome"] == "question" and item["gold"]["about"] == about}
        assert {"pt-BR", "en"} <= langs, f"a question about {about} in Portuguese and in English"


def test_every_item_passes_both_item_checks():
    for item in ITEMS:
        assert interpreter_pipeline.item_problems(item) == [], item["id"]
    assert tool().check_items(ITEMS, CATALOG) == []


def test_no_line_is_claimed_by_stages_0_to_3_so_every_line_reaches_the_model():
    assert [item["id"] for item in ITEMS if interpreter_pipeline.pre_model(item) is not None] == []


def test_the_lines_are_new_and_hold_no_address_and_no_phone_like_run():
    others = {normal(item["line"]) for path in sorted(FOLDER.glob("*.jsonl")) if path.name not in (FILE.name, CARD_SET) for item in rows(path)}
    lines = [normal(item["line"]) for item in ITEMS]
    assert len(set(lines)) == 50
    assert not others & set(lines), "no line of another set but the card arm of this measurement"
    for item in ITEMS:
        text = item["line"]
        assert "@" not in text and "http" not in text and ".com" not in text and ".br" not in text, item["id"]
        assert not re.search(r"[0-9]{8,}", text.replace(" ", "").replace("-", "")), item["id"]


def test_an_echo_model_is_correct_on_every_item():
    off = {item["id"]: echo_run(item) for item in ITEMS if echo_run(item)[0] != "correct"}
    assert off == {}, off


def test_vacuity_a_planted_wrong_gold_or_line_is_found():
    tooling = tool()
    done = next(item for item in ITEMS if item["gold"]["outcome"] == "question" and item["gold"]["about"] == "done")
    assert tooling.check_items([done], CATALOG) == []
    field = copy.deepcopy(done)
    field["gold"]["field"] = "when"          # a field belongs to a question about the card only
    assert tooling.check_items([field], CATALOG) != []
    moon = next(item for item in ITEMS if item["gold"]["outcome"] == "op")
    assert tooling.check_items([moon], CATALOG) == []
    flown = copy.deepcopy(moon)
    flown["gold"]["op"] = "fly-to-moon"          # not an op of the served catalog
    assert tooling.check_items([flown], CATALOG) != []
    spanned = next(item for item in ITEMS if item["gold"]["outcome"] == "op" and item["gold"]["slots"])
    assert tooling.check_items([spanned], CATALOG) == []
    planted = copy.deepcopy(spanned)
    slot = next(iter(planted["gold"]["slots"]))
    planted["gold"]["slots"][slot] = ["zorvald"]          # not a piece of the line
    assert any("not in the line" in problem for problem in tooling.check_items([planted], CATALOG))
    claimed = copy.deepcopy(moon)
    claimed["line"] = "/status"          # a typed command is stage 3 (code), not the model's
    assert interpreter_pipeline.pre_model(claimed) is not None
