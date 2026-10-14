#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The rendered video of a short post, as the page sees it: which file it is, whether its bytes are the ones its name says,
and what the person's approval of it binds. No model is called here, no network, and no
file outside <data_dir>/media/<recording>/ is opened (D7: the store is outside every repository).

What a render is (providers/renderer/README.md): `render-<sha12>.mp4`, written once by the renderer, mode 0400, never
rewritten, its name the first 12 hex characters of the sha256 of its bytes. A later render of the same recording is another
file with another name. The renderer's result for the recording (its `render` verb's JSON: `sha256`, `bytes`, `output`,
`cover`) is kept beside it as `render.json`, and the cover frame as `cover-<sha12>.png`; the still frame of a recording (the face-box picker's picture) is `still-<sha12>.png`, read the same way
(`open_still`); the media pipeline (a later package)
writes both. This module reads them and trusts neither: the file's bytes are hashed through the open descriptor.

Reading a file, `open_render` / `open_cover`:

  - the file is chosen by the recording id (16 hex, issued by code) and the sha256 (64 hex) the caller names, never by a
    path: the name is built here as `render-<sha[:12]>.mp4` / `cover-<sha[:12]>.png`, and nothing else can be asked for. The
    recording's raw file, an asset, a record and a folder are not names this module can build;
  - it is opened with O_NOFOLLOW relative to the recording's folder, which is itself opened with O_NOFOLLOW|O_DIRECTORY: a
    link at either place is refused, and so is a file that is not a regular file, has another link, or is over its limit;
  - the first bytes must be an MP4 (`ftyp`, read by media.sniff) or a PNG;
  - the open descriptor is hashed and the digest must equal the sha256 asked for. A file swapped between the hash and the read
    cannot be served, because the bytes are read from the descriptor that was hashed. The digest of a descriptor is kept for
    the next range request of the same file under its identity (device, inode, size, modification and change time of the
    descriptor): a render is 0400 and never rewritten, a replacement is another inode and a change moves the times, so a
    range request does not hash a hundred megabytes again, and an approval always does (`fresh`). Hashing is single flight per
    file: requests for one file hash it one at a time, so a cold cache costs one pass however many cards ask at once. What this does
    not catch: a write in place by the same user (who owns the file and can chmod it) while a stream is going is seen only by the next
    request, whose identity has moved; it is out of scope, since the person's own account can change the file under any check.

The approval, `approval_state`: the person's approval is a record in the recording's record.json (`approvals.<platform>`) that
binds the sha256 of the exact file and the sha256 of the caption text, the platform and the date. It is valid only while
both still equal the current render's and the current caption's: a re-render or an edit of the caption makes it `stale`, and
nothing downloads or publishes on a stale one. This module does the comparison; runtime/ops_video.py does the reading and
the writing, under the store's record lock (media.update).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading

import media

RENDER_RESULT = "render.json"          # the renderer's `render` result for the recording, written by the media pipeline
RESULT_MAX_BYTES = 256 * 1024
VIDEO_MAX_BYTES = media.MEDIA_MAX_BYTES  # a render is never larger than a recording may be
COVER_MAX_BYTES = 8 * 1024 * 1024
STILL_MAX_BYTES = 8 * 1024 * 1024        # a still frame of a recording (the renderer's `still`), the same limit as a cover
HASH_CHUNK = 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}")
RENDER_NAME = re.compile(r"render-([0-9a-f]{12})\.mp4")
PLATFORM = media.PLATFORM
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_COMMENT = 1000
MAX_CAPTION = 10000
LOG_MAX = 50                            # events kept in a record's approval log
VERIFIED_MAX = 64

_VERIFIED: dict = {}
_VERIFIED_LOCK = threading.Lock()
_HASHING: dict = {}                     # file identity -> the lock of the one hashing of it that runs (single flight)


class VideoError(Exception):
    """A refusal of this module. `kind` is the family: usage (the request is malformed), not_found (no such recording or file),
    refused (a rule of the work), too_large, type (the bytes are not what the name says)."""

    def __init__(self, message: str, kind: str = "refused"):
        super().__init__(message)
        self.kind = kind


