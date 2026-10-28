"""The catalog-batch dev file of CB-9 (package CB-9): `evals/interpreter/dev-catalog-v1.jsonl`, 77 fictional lines written by the CB-9 executor (not by the author of any `about` text), the lines of
the operations the version-2 catalog adds (a filtered items read, mail-read, todo-list, todo-add, todo-done, a repeat slot on event-create, series and occurrence cancels, a series change,
reminder-forget by words, file-ask) with their confusables. It is dev evidence, never blind, and a NEW file: the frozen corpora are not touched.

What it holds, each oracle below with this test's own literals: the file is canonical (the bytes the corpus tool writes) and sorted; the ids are unique, in the 60000 range and carry their language;
every item passes the measurement's `interpreter_pipeline.item_problems` and the corpus tool's `item_problems` (every span a piece of its line, every time one that exists once in its zone and
after the clock); every gold op and slot is a served op and slot of catalog version 2; the counts by language and by operation are literals; no line is a line of a frozen set and no line holds an
address or a phone-like run; no line is claimed by stages 0 to 3 (code), so every line reaches the model; an echo model that answers each gold is `correct` on every item but the two listed, each
with the reason code decides it differently. The summary of the blind set (`cb9-blind-split.json`: the set itself is never in the repository) is checked for its shape and its counts. Offline, no
model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_dev_catalog.py
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
interpreter_measure = st.load("interpreter_measure")
interpreter_pipeline = st.load("interpreter_pipeline")
natural = st.load("natural")
operations = st.load("operations")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
FILE = FOLDER / "dev-catalog-v1.jsonl"      # evals/interpreter/dev-catalog-v1.jsonl, named literally so the test selector picks this test when the file changes
SPLIT = FOLDER / "cb9-blind-split.json"      # evals/interpreter/cb9-blind-split.json
FROZEN = ("dev.jsonl", "dev-relabelled.jsonl", "ix-test-v1.jsonl", "dev-long-v1.jsonl", "dev-long-v2.jsonl", "blite-blind-v2.jsonl")

IDS_BY_LANG = {"pt-BR": "dev-pt-br-600", "en": "dev-en-600", "es": "dev-es-600", "fr": "dev-fr-600", "de": "dev-de-600", "it": "dev-it-600"}
ZONES = {"pt-BR": "America/Sao_Paulo", "en": "America/New_York", "es": "Europe/Madrid", "fr": "Europe/Paris", "de": "Europe/Berlin", "it": "Europe/Rome"}
LANG_COUNTS = {"de": 2, "en": 26, "es": 3, "fr": 3, "it": 1, "pt-BR": 42}
OP_COUNTS = {"ask": 1, "event-cancel": 6, "event-change": 1, "event-create": 15, "file-ask": 7, "file-read": 2, "items": 9, "mail-read": 8, "remind": 1, "reminder-forget": 2,
             "research": 2, "status": 2, "task": 1, "todo-add": 9, "todo-done": 5, "todo-list": 6}
CLOCK = "2026-11-03T09:30"      # a Tuesday; US clocks changed on 2026-11-01, European ones on 2026-10-25
UNREAD_NEGATED = "dev-pt-br-60003"      # "os e-mails não lidos, não a agenda": a negated noun, gold items {state} (ITEMS-NEGATION)      # validate: allow english-only -- the Portuguese line under test
TIME_ASK = "the code half-reads or doubts the time phrase of a language with no table, so it asks instead of taking the echo's time_iso (clarify time-ask)"
ECHO_OFF = {"dev-fr-60002": TIME_ASK, "dev-it-60000": TIME_ASK}      # the only items whose echo is not `correct`, each with why
NEW_OPS = ("mail-read", "todo-list", "todo-add", "todo-done", "file-ask")      # the rows of catalog version 2


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
    assert len(lines) == 77 == len(ITEMS)
    assert lines == [canon(item) for item in ITEMS], "every line is the canonical JSON of its item"
    ids = [item["id"] for item in ITEMS]
    assert ids == sorted(ids) and len(set(ids)) == 77
    loaded, data = interpreter_measure.load_corpus(str(FILE))
    assert len(loaded) == 77 and data == FILE.read_bytes()


def test_ids_are_in_the_60000_range_and_carry_their_language():
    per_lang = collections.Counter()
    for item in ITEMS:
        match = re.fullmatch(r"dev-(pt-br|en|es|fr|de|it)-(600[0-9]{2})", item["id"])
        assert match, item["id"]
        assert item["id"].startswith(IDS_BY_LANG[item["lang"]]), item["id"]
        per_lang[item["lang"]] += 1
    for lang, n in LANG_COUNTS.items():
        assert sorted(item["id"] for item in ITEMS if item["lang"] == lang) == [f"{IDS_BY_LANG[lang]}{k:02d}" for k in range(n)], "the numbers of a language run from 60000 without a gap"
    frozen_ids = {item["id"] for name in FROZEN for item in rows(FOLDER / name)}
    assert not frozen_ids & {item["id"] for item in ITEMS}, "no id of a frozen set"


def test_every_item_is_a_dev_line_with_the_clock_of_the_spec_and_the_zone_of_its_language():
    for item in ITEMS:
        assert item["split"] == "dev" and item["author"] == "opus" and item["channel"] == "messaging"
        assert item["forwarded"] is False and item["frame"] is None and item["tags"] == [] and item["hard"] is False
        assert item["clock"] == CLOCK, item["id"]
        assert item["zone"] == ZONES[item["lang"]], item["id"]


def test_every_item_passes_both_item_checks():
    for item in ITEMS:
        assert interpreter_pipeline.item_problems(item) == [], item["id"]
    assert tool().check_items(ITEMS, CATALOG) == []


def test_every_gold_op_and_slot_is_served_at_catalog_version_2_and_every_span_is_in_its_line():
    served = {row["op"]: row["slots"] for row in interpreter.SERVED["ops"]}
    assert operations.LINE_CATALOG == 2 and interpreter.SERVED["v"] == 2
    for op in NEW_OPS:
        assert op in served and op not in {row["op"] for row in json.loads((ROOT / "runtime" / "interpreter_catalog.json").read_text(encoding="utf-8"))["refused"]}
    for item in ITEMS:
        gold = item["gold"]
        assert gold["outcome"] == "op", item["id"]
        assert gold["op"] in served, item["id"]
        for slot, spans in gold["slots"].items():
            assert slot in served[gold["op"]], (item["id"], slot)
            assert spans and all(isinstance(s, str) and s for s in spans)
            if served[gold["op"]][slot] == "int":
                assert all(s.isdigit() and s in item["line"] for s in spans), (item["id"], slot)
            else:
                assert all(s in item["line"] for s in spans), (item["id"], slot)
        assert ("time" in gold) == any(slot in ("time", "when") for slot in gold["slots"]), item["id"]


def test_the_counts_by_language_and_by_operation_are_literals():
    assert dict(sorted(collections.Counter(item["lang"] for item in ITEMS).items())) == LANG_COUNTS
    assert dict(sorted(collections.Counter(item["gold"]["op"] for item in ITEMS).items())) == OP_COUNTS
    assert sum(LANG_COUNTS.values()) == sum(OP_COUNTS.values()) == 77
    assert LANG_COUNTS["pt-BR"] == 42 and LANG_COUNTS["en"] == 26 and sum(LANG_COUNTS[lang] for lang in ("es", "fr", "de", "it")) == 9


def test_the_new_slots_of_the_catalog_are_what_the_file_measures():
    used = collections.Counter(slot for item in ITEMS for slot in item["gold"]["slots"])
    assert used["repeat"] == 12 and used["target"] >= 20 and used["day"] >= 12 and used["state"] == 3 and used["message"] == 4 and used["item"] == 2 and used["service"] == 6
    repeats = [item for item in ITEMS if "repeat" in item["gold"]["slots"]]
    assert {item["gold"]["op"] for item in repeats} == {"event-create"} and len(repeats) == 12
    assert [item["id"] for item in ITEMS if item["also"]] == ["dev-en-60013", "dev-pt-br-60022", "dev-pt-br-60023"], "the three unsupported recurrences (pt-BR twice, en once) also accept the honest sentence code answers"
    for item in ITEMS:
        for alt in item["also"]:
            assert alt == {"outcome": "clarify"}, item["id"]


def test_one_items_line_carries_a_negated_noun():
    item = next(item for item in ITEMS if item["id"] == UNREAD_NEGATED)
    assert item["line"] == "os e-mails não lidos, não a agenda" and item["gold"] == {"op": "items", "outcome": "op", "slots": {"state": ["não lidos"]}}      # validate: allow english-only -- the Portuguese line under test


def test_the_lines_are_new_and_hold_no_address_and_no_phone_like_run():
    frozen = {normal(item["line"]) for name in FROZEN for item in rows(FOLDER / name)}
    lines = [normal(item["line"]) for item in ITEMS]
    assert len(set(lines)) == 77
    assert not frozen & set(lines), "no line of a frozen set"
    for item in ITEMS:
        text = item["line"]
        assert "@" not in text and "http" not in text and ".com" not in text and ".br" not in text, item["id"]
        assert not re.search(r"[0-9]{8,}", text.replace(" ", "").replace("-", "")), item["id"]


def test_no_line_is_claimed_by_stages_0_to_3_so_every_line_reaches_the_model():
    assert [item["id"] for item in ITEMS if interpreter_pipeline.pre_model(item) is not None] == []


def test_an_echo_model_is_correct_on_every_item_but_the_two_the_code_decides_differently():
    off = {}
    for item in ITEMS:
        category, observed = echo_run(item)
        if category != "correct":
            off[item["id"]] = (category, observed)
    assert set(off) == set(ECHO_OFF), "an item is wrong that is not listed, or a listed item is no longer wrong"
    assert all(category == "clarify" and observed == "clarify" for category, observed in off.values())
    for item_id in ECHO_OFF:
        item = next(i for i in ITEMS if i["id"] == item_id)
        assert item["lang"] in ("fr", "it") and "repeat" in item["gold"]["slots"], "a time table exists for pt-BR and en only: the listed items are a repeating line of another language"


def test_the_summary_of_the_blind_set_has_its_shape_and_its_counts():
    summary = json.loads(SPLIT.read_text(encoding="utf-8"))
    assert set(summary) == {"v", "file", "sha256", "items", "counts", "frozen"} and summary["v"] == 1
    assert summary["file"] == "cb9-blind-v1.jsonl" and summary["items"] == 50 and summary["frozen"] == "2026-10-28"
    assert re.fullmatch(r"[0-9a-f]{64}", summary["sha256"])
    counts = summary["counts"]
    assert set(counts) == {"author", "frame", "lang", "op", "outcome", "tags", "with_also"}
    assert sum(counts["lang"].values()) == sum(counts["op"].values()) == sum(counts["outcome"].values()) == sum(counts["frame"].values()) == 50
    assert counts["lang"] == {"de": 1, "en": 16, "es": 1, "fr": 1, "it": 1, "pt-BR": 30} and counts["author"] == {"opus": 50} and counts["with_also"] == 1
    assert counts["op"]["file-ask"] == 5 and counts["op"]["mail-reply"] == 6 and counts["op"]["mail-read"] == 4 and counts["op"]["todo-add"] == 4
    assert sum(counts["op"][op] for op in ("mail-archive", "mail-trash", "mail-mark", "mail-move")) == 6, "the six numbered mail writes of BL7-5"
    assert counts["tags"] == {} and counts["frame"] == {"none": 50}


def test_the_checks_are_not_vacuous():
    tooling = tool()
    base = next(item for item in ITEMS if item["id"] == "dev-pt-br-60000")
    assert tooling.check_items([base], CATALOG) == []
    planted = copy.deepcopy(base)
    planted["gold"]["slots"]["target"] = ["o cartão"]          # not a piece of the line      # validate: allow english-only -- the Portuguese line under test
    assert any("not in the line" in problem for problem in tooling.check_items([planted], CATALOG))
    wrong_slot = copy.deepcopy(base)
    wrong_slot["gold"]["slots"]["place"] = ["hoje"]          # not a slot of the op
    assert tooling.check_items([wrong_slot], CATALOG) != []
    past = copy.deepcopy(next(item for item in ITEMS if item["id"] == "dev-pt-br-60018"))
    assert past["gold"]["op"] == "event-create" and past["gold"]["time"] == ["2026-11-09T07:00"]
    past["gold"]["time"] = ["2026-11-01T07:00"]          # before the clock
    assert tooling.check_items([past], CATALOG) != []
    claimed = copy.deepcopy(base)
    claimed["line"] = "/status"          # a typed command is stage 3 (code), not the model's
    assert interpreter_pipeline.pre_model(claimed) is not None
    unreadable = copy.deepcopy(next(item for item in ITEMS if item["id"] == "dev-pt-br-60008"))
    assert echo_run(unreadable)[0] == "correct"
    unreadable["gold"]["slots"]["target"] = ["Livraria Lua Nova"]          # an echo that answers this gold names a span that is not in the line: the validator refuses it
    assert echo_run(unreadable)[0] != "correct"
    assert Echo(unreadable, [])("system", "user")["ok"] is True


def test_the_summary_of_the_second_blind_set_has_its_shape_its_groups_and_the_keys_the_harness_reads():
    """The second blind set (written by a fresh author for the round-2 measurement; the set is never in the repository): its summary carries the harness's own keys, the counts, and `group_of_id`."""
    summary = json.loads((FOLDER / "cb9-blind-v2-split.json").read_text(encoding="utf-8"))
    assert set(summary) == {"v", "file", "sha256", "items", "counts", "frozen", "group_of_id"} and summary["v"] == 1
    assert summary["file"] == "cb9-blind-v2.jsonl" and summary["items"] == 50 and summary["frozen"] == "2026-10-28"
    assert summary["sha256"] == "10f3308fdd2708b0cf678d9b45c9f293302f23e42602e0c385fe810b0ebd891e"      # the hash the measurement script (ix-cb9.sh) holds as WANT_SET
    counts = summary["counts"]
    assert sum(counts["group"].values()) == sum(counts["lang"].values()) == sum(counts["outcome"].values()) == 50 and len(summary["group_of_id"]) == 50
    assert counts["group"]["mail-write-numbered"] == 6 and counts["group"]["mail-reply-sender"] == 6, "the 12 follow-up lines of BL7-4 and BL7-5, reported apart"
    assert counts["group"]["event-create-repeat"] == 4 and counts["group"]["series-cancel"] == 2 and counts["group"]["occurrence-cancel"] == 2 and counts["group"]["file-ask"] == 5
    assert dict(collections.Counter(summary["group_of_id"].values())) == counts["group"], "the group of each id and the counts of the groups say the same"
    assert all(re.fullmatch(r"test-(pt-br|en|es|fr|de|it)-[0-9]{5}", item_id) for item_id in summary["group_of_id"])
    harness = interpreter_measure.thresholds()      # the loader the harness runs reads `sha256` and `items` and no other key
    assert harness["runs"] == 2 and isinstance(summary["sha256"], str) and isinstance(summary["items"], int)


