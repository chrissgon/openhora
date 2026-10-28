"""The recorded answers of the B-double-prime-lite measurement (package BL5A): four answers files (the long set M1 and the 50-item regression draw M2, on DeepSeek and on Sonnet),
their four evidence files and the catalog they were recorded with, replayed with no call.

Two kinds of literal, kept apart because later code changes move one and never the other:
  PUBLISHED  the counts the first measurement published (worst category of the runs of each item), read here from the four evidence files and never re-scored: they are what happened;
  REPLAY     the counts the CURRENT code gives the recorded answers (the catalog they were recorded with put in the place of the served one, as the replay gate does). A package that
             changes the check updates these, with its reason, and never the published ones. The M1 files are replayed twice: with the golds of `dev-long-v1.jsonl` (equal to the
             published counts today) and with the golds of `dev-long-v2.jsonl` (a labelled re-score under rule W1, written after the answers were seen: not blind, not a measurement).
The test builds `Answers("replay", ...)` directly, as the replay gate does, so it keeps working when the served prompt changes (the command-line replay then refuses these files by their
header, which is correct). The data files it reads are named below, so the test selector picks it when one changes: evals/interpreter/dev-long-v1.jsonl,
evals/interpreter/dev-long-v2.jsonl, evals/interpreter/dev.jsonl, evals/interpreter/replay/catalogs/catalog-a77f8a8f.json, the four answers files under
evals/interpreter/replay/*/blite-20261025/ and the four evidence files evals/interpreter/evidence/ix-20261025T03*.jsonl. Offline, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_blite_replay.py
"""
from __future__ import annotations

