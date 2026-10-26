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
                                    when the first is "e", "and", "y", "et" or "und"), `before` the one word right before the body's place in the line. In this order, and the first
                                    rule that holds decides:
                                      1. the literal marker ("exact text:", "texto exato:"...): the body starts with it, or the RAW line holds one that ends at or before the body's
                                         place (the interpreter's span may leave it out), or the body is not found in the line and the line holds one anywhere: False;
                                      2. the line's shape shows dictation: the raw character right before the body is a colon or an opening quote, or the body itself starts with
                                         a quote: False ("responde ao Pedro: obrigado pelo convite, com carinho");
                                      3. a say verb of the closed list SAY ("dizendo", "saying", "diciendo", "disant", "sagend", "dicendo"...) is `first`, is `before`, is one of the
                                         up to three words before a complementizer (que, that, dass, che, qu) that is `before` or that opens the body ("en disant que", "saying that",
                                         "dizendo a ela que"): False. Anything reported after a say verb stays literal, whatever it holds;
                                      4. `first` or `before` is a describing verb of the closed list HOW ("agradecendo", "explicando", "thanking"...), except "thank" followed by
                                         "you" or "u" (that is a thanks written to the recipient): True;
                                      5. the body holds a manner phrase of the closed list MANNER as whole words ("com jeitinho", "politely"...): True;
                                      6. otherwise False.
                                    Pure: nothing is read, written or called.
  text(ctx, channel, sender, body)  the reply's text: `mail_compose.write(ctx, channel, sender, [], None, body, reply=True)["body"]` when composing is on for the sender and the call
                                    gave a valid answer, else the person's own words (`body`, as before BL7-2). Never raises. Logs, prints and stores nothing.
  worded(ctx, channel, sender, body)
                                    `(text, composed)`: the same, with whether the model's wording is the text (the caller adds a notice to the card when it is not).

What the model may see for a reply: the date, the chat's language, an EMPTY recipient line, an EMPTY subject line and the person's own words (at most 1000 characters). Never the
message answered, its sender, its subject or its text, and never the reply's recipient (the index's From, L60): none of them is an argument of this file's functions, so none can be
sent. A composed body with an address or a link is refused by `mail_compose.validate` and falls back to the person's words; the model's subject is dropped.

Standard library only (the other modules are imported when a function needs them). Runs on Python 3.9: python3 runtime/mail_reply_compose.py --help
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mail_compose  # noqa: E402
import natural  # noqa: E402

# Closed lists, written folded (`natural.normal`: case folded, accents removed). A phrase is matched as whole words.
COMPLEMENTIZERS = frozenset(("que", "that", "dass", "che", "qu"))      # "qu'il" folds to "qu" and "il": the words that open reported speech after a say verb
THANKS_TO_YOU = ("you", "u")      # "thank you" is a thanks written to the recipient, "thank her" describes one
QUOTES = "\"\u201c\u2018\u00ab\u201e\u201a\u2039'"      # the opening quotes (the ASCII apostrophe counts only after a space or a bracket, `_dictated_shape`)
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


def _raw_context(body: str, line: str):
    """(the raw text of the line before the body, True) when the body is a piece of the line as typed (compared without regard to case), else ("", False)."""
    needle = body.strip().lower()
    where = line.lower().find(needle) if needle and isinstance(line, str) else -1
    return (line[:where], True) if where >= 0 else ("", False)


def _dictated_shape(head: str, body: str) -> bool:
    """Whether the raw line shows the body as written words: a colon or an opening quote right before it, or a body that starts with a quote."""
    if body.strip()[:1] in QUOTES:
        return True
    tail = head.rstrip()
    if tail.endswith(":"):
        return True
    return bool(tail) and tail[-1] in QUOTES and (len(tail) == 1 or tail[-2].isspace() or tail[-2] in "([")


def _how(word, following) -> bool:
    return word in HOW and not (word == "thank" and following in THANKS_TO_YOU)


def described(body: str, line: str) -> bool:
    """Whether the body of a reply describes its text (see the module's text). Never raises: a fault is "not described", the person's own words."""
    try:
        if not isinstance(body, str) or mail_compose.MARKER.match(body):
            return False      # the literal marker is checked first: "texto exato: agradecendo..." is the text
        mine = _words(body)
        if not mine:
            return False
        text = line if isinstance(line, str) else ""
        head, found = _raw_context(body, text)
        if found:
            if any(m.end() <= len(head) for m in mail_compose.MARKER.finditer(text)):
                return False      # the marker stands before the body, though the span left it out
            if _dictated_shape(head, body):
                return False
        elif mail_compose.MARKER.search(text):
            return False      # the body is not found as typed: a marker anywhere keeps the words literal
        k = 1 if mine[0] in JOINERS and len(mine) > 1 else 0
        first = mine[k]
        ahead = _words(text)
        at = _place(ahead, mine)
        back = ahead[max(0, at - 4):at] if at else []      # the up to four words right before the body
        before = back[-1] if back else None
        if first in SAY or before in SAY:
            return False
        if (before in COMPLEMENTIZERS and any(w in SAY for w in back[-4:-1])) or (mine[0] in COMPLEMENTIZERS and any(w in SAY for w in back[-3:])):
            return False      # reported words, whatever they hold: "dizendo que confirme...", "saying that I will gently...", "en disant que..."
        if _how(first, mine[k + 1] if len(mine) > k + 1 else None) or (before is not None and _how(before, mine[0])):
            return True
        padded = " " + " ".join(mine) + " "
        return any(" " + phrase + " " in padded for phrase in MANNER if phrase)
    except Exception:      # noqa: BLE001
        return False


def worded(ctx: dict, channel, sender, body: str) -> tuple:
    """(the text of the reply, whether the model worded it): the model's body when composing is on and its answer passed `mail_compose.validate`, else (`body`, False). Never raises."""
    try:
        if mail_compose.available(ctx, channel, sender):
            got = mail_compose.write(ctx, channel, sender, [], None, body, reply=True)
            if got.get("composed") and isinstance(got.get("body"), str) and got["body"].strip():
                return got["body"], True
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the person's words
        pass
    return body, False


def text(ctx: dict, channel, sender, body: str) -> str:
    """The text of the reply (see the module's text): `worded(...)[0]`. Never raises."""
    return worded(ctx, channel, sender, body)[0]


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
