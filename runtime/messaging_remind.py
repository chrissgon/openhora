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
slot. The operation `remind` reads the line with the clock (`said`) and never makes a reminder from free text at once: the reading comes back as a question (`ask`: the confirmation, with a one-tap Yes button where the platform has buttons, `Bridge.ask_yes`, and `tapped` for the tap), and so does whatever is unclear; the question is kept as a draft in `self.drafts` for that
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

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural  # noqa: E402  (the same folder: describes a moment in the project's language; the engine itself runs inside the operation, with its clock)
import phrases  # noqa: E402
import reminders as rm  # noqa: E402

CHANNEL = "messaging"
DRAFT_SECONDS = 600       # a question the bridge asked about a reminder is answered by the next line of that chat for this long, then forgotten
EXPIRED_SECONDS = 1800    # a "yes" this long after a question expired is told that the question expired (only that a question was open is remembered, never what it said)
# The English words of why a reminder did not go out, and the phrase-table key of each (runtime/phrases.py, package LR-1: the lines below are said in the project's language).
WHY_KEYS = {"late": "RM_WHY_LATE", "sender removed": "RM_WHY_SENDER_REMOVED", "not permitted": "RM_WHY_NOT_PERMITTED"}
WHY_TEXT = {why: phrases.en(key) for why, key in WHY_KEYS.items()}
NONE_WAIT = phrases.en("RM_NONE_WAIT")


