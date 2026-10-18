"""Reminders (package RM-1), the part that needs no messenger: the words a person types and the moment they mean (runtime/reminders.py, pure, with a fake
clock and explicit zones), and the operations of runtime/ops_reminders.py against the real operations layer and a real store: who may make one and for whom,
the caps, who sees and forgets which, and what the bridge asks of the store to send them (claim once, the late window, a sender removed or narrowed, the
count mode, a send that failed). The bridge's side (the commands from a phone, the tick, the stand-in messenger) is in test_messaging_reminders.py; the
table and its triggers are in providers/store/tests/test_sqlite_reminders.py. Offline, no model, no network; every name and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_reminders.py
"""
from __future__ import annotations

import datetime
import json

import pytest

import standin_tree as st
from test_attachments import IDENT, OTHER, accept, case, fake_key  # noqa: F401  (the project the attachment tests use)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_reminders = st.load("ops_reminders")
operations = st.load("operations")
rm = st.load("reminders")

BRT = datetime.timezone(datetime.timedelta(hours=-3), "BRT")
THIRD = "6161616161"
FOURTH = "7171717171"
FIFTH = "8181818181"
SENDER = f"telegram:{IDENT}"
PROFILES = {"staff": ["read", "talk", "reminders"], "reader": ["read", "talk"]}
NOT_ENABLED = "is not enabled for this channel"


class Clock:
    """The machine's clock, stood in: `now()` and `local_at()` of ops_reminders read it; `set` moves it."""

    def __init__(self, monkeypatch, wall="2026-10-18 14:00", zone=BRT):
        self.zone = zone
        self.moment = datetime.datetime.strptime(wall, "%Y-%m-%d %H:%M").replace(tzinfo=zone)
        monkeypatch.setattr(ops_reminders, "now", lambda: self.moment)
        monkeypatch.setattr(ops_reminders, "local_at", lambda naive: naive.replace(tzinfo=self.zone))

    def set(self, wall):
        self.moment = datetime.datetime.strptime(wall, "%Y-%m-%d %H:%M").replace(tzinfo=self.zone)

    def at(self, naive):
        return naive.replace(tzinfo=self.zone)


def moment(wall="2026-10-18 14:00", zone=BRT, seconds=0):
    return datetime.datetime.strptime(wall, "%Y-%m-%d %H:%M").replace(tzinfo=zone) + datetime.timedelta(seconds=seconds)


def resolve(when, now, zone=BRT):
    return rm.resolve(when, now, lambda naive: naive.replace(tzinfo=zone))


@pytest.fixture
def world(case, monkeypatch):  # noqa: F811
    """The attachment tests' project with four listed senders on telegram: IDENT, OTHER and FOURTH hold the group `reminders` (the channel's default
    profile is `staff`, and OTHER's own is the same), THIRD has a profile without it. The clock reads 2026-10-18 14:00 at -03:00."""
    accept(case.path, policies=PROFILES, channels={"messaging": "staff"},
           messaging={"senders": {"telegram": [IDENT, {"id": OTHER, "policy": "staff"}, {"id": THIRD, "policy": "reader"}, FOURTH, FIFTH]}})
    case.clock = Clock(monkeypatch)
    case.store = lambda: ops_core.context(case.path)
    case.rows = lambda *statuses: case.store()["store"].reminders_list(case.store()["conn"], list(statuses) or None)
    case.remind = lambda when, text, to=SENDER: ops.remind(case.path, when, text, to, channel="terminal")
    case.phone = lambda sender, when, text: ops.remind(case.path, when, text, channel="messaging", sender=sender)
    return case


# --- 1. the words: which forms there are ---------------------------------------------------------------------------------------------------


def test_the_line_after_remind_is_a_time_and_the_words_to_send():
    split = rm.split_line
    assert split("15:00 call the dentist") == ("15:00", "call the dentist")
    assert split("  15:00   call   the dentist  ") == ("15:00", "call   the dentist"), "the words keep their spaces until clean_text"
    assert split("2026-10-20 09:30 renew the passport") == ("2026-10-20 09:30", "renew the passport")
    assert split("in 2h stretch") == ("in 2h", "stretch") and split("in 90m tea time") == ("in 90m", "tea time")
    assert split("15:00 16:00 meeting") == ("15:00", "16:00 meeting"), "only the first word is the time"
    for bad in ("", "   ", "15:00", "15:00   ", "2026-10-20 09:30", "in 2h", "in"):
        with pytest.raises(ValueError) as e:
            split(bad)
        assert str(e.value) == rm.USAGE, bad
    assert split("buy milk") == ("buy", "milk"), "a line that is not a time is read as one; resolve refuses it"


