#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's part of the files a listed sender sends (package ATT-1b): from the update to the fetch, the hold, the card or the reply, and from the
card's answer to the add or the discard. The bridge (runtime/messaging_bridge.py) dispatches to it in three places and holds nothing of it; the limits, the
sentences and the folders are runtime/attachments.py, the operations are runtime/ops_attachments.py.

The order, for the files of one message, each step before the next and nothing fetched before the policy said yes:

  1. the provider declared `attachments` (else "This app's connection does not take files yet.");
  2. the policy: THIS sender's profile permits `attachment-hold` (the group `add-sources`, or the grant `add-sources-direct`), else the reply is the OFF sentence and
     nothing is fetched (one log line, no id);
  3. what the platform declared, before a byte: at most PER_MESSAGE files, no photo, voice note, video, audio or sticker, no declared size over the cap, the day's
     count and bytes, the held ceiling, a file already held (attachments.precheck, from the `attachments` read: outside the policy, like `pending`);
  4. one fetch at a time per project (the upload lock the page's uploads share), into an incoming folder the bridge made, by the reference the provider handed over
     and nothing else, at most the day's bytes left; the provider's answer is checked against the file it left;
  5. `attachment-hold`, through the one call path (`Bridge.run_op`): the operation checks the profile again, bounds and sniffs the file, records it and keeps it;
  6. a card (Add, Discard) bound in the ledger to the file's hash, its target and its label; or, with the grant `add-sources-direct`, the add at once.

The whole of 3 to 6 runs in the bridge's job thread, so that polling and the other chats go on. A tap or a typed `/add <n>` binds to the newest card of that file in
the chat, checks the sender's profile and the card's hash against the file as it is now, and runs the add (a job: the conversion takes seconds) or the discard.
The caption of a file is never a line to the planner and never echoed; the name is cleaned and cut (attachments.clean_name); nothing of the file's content is in a reply.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import attachments as att  # noqa: E402
import messaging_cards as cards  # noqa: E402
import messaging_provider as provider  # noqa: E402
import phrases  # noqa: E402

CHANNEL = "messaging"
CHANGED = phrases.en("CHANGED")
WORDS = {"add": "attachment-add", "discard": "attachment-discard"}
PATH = re.compile(r"(?<![\w:.-])(?:~|[A-Za-z]:)?/[\w.~-]+/|[A-Za-z]:\\|(?<!\w)~/")      # a folder of this machine in a sentence: `/a/b`, `~/b`, `C:\`


class Attachments:
    """The bridge's files: built once with the bridge and calling back into it (`reply`, `run_op`, `settings`, `start`, `deliver`, `ledger`)."""

    def __init__(self, bridge):
        self.bridge = bridge

    def phone(self, error, project=None) -> str:
        """What a phone is told of an error of the operations layer: its message, unless the message is a problem of this machine (an operation's `phone`
        sentence, a code of a folder, or any path in the text), which becomes a fixed sentence; the class alone is logged. A sentence of a file or of a reminder
        (the operations raise them in English) is said in the project's language (phrases.localize); any other message is the operations layer's own and stays."""
        cfg = self.bridge.cfg(project)
        said = getattr(error, "phone", None)
        if said:
            self.bridge.log(f"a machine problem was told to a phone ({error.__class__.__name__})")
            return phrases.localize(said, cfg)
        text = str(error)
        if PATH.search(text) or getattr(error, "code", 1) == 3:
            self.bridge.log(f"a machine problem was told to a phone ({error.__class__.__name__})")
            return phrases.text("ATT_MACHINE", cfg)
        return phrases.localize(text, cfg)

    def said(self, text: str, project) -> str:
        """The reply of an operation that adds or discards a file (one sentence, then a `Note:` line for each warning of the import) in the project's language."""
        cfg = self.bridge.cfg(project)
        return "\n".join(phrases.localize(line, cfg) for line in str(text).split("\n"))

    # --- what arrives ------------------------------------------------------------------------------------------------------------

    def arrived(self, project: dict, chat: str, intent: dict) -> None:
        """Steps 1 to 3 on the bridge's thread (nothing is fetched here), then the fetches in a job."""
        bridge = self.bridge
        caps = bridge.messenger.capabilities()
        if not caps.get("attachments"):
            bridge.reply(chat, bridge.t("ATT_NO_FILES", project=project), project)
            return
        settings = bridge.settings(project)
        if settings is None:
            bridge.reply(chat, bridge.t("NOT_ACCEPTED", project=project), project)
            return
        operations = bridge.ops.operations
        key = bridge.key(chat)
        if not operations.permitted("attachment-hold", CHANNEL, settings["policy"], None, key):
            bridge.log("a file was not fetched: the channel's policy takes none")
            bridge.reply(chat, bridge.t("ATT_OFF", cfg=settings), project)
            return
        direct = operations.granted("attachment-hold", CHANNEL, settings["policy"], "direct", key)
        files = intent["attachments"]
        target, ignored = att.caption_target(intent.get("text"), len(files))
        cap = min(att.FILE_CAP, caps.get("max_attachment_bytes") or att.FILE_CAP)
        try:
            held = bridge.ops.attachments(project["path"])
        except bridge.ops.OpsError as e:
            bridge.reply(chat, self.phone(e, project), project)
            return
        lines, todo, over = [], [], False
        for decision in att.precheck(files, cap=cap, today=held["today"], held=held["held"], platform=bridge.platform, sender=chat):
            file = decision["attachment"]
            if decision["over"]:
                over = True
            elif decision["duplicate"] is not None:
                if decision["duplicate"]["id"] is not None:        # (the same reference twice in one message is one file, said nothing of)
                    lines.append(bridge.t("ATT_DUPLICATE", cfg=settings, name=att.clean_name(file.get("name"), bridge.t("FILE_WORD", cfg=settings)), id=decision["duplicate"]["id"]))
            elif decision["refuse"] is not None:
                lines.append(att.refusal_text(decision["refuse"], file, bridge.platform, cap, settings))
            else:
                todo.append(file)
        if over:
            lines.append(bridge.t("ATT_OVER_MESSAGE", cfg=settings, n=att.PER_MESSAGE))
        if ignored:
            lines.append(bridge.t("ATT_CAPTION_IGNORED", cfg=settings))
        if lines:
            bridge.reply(chat, "\n".join(dict.fromkeys(lines)), project)
        if todo:
            bridge.start(project, chat, "attachment-hold", lambda: self.fetch_all(project, chat, todo, target, direct, cap))

    # --- the fetches, in a job -------------------------------------------------------------------------------------------------------

    def fetch_all(self, project: dict, chat: str, files: list, target, direct: bool, cap: int) -> None:
        for file in files:
            try:
                if self.fetch_one(project, chat, file, target, direct, cap) == "busy":
                    return       # another fetch holds the lock: the person was told once, and the rest of the message is not asked for
            except Exception as e:       # one file never takes the job down, and the class is all that is logged
                self.bridge.log(f"a file could not be taken ({e.__class__.__name__})")
                self.bridge.reply(chat, self.bridge.t("ATT_FETCH_FAILED", project=project), project)

    def fetch_one(self, project: dict, chat: str, file: dict, target, direct: bool, cap: int):
        """One file of the message: fetched, checked and held. Returns "busy" when the lock was taken by another fetch (nothing was fetched)."""
        bridge = self.bridge
        data_dir = bridge.ops.config(project["path"])["data_dir"]
        try:
            token, folder = att.make_incoming(data_dir)
        except att.FolderError:
            bridge.log("the folder of a fetch could not be made")
            bridge.reply(chat, bridge.t("ATT_FETCH_FAILED", project=project), project)
            return
        try:
            try:
                lock = att.fetch_lock(data_dir)
            except att.FetchBusy:
                bridge.reply(chat, bridge.t("ATT_BUSY", project=project), project)
                return "busy"
            try:
                today = bridge.ops.attachments(project["path"])["today"]
                if today["files"] >= att.DAY_FILES or today["bytes"] >= att.DAY_BYTES:
                    bridge.reply(chat, bridge.t("ATT_DAY", project=project, n=today["files"], size=att.size_text(today["bytes"], bridge.cfg(project))), project)
                    return
                budget = att.fetch_budget(cap, today)
                got = self.fetch(project, chat, file, folder, budget)
                if got is not None and not self.left_as_told(folder, got, budget):
                    bridge.log("a provider's file did not match its answer")
                    self.failed(project, chat, file, "fetch", self.written(folder))      # recorded before the lock is released: no other fetch runs one over the count
                    bridge.reply(chat, bridge.t("ATT_FETCH_FAILED", project=project), project)
                    got = None
            finally:
                lock.release()
            if got is None:
                return
            self.hold(project, chat, file, token, target, direct, budget)
        finally:
            att.remove_incoming(data_dir, token)

    def fetch(self, project: dict, chat: str, file: dict, folder: str, budget: int):
        """The provider's answer, or None after the attempt was recorded (it counts against the day) and the person was told why not."""
        bridge = self.bridge
        try:
            return bridge.messenger.fetch(file["ref"], folder, budget)
        except provider.MessengerError as e:
            bridge.log(f"a file could not be fetched ({e.kind})")
            if e.kind == "gone":
                self.failed(project, chat, file, "gone", 0)
                bridge.reply(chat, bridge.t("ATT_GONE", project=project, platform=bridge.platform), project)
            else:
                self.failed(project, chat, file, "size" if e.kind == "usage" else "fetch", self.written(folder))      # a cap that stopped it is a usage; the bytes are what was written (a file counts for one)
                bridge.reply(chat, bridge.t("ATT_FETCH_FAILED", project=project), project)
            return None

    def failed(self, project: dict, chat: str, file: dict, code: str, nbytes: int) -> None:
        """Tell the hold that a fetch ended with no file, so that it counts against the day's files and bytes (a flood of oversized or vanished files stops at
        the limit like any other). `nbytes` is what the provider actually wrote (0 for a transient error: the file still counts for one). A failure of this call is
        logged by class and changes nothing for the person."""
        bridge = self.bridge
        try:
            bridge.run_op(project, "attachment-hold", sender=chat, incoming=None, platform=bridge.platform, ref=file["ref"], name=file.get("name") or "",
                          declared_type=file.get("type"), declared_bytes=file.get("size"), failed=code, fetched_bytes=nbytes)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.log(f"a failed fetch could not be recorded ({e.__class__.__name__})")

    @staticmethod
    def written(folder: str) -> int:
        """The bytes a provider wrote in its folder (0 when there is no file there)."""
        try:
            return os.lstat(os.path.join(folder, att.CONTENT)).st_size
        except OSError:
            return 0

    @staticmethod
    def left_as_told(folder: str, got: dict, budget: int) -> bool:
        """Whether the provider left one regular file named `content` with no other name, of the size it said, no larger than it was allowed, and with the sha256 it said:
        what it answered is not taken on its word."""
        path = os.path.join(folder, att.CONTENT)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return False
        try:
            info = os.fstat(fd)
            if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == got["bytes"] and 0 < info.st_size <= budget):
                return False
            digest = hashlib.sha256()
            while True:
                piece = os.read(fd, 1 << 20)
                if not piece:
                    break
                digest.update(piece)
            return digest.hexdigest() == got["sha256"]
        finally:
            os.close(fd)

    def hold(self, project: dict, chat: str, file: dict, token: str, target, direct: bool, budget: int) -> None:
        bridge = self.bridge
        try:
            result = bridge.run_op(project, "attachment-hold", sender=chat, incoming=token, platform=bridge.platform, ref=file["ref"], name=file.get("name") or "",
                                   declared_type=file.get("type"), declared_bytes=file.get("size"), target=target, direct=direct, max_bytes=budget)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, self.phone(e, project), project)
            return
        if direct and isinstance(result.get("added"), dict):
            bridge.reply(chat, self.said(result["added"]["reply"], project), project)
            return
        self.send_card(project, chat, result)

    # --- the card ----------------------------------------------------------------------------------------------------------------

    def send_card(self, project: dict, chat: str, result: dict) -> None:
        bridge = self.bridge
        settings = bridge.settings(project)
        if settings is None:
            return
        row = dict(result["attachment"], target=result["target"], label=result["label"])
        card = cards.attachment_card(project["name"], row, result["next_version"], bridge.messenger.capabilities(), settings["policy"], settings["notices"],
                                     operations=bridge.ops.operations, sender=bridge.key(chat), cfg=settings)
        seq = bridge.ledger.next_seq()
        message = dict(card["message"])
        made = {f"{seq}:{a['op']}": a["op"] for a in message["actions"]}
        message["actions"] = [{"id": f"{seq}:{a['op']}", "label": a["label"]} for a in message["actions"]]
        try:
            message_id = bridge.deliver(chat, message)
        except provider.MessengerError as e:
            bridge.log(f"the card of a file could not be sent ({e.kind}); /pending lists the file")
            return
        try:
            bridge.ledger.add({"project": project["id"], "pending_id": None, "attachment_id": row["id"], "kind": "attachment",
                               "content_sha256": card["content_sha256"], "chat": chat, "message_id": message_id, "actions": made, "sent_at": bridge.clock(),
                               "whole": True, "approvable": False, "blocked": None, "effect_word": None})
        except OSError as e:
            bridge.log(f"the ledger could not be written ({e.__class__.__name__})")

    # --- the answer ----------------------------------------------------------------------------------------------------------------

    def tapped(self, project: dict, chat: str, card: dict, word: str) -> None:
        """A tap on a card of a file: `word` is `add` or `discard`."""
        self.decide(project, chat, word, card["attachment_id"], card)

    def typed(self, project: dict, chat: str, word: str, number: int) -> None:
        """`/add <n>` or `/discard <n>`: bound to the newest card of that file in this chat."""
        bridge = self.bridge
        card = bridge.ledger.attachment_card(project["id"], number, chat)
        if card is None:
            bridge.reply(chat, bridge.t("NO_CARD", project=project), project)
            return
        self.decide(project, chat, word, number, card)

    def decide(self, project: dict, chat: str, word: str, number: int, card: dict) -> None:
        bridge = self.bridge
        try:
            bridge.allow(project, WORDS[word], None, chat)
            read = bridge.ops.attachments(project["path"])
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, self.phone(e, project), project)
            return
        row = next((r for r in read["held"] if r["id"] == number), None)
        if row is None:
            decided = next((r for r in read["recent"] if r["id"] == number), None)
            bridge.reply(chat, bridge.t("ATT_NOT_HELD", project=project, status=phrases.status(decided["status"], bridge.cfg(project))) if decided else bridge.t("ATT_NO_SUCH", project=project, n=number), project)
            return
        if card.get("content_sha256") != att.card_sha256(row["sha256"], row["target"], row["label"]):
            bridge.reply(chat, bridge.t("CHANGED", project=project), project)
            return

        def call():
            try:
                done = bridge.run_op(project, WORDS[word], sender=chat, attachment_id=number)
                bridge.reply(chat, self.said(done["reply"], project), project)
            except (bridge.Refused, bridge.ops.OpsError) as e:
                bridge.reply(chat, self.phone(e, project), project)
        if word == "add":
            bridge.start(project, chat, WORDS[word], call)
        else:
            call()

    # --- /pending ----------------------------------------------------------------------------------------------------------------------

    def waiting(self, project: dict, chat: str):
        """The lines that list the files waiting for THIS sender's answer, or None: the sender's profile must permit `attachments`, and only a file that has a card
        in this chat is listed (the card is what `/add` and `/discard` bind to, and a file another sender sent has none here). The read is the operation's own for
        a messaging sender, which already holds back every other sender's file; the card is the second lock."""
        bridge = self.bridge
        try:
            held = bridge.run_op(project, "attachments", sender=chat)["held"]
        except (bridge.Refused, bridge.ops.OpsError):
            return None
        held = [r for r in held if bridge.ledger.attachment_card(project["id"], r["id"], chat) is not None]
        if not held:
            return None
        cfg = bridge.cfg(project)
        return phrases.text("ATT_WAITING_HEAD", cfg, project=project["name"]) + "\n" + "\n".join(
            phrases.text("ATT_WAITING_LINE", cfg, id=r["id"], name=r["name"]) for r in held)
