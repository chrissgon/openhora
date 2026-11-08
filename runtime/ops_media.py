#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of a new video (package V1b2): a recording in, the list, the start, the run, the caption review, the edit, the download and the still.

The operations layer is the authority: every rule (who may call, which recording, which task, which file leaves) is checked here or in the modules this file
calls (runtime/media.py, runtime/ops_media_edit.py, runtime/steps.py); a shell only carries the call.

  media_in(project, path=None, channel=None, *, stream=None, length=None)    take a recording (an MP4 or MOV) into the media store: from a file on this computer
                                                                            (`media-in --path`), or from the page's upload (a stream and its declared length)
  media_list(project, channel=None)                                          the recordings, oldest first, with the task working on each and its state
  video_new(project, media_id, post, channel=None)                           one request with one step task of the kind `media` (no plan, no model), run to the
                                                                            caption review
  video_run(project, task_id, channel=None)                                  the person's own start of a ready video (after the review was answered, after an
                                                                            edit at the delivery approval, after a retry); the media kind alone
  captions_read(project, task_id, channel=None)                              the caption review as the person reads it (ops_media_edit.view)
  captions_edit(project, task_id, revision, edits=None, edits_file=None, channel=None)    the closed edits of runtime/captions.py, at the review or at the approval
  video_download(project, task_id, out=None, channel=None)                   the delivered render, hashed again from the file it is copied from, to a new file
  video_still(project, task_id, out=None, channel=None)                      the still of the face box, to a new file

The channel rule: the terminal, and a call that names no channel, pass. The page needs the operation's group (operations.refusal); any other channel is
refused. A video or a still is written only to a new file outside the project (a video never enters git); without `out` the file or the bytes are handed to
the caller, and only the page's route asks for that. Nothing here reaches a provider, a network or an effect: the delivery is approved by `approve`.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import media  # noqa: E402
import operations  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media_edit  # noqa: E402
import ops_steps  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import step_media  # noqa: E402
import steps  # noqa: E402

KIND = step_media.KIND.name                        # "media"
TASK_KEY = "video"                                 # = flows/new-video.json tasks[0].key
TASK_TEXT = ("Transcribe and cut the recording, stop for the caption review, render and verify it for the post's platform, and stop for "
             "the person's approval of the exact render. Nothing leaves this computer until the person approves its hash; the file is "
             "then downloadable, and nothing is published.")      # = flows/new-video.json tasks[0].text (a test compares)
TITLE_KEY = "TITLE_VIDEO_MAKE"                     # the task's title: phrases.en(TITLE_KEY) == "Make the video" (= the flow's task title)
RUN_KEYS = ("ok", "stopped", "pending", "done", "failed", "code", "field", "next", "task_state")   # what a start reports of ops_steps.run_step; never `detail`
CHUNK = 1024 * 1024
EDITS_MAX = 1024 * 1024
VIDEO_NAME = "video-{sha12}.mp4"                   # the name a downloaded video carries
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
STILL_LIMIT = step_media.COVER_LIMIT               # 16 MiB
NOT_A_VIDEO = "this task is not a new video"
OUT_INSIDE = "a video or a still is never written inside the project (it would enter git): name a file outside the project folder"
QUOTA_TEXT = ("the store of recordings is full: no operation removes a recording yet, and the retention frees one that was never delivered after 30 days "
              "(the folder is media/ in the project's data folder)")
USAGE_CODES = ("usage", "type", "size")


def _channel(ctx: dict, operation: str, channel) -> None:
    """The terminal, and a call that names no channel, pass. The page needs the operation's group (operations.refusal). Any other channel
    is refused (operations.not_enabled)."""
    if channel in (None, "terminal"):
        return
    if channel == "page":
        refused = operations.refusal(operation, "page", ctx["cfg"]["channels"])
        if refused is not None:
            raise core.OpsError(refused, 1)
        return
    raise core.OpsError(operations.not_enabled(operation, project_config.clean_name(channel)), 1)


