#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A line that asks to delete a file (slice S14, limit L62): code knows it, and the platform cannot do it from a message yet.

Deleting or trashing a file is not an action of the platform. A line such as "remova o arquivo logo do drive" went to the interpreter or to the planning agent, which answered a generic
"I could not build the card" or a state digest. `asks(text)` is true for such a line, so that the conversation answers it at once with one plain sentence (PHONE_NO_FILE_DELETE) and
nothing else: no model, no card, no request.

The line is a request to delete a file when, after the polite words that may start it, it begins with a verb of deleting (closed lists in Portuguese, English, Spanish, French, German and
Italian) and names a file within the next three words (a file, a photo, an image, a document), and holds no word of negation. A question about what deleting does, a line that starts
with another verb, and a line that deletes something that is not a file (an event, a reminder) are not.

Standard library only. Runs on Python 3.9: python3 runtime/phone_delete.py --help
"""
from __future__ import annotations

import re
import sys
import unicodedata

VERBS = frozenset("""apaga apague apagar apaguem remove remova remover removam exclui exclua excluir deleta delete deletar deletem elimina elimine eliminar
erase trash borra borre borrar quita quite quitar supprime supprimer efface effacer retire retirer supprimez effacez loesche loeschen entferne entfernen
losche loschen cancella cancellare rimuovi rimuovere elimina eliminare""".split())
NOUNS = frozenset("""arquivo arquivos file files foto fotos imagem imagens documento documentos photo photos image images picture pictures archivo archivos imagen imagenes
fichier fichiers document documents datei dateien bild bilder dokument dokumente immagine immagini""".split())
POLITE = frozenset("""por favor pode poderia voce please can could you would kindly puedes podrias favor peux pourrais tu pouvez vous s il plait kannst konntest du bitte
koennen sie puoi potresti per favore ti ok entao agora""".split())
NEGATION = frozenset("nao no not dont don never nunca ne pas nicht kein keine non mai nada".split())
NEAR = 4      # the file is named within this many words after the verb ("o arquivo", "esse arquivo aqui", "the file called")
WORDS = 14    # a longer line is not a plain request to delete a file


def _words(text: str) -> list:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain).split()


def asks(text) -> bool:
    """Whether the line is a request to delete a file (see the module's text)."""
    if not isinstance(text, str) or text.lstrip().startswith("/"):
        return False
    words = _words(text)
    if not words or len(words) > WORDS or NEGATION & set(words):
        return False
    start = 0
    while start < len(words) and words[start] in POLITE:
        start += 1
    return start < len(words) and words[start] in VERBS and bool(NOUNS & set(words[start + 1:start + 1 + NEAR]))


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
