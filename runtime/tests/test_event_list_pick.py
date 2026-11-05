"""LP-1: a row of a list of events named by an ordinal word or by a value the list shows (runtime/event_lookup.py `_taken`, runtime/list_pick.py; scenario 38 of the acceptance).

The live case (2026-10-27): two meetings called "reuniao teste" tomorrow, at 10h and at 15h; "cancela a reuniao teste de amanha" answered with the numbered list, and "a das 15h" went on to the
model and ended in "Nao tive certeza...". Here the real calendar snapshots (test_calendar_write.py's world and the stand-in providers of test_sources_mail.py), the real family path and the real
card, a stand-in clock (Wednesday 2026-10-21 15:00 at -03:00) and a model that is never asked (or counted when it is). The list is made by `_found`, the pick goes through
`ops.say` and `event_lookup.take`, before any model call. Every expectation is a literal of this file (the events, the numbers, the sentences' fields); each oracle reads the card's own lines or
the sentence the phrase key makes from the test's own fields, never the code under test, and every rule has a vacuity test that plants a wrong result. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_list_pick.py
"""
from __future__ import annotations

import json

import pytest

import phrase_kit as pk
import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import CANCEL, CFG, OWNER, PT, TALKER, alone, build, card_problems, carry, op_text, says
from test_event_lookup_number_account import AGAIN, CARD_1, HAIR_2, HAIR_4, Model, listed, reads_at_once, say
from test_event_lookup_own_events import build as build_created, made, pending
from test_event_lookup_own_events import cards as card_ids
from test_ops_natural_writes import forget  # noqa: F401
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
event_lookup = st.load("event_lookup")
phrases = st.load("phrases")
list_pick = st.load("list_pick")
turn_gate = st.load("turn_gate")

PT = {"language": "pt-BR"}
# The calendar of scenario 38, numbered by the snapshot by day and start: the two meetings are 3 (10:00) and 5 (15:00), both tomorrow, Thursday 22/10.
MEETINGS = [
    ("21", "09:00", "10:00", "Dentist", "evden"),            # 1
    ("22", "08:00", "09:00", "Yoga", "evyoga"),               # 2
    ("22", "10:00", "11:00", "reunião teste", "evm10"),       # 3  # validate: allow english-only -- the Portuguese title under test
    ("22", "12:00", "13:00", "Lunch", "evlunch"),             # 4
    ("22", "15:00", "16:00", "reunião teste", "evm15"),       # 5  # validate: allow english-only -- the Portuguese title under test
]
LINE_38 = "Cancela a reunião teste de amanhã"      # validate: allow english-only -- the Portuguese line under test
M_3 = ("agenda#3", "reunião teste", "Thu 22/10/2026 10:00-11:00")      # validate: allow english-only -- the Portuguese title under test
M_5 = ("agenda#5", "reunião teste", "Thu 22/10/2026 15:00-16:00")      # validate: allow english-only -- the Portuguese title under test


@pytest.fixture(autouse=True)
def fresh_lists():
    event_lookup.forget_lists()
    st.load("ops_interpret").forget_all()
    yield
    event_lookup.forget_lists()


def T(key, **fields):
    """A sentence made by its phrase key and the test's own fields, in the project's language."""
    return phrases.text(key, PT, **fields)


def meetings_listed(world, monkeypatch, line=LINE_38, text=CANCEL):
    build(world, monkeypatch, events=MEETINGS)
    reply, extras = carry(world, line, text)
    assert "3. " in reply and "5. " in reply and "resend" not in extras, reply
    return reply


class Seeds:
    """A spy on the family path: the seeds `open_line` was called with (the seed's slots and the origin of its event), the real call goes on."""

    def __init__(self, monkeypatch):
        self.seen = []
        writes = ops_natural._writes()
        real = writes.open_line

        def spy(project, ctx, said, channel, sender, extras, seed=None):
            if seed is not None:
                self.seen.append((dict(seed), dict(getattr(seed, "origins", {}))))
            return real(project, ctx, said, channel, sender, extras, seed=seed)
        monkeypatch.setattr(writes, "open_line", spy)


# --- scenario 38 ------------------------------------------------------------------------------------------------------------------------------------


