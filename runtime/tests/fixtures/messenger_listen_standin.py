#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A stand-in messenger provider that listens, for the tests of the messaging bridge (runtime/tests/test_messaging_listen.py).
It implements `capabilities` and the long-lived `listen` of providers/messenger/README.md from files in the folder
STANDIN_DIR (caps.json overrides the capabilities; a null removes a key), and acts on the lines it is given, never on time.

script.json (optional) is {"1": step, "2": step, "default": step}: the step for the Nth start of the process, else
"default", else {}. A step has these keys, all optional:
  ready          false: never write the ready event (default true)
  emit           lines written right after ready: an object is written as JSON; {"raw": "text"} as that text; {"over": n}
                 as n bytes of "x" and a newline; {"bytes": "hex"} as those bytes and a newline
  after_send     {"<n>": [lines]}: written after the answer to the Nth send of this start. A line with "action": "@first"
                 taps the first button of the message just sent (its id), and "reply_to": "@sent" replies to it
  ignore_eof     true: keep running when stdin ends (the bridge must escalate)
  ignore_term    true: ignore SIGTERM
  grandchild     true: start a `sleep` child in the same group and record its pid
  noise          true: print() to stdout before the protocol starts (the dup of fd 1 must keep it out of the protocol)
  stderr         text written to stderr before anything else
  die            an exit code: exit at once, before the ready event
  paused         a reason: write an error event of kind "paused" with it and exit 3 at once, before the ready event
  paused_after_ready  a reason: after ready and the emitted lines, write that event and exit 3 (a session lost while connected)
A send to the chat "crash-1" makes the first start deliver it (it is recorded) and exit 1 without answering, "exit-3" writes the error event and exits 3,
"exit-2" does the same with 2, "silent" is never answered, "fail-usage", "fail-failed" and "fail-deferred" are answered ok:false
(the kind is the rest of the chat's name), "defer-first-<n>" is answered the same way for its first n sends, "defer-once" is answered ok:false, kind "deferred", the first time it is sent to
(then runs after_send "1" as a send does) and as any chat after, "no-id" is answered ok:true without a message_id, "doc-failed" ok:true with a message_id and document_failed:true. Records, one JSON object per line, in STANDIN_DIR: starts.jsonl (pid, pgid,
the arguments), requests.jsonl (every line it read), sent.jsonl (chat and message of each send it answered). No network.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys

PLATFORMS = ("chirp",)
DEFAULT_CAPS = {"max_text": 4096, "buttons": True, "max_buttons": 6, "max_button_label": 40, "lists": False,
                "max_list_rows": 0, "url_buttons": True, "reply_context": True, "documents": False, "listen": True}


def folder() -> str:
    return os.environ["STANDIN_DIR"]


def read(name, default):
    try:
        with open(os.path.join(folder(), name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def append(name, value) -> int:
    path = os.path.join(folder(), name)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(value) + "\n")
    with open(path, encoding="utf-8") as f:
        return len(f.readlines())


def listen(platform) -> int:
    out = os.fdopen(os.dup(1), "wb")   # the protocol's descriptor; fd 1 then points at stderr, so a stray print cannot corrupt a line
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def write(line: dict) -> None:
        out.write(json.dumps(line, ensure_ascii=True).encode("ascii") + b"\n")
        out.flush()

    def emit(item, sent=None) -> None:
        if "raw" in item:
            out.write(item["raw"].encode("utf-8") + b"\n")
        elif "over" in item:
            out.write(b"x" * item["over"] + b"\n")
        elif "bytes" in item:
            out.write(bytes.fromhex(item["bytes"]) + b"\n")
        else:
            item = json.loads(json.dumps(item))
            update = item.get("update", {})
            if sent and update.get("action") == "@first":
                update["action"] = sent["message"]["actions"][0]["id"]
            out.flush()
            write(item)
            return
        out.flush()

    number = append("starts.jsonl", {"pid": os.getpid(), "pgid": os.getpgid(0), "argv": sys.argv[1:]})
    script = read("script.json", {})
    step = script.get(str(number), script.get("default", {}))
    if step.get("stderr"):
        print(step["stderr"], file=sys.stderr, flush=True)
    if step.get("die") is not None:
        return step["die"]
    if step.get("paused") is not None:
        write({"event": "error", "kind": "paused", "reason": step["paused"]})
        return 3
    if step.get("ignore_term"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if step.get("grandchild"):
        child = subprocess.Popen(["sleep", "300"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        append("grandchildren.jsonl", {"pid": child.pid})
    if step.get("noise"):
        print("a library printed this to stdout")
    if step.get("ready", True):
        write({"event": "ready"})
    for item in step.get("emit", []):
        emit(item)
    if step.get("paused_after_ready") is not None:
        write({"event": "error", "kind": "paused", "reason": step["paused_after_ready"]})
        return 3
    sends = 0
    deferred = set()
    counts = {}
    for raw in sys.stdin.buffer:
        append("requests.jsonl", json.loads(raw))
        request = json.loads(raw)
        if request.get("op") != "send":
            continue
        chat = request["chat"]
        if chat == "crash-1" and number == 1:
            append("sent.jsonl", {"chat": chat, "message": request["message"]})
            return 1
        if chat in ("exit-3", "exit-2"):
            write({"event": "error", "kind": "not-configured" if chat == "exit-3" else "usage",
                   "reason": "no session; run the pairing command in a terminal"})
            return int(chat[-1])
        if chat == "silent":
            continue
        if chat == "defer-once" and "defer-once" not in deferred:
            deferred.add(chat)
            sends += 1
            write({"id": request["id"], "ok": False, "kind": "deferred", "reason": "outside the window; a reminder was sent"})
            for item in step.get("after_send", {}).get(str(sends), []):
                emit(item)
            continue
        if chat.startswith("defer-first-") and counts.get(chat, 0) < int(chat[len("defer-first-"):]):
            counts[chat] = counts.get(chat, 0) + 1
            sends += 1
            write({"id": request["id"], "ok": False, "kind": "deferred", "reason": "outside the window"})
            for item in step.get("after_send", {}).get(str(sends), []):
                emit(item)
            continue
        if chat in ("fail-usage", "fail-failed", "fail-deferred"):
            write({"id": request["id"], "ok": False, "kind": chat[5:], "reason": "refused by the stand-in"})
            continue
        if chat == "no-id":
            write({"id": request["id"], "ok": True})
            continue
        if chat == "doc-failed":      # the text went out and its document did not: ok, with the id, and the flag the bridge reads
            sends += 1
            count = append("sent.jsonl", {"chat": chat, "message": request["message"]})
            write({"id": request["id"], "ok": True, "message_id": f"m{count}", "document_failed": True})
            continue
        sends += 1
        sent = {"chat": chat, "message": request["message"]}
        count = append("sent.jsonl", sent)
        write({"id": request["id"], "ok": True, "message_id": f"m{count}"})
        for item in step.get("after_send", {}).get(str(sends), []):
            if item.get("update", {}).get("reply_to") == "@sent":
                item = {**item, "update": {**item["update"], "reply_to": f"m{count}"}}
            emit(item, sent)
    if step.get("ignore_eof"):
        signal.pause()
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="verb", required=True)
    for name in ("capabilities", "listen"):
        sub.add_parser(name).add_argument("--platform", required=True)
    a = p.parse_args()
    if a.verb == "capabilities":
        caps = {**DEFAULT_CAPS, **read("caps.json", {})}
        print(json.dumps({k: v for k, v in caps.items() if v is not None}))   # a null in caps.json removes the key
        return 0
    return listen(a.platform)


if __name__ == "__main__":
    raise SystemExit(main())
