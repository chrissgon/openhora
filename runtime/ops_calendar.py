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

  event_create(project, account, title, start[, end, calendar, location, reminder_minutes, notes])
        a new event on a calendar of the account (the first one the project lists when `calendar` is absent); nobody is invited; no recurrence
  event_change(project, account, event[, title, start, end, location, reminder_minutes, notes, calendar])
        change parts of an event you organize with no other attendee and no recurrence; `event` is a reference: `<source>#<n>` (the n-th item of a calendar
        snapshot, once the index of the snapshots is in the checkout) or `created:<decision>` (an event this runtime created). The calendar is the one the
        reference puts the event on (it must be one the project's `accounts` lists); `calendar` names it when the person wants to be sure, and a different one is refused
  event_cancel(project, account, event[, calendar])
        remove such an event: Google is expected to send it to the calendar's trash (30 days; to verify live); on Outlook this is not available yet

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

KIND = "calendar-event"


def _start(project, operation: str, account, args: dict, channel, sender) -> dict:
    """The one start of the family: the arguments the call gave (those that are not None), under the operation's name and the title of its card."""
    given = {k: v for k, v in args.items() if v is not None}
    if "event" in given:      # a reference into a snapshot is usable only by a caller who may read it (item_refs.may_read): the step asks with the caller's own channel and sender
        given.update({k: v for k, v in (("channel", channel if channel in ("terminal", "page", "messaging") else None), ("sender", sender if channel == "messaging" else None))
                      if v is not None})
    title_key = {"create": "TITLE_CAL_CREATE", "change": "TITLE_CAL_CHANGE", "cancel": "TITLE_CAL_CANCEL"}[operation]
    return account_start.start(project, KIND, {"account": account, "operation": operation, **given}, key_words=f"event-{operation}", title_key=title_key,
                               account=account, channel=channel, sender=sender)


def event_create(project: str, account: str, title: str, start: str, end: str | None = None, calendar: str | None = None, location: str | None = None,
                 reminder_minutes: int | None = None, notes: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare a new event and stop at its card. See the module's text."""
    return _start(project, "create", account, {"title": title, "start": start, "end": end, "calendar": calendar, "location": location,
                                               "reminder_minutes": reminder_minutes, "notes": notes}, channel, sender)


def event_change(project: str, account: str, event: str, title: str | None = None, start: str | None = None, end: str | None = None,
                 location: str | None = None, reminder_minutes: int | None = None, notes: str | None = None, channel: str | None = None,
                 sender: str | None = None, calendar: str | None = None) -> dict:
    """Prepare a change to an event and stop at its card (each part as it was and as it will be). See the module's text."""
    return _start(project, "change", account, {"event": event, "calendar": calendar, "title": title, "start": start, "end": end, "location": location,
                                               "reminder_minutes": reminder_minutes, "notes": notes}, channel, sender)


def event_cancel(project: str, account: str, event: str, channel: str | None = None, sender: str | None = None, calendar: str | None = None) -> dict:
    """Prepare the removal of an event and stop at its card. See the module's text."""
    return _start(project, "cancel", account, {"event": event, "calendar": calendar}, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
