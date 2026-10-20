#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the two file writers share (package W4a): `providers/writer/gdrive.py` (Google Drive) and `providers/writer/onedrive.py` (OneDrive). A name
with an underscore is never listed as an implementation by providers/resolve.py, so this file is a module, not a provider. The writers load it by
path, as the readers load `providers/_google.py` and `providers/_msgraph.py`.

It holds plumbing and no request: the exit codes, the one error type, the allow-list guard of a request function (limit L58), the canonical form
and the sha256 of a list of requests (the dry run), the reading of the content file the runtime hands over, and the ledger of idempotency keys.

  The dry run. A `--dry-run` reads no credential and opens no connection. It prints the exact list of requests the verb would send, each
  {"method", "path", "query", "body"[, "if_match"]} (the path as it is sent, every id percent-encoded; the body of a media upload is described by its
  content type, byte count and sha256, never carried), and `would_sha256`, the sha256 of the canonical JSON of that list (`would_sha256`). The runtime
  builds the same list from the document the person approved (runtime/files_document.py) and `--confirmed` is refused unless the hashes agree, so a
  writer that would send something other than what was approved is stopped before any request.

  The ledger. `<state>/writer-<impl>/ledger.json` (the state folder is $OPENHORA_STATE_DIR, else $XDG_STATE_HOME/openhora, else
  ~/.local/state/openhora; folders 0700, files 0600), under an exclusive file lock: a key is `pending` before the request that changes the account
  and `done` after the answer. A key that is `done` is answered again without a request (replayed); a key still `pending` means an earlier attempt
  may have landed, and the verb looks for its own mark in the account before it writes (each writer says how). A key is bound to the sha256 of the
  list of requests it was claimed for: the same key with other requests is refused.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time

EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = 0, 1, 2, 3, 4
STATE_ENV = "OPENHORA_STATE_DIR"
KEY = re.compile(r"files-[0-9a-f]{32}")
SHA256 = re.compile(r"[0-9a-f]{64}")
CONTENT_MAX = 25 * 1024 * 1024        # bytes: what one source may be (runtime/sources.py ORIGINAL_CAP); the writers send a body in one request
LOCK_SECONDS = 10.0
# The media types a file the platform writes may have: the extension of the name decides (runtime/files_document.py holds the same table).
MEDIA_TYPES = {"md": "text/markdown", "txt": "text/plain", "csv": "text/csv", "pdf": "application/pdf",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
# The images a save writes (a file a sender sent; runtime/files_document.py IMAGE_TYPES holds the same table): a test compares.
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "heic": "image/heic", "heif": "image/heif"}
MEDIA_TYPE = re.compile(r"[a-z]+/[a-z0-9.+-]{1,100}")


