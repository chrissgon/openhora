#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of a video that comes from a messaging app (package V1d-1, decision 14): a recording a listed sender sent, the post it is for, the words of its
captions, a correction and the run that goes on. The operations layer decides; the messaging bridge (runtime/messaging_video.py) only fetches, calls these and
says the answer. Every call is the bridge's: any channel but `messaging` is refused first, then the sender's profile must hold the group `media-phone`
(runtime/ops_actor.py guard).

  video_phone_posts(project, channel=None, sender=None)                          the posts a video may be for (a helper, not an operation; the guard names `video-phone-in`)
  video_phone_in(project, incoming, platform, ref, channel=None, sender=None)    keep the recording the bridge fetched into an incoming folder it made (`video-phone-in`)
  video_phone_start(project, media_id, post, channel=None, sender=None)          the new video of a recording for one of the posts offered, run to the caption review (`video-phone-start`)
  video_phone_reply(project, pending_id, text, channel=None, sender=None)        read a reply to the caption review or to the delivery decision of a video (`video-phone-reply`)
  video_phone_run(project, task_id, channel=None, sender=None)                   run the video again after the review was answered or the captions were corrected (`video-phone-run`)

What a reply can say is runtime/media_phone_words.py: `continue`, or one `wrong -> right` line for each correction. A correction changes the captions only
through runtime/ops_media_edit.py `edit`, by the closed edits of runtime/captions.py; at the delivery approval it answers the delivery decision, so the video is
rendered again and asked for again. The caption words are the person's own: they are returned to the caller and never written to a store, a decision or a log here.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import attachments as att  # noqa: E402
import media  # noqa: E402
import media_phone_words as words  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media  # noqa: E402
import ops_media_edit  # noqa: E402
import ops_step_effects  # noqa: E402
import step_media  # noqa: E402

CHANNEL = "messaging"
POSTS_DIR = ("docs", "marketing", "content")
POSTS_MAX = 10                       # the posts offered in one list
WORDS_TEXT_MAX = 3500                # the caption text sent in one message (a message holds 4096 characters on the first app; the rest is the sentence around it)
REVIEW_STEP = {"kind": "media", "step": "review"}
NOT_OFFERED = "that post is not one of the posts offered"


def _only_messaging(op: str, channel) -> None:
    """The first refusal of every call: these are the messaging bridge's calls (the precedent is `attachment-hold`)."""
    if channel != CHANNEL:
        raise core.OpsError(f"{op} is the messaging bridge's call", 1)


def _checked(project: str, op: str, channel, sender) -> dict:
    """The channel rule, the context, then the sender's profile (the group `media-phone`)."""
    _only_messaging(op, channel)
    ctx = core.context(project)
    ops_actor.guard(ctx, op, channel, sender)
    return ctx


def _free_bytes(cfg: dict) -> int:
    return max(0, media.QUOTA_BYTES - media.usage(cfg["data_dir"]))


def _posts(project: str) -> list:
    """The stems of the posts a video may be for: a regular file (never a link) `docs/marketing/content/<stem>.md` of at most POST_LIMIT bytes, UTF-8 text,
    with a `- Network:` line and a ```script block. Newest first, then by name; at most POSTS_MAX."""
    folder = os.path.join(project, *POSTS_DIR)
    root = os.path.realpath(project)
    real = os.path.realpath(folder)
    if not real.startswith(root.rstrip(os.sep) + os.sep) or not os.path.isdir(folder):
        return []
    found = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    for name in names:
        if not name.endswith(".md"):
            continue
        relative = "/".join(POSTS_DIR) + "/" + name
        if not step_media._is_post(relative):
            continue
        path = os.path.join(folder, name)
        try:
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_size > step_media.POST_LIMIT:
                continue
            with open(path, "rb") as f:
                text = f.read(step_media.POST_LIMIT + 1).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if step_media.NETWORK_LINE.search(text) and step_media.has_script(text):
            found.append((-info.st_mtime, name[:-3]))
    return [stem for _, stem in sorted(found)[:POSTS_MAX]]


def video_phone_posts(project: str, channel=None, sender=None) -> dict:
    """The posts a video may be offered for, and the bounds on a recording: {"posts": [stem, ...], "max_bytes": the store's bound per recording, "free_bytes":
    the quota left}. Not an operation of its own: it is asked under the guard of `video-phone-in`."""
    ctx = _checked(project, "video-phone-in", channel, sender)
    return {"posts": _posts(project), "max_bytes": media.MEDIA_MAX_BYTES, "free_bytes": _free_bytes(ctx["cfg"])}


