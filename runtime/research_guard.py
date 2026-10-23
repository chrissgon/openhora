#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A question about the person's own data is not a web search (slice R2-F1): a closed check of code, over a question and the line it came from.

The interpreter picks `research` for a question of general information, and a model can be wrong. A question that holds a possessive form of one of the project's sources ("minha
agenda", "meus e-mails", "my calendar", "mon dossier", "mein Kalender", "la mia cartella"...) is about the person's own calendar, mail, files or folders, and would send those words to
a web search service and a model that have nothing to do with them. `personal(text)` is True for such a text; the caller does not run the research and asks the person to say the line
again. The bare noun is NOT a possessive form ("agenda cultural", "pasta de dente", "the calendar of holidays" stay allowed): this is a check of the closed forms below, in the six
languages the interpreter reads (pt-BR, en, es, fr, de, it), not a reading of meaning. A possessive and a noun are at most two words apart ("meus ultimos emails", "my latest e-mails");
the Spanish and Italian "mi" is also a clitic pronoun, so it counts only next to the noun or one word before it. Accents, case and punctuation do not matter.

Pure. Standard library only. Runs on Python 3.9: python3 runtime/research_guard.py --help
"""
from __future__ import annotations

import re
import sys
import unicodedata

# The possessives (a word that can only possess) and the nouns of the project's sources, folded: lower case, no accent, every other character a space.
POSSESSIVES = ["my", "meu", "meus", "minha", "minhas", "mis", "mon", "ma", "mes", "mein", "meine", "meinen", "meinem", "meiner", "meines", "mio", "mia", "miei", "mie"]
CLITIC_POSSESSIVES = ["mi"]      # a possessive in Spanish and a pronoun in Italian: only next to the noun or one word before it
NOUNS = [
    # calendar
    "calendar", "calendars", "agenda", "agendas", "schedule", "calendario", "calendarios", "calendrier", "calendriers", "kalender", "terminkalender",
    # mail
    "email", "emails", "e mail", "e mails", "mail", "mails", "inbox", "mailbox", "caixa de entrada", "caixa de e mail", "correo", "correos", "courrier", "courriers", "posteingang",
    "posta", "casella di posta",
    # files, documents, folders, drive
    "file", "files", "arquivo", "arquivos", "archivo", "archivos", "fichier", "fichiers", "datei", "dateien", "documento", "documentos", "documento", "document", "documents",
    "dokument", "dokumente", "documenti", "folder", "folders", "pasta", "pastas", "carpeta", "carpetas", "dossier", "dossiers", "ordner", "cartella", "cartelle", "drive", "onedrive",
    "google drive",
]


def fold(text) -> str:
    """The text folded for the check: lower case, accents removed, every run of other characters a single space."""
    if not isinstance(text, str):
        return ""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return " " + re.sub(r"[^a-z0-9]+", " ", plain).strip() + " "


def _words(items) -> str:
    return "|".join(re.escape(item).replace(r"\ ", " ") for item in sorted(set(items), key=len, reverse=True))


_NOUN = _words(NOUNS)
FORMS = (
    re.compile(r" (?:" + _words(POSSESSIVES) + r")(?: [a-z0-9]+){0,2} (?:" + _NOUN + r") "),
    re.compile(r" (?:" + _words(CLITIC_POSSESSIVES) + r")(?: [a-z0-9]+){0,1} (?:" + _NOUN + r") "),
)


def personal(*texts) -> bool:
    """Whether any of the texts holds a possessive form of a source of the project (see the module's text)."""
    for text in texts:
        folded = fold(text)
        if folded.strip() and any(form.search(folded) for form in FORMS):
            return True
    return False


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
