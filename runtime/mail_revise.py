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
  call(entry, system, user)                the one model call, on the daily route of the entry that pinned this prompt

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
QUOTED = re.compile(r"\"([^\"]+)\"|“([^”]+)”")
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# The words of a request to change who receives the e-mail, folded (lower case, no accents), whole words. A closed list that only improves the sentence the person is told:
# the safety does not read it (the recipients are copied from the card and `mail_compose.validate` refuses an address that is not already there).
RECIPIENT_WORDS = frozenset({"destinatario", "destinatarios", "recipient", "recipients", "destinataire", "destinataires", "empfanger", "destinatari", "cc", "cco", "bcc", "cci"})
RECIPIENT_PHRASES = ("mande para", "manda para", "mandar para", "envie para", "envia para", "enviar para", "send it to", "send this to", "send to", "send the e-mail to",
                     "mandalo a", "envialo a", "envoie le a", "schick es an", "invialo a")


# The words that ask for a change, folded, in the six languages of the platform: a closed list that decides only whether a line after a card that cannot be revised, or that the model
# declined, was meant as a change (then one sentence is said) or is something else (then it goes on as it always did). No safety reads it.
CHANGE_WORDS = frozenset({"mude", "muda", "mudar", "altere", "altera", "alterar", "troque", "troca", "trocar", "ajuste", "ajusta", "ajustar", "corrija", "corrige", "corrigir", "edite", "edita",
                          "editar", "coloque", "coloca", "colocar", "adicione", "adiciona", "acrescente", "acrescenta", "remova", "remove", "tire", "tira", "substitua", "substitui", "inclua",
                          "inclui", "renomeie", "renomeia", "change", "edit", "adjust", "fix", "replace", "add", "remove", "put", "insert", "update", "rename", "cambia", "cambie", "modifica",
                          "modifique", "anade", "anada", "quita", "quite", "reemplaza", "modifie", "modifiez", "corrigez", "ajoute", "ajoutez", "remplace", "remplacez", "andere", "korrigiere",
                          "fuge", "ersetze", "aggiungi", "correggi", "sostituisci", "rimuovi"})


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


def literals(line: str) -> list:
    """The texts between quotation marks, in the order they come, each as written (surrounding white space removed)."""
    return [(a or b).strip() for a, b in QUOTED.findall(line or "") if (a or b).strip()]


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _outside(line: str) -> str:
    return QUOTED.sub(" ", line or "")


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


def has_change_word(line: str) -> bool:
    """Whether the line holds a word that asks for a change (see CHANGE_WORDS)."""
    return bool(set(re.findall(r"[a-z]+", _fold(line or ""))) & CHANGE_WORDS)


def message(language: str, subject: str, body: str, line: str) -> str:
    """The one user message of the model call: four parts and nothing else (see the module's text)."""
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
    new_body = unicodedata.normalize("NFC", got["body"])
    new_subject = unicodedata.normalize("NFC", got["subject"])
    if new_subject == unicodedata.normalize("NFC", subject) and new_body == unicodedata.normalize("NFC", old):
        return {"same": True}      # nothing changed: the instruction was not applied
    for wanted in literals(line):
        wanted = unicodedata.normalize("NFC", wanted)
        if wanted not in new_subject and wanted not in new_body:
            return None
    return {"subject": got["subject"], "body": got["body"]}


def call(entry: dict, system: str, user: str) -> dict:
    """The one model call: the entry's daily route (kind http, the hash the entry was decided on), as mail_compose does it, with this file's settings."""
    route = importlib.import_module("interpreter_route")
    rows = [r for r in route.daily_routes() if r["id"] == entry["route"]]
    if len(rows) != 1 or rows[0].get("kind") != "http" or route.route_sha256(rows[0]) != entry["route_sha256"]:
        return {"ok": False, "code": "E_ROUTE"}
    return route.complete(rows[0]["id"], system, user, accepted=[entry["route_sha256"]], deadline_ms=DEADLINE_MS, **PARAMS)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
