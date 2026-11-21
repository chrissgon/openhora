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
messaging card carries, `from_sha256` equal to `video.sha256`: the render itself when it is at most `PREVIEW_MAX_BYTES` (15 MiB), else the copy the
renderer's `preview` verb made (`preview_name` names its file), else null).

Three keys are present only when the video uses licensed or found pictures (V9b-3a, so a video with none keeps the document and the hash it always had): `assets` (one
`{slot, sha256, source, item, licence}` per picture the render drew, sorted by slot, at most 12: the normalised PNG's hash, the library, the item's id and the licence id),
`web` (one `{slot, sha256, page_host, page_sha256}` per asset whose licence nobody checked: the host of its source page and the sha256 of the page's address, never the address,
since a decision's body holds no tool output) and `credits` (the credit lines the licences ask for, which the delivery and the caption carry, at most 12 lines of 600
characters).

`check` refuses any other key or type and never echoes content: its `ValueError` names a field. `on_cards` is decision 14: a messaging card may
approve a delivery only when the preview it carries was made from this render. With no preview it is always False.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import re

WORD = "deliver"
VERSION = 1
KEYS = ("blocks", "cover", "effect", "platform", "post", "preview", "recording", "task", "verify", "version", "video")
OPTIONAL_KEYS = ("assets", "credits", "web")      # V9b-3a: present only when the video uses pictures from the media set
ASSETS_MAX = 12
SLOT = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
SOURCE = re.compile(r"[a-z][a-z0-9]{1,30}")
ITEM = re.compile(r"[A-Za-z0-9_-]{1,64}")
LICENCE = re.compile(r"[a-z][a-z0-9.-]{1,40}")
HOST = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?){1,8}")
CREDIT_MAX = 600      # = runtime/media_stock.py CREDIT_MAX; media_stock.credit_line caps its fields so every line fits

RECORDING = re.compile(r"[0-9a-f]{16}")
SHA256 = re.compile(r"[0-9a-f]{64}")
PLATFORM = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
POST = re.compile(r"docs/marketing/content/[a-z0-9][a-z0-9.-]{0,79}\.md")   # as runtime/publish_document.py CONTENT_PATH
BLOCK_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}:[a-z0-9][a-z0-9_.-]{0,63}")
BLOCKS_MAX = 64
# the largest preview a messaging card carries: under Telegram's 20 MiB and Twilio's 16 MB, read as 16,000,000 bytes or as 16 MiB. A render up to
# this size is its own preview; a larger one gets a copy from the renderer's `preview` verb (V3d), made to fit this size; with neither, the
# delivery is approved in the terminal or on the page. = providers/renderer/renderer-presets.json preview.max_bytes (a test compares)
PREVIEW_MAX_BYTES = 15 << 20
PREVIEW_FILE = "preview-{sha12}.mp4"
TITLE = "Deliver the video"
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
    if set(doc) - set(OPTIONAL_KEYS) != set(KEYS):
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
        if preview["sha256"] == video["sha256"] and preview["size"] != video["size"]:
            raise ValueError("preview.size")
    _check_assets(doc)
    return doc


