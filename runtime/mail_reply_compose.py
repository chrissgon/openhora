#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The text of a reply that the person described, worded by the model (BL7-2, an extension of slice S7; limits L60, L61 and L63).

"responde a Marlene agradecendo pelo convite e explicando com jeitinho que nao vou poder ir" does not dictate a text: it says what the reply should do. The interpreter's span
for the body is then a description, and until BL7-2 it went on the card as the text. The maintainer's rule of S7 (2026-10-20, a new e-mail) and his line of 2026-10-26 ("resposta
redigida") say the secretary words it. This file decides WHEN a reply's body is a description and, only then, asks the same compose route (`mail_compose.write`, the same pinned
prompt, the same rate, day and breaker limits, the same checks of the answer) for the text. It sends, approves and opens nothing: the reply card shows the WHOLE text and its approval
binds the card's hash (L55, L64), exactly as for every reply card.

  described(body, line)             True when the body DESCRIBES the text instead of dictating it. Both are folded by `natural.normal`; `first` is the body's first word (its second
                                    when the first is "e", "and", "y", "et" or "und"), `before` the one word right before the body's place in the line. In this order:
                                      1. the body starts with the closed marker of a literal text ("exact text:", "texto exato:"...): False;
                                      2. `first` or `before` is a say verb of the closed list SAY ("dizendo", "saying", "diciendo", "disant", "sagend", "dicendo"...): False. Reported
                                         words stay literal: "dizendo que aceito a proposta" is the text, as it was;
                                      3. `first` or `before` is a describing verb of the closed list HOW ("agradecendo", "explicando", "thanking"...): True;
                                      4. the body holds a manner phrase of the closed list MANNER as whole words ("com jeitinho", "politely"...): True;
                                      5. otherwise False.
                                    Pure: nothing is read, written or called.
  text(ctx, channel, sender, body)  the reply's text: `mail_compose.write(ctx, channel, sender, [], None, body, reply=True)["body"]` when composing is on for the sender and the call
                                    gave a valid answer, else the person's own words (`body`, as before BL7-2). Never raises. Logs, prints and stores nothing.

What the model may see for a reply: the date, the chat's language, an EMPTY recipient line, an EMPTY subject line and the person's own words (at most 1000 characters). Never the
message answered, its sender, its subject or its text, and never the reply's recipient (the index's From, L60): none of them is an argument of this file's functions, so none can be
sent. A composed body with an address or a link is refused by `mail_compose.validate` and falls back to the person's words; the model's subject is dropped.

Standard library only (the other modules are imported when a function needs them). Runs on Python 3.9: python3 runtime/mail_reply_compose.py --help
"""
from __future__ import annotations

import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mail_compose  # noqa: E402
import natural  # noqa: E402

# Closed lists, written folded (`natural.normal`: case folded, accents removed). A phrase is matched as whole words.
JOINERS = frozenset(("e", "and", "y", "et", "und"))      # a body that starts with "and" starts with its second word
SAY = frozenset((      # the words that report what the person said to say: the body after them is the text, as the person worded it
    "dizendo", "falando", "saying", "telling", "diciendo", "disant", "sagend", "dicendo"))
HOW = frozenset((      # the verbs that say what the reply should do, not what it says
    "agradecendo", "agradeca", "agradece", "pedindo", "explicando", "explique", "explica", "recusando", "recuse", "aceitando", "confirmando", "confirme", "perguntando",
    "pergunte", "lembrando", "avisando", "informando", "desculpando", "justificando", "parabenizando", "convidando", "cancelando", "negociando", "sugerindo", "propondo",
    "elogiando", "cobrando", "reclamando",
    "thanking", "thank", "explaining", "explain", "asking", "declining", "decline", "accepting", "confirming", "confirm", "apologizing", "apologising", "apologize", "apologise",
    "reminding", "informing", "congratulating", "inviting", "suggesting", "proposing", "complaining",
    "agradeciendo", "explicando", "pidiendo", "rechazando", "aceptando", "confirmando", "preguntando", "disculpandome",
    "remerciant", "expliquant", "demandant", "refusant", "acceptant", "confirmant",
    "bedanke", "bedanken", "erklare", "entschuldige",
    "ringraziando", "spiegando", "chiedendo", "rifiutando", "accettando", "confermando", "scusandomi"))
MANNER = tuple(natural.normal(p) for p in (      # how the reply should sound: a phrase of these in the body is a description of the text
    "com jeitinho", "com educacao", "educadamente", "de forma educada", "gentilmente", "com carinho", "politely", "nicely", "kindly", "gently", "firmly", "con cortesia",
    "amablemente", "poliment", "gentiment", "hoflich"))


def _words(text: str) -> list:
    return natural.normal(text).split()


def _place(words: list, body: list):
    """The index in `words` where the whole-word sequence `body` first stands, or None."""
    if not body:
        return None
    for at in range(len(words) - len(body) + 1):
        if words[at:at + len(body)] == body:
            return at
    return None


def described(body: str, line: str) -> bool:
    """Whether the body of a reply describes its text (see the module's text). Never raises: a fault is "not described", the person's own words."""
    try:
        if not isinstance(body, str) or mail_compose.MARKER.match(body):
            return False      # the literal marker is checked first: "texto exato: agradecendo..." is the text
        mine = _words(body)
        if not mine:
            return False
        first = mine[1] if mine[0] in JOINERS and len(mine) > 1 else mine[0]
        ahead = _words(line)
        at = _place(ahead, mine)
        before = ahead[at - 1] if at else None      # the one word right before the body's place in the line (None when the body opens the line or is not found)
        near = {first, before} - {None}
        if near & SAY:
            return False
        if near & HOW:
            return True
        padded = " " + " ".join(mine) + " "
        return any(" " + phrase + " " in padded for phrase in MANNER if phrase)
    except Exception:      # noqa: BLE001
        return False


def text(ctx: dict, channel, sender, body: str) -> str:
    """The text of the reply (see the module's text): the model's worded body when composing is on and its answer passed `mail_compose.validate`, else `body`. Never raises."""
    try:
        if mail_compose.available(ctx, channel, sender):
            got = mail_compose.write(ctx, channel, sender, [], None, body, reply=True)
            if got.get("composed") and isinstance(got.get("body"), str) and got["body"].strip():
                return got["body"]
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the person's words
        pass
    return body


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
