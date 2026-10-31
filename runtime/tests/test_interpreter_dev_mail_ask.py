"""The dev arm of the flip to catalog version 3 (package MAIL-SUMMARY-FLIP): `evals/interpreter/dev-mail-ask-v1.jsonl`, 24 fictional lines written by the executor of the flip (not by the author of any `about`
text), the lines the row `mail-ask` is meant for with their confusables. It is dev evidence, never blind, and a NEW file: the frozen corpora and the dev file of CB-9 are not touched. The blind set of the
same measurement (12 lines by an isolated author, frozen before the figure) is never in the repository, and this test does not read it.

What it holds, each oracle with this test's own literals: the file is canonical (the bytes the corpus tool writes) and sorted; the ids are unique, in the 61000 range and carry their language; every gold op
and slot is a served op and slot of catalog version 3 and every span is a piece of its line; the counts by language, by operation and by kind of line are literals; no line is a line of a frozen set and no
line holds an address or a phone-like run; no line is claimed by stages 0 to 3 (code), so every line reaches the model; an echo model that answers each gold is `correct` on every item. Offline, no model, no
network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_dev_mail_ask.py
"""
from __future__ import annotations

import collections
import copy
import importlib.util
import json
import re
from pathlib import Path

import standin_tree as st
from test_interpreter_echo import Echo, run as echo_run

interpreter = st.load("interpreter")
natural = st.load("natural")
natural_writes_mail = st.load("natural_writes_mail")
ops_mail_read = st.load("ops_mail_read")
interpreter_measure = st.load("interpreter_measure")
interpreter_pipeline = st.load("interpreter_pipeline")
operations = st.load("operations")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
FILE = FOLDER / "dev-mail-ask-v1.jsonl"      # evals/interpreter/dev-mail-ask-v1.jsonl, named literally so the test selector picks this test when the file changes
FROZEN = ("dev.jsonl", "dev-relabelled.jsonl", "ix-test-v1.jsonl", "dev-long-v1.jsonl", "dev-long-v2.jsonl", "blite-blind-v2.jsonl", "dev-catalog-v1.jsonl")

IDS_BY_LANG = {"pt-BR": "dev-pt-br-61", "en": "dev-en-61", "es": "dev-es-61", "fr": "dev-fr-61", "de": "dev-de-61", "it": "dev-it-61"}
ZONES = {"pt-BR": "America/Sao_Paulo", "en": "America/New_York", "es": "Europe/Madrid", "fr": "Europe/Paris", "de": "Europe/Berlin", "it": "Europe/Rome"}
LANG_COUNTS = {"de": 1, "en": 6, "es": 1, "fr": 1, "it": 1, "pt-BR": 14}
OP_COUNTS = {"ask": 1, "items": 1, "mail-ask": 19, "mail-read": 3}
CLOCK = "2026-11-03T09:30"      # a Tuesday, as the dev file of CB-9


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


ITEMS = rows(FILE)
CATALOG = tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")


def test_the_file_is_canonical_sorted_and_loads_in_the_harness():
    raw = FILE.read_text(encoding="utf-8")
    assert raw.endswith("\n") and "\r" not in raw
    lines = raw.split("\n")[:-1]
    assert len(lines) == 24 == len(ITEMS)
    assert lines == [canon(item) for item in ITEMS], "every line is the canonical JSON of its item"
    ids = [item["id"] for item in ITEMS]
    assert ids == sorted(ids) and len(set(ids)) == 24
    loaded, data = interpreter_measure.load_corpus(str(FILE))
    assert len(loaded) == 24 and data == FILE.read_bytes()


def test_ids_are_in_the_61000_range_and_carry_their_language():
    for item in ITEMS:
        assert re.fullmatch(r"dev-(pt-br|en|es|fr|de|it)-(61[0-9]{3})", item["id"]), item["id"]
        assert item["id"].startswith(IDS_BY_LANG[item["lang"]]), item["id"]
    for lang, n in LANG_COUNTS.items():
        assert sorted(item["id"] for item in ITEMS if item["lang"] == lang) == [f"{IDS_BY_LANG[lang]}{k:03d}" for k in range(n)], "the numbers of a language run from 61000 without a gap"
    others = {item["id"] for name in FROZEN for item in rows(FOLDER / name)}
    assert not others & {item["id"] for item in ITEMS}, "no id of another set"


