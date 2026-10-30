"""ACEITE-37: whether a list of events is still the last thing said to a sender (runtime/event_lookup.py `list_open`, runtime/ops_say.py `list_waits`), the read the bridge makes before a bare
word brings a card back. The list is the real one of the event tests (test_event_list_pick.py); the expectations are literals of this file; each has a vacuity case. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_list_waits_events.py
"""
from __future__ import annotations

import standin_tree as st
from test_calendar_write import world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_list_pick import LINE_38, MEETINGS, fresh_lists, meetings_listed  # noqa: F401
from test_event_lookup import OWNER, TALKER, says
from test_event_lookup_number_account import CARD_1, Model, say

ops = st.load("ops")


def test_the_list_that_was_just_shown_is_waiting_for_its_sender_only(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    assert ops.list_waits(world["path"], OWNER) is True
    assert ops.list_waits(world["path"], TALKER) is False      # another sender has no list
    assert ops.list_waits(world["path"], OWNER, "page") is False      # the page and the terminal have no list


def test_asking_changes_nothing_so_the_pick_after_it_still_works(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    assert ops.list_waits(world["path"], OWNER) is True and ops.list_waits(world["path"], OWNER) is True
    assert says(say(world, "o 3"), CARD_1)      # the read dropped nothing: the number still opens the card of row 3
    assert ops.list_waits(world["path"], OWNER) is False      # a line was read since: the list is no longer the last thing said


def test_a_line_read_after_the_list_ends_it(world, monkeypatch):
    meetings_listed(world, monkeypatch)
    Model(monkeypatch, '{"v":1,"kind":"none"}')      # the line in between goes to the model, which says nothing
    say(world, "obrigado")
    assert ops.list_waits(world["path"], OWNER) is False


def test_vacuity_with_no_list_shown_nothing_waits(world, monkeypatch):
    from test_event_lookup import build
    build(world, monkeypatch, events=MEETINGS)
    assert ops.list_waits(world["path"], OWNER) is False
