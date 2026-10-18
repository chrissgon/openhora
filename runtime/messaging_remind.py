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
then the operation. The reply (`made`, package NR-1) shows the number, the moment as a person reads it (the relative word, the weekday, the date, the hour and the
zone, in the project's language; a time of day that had passed says so and gives tomorrow's) and `/forget <n>`; the words are repeated only when the project's
notices are `text`. `/reminders` lists the sender's own
and `/forget <n>` cancels one of theirs; both go through the same path. An error of the operations layer reaches the phone as its message unless it is a
problem of this machine or carries a path, which becomes the one fixed sentence of the files (messaging_attach.Attachments.phone).

In the person's own words (package NR-1). A line that code matched to a reminder operation (runtime/natural.py through the intent `natural` of
runtime/messaging_inbound.py; `/remind <rest>` that the strict grammar does not claim is one too) is handled by `natural`: no model, no route lock, no model
slot. The operation `remind` reads the line with the clock (`said`); what is unclear comes back as a question (`ask`), kept as a draft in `self.drafts` for that
chat (memory only: DRAFT_SECONDS, one per chat, lost on a restart, never logged, never in the store), and the next update of the chat goes to `answer`, which finishes
the draft or drops it so that the update is handled as a new one. The calendar is not built: its row answers so and makes no reminder.

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
import natural  # noqa: E402  (the same folder: describes a moment in the project's language; the engine itself runs inside the operation, with its clock)
import phrases  # noqa: E402
import reminders as rm  # noqa: E402

CHANNEL = "messaging"
DRAFT_SECONDS = 600       # a question the bridge asked about a reminder is answered by the next line of that chat for this long, then forgotten
# The English words of why a reminder did not go out, and the phrase-table key of each (runtime/phrases.py, package LR-1: the lines below are said in the project's language).
WHY_KEYS = {"late": "RM_WHY_LATE", "sender removed": "RM_WHY_SENDER_REMOVED", "not permitted": "RM_WHY_NOT_PERMITTED"}
WHY_TEXT = {why: phrases.en(key) for why, key in WHY_KEYS.items()}
NONE_WAIT = phrases.en("RM_NONE_WAIT")


