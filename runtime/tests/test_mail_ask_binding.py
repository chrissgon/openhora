"""The numbers after a list mean that list for `mail-ask` too (package MAIL-SUMMARY-FLIP, backlog MAIL-ASK-BINDING; runtime/ops_natural.py `run`, runtime/item_refs.py `listed_source`).

A project with two mail boxes and a person who has just been shown ONE box's list ("Gmail", 1 message) and says "resume o 3": the 3 is the 3 of that list. Before this package the binding was only for
`mail-read`, so a number that a single OTHER box holds (Outlook has a message 3) named that box's message though it was not on the screen. Now the plan of `mail-ask` binds `message=<source>#<n>` as
`mail-read`'s plan does, so the plan's hash binds it and the read names the box that was on screen (here: past the end of its list, nothing is read).

Over the REAL snapshots behind the real runtime/item_refs.py, the real natural-request path (`ops_natural.run`) and the real `ops.say` for the OK, a stand-in clock; the reader that would answer is
never reached (a message the list does not hold stops the run at its naming, and the other cases stop at the plan). Every expectation is a literal of this file; every oracle has a vacuity case that fails
on a planted wrong result. Offline; every name, address and word is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_ask_binding.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import world  # noqa: F401  (the calendar world and its real snapshots)
from test_mail_list_account import ASKING, accept, boxes, call, clock, listed, live, mail_reads, next_line, snaps  # noqa: F401  (fixtures and helpers of the list tests)

item_refs = st.load("item_refs")
ops_file_ask = st.load("ops_file_ask")

PROFILES = {"asking": ["read", "talk", "ask", "ask-mail", "read-mail-body", "interpret"]}      # may ask a question about one e-mail (and read one: the last test); holds no confirm-reads-off
ONE_GMAIL = [tsm.message(1, "2026-10-17T09:00:00Z", "Bia Costa <bia@clinic.example>", "Appointment confirmed", "Your visit is confirmed.")]
THREE_OUTLOOK = [tsm.message(n, f"2026-10-17T0{n}:00:00Z", f"Dan Reis <dan@work.example>", f"Weekly report {n}", f"Weekly numbers {n} attached.", source="outlook") for n in (1, 2, 3)]
MOVED = "The list I showed has changed since: ask for the list again, then tell me the number."      # ML_LIST_MOVED
WHICH = "Which e-mail? Say its number, or some words of its sender or subject."      # MR_ASK
PLAN_THREE = "I understood: answer about e-mail 3 (a model reads that e-mail in an isolated run, up to US$ 0.25). Shall I go ahead?"


def ask_plan(world, args=None, line="resume o 3"):
    """The plan the line states for `mail-ask`, as the call the interpreter would give: (the reply, the plan's own arguments)."""
    reply, _extras = call(world, line, dict({"number": 3}, **(args or {})), name="mail-ask")
    return reply, dict(live(world)["state"]["args"])


@pytest.fixture
def two_boxes(world, snaps, clock):  # noqa: F811
    boxes(world, snaps, mails=ONE_GMAIL, others=THREE_OUTLOOK, profiles=PROFILES)
    return world


def test_after_the_list_of_one_box_the_number_of_a_summary_is_that_boxs_and_the_plan_binds_it(two_boxes, snaps):
    listed(two_boxes, 0)      # the person chose Gmail: one message on the screen
    next_line(two_boxes)
    reply, args = ask_plan(two_boxes)
    assert reply == PLAN_THREE
    assert args["number"] == 3 and args["message"] == "inbox#3", "bound to the box on screen, not to the box that happens to hold a message 3"
    assert set(args["pin"]) == {"inbox"}, "and the snapshot the plan pins is that box's alone"


def test_the_bound_number_names_the_box_on_screen_and_reads_nothing_when_it_is_past_the_end_of_that_list(two_boxes, snaps, monkeypatch):
    monkeypatch.setattr(ops_file_ask, "_skill", lambda: ("asst-answer", None))      # the reader is built and proven: only the naming is under test, and it stops before a run
    listed(two_boxes, 0)
    next_line(two_boxes)
    _reply, extras = call(two_boxes, "resume o 3", {"number": 3}, name="mail-ask")
    before = len(mail_reads(snaps))
    answer = accept(two_boxes, extras)
    assert "Weekly numbers 3 attached." not in answer and "Weekly report 3" not in answer, "Outlook's message 3 was not on the screen: nothing of it is read or named"
    assert answer == "Gmail has 1 e-mails in its newest snapshot, so there is no e-mail 3 there."
    assert len(mail_reads(snaps)) == before, "no provider is called to name it: the snapshot answers"


def test_after_the_list_of_all_the_boxes_nothing_is_bound_and_a_number_held_by_one_box_is_still_that_one(two_boxes, snaps):
    listed(two_boxes, 2)
    next_line(two_boxes)
    _reply, args = ask_plan(two_boxes)
    assert "message" not in args and args["number"] == 3, "no binding: the which-box rule of the naming stays as it was"


def test_a_box_named_in_the_line_or_the_call_wins_over_the_list_on_screen(two_boxes, snaps):
    listed(two_boxes, 0)
    next_line(two_boxes)
    _reply, args = ask_plan(two_boxes, line="resume o 3 do outlook")
    assert "message" not in args and args["number"] == 3, "the line names the account"
    _reply, args = ask_plan(two_boxes, {"account": "microsoft"})
    assert "message" not in args and args["account"] == "microsoft"
    _reply, args = ask_plan(two_boxes, {"message": "work#2"}, line="resume o work#2")
    assert args["message"] == "work#2", "a message the call names stays"


def test_the_memory_is_for_the_next_line_only_and_for_ten_minutes(two_boxes, snaps):
    listed(two_boxes, 0)
    next_line(two_boxes)
    next_line(two_boxes)
    assert "message" not in ask_plan(two_boxes)[1], "the second line after the list"
    listed(two_boxes, 0)
    next_line(two_boxes)
    snaps.listed += 601
    assert "message" not in ask_plan(two_boxes)[1], "after 600 seconds"


def new_gmail_mail(snaps):
    snaps.providers.mail["gmail"] = [tsm.message(2, "2026-10-17T09:30:00Z", "Cora Dias <cora@clinic.example>", "New invoice", "Please pay.")] + snaps.providers.mail["gmail"]
    snaps.later(minutes=1)
    snaps.refresh("inbox")      # the box has a newer snapshot than the one that was listed: the numbers moved


def test_a_list_whose_snapshot_moved_is_asked_for_again_and_no_plan_names_no_box(two_boxes, snaps):
    """Review of MAIL-SUMMARY-FLIP: the binding used to drop, the plan pinned the new versions of both boxes and Outlook's message 3 went to the model after a Posso? that named no box."""
    listed(two_boxes, 0)
    new_gmail_mail(snaps)
    next_line(two_boxes)
    before = len(mail_reads(snaps))      # the refresh above is the test's own
    for name, line in (("mail-ask", "resume o 3"), ("mail-read", "read e-mail 3")):
        reply, _extras = call(two_boxes, line, {"number": 3}, name=name)
        assert reply == MOVED and live(two_boxes) is None, name
    assert len(mail_reads(snaps)) == before


def test_vacuity_the_moved_list_without_the_question_plans_another_boxs_message(two_boxes, snaps, monkeypatch):
    listed(two_boxes, 0)
    new_gmail_mail(snaps)
    next_line(two_boxes)
    monkeypatch.setattr(item_refs, "list_moved", lambda ctx, channel, sender: False)      # planted: the question left out
    reply, args = ask_plan(two_boxes)
    assert reply == PLAN_THREE and "message" not in args and set(args["pin"]) == {"inbox", "work"}, "the oracle sees the plan that names no box and pins both"


def test_a_project_with_one_box_remembers_no_list_so_a_moved_snapshot_is_not_asked_about(world, snaps, clock):
    boxes(world, snaps, mails=ONE_GMAIL, others=THREE_OUTLOOK, second=False, profiles=PROFILES)
    _, extras = call(world, "list my e-mails")
    accept(world, extras)
    new_gmail_mail(snaps)
    next_line(world)
    reply, args = ask_plan(world)
    assert reply == PLAN_THREE and "message" not in args, "the stated limit: one box, no list remembered, the number is never ambiguous"


@pytest.mark.parametrize("number", [0, -1, 10000, 12345])
def test_a_number_no_message_can_have_is_asked_again_before_any_plan(two_boxes, snaps, number):
    """Review of MAIL-SUMMARY-FLIP: 0 and 12345 passed `interpreter.check`, and after a plan and a yes the phone got a typed-command error."""
    for name in ("mail-ask", "mail-read"):
        reply, extras = call(two_boxes, f"resume o {number}", {"number": number}, name=name)
        assert reply == WHICH and "plan_confirm" not in extras and live(two_boxes) is None, (name, number)
    listed(two_boxes, 0)
    next_line(two_boxes)
    assert call(two_boxes, f"resume o {number}", {"number": number}, name="mail-ask")[0] == WHICH, "also right after a list, before the binding"


def test_the_edges_of_the_range_are_planned(two_boxes, snaps):
    for number in (1, 9999):
        reply, extras = call(two_boxes, f"resume o {number}", {"number": number}, name="mail-ask")
        assert reply.startswith("I understood: answer about e-mail ") and "plan_confirm" in extras, number


def test_vacuity_without_the_listed_source_the_same_line_is_not_bound(two_boxes, snaps, monkeypatch):
    listed(two_boxes, 0)
    next_line(two_boxes)
    monkeypatch.setattr(item_refs, "listed_source", lambda ctx, channel, sender: None)      # planted: the memory of the list on screen is gone
    _reply, args = ask_plan(two_boxes)
    assert "message" not in args, "the oracle of the first test sees a plan that is not bound"


def test_vacuity_mail_read_is_bound_by_the_same_rule_so_the_binding_is_not_a_property_of_this_fixture(two_boxes, snaps):
    listed(two_boxes, 0)
    next_line(two_boxes)
    _reply, _extras = call(two_boxes, "read e-mail 3", {"number": 3}, name="mail-read")
    assert live(two_boxes)["state"]["args"].get("message") == "inbox#3"