def test_scenario_38_a_das_15h_after_the_list_opens_the_removal_card_of_the_15h_meeting_and_never_the_10h_one(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    model, seeds = Model(monkeypatch), Seeds(monkeypatch)
    assert says(say(world, "a das 15h"), CARD_1) and model.calls == 0
    item = ops.pending(world["path"], 1)
    assert card_problems(item, *M_5) == [] and pk.said(item["body"], "CARD_CAL_EVENT", CFG, event_id="evm15")
    assert card_problems(item, *M_3) != [], "vacuity: the card of the 10h meeting reads differently"
    assert seeds.seen == [({"op": "event-cancel", "slots": {"event": 5, "source": "agenda"}}, {"event": "listed"})], "the number the pick yields is the printed one, and its origin is `listed`"
    assert len(rows(world)[1]) == 1 and item["status"] == "open"


@pytest.mark.parametrize("line, reference", [
    ("a das 15h", M_5), ("a última", M_5), ("a ultima", M_5), ("o último", M_5), ("a primeira", M_3), ("o primeiro", M_3), ("a das 10h", M_3), ("a das 3", M_5), ("a das 10", M_3),
    ("cancela a última", M_5), ("cancela a das 15h", M_5), ("the last one", M_5), ("the first one", M_3), ("the one at 3pm", M_5), ("a de amanhã", None), ("a das 15h, por favor", M_5),  # validate: allow english-only -- the Portuguese lines under test
])      # validate: allow english-only -- the Portuguese lines under test
def test_every_pick_of_the_list_opens_the_card_of_the_row_it_names_and_asks_no_model(world, monkeypatch, line, reference):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch)
    reply = say(world, line)
    if reference is None:          # both rows are tomorrow: the day names two rows
        assert reply == T("LP_SEVERAL", value=T("LP_VALUE_DAY", weekday="qui", date="22/10"), rows="3 " + T("LP_AND") + " 5") and rows(world) == ([], [])
        return
    assert says(reply, CARD_1) and model.calls == 0, line
    assert card_problems(ops.pending(world["path"], 1), *reference) == [], line


def test_a_value_no_row_has_says_so_and_keeps_the_list_so_the_number_still_works(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch)
    assert say(world, "a das 12h") == T("LP_NONE", value=T("LP_VALUE_CLOCK", time="12:00")) and rows(world) == ([], [])
    assert say(world, "a das 14h") == T("LP_NONE", value=T("LP_VALUE_CLOCK", time="14:00")), "the list is still the last thing said after a pick that opened nothing"
    assert says(say(world, "o 3"), CARD_1) and model.calls == 0
    assert card_problems(ops.pending(world["path"], 1), *M_3) == []


def test_a_pick_after_a_line_in_between_is_no_pick_and_goes_to_the_model(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}', '{"v":1,"kind":"none"}')
    say(world, "obrigado")
    before = model.calls
    say(world, "a das 15h")
    assert rows(world) == ([], []) and model.calls == before + 1, "the list was the last thing said only for the line right after it"


# --- the corpus list: the numbers 2 and 4, both at 13:00 -----------------------------------------------------------------------------------------------


def corpus_listed(world, monkeypatch):
    build(world, monkeypatch)
    listed(world)


def test_the_list_whose_numbers_are_two_and_four_is_picked_by_position_and_by_day(world, monkeypatch):
    corpus_listed(world, monkeypatch)
    Model(monkeypatch)
    assert says(say(world, "a última"), CARD_1)
    assert card_problems(ops.pending(world["path"], 1), *HAIR_4) == []
    event_lookup.forget_lists()
    listed(world)
    assert alone(say(world, "o primeiro"), "ACCT_CARD_SENT", PT, pending=2)
    assert card_problems(ops.pending(world["path"], 2), *HAIR_2) == []


@pytest.mark.parametrize("line, reference", [("a de sexta", HAIR_4), ("a do dia 23", HAIR_4), ("a do dia 22", HAIR_2), ("a de quinta", HAIR_2), ("the one on friday", HAIR_4)])
def test_a_day_the_list_shows_picks_the_row_on_that_day(world, monkeypatch, line, reference):
    corpus_listed(world, monkeypatch)
    model = Model(monkeypatch)
    assert says(say(world, line), CARD_1) and model.calls == 0, line
    assert card_problems(ops.pending(world["path"], 1), *reference) == [], line


def test_the_second_of_a_list_numbered_two_and_four_is_asked_and_never_opens_row_four_silently(world, monkeypatch):
    corpus_listed(world, monkeypatch)
    model = Model(monkeypatch)
    assert say(world, "o segundo") == T("LP_ORDINAL_CLASH", n=2, position=T("LP_VALUE_ORDINAL", p=2), m=4) and rows(world) == ([], []) and model.calls == 0
    assert says(say(world, "o 4"), CARD_1) and card_problems(ops.pending(world["path"], 1), *HAIR_4) == [], "the number the question asks for is the number path"


