#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of the rendered video (runtime/video.py): the card the page draws, the person's approval of the exact file and
caption, sending a video back with a comment, and the three reads of bytes (the video, its cover, the download of the approved
file). A sibling of runtime/ops.py, which exposes each of them under its name; no shell imports this file. The names every
module of the layer shares are read as `core.<name>` (runtime/ops_core.py).

  video_card(project, recording, platform)     what the page shows for one post of the recording: the current render (its hash,
                                   size, duration, frame size), the cover, the caption exactly as the post file has it with its
                                   hash, the approval and whether it still holds, the comment of the last send-back, and the
                                   download name. It reads records and small files and hashes a render once per file (the digest is kept under the file's
                                   identity, one hashing at a time per file), so the first card of a new render costs a pass over it.
  video_approve(project, recording, video_sha256, caption_sha256, platform, channel)   the one explicit action: approve the exact
                                   render and the exact caption the person saw. It hashes the render's bytes again, requires the
                                   hash to equal both what the person saw and the current render, requires the caption to hash to
                                   what the person saw, and records the approval with the date. Nothing publishes or schedules.
  video_send_back(project, recording, comment, platform)   return the post to the review step with the person's comment: the
                                   approval is removed and the record says the pipeline resumes at `review`.
  video_raw(project, recording, sha256)        the render, opened and verified, for the service to stream (a file object)
  video_cover(project, recording, sha256)      the cover PNG of that render, the same way
  media_still(project, recording, sha256)      the still frame (a PNG) of the recording itself that the pipeline made for the face-box
                                               picker (renderer `still`), chosen by the recording and the PNG's own sha256, the same way
  video_download(project, recording, platform) the approved file, the same way, with its file name; refused while the approval
                                   does not hold

The reads that return a file object (`video_raw`, `video_cover`, `video_download`) are for the local service on its loopback
socket: the caller must close the file. A refusal of the store (video.VideoError) becomes an OpsError that carries `kind`, as the
media store's does (ops_media.py).

What approval binds and why it is here: the record's `approvals.<platform>` holds {video_sha256, caption_sha256, caption,
platform, approved_at, approved_via}. A re-render or an edit of the caption makes it stale (video.approval_state); the scheduling
and publishing packages read it and refuse a stale one. Reading the page's channel policy is the service's; the
approval is for the terminal and the page only, and refuses any other channel in code.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import sys

import ops_core as core
import media
import video

APPROVE_CHANNELS = ("terminal", "page")
PIPELINE_STEP = "review"


def _refusal(error: "video.VideoError | media.MediaError") -> "core.OpsError":
    out = core.OpsError(str(error), 2 if error.kind in ("usage", "length") else 1)
    out.kind = error.kind
    return out


def _data_dir(project: str) -> str:
    return core.context(project)["cfg"]["data_dir"]


def _platform_of(record: dict, platform) -> str:
    """The platform the call is about: the one named, which must be a post of the recording; or the only one the recording has."""
    posts = record.get("posts") or {}
    if platform is not None:
        if platform not in posts:
            raise video.VideoError(f"the recording has no post for {str(platform)[:40]!r}; its posts are: {', '.join(sorted(posts)) or 'none'}", "not_found")
        return platform
    if len(posts) == 1:
        return next(iter(posts))
    raise video.VideoError("the recording has " + ("no post file yet" if not posts else "several posts: name the platform (" + ", ".join(sorted(posts)) + ")"), "usage")


def _caption(project: str, rel: str):
    """({"text", "sha256", "chars", "post_file"} or None, problem or None): the caption of a post file under docs/."""
    import ops_reads
    try:
        text = ops_reads.artifact(project, rel)["text"]
    except core.OpsError as e:
        return None, f"the post file cannot be read: {e}"
    found = video.caption_of(text)
    if found is None:
        return None, "the post file has no single ```post block"
    if len(found) > video.MAX_CAPTION:
        return None, f"the caption is over {video.MAX_CAPTION} characters"
    return {"text": found, "sha256": video.caption_sha256(found), "chars": len(found), "post_file": rel}, None


