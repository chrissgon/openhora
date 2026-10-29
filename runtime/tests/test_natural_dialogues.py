"""Natural requests, tier 1: a dialogue fuzz over the question-and-answer machine (package NR-1). The maintainer's rule: a reminder in free text is made only after the person
said yes to a confirmation that showed the WHOLE reading (the day, the hour and the words), or answered "reminder" to the reminder-or-event question that showed it. A pick
among the readings offered, a time, a day, the words, "another time" or any other answer never makes one: it leads to the question that shows the reading it produced.

For every line of both corpora (test_natural_corpus.py) and every answer of a list of 21 (yes and no in both languages, bare hours, days, words, the kinds, a change with a
yes), the dialogue is walked two answers deep from a sample and one answer deep from all; each time a reminder is made, the test checks that the answer before it was the yes
(or the kind) to the question that showed that very reading and those very words. Offline, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_dialogues.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standin_tree as st
from closed_heads import trigger_reading  # noqa: F401  (S41-11 PR 2b: the reminder engine's old entry, the way `trigger`, for the tests that read a line that starts with a remind word)
from test_natural_corpus import clock, probe_lines

pytestmark = pytest.mark.usefixtures("trigger_reading")
natural = st.load("natural")

HERE = Path(__file__).resolve().parent
ANSWERS = ["sim", "yes", "9", "20", "21", "8", "às 8", "amanhã", "sexta", "lembrete", "reminder", "outra hora", "ligar pro banco", "ligar amanhã", "dia 25",      # validate: allow english-only -- Portuguese answers, the cases of the tests
           "sim, mas às 15h", "às 10h", "evento", "não", "ok", "2",      # validate: allow english-only -- Portuguese answers, the cases of the tests
           "lembrete às 15h", "um lembrete às 9 da noite", "lembrete dia 12 às 14h", "evento às 15h", "reminder at 3pm", "an event at 3pm"]      # validate: allow english-only -- Portuguese answers, the cases of the tests


def lines():
    out = [(json.loads(raw)["text"], clock(json.loads(raw)["clock"])) for raw in (HERE / "natural_corpus.jsonl").read_text(encoding="utf-8").splitlines() if raw.strip()]
    out += [(text, now) for text, _expect, now in probe_lines()]
    return out


def same(made: dict, ask: dict) -> bool:
    """Whether the reminder made is the very reading (day and hour) and the very words that the question showed."""
    shown = ask["readings"][0]
    return made["reading"]["date"] == shown["date"] and made["reading"]["time"] == shown["time"] and made["text"] == ask["text"]


def walk(ask, now, path, bad, depth):
    for answer in ANSWERS:
        got = natural.complete(ask, answer, now)
        if got is None:
            continue
        if "when" in got:
            allowed = ask["need"] == "confirm" and natural.affirm(answer) and same(got, ask)
            allowed = allowed or (ask["need"] == "kind" and same(got, ask) and (natural.affirm(answer) or natural.answer_kind(answer) == "notice"))
            if not allowed:
                bad.append((path + [answer], ask["need"], got["when"], got["text"]))
        elif "ask" in got and depth < 1:
            walk(got["ask"], now, path + [answer], bad, depth + 1)


def start(text, now):
    named = natural.candidate(text)
    if named is not None and named["op"] != "remind":
        return None
    got = natural.understand(text, now, named["how"] if named else "trigger")
    return got


def test_nothing_is_made_by_a_pick_a_time_a_day_the_words_or_any_answer_but_the_yes_to_the_reading_shown():
    every = lines()
    bad = []
    for index, (text, now) in enumerate(every):
        got = start(text, now)
        if got is None:
            continue
        assert "ask" in got, f"made at once: {text!r}"
        if index % 11 == 0:
            walk(got["ask"], now, [text], bad, 0)          # two answers deep from a sample
        else:
            for answer in ANSWERS:                       # one answer deep from the others
                done = natural.complete(got["ask"], answer, now)
                if done and "when" in done:
                    allowed = got["ask"]["need"] == "confirm" and natural.affirm(answer) and same(done, got["ask"])
                    allowed = allowed or (got["ask"]["need"] == "kind" and same(done, got["ask"]) and (natural.affirm(answer) or natural.answer_kind(answer) == "notice"))
                    if not allowed:
                        bad.append(([text, answer], got["ask"]["need"], done["when"], done["text"]))
    assert bad == [], "\n".join(map(str, bad[:20]))


@pytest.mark.parametrize("line,answers", [("me lembra às 8", ["20", "ligar pro banco amanhã"]), ("me lembra de ligar às 8", ["20"]), ("pilates às 8", ["20"]),      # validate: allow english-only -- a Portuguese line, the case of the tests
                                          ("remind me at 8", ["8pm", "call the bank tomorrow"])])
def test_a_pick_then_the_words_shows_the_whole_reading_and_waits_for_the_yes(line, answers):
    now = clock("2026-10-18 14:00")
    got = natural.understand(line, now, (natural.candidate(line) or {}).get("how", "trigger"))
    for answer in answers:
        assert "ask" in got, (line, answer)
        got = natural.complete(got["ask"], answer, now)
        assert got is not None and "when" not in got, (line, answer, got)
    assert got["ask"]["need"] in ("confirm", "kind") and got["ask"]["text"], "the reading is shown whole: the day, the hour and the words"


@pytest.mark.parametrize("answer", ["lembrete às 15h", "um lembrete às 9 da noite", "lembrete dia 12 às 14h", "reminder at 3pm"])      # validate: allow english-only -- Portuguese answers, the cases of the tests
def test_a_kind_answer_that_carries_a_time_changes_the_reading_and_asks_again_it_never_makes_the_reminder(answer):
    now = clock("2026-10-19 09:00")
    first = natural.understand("dentista quinta às 10h", now, "bare")
    assert first["ask"]["need"] == "kind"
    got = natural.complete(first["ask"], answer, now)
    assert got is not None and "when" not in got and got["ask"]["need"] in ("kind", "confirm"), got
    assert got["ask"]["readings"][0]["when"] != first["ask"]["readings"][0]["when"] and got["ask"]["text"] == "dentista"