def _check_assets(doc: dict) -> None:
    """The three optional keys, closed: each present only when it holds something, `web` naming assets of `assets`."""
    for key in ("assets", "web"):
        if key in doc and (not isinstance(doc[key], list) or not doc[key] or len(doc[key]) > ASSETS_MAX):
            raise ValueError(key)
    slots, unverified, previous = {}, set(), None
    for item in doc.get("assets", []):
        _keys(item, ("slot", "sha256", "source", "item", "licence"), "assets")
        if not (isinstance(item["slot"], str) and SLOT.fullmatch(item["slot"])) or (previous is not None and item["slot"] <= previous) or item["slot"] in slots:
            raise ValueError("assets.slot")
        previous = item["slot"]
        if not _sha(item["sha256"]):
            raise ValueError("assets.sha256")
        if not (isinstance(item["source"], str) and SOURCE.fullmatch(item["source"])) or not (isinstance(item["item"], str) and ITEM.fullmatch(item["item"])):
            raise ValueError("assets.source")
        if not (isinstance(item["licence"], str) and LICENCE.fullmatch(item["licence"])):
            raise ValueError("assets.licence")
        slots[item["slot"]] = item
        if item["licence"] == "unverified":
            unverified.add(item["slot"])
    seen = set()
    for item in doc.get("web", []):
        _keys(item, ("slot", "sha256", "page_host", "page_sha256"), "web")
        if item["slot"] not in unverified or item["slot"] in seen or slots[item["slot"]]["sha256"] != item["sha256"]:
            raise ValueError("web.slot")
        seen.add(item["slot"])
        if not (isinstance(item["page_host"], str) and HOST.fullmatch(item["page_host"])) or not _sha(item["page_sha256"]):
            raise ValueError("web.page")
    if unverified and seen != unverified:
        raise ValueError("web")      # a picture nobody checked is listed with its source page, always
    if "credits" in doc:      # S4: library text (a credit's title and author) is never in the document: it binds the credits by their count and their sha256
        found = doc["credits"]
        if not (isinstance(found, dict) and set(found) == {"count", "sha256"} and type(found["count"]) is int and 1 <= found["count"] <= ASSETS_MAX and _sha(found["sha256"])):
            raise ValueError("credits")


def build(*, task, recording, platform, post, video, cover, verify_platform, blocks=(), preview=None, assets=(), web=(), credits=None) -> dict:
    """The document, already passed through `check`. `video` is `{name, sha256, size, duration_ms}`, `cover` is `{name, sha256, size}` or
    None, `blocks` a sequence of `{id, sha256}` and `preview` None or `{sha256, size, from_sha256}`. `assets`, `web` and `credits` (V9b-3a) are added as keys only
    when they hold something: `assets` `{slot, sha256, source, item, licence}`, `web` `{slot, sha256, page_host, page_sha256}`, `credits` `{count, sha256}`: the number of credit lines and the sha256 of the list (the text is never in the document)."""
    doc = {"effect": WORD, "version": VERSION, "task": task, "recording": recording, "platform": platform, "post": post,
           "video": dict(video) if isinstance(video, dict) else video,
           "cover": dict(cover) if isinstance(cover, dict) else cover,
           "verify": {"passed": True, "platform": verify_platform},
           "blocks": [dict(b) if isinstance(b, dict) else b for b in blocks],
           "preview": dict(preview) if isinstance(preview, dict) else preview}
    for key, value in (("assets", assets), ("web", web)):
        if value:
            doc[key] = [dict(v) if isinstance(v, dict) else v for v in value]
    if credits:
        doc["credits"] = dict(credits)
    return check(doc)


def on_cards(doc) -> bool:
    """Decision 14: True only when the document carries a preview made from this very render. The bridge's per-chat rule (the card's file
    confirmed delivered by the provider) does the rest. With no preview it is always False."""
    preview = doc.get("preview") if isinstance(doc, dict) else None
    video = doc.get("video") if isinstance(doc, dict) else None
    return isinstance(preview, dict) and isinstance(video, dict) and preview.get("from_sha256") == video.get("sha256")


def preview_name(doc: dict) -> str:
    """The store's name of the file a document's preview is: the render itself when the preview's sha256 is the render's, else the copy the
    renderer's `preview` verb made, `preview-<12 hex>.mp4` of its own sha256. The document must hold a preview (check it first)."""
    preview, video = doc["preview"], doc["video"]
    if preview["sha256"] == video["sha256"]:
        return video["name"]
    return PREVIEW_FILE.format(sha12=preview["sha256"][:12])


def title(doc: dict) -> str:
    """The fixed title (the platform is the first line of the body), so a phone says it in the project's language."""
    return TITLE


def describe(doc: dict) -> str:
    return f"deliver {doc['video']['name']} ({doc['platform']})"


