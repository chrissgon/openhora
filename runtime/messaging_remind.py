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
the draft or drops it so that the update is handled as a new one. A calendar event is a write to the person's own accounts: it opens its card through runtime/ops_natural_writes.py (package NR-5), with the reading the question showed.

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
import drafts  # noqa: E402  (the same folder: the one store of the questions a line leaves open, shared with the operations layer; package NR-2)
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
        # chat -> the question asked about a reminder and what it needs (memory only, one per chat, never logged, never in the store): a view of the one store of drafts
        # (runtime/drafts.py), which the operations layer also keeps its questions in; a new bridge starts with none ("lost on a restart")
        self.drafts = drafts.View("messaging", "remind", lambda chat: f"{bridge.platform}:{chat}",
                                  lambda sender: sender[len(bridge.platform) + 1:] if sender.startswith(f"{bridge.platform}:") else None)
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
        settings = bridge.settings(project)
        bridge.reply(chat, natural.made_sentence(done, bridge.cfg(project), settings is None or settings["notices"] == "text"), project)

    # --- the person's own words (package NR-1) ----------------------------------------------------------------------------------------

    def natural(self, project: dict, chat: str, intent: dict) -> bool:
        """`/remind <free words>`, the one intent of kind `natural` left (messaging_inbound.parse): the operation `remind` reads the words with the clock; no model, no route lock, no model
        slot. The policy is the operation's own group, as for the typed command. Always True. (The branches of the other operations, the question "an event or something else" and its draft `eventorother`
        were unreachable once CANDIDATE-OUT 2 left this intent as the only producer, and 44-B 3b deleted them with the methods only they called.)"""
        self.said(project, chat, intent["text"], intent["how"], None)
        return True

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

    def shared(self, chat: str):
        """The question the interpreter's carry-out left for this chat in the store of drafts (S41-11), or None. Its owner is `remind`; the bridge holds no copy."""
        return drafts.get("messaging", self.bridge.key(chat), "remind")

    def ask_yes_shared(self, project: dict, chat: str, sentence: str) -> bool:
        """Send the question of the shared draft with the one-tap Yes button and bind the message to it (review C2-d). False when the platform has no buttons or the send failed: the plain question goes."""
        bridge = self.bridge
        draft = self.shared(chat)
        if draft is None or draft.get("need") not in ("confirm", "forget"):
            return False
        bridge.last_message.pop(chat, None)
        if not bridge.ask_yes(project, chat, sentence):
            return False
        draft["message_id"] = bridge.last_message.get(chat)
        return True

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
        elif done.get("event"):          # the kind question answered "event": the event is opened with the reading the question SHOWED and its words (NR-5)
            seed = {"op": "event-create"}
            if done.get("reading"):
                seed.update(reading=done["reading"], text=done.get("text") or "", origins={"start": "time-engine", "title": "line-span"})          # S41-7: the time is the engine's reading the question showed, the title the person's own words
            bridge.write(project, chat, done.get("line") or text, seed)
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
        settings = bridge.settings(project)
        sentence, keep = natural.question(draft, bridge.cfg(project), settings is None or settings["notices"] == "text", how)          # the words of every question: runtime/natural.py
        if not keep:
            bridge.reply(chat, sentence, project)          # said, and nothing is kept: a repetition is a routine's, not a reminder's
            return
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

    def forgot(self, project: dict, chat: str, done: dict) -> None:
        """The reply to a reminder just cancelled: what it was (its moment and, in text mode, its words) and how to get it back."""
        bridge = self.bridge
        settings = bridge.settings(project)
        bridge.reply(chat, natural.forgot_sentence(done, bridge.cfg(project), settings is None or settings["notices"] == "text"), project)

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
                    with bridge.sentences_for(item["chat"], project):      # TT-2: the reminder is said in the language of the sender it is for
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