# --- the names --------------------------------------------------------------------------------------------------------------


def check_sha(value, what="sha256") -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise VideoError(f"the {what} is 64 lowercase hexadecimal characters", "usage")
    return value


def render_name(sha256: str) -> str:
    return f"render-{check_sha(sha256)[:12]}.mp4"


def cover_name(sha256: str) -> str:
    return f"cover-{check_sha(sha256)[:12]}.png"


def still_name(sha256: str) -> str:
    return f"still-{check_sha(sha256)[:12]}.png"


def download_name(platform: str, sha256: str) -> str:
    """The file name the person gets: the platform and the first 12 hex characters of the hash, nothing that names a project or a
    person (a name is public the moment the file is posted)."""
    if not isinstance(platform, str) or not PLATFORM.fullmatch(platform):
        raise VideoError("a platform is a lowercase word", "usage")
    return f"short-video-{platform}-{check_sha(sha256)[:12]}.mp4"


# --- opening and verifying a file ------------------------------------------------------------------------------------------


class Opened:
    """A file opened for reading and checked: `file` (a binary file object; close it), `size`, `sha256`, `name`."""

    def __init__(self, file, size: int, sha256: str, name: str):
        self.file, self.size, self.sha256, self.name = file, size, sha256, name

    def close(self) -> None:
        self.file.close()


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _digest(f) -> str:
    h = hashlib.sha256()
    f.seek(0)
    while True:
        block = f.read(HASH_CHUNK)
        if not block:
            break
        h.update(block)
    f.seek(0)
    return h.hexdigest()