def test_the_usage_sentence_names_the_three_forms_and_the_clock():
    assert rm.USAGE == "Usage: /remind HH:MM <text>, /remind YYYY-MM-DD HH:MM <text> or /remind in <n>m|h|d <text> (24-hour clock, two digits)."
    assert rm.USAGE_FORGET == "Usage: /forget <n>"


# --- 2. HH:MM: today, or tomorrow when it has passed ----------------------------------------------------------------------------------------


def test_a_time_of_day_later_today_is_today_and_one_that_has_passed_is_tomorrow():
    now = moment("2026-10-18 14:00", seconds=30)
    got = resolve("15:00", now)
    assert got["wall"] == "2026-10-18T15:00" and got["zone"] == "BRT" and got["due"] == moment("2026-10-18 15:00")
    assert resolve("13:59", now)["wall"] == "2026-10-19T13:59", "past means tomorrow"
    assert resolve("14:00", now)["wall"] == "2026-10-19T14:00", "the minute that has begun has passed"
    assert resolve("00:00", now)["wall"] == "2026-10-19T00:00" and resolve("23:59", now)["wall"] == "2026-10-18T23:59"
    assert resolve("14:02", now)["wall"] == "2026-10-18T14:02"
    assert resolve("15:00", moment("2026-12-31 23:00"))["wall"] == "2027-01-01T15:00", "tomorrow crosses a month and a year"
    assert resolve("15:00", moment("2028-02-28 23:00"))["wall"] == "2028-02-29T15:00", "and a leap day"


def test_a_time_less_than_a_minute_ahead_is_refused_and_so_is_one_a_second_from_the_limit():
    now = moment("2026-10-18 14:00", seconds=30)
    with pytest.raises(ValueError) as e:
        resolve("14:01", now)
    assert str(e.value) == rm.TOO_SOON.format(now="2026-10-18 14:00") == "A reminder is at least one minute ahead. Now it is 2026-10-18 14:00."
    assert resolve("14:02", now)["wall"] == "2026-10-18T14:02" and rm.MIN_AHEAD == 60


# --- 3. a date, and a relative time ----------------------------------------------------------------------------------------------------------


def test_a_date_and_a_time_name_that_moment_and_a_moment_that_has_passed_is_refused():
    now = moment("2026-10-18 14:00")
    assert resolve("2026-10-20 09:30", now)["wall"] == "2026-10-20T09:30"
    assert resolve("2026-10-18 14:05", now)["wall"] == "2026-10-18T14:05"
    for past in ("2026-10-18 13:00", "2026-10-18 14:00", "2025-01-01 10:00"):
        with pytest.raises(ValueError) as e:
            resolve(past, now)
        assert str(e.value) == "That time has passed. Now it is 2026-10-18 14:00.", past
    assert resolve("2027-10-19 14:00", now)["wall"] == "2027-10-19T14:00", "366 days is the limit and a day of a leap-less year is 365"
    with pytest.raises(ValueError) as e:
        resolve("2027-10-20 14:00", now)
    assert str(e.value) == rm.TOO_FAR == "A reminder is at most 366 days ahead."
    assert rm.MAX_AHEAD == 366 * 86400


def test_a_relative_time_counts_from_now_and_never_comes_earlier_than_asked():
    now = moment("2026-10-18 14:00")
    assert resolve("in 2h", now)["wall"] == "2026-10-18T16:00" and resolve("in 90m", now)["wall"] == "2026-10-18T15:30"
    assert resolve("in 1d", now)["wall"] == "2026-10-19T14:00" and resolve("in 366d", now)["wall"] == "2027-10-19T14:00"
    assert resolve("in 10h", now)["wall"] == "2026-10-19T00:00", "across midnight"
    late = moment("2026-10-18 14:00", seconds=50)
    assert resolve("in 1m", late)["due"] == moment("2026-10-18 14:02"), "50 seconds past the minute: one minute is a full minute, rounded up to the next"
    assert resolve("in 2h", late)["wall"] == "2026-10-18T16:01"
    assert resolve("in   2h", now)["wall"] == "2026-10-18T16:00", "blanks between the words do not matter"
    for bad, sentence in (("in 367d", rm.TOO_FAR), ("in 9999d", rm.TOO_FAR), ("in 0m", rm.USAGE)):
        with pytest.raises(ValueError) as e:
            resolve(bad, now)
        assert str(e.value) == sentence, bad


# --- 4. what is refused, with the usage sentence or the one that says why ----------------------------------------------------------------------


@pytest.mark.parametrize("given", ["3pm", "3:00pm", "15h", "15", "9:30", "9h30", "15:00pm", "tomorrow 10:00", "next friday", "in 2 hours", "in 2", "in two h",
                                   "in 2w", "in -1h", "2026-10-20", "2026-10-20 9:30", "2026-10-20 teste", "20-10-2026 10:00", "2026-1-5 10:00",
                                   "2026/10/20 10:00", "10:00 2026-10-20", "15:00 16:00", "", "   ", "15:0", "15:000", "1500", "noon"])
