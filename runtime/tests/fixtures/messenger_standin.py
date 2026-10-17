#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A stand-in messenger provider for the tests of the messaging bridge (runtime/messaging.py). It implements the four
verbs of providers/messenger/README.md from files in the folder STANDIN_DIR: caps.json (the capabilities), queue.json
(the updates a test queued: a list), and it records what it was sent in sent.jsonl and acks.jsonl. No network."""
from __future__ import annotations

import argparse
import json
import os

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


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="verb", required=True)
    for name in ("capabilities", "receive", "send", "ack"):
        s = sub.add_parser(name)
        s.add_argument("--platform", required=True)
        if name == "receive":
            s.add_argument("--offset", type=int, default=0)
            s.add_argument("--timeout", type=int, default=0)
        if name == "send":
            s.add_argument("--chat", required=True)
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
        count = append("sent.jsonl", {"chat": a.chat, "message": message})
        failed = bool(message.get("document")) and read("document_fail.json", False) is True      # a test asks for a document that did not go out
        print(json.dumps({"message_id": str(100 + count), **({"document_failed": True} if failed else {})}))
    else:
        append("acks.jsonl", {"ref": a.action_ref})
        print(json.dumps({"acked": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
