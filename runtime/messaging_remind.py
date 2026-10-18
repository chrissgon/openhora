#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's part of reminders (package RM-1): `/remind`, `/reminders` and `/forget` from a listed sender, and the delivery of the reminders
that are due. The bridge (runtime/messaging_bridge.py) dispatches to it in four places and holds nothing of it; the words and the caps are
runtime/reminders.py, the operations and the claim of a due reminder are runtime/ops_reminders.py.

A reminder is a notice and never an effect (limit L51, contracts/runtime.md): it goes only to the private chat of the sender who made it (or whom the
terminal named), with that person's own words, and nothing is done in the world.

From a sender. `/remind <time> <text>` is parsed with no model (runtime/messaging_inbound.py splits the line, the operation reads the time against the
machine's clock) and goes through the one call path (`Bridge.run_op`): the policy of THIS sender first (the group `reminders`, in no default policy),
then the operation. The reply is a fixed sentence: the number, the day and the time, never the words the sender typed. `/reminders` lists the sender's own
and `/forget <n>` cancels one of theirs; both go through the same path. An error of the operations layer reaches the phone as its message unless it is a
problem of this machine or carries a path, which becomes the one fixed sentence of the files (messaging_attach.Attachments.phone).

Delivery. Each tick (`deliver`, after the cards and before the line about unread messages), per served project: the operation `reminders_due` claims the
reminders of this platform that are due, ends the ones later than the late window `missed` and the ones whose sender was removed or lost the group
`dropped` (the configuration is read then, not when the reminder was made), and returns what goes out (the text only when the project's notices carry
text). Each one is sent to its own chat through `Bridge.reply`, then marked `sent`; a send that failed or was deferred is marked open again and tried
again after a pause of 1, 2, 4, 8 ... minutes (not at every tick), until the late window ends it `missed`. A bridge that stops between the send and the
mark, and a mark that fails after a send that went out (logged by its class), both leave the reminder `sending`; it is open again after CLAIM_STALE
seconds, so a line may go twice and never zero times. The text of a reminder is never logged: the log has the class of an error and
the number of reminders, nothing else.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402
import reminders as rm  # noqa: E402

CHANNEL = "messaging"
# The English words of why a reminder did not go out, and the phrase-table key of each (runtime/phrases.py, package LR-1: the lines below are said in the project's language).
WHY_KEYS = {"late": "RM_WHY_LATE", "sender removed": "RM_WHY_SENDER_REMOVED", "not permitted": "RM_WHY_NOT_PERMITTED"}
WHY_TEXT = {why: phrases.en(key) for why, key in WHY_KEYS.items()}
NONE_WAIT = phrases.en("RM_NONE_WAIT")


class Reminders:
    """The bridge's reminders: built once with the bridge and calling back into it (`reply`, `run_op`, `log`, `ops`, `projects`, `platform`, `attach`)."""

    def __init__(self, bridge):
        self.bridge = bridge

    # --- what a sender types ----------------------------------------------------------------------------------------------------------

    def created(self, project: dict, chat: str, intent: dict) -> None:
        """`/remind <time> <text>`."""
        bridge = self.bridge
        try:
            done = bridge.run_op(project, "remind", sender=chat, when=intent["when"], text=intent["text"])
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return
        bridge.reply(chat, phrases.localize(done["reply"], bridge.cfg(project)), project)

    def listing(self, project: dict, chat: str) -> None:
        """`/reminders`: the sender's own that wait, and the ones that did not go out lately."""
        bridge = self.bridge
        try:
            found = bridge.run_op(project, "reminders", sender=chat)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return
        cfg = bridge.cfg(project)
        lines = [f"#{r['id']} {r['due']}" + (f" {r['text']}" if "text" in r else "") for r in found["open"]]
        gone = [f"#{r['id']} {r['due']}" + (f" {r['text']}" if "text" in r else "") + f" ({phrases.text(WHY_KEYS.get(r.get('why'), 'RM_WHY_OTHER'), cfg)})"
                for r in found["not_sent"]]
        if not lines and not gone:
            bridge.reply(chat, f"{project['name']}: {phrases.text('RM_NONE_WAIT', cfg)}", project)
            return
        out = [f"{project['name']}: " + (phrases.text("RM_WAITING_HEAD", cfg, zone=found["zone"]) if lines else phrases.text("RM_NONE_WAIT", cfg))] + lines
        if gone:
            out += [phrases.text("RM_NOT_SENT_HEAD", cfg)] + gone
        bridge.reply(chat, "\n".join(out), project)

    def forget(self, project: dict, chat: str, number: int) -> None:
        """`/forget <n>`."""
        bridge = self.bridge
        try:
            done = bridge.run_op(project, "reminder-forget", sender=chat, reminder_id=number)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return
        bridge.reply(chat, phrases.localize(done["reply"], bridge.cfg(project)), project)

    # --- what is due ------------------------------------------------------------------------------------------------------------------

    def deliver(self) -> None:
        """Send the reminders that are due, for every served project (see the module's text). Nothing here ends the bridge: a project that cannot be read
        (an error of the operations layer, or the store's own, such as a locked database) and a reminder that cannot be sent or marked are logged by the
        class of the error alone, and the next tick tries again (as `Bridge.handle_safely` does for an update)."""
        bridge = self.bridge
        for project in bridge.projects:
            try:
                due = bridge.ops.reminders_due(project["path"], bridge.platform)
            except Exception as e:
                bridge.log(f"reminders could not be read ({e.__class__.__name__})")
                continue
            if due["missed"] or due["dropped"]:
                bridge.log(f"reminders not sent: {due['missed']} missed, {due['dropped']} dropped")
            for item in due["send"]:
                try:
                    line = rm.line(item["id"], item.get("text"), item["due_local"], item["late"], bridge.cfg(project))
                    sent = bridge.reply(item["chat"], line)      # True: went out; False: the send failed (logged by `reply`); None: the platform deferred it
                except Exception as e:
                    bridge.log(f"a reminder could not be sent ({e.__class__.__name__})")      # it stays claimed and is open again when the claim goes stale
                    continue
                try:
                    if sent is True:
                        bridge.ops.reminders_sent(project["path"], item["id"])
                    else:
                        bridge.ops.reminders_retry(project["path"], item["id"])
                except Exception as e:
                    bridge.log(f"a reminder could not be marked ({e.__class__.__name__})")
