#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A stand-in messenger provider for the tests of the messaging bridge (runtime/messaging.py). It implements the four
verbs of providers/messenger/README.md from files in the folder STANDIN_DIR: caps.json (the capabilities), queue.json
(the updates a test queued: a list), and it records what it was sent in sent.jsonl and acks.jsonl. No network.

`fetch-attachment --platform p --ref r --out d --max-bytes n` (ATT-1) writes the file `files/<r>` of STANDIN_DIR as `<d>/content` (O_EXCL, mode 0600) and prints
{"bytes", "sha256"}. A ref in gone.json (a list) is a file the platform no longer serves: exit 1, the last line of stderr exactly "gone".
A ref in notgone.json exits 1 with "gone" first on stderr and another last line (a message that merely mentions it). A ref in fail.json exits 1 with another
reason. A file over --max-bytes is not written: exit 2. A ref in lie.json is written with one byte more than the count it prints (a provider that cannot be taken
at its word). A ref in outside.json is written as a link to a file elsewhere. Every call is recorded in fetches.jsonl (the ref, the folder, the cap). The
capabilities gain `attachments` and `max_attachment_bytes` from caps.json."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

PLATFORMS = ("telegram",)
DEFAULT_CAPS = {"max_text": 4096, "buttons": True, "max_buttons": 6, "max_button_label": 40, "lists": False,
                "max_list_rows": 0, "url_buttons": True, "reply_context": True, "documents": False}


def folder() -> str:
    return os.environ["STANDIN_DIR"]


def read(name: str, default):
    try:
        with open(os.path.join(folder(), name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def append(name: str, value) -> int:
    path = os.path.join(folder(), name)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(value) + "\n")
    with open(path, encoding="utf-8") as f:
        return len(f.readlines())


def fetch(a) -> int:
    append("fetches.jsonl", {"ref": a.ref, "out": a.out, "max_bytes": a.max_bytes})
    if a.ref in read("gone.json", []):
        print("the platform no longer serves this file", file=sys.stderr)
        print("gone", file=sys.stderr)         # the rule: exit 1 and the last non-empty line of stderr is exactly `gone`
        return 1
    if a.ref in read("fail.json", []):
        print("the platform refused the download", file=sys.stderr)
        return 1
    if a.ref in read("notgone.json", []):
        print("gone: not really, the platform answered 500 and the file is not gone", file=sys.stderr)
        print("the platform refused the download", file=sys.stderr)
        return 1
    try:
        with open(os.path.join(folder(), "files", a.ref), "rb") as f:
            data = f.read()
    except OSError:
        print("no such file", file=sys.stderr)
        print("gone", file=sys.stderr)
        return 1
    if len(data) > a.max_bytes:
        print("the file is over the cap", file=sys.stderr)
        return 2
    target = os.path.join(a.out, "content")
    if a.ref in read("outside.json", []):
        os.symlink(os.path.join(folder(), "files", a.ref), target)
    else:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data + (b"x" if a.ref in read("lie.json", []) else b""))
    print(json.dumps({"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="verb", required=True)
    for name in ("capabilities", "receive", "send", "ack", "typing", "fetch-attachment"):
        s = sub.add_parser(name)
        s.add_argument("--platform", required=True)
        if name == "fetch-attachment":
            s.add_argument("--ref", required=True)
            s.add_argument("--out", required=True)
            s.add_argument("--max-bytes", type=int, required=True)
        if name == "receive":
            s.add_argument("--offset", type=int, default=0)
            s.add_argument("--timeout", type=int, default=0)
        if name in ("send", "typing"):
            s.add_argument("--chat", required=True)
        if name == "send":
            s.add_argument("--message-file", required=True)
        if name == "ack":
            s.add_argument("--action-ref", required=True)
    a = p.parse_args()
    if a.verb == "capabilities":
        print(json.dumps({**DEFAULT_CAPS, **read("caps.json", {})}))
    elif a.verb == "receive":
        updates = [u for u in read("queue.json", []) if u["update_id"] >= a.offset]
        print(json.dumps({"updates": updates, "next_offset": max([u["update_id"] for u in updates], default=a.offset - 1) + 1}))
    elif a.verb == "send":
        with open(a.message_file, encoding="utf-8") as f:
            message = json.load(f)
        file = message.get("file")
        if file and read("file_usage.json", False) is True:      # S18: a provider that refuses the file before it sends anything (exit 2); nothing is recorded
            print("the file to send cannot be sent here", file=sys.stderr)
            return 2
        if file:      # S18: what the provider saw at the path while it ran (the bytes are read here, so a test knows the file existed at the send), and whether the folder was private
            with open(file["path"], "rb") as handle:
                seen = handle.read()
            message = {**message, "file": {**file, "bytes_hex": seen.hex(), "mode": oct(os.stat(file["path"]).st_mode & 0o777), "folder_mode": oct(os.stat(os.path.dirname(file["path"])).st_mode & 0o777)}}
        count = append("sent.jsonl", {"chat": a.chat, "message": message})
        failed = (bool(message.get("document")) and read("document_fail.json", False) is True) or (bool(file) and read("file_fail.json", False) is True)      # a test asks for a document or a file that did not go out
        print(json.dumps({"message_id": str(100 + count), **({"document_failed": True} if failed else {})}))
    elif a.verb == "fetch-attachment":
        return fetch(a)
    elif a.verb == "typing":      # S10: records the call; a test asks for a failure with fail_typing.json
        append("typing.jsonl", {"chat": a.chat})
        if read("fail_typing.json", False) is True:
            print("the platform refused the indicator", file=sys.stderr)
            return 1
        print(json.dumps({"typing": True}))
    else:
        append("acks.jsonl", {"ref": a.action_ref})
        print(json.dumps({"acked": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
