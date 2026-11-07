#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of a delivery, and nothing that delivers: what the step kind `media` builds and the effect kind `deliver` approves. Pure: it
reads no file, opens no store and calls no provider, so the step kind imports it and not the effect module (limit L30's structure, as
runtime/publish_document.py is for `publish`). The effect module (runtime/effect_deliver.py, a later package) is the only code that marks a
render delivered, through runtime/media.py `mark_delivered`.

The document, every key present: `effect` ("deliver"), `version` (1), `task` (the step task that prepared it), `recording` (the store's id,
16 hex characters), `platform`, `post` (the post's file under docs/marketing/content/), `video` (`name` `render-<12 hex>.mp4` equal to the
first 12 characters of its `sha256`, `size`, `duration_ms`), `cover` (null, or `name` `cover-<12 hex>.png`, `sha256`, `size`), `verify`
(`passed`, true, and the `platform` the renderer's check ran for), `blocks` (animation blocks the render mounted: `{id, sha256}`, sorted by id,
at most 64; empty until the block catalogue fills them) and `preview` (null, or `{sha256, size, from_sha256}`; the preview of the render a
messaging card carries, `from_sha256` equal to `video.sha256`; null until a channel can send one).

`check` refuses any other key or type and never echoes content: its `ValueError` names a field. `on_cards` is decision 14: a messaging card may
approve a delivery only when the preview it carries was made from this render. With no preview it is always False.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import re

WORD = "deliver"
VERSION = 1
KEYS = ("blocks", "cover", "effect", "platform", "post", "preview", "recording", "task", "verify", "version", "video")

RECORDING = re.compile(r"[0-9a-f]{16}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PLATFORM = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
POST = re.compile(r"docs/marketing/content/[a-z0-9][a-z0-9.-]{0,79}\.md")   # as runtime/publish_document.py CONTENT_PATH
BLOCK_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}:[a-z0-9][a-z0-9_.-]{0,63}")
BLOCKS_MAX = 64
CLOSING = "Approving marks this exact file downloadable. Nothing is published."