def test_an_ambiguous_or_unknown_form_is_refused_with_the_usage_sentence(given):
    with pytest.raises(ValueError) as e:
        resolve(given, moment("2026-10-18 14:00"))
    assert str(e.value) == rm.USAGE, given


def test_a_time_or_a_day_that_does_not_exist_is_refused_with_the_sentence_that_says_which():
    now = moment("2026-10-18 14:00")
    for given in ("24:00", "25:00", "12:60", "99:99"):
        with pytest.raises(ValueError) as e:
            resolve(given, now)
        assert str(e.value) == f"{given} is not a time of day (00:00 to 23:59).", given
    for given in ("2026-02-30", "2026-13-01", "2026-00-10", "2025-02-29"):
        with pytest.raises(ValueError) as e:
            resolve(given + " 10:00", now)
        assert str(e.value) == f"{given} is not a day of the calendar.", given
    assert resolve("2028-02-29 10:00", moment("2028-02-01 10:00"))["wall"] == "2028-02-29T10:00"


def test_a_clock_with_no_zone_is_refused_not_guessed():
    with pytest.raises(ValueError):
        rm.resolve("15:00", datetime.datetime(2026, 10, 18, 14, 0), lambda naive: naive)


# --- 5. the zone: a clock change ---------------------------------------------------------------------------------------------------------------


def new_york():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        return zoneinfo.ZoneInfo("America/New_York")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("this machine has no time zone database")


def test_a_wall_time_the_clock_skips_is_refused_and_one_that_happens_twice_means_its_first_time():
    zone = new_york()
    before_spring = datetime.datetime(2026, 3, 7, 12, 0, tzinfo=zone)
    with pytest.raises(ValueError) as e:
        resolve("2026-03-08 02:30", before_spring, zone)
    assert str(e.value) == "2026-03-08 02:30 does not exist on that day (the clock skips it). Pick another time."
    got = resolve("2026-03-08 03:30", before_spring, zone)
    assert got["due"].utcoffset() == datetime.timedelta(hours=-4) and got["wall"] == "2026-03-08T03:30" and got["zone"] == "EDT"
    before_fall = datetime.datetime(2026, 10, 31, 12, 0, tzinfo=zone)
    twice = resolve("2026-11-01 01:30", before_fall, zone)
    assert twice["due"].utcoffset() == datetime.timedelta(hours=-4), "01:30 happens twice that night; the first is meant"
    assert resolve("2026-11-01 02:30", before_fall, zone)["due"].utcoffset() == datetime.timedelta(hours=-5)
    noon = datetime.datetime(2026, 3, 7, 12, 0, tzinfo=zone)
    assert resolve("in 24h", noon, zone)["wall"] == "2026-03-08T13:00", "a relative time is elapsed time: 24 hours across the spring change is 13:00 on the wall"
    assert resolve("12:00", noon, zone)["wall"] == "2026-03-08T12:00" and resolve("12:00", noon, zone)["due"].astimezone(datetime.timezone.utc) - noon.astimezone(datetime.timezone.utc) == datetime.timedelta(hours=23)


def test_the_machines_own_rules_are_the_default_clock(monkeypatch):
    """Without a stand-in, the clock is the machine's local time with its zone, and `local_at` reads the rules of that zone for the wall time asked."""
    now = ops_reminders.now()
    assert now.tzinfo is not None and now.utcoffset() is not None
    asked = datetime.datetime(2026, 12, 25, 10, 0)
    got = ops_reminders.local_at(asked)
    assert got.tzinfo is not None and got.replace(tzinfo=None) == asked


# --- 6. the text -------------------------------------------------------------------------------------------------------------------------------


def test_the_text_is_one_line_of_at_most_300_characters():
    clean = rm.clean_text
    assert clean("Call the dentist") == "Call the dentist"
    assert clean("  two\nlines\r\n and\ttabs\x00\x1b[31m  ") == "two lines and tabs [31m"
    assert clean("a b c") == "a b c"
    assert clean("é" * 300) == "é" * 300 and len(clean("😀" * 300)) == 300, "characters, not bytes"
    for bad, sentence in (("", rm.NO_TEXT), ("   \n\t", rm.NO_TEXT), (None, rm.NO_TEXT), ("x" * 301, "A reminder is at most 300 characters; yours has 301.")):
        with pytest.raises(ValueError) as e:
            clean(bad)
        assert str(e.value) == sentence
    assert rm.TEXT_MAX == 300