def _open_in(data_dir: str, recording: str, name: str, limit: int, what: str):
    """The file `name` of the recording's folder, opened and checked as a plain file: (file object, fstat). VideoError otherwise."""
    folder = media.folder_of(data_dir, media.check_id(recording))
    try:
        media._check_dir(folder, "the recording's folder")
        dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except (OSError, media.MediaError):
        raise VideoError(f"there is no {what} for this recording", "not_found") from None
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        except OSError:
            raise VideoError(f"there is no {what} for this recording", "not_found") from None
    finally:
        os.close(dfd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise VideoError(f"the {what} is not a plain file", "refused")
        if info.st_size <= 0 or info.st_size > limit:
            raise VideoError(f"the {what} is {info.st_size} bytes, over the {limit} this page serves" if info.st_size else f"the {what} is empty",
                             "too_large" if info.st_size else "refused")
        return os.fdopen(fd, "rb"), info
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def digest_of(f, info, fresh: bool = False) -> str:
    """The sha256 of the open file, hashed through its descriptor. Not fresh: the digest remembered under the descriptor's identity is
    returned when there is one. Single flight: requests for the same file (the same identity) hash one at a time, so a cold cache costs
    one pass over the file however many cards ask at once; the others find the digest the first one left. Fresh (an approval): always
    hashed now, still one at a time per file."""
    key = _identity(info)
    if not fresh:
        with _VERIFIED_LOCK:
            known = _VERIFIED.get(key)
        if known is not None:
            return known
    with _VERIFIED_LOCK:
        flight = _HASHING.setdefault(key, threading.Lock())
    with flight:
        if not fresh:
            with _VERIFIED_LOCK:
                known = _VERIFIED.get(key)
            if known is not None:
                return known
        got = _digest(f)
        with _VERIFIED_LOCK:
            if len(_VERIFIED) >= VERIFIED_MAX:
                _VERIFIED.clear()
            _VERIFIED[key] = got
            if _HASHING.get(key) is flight:
                del _HASHING[key]
    return got


def _verified(f, info, expected: str, fresh: bool) -> None:
    if digest_of(f, info, fresh) != expected:
        raise VideoError("the bytes of this file are not the ones its name says (its sha256 differs); it is not served", "refused")


def open_render(data_dir: str, recording: str, sha256: str, fresh: bool = False) -> Opened:
    """The render whose bytes hash to `sha256`, opened for reading: the descriptor that was hashed is the one the caller reads.
    VideoError: not_found (no such file), usage (a malformed id or hash), too_large, type (not an MP4), refused (a link, another
    kind of file, or bytes whose hash differs)."""
    name = render_name(sha256)
    f, info = _open_in(data_dir, recording, name, VIDEO_MAX_BYTES, "render")
    try:
        found = media.sniff(f.read(media.SNIFF_BYTES))
        f.seek(0)
        if found != ("video", "mp4"):
            raise VideoError("this file is not an MP4 video", "type")
        _verified(f, info, sha256, fresh)
        return Opened(f, info.st_size, sha256, name)
    except BaseException:
        f.close()
        raise


def open_cover(data_dir: str, recording: str, render_sha256: str, expected_sha256=None) -> Opened:
    """The cover frame of the render `render_sha256`: `cover-<sha12>.png`, a PNG. When the renderer's result named the PNG's own
    sha256 (`expected_sha256`) the bytes must hash to it."""
    name = cover_name(render_sha256)
    f, info = _open_in(data_dir, recording, name, COVER_MAX_BYTES, "cover")
    try:
        if media.sniff(f.read(media.SNIFF_BYTES)) != ("image", "png"):
            raise VideoError("this file is not a PNG image", "type")
        f.seek(0)
        got = _digest(f)
        if expected_sha256 is not None and got != expected_sha256:
            raise VideoError("the bytes of the cover are not the ones the renderer reported", "refused")
        return Opened(f, info.st_size, got, name)
    except BaseException:
        f.close()
        raise


def open_still(data_dir: str, recording: str, sha256: str) -> Opened:
    """The still frame of the recording whose own bytes hash to `sha256`: `still-<sha12>.png`, a PNG, opened as a plain file inside the
    recording's folder (no link, one name, at most STILL_MAX_BYTES). The sha256 is the PNG's, as the renderer reported it and the pipeline
    recorded it: the open descriptor is hashed and must equal it, and the bytes are read from that same descriptor. VideoError: not_found,
    usage (a malformed id or hash), too_large, type (not a PNG), refused (a link, another kind of file, or bytes whose hash differs)."""
    name = still_name(sha256)
    f, info = _open_in(data_dir, recording, name, STILL_MAX_BYTES, "still")
    try:
        if media.sniff(f.read(media.SNIFF_BYTES)) != ("image", "png"):
            raise VideoError("this file is not a PNG image", "type")
        f.seek(0)
        _verified(f, info, sha256, False)
        return Opened(f, info.st_size, sha256, name)
    except BaseException:
        f.close()
        raise


# --- the renderer's result and the caption ---------------------------------------------------------------------------------


def _small_number(value, low=0, high=10 ** 12):
    return value if type(value) in (int, float) and not isinstance(value, bool) and low <= value <= high else None


def _word(value, limit=40):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:+ /-]{1,%d}" % limit, value) else None


