"""The recorded answers of the second B-double-prime-lite measurement (package BL5F, after fixes A to E): four answers files (the long set M1 on `dev-long-v2.jsonl` and the 50-item
regression draw M2 of `dev.jsonl`, on DeepSeek and on Sonnet), their four evidence files, replayed with no call.

Two kinds of literal, kept apart because later code changes move one and never the other:
  PUBLISHED  the counts the measurement published (worst category of the runs of each item), read here from the four evidence files and never re-scored: they are what happened;
  REPLAY     the counts the CURRENT code gives the recorded answers (the catalog they were recorded with, the same as the first run's, put in the place of the served one, as the replay
             gate does). A package that changes the check updates these, with its reason, and never the published ones.
Unlike the first run, M1 was recorded on `dev-long-v2.jsonl` itself, so no re-score under other golds is involved; v2 was written after the first run's answers were seen, so the M1 result
is not blind (published so). The test builds `Answers("replay", ...)` directly, as the replay gate does, so it keeps working when the served prompt changes (the command-line replay then
refuses these files by their header, which is correct). The data files it reads are named below, so the test selector picks it when one changes: evals/interpreter/dev-long-v2.jsonl,
evals/interpreter/dev.jsonl, evals/interpreter/replay/catalogs/catalog-a77f8a8f.json, the four answers files under evals/interpreter/replay/*/blite2-20261025/ and the four evidence
files evals/interpreter/evidence/ix-20261026T011821Z-25ff628e.jsonl, ix-20261026T011939Z-af4c6192.jsonl, ix-20261026T012015Z-79cfe53a.jsonl and ix-20261026T012427Z-cb139f8a.jsonl.
Offline, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_blite2_replay.py
"""
from __future__ import annotations

import collections
import hashlib
import json
import shutil
from pathlib import Path

import pytest

import standin_tree as st
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

ops_interpret = st.load("ops_interpret")
interpreter = st.load("interpreter")
interpreter_measure = st.load("interpreter_measure")
interpreter_pipeline = st.load("interpreter_pipeline")
interpreter_route = st.load("interpreter_route")

REPO = Path(__file__).resolve().parents[2]
FOLDER = REPO / "evals" / "interpreter"
V2 = FOLDER / "dev-long-v2.jsonl"
DEV = FOLDER / "dev.jsonl"
RECORDED_CATALOG = FOLDER / "replay" / "catalogs" / "catalog-a77f8a8f.json"
EVIDENCE = FOLDER / "evidence"
DEEPSEEK, SONNET = "or-deepseek-v4.1-flash", "acct-claude-sonnet-5.5"
RUN = "blite2-20261025"
ANSWERS = {   # (route, set) -> (the answers file, its evidence file, the corpus it was recorded on)
    (DEEPSEEK, "M1"): (f"{DEEPSEEK}/{RUN}/M1/20261026T011821Z-25ff628e.answers.jsonl", "ix-20261026T011821Z-25ff628e.jsonl", V2),
    (DEEPSEEK, "M2"): (f"{DEEPSEEK}/{RUN}/M2/20261026T011939Z-af4c6192.answers.jsonl", "ix-20261026T011939Z-af4c6192.jsonl", DEV),
    (SONNET, "M1"): (f"{SONNET}/{RUN}/M1/20261026T012015Z-79cfe53a.answers.jsonl", "ix-20261026T012015Z-79cfe53a.jsonl", V2),
    (SONNET, "M2"): (f"{SONNET}/{RUN}/M2/20261026T012427Z-cb139f8a.answers.jsonl", "ix-20261026T012427Z-cb139f8a.jsonl", DEV),
}
# PUBLISHED: worst category of the runs of each item (2 runs for M1, 1 for M2), as the run's summaries counted it.
PUBLISHED = {
    (DEEPSEEK, "M1"): {"correct": 41, "clarify": 4, "wrong_card": 1},
    (SONNET, "M1"): {"correct": 43, "clarify": 2, "wrong_card": 1},
    (DEEPSEEK, "M2"): {"correct": 46, "clarify": 4},
    (SONNET, "M2"): {"correct": 46, "clarify": 3, "wrong_read": 1},
}
# REPLAY: what the current code gives the recorded answers.
REPLAY = {
    (DEEPSEEK, "M1"): {"correct": 38, "clarify": 7, "wrong_card": 1},      # equal to the published counts until BL7-4 (the scorer follows the product for a mail write: a card the product does not open is a clarify): 41/4/1 -> 38/7/1
    (SONNET, "M1"): {"correct": 41, "clarify": 5},      # BL7-1 (the line's subject stays in a message's target): dev-pt-br-50007 run 2, wrong_card -> correct, 44/2; BL7-4: 41/5; the PUBLISHED counts above stay as they were
    (DEEPSEEK, "M2"): {"correct": 43, "clarify": 7},      # BL7-4: 46/4 -> 43/7
    (SONNET, "M2"): {"correct": 43, "clarify": 6, "wrong_read": 1},      # BL7-4: 46/3/1 -> 43/6/1
}