def test_two_lines_hold_a_series_word_in_a_one_off_event_title_and_their_gold_has_no_repeat():
    """The review of 2026-10-28: with the interpreter on, "put weekly review on my calendar tomorrow at 3pm" and "marca uma daily amanhã às 9h" go to the model; the gold keeps the word in the title."""      # validate: allow english-only -- the Portuguese line under test
    recurrence = st.load("recurrence")
    found = {item["id"]: item for item in ITEMS if item["id"] in ("dev-en-60025", "dev-pt-br-60041")}
    assert set(found) == {"dev-en-60025", "dev-pt-br-60041"}
    for item in found.values():
        gold = item["gold"]
        assert gold["op"] == "event-create" and "repeat" not in gold["slots"] and recurrence.mentions(item["line"]), item["id"]
        assert any(word in gold["slots"]["title"][0] for word in ("weekly", "daily")) and gold["time"], item["id"]
    assert found["dev-en-60025"]["gold"]["time"] == ["2026-11-04T15:00"] and found["dev-pt-br-60041"]["gold"]["time"] == ["2026-11-04T09:00"]
    loud = copy.deepcopy(found["dev-en-60025"])
    loud["gold"]["slots"]["repeat"] = ["weekly"]      # vacuity: a gold that held a repeat would be a different item, and this test would refuse it
    assert "repeat" in loud["gold"]["slots"] and loud["gold"] != found["dev-en-60025"]["gold"]
