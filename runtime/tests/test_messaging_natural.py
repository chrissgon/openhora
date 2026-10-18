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
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_queue import WAIT, clocked, planner, settle  # noqa: F401  (the planner stand-in, the bridge's clock and the waiting for its jobs)
from test_messaging_reminders import WITH, day, listed  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER, STAFF, accept
from test_sender_profiles_bridge import NOT_ENABLED, OTHER, configure, lab  # noqa: F401  (the lab fixture)

bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
ops = st.load("ops")
phrases = st.load("phrases")

ENGLISH = "remind me tomorrow at 1 pm to call the florist"
EN_REPLY = "Reminder #1: tomorrow, Mon 19/10, at 13:00 (BRT): call the florist. To undo: /forget 1."


def portuguese(day):  # noqa: F811
    accept(day.path, language="pt-BR")


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
    day.say(OWNER, pt.LINE_SLASH)
    assert day.texts(OWNER) == [pt.REPLY_CLASS]
    row = day.all()["open"][0]
    assert row["due"] == "2026-10-19 13:00" and row["text"] == "aula de violão" and row["zone"] == "BRT"      # validate: allow english-only -- the words of the line above
    no_model(planner)
    assert day.bridge.waiting == [] and not day.bridge.exclusive, "no model slot, no route lock"


def test_a_line_with_a_remind_word_makes_the_same_reminder_in_any_word_order(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    assert day.texts(OWNER) == [pt.REPLY_CLASS]
    day.say(OWNER, pt.LINE_CLASS_REORDER)
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS.replace("#1", "#2").replace("/forget 1", "/forget 2")
    assert [r["text"] for r in day.all()["open"]] == ["aula de violão", "aula de violão"]      # validate: allow english-only -- the words of the lines above
    no_model(planner)


def test_a_remind_word_in_the_middle_of_the_line_counts_and_the_trigger_words_are_not_in_the_text(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_FORTY)
    assert day.texts(OWNER) == [pt.REPLY_FORTY]
    assert day.all()["open"][0]["text"] == "desligar o forno"
    no_model(planner)


def test_the_hour_with_no_marker_is_one_question_and_the_remind_word_settles_the_kind(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_NINE_FIRST)
    assert day.texts(OWNER) == [pt.ASK_NINE_FIRST]
    day.say(OWNER, "9")
    assert day.texts(OWNER)[-1] == pt.REPLY_PLANTS and len(day.texts(OWNER)) == 2, "one question and then the reminder: never reminder-or-event"
    assert day.all()["open"][0]["text"] == "regar as plantas"
    no_model(planner)


def test_the_words_are_echoed_only_in_text_mode(day, planner):  # noqa: F811
    portuguese(day)
    listed(day, notices="count")
    accept(day.path, language="pt-BR")
    day.say(OWNER, pt.LINE_CLASS)
    assert day.texts(OWNER) == [pt.REPLY_CLASS_COUNT] and "violão" not in " ".join(day.texts(OWNER))      # validate: allow english-only -- a word of the lines above
    assert day.all()["open"][0]["text"] == "aula de violão", "the words are in the store, which the owner reads in the terminal"      # validate: allow english-only -- the words of the line above
    no_model(planner)


def test_a_time_of_day_that_has_passed_says_so_and_gives_tomorrows_but_a_day_the_person_named_is_refused_not_moved(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "/remind 13:00 aula de violão")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER) == [pt.PAST_TODAY]
    day.say(OWNER, pt.LINE_TODAY_PAST)
    assert day.texts(OWNER)[-1] == pt.REPLY_PAST_DAY and len(day.all()["open"]) == 1, "today's date with an hour that has passed is past, not next year's"
    no_model(planner)


def test_a_date_that_has_passed_this_year_is_confirmed_with_its_year_and_the_year_stays_in_the_reply(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_YEAR)
    assert day.texts(OWNER) == [pt.CONFIRM_YEAR] and day.all()["open"] == []
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] == pt.REPLY_YEAR and day.all()["open"][0]["due"] == "2027-01-05 09:00"
    no_model(planner)