def test_the_caps_and_the_windows_are_the_constants_of_the_specification():
    assert (rm.OPEN_MAX, rm.DAY_MAX, rm.TEXT_MAX) == (100, 30, 300)
    assert (rm.MIN_AHEAD, rm.MAX_AHEAD, rm.LATE_WINDOW) == (60, 366 * 86400, 6 * 3600)
    assert rm.LATE_MARK == 300 and rm.CLAIM_STALE == 600 and rm.PER_TICK == 10
    assert rm.STATUSES == ("open", "sending", "sent", "cancelled", "missed", "dropped")


# --- 7. late: delivered with the time it was due, or missed -------------------------------------------------------------------------------------


def test_the_late_window_is_six_hours_and_a_late_line_carries_the_time_it_was_due():
    due = moment("2026-10-18 09:00")
    assert rm.verdict(due, moment("2026-10-18 08:59")) == ("wait", -60)
    assert rm.verdict(due, moment("2026-10-18 09:00")) == ("send", 0)
    assert rm.verdict(due, moment("2026-10-18 14:00")) == ("send", 5 * 3600), "5 hours late is sent"
    assert rm.verdict(due, moment("2026-10-18 15:00")) == ("send", 6 * 3600), "exactly 6 hours is the last second"
    assert rm.verdict(due, moment("2026-10-18 15:00", seconds=1)) == ("missed", 6 * 3600 + 1)
    assert rm.verdict(due, moment("2026-10-18 16:00")) == ("missed", 7 * 3600), "7 hours late is missed"
    assert rm.line(4, "Call the dentist", "2026-10-18T09:00", 30) == "Reminder: Call the dentist", "the tick's own delay is not a mark"
    assert rm.line(4, "Call the dentist", "2026-10-18T09:00", 300) == "Reminder: Call the dentist"
    assert rm.line(4, "Call the dentist", "2026-10-18T09:00", 301) == "Reminder: Call the dentist (due at 09:00)"
    assert rm.line(4, None, "2026-10-18T09:00", 0) == "A reminder is due (#4)."
    assert rm.line(4, None, "2026-10-18T09:00", 3600) == "A reminder is due (#4). It was due at 09:00."


# --- 8. making one -------------------------------------------------------------------------------------------------------------------------------


def test_the_terminal_makes_a_reminder_for_a_listed_sender_and_the_answer_names_the_day_and_the_time(world):
    got = world.remind("15:00", "Call the dentist")
    assert got["reply"] == "Reminder #1 set for 2026-10-18 15:00 (BRT)."
    assert got["reminder"] == {"id": 1, "due": "2026-10-18 15:00", "zone": "BRT", "status": "open", "platform": "telegram", "for": "staff on telegram",
                               "created_by": "terminal", "text": "Call the dentist"}
    assert IDENT not in str(got), "the sender's id is in the store alone"
    [row] = world.rows()
    assert (row["platform"], row["chat"], row["created_by"], row["status"], row["due_local"], row["zone"]) == ("telegram", IDENT, "terminal", "open", "2026-10-18T15:00", "BRT")
    assert row["due_utc"] == "2026-10-18T18:00:00.000000Z" and row["text"] == "Call the dentist"
    assert world.remind("in 2h", "Stretch")["reply"] == "Reminder #2 set for 2026-10-18 16:00 (BRT)."
    assert world.remind("2026-10-20 09:30", "Renew the passport")["reply"] == "Reminder #3 set for 2026-10-20 09:30 (BRT)."


def test_the_terminal_names_the_sender_and_a_sender_it_names_must_be_listed_and_hold_the_group(world):
    for to, sentence in ((None, rm.TERMINAL_USAGE), ("", rm.TERMINAL_USAGE), ("nobody", rm.TERMINAL_USAGE), ("telegram:", rm.TERMINAL_USAGE)):
        with pytest.raises(ops.OpsError) as e:
            world.remind("15:00", "x", to)
        assert str(e.value) == sentence and e.value.code == 2, to
    with pytest.raises(ops.OpsError) as e:
        world.remind("15:00", "x", "telegram:999")
    assert "telegram:999 is not a listed sender" in str(e.value)
    with pytest.raises(ops.OpsError) as e:
        world.remind("15:00", "x", "chirp:" + IDENT)
    assert "is not a listed sender" in str(e.value), "the platform counts: a listed id on telegram is no sender on another"
    with pytest.raises(ops.OpsError) as e:
        world.remind("15:00", "x", f"telegram:{THIRD}")
    assert "does not hold the group reminders" in str(e.value) and "--widen" in str(e.value)
    assert world.rows() == []


def test_a_refused_time_or_text_stores_nothing_and_is_a_usage_error(world):
    world.clock.moment += datetime.timedelta(seconds=30)
    for when, text, sentence in (("3pm", "x", rm.USAGE), ("15:00", "   ", rm.NO_TEXT), ("15:00", "y" * 301, "A reminder is at most 300 characters; yours has 301."),
                                 ("2026-10-18 13:00", "x", "That time has passed. Now it is 2026-10-18 14:00."), ("14:01", "x", rm.TOO_SOON.format(now="2026-10-18 14:00"))):
        with pytest.raises(ops.OpsError) as e:
            world.remind(when, text)
        assert str(e.value) == sentence and e.value.code == 2, (when, text)
    assert world.rows() == []


