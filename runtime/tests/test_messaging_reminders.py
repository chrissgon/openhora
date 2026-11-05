"""Reminders on a messaging app (package RM-1): `/remind`, `/reminders` and `/forget` from a listed sender, and the delivery of what is due, over the REAL
operations layer and a stand-in messenger provider (the lab of test_sender_profiles_bridge.py): the group `reminders` off until a profile lists it, the reply
that never echoes the words, a reminder delivered once to the chat that made it and to no other, the count mode, a sender removed or narrowed before the
time, the late window, a send that failed, a restart, a phone that is never told a path, and limit L51. The pure part and the operations are in
test_reminders.py; the table in providers/store/tests/test_sqlite_reminders.py. Offline, no model, no network; invented ids.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_reminders.py
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import pytest

import phone_said as ps
import phrase_kit as pk
import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_queue import WAIT, planner, settle  # noqa: F401  (the planner stand-in and the waiting for the bridge's jobs)
from test_reminders import BRT, Clock
from test_sender_profiles import OWNER, OWNER_KEY, POLICIES, STAFF, STAFF_KEY
from test_sender_profiles_bridge import NOT_ENABLED, OTHER, POLICIES_ALL, configure, lab  # noqa: F401  (the lab fixture)
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")
ops_reminders = st.load("ops_reminders")
operations = st.load("operations")
bridge = st.load("messaging_bridge")
inbound = st.load("messaging_inbound")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
rm = st.load("reminders")
effects = st.load("effects")
attachments = st.load("attachments")
phrases = st.load("phrases")

# The owner and a desk hold the group `reminders`; the employee's profile does not; the channel's default is the employee's.
WITH = {**POLICIES_ALL, "owner": [*POLICIES["owner"], "reminders"], "desk": ["read-limited", "talk", "reminders"]}
DENTIST = "Call the dentist about Thursday"


def listed(lab, notices="text", senders=None):
    configure(lab, senders or [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}, {"id": OTHER, "policy": "desk"}], policies=WITH, notices=notices)


def reminder_texts(lab, chat):
    return [t for t in lab.texts(chat) if pk.said(t, "RM_TEXT_LINE") or pk.said(t, "RM_COUNT_LINE")]


def reminder_bodies(lab, chat):
    """What the chat was sent as reminders: the words of each `Reminder: <text>` line, and None for a count line (`A reminder is due`)."""
    return [pk.which(t)[1]["text"] if pk.said(t, "RM_TEXT_LINE") else None for t in reminder_texts(lab, chat)]


def listing(text):
    """A `/reminders` reply as (project, sentence after it, the other lines): the first line is `<project>: <sentence>`."""
    first, *rest = text.split("\n")
    project, _, sentence = first.partition(": ")
    return project, sentence, rest




@pytest.fixture
def day(lab, monkeypatch):  # noqa: F811
    """The lab with the owner, the employee and a desk listed, and a clock that reads 2026-10-18 14:00 at -03:00 for the operations."""
    listed(lab)
    lab.clock = Clock(monkeypatch)
    lab.all = lambda: ops.reminders_read(lab.path, channel="terminal")
    return lab


# --- 1. the commands -----------------------------------------------------------------------------------------------------------------------


def test_the_three_commands_are_read_from_a_line_with_no_clock_and_no_model():
    parse = inbound.parse
    update = lambda text: {"text": text}  # noqa: E731
    assert parse(update("/remind 15:00 Call the dentist")) == {"kind": "remind", "when": "15:00", "text": "Call the dentist"}
    assert parse(update("/remind@openhora_bot 2026-10-20 09:30 pay rent")) == {"kind": "remind", "when": "2026-10-20 09:30", "text": "pay rent"}
    assert parse(update("/REMIND in 2h stretch")) == {"kind": "remind", "when": "in 2h", "text": "stretch"}
    assert parse(update("/reminders")) == {"kind": "reminders"} and parse(update("/forget 3")) == {"kind": "forget", "id": 3}
    for line, rest in (("/remind", ""), ("/remind 15:00", "15:00"), ("/remind   ", ""), ("/remind in 2h", "in 2h"), ("/remind 13hrs oil change tomorrow", "13hrs oil change tomorrow")):
        assert parse(update(line)) == {"kind": "natural", "op": "remind", "how": "command", "text": rest}, line      # the strict grammar does not claim it: the person's own words (NR-1)
    for line in ("/forget", "/forget x", "/forget -1", "/forget 3x"):
        got = parse(update(line))
        assert set(got) == {"kind", "text"} and got["kind"] == "usage" and pk.said(got["text"], "USAGE_FORGET"), line
    assert parse(update("remind me at 15:00")) == {"kind": "text", "text": "remind me at 15:00"}, "S41-11: a remind word starts no reminder here any more: a plain line, read by the interpreter (L63)"
    assert parse(update("when does the shop open")) == {"kind": "text", "text": "when does the shop open"}, "free text still goes to the planning agent"
    for blank in ("\n", "\u00a0", "\t", "\u2003", "  ", "\r\n"):         # the command word ends at any blank: the line is a command, never a line for a model
        assert parse(update(f"/remind{blank}15:00 Call")) == {"kind": "remind", "when": "15:00", "text": "Call"}, repr(blank)
        assert parse(update(f"/forget{blank}3")) == {"kind": "forget", "id": 3} and parse(update(f"/reminders{blank}")) == {"kind": "reminders"}
    assert parse(update("/remind\n")) == parse(update("/remind\u00a0")) == {"kind": "natural", "op": "remind", "how": "command", "text": ""}
    assert parse(update("/approve\n12"))["kind"] == "approve"
    assert "/remind <time> <text>" in inbound.HELP and "/reminders" in inbound.HELP and "/forget <n>" in inbound.HELP


def test_a_line_the_bridge_cannot_read_is_asked_back_and_makes_nothing(day):
    rolled = phrases.text("NT_ROLLED", None, time="13:00", when="tomorrow, Mon 19/10, at 13:00 (BRT)")
    for line, key, fields in (("/remind", "NT_ASK_WHEN_SLASH", {}), ("/remind buy milk", "NT_ASK_WHEN_SLASH", {}), ("/remind 15:00", "NT_ASK_TEXT", {}),
                              ("/remind 25:00 call", "RM_NOT_A_TIME", {"given": "25:00"}), ("/remind 13:00 x", "NT_SET_TEXT", {"id": 1, "when": rolled, "text": "x"}),
                              ("/forget", "USAGE_FORGET", {})):
        before = len(day.texts(OWNER))
        day.say(OWNER, line)
        got = day.texts(OWNER)[before:]
        assert len(got) == 1 and pk.said(got[0], key, **fields), (line, got)      # for `/remind 13:00 x`: past means tomorrow, and says so
        day.bridge.remind.drafts.clear()
    assert [r["id"] for r in day.all()["open"]] == [1]


def test_a_sender_whose_profile_lacks_the_group_is_refused_and_so_is_the_default_policy(day):
    day.say(STAFF, "/remind 15:00 Call the dentist")
    assert ps.refused(day.texts(STAFF)[-1])
    day.say(STAFF, "/reminders")
    assert NOT_ENABLED in day.texts(STAFF)[-1]
    day.say(STAFF, "/forget 1")
    assert NOT_ENABLED in day.texts(STAFF)[-1]
    listed(day, senders=[OWNER, STAFF])                       # no profile of their own: the channel's default, which is the employee's
    day.say(OWNER, "/remind 15:00 Call the dentist")
    assert NOT_ENABLED in day.texts(OWNER)[-1]
    listed(day, senders=[{"id": OWNER, "policy": "owner"}])
    configure(day, [OWNER], policies=WITH, channel=None)      # the closed default of a messaging app
    day.say(OWNER, "/remind 15:00 Call the dentist")
    assert NOT_ENABLED in day.texts(OWNER)[-1]
    assert day.all()["open"] == []


def test_the_reply_names_the_number_the_day_the_weekday_the_time_the_zone_and_the_way_to_undo_it(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    pk.assert_said(day.texts(OWNER)[-1], "NT_SET_TEXT", id=1, when="today, Sun 18/10, at 15:00 (BRT)", text=DENTIST)
    day.say(OWNER, "/remind in 2h stretch a little")
    day.say(OWNER, "/remind 2026-10-20 09:30 renew the passport")
    second, third = day.texts(OWNER)[-2:]
    pk.assert_said(second, "NT_SET_TEXT", id=2, when="today, Sun 18/10, at 16:00 (BRT)", text="stretch a little")
    pk.assert_said(third, "NT_SET_TEXT", id=3, when="Tue 20/10 at 09:30 (BRT)", text="renew the passport")
    assert day.texts(STAFF) == [], "nobody else is told"


def test_in_count_mode_the_reply_names_the_moment_and_never_the_words(day):
    listed(day, notices="count")
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OWNER, "/remind tomorrow 1 pm stretch a little")      # in words: the reading is shown, and a yes makes it
    pk.assert_said(day.texts(OWNER)[-1], "NT_CONFIRM_COUNT", when="tomorrow, Mon 19/10, at 13:00")
    day.say(OWNER, "yes")
    pk.assert_said(day.texts(OWNER)[-3], "NT_SET_COUNT", id=1, when="today, Sun 18/10, at 15:00 (BRT)")
    pk.assert_said(day.texts(OWNER)[-1], "NT_SET_COUNT", id=2, when="tomorrow, Mon 19/10, at 13:00 (BRT)")
    assert "dentist" not in " ".join(day.texts(OWNER)) and "stretch" not in " ".join(day.texts(OWNER))


def test_a_text_that_looks_like_a_credential_is_refused_without_repeating_it(day):
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    day.say(OWNER, f"/remind 15:00 use {key}")
    assert "looks like a credential" in day.texts(OWNER)[-1] and key not in day.texts(OWNER)[-1] and key not in " ".join(day.log)
    assert day.all()["open"] == []


def test_reminders_lists_the_senders_own_and_forget_cancels_only_theirs(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OTHER, "/remind 16:00 Take the bread out")
    day.say(OWNER, "/reminders")
    project, sentence, rows = listing(day.texts(OWNER)[-1])
    assert project == "northwind-shop" and pk.said(sentence, "RM_WAITING_HEAD", zone="BRT") and rows == [f"#1 today, Sun 18/10, at 15:00: {DENTIST}"]      # literal: a row is the layer's own line (number, moment, words), not a table sentence
    assert "bread" not in day.texts(OWNER)[-1]
    day.say(OTHER, "/reminders")
    project, sentence, rows = listing(day.texts(OTHER)[-1])
    assert project == "northwind-shop" and pk.said(sentence, "RM_WAITING_HEAD", zone="BRT") and rows == ["#2 today, Sun 18/10, at 16:00: Take the bread out"]
    day.say(OTHER, "/forget 1")
    assert pk.said(day.texts(OTHER)[-1], "RM_NO_SUCH", n=1), "another's reminder is answered as one that does not exist"
    day.say(OTHER, "/forget 99")
    assert pk.said(day.texts(OTHER)[-1], "RM_NO_SUCH", n=99)
    assert [r["status"] for r in day.all()["open"]] == ["open", "open"]
    day.say(OWNER, "/forget 1")
    pk.assert_said(day.texts(OWNER)[-1], "NT_FORGOT_TEXT", id=1, when="today, Sun 18/10, at 15:00 (BRT)", text=DENTIST)
    day.say(OWNER, "/reminders")
    project, sentence, rows = listing(day.texts(OWNER)[-1])
    assert project == "northwind-shop" and pk.said(sentence, "RM_NONE_WAIT") and rows == []
    day.say(OWNER, "/forget 1")
    assert pk.said(day.texts(OWNER)[-1], "RM_NOT_WAITING", n=1, status="cancelled")


def test_in_count_mode_the_list_names_the_time_and_not_the_words(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    listed(day, notices="count")
    day.say(OWNER, "/reminders")
    project, sentence, rows = listing(day.texts(OWNER)[-1])
    assert project == "northwind-shop" and pk.said(sentence, "RM_WAITING_HEAD", zone="BRT") and rows == ["#1 today, Sun 18/10, at 15:00"] and "dentist" not in day.texts(OWNER)[-1]


# --- the queue of waiting lines (BQ-1) never keeps these ---------------------------------------------------------------------------------------


def test_the_three_commands_are_never_kept_by_the_queue_and_are_handled_at_once_while_the_project_is_busy(day, planner):  # noqa: F811
    for line in ("/remind 15:00 x", "/remind@openhora_bot 15:00 x", "/remind\n15:00 x", "/remind\u00a015:00 x", "/REMINDERS", "/forget 1", "/forget\n1"):
        assert not bridge.queueable(line), line
    planner.hold = {0}
    day.say(OWNER, "when does the shop open")                     # a plain line takes the project's slot and holds it
    assert planner.reached(0).wait(WAIT)
    day.say(OWNER, "another plain line")                           # a plain line meets the busy project and waits
    assert day.texts(OWNER)[-1] == bridge.QUEUED and len(day.bridge.waiting) == 1
    waiting = len(day.bridge.waiting)
    before = len(day.texts(OWNER))
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    got = day.texts(OWNER)[before:]
    assert len(got) == 1 and pk.said(got[0], "NT_SET_TEXT", id=1, when="today, Sun 18/10, at 15:00 (BRT)", text=DENTIST), "answered at once, not kept and not refused as busy"
    day.say(OWNER, "/reminders")
    project, sentence, rows = listing(day.texts(OWNER)[-1])
    assert project == "northwind-shop" and pk.said(sentence, "RM_WAITING_HEAD", zone="BRT") and rows == [f"#1 today, Sun 18/10, at 15:00: {DENTIST}"]
    day.say(OWNER, "/forget 1")
    pk.assert_said(day.texts(OWNER)[-1], "NT_FORGOT_TEXT", id=1, when="today, Sun 18/10, at 15:00 (BRT)", text=DENTIST)
    day.say(OWNER, "/remind 15:00 again")
    pk.assert_said(day.texts(OWNER)[-1], "NT_SET_TEXT", id=2, when="today, Sun 18/10, at 15:00 (BRT)", text="again")
    assert len(day.bridge.waiting) == waiting and not any(bridge.QUEUED == t for t in day.texts(OWNER)[before:]), "the queue holds what it held"
    assert all("remind" not in c for c in planner.texts()), "no model run saw a reminder command"
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()                                              # the delivery goes on while the slot is held
    assert reminder_bodies(day, OWNER) == ["again"]
    planner.open_all()
    assert settle(day)
    assert planner.texts() == ["when does the shop open", "another plain line"] and not any("remind" in t.lower() for t in planner.texts())


# --- 2. the delivery -------------------------------------------------------------------------------------------------------------------------------


def test_a_due_reminder_goes_once_to_the_chat_that_made_it_and_to_no_other(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OTHER, "/remind 15:00 Take the bread out")
    day.bridge.tick()
    assert reminder_texts(day, OWNER) == [] and reminder_texts(day, OTHER) == [], "not before its time"
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    assert reminder_bodies(day, OWNER) == [DENTIST] and reminder_bodies(day, OTHER) == ["Take the bread out"]
    assert reminder_texts(day, STAFF) == [] and not any("dentist" in t or "bread" in t for t in day.texts(STAFF))
    day.bridge.tick()
    day.bridge.tick()
    assert reminder_bodies(day, OWNER) == [DENTIST], "delivered once"
    assert sorted(r["status"] for r in day.all()["open"]) == []
    assert [r["status"] for r in ops_reminders.core.context(day.path)["store"].reminders_list(ops_reminders.core.context(day.path)["conn"])] == ["sent", "sent"]


def test_a_reminder_made_in_the_terminal_goes_to_the_listed_sender_it_names_and_nobody_else(day):
    ops.remind(day.path, "in 5m", "From the terminal", OWNER_KEY, channel="terminal")
    day.clock.set("2026-10-18 14:10")
    day.bridge.tick()
    assert reminder_bodies(day, OWNER) == ["From the terminal"] and reminder_texts(day, OTHER) == [] and reminder_texts(day, STAFF) == []


def test_in_count_mode_the_phone_gets_the_number_and_no_text(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    listed(day, notices="count")
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    [due] = reminder_texts(day, OWNER)
    pk.assert_said(due, "RM_COUNT_LINE", id=1)
    assert not any("dentist" in t for t in day.texts(OWNER)[1:]) and "dentist" not in json.dumps(day.sent()[1:]), "after the reply that made it, no line carries the words"


def test_a_sender_removed_before_the_time_gets_nothing_and_the_creator_can_read_that_in_the_terminal(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OTHER, "/remind 15:00 Take the bread out")
    listed(day, senders=[{"id": OTHER, "policy": "desk"}])
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    assert reminder_texts(day, OWNER) == [] and reminder_bodies(day, OTHER) == ["Take the bread out"]
    assert [(r["id"], r["why"]) for r in day.all()["not_sent"]] == [(1, "sender removed")]
    listed(day)
    day.say(OWNER, "/reminders")
    project, sentence, rows = listing(day.texts(OWNER)[-1])
    row, _, why = rows[1].rpartition(" (")
    assert project == "northwind-shop" and pk.said(sentence, "RM_NONE_WAIT") and len(rows) == 2 and pk.said(rows[0], "RM_NOT_SENT_HEAD")
    assert row == f"#1 today, Sun 18/10, at 15:00: {DENTIST}" and pk.said(why.rstrip(")"), "RM_WHY_SENDER_REMOVED")


def test_a_sender_narrowed_before_the_time_gets_nothing(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    configure(day, [{"id": OWNER, "policy": "owner"}], policies={**WITH, "owner": POLICIES["owner"]})      # the group is taken away: no ceremony
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    assert reminder_texts(day, OWNER) == [] and [r["why"] for r in day.all()["not_sent"]] == ["not permitted"]
    day.say(OWNER, "/reminders")
    assert NOT_ENABLED in day.texts(OWNER)[-1]


def test_late_by_five_hours_it_goes_with_the_time_it_was_due_and_late_by_seven_it_is_missed_and_the_creator_is_told_when_they_ask(day):
    day.say(OWNER, f"/remind 2026-10-19 09:00 {DENTIST}")
    day.clock.set("2026-10-19 14:00")                               # five hours past 09:00: the bridge was not running
    day.bridge.tick()
    [late] = reminder_texts(day, OWNER)
    pk.assert_said(late, "RM_TEXT_LINE", text=DENTIST + phrases.text("RM_TEXT_LATE", None, at="09:00"))
    day.say(OWNER, "/remind 2026-10-20 08:00 Third")
    day.clock.set("2026-10-20 15:00")                               # seven hours past 08:00
    day.bridge.tick()
    assert not any("Third" in t for t in reminder_texts(day, OWNER)), "seven hours late is never sent"
    day.say(OWNER, "/reminders")
    project, sentence, rows = listing(day.texts(OWNER)[-1])
    row, _, why = rows[1].rpartition(" (")
    assert project == "northwind-shop" and pk.said(sentence, "RM_NONE_WAIT") and len(rows) == 2 and pk.said(rows[0], "RM_NOT_SENT_HEAD")
    assert row == "#2 today, Tue 20/10, at 08:00: Third" and pk.said(why.rstrip(")"), "RM_WHY_LATE")
    assert "Third" not in " ".join(day.log) and DENTIST not in " ".join(day.log)


def test_a_send_that_failed_or_was_deferred_is_tried_again_after_a_pause_that_doubles_and_goes_once(day, monkeypatch):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.clock.set("2026-10-18 15:00")
    real = day.bridge.messenger.send
    answers = [providers.MessengerError("failed", "the app did not answer"), providers.MessengerError("deferred", "outside the window")]

    def flaky(chat, message):
        if answers and message["text"].startswith("Reminder:"):      # the cards of the lab's decisions go out as they always do
            raise answers.pop(0)
        return real(chat, message)
    monkeypatch.setattr(day.bridge.messenger, "send", flaky)
    day.bridge.tick()
    assert reminder_texts(day, OWNER) == [] and [r["status"] for r in day.all()["open"]] == ["open"] and len(answers) == 1
    day.bridge.tick()
    day.bridge.tick()
    assert len(answers) == 1, "the next ticks do not try again inside the minute"
    day.clock.moment += datetime.timedelta(minutes=1)
    day.bridge.tick()
    assert reminder_texts(day, OWNER) == [] and not answers, "the second try is the deferred one"
    day.clock.moment += datetime.timedelta(minutes=1, seconds=59)
    day.bridge.tick()
    assert reminder_texts(day, OWNER) == [], "two minutes were asked for"
    day.clock.moment += datetime.timedelta(seconds=1)
    day.bridge.tick()
    assert reminder_bodies(day, OWNER) == [DENTIST] and day.all()["open"] == [], "four minutes late: within the tick's own delay, no mark"
    day.bridge.tick()
    assert len(reminder_texts(day, OWNER)) == 1
    assert DENTIST not in " ".join(day.log), "a failed send logs its class, never the words"


def test_a_mark_that_fails_after_the_line_went_out_is_logged_by_class_and_the_line_may_go_twice(day, monkeypatch):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.clock.set("2026-10-18 15:00")
    real = ops.reminders_sent
    monkeypatch.setattr(ops, "reminders_sent", lambda *a, **k: (_ for _ in ()).throw(ops.OpsError("the store at /Users/someone/x: locked", 1)))
    day.bridge.tick()
    assert reminder_bodies(day, OWNER) == [DENTIST]
    assert any("a reminder could not be marked (OpsError)" in x for x in day.log) and not any("/Users" in x or "dentist" in x for x in day.log)
    day.bridge.tick()
    assert len(reminder_texts(day, OWNER)) == 1, "still claimed"
    monkeypatch.setattr(ops, "reminders_sent", real)
    day.clock.moment += datetime.timedelta(seconds=rm.CLAIM_STALE + 1)
    day.bridge.tick()
    assert len(reminder_texts(day, OWNER)) == 2, "the documented duplicate: the claim went stale and the line went again; it is marked now"
    day.bridge.tick()
    assert len(reminder_texts(day, OWNER)) == 2 and day.all()["open"] == []


def test_a_restart_does_not_send_again_what_was_sent_and_sends_what_a_stopped_bridge_only_claimed(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OWNER, "/remind 15:00 Second")
    day.clock.set("2026-10-18 15:00")
    claimed = ops.reminders_due(day.path, "telegram")["send"]                      # a bridge claimed both and stopped before it sent either
    assert [c["id"] for c in claimed] == [1, 2]
    ops.reminders_sent(day.path, 1)                                                # the first line was marked sent before it stopped
    fresh = bridge.Bridge(ops, day.bridge.projects, day.bridge.messenger, ledgers.Ledger(str(day.tmp / "ledger-data"), "telegram"), "telegram", day.log.append,
                          clock=lambda: "2026-10-11T10:00:00+00:00")
    fresh.tick()
    assert reminder_texts(day, OWNER) == [], "the second is still claimed: not before the claim is stale"
    day.clock.moment += datetime.timedelta(seconds=rm.CLAIM_STALE + 1)
    fresh.tick()
    [second] = reminder_texts(day, OWNER)
    pk.assert_said(second, "RM_TEXT_LINE", text="Second" + phrases.text("RM_TEXT_LATE", None, at="15:00"))      # a stopped bridge's reminder goes out when a new one starts, and the sent one does not"
    fresh.tick()
    assert len(reminder_texts(day, OWNER)) == 1


def test_the_words_of_a_reminder_are_never_in_the_log(day):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OTHER, "/remind 15:00 Take the bread out")
    listed(day, senders=[{"id": OTHER, "policy": "desk"}])
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    day.clock.set("2026-10-19 15:00")
    day.say(OTHER, "/remind in 5m Third")
    day.bridge.tick()
    assert not any(w in " ".join(day.log) for w in ("dentist", "bread", "Third", DENTIST)), day.log


# --- 3. what a phone is told -------------------------------------------------------------------------------------------------------------------


def test_a_phone_is_never_told_a_path_a_machine_problem_is_one_fixed_sentence(day, monkeypatch):
    def broken(*args, **kwargs):
        raise ops.OpsError("the store at /Users/someone/data/store/tasks.sqlite: database is locked", 1)
    monkeypatch.setattr(ops, "reminders_read", broken)
    monkeypatch.setattr(ops, "remind", broken)
    monkeypatch.setattr(ops, "reminder_forget", broken)
    for line in ("/reminders", "/remind 15:00 x", "/forget 1"):
        day.say(OWNER, line)
        assert day.texts(OWNER)[-1] == attachments.MACHINE and "/Users" not in day.texts(OWNER)[-1], line
    assert not any("/Users" in x for x in day.log), "only the class of the error is logged"


def test_a_raw_error_of_the_store_never_ends_the_bridge_and_the_next_tick_delivers(day, monkeypatch):
    """A locked database raises the store's own sqlite3.OperationalError, not an OpsError: `tick()` (and so `serve_loop`, which catches only the
    messenger's errors) must not see it. The reminder is delivered by the tick after."""
    import sqlite3
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.clock.set("2026-10-18 15:00")
    real_due, real_sent = ops.reminders_due, ops.reminders_sent
    monkeypatch.setattr(ops, "reminders_due", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked: /Users/someone/x")))
    day.bridge.tick()                                                      # does not raise
    assert any("reminders could not be read (OperationalError)" in x for x in day.log) and not any("/Users" in x or "locked" in x for x in day.log)
    assert reminder_texts(day, OWNER) == []
    monkeypatch.setattr(ops, "reminders_due", real_due)
    monkeypatch.setattr(ops, "reminders_sent", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    day.bridge.tick()                                                      # the line goes out; marking it fails; the tick goes on
    assert reminder_bodies(day, OWNER) == [DENTIST]
    assert any("a reminder could not be marked (OperationalError)" in x for x in day.log)
    monkeypatch.setattr(ops, "reminders_sent", real_sent)
    day.bridge.tick()
    assert len(reminder_texts(day, OWNER)) == 1, "still claimed: not sent twice at once"
    # a send that raises something other than the messenger's error leaves the claim, logs its class, and the other reminders of the tick still go
    day.say(OWNER, "/remind 15:30 Second")
    day.say(OWNER, "/remind 15:30 Third")
    day.clock.set("2026-10-18 15:30")
    real_reply = day.bridge.reply
    calls = []

    def reply(chat, text):
        calls.append(text)
        if pk.said(text, "RM_TEXT_LINE", text="Second"):
            raise RuntimeError("boom with " + text)
        return real_reply(chat, text)
    monkeypatch.setattr(day.bridge, "reply", reply)
    day.bridge.tick()
    assert reminder_bodies(day, OWNER).count("Third") == 1 and "Second" not in reminder_bodies(day, OWNER)
    assert any("a reminder could not be sent (RuntimeError)" in x for x in day.log) and not any("boom" in x or "Second" in x for x in day.log)


def test_a_delivery_that_cannot_read_the_store_logs_its_class_and_goes_on(day, monkeypatch):
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.clock.set("2026-10-18 15:00")
    monkeypatch.setattr(ops, "reminders_due", lambda *a, **k: (_ for _ in ()).throw(ops.OpsError("the store at /Users/someone/x: locked", 1)))
    day.bridge.tick()
    assert any("reminders could not be read (OpsError)" in x for x in day.log) and not any("/Users" in x for x in day.log)


# --- 4. limit L51 ---------------------------------------------------------------------------------------------------------------------------------


def test_limit_51_a_reminder_is_a_notice_to_the_sender_who_set_it_and_never_an_effect(day):
    store = ops_reminders.core.context(day.path)
    counts = lambda: [store["conn"].execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("pending_decisions", "approvals", "tasks", "actions")]  # noqa: E731
    before = counts()
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    other_key = f"telegram:{OTHER}"
    ops.remind(day.path, "15:00", "From the terminal", other_key, channel="terminal")
    with pytest.raises(ops.OpsError):
        ops.remind(day.path, "15:00", "x", f"telegram:{STAFF}", channel="terminal")           # a sender whose profile lacks the group
    with pytest.raises(ops.OpsError):
        ops.remind(day.path, "15:00", "x", "telegram:55119000009999", channel="terminal")     # a sender the project does not list
    with pytest.raises(ops.OpsError):
        ops.remind(day.path, "15:00", "x", other_key, channel="messaging", sender=OWNER_KEY)  # a messaging sender never names another chat
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    assert reminder_bodies(day, OWNER) == [DENTIST] and reminder_bodies(day, OTHER) == ["From the terminal"] and reminder_texts(day, STAFF) == []
    assert {r["chat"] for r in day.sent() if pk.said(r["message"]["text"], "RM_TEXT_LINE")} == {OWNER, OTHER}
    assert counts() == before, "no decision, approval, task or action: nothing is done in the world"
    # in code: it is not in the vocabulary of effects, takes no hash, and no module of it reaches an effect, a provider or the network
    assert "reminder" not in " ".join(effects.KINDS) and not any("remind" in w for w in operations.EFFECT_APPROVAL_WORDS)
    for name in ("reminders", "ops_reminders", "messaging_remind"):
        source = (st.RUNTIME / f"{name}.py").read_text(encoding="utf-8")
        imports = set(re.findall(r"^\s*(?:import|from)\s+(\w+)", source, re.M))
        assert not imports & {"effects", "effect_send", "effect_publish", "effect_write", "effect_commit", "subprocess", "socket", "urllib", "http", "requests",
                              "lab", "router", "plan", "approvals"}, (name, imports)
    for name in ("remind", "reminders", "reminder-forget"):
        assert "mcp" not in operations.by_name(name)["channels"] and not operations.permitted(name, "mcp", None)
    assert Path(day.path).joinpath("docs").exists() and DENTIST not in "".join(p.read_text(errors="ignore") for p in Path(day.path).rglob("*.md")), \
        "the words are in the store, outside the project's files"
