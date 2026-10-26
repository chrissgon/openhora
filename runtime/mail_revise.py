#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The words that change a waiting e-mail card (slice S13): what the model is shown, what code accepts of its answer, and the closed reading of the instruction.

The maintainer's rule (2026-10-22): "Caso eu queira ajustar alguma informacao antes de enviar, deve ser possível". A person who reads the card of an e-mail and wants
a word changed says so in a line ("after Regards, put my name"), and the card is replaced by a new one with the change. This file is the pure part; the operation that
reads the card and opens the new one is runtime/ops_card_revise.py. Nothing here sends, approves, opens or closes a card, logs, prints or stores a word.

  prompt_template(), prompt_sha256()       the fixed prompt (runtime/mail_revise_prompt.txt) and the hash that runtime/interpreter_enable.json pins (`revise_prompt_sha256`)
  shape(doc)                               {"kind": "send" | "draft", "account", "address" (the account's, the From), "to", "subject", "body"} for the effect document of a NEW e-mail from the person's own
                                           account that this path can reproduce exactly, else None. A reply, a card with a Cc or a Bcc or a file, and a card of the outbox are not
                                           revisable: the card was made from a message, a file or a list that the family would have to read again
  has_change_word(line)                    whether the line holds a word that asks for a change (a closed list in six languages; it decides only whether a sentence is said)
  clean(line)                              the instruction as one line (white space collapsed), or None when it is empty or longer than INSTRUCTION_MAX
  literals(line)                           the texts the instruction puts between quotation marks ("..." or the curved pair), in order
  asks_recipients(line)                    whether the instruction, outside its quoted texts, names an address or asks to change who receives the e-mail
  message(language, subject, body, line)   the one user message the model is given: nothing else of the person, of the mailbox or of any third party
  accept(text, to, subject, body, line)    {"subject", "body"} for the model's text, {"same": True} when it is valid and changes nothing, or None. Code decides: `mail_compose.validate` (strict JSON with exactly the two keys, no
                                           header line, no HTML, no code fence, no link, no address other than the recipients of the card and those the card's own text already
                                           holds, nothing the card refuses), a change from the card as it was, and every quoted text of the instruction in the new subject or body
  PARAMS, DEADLINE_MS                      the settings of the one model call, which is the gate's (`turn_gate.call`, runtime/turn_gate.py), on the daily route of the entry that pinned this prompt

What the model sees: the language, the subject, the body of the card and the instruction line. Never the recipients, the sender's address, a message of the mailbox, a file
or any third-party text. The recipients and the account of the new card are the old card's, copied by code: a revision can never change who receives an e-mail.

Privacy (limit L63, D2): the card's text and the instruction go to the model provider under the retention terms the group `interpret` was widened with, exactly as the
interpreter's line and the compose call do. Nothing is logged, printed or written by this file: no instruction, no subject, no body, no exception message.

Standard library only (the other modules are imported when a function needs them). Runs on Python 3.9: python3 runtime/mail_revise.py --help
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "mail_revise_prompt.txt")
PARAMS = {"temperature": 0.2, "max_tokens": 1800, "reasoning": "off"}
DEADLINE_MS = 8000
INSTRUCTION_MAX = 600       # characters of the person's line that are read; a longer text is a new request, not a change
BODY_MAX = 4000             # characters of a card's body that are sent; a longer card is not revised (the validator accepts at most this much back)
WHITE = re.compile(r"\s+")
OBJECT = re.compile(r"(?<![a-z])(?:a\s+mensagem|(?:o|este|esta|esse|essa|the|this|that|el|la|le|der|die|das|il|lo)\s+(?:e-?mail|mensagem|mensaje|message|texto|text|assunto|asunto|subject|sujet|betreff|oggetto|corpo|cuerpo|body|"
                    r"corps|evento|event|evenement|termin|card|cartao|correo|courriel|nachricht|messaggio|testo))(?![a-z])")
QUOTED = re.compile(r"\"([^\"]+)\"|“([^”]+)”")
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# The words of a request to change who receives the e-mail, folded (lower case, no accents), whole words. A closed list that only improves the sentence the person is told:
# the safety does not read it (the recipients are copied from the card and `mail_compose.validate` refuses an address that is not already there).
RECIPIENT_WORDS = frozenset({"destinatario", "destinatarios", "recipient", "recipients", "destinataire", "destinataires", "empfanger", "destinatari", "cc", "cco", "bcc", "cci"})
RECIPIENT_PHRASES = ("mande para", "manda para", "mandar para", "envie para", "envia para", "enviar para", "send it to", "send this to", "send to", "send the e-mail to",
                     "mandalo a", "envialo a", "envoie le a", "schick es an", "invialo a")


