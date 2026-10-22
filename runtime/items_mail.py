#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The mail half of the list a phone reads (slice S15b, beside runtime/ops_items.py): what a person needs of a message in one line, and "the last e-mail" with the start of its text.

  blocks(text)                  {n: {"when", "from", "body"}} of the messages the text of a mail snapshot prints (`## 1. 2026-10-21 09:39`, From:, Subject:, the body indented by two spaces)
  who(name_or_from, address)    the sender as a person reads it: the display name when the message has one, else the address with the random token of its local part taken out
  readable_address(address)     `no-reply-3f9a8c21@mail.vendor.example` -> `no-reply@mail.vendor.example`
  when_text(when, now, cfg)     "today 14:02", "yesterday 09:39", "Mon 20/10 18:10" in the project's language, in the machine's zone
  preview(lines)                the start of the body: plain text, no link or markup, cut on a word at about PREVIEW_CHARS
  count_of(said)                how many messages a line asks for ("o último email" 1, "os 3 últimos emails" 3, "the last three emails" 3), by code and from a closed list of
                                words in the six languages, or None when the line asks for no count

The text of a snapshot is read by runtime/ops_items.py after its hash was checked against the store's record; this file only parses what it is given. A message is another person's
words: nothing here prints, logs or keeps a word of it, and the preview is cut from the snapshot's own cleaned body (links already replaced, control characters gone), never from a provider.

Standard library only. Runs on Python 3.9: python3 runtime/items_mail.py --help
"""
from __future__ import annotations

import datetime
import re
import sys
from email.utils import parseaddr

import natural
import phrases
import snapshot_text

PREVIEW_CHARS = 300      # about this many characters of the body, cut on a word
NAME_MAX = 60            # characters of a display name
SUBJECT_MAX = 120        # characters of a subject on a phone
COUNT_MAX = 20           # the most messages a line may ask for (the list prints at most this many for a source)
BLOCK = re.compile(r"## ([0-9]{1,4})\. (.*)")
STAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2})")
SEPARATOR = re.compile(r"([-_.+=])")
PLACEHOLDERS = ("(no text)", "(nothing but the history of earlier messages)")
NOISE = re.compile(r"<[^<>]{0,200}>|[*`#>|\[\]{}~]+|[-=_]{3,}")


def blocks(text: str) -> dict:
    """{n: {"when" ("YYYY-MM-DD HH:MM" in the zone the snapshot was made in, or None), "from" (the From: line as printed), "body" (the lines, two spaces taken off)}}."""
    out, current, in_body = {}, None, False
    for line in text.splitlines():
        head = BLOCK.fullmatch(line)
        if head:
            stamp = STAMP.fullmatch(head.group(2).strip())
            current = out.setdefault(int(head.group(1)), {"when": head.group(2).strip() if stamp else None, "from": "", "body": []})
            in_body = False
        elif current is not None and not in_body:
            if line.startswith("From: "):
                current["from"] = line[6:]
            elif not line.strip():
                in_body = bool(current.get("seen_subject"))
            elif line.startswith("Subject: "):
                current["seen_subject"] = True
        elif current is not None and in_body and (line.startswith("  ") or not line.strip()):
            current["body"].append(line[2:])
    for entry in out.values():
        entry.pop("seen_subject", None)
    return out


def _random(piece: str) -> bool:
    """A piece of a local part that is a token and not a word: four digits or more, or six letters and digits with a digit in them, or a long run of letters and digits."""
    return bool(re.fullmatch(r"[0-9]{4,}", piece) or (re.fullmatch(r"[0-9a-z]{6,}", piece) and (any(c.isdigit() for c in piece) or len(piece) >= 12)))


def readable_address(address: str) -> str:
    """The address with the random tokens of its local part taken out, and the domain kept: `no-reply-3f9a8c21@mail.vendor.example` is `no-reply@mail.vendor.example`; a local part that is
    all token is the domain alone. An address that is not one is returned as it is."""
    local, at, domain = (address or "").partition("@")
    if not at or not domain:
        return address or ""
    parts = SEPARATOR.split(local)
    kept = ""
    for index in range(0, len(parts), 2):
        piece = parts[index]
        if piece and not _random(piece.lower()):
            kept += (parts[index - 1] if kept and index else "") + piece
    return f"{kept}@{domain}" if kept else domain


def who(sender: str, address: str) -> str:
    """The sender of a message as a person reads it: the display name of the From: line when it has one that is not the address, else the readable form of the address."""
    name = parseaddr(sender or "")[0].strip().strip("\"'").strip()
    name = snapshot_text.one_line(name, NAME_MAX)
    if name and "@" not in name:
        return name
    return readable_address(address or parseaddr(sender or "")[1])


def when_text(when, now: datetime.datetime, cfg: dict) -> str:
    """"today 14:02", "yesterday 09:39" or "Mon 20/10 18:10" for a stamp `YYYY-MM-DD HH:MM`, in the project's language; "" when the stamp cannot be read."""
    found = STAMP.fullmatch(when or "")
    if not found:
        return ""
    try:
        day = datetime.date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
    except ValueError:
        return ""
    clock = f"{found.group(4)}:{found.group(5)}"
    today = now.date()
    if day == today:
        return f"{phrases.text('NW_ITEMS_TODAY', cfg)} {clock}"
    if day == today - datetime.timedelta(days=1):
        return f"{phrases.text('NW_ITEMS_YESTERDAY', cfg)} {clock}"
    return f"{phrases.text(phrases.WEEKDAY_KEYS[day.weekday()], cfg)} {day.strftime('%d/%m')} {clock}"