class Reminders:
    """The bridge's reminders: built once with the bridge and calling back into it (`reply`, `run_op`, `log`, `ops`, `projects`, `platform`, `attach`)."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.drafts = {}      # chat -> the question asked about a reminder and what it needs (memory only, one per chat, never logged, never in the store)
        self.expired = {}     # chat -> when its question expired (memory only: no words), so that a late "yes" is told so
        self.discarded = set()      # chats whose open question the line being handled just replaced (cleared at the start of every update)

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
            if intent.get("bare"):          # "cancela #3", "cancela o 3": no noun, so a sender with no such reminder (or no such group) has a plain line
                try:
                    bridge.allow(project, "reminder-forget", sender=chat)
                    bridge.run_op(project, "reminder-forget", sender=chat, reminder_id=intent["id"], preview=True)
                except (bridge.Refused, bridge.ops.OpsError):
                    return False
                self.forget_confirm(project, chat, [intent["id"]])
            elif intent.get("ids") or (intent.get("id") and intent.get("confirm")):
                self.forget_confirm(project, chat, intent.get("ids") or [intent["id"]])
            elif intent.get("at"):
                self.forget_at(project, chat, intent["at"])
            elif intent.get("id"):
                self.forget(project, chat, intent["id"])
            elif intent.get("words"):
                self.forget_words(project, chat, intent["words"])
            elif self.listing(project, chat):
                bridge.reply(chat, phrases.text("NT_WHICH", cfg), project)
        elif op == "reminder-restore":
            try:
                bridge.allow(project, "reminder-restore", sender=chat)
            except bridge.Refused:
                return False          # "undo" may mean anything: for a sender who cannot make reminders it is a plain line
            return self.restore(project, chat)
        elif op == "calendar-event-create":
            if intent.get("how") == "ask":
                self.ask_event(project, chat, intent["text"])
            else:
                self.not_built(project, chat)
        else:
            if intent["how"] in ("bare", "note"):
                try:
                    bridge.allow(project, "remind", sender=chat)
                except bridge.Refused:
                    return False
            self.said(project, chat, intent["text"], intent["how"], None)
        return True

    def not_built(self, project: dict, chat: str) -> None:
        """The calendar is not built: say so in the project's language, after the policy of a plain line (a sender who may not talk is refused as for any line)."""
        bridge = self.bridge
        try:
            bridge.allow(project, "say", sender=chat)
        except bridge.Refused as e:
            bridge.reply(chat, str(e), project)
            return
        bridge.reply(chat, phrases.text("NT_CALENDAR_NOT_BUILT", bridge.cfg(project)), project)

    def ask_event(self, project: dict, chat: str, line: str, retries: int = 0) -> None:
        """A scheduling verb with a time and no calendar word: ask whether it is an event or something else, and keep the line (memory only) so that
        "something else" can send it on to the planning agent."""
        bridge = self.bridge
        try:
            bridge.allow(project, "say", sender=chat)
        except bridge.Refused as e:
            bridge.reply(chat, str(e), project)
            return
        self.question(project, chat, phrases.text("NT_ASK_EVENT_OR_OTHER", bridge.cfg(project)), {**natural._draft("eventorother", "ask", line, ""), "retries": retries})

    def question(self, project: dict, chat: str, sentence: str, draft: dict) -> None:
        """Send a question and keep its draft for the next line of the chat (memory only). A question that replaces one still open says so. A question that is answered
        by a "yes" (the confirmation of a reading, the cancel of a reminder) carries a one-tap "Yes" button where the platform has buttons; the typed "yes" works everywhere."""
        bridge = self.bridge
        if chat in self.discarded:
            self.discarded.discard(chat)
            sentence = phrases.text("NT_DISCARDED", bridge.cfg(project)) + " " + sentence
        bridge.last_message.pop(chat, None)
        if not (draft["need"] in ("confirm", "forget") and bridge.ask_yes(project, chat, sentence)):
            bridge.reply(chat, sentence, project)
        self.drafts[chat] = {**draft, "project": project["id"], "at": bridge.monotonic(), "message_id": bridge.last_message.get(chat)}

    def tapped(self, project: dict, chat: str, card: dict) -> None:
        """A tap on the "Yes" button of a question about a reminder: the same as the typed "yes", for the question the button belongs to. A button of a question that is
        no longer the open one (answered, replaced, expired, lost on a restart) is told so."""
        bridge = self.bridge
        draft = self.drafts.get(chat)
        asked, pressed = str(draft.get("message_id") or "") if draft else "", str(card.get("message_id") or "")
        if draft is None or draft["project"] != project["id"] or not asked or not pressed or asked != pressed:          # a button is the answer to ITS question, and a question with no id cannot be told from another
            bridge.reply(chat, phrases.text("NT_EXPIRED", bridge.cfg(project)), project)
            return
        if bridge.monotonic() - draft["at"] > DRAFT_SECONDS:
            self.drafts.pop(chat, None)
            self.expired[chat] = draft["at"] + DRAFT_SECONDS
            bridge.reply(chat, phrases.text("NT_EXPIRED", bridge.cfg(project)), project)
            return
        self.drafts.pop(chat, None)
        self.said(project, chat, "yes", draft["how"], draft)

    def sweep(self) -> None:
        """Forget the questions older than DRAFT_SECONDS: the person's words leave memory when the time is up, not only when the chat writes again. Only the fact that
        a question expired is kept, for EXPIRED_SECONDS, so that a "yes" that comes too late is told so."""
        now = self.bridge.monotonic()
        for chat in [c for c, d in self.drafts.items() if now - d["at"] > DRAFT_SECONDS]:
            del self.drafts[chat]
            self.expired[chat] = now
        for chat in [c for c, at in self.expired.items() if now - at > EXPIRED_SECONDS]:
            del self.expired[chat]

    def late(self, project: dict, chat: str, kind: str, text: str) -> bool:
        """The first line of a chat after its question expired: when it is a plain "yes" it is told that the question is no longer open (True); any other line is
        handled as a new one, and the memory of the expired question goes either way."""
        at = self.expired.pop(chat, None)
        if at is None or kind not in ("text", "natural", "reply") or self.bridge.monotonic() - at > EXPIRED_SECONDS or not natural.affirm(text):
            return False
        self.bridge.reply(chat, phrases.text("NT_EXPIRED", self.bridge.cfg(project)), project)
        return True

    def answer(self, project: dict, chat: str, kind: str, text: str, reply_to=None) -> bool:
        """The next update of a chat that has a question open: when it is a plain line (or a reply gesture) that answers it, it is handled here (True); any other
        update, a command, a file or a line that is not an answer, drops the question and is handled as a new one (False). A question older than DRAFT_SECONDS,
        or asked about another project, is already forgotten."""
        bridge = self.bridge
        draft = self.drafts.pop(chat, None)
        if draft is None:
            return False
        if draft["project"] != project["id"] or bridge.monotonic() - draft["at"] > DRAFT_SECONDS:
            self.expired[chat] = draft["at"] + DRAFT_SECONDS
            return self.late(project, chat, kind, text) if draft["project"] == project["id"] else False
        if self.finish(project, chat, draft, kind, text, reply_to):
            return True
        self.discarded.add(chat)          # the line does not answer the question: a question it asks says the previous one was discarded
        return False

    def finish(self, project: dict, chat: str, draft: dict, kind: str, text: str, reply_to) -> bool:
        """Whether `text` answers `draft` (it then has been handled)."""
        bridge = self.bridge
        if kind not in ("text", "natural", "reply") or text.lstrip().startswith("/"):
            return False
        if reply_to and reply_to != draft.get("message_id"):          # a reply to another message is not the answer to this question
            return False
        if draft["need"] == "eventorother":
            chosen = natural.answer_kind(text)
            if chosen is None and draft.get("retries", 0) < 1 and natural.short_answer(text):
                self.ask_event(project, chat, draft["line"], retries=1)          # a short reply that is neither: asked once more
                return True
            if chosen == "event":
                self.not_built(project, chat)
            elif chosen == "other":
                bridge.say(project, chat, draft["line"])
            elif chosen == "notice":
                self.said(project, chat, draft["line"], "trigger", None)
            return chosen is not None
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
        if done.get("cancel"):
            bridge.reply(chat, phrases.text("NT_KEPT" if done.get("kept") else "NT_CANCELLED", cfg), project)
        elif done.get("event"):
            bridge.reply(chat, phrases.text("NT_CALENDAR_NOT_BUILT", cfg), project)
        elif done.get("forget"):
            for number in done["forget"]:
                self.forget(project, chat, number)
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
        if need == "recurring":
            bridge.reply(chat, phrases.text("NT_RECURRING", cfg), project)          # said, and nothing is kept: a repetition is a routine's, not a reminder's
            return
        if need == "confirm":
            when = natural.describe(draft["readings"][0], cfg)
            if draft["readings"][0].get("rolled"):          # "this morning at 9" said in the afternoon: tomorrow's is shown as such
                when = phrases.text("NT_ROLLED", cfg, time=draft["readings"][0]["time"], when=when)
            sentence = phrases.text("NT_CONFIRM_TEXT", cfg, when=when, text=draft["text"]) if with_text else phrases.text("NT_CONFIRM_COUNT", cfg, when=when)
        elif need == "time":
            if draft.get("day"):
                sentence = phrases.text("NT_ASK_TIME_DAY", cfg, day=natural.capital(natural.describe_day(draft["day"], cfg)))
            elif how == "note":
                sentence = phrases.text("NT_ASK_NOTE", cfg)
            else:
                sentence = phrases.text("NT_ASK_WHEN_SLASH" if how == "command" else "NT_ASK_WHEN", cfg)
        elif need == "reading":
            options = f" {phrases.text('NT_OR', cfg)} ".join(natural.describe(r, cfg) for r in draft["readings"])
            sentence = phrases.text("NT_ASK_READINGS", cfg, options=options)
        elif need == "text":
            sentence = phrases.text("NT_ASK_TEXT", cfg)
        elif need == "again":
            sentence = phrases.text("NT_ASK_AGAIN", cfg)
        elif need == "weekday":
            sentence = phrases.text("NT_ASK_WEEKDAY", cfg)
        elif need == "forget":
            sentence = draft["sentence"]
        else:
            when = natural.capital(natural.describe(draft["readings"][0], cfg))
            sentence = phrases.text("NT_ASK_KIND_TEXT", cfg, when=when, text=draft["text"]) if with_text else phrases.text("NT_ASK_KIND_COUNT", cfg, when=when)
        self.question(project, chat, sentence, draft)

    def listing(self, project: dict, chat: str) -> bool:
        """`/reminders`: the sender's own that wait, and the ones that did not go out lately, each with its moment as a person reads it, in the project's
        language. True when the list was sent."""
        bridge = self.bridge
        try:
            found = bridge.run_op(project, "reminders", sender=chat)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return False
        cfg = bridge.cfg(project)
        today = datetime.date.fromisoformat(found["now"][:10])

        def line(r):
            when = natural.describe(natural.info_of(r["due"][:10], r["due"][11:16], today), cfg)
            return f"#{r['id']} {when}" + (f": {r['text']}" if "text" in r else "")
        lines = [line(r) for r in found["open"]]
        gone = [line(r) + f" ({phrases.text(WHY_KEYS.get(r.get('why'), 'RM_WHY_OTHER'), cfg)})" for r in found["not_sent"]]
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
        self.forgot(project, chat, done)

    def forget_confirm(self, project: dict, chat: str, numbers: list) -> None:
        """"Cancel reminder of 3", "cancel reminders 1 and 2": a number that is not written as an explicit id is shown with what it names, and cancelled only on a
        "yes". Each reminder is checked under the sender's own policy (a number that is not theirs is answered as one that does not exist)."""
        bridge = self.bridge
        shown = []
        for number in numbers:
            try:
                shown.append(bridge.run_op(project, "reminder-forget", sender=chat, reminder_id=number, preview=True))
            except (bridge.Refused, bridge.ops.OpsError) as e:
                bridge.reply(chat, bridge.attach.phone(e, project), project)
                return
        self.ask_forget(project, chat, shown)

    def forget_at(self, project: dict, chat: str, at: str) -> None:
        """"Cancel the 9 o'clock reminder": the sender's reminders due at that hour; the one found is shown and confirmed, several are listed and asked, none is said."""
        bridge = self.bridge
        try:
            done = bridge.run_op(project, "reminder-forget", sender=chat, at=at)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return
        if done.get("none"):
            bridge.reply(chat, phrases.text("NT_NO_MATCH", bridge.cfg(project)), project)
        elif done.get("choose"):
            if self.listing(project, chat):
                bridge.reply(chat, phrases.text("NT_WHICH", bridge.cfg(project)), project)
        else:
            self.ask_forget(project, chat, [done])

    def ask_forget(self, project: dict, chat: str, shown: list) -> None:
        """Ask "cancel it?" with what would be cancelled (its moment and, in text mode, its words), and keep the numbers for the answer."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        settings = bridge.settings(project)
        with_text = settings is None or settings["notices"] == "text"

        def one(done):
            when = natural.describe(done["human"], cfg, done["human"]["zone"])
            row = done["preview"]
            return f"#{row['id']} {when}" + (f": {row['text']}" if "text" in row and with_text else "")
        numbers = [done["preview"]["id"] for done in shown]
        if len(shown) == 1:
            row, when = shown[0]["preview"], natural.describe(shown[0]["human"], cfg, shown[0]["human"]["zone"])
            if "text" in row and with_text:
                sentence = phrases.text("NT_ASK_FORGET_TEXT", cfg, id=row["id"], when=when, text=row["text"])
            else:
                sentence = phrases.text("NT_ASK_FORGET_COUNT", cfg, id=row["id"], when=when)
        else:
            sentence = "\n".join([phrases.text("NT_ASK_FORGET_MANY", cfg)] + [one(done) for done in shown])
        self.question(project, chat, sentence, {**natural._draft("forget", "trigger", "", ""), "ids": numbers, "sentence": sentence})

    def forgot(self, project: dict, chat: str, done: dict) -> None:
        """The reply to a reminder just cancelled: what it was (its moment and, in text mode, its words) and how to get it back."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        human, row = done["human"], done["reminder"]
        when = natural.describe(human, cfg, human["zone"])
        settings = bridge.settings(project)
        if "text" in row and (settings is None or settings["notices"] == "text"):
            bridge.reply(chat, phrases.text("NT_FORGOT_TEXT", cfg, id=row["id"], when=when, text=row["text"]), project)
        else:
            bridge.reply(chat, phrases.text("NT_FORGOT_COUNT", cfg, id=row["id"], when=when), project)

    def restore(self, project: dict, chat: str) -> bool:
        """"Undo": the last reminder this sender cancelled in the last ten minutes comes back as a new one. False when there is none (the line is then a plain line)."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        try:
            done = bridge.run_op(project, "reminder-restore", sender=chat)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return True
        if done.get("none"):
            return False
        human, row = done["human"], done["reminder"]
        when = natural.describe(human, cfg, human["zone"])
        settings = bridge.settings(project)
        if "text" in row and (settings is None or settings["notices"] == "text"):
            bridge.reply(chat, phrases.text("NT_RESTORED_TEXT", cfg, old=done["restored"], id=row["id"], when=when, text=row["text"]), project)
        else:
            bridge.reply(chat, phrases.text("NT_RESTORED_COUNT", cfg, old=done["restored"], id=row["id"], when=when), project)
        return True

    def forget_words(self, project: dict, chat: str, words: list) -> None:
        """"Cancel the florist reminder": the one waiting reminder of the sender that holds those words is forgotten and said (what it was, so a mistake shows);
        when several hold them the list is sent and the number asked; when none does, the sender is told so and the line goes nowhere."""
        bridge = self.bridge
        cfg = bridge.cfg(project)
        try:
            done = bridge.run_op(project, "reminder-forget", sender=chat, matching=words)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, bridge.attach.phone(e, project), project)
            return
        if done.get("none"):
            bridge.reply(chat, phrases.text("NT_NO_MATCH", cfg), project)
        elif done.get("choose"):
            if self.listing(project, chat):
                bridge.reply(chat, phrases.text("NT_WHICH", cfg), project)
        elif done.get("preview"):
            self.ask_forget(project, chat, [done])
        else:
            self.forgot(project, chat, done)

    # --- what is due ------------------------------------------------------------------------------------------------------------------

    def deliver(self) -> None:
        """Send the reminders that are due, for every served project (see the module's text). Nothing here ends the bridge: a project that cannot be read
        (an error of the operations layer, or the store's own, such as a locked database) and a reminder that cannot be sent or marked are logged by the
        class of the error alone, and the next tick tries again (as `Bridge.handle_safely` does for an update)."""
        bridge = self.bridge
        self.sweep()
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