def test_an_english_project_gets_english_in_the_same_shape(day, planner):  # noqa: F811
    day.say(OWNER, ENGLISH)
    assert day.texts(OWNER) == [EN_REPLY]
    day.say(OWNER, "Please remind me on friday to pay the rent")
    assert day.texts(OWNER)[-1] == "Fri 23/10: at what time? Reply with a time, for example 1 pm."
    day.say(OWNER, "remind me to stretch")
    assert day.texts(OWNER)[-1] == "The previous question was discarded. When? Example: remind me tomorrow at 1 pm to water the plants"
    no_model(planner)


def test_a_line_in_the_other_language_is_understood_too(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, ENGLISH)
    assert day.texts(OWNER) == ["Lembrete #1: amanhã, seg 19/10, às 13:00 (BRT): call the florist. Para desfazer: /forget 1."]      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


# --- 2. what is asked back, and the draft ----------------------------------------------------------------------------------------------------------


def test_an_hour_with_no_marker_asks_09_or_21_and_the_next_line_finishes_it(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_NINE)
    assert day.texts(OWNER) == [pt.ASK_NINE] and day.all()["open"] == [], "a question makes nothing"
    assert set(day.bridge.remind.drafts) == {OWNER}
    day.say(OWNER, "21h")
    assert day.texts(OWNER)[-1] == pt.REPLY_FRIDAY_21 and day.bridge.remind.drafts == {}
    assert day.all()["open"][0]["due"] == "2026-10-23 21:00" and day.all()["open"][0]["text"] == "ligar para a gráfica"      # validate: allow english-only -- a word of the line above
    no_model(planner)


def test_quinta_que_vem_asks_both_thursdays_and_the_day_picks_one(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_THURSDAY)
    assert day.texts(OWNER) == [pt.ASK_THURSDAY] and day.all()["open"] == []
    day.say(OWNER, "dia 22")
    assert day.texts(OWNER)[-1] == pt.REPLY_THURSDAY and day.all()["open"][0]["due"] == "2026-10-22 15:30"
    no_model(planner)