def summary(doc: dict) -> dict:
    """The closed facts a decision's payload records: words, hashes and numbers."""
    found = {"word": WORD, "platform": doc["platform"], "video_sha256": doc["video"]["sha256"], "size": doc["video"]["size"],
             "duration_ms": doc["video"]["duration_ms"], "blocks": len(doc["blocks"]), "preview": doc["preview"] is not None}
    if doc.get("assets"):      # only a video with pictures adds the keys: the summary of every other video is what it always was
        found.update(assets=len(doc["assets"]), web=len(doc.get("web") or []), credits=doc["credits"]["count"] if doc.get("credits") else 0)
    return found


def card_lines(doc: dict, digest: str) -> list:
    """The lines of the body as `[key, {field: text}]`, every value a str: what a messaging card says in the project's language
    (runtime/phrases.py `card_text`). `body` is their English sentences, so the stored body and its hash do not change."""
    video, cover, preview = doc["video"], doc["cover"], doc["preview"]
    mb = f"{video['size'] / 1_000_000:.1f}"
    seconds = f"{video['duration_ms'] / 1000:.1f}"
    lines = [["CARD_VIDEO_PLATFORM", {"platform": doc["platform"]}],
             ["CARD_VIDEO_POST", {"post": doc["post"]}],
             ["CARD_VIDEO_FILE", {"name": video["name"], "mb": mb, "seconds": seconds, "sha": video["sha256"]}]]
    lines.append(["CARD_VIDEO_COVER", {"name": cover["name"], "sha": cover["sha256"]}] if cover else ["CARD_VIDEO_NO_COVER", {}])
    lines.append(["CARD_VIDEO_VERIFIED", {"platform": doc["verify"]["platform"]}])
    if doc["blocks"]:
        lines.extend(["CARD_VIDEO_BLOCK", {"id": b["id"], "sha": b["sha256"]}] for b in doc["blocks"])
    else:
        lines.append(["CARD_VIDEO_NO_BLOCKS", {}])
    lines.append(["CARD_VIDEO_PREVIEW", {"sha": preview["sha256"], "origin": preview["from_sha256"]}] if preview else ["CARD_VIDEO_NO_PREVIEW", {}])
    lines.extend(_asset_card_lines(doc))
    lines.append(["CARD_VIDEO_DIGEST", {"digest": digest}])
    lines.append(["CARD_VIDEO_CLOSING", {}])
    return lines


def _asset_card_lines(doc: dict) -> list:
    """The lines of the pictures: one per picture, how many credits there are (the text is on this computer's page, never on a phone card: S4), and for each picture nobody
    checked the short warning (its host). No text a library or a web page wrote, and no source page address, is on a card."""
    lines = [["CARD_VIDEO_ASSET", {"slot": a["slot"], "source": a["source"], "licence": a["licence"], "sha": a["sha256"]}] for a in doc.get("assets") or []]
    if doc.get("credits"):
        lines.append(["CARD_VIDEO_CREDITS_COUNT", {"count": str(doc["credits"]["count"]), "sha": doc["credits"]["sha256"]}])
    for w in doc.get("web") or []:
        lines.append(["CARD_VIDEO_WEB", {"host": w["page_host"]}])
    return lines


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
        lines.extend(f"Animation block: {b['id']} {b['sha256']}" for b in doc["blocks"])
    else:
        lines.append("no animation blocks")
    lines.append(f"preview {preview['sha256']}, made from {preview['from_sha256']}" if preview else "no preview")
    for a in doc.get("assets") or []:
        lines.append(f"Picture: {a['slot']}, {a['source']}, {a['licence']}, sha256 {a['sha256']}")
    if doc.get("credits"):
        lines.append(f"{doc['credits']['count']} pictures need a credit; the credit text is on this computer's page (sha256 {doc['credits']['sha256']})")
    for w in doc.get("web") or []:
        lines.append(f"Found on the web, licence not checked: {w['page_host']}")
    lines.append(f"Delivery document sha256 {digest}")
    lines.append(CLOSING)
    return "\n".join(lines)
