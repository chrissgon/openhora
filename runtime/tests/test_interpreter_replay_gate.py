"""The regression gate of the interpreter in use (slice S1): the recorded answers of the development pilots, replayed with no call, still give the counts the evidence states, and the
decision the runtime takes for an answer is the decision the measured pipeline took.

Two kinds of literal, kept apart because later code changes move one and never the other (BL7-4): PUBLISHED, the counts the evidence files state (what happened, never re-scored), and
REPLAY, the counts the CURRENT code gives the recorded answers. A package that changes the check or the mapping updates REPLAY, with its reason, and never PUBLISHED or an evidence file.

The three answer files recorded at the prompt `5bee55ce...` (DeepSeek iteration 2, Sonnet and Haiku on the maintainer's account; the prompt in use until BL5B added rule 9 on 2026-10-25, so they are
kept now as a regression of the CODE on answers recorded at the previous prompt, and the CLI's header check refuses them) are replayed on `evals/interpreter/dev.jsonl`
with the pipeline of the measurement; the count of each category must equal the count of the evidence lines of the same test, written here as literals and read again from the evidence
file; for every replayed item that reached the model and has no frame, `ops_interpret.decide` (what the runtime calls on the model's text) gives the decision the pipeline gave. The two
files at the earlier prompt (`c492b43b...`) are refused by the replay's own header check. No model is called; a change of the prompt, the catalog, the protocol, the route or the code of
the checks fails this test. The recorded answers were made with the catalog `a43735d2...`, which a later slice changed (S8 added `file-read`): the gate keeps replaying them against a
committed copy of THAT catalog (`evals/interpreter/replay/catalogs/`), put in the place of the served one for the length of each replay, so that a change to the served catalog
neither weakens the gate nor changes what the recorded answers meant; every header must name that catalog's hash. The data files it reads are named below, so the test selector picks it when one changes (the interpreter data files: interpreter_prompt.txt,
interpreter_catalog.json, interpreter_protocol.json, interpreter_routes.json, interpreter_enable.json).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_replay_gate.py
"""
from __future__ import annotations

import collections
import json
import shutil
from pathlib import Path

import pytest

import standin_tree as st
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

ops_interpret = st.load("ops_interpret")
interpreter = st.load("interpreter")
interpreter_enable = st.load("interpreter_enable")
interpreter_measure = st.load("interpreter_measure")
interpreter_pipeline = st.load("interpreter_pipeline")
interpreter_route = st.load("interpreter_route")

REPO = Path(__file__).resolve().parents[2]
DATA_FILES = ("runtime/interpreter_prompt.txt", "runtime/interpreter_catalog.json", "runtime/interpreter_protocol.json", "runtime/interpreter_routes.json", "runtime/interpreter_enable.json")
CORPUS = REPO / "evals" / "interpreter" / "dev.jsonl"
REPLAY = REPO / "evals" / "interpreter" / "replay"
EVIDENCE = REPO / "evals" / "interpreter" / "evidence"
IN_USE = {   # answers file -> its evidence file
    "or-deepseek-v4.1-flash/iter-2-20261021T125017/20261021T155019Z-f148397b.answers.jsonl": "ix-20261021T155019Z-f148397b.jsonl",
    "acct-claude-sonnet-5.5/iter-1-20261021T154157/20261021T184159Z-cda87ebe.answers.jsonl": "ix-20261021T184159Z-cda87ebe.jsonl",
    "acct-claude-haiku-4.5/iter-1-20261021T154157/20261021T184159Z-7ceca7ad.answers.jsonl": "ix-20261021T184159Z-7ceca7ad.jsonl",
}
PUBLISHED = {   # answers file -> the counts of the categories of its 50 items, as the evidence files state them (never re-scored)
    "or-deepseek-v4.1-flash/iter-2-20261021T125017/20261021T155019Z-f148397b.answers.jsonl": {"clarify": 4, "correct": 46},
    "acct-claude-sonnet-5.5/iter-1-20261021T154157/20261021T184159Z-cda87ebe.answers.jsonl": {"clarify": 2, "correct": 48},
    "acct-claude-haiku-4.5/iter-1-20261021T154157/20261021T184159Z-7ceca7ad.answers.jsonl": {"clarify": 15, "correct": 32, "wrong_card": 2, "wrong_item_binding": 1},
}
REPLAY_COUNTS = {   # answers file -> what the current code gives the recorded answers
    # BL7-4 (the scorer follows the product for a mail write: a card the product does not open, a recipient, a body, a folder or a state it asks, is a clarify): 4 -> 7 and 2 -> 5 and 15 -> 18 clarify, the
    # same correct items less; the dev re-score of the recorded answers, never a published number
    "or-deepseek-v4.1-flash/iter-2-20261021T125017/20261021T155019Z-f148397b.answers.jsonl": {"clarify": 7, "correct": 43},
    "acct-claude-sonnet-5.5/iter-1-20261021T154157/20261021T184159Z-cda87ebe.answers.jsonl": {"clarify": 5, "correct": 45},
    "acct-claude-haiku-4.5/iter-1-20261021T154157/20261021T184159Z-7ceca7ad.answers.jsonl": {"clarify": 18, "correct": 29, "wrong_card": 2, "wrong_item_binding": 1},
}
EARLIER = ("or-deepseek-v4.1-flash/iter-1-20261021T094443/20261021T124445Z-ea9f0c2f.answers.jsonl", "or-deepseek-v4.1-flash/iter-1-20261021T094736/20261021T124738Z-d0fc5d83.answers.jsonl")
PROMPT_IN_USE = PINNED_HASHES["interpreter_prompt"]      # the prompt of this checkout (BL5B added rule 9 to it)
PROMPT_RECORDED = PINNED_HASHES["interpreter_prompt_5bee"]      # the prompt the in-use answers were recorded at: what every in-use header names
RECORDED_CATALOG = REPO / "evals" / "interpreter" / "replay" / "catalogs" / "catalog-a43735d2.json"
RECORDED_CATALOG_SHA256 = PINNED_HASHES["interpreter_catalog_before_s8"]      # a literal: the hash every in-use answers file names in its header (scripts/tests/pinned_hashes.json)


