#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A line that asks to delete a file (slice S14, limit L62): code knows it, and the platform cannot do it from a message yet.

Deleting or trashing a file is not an action of the platform. A line such as "remova o arquivo logo do drive" went to the interpreter or to the planning agent, which answered a generic
"I could not build the card" or a state digest. `asks(text)` is true for such a line, so that the conversation answers it at once with one plain sentence (PHONE_NO_FILE_DELETE) and
nothing else: no model, no card, no request.

The line is a request to delete a file when, after the polite words that may start it, it begins with a verb of deleting or of throwing away (closed lists in Portuguese, English,
Spanish, French, German and Italian; a verb of moving counts with a word of the trash) and the first thing it names within the next four words is a file (a file, a photo, an image, a
document), or it names a file by its extension ("logo.png") in a place that holds files (a drive, a folder), and it holds no word of negation. A question about what deleting does, a
line that starts with another verb, and a line that removes an event, a reminder or a message are not.

Standard library only. Runs on Python 3.9: python3 runtime/phone_delete.py --help
"""
from __future__ import annotations

import re
import sys
import unicodedata

# "descarta" and "discard" are not here: with a file held for the person they are the words of a card (messaging_attach.line), and without one they are an ordinary line.
VERBS = frozenset("""apaga apague apagar apaguem remove remova remover removam exclui exclua excluir deleta delete deletar deletem elimina elimine eliminar
jogue joga jogar tire tira tirar erase trash toss borra borre borrar quita quite quitar supprime supprimer supprimez efface effacer effacez retire retirer jette jeter
loesche loeschen losche loschen entferne entfernen wirf werfe cancella cancellare rimuovi rimuovere butta buttare eliminare""".split())
MOVERS = frozenset("mova mover move mueve mueva mets mettre verschiebe verschieben sposta spostare put send".split())      # "move the file to the trash": a verb of moving counts only with a word of the trash
TRASH = frozenset("lixeira lixo trash recycle bin papelera basura corbeille poubelle papierkorb muell cestino spazzatura".split())
FILES = frozenset("""arquivo arquivos file files foto fotos imagem imagens documento documentos photo photos image images picture pictures archivo archivos imagen imagenes
fichier fichiers document documents datei dateien bild bilder dokument dokumente immagine immagini""".split())
EXTENSIONS = frozenset("png jpg jpeg gif svg webp heic pdf doc docx xls xlsx csv txt md ppt pptx zip mp3 mp4 mov json".split())      # a name that ends so is a file whether or not the line says "file"
OTHER = frozenset("""evento eventos event events compromisso compromissos reuniao reunioes meeting agenda calendario calendar lembrete lembretes reminder email emails mail mails mensagem
mensagens message messages correo correos courriel rascunho rascunhos draft drafts thread conversa termin ereignis evento riunione promemoria posta""".split())      # what a request to remove is about when it is not a file
POLITE = frozenset("""por favor pode poderia voce please can could you would kindly puedes podrias favor peux pourrais tu pouvez vous s il plait kannst konntest du bitte
koennen sie puoi potresti per favore ti ok entao agora oi ola""".split())
NEGATION = frozenset("nao no not dont don never nunca ne pas nicht kein keine non mai nada".split())
ARTICLES = frozenset("""o a os as um uma uns umas esse essa esses essas este esta the this that these those my meu minha el la los las le les un une der die das dem den ein eine
il lo gli i il""".split())      # what may stand between the word for a file and its name ("o arquivo esse aqui" is not read: only these words are skipped)
NAME_STOPS = frozenset("""do da dos das de no na nos nas em dentro pelo pela para por from in on of at to into inside within del en desde du des dans sur von aus im dal dalla dallo di nel nella
nello drive onedrive google microsoft nuvem cloud pasta folder diretorio directory carpeta dossier ordner cartella""".split())      # the name of a file read by code ends at one of these
NEAR = 4      # the thing is named within this many words after the verb ("o arquivo", "esse arquivo aqui", "o arquivo logo.png")
WORDS = 20    # a longer line is not a plain request to delete a file


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
    if start >= len(words):
        return False
    verb = words[start]
    if verb not in VERBS and not (verb in MOVERS and TRASH & set(words)):
        return False
    near = words[start + 1:start + 1 + NEAR]
    for word in near:      # the first thing named decides: a file, or an event or a message (never a file)
        if word in OTHER:
            return False
        if word in FILES:
            return True
    return bool(EXTENSIONS & set(words[start + 1:]))      # no thing named in the first words, but a name that ends as a file does: "remova logo.png do drive"


def _edge(token: str) -> str:
    return token.strip(".,;:!?()[]")


def name(text):
    """The name of the file a line that asks to delete one names, read by code alone, or None (a line whose name is not plainly after the word for a file, or after the verb when it ends as a file
    does). Slice R2-A: a sender who may move a file to the trash is answered by the operation `file-trash`, and the name is the span of the line it searches for. The name is the one word after
    the word for a file and its articles ("o arquivo openhora-mark.png"), or the words in quotes ("o arquivo \"contrato de locacao\""); with no word for a file, the first word that ends as a
    file does. It stops at a word that starts the place ("do drive", "em /openhora", "from my drive"). Case, accents and the dots of the name are kept."""
    if not asks(text):
        return None
    tokens = text.split()
    folded = [" ".join(_words(_edge(t))) for t in tokens]
    start = 0
    while start < len(tokens) and folded[start] in POLITE:
        start += 1
    if start >= len(tokens):
        return None
    begin = None
    for at in range(start + 1, min(len(tokens), start + 1 + NEAR)):
        if folded[at] in OTHER:
            return None
        if folded[at] in FILES:
            begin = at + 1
            break
    if begin is None:      # no word for a file: the first word that ends as a file does
        begin = next((at for at in range(start + 1, len(tokens)) if _edge(tokens[at]).rpartition(".")[2].lower() in EXTENSIONS and "." in _edge(tokens[at])), None)
    if begin is None:
        return None
    while begin < len(tokens) and folded[begin] in ARTICLES:
        begin += 1
    if begin >= len(tokens):
        return None
    first = tokens[begin]
    quote = first[:1] if first[:1] in "\"'\u201c\u2018" else ""
    if quote:
        closing = {"\"": "\"", "'": "'", "\u201c": "\u201d", "\u2018": "\u2019"}[quote]
        found = []
        for token in tokens[begin:]:
            found.append(token)
            if len(found) > 1 or len(token) > 1:
                if token.rstrip(".,;:!?)").endswith(closing):
                    break
        else:
            return None
        said = " ".join(found).strip()
        said = said[1:].rstrip(".,;:!?)")
        said = said[:-1] if said.endswith(closing) else said
        picked = said.strip()
    else:
        if folded[begin] in NAME_STOPS or not _edge(first):
            return None
        picked = _edge(first)
    return picked if 1 <= len(picked) <= 300 else None


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