class WriterError(Exception):
    """An error with an exit code and a one-line message. `status` is the HTTP status the service answered with, None when it answered nothing."""

    def __init__(self, message, code=EXIT_REFUSED, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


def one_line(text, limit: int = 300) -> str:
    return " ".join(str(text if text is not None else "").split())[:limit]


def emit(obj: dict) -> int:
    print(json.dumps(obj, sort_keys=True))
    return EXIT_OK


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the dry run -----------------------------------------------------------------------------------------------------------------------


def canonical(requests) -> bytes:
    """The canonical text of a list of requests: sorted keys, no spaces, ASCII escapes. The runtime builds the same text."""
    return json.dumps(requests, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def would_sha256(requests) -> str:
    return hashlib.sha256(canonical(requests)).hexdigest()


def check_key(value) -> str:
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise WriterError("--idempotency-key is the key the runtime derives: files- and 32 hexadecimal digits", EXIT_USAGE)
    return value


def check_sha256(value, flag: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise WriterError(f"{flag} is 64 hexadecimal digits", EXIT_USAGE)
    return value


def check_count(value, flag: str) -> int:
    if not isinstance(value, str) or not value.isdigit() or not 1 <= int(value) <= CONTENT_MAX:
        raise WriterError(f"{flag} is a whole number from 1 to {CONTENT_MAX}", EXIT_USAGE)
    return int(value)


def check_media_type(value, flag: str = "--media-type") -> str:
    if not isinstance(value, str) or not MEDIA_TYPE.fullmatch(value) or value not in MEDIA_TYPES.values() and value not in IMAGE_TYPES.values():
        raise WriterError(f"{flag} is one of: {', '.join(sorted(set(MEDIA_TYPES.values()) | set(IMAGE_TYPES.values())))}", EXIT_USAGE)
    return value


def read_content(path, expected_bytes: int, expected_sha256: str) -> bytes:
    """The content file the runtime wrote: an absolute path, a regular file with one link, opened without following a link, at most CONTENT_MAX bytes,
    and exactly the byte count and the sha256 the flags state (what is sent is what was approved). WriterError (usage) otherwise."""
    if not isinstance(path, str) or not os.path.isabs(path):
        raise WriterError("--content-file is the absolute path of a file", EXIT_USAGE)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise WriterError("--content-file cannot be opened (it is missing or a link)", EXIT_USAGE) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > CONTENT_MAX:
            raise WriterError("--content-file is not a plain file within the size one write takes", EXIT_USAGE)
        with os.fdopen(fd, "rb") as f:
            fd = None
            data = f.read(CONTENT_MAX + 1)
    finally:
        if fd is not None:
            os.close(fd)
    if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise WriterError("--content-file is not the content whose size and sha256 the flags state: nothing was sent", EXIT_USAGE)
    return data


# --- the allow-list (limit L58) --------------------------------------------------------------------------------------------------------


def guarded(allowed, method: str, path: str) -> None:
    """Refuse a request whose method and path match no pair of the writer's constant ALLOWED (a tuple of (method, full-match path regex)). The writers
    call this in the one function that sends a request, so there is no other way out of the process."""
    if not any(method == m and re.fullmatch(rx, path) for m, rx in allowed):
        raise WriterError(f"the writer refuses {method} {one_line(path, 80)}: it is not on its allow-list", EXIT_REFUSED)


# --- the state folder and the ledger ---------------------------------------------------------------------------------------------------


def state_dir() -> str:
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def private_dir(path: str, what: str) -> str:
    """Make `path` (0700) when missing and check it: a real directory, this user's, closed to the group and others."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise WriterError(f"the {what} {path} cannot be made ({e.strerror or e.__class__.__name__})", EXIT_NOT_CONFIGURED) from None
    if not stat.S_ISDIR(found.st_mode):
        raise WriterError(f"the {what} {path} is not a real directory (a link or a file); remove it", EXIT_NOT_CONFIGURED)
    if found.st_uid != os.getuid():
        raise WriterError(f"the {what} {path} is not owned by this user", EXIT_NOT_CONFIGURED)
    if found.st_mode & 0o077:
        raise WriterError(f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); run chmod 700 on it",
                          EXIT_NOT_CONFIGURED)
    return path


def _write_private_json(path: str, value) -> None:
    temporary = f"{path}.tmp-{os.getpid()}"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, sort_keys=True)
            f.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return default
    return found if isinstance(found, type(default)) else default


class Ledger:
    """The idempotency ledger of one writer (`impl`: gdrive, onedrive). Every method that changes it holds the file lock."""

    LEDGER, LOCK = "ledger.json", "ledger.lock"

    def __init__(self, impl: str):
        self.impl = impl

    def folder(self, create: bool = True):
        base = state_dir()
        path = os.path.join(base, f"writer-{self.impl}")
        if not create and not os.path.isdir(path):
            return None
        private_dir(base, "state folder")
        return private_dir(path, f"writer {self.impl} state folder")

    @contextlib.contextmanager
    def locked(self):
        """The ledger under an exclusive file lock: yields the dict, written back when the block ends without an error."""
        base = self.folder()
        fd = os.open(os.path.join(base, self.LOCK), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + LOCK_SECONDS
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise WriterError("the ledger is locked by another write; try again", EXIT_REFUSED) from None
                    time.sleep(0.05)
            path = os.path.join(base, self.LEDGER)
            data = _read_json(path, {"keys": {}})
            data.setdefault("keys", {})
            yield data
            _write_private_json(path, data)
        finally:
            os.close(fd)

    def peek(self, key: str):
        """The entry of a key, read without writing anything or making any folder (a dry run)."""
        found = self.folder(create=False)
        if not found:
            return None
        return (_read_json(os.path.join(found, self.LEDGER), {"keys": {}}).get("keys") or {}).get(key)

    def claim(self, key: str, plan_sha: str) -> dict:
        """Take a key for a list of requests: {"state": "new"} when it was free (now `pending`, with the time it was claimed), {"state": "done", ...the
        result} when an earlier attempt finished, {"state": "pending", "since": the time of the earlier claim} when an earlier attempt may have landed.
        WriterError (refused) when the key was claimed for other requests."""
        with self.locked() as ledger:
            entry = ledger["keys"].get(key)
            if entry is None:
                ledger["keys"][key] = {"state": "pending", "plan": plan_sha, "since": now_iso()}
                return {"state": "new", "since": ledger["keys"][key]["since"]}
            if entry.get("plan") != plan_sha:
                raise WriterError("this idempotency key was used for other requests: nothing was sent", EXIT_REFUSED)
            if entry.get("state") == "done":
                return {"state": "done", "result": entry.get("result") or {}}
            return {"state": "pending", "since": entry.get("since")}

    def done(self, key: str, result: dict) -> None:
        """Record the key done after the answer. A ledger that cannot be written then does not turn a write that landed into a failure: the key stays
        pending, which a later attempt resolves by looking for the mark in the account."""
        try:
            with self.locked() as ledger:
                entry = ledger["keys"].get(key)
                if entry is not None:
                    ledger["keys"][key] = {**entry, "state": "done", "result": result, "at": now_iso()}
        except (WriterError, OSError):
            print(f"warning: the write landed and the ledger could not record it: the key {key} stays pending", file=sys.stderr)

    def release(self, key: str) -> None:
        """Give a key back after a request the service refused outright (nothing changed): the next attempt starts clean."""
        with self.locked() as ledger:
            if ledger["keys"].get(key, {}).get("state") == "pending":
                ledger["keys"].pop(key, None)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
