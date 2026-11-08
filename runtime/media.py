#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The store of the recordings a `media` task works on (decision 12, VD8): `<data_dir>/media/<id>/`, outside the project, so a video never
enters git. It stores and nothing else. It has no host ffprobe and no knowledge of codecs: the deep checks (streams, codecs, HDR, the
300-second limit) are the renderer's `analyse` step in the container, because nothing parses a stranger's media on the host (VD4).

A recording is one folder named by 16 hex characters. It holds `record.json` (mode 0600, the folder 0700, written whole by a temporary
file and `os.replace` under `.record.lock`), the recording itself as `raw.mp4` or `raw.mov`, and the work files the step kind writes by
closed names (`WORK_NAMES`, plus the renders, covers, stills and previews named by a hash). Every path is opened with O_NOFOLLOW, and every file is
opened through the descriptor of its folder.

  * Taking a recording: `receive` (a stream) and `receive_file` (a file) go through `runtime/intake.py` (`stream_in`): the length is
    bounded first, the type is read from the bytes (an MP4 or a MOV), at most `MEDIA_MAX_BYTES`, `QUOTA_BYTES` for the whole store, one
    upload at a time under a lock of its own so a 1 GiB upload never holds the sources' lock.
  * The record binds one task (`bind_task`) and, once a person approved the delivery, names the render that is downloadable.
    `mark_delivered` is the one function that writes `delivered`, and `delivered_file` the one reader that hands a render out; both hash
    the file again, so a render that changed after it was shown is `stale`, never delivered.
  * A removal the person asked for (`media-remove`, runtime/ops_media_remove.py): `remove` takes the record's lock, checks that the record
    still names the task the caller checked, renames the folder `.removed-<id>` and removes it; `purge` sweeps what a removal cut short left.
  * Retention (decision 12), run by `runtime/upkeep.py`, part `media`, through `purge`: the recording and its transcript 7 days after the
    delivery, the render 30 days after it, an undelivered recording 30 days after it was last touched; never one whose task is running.
    A folder with no record, or an upload's temporary file, goes after a day.

Errors are one class, `MediaError(message, code)`; `code` is one of usage, not_found, type, size, quota, busy, no_space, taken, delivered,
unreadable, stale. A message never holds a file's content.

Standard library only, plus runtime/intake.py. Runs on Python 3.9.
"""
from __future__ import annotations

import calendar
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intake  # noqa: E402  (the generic streaming intake: the bounds, the type from the bytes, the lock)

ROOT_NAME = "media"
ID = re.compile(r"[0-9a-f]{16}")             # secrets.token_hex(8)
RECORD = "record.json"
UPLOAD_LOCK = ".upload.lock"                  # in <data_dir>/media/, its own: a 1 GiB upload never holds the sources' lock
RECORD_LOCK = ".record.lock"                  # in each recording folder
MEDIA_MAX_BYTES = 1 << 30                     # = providers/renderer/_host.py MAX_RECORDING_BYTES (a test reads that file as text and compares)
QUOTA_BYTES = 8 << 30                         # the whole store
RAW_DAYS = 7                                  # decision 12: the recording and transcript, 7 days after delivery
RENDER_DAYS = 30                              # decision 12: the render, 30 days after delivery
ABANDONED_DAYS = 30                           # decision 12: an undelivered recording untouched for 30 days
STRAY_DAYS = 1                                # a temporary upload file, or a folder with no record
WORK_NAMES = frozenset({"transcript.json", "analysis.json", "transcript.edited.json", "review.json", "proposal.edl.json",
                        "proposal.beats.json", "edl.json", "beats.json", "render.json", "verify.json"})
RENDER = re.compile(r"render-[0-9a-f]{12}\.mp4")
COVER = re.compile(r"cover-[0-9a-f]{12}\.png")
STILL = re.compile(r"still-[0-9a-f]{12}\.png")
PREVIEW = re.compile(r"preview-[0-9a-f]{12}\.mp4")
RAW = re.compile(r"raw\.(mp4|mov)")
REMOVED = re.compile(r"\.removed-[0-9a-f]{16}")   # a recording a person removed (media-remove), renamed out of the store before its files go
KEPT_AFTER_RAW = (RECORD, "render.json", "verify.json")   # plus RENDER and COVER names: what survives the 7-day purge
JSON_LIMIT = 5 * 1024 * 1024

DAY = 86400.0
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SHA256 = re.compile(r"[0-9a-f]{64}")
CODES = ("usage", "not_found", "type", "size", "quota", "busy", "no_space", "taken", "delivered", "unreadable", "stale")
RECORD_KEYS = {"version", "id", "created_at", "updated_at", "raw", "task", "delivered", "purged"}
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class MediaError(Exception):
    """A refusal of the store. `code` is one of CODES; the message is for a person and never holds a file's content."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


