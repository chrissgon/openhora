#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the two mailbox writers share (package W3): providers/writer/gmail.py and providers/writer/outlook-mail.py. A name with an underscore is never listed as an
implementation by providers/resolve.py, so this file is a module, not a provider. It holds no HTTP, no credential and no request: only the parts that must be the
same in both writers so that they cannot drift apart.

  WriterError            an error with an exit code and a one-line message (the writers print "error: <message>" and exit with the code)
  state_dir, folder      the ledger folder of a writer: <state>/writer-<implementation>/ (0700, files 0600, an exclusive file lock)
  claim, settle, peek    the ledger of a request: ONE ENTRY PER MESSAGE (key + the message's id), `pending` before the call that touches it and `done` after its
                         answer, so a request that stopped half way is known message by message (the rules of providers/mailer/smtp.py)
  canonical, sha         the one text a request is hashed from, and its sha256 (`would_sha256` of a dry run)
  read_spec              the spec file a writer is handed (ids, the base each message was read in, the labels or the folder, a draft's text), read without following
                         a link and checked
  KEY, GMAIL_ID, GRAPH_ID, ...   the full-match patterns of the ids that enter a path

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
SPEC_MAX_BYTES = 256 * 1024
IDS_MAX = 20                                                   # messages in one request (the platform's cap)
KEY = re.compile(r"(?!-)[A-Za-z0-9._-]{1,128}")                # an id, a key or a change key never starts with a hyphen: a flag would read it
GMAIL_ID = re.compile(r"(?!-)[A-Za-z0-9_-]{1,64}")
GRAPH_ID = re.compile(r"(?!-)[A-Za-z0-9_=+-]{1,600}")
GMAIL_LABEL = re.compile(r"(?!-)[A-Za-z0-9_-]{1,64}")
GRAPH_FOLDER = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")
CHANGE_KEY = re.compile(r"(?!-)[A-Za-z0-9_=+/.-]{1,200}")
INTERNET_ID = re.compile(r"[\x21-\x7e]{1,998}")
ADDRESS = re.compile(r"(?!-)[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}@[A-Za-z0-9.-]{1,253}")
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")                  # control, format, separators, surrogate, private use
INVISIBLE_LETTERS = "\u115f\u1160\u3164\uffa0\u2800\u180e\u034f"      # letters and marks that draw nothing
SUBJECT_MAX, BODY_MAX, RECIPIENTS_MAX = 200, 100 * 1024, 20


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


def entry_key(key: str, item: str) -> str:
    """The ledger key of one message (or of the one draft) of a request: the request's key and a short hash of the item, so that no id of the service is a key."""
    return f"{key}:{sha(item)[:20]}"


def claim(implementation: str, key: str, items: dict, operation: str) -> dict:
    """Record the entry of each item `pending` before the call that touches it. `items` is {item: the sha256 of the request for that item}. Returns {item:
    (state, entry)}: "new", "pending" (an earlier attempt's outcome is not known) or "done". A key used for another request is a usage error, and nothing is
    recorded then."""
    with ledger_locked(implementation) as ledger:
        found, made = {}, {}
        for item, digest in items.items():
            entry = ledger["keys"].get(entry_key(key, item))
            if entry is None:
                made[item] = {"status": "pending", "operation": operation, "payload_sha256": digest, "created_at": now_iso()}
                found[item] = ("new", made[item])
            elif entry.get("payload_sha256") != digest:
                raise WriterError(f"the key {key} was used for another request: a key is one request", EXIT_USAGE)
            else:
                found[item] = ("done" if entry.get("status") == "done" else "pending", dict(entry))
        for item, entry in made.items():
            ledger["keys"][entry_key(key, item)] = entry
        return found


def settle(implementation: str, key: str, items, status: str, **facts) -> None:
    """done: record the answer for each item. released: forget the entries that are still `pending` (nothing changed), so the same request may be tried again."""
    with ledger_locked(implementation) as ledger:
        for item in items:
            name = entry_key(key, item)
            entry = ledger["keys"].get(name)
            if entry is None:
                continue
            if status == "done":
                entry.update(facts)
                entry["status"], entry["done_at"] = "done", now_iso()
            elif entry.get("status") == "pending":
                del ledger["keys"][name]


def annotate(implementation: str, key: str, items, **facts) -> None:
    """Note facts on the entries of items, whatever their status (the id of a draft made; that a message is about to be sent): written BEFORE the call they describe."""
    with ledger_locked(implementation) as ledger:
        for item in items:
            entry = ledger["keys"].get(entry_key(key, item))
            if entry is not None:
                entry.update(facts)


def peek(implementation: str, key: str, items) -> dict:
    """{item: "done" | "pending" | "absent"}, read without writing anything or making any folder (a dry run, and `message-meta`)."""
    found = folder(implementation, create=False)
    keys = (_read_json(os.path.join(found, LEDGER), {"keys": {}}).get("keys") or {}) if found else {}
    return {item: (keys.get(entry_key(key, item)) or {}).get("status", "absent") for item in items}


# --- the texts ---------------------------------------------------------------------------------------------------------------------------------------


def one_line_text(value, what: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum or value != value.strip() \
            or any(unicodedata.category(c) in HIDDEN or c in INVISIBLE_LETTERS for c in value):
        raise WriterError(f"{what} is one line of at most {maximum} characters, with no hidden or control character", EXIT_USAGE)
    return value


def body_text(value) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > BODY_MAX or "\r" in value \
            or any(c not in "\n\t" and (unicodedata.category(c) in HIDDEN or c in INVISIBLE_LETTERS) for c in value):
        raise WriterError(f"the body is text of at most {BODY_MAX} bytes with \\n line ends and no hidden or control character", EXIT_USAGE)
    return value


def address_list(value, what: str) -> list:
    if not isinstance(value, list) or len(value) > RECIPIENTS_MAX or not all(isinstance(a, str) and ADDRESS.fullmatch(a) and a.count("@") == 1 for a in value):
        raise WriterError(f"{what} is a list of at most {RECIPIENTS_MAX} plain addresses", EXIT_USAGE)
    return list(value)


# --- the spec file ------------------------------------------------------------------------------------------------------------------------------------


def read_json_file(path, flag: str = "--spec-file") -> dict:
    """The JSON object in a private file, read without following a link. Usage error (exit 2) when it cannot be read or is not an object."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, TypeError):
        raise WriterError(f"{flag} cannot be read (missing, or a link)", EXIT_USAGE) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise WriterError(f"{flag} is not a regular file", EXIT_USAGE)
        with os.fdopen(os.dup(fd), "rb") as f:
            data = f.read(SPEC_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > SPEC_MAX_BYTES:
        raise WriterError(f"{flag} is too large", EXIT_USAGE)
    try:
        spec = json.loads(data.decode("utf-8"))
    except ValueError:
        spec = None
    if not isinstance(spec, dict):
        raise WriterError(f"{flag} is one JSON object", EXIT_USAGE)
    return spec


def exact_keys(spec: dict, keys, what: str) -> None:
    if set(spec) != set(keys):
        raise WriterError(f"the spec of {what} has exactly the keys {', '.join(keys)}", EXIT_USAGE)


def id_list(value, pattern, what: str = "ids") -> list:
    """1 to IDS_MAX distinct ids, each a full match of `pattern`."""
    if not isinstance(value, list) or not 1 <= len(value) <= IDS_MAX or len(set(value)) != len(value) \
            or not all(isinstance(i, str) and pattern.fullmatch(i) for i in value):
        raise WriterError(f"{what} is 1 to {IDS_MAX} distinct message ids", EXIT_USAGE)
    return list(value)


def positions(numbers) -> str:
    """The positions (1-based, in the spec's order) of a set of messages, as a short text: `1,2,5`."""
    return ",".join(str(n) for n in sorted(numbers))


if __name__ == "__main__":
    import sys
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
