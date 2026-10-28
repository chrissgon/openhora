"""The recorded answers of the blind B-double-prime-lite measurement of 2026-10-26 (package BL7-0): two answers files (DeepSeek and Sonnet, 2 runs over the 60 lines of
`blite-blind-v2.jsonl`) and their two evidence files, replayed with no call. The set is spent: this is the blind number, and every later replay of these answers is a dev re-score.

Two kinds of literal, kept apart because later code changes move one and never the other:
  PUBLISHED  the counts and rates the measurement published (worst category of the 2 runs of each item), read here from the two evidence files and never re-scored: they are what happened;
  REPLAY     the counts the CURRENT code gives the recorded answers (the catalog they were recorded with, the same as the earlier long-set runs', put in the place of the served one, as
             the replay gate does). A package that changes the check updates these, with its reason, and never the published ones.
The test builds `Answers("replay", ...)` directly, as the replay gate does, so it keeps working when the served prompt changes (the command-line replay then refuses these files by their
header, which is correct, and refuses answers inside the checkout for a test-split corpus, by design: the test does not use the command line). The data files it reads are named below, so
the test selector picks it when one changes: evals/interpreter/blite-blind-v1.jsonl, evals/interpreter/blite-blind-v2.jsonl, evals/interpreter/blite-blind-v2-split.json,
evals/interpreter/replay/catalogs/catalog-a77f8a8f.json, the two answers files under evals/interpreter/replay/*/blind-20261026/ and the two evidence files
evals/interpreter/evidence/ix-20261026T025216Z-aa31e463.jsonl and ix-20261026T025351Z-4b4e44f0.jsonl.
Offline, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_blind_replay.py
"""
from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import shutil
import sys
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
V1 = FOLDER / "blite-blind-v1.jsonl"
V2 = FOLDER / "blite-blind-v2.jsonl"
SPLIT = FOLDER / "blite-blind-v2-split.json"
RECORDED_CATALOG = FOLDER / "replay" / "catalogs" / "catalog-a77f8a8f.json"
EVIDENCE = FOLDER / "evidence"
DEEPSEEK, SONNET = "or-deepseek-v4.1-flash", "acct-claude-sonnet-5.5"
RUN = "blind-20261026"
V1_SHA256 = "0912d128331db46e28a35c7e180355f19330d125af7d60c8ae0dceb9fc17dc4d"      # never measured: published as history
ANSWERS = {   # route -> (the answers file, its evidence file)
    DEEPSEEK: (f"{DEEPSEEK}/{RUN}/20261026T025216Z-aa31e463.answers.jsonl", "ix-20261026T025216Z-aa31e463.jsonl"),
    SONNET: (f"{SONNET}/{RUN}/20261026T025351Z-4b4e44f0.answers.jsonl", "ix-20261026T025351Z-4b4e44f0.jsonl"),
}
# PUBLISHED: worst category of the 2 runs of each item (60 items), as the run's summaries counted it.
PUBLISHED = {
    DEEPSEEK: {"correct": 48, "clarify": 7, "wrong_card": 3, "wrong_read": 1, "wrong_route": 1},
    SONNET: {"correct": 54, "clarify": 2, "wrong_card": 2, "wrong_read": 2},
}
# The published rates (RESULT of 2026-10-26, pass rules 2 and 3): correct_direct per language and overall, the clarify rate, the wrong_card point rate per language as (items, of).
PUBLISHED_RATES = {
    DEEPSEEK: {"correct_direct": {"pt-BR": 0.857, "en": 0.786, "all": 0.807}, "clarify_rate": 0.123, "wrong_card": {"pt-BR": (1, 30), "en": (2, 15)}},
    SONNET: {"correct_direct": {"pt-BR": 0.893, "en": 0.929, "all": 0.895}, "clarify_rate": 0.035, "wrong_card": {"pt-BR": (2, 30), "en": (0, 15)}},
}
# REPLAY: what the current code gives the recorded answers.
REPLAY = {
    DEEPSEEK: {"correct": 48, "clarify": 10, "wrong_read": 1, "wrong_route": 1},      # BL7-1 (the line's subject stays in a message's target, an inherit of a slot the line fills is dropped, a corrected read stays a read): 48/7/3 -> 53/5/0; then BL7-4 (the scorer follows the product for a mail write: a card the product does not open, a question it asks first, is a clarify): 53/5 -> 48/10, five correct items the product asks about; the dev re-score of the spent answers, not a blind number; the PUBLISHED counts above stay as they were
    SONNET: {"correct": 49, "clarify": 7, "wrong_card": 2, "wrong_read": 2},      # BL7-1 moves no Sonnet item; BL7-4 (the same scorer step): 54/2 -> 49/7, five correct items the product asks about
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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worst_counts(rows) -> dict:
    """The category counts of the worst run of each item, zeros left out."""
    score = interpreter_measure.score
    return {c: n for c, n in collections.Counter(r["category"] for r in score.worst_of_runs(rows).values()).items() if n}


def replay(path: Path, corpus: Path):
    """(the scored rows of an answers file with no call, the answers object that served them)."""
    header, found = interpreter_measure.read_answers(str(path))
    items, _ = interpreter_measure.load_corpus(str(corpus))
    route = interpreter_route.find(header["route"])
    answers = interpreter_measure.Answers("replay", header, found, None)
    done = interpreter_measure.run_all(items, header["runs"], 1, answers, route)
    rows, _, _ = interpreter_measure.score_runs(items, header["runs"], done, None, None)
    return rows, answers


def evidence_rows(name: str) -> list:
    """The item lines of an evidence file, as scored rows (item, lang, gold, category), one per run."""
    out = []
    for raw in (EVIDENCE / name).read_text(encoding="utf-8").splitlines():
        line = json.loads(raw)
        if line["record"] == "item":
            out.append({"item": line["item"], "lang": line["lang"], "gold": line["gold"], "category": line["category"]})
    return out


def path_of(route) -> Path:
    return FOLDER / "replay" / ANSWERS[route][0]


def folder_listing(folder: Path) -> list:
    return sorted(p.name for p in folder.iterdir())


def test_the_corpus_is_the_measured_one():
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    assert sha256(V2) == split["sha256"] == "984356db30069dcbc64c24b925ec975c031dd9049475a8e81fbb493a73db58f0"
    assert sha256(V1) == V1_SHA256      # v1 was never measured: it is history, and unchanged byte for byte
    items, _ = interpreter_measure.load_corpus(str(V2))
    assert len(items) == split["items"] == 60      # the summary states the number of items; the ids of the corpus are the ones the answers name
    ids = {item["id"] for item in items}
    for route in ANSWERS:
        assert {record["item"] for key, record in interpreter_measure.read_answers(str(path_of(route)))[1].items()} == ids


@pytest.mark.parametrize("route", sorted(ANSWERS))
def test_every_header_names_the_catalog_the_prompt_and_the_corpus_of_the_measurement(route):
    header, found = interpreter_measure.read_answers(str(path_of(route)))
    assert header["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_blite"]
    assert header["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_1423"]
    assert header["corpus_sha256"] == sha256(SPLIT) == "95b447d4d9e22b39b3c5dc7909b40e62698ef2ee3bc7c9b40eb6d994a53d49e3"      # a split-file event: the hash of the summary
    assert header["route"] == route and header["runs"] == 2 and len(found) == 120


@pytest.mark.parametrize("route", sorted(ANSWERS))
def test_the_published_counts_are_the_counts_of_the_evidence_files(route):
    rows = evidence_rows(ANSWERS[route][1])
    assert len(rows) == 120
    assert worst_counts(rows) == PUBLISHED[route]
    assert not [r for r in rows if r["category"] == "wrong_effect_unconfirmed"]


@pytest.mark.parametrize("route", sorted(ANSWERS))
def test_the_published_rates_are_the_rates_of_the_evidence_files(route):
    score = interpreter_measure.score
    worst = list(score.worst_of_runs(evidence_rows(ANSWERS[route][1])).values())
    published = PUBLISHED_RATES[route]
    overall = score.measures(worst)
    assert overall["correct_direct"] == pytest.approx(published["correct_direct"]["all"], abs=5e-4)
    assert overall["clarify_rate"] == pytest.approx(published["clarify_rate"], abs=5e-4)
    for lang in ("pt-BR", "en"):
        by_lang = score.measures([r for r in worst if r["lang"] == lang])
        assert by_lang["correct_direct"] == pytest.approx(published["correct_direct"][lang], abs=5e-4)
        assert (by_lang["counts"]["wrong_card"], by_lang["n"]) == published["wrong_card"][lang]


@pytest.mark.parametrize("route", sorted(ANSWERS))
def test_the_replay_of_the_current_code_gives_the_recorded_counts(route, recorded_catalog):
    rows, _ = replay(path_of(route), V2)
    assert worst_counts(rows) == REPLAY[route]


def test_a_replay_never_writes_evidence_and_makes_no_call(recorded_catalog):
    before = folder_listing(EVIDENCE)
    for route in sorted(ANSWERS):
        _, answers = replay(path_of(route), V2)
        assert answers.live_calls == 0 and answers.handle is None      # no call was made, and no file was opened for writing
    assert folder_listing(EVIDENCE) == before


def test_the_two_events_are_published_apart_from_the_gate_by_the_status_script():
    spec = importlib.util.spec_from_file_location("interpreter_status_blind_test", REPO / "evals" / "interpreter_status.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    result = module.status(str(REPO))
    held = {entry["test"]: entry for entry in result["heldout"] if entry["set"] == SPLIT.name}
    assert set(held) == {"20261026T025216Z-aa31e463", "20261026T025351Z-4b4e44f0"}
    assert {entry["route"] for entry in held.values()} == {DEEPSEEK, SONNET}
    for route, (_, name) in ANSWERS.items():
        entry = held[name.removeprefix("ix-").removesuffix(".jsonl")]
        assert entry["items"] == 60 and entry["runs"] == 2 and entry["corpus_sha256"] == sha256(SPLIT)
        assert {c: n for c, n in entry["measures"]["counts"].items() if n} == PUBLISHED[route]
    for row in result["rows"]:      # no band, cause or go input reads them
        assert not any(test in json.dumps(row) for test in held)


def test_vacuity_one_recorded_answer_altered_in_a_copy_changes_the_counts(tmp_path, recorded_catalog):
    copy = tmp_path / "answers.jsonl"
    shutil.copy(path_of(DEEPSEEK), copy)
    lines = copy.read_text(encoding="utf-8").splitlines()
    for n, raw in enumerate(lines[1:], 1):
        record = json.loads(raw)
        if record["ok"] and '"kind":"op"' in record["text"] and record["item"].startswith("test-en"):
            record["text"] = '{"v":1,"kind":"none"}'      # the planted fault: an operation the model named becomes "nothing to do"
            lines[n] = json.dumps(record, sort_keys=True, separators=(",", ":"))
            break
    else:
        pytest.fail("no operation answer of an English item was found to alter")
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows, _ = replay(copy, V2)
    assert worst_counts(rows) != REPLAY[DEEPSEEK]
