#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Watching a video before its delivery (package V1c-3, limit L71): the bytes of the render the open deliver decision names, checked, and nothing else.

`video_watch(project, task_id, channel=None)` is the operation `video-watch` (page only, refused on the --lan socket). It answers
`{"media_type": "video/mp4", "data": bytes}` for the one open deliver decision of the media task `task_id` (the bytes of its preview: the render itself
when it is at most deliver_document.PREVIEW_MAX_BYTES, else the renderer's copy that deliver_document.preview_name names), and refuses (core.OpsError, code 1) unless all
of these hold:

  - the channel is `page`, and the page may approve a deliver effect (the check the approval itself makes: it may watch only what it may approve);
  - the task waits at the delivery approval, with one open decision that is the effect of the gate `deliver` of a step task of the kind `media`;
  - its document (read by the hash the decision carries) holds a preview made from this very render (deliver_document.on_cards), which is the render
    itself when it is at most deliver_document.PREVIEW_MAX_BYTES;
  - the preview's file, read from the store, still hashes to the hash the document recorded.

It writes nothing, marks nothing (media.mark_delivered is never called) and sends nothing. It reads at most deliver_document.PREVIEW_MAX_BYTES (15 MiB) into memory. The approval stays a
decision of the hash of the exact render: this is for looking.

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

CHANNEL = "page"
KIND = "effect:" + deliver_document.WORD
NOT_WAITING = "this video is not waiting for its delivery"
TOO_LARGE = "this video is larger than a preview: download it after you approve the delivery"
CHANGED = "the render changed after it was shown"
PAGE_ONLY = "watching a video before its delivery is for this computer's own page only"


def _open_delivery(ctx: dict, task_id):
    """The one open deliver decision of the media task `task_id`, with (task, kind, gate), or a refusal."""
    store = ctx["store"]
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise core.OpsError(NOT_WAITING, 1)
    task = core._stored(ctx, store.task_get, task_id)
    if task.get("state") != "waiting":
        raise core.OpsError(NOT_WAITING, 1)
    items = [p for p in core._stored(ctx, store.pending_list, "open", task["id"]) if p.get("kind") == "effect"]
    for item in sorted(items, key=lambda p: p["id"], reverse=True):
        found = ops_step_effects.step_effect_of(ctx, item)
        if found is None:
            continue
        _, kind, gate = found
        named = (item.get("payload") or {}).get("step") or {}
        if kind.name == "media" and gate.word == deliver_document.WORD and named.get("step") == "deliver":
            return item, found
    raise core.OpsError(NOT_WAITING, 1)


def video_watch(project: str, task_id, channel=None) -> dict:
    """The bytes of the render the open deliver decision of `task_id` names: {"media_type": "video/mp4", "data": bytes}."""
    if channel != CHANNEL:
        raise core.OpsError(PAGE_ONLY, 1)
    ctx = core.context(project)
    ops_actor.guard(ctx, "approve", channel, None, kind=KIND)
    item, found = _open_delivery(ctx, task_id)
    task = found[0]
    cycle = (item.get("payload") or {}).get("cycle", 0)
    digest = item.get("payload_sha256")
    if type(cycle) is not int or not isinstance(digest, str):
        raise core.OpsError(NOT_WAITING, 1)
    try:
        doc = ops_step_seams.EffectFiles(ctx["cfg"]).read(task["id"], cycle, digest)
        deliver_document.check(doc)
    except (effects.EffectError, ValueError):
        raise core.OpsError("the delivery document cannot be read", 1) from None
    if not deliver_document.on_cards(doc):
        raise core.OpsError(TOO_LARGE, 1)
    preview = doc["preview"]
    if preview["size"] > deliver_document.PREVIEW_MAX_BYTES:
        raise core.OpsError(TOO_LARGE, 1)
    try:
        data = media.read_work(ctx["cfg"]["data_dir"], doc["recording"], deliver_document.preview_name(doc), limit=preview["size"])
    except media.MediaError as e:
        raise core.OpsError(str(e), 1) from None
    if hashlib.sha256(data).hexdigest() != preview["sha256"]:
        raise core.OpsError(CHANGED, 1)
    return {"media_type": "video/mp4", "data": data}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