def test_a_text_that_looks_like_a_credential_is_refused_and_nothing_of_it_is_stored_or_said(world):
    key = fake_key()
    with pytest.raises(ops.OpsError) as e:
        world.remind("15:00", f"my key is {key}")
    assert "looks like a credential" in str(e.value) and key not in str(e.value) and e.value.code == 2
    with pytest.raises(ops.OpsError):
        world.phone(SENDER, "15:00", f"use {key} tonight")
    assert world.rows() == []
    assert world.remind("15:00", "Pay the electricity bill")["reply"].startswith("Reminder #")


def test_the_group_is_off_for_a_messaging_app_until_the_project_lists_it_and_the_sender_must_hold_it(world):
    me = SENDER
    got = world.phone(me, "15:00", "Call the dentist")
    assert got["reply"] == "Reminder #1 set for 2026-10-18 15:00 (BRT)."
    assert world.rows()[0]["created_by"] == f"messaging:telegram:staff:{IDENT}" and world.rows()[0]["chat"] == IDENT
    with pytest.raises(ops.OpsError) as e:
        world.phone(f"telegram:{THIRD}", "15:00", "x")
    assert NOT_ENABLED in str(e.value) and "/remind" in str(e.value)
    accept(world.path, policies=PROFILES, channels={}, messaging={"senders": {"telegram": [IDENT]}})
    with pytest.raises(ops.OpsError) as e:
        world.phone(me, "15:00", "x")
    assert NOT_ENABLED in str(e.value), "the default policy of a messaging app does not carry it"
    assert len(world.rows()) == 1


def test_a_messaging_sender_reminds_themselves_only(world):
    with pytest.raises(ops.OpsError) as e:
        ops.remind(world.path, "15:00", "x", f"telegram:{OTHER}", channel="messaging", sender=SENDER)
    assert "your own chat" in str(e.value)
    with pytest.raises(ops.OpsError):
        ops.remind(world.path, "15:00", "x", channel="messaging", sender=None)     # a call that names no sender is refused (ops_actor.require)
    with pytest.raises(ops.OpsError):
        ops.remind(world.path, "15:00", "x", channel="messaging", sender="telegram:999")      # not a listed sender
    assert world.rows() == []
    assert world.phone(f"telegram:{OTHER}", "15:00", "x")["reminder"]["for"] == "staff on telegram"
    assert world.rows()[0]["chat"] == OTHER


def test_the_text_is_stored_clean_and_never_in_the_answer_of_a_messaging_app(world):
    got = world.phone(SENDER, "15:00", "  Call\nthe   dentist\t")
    assert got["reply"] == "Reminder #1 set for 2026-10-18 15:00 (BRT)." and "Call" not in got["reply"]
    assert world.rows()[0]["text"] == "Call the dentist"


# --- 9. the caps -----------------------------------------------------------------------------------------------------------------------------------


def test_thirty_reminders_a_day_for_one_chat_then_the_next_day_and_the_other_chats_are_not_affected(world):
    for n in range(rm.DAY_MAX):
        world.remind(f"in {n + 1}m", f"line {n}")
    with pytest.raises(ops.OpsError) as e:
        world.remind("in 40m", "one too many")
    assert str(e.value) == "30 reminders were already made for this chat today. Try again tomorrow."
    assert world.remind("in 40m", "for someone else", f"telegram:{OTHER}")["reply"].startswith("Reminder #31")
    world.clock.set("2026-10-19 09:00")
    assert world.remind("in 40m", "a new day")["reminder"]["id"] == 32, "the day is the machine's local day"
    assert len(world.rows()) == 32


def test_one_hundred_reminders_wait_in_a_project_and_a_sent_one_makes_room(world):
    senders = [SENDER, f"telegram:{OTHER}", f"telegram:{FOURTH}", f"telegram:{FIFTH}"]
    n = 0
    for sender in senders:
        for _ in range(30 if sender != senders[-1] else 10):
            n += 1
            world.remind("in 2h", f"line {n}", sender)
    assert len(world.rows("open")) == 100
    with pytest.raises(ops.OpsError) as e:
        world.remind("in 2h", "the hundred and first", f"telegram:{FIFTH}")
    assert str(e.value) == "There are already 100 reminders waiting in this project. Forget one first."
    ops.reminder_forget(world.path, 1, channel="terminal")
    assert world.remind("in 2h", "now there is room", f"telegram:{FIFTH}")["reminder"]["id"] == 101


# --- 10. who sees and who forgets -------------------------------------------------------------------------------------------------------------------


