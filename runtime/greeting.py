#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A greeting, or a plain request for help, gets a greeting back and a short summary of what the assistant can do for THIS sender (slice S5).

Code decides; no model reads the line. `is_greeting(line, language=None)` is true only when the WHOLE line is made of closed phrases: a greeting ("oi", "bom dia", "hello",
"hola", "bonjour", "hallo", "ciao", "tudo bem?"...), a request for help or for what the assistant does ("ajuda", "o que voce faz", "help", "what can you do"...), and polite
fillers ("por favor", "please"). Accents, case, punctuation and emoji do not matter; a letter stretched at the end of a short word ("oiii") does not matter. A line that
goes on to ask for anything ("oi, lista os emails", "bom dia, me lembra de X") is not a greeting: it is read as it always was. The lists are this module's own data, in the six
languages the interpreter reads (pt-BR, en, es, fr, de, it). With `language=None` every list is read, because a person may write in any of them whatever the project's language
is (the rule of runtime/card_words.py); with a tag only that language's lists are, and a tag with no list reads English. With `helps=False` only the greetings are: the page, the terminal and the conversation keep the help
in words they always had (the list of commands), and only a messaging app, which has no list of commands to type, answers it with the summary.

The answer is built by `ops_say._greeting_reply` (a greeting in the project's language and one short line for each family of capabilities the SENDER'S policy permits, from the
phrase table), which the row `greeting` of runtime/ops_turn.py calls before the interpreter's seam for any sender who may talk, and which the messaging bridge lets through to `say` for a help line of such
a sender. This module reads nothing of the project: a pure reading of one line.

`as_question(line, language=None)` is true for a line that is wholly a greeting (never a help form) and carries a question mark ("oi, tudo bem?"): it asks how the other one is, so it is never
the answer yes to a question (package L64H; the kind `plan-confirm` of runtime/messaging_turn.py reads it).

