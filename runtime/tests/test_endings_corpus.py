"""The corpus of archived lab runs (runtime/tests/corpus/endings.jsonl) is well formed, and the classifier of
endings never guesses on it. Offline: the corpus is a file; no model is called.

The corpus is built by runtime/tests/corpus/build_corpus.py from an archive of lab runs. This file checks its
form, the two things the first classifier must already hold on every line, and the total classifier (with the
facts of each line's skill, manifest.ending_facts): invariants on every line, the labels a person read
(runtime/tests/corpus/labels.json), and two ceilings on what stays unclassified, which only go down.

A corpus line does not record what the run's copy held, so no line carries `outputs_present`: the rule that names
a run that changed nothing `done` because its output is already there never fires here (test_endings_total.py
tests it).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_endings_corpus.py
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
endings = importlib.import_module("endings")
manifest = importlib.import_module("manifest")
CORPUS = REPO / "runtime" / "tests" / "corpus" / "endings.jsonl"
LABELS = REPO / "runtime" / "tests" / "corpus" / "labels.json"
# Labelled stand-ins: lines in the corpus's form, with invented content, for a reply shape a real run showed after
# the corpus was built (the corpus itself is what build_corpus.py writes from the archive, so nothing is added to
# it). Their ids start with "standin/"; they are read by the label test only, never by the counts.
STANDINS = REPO / "runtime" / "tests" / "corpus" / "standins.jsonl"
# Set to the counts `python3 runtime/endings.py --corpus runtime/tests/corpus/endings.jsonl` printed after the
# tuning of stage 2 (WP-2.2). Lowering one is always allowed; raising one needs a sentence in the pull request.
UNCLASSIFIED_STOPPED_MAX = 115
UNCLASSIFIED_CHANGED_MAX = 43
# The measured share of the stopped lines whose guard passed that are classified question or blocked (361 of 468),
# rounded down to two decimals.
STOPS_RECOGNISED_MIN = 0.77
KEYS = {"id", "skill", "case", "tier", "response", "created", "modified", "deleted", "stopped", "outputs_written",
        "stop_reason", "guards", "pass_rate"}


def lines():
    return [json.loads(line) for line in CORPUS.read_text(encoding="ascii").splitlines()]


def test_the_corpus_is_sorted_has_closed_keys_and_holds_runs_of_both_tiers():
    rows = lines()
    assert len(rows) >= 400 and [r["id"] for r in rows] == sorted({r["id"] for r in rows})
    for r in rows:
        assert set(r) == KEYS, r["id"]
        assert r["tier"] in ("strong", "floor") and isinstance(r["response"], str)
        assert r["stopped"] == (not (r["created"] or r["modified"] or r["deleted"])), r["id"]
        assert set(r["outputs_written"]) <= set(r["created"] + r["modified"]), r["id"]
        assert r["guards"] is None or all(set(g) == {"position", "passed"} for g in r["guards"]), r["id"]
    assert {r["tier"] for r in rows} == {"strong", "floor"} and len({r["skill"] for r in rows}) >= 40
    assert (REPO / "skills" / rows[0]["skill"]).is_dir()


def standins():
    return [json.loads(line) for line in STANDINS.read_text(encoding="ascii").splitlines()]


def test_the_stand_ins_have_the_corpus_form_and_are_not_in_the_corpus():
    rows, ids = standins(), {r["id"] for r in lines()}
    assert rows
    for r in rows:
        assert set(r) == KEYS and r["id"].startswith("standin/") and r["id"] not in ids, r["id"]
        assert r["stopped"] == (not (r["created"] or r["modified"] or r["deleted"])), r["id"]
        assert set(r["outputs_written"]) <= set(r["created"] + r["modified"]), r["id"]
        assert (REPO / "skills" / r["skill"]).is_dir(), r["id"]


def test_the_classifier_answers_within_its_closed_list_and_never_calls_a_run_that_wrote_nothing_done():
    counts = {}
    for r in lines():
        changes = {"created": r["created"], "modified": r["modified"], "deleted": r["deleted"], "unchanged": []}
        ending, why = endings.classify(r["response"], changes, r["outputs_written"], [], [])
        assert ending in endings.ENDINGS and why, r["id"]
        if r["stopped"]:
            assert ending in ("question", "unclassified"), r["id"]
        else:
            assert ending != "question", r["id"]
        if not r["outputs_written"]:
            assert ending not in ("done", "draft_with_questions"), r["id"]
        counts[ending] = counts.get(ending, 0) + 1
    assert counts.get("question", 0) > 0 and counts.get("done", 0) > 0 and counts.get("unclassified", 0) > 0


def classified(rows=None):
    """[(line, ending)] for every corpus line (or the lines given), with the facts of its skill."""
    facts, out = {}, []
    for r in lines() if rows is None else rows:
        if r["skill"] not in facts:
            facts[r["skill"]] = manifest.ending_facts(str(REPO), r["skill"])
        out.append((r, endings.classify_line(r, facts[r["skill"]])[0]))
    return out


def test_no_run_that_changed_no_file_is_called_done_or_a_draft():
    for r, ending in classified():
        if r["stopped"]:
            assert ending in ("question", "blocked", "unclassified"), (r["id"], ending)


def test_no_run_is_called_done_when_its_skill_declares_a_fixed_output_and_wrote_none():
    fixed = {}
    for r, ending in classified():
        if r["skill"] not in fixed:
            fixed[r["skill"]] = manifest.ending_facts(str(REPO), r["skill"])["fixed_output"]
        if not r["stopped"] and not r["outputs_written"] and fixed[r["skill"]]:
            assert ending not in ("done", "draft_with_questions"), (r["id"], ending)


def test_every_labelled_run_gets_its_label():
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    got = {r["id"]: ending for r, ending in classified(lines() + standins())}
    assert labels and set(labels.values()) <= set(endings.ENDINGS)
    wrong = {i: (want, got.get(i)) for i, want in labels.items() if got.get(i) != want}
    assert not wrong, f"labelled runs classified otherwise (label, classifier): {wrong}"


def test_the_number_of_unclassified_runs_does_not_grow():
    rows = classified()
    stopped = sum(1 for r, e in rows if r["stopped"] and e == "unclassified")
    changed = sum(1 for r, e in rows if not r["stopped"] and e == "unclassified")
    assert stopped <= UNCLASSIFIED_STOPPED_MAX and changed <= UNCLASSIFIED_CHANGED_MAX, (stopped, changed)


def test_the_runs_the_guards_say_stopped_correctly_are_recognised_as_stops():
    rows = [(r, e) for r, e in classified() if r["stopped"] and r["guards"] and any(g["passed"] for g in r["guards"])]
    share = sum(1 for _, e in rows if e in ("question", "blocked")) / len(rows)
    assert rows and share >= STOPS_RECOGNISED_MIN, share