def test_any_other_line_drops_the_question_and_is_handled_as_a_new_line(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_NINE)
    day.say(OWNER, "when does the shop open")
    assert day.bridge.remind.drafts == {} and settle(day)
    assert planner.texts() == ["when does the shop open"], "the other line went on to the planning agent as any plain line"
    day.say(OWNER, "21h")
    assert settle(day) and planner.texts()[-1] == "21h" and day.all()["open"] == [], "the question is gone: 21h alone is a plain line now"
    day.say(OWNER, pt.LINE_NINE)
    day.say(OWNER, "/reminders")
    assert day.bridge.remind.drafts == {} and day.texts(OWNER)[-1] == pt.LIST_NONE
    day.say(OWNER, pt.LINE_NINE)
    day.say(OWNER, "sexta às 10h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.all()["open"][0]["due"] == "2026-10-23 10:00", "a full new time (a day and an hour) replaces the readings offered"
    assert day.bridge.remind.drafts == {}


def test_the_question_is_forgotten_after_ten_minutes_swept_on_the_tick_lost_on_a_restart_and_kept_per_chat(day, planner):  # noqa: F811
    portuguese(day)
    now = clocked(day)
    day.say(OWNER, pt.LINE_NINE)
    day.say(OTHER, "21h")
    assert day.bridge.remind.drafts.keys() == {OWNER}, "another chat's line neither finishes nor drops it"
    assert settle(day) and planner.texts() == ["21h"]
    now[0] += 599
    day.say(OWNER, "21h")
    assert day.all()["open"][0]["due"] == "2026-10-23 21:00", "nine minutes and a half: still there"
    day.say(OWNER, pt.LINE_NINE)
    now[0] += 601
    day.say(OWNER, "21h")
    assert len(day.all()["open"]) == 1 and settle(day) and planner.texts()[-1] == "21h", "ten minutes and a second: forgotten, a plain line"
    day.say(OWNER, pt.LINE_NINE)
    now[0] += 601
    day.bridge.tick()
    assert day.bridge.remind.drafts == {}, "the words leave memory on the tick, whether or not the chat writes again"
    day.say(OWNER, pt.LINE_NINE)
    fresh = bridge.Bridge(ops, day.bridge.projects, day.bridge.messenger, ledgers.Ledger(str(day.tmp / "ledger-data"), "telegram"), "telegram", day.log.append,
                          clock=lambda: "2026-10-11T10:00:00+00:00")
    assert fresh.remind.drafts == {}, "lost on a restart"
    fresh.handle(update(OWNER, "21h"))
    assert len(day.all()["open"]) == 1 and settle(day)


def test_a_question_is_answered_by_a_reply_only_to_its_own_message_and_a_reminder_asked_as_a_reply_is_still_a_reminder(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_NINE)
    day.say(OWNER, "21h", reply_to="m-9")
    assert day.all()["open"] == [] and day.bridge.remind.drafts == {} and settle(day) and planner.texts() == ["21h"], "a reply to another message is not the answer"
    day.say(OWNER, pt.LINE_NINE)
    day.say(OWNER, "21h", reply_to=last_id(day))
    assert day.all()["open"][0]["due"] == "2026-10-23 21:00", "a reply to the question itself is"
    day.say(OWNER, pt.LINE_CLASS, reply_to="m-2")
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS.replace("#1", "#2").replace("/forget 1", "/forget 2")
    assert planner.texts() == ["21h"]


def test_a_day_with_no_hour_asks_the_hour_and_a_remind_word_with_no_time_asks_when(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_NO_HOUR)
    assert day.texts(OWNER)[-1] == pt.ASK_TIME_TOMORROW and day.all()["open"] == []
    day.say(OWNER, "9h")
    assert day.all()["open"][0]["due"] == "2026-10-19 09:00" and day.all()["open"][0]["text"] == "ligar"
    day.say(OWNER, pt.LINE_NO_TIME)
    assert day.texts(OWNER)[-1] == pt.ASK_WHEN
    day.say(OWNER, "daqui a 2 horas")
    by_id = {r["id"]: r for r in day.all()["open"]}
    assert by_id[2]["due"] == "2026-10-18 16:00" and by_id[2]["text"] == "regar as plantas"
    day.say(OWNER, "/remind")
    assert day.texts(OWNER)[-1] == pt.SLASH_ASK_WHEN, "never the English usage sentence for a Portuguese project"
    no_model(planner)


def test_a_reading_with_something_uncertain_is_shown_and_confirmed_and_the_answer_replaces_only_what_it_names(day, planner):  # noqa: F811
    portuguese(day)
    for line in pt.UNSURE_LINES:
        day.say(OWNER, line)
        assert day.texts(OWNER)[-1].startswith("Entendi: ") and day.texts(OWNER)[-1].endswith("Confirma? (sim / outra hora)"), line
        day.bridge.remind.drafts.clear()
    assert day.all()["open"] == []
    day.say(OWNER, "me lembra amnha às 9h de pagar a conta")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.CONFIRM_AMNHA
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] == pt.REPLY_AMNHA
    day.say(OWNER, pt.LINE_UNSURE)
    day.say(OWNER, "sexta")
    newest = lambda: max(day.all()["open"], key=lambda r: r["id"])      # noqa: E731
    assert newest()["due"] == "2026-10-23 10:00", "a day alone replaces the day and keeps the hour"
    day.say(OWNER, pt.LINE_UNSURE)
    day.say(OWNER, "11h")
    assert newest()["due"] == "2026-10-19 11:00", "an hour alone replaces the hour"
    day.say(OWNER, pt.LINE_UNSURE)
    day.say(OWNER, "não")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.CANCELLED and day.bridge.remind.drafts == {} and len(day.all()["open"]) == 3
    no_model(planner)


def test_words_that_only_look_like_a_day_are_made_at_once(day, planner):  # noqa: F811
    portuguese(day)
    for line in pt.PLAIN_LINES:
        day.say(OWNER, line)
        assert day.texts(OWNER)[-1].startswith("Lembrete #"), line
    no_model(planner)


def test_a_line_that_repeats_is_said_to_be_a_routines_and_nothing_is_kept_or_made(day, planner):  # noqa: F811
    portuguese(day)
    for line in pt.RECURRING_LINES:
        day.say(OWNER, line)
        assert day.texts(OWNER)[-1] == pt.RECURRING, line
    assert day.all()["open"] == [] and day.bridge.remind.drafts == {}
    day.say(OWNER, "remind me every monday at 8am to water the plants")
    assert day.texts(OWNER)[-1] == pt.RECURRING
    no_model(planner)


