#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a phone is told when the operations layer fails in a project that does not speak English (slice S14, limit L62): the project's language, never the layer's English.

The operations layer raises its errors in English, precisely (`pending decision 14 is a question: reject takes a plan, an acceptance or an effect`): useful on the page,
in the terminal and in the conversation, nonsense in a Portuguese chat. `said(text, cfg, failure)` is the net under the places that hand such a text to a phone:

  * the project's language is English, or has no table: the text is returned as it was (an English phone keeps the precise text, as before);
  * a text the table of the language says by a template (a decision that does not exist, one that is not open, one of another kind than the command takes) is the
    template's sentence, with the number and the decision's kind as words of the language;
  * any other text that comes from the operations layer (`failure` is true, or the text starts with `error: `) is the one plain sentence PHONE_FAILED, unless it already
    holds a letter that only the language uses (it was said in the language already);
  * any other text is returned as it was: a person's words and the sentences of the phrase table are not touched.

The page, the terminal and the stored text are never changed: this runs on the way to a messaging app only.

Standard library only. Runs on Python 3.9: python3 runtime/phone_errors.py --help
"""
from __future__ import annotations

import functools
import os
import re
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402  (the same folder)

PREFIX = "error: "
LOCALIZED = re.compile("[À-ɏ]")      # a letter with an accent: the text is already in a language that is not English
KIND = r"(?P<kind>[a-z]+)"
NUMBER = r"(?P<number>\d+)"
SETTLED = ("resolved", "approved", "rejected", "cancelled", "answered", "released", "dismissed", "accepted", "executed")      # a status that reads "was already <status>"
# (pattern of the English text, phrase key, the groups the sentence takes). The kind is said as a word of the language; the status, too.
TEMPLATES = (
    (re.compile(r"no pending decision " + NUMBER), "NO_SUCH_DECISION", ("number",)),
    (re.compile(r"[Pp]ending decision " + NUMBER + r" is (?P<status>" + "|".join(SETTLED) + r"), not open"), "NOT_OPEN_DONE", ("number", "status")),
    (re.compile(r"[Pp]ending decision " + NUMBER + r" is (?P<status>[a-z-]+), not open"), "NOT_OPEN", ("number", "status")),
    (re.compile(r"[Pp]ending decision " + NUMBER + r" is an? " + KIND + r": it is approved or rejected, not answered or released"), "NOT_ANSWERABLE", ("number", "kind")),
    (re.compile(r"[Pp]ending decision " + NUMBER + r" is an? " + KIND + r": it is answered, not released"), "NOT_RELEASABLE", ("number", "kind")),
    (re.compile(r"[Pp]ending decision " + NUMBER + r" is an? " + KIND + r": (?:reject takes a plan, an acceptance(?:,| or) an effect(?: or a question)?|only an effect is rejected here)"),
     "NOT_REJECTABLE", ("number", "kind")),
    (re.compile(r"question " + NUMBER + r" was not dismissed: its request still has other decisions open"), "QUESTION_HAS_COMPANY", ("number",)),
    (re.compile(re.escape("use the card's button, or /approve <id> as the whole line")), "PHONE_USE_CARD", ()),
)


@functools.lru_cache(maxsize=None)
def _said_already(tag: str):
    """One regular expression for every sentence of the language's table (its fields match any text): a text that matches was said in the language already."""
    parts = []
    for sentence in (phrases.TABLE.get(tag) or {}).values():
        made = "".join(re.escape(lit) + (".+?" if name is not None else "") for lit, name, _spec, _conv in string.Formatter().parse(sentence))
        if made:
            parts.append(made)
    return re.compile("|".join(parts), re.S) if parts else None


def spoken(body: str, cfg=None) -> bool:
    """Whether `body` is in the project's language already: it holds a letter only that language uses, or it is a sentence of the phrase table."""
    found = _said_already(phrases.tag(cfg))
    return bool(LOCALIZED.search(body) or (found and found.fullmatch(body)))


def english(cfg=None) -> bool:
    """Whether the project's phone speaks English (or a language with no table), where nothing here applies."""
    return phrases.tag(cfg) not in phrases.TABLE or phrases.tag(cfg) == phrases.DEFAULT


def said(text, cfg=None, failure: bool = False):
    """`text` as a phone may read it (see the module's text). `failure` says the text is an error of the operations layer (an `OpsError`'s text); a text that starts with
    `error: ` is one too."""
    if not isinstance(text, str):
        return text
    if english(cfg):      # an English phone keeps the precise text, except for a decision that is already settled, which is told plainly
        found = TEMPLATES[1][0].fullmatch(text[len(PREFIX):] if text.startswith(PREFIX) else text)
        return phrases.text("NOT_OPEN_DONE", cfg, number=found.group("number"), status=found.group("status")) if found and (failure or text.startswith(PREFIX)) else text
    prefixed = text.startswith(PREFIX)
    if not (prefixed or failure):
        return text
    body = text[len(PREFIX):] if prefixed else text
    for pattern, key, groups in TEMPLATES:
        found = pattern.fullmatch(body)
        if found:
            fields = {g: found.group(g) for g in groups}
            if "kind" in fields:
                fields["kind"] = phrases.kind_word(fields["kind"], cfg)
            if "status" in fields:
                fields["status"] = phrases.status(fields["status"], cfg)
            return phrases.phone(key, cfg, **fields)
    if spoken(body, cfg):
        return body
    return phrases.phone("PHONE_FAILED", cfg)


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