def _render(data_dir: str, recording: str):
    """(the current render's facts, problem or None). The pipeline's result names it; without one, the newest render file in the
    folder does, hashed through its descriptor."""
    result = video.read_result(data_dir, recording)
    if result is not None:
        name = video.render_name(result["sha256"])
        try:
            opened = video.open_render(data_dir, recording, result["sha256"])
        except video.VideoError as e:
            return None, f"the render the pipeline named cannot be served: {e}"
        opened.close()
        return {**result, "name": name, "bytes": opened.size, "source": "result"}, None
    newest = video.newest_render(data_dir, recording)
    if newest is None:
        return None, None
    name, sha12 = newest
    sha = video.sha_of_name(data_dir, recording, name, sha12)
    if sha is None:
        return None, "the newest render file does not hash to its name"
    size = None
    try:
        opened = video.open_render(data_dir, recording, sha)
        size = opened.size
        opened.close()
    except video.VideoError as e:
        return None, str(e)
    return {"sha256": sha, "bytes": size, "duration": None, "width": None, "height": None, "fps": None, "codec": None,
            "audio_codec": None, "cover": None, "name": name, "source": "folder"}, None


def _cover(data_dir: str, recording: str, render: dict):
    """The cover's facts if its file is there and is a PNG (that hashes to the renderer's report, when it gave one)."""
    expected = (render.get("cover") or {}).get("sha256")
    try:
        opened = video.open_cover(data_dir, recording, render["sha256"], expected)
    except video.VideoError:
        return None
    opened.close()
    return {"sha256": opened.sha256, "bytes": opened.size, "offset_ms": (render.get("cover") or {}).get("offset_ms")}


def _card(project: str, recording: str, platform) -> dict:
    data_dir = _data_dir(project)
    record = media.load(data_dir, media.check_id(recording))
    posts = record.get("posts") or {}
    out = {"recording": recording, "status": record.get("status"), "platforms": sorted(posts), "platform": None,
           "render": None, "cover": None, "caption": None, "approval": None, "sent_back": None, "can_download": False,
           "download_name": None, "problems": []}
    try:
        chosen = _platform_of(record, platform)
    except video.VideoError as e:
        if platform is not None:
            raise
        out["problems"].append(str(e))
        chosen = None
    render, problem = _render(data_dir, recording)
    if problem:
        out["problems"].append(problem)
    out["render"] = render
    if render is not None:
        out["cover"] = _cover(data_dir, recording, render)
    elif not problem:
        out["problems"].append("there is no render yet")
    if chosen is None:
        return out
    out["platform"] = chosen
    caption, problem = _caption(project, posts[chosen])
    if problem:
        out["problems"].append(problem)
    out["caption"] = caption
    approval = (record.get("approvals") or {}).get(chosen)
    if approval is not None:
        state, reasons = video.approval_state(approval, render["sha256"] if render else None, caption["sha256"] if caption else None)
        out["approval"] = {"state": state, "reasons": reasons, "approved_at": approval.get("approved_at"),
                           "video_sha256": approval.get("video_sha256"), "caption_sha256": approval.get("caption_sha256"),
                           "platform": chosen, "approved_via": approval.get("approved_via"), "caption": approval.get("caption")}
        if state == "approved":
            out["can_download"] = True
            out["download_name"] = video.download_name(chosen, approval["video_sha256"])
    back = record.get("sent_back")
    if isinstance(back, dict) and back.get("platform") == chosen:
        out["sent_back"] = {"comment": back.get("comment"), "at": back.get("at"), "render_sha256": back.get("render_sha256"),
                            "blocks_approval": _sent_back_blocks(record, chosen, render["sha256"] if render else None,
                                                                 caption["sha256"] if caption else None)}
    return out


def video_card(project: str, recording: str, platform: str | None = None) -> dict:
    """What the page shows for one post of the recording (see the module's text)."""
    try:
        return _card(project, recording, platform)
    except (video.VideoError, media.MediaError) as e:
        raise _refusal(e) from None