def test_the_words_missing_are_asked_and_the_next_line_is_them_only_when_it_is_short_and_not_work_or_thanks(day, planner):  # noqa: F811
    day.say(OWNER, "remind me tomorrow at 9am")
    assert day.texts(OWNER)[-1] == "What should I remind you of? Reply with the words to send."
    day.say(OWNER, "water the plants")
    assert day.all()["open"][0]["text"] == "water the plants" and day.all()["open"][0]["due"] == "2026-10-19 09:00"
    for answer in ("write the launch post for the shop", "please send the report to the whole team now"):
        day.say(OWNER, "remind me tomorrow at 9am")
        day.say(OWNER, answer)
        assert day.bridge.remind.drafts == {}, answer
    for answer in ("thanks", "yes"):
        day.say(OWNER, "remind me tomorrow at 9am")
        day.say(OWNER, answer)
        assert day.texts(OWNER)[-1] == "What should I remind you of? Reply with the words to send.", "a short reply that is no answer: the question once more"
        day.say(OWNER, answer)
        assert day.bridge.remind.drafts == {}, "and the second time the line is a plain one"
    assert settle(day) and planner.texts() == ["write the launch post for the shop", "please send the report to the whole team now", "thanks", "yes"]
    assert len(day.all()["open"]) == 1
    day.say(OWNER, "remind me tomorrow at 9am")
    day.say(OWNER, "never mind")
    assert day.texts(OWNER)[-1] == "Ok, no reminder was made." and day.bridge.remind.drafts == {}
    day.say(OWNER, "remind me tomorrow at 9am")
    day.say(OWNER, "2pm")
    assert day.texts(OWNER)[-1] == "What should I remind you of? Reply with the words to send." and day.bridge.remind.drafts[OWNER]["readings"][0]["when"] == "2026-10-19 14:00", \
        "a bare time completes the time, not the text"


def test_a_line_with_a_time_and_neither_kind_of_word_asks_a_reminder_or_a_calendar_event(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_BARE)
    assert day.texts(OWNER) == [pt.ASK_KIND] and day.all()["open"] == []
    day.say(OWNER, "lembrete")
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS and day.all()["open"][0]["text"] == "aula de violão"      # validate: allow english-only -- a word of the lines above
    day.say(OWNER, pt.LINE_NOTE_TIME)
    assert day.texts(OWNER)[-1] == pt.ASK_KIND
    day.say(OWNER, "agenda")
    assert day.texts(OWNER)[-1] == pt.NOT_BUILT and len(day.all()["open"]) == 1, "the calendar is not built: nothing is made in its place"
    day.say(OWNER, pt.LINE_NOTE_TIME)
    day.say(OWNER, "sim")
    assert settle(day) and len(day.all()["open"]) == 2 and day.bridge.remind.drafts == {}
    assert planner.texts() == [], "a yes to \"a reminder or an event\" is the reminder"
    listed(day, notices="count")
    accept(day.path, language="pt-BR")
    day.say(OWNER, pt.LINE_BARE)
    assert day.texts(OWNER)[-1] == pt.ASK_KIND_COUNT