def _media_error(e: "media.MediaError") -> "core.OpsError":
    """The OpsError of a refusal of the media store: usage, type and size are the caller's (2), every other one is a state of the store (1). A message of
    the store never holds a file's content, so it may be shown."""
    text = QUOTA_TEXT if e.code == "quota" else str(e)
    return core.OpsError(f"{text} ({e.code})", 2 if e.code in USAGE_CODES else 1)


def _sentence(failure: "steps.StepFailure") -> str:
    """The step's own sentence for a refusal: the field it names and what to do next."""
    record = steps.failure_record("", failure, "")
    return " ".join(p for p in (record["field"] and f"{record['field']}:", failure.next or record["code"].replace("_", " ")) if p)


def _task_state(ctx: dict, task_id):
    """The state of a task, or None when the task is gone."""
    try:
        return core._stored(ctx, ctx["store"].task_get, task_id)["state"]
    except core.OpsError:
        return None


def _video_task(ctx: dict, task_id) -> tuple:
    """(the task row, the recording's id, the engine's state) of a step task of the kind `media`; core.OpsError(NOT_A_VIDEO, 1) otherwise."""
    task = core._stored(ctx, ctx["store"].task_get, task_id)
    if not ctx["store"].is_step_task(task) or task.get("step_kind") != KIND:
        raise core.OpsError(NOT_A_VIDEO, 1)
    rid = (task.get("step_args") or {}).get("media")
    if not isinstance(rid, str) or not media.ID.fullmatch(rid):
        raise core.OpsError("this task names no recording", 1)
    try:
        state = steps.state_of(steps.kind_of(KIND), task.get("step_state"))
    except steps.StepFailure:
        raise core.OpsError("the state of this task cannot be read", 1) from None
    return task, rid, state


def _run_report(out: dict) -> dict:
    """What a start tells of the step's run: whether it ran, why not, and the keys of RUN_KEYS the engine's result holds."""
    started = out.get("ran") is not None
    report = {"started": started}
    if not started:
        report["reason"] = out.get("reason")
        return report
    report.update({k: out[k] for k in RUN_KEYS if k in out})
    return report


def media_in(project: str, path=None, channel=None, *, stream=None, length=None) -> dict:
    """Take a recording into the media store, from a file on this computer (`path`) or from the page's upload (`stream` of `length` bytes). Returns
    {"media": the id, "size", "type": "mp4" or "mov", "created_at"}; never a path. core.OpsError for every refusal, and nothing is kept then."""
    ctx = core.context(project)
    _channel(ctx, "media-in", channel)
    if (path is None) == (stream is None):
        raise core.OpsError("give the recording as a file (--path) or as the page's upload, one of them", 2)
    if stream is not None:
        if channel != "page":
            raise core.OpsError("only the page's upload hands a stream", 2)
        if not isinstance(length, int) or isinstance(length, bool) or length < 1:
            raise core.OpsError("an upload needs its length in bytes", 2)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        if stream is None:
            record = media.receive_file(data_dir, os.path.abspath(str(path)))
        else:
            record = media.receive(data_dir, stream, length)
    except media.MediaError as e:
        raise _media_error(e) from None
    except OSError:
        raise core.OpsError("the upload ended before its declared length; nothing was kept", 2) from None
    return {"media": record["id"], "size": record["raw"]["size"], "type": record["raw"]["type"], "created_at": record["created_at"]}


def media_list(project: str, channel=None) -> dict:
    """The recordings of the media store, oldest first. Returns {"recordings": [{"media", "created_at", "updated_at", "size", "type", "raw_kept",
    "task", "task_state", "delivered_at"}], "used_bytes", "quota_bytes"}; `size` and `type` are None after the retention removed the recording."""
    ctx = core.context(project)
    _channel(ctx, "media-list", channel)
    data_dir = ctx["cfg"]["data_dir"]
    rows = []
    for record in media.records(data_dir):
        raw = record["raw"]
        task = record["task"]
        rows.append({"media": record["id"], "created_at": record["created_at"], "updated_at": record["updated_at"],
                     "size": raw["size"] if raw else None, "type": raw["type"] if raw else None, "raw_kept": raw is not None,
                     "task": task, "task_state": _task_state(ctx, task) if task is not None else None,
                     "delivered_at": (record["delivered"] or {}).get("at")})
    return {"recordings": rows, "used_bytes": media.usage(data_dir), "quota_bytes": media.QUOTA_BYTES}


