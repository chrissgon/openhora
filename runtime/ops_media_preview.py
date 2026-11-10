#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The preview of a delivery on a messaging app (package V1d-2, decision 14): the bytes of the preview a deliver card is for, checked, and nothing else.

`video_preview(project, pending_id, channel=None, sender=None)` is a public helper of the operations layer, not a row of the table of operations: only the
messaging bridge calls it (runtime/messaging_preview.py), as the channel `messaging` and as the sender the card is for. It answers
`{"name", "kind", "data", "size", "sha256"}` for the open deliver decision `pending_id`, and refuses (core.OpsError, code 1) unless all of these hold:

  - the channel is `messaging`, and the sender's profile covers `approve` for a deliver effect (the check the approval itself makes);
  - the decision is open, an effect, and the effect of the gate `deliver` of a step task of the kind `media`;
  - its document (read by the hash the decision carries) holds a preview made from this very render (deliver_document.on_cards): the render itself
    when it is at most deliver_document.PREVIEW_MAX_BYTES, else the renderer's copy (deliver_document.preview_name);
  - the preview's file, read from the store, still hashes to the hash the document recorded.

It writes nothing, sends nothing and answers nobody. It reads at most deliver_document.PREVIEW_MAX_BYTES (15 MiB) into memory. The approval stays a decision of the hash of the exact render: the
preview is for looking.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import deliver_document  # noqa: E402
import effects  # noqa: E402
import media  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_step_effects  # noqa: E402
import ops_step_seams  # noqa: E402

CHANNEL = "messaging"
KIND = "effect:" + deliver_document.WORD      # = messaging_cards.effect_kind({"effect_word": "deliver"}) (a test compares)
NAME = "video-{sha12}.mp4"
NOT_DELIVERY = "this decision is not the delivery of a video"
NO_PREVIEW = "this video has no preview: approve it in the terminal or on the page"
CHANGED = "the render changed after it was shown"


def video_preview(project: str, pending_id, channel=None, sender=None) -> dict:
    """The preview of the deliver decision `pending_id` for a messaging sender: {"name", "kind": "video", "data", "size", "sha256"}."""
    if channel != CHANNEL:
        raise core.OpsError("the preview of a delivery is for a messaging app only", 1)
    ctx = core.context(project)
    ops_actor.guard(ctx, "approve", channel, sender, kind=KIND)
    item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    if item.get("status") != "open" or item.get("kind") != "effect":
        raise core.OpsError(NOT_DELIVERY, 1)
    found = ops_step_effects.step_effect_of(ctx, item)
    if found is None:
        raise core.OpsError(NOT_DELIVERY, 1)
    task, kind, gate = found
    named = (item.get("payload") or {}).get("step")
    if kind.name != "media" or gate.word != deliver_document.WORD or named.get("step") != "deliver":
        raise core.OpsError(NOT_DELIVERY, 1)
    cycle = (item.get("payload") or {}).get("cycle", 0)
    digest = item.get("payload_sha256")
    if type(cycle) is not int or not isinstance(digest, str):
        raise core.OpsError(NOT_DELIVERY, 1)
    try:
        doc = ops_step_seams.EffectFiles(ctx["cfg"]).read(task["id"], cycle, digest)
        deliver_document.check(doc)
    except (effects.EffectError, ValueError):
        raise core.OpsError("the delivery document cannot be read", 1) from None
    if not deliver_document.on_cards(doc):
        raise core.OpsError(NO_PREVIEW, 1)
    preview = doc["preview"]
    if preview["size"] > deliver_document.PREVIEW_MAX_BYTES:
        raise core.OpsError(NO_PREVIEW, 1)
    try:
        data = media.read_work(ctx["cfg"]["data_dir"], doc["recording"], deliver_document.preview_name(doc), limit=preview["size"])
    except media.MediaError as e:
        raise core.OpsError(str(e), 1) from None
    found_sha = hashlib.sha256(data).hexdigest()
    if found_sha != preview["sha256"]:
        raise core.OpsError(CHANGED, 1)
    return {"name": NAME.format(sha12=preview["sha256"][:12]), "kind": "video", "data": data, "size": len(data), "sha256": found_sha}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