def test_two_rows_at_one_hour_are_asked_and_the_list_is_kept(world, monkeypatch):
    corpus_listed(world, monkeypatch)
    Model(monkeypatch)
    assert say(world, "a das 13h") == T("LP_SEVERAL", value=T("LP_VALUE_CLOCK", time="13:00"), rows="2 " + T("LP_AND") + " 4") and rows(world) == ([], [])
    assert says(say(world, "o 2"), CARD_1)


def test_a_day_with_no_row_and_a_weekday_with_no_row_are_asked_with_the_list_kept(world, monkeypatch):
    corpus_listed(world, monkeypatch)
    Model(monkeypatch)
    assert say(world, "a de segunda") == T("LP_NONE", value=T("LP_VALUE_WEEKDAY", weekday="seg")) and rows(world) == ([], [])
    assert say(world, "a do dia 25") == T("LP_NONE", value=T("LP_VALUE_DAY", weekday="dom", date="25/10")) and rows(world) == ([], [])


def test_an_ordinal_beyond_the_list_is_asked(world, monkeypatch):
    corpus_listed(world, monkeypatch)
    Model(monkeypatch)
    assert say(world, "o quinto") == T("LP_NONE", value=T("LP_VALUE_ORDINAL", p=5)) and rows(world) == ([], [])


def test_a_weekday_word_is_read_as_the_day_and_as_the_position_and_asked_when_they_differ(world, monkeypatch):
    corpus_listed(world, monkeypatch)
    Model(monkeypatch)
    # the list holds Thursday (row 2) and Friday (row 4): "a sexta" is Friday, and the sixth does not exist -> the Friday row
    assert says(say(world, "a sexta"), CARD_1) and card_problems(ops.pending(world["path"], 1), *HAIR_4) == []
    event_lookup.forget_lists()
    listed(world)
    # "a quinta": Thursday is row 2; the fifth does not exist -> the Thursday row
    assert alone(say(world, "a quinta"), "ACCT_CARD_SENT", PT, pending=2)
    assert card_problems(ops.pending(world["path"], 2), *HAIR_2) == []


SESSIONS = [("22", "08:00", "09:00", "Sessao alfa", "evs0"), ("22", "09:00", "10:00", "Sessao beta", "evs1"), ("22", "10:00", "11:00", "Sessao gama", "evs2"),
            ("22", "11:00", "12:00", "Sessao delta", "evs3")]


def sessions_listed(world, monkeypatch, tail):
    build(world, monkeypatch, events=SESSIONS + tail)
    reply, _ = carry(world, "Cancela a sessao", CANCEL)
    assert reply.count("\n") >= 6, reply
    Model(monkeypatch)


def test_a_sexta_when_the_friday_row_is_not_the_sixth_is_asked_and_neither_row_is_opened_silently(world, monkeypatch):
    """Probe 3: seven rows, Friday is the fifth and the sixth is a Sunday: "a sexta" is the day (5) or the position (6): asked, no card."""
    sessions_listed(world, monkeypatch, [("23", "08:00", "09:00", "Sessao omega", "evs4"), ("25", "08:00", "09:00", "Sessao sigma", "evs5"), ("25", "09:00", "10:00", "Sessao zeta", "evs6")])
    assert say(world, "a sexta") == T("LP_DAY_OR_POSITION", a="5", position=T("LP_VALUE_ORDINAL", p=6), b="6") and rows(world) == ([], [])
    assert says(say(world, "o 5"), CARD_1), "the number the question asks for is the number path"
    assert pk.said(ops.pending(world["path"], 1)["body"], "CARD_CAL_EVENT", CFG, event_id="evs4")


def test_a_sexta_when_the_friday_row_is_the_sixth_opens_it_because_both_readings_name_it(world, monkeypatch):
    sessions_listed(world, monkeypatch, [("22", "12:00", "13:00", "Sessao omega", "evs4"), ("23", "08:00", "09:00", "Sessao sigma", "evs5")])
    assert says(say(world, "a sexta"), CARD_1)
    assert pk.said(ops.pending(world["path"], 1)["body"], "CARD_CAL_EVENT", CFG, event_id="evs5"), "the sixth row is the Friday row"


# --- the change list --------------------------------------------------------------------------------------------------------------------------------


