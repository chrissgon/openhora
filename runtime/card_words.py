# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The words that decide a decision card (package S2, limit L64): a pure reading of one line.

`card_word(line)` answers {"op": "approve" | "reject", "n": position | None, "all": bool} when the WHOLE line is one closed form of the lists below, and None for
everything else. A line is a form when it is: polite words, one approve or reject phrase, then either nothing, or an optional article ("o", "the", "number") with a
number or an ordinal ("aprovo o 2", "approve the second"), or the word for all ("aprova todos", "todos nao"), then polite words. Accents, case and punctuation do not
matter. There is never an open tail: "pode marcar o dentista" and "pode marcar amanha as 3" are not forms, they are requests. A line that is both an approve and a reject form
is None; a slash line, an empty line and a line of more than `LINE_WORDS_MAX` words are None.

A line in QUESTION FORM is never a card word (ACEITE-37, the maintainer, 2026-10-30): "sim?", "pode?", "nao?" (the line ends in a question mark, however much punctuation follows it) and a line that asks
for the act with "can you", "could you" or "would you" ("can you approve", "could you cancel") or, in Portuguese, with "poderia" or "consegue" ("poderia aprovar", "consegue aprovar") ask something and decide nothing; they go on to the model as any free line. `question_form(line)` says it,
`card_shape(line)` is the reading without that rule (the shape of an approve or a reject form, asked or not), for the readers that must keep treating such a line as card-shaped (they are named in the
function's text), and `card_word` is the shape unless the line is a question. "sim!", "sim.", "SIM", "ok", "pode" and "yes" stay forms.

The lists are this module's own data: the two languages the runtime has tables for (`en`, `pt-BR`), read together, because a person may write in either whatever the project's
language is (the same rule the natural-request tables follow). The approve and reject phrases of the maintainer's own list (2026-10-20): "sim", "ok", "aprovo", "aprova", "pode",
"pode marcar", "pode mandar", "pode salvar", "manda ver", "aprovado" (+ "pode aprovar"); "yes", "ok", "approve", "approved", "go ahead"; "nao", "rejeito", "rejeita", "cancela",
"deixa"; "no", "reject", "cancel". The ordinals, the articles and the word for all are this package's choice.

This module decides nothing: it reads no card, no policy and no ledger. The bridge (runtime/messaging_bridge.py) executes what a word means, only when every condition of L64
holds, through the same call as the card's button. `all` is returned as it is; the caller never approves it.

`reply_line(text)` (S10) is the line an e-mail reply decides with: a reply carries a phone's signature or the quoted card under its words ("sim", a blank line, "Enviado do meu iPhone"), which
made it more than one phrase. The first non-empty line is the line; everything after it must be a signature or a quote (it begins at a delimiter line: "--", "Enviado do meu",
"Sent from my", "Enviado de", "Get Outlook for", a quote header such as "Em ... escreveu:" or "On ... wrote:", or a line that starts with ">"), else the text is not one phrase
and nothing is returned ("sim" and then "mas muda o horario" on its own line is a request, never an approval). Only the bridge calls it, and only on a platform whose acts are replies.

Standard library only. Runs on Python 3.9: python3 runtime/card_words.py --help
"""
from __future__ import annotations

import re
import sys
import unicodedata

LINE_WORDS_MAX = 8      # a longer line is a sentence, never a form
ORDINALS_MAX = 10
ORDINAL_ARTICLES = ["a"]      # an article that may stand before an ordinal word ("a primeira") and never before a number ("\u00e0 1" is a time)

WORDS = {
    "en": {
        "approve": ["yes", "ok", "approve", "approved", "go ahead"],
        "reject": ["no", "reject", "cancel"],
        "all": ["all"],
        "articles": ["the", "number", "n"],
        "polite": ["please", "pls", "can you", "could you", "would you", "hey", "hi"],
        "ordinals": [["first"], ["second"], ["third"], ["fourth"], ["fifth"], ["sixth"], ["seventh"], ["eighth"], ["ninth"], ["tenth"]],
    },
    "pt-BR": {
        "approve": ["sim", "ok", "aprovo", "aprova", "aprovar", "aprovado", "pode", "pode marcar", "pode mandar", "pode salvar", "manda ver"],
        "reject": ["nao", "rejeito", "rejeita", "cancela", "deixa"],
        "all": ["todos", "todas"],
        "articles": ["o", "numero", "n"],
        "polite": ["por favor", "pf", "pode", "poderia", "consegue", "oi", "ola", "ei"],
        # no "segunda", "quarta", "quinta" or "sexta": they are the days of the week ("pode marcar segunda" is a request, not the second card)
        "ordinals": [["primeiro", "primeira"], ["segundo"], ["terceiro", "terceira"], ["quarto"], ["quinto"], ["sexto"],
                     ["setimo", "setima"], ["oitavo", "oitava"], ["nono", "nona"], ["decimo", "decima"]],
    },
}
QUESTION_LEADS = ("can you", "could you", "would you", "poderia", "consegue")      # a line that asks for the act in these words is a question, whatever follows ("can you approve", "poderia aprovar"); "pode" is not one: "pode aprovar" is an imperative
QUESTION_MARK = re.compile(r"[?\uff1f][^\w]*$")      # a question mark followed by nothing but punctuation and blanks: "sim?", "pode ?", "nao?!"
PHRASE = re.compile(r"[a-z0-9]+(?: [a-z0-9]+)*")
LISTS = ("approve", "reject", "all", "articles", "polite")


def merged() -> dict:
    """The lists of every language, joined: {"approve": [...], "reject": [...], "all": [...], "articles": [...], "polite": [...], "ordinals": [[...] x ORDINALS_MAX]}."""
    out = {key: [] for key in LISTS}
    out["ordinals"] = [[] for _ in range(ORDINALS_MAX)]
    for table in WORDS.values():
        for key in LISTS:
            out[key] += [p for p in table.get(key, []) if p not in out[key]]
        for at, words in enumerate(table.get("ordinals", [])):
            if at < ORDINALS_MAX:
                out["ordinals"][at] += [p for p in words if p not in out["ordinals"][at]]
    return out


def check() -> None:
    """ValueError when a list is not made of phrases (a-z and 0-9 separated by one space, no accent, no character a regular expression means anything by), when an
    ordinal list is longer than ORDINALS_MAX, or when a phrase is in two of `approve`, `reject` and `all`."""
    for table in WORDS.values():
        if len(table.get("ordinals", [])) > ORDINALS_MAX:
            raise ValueError(f"card words: at most {ORDINALS_MAX} ordinals")
    words = merged()
    for key in LISTS:
        for phrase in words[key]:
            if not PHRASE.fullmatch(phrase):
                raise ValueError(f"card words: {key} holds {phrase!r}, which is not a phrase of a-z and 0-9 separated by one space")
    for group in words["ordinals"]:
        for phrase in group:
            if not PHRASE.fullmatch(phrase):
                raise ValueError(f"card words: ordinals holds {phrase!r}, which is not a phrase of a-z and 0-9 separated by one space")
    for first, second in (("approve", "reject"), ("approve", "all"), ("reject", "all")):
        both = set(words[first]) & set(words[second])
        if both:
            raise ValueError(f"card words: {sorted(both)[0]!r} is in {first} and in {second}")


def normal(line: str) -> str:
    """The line in lower case, accents off, every other character a space, blanks collapsed."""
    folded = unicodedata.normalize("NFKD", line.lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def _alternation(phrases: list) -> str:
    return "|".join(re.escape(p) for p in sorted(set(phrases), key=lambda p: (-len(p), p)))


_COMPILED = {}


def _forms() -> dict:
    if not _COMPILED:
        check()
        given = merged()
        polite = given["polite"]
        lead = f"(?:(?:{_alternation(polite)})\\s+)*" if polite else ""
        tail = f"(?:\\s+(?:{_alternation(polite)}))*" if polite else ""
        ordinal_at = {w: at + 1 for at, words in enumerate(given["ordinals"]) for w in words}
        articles = f"(?:(?:{_alternation(given['articles'])})\\s+)?"
        for_ordinal = f"(?:(?:{_alternation(given['articles'] + ORDINAL_ARTICLES)})\\s+)?"      # "a primeira": the feminine article, before an ordinal word only
        place = f"{articles}(?P<n>[0-9]{{1,2}})" + (f"|{for_ordinal}(?P<o>{_alternation(list(ordinal_at))})" if ordinal_at else "")
        position = f"(?:\\s+(?:{place}))"
        every = f"(?P<a>{_alternation(given['all'])})"
        shapes = {}
        for op in ("approve", "reject"):
            form = f"(?:{_alternation(given[op])})"
            whole_only = [w for w in given[op] if w == "pode" or w.startswith("pode ")]      # "pode marcar", "pode mandar", "pode salvar": a whole-line approval, never followed by a position ("pode marcar 3")
            with_position = [w for w in given[op] if w not in whole_only]
            first = f"(?:{_alternation(whole_only)})" if whole_only else None
            second = f"(?:{_alternation(with_position)})(?:{position})?" if with_position else None
            core = "|".join(x for x in (first, second) if x)
            shapes[op] = [re.compile(f"{lead}(?:{core}){tail}"),
                          re.compile(f"{lead}{form}\\s+{every}{tail}"),
                          re.compile(f"{lead}{every}\\s+{form}{tail}")]
        _COMPILED.update(shapes=shapes, ordinal_at=ordinal_at)
    return _COMPILED


SIGNATURE_STARTS = ("enviado do meu", "sent from my", "enviado de", "get outlook for")      # a phone's one-line signature: short, with no comma (a longer line is the sender's words)
SIGNATURE_WORDS_MAX = 6
QUOTE_HEADER = re.compile(r"(?:em|on)\s.*(?:escreveu|wrote)\s*:?", re.I)


def _delimiter(line: str) -> bool:
    """Whether a stripped line starts the signature block or the quoted history for good: the "--" delimiter, a quoted line, or a quote header."""
    return line == "--" or line.startswith(("-- ", ">")) or bool(QUOTE_HEADER.fullmatch(line))


def _phone_signature(line: str) -> bool:
    return line.lower().startswith(SIGNATURE_STARTS) and len(line.split()) <= SIGNATURE_WORDS_MAX and "," not in line


def _opens_tail(line: str) -> bool:
    """Whether a stripped line opens the signature or the quoted history of an e-mail reply."""
    return _delimiter(line) or _phone_signature(line)


def reply_line(text):
    """The first non-empty line of an e-mail reply, when everything after it is a signature or a quote; else "" (see the module's text). Every later non-empty line is
    checked: a line that is not a signature or a quote (the sender's own words, even after a phone's one-line signature) makes the text more than one phrase; from a
    delimiter ("--", a quote) on, the rest is the signature or the history and is not read."""
    if not isinstance(text, str):
        return ""
    first = None
    for line in (raw.strip() for raw in text.split("\n")):
        if not line:
            continue
        if first is None:
            if _opens_tail(line):
                return ""
            first = line
        elif not _opens_tail(line):
            return ""
        elif _delimiter(line):
            return first
    return first or ""


def question_form(line) -> bool:
    """Whether the line asks instead of saying: it ends in a question mark (a trailing run of punctuation after it does not hide it), or it asks for the act with one of QUESTION_LEADS as whole words."""
    if not isinstance(line, str):
        return False
    if QUESTION_MARK.search(line.strip()):
        return True
    flat = f" {normal(line)} "
    return any(f" {lead} " in flat for lead in QUESTION_LEADS)


def card_word(line):
    """{"op": "approve" | "reject", "n": position | None, "all": bool} when the whole line is one closed form that is not a question, else None (see the module's text)."""
    return None if question_form(line) else card_shape(line)


def card_shape(line):
    """What `card_word` answers without the question rule: the closed form the line has, asked or not. The readers that keep the line away from something other than the card words (the change of
    a card in runtime/ops_card_revise.py, the claim of a research answer in runtime/research_reply.py) use it, so that "sim?" is still no change and no claim."""
    if not isinstance(line, str) or not line.strip() or line.lstrip().startswith("/"):
        return None
    flat = normal(line)
    if not flat or len(flat.split()) > LINE_WORDS_MAX:
        return None
    forms = _forms()
    found = {}
    for op, shapes in forms["shapes"].items():
        for shape in shapes:
            hit = shape.fullmatch(flat)
            if hit:
                groups = hit.groupdict()
                n = groups.get("n")
                number = int(n) if n is not None else forms["ordinal_at"].get(groups.get("o")) if groups.get("o") else None
                if n is not None and number < 1:
                    return None
                found[op] = {"op": op, "n": number, "all": bool(groups.get("a"))}
                break
    return next(iter(found.values())) if len(found) == 1 else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