def video_phone_in(project: str, incoming: str, platform: str, ref: str, channel=None, sender=None) -> dict:
    """Keep the recording the bridge fetched into the incoming folder `incoming` (attachments.make_incoming): the media store bounds it, reads its type from its
    bytes and keeps it. Returns {"media": the id, "size", "type": "mp4" or "mov"}, never a path. The incoming folder is the bridge's: it is not removed here."""
    ctx = _checked(project, "video-phone-in", channel, sender)
    cfg = ctx["cfg"]
    if ops_actor.split(sender)[0] != platform or not isinstance(ref, str) or not ref:
        raise core.OpsError("the platform and the reference must be the sender's own", 2)
    try:
        folder = att.incoming_path(cfg["data_dir"], incoming)
    except att.FolderError:
        raise core.OpsError(att.GONE.format(platform=platform), 1) from None
    try:
        record = media.receive_file(cfg["data_dir"], os.path.join(folder, att.CONTENT))
    except media.MediaError as e:
        raise ops_media._media_error(e) from None
    except OSError:
        raise core.OpsError("the recording could not be read; nothing was kept", 1) from None
    return {"media": record["id"], "size": record["raw"]["size"], "type": record["raw"]["type"]}


def _caption_text(ctx: dict, task_id) -> dict:
    """The words of the review as text for the sender's chat: one line for each caption chunk, then the words in no chunk on one last line. Cut at the last line
    end before WORDS_TEXT_MAX characters, with `cut` true, when longer. {"words": text, "cut": bool, "revision": the revision an edit must name}."""
    seen = ops_media_edit.view(ctx, task_id)["view"]
    by_index = {w["index"]: w["text"] for w in seen["words"]}
    lines, used = [], set()
    for chunk in seen["chunks"]:
        lines.append(" ".join(by_index[i] for i in chunk["words"] if i in by_index))
        used.update(chunk["words"])
    rest = [w["text"] for w in seen["words"] if w["index"] not in used]
    if rest:
        lines.append(" ".join(rest))
    text, cut = "\n".join(lines), False
    if len(text) > WORDS_TEXT_MAX:
        text, cut = text[:WORDS_TEXT_MAX], True
        text = text.rsplit("\n", 1)[0] if "\n" in text else text
    return {"words": text, "cut": cut, "revision": seen["revision"]}


def video_phone_start(project: str, media_id, post, channel=None, sender=None) -> dict:
    """Start the video of a recording for one of the posts offered (`video_phone_posts`) and run it to the caption review. Returns what
    runtime/ops_media.py `video_new` returns and, when it stopped at the review, `words`, `cut` and `revision` (the caption text for the sender's chat)."""
    ctx = _checked(project, "video-phone-start", channel, sender)
    if not isinstance(post, str) or post not in _posts(project):
        raise core.OpsError(NOT_OFFERED, 2)
    out = ops_media.video_new(project, media_id, "/".join(POSTS_DIR) + "/" + post + ".md")
    if out.get("stopped") == "review":
        out = {**out, **_caption_text(ctx, out["task"])}
    return out


def _is_video_decision(ctx: dict, item: dict) -> bool:
    """Whether the open decision is the caption review question of a video, or the delivery decision of a video."""
    if item.get("status") != "open":
        return False
    payload = item.get("payload") or {}
    if item.get("kind") == "question":
        step = payload.get("step")
        return isinstance(step, dict) and {k: step.get(k) for k in ("kind", "step")} == REVIEW_STEP
    if item.get("kind") == "effect":
        found = ops_step_effects.step_effect_of(ctx, item)
        step = payload.get("step")
        return found is not None and found[0].get("step_kind") == step_media.KIND.name and isinstance(step, dict) and step.get("step") == step_media.GATE_STEP
    return False


def video_phone_reply(project: str, pending_id, text, channel=None, sender=None) -> dict:
    """Read the reply `text` to the open decision `pending_id`. A decision that is not a video's caption review or delivery gives {"action": "not-video"} (the
    bridge then treats the reply as it always did). Otherwise {"action": ...}: `continue` (the review is right: the bridge answers it and runs the video),
    `edited` (with `task`, `mode`, `answered`, `run` and the new caption text), `not_found` or `ambiguous` (with `wrong`), or `unknown`."""
    ctx = _checked(project, "video-phone-reply", channel, sender)
    try:
        item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    except core.OpsError:
        return {"action": "not-video"}
    if not _is_video_decision(ctx, item):
        return {"action": "not-video"}
    read = words.read(text)
    if read["kind"] == "continue":
        return {"action": "continue", "task": item["task_id"]} if item["kind"] == "question" else {"action": "unknown"}
    if read["kind"] != "corrections":
        return {"action": "unknown"}
    task = item["task_id"]
    seen = ops_media_edit.view(ctx, task)
    if seen["mode"] is None:
        raise core.OpsError(ops_media_edit.WAITING_ONLY, 1)
    try:
        edits = words.edits(seen["view"]["words"], read["pairs"])
    except words.WordsError as e:
        return {"action": e.code, "wrong": e.wrong}
    done = ops_media_edit.edit(ctx, task, seen["view"]["revision"], edits, actor=sender)
    return {"action": "edited", "task": task, "mode": done["mode"], "answered": done["answered"], "run": done["mode"] == "gate", **_caption_text(ctx, task)}


def video_phone_run(project: str, task_id, channel=None, sender=None) -> dict:
    """Run the video again after the caption review was answered or the captions were corrected at the delivery approval; when it stops at the review, the
    caption text is added as in `video_phone_start`."""
    ctx = _checked(project, "video-phone-run", channel, sender)
    out = ops_media.video_run(project, task_id)
    if out.get("stopped") == "review":
        out = {**out, **_caption_text(ctx, task_id)}
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
