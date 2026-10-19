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
  {"kind": "natural", "op": ..., "how": ..., "text": "..."}   a line in the person's own words that code matched to an operation, with no model (NR-1,
                                                      runtime/natural.py): op "remind" (how "trigger" | "bare" | "note" | "command"), "reminders", "reminder-forget"
                                                      (with "id": n, or "words": what was said of it, or "many") or "calendar-event-create" (planned; how "trigger" or "ask"); `/remind <rest>` that the strict grammar above
                                                      does not claim is one too (how "command"). The time is worked out by the operation, with the clock. A line that asks for a
                                                      write to the person's own accounts (NR-5, runtime/natural_writes.py: an event, a file; a family module reads each form) is
                                                      {"kind": "natural", "op": "write", "write": <the operation>, "text"}: it is read and asked back by code, never by a model,
                                                      and only OPENS the card of its exact content
  {"kind": "reminders"} {"kind": "forget", "id": 3}   /reminders, /forget <n>
  {"kind": "pending"} {"kind": "project", "name": ""} {"kind": "help"}
  {"kind": "reply", "reply_to": "<message id>", "text": "..."}   a reply to a message, not a command
  {"kind": "text", "text": "..."}                     anything else: a line for the planning agent (a command the
                                                      bridge does not handle itself, such as /status, goes there too:
                                                      the operations layer decides, by the channel's policy)
  {"kind": "usage", "text": "Usage: ..."}             a command it handles with arguments it cannot read

The sentences it names (HELP, the usage lines) are the phrase table's English text (runtime/phrases.py); the bridge says them in the project's language, and `usage_key`
maps the sentence of a `usage` intent to its key. The intents themselves are the same in every language.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural  # noqa: E402  (the same folder: a line in the person's own words, matched by code to an operation; package NR-1)
import natural_writes  # noqa: E402  (the same folder: a line that asks for a write to the person's accounts; package NR-5)
import phrases  # noqa: E402  (the same folder: the sentences, in the project's language; the bridge says them, this module only names them)
import reminders  # noqa: E402  (the same folder: the pure part of a reminder, which reads the words after /remind)

USAGE = {"approve": "/approve <id>", "reject": "/reject <id> [note]", "release": "/release <id>", "answer": "/answer <id> <text>",
         "add": "/add <n>", "discard": "/discard <n>", "forget": "/forget <n>"}
HELP = phrases.en("HELP")
USAGE_KEYS = {phrases.en("USAGE_" + name.upper()): "USAGE_" + name.upper() for name in USAGE}      # the phrase-table key of each usage sentence
USAGE_KEYS[phrases.en("RM_USAGE")] = "RM_USAGE"


def usage_key(text: str):
    """The phrase-table key of a usage sentence this module returned in a `usage` intent (the bridge says it in the project's language), else None."""
    return USAGE_KEYS.get(text)


def _id(text: str):
    word = text.split(None, 1)[0] if text.split() else ""
    return int(word) if word.isascii() and word.isdigit() else None


def _starts_with_a_day(text: str) -> bool:
    """Whether the first words of a strict reminder's text are a day, a date or a week of some language's table ("tomorrow call", "de amanha ligar", "sexta pagar", "dia 25
    pagar", "next week call", "18/11 ligar"; one or two connectors may come first): the line is then read in the person's own words, shown and confirmed, instead of
    making a reminder for the hour with that word in its text."""
    found = natural.nt.find(text or "")
    norm, tables = found["norm"], found["tables"]
    stop = natural._stop(tables) | {w for t in tables for p in t["prefixes"] for w in p.split()}

    def lead(before: str) -> bool:
        words = re.findall(r"[a-z0-9]+", before)
        return len(words) <= 2 and all(w in stop for w in words)
    first = next(iter(found["hits"]), None)
    if first and first["kind"] in ("date", "slash", "relative") and lead(norm[:first["s"]]):
        return True
    week = natural._week(norm, tables)
    return bool(week and lead(norm[:week[0]])) or bool(re.match(r"\s*[0-9]{1,2}/[0-9]{1,2}(?:/[0-9]{2,4})?(?![0-9])", text or ""))


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
            strict = reminders.strict(rest)
            if strict and not _starts_with_a_day(strict[1]):
                return {"kind": "remind", "when": strict[0], "text": strict[1]}
            # the strict grammar does not claim it, or its words begin with a day ("/remind 15:00 amanha ligar": the day is not part of the words): the person's own words (NR-1)
            return {"kind": "natural", "op": "remind", "how": "command", "text": rest}      # the strict grammar does not claim it: the person's own words (NR-1)
        if name == "reminders":
            return {"kind": "reminders"}
        if name == "pending":
            return {"kind": "pending"}
        if name == "project":
            return {"kind": "project", "name": rest}
        if name in ("help", "start"):
            return {"kind": "help"}
        return {"kind": "text", "text": text}
    written = natural_writes.candidate(text)          # a write to the person's accounts (NR-5): before the reminders' intents, so that "marca o e-mail 3 como lido" is a mail form
    if written:
        return {"kind": "natural", "op": "write", "write": written["op"], "how": "trigger", "text": text}
    named = natural.candidate(text)          # before the reply gesture: a reminder asked as a reply to a message is still a reminder (NR-1)
    if named:
        return {"kind": "natural", "text": text, **named}
    if update.get("reply_to"):
        return {"kind": "reply", "reply_to": update["reply_to"], "text": text}
    return {"kind": "text", "text": text}
