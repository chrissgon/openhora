"""Offline tests of check_explained.py: the shape, the closed words, the lengths, the quote-is-a-line grounding, the usage
errors and that the refused text never reaches the output.

Names are fictional and hosts are under .example. Nothing here opens a link.

Run: uv run --with pytest pytest skills/mkt-video-media-explain/scripts/tests
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_explained.py"
SLOTS = ["city-night", "poster"]
LINES = {"city-night": ["© StockPix Images", "PREVIEW ONLY"], "poster": ["promo.example"]}

GOOD = {
    "schema_version": 1,
    "slots": [
        {"slot": "city-night", "findings": [
            {"source": "text", "quote": "PREVIEW ONLY", "concern": "licence_mark", "explanation": "A stock preview mark: the picture is a sample, not the licensed file."}]},
        {"slot": "poster", "findings": [
            {"source": "qr", "quote": "promo.example", "concern": "link", "explanation": "The code leads to promo.example; anyone can point a phone at the video and open it."}]},
    ],
    "open": [],
}


def doc(**changes):
    out = copy.deepcopy(GOOD)
    out.update(changes)
    return out


def finding(**changes):
    out = copy.deepcopy(GOOD["slots"][0]["findings"][0])
    out.update(changes)
    return out


def run(tmp_path, data, slots=SLOTS, lines=None, raw=None, extra=()):
    path = tmp_path / "scan-explained.json"
    path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
    argv = [sys.executable, str(SCRIPT), "--file", str(path)]
    for slot in slots:
        argv += ["--slot", slot]
    if lines is not None:
        task = tmp_path / "task.json"
        task.write_text(json.dumps({"slots": lines}), encoding="utf-8")
        argv += ["--task-file", str(task)]
    done = subprocess.run(argv + list(extra), capture_output=True, text=True, timeout=30)
    return done, (json.loads(done.stdout) if done.stdout.strip() else None)


def codes(answer):
    return {e["code"] for e in answer["errors"]}


def test_a_good_file_passes(tmp_path):
    done, answer = run(tmp_path, GOOD)
    assert done.returncode == 0 and answer["ok"] is True and answer["summary"] == "ok: 2 findings in 2 slots"


def test_the_quotes_are_checked_against_the_task_lines(tmp_path):
    done, answer = run(tmp_path, GOOD, lines=LINES)
    assert done.returncode == 0 and answer["ok"] is True


def test_a_quote_the_task_did_not_give_is_refused_and_not_printed(tmp_path):
    bad = doc(slots=[{"slot": "city-night", "findings": [finding(quote="INVENTED QUOTE ZZ")]}, GOOD["slots"][1]])
    done, answer = run(tmp_path, bad, lines=LINES)
    assert done.returncode == 1 and "not_a_line_of_the_task" in codes(answer) and "INVENTED QUOTE ZZ" not in done.stdout


def test_without_a_task_file_the_quote_is_not_compared(tmp_path):
    bad = doc(slots=[{"slot": "city-night", "findings": [finding(quote="anything")]}, GOOD["slots"][1]])
    done, answer = run(tmp_path, bad)
    assert done.returncode == 0


@pytest.mark.parametrize("change,code", [
    ({"schema_version": 2}, "not_1"),
    ({"slots": "x"}, "not_a_list"),
    ({"open": "x"}, "not_a_list"),
    ({"extra": 1}, "unknown_key"),
    ({"open": [{"code": "other"}]}, "not_in_list"),
])
def test_file_level_rules(tmp_path, change, code):
    done, answer = run(tmp_path, doc(**change))
    assert done.returncode == 1 and code in codes(answer)


@pytest.mark.parametrize("change,code", [
    ({"source": "image"}, "not_in_list"),
    ({"concern": "safe"}, "not_in_list"),
    ({"quote": ""}, "not_text"),
    ({"quote": "x" * 201}, "too_long"),
    ({"explanation": "y" * 241}, "too_long"),
    ({"explanation": "See https://prize.example/claim for it."}, "web_address"),
    ({"explanation": "bad\u202etext"}, "bad_character"),
    ({"quote": "zero\u200bwidth"}, "bad_character"),
    ({"quote": 5}, "not_text"),
])
def test_finding_rules(tmp_path, change, code):
    bad = doc(slots=[{"slot": "city-night", "findings": [finding(**change)]}, GOOD["slots"][1]])
    done, answer = run(tmp_path, bad)
    assert done.returncode == 1 and code in codes(answer)


def test_a_finding_with_a_missing_or_extra_key_is_refused(tmp_path):
    missing = finding()
    del missing["concern"]
    for bad_finding in (missing, dict(finding(), note="x")):
        bad = doc(slots=[{"slot": "city-night", "findings": [bad_finding]}, GOOD["slots"][1]])
        done, answer = run(tmp_path, bad)
        assert done.returncode == 1 and "bad_keys" in codes(answer)


def test_slot_rules(tmp_path):
    unknown = doc(slots=[{"slot": "ghost", "findings": [finding()]}] + GOOD["slots"])
    assert "unknown_slot" in codes(run(tmp_path, unknown)[1])
    twice = doc(slots=GOOD["slots"] + [GOOD["slots"][0]])
    assert "duplicate_slot" in codes(run(tmp_path, twice)[1])
    lacking = doc(slots=[GOOD["slots"][0]])
    assert "slot_missing" in codes(run(tmp_path, lacking)[1])
    empty = doc(slots=[{"slot": "city-night", "findings": []}, GOOD["slots"][1]])
    assert "empty_or_not_a_list" in codes(run(tmp_path, empty)[1])
    many = doc(slots=[{"slot": "city-night", "findings": [finding()] * 13}, GOOD["slots"][1]])
    assert "too_many" in codes(run(tmp_path, many)[1])


def test_the_nothing_to_explain_open_item_is_known(tmp_path):
    done, answer = run(tmp_path, doc(open=[{"code": "nothing_to_explain"}]))
    assert done.returncode == 0


def test_a_file_that_is_not_json_is_an_error_not_a_crash(tmp_path):
    done, answer = run(tmp_path, None, raw="not json {")
    assert done.returncode == 1 and "not_an_object" in codes(answer)


def test_usage_errors_exit_2(tmp_path):
    done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 2 and done.stdout == ""
    done = subprocess.run([sys.executable, str(SCRIPT), "--slot", "Bad Slot"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 2
    done = subprocess.run([sys.executable, str(SCRIPT), "--slot", "a", "--task-file", str(tmp_path / "none.json")], capture_output=True, text=True, timeout=30)
    assert done.returncode == 2


def test_help_exits_0():
    done = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0 and "--task-file" in done.stdout