class Reminders:
    """The bridge's reminders: built once with the bridge and calling back into it (`reply`, `run_op`, `log`, `ops`, `projects`, `platform`, `attach`)."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.drafts = {}      # chat -> the question asked about a reminder and what it needs (memory only, one per chat, never logged, never in the store)

    # --- what a sender types ----------------------------------------------------------------------------------------------------------

    def created(self, project: dict, chat: str, intent: dict) -> None:
        """`/remind <time> <text>`."""
        bridge = self.bridge
        try:
            done = bridge.run_op(project, "remind", sender=chat, when=intent["when"], text=intent["text"])
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return
        self.made(project, chat, done)

    def made(self, project: dict, chat: str, done: dict) -> None:
        """The reply to a reminder just made: its number, the moment as a person reads it (the day, the weekday, the date, the hour and the zone; a time of
        day that had passed says so and gives tomorrow's), the words only when the project's notices carry text, and the way to undo it."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        human, reminder = done["human"], done["reminder"]
        when = natural.describe(human, cfg, human["zone"])
        if human["rolled"]:
            when = phrases.text("NT_ROLLED", cfg, time=human["time"], when=when)
        settings = bridge.settings(project)
        if settings is None or settings["notices"] == "text":
            bridge.reply(chat, phrases.text("NT_SET_TEXT", cfg, id=reminder["id"], when=when, text=reminder["text"]), project)
        else:
            bridge.reply(chat, phrases.text("NT_SET_COUNT", cfg, id=reminder["id"], when=when), project)

    # --- the person's own words (package NR-1) ----------------------------------------------------------------------------------------

    def natural(self, project: dict, chat: str, intent: dict) -> bool:
        """A line in the person's own words that code matched to a reminder operation (runtime/natural.py `candidate`): no model, no route lock, no model
        slot. The policy is the operation's own group, as for the typed command. False when the line is not for these operations after all (a line that only
        looks like a request, from a sender who cannot make reminders): the caller then handles it as any plain line."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        op = intent["op"]
        if op == "reminders":
            self.listing(project, chat)
        elif op == "reminder-forget":
            if intent.get("id"):
                self.forget(project, chat, intent["id"])
            elif self.listing(project, chat):
                bridge.reply(chat, phrases.text("NT_WHICH", cfg), project)
        elif op == "calendar-event-create":
            bridge.reply(chat, phrases.text("NT_CALENDAR_NOT_BUILT", cfg), project)
        else:
            if intent["how"] == "bare":
                try:
                    bridge.allow(project, "remind", sender=chat)
                except bridge.Refused:
                    return False
            self.said(project, chat, intent["text"], intent["how"], None)
        return True

    def answer(self, project: dict, chat: str, kind: str, text: str) -> bool:
        """The next update of a chat that has a question open: when it is a plain line that answers it, it is handled here (True); any other update, a command,
        a file or a line that is not an answer, drops the question and is handled as a new one (False). A question older than DRAFT_SECONDS, or asked about
        another project, is already forgotten."""
        bridge = self.bridge
        draft = self.drafts.pop(chat, None)
        if draft is None or kind not in ("text", "natural") or text.lstrip().startswith("/"):
            return False
        if draft["project"] != project["id"] or bridge.monotonic() - draft["at"] > DRAFT_SECONDS:
            return False
        return self.said(project, chat, text, draft["how"], draft)

    def said(self, project: dict, chat: str, text: str, how: str, draft) -> bool:
        """The operation reads `text` with the clock: a reminder made (replied), a question (kept, asked), the calendar chosen (not built yet), or a line that
        does not answer the draft (False). An error of the operation reaches the phone as its message, as for the typed command."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        try:
            done = bridge.run_op(project, "remind", sender=chat, said=text, how=how, draft=draft)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return True
        if done.get("declined"):
            return False
        if done.get("event"):
            bridge.reply(chat, phrases.text("NT_CALENDAR_NOT_BUILT", cfg), project)
        elif "ask" in done:
            self.ask(project, chat, done["ask"], how)
        else:
            self.made(project, chat, done)
        return True

    def ask(self, project: dict, chat: str, draft: dict, how: str) -> None:
        """Ask what is missing, in the project's language, and keep the draft for the next line of this chat. The words of the reminder are repeated
        only when the project's notices carry text."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        need = draft["need"]
        settings = bridge.settings(project)
        with_text = settings is None or settings["notices"] == "text"
        if need == "time":
            if draft.get("day"):
                sentence = phrases.text("NT_ASK_TIME_DAY", cfg, day=natural.capital(natural.describe_day(draft["day"], cfg)))
            else:
                sentence = phrases.text("NT_ASK_WHEN_SLASH" if how == "command" else "NT_ASK_WHEN", cfg)
        elif need == "reading":
            options = f" {phrases.text('NT_OR', cfg)} ".join(natural.describe(r, cfg) for r in draft["readings"])
            sentence = phrases.text("NT_ASK_READINGS", cfg, options=options)
        elif need == "text":
            sentence = phrases.text("NT_ASK_TEXT", cfg)
        else:
            when = natural.capital(natural.describe(draft["readings"][0], cfg))
            sentence = phrases.text("NT_ASK_KIND_TEXT", cfg, when=when, text=draft["text"]) if with_text else phrases.text("NT_ASK_KIND_COUNT", cfg, when=when)
        self.drafts[chat] = {**draft, "project": project["id"], "at": bridge.monotonic()}
        bridge.reply(chat, sentence, project)

    def listing(self, project: dict, chat: str) -> bool:
        """`/reminders`: the sender's own that wait, and the ones that did not go out lately. True when the list was sent."""
        bridge = self.bridge
        try:
            found = bridge.run_op(project, "reminders", sender=chat)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return False
        cfg = bridge.cfg(project)
        lines = [f"#{r['id']} {r['due']}" + (f" {r['text']}" if "text" in r else "") for r in found["open"]]
        gone = [f"#{r['id']} {r['due']}" + (f" {r['text']}" if "text" in r else "") + f" ({phrases.text(WHY_KEYS.get(r.get('why'), 'RM_WHY_OTHER'), cfg)})"
                for r in found["not_sent"]]
        if not lines and not gone:
            bridge.reply(chat, f"{project['name']}: {phrases.text('RM_NONE_WAIT', cfg)}", project)
            return False
        out = [f"{project['name']}: " + (phrases.text("RM_WAITING_HEAD", cfg, zone=found["zone"]) if lines else phrases.text("RM_NONE_WAIT", cfg))] + lines
        if gone:
            out += [phrases.text("RM_NOT_SENT_HEAD", cfg)] + gone
        bridge.reply(chat, "\n".join(out), project)
        return bool(lines)

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