# The words that ask for a change, folded, in the six languages of the platform: a closed list that decides only whether a line after a card that cannot be revised, or that the model
# declined, was meant as a change (then one sentence is said) or is something else (then it goes on as it always did). No safety reads it.
ORIGINAL_WORDS = frozenset({"mude", "muda", "mudar", "altere", "altera", "alterar", "troque", "troca", "trocar", "ajuste", "ajusta", "ajustar", "corrija", "corrige", "corrigir", "edite", "edita",
                            "editar", "coloque", "coloca", "colocar", "adicione", "adiciona", "acrescente", "acrescenta", "remova", "remove", "tire", "tira", "substitua", "substitui", "inclua",
                            "inclui", "renomeie", "renomeia", "change", "edit", "adjust", "fix", "replace", "add", "remove", "put", "insert", "update", "rename", "cambia", "cambie", "modifica",
                            "modifique", "anade", "anada", "quita", "quite", "reemplaza", "modifie", "modifiez", "corrigez", "ajoute", "ajoutez", "remplace", "remplacez", "andere", "korrigiere",
                            "fuge", "ersetze", "aggiungi", "correggi", "sostituisci", "rimuovi"})
# S13b: the verbs that write, end or sign a text ("Escreva ao final do email: ..."). They are also the verbs of ordinary requests ("escreva para a Ana", "termina a tarefa 3", "deixa pra la",      # validate: allow english-only -- Portuguese examples of the ordinary requests
# "sign me up"), so they open the gate only beside a locator ("ao final") or an object of the card ("o email") in the same line. "pôr" is not here: folded it is "por".
WIDE_VERBS = frozenset({"escreva", "escreve", "escrever", "reescreva", "reescreve", "reescrever", "ponha", "poe", "deixe", "deixa", "deixar", "termine", "termina", "terminar", "finalize",
                        "finaliza", "finalizar", "encerre", "encerra", "encerrar", "assine", "assina", "assinar", "acrescentar", "incluir", "retire", "retira", "retirar",
                        "write", "rewrite", "sign", "end", "finish", "append", "escribe", "escriba", "pon", "ponga", "firma", "firme", "ecris", "ecrivez", "mets", "mettez", "signe", "signez",
                        "schreibe", "schreib", "setze", "beende", "unterschreibe", "scrivi", "metti"})
CHANGE_WORDS = ORIGINAL_WORDS | WIDE_VERBS
# Where in the e-mail a text is asked for, folded: the end and the start. A closed list in the six languages.
END_LOCATORS = ("ao final", "no fim", "no final", "na assinatura", "at the end", "al final", "a la fin", "am ende", "alla fine", "ao fim", "no fim do")
START_LOCATORS = ("no comeco", "no inicio", "ao comeco", "ao inicio", "at the start", "at the beginning", "al principio", "al inicio", "au debut", "am anfang", "all inizio", "all'inizio")


def prompt_template() -> str:
    with open(PROMPT_FILE, encoding="utf-8") as handle:
        return handle.read()


