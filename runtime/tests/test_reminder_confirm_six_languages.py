"""A reminder the interpreter opened is confirmed by the person's own word, in es, fr, de and it (slice S4, review item (b) of S1; runtime/natural_lang_en.py `requests.yes` and
`requests.no`, runtime/natural.py `confirm_kind`, the messaging bridge's reminder engine).

Through the REAL messaging bridge over the real operations layer: a line in Spanish, French, German or Italian reaches the interpreter (a stand-in model answers with a `remind`
decision written by hand), which shows the reading and asks to confirm; the NEXT line goes through the bridge as it is (a stand-in messenger). The yes and the no words are this
file's own literals, never the language tables; a reminder row is the evidence of a yes.

  yes: sí, vale, oui, d'accord, ja, genau, sì, va bene -> one reminder with the span's words
  no:  no, non, nein, no grazie                           -> none
  neither: quizás                                         -> none

Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_reminder_confirm_six_languages.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_ask import accept
from test_messaging_ask import wait_for
from test_messaging_natural_ops import rig  # noqa: F401  (the bridge over the real operations layer with a stand-in messenger)
from test_ops_interpret_dispatch import IX_PROFILES, ZONE
from test_ops_natural import OWNER, docs, world  # noqa: F401

ops = st.load("ops")
interpreter_route = st.load("interpreter_route")
drafts = st.load("drafts")
ops_interpret = st.load("ops_interpret")
natural = st.load("natural")


def remind(text, when, iso, weekday):
    return json.dumps({"v": 1, "kind": "op", "op": "remind", "slots": {"text": text, "when": when}, "time_iso": iso, "weekday": weekday}, ensure_ascii=False)


# (the line, the model's text, the words of the reminder): lines the tables of pt-BR and en do not claim (natural.candidate is None), so that they reach the interpreter
ROWS = {
    "es": ("recuerdame llamar a Dana el lunes a las 15:00", remind("llamar a Dana", "el lunes a las 15:00", "2026-10-19T15:00", "mon"), "llamar a Dana"),
    "fr": ("rappelle-moi d'appeler Dana vendredi a 15 heures", remind("appeler Dana", "vendredi a 15 heures", "2026-10-23T15:00", "fri"), "appeler Dana"),
    "de": ("erinnere mich am Freitag um 15 Uhr an Dana", remind("an Dana", "am Freitag um 15 Uhr", "2026-10-23T15:00", "fri"), "an Dana"),
    "it": ("ricordami di chiamare Dana venerdi alle 15", remind("chiamare Dana", "venerdi alle 15", "2026-10-23T15:00", "fri"), "chiamare Dana"),
}
YES = [("es", "sí"), ("es", "vale"), ("fr", "oui"), ("fr", "d'accord"), ("de", "ja"), ("de", "genau"), ("it", "sì"), ("it", "va bene")]      # validate: allow english-only -- words the person types in Spanish and Italian
NO = [("es", "no"), ("fr", "non"), ("de", "nein"), ("it", "no grazie")]
NEITHER = [("es", "quizás")]       # validate: allow english-only -- a word the person types in Spanish


def opened(rig, monkeypatch, language):
    """The owner types the reminder line in `language`; the model answers with a `remind` decision; the bridge sends the reading. Nothing exists yet."""
    line, model, words = ROWS[language]
    accept(rig.world["path"], policies=IX_PROFILES, messaging={"senders": {"telegram": [{"id": OWNER, "policy": "owner"}]}})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: {"ok": True, "text": model, "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"})
    rig.bridge.handle(rig.update(OWNER, line))
    assert wait_for(lambda: len(rig.sent()) == 1 and not rig.bridge.exclusive), language
    assert rig.sent()[0]["message"]["text"].endswith(f": {words}. Confirm? (yes / another time)"), rig.sent()[0]["message"]["text"]
    assert reminders(rig) == []
    return words


def reminders(rig):
    return [r["text"] for r in ops.reminders_read(rig.project["path"], channel="terminal")["open"]]


def answer(rig, word):
    """The next line, through the bridge as it is; True when the bridge sent one more message."""
    rig.bridge.handle(rig.update(OWNER, word))
    return wait_for(lambda: len(rig.sent()) == 2)


@pytest.mark.parametrize("language,word", YES)
def test_a_yes_in_the_persons_own_word_makes_the_reminder_the_interpreter_opened(rig, monkeypatch, language, word):
    words = opened(rig, monkeypatch, language)
    assert answer(rig, word), word
    assert rig.sent()[1]["message"]["text"].startswith("Reminder #1: ") and words in rig.sent()[1]["message"]["text"], rig.sent()[1]["message"]["text"]
    assert reminders(rig) == [words]


@pytest.mark.parametrize("language,word", NO)
def test_a_no_in_the_persons_own_word_makes_no_reminder(rig, monkeypatch, language, word):
    opened(rig, monkeypatch, language)
    answer(rig, word)
    assert reminders(rig) == [] and drafts.count() == 0, word      # and the question is closed: a no is taken for a no, not asked again


@pytest.mark.parametrize("language,word", NEITHER)
def test_a_maybe_is_neither_and_makes_no_reminder(rig, monkeypatch, language, word):
    opened(rig, monkeypatch, language)
    answer(rig, word)
    assert reminders(rig) == [], word


@pytest.mark.parametrize("language,word", [("es", "vale"), ("fr", "d'accord"), ("de", "genau"), ("it", "va bene")])
def test_vacuity_without_the_lists_of_words_the_yes_rows_fail(rig, monkeypatch, language, word):
    """The plant: the language data answers no word. A word that only the lists hold then makes no reminder, so the yes rows above would fail."""
    monkeypatch.setattr(natural, "words_of", lambda *args, **kwargs: [])
    opened(rig, monkeypatch, language)
    answer(rig, word)
    assert reminders(rig) == [], (language, word)