# --- names and times -------------------------------------------------------------------------------------------------------------


def root_of(data_dir: str) -> str:
    """The folder of the whole store: `<data_dir>/media`."""
    return os.path.join(data_dir, ROOT_NAME)


def check_id(value) -> str:
    """The recording id, or MediaError (usage) when it is not 16 lower-case hex characters."""
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise MediaError("a recording id is 16 hexadecimal characters", "usage")
    return value


def folder_of(data_dir: str, rid: str) -> str:
    """The folder of a recording: `<data_dir>/media/<id>`, after the id was checked."""
    return os.path.join(root_of(data_dir), check_id(rid))


def _stamp(now) -> str:
    return time.strftime(STAMP_FORMAT, time.gmtime(time.time() if now is None else now))


def _epoch(text):
    """The POSIX time of a stamp, or None when it is not one."""
    if not isinstance(text, str) or not STAMP.fullmatch(text):
        return None
    try:
        return float(calendar.timegm(time.strptime(text, STAMP_FORMAT)))
    except (ValueError, OverflowError):
        return None


def _is_int(value) -> bool:
    return type(value) is int


def _check_name(name) -> str:
    """A work file's name: one of WORK_NAMES, or a render, cover, still, preview or raw file named by its hash or type."""
    if isinstance(name, str) and (name in WORK_NAMES or any(p.fullmatch(name) for p in (RENDER, COVER, STILL, PREVIEW, RAW))):
        return name
    raise MediaError("that is not the name of a file the store keeps", "usage")


# --- descriptors: nothing is followed ----------------------------------------------------------------------------------------------


def _open_folder(data_dir: str, rid: str) -> int:
    """The descriptor of a recording's folder, opened without following a link at its name."""
    path = folder_of(data_dir, rid)
    try:
        fd = os.open(path, os.O_RDONLY | DIRECTORY | NOFOLLOW)
    except FileNotFoundError:
        raise MediaError("there is no such recording", "not_found") from None
    except OSError:
        raise MediaError("the recording's folder cannot be opened", "unreadable") from None
    return fd


def _open_root(data_dir: str):
    """The descriptor of the store's root, or None when there is none yet."""
    try:
        return os.open(root_of(data_dir), os.O_RDONLY | DIRECTORY | NOFOLLOW)
    except OSError:
        return None


def _open_in(dfd: int, name: str, flags: int, mode: int = 0o600) -> int:
    return os.open(name, flags | NOFOLLOW, mode, dir_fd=dfd)


def _remove_tree(parent_fd: int, name: str) -> bool:
    """Remove a file, a link (the link itself) or a folder tree by name from the folder `parent_fd`, never following a link; a folder is
    opened with O_NOFOLLOW and compared with its lstat before anything in it is touched. True when it is gone."""
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        try:
            os.unlink(name, dir_fd=parent_fd)
            return True
        except OSError:
            return False
    try:
        sub = os.open(name, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=parent_fd)
    except OSError:
        return False
    clean = True
    try:
        if not os.path.samestat(os.fstat(sub), info):
            return False
        try:
            os.fchmod(sub, 0o700)
        except OSError:
            pass
        for child in os.listdir(sub):
            clean = _remove_tree(sub, child) and clean
    finally:
        os.close(sub)
    if not clean:
        return False
    try:
        os.rmdir(name, dir_fd=parent_fd)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def _record_lock(dfd: int):
    """The exclusive lock of one recording's record, waiting for it; the file is `.record.lock` of the folder, opened without following a link."""
    try:
        fd = _open_in(dfd, RECORD_LOCK, os.O_WRONLY | os.O_CREAT)
    except OSError:
        raise MediaError("the recording's lock cannot be taken", "unreadable") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


