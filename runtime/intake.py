#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The generic streaming intake: how a body of a declared length gets from a stream onto disk, safely. It knows no store, no
recording, no slot and no kind of document; the module that owns a kind of source (runtime/sources.py, later) calls it,
decides what the file is and where it is kept, and extends the type table.

`stream_in(stream, length, dest_dir, cap=...)` does this, in this order:

  1. the declared length is bounded before one byte is read: a missing length, a length over `cap` and a length under
     `minimum` are refused (codes length, usage, too_large, too_small);
  2. the destination folder is opened once with O_DIRECTORY|O_NOFOLLOW (a link at its name is refused), that open descriptor
     is checked with fstat (ours, closed to others), and the temporary file is created and removed through the descriptor
     (`dir_fd`), so the folder cannot be swapped between the check and the write; it must have the free space the body
     needs plus `free_margin` (code no_space), still before one byte is read;
  3. the first bytes (at most SNIFF_BYTES) are read and the type is read from them with `sniff`, never from a name or a
     Content-Type; `accept(found)` may refuse a type (raise IntakeError) before any file exists;
  4. the body is written in chunks of CHUNK_BYTES to a temporary file created with O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600,
     while sha256 is computed as the bytes pass: the body is never whole in memory;
  5. the time is bounded twice: a wall deadline for the whole body (`max_seconds`), which holds against a slow sender
     because every read is armed with the time left (a stream's `settimeout`, at most `stall_seconds`) and uses `read1`
     when the stream has it; and a stall limit for one read (`stall_seconds`);
  6. it returns `Received(path, sha256, size, type)`: the temporary file's path, the hash of the bytes, their count and
     what `sniff` found (None for a body no entry of the table knows). The caller checks the file further, moves it to
     its final name (os.link never replaces) and deletes the temporary file when it is done with it.

Free space is checked and the body written under no lock unless `lock_path` is given: with it, `stream_in` takes the upload
lock (non-blocking, `one_at_a_time`) after the length is bounded and holds it across the free-space check and the write, so
two intakes do not both count the same free space. A caller that passes no `lock_path` must hold `one_at_a_time` itself
around the call.

On every failure (short body, stall, deadline, a full disk, a name taken by a file or a link) the temporary file is
removed and an IntakeError is raised; nothing is left behind. A stream with no `settimeout` (an in-memory buffer) cannot
stall, so only the wall deadline applies to it.

The type table. `sniff(head, table=None)` reads `SNIFF_TABLE`, a list of `(kind, test)` entries: `test(head)` returns the
subtype (a short string) when the first bytes are of that kind and None otherwise; the first entry that answers decides, and
`sniff` returns `(kind, subtype)`. A later package adds an entry with `add_sniffer(kind, test)` or passes its own list as
`table`; the function is not edited. The table here knows MP4 and MOV boxes, HEIF boxes and PNG, JPEG and WebP images.

Errors are one class, `IntakeError(message, code)`: `code` is a machine word (length, usage, too_large, too_small, type,
refused, timeout, stalled, no_space) and the message is for a person.

`Lock` is an exclusive flock on a file, non-blocking or not; `one_at_a_time(path)` takes it without waiting, for "one
upload at a time".

Standard library only. Runs on Python 3.9. Imports nothing else of the repository.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import secrets
import stat
import time
from typing import Callable, List, NamedTuple, Optional, Tuple

CHUNK_BYTES = 1024 * 1024
SNIFF_BYTES = 4096
MIN_BYTES = 32                              # the least a body can be to hold a container header
FREE_MARGIN_BYTES = 256 * 1024 * 1024       # free space must exceed the length by this much
UPLOAD_MAX_SECONDS = 1800                   # wall time of one body, held against a slow sender too
STALL_SECONDS = 30                          # the longest one read may wait for the next bytes
PART_PREFIX, PART_SUFFIX = ".incoming-", ".part"

MOV_BRANDS = (b"qt  ",)
MP4_BRANDS = (b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash", b"3gp4", b"3gp5")
HEIF_BRANDS = (b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"avif")


class IntakeError(Exception):
    """A refusal of the intake. `code` is the machine word (see the module text); the message is for a person."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class Received(NamedTuple):
    path: str
    sha256: str
    size: int
    type: Optional[Tuple[str, str]]


# --- the lock -------------------------------------------------------------------------------------------------------------------


class Lock:
    """An flock on a file. blocking=False raises BlockingIOError at once when another holder has it. The file is opened
    with O_NOFOLLOW and mode 0600."""

    def __init__(self, path: str, blocking: bool = True):
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
        self.release()

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def one_at_a_time(path: str) -> Lock:
    """The lock on `path`, taken without waiting; IntakeError (refused) when another holder has it. Release it with
    `.release()` (or use it as a context manager through `with Lock(path, blocking=False)`)."""
    lock = Lock(path, blocking=False)
    try:
        lock.__enter__()
    except BlockingIOError:
        raise IntakeError("another upload is running: wait for it to end", "refused") from None
    except OSError as e:
        raise IntakeError(f"the upload lock cannot be taken: {e.strerror}", "refused") from None
    return lock


# --- reading the type from the bytes ---------------------------------------------------------------------------------------------


def _ftyp_brand(head: bytes) -> Optional[bytes]:
    """The brand of an ISO base media `ftyp` box at offset 4, or None when the box is not plausible."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        size = int.from_bytes(head[0:4], "big")
        if size != 1 and not 12 <= size <= 4096:
            return None
        return head[8:12]
    return None


def _video(head: bytes) -> Optional[str]:
    brand = _ftyp_brand(head)
    if brand in MOV_BRANDS:
        return "mov"
    if brand in MP4_BRANDS:
        return "mp4"
    return None


def _heif(head: bytes) -> Optional[str]:
    brand = _ftyp_brand(head)
    return brand.decode("ascii", "replace") if brand in HEIF_BRANDS else None


def _image(head: bytes) -> Optional[str]:
    if head[4:8] == b"ftyp":   # a box the video and HEIF entries rejected decides "no type"; it is not an image with a box inside
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


SniffTest = Callable[[bytes], Optional[str]]
SNIFF_TABLE: List[Tuple[str, SniffTest]] = [("video", _video), ("heif", _heif), ("image", _image)]


def add_sniffer(kind: str, test: SniffTest) -> None:
    """Append an entry to SNIFF_TABLE: `test(head)` returns the subtype or None. An entry for a kind already in the table
    is added after it (the first entry that answers decides)."""
    SNIFF_TABLE.append((kind, test))


def sniff(head: bytes, table: Optional[List[Tuple[str, SniffTest]]] = None):
    """The type of a body read from its first bytes: (kind, subtype), for example ("video", "mp4"), or None. The table is
    SNIFF_TABLE unless `table` is given. The name and the Content-Type are never looked at."""
    for kind, test in (SNIFF_TABLE if table is None else table):
        found = test(head)
        if found:
            return (kind, found)
    return None


# --- the bounds ---------------------------------------------------------------------------------------------------------------


def bound_length(length, cap: int, minimum: int = MIN_BYTES) -> int:
    """The declared length, checked before one byte is read."""
    if length is None:
        raise IntakeError("a Content-Length is required", "length")
    if type(length) is not int or length < 0:
        raise IntakeError("the Content-Length is not a number", "usage")
    if length > cap:
        raise IntakeError(f"the body is {length} bytes, more than the {cap} this route takes", "too_large")
    if length < minimum:
        raise IntakeError(f"the body is {length} bytes, under the {minimum} it needs at least", "too_small")
    return length


def open_dir(path: str, what: str = "the destination folder") -> int:
    """Open the folder once, without following a link at its name, and check the open descriptor (fstat, never a second
    look at the name): a directory, ours, closed to others. Returns the descriptor; the caller closes it."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise IntakeError(f"{what} cannot be opened as a plain folder: {e.strerror}", "refused") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise IntakeError(f"{what} is not a plain folder", "refused")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise IntakeError(f"{what} is not owned by this user", "refused")
        if info.st_mode & 0o077:
            raise IntakeError(f"{what} is open to other users (its mode must be 0700)", "refused")
    except BaseException:
        os.close(fd)
        raise
    return fd


def free_bytes(path) -> int:
    """Free bytes on the file system of a path or an open descriptor."""
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


class _Budget:
    """The time of one body: a wall deadline and a stall limit for one read."""

    def __init__(self, max_seconds: float, stall_seconds: float):
        self.seconds, self.stall = max_seconds, stall_seconds
        self.deadline = time.monotonic() + max_seconds

    def _over(self) -> IntakeError:
        return IntakeError(f"the upload took more than {self.seconds:g} s", "timeout")

    def pull(self, stream, n: int) -> bytes:
        """One read of the body that cannot outlast the deadline: the stream's timeout (a socket's) is set to the time left
        (at most the stall limit), and `read1` is used when there is one, because `read(n)` of a buffered reader waits until
        n bytes arrived, which a slow sender would stretch past any deadline."""
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise self._over()
        arm = getattr(stream, "settimeout", None)
        if callable(arm):
            arm(max(0.05, min(left, self.stall)))
        take = getattr(stream, "read1", None) or stream.read
        try:
            piece = take(n)
        except OSError:
            if time.monotonic() >= self.deadline:
                raise self._over() from None
            raise IntakeError("the connection stalled or closed before the body arrived", "stalled") from None
        if len(piece) > n:
            raise IntakeError("the stream gave more bytes than were asked for", "usage")
        return piece

    def head(self, stream, length: int) -> bytes:
        """The first bytes of the body, up to SNIFF_BYTES, read until that many or the body's end."""
        want = min(length, SNIFF_BYTES)
        head = b""
        while len(head) < want:
            piece = self.pull(stream, want - len(head))
            if not piece:
                break
            head += piece
        if len(head) < want:
            raise IntakeError("the body ended before its Content-Length", "usage")
        return head


def _unlink(dir_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass


def _write(out, data: bytes) -> None:
    out.write(data)


def _stream_to(dir_fd: int, name: str, head: bytes, stream, length: int, budget: _Budget) -> Tuple[int, str]:
    """Write the body to the temporary name in the folder `dir_fd`, chunk by chunk, hashing as it goes. The file is created
    with O_CREAT|O_EXCL|O_NOFOLLOW and mode 0600; it is deleted here when the body fails (short, stalled, too slow, the disk
    full)."""
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    except OSError as e:   # the name is taken (a file or a link someone placed there), or the folder cannot be written
        raise IntakeError(f"the temporary file cannot be created ({e.strerror}): nothing was written", "refused") from None
    digest = hashlib.sha256()
    count = 0
    try:
        with os.fdopen(fd, "wb") as out:
            fd = None
            digest.update(head)
            _write(out, head)
            count = len(head)
            while count < length:
                piece = budget.pull(stream, min(CHUNK_BYTES, length - count))
                if not piece:
                    raise IntakeError("the body ended before its Content-Length", "usage")
                digest.update(piece)
                _write(out, piece)
                count += len(piece)
            out.flush()
            os.fsync(out.fileno())
    except OSError as e:   # a read failure is turned into an IntakeError by `pull`; an OSError here is the disk's
        if fd is not None:
            os.close(fd)
        _unlink(dir_fd, name)
        if e.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
            raise IntakeError("the disk filled up while the file was being written", "no_space") from None
        raise IntakeError(f"the file could not be written: {e.strerror}", "refused") from None
    except BaseException:
        if fd is not None:
            os.close(fd)
        _unlink(dir_fd, name)
        raise
    return count, digest.hexdigest()


def stream_in(stream, length, dest_dir: str, *, cap: int, minimum: int = MIN_BYTES, max_seconds: float = UPLOAD_MAX_SECONDS,
              stall_seconds: float = STALL_SECONDS, free_margin: Optional[int] = FREE_MARGIN_BYTES,
              sniff_table: Optional[List[Tuple[str, SniffTest]]] = None,
              accept: Optional[Callable[[Optional[Tuple[str, str]]], None]] = None,
              lock_path: Optional[str] = None) -> Received:
    """Read `length` bytes from `stream` into a new temporary file in `dest_dir` and return Received(path, sha256, size,
    type). IntakeError for every refusal, and nothing is left on disk then. `cap` is the most a body may be; `minimum`
    the least. `accept(found)` is called with what `sniff` found before any file exists and refuses by raising IntakeError;
    with no `accept` any body is taken, a type or not. `free_margin=None` skips the free-space check. `lock_path`: the file
    of the upload lock, held across the free-space check and the write (see the module text; without it the caller holds
    `one_at_a_time`). The returned `path` is `dest_dir` plus the name, for the caller's later steps; the file itself was
    created through the descriptor of the folder as it was when it was checked. The module text gives the order."""
    length = bound_length(length, cap, minimum)
    lock = one_at_a_time(lock_path) if lock_path is not None else None
    try:
        dir_fd = open_dir(dest_dir)
        try:
            if free_margin is not None and free_bytes(dir_fd) < length + free_margin:
                raise IntakeError("the disk has not enough free space for this file", "no_space")
            budget = _Budget(max_seconds, stall_seconds)
            head = budget.head(stream, length)
            found = sniff(head, sniff_table)
            if accept is not None:
                accept(found)
            name = f"{PART_PREFIX}{secrets.token_hex(8)}{PART_SUFFIX}"
            count, sha256 = _stream_to(dir_fd, name, head, stream, length, budget)
        finally:
            os.close(dir_fd)
    finally:
        if lock is not None:
            lock.release()
    return Received(os.path.join(dest_dir, name), sha256, count, found)