@pytest.fixture
def recorded_catalog(monkeypatch):
    """The catalog the answers were recorded with, in the place of the served one (the served file is not touched), as the replay gate does."""
    recorded = json.loads(RECORDED_CATALOG.read_text(encoding="utf-8"))
    assert interpreter.catalog_sha256(recorded) == PINNED_HASHES["interpreter_catalog_blite"]
    for module in {interpreter, ops_interpret.interpreter}:
        monkeypatch.setattr(module, "SERVED", recorded)
        monkeypatch.setattr(module, "SERVED_SHA256", PINNED_HASHES["interpreter_catalog_blite"])
    monkeypatch.setattr(interpreter_pipeline, "SERVED", recorded)
    monkeypatch.setattr(interpreter_pipeline, "ALLOWED", frozenset(row["op"] for row in recorded["ops"]))
    return recorded


def worst_counts(rows) -> dict:
    """The category counts of the worst run of each item, zeros left out."""
    score = interpreter_measure.score
    return {c: n for c, n in collections.Counter(r["category"] for r in score.worst_of_runs(rows).values()).items() if n}


def replay(path: Path, corpus: Path) -> list:
    """The scored rows of an answers file with no call."""
    header, found = interpreter_measure.read_answers(str(path))
    items, _ = interpreter_measure.load_corpus(str(corpus))
    route = interpreter_route.find(header["route"])
    chosen = interpreter_measure.draw(items, header["sample"]["n"], header["sample"]["seed"], header["sequential"]) if header["sample"] else items
    answers = interpreter_measure.Answers("replay", header, found, None)
    done = interpreter_measure.run_all(chosen, header["runs"], 1, answers, route)
    rows, _, _ = interpreter_measure.score_runs(chosen, header["runs"], done, None, None)
    return rows


def evidence_worst(name: str) -> dict:
    """The published counts, read from an evidence file: the worst category of the runs of each item."""
    score = interpreter_measure.score
    worst = {}
    for raw in (EVIDENCE / name).read_text(encoding="utf-8").splitlines():
        line = json.loads(raw)
        if line["record"] == "item":
            held = worst.get(line["item"])
            if held is None or score.RANK[line["category"]] < score.RANK[held]:
                worst[line["item"]] = line["category"]
    return dict(collections.Counter(worst.values()))


def path_of(key) -> Path:
    return FOLDER / "replay" / ANSWERS[key][0]


@pytest.mark.parametrize("key", sorted(ANSWERS))
def test_the_published_counts_are_the_counts_of_the_evidence_files(key):
    assert evidence_worst(ANSWERS[key][1]) == PUBLISHED[key]


@pytest.mark.parametrize("key", sorted(ANSWERS))
def test_every_header_names_the_catalog_and_the_prompt_of_the_run_and_the_corpus_it_was_recorded_on(key):
    header, _ = interpreter_measure.read_answers(str(path_of(key)))
    assert header["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_blite"]
    assert header["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_1423"]
    assert header["corpus_sha256"] == hashlib.sha256(ANSWERS[key][2].read_bytes()).hexdigest()      # v2 and dev.jsonl are unchanged byte for byte
    assert header["test"] in ANSWERS[key][1]


@pytest.mark.parametrize("key", sorted(ANSWERS))
def test_the_replay_of_the_current_code_gives_the_recorded_counts(key, recorded_catalog):
    assert worst_counts(replay(path_of(key), ANSWERS[key][2])) == REPLAY[key]


def test_vacuity_one_recorded_answer_altered_in_a_copy_changes_the_counts(tmp_path, recorded_catalog):
    copy = tmp_path / "answers.jsonl"
    shutil.copy(path_of((DEEPSEEK, "M1")), copy)
    lines = copy.read_text(encoding="utf-8").splitlines()
    for n, raw in enumerate(lines[1:], 1):
        record = json.loads(raw)
        if record["ok"] and '"kind":"op"' in record["text"] and record["item"].startswith("dev-en"):
            record["text"] = '{"v":1,"kind":"none"}'      # the planted fault: an operation the model named becomes "nothing to do"
            lines[n] = json.dumps(record, sort_keys=True, separators=(",", ":"))
            break
    else:
        pytest.fail("no operation answer of an English item was found to alter")
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert worst_counts(replay(copy, V2)) != REPLAY[(DEEPSEEK, "M1")]