def video_approve(project: str, recording: str, video_sha256: str, caption_sha256: str, platform: str | None = None,
                  channel: str = "terminal") -> dict:
    """Approve the exact render and caption the person saw, and record it with the date. Refused from any channel but the
    terminal and the page, for a post that is not open, when there is no render, when the render is not the one the person saw
    (a re-render happened), when the file's bytes do not hash to what the person saw, and when the caption is not the one the
    person read. The file is hashed again here, never taken from the record."""
    if channel not in APPROVE_CHANNELS:
        raise core.OpsError("a video is approved from the terminal or the local page only", 1)
    try:
        video.check_sha(video_sha256, "video sha256")
        video.check_sha(caption_sha256, "caption sha256")
        data_dir = _data_dir(project)
        media.check_id(recording)
        record = media.load(data_dir, recording)
        chosen = _platform_of(record, platform)
        _need_open(record)
        render, problem = _render(data_dir, recording)
        if render is None:
            raise video.VideoError(problem or "there is no render yet: nothing to approve", "refused")
        if render["sha256"] != video_sha256:
            raise video.VideoError("the render changed since you watched it: reload the card and watch the new one before you approve", "refused")
        caption, problem = _caption(project, record["posts"][chosen])
        if caption is None:
            raise video.VideoError(problem or "the caption cannot be read", "refused")
        if caption["sha256"] != caption_sha256:
            raise video.VideoError("the caption changed since you read it: reload the card and read it again before you approve", "refused")
        if _sent_back_blocks(record, chosen, render["sha256"], caption["sha256"]):
            raise video.VideoError("this post was sent back with a comment and has not been rendered again nor had its caption edited since: "
                                   "it takes no approval until it changes (code sent_back)", "sent_back")
        opened = video.open_render(data_dir, recording, video_sha256, fresh=True)   # the bytes, hashed now
        size = opened.size
        opened.close()
        stamp = media.stamp()
        entry = {"video_sha256": video_sha256, "video_bytes": size, "caption_sha256": caption_sha256, "caption": caption["text"],
                 "platform": chosen, "approved_at": stamp, "approved_via": channel}

        def change(r: dict) -> None:
            _need_open(r)
            if _sent_back_blocks(r, chosen, render["sha256"], caption["sha256"]):   # a send-back in another tab, between the read and the write
                raise video.VideoError("this post was just sent back: it takes no approval until it changes (code sent_back)", "sent_back")
            r.setdefault("approvals", {})[chosen] = entry
            if isinstance(r.get("sent_back"), dict) and r["sent_back"].get("platform") == chosen:
                r["sent_back"] = None
            video.log_event(r, {"event": "approved", "platform": chosen, "at": stamp, "video_sha256": video_sha256,
                                "caption_sha256": caption_sha256, "via": channel})

        media.update(data_dir, recording, change)
        return _card(project, recording, chosen)
    except (video.VideoError, media.MediaError) as e:
        raise _refusal(e) from None


def _sent_back_blocks(record: dict, platform: str, render_sha, caption_sha) -> bool:
    """Whether a send-back still holds the post at the review step: the pipeline has not resumed (`resume` is pending for this platform)
    and the render and the caption are still the pair that was sent back. A new render or an edit of the caption lifts it."""
    back, resume = record.get("sent_back"), record.get("resume")
    if not isinstance(back, dict) or back.get("platform") != platform:
        return False
    if not isinstance(resume, dict) or resume.get("platform") != platform:
        return False
    return back.get("render_sha256") == render_sha and back.get("caption_sha256") == caption_sha


def _need_open(record: dict) -> None:
    if record.get("status") != "open":
        raise video.VideoError(f"this post is {record.get('status')}: it takes no new approval", "refused")