# --- the record ------------------------------------------------------------------------------------------------------------------


def _check_record(record, rid: str) -> dict:
    """The record, or MediaError (unreadable) when a key or a type is not as the module text says."""
    def bad():
        raise MediaError("the recording's record is damaged", "unreadable")
    if not isinstance(record, dict) or set(record) != RECORD_KEYS or record["version"] != 1 or type(record["version"]) is not int:
        bad()
    if record["id"] != rid or _epoch(record["created_at"]) is None or _epoch(record["updated_at"]) is None:
        bad()
    raw = record["raw"]
    if raw is not None:
        if not isinstance(raw, dict) or set(raw) != {"name", "sha256", "size", "type"}:
            bad()
        if not (isinstance(raw["name"], str) and RAW.fullmatch(raw["name"]) and isinstance(raw["sha256"], str)
                and SHA256.fullmatch(raw["sha256"]) and _is_int(raw["size"]) and raw["size"] >= 0 and raw["type"] in ("mp4", "mov")):
            bad()
    if record["task"] is not None and not (_is_int(record["task"]) and record["task"] >= 0):
        bad()
    delivered = record["delivered"]
    if delivered is not None:
        if not isinstance(delivered, dict) or set(delivered) != {"at", "sha256", "task", "pending"}:
            bad()
        if not (_epoch(delivered["at"]) is not None and isinstance(delivered["sha256"], str) and SHA256.fullmatch(delivered["sha256"])
                and _is_int(delivered["task"]) and (delivered["pending"] is None or _is_int(delivered["pending"]))):
            bad()
    purged = record["purged"]
    if not isinstance(purged, dict) or set(purged) != {"raw"} or not (purged["raw"] is None or _epoch(purged["raw"]) is not None):
        bad()
    return record


def _read_record(dfd: int, rid: str) -> dict:
    try:
        fd = _open_in(dfd, RECORD, os.O_RDONLY)
    except FileNotFoundError:
        raise MediaError("there is no such recording", "not_found") from None
    except OSError:
        raise MediaError("the recording's record cannot be opened", "unreadable") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > JSON_LIMIT:
            raise MediaError("the recording's record is damaged", "unreadable")
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(JSON_LIMIT + 1)
    finally:
        os.close(fd)
    try:
        record = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise MediaError("the recording's record is damaged", "unreadable") from None
    return _check_record(record, rid)