def test_every_item_is_a_dev_line_with_the_clock_of_the_spec_and_the_zone_of_its_language():
    for item in ITEMS:
        assert item["split"] == "dev" and item["channel"] == "messaging"
        assert item["forwarded"] is False and item["frame"] is None and item["tags"] == [] and item["hard"] is False and item["also"] == []
        assert item["clock"] == CLOCK, item["id"]
        assert item["zone"] == ZONES[item["lang"]], item["id"]


def test_every_item_passes_both_item_checks():
    for item in ITEMS:
        assert interpreter_pipeline.item_problems(item) == [], item["id"]
    assert tool().check_items(ITEMS, CATALOG) == []


def test_every_gold_op_and_slot_is_served_at_catalog_version_3_and_every_span_is_in_its_line():
    served = {row["op"]: row["slots"] for row in interpreter.SERVED["ops"]}
    assert operations.LINE_CATALOG == 3 and interpreter.SERVED["v"] == 3
    assert served["mail-ask"] == {"message": "int", "target": "span", "day": "span", "service": "word"}, "the row the file measures, with the slots the spec gives it"
    for item in ITEMS:
        gold = item["gold"]
        assert gold["outcome"] == "op", item["id"]
        assert gold["op"] in served, item["id"]
        for slot, spans in gold["slots"].items():
            assert slot in served[gold["op"]], (item["id"], slot)
            assert spans and all(isinstance(s, str) and s and s in item["line"] for s in spans), (item["id"], slot)
            if served[gold["op"]][slot] == "int":
                assert all(s.isdigit() for s in spans), (item["id"], slot)


def test_the_counts_by_language_by_operation_and_by_kind_of_line_are_literals():
    assert dict(sorted(collections.Counter(item["lang"] for item in ITEMS).items())) == LANG_COUNTS
    assert dict(sorted(collections.Counter(item["gold"]["op"] for item in ITEMS).items())) == OP_COUNTS
    assert sum(LANG_COUNTS.values()) == sum(OP_COUNTS.values()) == 24
    asked = [item for item in ITEMS if item["gold"]["op"] == "mail-ask"]
    pasted = [item for item in asked if " · " in item["line"]]
    by_number = [item for item in asked if "message" in item["gold"]["slots"]]
    newest = [item for item in asked if any(span.startswith(("o último", "último")) for span in item["gold"]["slots"].get("target", []))]
    assert (len(pasted), len(by_number), len(newest)) == (5, 4, 2), "five pasted list lines, four by number, two for the newest (the engine's table of the newest has Portuguese and English only)"
    assert len(asked) - len(pasted) - len(by_number) - len(newest) == 8, "five by a sender or subject, and three questions (a date, an amount, a due date)"
    assert [item["gold"]["op"] for item in ITEMS if item["gold"]["op"] in ("mail-read", "items", "ask")].count("mail-read") == 3, "three lines that must stay mail-read"
    assert {item["gold"]["op"] for item in ITEMS if item["gold"]["op"] in ("items", "ask")} == {"items", "ask"}, "and two that must stay items or ask"
    assert all(" · " in item["line"] for item in pasted) and all(re.search(r"(hoje|ontem|segunda|today) [0-9]{2}:[0-9]{2}$", item["line"]) for item in pasted), "a pasted line is the form code prints: who · subject · when"


# What each target-bearing item names, as words of the message's sender or subject: the test's own literals. `ops_mail_read._find` finds a message when `target_words(span)` is a subset of the words of
# its address, subject or display name (`natural_writes_mail.match_words`, `_read_matches`); a span that keeps a function word of a language the engine has no table for ("von", "di", "le") asks for a word
# the message does not carry. "newest" is read by `says_newest`, whose table has Portuguese and English phrases only.
NAMES = {"dev-pt-br-61006": {"clinica", "leve"}, "dev-pt-br-61009": {"dana"}, "dev-pt-br-61010": {"banco", "alvorada"}, "dev-pt-br-61012": {"clinica", "leve"},
         "dev-en-61002": {"marisol", "quenby", "roof", "repair"}, "dev-en-61003": {"dana", "whitlock"}, "dev-de-61000": {"lena", "brandt"}, "dev-it-61000": {"marta", "fontana"},
         "dev-fr-61000": {"helene", "moreau"}}
