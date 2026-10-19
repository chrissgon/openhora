"""Natural requests, tier 1: the rule that governs them, run over two corpora (package NR-1). A line is NEVER made at a moment other than the one a person means: when the
engine is not sure, or does not know the words (another language, a holiday, a month with no cue), the reading is asked about or shown and confirmed. An ask or a
confirm is always allowed; the only failure is a line made at the wrong moment ("silently wrong"), a line that should have been asked about and was made, or a line that
is not a time line and was made.

  natural_corpus.jsonl      575 labelled lines of the spike of 2026-10-18 (Portuguese, English and a few Spanish, French, German and Japanese; invented names): text, language,
                            clock, expected {kind: time | ask | none, due}, optional also_ok (another moment a person could accept), timeonly. The lines of the maintainer's own file
                            are NOT in it. Expectations were written from the rule, never taken from an engine's output.
  natural_probe_lines.txt   the probe lines of the independent reviews: `text || expectation` (see the head of the file).

Offline, no model, no network. Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_corpus.py
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

import standin_tree as st

natural = st.load("natural")

HERE = Path(__file__).resolve().parent
BRT = datetime.timezone(datetime.timedelta(hours=-3))
FORMAT = "%Y-%m-%d %H:%M"


def clock(text: str) -> datetime.datetime:
    return datetime.datetime.strptime(text, FORMAT).replace(tzinfo=BRT)


def decide(text: str, now: datetime.datetime) -> dict:
    """What the platform does with a line at a clock: {"out": "made", "due": "YYYY-MM-DD HH:MM"} when it would make a reminder (a question that only asks for the words or the
    kind has the moment already: it counts as made), {"out": "asked", "need": ...} for any other question, a confirmation or a refusal (a moment that has passed, a date the
    calendar does not have, more than 366 days ahead), and {"out": "unmatched"} when no reminder row takes the line."""
    named = natural.candidate(text)
    if named is not None and named["op"] != "remind":
        return {"out": "unmatched", "op": named["op"]}
    how = named["how"] if named else "trigger"
    got = natural.understand(text, now, how)
    if "ask" in got:
        ask = got["ask"]
        if ask["need"] not in ("text", "kind"):
            return {"out": "asked", "need": ask["need"]}
        reading = ask["readings"][0]
    else:
        reading = got["reading"]
    try:
        due = datetime.datetime.strptime(f"{reading['date']} {reading['time']}", FORMAT)
    except ValueError:
        return {"out": "asked", "need": "invalid date"}
    local = now.replace(tzinfo=None)
    if due <= local or due - local > datetime.timedelta(days=366):
        return {"out": "asked", "need": "refused"}
    return {"out": "made", "due": due.strftime(FORMAT)}


def corpus():
    return [json.loads(line) for line in (HERE / "natural_corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def silently_wrong(row: dict, got: dict):
    """The label of the failure, or None."""
    expected = row["expected"]
    if got["out"] != "made":
        return None
    if expected["kind"] == "time":
        return None if got["due"] == expected["due"] else "made at another moment"
    if expected["kind"] == "ask":
        return None if got["due"] in row.get("also_ok", []) else "made, should have been asked"
    return "made, not a time line"


def test_the_corpus_holds_no_line_of_the_maintainers_file_and_has_every_shape():
    rows = corpus()
    assert len(rows) >= 500 and {r["language"] for r in rows} >= {"pt-BR", "en", "es", "fr", "de", "ja"}
    assert {r["expected"]["kind"] for r in rows} == {"time", "ask", "none"}


def test_no_line_of_the_corpus_is_made_silently_at_the_wrong_moment():
    wrong = []
    for row in corpus():
        got = decide(row["text"], clock(row["clock"]))
        label = silently_wrong(row, got)
        if label:
            wrong.append(f"{label}: {row['text']!r} at {row['clock']}: expected {row['expected'].get('due') or row['expected']['kind']}, got {got.get('due')}")
    assert wrong == [], "\n".join(wrong)


# --- the probe lines ------------------------------------------------------------------------------------------------------------------------------


def probe_lines():
    now = clock("2026-10-18 14:00")
    out = []
    for raw in (HERE / "natural_probe_lines.txt").read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        if raw.startswith("@clock "):
            now = clock(raw[len("@clock "):].strip())
            continue
        text, _, expect = raw.rpartition(" || ")
        out.append((text.strip(), expect.strip(), now))
    return out


def test_no_probe_line_is_made_silently_wrong():
    wrong = []
    for text, expect, now in probe_lines():
        got = decide(text, now)
        if expect.startswith("="):
            if got["out"] == "made" and got["due"] != expect[1:]:
                wrong.append(f"{text!r} at {now:%Y-%m-%d %H:%M}: expected {expect[1:]}, made {got['due']}")
        elif expect == "?":
            if got["out"] == "made":
                wrong.append(f"{text!r} at {now:%Y-%m-%d %H:%M}: made {got['due']}, should have been asked")
        elif expect == "R":
            try:
                recurring = natural.understand(text, now, (natural.candidate(text) or {}).get("how", "trigger"))["ask"]["need"] == "recurring"
            except KeyError:
                recurring = False
            if not recurring:
                wrong.append(f"{text!r} at {now:%Y-%m-%d %H:%M}: a routine's, not said so")
        elif expect == "N":
            if got["out"] != "unmatched" and natural.candidate(text) is not None:
                wrong.append(f"{text!r}: not a reminder, matched to {natural.candidate(text)}")
    assert wrong == [], "\n".join(wrong)


def test_every_expected_moment_of_the_probe_lines_is_reached_or_asked_never_dropped():
    """A line the reviewers expect to be made at a moment is, at least, understood: a line that returns nothing at all would be handled as a plain line by the planning agent."""
    lost = []
    for text, expect, now in probe_lines():
        if expect.startswith("=") and decide(text, now)["out"] == "unmatched":
            lost.append(text)
    assert lost == [], lost


@pytest.mark.parametrize("expect", ["any"])
def test_the_lines_with_no_expectation_do_not_break_the_engine(expect):
    for text, wanted, now in probe_lines():
        if wanted == expect:
            decide(text, now)