def test_a_messaging_sender_reads_their_own_reminders_and_the_terminal_reads_them_all(world):
    world.remind("15:00", "Mine", SENDER)
    world.remind("16:00", "Another's", f"telegram:{OTHER}")
    mine = ops.reminders_read(world.path, channel="messaging", sender=SENDER)
    assert [(r["id"], r["text"]) for r in mine["open"]] == [(1, "Mine")] and mine["not_sent"] == []
    assert OTHER not in str(mine) and IDENT not in str(mine)
    assert mine["now"] == "2026-10-18 14:00" and mine["zone"] == "BRT"
    assert mine["limits"] == {"open": 100, "per_chat_per_day": 30, "text_characters": 300, "late_window_hours": 6}
    everyone = ops.reminders_read(world.path, channel="terminal")
    assert [(r["id"], r["text"], r["for"]) for r in everyone["open"]] == [(1, "Mine", "staff on telegram"), (2, "Another's", "staff on telegram")]
    assert ops.reminders_read(world.path, channel="page")["open"] == everyone["open"]
    with pytest.raises(ops.OpsError) as e:
        ops.reminders_read(world.path, channel="messaging", sender=f"telegram:{THIRD}")
    assert NOT_ENABLED in str(e.value)


def test_in_count_mode_a_messaging_sender_reads_no_text_and_the_terminal_still_does(world):
    world.phone(SENDER, "15:00", "Call the dentist")
    accept(world.path, policies=PROFILES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [IDENT]}, "notices": "count"})
    mine = ops.reminders_read(world.path, channel="messaging", sender=SENDER)
    assert [r["id"] for r in mine["open"]] == [1] and "text" not in mine["open"][0] and "dentist" not in str(mine)
    assert ops.reminders_read(world.path, channel="terminal")["open"][0]["text"] == "Call the dentist"


def test_a_sender_forgets_their_own_reminder_and_another_sender_s_looks_like_one_that_does_not_exist(world):
    world.remind("15:00", "Mine", SENDER)
    world.remind("16:00", "Another's", f"telegram:{OTHER}")
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_forget(world.path, 2, channel="messaging", sender=SENDER)
    other = str(e.value)
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_forget(world.path, 99, channel="messaging", sender=SENDER)
    assert other == str(e.value).replace("99", "2") == "No reminder 2 waits for you.", "the same answer for a reminder of someone else and one that is not there"
    assert world.rows("open")[1]["id"] == 2
    assert ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER)["reply"] == "Forgot reminder #1."
    assert [r["id"] for r in world.rows("cancelled")] == [1]
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER)
    assert str(e.value) == "Reminder 1 is cancelled, not waiting."
    assert ops.reminder_forget(world.path, 2, channel="terminal")["reminder"]["status"] == "cancelled", "the terminal is the person's own"
    for bad in (0, -1, "1", True):
        with pytest.raises(ops.OpsError):
            ops.reminder_forget(world.path, bad, channel="terminal")


def test_a_reminder_that_is_being_sent_is_not_forgotten_and_the_ones_that_did_not_go_out_are_listed_for_a_week(world):
    world.remind("in 2h", "Mine")
    world.clock.set("2026-10-18 16:00")
    [sending] = ops.reminders_due(world.path, "telegram")["send"]
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_forget(world.path, sending["id"], channel="messaging", sender=SENDER)
    assert str(e.value) == "Reminder 1 is being sent now."
    ops.reminders_retry(world.path, 1)
    world.clock.set("2026-10-19 04:00")
    assert ops.reminders_due(world.path, "telegram")["missed"] == 1
    gone = ops.reminders_read(world.path, channel="messaging", sender=SENDER)
    assert gone["open"] == [] and [(r["id"], r["status"], r["why"]) for r in gone["not_sent"]] == [(1, "missed", "late")]
    world.clock.set("2026-10-26 04:01")
    assert ops.reminders_read(world.path, channel="messaging", sender=SENDER)["not_sent"] == [], "after a week they are no longer named"


# --- 11. what the bridge asks of the store -----------------------------------------------------------------------------------------------------------


def due_ids(world, platform="telegram"):
    return [(r["id"], r["chat"]) for r in ops.reminders_due(world.path, platform)["send"]]


def test_a_due_reminder_is_claimed_by_one_call_and_sent_once(world):
    world.remind("in 2h", "Call the dentist")
    assert due_ids(world) == []
    world.clock.set("2026-10-18 16:00")
    got = ops.reminders_due(world.path, "telegram")
    assert got == {"send": [{"id": 1, "chat": IDENT, "late": 0, "due_local": "2026-10-18T16:00", "text": "Call the dentist"}], "missed": 0, "dropped": 0}
    assert world.rows()[0]["status"] == "sending"
    assert due_ids(world) == [], "a second tick finds it claimed"
    assert ops.reminders_sent(world.path, 1) == {"id": 1}
    assert world.rows()[0]["status"] == "sent" and world.rows()[0]["ended_at"]
    assert due_ids(world) == []
    with pytest.raises(ops.OpsError):
        ops.reminders_sent(world.path, 1)           # an ended reminder is final


