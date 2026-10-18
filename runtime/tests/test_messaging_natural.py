"""Reminders asked in the person's own words, through a messaging bridge (package NR-1): `me lembra amanha as 13h do corte de cabelo`, `/remind corte de cabelo as 13hrs
amanha`, the question asked back when a line can be read two ways or lacks the hour, the draft that finishes it (ten minutes, one per chat, lost on a restart, dropped by
any other line), the calendar that is not built yet, the lists and the forgets in words, a profile without the group, and the rule behind all of it: code reads the
line, so no model runs, no route lock is taken and no model slot is held. Over the REAL operations layer, a stand-in messenger, a stand-in planner that records every
line a model would have been given, and a stand-in clock (Sunday 2026-10-18 14:00 at -03:00). The parser is in test_natural_time.py, the pure rules and the operation
in test_natural_reminders.py. Offline, no model, no network; invented words.

The Portuguese lines and the sentences they must get are in natural_cases_pt_br.py, the one test file written in Portuguese on purpose.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural.py
"""
from __future__ import annotations

import json

import natural_cases_pt_br as pt
import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_queue import WAIT, clocked, planner, settle  # noqa: F401  (the planner stand-in, the bridge's clock and the waiting for its jobs)
from test_messaging_reminders import day, listed  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER, STAFF, accept
from test_sender_profiles_bridge import NOT_ENABLED, OTHER, lab  # noqa: F401  (the lab fixture)

bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
ops = st.load("ops")
phrases = st.load("phrases")

PT = {"language": "pt-BR"}
HAIRCUT = "me lembra amanhã às 13h do corte de cabelo"      # validate: allow english-only -- a Portuguese line, the case of the tests
ENGLISH = "remind me tomorrow at 1 pm to call the dentist"


def portuguese(day):  # noqa: F811
    accept(day.path, language="pt-BR")


def no_model(planner):  # noqa: F811
    assert planner.texts() == [], "a line read by code never reaches the planning agent"


# --- 1. the lines that make a reminder at once ---------------------------------------------------------------------------------------------------------


def test_a_slash_command_in_words_makes_the_reminder_and_answers_in_the_language_with_the_weekday_the_date_the_zone_and_the_undo(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "/remind corte de cabelo as 13hrs amanha")
    assert day.texts(OWNER) == [pt.REPLY_CUT]
    row = day.all()["open"][0]
    assert row["due"] == "2026-10-19 13:00" and row["text"] == "corte de cabelo" and row["zone"] == "BRT"
    no_model(planner)
    assert day.bridge.waiting == [] and day.bridge.exclusive == set() or not day.bridge.exclusive, "no model slot, no route lock"


