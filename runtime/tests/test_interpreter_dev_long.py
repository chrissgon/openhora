"""The long-line dev file of B-double-prime-lite (package BL3): `evals/interpreter/dev-long-v1.jsonl`, 46 fictional, information-rich lines (day words, articles, "da agenda",
polite words, titles of several words) written by the specification, not labelled blind. It is dev evidence, never the gate's held-out split, and it is a NEW file: `dev.jsonl` is
frozen and the replay gate draws its samples from it, so nothing here may touch that file.

What it holds, each oracle below with this test's own literals: the file is canonical (the bytes the corpus tool writes) and sorted; the ids are unique and in the 50000 range; every
item passes the measurement's `interpreter_pipeline.item_problems` and the corpus tool's `item_problems` (which checks every span is a piece of its line, character for character,
and every time exists once in its zone); every frame passes `interpreter.frame_problems` with the served catalog; every gold op and slot is an op and a slot of `natural.NATURAL`;
the counts by language, by gold op and by tag are literals; no line is a line of the frozen sets (`dev.jsonl`, `dev-relabelled.jsonl`, `ix-test-v1.jsonl`); no line holds an address or
a phone-like digit run. Offline, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_dev_long.py
"""
from __future__ import annotations

import collections
import copy
import importlib.util
import json
import re
from pathlib import Path

import standin_tree as st

interpreter = st.load("interpreter")
interpreter_measure = st.load("interpreter_measure")
interpreter_pipeline = st.load("interpreter_pipeline")
natural = st.load("natural")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
FILE = FOLDER / "dev-long-v1.jsonl"      # evals/interpreter/dev-long-v1.jsonl, named literally so the test selector picks this test when the file changes
FROZEN = ("dev.jsonl", "dev-relabelled.jsonl", "ix-test-v1.jsonl")

IDS_BY_LANG = {"pt-BR": "dev-pt-br-500", "en": "dev-en-500", "es": "dev-es-500", "fr": "dev-fr-500", "de": "dev-de-500", "it": "dev-it-500"}
ZONES = {"pt-BR": "America/Sao_Paulo", "en": "America/New_York", "es": "Europe/Madrid", "fr": "Europe/Paris", "de": "Europe/Berlin", "it": "Europe/Rome"}
LANG_COUNTS = {"de": 3, "en": 10, "es": 3, "fr": 3, "it": 3, "pt-BR": 24}
OP_COUNTS = {"answer": 1, "cancel": 5, "event-cancel": 10, "event-change": 6, "file-read": 2, "items": 6, "mail-archive": 2, "mail-mark": 1, "mail-move": 1,
             "mail-reply": 4, "mail-trash": 2, "none": 1, "research": 3, "route": 1, "stop-task": 1}
TAG_COUNTS = {"filler": 17, "multi-turn": 5, "must-route": 1}
CLOCK = "2026-10-27T09:30"


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
    assert len(lines) == 46 == len(ITEMS)
    assert lines == [canon(item) for item in ITEMS], "every line is the canonical JSON of its item"
    ids = [item["id"] for item in ITEMS]
    assert ids == sorted(ids) and len(set(ids)) == 46
    loaded, data = interpreter_measure.load_corpus(str(FILE))
    assert len(loaded) == 46 and data == FILE.read_bytes()


def test_ids_are_in_the_50000_range_and_carry_their_language():
    for item in ITEMS:
        match = re.fullmatch(r"dev-(pt-br|en|es|fr|de|it)-(500[0-9]{2})", item["id"])
        assert match, item["id"]
        assert item["id"].startswith(IDS_BY_LANG[item["lang"]]), item["id"]
        assert 50000 <= int(match.group(2)) <= 50099
    frozen_ids = {item["id"] for name in FROZEN for item in rows(FOLDER / name)}
    assert not frozen_ids & {item["id"] for item in ITEMS}, "no id of a frozen set"


def test_every_item_is_a_dev_line_of_the_spec_with_the_same_clock_and_the_zone_of_its_language():
    for item in ITEMS:
        assert item["split"] == "dev" and item["author"] == "opus" and item["channel"] == "messaging"
        assert item["forwarded"] is False and item["also"] == []
        assert item["clock"] == CLOCK, item["id"]
        assert item["zone"] == ZONES[item["lang"]], item["id"]
        assert item["hard"] is False, "no tag of the file is a hard tag"
        assert set(item["tags"]) <= {"filler", "multi-turn", "must-route"}
        assert ("multi-turn" in item["tags"]) == (item["frame"] is not None), item["id"]


def test_every_item_passes_both_item_checks_and_every_frame_the_frame_check():
    for item in ITEMS:
        assert interpreter_pipeline.item_problems(item) == [], item["id"]
        if item["frame"] is not None:
            assert interpreter.frame_problems(item["frame"], interpreter.SERVED) == [], item["id"]
    assert tool().check_items(ITEMS, CATALOG) == []


