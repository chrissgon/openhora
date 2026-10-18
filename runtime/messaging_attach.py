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

import os
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import attachments as att  # noqa: E402
import messaging_cards as cards  # noqa: E402
import messaging_provider as provider  # noqa: E402

CHANNEL = "messaging"
CHANGED = "This decision changed since you saw it."
WORDS = {"add": "attachment-add", "discard": "attachment-discard"}


class Attachments:
    """The bridge's files: built once with the bridge and calling back into it (`reply`, `run_op`, `settings`, `start`, `deliver`, `ledger`)."""

    def __init__(self, bridge):
        self.bridge = bridge

    # --- what arrives ------------------------------------------------------------------------------------------------------------

    def arrived(self, project: dict, chat: str, intent: dict) -> None:
        """Steps 1 to 3 on the bridge's thread (nothing is fetched here), then the fetches in a job."""
        bridge = self.bridge
        caps = bridge.messenger.capabilities()
        if not caps.get("attachments"):
            bridge.reply(chat, att.NO_FILES)
            return
        settings = bridge.settings(project)
        if settings is None:
            bridge.reply(chat, bridge.NOT_ACCEPTED)
            return
        operations = bridge.ops.operations
        key = bridge.key(chat)
        if not operations.permitted("attachment-hold", CHANNEL, settings["policy"], None, key):
            bridge.log("a file was not fetched: the channel's policy takes none")
            bridge.reply(chat, att.OFF)
            return
        direct = operations.granted("attachment-hold", CHANNEL, settings["policy"], "direct", key)
        files = intent["attachments"]
        target, ignored = att.caption_target(intent.get("text"), len(files))
        cap = min(att.FILE_CAP, caps.get("max_attachment_bytes") or att.FILE_CAP)
        try:
            held = bridge.ops.attachments(project["path"])
        except bridge.ops.OpsError as e:
            bridge.reply(chat, str(e))
            return
        lines, todo, over = [], [], False
        for decision in att.precheck(files, cap=cap, today=held["today"], held=held["held"], platform=bridge.platform):
            file = decision["attachment"]
            if decision["over"]:
                over = True
            elif decision["duplicate"] is not None:
                lines.append(att.DUPLICATE.format(name=att.clean_name(file.get("name")), id=decision["duplicate"]["id"]))
            elif decision["refuse"] is not None:
                lines.append(att.refusal_text(decision["refuse"], file, bridge.platform, cap))
            else:
                todo.append(file)
        if over:
            lines.append(att.OVER_MESSAGE.format(n=att.PER_MESSAGE))
        if ignored:
            lines.append(att.CAPTION_IGNORED)
        if lines:
            bridge.reply(chat, "\n".join(dict.fromkeys(lines)))
        if todo:
            bridge.start(project, chat, "attachment-hold", lambda: self.fetch_all(project, chat, todo, target, direct, cap))

    # --- the fetches, in a job -------------------------------------------------------------------------------------------------------

    def fetch_all(self, project: dict, chat: str, files: list, target, direct: bool, cap: int) -> None:
        for file in files:
            try:
                self.fetch_one(project, chat, file, target, direct, cap)
            except Exception as e:       # one file never takes the job down, and the class is all that is logged
                self.bridge.log(f"a file could not be taken ({e.__class__.__name__})")
                self.bridge.reply(chat, att.FETCH_FAILED)

    def fetch_one(self, project: dict, chat: str, file: dict, target, direct: bool, cap: int) -> None:
        bridge = self.bridge
        data_dir = bridge.ops.config(project["path"])["data_dir"]
        try:
            token, folder = att.make_incoming(data_dir)
        except att.FolderError:
            bridge.log("the folder of a fetch could not be made")
            bridge.reply(chat, att.FETCH_FAILED)
            return
        try:
            try:
                lock = att.fetch_lock(data_dir)
            except att.FetchBusy:
                bridge.reply(chat, att.BUSY)
                return
            try:
                today = bridge.ops.attachments(project["path"])["today"]
                if today["files"] >= att.DAY_FILES or today["bytes"] >= att.DAY_BYTES:
                    bridge.reply(chat, att.DAY.format(n=today["files"], size=att.size_text(today["bytes"])))
                    return
                budget = att.fetch_budget(cap, today)
                got = self.fetch(chat, file, folder, budget)
            finally:
                lock.release()
            if got is None:
                return
            if not self.left_as_told(folder, got, budget):
                bridge.log("a provider's file did not match its answer")
                bridge.reply(chat, att.FETCH_FAILED)
                return
            self.hold(project, chat, file, token, target, direct)
        finally:
            att.remove_incoming(data_dir, token)

    def fetch(self, chat: str, file: dict, folder: str, budget: int):
        """The provider's answer, or None after the person was told why not."""
        bridge = self.bridge
        try:
            return bridge.messenger.fetch(file["ref"], folder, budget)
        except provider.MessengerError as e:
            bridge.log(f"a file could not be fetched ({e.kind})")
            bridge.reply(chat, att.GONE.format(platform=bridge.platform) if e.kind == "gone" else att.FETCH_FAILED)
            return None

    @staticmethod
    def left_as_told(folder: str, got: dict, budget: int) -> bool:
        """Whether the provider left one regular file named `content`, of the size it said and no more than it was allowed: what it answered is not taken on its word."""
        try:
            info = os.lstat(os.path.join(folder, att.CONTENT))
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and info.st_size == got["bytes"] and 0 < info.st_size <= budget

    def hold(self, project: dict, chat: str, file: dict, token: str, target, direct: bool) -> None:
        bridge = self.bridge
        try:
            result = bridge.run_op(project, "attachment-hold", sender=chat, incoming=token, platform=bridge.platform, ref=file["ref"], name=file.get("name") or "",
                                   declared_type=file.get("type"), declared_bytes=file.get("size"), target=target, direct=direct)
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, str(e))
            return
        if direct and isinstance(result.get("added"), dict):
            bridge.reply(chat, result["added"]["reply"])
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
                                     operations=bridge.ops.operations, sender=bridge.key(chat))
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
            bridge.reply(chat, bridge.NO_CARD)
            return
        self.decide(project, chat, word, number, card)

    def decide(self, project: dict, chat: str, word: str, number: int, card: dict) -> None:
        bridge = self.bridge
        try:
            bridge.allow(project, WORDS[word], None, chat)
            read = bridge.ops.attachments(project["path"])
        except (bridge.Refused, bridge.ops.OpsError) as e:
            bridge.reply(chat, str(e))
            return
        row = next((r for r in read["held"] if r["id"] == number), None)
        if row is None:
            decided = next((r for r in read["recent"] if r["id"] == number), None)
            bridge.reply(chat, att.NOT_HELD.format(status=decided["status"]) if decided else att.NO_SUCH.format(n=number))
            return
        if card.get("content_sha256") != att.card_sha256(row["sha256"], row["target"], row["label"]):
            bridge.reply(chat, CHANGED)
            return

        def call():
            try:
                done = bridge.run_op(project, WORDS[word], sender=chat, attachment_id=number)
                bridge.reply(chat, done["reply"])
            except (bridge.Refused, bridge.ops.OpsError) as e:
                bridge.reply(chat, str(e))
        if word == "add":
            bridge.start(project, chat, WORDS[word], call)
        else:
            call()

    # --- /pending ----------------------------------------------------------------------------------------------------------------------

    def waiting(self, project: dict, chat: str):
        """The lines that list the files waiting for this sender's answer, or None: the sender's profile must permit `attachments`."""
        bridge = self.bridge
        settings = bridge.settings(project)
        if settings is None or not bridge.ops.operations.permitted("attachments", CHANNEL, settings["policy"], None, bridge.key(chat)):
            return None
        try:
            held = bridge.ops.attachments(project["path"])["held"]
        except bridge.ops.OpsError:
            return None
        if not held:
            return None
        return f"{project['name']}: files waiting for your answer\n" + "\n".join(
            f"file #{r['id']} {r['name']}: /add {r['id']} or /discard {r['id']}" for r in held)