Standard library only. Runs on Python 3.9: python3 runtime/greeting.py --help
"""
from __future__ import annotations

import re
import sys
import unicodedata


LINE_WORDS_MAX = 10      # a longer line is a sentence, never a greeting
QUESTION_MARKS = ("?", "\u00bf")      # read after NFKC, so the full-width question mark is "?"
STRETCH_MAX = 4          # extra copies of the last letter of a short word that may be stretched ("oiiii")
STRETCHED = ("oi", "ola", "opa", "hi", "hey", "hello", "hola", "hallo", "ciao")

# Phrases are written as normal() writes a line: a-z and 0-9, one space between words, no accent ("j ai", "qu est ce", "how s").
WORDS = {
    "pt-BR": {
        "greet": ["oi", "oie", "ola", "opa", "salve", "fala", "e ai", "eai", "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom", "tudo certo", "td bem", "como vai",
                  "como vai voce", "como voce esta", "como esta", "beleza"],
        "help": ["ajuda", "me ajuda", "preciso de ajuda", "o que voce faz", "o que voce pode fazer", "o que voce sabe fazer", "o que voce consegue fazer",
                 "o que consegue fazer", "no que voce pode me ajudar", "como voce pode me ajudar", "como pode me ajudar"],
        "filler": ["por favor", "pf", "pessoal"],
    },
    "en": {
        "greet": ["hi", "hello", "hey", "hey there", "hi there", "hello there", "howdy", "yo", "good morning", "good afternoon", "good evening", "good night", "how are you",
                  "how are you doing", "how is it going", "how s it going", "what s up", "whats up", "sup"],
        "help": ["help", "help me", "i need help", "what can you do", "what can you do for me", "what do you do", "what are you able to do", "how can you help",
                 "how can you help me", "what can i ask you", "what can i ask"],
        "filler": ["please", "pls"],
    },
    "es": {
        "greet": ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "que tal", "como estas", "como esta", "como andas", "todo bien"],
        "help": ["ayuda", "ayudame", "necesito ayuda", "que puedes hacer", "que sabes hacer", "que haces", "en que puedes ayudarme", "como puedes ayudarme"],
        "filler": ["por favor"],
    },
    "fr": {
        "greet": ["bonjour", "bonsoir", "salut", "coucou", "allo", "ca va", "comment ca va", "comment vas tu", "comment allez vous"],
        "help": ["aide", "aide moi", "j ai besoin d aide", "que peux tu faire", "que peux tu faire pour moi", "que pouvez vous faire", "que sais tu faire",
                 "qu est ce que tu sais faire", "qu est ce que tu peux faire", "que fais tu", "comment peux tu m aider"],
        "filler": ["s il te plait", "s il vous plait", "svp", "stp"],
    },
    "de": {
        "greet": ["hallo", "guten morgen", "guten tag", "guten abend", "gute nacht", "moin", "servus", "gruss dich", "wie geht s", "wie gehts", "wie geht es dir"],
        "help": ["hilfe", "hilf mir", "ich brauche hilfe", "was kannst du", "was kannst du tun", "was kannst du machen", "was kannst du alles", "was machst du",
                 "wie kannst du mir helfen"],
        "filler": ["bitte"],
    },
    "it": {
        "greet": ["ciao", "salve", "buongiorno", "buonasera", "buonanotte", "buon pomeriggio", "come stai", "come va", "tutto bene", "ehi"],
        "help": ["aiuto", "aiutami", "ho bisogno di aiuto", "cosa puoi fare", "che cosa puoi fare", "cosa sai fare", "che cosa sai fare", "cosa fai", "come puoi aiutarmi",
                 "in cosa puoi aiutarmi"],
        "filler": ["per favore", "per piacere"],
    },
}
PHRASE = re.compile(r"[a-z0-9]+(?: [a-z0-9]+)*")
_COMPILED = {}

# S41-11: the closed forms of "help in words" that the fixed list of commands answers (the row `help-in-words` of runtime/messaging_turn.py), moved here from `requests.forms.commands` of the language
# tables (runtime/natural_lang_pt_br.py, natural_lang_en.py), which keep the key until the tables' deletion. Each is a whole-line form over normal(): words, groups `( )`, `|` and `?`, nothing open.
HELP_FORMS = (
    r"ajuda", r"(que|quais) (comandos|coisas) (voce|vc) (tem|sabe fazer|faz|entende)", r"o que (voce|vc) (sabe|consegue|pode) fazer", r"como (eu )?(uso|usar)( isso| voce)?",  # validate: allow english-only -- the closed Portuguese forms of help in words, language data
    r"help( me)?", r"what can you do", r"what (commands|can i ask)( do you (have|know))?", r"how (do|can) i use (this|you)",
)
HELP_LINE_WORDS_MAX = 40      # as `natural.LINE_WORDS`: a longer line is a request, not a form
_HELP_COMPILED = []


def normal(line: str) -> str:
    """The line in lower case, accents off ("ss" for the German sharp s), every other character (punctuation, emoji) a space, blanks collapsed."""
    folded = unicodedata.normalize("NFKD", line.lower().replace("\u00df", "ss"))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def check() -> None:
    """ValueError when a phrase is not written as normal() writes a line, or a list is empty."""
    for tag, table in WORDS.items():
        for key in ("greet", "help", "filler"):
            if not table.get(key):
                raise ValueError(f"greeting: {tag} has no {key} list")
            for phrase in table[key]:
                if not PHRASE.fullmatch(phrase):
                    raise ValueError(f"greeting: {tag} {key} holds {phrase!r}, which is not a phrase of a-z and 0-9 separated by one space")


def _unit(phrase: str) -> str:
    stretch = f"{re.escape(phrase[-1])}{{0,{STRETCH_MAX}}}" if phrase in STRETCHED else ""
    return re.escape(phrase) + stretch


def _alternation(phrases_: list) -> str:
    return "|".join(_unit(p) for p in sorted(set(phrases_), key=lambda p: (-len(p), p)))


def _shape(language, helps=True):
    """The compiled shape of a line for a language (every language when None; a tag with no list reads English); without `helps` the help forms are not read."""
    key = language if language in WORDS else ("en" if language else None)
    if (key, helps) not in _COMPILED:
        check()
        tables = [WORDS[key]] if key else list(WORDS.values())
        core = _alternation([p for t in tables for p in t["greet"] + (t["help"] if helps else [])])
        filler = _alternation([p for t in WORDS.values() for p in t["filler"]])
        _COMPILED[(key, helps)] = re.compile(f"(?:(?:{filler}) )*(?:{core})(?: (?:{core}|{filler}))*")
    return _COMPILED[(key, helps)]


def is_greeting(line, language=None, helps=True) -> bool:
    """Whether the WHOLE line is a greeting or, unless `helps` is false, a request for help (see the module's text). A slash line, an empty line and a line of more than LINE_WORDS_MAX words are not."""
    if not isinstance(line, str) or not line.strip() or line.lstrip().startswith("/"):
        return False
    flat = normal(line)
    if not flat or len(flat.split()) > LINE_WORDS_MAX:
        return False
    return _shape(language, helps).fullmatch(flat) is not None


def help_form(line) -> bool:
    """Whether the WHOLE line is one closed form of help in words (`HELP_FORMS`): the typed /help said in words, answered with the fixed list of commands to every listed sender (S41-11: the row
    `help-in-words`; the decision of 2026-10-28 keeps it code). A slash line, a line with an address and an empty line are not."""
    if not isinstance(line, str) or not line.strip() or line.startswith("/") or "@" in line:
        return False
    flat = normal(line)
    if not flat or len(flat.split()) > HELP_LINE_WORDS_MAX:
        return False
    if not _HELP_COMPILED:
        _HELP_COMPILED.extend(re.compile(form) for form in HELP_FORMS)
    return any(form.fullmatch(flat) for form in _HELP_COMPILED)


def as_question(line, language=None) -> bool:
    """Whether the WHOLE line is a greeting (never a help form) written as a question: `is_greeting(line, language, helps=False)` and a question mark anywhere in it ("oi, tudo bem?", "tudo bem?",
    "hi, how are you?"). Such a line asks how the other one is; it is never the answer yes to a question (package L64H)."""
    if not is_greeting(line, language, helps=False):
        return False
    folded = unicodedata.normalize("NFKC", line)
    return any(mark in folded for mark in QUESTION_MARKS)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