def test_every_gold_op_and_slot_is_in_the_natural_table_and_every_span_is_in_its_line():
    for item in ITEMS:
        gold = item["gold"]
        if gold["outcome"] != "op":
            continue
        assert gold["op"] in natural.NATURAL, item["id"]
        for slot, spans in gold["slots"].items():
            assert slot in natural.NATURAL[gold["op"]]["slots"], (item["id"], slot)
            assert spans and all(isinstance(s, str) and s for s in spans)
            kind = natural.NATURAL[gold["op"]]["slots"][slot][0]
            if kind != "int":
                assert all(s in item["line"] for s in spans), (item["id"], slot)
            else:
                assert all(s.isdigit() and s in item["line"] for s in spans), (item["id"], slot)
        assert ("time" in gold) == any(slot in ("time", "when") for slot in gold["slots"]), item["id"]


def test_the_day_and_target_slots_of_the_merged_catalog_are_used():
    used = collections.Counter(slot for item in ITEMS if item["gold"]["outcome"] == "op" for slot in item["gold"]["slots"])
    assert used["target"] >= 15 and used["day"] >= 12, "the new additive slots are what this file measures"
    for op in ("event-change", "event-cancel", "mail-reply", "mail-archive", "mail-move", "mail-mark", "mail-trash"):
        assert {"target", "day"} <= set(CATALOG["ops"][op]["slots"]), op


def test_the_counts_by_language_by_operation_and_by_tag_are_literals():
    assert dict(sorted(collections.Counter(item["lang"] for item in ITEMS).items())) == LANG_COUNTS
    ops = collections.Counter(item["gold"].get("op") or item["gold"]["outcome"] for item in ITEMS)
    assert dict(sorted(ops.items())) == OP_COUNTS
    assert dict(sorted(collections.Counter(tag for item in ITEMS for tag in item["tags"]).items())) == TAG_COUNTS
    assert sum(LANG_COUNTS.values()) == sum(OP_COUNTS.values()) == 46


def test_the_frames_are_the_plan_confirm_ones_the_spec_names():
    framed = {item["id"]: item for item in ITEMS if item["frame"] is not None}
    assert sorted(framed) == ["dev-en-50008", "dev-pt-br-50016", "dev-pt-br-50017", "dev-pt-br-50018", "dev-pt-br-50023"]
    for item in framed.values():
        assert [(i["kind"], i["need"]) for i in item["frame"]["items"]] == [("plan-confirm", "confirm")]
        assert set(item["frame"]["items"][0]) == {"id", "kind", "need", "op", "age_s"}
    assert framed["dev-pt-br-50018"]["gold"] == {"outcome": "answer", "item": "i1", "confirm": "yes"}


def test_the_lines_are_new_and_hold_no_address_and_no_phone_like_run():
    frozen = {normal(item["line"]) for name in FROZEN for item in rows(FOLDER / name)}
    lines = [normal(item["line"]) for item in ITEMS]
    assert len(set(lines)) == 46
    assert not frozen & set(lines), "no line of a frozen set"
    for item in ITEMS:
        text = item["line"] + " " + json.dumps(item["frame"] or {}, ensure_ascii=False)
        assert "@" not in text, item["id"]
        assert not re.search(r"[0-9]{8,}", text.replace(" ", "").replace("-", "")), item["id"]
        assert "http" not in text and ".com" not in text and ".br" not in text, item["id"]


def test_the_frozen_dev_file_is_not_part_of_this_file_and_is_still_read_by_the_replay_gate():
    assert FILE != FOLDER / "dev.jsonl"
    assert len(rows(FOLDER / "dev.jsonl")) >= 50
    gate = (ROOT / "runtime" / "tests" / "test_interpreter_replay_gate.py").read_text(encoding="utf-8")
    assert '"dev.jsonl"' in gate and "dev-long" not in gate


def test_the_checks_are_not_vacuous():
    tooling = tool()

    def problems(item, catalog):
        return tooling.check_items([item], catalog)

    base = next(item for item in ITEMS if item["id"] == "dev-pt-br-50000")
    assert problems(base, CATALOG) == []
    planted = copy.deepcopy(base)
    planted["gold"]["slots"]["target"] = ["corte de barba"]          # not a piece of the line
    assert any("not in the line" in problem for problem in problems(planted, CATALOG))
    wrong_slot = copy.deepcopy(base)
    wrong_slot["gold"]["slots"]["place"] = ["amanha"]                 # not a slot of the op
    assert problems(wrong_slot, CATALOG) != []
    wrong_frame = copy.deepcopy(next(item for item in ITEMS if item["id"] == "dev-pt-br-50018"))
    wrong_frame["frame"]["items"][0]["need"] = "slot"                 # a plan-confirm item is need confirm
    assert problems(wrong_frame, CATALOG) != []
    assert interpreter.frame_problems(wrong_frame["frame"], interpreter.SERVED) != []
    past = copy.deepcopy(next(item for item in ITEMS if item["id"] == "dev-pt-br-50004"))
    past["gold"]["time"] = ["2026-10-20T10:00"]                       # before the clock
    assert problems(past, CATALOG) != []
    assert interpreter_pipeline.item_problems({"id": "dev-en-50099"}) != []
