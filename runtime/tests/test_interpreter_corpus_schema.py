"""The committed corpus of the interpreter experiment (package IX-1) against the item format, the served catalog, the
natural-request table and the frame checker of the interpreter.

What it reads: evals/interpreter/dev.jsonl and dev-relabelled.jsonl (the dev split), test-split.json (the frozen test
split's summary) when they exist, runtime/interpreter_catalog.json (C0), runtime/natural.py (NATURAL, the oracle for
every op and slot) and, once IX-2a has merged, runtime/interpreter.py (`frame_problems`). The relabelled file is
rebuilt from the three corpora of runtime/tests and must be byte-identical: it is code's output, never edited by hand.
Each oracle below reads the raw files with this test's own literal lists. Offline, no model, no network.
Run: uv run --with pytest pytest runtime/tests/test_interpreter_corpus_schema.py
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

import standin_tree as st

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
CATALOG = ROOT / "runtime" / "interpreter_catalog.json"
SOURCES = {"natural": (ROOT / "runtime/tests/natural_corpus.jsonl", 10000),
           "writes": (ROOT / "runtime/tests/natural_writes_corpus.jsonl", 20000),
           "mail": (ROOT / "runtime/tests/natural_writes_mail_corpus.jsonl", 30000)}
ID = re.compile(r"^(dev|test)-(pt-br|en|es|fr|de|it|ja|mx)-([0-9]{5})$")
LANG_PART = {"pt-BR": "pt-br", "en": "en", "es": "es", "fr": "fr", "de": "de", "it": "it", "ja": "ja", "mixed": "mx"}
ITEM_KEYS = {"id", "split", "lang", "author", "tags", "hard", "clock", "zone", "channel", "forwarded", "frame", "line", "gold", "also"}
TIME_SLOTS = {("remind", "when"), ("event-create", "time"), ("event-change", "time")}
SPLIT_KEYS = {"v", "file", "sha256", "items", "counts", "frozen"}
COUNT_KEYS = {"lang", "author", "outcome", "op", "tags"}
# A catalog of this test, for the planted items, in the served file's shape.
LITERAL_CATALOG = {"v": 1, "ops": [{"op": "remind", "class": "N", "what": "a reminder", "slots": {"text": "span", "when": "when"}}],
                   "refused": [{"op": "approve", "class": "D", "what": "approve"}]}


def tool(name="interpreter_corpus"):
    """A file of the tool (scripts/ is tooling: loaded by path, never imported from runtime/ code)."""
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dev_files() -> list:
    return [p for p in (FOLDER / "dev.jsonl", FOLDER / "dev-relabelled.jsonl") if p.exists()]


def served_catalog():
    if not CATALOG.exists():
        pytest.skip("runtime/interpreter_catalog.json is written by package C0, which merges before this package")
    return tool().load_catalog(CATALOG)


def within(due, clock) -> bool:
    """A moment after the clock and at most 366 days on (the interpreter's time-past and time-far), read by this test."""
    if not due:
        return False
    start, end = datetime.datetime.strptime(clock, "%Y-%m-%d %H:%M"), datetime.datetime.strptime(due, "%Y-%m-%d %H:%M")
    return start < end and end - start <= datetime.timedelta(days=366)


def test_the_relabelled_file_is_codes_output_byte_for_byte(tmp_path):
    out = tmp_path / "dev-relabelled.jsonl"
    module = tool()
    assert module.main(["relabel", "--out", str(out)]) == 0
    assert out.read_bytes() == (FOLDER / "dev-relabelled.jsonl").read_bytes()


def test_each_relabelled_item_is_its_source_line_with_the_mapped_gold():
    items = {i["id"]: i for i in rows(FOLDER / "dev-relabelled.jsonl")}
    expected = 0
    for name, (path, base) in SOURCES.items():
        for n, source in enumerate(rows(path)):
            expected += 1
            lang = source.get("language") or source["lang"]
            it = items[f"dev-{LANG_PART[lang]}-{base + n:05d}"]
            assert it["line"] == (source.get("text") or source["line"]) and it["lang"] == lang and it["author"] == "relabel"
            gold = it["gold"]
            if name != "natural":
                want = {"outcome": "route"} if source["op"] == "work" else {"outcome": "op", "op": source["op"], "scope": "op"}
                assert gold == want and it["tags"] == ["relabel-op"], it["id"]
            else:
                due = source["expected"].get("due")
                readable = source["expected"]["kind"] == "time" and within(due, source["clock"])
                if source.get("timeonly"):
                    assert it["frame"]["items"][0]["kind"] == "reminder-confirm" and "multi-turn" in it["tags"]
                    want = {"outcome": "answer", "item": "i1", "slot": "when"} if readable else {"outcome": "clarify"}  # the reading only, no span
                    assert {k: v for k, v in gold.items() if k != "time"} == want, it["id"]
                else:
                    assert it["frame"] is None and gold["scope"] == "time"
                    assert gold["outcome"] == ("op" if readable else "clarify"), it["id"]
                if readable:
                    assert gold["time"][0] == due.replace(" ", "T"), it["id"]
    assert len(items) == expected == 575 + 414 + 355


def test_every_gold_op_and_slot_of_the_dev_split_exists_in_natural():
    natural = st.load("natural")
    for path in dev_files():
        for it in rows(path):
            for gold in [it["gold"]] + it["also"]:
                if gold["outcome"] == "op" and gold.get("op") is not None:
                    assert gold["op"] in natural.NATURAL, it["id"]
                    assert set(gold.get("slots") or {}) <= set(natural.NATURAL[gold["op"]]["slots"]), it["id"]
            for frame_item in (it["frame"] or {}).get("items", []):
                if "op" in frame_item:
                    assert frame_item["op"] in natural.NATURAL and frame_item.get("slot", "text") in natural.NATURAL[frame_item["op"]]["slots"]


def test_ids_are_unique_and_the_files_are_canonical():
    seen = set()
    for path in dev_files():
        raw = path.read_text(encoding="utf-8").splitlines()
        items = [json.loads(line) for line in raw]
        assert raw == [json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for i in items], path.name
        ids = [i["id"] for i in items]
        assert ids == sorted(ids) and not seen & set(ids), path.name
        seen |= set(ids)
        for it in items:
            match = ID.match(it["id"])
            assert set(it) - {"base"} == ITEM_KEYS and match and match.group(1) == "dev" == it["split"]
            assert match.group(2) == LANG_PART[it["lang"]]


def test_every_dev_item_passes_check_against_the_served_catalog():
    cat = served_catalog()
    files = dev_files()
    assert FOLDER / "dev-relabelled.jsonl" in files
    problems = tool().check_items([i for p in files for i in rows(p)], cat)
    assert problems == [], problems[:20]


def test_the_tools_time_slots_are_the_catalogs():
    assert tool("interpreter_corpus_format").TIME_SLOTS == TIME_SLOTS
    if not (ROOT / "runtime" / "interpreter_catalog.py").exists():
        pytest.skip("runtime/interpreter_catalog.py is written by package C0")
    assert set(st.load("interpreter_catalog").TIME_SLOTS) == TIME_SLOTS


def test_every_frame_passes_the_interpreters_frame_checker():
    cat = served_catalog()
    if not (ROOT / "runtime" / "interpreter.py").exists():
        pytest.skip("runtime/interpreter.py (frame_problems) is written by package IX-2a, which merges before this package")
    interpreter = st.load("interpreter")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    frames = [(i["id"], i["frame"]) for p in dev_files() for i in rows(p) if i["frame"] is not None]
    assert frames, "the relabelled timeonly lines carry a frame"
    assert cat["ops"], "the served catalog has ops"
    bad = [(key, interpreter.frame_problems(frame, catalog)) for key, frame in frames]
    assert [b for b in bad if b[1]] == []


def split_problems(split: dict) -> list:
    """The shape of test-split.json: closed keys, counts that sum to items, a sha256 of 64 hex."""
    out = []
    if set(split) != SPLIT_KEYS or split.get("v") != 1 or split.get("file") != "ix-test-v1.jsonl":
        out.append("keys")
    if not re.fullmatch(r"[0-9a-f]{64}", str(split.get("sha256"))):
        out.append("sha256")
    counts = split.get("counts") or {}
    if set(counts) != COUNT_KEYS:
        out.append("counts")
    for key in ("lang", "author", "outcome"):
        if sum((counts.get(key) or {}).values()) != split.get("items"):
            out.append(f"counts.{key}")
    return out


def test_the_test_split_file_has_its_shape_and_counts_that_sum_to_its_items():
    good = {"v": 1, "file": "ix-test-v1.jsonl", "sha256": hashlib.sha256(b"x").hexdigest(), "items": 3, "frozen": "2026-10-21",
            "counts": {"lang": {"en": 2, "pt-BR": 1}, "author": {"gen": 3}, "outcome": {"op": 2, "none": 1}, "op": {"remind": 2},
                       "tags": {}}}
    assert split_problems(good) == []
    # vacuity: counts that do not sum to the items are caught
    assert split_problems(dict(good, items=4)) == ["counts.lang", "counts.author", "counts.outcome"]
    path = FOLDER / "test-split.json"
    if path.exists():
        assert split_problems(json.loads(path.read_text(encoding="utf-8"))) == []


def test_a_planted_item_with_an_unknown_op_fails_check(tmp_path):
    module = tool()
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(LITERAL_CATALOG), encoding="utf-8")
    cat = module.load_catalog(path)  # the reader the served catalog goes through
    good = {"id": "dev-en-00001", "split": "dev", "lang": "en", "author": "opus", "tags": [], "hard": False, "clock": "2026-10-22T14:00",
            "zone": "America/Sao_Paulo", "channel": "messaging", "forwarded": False, "frame": None,
            "line": "remind me to call Bob tomorrow at 9", "gold": {"outcome": "op", "op": "remind",
            "slots": {"text": ["call Bob"], "when": ["tomorrow at 9"]}, "time": ["2026-10-23T09:00"]}, "also": []}
    assert module.check_items([good], cat) == []
    planted = dict(good, id="dev-en-00002", gold={"outcome": "op", "op": "launch-rocket", "slots": {}})
    assert [p.split()[0] for p in module.check_items([planted], cat)] == ["dev-en-00002"]
    refused = dict(good, id="dev-en-00003", gold={"outcome": "op", "op": "approve", "slots": {}})
    assert module.check_items([refused], cat), "a refused op is no op of the catalog"