def preview(lines: list) -> str:
    """The start of a body as plain text: the lines joined, the snapshot's `<link: host>` and `<address>` marks and any markup taken out, white space collapsed, the cut mark dropped,
    and about PREVIEW_CHARS characters cut on a word with an ellipsis. "" for a message with no text."""
    text = " ".join(" ".join(line.split()) for line in lines).strip()
    if text in PLACEHOLDERS:
        return ""
    if text.endswith(snapshot_text.CUT):
        text = text[:-len(snapshot_text.CUT)]
    text = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(NOISE.sub(" ", text).split()))
    if len(text) <= PREVIEW_CHARS:
        return text
    cut = text[:PREVIEW_CHARS]
    cut = cut[:cut.rfind(" ")] if " " in cut[PREVIEW_CHARS // 2:] else cut
    return cut.rstrip(" ,;:.-") + "…"


# --- how many messages a line asks for ------------------------------------------------------------------------------------------------------------------
# The words are folded (lower case, no accent) as natural.normal writes them; each group is the closed list of the six languages the tables ship.

NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,                      # pt  validate: allow english-only -- the closed words of the languages a line may be written in
           "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,                                          # en
           "uno": 1, "dos": 2, "cuatro": 4, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,                                                                      # es
           "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,                                        # fr
           "ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,                          # de
           "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "dieci": 10}                                                         # it
LAST_ONE = {"ultimo", "ultima", "latest", "newest", "dernier", "derniere", "letzte", "letzter", "letztes", "neueste", "neuester"}          # a word for "the last" in the singular
LAST_MANY = {"ultimos", "ultimas", "ultimi", "ultime", "derniers", "dernieres", "letzten", "neuesten"}                                       # ... in the plural
LAST_EN = {"last", "recent"}          # English `last` is a singular only before a name of NOUNS: "the last email" is one message, "my last emails" is a list
NOUNS = {"email", "mail", "message", "mensagem", "mensaje", "courriel", "nachricht", "messaggio", "correo"}          # a message's name in the singular, in the six languages (`e mail` folds to two words)
FILLER = {"o", "a", "os", "as", "the", "my", "meu", "meus", "minha", "minhas", "mi", "mis", "mon", "mes", "mein", "meine", "il", "i", "le", "la", "les", "los", "las", "el", "der", "die", "das",
          "de", "do", "da", "of", "e"}          # words that may stand between the word for "last" and its number or noun


def _number(word: str):
    if word.isdigit() and 1 <= int(word) <= 999:
        return min(int(word), COUNT_MAX)
    return NUMBERS.get(word)


def _next(words: list) -> str:
    """The first word of `words` that is not a filler (or "")."""
    return next((w for w in words if w not in FILLER), "")


def count_of(said):
    """How many messages the line asks for: 1 for "o último e-mail" / "the last email" / "dernier e-mail", N for "os 3 últimos" / "the last three" / "letzten 5 E-Mails", None when the line asks
    for no count (a plain list, or "os últimos e-mails" with no number). A number written in digits or in one of the closed words, right before or right after the word for "last"."""
    words = natural.normal(said if isinstance(said, str) else "").split()
    for index, word in enumerate(words):
        if word not in LAST_ONE and word not in LAST_MANY and word not in LAST_EN:
            continue
        for neighbour in (_next(reversed(words[max(0, index - 2):index])), _next(words[index + 1:index + 3])):
            found = _number(neighbour)
            if found:
                return found
        if word in LAST_ONE or (word in LAST_EN and _next(words[index + 1:index + 3]) in NOUNS):
            return 1
    return None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