def test_a_send_that_failed_is_open_again_and_tried_at_the_next_tick_until_the_window_ends(world):
    world.remind("in 2h", "Call the dentist")
    world.clock.set("2026-10-18 16:00")
    assert due_ids(world) == [(1, IDENT)]
    assert ops.reminders_retry(world.path, 1) == {"id": 1, "open": True}
    world.clock.set("2026-10-18 16:01")
    assert due_ids(world) == [(1, IDENT)], "tried again"
    ops.reminders_retry(world.path, 1)
    world.clock.set("2026-10-18 22:01")
    assert ops.reminders_due(world.path, "telegram") == {"send": [], "missed": 1, "dropped": 0}
    assert world.rows()[0]["status"] == "missed" and world.rows()[0]["why"] == "late"


def test_a_bridge_that_stopped_between_the_send_and_the_mark_leaves_the_reminder_open_again_after_ten_minutes(world):
    world.remind("in 2h", "Call the dentist")
    world.clock.set("2026-10-18 16:00")
    assert due_ids(world) == [(1, IDENT)]
    world.clock.moment += datetime.timedelta(seconds=rm.CLAIM_STALE - 1)
    assert due_ids(world) == [] and world.rows()[0]["status"] == "sending"
    world.clock.moment += datetime.timedelta(seconds=2)
    store = world.store()
    store["conn"].execute("UPDATE reminders SET claimed_at = '2026-10-18T19:00:00.000000Z' WHERE id = 1")      # the claim is stamped by the store's clock: stand it in
    store["conn"].commit()
    got = ops.reminders_due(world.path, "telegram")
    assert [r["id"] for r in got["send"]] == [1] and got["send"][0]["late"] == rm.CLAIM_STALE + 1, "it may go twice (said in the docs), never zero times"


def test_five_hours_late_is_delivered_with_the_time_it_was_due_and_seven_hours_late_is_missed(world):
    world.remind("2026-10-18 15:00", "Five hours late")
    world.remind("2026-10-18 15:00", "Seven hours late")
    world.clock.set("2026-10-18 20:00")
    got = ops.reminders_due(world.path, "telegram")
    assert [(r["id"], r["late"]) for r in got["send"]] == [(1, 5 * 3600), (2, 5 * 3600)]
    ops.reminders_sent(world.path, 1)
    ops.reminders_retry(world.path, 2)
    world.clock.set("2026-10-18 22:00")
    got = ops.reminders_due(world.path, "telegram")
    assert got["send"] == [] and got["missed"] == 1, "7 hours past its time the one that was only claimed once is missed"
    assert sorted((r["id"], r["status"]) for r in world.rows()) == [(1, "sent"), (2, "missed")]
    assert rm.line(1, "Five hours late", "2026-10-18T15:00", 5 * 3600) == "Reminder: Five hours late (due at 15:00)"


def test_a_sender_removed_before_the_time_gets_nothing_and_the_reminder_is_dropped(world):
    world.remind("in 2h", "Call the dentist")
    world.remind("in 2h", "Another's", f"telegram:{OTHER}")
    accept(world.path, policies=PROFILES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [OTHER]}})
    world.clock.set("2026-10-18 16:00")
    assert ops.reminders_due(world.path, "telegram") == {"send": [{"id": 2, "chat": OTHER, "late": 0, "due_local": "2026-10-18T16:00", "text": "Another's"}],
                                                       "missed": 0, "dropped": 1}
    [first] = world.rows("dropped")
    assert (first["id"], first["why"]) == (1, "sender removed")
    assert [r["why"] for r in ops.reminders_read(world.path, channel="terminal")["not_sent"]] == ["sender removed"]


def test_a_sender_who_lost_the_group_before_the_time_gets_nothing_and_the_reminder_is_dropped(world):
    world.remind("in 2h", "Call the dentist")
    accept(world.path, policies=PROFILES, channels={"messaging": "reader"}, messaging={"senders": {"telegram": [IDENT]}})      # narrowing: no ceremony
    world.clock.set("2026-10-18 16:00")
    assert ops.reminders_due(world.path, "telegram") == {"send": [], "missed": 0, "dropped": 1}
    assert [(r["id"], r["why"]) for r in world.rows("dropped")] == [(1, "not permitted")]