def video_new(project: str, media_id, post, channel=None) -> dict:
    """Start a new video from a recording and a post: one request with one step task of the kind `media` (no plan, no model), run to the caption review.
    Returns {"request", "task", "media", "started", ...}: `started` is whether the step ran; when it did not, `reason` says why and the task stays `ready`
    (video_run starts it later); otherwise the keys of RUN_KEYS the run reported. A failed step leaves the task `failed` (`retry` exists). core.OpsError
    for every refusal before anything is made."""
    ctx = core.context(project)
    _channel(ctx, "video-new", channel)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        record = media.load(data_dir, media.check_id(media_id))
    except media.MediaError as e:
        raise _media_error(e) from None
    if record["delivered"] is not None:
        raise core.OpsError("this recording was delivered; a new video of it starts from a new recording (media-in)", 1)
    if record["raw"] is None:
        raise core.OpsError("the recording was removed by the retention", 1)
    old = record["task"]
    if old is not None:
        state = _task_state(ctx, old)
        if state is not None and state not in ("cancelled", "failed"):
            raise core.OpsError(f"recording {media_id} is in task {old}, which is {state}: finish or cancel it first", 1)
    store = ctx["store"]
    try:
        made = steps.add_task(store, ctx["conn"], KIND, {"media": media_id, "post": post}, key=TASK_KEY, title=phrases.en(TITLE_KEY), text=TASK_TEXT)
    except steps.StepFailure as e:
        raise core.OpsError(_sentence(e), 2) from None
    except store.StoreError as e:
        raise core.OpsError(str(e), e.code) from None
    out = ops_steps.run_step(project, made["task"])
    return {"request": made["request"], "task": made["task"], "media": media_id, **_run_report(out)}


def video_run(project: str, task_id, channel=None) -> dict:
    """The person's own start of a ready new video (after the caption review was answered, after an edit at the delivery approval, after a retry).
    Returns {"task", "media", "started", ...} as video_new, without `request`."""
    ctx = core.context(project)
    _channel(ctx, "video-run", channel)
    _, rid, _ = _video_task(ctx, task_id)
    out = ops_steps.run_step(project, task_id)
    return {"task": task_id, "media": rid, **_run_report(out)}


def captions_read(project: str, task_id, channel=None) -> dict:
    """The caption review of a new video: what ops_media_edit.view returns ({"task", "media", "mode", "still", "view"})."""
    ctx = core.context(project)
    _channel(ctx, "captions-read", channel)
    return ops_media_edit.view(ctx, task_id)


def captions_edit(project: str, task_id, revision, edits=None, edits_file=None, channel=None) -> dict:
    """Edit the captions of a new video at the caption review or at the delivery approval. `edits` or `edits_file` (the text of the file; the terminal read
    it) is a JSON list of the closed edit objects of runtime/captions.py. Returns what ops_media_edit.edit returns: {"task", "mode", "applied", "answered"}."""
    ctx = core.context(project)
    _channel(ctx, "captions-edit", channel)
    if (edits is None) == (edits_file is None):
        raise core.OpsError("give the edits as JSON text (--edits) or as a file (--edits-file), one of them", 2)
    text = edits if edits is not None else edits_file
    if not isinstance(text, str):
        raise core.OpsError("the edits are a JSON list of edit objects (runtime/captions.py)", 2)
    if len(text.encode("utf-8", "replace")) > EDITS_MAX:
        raise core.OpsError("the edits are longer than 1 MiB", 2)
    try:
        listed = json.loads(text)
    except (ValueError, RecursionError):
        listed = None
    if not isinstance(listed, list):
        raise core.OpsError("the edits are a JSON list of edit objects (runtime/captions.py)", 2)
    return ops_media_edit.edit(ctx, task_id, revision, listed)


