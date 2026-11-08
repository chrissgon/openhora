#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's part of the preview of a delivery (package V1d-2, decision 14): the render, sent as a video of its own before the deliver card.

`send(bridge, project, item, chat, settings)` is called by `Bridge._send_card` for the card of a deliver effect that a card can hold whole
(`effect_on_cards`), before the card is built for sending. It answers:

  "sent"    the provider confirmed the video in that chat: the card offers its approval, by the bridge's own rule (a card is whole only when what it needs arrived)
  "failed"  the app cannot be sent a video, the operations layer refused the preview, the preview is larger than the app takes, or the provider did not confirm it
            (a provider that cannot tell is a failure): the card is then built with no approval, and says the delivery is approved on the page
  None      the platform deferred the send: nothing is recorded and the card is tried again

The operations layer decides which file is the preview (runtime/ops_media_preview.py `video_preview`: the sender's right, the decision, the hash of the render);
this module only asks for it through `bridge.ops`, sends it, and says one sentence. It reads no store, no file and no credential, and logs no name, no path and no byte.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import attachments as att  # noqa: E402
import messaging_provider as provider  # noqa: E402

VIDEO_TYPE = "mp4"
KEY = "VID_PREVIEW"


def applies(item: dict) -> bool:
    """Whether `item` is the card of a deliver effect that a card can hold whole: the only kind of card that has a preview."""
    return item.get("kind") == "effect" and item.get("effect_word") == "deliver" and item.get("effect_on_cards") is True


def send(bridge, project: dict, item: dict, chat: str, settings: dict):
    """Send the preview video of the deliver decision `item` to `chat`: "sent", "failed", or None when the platform deferred it."""
    caps = bridge.messenger.capabilities()
    if VIDEO_TYPE not in (caps.get("video_types") or []):
        bridge.log("this app cannot be sent a video: the delivery is approved on the page")
        return "failed"
    try:
        got = bridge.ops.video_preview(project["path"], item["id"], channel="messaging", sender=bridge.key(chat))
    except bridge.ops.OpsError as e:
        bridge.log(f"the preview of a delivery was refused ({getattr(e, 'code', 1)})")
        return "failed"
    if got["size"] > int(caps.get("max_video_bytes") or 0):
        bridge.log("the preview of a delivery is larger than this app takes")
        return "failed"
    text = bridge.t(KEY, project=project, size=att.size_text(got["size"], settings))
    message = {"text": text, "actions": [], "link": None, "document": None}
    try:
        sent = bridge.deliver_file(chat, message, {"name": got["name"], "kind": "video", "data": got["data"]})
    except provider.MessengerError as e:
        if e.kind == "deferred":
            bridge.defer(project, item, chat)
            return None
        bridge.log(f"the preview of a delivery could not be sent ({e.kind})")
        if e.kind == "not-configured":
            raise
        return "failed"
    if getattr(sent, "document_failed", True) is not False:      # a provider that cannot tell is a failure: the card is then not approvable
        bridge.log("the preview of a delivery was not delivered: its card has no approval")
        return "failed"
    return "sent"


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
