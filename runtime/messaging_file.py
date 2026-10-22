#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The file a reply carries on a messaging app (slice S18): a small helper of the messaging bridge, never a gate by itself.

The operations layer (runtime/ops_file_read.py) hands the bridge a found file as bytes in memory, `{"name", "kind": "photo" | "document", "data"}`, when the sender holds the group
`send-files` and the app can carry a file. This module is the bridge's side of the three things that follow:

  limits(capabilities)                    what the app can carry, from the provider's capabilities: `{"max_bytes", "photo_max_bytes", "photo_types", "types"}`, or None when the
                                          provider does not declare `send_files` (nothing is then asked of the operations layer and every reply is the text it always was)
  allowed(operations, policy, key, attachment, caps)   the check made AGAIN at the moment of the send: the sender's profile in the configuration read now still holds `send-files`
                                          and `read-files`, and the file is still within what the app takes (limit: a sender removed or narrowed since the search loses the file)
  refusal(operations, policy, key, attachment, caps)   why it may not go now: "read", "right" or "limit" (`allowed` is its "" as a boolean)
  sweep()                                 at the start of the bridge: remove the folders of this module's exact prefix, owned by this user, mode 0700, older than an hour (a crash leaves one)
  staged(attachment)                      a context manager: the bytes written to ONE temporary file in a folder made for this send (mode 0700, the file 0600), the message's
                                          `file` entry `{"name", "kind", "path"}` as its value, and the folder removed in a `finally` however the send ends

Nothing here logs or keeps a name, a folder or a byte; the temporary folder exists only for the length of one send. The provider reads the file from the path and sends it
(providers/messenger/README.md, the `file` entry of the neutral message); the file's bytes are not in the message file, which a provider's listen mode could not carry.

Standard library only. Runs on Python 3.9: python3 runtime/messaging_file.py --help
"""
from __future__ import annotations

import contextlib
import os
import shutil
import stat
import sys
import tempfile
import time

SEND_GROUP = "send-files"
READ_GROUP = "read-files"
CHANNEL = "messaging"
PREFIX = "messenger-file-"      # the name every folder of `staged` starts with, and the only folders `sweep` removes
SWEEP_AGE = 3600.0             # seconds: a folder of a send is gone in a minute; one older than an hour was left by a crash


def limits(capabilities) -> dict | None:
    """What the app can carry as a file, from the provider's capabilities, or None when it declares no `send_files` (or no size) or the capabilities are not a mapping."""
    if not isinstance(capabilities, dict) or capabilities.get("send_files") is not True:
        return None
    biggest = capabilities.get("max_send_bytes")
    if type(biggest) is not int or biggest <= 0:
        return None
    photo = capabilities.get("max_photo_bytes")
    return {"max_bytes": biggest, "photo_max_bytes": photo if type(photo) is int and photo > 0 else 0,
            "photo_types": [t for t in capabilities.get("photo_types") or [] if isinstance(t, str)], "types": [t for t in capabilities.get("send_types") or [] if isinstance(t, str)]}


def refusal(operations, policy, key: str, attachment, caps) -> str:
    """Why the file may not go NOW, or "" when it may: "read" (the sender's profile in `policy`, the project's accepted channels mapping read now, no longer holds `read-files`: nothing
    that was found is shown any more), "right" (it no longer holds `send-files`) or "limit" (the app's limits are not known, or the file is not a document or a photo within them).
    `operations` is the module runtime/operations.py (the bridge's own handle on it)."""
    if not operations.holds(READ_GROUP, CHANNEL, policy, key):
        return "read"
    if not operations.holds(SEND_GROUP, CHANNEL, policy, key):
        return "right"
    if not isinstance(attachment, dict) or not isinstance(caps, dict) or attachment.get("kind") not in ("photo", "document"):
        return "limit"
    data = attachment.get("data")
    if not isinstance(data, (bytes, bytearray)) or not data or not isinstance(attachment.get("name"), str) or not attachment["name"]:
        return "limit"
    if len(data) > caps["max_bytes"] or (attachment["kind"] == "photo" and len(data) > caps["photo_max_bytes"]):
        return "limit"
    return ""


def allowed(operations, policy, key: str, attachment, caps) -> bool:
    """Whether the file may still go: `refusal` says nothing."""
    return refusal(operations, policy, key, attachment, caps) == ""


@contextlib.contextmanager
def staged(attachment: dict):
    """The `file` entry of a neutral message for this attachment: the bytes in one new file of a new private folder, which is removed when the block ends, whatever happens in it."""
    folder = tempfile.mkdtemp(prefix=PREFIX)
    try:
        os.chmod(folder, 0o700)
        path = os.path.join(folder, "content")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
        with os.fdopen(descriptor, "wb") as out:
            out.write(attachment["data"])
        yield {"name": attachment["name"], "kind": attachment["kind"], "path": path}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def sweep(now=None, older_than: float = SWEEP_AGE) -> int:
    """Remove the folders `staged` made and a crash left behind: in the temporary folder, a real folder (not a link) whose name starts with exactly `messenger-file-`, owned by this
    user, mode 0700, and last changed more than `older_than` seconds ago (an hour). Anything else in the temporary folder is left alone. Returns how many were removed; a fault on one folder is
    skipped, never raised, and nothing is logged (a name here is a random token, but the folder held a person's file)."""
    base = tempfile.gettempdir()
    now = time.time() if now is None else now
    removed = 0
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for name in names:
        if not name.startswith(PREFIX):
            continue
        path = os.path.join(base, name)
        try:
            info = os.lstat(path)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700 or now - info.st_mtime <= older_than:
                continue
            shutil.rmtree(path)
            removed += 1
        except OSError:
            continue
    return removed


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