def test_anote_with_a_day_and_no_hour_asks_the_hour_then_which_kind_and_anota_with_no_time_offers_a_reminder(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "anote aula de violão amanhã")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1].endswith("a que horas? Responda com uma hora, por exemplo 13h.")      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "13h")
    assert day.texts(OWNER)[-1] == pt.ASK_KIND
    day.say(OWNER, "lembrete")
    assert day.texts(OWNER)[-1] == pt.REPLY_CLASS
    day.say(OWNER, pt.LINE_NOTE)
    assert day.texts(OWNER)[-1] == pt.ASK_NOTE and len(day.all()["open"]) == 1
    day.say(OWNER, "amanhã às 10h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.REPLY_NOTE.replace("#1", "#2").replace("/forget 1", "/forget 2"), "the note word and a time answer make the reminder with no second question"
    no_model(planner)


# --- 3. the calendar, and the scheduling verb that is not a calendar word ------------------------------------------------------------------------------


def test_the_calendar_is_not_built_and_a_line_that_asks_for_it_makes_no_reminder(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CALENDAR)
    assert day.texts(OWNER) == [pt.NOT_BUILT] and day.all()["open"] == [] and day.bridge.remind.drafts == {}
    day.say(OWNER, pt.LINE_MARCA)
    assert day.texts(OWNER)[-1] == pt.NOT_BUILT, "marca with a time is an event write: it ends in a card the person approves, so it is claimed"
    day.say(OWNER, "put on my calendar the florist friday at 9")
    assert day.texts(OWNER)[-1] == pt.NOT_BUILT
    no_model(planner)


def test_a_bare_calendar_word_is_a_read_and_goes_to_the_planning_agent(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_AGENDA_READ)
    day.say(OWNER, "calendar for tomorrow?")
    assert settle(day) and planner.texts() == [pt.LINE_AGENDA_READ, "calendar for tomorrow?"] and day.all()["open"] == [] and day.bridge.remind.drafts == {}


def test_a_scheduling_verb_with_no_calendar_word_asks_event_or_something_else_and_something_else_goes_to_the_planning_agent(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_LOOSE)
    assert day.texts(OWNER) == [pt.ASK_EVENT_OR_OTHER] and day.all()["open"] == []
    day.say(OWNER, "outra coisa")
    assert settle(day) and planner.texts() == [pt.LINE_LOOSE], "the line goes on, whole, to the planning agent"
    day.say(OWNER, pt.LINE_LOOSE)
    day.say(OWNER, "agenda")
    assert day.texts(OWNER)[-1] == pt.NOT_BUILT and planner.texts() == [pt.LINE_LOOSE]
    day.say(OWNER, pt.LINE_LOOSE)
    day.say(OWNER, "lembrete")
    assert day.all()["open"][0]["due"] == "2026-10-19 10:00", "a reminder was chosen: the line is kept, not lost"
    day.say(OWNER, pt.LINE_LOOSE)
    day.say(OWNER, "quando abre a loja")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert settle(day) and planner.texts()[-1] == "quando abre a loja" and day.bridge.remind.drafts == {}      # validate: allow english-only -- a Portuguese line, the case of the tests


def test_schedule_the_post_for_tomorrow_does_not_get_the_calendar_reply(day, planner):  # noqa: F811
    day.say(OWNER, "schedule the post for tomorrow at 9am")
    assert day.texts(OWNER)[-1].startswith("An event in your calendar, or something else?") and "I cannot do that yet" not in day.texts(OWNER)[-1]
    day.say(OWNER, "something else")
    assert settle(day) and planner.texts() == ["schedule the post for tomorrow at 9am"]
    day.say(OWNER, "schedule the post")
    assert settle(day) and planner.texts()[-1] == "schedule the post", "a verb with no time is a plain line"


# --- 4. the policy ----------------------------------------------------------------------------------------------------------------------------------


def test_a_profile_without_the_group_gets_the_typed_refusal_for_a_remind_word_and_its_bare_lines_go_on_to_the_planning_agent(day, planner):  # noqa: F811
    day.say(STAFF, ENGLISH)
    assert NOT_ENABLED in day.texts(STAFF)[-1] and "remind" in day.texts(STAFF)[-1] and day.all()["open"] == []
    typed = len(day.texts(STAFF))
    day.say(STAFF, "/remind tomorrow 1 pm call the florist")
    assert day.texts(STAFF)[typed:] and NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "what reminders do I have")
    assert NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "forget reminder 3")
    assert NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "forget the reminder about the florist")
    assert NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "violin class tomorrow 1pm")
    day.say(STAFF, "undo")
    assert settle(day) and planner.texts() == ["violin class tomorrow 1pm", "undo"], "a line that only looks like a request is a plain line for a sender who cannot remind"
    assert day.all()["open"] == [] and day.bridge.remind.drafts == {}