def prompt_sha256() -> str:
    """The sha256 of the revise prompt's bytes: the version that interpreter_enable.json pins."""
    with open(PROMPT_FILE, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


# --- the card ------------------------------------------------------------------------------------------------------------------------------------


def _addresses(found) -> bool:
    return isinstance(found, list) and all(isinstance(a, str) and a for a in found)


def shape(doc):
    """The revisable shape of an effect document (see the module's text), or None."""
    if not isinstance(doc, dict):
        return None
    if doc.get("effect") == "send":
        kind, mail, address = "send", doc, doc.get("from")
        clean_reply = doc.get("in_reply_to") is None and doc.get("reply") is None and doc.get("thread_id") is None and not doc.get("references") and not doc.get("attachments")
    elif doc.get("effect") == "mailbox" and doc.get("action") == "draft" and isinstance(doc.get("draft"), dict):
        kind, mail, address = "draft", doc["draft"], doc.get("address")
        clean_reply = mail.get("reply") is None
    else:
        return None
    account = doc.get("account")
    if account not in ("google", "microsoft") or not clean_reply or not isinstance(address, str) or not address:
        return None
    if not _addresses(mail.get("to")) or not mail["to"] or mail.get("cc") or mail.get("bcc"):
        return None
    subject, body = mail.get("subject"), mail.get("body")
    if not isinstance(subject, str) or not isinstance(body, str) or not subject.strip() or not body.strip() or len(body) > BODY_MAX:
        return None
    return {"kind": kind, "account": account, "address": address, "to": list(mail["to"]), "subject": subject, "body": body}


# --- the instruction -----------------------------------------------------------------------------------------------------------------------------


def clean(line):
    """The instruction as one line, or None (see the module's text)."""
    one = WHITE.sub(" ", line).strip() if isinstance(line, str) else ""
    return one if one and len(one) <= INSTRUCTION_MAX else None


BLOCK = re.compile(r"^(.*?):[ \t]*\n\s*(\S.*)$", re.S)      # "...:" at the end of a line, and a text after it (a colon with the text on the same line is no block)


def instruction(text):
    """The instruction as the person wrote it, line breaks kept (a line's trailing white space and runs of blank lines cut), or None when it is empty or longer than INSTRUCTION_MAX. The
    model is shown this form, and `literals` reads its text block."""
    if not isinstance(text, str):
        return None
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n")]
    one = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return one if one and len(one) <= INSTRUCTION_MAX else None


def _words_of(line: str) -> set:
    return set(re.findall(r"[a-z]+", _fold(line or "")))


def _has_phrase(line: str, phrases) -> bool:
    folded = _fold(line or "")
    return any(re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", folded) for p in phrases)


def has_locator(line: str) -> bool:
    """Whether the line says WHERE in the e-mail ("ao final", "no fim", "at the end", "no comeco"...: END_LOCATORS and START_LOCATORS)."""
    return _has_phrase(line, END_LOCATORS + START_LOCATORS)


def has_change_word(line: str) -> bool:
    """Whether the line holds a word that has always asked for a change (ORIGINAL_WORDS: "muda", "troca", "ajusta", "corrige"...)."""
    return bool(_words_of(line) & ORIGINAL_WORDS)


def asks_change(line: str) -> bool:
    """Whether the line asks for a change of the e-mail: a word of ORIGINAL_WORDS, or a verb that writes, ends or signs a text (WIDE_VERBS) together with a locator or an object of the
    card in the same line ("escreva ao final", "assine o email"). "escreva para a Ana", "termina a tarefa 3" and "sign me up" ask nothing of the card."""
    words = _words_of(line)
    return bool(words & ORIGINAL_WORDS) or bool(words & WIDE_VERBS and (has_locator(line) or names_object(line)))


def split_block(text: str) -> tuple:
    """(the instruction before its text block, the block or ""): the block is what follows the first line that ends with a colon, with its line breaks (see `literals`)."""
    found = BLOCK.match(text or "")
    return (found.group(1) + ":", found.group(2).strip()) if found else (text or "", "")


def _block_asked(before: str) -> bool:
    """Whether the line before a colon asks for the block as text of the e-mail: a verb that changes or writes (any of the two lists) and, in the same line, a locator or an object of the
    card. "Pensando aqui:", "Lista de compras:" and "Me ajuda com isso:" ask for nothing."""      # validate: allow english-only -- Portuguese examples
    return bool(_words_of(before) & CHANGE_WORDS) and (has_locator(before) or names_object(before))


def literal_items(text: str) -> list:
    """[(text, is_block)]: the texts between quotation marks, as written, in the order they come, and the block after a colon and a line break when the line before it asks for it
    (`_block_asked`); each with the white space around it cut. With no such block a text between quotation marks counts wherever it stands. Read the instruction with its line breaks
    (`instruction`): once it is one line there is no block."""
    before, block = split_block(text)
    if block and _block_asked(before):
        return [((a or b).strip(), False) for a, b in QUOTED.findall(before) if (a or b).strip()] + [(block, True)]
    return [((a or b).strip(), False) for a, b in QUOTED.findall(text or "") if (a or b).strip()]


def literals(text: str) -> list:
    """The texts the instruction asks for as they are written (see `literal_items`)."""
    return [t for t, _ in literal_items(text)]


def names_object(line: str) -> bool:
    """Whether the line names the card's object with a definite article ("o email", "a mensagem", "the subject", "el asunto"...), in the singular: a line about THE card, whatever its verb.
    "os emails" (a list), "um email" (a new one) and "emails" are not. A closed list in the six languages; it only decides whether a sentence is said."""
    return bool(OBJECT.search(_fold(line or "")))


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _outside(line: str) -> str:
    """The instruction without its quoted texts and without its text block (what the person asks for is not what the person says about the card)."""
    return QUOTED.sub(" ", split_block(line)[0])


def has_address(line: str) -> bool:
    """Whether the instruction holds an e-mail address outside its quoted texts."""
    return bool(ADDRESS.search(unicodedata.normalize("NFKC", _outside(line))))


def recipient_words(line: str) -> bool:
    """Whether the instruction, outside its quoted texts, asks in words to change who receives the e-mail (a word or a phrase of the closed lists)."""
    folded = _fold(_outside(line))
    return bool(set(re.findall(r"[a-z]+", folded)) & RECIPIENT_WORDS) or any(re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", folded) for p in RECIPIENT_PHRASES)


def asks_recipients(line: str) -> bool:
    """Whether the instruction, outside its quoted texts, holds an address or asks to change who receives the e-mail (see the module's text)."""
    return has_address(line) or recipient_words(line)


def message(language: str, subject: str, body: str, line: str) -> str:
    """The one user message of the model call: four parts and nothing else (see the module's text). The instruction keeps its line breaks, so that a text block can be told."""
    return f"language: {language}\nsubject: {subject}\ninstruction: {line}\nbody:\n{body}"


# --- the answer ----------------------------------------------------------------------------------------------------------------------------------


def _own_addresses(*texts) -> list:
    """The addresses the card's own text already holds (an address the person wrote in it stays; a new one is never allowed)."""
    found = []
    for text in texts:
        for match in ADDRESS.findall(unicodedata.normalize("NFKC", text)):
            if match not in found:
                found.append(match)
    return found


def _flat(text: str) -> str:
    """The text with every run of white space one space and the accents composed: how a text asked for is looked for in the card (a line break more or less is no difference)."""
    return WHITE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def _model_field(text, name: str):
    """A text field the model's answer holds, or None (the answer is parsed again here only to compare its subject and its body with the card's)."""
    compose = importlib.import_module("mail_compose")
    body = text.strip()
    found = compose.FENCE.fullmatch(body)
    try:
        obj = json.loads(found.group(1) if found else body)
    except (ValueError, RecursionError):
        return None
    return obj.get(name) if isinstance(obj, dict) and isinstance(obj.get(name), str) else None


def _kept_close(got_body: str, text, old: str) -> str:
    """The validator drops a closing formula that ends a body with nothing after it (S12). A card whose own text ended with such a closing (a text sent as written) keeps it when the model
    kept it too and the line did not ask for more: the body the model wrote, if the part the validator dropped is the very one the card ended with; else the validated body."""
    compose = importlib.import_module("mail_compose")
    raw = (_model_field(text, "body") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    core = compose.without_dangling_close(old)
    tail = old[len(core):] if old.startswith(core) else ""
    return raw if tail.strip() and raw == got_body + tail and raw.endswith(tail) else got_body


def accept(text, to, subject: str, body: str, line: str):
    """{"subject", "body"} for the model's text, or None (see the module's text)."""
    compose = importlib.import_module("mail_compose")
    allowed = list(to) + [a for a in _own_addresses(subject, body) if a not in to]
    got = compose.validate(text, allowed)
    if got is None:      # a card whose own subject the validator would not accept as a model-written one (it starts like a reply, say) may keep it unchanged
        shown = _model_field(text, "subject") if isinstance(text, str) else None
        got = compose.validate(text, allowed, subject) if shown is not None and shown.strip() == subject else None
    if got is None:
        return None
    old = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    got = dict(got, body=_kept_close(got["body"], text, old))
    items = literal_items(line)
    seen = lambda fixed, new_text, new_subject: all((_flat(t) in _flat(new_subject + "\n" + new_text)) if block else (unicodedata.normalize("NFC", t) in unicodedata.normalize("NFC", new_subject + "\n" + new_text))
                                                    for t, block in items)
    old_flat = _flat(old)
    # a model that writes again, at the end, the very text the card already ends with, has changed nothing the person asked for
    for t, _ in items:
        flat = _flat(t)
        if old_flat.endswith(flat) and _flat(got["body"]) == old_flat + " " + flat:
            got = {"subject": subject, "body": old}
            break
    new_body = unicodedata.normalize("NFC", got["body"])
    new_subject = unicodedata.normalize("NFC", got["subject"])
    if new_subject == unicodedata.normalize("NFC", subject) and new_body == unicodedata.normalize("NFC", old):
        # nothing changed: the instruction was not applied; `holds` says the card already holds every text the line asks for AT THE PLACE asked (then the card is already as asked)
        return {"same": True, "holds": bool(items) and _holds(items, line, subject, old)}
    if not seen(None, new_body, new_subject):
        return None
    return {"subject": got["subject"], "body": got["body"]}


def _holds(items: list, line: str, subject: str, old: str) -> bool:
    """Whether the card already holds every text of `items` where the line asks for it: at the end of the body for "ao final", at the start for "no inicio", anywhere when the line says
    no place. A quoted text is looked for as written, a block with its white space as one space."""
    old_flat, whole = _flat(old), unicodedata.normalize("NFC", subject + "\n" + old)
    at_start, at_end = _has_phrase(line, START_LOCATORS), _has_phrase(line, END_LOCATORS)
    for t, block in items:
        flat = _flat(t)
        if at_start and not at_end:
            ok = old_flat.startswith(flat)
        elif at_end and not at_start:
            ok = old_flat.endswith(flat)
        else:
            ok = (flat in old_flat) if block else (unicodedata.normalize("NFC", t) in whole)
        if not ok:
            return False
    return True


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
