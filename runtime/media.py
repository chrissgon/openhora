#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The media store: where a person's recording (and the images and clips of a post's slots) lives, how it gets in, and
when it is deleted. No model is called here and no file of a project is read: the store is <data_dir>/media/, outside
every repository, and nothing under it enters a run copy (contracts/runtime.md, limit L2).

Layout, every folder mode 0700 and every file mode 0600:

  <data_dir>/media/                       the store; .upload.lock (one upload at a time per project), .record.lock
  <data_dir>/media/<id>/                  one recording, <id> issued by code (16 hex characters, never a name from a
                                          model or a person)
  <data_dir>/media/<id>/record.json       the record code writes: status, the raw file's facts, the post files (one per
                                          platform), the asset slots, the tasks, the dates the retention reads
  <data_dir>/media/<id>/raw.mov|raw.mp4   the recording as it arrived (named by its type, never by the person's file name)
  <data_dir>/media/<id>/assets/<slot>.<ext>   the file of one asset slot
  <data_dir>/media/<id>/render-<sha12>.mp4, cover*, payload/, transcript.json, ...   written by later packages

Intake, `receive(data_dir, stream, length, ...)`, one function for the page's route and for `media-in`:

  - the Content-Length is bounded before one byte is read (MEDIA_MAX_BYTES for a recording; for an asset, the largest
    asset limit first, then the limit of its type once the first bytes name the type);
  - the type is read from the bytes (an MP4 or MOV `ftyp` box at offset 4; PNG, JPEG and WebP signatures), never from the
    name or the Content-Type; a wrong type is refused before a file exists;
  - free space (statvfs) is at least the length plus FREE_MARGIN_BYTES, the store is under QUOTA_BYTES, fewer than
    MAX_RENDERS renders are kept, and no other upload of the project runs (a lock, taken without waiting), all before the
    body is read;
  - the body is written in chunks of CHUNK_BYTES to a temporary name opened with O_CREAT|O_EXCL|O_NOFOLLOW in a folder
    checked with lstat (a directory, not a link, ours, 0700), hashed (sha256) as it is written, never whole in memory;
  - it is linked to its final name (os.link: it never replaces a recording's raw file) only after the length, the hash
    and the checks of the file (ffprobe for a video, the header for an image) passed; the temporary file is deleted on
    any failure, disconnect, timeout or full disk (507), and a recording folder this call made is removed with it;
  - the upload has a deadline, UPLOAD_MAX_SECONDS, that holds against a slow sender: every read is armed with the time left
    (a stream's settimeout, at most STALL_SECONDS) and uses read1, which returns what has arrived instead of waiting for all
    n bytes; when it passes the upload is refused and the upload lock is released;
  - only an open recording takes a file (not published, cancelled, scheduled, frozen or purged); that and the slot are checked
    again under the record lock when the record is written, so a freeze, a mark or a dropped slot during the upload is a
    refusal (409 or 404), not an error;
  - an asset is stored as <slot>-<sha12>.<ext>: a new file for the slot is put in place first and the old file is deleted only
    after the record names the new one, so a failed swap loses nothing;
  - a recording must have exactly one video stream and at most one audio stream (data and metadata streams, which an iPhone
    adds, are not counted), last at most MAX_SECONDS, and not be HDR (refused with the way to record again);
  - the file name header is a label: it is sanitised (never a reason to refuse an upload).

What intake does NOT establish: a slot's image or clip is checked by its header and, for a clip, by ffprobe; it is not decoded
here and stays UNTRUSTED. A later package (P5) normalises it by decoding it once inside its container; nothing may open it
with a general-purpose decoder before that. A video is read only with the demuxer forced (`-f mov`), `-protocol_whitelist file`
and `-enable_drefs 0` (no reference to another file), by ffprobe here and by every other reader of a recording.

Retention, `purge(data_dir, now, ...)` (decision D7), run by code in a dispatcher round and by `media-purge`, never by a
task: the raw recording, the transcript, the base list, the annotation file, the assets and the edit task's run folders
go RAW_DAYS after the post was published or cancelled; the renders, the covers and the payload folder go RENDER_DAYS
after publication; the media of an abandoned post (status open, untouched) go ABANDONED_DAYS after its last change.

Usage (a library; the shells are runtime/ops_media.py, runtime/cli.py media-in, media-list and media-purge, and
runtime/service.py): python3 runtime/media.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
import unicodedata
import urllib.parse

MEDIA_DIR = "media"
RECORD = "record.json"
ASSETS = "assets"
UPLOAD_LOCK = ".upload.lock"
RECORD_LOCK = ".record.lock"

# The limits. Each has a test named after it (runtime/tests/test_media_limits.py).
MEDIA_MAX_BYTES = 1024 * 1024 * 1024        # a recording: 1 GiB (D8)
MAX_SECONDS = 300                           # a recording: 300 s (D8, amended 2026-10-13: the 180 s of the plan was raised)
MIN_BYTES = 32                              # the least a body can be to hold a container header
CHUNK_BYTES = 1024 * 1024
SNIFF_BYTES = 4096
FREE_MARGIN_BYTES = 256 * 1024 * 1024       # free space must exceed the length by this much
QUOTA_BYTES = 8 * 1024 * 1024 * 1024        # the store of one project
MAX_RENDERS = 20                            # renders kept in the store; a new upload is refused at the cap
UPLOAD_MAX_SECONDS = 1800                   # wall time of one upload, held against a slow sender too (every read is armed with the time left)
STALL_SECONDS = 30                          # the longest one read may wait for the next bytes
PROBE_TIMEOUT = 60
RECORDING_MAX_SIDE = 8192                   # pixels, width and height of a recording
IMAGE_MAX_BYTES = 25 * 1024 * 1024          # an image for a slot
CLIP_MAX_BYTES = 256 * 1024 * 1024          # a clip for a slot
CLIP_MAX_SECONDS = 60
IMAGE_MAX_SIDE = 8192
IMAGE_MAX_PIXELS = 50_000_000
NAME_MAX_CHARS = 120
NAME_MAX_BYTES = 255
HEADER_NAME_MAX = 1024                      # the longest raw header value read as a file name

# Retention (D7). ABANDONED_DAYS is the recommendation for the number the maintainer sets.
RAW_DAYS = 7
RENDER_DAYS = 30
ABANDONED_DAYS = 30
STRAY_DAYS = 1                              # a temporary file or a folder with no record, older than this, is removed

STATUSES = ("open", "scheduled", "published", "cancelled")
ID = re.compile(r"[0-9a-f]{16}")
SLOT = re.compile(r"[0-9a-f]{12}")
RENDER = re.compile(r"render-[0-9a-f]{12}\.mp4")
PART = re.compile(r"\.incoming-[0-9a-f]{16}\.part")
SLOT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
POST_PATH = re.compile(r"docs/[A-Za-z0-9][A-Za-z0-9._/-]{0,200}\.md")
PLATFORM = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")

MOV_BRANDS = (b"qt  ",)
MP4_BRANDS = (b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash", b"3gp4", b"3gp5")
HEIF_BRANDS = (b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"avif")
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
BAD_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")

HDR_MESSAGE = ("this recording is HDR (HLG, PQ or Dolby Vision), which is not supported yet: record again with HDR off "
               "(iPhone: Settings, Camera, Record Video, turn off HDR Video) or export an SDR copy")
HEIF_MESSAGE = "this image is HEIC or HEIF: export it as JPEG and attach that"


class MediaError(Exception):
    """A refusal of the store. `kind` is the family of the refusal, which a shell turns into its own word: usage (the
    request is malformed), length (no Content-Length), too_large, type (the bytes are not a type this route takes),
    refused (a rule of the work: busy, quota, frozen, a recording that already has its file), no_space, not_found."""

    def __init__(self, message: str, kind: str = "refused"):
        super().__init__(message)
        self.kind = kind


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(moment=None) -> str:
    return (moment or now_utc()).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(text) -> datetime.datetime:
    return datetime.datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


# --- the folders ------------------------------------------------------------------------------------------------------


def root_of(data_dir: str) -> str:
    """<data_dir>/media"""
    return os.path.join(data_dir, MEDIA_DIR)


def new_id() -> str:
    """A recording id, issued by code: 16 hexadecimal characters from the system's random source."""
    return secrets.token_hex(8)


def check_id(value, what="recording") -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise MediaError(f"the {what} id is 16 lowercase hexadecimal characters; one is issued by code", "usage")
    return value


def check_slot(value) -> str:
    if not isinstance(value, str) or not SLOT.fullmatch(value):
        raise MediaError("the slot id is 12 lowercase hexadecimal characters; slot ids are issued by code", "usage")
    return value


def _check_dir(path: str, what: str) -> None:
    """The folder is a real directory (not a link), ours, closed to others (lstat, never stat)."""
    try:
        info = os.lstat(path)
    except OSError as e:
        raise MediaError(f"{what} cannot be read: {e.strerror}", "refused") from None
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise MediaError(f"{what} is not a plain folder", "refused")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MediaError(f"{what} is not owned by this user", "refused")
    if info.st_mode & 0o077:
        raise MediaError(f"{what} is open to other users (its mode must be 0700)", "refused")


def _private_dir(path: str, what: str) -> None:
    """Make the folder (mode 0700) when it is not there, then check it with lstat."""
    if not os.path.lexists(path):
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        except OSError as e:
            raise MediaError(f"{what} cannot be made: {e.strerror}", "refused") from None
    _check_dir(path, what)


def ensure_root(data_dir: str) -> str:
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    root = root_of(data_dir)
    _private_dir(root, "the media store")
    return root


def folder_of(data_dir: str, rid: str) -> str:
    return os.path.join(root_of(data_dir), check_id(rid))


# --- the record ---------------------------------------------------------------------------------------------------------


class _Lock:
    """An flock on a file of the store. blocking=False raises BlockingIOError at once when another holder has it."""

    def __init__(self, path: str, blocking: bool):
        self.path, self.blocking, self.fd = path, blocking, None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB))
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _write_json(path: str, value) -> None:
    temporary = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(temporary, path)


def load(data_dir: str, rid: str) -> dict:
    """The record of a recording; MediaError (not_found) when there is none."""
    path = os.path.join(folder_of(data_dir, rid), RECORD)
    try:
        with open(path, "rb") as f:
            value = json.loads(f.read(1024 * 1024).decode("utf-8"))
    except (OSError, ValueError):
        raise MediaError(f"no recording {rid}; a recording id is issued by code when a recording is started", "not_found") from None
    if not isinstance(value, dict) or value.get("id") != rid:
        raise MediaError(f"the record of {rid} cannot be read", "not_found")
    return value


def update(data_dir: str, rid: str, change, now=None) -> dict:
    """Read the record, let `change(record)` edit it, stamp `updated_at` and write it back (atomically), under the record
    lock. Returns the record."""
    folder = folder_of(data_dir, rid)
    with _Lock(os.path.join(root_of(data_dir), RECORD_LOCK), blocking=True):
        record = load(data_dir, rid)
        change(record)
        record["updated_at"] = stamp(now)
        _write_json(os.path.join(folder, RECORD), record)
    return record


def create(data_dir: str, now=None, posts=None, tasks=None) -> dict:
    """Issue a recording id and write its record. The id keys everything else; the post files (one per platform) and the
    tasks are bound to it by code, never by a model's slug."""
    ensure_root(data_dir)
    rid = new_id()
    folder = folder_of(data_dir, rid)
    os.mkdir(folder, 0o700)
    record = {"version": 1, "id": rid, "created_at": stamp(now), "updated_at": stamp(now), "status": "open",
              "ended_at": None, "raw": None, "posts": {}, "slots": {}, "frozen": False, "tasks": {}, "purged": {}}
    try:
        with _Lock(os.path.join(root_of(data_dir), RECORD_LOCK), blocking=True):
            _write_json(os.path.join(folder, RECORD), record)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if posts:
        link_posts(data_dir, rid, posts, now=now)
    if tasks:
        bind_tasks(data_dir, rid, tasks, now=now)
    return load(data_dir, rid)


def link_posts(data_dir: str, rid: str, posts: dict, now=None) -> dict:
    """Map the recording to its post files, one per platform: {"instagram": "docs/marketing/posts/x.md"}. The path is a
    project-relative path of a Markdown file under docs/ (no `..`, no link is followed here)."""
    clean = {}
    for platform, path in (posts or {}).items():
        if not isinstance(platform, str) or not PLATFORM.fullmatch(platform):
            raise MediaError("a platform is a lowercase word", "usage")
        if not isinstance(path, str) or not POST_PATH.fullmatch(path) or ".." in path.split("/") or "//" in path:
            raise MediaError("a post file is a Markdown file under docs/ of the project", "usage")
        clean[platform] = path
    return update(data_dir, rid, lambda r: r["posts"].update(clean), now)


def bind_tasks(data_dir: str, rid: str, tasks: dict, now=None) -> dict:
    """Bind task ids to the recording: {"code": <the media pipeline's code task>, "edit": <the edit task of M2>}. The
    purge removes the run folders of these tasks with the recording."""
    clean = {}
    for name, value in (tasks or {}).items():
        if name not in ("code", "edit") or type(value) is not int or value < 1:
            raise MediaError("tasks takes code and edit, each a task id", "usage")
        clean[name] = value
    return update(data_dir, rid, lambda r: r["tasks"].update(clean), now)


def mark(data_dir: str, rid: str, status: str, now=None) -> dict:
    """Move the recording to a status: open, scheduled, published or cancelled. published and cancelled are the ends:
    they stamp `ended_at`, which the retention counts from. Called by the packages that publish and cancel."""
    if status not in STATUSES:
        raise MediaError(f"status is one of {', '.join(STATUSES)}", "usage")

    def change(record):
        record["status"] = status
        if status in ("published", "cancelled") and not record.get("ended_at"):
            record["ended_at"] = stamp(now)
        if status in ("published", "cancelled"):
            record["frozen"] = True

    return update(data_dir, rid, change, now)


def freeze(data_dir: str, rid: str, now=None) -> dict:
    """The assets are frozen once an effect is open: an upload for a slot is refused afterwards."""
    return update(data_dir, rid, lambda r: r.update(frozen=True), now)


def slot_id(rid: str, key: str) -> str:
    """The id of the slot named `key` in the script of this recording: issued by code, the same for the same key."""
    return hashlib.sha256(f"{check_id(rid)}\0{key}".encode("utf-8")).hexdigest()[:12]


def register_slots(data_dir: str, rid: str, slots: list, now=None) -> dict:
    """Register the asset slots the script declares: [{"key": "beat-3", "description": "..."}]. A slot id is issued by code
    from the key and is bound to the sha256 of the slot's description. When the description of a slot that holds a file
    changed, the file is marked `stale`: the person is asked to upload again or confirm (confirm_slot). Returns the record."""
    entries = {}
    for slot in slots:
        key, description = slot.get("key"), slot.get("description")
        if not isinstance(key, str) or not SLOT_KEY.fullmatch(key) or not isinstance(description, str) or not description.strip():
            raise MediaError("a slot has a key (letters, digits, '.', '_', ':', '-') and a description", "usage")
        entries[slot_id(rid, key)] = {"key": key, "description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest()}

    def change(record):
        if record.get("frozen"):
            raise MediaError("the assets are frozen: an effect is open for this recording", "refused")
        slots_now = record["slots"]
        for sid in list(slots_now):
            if sid not in entries:
                _drop_asset_file(data_dir, rid, slots_now[sid])
                del slots_now[sid]
        for sid, entry in entries.items():
            held = slots_now.get(sid)
            if held is None:
                slots_now[sid] = {**entry, "asset": None}
            elif held["description_sha256"] != entry["description_sha256"]:
                held["description_sha256"] = entry["description_sha256"]
                if held.get("asset"):
                    held["asset"]["stale"] = True

    return update(data_dir, rid, change, now)


def confirm_slot(data_dir: str, rid: str, sid: str, now=None) -> dict:
    """The person confirms the file of a slot whose description changed."""
    check_slot(sid)

    def change(record):
        held = record["slots"].get(sid)
        if held is None or not held.get("asset"):
            raise MediaError("that slot holds no file", "not_found")
        held["asset"]["stale"] = False

    return update(data_dir, rid, change, now)


def _drop_asset_file(data_dir: str, rid: str, slot: dict) -> None:
    asset = slot.get("asset") if isinstance(slot, dict) else None
    if asset and isinstance(asset.get("file"), str) and re.fullmatch(r"[0-9a-f]{12}-[0-9a-f]{12}\.[a-z0-9]{2,4}", asset["file"]):
        try:
            os.unlink(os.path.join(folder_of(data_dir, rid), ASSETS, asset["file"]))
        except OSError:
            pass


def records(data_dir: str) -> list:
    """Every record of the store, oldest first: the recording folders with a readable record."""
    root = root_of(data_dir)
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    for name in names:
        if not ID.fullmatch(name):
            continue
        try:
            out.append(load(data_dir, name))
        except MediaError:
            continue
    return sorted(out, key=lambda r: (r.get("created_at", ""), r["id"]))


# --- measuring the store ------------------------------------------------------------------------------------------------


def tree_bytes(path: str) -> int:
    """The bytes of the files under a path, counted with lstat (a link counts as itself, nothing is followed)."""
    total = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    total += tree_bytes(entry.path)
                else:
                    total += info.st_size
    except OSError:
        return 0
    return total


def renders_kept(data_dir: str) -> int:
    """How many render-<sha12>.mp4 files the store holds."""
    count = 0
    root = root_of(data_dir)
    try:
        folders = [n for n in os.listdir(root) if ID.fullmatch(n)]
    except OSError:
        return 0
    for name in folders:
        try:
            count += sum(1 for n in os.listdir(os.path.join(root, name)) if RENDER.fullmatch(n))
        except OSError:
            continue
    return count


def usage(data_dir: str) -> dict:
    """{"bytes", "quota_bytes", "recordings", "renders", "max_renders"} of the store."""
    return {"bytes": tree_bytes(root_of(data_dir)), "quota_bytes": QUOTA_BYTES, "recordings": len(records(data_dir)),
            "renders": renders_kept(data_dir), "max_renders": MAX_RENDERS}


def _free_bytes(path: str) -> int:
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


# --- reading the type from the bytes --------------------------------------------------------------------------------------


def sniff(head: bytes):
    """The type of a file, read from its first bytes: ("video", "mov"|"mp4"), ("image", "png"|"jpeg"|"webp"), ("heif", brand)
    or None. The name and the Content-Type are never looked at."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        size = int.from_bytes(head[0:4], "big")
        brand = head[8:12]
        if size != 1 and not 12 <= size <= 4096:
            return None
        if brand in MOV_BRANDS:
            return ("video", "mov")
        if brand in MP4_BRANDS:
            return ("video", "mp4")
        if brand in HEIF_BRANDS:
            return ("heif", brand.decode("ascii", "replace"))
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ("image", "png")
    if head[:3] == b"\xff\xd8\xff":
        return ("image", "jpeg")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ("image", "webp")
    return None


def image_facts(path: str, kind: str) -> dict:
    """{"width", "height"} from the file's header; MediaError for an animation (an APNG or an animated WebP), a header that
    cannot be read, or sides over IMAGE_MAX_SIDE / IMAGE_MAX_PIXELS. Nothing is decoded."""
    try:
        with open(path, "rb") as f:
            width, height = {"png": _png_size, "jpeg": _jpeg_size, "webp": _webp_size}[kind](f)
    except (OSError, ValueError, IndexError):
        raise MediaError("the image's header cannot be read", "type") from None
    if not (0 < width <= IMAGE_MAX_SIDE and 0 < height <= IMAGE_MAX_SIDE) or width * height > IMAGE_MAX_PIXELS:
        raise MediaError(f"the image is {width}x{height} pixels; at most {IMAGE_MAX_SIDE} on a side and "
                         f"{IMAGE_MAX_PIXELS // 1_000_000} megapixels", "too_large")
    return {"width": width, "height": height}


def _png_size(f):
    head = f.read(24)
    if head[12:16] != b"IHDR":
        raise ValueError("no IHDR")
    f.seek(8)
    for _ in range(64):   # chunks before the first IDAT: an animated PNG announces itself with acTL there
        header = f.read(8)
        if len(header) < 8:
            break
        length, name = int.from_bytes(header[:4], "big"), header[4:8]
        if name == b"acTL":
            raise MediaError("the image is an animated PNG: attach a still image", "type")
        if name == b"IDAT":
            break
        f.seek(length + 4, 1)
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _jpeg_size(f):
    f.seek(2)
    for _ in range(2000):
        marker = f.read(2)
        while len(marker) == 2 and marker[0] == 0xFF and marker[1] == 0xFF:
            marker = b"\xff" + f.read(1)
        if len(marker) < 2 or marker[0] != 0xFF:
            raise ValueError("no marker")
        code = marker[1]
        if 0xD0 <= code <= 0xD9 or code == 0x01:
            continue
        length = int.from_bytes(f.read(2), "big")
        if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
            body = f.read(5)
            return int.from_bytes(body[3:5], "big"), int.from_bytes(body[1:3], "big")
        f.seek(length - 2, 1)
    raise ValueError("no frame header")


def _webp_size(f):
    head = f.read(32)
    kind = head[12:16]
    if kind == b"VP8X":
        if head[20] & 0x02:
            raise MediaError("the image is an animated WebP: attach a still image", "type")
        return int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1
    if kind == b"VP8 ":
        return int.from_bytes(head[26:28], "little") & 0x3FFF, int.from_bytes(head[28:30], "little") & 0x3FFF
    if kind == b"VP8L":
        bits = int.from_bytes(head[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ValueError("unknown WebP chunk")


# --- ffprobe -----------------------------------------------------------------------------------------------------------


def ffprobe_path():
    return shutil.which("ffprobe")


def probe(path: str) -> dict:
    """What ffprobe reads of a video file, forced to the mov demuxer (an MP4 is read by it too) and to local files only:
    {"duration", "width", "height", "fps", "video_codec", "audio_codec", "videos", "audios", "hdr", "others"}. `others`
    counts the streams that are neither video nor audio (data, metadata, subtitles): they are ignored, never refused.
    MediaError when ffprobe is missing, fails, or times out."""
    tool = ffprobe_path()
    if tool is None:
        raise MediaError("ffprobe was not found on the PATH: install ffmpeg (brew install ffmpeg-full) to take a video in", "refused")
    argv = [tool, "-v", "error", "-protocol_whitelist", "file", "-f", "mov", "-enable_drefs", "0", "-print_format", "json", "-show_format",
            "-show_streams", "-i", path]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=PROBE_TIMEOUT, check=False, stdin=subprocess.DEVNULL,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    except subprocess.TimeoutExpired:
        raise MediaError("reading the video took too long: it is refused", "type") from None
    except OSError as e:
        raise MediaError(f"ffprobe could not run: {e.strerror}", "refused") from None
    try:
        data = json.loads(done.stdout.decode("utf-8", "replace") or "{}")
        streams = data["streams"]
    except (ValueError, KeyError, TypeError):
        raise MediaError("this file is not a video this store can read (MP4 or MOV)", "type") from None
    if done.returncode != 0 or not isinstance(streams, list):
        raise MediaError("this file is not a video this store can read (MP4 or MOV)", "type")
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    others = len(streams) - len(videos) - len(audios)
    out = {"videos": len(videos), "audios": len(audios), "others": others, "duration": None, "width": None, "height": None,
           "fps": None, "video_codec": None, "audio_codec": None, "hdr": False}
    if audios:
        out["audio_codec"] = audios[0].get("codec_name")
    for candidate in ((data.get("format") or {}).get("duration"), *( [videos[0].get("duration")] if videos else [])):
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out["duration"] = value
            break
    if videos:
        v = videos[0]
        out.update(width=v.get("width"), height=v.get("height"), video_codec=v.get("codec_name"))
        rate = str(v.get("avg_frame_rate") or v.get("r_frame_rate") or "")
        if re.fullmatch(r"\d{1,6}/\d{1,6}", rate) and rate.split("/")[1] != "0":
            top, bottom = rate.split("/")
            out["fps"] = round(int(top) / int(bottom), 3)
        out["hdr"] = v.get("color_transfer") in HDR_TRANSFERS or any(
            "DOVI" in str(side.get("side_data_type", "")).upper() or "DOLBY" in str(side.get("side_data_type", "")).upper()
            for side in (v.get("side_data_list") or []) if isinstance(side, dict))
    return out


def check_video(facts: dict, *, limit_seconds: int, label: str) -> None:
    """The stream check and the limits of a recording or a clip. Data and metadata streams are not counted."""
    if facts["videos"] != 1:
        raise MediaError(f"{label} has {facts['videos']} video streams; it must have exactly one", "type")
    if facts["audios"] > 1:
        raise MediaError(f"{label} has {facts['audios']} audio streams; at most one is taken", "type")
    if facts["hdr"]:
        raise MediaError(HDR_MESSAGE, "type")
    if facts["duration"] is None:
        raise MediaError(f"the length of {label} cannot be read", "type")
    if facts["duration"] > limit_seconds:
        raise MediaError(f"{label} is {facts['duration']:.1f} s long; at most {limit_seconds} s", "too_large")
    width, height = facts["width"], facts["height"]
    if not (isinstance(width, int) and isinstance(height, int) and 0 < width <= RECORDING_MAX_SIDE and 0 < height <= RECORDING_MAX_SIDE):
        raise MediaError(f"{label} is {width}x{height} pixels; at most {RECORDING_MAX_SIDE} on a side", "too_large")


# --- the file name ------------------------------------------------------------------------------------------------------------


FALLBACK_NAME = "file"


def clean_name(value):
    """The display label of a file, from the header that carries it (percent-encoded UTF-8): it is sanitised and never
    refused, because a label is not worth a failed upload. Decoded (a byte that is not UTF-8 is dropped), normalised to NFC,
    every character of category Cc, Cf, Cs, Co, Cn, Zl or Zp dropped, a path separator turned into `_`, trimmed, cut to
    NAME_MAX_CHARS characters and NAME_MAX_BYTES bytes on a character boundary, and FALLBACK_NAME when nothing is left. It is
    a label for the person, never a path: the store names the file itself. None when no name was given."""
    if value is None:
        return None
    if not isinstance(value, str):
        return FALLBACK_NAME
    value = value[:HEADER_NAME_MAX]
    if not value.isascii():
        value = urllib.parse.quote(value, safe="")
    text = urllib.parse.unquote(value, encoding="utf-8", errors="ignore")
    text = unicodedata.normalize("NFC", text)
    text = "".join("_" if c in "/\\" else c for c in text if unicodedata.category(c) not in BAD_CATEGORIES).strip(" ")
    text = text[:NAME_MAX_CHARS]
    while len(text.encode("utf-8")) > NAME_MAX_BYTES:
        text = text[:-1]
    return text.strip(" ") or FALLBACK_NAME


# --- intake ----------------------------------------------------------------------------------------------------------------------


def _pull(stream, n: int, deadline: float) -> bytes:
    """One read of the body that cannot outlast the upload's deadline: the stream's timeout (a socket's) is set to the time left
    (at most STALL_SECONDS), and `read1` is used when there is one, because `read(n)` of a buffered reader waits until n bytes
    arrived, which a slow sender would stretch past any deadline."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise MediaError(f"the upload took more than {UPLOAD_MAX_SECONDS} s", "refused")
    arm = getattr(stream, "settimeout", None)
    if callable(arm):
        arm(max(0.05, min(left, STALL_SECONDS)))
    take = getattr(stream, "read1", None) or stream.read
    try:
        return take(n)
    except OSError:
        if time.monotonic() >= deadline:
            raise MediaError(f"the upload took more than {UPLOAD_MAX_SECONDS} s", "refused") from None
        raise MediaError("the connection stalled or closed before the body arrived", "usage") from None


def _read_head(stream, length: int, deadline: float) -> bytes:
    """The first bytes of the body, up to SNIFF_BYTES, read until that many or the body's end."""
    want = min(length, SNIFF_BYTES)
    head = b""
    while len(head) < want:
        piece = _pull(stream, want - len(head), deadline)
        if not piece:
            break
        head += piece
    if len(head) < want:
        raise MediaError("the body ended before its Content-Length", "usage")
    return head


def _bound_length(length, ceiling: int) -> int:
    if length is None:
        raise MediaError("a Content-Length is required", "length")
    if type(length) is not int or length < 0:
        raise MediaError("the Content-Length is not a number", "usage")
    if length > ceiling:
        raise MediaError(f"the body is {length} bytes, more than the {ceiling} this route takes", "too_large")
    if length < MIN_BYTES:
        raise MediaError("the body is too small to be a video or an image", "type")
    return length


def receive(data_dir: str, stream, length, *, recording=None, slot=None, name=None, now=None) -> dict:
    """Take one file in. With no `slot` it is a recording: with no `recording` a new recording id is issued, with one the
    file is attached to that recording (which must have no raw file yet). With a `slot` it is the asset of that slot of
    `recording`. `stream` has read(n); `length` is the declared Content-Length. Returns {"recording", "kind": "recording"|
    "asset", "slot", "name", "bytes", "sha256", "type", "facts"}. MediaError for every refusal; nothing is left on disk then.

    The order of the refusals is deliberate, from what needs no read to what needs the whole file: (1) the ids and the length
    (usage, length, too_large); (2) the lock, the quota, the render cap and free space; (3) the record (not_found, or not open);
    (4) the first bytes: a body that is not a video (or an image, for a slot) is `type` whether or not ffprobe is installed;
    (5) only for a video, that ffprobe is installed; (6) the body, the hash, then the checks of the file."""
    kind = "asset" if slot is not None else "recording"
    if recording is not None:
        check_id(recording)
    if slot is not None:
        check_slot(slot)
        if recording is None:
            raise MediaError("an asset needs the recording id", "usage")
    label = clean_name(name)
    ceiling = MEDIA_MAX_BYTES if kind == "recording" else max(IMAGE_MAX_BYTES, CLIP_MAX_BYTES)
    length = _bound_length(length, ceiling)
    root = ensure_root(data_dir)
    try:
        lock = _Lock(os.path.join(root, UPLOAD_LOCK), blocking=False)
        lock.__enter__()
    except BlockingIOError:
        raise MediaError("another upload of this project is running: wait for it to end", "refused") from None
    except OSError as e:
        raise MediaError(f"the upload lock cannot be taken: {e.strerror}", "refused") from None
    try:
        return _receive_locked(data_dir, root, stream, length, kind, recording, slot, label, now,
                               time.monotonic() + UPLOAD_MAX_SECONDS)
    finally:
        lock.__exit__(None, None, None)


def _require_open(record: dict, kind: str, slot) -> None:
    """A file is taken in only for a recording that is open: not published, cancelled or scheduled, not frozen (an effect is
    open), not purged; a recording takes its raw file once, an asset needs a slot the code issued. Checked before the body is
    read and again, under the record lock, when the record is written (a freeze, a mark or a purge do not take the upload lock)."""
    rid = record.get("id")
    if record.get("status") != "open":
        raise MediaError(f"recording {rid} is {record.get('status')}: it takes no more files", "refused")
    if record.get("frozen"):
        raise MediaError("the assets are frozen: an effect is open for this recording", "refused")
    if (record.get("purged") or {}).get("raw"):
        raise MediaError(f"the media of recording {rid} was purged", "refused")
    if kind == "recording" and record.get("raw"):
        raise MediaError(f"recording {rid} already has its file; a recording is never replaced", "refused")
    if kind == "asset" and slot not in (record.get("slots") or {}):
        raise MediaError(f"recording {rid} has no slot {slot}; slot ids are issued by code", "not_found")


def _receive_locked(data_dir, root, stream, length, kind, recording, slot, label, now, deadline) -> dict:
    # --- everything that can be refused before the body is read
    used = tree_bytes(root)
    if used + length > QUOTA_BYTES:
        raise MediaError(f"the media store holds {used} bytes and this file would pass its {QUOTA_BYTES}: purge old media first", "refused")
    if renders_kept(data_dir) >= MAX_RENDERS:
        raise MediaError(f"the store keeps {MAX_RENDERS} renders already: purge old media first", "refused")
    if _free_bytes(root) < length + FREE_MARGIN_BYTES:
        raise MediaError("the disk has not enough free space for this file", "no_space")
    record = None
    if recording is not None:
        record = load(data_dir, recording)
        _require_open(record, kind, slot)
    # --- the first bytes name the type; a wrong one is refused before a file exists
    head = _read_head(stream, length, deadline)
    found = sniff(head)
    if found is None:
        raise MediaError("this is not an MP4 or MOV video" + ("" if kind == "recording" else ", or a PNG, JPEG or WebP image"), "type")
    if found[0] == "heif":
        raise MediaError(HEIF_MESSAGE, "type")
    if kind == "recording" and found[0] != "video":
        raise MediaError("a recording is an MP4 or MOV video", "type")
    if found[0] == "image" and length > IMAGE_MAX_BYTES:
        raise MediaError(f"an image is at most {IMAGE_MAX_BYTES} bytes", "too_large")
    if found[0] == "video":
        if kind == "asset" and length > CLIP_MAX_BYTES:
            raise MediaError(f"a clip is at most {CLIP_MAX_BYTES} bytes", "too_large")
        if ffprobe_path() is None:   # after the type is known: a body that is not a video is refused as such whether or not ffprobe is installed
            raise MediaError("ffprobe was not found on the PATH: install ffmpeg (brew install ffmpeg-full) to take a video in", "refused")
    # --- the destination
    issued = recording is None
    if issued:
        record = create(data_dir, now=now)
        recording = record["id"]
    folder = folder_of(data_dir, recording)
    try:
        _check_dir(folder, "the recording's folder")
        target_dir = folder
        if kind == "asset":
            target_dir = os.path.join(folder, ASSETS)
            _private_dir(target_dir, "the assets folder")
        temporary = os.path.join(target_dir, f".incoming-{secrets.token_hex(8)}.part")
        written = _stream_to(temporary, head, stream, length, deadline)
        try:
            result = _finish(data_dir, folder, target_dir, temporary, kind, recording, slot, label, found, written, now)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return result
    except BaseException:
        if issued:
            shutil.rmtree(folder, ignore_errors=True)
        raise


def _write(out, data: bytes) -> None:
    out.write(data)


def _stream_to(temporary: str, head: bytes, stream, length: int, deadline: float) -> dict:
    """Write the body to the temporary name, chunk by chunk, hashing as it goes. The file is created with O_CREAT|O_EXCL|
    O_NOFOLLOW and mode 0600; it is deleted here when the body fails (short, stalled, too slow, the disk full)."""
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as e:   # the name is taken (a file or a link someone placed there), or the folder cannot be written
        raise MediaError(f"the temporary file cannot be created ({e.strerror}): nothing was written", "refused") from None
    digest = hashlib.sha256()
    count = 0
    try:
        with os.fdopen(fd, "wb") as out:
            fd = None
            digest.update(head)
            _write(out, head)
            count = len(head)
            while count < length:
                piece = _pull(stream, min(CHUNK_BYTES, length - count), deadline)
                if not piece:
                    raise MediaError("the body ended before its Content-Length", "usage")
                digest.update(piece)
                _write(out, piece)
                count += len(piece)
            out.flush()
            os.fsync(out.fileno())
    except OSError as e:   # a read failure is turned into a MediaError by _pull; an OSError here is the disk's
        if fd is not None:
            os.close(fd)
        _unlink(temporary)
        if e.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
            raise MediaError("the disk filled up while the file was being written", "no_space") from None
        raise MediaError(f"the file could not be written: {e.strerror}", "refused") from None
    except BaseException:
        if fd is not None:
            os.close(fd)
        _unlink(temporary)
        raise
    return {"bytes": count, "sha256": digest.hexdigest()}


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _finish(data_dir, folder, target_dir, temporary, kind, recording, slot, label, found, written, now) -> dict:
    """The checks of the file once it is whole, then its final name and its record."""
    if found[0] == "video":
        facts = probe(temporary)
        if kind == "recording":
            check_video(facts, limit_seconds=MAX_SECONDS, label="the recording")
        else:
            check_video(facts, limit_seconds=CLIP_MAX_SECONDS, label="the clip")
        ext = found[1]
    else:
        facts = image_facts(temporary, found[1])
        ext = {"png": "png", "jpeg": "jpg", "webp": "webp"}[found[1]]
    info = {"bytes": written["bytes"], "sha256": written["sha256"], "type": found[1], "name": label,
            "uploaded_at": stamp(now), **{k: v for k, v in facts.items() if k in ("duration", "width", "height", "fps", "video_codec", "audio_codec")}}
    if kind == "recording":
        final_name = f"raw.{ext}"
    else:   # named by its hash: a new file for the slot never overwrites the one the record still points to
        final_name = f"{slot}-{written['sha256'][:12]}.{ext}"
        info["stale"] = False
    info["file"] = final_name
    final = os.path.join(target_dir, final_name)
    placed = False
    try:
        os.link(temporary, final)   # never replaces
        placed = True
    except FileExistsError:
        if kind == "recording":
            raise MediaError(f"recording {recording} already has its file; a recording is never replaced", "refused") from None
        # an asset with the same content is already there under this name: the record is pointed at it again
    except OSError as e:
        raise MediaError(f"the file cannot be put in place: {e.strerror}", "refused") from None
    previous = {}

    def change(record):
        _require_open(record, kind, slot)   # the record is read again under its lock: a freeze, a mark or a dropped slot since the start
        if kind == "recording":
            record["raw"] = info
        else:
            previous["asset"] = record["slots"][slot].get("asset")
            record["slots"][slot]["asset"] = info

    try:
        update(data_dir, recording, change, now)
    except BaseException:
        if placed:
            _unlink(final)
        raise
    old = previous.get("asset")
    if old and old.get("file") and old["file"] != final_name:   # the old file goes only after the record no longer names it
        _drop_asset_file(data_dir, recording, {"asset": old})
    return {"recording": recording, "kind": kind, "slot": slot, "name": label, "bytes": info["bytes"], "sha256": info["sha256"],
            "type": found[1], "facts": {k: v for k, v in info.items() if k in ("duration", "width", "height", "fps", "video_codec", "audio_codec")}}


def receive_file(data_dir: str, path: str, *, recording=None, slot=None, now=None) -> dict:
    """`media-in`: take a file of the person's from disk in through the same function as the page's route. The path must be
    a regular file that is not a link (opened with O_NOFOLLOW); its name is its display name."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise MediaError(f"{path} cannot be opened (a link is refused): {e.strerror}", "usage") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise MediaError(f"{path} is not a regular file", "usage")
        base = os.path.basename(path)
        label = urllib.parse.quote(base, safe="") if base else None
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return receive(data_dir, stream, info.st_size, recording=recording, slot=slot, name=label, now=now)
    finally:
        os.close(fd)


# --- retention (D7) ---------------------------------------------------------------------------------------------------------------


def _older(moment, now, days) -> bool:
    try:
        return now - parse_stamp(moment) >= datetime.timedelta(days=days)
    except (TypeError, ValueError):
        return False


def due(record: dict, now) -> str:
    """What the retention removes from a recording now: "all" (the whole folder), "raw" (everything but the renders, the
    covers and the payload folder) or "" (nothing). Pure.
      open          untouched for ABANDONED_DAYS: all (an abandoned post)
      scheduled     nothing (it ends when published or cancelled)
      cancelled     RAW_DAYS after the cancellation: all
      published     RAW_DAYS after publication: raw; RENDER_DAYS after publication: all"""
    status = record.get("status")
    if status == "open":
        return "all" if _older(record.get("updated_at"), now, ABANDONED_DAYS) else ""
    if status == "cancelled":
        return "all" if _older(record.get("ended_at"), now, RAW_DAYS) else ""
    if status == "published":
        if _older(record.get("ended_at"), now, RENDER_DAYS):
            return "all"
        if _older(record.get("ended_at"), now, RAW_DAYS) and not record.get("purged", {}).get("raw"):
            return "raw"
    return ""


def _remove_tree(path: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        os.unlink(path)
        return
    shutil.rmtree(path)


def purge(data_dir: str, now=None, run_dirs_of=None, only=None, include_scheduled=False) -> dict:
    """Apply the retention to the store: {"removed": [{"recording", "what": "raw"|"all", "run_dirs": n}], "stray": n,
    "skipped": [reasons]}. `run_dirs_of(record, forced)` returns the run folders of the recording's tasks (the operations layer
    reads them from the store; `forced` is true for a purge by id) or None when a run of them is going, or, for an open post
    purged by age, when its task still waits: the recording is then left for the next round. Nothing is purged while an upload
    runs. With `only`, one recording id is purged whatever its age, but a `scheduled` one only with `include_scheduled` (its post
    is still to go out). No model."""
    now = now or now_utc()
    out = {"removed": [], "stray": 0, "skipped": []}
    root = root_of(data_dir)
    if not os.path.isdir(root):
        return out
    try:
        lock = _Lock(os.path.join(root, UPLOAD_LOCK), blocking=False)
        lock.__enter__()
    except BlockingIOError:
        out["skipped"].append("an upload is running")
        return out
    except OSError:
        return out
    try:
        for record in records(data_dir):
            rid = record["id"]
            what = "all" if only == rid else due(record, now)
            if only is not None and only != rid:
                continue
            if not what:
                continue
            if only == rid and record.get("status") == "scheduled" and not include_scheduled:
                raise MediaError(f"recording {rid} is scheduled: its post has not gone out; purge it with --include-scheduled "
                                 "if you mean to lose it", "refused")
            dirs = run_dirs_of(record, only == rid) if run_dirs_of else []
            if dirs is None:
                out["skipped"].append(f"{rid}: a run of its edit task is still going")
                continue
            for path in dirs:
                _remove_tree(path)
            folder = folder_of(data_dir, rid)
            if what == "all":
                _remove_tree(folder)
            else:
                _purge_raw(data_dir, rid, folder, now)
            out["removed"].append({"recording": rid, "what": what, "run_dirs": len(dirs)})
        if only is None:
            out["stray"] = _sweep_stray(root, now)
    finally:
        lock.__exit__(None, None, None)
    return out


def _purge_raw(data_dir: str, rid: str, folder: str, now) -> None:
    """Everything but the renders, the covers, the payload folder and the record."""
    keep = {RECORD, "payload"}
    for name in os.listdir(folder):
        if name in keep or RENDER.fullmatch(name) or re.fullmatch(r"cover[A-Za-z0-9._-]*", name):
            continue
        _remove_tree(os.path.join(folder, name))

    def change(record):
        record["raw"] = None
        record["slots"] = {sid: {**slot, "asset": None} for sid, slot in record.get("slots", {}).items()}
        record.setdefault("purged", {})["raw"] = stamp(now)

    update(data_dir, rid, change, now)


def _sweep_stray(root: str, now) -> int:
    """Remove a temporary upload file, or a folder with no record, that is older than STRAY_DAYS. Called with the upload
    lock held, so no upload is writing."""
    count = 0
    limit = now.timestamp() - STRAY_DAYS * 86400
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not ID.fullmatch(name):
            continue
        try:
            info = os.lstat(path)
        except OSError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            continue
        if not os.path.exists(os.path.join(path, RECORD)):
            if info.st_mtime < limit:
                _remove_tree(path)
                count += 1
            continue
        for folder in (path, os.path.join(path, ASSETS)):
            try:
                inner = os.listdir(folder)
            except OSError:
                continue
            for part in inner:
                if PART.fullmatch(part):
                    try:
                        if os.lstat(os.path.join(folder, part)).st_mtime < limit:
                            os.unlink(os.path.join(folder, part))
                            count += 1
                    except OSError:
                        pass
    return count


def run_dirs_inside(data_dir: str, candidates) -> list:
    """The run folders among `candidates` that really lie under <data_dir>/task-runs/ (by real path): a value from the store
    is never trusted to name a folder outside it."""
    base = os.path.realpath(os.path.join(data_dir, "task-runs")) + os.sep
    out = []
    for path in candidates:
        if isinstance(path, str) and path and os.path.realpath(path).startswith(base) and os.path.lexists(path):
            out.append(path)
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