def test_a_line_with_a_remind_word_makes_the_same_reminder_in_any_word_order(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, HAIRCUT)
    assert day.texts(OWNER) == [pt.REPLY_CUT]
    day.say(OWNER, "me lembra do corte de cabelo amanhã às 13h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.REPLY_CUT.replace("#1", "#2").replace("/forget 1", "/forget 2")
    assert [r["text"] for r in day.all()["open"]] == ["corte de cabelo", "corte de cabelo"]
    no_model(planner)


def test_the_words_are_echoed_only_in_text_mode(day, planner):  # noqa: F811
    portuguese(day)
    listed(day, notices="count")
    accept(day.path, language="pt-BR")
    day.say(OWNER, HAIRCUT)
    assert day.texts(OWNER) == [pt.REPLY_CUT_COUNT] and "cabelo" not in " ".join(day.texts(OWNER))
    assert day.all()["open"][0]["text"] == "corte de cabelo", "the words are in the store, which the owner reads in the terminal"
    no_model(planner)


def test_a_time_of_day_that_has_passed_says_so_and_gives_tomorrows(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "/remind 13:00 corte de cabelo")
    assert day.texts(OWNER) == [pt.PAST_TODAY]
    day.say(OWNER, "me lembra às 13h do dentista")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert "13:00 de hoje já passou: amanhã, seg 19/10, às 13:00 (BRT): dentista" in day.texts(OWNER)[-1]      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_an_english_project_gets_english_in_the_same_shape(day, planner):  # noqa: F811
    day.say(OWNER, ENGLISH)
    assert day.texts(OWNER) == ["Reminder #1: tomorrow, Mon 19/10, at 13:00 (BRT): call the dentist. To undo: /forget 1."]
    day.say(OWNER, "Please remind me on friday to pay the rent")
    assert day.texts(OWNER)[-1] == "Fri 23/10: at what time? Reply with a time, for example 1 pm."
    day.say(OWNER, "remind me to stretch")
    assert day.texts(OWNER)[-1] == "When? Example: remind me tomorrow at 1 pm to call the dentist"
    no_model(planner)


def test_a_line_in_the_other_language_is_understood_too(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, ENGLISH)
    assert day.texts(OWNER) == ["Lembrete #1: amanhã, seg 19/10, às 13:00 (BRT): call the dentist. Para desfazer: /forget 1."]      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


# --- 2. what is asked back, and the draft ----------------------------------------------------------------------------------------------------------


def test_an_hour_with_no_marker_asks_09_or_21_and_the_next_line_finishes_it(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER) == [pt.ASK_NINE] and day.all()["open"] == [], "a question makes nothing"
    assert set(day.bridge.remind.drafts) == {OWNER}
    day.say(OWNER, "21h")
    assert day.texts(OWNER)[-1] == pt.REPLY_FRIDAY_21 and day.bridge.remind.drafts == {}
    assert day.all()["open"][0]["due"] == "2026-10-23 21:00" and day.all()["open"][0]["text"] == "ligar para a gráfica"      # validate: allow english-only -- a Portuguese line, the case of the tests
    no_model(planner)


def test_any_other_line_drops_the_question_and_is_handled_as_a_new_line(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "when does the shop open")
    assert day.bridge.remind.drafts == {} and settle(day)
    assert planner.texts() == ["when does the shop open"], "the other line went on to the planning agent as any plain line"
    day.say(OWNER, "21h")
    assert settle(day) and planner.texts()[-1] == "21h" and day.all()["open"] == [], "the question is gone: 21h alone is a plain line now"
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "/reminders")
    assert day.bridge.remind.drafts == {} and day.texts(OWNER)[-1] == "northwind-shop: nenhum lembrete pendente."      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "sexta às 10h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.all()["open"] == [] and day.bridge.remind.drafts == {}, "a time that is not one of the readings does not finish it"


def test_the_question_is_forgotten_after_ten_minutes_and_on_a_restart_and_is_kept_per_chat(day, planner):  # noqa: F811
    portuguese(day)
    now = clocked(day)
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OTHER, "21h")
    assert day.bridge.remind.drafts.keys() == {OWNER}, "another chat's line neither finishes nor drops it"
    assert settle(day) and planner.texts() == ["21h"]
    now[0] += 599
    day.say(OWNER, "21h")
    assert day.all()["open"][0]["due"] == "2026-10-23 21:00", "nine minutes and a half: still there"
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    now[0] += 601
    day.say(OWNER, "21h")
    assert len(day.all()["open"]) == 1 and settle(day) and planner.texts()[-1] == "21h", "ten minutes and a second: forgotten, a plain line"
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    fresh = bridge.Bridge(ops, day.bridge.projects, day.bridge.messenger, ledgers.Ledger(str(day.tmp / "ledger-data"), "telegram"), "telegram", day.log.append,
                          clock=lambda: "2026-10-11T10:00:00+00:00")
    assert fresh.remind.drafts == {}, "lost on a restart"
    fresh.handle({"update_id": 9, "sender": OWNER, "chat": OWNER, "private": True, "text": "21h", "action": None, "action_ref": None, "reply_to": None})
    assert len(day.all()["open"]) == 1 and settle(day)


def test_a_day_with_no_hour_asks_the_hour_and_a_remind_word_with_no_time_asks_when(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "me lembra de ligar amanhã")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_TIME_TOMORROW and day.all()["open"] == []
    day.say(OWNER, "9h")
    assert day.all()["open"][0]["due"] == "2026-10-19 09:00" and day.all()["open"][0]["text"] == "ligar"
    day.say(OWNER, "me lembra do remédio")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_WHEN
    day.say(OWNER, "daqui a 2 horas")
    by_id = {r["id"]: r for r in day.all()["open"]}
    assert by_id[2]["due"] == "2026-10-18 16:00" and by_id[2]["text"] == "remédio"      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "/remind")
    assert day.texts(OWNER)[-1] == pt.SLASH_ASK_WHEN, "never the English usage sentence for a Portuguese project"
    no_model(planner)


