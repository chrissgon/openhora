#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations over the person's own calendar (package W1): create an event, change one, remove one. Each one PREPARES and nothing else: it checks its
arguments, makes one request with one step task of the kind `calendar-event` (runtime/step_calendar_event.py), runs the preparation in this process with no model,
and stops at the card that asks the person to approve it (runtime/account_start.py). It returns {"request", "task", "pending", "word", "on_cards"}; the
messaging bridge then sends the decision's card as it sends every card and says `account_start.reply_text`. Nothing is written to any calendar here: the write is
runtime/effect_calendar.py `execute`, reached only by `approve` with the hash of the card (limit L55).

  event_create(project, account, title, start[, end, calendar, location, reminder_minutes, notes, repeat])
        a new event on a calendar of the account (the first one the project lists when `calendar` is absent); nobody is invited; `repeat` ("daily" or "weekly", weekly on the
        weekday of `start`) makes a series with no end, for a timed event, written in this machine's named zone (CB-7)
  event_change(project, account, event[, title, start, end, location, reminder_minutes, notes, calendar])
        change parts of an event you organize with no other attendee and no recurrence; `event` is a reference: `<source>#<n>` (the n-th item of a calendar
        snapshot, once the index of the snapshots is in the checkout) or `created:<decision>` (an event this runtime created). The calendar is the one the
        reference puts the event on (it must be one the project's `accounts` lists); `calendar` names it when the person wants to be sure, and a different one is refused
  event_cancel(project, account, event[, calendar, series, occurrence])
        remove such an event: Google is expected to send it to the calendar's trash (30 days; to verify live); on Outlook it may not be recoverable (not verified). An event of a
        daily or weekly series is cancelled with `series` (the whole series: the master, read by code) or `occurrence` (a local day, YYYY-MM-DD: only that day's occurrence, found
        by code in the provider's list of the series' instances; the series stays); a series is never changed, and neither is its master (CB-7)

Who may call what is the table of operations (runtime/operations.py: the group `calendar-write`, in no default policy, never on the MCP mode) and, for a messaging
sender, runtime/account_start.py (the profile of THAT sender, read from the configuration loaded for this call). The words of the person (a title, notes) reach a
model nowhere on this path: the card is made by code from the arguments.

Sibling of runtime/ops.py, which exposes the operations under their names. It reaches no operation of ops.py. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import account_start  # noqa: E402
import ops_core as core  # noqa: E402

KIND = "calendar-event"


TITLE_KEYS = {"create": "TITLE_CAL_CREATE", "change": "TITLE_CAL_CHANGE", "cancel": "TITLE_CAL_CANCEL", "cancel-series": "TITLE_CAL_CANCEL_SERIES",
              "cancel-occurrence": "TITLE_CAL_CANCEL_OCCURRENCE"}


def _start(project, operation: str, account, args: dict, channel, sender) -> dict:
    """The one start of the family: the arguments the call gave (those that are not None), under the operation's name and the title of its card."""
    given = {k: v for k, v in args.items() if v is not None}
    # who asked goes with the arguments, as the caller gave it (never mapped to a channel with more rights): a reference into a snapshot is usable only by a caller who
    # may read it (item_refs.may_read), a `created:` reference only by the sender who asked for that event, and the step refuses a channel it does not know
    given.update({k: v for k, v in (("channel", channel if channel is not None else "terminal"), ("sender", sender if channel == "messaging" else None)) if v is not None})
    # the cancel of a series or of one occurrence is the operation `event-cancel` for the policy (its group, its grant), the task's key and the channel's rights: the same word, not a new one
    return account_start.start(project, KIND, {"account": account, "operation": operation, **given}, key_words="event-cancel" if operation.startswith("cancel") else f"event-{operation}",
                               title_key=TITLE_KEYS[operation], account=account, channel=channel, sender=sender)


def event_create(project: str, account: str, title: str, start: str, end: str | None = None, calendar: str | None = None, location: str | None = None,
                 reminder_minutes: int | None = None, notes: str | None = None, channel: str | None = None, sender: str | None = None, repeat: str | None = None) -> dict:
    """Prepare a new event and stop at its card. See the module's text."""
    return _start(project, "create", account, {"title": title, "start": start, "end": end, "calendar": calendar, "location": location,
                                               "reminder_minutes": reminder_minutes, "notes": notes, "repeat": repeat}, channel, sender)


def event_change(project: str, account: str, event: str, title: str | None = None, start: str | None = None, end: str | None = None,
                 location: str | None = None, reminder_minutes: int | None = None, notes: str | None = None, channel: str | None = None,
                 sender: str | None = None, calendar: str | None = None) -> dict:
    """Prepare a change to an event and stop at its card (each part as it was and as it will be). See the module's text."""
    return _start(project, "change", account, {"event": event, "calendar": calendar, "title": title, "start": start, "end": end, "location": location,
                                               "reminder_minutes": reminder_minutes, "notes": notes}, channel, sender)


def event_cancel(project: str, account: str, event: str, channel: str | None = None, sender: str | None = None, calendar: str | None = None, series: bool = False,
                 occurrence: str | None = None) -> dict:
    """Prepare the removal of an event, of a whole series or of one occurrence of it, and stop at its card. See the module's text."""
    if series and occurrence is not None:
        raise core.OpsError("give --series (the whole series) or --occurrence (one day's occurrence), not both", 2)
    operation = "cancel-series" if series else "cancel-occurrence" if occurrence is not None else "cancel"
    return _start(project, operation, account, {"event": event, "calendar": calendar, "occurrence": occurrence}, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