@pytest.fixture
def recorded_catalog(monkeypatch):
    """The catalog the answers were recorded with, in the place of the served one (the served file is not touched): the check, the pipeline and the runtime's `decide` all read it."""
    recorded = json.loads(RECORDED_CATALOG.read_text(encoding="utf-8"))
    assert interpreter.catalog_sha256(recorded) == RECORDED_CATALOG_SHA256
    for module in {interpreter, ops_interpret.interpreter}:
        monkeypatch.setattr(module, "SERVED", recorded)
        monkeypatch.setattr(module, "SERVED_SHA256", RECORDED_CATALOG_SHA256)
    monkeypatch.setattr(interpreter_pipeline, "SERVED", recorded)
    monkeypatch.setattr(interpreter_pipeline, "ALLOWED", frozenset(row["op"] for row in recorded["ops"]))
    return recorded


def replay(path: Path) -> tuple:
    """(chosen items, the scored runs [(item, run, outcome, category)], the answers) of the file, with no call."""
    header, found = interpreter_measure.read_answers(str(path))
    items, _ = interpreter_measure.load_corpus(str(CORPUS))
    route = interpreter_route.find(header["route"])
    chosen = interpreter_measure.draw(items, header["sample"]["n"], header["sample"]["seed"], header["sequential"])
    answers = interpreter_measure.Answers("replay", header, found, None)
    done = interpreter_measure.run_all(chosen, header["runs"], 1, answers, route)
    rows, _, scored = interpreter_measure.score_runs(chosen, header["runs"], done, None, None)
    return chosen, scored, rows, found


def evidence_counts(name: str) -> dict:
    lines = [json.loads(line) for line in (EVIDENCE / name).read_text(encoding="utf-8").splitlines()]
    return dict(collections.Counter(line["category"] for line in lines if line["record"] == "item"))


def test_the_data_files_the_gate_depends_on_exist_and_the_prompt_in_use_is_the_checkouts():
    assert all((REPO / rel).is_file() for rel in DATA_FILES)
    assert interpreter.prompt_sha256() == PROMPT_IN_USE


@pytest.mark.parametrize("name", sorted(IN_USE))
def test_the_replay_gives_the_counts_of_the_evidence(name, recorded_catalog):
    chosen, scored, rows, _ = replay(REPLAY / name)
    got = dict(collections.Counter(row["category"] for row in rows))
    assert got == REPLAY_COUNTS[name], f"{name}: the replay of the current code is the REPLAY literal"
    assert PUBLISHED[name] == evidence_counts(IN_USE[name]), f"{name}: the PUBLISHED literal is what the evidence file states"
    assert len(chosen) == 50 and sum(got.values()) == 50


@pytest.mark.parametrize("name", sorted(IN_USE))
def test_the_decision_of_the_runtime_for_a_recorded_answer_is_the_decision_of_the_measured_pipeline(name, recorded_catalog):
    chosen, scored, rows, found = replay(REPLAY / name)
    compared = 0
    for item, run, outcome, category in scored:
        if outcome["stage"] != "model" or item["frame"] is not None or outcome["call"] is None:
            continue
        record = found[(item["id"], run)]
        decision = ops_interpret.decide(item["line"], record["text"], interpreter_pipeline.now_of(item), item["zone"], interpreter_pipeline.ALLOWED)
        seen = interpreter_pipeline.with_mail_step(decision, item["line"], interpreter_pipeline.now_of(item), item["zone"], item["lang"])          # BL7-4: the measurement's own step for a mail write
        assert interpreter_pipeline.observe(seen) == (outcome["observed"], outcome["detail"]), item["id"]
        compared += 1
    assert compared >= 35, "most of the sample reaches the model with no frame"