def video_send_back(project: str, recording: str, comment: str, platform: str | None = None) -> dict:
    """Return the post to the review step with the person's comment: any approval of it is removed, and the record says the
    pipeline resumes at `review` (`resume`), for the media pipeline's "Prepare again" to read. The comment is the person's note
    on the video, never transcript text, and is kept with the date."""
    try:
        text = video.clean_comment(comment)
        data_dir = _data_dir(project)
        media.check_id(recording)
        record = media.load(data_dir, recording)
        chosen = _platform_of(record, platform)
        _need_open(record)
        render, _ = _render(data_dir, recording)
        caption, _ = _caption(project, record["posts"][chosen])
        stamp = media.stamp()

        def change(r: dict) -> None:
            _need_open(r)
            approvals = r.setdefault("approvals", {})
            had = approvals.pop(chosen, None) is not None
            r["sent_back"] = {"platform": chosen, "comment": text, "at": stamp, "render_sha256": render["sha256"] if render else None,
                              "caption_sha256": caption["sha256"] if caption else None}
            r["resume"] = {"step": PIPELINE_STEP, "reason": "sent_back", "platform": chosen, "at": stamp}
            video.log_event(r, {"event": "sent_back", "platform": chosen, "at": stamp, "approval_removed": had})

        media.update(data_dir, recording, change)
        return _card(project, recording, chosen)
    except (video.VideoError, media.MediaError) as e:
        raise _refusal(e) from None


def _stream(opened: "video.Opened", media_type: str, **more) -> dict:
    return {"file": opened.file, "size": opened.size, "media_type": media_type, "sha256": opened.sha256, "name": opened.name, **more,
            "opened": opened}


def video_raw(project: str, recording: str, sha256: str) -> dict:
    """The render named by its recording and its sha256, opened and verified: {"file", "size", "media_type": "video/mp4",
    "sha256", "name"}. The caller closes the file."""
    try:
        return _stream(video.open_render(_data_dir(project), recording, sha256), "video/mp4")
    except (video.VideoError, media.MediaError) as e:
        raise _refusal(e) from None


def video_cover(project: str, recording: str, sha256: str) -> dict:
    """The cover PNG of the render `sha256`: {"file", "size", "media_type": "image/png", "sha256", "name"}. The caller closes it."""
    try:
        data_dir = _data_dir(project)
        result = video.read_result(data_dir, recording)
        expected = ((result or {}).get("cover") or {}).get("sha256") if result and result["sha256"] == sha256 else None
        return _stream(video.open_cover(data_dir, recording, sha256, expected), "image/png")
    except (video.VideoError, media.MediaError) as e:
        raise _refusal(e) from None


def media_still(project: str, recording: str, sha256: str) -> dict:
    """The still frame of a recording, named by the recording and the PNG's sha256: {"file", "size", "media_type": "image/png", "sha256",
    "name"}. The file is `still-<sha12>.png` in the recording's folder, opened without following a link, a PNG, at most 8 MiB, and the open
    descriptor's hash must equal the sha256 asked for. The caller closes it."""
    try:
        return _stream(video.open_still(_data_dir(project), recording, sha256), "image/png")
    except (video.VideoError, media.MediaError) as e:
        raise _refusal(e) from None


def video_download(project: str, recording: str, platform: str | None = None) -> dict:
    """The approved file of a post, for the person to keep and post by hand: refused while no approval holds (none, or stale
    because the render or the caption changed since). {"file", "size", "media_type", "sha256", "name", "filename"}."""
    try:
        card = _card(project, recording, platform)
        approval = card["approval"]
        if approval is None or approval["state"] != "approved":
            raise video.VideoError("nothing is approved for download: approve this video and caption first" if approval is None
                                   else "the approval no longer holds (" + " and ".join(r.replace("_", " ") for r in approval["reasons"]) + "): approve again", "refused")
        opened = video.open_render(_data_dir(project), recording, approval["video_sha256"])
        return _stream(opened, "video/mp4", filename=card["download_name"])
    except (video.VideoError, media.MediaError) as e:
        raise _refusal(e) from None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
