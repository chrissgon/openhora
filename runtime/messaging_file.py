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
import sys
import tempfile

SEND_GROUP = "send-files"
READ_GROUP = "read-files"
CHANNEL = "messaging"


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


def allowed(operations, policy, key: str, attachment, caps) -> bool:
    """Whether the file may still go: the app's limits are known, the sender's profile in `policy` (the project's accepted channels mapping, read now) holds both groups, and the
    file is a document or a photo within the limits. `operations` is the module runtime/operations.py (the bridge's own handle on it)."""
    if not isinstance(attachment, dict) or not isinstance(caps, dict) or attachment.get("kind") not in ("photo", "document"):
        return False
    data = attachment.get("data")
    if not isinstance(data, (bytes, bytearray)) or not data or not isinstance(attachment.get("name"), str) or not attachment["name"]:
        return False
    if len(data) > caps["max_bytes"] or (attachment["kind"] == "photo" and len(data) > caps["photo_max_bytes"]):
        return False
    return bool(operations.holds(SEND_GROUP, CHANNEL, policy, key) and operations.holds(READ_GROUP, CHANNEL, policy, key))


@contextlib.contextmanager
def staged(attachment: dict):
    """The `file` entry of a neutral message for this attachment: the bytes in one new file of a new private folder, which is removed when the block ends, whatever happens in it."""
    folder = tempfile.mkdtemp(prefix="messenger-file-")
    try:
        os.chmod(folder, 0o700)
        path = os.path.join(folder, "content")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0), 0o600)
        with os.fdopen(descriptor, "wb") as out:
            out.write(attachment["data"])
        yield {"name": attachment["name"], "kind": attachment["kind"], "path": path}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