def test_the_profile_is_read_when_the_reminder_fires_and_not_when_it_was_made(world):
    """A sender narrowed and widened again before the time is sent the reminder: what counts is the file accepted at the moment it fires."""
    world.remind("in 2h", "Call the dentist")
    accept(world.path, policies=PROFILES, channels={"messaging": "reader"}, messaging={"senders": {"telegram": [IDENT]}})
    accept(world.path, policies=PROFILES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [IDENT]}})
    world.clock.set("2026-10-18 16:00")
    assert due_ids(world) == [(1, IDENT)]


def test_in_count_mode_a_due_reminder_carries_no_text(world):
    world.remind("in 2h", "Call the dentist")
    accept(world.path, policies=PROFILES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [IDENT]}, "notices": "count"})
    world.clock.set("2026-10-18 16:00")
    [item] = ops.reminders_due(world.path, "telegram")["send"]
    assert item == {"id": 1, "chat": IDENT, "late": 0, "due_local": "2026-10-18T16:00"} and "dentist" not in str(item)
    assert rm.line(item["id"], item.get("text"), item["due_local"], item["late"]) == "A reminder is due (#1)."


def test_only_the_platform_asking_is_served_and_no_more_than_ten_go_out_in_a_tick(world):
    for n in range(12):
        world.remind("in 2h", f"line {n}")
    world.clock.set("2026-10-18 16:00")
    assert ops.reminders_due(world.path, "chirp") == {"send": [], "missed": 0, "dropped": 0}
    assert len(world.rows("open")) == 12
    got = ops.reminders_due(world.path, "telegram")
    assert [r["id"] for r in got["send"]] == list(range(1, 11)), "the oldest first, at most PER_TICK"
    assert [r["id"] for r in ops.reminders_due(world.path, "telegram")["send"]] == [11, 12]


def test_a_reminder_is_sent_to_the_chat_it_was_made_for_and_nothing_names_another(world):
    world.remind("in 2h", "for the first")
    world.phone(f"telegram:{OTHER}", "in 2h", "for the second")
    world.clock.set("2026-10-18 16:00")
    assert sorted(due_ids(world)) == [(1, IDENT), (2, OTHER)]
    assert {r["id"]: r["chat"] for r in world.rows()} == {1: IDENT, 2: OTHER}


# --- 12. the policy ---------------------------------------------------------------------------------------------------------------------------------


def test_the_group_is_in_no_default_policy_and_never_on_the_mcp_mode():
    rows = ("remind", "reminders", "reminder-forget")
    assert operations.GROUPS["reminders"] == {"operations": rows, "kind": None}
    assert "reminders" not in operations.DEFAULT_POLICY["messaging"] and not any("reminders" in v for v in operations.DEFAULT_POLICY.values())
    assert all("reminders" not in groups for groups in operations.GRANTS.values()), "it is a group inside the ceiling, not a grant"
    for name in rows:
        row = operations.by_name(name)
        assert row["channels"] == ("terminal", "page", "messaging") and "mcp" not in row["channels"] and "chat" not in row["channels"], name
        assert row["model"] is False and row.get("channel_arg") is True
        assert not operations.permitted(name, "mcp", None) and not operations.permitted(name, "mcp", {"mcp": list(operations.GROUPS)}), name
        assert not operations.permitted(name, "messaging", None) and operations.permitted(name, "messaging", {"messaging": ["reminders"]}), name
        assert operations.permitted(name, "terminal", {}) and "mcp" not in operations.NEVER_GRANTED
    assert "mcp" in operations.GRANTS and "chat" in operations.NEVER_GRANTED and "terminal" in operations.NEVER_GRANTED
    assert "is valid" not in (operations.group_refusal("messaging", "reminders") or "") and operations.group_refusal("messaging", "reminders") is None
    refusal = operations.group_refusal("mcp", "reminders")
    assert refusal and "reminders" in refusal and "mcp" in refusal, "a configuration that lists it for the MCP mode is refused"


def test_turning_the_group_on_is_a_widening_that_accept_config_takes_only_with_its_hash(world):
    accept(world.path, policies={"staff": ["read", "talk"]}, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [IDENT]}})
    file = world.path + "/docs/workbench/runtime.json"
    raw = json.loads(open(file).read())
    raw["policies"] = {"staff": ["read", "talk", "reminders"]}
    open(file, "w").write(json.dumps(raw))
    shown = ops.config(world.path)
    assert shown["widening_sha256"] and any(w["group"] == "reminders" for w in shown["widening"]), shown["widening"]
    assert [w["means"] for w in shown["widening"] if w["group"] == "reminders"][0] == operations.GROUP_TEXT["reminders"]
    with pytest.raises(ops.OpsError) as e:
        ops.accept_config(world.path, shown["sha256"])
    assert "--widen" in str(e.value) or "widen" in str(e.value)
    ops.accept_config(world.path, shown["sha256"], widen=shown["widening_sha256"])
    assert world.phone(SENDER, "15:00", "now it is on")["reply"].startswith("Reminder #1")