def test_a_profile_that_may_remind_and_may_not_talk_still_reminds_in_words_and_the_calendar_reply_is_a_plain_line_it_may_not_have(day, planner):  # noqa: F811
    configure(day, [{"id": OWNER, "policy": "clerk"}], policies={**WITH, "clerk": ["read-limited", "reminders"]})
    day.say(OWNER, ENGLISH)
    assert day.texts(OWNER)[-1].startswith("Reminder #1: tomorrow, Mon 19/10, at 13:00"), "the group asked is the operation's own, not `talk`"
    day.say(OWNER, "when does the shop open")
    assert settle(day) and NOT_ENABLED in day.texts(OWNER)[-1] and planner.texts() == []
    day.say(OWNER, "put on my calendar the florist friday at 9")
    assert NOT_ENABLED in day.texts(OWNER)[-1] and "I cannot do that yet" not in day.texts(OWNER)[-1], "the calendar answer checks the policy of a plain line"


def test_a_reminder_in_words_goes_only_to_the_chat_that_asked_for_it(day, planner):  # noqa: F811
    day.say(OWNER, ENGLISH)
    day.say(OTHER, "remind me tomorrow at 1 pm to take the bread out")
    day.clock.set("2026-10-19 13:00")
    day.bridge.tick()
    assert [t for t in day.texts(OWNER) if t.startswith("Reminder:")] == ["Reminder: call the florist"]
    assert [t for t in day.texts(OTHER) if t.startswith("Reminder:")] == ["Reminder: take the bread out"]
    assert not any("florist" in t or "bread" in t or t.startswith("Reminder") for t in day.texts(STAFF)), "nobody else is told"


# --- 5. lists, forgets and the undo in words ----------------------------------------------------------------------------------------------------------


def test_the_list_shows_human_dates_in_the_projects_language_and_the_forget_by_number_says_what_it_cancelled(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_LIST)
    assert day.texts(OWNER)[-1] == pt.LIST_NONE
    day.say(OWNER, pt.LINE_FORGET_ASK)
    assert day.texts(OWNER)[-1] == pt.LIST_NONE, "nothing to choose from: no question"
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_LIST_BARE)
    assert day.texts(OWNER)[-1] == f"{pt.LIST_HEAD}\n{pt.LIST_ONE}"
    day.say(OWNER, pt.LINE_FORGET_ASK)
    assert day.texts(OWNER)[-2].startswith(pt.LIST_HEAD) and day.texts(OWNER)[-1] == pt.WHICH
    day.say(OWNER, pt.LINE_FORGET_NUM)
    assert day.texts(OWNER)[-1] == pt.FORGOT and day.all()["open"] == []
    day.say(OTHER, "forget reminder 1")
    assert day.texts(OTHER)[-1] == "Não há lembrete 1 esperando por você."      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_forget_by_the_words_the_person_says_cancels_the_one_that_matches_and_asks_when_several_do_and_says_so_when_none_does(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_FORGET_NONE)
    assert day.texts(OWNER)[-1] == pt.NO_MATCH and len(day.all()["open"]) == 1, "none: said, and the line goes nowhere"
    day.say(OWNER, pt.LINE_CLASS_REORDER)
    day.say(OWNER, pt.LINE_FORGET_WORDS)
    assert day.texts(OWNER)[-1] == pt.WHICH and day.texts(OWNER)[-2].startswith(pt.LIST_HEAD) and len(day.all()["open"]) == 2, "two match: the list and the question"
    day.say(OWNER, pt.LINE_FORGET_NUM)
    day.say(OWNER, pt.LINE_FORGET_WORDS)
    assert day.texts(OWNER)[-1] == pt.FORGOT_BY_WORDS and day.all()["open"] == [], "one matches: cancelled, and said what it was"
    day.say(OTHER, "remind me tomorrow at 1 pm to take the bread out")
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, "cancela o lembrete do pão")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.NO_MATCH, "another sender's reminder is never found"
    assert len(day.all()["open"]) == 2
    no_model(planner)