def test_after_a_change_list_a_das_15h_carries_the_new_time_recorded_with_the_list(world, monkeypatch):
    build(world, monkeypatch, events=MEETINGS)
    model = Model(monkeypatch)
    reply, _ = carry(world, "Muda a reunião teste para as 17h", op_text("event-change", {"time": "as 17h"}, time_iso="2026-10-21T17:00", weekday="wed"))      # validate: allow english-only -- the Portuguese line under test
    assert "3. " in reply and "5. " in reply, reply
    assert says(say(world, "a das 15h"), CARD_1) and model.calls == 0
    body = ops.pending(world["path"], 1)["body"]
    assert pk.said(body, "CARD_CAL_SNAPSHOT", CFG, reference="agenda#5", read_at="2026-10-21T17:00:00Z"), body
    assert pk.said(body, "CARD_CAL_BEFORE_WHEN", CFG, when="Thu 22/10/2026 15:00-16:00 (America/Sao_Paulo)") and pk.said(body, "CARD_CAL_AFTER_WHEN", CFG, when="Thu 22/10/2026 17:00-18:00 (America/Sao_Paulo)"), "17h is the time the person asked for"


@pytest.mark.parametrize("line", ["às 15h", "15h", "para as 15h", "as 17h"])
def test_a_time_said_after_a_change_list_with_no_lead_is_never_taken_for_a_row(world, monkeypatch, line):
    build(world, monkeypatch, events=MEETINGS)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    carry(world, "Muda a reunião teste para as 17h", op_text("event-change", {"time": "as 17h"}, time_iso="2026-10-21T17:00", weekday="wed"))      # validate: allow english-only -- the Portuguese line under test
    say(world, line)
    assert rows(world) == ([], []) and model.calls == 1, "the line is no pick: it goes on as it did, to the model"


# --- the other lists and the guards ----------------------------------------------------------------------------------------------------------------


def test_the_items_list_of_a_calendar_is_picked_by_position_and_a_bare_pick_asks_what_to_do(world, monkeypatch):
    build(world, monkeypatch, events=MEETINGS)
    reads_at_once(world)
    model = Model(monkeypatch)
    shown = say(world, "lista os eventos")
    assert "3. " in shown and "5. " in shown, shown
    assert say(world, "a última") == T("EV_LIST_WHAT", n=5), "a bare pick on an items list asks what to do with the row, as a bare number does"
    assert says(say(world, "cancela a das 15h"), CARD_1) and model.calls == 0
    assert card_problems(ops.pending(world["path"], 1), *M_5) == []


def test_the_items_list_of_a_calendar_holds_positions_of_one_section_only(world, monkeypatch):
    build(world, monkeypatch, events=MEETINGS)
    reads_at_once(world)
    Model(monkeypatch)
    say(world, "lista os eventos")
    record = next(iter(event_lookup._LISTS.values()))
    assert [s["position"] for s in record["shown"]] == [1, 2, 3, 4, 5] and record["more"] is False