def _int(value, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def _sha(value) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _keys(value, keys, field: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(field)
    for key in keys:
        if key not in value:
            raise ValueError(f"{field}.{key}")
    if set(value) != set(keys):
        raise ValueError(field)


def check(doc) -> dict:
    """The document, or ValueError naming the first field that is wrong. It never echoes content."""
    if not isinstance(doc, dict):
        raise ValueError("document")
    for key in KEYS:
        if key not in doc:
            raise ValueError(key)
    if set(doc) != set(KEYS):
        raise ValueError("keys")
    if doc["effect"] != WORD:
        raise ValueError("effect")
    if not _int(doc["version"], 1) or doc["version"] != VERSION:
        raise ValueError("version")
    if not _int(doc["task"], 1):
        raise ValueError("task")
    if not isinstance(doc["recording"], str) or not RECORDING.fullmatch(doc["recording"]):
        raise ValueError("recording")
    if not isinstance(doc["platform"], str) or not PLATFORM.fullmatch(doc["platform"]):
        raise ValueError("platform")
    if not isinstance(doc["post"], str) or not POST.fullmatch(doc["post"]):
        raise ValueError("post")
    video = doc["video"]
    _keys(video, ("name", "sha256", "size", "duration_ms"), "video")
    if not _sha(video["sha256"]):
        raise ValueError("video.sha256")
    if video["name"] != f"render-{video['sha256'][:12]}.mp4":
        raise ValueError("video.name")
    if not _int(video["size"], 1):
        raise ValueError("video.size")
    if not _int(video["duration_ms"], 1):
        raise ValueError("video.duration_ms")
    cover = doc["cover"]
    if cover is not None:
        _keys(cover, ("name", "sha256", "size"), "cover")
        if not _sha(cover["sha256"]):
            raise ValueError("cover.sha256")
        if cover["name"] != f"cover-{cover['sha256'][:12]}.png":
            raise ValueError("cover.name")
        if not _int(cover["size"], 1):
            raise ValueError("cover.size")
    verify = doc["verify"]
    _keys(verify, ("passed", "platform"), "verify")
    if verify["passed"] is not True:
        raise ValueError("verify.passed")
    if verify["platform"] != doc["platform"]:
        raise ValueError("verify.platform")
    blocks = doc["blocks"]
    if not isinstance(blocks, list) or len(blocks) > BLOCKS_MAX:
        raise ValueError("blocks")
    previous = None
    for block in blocks:
        _keys(block, ("id", "sha256"), "blocks")
        if not isinstance(block["id"], str) or not BLOCK_ID.fullmatch(block["id"]):
            raise ValueError("blocks.id")
        if not _sha(block["sha256"]):
            raise ValueError("blocks.sha256")
        if previous is not None and block["id"] <= previous:
            raise ValueError("blocks.order")
        previous = block["id"]
    preview = doc["preview"]
    if preview is not None:
        _keys(preview, ("sha256", "size", "from_sha256"), "preview")
        if not _sha(preview["sha256"]) or not _sha(preview["from_sha256"]):
            raise ValueError("preview.sha256")
        if not _int(preview["size"], 1):
            raise ValueError("preview.size")
        if preview["from_sha256"] != video["sha256"]:
            raise ValueError("preview.from_sha256")
    return doc


def build(*, task, recording, platform, post, video, cover, verify_platform, blocks=(), preview=None) -> dict:
    """The document, already passed through `check`. `video` is `{name, sha256, size, duration_ms}`, `cover` is `{name, sha256, size}` or
    None, `blocks` a sequence of `{id, sha256}` and `preview` None or `{sha256, size, from_sha256}`."""
    doc = {"effect": WORD, "version": VERSION, "task": task, "recording": recording, "platform": platform, "post": post,
           "video": dict(video) if isinstance(video, dict) else video,
           "cover": dict(cover) if isinstance(cover, dict) else cover,
           "verify": {"passed": True, "platform": verify_platform},
           "blocks": [dict(b) if isinstance(b, dict) else b for b in blocks],
           "preview": dict(preview) if isinstance(preview, dict) else preview}
    return check(doc)


def on_cards(doc) -> bool:
    """Decision 14: True only when the document carries a preview made from this very render. The bridge's per-chat rule (the card's file
    confirmed delivered by the provider) does the rest. With no preview it is always False."""
    preview = doc.get("preview") if isinstance(doc, dict) else None
    video = doc.get("video") if isinstance(doc, dict) else None
    return isinstance(preview, dict) and isinstance(video, dict) and preview.get("from_sha256") == video.get("sha256")


def title(doc: dict) -> str:
    return f"Deliver the video for {doc['platform']}"


def describe(doc: dict) -> str:
    return f"deliver {doc['video']['name']} ({doc['platform']})"


def summary(doc: dict) -> dict:
    """The closed facts a decision's payload records: words, hashes and numbers."""
    return {"word": WORD, "platform": doc["platform"], "video_sha256": doc["video"]["sha256"], "size": doc["video"]["size"],
            "duration_ms": doc["video"]["duration_ms"], "blocks": len(doc["blocks"]), "preview": doc["preview"] is not None}


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving: one fixed line per fact, then the hash of this document and the one sentence that says what
    approving does."""
    video, cover, preview = doc["video"], doc["cover"], doc["preview"]
    lines = [f"Platform: {doc['platform']}",
             f"Post: {doc['post']}",
             f"Video: {video['name']}, {video['size'] / 1_000_000:.1f} MB, {video['duration_ms'] / 1000:.1f} s, sha256 {video['sha256']}"]
    lines.append(f"Cover: {cover['name']}, sha256 {cover['sha256']}" if cover else "Cover: no cover")
    lines.append(f"verified for {doc['verify']['platform']}")
    if doc["blocks"]:
        lines.extend(f"{b['id']} {b['sha256']}" for b in doc["blocks"])
    else:
        lines.append("no animation blocks")
    lines.append(f"preview {preview['sha256']}, made from {preview['from_sha256']}" if preview else "no preview")
    lines.append(f"Delivery document sha256 {digest}")
    lines.append(CLOSING)
    return "\n".join(lines)
