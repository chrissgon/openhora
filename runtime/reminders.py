#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Reminders, the pure part (package RM-1): what a person types, as a moment and a text, and the rules that decide whether a reminder is still
to be sent. No store, no clock of its own, no file, no network: the operations (runtime/ops_reminders.py) pass the clock in.

A reminder is a stored one-shot notice the messaging bridge sends to the chat that made it, with the person's own words and no model in between.
It is never an effect (nothing is done in the world); limit L51 (contracts/runtime.md) is what keeps it that way.

What a person types (the words after `/remind`, or the two arguments of the terminal's `remind`):

  HH:MM <text>                       today at that time, or tomorrow when that time has passed
  YYYY-MM-DD HH:MM <text>            that day
  in <n>m | in <n>h | in <n>d <text> that long from now (n from 1 to 9999)

HH:MM is a 24-hour clock with two digits for the hour ("09:30", never "9:30", "9h30" or "9am": a time that can be read two ways is refused with the
usage sentence, not guessed). The zone is the host's: the local time of the machine that runs the bridge, the same clock a routine's `at` reads. A
wall time that does not exist (the hour a clock change skips) is refused; one that happens twice means its first occurrence. A reminder is at least
one minute ahead (MIN_AHEAD) and at most 366 days ahead (MAX_AHEAD).

  split_line(rest)            (when, text) of the words after `/remind`: only the first one or two words are the time; ValueError(USAGE) otherwise
  strict(rest)                (when, text) when the words after `/remind` begin with a time of the strict grammar above and have words after it, else None (the
                              line is then read in the person's own words by runtime/natural.py, package NR-1)
  resolve(when, now, at[, local])  the due moment of a `when`: {"due": aware datetime, "wall": "YYYY-MM-DDTHH:MM", "zone": name}; ValueError(sentence) says why not
  is_time_only(when)          whether a `when` is a bare `HH:MM` (today, or tomorrow when it has passed)
  clean_text(text)            the text as it is stored (one line, control characters and runs of blanks become one space, format characters dropped), or ValueError(sentence)
  retry_delay(attempts)       how long a reminder whose send failed waits before the next try (1, 2, 4, 8 ... minutes)
  verdict(due, now)           what to do with an open reminder: "wait", "send" or "missed" (the late window), and how late it is
  line(id, text, due_local, late[, cfg])  the line a due reminder goes out as, with the mark "(due at HH:MM)" when it went out late, in the language of `cfg` (runtime/phrases.py)

`now` is an aware datetime; `at(naive)` is the aware datetime of a local wall time, by the rules of the zone (the host's own, or a stand-in's). The
caps and the sentences are constants of this file, read by the operations and the tests. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402  (the same folder: the sentences, in the project's language)

UTC = datetime.timezone.utc

TEXT_MAX = 300                    # characters of one reminder
OPEN_MAX = 100                    # reminders waiting (open or being sent) in a project
OPEN_CHAT_MAX = 30                # and for one chat, so that one sender cannot fill the project and block the others
BACKOFF_MAX_MINUTES = 64          # a send that failed is tried again after 1, 2, 4, 8 ... minutes, no longer apart than this
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

# The English sentences, kept under their old names (the operations raise them as the text of an OpsError, and the terminal shows them as they are); the phrase
# table (runtime/phrases.py) is their source, and the messaging bridge says them on a phone in the project's language (package LR-1).
USAGE = phrases.en("RM_USAGE")
USAGE_FORGET = phrases.en("USAGE_FORGET")
TEXT_LINE = phrases.en("RM_TEXT_LINE")
COUNT_LINE = phrases.en("RM_COUNT_LINE")
NO_SUCH = phrases.en("RM_NO_SUCH")
NOT_WAITING = phrases.en("RM_NOT_WAITING")
BEING_SENT = phrases.en("RM_BEING_SENT")
OPEN_FULL = phrases.en("RM_OPEN_FULL")
CHAT_FULL = phrases.en("RM_CHAT_FULL")
DAY_FULL = phrases.en("RM_DAY_FULL")
SET = phrases.en("RM_SET")
FORGOT = phrases.en("RM_FORGOT")
NOT_LISTED = phrases.en("RM_NOT_LISTED")
TERMINAL_USAGE = ("--when is HH:MM, YYYY-MM-DD HH:MM or in <n>m|h|d (24-hour clock, two digits), and --text is what to say; "
                  "--to <platform>:<id> names the listed sender it goes to.")
NOT_A_TIME = phrases.en("RM_NOT_A_TIME")
NO_SUCH_DATE = phrases.en("RM_NO_SUCH_DATE")
NO_SUCH_TIME = phrases.en("RM_NO_SUCH_TIME")
PAST = phrases.en("RM_PAST")
TOO_SOON = phrases.en("RM_TOO_SOON")
TOO_FAR = phrases.en("RM_TOO_FAR")
NO_TEXT = phrases.en("RM_NO_TEXT")
TOO_LONG = phrases.en("RM_TOO_LONG")
CREDENTIAL = phrases.en("RM_CREDENTIAL")

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


_STRICT_CLOCK = re.compile(r"[0-9]{2}:[0-9]{2}")
_STRICT_RELATIVE = re.compile(r"[0-9]{1,4}[mhd]")


def strict(rest) -> "tuple | None":
    """(when, text) when the words after `/remind` begin with a time of the strict grammar and have words after it: `HH:MM` with two digits each (so `25:00`
    is claimed and refused as a time of day, as before), a date and such a time, or `in <n><unit>`. None when they do not (`13hrs`, `9:30`, `tomorrow 13h`, a
    time and no words): the line is then read in the person's own words (runtime/natural.py). Pure, no clock."""
    words = (rest or "").split()
    for head in (1, 2):
        if len(words) <= head:
            continue
        given = words[:head]
        if (head == 1 and _STRICT_CLOCK.fullmatch(given[0])) or (head == 2 and ((_DATE.fullmatch(given[0]) and _STRICT_CLOCK.fullmatch(given[1])) or (
                given[0] == "in" and _STRICT_RELATIVE.fullmatch(given[1])))):
            return split_line(rest)
    return None


def is_time_only(when) -> bool:
    """Whether `when` is a time of day with no day (`HH:MM`): the form that means today, or tomorrow when today's has passed."""
    return bool(_TIME.fullmatch(" ".join((when or "").split())))


def clean_text(text) -> str:
    """The text as it is stored: one line (a control character or a line end, and a run of blanks, is one space; a format character, Unicode category
    Cf, is dropped: a bidirectional override can disguise a line, and an emoji joiner is lost with it), not empty, at most TEXT_MAX characters. ValueError(sentence) when it is not."""
    given = _CONTROL.sub(" ", text if isinstance(text, str) else "")
    given = "".join(c for c in given if unicodedata.category(c) != "Cf")      # bidi overrides, zero-width characters, the byte order mark, the soft hyphen
    one = " ".join(given.split())
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


def resolve(when: str, now: datetime.datetime, at, local=None) -> dict:
    """The due moment of `when` ({"due": aware datetime, "wall": "YYYY-MM-DDTHH:MM", "zone": name}), or ValueError with the sentence that says why not.
    `now` is aware; `at(naive)` is the aware datetime of a local wall time; `local(instant)` is an instant read in the local time of THAT day (the machine's
    rules, so a clock change between now and then counts; by default the zone `now` carries). Checked in this order: the form, the time of day and the date, the
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
        due = local(due) if local is not None else due.astimezone(now.tzinfo)
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
            today = datetime.datetime.combine(day, datetime.time(hour, minute))
            tomorrow = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(hour, minute))
            if today <= now.replace(tzinfo=None):       # already past on the wall clock: tomorrow's, whether or not today's exists (the hour a clock change skips)
                due = _at(tomorrow, at)
            else:
                due = _at(today, at)                     # a time ahead that the clock skips is refused
                if due.astimezone(UTC) <= now.astimezone(UTC):      # the first of two occurrences has passed
                    due = _at(tomorrow, at)
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


def retry_delay(attempts: int) -> int:
    """Seconds to wait before a reminder whose send failed `attempts` times (1 for the first failure) is tried again: 1, 2, 4, 8 ... minutes, to BACKOFF_MAX_MINUTES."""
    return 60 * min(2 ** max(0, int(attempts) - 1), BACKOFF_MAX_MINUTES)


def verdict(due: datetime.datetime, now: datetime.datetime) -> tuple:
    """(word, seconds late) for an open reminder: "wait" before its time, "send" from its time to LATE_WINDOW after it, "missed" later than that."""
    late = int((now.astimezone(UTC) - due.astimezone(UTC)).total_seconds())
    if late < 0:
        return "wait", late
    return ("send" if late <= LATE_WINDOW else "missed"), late


def line(reminder_id: int, text, due_local: str, late: int, cfg=None) -> str:
    """The line a due reminder goes out as: "Reminder: <text>", or, when the project's notices carry no text (`text` is None), "A reminder is due
    (#<id>)."; either followed by the mark "(due at HH:MM)" when it went out later than LATE_MARK (the wall time it was asked for, from `due_local`).
    `cfg` maps `language` to the project's setting (runtime/phrases.py): the frame is said in it; the person's own words are never touched."""
    at = due_local[11:16] if late > LATE_MARK and len(due_local) >= 16 else ""
    if text is None:
        return phrases.text("RM_COUNT_LINE", cfg, id=reminder_id) + (phrases.text("RM_COUNT_LATE", cfg, at=at) if at else "")
    return phrases.text("RM_TEXT_LINE", cfg, text=text) + (phrases.text("RM_TEXT_LATE", cfg, at=at) if at else "")


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