def test_the_words_missing_are_asked_and_the_next_line_is_them(day, planner):  # noqa: F811
    day.say(OWNER, "remind me tomorrow at 9am")
    assert day.texts(OWNER)[-1] == "What should I remind you of? Reply with the words to send."
    day.say(OWNER, "water the plants")
    assert day.all()["open"][0]["text"] == "water the plants" and day.all()["open"][0]["due"] == "2026-10-19 09:00"
    no_model(planner)


def test_a_line_with_a_time_and_neither_kind_of_word_asks_a_reminder_or_a_calendar_event(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "corte de cabelo amanhã 13h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER) == [pt.ASK_KIND] and day.all()["open"] == []
    day.say(OWNER, "lembrete")
    assert day.texts(OWNER)[-1] == pt.REPLY_CUT and day.all()["open"][0]["text"] == "corte de cabelo"
    day.say(OWNER, "anote corte de cabelo amanhã às 13hrs")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_KIND
    day.say(OWNER, "agenda")
    assert day.texts(OWNER)[-1] == pt.NOT_BUILT and len(day.all()["open"]) == 1, "the calendar is not built: nothing is made in its place"
    day.say(OWNER, "anote corte de cabelo amanhã às 13hrs")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "sim")
    assert settle(day) and len(day.all()["open"]) == 1 and day.bridge.remind.drafts == {}
    assert planner.texts() == ["sim"], "a yes does not say which of the two: the question is dropped and the yes is a plain line"
    planner.calls.clear() if hasattr(planner, "calls") else None
    listed(day, notices="count")
    accept(day.path, language="pt-BR")
    day.say(OWNER, "corte de cabelo amanhã 13h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_KIND_COUNT


def test_anote_with_a_day_and_no_hour_asks_the_hour_then_which_kind(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "anote corte de cabelo amanhã")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1].endswith("a que horas? Responda com uma hora, por exemplo 13h.")      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "13h")
    assert day.texts(OWNER)[-1] == pt.ASK_KIND
    day.say(OWNER, "lembrete")
    assert day.texts(OWNER)[-1] == pt.REPLY_CUT
    no_model(planner)


def test_the_calendar_is_not_built_and_a_line_that_asks_for_it_makes_no_reminder(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "marca na agenda o dentista sexta às 9")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER) == [pt.NOT_BUILT] and day.all()["open"] == [] and day.bridge.remind.drafts == {}
    day.say(OWNER, "put on my calendar the dentist friday at 9")
    assert day.texts(OWNER)[-1] == pt.NOT_BUILT
    no_model(planner)


# --- 3. the policy ----------------------------------------------------------------------------------------------------------------------------------


def test_a_profile_without_the_group_gets_the_typed_refusal_for_a_remind_word_and_its_bare_lines_go_on_to_the_planning_agent(day, planner):  # noqa: F811
    day.say(STAFF, ENGLISH)
    assert NOT_ENABLED in day.texts(STAFF)[-1] and "remind" in day.texts(STAFF)[-1] and day.all()["open"] == []
    typed = len(day.texts(STAFF))
    day.say(STAFF, "/remind tomorrow 1 pm call the dentist")
    assert day.texts(STAFF)[typed:] and NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "what reminders do I have")
    assert NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "forget reminder 3")
    assert NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "haircut tomorrow 1pm")
    assert settle(day) and planner.texts() == ["haircut tomorrow 1pm"], "a line that only looks like a request is a plain line for a sender who cannot remind"
    assert day.all()["open"] == [] and day.bridge.remind.drafts == {}


