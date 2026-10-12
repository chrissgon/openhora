# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a person sent to the messaging bridge, as an intent (runtime/messaging.py). Pure: one update of a messenger
provider (providers/messenger/README.md) in, one dict out, nothing called.

  {"kind": "action", "action": "<id>"}                a tapped button
  {"kind": "approve", "id": 12}                       /approve 12
  {"kind": "reject", "id": 12, "note": "text"|None}   /reject 12 [note]
  {"kind": "release", "id": 12}                       /release 12
  {"kind": "answer", "id": 12, "text": "..."}         /answer 12 <text>
  {"kind": "pending"} {"kind": "project", "name": ""} {"kind": "help"}
  {"kind": "reply", "reply_to": "<message id>", "text": "..."}   a reply to a message, not a command
  {"kind": "text", "text": "..."}                     anything else: a line for the planning agent (a command the
                                                      bridge does not handle itself, such as /status, goes there too:
                                                      the operations layer decides, by the channel's policy)
  {"kind": "usage", "text": "Usage: ..."}             a command it handles with arguments it cannot read

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

USAGE = {"approve": "/approve <id>", "reject": "/reject <id> [note]", "release": "/release <id>", "answer": "/answer <id> <text>"}
HELP = ("Commands:\n/pending            what waits for you\n/approve <id>       approve what the last card of <id> showed\n"
        "/reject <id> [note] reject it\n/release <id>       release a delivery\n/answer <id> <text> answer a question\n"
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
    if not text:
        return {"kind": "ignore"}
    if text.startswith("/"):
        word, _, rest = text.partition(" ")
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
            return {"kind": name, "id": number}
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
