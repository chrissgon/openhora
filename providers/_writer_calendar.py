#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the two calendar writers share (package W1): providers/writer/google-calendar.py and providers/writer/outlook-calendar.py. A name with an underscore is
never listed as an implementation by providers/resolve.py, so this file is a module, not a provider. It holds no HTTP, no credential and no request: only the
parts that must be the same in both writers so that they cannot drift apart.

  WriterError            an error with an exit code and a one-line message (the writers print "error: <message>" and exit with the code)
  state_dir, private_dir, ledger_locked, ledger_peek, settle   the ledger of a writer: <state>/writer-<implementation>/ledger.json (folders 0700, files 0600, an
                         exclusive file lock), the key of a request recorded `pending` before the call and `done` after the answer (the rules of
                         providers/mailer/smtp.py)
  canonical, sha         the one text a request is hashed from, and its sha256 (`would_sha256` of a dry run)
  read_spec              the spec file a writer is handed (the person's words, in a private file, never on a command line), read without following a link and
                         checked: the keys of a create or of a change, the limits, the forms of the times
  KEY, EVENT_ID, CALENDAR_ID   the full-match patterns of the ids that enter a path

Standard library only. Runs on Python 3.9. It sends nothing: no method, no path, no URL is in this file (limits L57 and L58 are each writer's own).
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
import time
import unicodedata

EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = 0, 1, 2, 3, 4
STATE_ENV = "OPENHORA_STATE_DIR"
LEDGER, LOCK = "ledger.json", "ledger.lock"
LOCK_SECONDS = 10
SPEC_MAX_BYTES = 64 * 1024
KEY = re.compile(r"[A-Za-z0-9._-]{1,128}")
EVENT_ID = re.compile(r"[A-Za-z0-9=_+-]{1,600}")
CALENDAR_ID = re.compile(r"(?!\.{1,2}$)[A-Za-z0-9._@+=-]{1,300}")
ETAG = re.compile(r"[A-Za-z0-9_=+/.\"-]{1,200}")
INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
TITLE_MAX, LOCATION_MAX, NOTES_MAX, REMINDER_MAX = 200, 200, 2000, 40320
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")      # control, format, separators, surrogate, private use
CREATE_KEYS = ("title", "all_day", "start_at", "end_at", "location", "reminder_minutes", "notes")
WHEN_KEYS = ("all_day", "start_at", "end_at")
CHANGE_KEYS = ("title", "location", "reminder_minutes", "notes") + WHEN_KEYS


class WriterError(Exception):
    """An error with an exit code and a one-line message. `status` is the HTTP status of the service when there was one."""

    def __init__(self, message, code=EXIT_REFUSED, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


# --- the hash of a request ------------------------------------------------------------------------------------------------------------------------


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def sha(text) -> str:
    return hashlib.sha256(text.encode("utf-8") if isinstance(text, str) else text).hexdigest()


# --- the state folder and the ledger ----------------------------------------------------------------------------------------------------------------


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
        raise WriterError(f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); run chmod 700 on it", EXIT_NOT_CONFIGURED)
    return path


def folder(implementation: str, create: bool = True):
    """<state>/writer-<implementation>, made and checked; None when it does not exist and `create` is False (a dry run makes nothing)."""
    base = state_dir()
    path = os.path.join(base, f"writer-{implementation}")
    if not create and not os.path.isdir(path):
        return None
    private_dir(base, "state folder")
    return private_dir(path, "writer state folder")


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


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def ledger_locked(implementation: str):
    """The ledger under an exclusive file lock: yields the dict, written back when the block ends without an error."""
    base = folder(implementation)
    fd = os.open(os.path.join(base, LOCK), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
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
        path = os.path.join(base, LEDGER)
        data = _read_json(path, {"keys": {}})
        data.setdefault("keys", {})
        yield data
        _write_private_json(path, data)
    finally:
        os.close(fd)


def ledger_peek(implementation: str, key: str):
    """The entry of a key, read without writing anything or making any folder (a dry run)."""
    found = folder(implementation, create=False)
    if not found:
        return None
    return (_read_json(os.path.join(found, LEDGER), {"keys": {}}).get("keys") or {}).get(key)


def claim(implementation: str, key: str, digest: str, operation: str):
    """Record the key `pending` before the call. Returns (state, entry): "new", "pending" (an earlier attempt's outcome is not known) or "done". A key used for
    another request is a usage error."""
    with ledger_locked(implementation) as ledger:
        entry = ledger["keys"].get(key)
        if entry is None:
            ledger["keys"][key] = {"status": "pending", "operation": operation, "payload_sha256": digest, "created_at": now_iso()}
            return "new", ledger["keys"][key]
        if entry.get("payload_sha256") != digest:
            raise WriterError(f"the key {key} was used for another request: a key is one request", EXIT_USAGE)
        return ("done" if entry.get("status") == "done" else "pending"), dict(entry)


def settle(implementation: str, key: str, status: str, **facts) -> None:
    """done: record the answer (the event's id and version). released: forget the key (nothing changed), so the same request may be tried again."""
    with ledger_locked(implementation) as ledger:
        entry = ledger["keys"].get(key)
        if entry is None:
            return
        if status == "done":
            entry.update(facts)
            entry["status"], entry["done_at"] = "done", now_iso()
        else:
            del ledger["keys"][key]


# --- the spec file ------------------------------------------------------------------------------------------------------------------------------------


def one_line(value, what: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum or value != value.strip() \
            or any(unicodedata.category(c) in HIDDEN for c in value):
        raise WriterError(f"{what} is one line of at most {maximum} characters, with no hidden or control character", EXIT_USAGE)
    return value


def _times(spec: dict) -> None:
    if not isinstance(spec.get("all_day"), bool):
        raise WriterError("all_day is true or false", EXIT_USAGE)
    pattern = DAY if spec["all_day"] else INSTANT
    for name in ("start_at", "end_at"):
        if not isinstance(spec.get(name), str) or not pattern.fullmatch(spec[name]):
            raise WriterError(f"{name} is {'a day' if spec['all_day'] else 'an instant with its offset'}", EXIT_USAGE)
    try:
        if spec["all_day"]:
            first, last = (datetime.date.fromisoformat(spec[n]) for n in ("start_at", "end_at"))
        else:
            first, last = (datetime.datetime.fromisoformat(spec[n][:-1] + "+00:00" if spec[n].endswith("Z") else spec[n]) for n in ("start_at", "end_at"))
    except ValueError:
        raise WriterError("start_at and end_at are real times", EXIT_USAGE) from None
    if last <= first:
        raise WriterError("the event ends after it starts", EXIT_USAGE)


def read_spec(path, operation: str) -> dict:
    """The spec the writer is handed in a file. `operation` is `create` (the whole event) or `change` (the parts to change: any of CHANGE_KEYS, the three times
    together). Usage error (exit 2) when the file cannot be read, is not an object, or holds a key, a limit or a form that is not allowed."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, TypeError):
        raise WriterError("--spec-file cannot be read (missing, or a link)", EXIT_USAGE) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise WriterError("--spec-file is not a regular file", EXIT_USAGE)
        with os.fdopen(os.dup(fd), "rb") as f:
            data = f.read(SPEC_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > SPEC_MAX_BYTES:
        raise WriterError("--spec-file is too large", EXIT_USAGE)
    try:
        spec = json.loads(data.decode("utf-8"))
    except ValueError:
        spec = None
    if not isinstance(spec, dict):
        raise WriterError("--spec-file is one JSON object", EXIT_USAGE)
    if operation == "create":
        if set(spec) != set(CREATE_KEYS):
            raise WriterError(f"the spec of a new event has exactly the keys {', '.join(CREATE_KEYS)}", EXIT_USAGE)
        _times(spec)
    else:
        if not spec or set(spec) - set(CHANGE_KEYS) or (set(spec) & set(WHEN_KEYS) and set(WHEN_KEYS) - set(spec)):
            raise WriterError(f"the spec of a change has some of {', '.join(CHANGE_KEYS)}, and the three times together", EXIT_USAGE)
        if set(WHEN_KEYS) <= set(spec):
            _times(spec)
    if "title" in spec:
        one_line(spec["title"], "the title", TITLE_MAX, True)
    if "location" in spec:
        one_line(spec["location"], "the location", LOCATION_MAX)
    if "notes" in spec:
        text = spec["notes"]
        if not isinstance(text, str) or len(text) > NOTES_MAX or "\r" in text or any(c not in "\n\t" and unicodedata.category(c) in HIDDEN for c in text):
            raise WriterError(f"the notes are at most {NOTES_MAX} characters of text with \\n line ends and no hidden or control character", EXIT_USAGE)
    if "reminder_minutes" in spec:
        value = spec["reminder_minutes"]
        if (value is None and operation != "create") or (value is not None and (type(value) is not int or not 0 <= value <= REMINDER_MAX)):
            raise WriterError(f"the reminder is a whole number of minutes from 0 to {REMINDER_MAX}", EXIT_USAGE)
    return spec


if __name__ == "__main__":
    import sys
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