def test_a_profile_that_may_remind_and_may_not_talk_still_reminds_in_words(day, planner):  # noqa: F811
    from test_messaging_reminders import WITH
    from test_sender_profiles_bridge import configure
    configure(day, [{"id": OWNER, "policy": "clerk"}], policies={**WITH, "clerk": ["read-limited", "reminders"]})
    day.say(OWNER, ENGLISH)
    assert day.texts(OWNER)[-1].startswith("Reminder #1: tomorrow, Mon 19/10, at 13:00"), "the group asked is the operation's own, not `talk`"
    day.say(OWNER, "when does the shop open")
    assert settle(day) and NOT_ENABLED in day.texts(OWNER)[-1] and planner.texts() == []


def test_a_reminder_in_words_goes_only_to_the_chat_that_asked_for_it(day, planner):  # noqa: F811
    day.say(OWNER, ENGLISH)
    day.say(OTHER, "remind me tomorrow at 1 pm to take the bread out")
    day.clock.set("2026-10-19 13:00")
    day.bridge.tick()
    assert [t for t in day.texts(OWNER) if t.startswith("Reminder:")] == ["Reminder: call the dentist"]
    assert [t for t in day.texts(OTHER) if t.startswith("Reminder:")] == ["Reminder: take the bread out"]
    assert not any("dentist" in t or "bread" in t or t.startswith("Reminder") for t in day.texts(STAFF)), "nobody else is told"


# --- 4. lists and forgets in words --------------------------------------------------------------------------------------------------------------------


def test_the_list_and_the_forget_in_words_do_what_the_typed_commands_do(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "quais lembretes eu tenho?")
    assert day.texts(OWNER)[-1] == "northwind-shop: nenhum lembrete pendente."      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "esquece o lembrete")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == "northwind-shop: nenhum lembrete pendente.", "nothing to choose from: no question"      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, HAIRCUT)
    day.say(OWNER, "meus lembretes")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == "northwind-shop: lembretes pendentes (BRT)\n#1 2026-10-19 13:00 corte de cabelo"      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "esquece o lembrete")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-2].startswith("northwind-shop: lembretes pendentes") and day.texts(OWNER)[-1] == pt.WHICH
    day.say(OWNER, "esquece o lembrete 1")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.FORGOT and day.all()["open"] == []
    day.say(OTHER, "forget reminder 1")
    assert day.texts(OTHER)[-1] == "Não há lembrete 1 esperando por você."      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


# --- 5. no model, no route lock, no model slot, nothing in the log -------------------------------------------------------------------------------------------


def test_a_line_read_by_code_is_not_held_behind_a_running_router_and_never_queued(day, planner):  # noqa: F811
    planner.hold = {0}
    day.say(OWNER, "when does the shop open")
    assert planner.reached(0).wait(WAIT)
    day.say(OWNER, "another plain line")
    assert len(day.bridge.waiting) == 1
    before = len(day.texts(OWNER))
    day.say(OWNER, ENGLISH)
    day.say(OWNER, "what reminders do I have")
    assert day.texts(OWNER)[before:][0].startswith("Reminder #1: tomorrow, Mon 19/10, at 13:00") and "#1" in day.texts(OWNER)[-1]
    assert len(day.bridge.waiting) == 1 and not any(t == bridge.QUEUED for t in day.texts(OWNER)[before:]), "answered at once, not kept and not refused as busy"
    assert planner.texts() == ["when does the shop open"], "no model run saw a reminder line"
    planner.open_all()
    assert settle(day) and planner.texts() == ["when does the shop open", "another plain line"]


def test_the_words_of_a_reminder_are_never_in_the_log_nor_in_a_file_of_the_project(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, HAIRCUT)
    day.say(OWNER, "me lembra sexta às 9 de ligar para a gráfica")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "21h")
    day.say(OWNER, "corte de barba amanhã 13h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "agenda")
    log = " ".join(day.log)
    assert not any(w in log for w in ("cabelo", "gráfica", "barba", "ligar")), day.log      # validate: allow english-only -- words of the lines above
    from pathlib import Path
    files = "".join(p.read_text(errors="ignore") for p in Path(day.path).rglob("*.md"))
    assert "cabelo" not in files and "gráfica" not in files      # validate: allow english-only -- words of the lines above
    assert "cabelo" not in json.dumps([m for m in day.sent() if not m["message"]["text"].startswith("Lembrete #")])      # validate: allow english-only -- a word of the lines above
