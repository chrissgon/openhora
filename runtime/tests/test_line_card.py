"""The card a line is about (package ANY-QUESTION Q1, runtime/line_card.py): the one number the messaging bridge leaves for the operations layer on the thread that runs the line.

Held here: `current()` is None outside a `hold`; inside it is the value; nested holds restore the earlier value on exit; an exception restores it; another thread never sees it; and anything that is not
a whole number of at least 1 (a string, zero, a bool, a float, None) holds None. Offline, no model, no store.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_line_card.py
"""
from __future__ import annotations

import threading

import pytest

import standin_tree as st

line_card = st.load("line_card")


def test_the_number_is_none_outside_a_hold_and_the_value_inside():
    assert line_card.current() is None
    with line_card.hold(7):
        assert line_card.current() == 7
    assert line_card.current() is None


def test_nested_holds_restore_the_earlier_value_on_exit():
    with line_card.hold(3):
        with line_card.hold(9):
            assert line_card.current() == 9
        assert line_card.current() == 3
        with line_card.hold(None):
            assert line_card.current() is None
        assert line_card.current() == 3
    assert line_card.current() is None


def test_an_exception_restores_the_earlier_value():
    with line_card.hold(4):
        with pytest.raises(RuntimeError):
            with line_card.hold(5):
                assert line_card.current() == 5
                raise RuntimeError("planted")
        assert line_card.current() == 4
    assert line_card.current() is None


def test_another_thread_sees_none():
    seen = []
    with line_card.hold(6):
        thread = threading.Thread(target=lambda: seen.append(line_card.current()))
        thread.start()
        thread.join(5)
        assert line_card.current() == 6
    assert seen == [None]


def test_a_thread_holds_its_own_number():
    seen = {}
    started, release = threading.Event(), threading.Event()

    def other():
        with line_card.hold(11):
            started.set()
            release.wait(5)
            seen["other"] = line_card.current()

    thread = threading.Thread(target=other)
    thread.start()
    assert started.wait(5)
    with line_card.hold(12):
        release.set()
        thread.join(5)
        assert line_card.current() == 12
    assert seen == {"other": 11}


@pytest.mark.parametrize("value", ["3", 0, -1, True, False, 2.0, None, [3], {"id": 3}])
def test_a_value_that_is_not_a_whole_number_of_at_least_one_holds_none(value):
    with line_card.hold(5):
        with line_card.hold(value):
            assert line_card.current() is None
        assert line_card.current() == 5


def test_vacuity_a_planted_hold_of_a_string_would_be_seen_as_a_string():
    with line_card.hold(8):
        assert line_card.current() == 8 and line_card.current() != "8"
