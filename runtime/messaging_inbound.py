# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a person sent to the messaging bridge, as an intent (runtime/messaging.py). Pure: one update of a messenger
provider (providers/messenger/README.md) in, one dict out, nothing called.

  {"kind": "action", "action": "<id>"}                a tapped button
  {"kind": "approve", "id": 12}                       /approve 12 ("sha256": the typed hash, when /approve 12 <hash> carries one)
  {"kind": "reject", "id": 12, "note": "text"|None}   /reject 12 [note]
  {"kind": "release", "id": 12}                       /release 12
  {"kind": "answer", "id": 12, "text": "..."}         /answer 12 <text>
  {"kind": "add", "id": 3} {"kind": "discard", "id": 3}   /add 3, /discard 3: the answer to the card of a file that was sent (the attachment's number)
  {"kind": "attachment", "attachments": [...], "text": "..."|None}   files sent (ATT-1), the caption in "text"; checked by messaging_provider.valid_attachments
  {"kind": "remind", "when": "15:00", "text": "..."}  /remind <time> <text> (RM-1): the time as typed (HH:MM, YYYY-MM-DD HH:MM or in <n>m|h|d) and the words;
                                                      the moment is worked out by the operation, with the clock
  {"kind": "reminders"} {"kind": "forget", "id": 3}   /reminders, /forget <n>
  {"kind": "pending"} {"kind": "project", "name": ""} {"kind": "help"}
  {"kind": "reply", "reply_to": "<message id>", "text": "..."}   a reply to a message, not a command
  {"kind": "text", "text": "..."}                     anything else: a line for the planning agent (a command the
                                                      bridge does not handle itself, such as /status, goes there too:
                                                      the operations layer decides, by the channel's policy)
  {"kind": "usage", "text": "Usage: ..."}             a command it handles with arguments it cannot read

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reminders  # noqa: E402  (the same folder: the pure part of a reminder, which reads the words after /remind)

USAGE = {"approve": "/approve <id>", "reject": "/reject <id> [note]", "release": "/release <id>", "answer": "/answer <id> <text>",
         "add": "/add <n>", "discard": "/discard <n>", "forget": "/forget <n>"}
HELP = ("Commands:\n/pending            what waits for you\n/approve <id>       approve what the last card of <id> showed\n"
        "/reject <id> [note] reject it\n/release <id>       release a delivery\n/answer <id> <text> answer a question\n"
        "/ask <question>     answer a question from the project's sources\n"
        "/add <n>            add a file you sent as a source\n/discard <n>        delete a file you sent\n"
        "/remind <time> <text> a reminder sent back to you once (15:00, 2026-10-20 09:30 or in 2h)\n/reminders          the reminders that wait\n"
        "/forget <n>         cancel a reminder\n"
        "/project [name]     choose the project your lines go to\n/help               this list\n"
        "Any other line goes to the planning agent. Which of these your project turns on is in its configuration "
        "(channels.messaging).")


def _id(text: str):
    word = text.split(None, 1)[0] if text.split() else ""
    return int(word) if word.isascii() and word.isdigit() else None


def parse(update: dict) -> dict:
    action = update.get("action")
    if action:
        return {"kind": "action", "action": action}
    text = (update.get("text") or "").strip()
    if update.get("attachments"):
        return {"kind": "attachment", "attachments": list(update["attachments"]), "text": text or None}
    if not text:
        return {"kind": "ignore"}
    if text.startswith("/"):
        pieces = text.split(None, 1)       # the command word ends at any blank (a line end, a no-break space), so `/remind\n15:00 x` is a command and never a line for a model
        word, rest = pieces[0], (pieces[1] if len(pieces) > 1 else "")
        name, rest = word[1:].split("@", 1)[0].lower(), rest.strip()
        if name in USAGE:
            number = _id(rest)
            tail = rest.split(None, 1)[1].strip() if len(rest.split(None, 1)) > 1 else ""
            if number is None or (name == "answer" and not tail):
                return {"kind": "usage", "text": "Usage: " + USAGE[name]}
            if name == "answer":
                return {"kind": "answer", "id": number, "text": tail}
            if name == "reject":
                return {"kind": "reject", "id": number, "note": tail or None}
            if name == "approve" and tail:
                return {"kind": name, "id": number, "sha256": tail.split()[0].lower()}
            return {"kind": name, "id": number}
        if name == "remind":
            try:
                when, body = reminders.split_line(rest)
            except ValueError as e:
                return {"kind": "usage", "text": str(e)}
            return {"kind": "remind", "when": when, "text": body}
        if name == "reminders":
            return {"kind": "reminders"}
        if name == "pending":
            return {"kind": "pending"}
        if name == "project":
            return {"kind": "project", "name": rest}
        if name in ("help", "start"):
            return {"kind": "help"}
        return {"kind": "text", "text": text}
    if update.get("reply_to"):
        return {"kind": "reply", "reply_to": update["reply_to"], "text": text}
    return {"kind": "text", "text": text}