import collections
import hashlib
import json
import shutil
import subprocess
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
V1 = FOLDER / "dev-long-v1.jsonl"
V2 = FOLDER / "dev-long-v2.jsonl"
DEV = FOLDER / "dev.jsonl"
RECORDED_CATALOG = FOLDER / "replay" / "catalogs" / "catalog-a77f8a8f.json"
EVIDENCE = FOLDER / "evidence"
TOOL = REPO / "scripts" / "interpreter_corpus.py"
DEEPSEEK, SONNET = "or-deepseek-v4.1-flash", "acct-claude-sonnet-5.5"
RUN = "blite-20261025"
ANSWERS = {   # (route, set) -> (the answers file, its evidence file, the corpus it was recorded on)
    (DEEPSEEK, "M1"): (f"{DEEPSEEK}/{RUN}/M1/20261025T033351Z-4d5c4ce4.answers.jsonl", "ix-20261025T033351Z-4d5c4ce4.jsonl", V1),
    (DEEPSEEK, "M2"): (f"{DEEPSEEK}/{RUN}/M2/20261025T033519Z-4ffcb9b2.answers.jsonl", "ix-20261025T033519Z-4ffcb9b2.jsonl", DEV),
    (SONNET, "M1"): (f"{SONNET}/{RUN}/M1/20261025T033607Z-72f2f30b.answers.jsonl", "ix-20261025T033607Z-72f2f30b.jsonl", V1),
    (SONNET, "M2"): (f"{SONNET}/{RUN}/M2/20261025T034023Z-0b0cc69e.answers.jsonl", "ix-20261025T034023Z-0b0cc69e.jsonl", DEV),
}
# PUBLISHED: worst category of the runs of each item, as the first measurement's summaries counted it.
PUBLISHED = {
    (DEEPSEEK, "M1"): {"correct": 27, "clarify": 13, "wrong_card": 6},
    (SONNET, "M1"): {"correct": 31, "clarify": 9, "wrong_card": 6},
    (DEEPSEEK, "M2"): {"correct": 45, "clarify": 4, "missed": 1},
    (SONNET, "M2"): {"correct": 46, "clarify": 3, "wrong_read": 1},
}
# REPLAY: what the current code gives the recorded answers.
REPLAY = {      # M1 moved by BL5C (the old day of a change, the trigger word of a time span: SPEC-BLITE-5C) and by BL5B (a no with a new detail after "Posso?" is a revised op: four items, dev-pt-br-50016, dev-en-50008, dev-pt-br-50017, dev-pt-br-50023), not by a gold; M2 did not move
    (DEEPSEEK, "M1"): {"correct": 34, "clarify": 8, "wrong_card": 4},      # BL5C: 31/9/6 before BL5B; BL7-1 (the line's subject stays in a message's target) 35/5/6; BL7-4 (the scorer follows the product for a mail write): 34/8/4
    (SONNET, "M1"): {"correct": 38, "clarify": 5, "wrong_card": 3},      # BL5C: 34/6/6 before BL5B; BL7-4: 38/2/6 -> 38/5/3 (three cards the product does not open are clarify)
    (DEEPSEEK, "M2"): {"correct": 43, "clarify": 6, "missed": 1},      # BL7-5 (a believed message number opens the family when the closed forms read none; a long sender-and-subject target is grounded): 42/7 -> 43/6 (dev-pt-br-00035); BL7-4: 45/4/1 -> 42/7/1, three correct items the product asks about
    (SONNET, "M2"): {"correct": 44, "clarify": 5, "wrong_read": 1},      # BL7-5 (a believed message number opens the family when the closed forms read none; a long sender-and-subject target is grounded): 43/6 -> 44/5 (dev-pt-br-00035); BL7-4: 46/3/1 -> 43/6/1
}
# REPLAY, re-score under the golds of dev-long-v2.jsonl (rule W1): labelled "not blind" wherever it is published.
REPLAY_V2 = {
    (DEEPSEEK, "M1"): {"correct": 38, "clarify": 8},      # BL5C: 32/13/1 before; BL5C then BL5B: 36/9/1 then 40/5/1; BL7-1 (the line's subject stays in a message's target): dev-pt-br-50007 run 1, wrong_card -> correct, 41/5; BL7-4 (the scorer follows the product for a mail write): 38/8 (answers recorded at the OLD prompt: what the code does with them, not what the new prompt makes a model say)
    (SONNET, "M1"): {"correct": 41, "clarify": 5},      # BL5C: 37/9 before; BL5C then BL5B: 40/6 then 44/2; BL7-4: 41/5
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


def replay(path: Path, corpus: Path, golds: Path = None) -> list:
    """The scored rows of an answers file with no call; `golds`, when given, is the file whose gold and also score the runs."""
    header, found = interpreter_measure.read_answers(str(path))
    items, _ = interpreter_measure.load_corpus(str(corpus))
    route = interpreter_route.find(header["route"])
    chosen = interpreter_measure.draw(items, header["sample"]["n"], header["sample"]["seed"], header["sequential"]) if header["sample"] else items
    answers = interpreter_measure.Answers("replay", header, found, None)
    done = interpreter_measure.run_all(chosen, header["runs"], 1, answers, route)
    if golds is not None:
        graded, _ = interpreter_measure.load_golds(str(golds), items)
        by_id = {i["id"]: i for i in graded}
        chosen = [by_id[i["id"]] for i in chosen]
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
    assert header["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_5bee"]
    assert header["corpus_sha256"] == hashlib.sha256(ANSWERS[key][2].read_bytes()).hexdigest()      # v1 and dev.jsonl are unchanged byte for byte
    assert header["test"] in ANSWERS[key][1]


@pytest.mark.parametrize("key", sorted(ANSWERS))
def test_the_replay_of_the_current_code_gives_the_recorded_counts(key, recorded_catalog):
    assert worst_counts(replay(path_of(key), ANSWERS[key][2])) == REPLAY[key]


@pytest.mark.parametrize("key", sorted(REPLAY_V2))
def test_the_re_score_under_the_golds_of_v2_gives_the_labelled_counts(key, recorded_catalog):
    assert worst_counts(replay(path_of(key), V1, golds=V2)) == REPLAY_V2[key]


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
    assert worst_counts(replay(copy, V1)) != REPLAY[(DEEPSEEK, "M1")]


def test_the_golds_of_v2_are_rule_w1_applied_to_v1_byte_for_byte():
    done = subprocess.run([sys.executable, str(TOOL), "widen-golds", "--in", str(V1)], capture_output=True, timeout=120)
    assert done.returncode == 0
    assert done.stdout == V2.read_bytes()


def test_a_golds_re_score_never_writes_evidence(tmp_path, monkeypatch, capsys, recorded_catalog):
    """The command-line path of a re-score, with the header check set aside (it is not what is tested here): the summary is labelled and no evidence file appears."""
    monkeypatch.setattr(interpreter_measure, "differing", lambda header, wanted: "")
    monkeypatch.setattr(interpreter_measure.evidence, "EVIDENCE_DIR", str(tmp_path))
    before = sorted(p.name for p in EVIDENCE.iterdir())
    code = interpreter_measure.main(["--corpus", str(V1), "--route", DEEPSEEK, "--runs", "2", "--replay", str(path_of((DEEPSEEK, "M1")).parent), "--golds", str(V2), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["rescore"] is True and out["golds_file"] == "dev-long-v2.jsonl" and out["golds_sha256"] == hashlib.sha256(V2.read_bytes()).hexdigest()
    assert {c: n for c, n in out["measures"]["counts"].items() if n} == REPLAY_V2[(DEEPSEEK, "M1")]
    assert list(tmp_path.iterdir()) == [] and sorted(p.name for p in EVIDENCE.iterdir()) == before


def test_golds_without_replay_is_a_usage_error(capsys):
    code = interpreter_measure.main(["--corpus", str(V1), "--route", DEEPSEEK, "--runs", "2", "--golds", str(V2)])
    assert code == 2 and "--replay" in capsys.readouterr().err


def planted(tmp_path, edit) -> Path:
    items = [json.loads(raw) for raw in V2.read_text(encoding="utf-8").splitlines()]
    edit(items)
    path = tmp_path / "golds.jsonl"
    path.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for i in items), encoding="utf-8")
    return path


@pytest.mark.parametrize("key", ("line", "frame", "clock"))
def test_vacuity_a_golds_file_with_one_changed_line_frame_or_clock_is_refused(tmp_path, key):
    def edit(items):
        item = next(i for i in items if (i["frame"] is not None if key == "frame" else True))
        item[key] = {"line": item["line"] + " x", "clock": "2026-10-27T09:31", "frame": None}[key]      # the planted change
    items, _ = interpreter_measure.load_corpus(str(V1))
    with pytest.raises(interpreter_measure.Refused) as caught:
        interpreter_measure.load_golds(str(planted(tmp_path, edit)), items)
    assert f"in {key}" in str(caught.value) and "item dev-" in str(caught.value)


def test_vacuity_a_golds_file_with_a_missing_id_is_refused(tmp_path):
    items, _ = interpreter_measure.load_corpus(str(V1))
    with pytest.raises(interpreter_measure.Refused) as caught:
        interpreter_measure.load_golds(str(planted(tmp_path, lambda rows: rows.pop())), items)
    assert str(caught.value).startswith("the golds file lacks item dev-")


def test_the_golds_of_v2_change_only_gold_slots_of_span_kind():
    """W1 adds no content word and touches no op, outcome, frame, time or time slot: every key but gold.slots equals v1, and in the gold only span lists grew."""
    one = [json.loads(raw) for raw in V1.read_text(encoding="utf-8").splitlines()]
    two = [json.loads(raw) for raw in V2.read_text(encoding="utf-8").splitlines()]
    assert [i["id"] for i in one] == [i["id"] for i in two]
    grew = 0
    for a, b in zip(one, two):
        assert {k: v for k, v in a.items() if k != "gold"} == {k: v for k, v in b.items() if k != "gold"}
        assert {k: v for k, v in a["gold"].items() if k != "slots"} == {k: v for k, v in b["gold"].items() if k != "slots"}
        for slot, accepted in a["gold"].get("slots", {}).items():
            assert set(accepted) <= set(b["gold"]["slots"][slot])
            if set(accepted) != set(b["gold"]["slots"][slot]):
                grew += 1
                assert (a["gold"]["op"], slot) not in {("remind", "when"), ("event-create", "time"), ("event-change", "time")}
                assert all(piece in a["line"] for piece in b["gold"]["slots"][slot])      # every accepted piece stands in the line
    assert grew > 0
