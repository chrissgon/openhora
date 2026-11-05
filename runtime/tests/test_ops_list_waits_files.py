"""ACEITE-37: whether a list of files is still the last thing said to a sender (runtime/ops_file_read.py `list_open`, runtime/ops_say.py `list_waits`), the read the bridge makes before a bare
word brings a card back. The list is the real one of the file world (test_file_list_pick.py); the expectations are literals of this file; each has a vacuity case. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_list_waits_files.py
"""
from __future__ import annotations

import standin_tree as st
from test_file_list_pick import fresh_lists, take, two  # noqa: F401
from test_file_read import READER_KEY, ACTIVITIES, HEAD, LINE_1, SECRET_MARK, WANTED, drives, item, ops_core, ops_file_read, phone  # noqa: F401  (the file world)
from test_ops_natural import world  # noqa: F401

ops = st.load("ops")


def test_the_list_of_files_that_was_just_shown_is_waiting_for_its_sender_only(drives):
    two(drives)
    assert ops.list_waits(drives["path"], READER_KEY) is True
    assert ops.list_waits(drives["path"], "telegram:1") is False
    assert ops.list_waits(drives["path"], READER_KEY, "page") is False


def test_a_line_read_after_the_list_ends_it(drives):
    two(drives)
    ctx = ops_core.context(drives["path"])
    ops_file_read.begin_turn(ctx, "messaging", READER_KEY)
    assert ops.list_waits(drives["path"], READER_KEY) is False


def test_vacuity_with_no_list_shown_nothing_waits(drives):
    assert ops.list_waits(drives["path"], READER_KEY) is False