def test_the_record_holds_clocks_days_accounts_and_positions_and_no_title_line_or_text(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    record = next(iter(event_lookup._LISTS.values()))
    assert record["shown"] == [{"day": "2026-10-22", "start": "10:00", "account": "google", "position": 1}, {"day": "2026-10-22", "start": "15:00", "account": "google", "position": 2}]
    assert record["more"] is False
    kept = repr(event_lookup._LISTS).lower()
    for piece in ("reuni", "teste", "cancela", "yoga", "dentist", "lunch", "evm1"):
        assert piece not in kept, piece


def test_a_pick_after_a_refreshed_snapshot_is_asked_again_and_opens_no_card(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch)
    world["snaps"].providers.events[("google", fgw.CALENDAR)].insert(0, tsm.event(9, "2026-10-21T08:00:00-03:00", "2026-10-21T08:30:00-03:00", "Breakfast", id="evnew"))
    world["snaps"].later(minutes=5)
    world["snaps"].refresh("agenda")
    assert says(say(world, "a das 15h"), AGAIN) and model.calls == 0 and rows(world) == ([], [])


def test_a_pick_after_a_new_decision_card_opens_no_event_card(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    ops.event_create(world["path"], "google", "Haircut with Joe", "2026-10-23T13:00")
    say(world, "a das 15h")
    titles = [i["title"] for i in rows(world)[1]]
    assert model.calls == 1 and len(titles) == 1 and pk.said(titles[0], "TITLE_CAL_CREATE", CFG), "the list ended when a card was made: no removal card"


def test_a_sender_who_may_not_read_the_calendar_gets_no_pick_even_from_a_record_of_their_own(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    ctx = ops_core.context(world["path"])
    shown = [{"day": "2026-10-22", "start": "10:00", "account": "google", "position": 1}, {"day": "2026-10-22", "start": "15:00", "account": "google", "position": 2}]
    event_lookup._remember(ctx, "messaging", TALKER, "event-cancel", None, [("agenda", 3, "x"), ("agenda", 5, "x")], shown)
    event_lookup._remember(ctx, "messaging", OWNER, "event-cancel", None, [("agenda", 3, "x"), ("agenda", 5, "x")], shown)
    now, writes = ops_natural._clock(), ops_natural._writes()
    assert event_lookup.take(world["path"], ctx, "a das 12h", TALKER, {}, writes, now) is None, "the talker has no right to read a snapshot: no row is named"
    assert event_lookup.take(world["path"], ctx, "a das 12h", OWNER, {}, writes, now) == T("LP_NONE", value=T("LP_VALUE_CLOCK", time="12:00")), "control: the owner's record is read"


@pytest.mark.parametrize("minute, opens", [("15:09", True), ("15:11", False)])
def test_a_pick_is_valid_for_ten_minutes_and_a_new_line_after_them(world, monkeypatch, minute, opens):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    world["clock"].set(f"2026-10-21 {minute}")
    reply = say(world, "a última")
    assert (says(reply, CARD_1) and model.calls == 0) if opens else (model.calls == 1 and rows(world) == ([], [])), minute


@pytest.mark.parametrize("line", ["os dois últimos", "as duas", "ambas", "a das 15h e muda para as 17h", "a reunião das 15h", "aprovo a segunda", "o do banco"])      # validate: allow english-only -- the Portuguese lines under test
def test_a_line_that_is_not_a_closed_pick_or_names_no_day_the_list_has_goes_on_to_the_model(world, monkeypatch, line):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    say(world, line)
    assert model.calls == 1 and rows(world) == ([], []), line


def test_a_weekday_with_no_row_is_asked_in_words_of_the_day_and_never_guessed(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    Model(monkeypatch)
    assert say(world, "a de sábado") == T("LP_NONE", value=T("LP_VALUE_WEEKDAY", weekday="sáb")) and rows(world) == ([], [])      # validate: allow english-only -- the Portuguese weekday under test


def test_the_number_form_is_unchanged_and_wins_over_a_pick(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch)
    assert says(say(world, "cancela o 3"), CARD_1) and model.calls == 0
    assert card_problems(ops.pending(world["path"], 1), *M_3) == []


# --- created events ---------------------------------------------------------------------------------------------------------------------------------


def test_the_list_of_two_created_events_is_picked_by_the_last_and_opens_the_card_of_the_later(world, monkeypatch):
    build_created(world, monkeypatch)
    made(world)
    made(world, start="2026-10-23T13:00")
    model = Model(monkeypatch)
    reply, _ = carry(world, "Cancela o corte de cabelo", CANCEL)
    assert "1. " in reply and "2. " in reply, reply
    record = next(iter(event_lookup._LISTS.values()))
    assert [s["account"] for s in record["shown"]] == ["google", "google"] and [s["start"] for s in record["shown"]] == ["13:00", "13:00"]
    assert alone(say(world, "a última"), "ACCT_CARD_SENT", PT, pending=3) and model.calls == 0      # validate: allow english-only -- the Portuguese sentence under test
    body = pending(world, 3)["body"]
    assert pk.said(body, "CARD_CAL_EVENT", CFG, event_id="ev0002") and pk.said(body, "CARD_CAL_WHEN", CFG, when="Fri 23/10/2026 13:00-14:00 (America/Sao_Paulo)"), body
    assert card_ids(world) == [1, 2, 3]


# --- vacuity ------------------------------------------------------------------------------------------------------------------------------------------


def test_vacuity_without_the_pick_call_a_das_15h_goes_to_the_model_and_the_oracle_sees_it(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    monkeypatch.setattr(list_pick, "read", lambda said: None)
    say(world, "a das 15h")
    assert model.calls == 1 and rows(world) == ([], []), "the planted _taken reads no pick: the card of the scenario is never opened"


def test_vacuity_a_pick_that_chooses_the_first_row_opens_the_wrong_card_and_the_card_oracle_sees_it(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    Model(monkeypatch)
    monkeypatch.setattr(list_pick, "choose", lambda form, rows_, day_of, more=False: ("one", 0, None))
    say(world, "a das 15h")
    assert card_problems(ops.pending(world["path"], 1), *M_5) != [], "the planted choice opened the 10h card"