def test_a_number_inside_the_words_is_a_word_and_never_the_number_of_a_reminder_and_a_work_line_is_not_swallowed(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_TWO_BOLETOS)
    day.say(OWNER, pt.LINE_FORGET_NINE)
    assert day.texts(OWNER)[-1] == pt.NO_MATCH and len(day.all()["open"]) == 2, '"das 1" is the word 1, not reminder #1'
    day.say(OWNER, pt.LINE_FORGET_BOLETOS)
    assert day.texts(OWNER)[-1].startswith("Lembrete #2 cancelado: amanhã, seg 19/10, às 15:00 (BRT): pagar 2 boletos.")      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "delete reminder emails from inbox")
    day.say(OWNER, "remove the reminder banner from the site")
    assert settle(day) and planner.texts() == ["delete reminder emails from inbox", "remove the reminder banner from the site"]


def test_undo_brings_back_the_last_reminder_the_sender_cancelled_within_ten_minutes_as_a_new_one(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_FORGET_NUM)
    assert day.all()["open"] == []
    day.say(OWNER, pt.LINE_UNDO)
    assert day.texts(OWNER)[-1] == pt.RESTORED
    row = day.all()["open"][0]
    assert row["id"] == 2 and row["text"] == "aula de violão" and row["due"] == "2026-10-19 13:00"      # validate: allow english-only -- the words of the lines above
    day.say(OWNER, pt.LINE_UNDO)
    assert day.texts(OWNER)[-1] == "O lembrete 1 já está de volta." and len(day.all()["open"]) == 1, "the second undo is told it is already back"      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "/forget 2")
    day.clock.moment += datetime.timedelta(minutes=11)
    day.say(OWNER, "undo")
    assert settle(day) and planner.texts()[-1] == "undo" and day.all()["open"] == [], "ten minutes is the limit"


def test_undo_brings_back_only_the_senders_own_and_not_one_whose_time_is_too_close(day, planner):  # noqa: F811
    day.say(OWNER, ENGLISH)
    day.say(OWNER, "/forget 1")
    day.say(OTHER, "undo")
    assert settle(day) and planner.texts() == ["undo"] and day.all()["open"] == [], "another sender's cancelled reminder is not theirs to bring back"
    day.say(OWNER, "undo")
    assert day.texts(OWNER)[-1].startswith("Reminder #1 is back as #2: tomorrow, Mon 19/10, at 13:00 (BRT): call the florist.")
    day.clock.set("2026-10-19 12:59")
    day.clock.moment += datetime.timedelta(seconds=30)
    day.say(OWNER, "/forget 2")
    day.say(OWNER, "undo")
    assert "too close to its time" in day.texts(OWNER)[-1] and day.all()["open"] == []


def test_a_list_request_is_list_shaped_and_a_report_about_reminders_goes_to_the_planning_agent(day, planner):  # noqa: F811
    portuguese(day)
    for line in ("lembretes funcionam no whatsapp?", "meus lembretes não chegaram", "lembrete 3 não chegou"):      # validate: allow english-only -- Portuguese lines, the cases of the tests
        day.say(OWNER, line)
    day.say(OWNER, "reminders are broken")
    assert settle(day) and planner.texts() == ["lembretes funcionam no whatsapp?", "meus lembretes não chegaram", "lembrete 3 não chegou", "reminders are broken"]      # validate: allow english-only -- Portuguese lines, the cases of the tests


# --- 6. no model, no route lock, no model slot, nothing in the log -------------------------------------------------------------------------------------------


def test_a_line_read_by_code_is_not_held_behind_a_running_router_and_never_queued(day, planner):  # noqa: F811
    planner.hold = {0}
    day.say(OWNER, "when does the shop open")
    assert planner.reached(0).wait(WAIT)
    day.say(OWNER, "another plain line")
    assert len(day.bridge.waiting) == 1
    before = len(day.texts(OWNER))
    day.say(OWNER, ENGLISH)
    day.say(OWNER, "what reminders do I have")
    assert day.texts(OWNER)[before:][0] == EN_REPLY and "#1" in day.texts(OWNER)[-1]
    assert len(day.bridge.waiting) == 1 and not any(t == bridge.QUEUED for t in day.texts(OWNER)[before:]), "answered at once, not kept and not refused as busy"
    assert planner.texts() == ["when does the shop open"], "no model run saw a reminder line"
    planner.open_all()
    assert settle(day) and planner.texts() == ["when does the shop open", "another plain line"]


def test_the_words_of_a_reminder_are_never_in_the_log_nor_in_a_file_of_the_project(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
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