def _inside(project: str, folder: str) -> bool:
    root = os.path.realpath(project)
    real = os.path.realpath(folder)
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def _write_out(project: str, out, chunks) -> str:
    """Write the chunks to a new file `out`, mode 0600, never inside the project (a video never enters git). Returns the absolute path. A partial file is
    removed on every failure."""
    target = os.path.abspath(str(out))
    folder = os.path.dirname(target)
    if not os.path.isdir(folder):
        raise core.OpsError(f"the folder of {out} does not exist", 1)
    if _inside(project, folder):
        raise core.OpsError(OUT_INSIDE, 1)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | media.NOFOLLOW, 0o600)
    except FileExistsError:
        raise core.OpsError(f"{out} exists: name a new file", 1) from None
    except OSError:
        raise core.OpsError(f"{out} cannot be created", 1) from None
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in chunks:
                f.write(chunk)
    except BaseException:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    return target


def _need_out(out, channel) -> None:
    if out is None and channel != "page":
        raise core.OpsError("name the file to write: --out <path>", 2)


def _opened_delivered(data_dir: str, rid: str):
    """(the open binary file of the delivered render, its sha256, its size), hashed again from the descriptor it will be read from; core.OpsError when the
    render changed after the approval."""
    try:
        found = media.delivered_file(data_dir, rid)
    except media.MediaError as e:
        raise _media_error(e) from None
    try:
        fd = os.open(found["path"], os.O_RDONLY | media.NOFOLLOW)
    except OSError:
        raise core.OpsError("the delivered video cannot be opened (unreadable)", 1) from None
    source = os.fdopen(fd, "rb")
    try:
        digest, size = hashlib.sha256(), 0
        for chunk in iter(lambda: source.read(CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
        if digest.hexdigest() != found["sha256"]:
            raise core.OpsError("the delivered video changed after it was approved (stale)", 1)
        source.seek(0)
    except BaseException:
        source.close()
        raise
    return source, found["sha256"], size


def video_download(project: str, task_id, out=None, channel=None) -> dict:
    """The delivered render of a new video, only the exact one the approval named, hashed again. With `out`: written to a new file outside the project and
    {"task", "media", "path", "name", "sha256", "size"} returned. Without `out` (the page only): {"stream": the open binary file, which the caller closes,
    "name", "sha256", "size"}."""
    ctx = core.context(project)
    _channel(ctx, "video-download", channel)
    _, rid, _ = _video_task(ctx, task_id)
    _need_out(out, channel)
    source, digest, size = _opened_delivered(ctx["cfg"]["data_dir"], rid)
    name = VIDEO_NAME.format(sha12=digest[:12])
    if out is None:
        return {"stream": source, "name": name, "sha256": digest, "size": size}
    try:
        path = _write_out(project, out, iter(lambda: source.read(CHUNK), b""))
    finally:
        source.close()
    return {"task": task_id, "media": rid, "path": path, "name": name, "sha256": digest, "size": size}


def video_still(project: str, task_id, out=None, channel=None) -> dict:
    """The still the engine made for the face box of a new video. With `out`: written to a new file outside the project and
    {"task", "media", "path", "name", "sha256", "size"} returned. Without `out` (the page only): {"media_type": "image/png", "data": the bytes}."""
    ctx = core.context(project)
    _channel(ctx, "video-still", channel)
    _, rid, state = _video_task(ctx, task_id)
    _need_out(out, channel)
    name = ((state["steps"].get("still") or {}).get("result") or {}).get("name")
    if not isinstance(name, str) or not step_media.STILL_NAME.fullmatch(name):
        raise core.OpsError("no still was made for this video", 1)
    try:
        data = media.read_work(ctx["cfg"]["data_dir"], rid, name, STILL_LIMIT)
    except media.MediaError as e:
        raise _media_error(e) from None
    if not data.startswith(PNG_MAGIC):
        raise core.OpsError("the still is not a PNG image", 1)
    if out is None:
        return {"media_type": "image/png", "data": data}
    path = _write_out(project, out, iter((data,)))
    return {"task": task_id, "media": rid, "path": path, "name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