@pytest.mark.parametrize("name", EARLIER)
def test_an_answers_file_at_the_earlier_prompt_is_refused_by_the_header_check(name):
    header, _ = interpreter_measure.read_answers(str(REPLAY / name))
    items, data = interpreter_measure.load_corpus(str(CORPUS))
    wanted = interpreter_measure.header_of("", interpreter_route.find(header["route"]), header["corpus_sha256"], header["runs"], header["sequential"], header["sample"])
    assert header["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_earlier"]
    assert interpreter_measure.differing(header, wanted) == "prompt_sha256"


def test_vacuity_one_recorded_answer_altered_in_a_copy_changes_the_counts(tmp_path, recorded_catalog):
    name = "or-deepseek-v4.1-flash/iter-2-20261021T125017/20261021T155019Z-f148397b.answers.jsonl"
    copy = tmp_path / "answers.jsonl"
    shutil.copy(REPLAY / name, copy)
    lines = copy.read_text(encoding="utf-8").splitlines()
    for n, raw in enumerate(lines[1:], 1):
        record = json.loads(raw)
        if record["ok"] and '"kind":"op"' in record["text"] and "dev-en" in record["item"]:
            record["text"] = '{"v":1,"kind":"none"}'      # the planted fault: an operation the model named becomes "nothing to do"
            lines[n] = json.dumps(record, sort_keys=True, separators=(",", ":"))
            break
    copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, _, rows, _ = replay(copy)
    assert dict(collections.Counter(row["category"] for row in rows)) != REPLAY_COUNTS[name]


@pytest.mark.parametrize("name", sorted(IN_USE))
def test_every_in_use_answers_file_names_the_catalog_it_was_recorded_with(name):
    header, _ = interpreter_measure.read_answers(str(REPLAY / name))
    assert header["catalog_sha256"] == RECORDED_CATALOG_SHA256
    assert header["prompt_sha256"] == PROMPT_RECORDED != PROMPT_IN_USE


@pytest.mark.parametrize("name", sorted(IN_USE))
def test_the_header_check_of_the_cli_refuses_an_in_use_file_by_its_prompt_since_the_prompt_changed(name):
    """The in-use files are kept as a regression of the CODE on answers recorded at the previous prompt (the tests above build `Answers` directly); a measurement run by the CLI refuses them."""
    header, _ = interpreter_measure.read_answers(str(REPLAY / name))
    items, data = interpreter_measure.load_corpus(str(CORPUS))
    wanted = interpreter_measure.header_of("", interpreter_route.find(header["route"]), header["corpus_sha256"], header["runs"], header["sequential"], header["sample"])
    assert interpreter_measure.differing(header, wanted) == "prompt_sha256" and wanted["prompt_sha256"] == PROMPT_IN_USE


def test_the_served_catalog_is_no_longer_the_recorded_one_and_the_gate_does_not_read_it():
    """The slice that added `file-read` changed the served catalog; the gate replays the recorded copy, so the two differ and only the copy matters to it."""
    assert interpreter.SERVED_SHA256 != RECORDED_CATALOG_SHA256
    recorded = {row["op"] for row in json.loads(RECORDED_CATALOG.read_text(encoding="utf-8"))["ops"]}
    served = {row["op"] for row in interpreter.SERVED["ops"]}
    assert recorded < served and served - recorded == {"file-read", "research", "file-trash"}


def test_vacuity_a_recorded_copy_that_lost_an_operation_changes_the_replay(monkeypatch, tmp_path, recorded_catalog):
    """The planted fault: the copy of the recorded catalog is altered (an operation the recorded answers name is removed), and the counts or the hash no longer hold."""
    altered = json.loads(json.dumps(recorded_catalog))
    altered["ops"] = [row for row in altered["ops"] if row["op"] != "mail-trash"]
    assert interpreter.catalog_sha256(altered) != RECORDED_CATALOG_SHA256
    name = "or-deepseek-v4.1-flash/iter-2-20261021T125017/20261021T155019Z-f148397b.answers.jsonl"
    monkeypatch.setattr(interpreter_pipeline, "ALLOWED", frozenset(row["op"] for row in altered["ops"]))
    _, _, rows, _ = replay(REPLAY / name)
    assert dict(collections.Counter(row["category"] for row in rows)) != REPLAY_COUNTS[name]
