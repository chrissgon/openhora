"""LP-1: the bridge leaves "a das 15h" to the list when the list is live (runtime/messaging_turn.py `reminder_form`, runtime/messaging_bridge.py `Bridge.list_picks`, runtime/ops_say.py
`event_list_picks`, runtime/event_lookup.py `picks`).

The finding behind it (2026-10-28): the parse of a messaging line reads a short line that holds a clock and nothing that asks for work ("a das 15h", "the one at 3pm") as a reminder with no words, and the
bridge's row `reminder-form` takes it before the operations layer's row `event-list-number` can; the very line of scenario 38 therefore asked "What should I remind you of?". The row now declines that one
shape when the sender's live list of events would answer the line as a pick. Held here: the row declines only for a bare reminder and only when the operations layer says the list takes the line; every other
intent goes where it went; `Bridge.list_picks` asks the operations layer by name and treats a missing function or a refusal as "no list"; and `picks` is read-only and true only for the line right after a list,
from a sender who may read it, for a closed pick that is no number form. The whole path is also in the entry replay (`entry_ext/lp-1.*`, trace `say-natural` then `event-list-number`).
Every expectation is a literal of this file; each rule has a vacuity test. Offline; no model is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_bridge_list_pick.py
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import standin_tree as st
import test_sources_mail as tsm  # noqa: F401
from test_calendar_write import fgw, rows, world  # noqa: F401
from test_event_list_pick import LINE_38, MEETINGS, CANCEL, OWNER, TALKER, build, carry, ops, ops_core, ops_natural, event_lookup, meetings_listed, fresh_lists  # noqa: F401
from test_event_lookup_number_account import Model, say
from test_ops_natural_writes import forget  # noqa: F401

messaging_turn = st.load("messaging_turn")
messaging_bridge = st.load("messaging_bridge")


class Stub:
    """A bridge that records what the row asked: `list_picks` answers `picked`, `remind.natural` records the intents it was given and answers True."""

    def __init__(self, picked):
        self.picked, self.asked, self.taken = picked, [], []
        self.remind = SimpleNamespace(natural=lambda project, chat, intent: self.taken.append(intent) or True)

    def list_picks(self, project, chat, text):
        self.asked.append(text)
        return self.picked


def turn(intent, kind="natural"):
    return SimpleNamespace(kind=kind, intent=intent, project={"id": "p"}, chat="chat-1")


BARE = {"op": "remind", "how": "bare", "text": "a das 15h"}      # validate: allow english-only -- the Portuguese line under test


def test_a_bare_reminder_that_the_live_list_takes_as_a_pick_is_left_to_the_operations_layer():
    bridge = Stub(picked=True)
    assert messaging_turn.reminder_form(bridge, turn(BARE)) is False
    assert bridge.asked == ["a das 15h"] and bridge.taken == [], "the row asked once and made no reminder"      # validate: allow english-only -- the Portuguese line under test


def test_with_no_list_the_bare_reminder_is_made_as_it_always_was():
    bridge = Stub(picked=False)
    assert messaging_turn.reminder_form(bridge, turn(BARE)) is True
    assert bridge.taken == [BARE]


@pytest.mark.parametrize("intent", [
    {"op": "remind", "how": "trigger", "text": "me lembra de ligar para o dentista"},      # validate: allow english-only -- the Portuguese line under test
    {"op": "remind", "how": "note", "text": "anota comprar pão"},      # validate: allow english-only -- the Portuguese line under test
    {"op": "reminders", "how": "trigger", "text": "meus lembretes"},      # validate: allow english-only -- the Portuguese line under test
    {"op": "calendar-event-create", "how": "ask", "text": "marca dentista amanha as 15h"},      # validate: allow english-only -- the Portuguese line under test
])
def test_every_other_intent_of_the_row_goes_where_it_went_and_the_list_is_not_even_asked(intent):
    bridge = Stub(picked=True)
    assert messaging_turn.reminder_form(bridge, turn(intent)) is True
    assert bridge.asked == [] and bridge.taken == [intent]


def test_a_write_and_a_line_that_is_not_natural_are_not_this_rows_and_ask_nothing():
    bridge = Stub(picked=True)
    assert messaging_turn.reminder_form(bridge, turn({"op": "write", "text": "x"})) is False
    assert messaging_turn.reminder_form(bridge, turn({"text": "x"}, kind="say")) is False
    assert bridge.asked == [] and bridge.taken == []


def test_vacuity_a_row_that_never_asks_the_list_makes_the_reminder_and_the_oracle_sees_it(monkeypatch):
    bridge = Stub(picked=True)
    bridge.list_picks = lambda project, chat, text: False
    assert messaging_turn.reminder_form(bridge, turn(BARE)) is True and bridge.taken == [BARE], "the planted bridge answers no list: the reminder asked for words, the line of scenario 38"


# --- Bridge.list_picks ----------------------------------------------------------------------------------------------------------------------------


def real(ops_object):
    return SimpleNamespace(ops=ops_object, key=lambda chat: f"telegram:{chat}")


class Boom(Exception):
    pass


def test_the_bridge_asks_the_operations_layer_with_the_project_the_text_and_the_senders_key():
    seen = []
    ops_object = SimpleNamespace(event_list_picks=lambda path, text, sender: seen.append((path, text, sender)) or True, OpsError=Boom)
    assert messaging_bridge.Bridge.list_picks(real(ops_object), {"path": "/p"}, "77", "a última") is True      # validate: allow english-only -- the Portuguese line under test
    assert seen == [("/p", "a última", "telegram:77")]      # validate: allow english-only -- the Portuguese line under test


def test_an_operations_object_without_the_function_or_one_that_refuses_has_no_list():
    assert messaging_bridge.Bridge.list_picks(real(SimpleNamespace(OpsError=Boom)), {"path": "/p"}, "77", "a última") is False      # validate: allow english-only -- the Portuguese line under test

    def refuse(path, text, sender):
        raise Boom("no")
    assert messaging_bridge.Bridge.list_picks(real(SimpleNamespace(event_list_picks=refuse, OpsError=Boom)), {"path": "/p"}, "77", "a última") is False      # validate: allow english-only -- the Portuguese line under test


# --- event_lookup.picks, through the real operations layer -----------------------------------------------------------------------------------------


def peeked(world, line, sender=OWNER):
    return ops.event_list_picks(world["path"], line, sender)


def test_the_list_takes_a_pick_right_after_it_and_asking_changes_nothing(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    Model(monkeypatch)
    before = repr(event_lookup._LISTS)
    assert peeked(world, "a das 15h") is True and peeked(world, "a das 15h") is True      # validate: allow english-only -- the Portuguese line under test
    assert repr(event_lookup._LISTS) == before, "read-only: nothing was dropped or counted"
    assert say(world, "a das 15h").startswith("O card #1"), "and the list still answers the line"      # validate: allow english-only -- the Portuguese line under test


@pytest.mark.parametrize("line, expected", [("a última", True), ("a das 12h", True), ("o 3", False), ("cancela o 3", False), ("15h", False), ("às 15h", False), ("a das 15h e muda para as 17h", False),      # validate: allow english-only -- the Portuguese lines under test
                                             ("o do banco", False), ("oi", False), ("", False)])
def test_only_a_closed_pick_that_is_no_number_form_is_one(world, monkeypatch, line, expected):
    meetings_listed(world, monkeypatch)
    Model(monkeypatch)
    assert peeked(world, line) is expected, line


def test_no_list_another_sender_a_line_in_between_a_new_card_and_the_window_say_no(world, monkeypatch):
    build(world, monkeypatch, events=MEETINGS)
    Model(monkeypatch, '{"v":1,"kind":"none"}')
    assert peeked(world, "a das 15h") is False, "no list yet"      # validate: allow english-only -- the Portuguese line under test
    carry(world, LINE_38, CANCEL)
    assert peeked(world, "a das 15h", sender=TALKER) is False, "another sender: no list of their own"      # validate: allow english-only -- the Portuguese line under test
    assert peeked(world, "a das 15h") is True      # validate: allow english-only -- the Portuguese line under test
    world["clock"].set("2026-10-21 15:11")
    assert peeked(world, "a das 15h") is False, "eleven minutes later"      # validate: allow english-only -- the Portuguese line under test
    world["clock"].set("2026-10-21 15:00")
    event_lookup.forget_lists()
    carry(world, LINE_38, CANCEL)
    ops.event_create(world["path"], "google", "Haircut with Joe", "2026-10-23T13:00")
    assert peeked(world, "a das 15h") is False, "a decision card made since the list ends it"      # validate: allow english-only -- the Portuguese line under test


def test_a_list_that_a_line_already_passed_through_say_no_longer_picks(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    Model(monkeypatch, '{"v":1,"kind":"none"}')
    say(world, "obrigado")      # validate: allow english-only -- the Portuguese line under test
    assert peeked(world, "a das 15h") is False      # validate: allow english-only -- the Portuguese line under test


def test_vacuity_a_peek_that_counted_the_line_would_end_the_list_before_it_is_used(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    Model(monkeypatch)
    record = next(iter(event_lookup._LISTS.values()))
    record["seen"] = 1          # what a counting peek would leave behind
    assert peeked(world, "a das 15h") is False      # validate: allow english-only -- the Portuguese line under test
    record["seen"] = 0
    assert peeked(world, "a das 15h") is True      # validate: allow english-only -- the Portuguese line under test
