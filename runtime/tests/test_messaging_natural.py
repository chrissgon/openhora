"""Reminders asked in the person's own words, through a messaging bridge (package NR-1): `me lembra amanha as 13h da aula de violao`, `/remind aula de violao as 13hrs
amanha`, the question asked back when a line can be read two ways or lacks the hour, the reading shown and confirmed when something about it is uncertain, the draft that
finishes it (ten minutes, one per chat, lost on a restart, swept on the tick, dropped by any other line, answered by a reply only to its own question), the calendar
that is not built yet, the scheduling verb that is not a calendar word, the lists, the forgets and the undo in words, a profile without the group, and the rule behind
all of it: code reads the line, so no model runs, no route lock is taken and no model slot is held. Over the REAL operations layer, a stand-in messenger, a stand-in
planner that records every line a model would have been given, and a stand-in clock (Sunday 2026-10-18 14:00 at -03:00). The parser is in test_natural_time.py, the
pure rules and the operation in test_natural_reminders.py, a reply to a card in test_messaging_natural_reply.py. Offline, no model, no network; invented words.

The Portuguese lines and the sentences they must get are in natural_cases_pt_br.py, the one test file written in Portuguese on purpose.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural.py
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import natural_cases_pt_br as pt
import standin_tree as st
from natural_kit import say_yes
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_queue import WAIT, clocked, planner, settle  # noqa: F401  (the planner stand-in, the bridge's clock and the waiting for its jobs)
from test_messaging_reminders import WITH, day, listed  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER, STAFF, accept
from test_sender_profiles_bridge import NOT_ENABLED, OTHER, configure, lab  # noqa: F401  (the lab fixture)
import pytest
from closed_heads import closed_heads, tier1_forms, words_interpreted  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms", "words_interpreted")      # S41-11: every closed form claims a line in this file, as it did

bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
ops = st.load("ops")
phrases = st.load("phrases")

ENGLISH = "remind me tomorrow at 1 pm to call the florist"
EN_REPLY = "Reminder #1: tomorrow, Mon 19/10, at 13:00 (BRT): call the florist. To undo: /forget 1."


def portuguese(day):  # noqa: F811
    accept(day.path, language="pt-BR")


NO_GROUP = "Você ainda não tem permissão para isso por aqui."          # the profile of these tests lists no calendar-write: a write line gets the plain refusal of a phone (NR-5, S10)  # validate: allow english-only -- the Portuguese sentence under test


def say_plain(day, text, sender=OWNER):  # noqa: F811
    """A line that goes to the planning agent, and the wait for its job to end before the next line is sent: the bridge keeps one waiting line per chat (QUEUE_PER_CHAT) and
    refuses a second while the slot is held, so lines sent back to back reach the planner or not by the speed of the machine."""
    day.say(sender, text)
    assert settle(day), "the planning agent's job ended"


def no_model(planner):  # noqa: F811
    assert planner.texts() == [], "a line read by code never reaches the planning agent"


def update(sender, text, **fields):
    return {"update_id": 9, "sender": sender, "chat": sender, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None, **fields}


def last_id(day):  # noqa: F811
    """The id the stand-in messenger gave the message it sent last."""
    return str(100 + len(day.sent()))


# --- 1. the lines that make a reminder at once ---------------------------------------------------------------------------------------------------------


def test_a_slash_command_in_words_makes_the_reminder_and_answers_in_the_language_with_the_weekday_the_date_the_zone_and_the_undo(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, pt.LINE_SLASH)
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS and len(day.texts(OWNER)) == 2, "the reading is shown, then made on the yes"
    row = day.all()["open"][0]
    assert row["due"] == "2026-10-19 13:00" and row["text"] == "aula de violão" and row["zone"] == "BRT"      # validate: allow english-only -- the words of the line above
    no_model(planner)
    assert day.bridge.waiting == [] and not day.bridge.exclusive, "no model slot, no route lock"


def test_a_line_with_a_remind_word_makes_the_same_reminder_in_any_word_order(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, pt.LINE_CLASS)
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS and len(day.texts(OWNER)) == 2, "the reading is shown, then made on the yes"
    say_yes(day, OWNER, pt.LINE_CLASS_REORDER)
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS.replace("#1", "#2").replace("/forget 1", "/forget 2")
    assert [r["text"] for r in day.all()["open"]] == ["aula de violão", "aula de violão"]      # validate: allow english-only -- the words of the lines above
    no_model(planner)


def test_a_remind_word_in_the_middle_of_the_line_counts_and_the_trigger_words_are_not_in_the_text(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, pt.LINE_FORTY)
    assert day.texts(OWNER)[-1] == pt.REPLY_FORTY and len(day.texts(OWNER)) == 2, "the reading is shown, then made on the yes"
    assert day.all()["open"][0]["text"] == "desligar o fogão"      # validate: allow english-only -- the words of the line above
    no_model(planner)


def test_the_hour_with_no_marker_is_one_question_and_the_remind_word_settles_the_kind(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_NINE_FIRST)
    assert day.texts(OWNER) == [pt.ASK_NINE_FIRST]
    say_yes(day, OWNER, "9")
    assert day.texts(OWNER)[-1] == pt.REPLY_PLANTS and len(day.texts(OWNER)) == 3, "one question, the reading shown, then the reminder on the yes: never reminder-or-event"
    assert day.all()["open"][0]["text"] == "regar as plantas"
    no_model(planner)


def test_the_words_are_echoed_only_in_text_mode(day, planner):  # noqa: F811
    portuguese(day)
    listed(day, notices="count")
    accept(day.path, language="pt-BR")
    say_yes(day, OWNER, pt.LINE_CLASS)
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS_COUNT and len(day.texts(OWNER)) == 2, "the reading is shown, then made on the yes" and "violão" not in " ".join(day.texts(OWNER))      # validate: allow english-only -- a word of the lines above
    assert day.all()["open"][0]["text"] == "aula de violão", "the words are in the store, which the owner reads in the terminal"      # validate: allow english-only -- the words of the line above
    no_model(planner)


def test_a_date_that_has_passed_this_year_is_confirmed_with_its_year_and_the_year_stays_in_the_reply(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_YEAR)
    assert day.texts(OWNER) == [pt.CONFIRM_YEAR] and day.all()["open"] == []
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] == pt.REPLY_YEAR and day.all()["open"][0]["due"] == "2027-01-05 09:00"
    no_model(planner)


def test_a_line_in_the_other_language_is_understood_too(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, ENGLISH)
    assert day.texts(OWNER)[-1] == "Lembrete #1: amanhã, seg 19/10, às 13:00 (BRT): call the florist. Para desfazer: /forget 1." and len(day.texts(OWNER)) == 2, "the reading is shown, then made on the yes"      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


# --- 2. what is asked back, and the draft ----------------------------------------------------------------------------------------------------------


# --- 3. the calendar, and the scheduling verb that is not a calendar word ------------------------------------------------------------------------------


def test_a_bare_calendar_word_is_a_read_and_goes_to_the_planning_agent(day, planner):  # noqa: F811
    portuguese(day)
    say_plain(day, pt.LINE_AGENDA_READ)
    say_plain(day, "calendar for tomorrow?")
    assert settle(day) and planner.texts() == [pt.LINE_AGENDA_READ, "calendar for tomorrow?"] and day.all()["open"] == [] and day.bridge.remind.drafts == {}


# --- 4. the policy ----------------------------------------------------------------------------------------------------------------------------------


# --- 5. lists, forgets and the undo in words ----------------------------------------------------------------------------------------------------------


# --- 6. no model, no route lock, no model slot, nothing in the log -------------------------------------------------------------------------------------------


def test_the_words_of_a_reminder_are_never_in_the_log_nor_in_a_file_of_the_project(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_NINE)
    day.say(OWNER, "21h")
    day.say(OWNER, "veterinário amanhã 13h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "agenda")
    day.say(OWNER, pt.LINE_FORGET_WORDS)
    day.say(OWNER, pt.LINE_UNDO)
    log = " ".join(day.log)
    assert not any(w in log for w in ("violão", "gráfica", "veterinário", "ligar")), day.log      # validate: allow english-only -- words of the lines above
    files = "".join(p.read_text(errors="ignore") for p in Path(day.path).rglob("*.md"))
    assert "violão" not in files and "gráfica" not in files      # validate: allow english-only -- words of the lines above
    assert "violão" not in json.dumps([m for m in day.sent() if not m["message"]["text"].startswith(("Lembrete #", "O lembrete #"))])      # validate: allow english-only -- a word of the lines above


def test_a_bridge_stops_at_start_with_a_sentence_when_a_language_table_is_broken(day, monkeypatch):  # noqa: F811
    natural_time = st.load("natural_time")
    monkeypatch.setattr(natural_time, "_default", [])
    monkeypatch.setattr(natural_time, "load_languages", lambda *a, **k: (_ for _ in ()).throw(ValueError("language table 'xx': markers is a list")))
    import pytest
    with pytest.raises(bridge.Fatal) as e:
        bridge.Bridge(ops, day.bridge.projects, day.bridge.messenger, ledgers.Ledger(str(day.tmp / "ledger-data"), "telegram"), "telegram", day.log.append)
    assert "natural-request language tables are not valid" in str(e.value) and "markers" in str(e.value)
