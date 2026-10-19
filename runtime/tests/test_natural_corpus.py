"""Natural requests, tier 1: the rule that governs them, run over two corpora (package NR-1). A reminder asked in free text is NEVER made at once: the reading is shown
("Entendi: amanha, seg 19/10, as 09:00: ligar pro fisioterapeuta. Confirma?") and made only after the person's "yes" (a button where the platform has buttons, or typed). That
makes a silently wrong reminder impossible by construction, and it is the first thing these tests assert for every line of both corpora. What they also count, as a METRIC
and not as a failure, is how many readings were SHOWN wrong: a wrong reading costs the person one correction, so the number is tracked (printed with the test output and
recorded as a property of the test) and kept low by fixing the engine, not by an exemption.

  natural_corpus.jsonl      575 labelled lines of the spike of 2026-10-18 (Portuguese, English and a few Spanish, French, German and Japanese; invented names): text, language,
                            clock, expected {kind: time | ask | none, due}, optional also_ok (another moment a person could accept), timeonly. The lines of the maintainer's own file
                            are NOT in it. Expectations were written from the rule, never taken from an engine's output.
  natural_probe_lines.txt   the probe lines of the independent reviews: `text || expectation` (see the head of the file).

Offline, no model, no network. Run: uv run --with pytest==9.1.1 pytest -s runtime/tests/test_natural_corpus.py
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import standin_tree as st

natural = st.load("natural")

HERE = Path(__file__).resolve().parent
BRT = datetime.timezone(datetime.timedelta(hours=-3))
FORMAT = "%Y-%m-%d %H:%M"


def clock(text: str) -> datetime.datetime:
    return datetime.datetime.strptime(text, FORMAT).replace(tzinfo=BRT)


def decide(text: str, now: datetime.datetime) -> dict:
    """What the platform does with a line at a clock: {"out": "made"} when it would make a reminder with no question (the failure these tests exist to catch),
    {"out": "shown", "due": "YYYY-MM-DD HH:MM"} when it shows one reading to be confirmed (the confirmation, the kind question that holds the reading, or the question for the
    words that already has it), {"out": "asked", "need": ...} for any other question or a refusal (a moment that has passed, a date the calendar does not have, more than
    366 days ahead), {"out": "unmatched"} when no reminder row takes the line."""
    named = natural.candidate(text)
    if named is not None and named["op"] != "remind":
        return {"out": "unmatched", "op": named["op"]}
    how = named["how"] if named else "trigger"
    got = natural.understand(text, now, how)
    if "ask" not in got:
        return {"out": "made"}
    ask = got["ask"]
    if ask["need"] not in ("confirm", "kind", "text") or not ask["readings"]:
        return {"out": "asked", "need": ask["need"]}
    reading = ask["readings"][0]
    try:
        due = datetime.datetime.strptime(f"{reading['date']} {reading['time']}", FORMAT)
    except ValueError:
        return {"out": "asked", "need": "invalid date"}
    local = now.replace(tzinfo=None)
    if due <= local or due - local > datetime.timedelta(days=366):
        return {"out": "asked", "need": "refused"}
    return {"out": "shown", "due": due.strftime(FORMAT)}


def corpus():
    return [json.loads(line) for line in (HERE / "natural_corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def wrong_shown(row: dict, got: dict) -> bool:
    """Whether the reading shown for a line that expects a moment is another moment (the metric)."""
    expected = row["expected"]
    return expected["kind"] == "time" and got["out"] == "shown" and got["due"] != expected["due"] and got["due"] not in row.get("also_ok", [])


def test_the_corpus_holds_no_line_of_the_maintainers_file_and_has_every_shape():
    rows = corpus()
    assert len(rows) >= 500 and {r["language"] for r in rows} >= {"pt-BR", "en", "es", "fr", "de", "ja"}
    assert {r["expected"]["kind"] for r in rows} == {"time", "ask", "none"}


def test_no_line_of_the_corpus_is_made_without_a_confirmation(record_property):
    made, wrong, expecting = [], 0, 0
    for row in corpus():
        got = decide(row["text"], clock(row["clock"]))
        if got["out"] == "made":
            made.append(f"{row['text']!r} at {row['clock']}")
        expecting += row["expected"]["kind"] == "time"
        wrong += wrong_shown(row, got)
    record_property("wrong_shown_readings", wrong)
    print(f"\nmetric: {wrong} readings shown wrong of {expecting} lines that expect a moment (a wrong reading costs the person one correction)")
    assert made == [], "\n".join(made)


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


def test_no_probe_line_is_made_without_a_confirmation_and_the_routines_and_the_non_reminders_are_what_they_are(record_property):
    wrong, shown_wrong, expecting = [], 0, 0
    for text, expect, now in probe_lines():
        got = decide(text, now)
        if got["out"] == "made":
            wrong.append(f"{text!r} at {now:%Y-%m-%d %H:%M}: made with no confirmation")
        if expect.startswith("="):
            expecting += 1
            shown_wrong += got["out"] == "shown" and got["due"] != expect[1:]
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
    record_property("wrong_shown_probe_readings", shown_wrong)
    print(f"\nmetric: {shown_wrong} probe readings shown wrong of {expecting} that expect a moment")
    assert wrong == [], "\n".join(wrong)


def test_every_expected_moment_of_the_probe_lines_is_reached_or_asked_never_dropped():
    """A line the reviewers expect to become a reminder is, at least, understood: a line that returns nothing at all would be handled as a plain line by the planning agent."""
    lost = []
    for text, expect, now in probe_lines():
        if expect.startswith("=") and decide(text, now)["out"] == "unmatched":
            lost.append(text)
    assert lost == [], lost


def test_the_lines_with_no_expectation_do_not_break_the_engine():
    for text, wanted, now in probe_lines():
        if wanted == "any":
            decide(text, now)