def _write_record(dfd: int, record: dict) -> None:
    """Write the record whole: a temporary file, then `os.replace`, so a reader sees the old record or the new one and never half of one."""
    temporary = f".{RECORD}.part"
    try:
        fd = _open_in(dfd, temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    except OSError:
        raise MediaError("the recording's record cannot be written", "unreadable") from None
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as f:
            f.write(json.dumps(record, sort_keys=True).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
    except OSError as e:
        with contextlib.suppress(OSError):
            os.unlink(temporary, dir_fd=dfd)
        if e.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
            raise MediaError("the disk is full", "no_space") from None
        raise MediaError("the recording's record cannot be written", "unreadable") from None
    finally:
        os.close(fd)
    os.replace(temporary, RECORD, src_dir_fd=dfd, dst_dir_fd=dfd)


def load(data_dir: str, rid: str) -> dict:
    """The record of a recording, read and checked: `not_found` when there is none, `unreadable` when it is damaged."""
    dfd = _open_folder(data_dir, rid)
    try:
        return _read_record(dfd, rid)
    finally:
        os.close(dfd)


def records(data_dir: str) -> list:
    """Every recording of the store that has a readable record, oldest first (by `created_at`, then id)."""
    out = []
    rfd = _open_root(data_dir)
    if rfd is None:
        return out
    try:
        names = [n for n in os.listdir(rfd) if ID.fullmatch(n)]
    finally:
        os.close(rfd)
    for name in names:
        try:
            out.append(load(data_dir, name))
        except MediaError:
            continue
    out.sort(key=lambda r: (r["created_at"], r["id"]))
    return out


def update(data_dir: str, rid: str, change, now=None) -> dict:
    """Change a record under its lock: load it, call `change(record)` (it edits the record in place, or returns a new dict; returning
    False writes nothing), set `updated_at`, check it and write it whole. Returns the record."""
    dfd = _open_folder(data_dir, rid)
    try:
        with _record_lock(dfd):
            record = _read_record(dfd, rid)
            outcome = change(record)
            if outcome is False:
                return record
            if isinstance(outcome, dict):
                record = outcome
            record["updated_at"] = _stamp(now)
            _check_record(record, rid)
            _write_record(dfd, record)
            return record
    finally:
        os.close(dfd)


def bind_task(data_dir: str, rid: str, task_id: int, *, may_replace, now=None) -> dict:
    """Bind a recording to the task that works on it. A delivered recording is never bound again (`delivered`), a purged one is `stale`.
    A recording with no task, or with this task, is bound; one bound to another task is bound to this one only when
    `may_replace(old_task_id)` is True (the old task is cancelled or failed), else `taken`."""
    if not _is_int(task_id) or task_id < 0:
        raise MediaError("a task id is a whole number", "usage")

    def change(record):
        if record["delivered"] is not None:
            raise MediaError("this recording was delivered; a new video of it starts from a new recording", "delivered")
        if record["raw"] is None:
            raise MediaError("the recording was purged by the retention", "stale")
        old = record["task"]
        if old is None or old == task_id:
            record["task"] = task_id
        elif may_replace(old):
            record["task"] = task_id
        else:
            raise MediaError("another task is working on this recording", "taken")

    return update(data_dir, rid, change, now)


# --- taking a recording ----------------------------------------------------------------------------------------------------------


def _accept_video(found) -> None:
    if found not in (("video", "mp4"), ("video", "mov")):
        raise intake.IntakeError("only an MP4 or MOV video is taken", "type")


def _from_intake(e: "intake.IntakeError") -> MediaError:
    code = {"refused": "busy", "no_space": "no_space", "type": "type"}.get(e.code, "size")
    return MediaError(str(e), code)


def receive(data_dir: str, stream, length, *, now=None) -> dict:
    """Take a recording from a stream of a declared length into a new recording folder and return its record. The length is bounded
    before one byte is read, the type is read from the bytes (an MP4 or a MOV), and on every failure the new folder is removed."""
    root = root_of(data_dir)
    os.makedirs(root, mode=0o700, exist_ok=True)
    if _is_int(length) and usage(data_dir) + length > QUOTA_BYTES:
        raise MediaError("the store of recordings is full: a recording must be removed first", "quota")
    rid = secrets.token_hex(8)
    folder = os.path.join(root, rid)
    os.mkdir(folder, 0o700)
    os.chmod(folder, 0o700)
    try:
        try:
            received = intake.stream_in(stream, length, folder, cap=MEDIA_MAX_BYTES, accept=_accept_video,
                                        lock_path=os.path.join(root, UPLOAD_LOCK))
        except intake.IntakeError as e:
            raise _from_intake(e) from None
        subtype = received.type[1]
        name = f"raw.{subtype}"
        dfd = os.open(folder, os.O_RDONLY | DIRECTORY | NOFOLLOW)
        try:
            os.rename(os.path.basename(received.path), name, src_dir_fd=dfd, dst_dir_fd=dfd)
            stamp = _stamp(now)
            record = {"version": 1, "id": rid, "created_at": stamp, "updated_at": stamp,
                      "raw": {"name": name, "sha256": received.sha256, "size": received.size, "type": subtype},
                      "task": None, "delivered": None, "purged": {"raw": None}}
            with _record_lock(dfd):
                _write_record(dfd, record)
        finally:
            os.close(dfd)
    except BaseException:
        rfd = _open_root(data_dir)
        if rfd is not None:
            try:
                _remove_tree(rfd, rid)
            finally:
                os.close(rfd)
        raise
    return record


def receive_file(data_dir: str, path: str, *, now=None) -> dict:
    """Take a recording from a file on this computer: it must be a regular file, opened without following a link."""
    try:
        fd = os.open(path, os.O_RDONLY | NOFOLLOW)
    except OSError:
        raise MediaError("that file cannot be opened (a link, a missing file or a folder is not taken)", "usage") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise MediaError("that is not a regular file", "usage")
        with os.fdopen(fd, "rb", closefd=False) as f:
            return receive(data_dir, f, info.st_size, now=now)
    finally:
        os.close(fd)


# --- the work files ---------------------------------------------------------------------------------------------------------------


def path_of(data_dir: str, rid: str, name: str, *, must_exist: bool = True) -> str:
    """The absolute path of a work file, for a provider's argument. With `must_exist`, a missing file is `not_found` and a link or a file
    that is not regular is `unreadable`."""
    _check_name(name)
    path = os.path.join(folder_of(data_dir, rid), name)
    if must_exist:
        dfd = _open_folder(data_dir, rid)
        try:
            try:
                info = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            except FileNotFoundError:
                raise MediaError("that file is not kept", "not_found") from None
            except OSError:
                raise MediaError("that file cannot be read", "unreadable") from None
        finally:
            os.close(dfd)
        if not stat.S_ISREG(info.st_mode):
            raise MediaError("that file is not a plain file", "unreadable")
    return path


def read_work(data_dir: str, rid: str, name: str, limit: int = JSON_LIMIT) -> bytes:
    """The bytes of a work file: a regular file with one link, at most `limit` bytes."""
    _check_name(name)
    dfd = _open_folder(data_dir, rid)
    try:
        try:
            fd = _open_in(dfd, name, os.O_RDONLY)
        except FileNotFoundError:
            raise MediaError("that file is not kept", "not_found") from None
        except OSError:
            raise MediaError("that file cannot be read", "unreadable") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise MediaError("that file cannot be read", "unreadable")
            with os.fdopen(fd, "rb", closefd=False) as f:
                return f.read(limit + 1)
        finally:
            os.close(fd)
    finally:
        os.close(dfd)


def write_work(data_dir: str, rid: str, name: str, data: bytes) -> str:
    """Write a work file (a name of WORK_NAMES only) whole: a temporary file, then `os.replace`, mode 0600. Returns the sha256 of the bytes
    and touches the record's `updated_at`."""
    if not isinstance(name, str) or name not in WORK_NAMES:
        raise MediaError("that is not the name of a file a step writes", "usage")
    if not isinstance(data, (bytes, bytearray)):
        raise MediaError("a work file is written from bytes", "usage")
    dfd = _open_folder(data_dir, rid)
    try:
        temporary = f".{name}.part"
        try:
            fd = _open_in(dfd, temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        except OSError:
            raise MediaError("that file cannot be written", "unreadable") from None
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as f:
                f.write(bytes(data))
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            with contextlib.suppress(OSError):
                os.unlink(temporary, dir_fd=dfd)
            if e.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
                raise MediaError("the disk is full", "no_space") from None
            raise MediaError("that file cannot be written", "unreadable") from None
        finally:
            os.close(fd)
        os.replace(temporary, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    finally:
        os.close(dfd)
    update(data_dir, rid, lambda record: None)
    return hashlib.sha256(bytes(data)).hexdigest()


def remove_work(data_dir: str, rid: str, names) -> int:
    """Remove the work files that match `names`: strings from WORK_NAMES or compiled patterns (RENDER, COVER, STILL, PREVIEW). Never the record and
    never the recording. Returns the number removed."""
    exact, patterns = set(), []
    for item in names:
        if isinstance(item, str):
            if item == RECORD or RAW.fullmatch(item):
                continue
            _check_name(item)
            exact.add(item)
        elif hasattr(item, "fullmatch"):
            patterns.append(item)
        else:
            raise MediaError("a name is a string or a compiled pattern", "usage")
    dfd = _open_folder(data_dir, rid)
    count = 0
    try:
        for entry in sorted(os.listdir(dfd)):
            if entry == RECORD or RAW.fullmatch(entry):
                continue
            if entry in exact or any(p.fullmatch(entry) for p in patterns):
                try:
                    info = os.stat(entry, dir_fd=dfd, follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        continue
                    os.unlink(entry, dir_fd=dfd)
                    count += 1
                except OSError:
                    continue
    finally:
        os.close(dfd)
    return count


def _digest(path: str):
    """(sha256, size) of a file, read in 1 MiB chunks from one open descriptor; a link or a file that is not regular is refused."""
    try:
        fd = os.open(path, os.O_RDONLY | NOFOLLOW)
    except FileNotFoundError:
        raise MediaError("that file is not kept", "not_found") from None
    except OSError:
        raise MediaError("that file cannot be read", "unreadable") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise MediaError("that file is not a plain file", "unreadable")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest(), info.st_size
    finally:
        os.close(fd)


def sha256_of(path: str) -> str:
    """The sha256 of a file, read in 1 MiB chunks."""
    return _digest(path)[0]


# --- the delivery ----------------------------------------------------------------------------------------------------------------


def mark_delivered(data_dir: str, rid: str, *, sha256: str, task_id: int, pending_id, now=None) -> dict:
    """Mark the render `render-<sha256[:12]>.mp4` of a recording delivered (downloadable). The ONLY function that writes `delivered`. The
    file is hashed again under the record's lock: a render that is missing or whose bytes changed after its name was given is `stale`.
    Already delivered with the same hash it returns the record unchanged; with another hash, `delivered`."""
    if not isinstance(sha256, str) or not SHA256.fullmatch(sha256) or not _is_int(task_id) or task_id < 0:
        raise MediaError("a delivery names the render's sha256 and a task", "usage")
    if pending_id is not None and not _is_int(pending_id):
        raise MediaError("a pending decision id is a whole number", "usage")
    name = f"render-{sha256[:12]}.mp4"

    def change(record):
        delivered = record["delivered"]
        if delivered is not None:
            if delivered["sha256"] == sha256:
                return False
            raise MediaError("another render of this recording was delivered already", "delivered")
        try:
            found = sha256_of(path_of(data_dir, rid, name))
        except MediaError:
            raise MediaError("the render is missing or unreadable", "stale") from None
        if found != sha256:
            raise MediaError("the render changed after it was shown", "stale")
        record["delivered"] = {"at": _stamp(now), "sha256": sha256, "task": task_id, "pending": pending_id}

    return update(data_dir, rid, change, now)


def delivered_file(data_dir: str, rid: str) -> dict:
    """`{"path", "sha256", "size"}` of the delivered render, only when a delivery is recorded and the file hashes to it again: `not_found`
    when none was delivered (or the file is gone), `stale` when the bytes changed. The one reader that hands a render out."""
    record = load(data_dir, rid)
    delivered = record["delivered"]
    if delivered is None:
        raise MediaError("no render of this recording was delivered", "not_found")
    path = path_of(data_dir, rid, f"render-{delivered['sha256'][:12]}.mp4", must_exist=False)
    found, size = _digest(path)
    if found != delivered["sha256"]:
        raise MediaError("the delivered render changed after it was approved", "stale")
    return {"path": path, "sha256": found, "size": size}


# --- a removal the person asked for --------------------------------------------------------------------------------------------


def footprint(data_dir: str, rid: str) -> dict:
    """{"bytes", "files"}: the regular files of one recording's folder, at any depth, counted with lstat (no link is followed). `not_found`
    when there is no such recording folder, `unreadable` when it is not a folder."""
    check_id(rid)
    path = folder_of(data_dir, rid)
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        raise MediaError("there is no such recording", "not_found") from None
    except OSError:
        raise MediaError("the recording's folder cannot be opened", "unreadable") from None
    if not stat.S_ISDIR(info.st_mode):
        raise MediaError("the recording's folder cannot be opened", "unreadable")
    total, count, stack = 0, 0, [path]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                found = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(found.st_mode):
                stack.append(entry.path)
            elif stat.S_ISREG(found.st_mode):
                total += found.st_size
                count += 1
    return {"bytes": total, "files": count}


def remove(data_dir: str, rid: str, *, task) -> dict:
    """Remove one recording for good, at the person's request (`media-remove`): the folder whole, with the recording, the transcript, every
    work file, the renders, the covers and the stills. Under the record's lock the record must still name `task` (the task id the caller
    checked, or None): otherwise `taken`, and nothing is removed. The folder is renamed `.removed-<id>` under that lock, so a reader sees
    the recording whole or not at all; then its files are removed. What a removal cut short leaves is swept by the next `purge`.
    Returns {"recording", "bytes", "files", "delivered_at", "left"}: `left` is True when some of it could not be removed now."""
    check_id(rid)
    if task is not None and not (_is_int(task) and task >= 0):
        raise MediaError("a task id is a whole number", "usage")
    rfd = _open_root(data_dir)
    if rfd is None:
        raise MediaError("there is no such recording", "not_found")
    try:
        dfd = _open_folder(data_dir, rid)
        try:
            with _record_lock(dfd):
                record = _read_record(dfd, rid)
                if record["task"] != task:
                    raise MediaError("the recording changed while it was being removed: look at it again", "taken")
                measured = footprint(data_dir, rid)
                try:
                    named = os.stat(rid, dir_fd=rfd, follow_symlinks=False)
                except OSError:
                    raise MediaError("the recording's folder cannot be opened", "unreadable") from None
                if not os.path.samestat(named, os.fstat(dfd)):
                    raise MediaError("the recording's folder cannot be opened", "unreadable")
                tomb = f".removed-{rid}"
                try:
                    os.rename(rid, tomb, src_dir_fd=rfd, dst_dir_fd=rfd)
                except OSError:
                    raise MediaError("the recording cannot be removed now", "busy") from None
        finally:
            os.close(dfd)
        clean = _remove_tree(rfd, tomb)
    finally:
        os.close(rfd)
    return {"recording": rid, "bytes": measured["bytes"], "files": measured["files"],
            "delivered_at": (record["delivered"] or {}).get("at"), "left": not clean}


# --- size and retention ----------------------------------------------------------------------------------------------------------


def usage(data_dir: str) -> int:
    """The bytes of every regular file under the store's root, counted with `lstat` (no link is followed)."""
    total, stack = 0, [root_of(data_dir)]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode):
                stack.append(entry.path)
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def due(record: dict, now: float) -> str:
    """What the retention owes a recording now, pure: `"all"` (remove the folder), `"raw"` (remove the recording and the transcript) or
    `""`. Not delivered and untouched for ABANDONED_DAYS: all. Delivered RENDER_DAYS ago: all. Delivered RAW_DAYS ago, the recording not
    purged yet: raw. An unreadable time gives `""`."""
    try:
        delivered = record.get("delivered")
        if delivered is None:
            touched = _epoch(record.get("updated_at"))
            return "all" if touched is not None and now - touched >= ABANDONED_DAYS * DAY else ""
        at = _epoch(delivered.get("at"))
        if at is None:
            return ""
        if now - at >= RENDER_DAYS * DAY:
            return "all"
        purged = record.get("purged") or {}
        if now - at >= RAW_DAYS * DAY and purged.get("raw") is None:
            return "raw"
    except (AttributeError, TypeError):
        pass
    return ""


def _newest(parent_fd: int, name: str, info) -> float:
    """The newest modification time of a folder and of its entries (not deeper)."""
    newest = info.st_mtime
    if not stat.S_ISDIR(info.st_mode):
        return newest
    try:
        sub = os.open(name, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=parent_fd)
    except OSError:
        return newest
    try:
        for child in os.listdir(sub):
            try:
                newest = max(newest, os.stat(child, dir_fd=sub, follow_symlinks=False).st_mtime)
            except OSError:
                continue
    finally:
        os.close(sub)
    return newest


def _is_part(name: str) -> bool:
    """A temporary file of an upload (intake's) or of a write of this module: `.incoming-*.part`, `.<name>.part`."""
    return name.endswith(intake.PART_SUFFIX) and name.startswith((intake.PART_PREFIX, "."))


def purge(data_dir: str, *, now: float, busy=lambda task_id: False) -> dict:
    """The retention of the store (decision 12), under the upload lock taken without waiting: an upload that is running skips the pass. For each
    recording `due` says what is owed; a recording whose task is running (`busy(task_id)`) is kept; `"all"` removes the folder, `"raw"` removes
    every entry but the record, `render.json`, `verify.json`, the renders and the covers, and records that the recording was purged. Then the
    strays: a folder with an id for a name and no record, and the temporary files of an upload, when older than STRAY_DAYS.
    Returns `{"removed": [{"recording", "what"}], "kept": [id], "stray": n, "skipped": [why]}`."""
    out = {"removed": [], "kept": [], "stray": 0, "skipped": []}
    rfd = _open_root(data_dir)
    if rfd is None:
        return out
    try:
        try:
            lock = intake.Lock(os.path.join(root_of(data_dir), UPLOAD_LOCK), blocking=False)
            lock.__enter__()
        except BlockingIOError:
            return {"removed": [], "kept": [], "stray": 0, "skipped": ["an upload is running"]}
        except OSError:
            return {"removed": [], "kept": [], "stray": 0, "skipped": ["the upload lock cannot be taken"]}
        try:
            for record in records(data_dir):
                rid, what = record["id"], due(record, now)
                if not what:
                    continue
                if record["task"] is not None and busy(record["task"]):
                    out["kept"].append(rid)
                    continue
                if what == "all":
                    if _remove_tree(rfd, rid):
                        out["removed"].append({"recording": rid, "what": "all"})
                    else:
                        out["kept"].append(rid)
                elif _purge_raw(data_dir, rid, now):
                    out["removed"].append({"recording": rid, "what": "raw"})
                else:
                    out["kept"].append(rid)
            out["stray"] = _sweep_strays(data_dir, rfd, now)
        finally:
            lock.release()
    finally:
        os.close(rfd)
    return out


def _purge_raw(data_dir: str, rid: str, now: float) -> bool:
    """Remove the recording, the transcript and the work files of one recording, keep what survives the 7-day purge, and record it."""
    try:
        dfd = _open_folder(data_dir, rid)
    except MediaError:
        return False
    clean = True
    try:
        for entry in os.listdir(dfd):
            if entry in KEPT_AFTER_RAW or entry == RECORD_LOCK or RENDER.fullmatch(entry) or COVER.fullmatch(entry):
                continue
            clean = _remove_tree(dfd, entry) and clean
    finally:
        os.close(dfd)
    if not clean:
        return False

    def change(record):
        record["raw"] = None
        record["purged"] = {"raw": _stamp(now)}

    try:
        update(data_dir, rid, change, now)
    except MediaError:
        return False
    return True


def _sweep_strays(data_dir: str, rfd: int, now: float) -> int:
    """Remove what no record owns: a folder with an id for a name and no record, and the temporary files of an upload or a write, once they
    are older than STRAY_DAYS; and, at once, what a removal the person asked for left (`.removed-<id>`). Returns how many were removed."""
    count, limit = 0, STRAY_DAYS * DAY
    for name in sorted(os.listdir(rfd)):
        try:
            info = os.stat(name, dir_fd=rfd, follow_symlinks=False)
        except OSError:
            continue
        if ID.fullmatch(name):
            has_record = False
            if stat.S_ISDIR(info.st_mode):
                try:
                    sub = os.open(name, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=rfd)
                except OSError:
                    continue
                try:
                    has_record = RECORD in os.listdir(sub)
                    if has_record:
                        for part in os.listdir(sub):
                            if _is_part(part):
                                try:
                                    pinfo = os.stat(part, dir_fd=sub, follow_symlinks=False)
                                except OSError:
                                    continue
                                if now - pinfo.st_mtime >= limit and _remove_tree(sub, part):
                                    count += 1
                finally:
                    os.close(sub)
            if not has_record and now - _newest(rfd, name, info) >= limit and _remove_tree(rfd, name):
                count += 1
        elif REMOVED.fullmatch(name):          # a removal the person asked for, cut short: it goes at once, whatever its age
            if _remove_tree(rfd, name):
                count += 1
        elif _is_part(name) and name.startswith(intake.PART_PREFIX) and now - info.st_mtime >= limit and _remove_tree(rfd, name):
            count += 1
    return count
