#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's part of a recording that comes from a Google Drive link (package V1d-3, decision 14, limit L70): a listed sender whose profile holds
the group `media-phone` sends a link to the file, and the recording is fetched and goes on as a recording sent as a file would. The bridge (runtime/messaging_bridge.py)
builds the module through runtime/messaging_video.py, whose `Videos.line` asks it first; it holds nothing of the rules. Whether the link is a Drive link, how
the file is fetched, the bound and what is kept are the operation `video-phone-fetch` of runtime/ops_media_cloud.py, called through `Bridge.run_op` (the policy
first). This module recognises a line that may hold a Drive link, says the work has begun, runs the operation in a job and says the result in the sender's language.

The order: `link` (a line with a Drive host in it, from a sender whose profile permits `video-phone-fetch`; any other line is not taken and goes on as it always did),
the fetch in a job, then the recording is received exactly as a file would be: the posts are read again and `Videos.choose` asks which post it is for.

This module imports only the modules the layer map lets a messaging module read.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import attachments as att  # noqa: E402

CHANNEL = "messaging"
OP = "video-phone-fetch"
HOST_WORDS = ("drive.google.com/", "docs.google.com/")
REFUSED = "refused: "
REFUSALS = {"not_shared": "VID_CLOUD_NOT_SHARED", "too_large": "VID_CLOUD_TOO_LARGE", "no_length": "VID_CLOUD_NO_LENGTH"}


class Cloud:
    """The bridge's Drive links: built once with the bridge and the `Videos` it belongs to (`videos.choose` goes on as for a recording sent as a file)."""

    def __init__(self, bridge, videos):
        self.bridge = bridge
        self.videos = videos

    def _say(self, chat: str, project: dict, key: str, **fields) -> None:
        self.bridge.reply(chat, self.bridge.t(key, project=project, **fields), project)

    def _fail(self, chat: str, project: dict, error) -> None:
        self.bridge.reply(chat, self.bridge.attach.phone(error, project), project)

    def link(self, project: dict, chat: str, text: str) -> bool:
        """True when this line was taken: a Drive host is in it and THIS sender's profile permits `video-phone-fetch`. Then the work begins in a job; the link
        itself is read by the operation (a line that names the host and holds no link is answered there). False sends nothing and logs nothing."""
        bridge = self.bridge
        lowered = (text or "").lower()
        if not any(word in lowered for word in HOST_WORDS):
            return False
        settings = bridge.settings(project)
        if settings is None or not bridge.ops.operations.permitted(OP, CHANNEL, settings["policy"], None, bridge.key(chat)):
            return False
        self._say(chat, project, "VID_CLOUD_FETCHING")
        bridge.start(project, chat, OP, lambda: self.fetched(project, chat, text))
        return True

    def fetched(self, project: dict, chat: str, text: str) -> None:
        """The job: fetch, say the recording arrived, then ask which post it is for."""
        bridge = self.bridge
        try:
            out = bridge.run_op(project, OP, sender=chat, text=text)
        except bridge.ops.OpsError as e:
            message = str(e)
            if message.startswith(REFUSED):
                self._say(chat, project, REFUSALS.get(message[len(REFUSED):], "VID_CLOUD_FAILED"))
            else:
                self._fail(chat, project, e)
            return
        self._say(chat, project, "VID_RECEIVED", size=att.size_text(out["size"], bridge.cfg(project)))
        try:
            got = bridge.ops.video_phone_posts(project["path"], channel=CHANNEL, sender=bridge.key(chat))
        except bridge.ops.OpsError as e:
            self._fail(chat, project, e)
            return
        if not got["posts"]:
            self._say(chat, project, "VID_NO_POST")
            return
        self.videos.choose(project, chat, out["media"], "", got["posts"])


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