def read_result(data_dir: str, recording: str):
    """The renderer's result for the recording as kept by the pipeline (render.json), reduced to the facts the page shows: None
    when there is none or it cannot be read as one; else {"sha256", "bytes", "duration", "width", "height", "fps", "codec",
    "audio_codec", "cover": {"offset_ms", "sha256"} | None}. Every field is checked; nothing else survives."""
    folder = media.folder_of(data_dir, media.check_id(recording))
    try:
        dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        fd = os.open(RENDER_RESULT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError:
        return None
    finally:
        os.close(dfd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > RESULT_MAX_BYTES:
            return None
        with os.fdopen(fd, "rb") as f:
            fd = None
            value = json.loads(f.read(RESULT_MAX_BYTES + 1).decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    if not isinstance(value, dict) or not isinstance(value.get("sha256"), str) or not SHA256.fullmatch(value["sha256"]):
        return None
    out_facts = value.get("output") if isinstance(value.get("output"), dict) else {}
    cover = value.get("cover") if isinstance(value.get("cover"), dict) else None
    cover_sha = cover.get("sha256") if cover and isinstance(cover.get("sha256"), str) and SHA256.fullmatch(cover["sha256"]) else None
    return {
        "sha256": value["sha256"],
        "bytes": _small_number(out_facts.get("bytes", value.get("bytes"))),
        "duration": _small_number(out_facts.get("duration", value.get("out_seconds")), 0, 86400),
        "width": _small_number(out_facts.get("width"), 0, 20000), "height": _small_number(out_facts.get("height"), 0, 20000),
        "fps": _small_number(out_facts.get("fps"), 0, 1000), "codec": _word(out_facts.get("codec")),
        "audio_codec": _word(out_facts.get("audio_codec")),
        "cover": {"offset_ms": _small_number(cover.get("offset_ms"), 0, 86400000), "sha256": cover_sha} if cover else None,
    }


def newest_render(data_dir: str, recording: str):
    """The newest `render-<sha12>.mp4` of the recording's folder by its modification time (the folder holds one per render
    until retention removes them), as (name, sha12), or None. Used only when the pipeline has not kept a result."""
    folder = media.folder_of(data_dir, media.check_id(recording))
    best = None
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                found = RENDER_NAME.fullmatch(entry.name)
                if not found:
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                if best is None or info.st_mtime_ns > best[0]:
                    best = (info.st_mtime_ns, entry.name, found.group(1))
    except OSError:
        return None
    return None if best is None else (best[1], best[2])


def sha_of_name(data_dir: str, recording: str, name: str, sha12: str):
    """The full sha256 of the render file `name`, hashed through its open descriptor, or None when it cannot be read or does not
    hash to its name."""
    try:
        f, info = _open_in(data_dir, recording, name, VIDEO_MAX_BYTES, "render")
    except VideoError:
        return None
    try:
        got = digest_of(f, info)
        return got if got.startswith(sha12) else None
    finally:
        f.close()


def caption_of(text: str):
    """The caption in a post file: the exact text of its first ```post block (the form the payload builder reads), or None when
    there is none, it is not closed, or there are two. Line ends are \\n; the text is stripped of blank lines at both ends."""
    fence = re.compile(r"^```([\w-]*)\s*$")
    name, buf, found = None, [], []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = fence.match(line)
        if name is None:
            if m and m.group(1) == "post":
                name, buf = "post", []
        elif m and m.group(1) == "":
            found.append("\n".join(buf).strip("\n"))
            name = None
        else:
            buf.append(line)
    if name is not None or len(found) != 1:
        return None
    return found[0]


def caption_sha256(caption: str) -> str:
    return hashlib.sha256(caption.encode("utf-8")).hexdigest()


# --- the approval -----------------------------------------------------------------------------------------------------------


def approval_state(approval, render_sha256, caption_sha256_):
    """('none', []) with no approval; ('approved', []) when it binds this render and this caption; ('stale', reasons) otherwise,
    the reasons being "render_changed" and "caption_changed". Pure."""
    if not isinstance(approval, dict):
        return "none", []
    reasons = []
    if approval.get("video_sha256") != render_sha256:
        reasons.append("render_changed")
    if approval.get("caption_sha256") != caption_sha256_:
        reasons.append("caption_changed")
    return ("stale", reasons) if reasons else ("approved", [])


def clean_comment(value) -> str:
    """The person's comment on a video sent back: text, control characters removed, at most MAX_COMMENT characters, not empty."""
    if not isinstance(value, str):
        raise VideoError("the comment is text", "usage")
    text = CONTROL.sub(" ", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not text:
        raise VideoError("sending a video back needs a comment: say what to change", "usage")
    if len(text) > MAX_COMMENT:
        raise VideoError(f"the comment is at most {MAX_COMMENT} characters", "usage")
    return text


def log_event(record: dict, event: dict) -> None:
    """Append an event to the record's approval log, keeping the last LOG_MAX."""
    log = record.setdefault("approval_log", [])
    log.append(event)
    del log[:-LOG_MAX]


if __name__ == "__main__":
    import sys
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
