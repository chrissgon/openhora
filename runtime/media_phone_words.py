#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The words of a reply about the captions of a video, read on the operations side (package V1d-1).

A person who looks at the captions of a video on a messaging app answers in one of three ways:

  continue     the captions are right: one of CONTINUE_WORDS, alone (a trailing "." or "!" is allowed)
  corrections  one to MAX_LINES lines, each `wrong -> right` (the arrow may be `->`, `→` or `=>`): `wrong` is one to eight words that appear in the
               captions as one run, `right` is what they become (nothing after the arrow deletes them)
  unknown      anything else

`read(text)` tells which. `find(words, wrong)` locates a `wrong` run in the caption words of the review (the rows of `captions.view`), compared without
case and without the punctuation at the edge of a word, and refuses a run that is absent (`not_found`) or appears more than once (`ambiguous`).
`edits(words, pairs)` maps the corrections to the closed edit objects of runtime/captions.py (`edit`, `delete`, `merge`), in the numbering of the revision
the words were read from; whether two corrections touch one word is left to `captions.apply_edits`, which refuses it. `post_choice(text, count)` reads the
number of a post in a list.

Nothing here reads a file or the network, or imports another module of this checkout. The words are the person's own: they are not kept or logged here.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import re
import sys

CONTINUE_WORDS = ("continue", "go on", "next",                                                    # en
                  "continuar", "continua", "seguir", "segue", "pode seguir", "pode continuar")   # pt-BR ("continue" is also pt-BR)
ARROWS = ("->", "→", "=>")      # wrong -> right; the arrow, and =>
MAX_LINES = 20                  # corrections in one reply
WRONG_MAX_WORDS = 8
RIGHT_MAX_WORDS = 20
POST_NUMBER = re.compile(r"\s*([0-9]{1,2})\s*[.)]?\s*")


class WordsError(Exception):
    """A correction that cannot be placed: `code` is `not_found` or `ambiguous`, `wrong` the words as written."""

    def __init__(self, code: str, wrong: str = ""):
        super().__init__(f"{code}: {wrong}")
        self.code = code
        self.wrong = wrong


def norm(word: str) -> str:
    """The word without case and without the characters at its two ends that are not letters or digits: "Lane," and "lane" are equal. "" means no word."""
    text = str(word).casefold()
    start, end = 0, len(text)
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not text[end - 1].isalnum():
        end -= 1
    return text[start:end]


def _pair(line: str):
    """[wrong words, right words] of one line, or None when the line is not one correction."""
    found = [(line.find(arrow), arrow) for arrow in ARROWS if line.find(arrow) != -1]
    if len(found) != 1 or sum(line.count(arrow) for arrow in ARROWS) != 1:
        return None
    position, arrow = found[0]
    wrong, right = line[:position].split(), line[position + len(arrow):].split()
    if not 1 <= len(wrong) <= WRONG_MAX_WORDS or any(not norm(w) for w in wrong) or len(right) > RIGHT_MAX_WORDS:
        return None
    return [wrong, right]


def read(text) -> dict:
    """The kind of a reply: {"kind": "continue"}, {"kind": "corrections", "pairs": [[wrong words, right words], ...]} or {"kind": "unknown"}."""
    if not isinstance(text, str) or not text.strip():
        return {"kind": "unknown"}
    whole = text.strip().lower()
    if whole[-1:] in (".", "!"):
        whole = whole[:-1].rstrip()
    if whole in CONTINUE_WORDS:
        return {"kind": "continue"}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not 1 <= len(lines) <= MAX_LINES:
        return {"kind": "unknown"}
    pairs = []
    for line in lines:
        pair = _pair(line)
        if pair is None:
            return {"kind": "unknown"}
        pairs.append(pair)
    return {"kind": "corrections", "pairs": pairs}


def find(words: list, wrong: list) -> tuple:
    """(first index, last index) of the one run of `words` (the rows of the review's words, each with `index` and `text`) that equals `wrong`, in the rows' own
    `index` values. WordsError `not_found` when none does, `ambiguous` when more than one does."""
    have = [norm(w["text"]) for w in words]
    want = [norm(x) for x in wrong]
    n = len(want)
    shown = " ".join(wrong)
    hits = [i for i in range(len(have) - n + 1) if have[i:i + n] == want] if n else []
    if not hits:
        raise WordsError("not_found", shown)
    if len(hits) > 1:
        raise WordsError("ambiguous", shown)
    return words[hits[0]]["index"], words[hits[0] + n - 1]["index"]


def edits(words: list, pairs: list) -> list:
    """The closed edit objects of runtime/captions.py for the corrections, in the numbering of the revision `words` came from."""
    out = []
    for wrong, right in pairs:
        i, j = find(words, wrong)
        n, m = j - i + 1, len(right)
        if m == 0:
            out.extend({"op": "delete", "index": k} for k in range(i, j + 1))
        elif n == m:
            out.extend({"op": "edit", "index": i + k, "text": right[k]} for k in range(n))
        elif m > n:
            out.extend({"op": "edit", "index": i + k, "text": right[k]} for k in range(n - 1))
            out.append({"op": "edit", "index": j, "text": " ".join(right[n - 1:])})      # a text of several words is a split (runtime/captions.py)
        else:
            out.extend({"op": "edit", "index": i + k, "text": right[k]} for k in range(m - 1))
            out.append({"op": "merge", "from": i + m - 1, "to": j, "text": right[m - 1]})
    return out


def post_choice(text, count: int):
    """The 1-based number a reply names, when it is a whole number (a full stop or a closing bracket after it is allowed) from 1 to `count`; else None."""
    if not isinstance(text, str):
        return None
    found = POST_NUMBER.fullmatch(text)
    if not found:
        return None
    number = int(found.group(1))
    return number if 1 <= number <= count else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
