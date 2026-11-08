#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's part of a video that comes from a messaging app (package V1d-1, decision 14): the recording a listed sender sends, the post it is for,
the captions sent back, the corrections and the go-ahead. The bridge (runtime/messaging_bridge.py) builds it and the turn rows (runtime/messaging_turn.py)
call it in three places; it holds nothing of the rules. Who may send a recording, which post, which words a correction changes and the run are the operations of
runtime/ops_media_phone.py, called through `Bridge.run_op` (the policy first). This module fetches through the provider, calls them and says the result in the
sender's language.

The order, for a video that arrives (each step before the next; nothing is fetched before the last check):

  1. `claims`: exactly one attachment, declared as a video, from a sender whose profile holds the group `media-phone` (it sends nothing and logs nothing: when it
     is false the line goes on to the files' path, which refuses a video as it always did);
  2. `arrived`: the posts a video may be for and the bounds on a recording (the least of the media store's per-recording bound, the quota left and the provider's
     file limit), a declared size over the bound, no post ready: each is said and nothing is fetched;
  3. `fetch`, in a job: one incoming folder, one fetch at a time, the provider's file taken at its word only after `Attachments.left_as_told`, the recording kept by
     `video-phone-in`, the incoming folder removed whatever happens;
  4. `choose`: the caption names a post, or the numbered list is sent and `line` reads the number (held in memory for an hour);
  5. `start` and `started`: the video runs to the caption review and its words go back to the chat of the sender who sent the recording.

`replied` reads a reply to the caption review card (`continue`, or `wrong -> right` lines) and to the delivery card (corrections only). The caption words are only
sent, never kept here.

This module imports only the modules the layer map lets a messaging module read.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import os
import re
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import attachments as att  # noqa: E402
import messaging_provider as provider  # noqa: E402

CHANNEL = "messaging"
VIDEO_TYPES = ("video", "video/mp4", "video/quicktime")
HELD_SECONDS = 3600
NUMBER = re.compile(r"\s*([0-9]{1,2})\s*[.)]?\s*")      # the same rule as runtime/media_phone_words.py post_choice, written again: this module cannot import it


class Videos:
    """The bridge's videos: built once with the bridge and calling back into it (`reply`, `t`, `run_op`, `settings`, `start`, `attach`, `messenger`)."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.held = {}              # chat -> {"media", "posts", "at", "project"}: a recording waiting for the post's number; memory only
        self.lock = threading.Lock()

    def _say(self, chat: str, project: dict, key: str, **fields) -> None:
        self.bridge.reply(chat, self.bridge.t(key, project=project, **fields), project)

    def _fail(self, chat: str, project: dict, error) -> None:
        self.bridge.reply(chat, self.bridge.attach.phone(error, project), project)

    def _seconds_since(self, then: str):
        try:
            began = datetime.datetime.fromisoformat(then)
            return (datetime.datetime.fromisoformat(self.bridge.clock()) - began).total_seconds()
        except (ValueError, TypeError):
            return None

    # --- what arrives ------------------------------------------------------------------------------------------------------------

    def claims(self, project: dict, chat: str, intent: dict) -> bool:
        """Whether this line is a video this module takes: the provider takes attachments, the message holds exactly one, declared as a video, the project's
        configuration is accepted and THIS sender's profile permits `video-phone-in`. It sends nothing and logs nothing."""
        bridge = self.bridge
        files = intent.get("attachments") or []
        if len(files) != 1 or not bridge.messenger.capabilities().get("attachments"):
            return False
        declared = att.normalised(files[0]).get("type")
        if not isinstance(declared, str) or declared.lower() not in VIDEO_TYPES:
            return False
        settings = bridge.settings(project)
        if settings is None:
            return False
        return bool(bridge.ops.operations.permitted("video-phone-in", CHANNEL, settings["policy"], None, bridge.key(chat)))

    def arrived(self, project: dict, chat: str, intent: dict) -> None:
        """Steps 2 of the order, on the bridge's thread. Nothing is fetched here: a recording over the bound or with no post to be for is said and left."""
        bridge = self.bridge
        file = att.normalised(intent["attachments"][0])
        try:
            got = bridge.ops.video_phone_posts(project["path"], channel=CHANNEL, sender=bridge.key(chat))
        except bridge.ops.OpsError as e:
            self._fail(chat, project, e)
            return
        caps = bridge.messenger.capabilities()
        cap = min(got["max_bytes"], got["free_bytes"], caps.get("max_attachment_bytes") or got["max_bytes"])
        declared = file.get("size")
        if isinstance(declared, int) and not isinstance(declared, bool) and declared > cap:
            cfg = bridge.cfg(project)
            self._say(chat, project, "VID_TOO_BIG", size=att.size_text(declared, cfg), cap=att.size_text(cap, cfg))
            return
        if not got["posts"]:
            self._say(chat, project, "VID_NO_POST")
            return
        self._say(chat, project, "VID_FETCHING")
        caption = intent.get("text") or ""
        bridge.start(project, chat, "video-phone-in", lambda: self.fetch(project, chat, file, cap, caption, got["posts"]))

    def fetch(self, project: dict, chat: str, file: dict, cap: int, caption: str, posts: list) -> None:
        """Step 3, in a job: the steps of `Attachments.fetch_one` for one file, under the cap given, with no day counter (a recording is not a source file: the
        media store's quota bounds it)."""
        bridge = self.bridge
        data_dir = bridge.ops.config(project["path"])["data_dir"]
        try:
            token, folder = att.make_incoming(data_dir)
        except att.FolderError:
            bridge.log("the folder of a fetch could not be made")
            self._say(chat, project, "ATT_FETCH_FAILED")
            return
        media = None
        try:
            try:
                lock = att.fetch_lock(data_dir)
            except att.FetchBusy:
                self._say(chat, project, "ATT_BUSY")
                return
            try:
                try:
                    got = bridge.messenger.fetch(file["ref"], folder, cap)
                except provider.MessengerError as e:
                    bridge.log(f"a recording could not be fetched ({e.kind})")
                    self._say(chat, project, "ATT_GONE" if e.kind == "gone" else "ATT_FETCH_FAILED", **({"platform": bridge.platform} if e.kind == "gone" else {}))
                    return
                if not bridge.attach.left_as_told(folder, got, cap):
                    bridge.log("a provider's file did not match its answer")
                    self._say(chat, project, "ATT_FETCH_FAILED")
                    return
                try:
                    kept = bridge.run_op(project, "video-phone-in", sender=chat, incoming=token, platform=bridge.platform, ref=file["ref"])
                except bridge.ops.OpsError as e:
                    self._fail(chat, project, e)
                    return
                media = kept["media"]
                self._say(chat, project, "VID_RECEIVED", size=att.size_text(kept["size"], bridge.cfg(project)))
            finally:
                lock.release()
        finally:
            att.remove_incoming(data_dir, token)
        if media is not None:
            self.choose(project, chat, media, caption, posts)

    # --- the post ----------------------------------------------------------------------------------------------------------------

    def choose(self, project: dict, chat: str, media: str, caption: str, posts: list) -> None:
        """Step 4: the caption names a post (its stem, exactly), or the numbered list is sent and the number is read from the next line."""
        wanted = (caption or "").strip().lower()
        for stem in posts:
            if stem.lower() == wanted:
                self.start(project, chat, media, stem)
                return
        with self.lock:
            self.held[chat] = {"media": media, "posts": list(posts), "at": self.bridge.clock(), "project": project["id"]}
        listing = "\n".join(f"{n}. {stem}" for n, stem in enumerate(posts, 1))
        self._say(chat, project, "VID_PICK_POST", list=listing)

    def line(self, project: dict, chat: str, text: str) -> bool:
        """A line of text from a chat that has a recording waiting for its post: a number from the list, or the post's exact name, starts the video; a number
        out of range is told; anything else returns False (the recording waits until it is an hour old)."""
        with self.lock:
            entry = self.held.get(chat)
            if entry is None or entry["project"] != project["id"]:
                return False
            age = self._seconds_since(entry["at"])
            if age is None or age >= HELD_SECONDS:
                self.held.pop(chat, None)
                return False
            posts = entry["posts"]
            found = NUMBER.fullmatch(text or "")
            stem = None
            if found:
                number = int(found.group(1))
                if not 1 <= number <= len(posts):
                    stem = ""
                else:
                    stem = posts[number - 1]
            elif (text or "").strip() in posts:
                stem = (text or "").strip()
            if stem is None:
                return False
            if stem == "":
                told = len(posts)
            else:
                told = None
                self.held.pop(chat, None)
        if told is not None:
            self._say(chat, project, "VID_POST_GONE", n=told)
            return True
        self.start(project, chat, entry["media"], stem)
        return True

    # --- the video ---------------------------------------------------------------------------------------------------------------

    def start(self, project: dict, chat: str, media: str, post: str) -> None:
        """Step 5: the video of the recording for the post, in a job, to the caption review."""
        bridge = self.bridge

        def call():
            try:
                out = bridge.run_op(project, "video-phone-start", sender=chat, media_id=media, post=post)
            except bridge.ops.OpsError as e:
                self._fail(chat, project, e)
                return
            self.started(project, chat, out)
        bridge.start(project, chat, "video-phone-start", call)

    def started(self, project: dict, chat: str, out: dict) -> None:
        """What a run that ended says: at the caption review its words go to the sender's chat; a step that did not run, or that failed, is said in one sentence.
        Any other stop (the delivery approval) is the bridge's usual card."""
        if out.get("stopped") == "review":
            self._say(chat, project, "VID_REVIEW_WORDS", words=out["words"])
            if out.get("cut"):
                self._say(chat, project, "VID_CUT")
        elif not out.get("started", True) or out.get("ok") is False:
            self._say(chat, project, "VID_NOT_STARTED")

    def run(self, project: dict, chat: str, task: int) -> None:
        """Run the video again, in a job, and say where it stopped."""
        bridge = self.bridge

        def call():
            try:
                out = bridge.run_op(project, "video-phone-run", sender=chat, task_id=task)
            except bridge.ops.OpsError as e:
                self._fail(chat, project, e)
                return
            self.started(project, chat, out)
        bridge.start(project, chat, "video-phone-run", call)

    def replied(self, project: dict, chat: str, card: dict, text: str) -> bool:
        """A reply to the caption review card (kind `question`) or to the delivery card (kind `effect`) of a video. True when it was read here; False when the
        sender's profile does not permit it or the card is not a video's, so that the reply goes on as it always did."""
        bridge = self.bridge
        settings = bridge.settings(project)
        if settings is None or not bridge.ops.operations.permitted("video-phone-reply", CHANNEL, settings["policy"], None, bridge.key(chat)):
            return False
        try:
            out = bridge.run_op(project, "video-phone-reply", sender=chat, pending_id=card["pending_id"], text=text)
        except bridge.ops.OpsError as e:
            self._fail(chat, project, e)
            return True
        action = out["action"]
        if action == "not-video":
            return False
        if action == "continue":
            try:
                bridge.run_op(project, "answer", sender=chat, pending_id=card["pending_id"], text="continue")
            except bridge.ops.OpsError as e:
                self._fail(chat, project, e)
                return True
            except bridge.Refused as e:
                bridge.reply(chat, str(e), project, guard=True)
                return True
            self._say(chat, project, "VID_RENDERING")
            self.run(project, chat, out["task"])
        elif action == "edited":
            if out["run"]:
                self._say(chat, project, "VID_EDITED_GATE")
                self.run(project, chat, out["task"])
            else:
                self._say(chat, project, "VID_EDITED", words=out["words"])
                if out.get("cut"):
                    self._say(chat, project, "VID_CUT")
        elif action in ("not_found", "ambiguous"):
            self._say(chat, project, "VID_NOT_FOUND" if action == "not_found" else "VID_AMBIGUOUS", wrong=out["wrong"])
        else:
            self._say(chat, project, "VID_HOW")
        return True


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