NEWEST = {"dev-pt-br-61007", "dev-pt-br-61008"}


def findable(span: str, names: set, tables) -> bool:
    """Whether `ops_mail_read._find` would find the message the line names with this target span: a list line, the newest, or words that are all in the message's own words."""
    if ops_mail_read._list_line(span) is not None:
        return True
    if natural_writes_mail.says_newest(span, tables):
        return True
    words = natural_writes_mail.target_words(span, tables)
    return bool(words) and set(words) <= names


def test_every_accepted_target_is_one_the_engine_finds_the_message_with():
    """Review of MAIL-SUMMARY-FLIP: `correct` means a gold span, so a gold span the engine cannot use makes a model that is right look right. Every accepted target is findable."""
    tables = natural._tables(None)
    targeted = [item for item in ITEMS if item["gold"]["op"] in ("mail-ask", "mail-read") and "target" in item["gold"]["slots"]]
    assert {item["id"] for item in targeted} == set(NAMES) | NEWEST | {item["id"] for item in ITEMS if " · " in item["line"]}, "every targeted item is described above"
    for item in targeted:
        for span in item["gold"]["slots"]["target"]:
            assert findable(span, NAMES.get(item["id"], set()), tables), (item["id"], span)
        if item["id"] in NEWEST:
            assert all(natural_writes_mail.says_newest(span, tables) for span in item["gold"]["slots"]["target"]), item["id"]


def test_vacuity_a_span_with_a_function_word_of_a_language_without_a_table_is_not_findable():
    tables = natural._tables(None)
    for span in ("von Lena Brandt", "die E-Mail von Lena Brandt", "di Marta Fontana", "l'email di Marta Fontana", "le dernier", "d'Hélène Moreau"):      # validate: allow english-only -- the lines under test
        names = {"lena", "brandt", "marta", "fontana", "helene", "moreau"}
        assert not findable(span, names, tables), span
    assert findable("Lena Brandt", {"lena", "brandt"}, tables) and findable("o último", set(), tables) and findable("da Dana", {"dana"}, tables)      # validate: allow english-only -- the lines under test


def test_the_lines_are_new_and_hold_no_address_and_no_phone_like_run():
    frozen = {normal(item["line"]) for name in FROZEN for item in rows(FOLDER / name)}
    lines = [normal(item["line"]) for item in ITEMS]
    assert len(set(lines)) == 24
    assert not frozen & set(lines), "no line of a frozen set"
    for item in ITEMS:
        text = item["line"]
        assert "@" not in text and "http" not in text and ".com" not in text and ".br" not in text, item["id"]
        assert not re.search(r"[0-9]{8,}", text.replace(" ", "").replace("-", "")), item["id"]


def test_no_line_is_claimed_by_stages_0_to_3_so_every_line_reaches_the_model():
    assert [item["id"] for item in ITEMS if interpreter_pipeline.pre_model(item) is not None] == []


def test_an_echo_model_is_correct_on_every_item():
    off = {item["id"]: echo_run(item) for item in ITEMS if echo_run(item)[0] != "correct"}
    assert off == {}, off


def test_the_checks_are_not_vacuous():
    tooling = tool()
    base = next(item for item in ITEMS if item["id"] == "dev-pt-br-61005")
    assert base["line"] == "resuma o 3 do Gmail" and tooling.check_items([base], CATALOG) == []
    planted = copy.deepcopy(base)
    planted["gold"]["slots"]["service"] = ["Outlook"]          # not a piece of the line
    assert any("not in the line" in problem for problem in tooling.check_items([planted], CATALOG))
    wrong_slot = copy.deepcopy(base)
    wrong_slot["gold"]["slots"]["place"] = ["Gmail"]          # not a slot of the op
    assert tooling.check_items([wrong_slot], CATALOG) != []
    claimed = copy.deepcopy(base)
    claimed["line"] = "/status"          # a typed command is stage 3 (code), not the model's
    assert interpreter_pipeline.pre_model(claimed) is not None
    unreadable = copy.deepcopy(base)
    assert echo_run(unreadable)[0] == "correct"
    unreadable["gold"]["slots"]["service"] = ["Outlook"]          # an echo that answers this gold names a span that is not in the line: the validator refuses it
    assert echo_run(unreadable)[0] != "correct"
    assert Echo(unreadable, [])("system", "user")["ok"] is True
