"""What a finished render, a cover or a still is made into, and how it is stored: the platform file's read, one frame of a render
(cover), one frame of a recording framed as the render frames it (still), the PNG header's size, and the write that never rewrites.
No browser, no frames: both engines import this file, and `_inner.py` runs `cover`, `still` and `verify` on it alone. Standard library only.
"""
from __future__ import annotations

import os
import shutil
import struct
import tempfile

import _edl
import _media
from _text import Refusal
from _vocab import read_json


def read_platform(path) -> dict:
    """The platform file: a JSON object, or a Refusal (`null`, a list or a number would silently skip the platform's checks)."""
    platform = read_json(path)
    if not isinstance(platform, dict):
        raise Refusal("bad_platform", "platform")
    return platform


def write_once(src: str, final: str, digest: str) -> bool:
    """Copy `src` to `final` with O_EXCL and mode 0400; never rewrite. An existing file with the same bytes is a replay
    (True); an existing file with other bytes is refused. The copy is re-hashed."""
    try:
        fd = os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    except FileExistsError:
        if _media.sha256_file(final) != digest:
            raise Refusal("name_collision", "output") from None
        return True
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as fh:
            shutil.copyfileobj(fh, out, 1 << 20)
    except BaseException:
        os.unlink(final)
        raise
    if _media.sha256_file(final) != digest:
        os.unlink(final)
        raise Refusal("copy_failed", "output")
    return False


def make_cover(ffmpeg: str, video: str, out: str, offset_ms: int, duration: float) -> dict:
    """One PNG frame of the render at `offset_ms` (0600, written through a temporary name)."""
    if not isinstance(offset_ms, int) or offset_ms < 0 or offset_ms / 1000.0 >= duration:
        raise Refusal("bad_cover_offset", "offset")
    folder = os.path.dirname(os.path.abspath(out))
    os.makedirs(folder, mode=0o700, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".cover-", dir=folder)
    try:
        _media.run(_media.cover_argv(ffmpeg, os.path.abspath(video), offset_ms / 1000.0, "cover.png"), 120, cwd=work)
        part = os.path.join(work, "cover.png")
        if not os.path.isfile(part) or os.path.getsize(part) == 0:
            raise Refusal("cover_failed", "cover")
        os.chmod(part, 0o600)
        os.replace(part, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"path": os.path.abspath(out), "offset_ms": offset_ms, "sha256": _media.sha256_file(out)}


def png_size(path: str):
    """(width, height) of a PNG file from its header bytes, or None when the file is not a PNG."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def make_still(ffmpeg: str, recording: str, out: str, at_ms: int, facts: dict, size: tuple) -> dict:
    """One PNG frame of the recording at `at_ms`, framed as the render frames it into `size` (0600, written through a temporary name).
    `facts` are the recording's probe facts: the offset must lie inside the recording and the colour matrix is read from them the way
    `base` reads it for the edit list."""
    if not isinstance(at_ms, int) or isinstance(at_ms, bool) or at_ms < 0 or at_ms / 1000.0 >= facts["duration"]:
        raise Refusal("bad_still_offset", "at-ms")
    matrix = "auto" if facts.get("color_space") not in (None, "unknown", "bt709") else "bt709"
    folder = os.path.dirname(os.path.abspath(out))
    os.makedirs(folder, mode=0o700, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".still-", dir=folder)
    try:
        _media.run(_media.still_argv(ffmpeg, os.path.abspath(recording), at_ms / 1000.0, size, matrix, "still.png"), 120, cwd=work)
        part = os.path.join(work, "still.png")
        if not os.path.isfile(part) or os.path.getsize(part) == 0 or png_size(part) != tuple(size):
            raise Refusal("still_failed", "still")
        os.chmod(part, 0o600)
        os.replace(part, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"at_ms": at_ms, "sha256": _media.sha256_file(out), "width": size[0], "height": size[1], "bytes": os.path.getsize(out)}


def time_limit_for(data: dict, out_seconds: float, requested=None) -> int:
    lim = data["limits"]
    chosen = lim["render_seconds_base"] + lim["render_seconds_per_output_second"] * out_seconds if requested is None else requested
    return int(min(lim["render_seconds_max"], max(10, chosen)))


def check_documents(data, edl, beats, platform, vocab, allow) -> dict:
    """Check the edit list and the beats. Returns {mentions}; raises the first Refusal. `platform` None is for the callers that have no
    platform on purpose (`check` without a file, the storyboard); `render` and `verify` read theirs with `read_platform`."""
    first = _edl.check_edl(edl, data, vocab, allow, platform)
    second = _edl.check_beats(beats, edl, vocab)
    frame = (platform or {}).get("video") or {}
    for key, ok in (("fps_min", lambda v: edl["fps"] >= v), ("fps_max", lambda v: edl["fps"] <= v)):
        if frame.get(key) is not None and not ok(frame[key]):
            raise Refusal("fps_outside_platform", "edl.fps")
    return {"mentions": sorted(set(first["mentions"]) | set(second["mentions"]))}


def check_recording(ffprobe, src: str, edl: dict, limits: dict) -> dict:
    """The recording is the one the edit list was made from: not longer than the input limit, the same duration (within 0.05 s), the
    same sha256 and the same audio. Returns the probe it made; raises the first Refusal."""
    facts = _media.probe(ffprobe, src)
    if facts["duration"] > limits["input_seconds_max"]:
        raise Refusal("input_too_long", "input")
    if abs(facts["duration"] - edl["source"]["duration"]) > 0.05:
        raise Refusal("recording_changed", "input")
    if _media.sha256_file(src) != edl["source"]["sha256"]:
        raise Refusal("recording_changed", "input")
    if bool(facts["has_audio"]) != edl["source"]["has_audio"]:
        raise Refusal("recording_changed", "input")
    return facts
