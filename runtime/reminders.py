#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Reminders, the pure part (package RM-1): what a person types, as a moment and a text, and the rules that decide whether a reminder is still
to be sent. No store, no clock of its own, no file, no network: the operations (runtime/ops_reminders.py) pass the clock in.

A reminder is a stored one-shot notice the messaging bridge sends to the chat that made it, with the person's own words and no model in between.
It is never an effect (nothing is done in the world); limit LR (contracts/runtime.md) is what keeps it that way.

What a person types (the words after `/remind`, or the two arguments of the terminal's `remind`):

  HH:MM <text>                       today at that time, or tomorrow when that time has passed
  YYYY-MM-DD HH:MM <text>            that day
  in <n>m | in <n>h | in <n>d <text> that long from now (n from 1 to 9999)

HH:MM is a 24-hour clock with two digits for the hour ("09:30", never "9:30", "9h30" or "9am": a time that can be read two ways is refused with the
usage sentence, not guessed). The zone is the host's: the local time of the machine that runs the bridge, the same clock a routine's `at` reads. A
wall time that does not exist (the hour a clock change skips) is refused; one that happens twice means its first occurrence. A reminder is at least
one minute ahead (MIN_AHEAD) and at most 366 days ahead (MAX_AHEAD).

  split_line(rest)            (when, text) of the words after `/remind`: only the first one or two words are the time; ValueError(USAGE) otherwise
  resolve(when, now, at)      the due moment of a `when`: {"due": aware datetime, "wall": "YYYY-MM-DDTHH:MM", "zone": name}; ValueError(sentence) says why not
  clean_text(text)            the text as it is stored (one line, control characters and runs of blanks become one space), or ValueError(sentence)
  verdict(due, now)           what to do with an open reminder: "wait", "send" or "missed" (the late window), and how late it is
  line(id, text, due_local, late)  the line a due reminder goes out as, with the mark "(due at HH:MM)" when it went out late

`now` is an aware datetime; `at(naive)` is the aware datetime of a local wall time, by the rules of the zone (the host's own, or a stand-in's). The
caps and the sentences are constants of this file, read by the operations and the tests. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import re
import sys

UTC = datetime.timezone.utc

TEXT_MAX = 300                    # characters of one reminder
OPEN_MAX = 100                    # reminders waiting (open or being sent) in a project
DAY_MAX = 30                      # reminders made for one recipient in a day (the local day of the clock)
MIN_AHEAD = 60                    # seconds: a reminder is at least this far from now
MAX_AHEAD = 366 * 86400           # seconds: and at most this far
LATE_WINDOW = 6 * 3600            # seconds: a reminder this late or less is sent when a bridge runs again; later it ends `missed`
LATE_MARK = 300                   # seconds: a reminder later than this goes out marked "(due at HH:MM)"; within it, the tick's own delay, it is sent plain
CLAIM_STALE = 600                 # seconds: a reminder that has been `sending` this long belongs to a bridge that stopped; it is open again
PER_TICK = 10                     # reminders one tick of the bridge sends for one project; the rest wait for the next tick
RECENT_DAYS = 7                   # how long `/reminders` keeps naming a reminder that did not go out (missed, dropped)
RECENT_MAX = 10
STATUSES = ("open", "sending", "sent", "cancelled", "missed", "dropped")
FINAL = ("sent", "cancelled", "missed", "dropped")
WHYS = ("late", "sender removed", "not permitted")    # the closed words kept with a reminder that ended `missed` or `dropped`

USAGE = "Usage: /remind HH:MM <text>, /remind YYYY-MM-DD HH:MM <text> or /remind in <n>m|h|d <text> (24-hour clock, two digits)."
USAGE_FORGET = "Usage: /forget <n>"
TEXT_LINE = "Reminder: {text}"
COUNT_LINE = "A reminder is due (#{id})."
NO_SUCH = "No reminder {n} waits for you."
NOT_WAITING = "Reminder {n} is {status}, not waiting."
BEING_SENT = "Reminder {n} is being sent now."
OPEN_FULL = "There are already {n} reminders waiting in this project. Forget one first."
DAY_FULL = "{n} reminders were already made for this chat today. Try again tomorrow."
SET = "Reminder #{id} set for {wall} ({zone})."
FORGOT = "Forgot reminder #{id}."
NOT_LISTED = "You are not a listed sender of this project."
TERMINAL_USAGE = ("--when is HH:MM, YYYY-MM-DD HH:MM or in <n>m|h|d (24-hour clock, two digits), and --text is what to say; "
                  "--to <platform>:<id> names the listed sender it goes to.")
NOT_A_TIME = "{given} is not a time of day (00:00 to 23:59)."
NO_SUCH_DATE = "{given} is not a day of the calendar."
NO_SUCH_TIME = "{given} does not exist on that day (the clock skips it). Pick another time."
PAST = "That time has passed. Now it is {now}."
TOO_SOON = "A reminder is at least one minute ahead. Now it is {now}."
TOO_FAR = "A reminder is at most 366 days ahead."
NO_TEXT = "A reminder needs the words to send."
TOO_LONG = "A reminder is at most {max} characters; yours has {n}."
CREDENTIAL = "That text looks like a credential ({labels}); a reminder is a message sent to your phone, so it is not stored."

_TIME = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
_LOOSE_TIME = re.compile(r"[0-9]{1,2}:[0-9]{2}")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_RELATIVE = re.compile(r"in ([0-9]{1,4})([mhd])")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")
_UNITS = {"m": 60, "h": 3600, "d": 86400}


def split_line(rest: str) -> tuple:
    """(when, text) of the words after `/remind`. The time is the first word (HH:MM), the first two (a date and a time) or the first two of
    `in <n><unit>`; everything after is the text, as it was typed. ValueError(USAGE) when the line has no time or no text."""
    first = (rest or "").split(None, 1)
    if not first:
        raise ValueError(USAGE)
    head = 2 if first[0] == "in" or _DATE.fullmatch(first[0]) else 1
    parts = (rest or "").split(None, head)
    if len(parts) <= head or not parts[head].strip():
        raise ValueError(USAGE)
    return " ".join(parts[:head]), parts[head].strip()


def clean_text(text) -> str:
    """The text as it is stored: one line (a control character or a line end, and a run of blanks, is one space), not empty, at most TEXT_MAX
    characters. ValueError(sentence) when it is not."""
    one = " ".join(_CONTROL.sub(" ", text if isinstance(text, str) else "").split())
    if not one:
        raise ValueError(NO_TEXT)
    if len(one) > TEXT_MAX:
        raise ValueError(TOO_LONG.format(max=TEXT_MAX, n=len(one)))
    return one


def _wall(moment: datetime.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


def _exists(moment: datetime.datetime, naive: datetime.datetime) -> bool:
    """Whether the wall time `naive` is a time that exists in the zone of `moment` (the aware datetime `at` made for it): the instant, read in the
    zone again, gives the same wall time."""
    back = moment.astimezone(datetime.timezone.utc).astimezone(moment.tzinfo)
    return moment.replace(tzinfo=None) == naive and back.replace(tzinfo=None) == naive


def _at(naive: datetime.datetime, at) -> datetime.datetime:
    moment = at(naive)
    if not _exists(moment, naive):
        raise ValueError(NO_SUCH_TIME.format(given=_wall(naive)))
    return moment


def zone_name(moment: datetime.datetime) -> str:
    return moment.tzname() or (moment.strftime("%z") or "UTC")


def resolve(when: str, now: datetime.datetime, at) -> dict:
    """The due moment of `when` ({"due": aware datetime, "wall": "YYYY-MM-DDTHH:MM", "zone": name}), or ValueError with the sentence that says why not.
    `now` is aware; `at(naive)` is the aware datetime of a local wall time. Checked in this order: the form, the time of day and the date, the
    wall time exists, it is not past, it is at least MIN_AHEAD and at most MAX_AHEAD from now."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("the clock has no zone")
    given = " ".join((when or "").split())
    relative = _RELATIVE.fullmatch(given)
    if relative:
        seconds = int(relative.group(1)) * _UNITS[relative.group(2)]
        if seconds < 1:
            raise ValueError(USAGE)
        due = now.astimezone(UTC) + datetime.timedelta(seconds=seconds)       # elapsed time, so a clock change in between counts: arithmetic in UTC
        if due.second or due.microsecond:       # to the minute, upwards: a reminder never comes earlier than it was asked
            due = due.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        due = due.astimezone(now.tzinfo)
    else:
        words = given.split(" ")
        if len(words) == 2 and _DATE.fullmatch(words[0]):
            date, clock = words
        elif len(words) == 1:
            date, clock = None, words[0]
        else:
            raise ValueError(USAGE)
        if not _TIME.fullmatch(clock):
            if _LOOSE_TIME.fullmatch(clock) and len(clock) == 5:
                raise ValueError(NOT_A_TIME.format(given=clock))
            raise ValueError(USAGE)
        hour, minute = int(clock[:2]), int(clock[3:])
        if date is None:
            day = now.date()
            due = _at(datetime.datetime.combine(day, datetime.time(hour, minute)), at)
            if due.astimezone(UTC) <= now.astimezone(UTC):
                due = _at(datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(hour, minute)), at)
        else:
            try:
                day = datetime.date(int(date[:4]), int(date[5:7]), int(date[8:]))
            except ValueError:
                raise ValueError(NO_SUCH_DATE.format(given=date)) from None
            due = _at(datetime.datetime.combine(day, datetime.time(hour, minute)), at)
    ahead = (due.astimezone(UTC) - now.astimezone(UTC)).total_seconds()        # two aware times of one zone object compare by their wall clocks: UTC says how far apart they are
    if ahead <= 0:
        raise ValueError(PAST.format(now=_wall(now)))
    if ahead < MIN_AHEAD:
        raise ValueError(TOO_SOON.format(now=_wall(now)))
    if ahead > MAX_AHEAD:
        raise ValueError(TOO_FAR)
    return {"due": due, "wall": due.strftime("%Y-%m-%dT%H:%M"), "zone": zone_name(due)}


def verdict(due: datetime.datetime, now: datetime.datetime) -> tuple:
    """(word, seconds late) for an open reminder: "wait" before its time, "send" from its time to LATE_WINDOW after it, "missed" later than that."""
    late = int((now.astimezone(UTC) - due.astimezone(UTC)).total_seconds())
    if late < 0:
        return "wait", late
    return ("send" if late <= LATE_WINDOW else "missed"), late


def line(reminder_id: int, text, due_local: str, late: int) -> str:
    """The line a due reminder goes out as: "Reminder: <text>", or, when the project's notices carry no text (`text` is None), "A reminder is due
    (#<id>)."; either followed by the mark "(due at HH:MM)" when it went out later than LATE_MARK (the wall time it was asked for, from `due_local`)."""
    at = due_local[11:16] if late > LATE_MARK and len(due_local) >= 16 else ""
    if text is None:
        return COUNT_LINE.format(id=reminder_id) + (f" It was due at {at}." if at else "")
    return TEXT_LINE.format(text=text) + (f" (due at {at})" if at else "")


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
