#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of an e-mail to send, and nothing that sends (package EMAIL-SEND): what the step kind `send-email` builds and the effect
kind `send` approves. The effect document (its keys, its checks, the credential scan of the subject and the body), the title and the
preview the person reads, the one line that says what is approved, the closed facts a decision's payload records, and the arguments of the
provider's verb. It holds no function that calls a provider or executes an effect: that is runtime/effect_send.py, reached from the
operation `approve` only. The step kind imports this module and not that one, so a step kind has no function in reach that could send
(limit L30; docs/architecture/platform/outputs.md).

The document. `effect` ("send"), `task` (the step task that prepared it), `provider` (the implementation of the class sender:email the
project resolved to: the send is refused if it resolves to another now), `from` (the address of the project's outbox), `to`, `cc`, `bcc`
(lists of normalised addresses; the Bcc is in the document, in the hash and on the card), `subject`, `body`, `body_sha256`, `in_reply_to`
(a Message-ID or null), `attachments` ([{path (a file of the project's docs/), name (what the recipient sees), media_type, bytes, sha256}]),
`message_id`, `idempotency_key` and `dry_run_sha256` (the hash of what the provider's dry run printed: its headers, its envelope, its
body and each attachment's name, size and hash).

The key is the document's own: `send-` and the first 32 hex digits of the sha256 of the task, the sender, the recipients, the subject,
the body, the reply and the attachments (name and hash), so one e-mail is sent once however many decisions reach it; the Message-ID
derives from it. The recipients are inside the hash the person approves, so an approval of an e-mail covers no other recipient. The date
and the MIME boundaries are not content: the provider makes them.

An e-mail from the person's own account (package W2, SPEC-SECRETARY-WRITES 3.2) is the same document with four keys more: `account` (`google` or `microsoft`),
`thread_id` (Gmail's conversation of the message answered, else null), `references` (the Message-ID chain a reply names) and `reply` (null, or what the snapshot
index recorded of the message answered: `ref`, `address` (its sender, the one recipient of the reply), `reply_to` (another address it asked replies to go to, shown
and never used), `subject` (as the index cleaned it), `read_at`, `provider_id` and `message_id`, and `received` (the moment the message came, UTC, as the index recorded it)
only when the index had it: S16C-REPLY-DATE, an optional key inside the hash, so a document made without it keeps its keys and its hash; the card shows it, nothing uses it). Its `from` is the account's address (`accounts.<account>.address`)
and its `provider` is the mailer of the account (`gmail`, `outlook`). A document without `account` is the outbox's, with the keys and the hash it always had. The
card of an own-account e-mail is said line by line (`card_lines`, the family CARD_MAIL_ of runtime/phrases.py): the person's text sits behind a gutter mark on every
line, a line of it that could pass for the frame of the card is refused, and so is a hidden character. Recipients come only from the approved document: the
arguments the person gave or, for a reply, the sender of the message answered as the index recorded it (limit L60).

Standard library only, plus the credential scan of runtime/workcopy.py and the error class of runtime/effects.py. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import mail_address  # noqa: E402
import operations  # noqa: E402  (the command line the preview shows)
import phrases  # noqa: E402  (the lines of the card of an e-mail from the person's own account)
import snapshot_text  # noqa: E402  (the moment of a message, in the machine's zone, for the card)
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "send"
KEYS = ("effect", "task", "provider", "from", "to", "cc", "bcc", "subject", "body", "body_sha256", "in_reply_to", "attachments",
        "message_id", "idempotency_key", "dry_run_sha256")
ATTACHMENT_KEYS = ("path", "name", "media_type", "bytes", "sha256")
RECIPIENTS_MAX = 20            # in all, To + Cc + Bcc: a hard cap in code (the provider holds the same)
SUBJECT_MAX = 200              # characters
BODY_MAX = 100 * 1024          # bytes of UTF-8
ATTACH_MAX = 10                # files
ATTACH_TOTAL_MAX = 18 * 1024 * 1024     # bytes together: a message over about 25 MB is refused by most servers, and base64 adds a third
# The extensions an attachment may have, and the type each is sent as (providers/_email.py MEDIA_TYPES: a test holds them equal).
MEDIA_TYPES = {"pdf": "application/pdf", "txt": "text/plain", "csv": "text/csv", "md": "text/markdown", "png": "image/png",
               "jpg": "image/jpeg",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "odt": "application/vnd.oasis.opendocument.text"}
SHA256 = re.compile(r"[0-9a-f]{64}")
PROVIDER = re.compile(r"[a-z][a-z0-9-]{0,39}")
DOCS_PATH = re.compile(r"docs/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
ATTACHMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,99}")
REFERENCE = re.compile(r"<[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]{1,200}@[A-Za-z0-9.-]{1,200}>")
MESSAGE_ID = re.compile(r"<oh\.[0-9a-f]{32}@[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?>")
CONTROL = re.compile(r"[\x00-\x1f\x7f\x85  ]")
CONTROL_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")       # a body may have newlines (\n, \r) and tabs, no other control character
ACCOUNTS = {"google": "gmail", "microsoft": "outlook"}      # the account of the person's own -> the mailer (an implementation of the class sender:email) that sends from it
ACCOUNT_KEYS = ("account", "thread_id", "references", "reply")      # the keys an own-account document has beside KEYS
REPLY_KEYS = ("ref", "address", "reply_to", "subject", "read_at", "provider_id", "message_id")
REPLY_OPTIONAL = ("received",)      # S16C-REPLY-DATE: a key a reply document has only when the index recorded the time the message came; a document without it keeps its keys and its hash
RECEIVED = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")      # as runtime/item_refs.py reads it back (this module imports no item_refs)
ENGLISH_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")      # the shape phrases.localize_dates turns into the language's word on a phone
THREAD_ID = re.compile(r"[A-Za-z0-9_=-]{1,200}")
PROVIDER_ID = re.compile(r"[A-Za-z0-9=_+-]{1,700}")
SNAPSHOT_REF = re.compile(r"[a-z0-9][a-z0-9-]{0,39}#[1-9][0-9]{0,3}")
REPLY_SUBJECT_MAX = 120      # characters: what the index keeps of a subject
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")
INVISIBLE = "\u3164\u115f\u1160\uffa0\u2800\u034f\ufe0f\u180b\u180c\u180d\u17b4\u17b5"      # letters and marks that draw nothing (Hangul fillers, the blank braille pattern, variation selectors...)      # control (but the line end and the tab of a text), format, separators, surrogate, private use


def sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _usage(reason: str):
    return effects.EffectError("usage", reason)


def addresses(text, what: str) -> list:
    """The addresses of a comma-separated list, normalised (EffectError usage naming `what` when one is not an address)."""
    try:
        return mail_address.split_list(text)
    except mail_address.AddressError as e:
        raise _usage(f"{what}: {e.reason}") from None


def sender(text) -> str:
    try:
        return mail_address.normalize_address(text)
    except mail_address.AddressError as e:
        raise _usage(f"the sender: {e.reason}") from None


def attachment_name(name) -> str:
    """What the recipient sees as the file's name; EffectError usage when it is not plain or its extension is not one of MEDIA_TYPES."""
    if not isinstance(name, str) or not ATTACHMENT_NAME.fullmatch(name) or ".." in name or name != name.strip() or name.endswith(".") \
            or "." not in name or name.rsplit(".", 1)[-1].lower() not in MEDIA_TYPES:
        raise _usage("an attachment name is plain letters, digits, dots, spaces, hyphens and underscores, at most 100 characters, and ends in "
                     "one of: " + ", ".join(sorted(MEDIA_TYPES)))
    return name


def media_type(name: str) -> str:
    return MEDIA_TYPES[name.rsplit(".", 1)[-1].lower()]


def _media_or_blank(name) -> str:
    """The media type of an attachment name, or "" when it has none (check() then refuses the document, naming the rule)."""
    ok = isinstance(name, str) and "." in name and name.rsplit(".", 1)[-1].lower() in MEDIA_TYPES
    return media_type(name) if ok else ""


def check_recipients(sender_address: str, to: list, cc: list, bcc: list) -> None:
    """At least one To, at most RECIPIENTS_MAX in all, and no address twice (compared lower-cased)."""
    everyone = list(to) + list(cc) + list(bcc)
    if not to:
        raise _usage("an e-mail has at least one To recipient")
    if len(everyone) > RECIPIENTS_MAX:
        raise _usage(f"{len(everyone)} recipients: an e-mail goes to at most {RECIPIENTS_MAX} in all (To, Cc and Bcc)")
    keys = [mail_address.address_key(a) for a in everyone]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    if twice:
        raise _usage(f"the address {twice[0]} is listed twice")


def check_subject(subject) -> str:
    if not isinstance(subject, str) or not subject.strip() or subject != subject.strip() or len(subject) > SUBJECT_MAX or CONTROL.search(subject):
        raise _usage(f"the subject is one line of at most {SUBJECT_MAX} characters, with no space around it")
    if "=?" in subject:
        raise _usage("the subject holds no =? (a mail library decodes an encoded word, and the text sent would not be the text approved)")
    return subject


def lines_as_lf(text):
    """The text with its line breaks (CRLF, CR) written LF, as the document holds it; anything that is not text is returned as it is."""
    return text.replace("\r\n", "\n").replace("\r", "\n") if isinstance(text, str) else text


def check_body(body) -> bytes:
    if not isinstance(body, str) or not body.strip() or "\x00" in body or "\r" in body or CONTROL_TEXT.search(body):
        raise _usage("the body is non-empty text with line breaks written \\n (no \\r) and no control character but a tab")
    data = body.encode("utf-8")
    if len(data) > BODY_MAX:
        raise _usage(f"the body is {len(data)} bytes, over the {BODY_MAX} one e-mail takes")
    return data


def check_reference(value):
    if value is not None and (not isinstance(value, str) or not REFERENCE.fullmatch(value) or "=?" in value):
        raise _usage("in_reply_to is a Message-ID, one <local@domain> with no space")
    return value


def key_of(*, task_id: int, from_addr: str, to, cc, bcc, subject: str, body: str, in_reply_to, attachments, own=None) -> str:
    """`send-` and 32 hex digits: the key of one e-mail, from everything the person approves of it. `own` is what an e-mail from the person's own account adds
    to that (its account, conversation, references and the message answered); the outbox's e-mail has none, and its key is the one it always had."""
    said = {"task": task_id, "from": from_addr, "to": list(to), "cc": list(cc), "bcc": list(bcc), "subject": subject, "body": body,
            "in_reply_to": in_reply_to, "attachments": [[a["name"], a["sha256"]] for a in attachments]}
    if own is not None:
        said["own"] = own
    return "send-" + sha(json.dumps(said, sort_keys=True, ensure_ascii=True, separators=(",", ":")))[:32]


def reply_of(facts: dict) -> dict:
    """The `reply` of a document from the facts of the message answered (runtime/mail_refs.py reply_facts): the REPLY_KEYS, and `received` only when the index
    recorded the time (a null one is no key: the document of such a message is the one it was before the key existed, with the hash it had)."""
    reply = {k: facts[k] for k in REPLY_KEYS}
    if facts.get("received") is not None:
        reply["received"] = facts["received"]
    return reply


def _reply_part(reply: dict) -> dict:
    """The keys of `reply` a document keeps: the seven, and an optional one only when it is there."""
    return {k: reply.get(k) for k in REPLY_KEYS + tuple(k for k in REPLY_OPTIONAL if k in reply)}


def _own_of(account, thread_id, references, reply):
    """What key_of adds for an own-account e-mail: nothing the card does not show or the service does not need."""
    return {"account": account, "thread_id": thread_id, "references": list(references or []), "reply": None if reply is None else _reply_part(reply)}


def message_id_of(key: str, from_addr: str) -> str:
    """`<oh.<32 hex>@domain>` derived from the key (providers/_email.py message_id with a seed: a test holds them equal)."""
    return f"<oh.{sha(key)[:32]}@{mail_address.domain_of(from_addr)}>"


def document(*, task_id: int, provider: str, from_addr: str, to: list, cc: list, bcc: list, subject: str, body: str, in_reply_to,
             attachments: list, dry_run_sha256: str, account=None, thread_id=None, references=None, reply=None) -> dict:
    """The effect document, checked. `attachments` is [{path, name, bytes, sha256}] (the media type is derived). EffectError usage when a
    piece is not in its form, a limit is passed, or the subject or the body holds what looks like a credential. `account` (with `thread_id`, `references` and
    `reply`) makes it an e-mail from the person's own account."""
    items = [{"path": a["path"], "name": a["name"], "media_type": _media_or_blank(a["name"]), "bytes": a["bytes"], "sha256": a["sha256"]}
             for a in attachments]
    own = _own_of(account, thread_id, references, reply) if account is not None else None
    key = key_of(task_id=task_id, from_addr=from_addr, to=to, cc=cc, bcc=bcc, subject=subject, body=body, in_reply_to=in_reply_to,
                 attachments=items, own=own)
    doc = {"effect": WORD, "task": task_id, "provider": provider, "from": from_addr, "to": list(to), "cc": list(cc), "bcc": list(bcc),
           "subject": subject, "body": body, "body_sha256": sha(body), "in_reply_to": in_reply_to, "attachments": items,
           "message_id": message_id_of(key, from_addr) if isinstance(from_addr, str) and "@" in from_addr else "", "idempotency_key": key,
           "dry_run_sha256": dry_run_sha256}
    if own is not None:
        doc.update(account=account, thread_id=thread_id, references=list(references or []), reply=None if reply is None else _reply_part(reply))
    check(doc)
    return doc


def _addresses_in(doc: dict, name: str) -> list:
    found = doc[name]
    if not isinstance(found, list) or not all(isinstance(a, str) for a in found):
        raise _usage(f"{name} is a list of addresses")
    try:
        if [mail_address.normalize_address(a) for a in found] != found:
            raise mail_address.AddressError("an address is in its normal form")
    except mail_address.AddressError as e:
        raise _usage(f"{name}: {e.reason}") from None
    return found


def is_own(doc) -> bool:
    """Whether the document is an e-mail from the person's own account (it has an `account`), not the outbox's."""
    return isinstance(doc, dict) and "account" in doc


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the send."""
    if not isinstance(doc, dict) or set(doc) not in (set(KEYS), set(KEYS) | set(ACCOUNT_KEYS)) or doc["effect"] != WORD:
        raise _usage("the effect document of an e-mail has exactly its keys")
    if not isinstance(doc["task"], int) or isinstance(doc["task"], bool) or doc["task"] < 1:
        raise _usage("task is a task id")
    if not isinstance(doc["provider"], str) or not PROVIDER.fullmatch(doc["provider"]):
        raise _usage("provider is the name of an implementation")
    if sender(doc["from"]) != doc["from"]:
        raise _usage("the sender is in its normal form")
    to, cc, bcc = (_addresses_in(doc, n) for n in ("to", "cc", "bcc"))
    check_recipients(doc["from"], to, cc, bcc)
    check_subject(doc["subject"])
    data = check_body(doc["body"])
    if doc["body_sha256"] != sha(data):
        raise _usage("the body is not the one whose hash the document states")
    check_reference(doc["in_reply_to"])
    attachments = doc["attachments"]
    if not isinstance(attachments, list) or len(attachments) > ATTACH_MAX:
        raise _usage(f"an e-mail has at most {ATTACH_MAX} attachments")
    total, names = 0, set()
    for item in attachments:
        if not isinstance(item, dict) or set(item) != set(ATTACHMENT_KEYS):
            raise _usage("an attachment has exactly its keys")
        if not isinstance(item["path"], str) or not DOCS_PATH.fullmatch(item["path"]) or ".." in item["path"].split("/") \
                or item["path"].endswith(".comments.md"):
            raise _usage("an attachment is a file under docs/")
        attachment_name(item["name"])
        if item["media_type"] != media_type(item["name"]):
            raise _usage("an attachment's media type is the one its extension has")
        if not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool) or item["bytes"] < 0 \
                or not isinstance(item["sha256"], str) or not SHA256.fullmatch(item["sha256"]):
            raise _usage("an attachment has its size and its sha256")
        if item["name"].lower() in names:
            raise _usage("two attachments have the same name")
        names.add(item["name"].lower())
        total += item["bytes"]
    if total > ATTACH_TOTAL_MAX:
        raise _usage(f"the attachments are {total} bytes together, over the {ATTACH_TOTAL_MAX} one e-mail takes")
    if is_own(doc):
        _check_own(doc)
    key = key_of(task_id=doc["task"], from_addr=doc["from"], to=to, cc=cc, bcc=bcc, subject=doc["subject"], body=doc["body"],
                 in_reply_to=doc["in_reply_to"], attachments=attachments,
                 own=_own_of(doc["account"], doc["thread_id"], doc["references"], doc["reply"]) if is_own(doc) else None)
    if doc["idempotency_key"] != key or doc["message_id"] != message_id_of(key, doc["from"]) or not MESSAGE_ID.fullmatch(doc["message_id"]):
        raise _usage("the key and the Message-ID are the ones the content derives")
    if not isinstance(doc["dry_run_sha256"], str) or not SHA256.fullmatch(doc["dry_run_sha256"]):
        raise _usage("dry_run_sha256 is the hash of what the provider's dry run printed")
    why = workcopy.scan((doc["subject"] + "\n" + doc["body"]).encode("utf-8"))
    if why:
        raise _usage(f"the subject or the body {why}: it is not sent anywhere")
    return doc


def recipients(doc: dict) -> list:
    """Every address the e-mail goes to, in the order of the envelope: To, then Cc, then Bcc."""
    return list(doc["to"]) + list(doc["cc"]) + list(doc["bcc"])


def title(doc: dict) -> str:
    """The title of the pending decision. An e-mail from the person's own account has a fixed one, written by code: the subject is the person's words and is on
    the card, not in the heading."""
    if is_own(doc):
        return phrases.en("TITLE_MAIL_REPLY" if doc["reply"] else "TITLE_MAIL_SEND")
    return f"Send e-mail: {doc['subject'][:80]}"


def describe(doc: dict) -> str:
    """What is approved, in one line."""
    n = len(recipients(doc))
    if is_own(doc):      # the record of an approval is kept for good: it names the account and the count, never the person's words
        return f"send an e-mail from their own {doc['account']} account {doc['from']} to {n} recipient{'' if n == 1 else 's'}"
    return f"send an e-mail from {doc['from']} to {n} recipient{'' if n == 1 else 's'}: {doc['subject'][:120]}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the text or an address."""
    out = {"recipients": len(recipients(doc)), "bcc": len(doc["bcc"]), "attachments": len(doc["attachments"]), "bytes": len(doc["body"].encode("utf-8")),
           "body_sha256": doc["body_sha256"], "message_id": doc["message_id"]}
    if is_own(doc):
        out.update(account=doc["account"], reply=doc["reply"] is not None)
    return out


def facts(doc: dict, kind: str, service_message_id=None) -> dict:
    """What the execution records of a send that landed: `kind` is "sent" or "replayed". `service_message_id` is the Message-ID the service gave the message when it
    is not the one the document asked for (Graph's `internetMessageId`): recorded, in its plain form, so that the message can be found in the sent mail."""
    out = {"sent": True, "replayed": kind == "replayed", "message_id": doc["message_id"], "recipients": len(recipients(doc)),
           "attachments": len(doc["attachments"]), "bytes": len(doc["body"].encode("utf-8")), "idempotency_key": doc["idempotency_key"]}
    if is_own(doc):
        out.update(account=doc["account"], reply=doc["reply"] is not None)
        if isinstance(service_message_id, str) and REFERENCE.fullmatch(service_message_id) and "=?" not in service_message_id:
            out["service_message_id"] = service_message_id
    return out


# --- an e-mail from the person's own account: what the card must not let a text fake, and the checks of its extra keys -------------------------------------

FRAME_MARK = "-----"
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2500\u2501\ufe58\ufe63\uff0d\u00ad"      # look-alikes of a hyphen that NFKC leaves alone
MARKDOWN = " \t#>*_`~|+:"      # what a Markdown renderer strips or turns into a style before a line's visible text
BULLET = re.compile(r"(?:[-+*]|\d+[.)])\s+")
GUTTER = "\u2502"      # the mark in front of every line of the text on the card: a line of the text can never be taken for a line of the card


def frame_like(line: str) -> bool:
    """Whether the visible form of a line of the person's text starts with the mark of the card's frame rules (five hyphens), as a phone shows it after a
    Markdown renderer made a heading, a quote, a bold span or a list item of it: NFKC, the look-alike dashes read as hyphens, the Markdown markers and a list
    bullet stripped. Such a line could look like the end of the text (the card also puts a mark in front of every line of the text, so this is the second guard)."""
    seen = unicodedata.normalize("NFKC", line)
    seen = "".join("-" if unicodedata.category(c) == "Pd" or c in DASHES else c for c in seen)
    for _ in range(8):
        stripped = seen.lstrip(MARKDOWN)
        found = BULLET.match(stripped)
        stripped = stripped[found.end():] if found else stripped
        if stripped == seen:
            break
        seen = stripped
    return seen.startswith(FRAME_MARK)


def guttered(text: str) -> str:
    """The text as the card shows it: every line behind the gutter mark, an empty line too, the last line break dropped. A renderer that reads Markdown finds a
    line that begins with the mark, never a heading, a quote, a rule or a fence."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(f"{GUTTER} {line}" if line else GUTTER for line in lines)


def text_problem(text, multiline: bool = True) -> str:
    """Why a text of an e-mail from the person's own account cannot be on a card as it is, or "": it holds a control character (but the line end and the tab of a
    body), a format, separator, surrogate or private-use character (a card with one is no card: a hidden character could make a line say what it does not), or a
    line that could pass for the frame of the card."""
    if not isinstance(text, str):
        return ""
    for c in text:
        if multiline and c in "\n\t":
            continue
        if unicodedata.category(c) in HIDDEN or c in INVISIBLE:
            return phrases.en("ACCT_MAIL_TEXT_HIDDEN")
    if multiline and any(frame_like(line) for line in text.split("\n")):
        return phrases.en("ACCT_MAIL_FRAME")
    return ""


def _check_own(doc: dict) -> None:
    """The extra keys of an e-mail from the person's own account are in their form, and they agree with the rest of the document."""
    account = doc["account"]
    if account not in ACCOUNTS or doc["provider"] != ACCOUNTS[account]:
        raise _usage("account is google or microsoft, and the provider is the mailer of that account")
    thread, references, reply = doc["thread_id"], doc["references"], doc["reply"]
    if thread is not None and (not isinstance(thread, str) or not THREAD_ID.fullmatch(thread)):
        raise _usage("thread_id is the id of a conversation")
    if not isinstance(references, list) or not all(isinstance(r, str) for r in references):
        raise _usage("references is a list of Message-IDs")
    for item in references:
        check_reference(item)
    if account == "google" and doc["bcc"]:
        raise _usage("a Bcc is not sent from a Google account in this version")
    if text_problem(doc["body"]) or text_problem(doc["subject"], multiline=False):
        raise _usage("the subject or the body holds a character or a line a card cannot show")
    if reply is None:
        if thread is not None or references or doc["in_reply_to"] is not None:
            raise _usage("an e-mail that answers no message has no conversation and no references")
        return
    if not isinstance(reply, dict) or set(reply) not in (set(REPLY_KEYS), set(REPLY_KEYS) | set(REPLY_OPTIONAL)):
        raise _usage("the message answered has exactly its keys")
    if "received" in reply and reply["received"] is not None and (not isinstance(reply["received"], str) or not RECEIVED.fullmatch(reply["received"])
                                                                   or snapshot_text.parse_moment(reply["received"]) is None):      # the shape, and a date that exists
        raise _usage("the message answered has the time it came, as the index recorded it")
    for name in ("address", "reply_to"):
        value = reply[name]
        if value is None and name == "reply_to":
            continue
        try:
            if not isinstance(value, str) or mail_address.normalize_address(value) != value:
                raise mail_address.AddressError("an address in its normal form")
        except mail_address.AddressError as e:
            raise _usage(f"the message answered: {name}: {e.reason}") from None
    if not isinstance(reply["ref"], str) or not SNAPSHOT_REF.fullmatch(reply["ref"]):
        raise _usage("the message answered is named by a reference of a snapshot")
    if not isinstance(reply["subject"], str) or len(reply["subject"]) > REPLY_SUBJECT_MAX or CONTROL.search(reply["subject"]) \
            or text_problem(reply["subject"], multiline=False) or not isinstance(reply["read_at"], str) or len(reply["read_at"]) > 40 \
            or text_problem(reply["read_at"], multiline=False):
        raise _usage("the message answered has a subject of at most 120 characters, and the time of its snapshot")
    if reply["provider_id"] is not None and (not isinstance(reply["provider_id"], str) or not PROVIDER_ID.fullmatch(reply["provider_id"])):
        raise _usage("the message answered has the service's id")
    if reply["message_id"] is None:
        raise _usage("a reply names the message it answers in In-Reply-To and References")
    check_reference(reply["message_id"])
    if doc["in_reply_to"] != reply["message_id"] or references != [reply["message_id"]]:
        raise _usage("a reply names the message it answers in In-Reply-To and References")
    if doc["to"] != [reply["address"]] or doc["cc"] or doc["bcc"] or doc["attachments"]:
        raise _usage("a reply goes to the sender of the message it answers, and to no one else, with no attachment")
    if doc["subject"][:3].lower() != "re:":
        raise _usage("the subject of a reply starts with Re:")
    if account == "google" and (thread is None or reply["provider_id"] is None):
        raise _usage("a reply from a Google account names the conversation and the id of the message")
    if account == "microsoft" and (thread is not None or reply["provider_id"] is None):
        raise _usage("a reply from a Microsoft account names the service's id of the message, and no conversation")


def received_text(received: str) -> str:
    """The moment a message came (the index's `received`, UTC) as the card says it, in the machine's zone: `Thu 22/10/2026 14:05`, with the English weekday that
    phrases.localize_dates turns into the project's word on a phone. The value is the document's own, so the card shows exactly what the hash covers."""
    moment = snapshot_text.to_zone(snapshot_text.parse_moment(received)[1], None)
    return f"{ENGLISH_WEEKDAY[moment.weekday()]} {moment.day:02d}/{moment.month:02d}/{moment.year} {moment:%H:%M}"


def card_lines(doc: dict, digest: str) -> list:
    """The card of an e-mail from the person's own account, line by line: [[phrase key, {field: text}], ...], every key of the family CARD_ (runtime/phrases.py).
    The sender (the account) and every recipient come first, so that nothing a long text can do hides one; the Bcc is listed; then the subject, the message answered
    (and the other address it asked replies to go to, which is not used), the text exactly as it will be sent behind a mark on every line, each attachment by
    name, size and hash, and the hash with the command that approves it. The values are the person's or a service's words and are never translated."""
    own = [["CARD_MAIL_REPLY" if doc["reply"] else "CARD_MAIL_SEND", {}], ["CARD_MAIL_FROM_ACCOUNT", {"address": doc["from"], "account": doc["account"]}]]
    reply = doc["reply"]
    if reply:
        said = {"address": reply["address"], "ref": reply["ref"], "read_at": reply["read_at"], "subject": reply["subject"] or "-"}
        if reply.get("received"):      # S16C-REPLY-DATE: the time the message came, when the index had it; a reply made before shows the line it always showed
            own.append(["CARD_MAIL_REPLY_TO_AT", {**said, "received": received_text(reply["received"])}])
        else:
            own.append(["CARD_MAIL_REPLY_TO", said])
        if reply["reply_to"]:
            own.append(["CARD_MAIL_REPLY_TO_DIFFERS", {"other": reply["reply_to"]}])
        own.append(["CARD_MAIL_IN_REPLY", {"message_id": doc["in_reply_to"]}])
    else:
        own.append(["CARD_MAIL_TO", {"addresses": ", ".join(doc["to"])}])
    for key, name in (("CARD_MAIL_CC", "cc"), ("CARD_MAIL_BCC", "bcc")):
        if doc[name]:
            own.append([key, {"addresses": ", ".join(doc[name])}])
    own += [["CARD_MAIL_SUBJECT_REPLY" if reply else "CARD_MAIL_SUBJECT", {"subject": doc["subject"]}], ["CARD_MAIL_COUNT", {"count": str(len(recipients(doc)))}],
            ["CARD_MAIL_MESSAGE", {"body": guttered(doc["body"])}]]
    if doc["attachments"]:
        own.append(["CARD_MAIL_ATTACHMENTS", {"count": str(len(doc["attachments"]))}])
        own += [["CARD_MAIL_ATTACHMENT", {"name": a["name"], "bytes": str(a["bytes"]), "sha": a["sha256"], "path": a["path"]}] for a in doc["attachments"]]
        own.append(["CARD_MAIL_ATTACH_NOTE", {}])
    own += [["CARD_MAIL_HASH", {"sha": digest}],
            ["CARD_MAIL_APPROVE", {"command": operations.command_line("approve", "<project>", pending_id="<this pending decision's id>", sha256=digest)}],
            ["CARD_MAIL_ONCE", {}]]
    return own


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving, the whole e-mail: the sender and every recipient first (so that nothing a long text can do
    hides one), the Bcc included, then the subject, the reply, the text exactly as it will be sent, each attachment by name, size and hash, and
    the hash of the effect with the command that approves it. For an e-mail from the person's own account, the lines of its card in English."""
    if is_own(doc):
        return phrases.card_text(card_lines(doc, digest))

    def line(label, items):
        return f"{label}: " + (", ".join(items) if items else "(none)")
    lines = ["Code sends this e-mail after your approval, to exactly these recipients and no one else, and nothing else.", "",
             f"From: {doc['from']}", line("To", doc["to"]), line("Cc", doc["cc"]),
             line("Bcc (hidden from the others, listed here for you)", doc["bcc"]),
             f"Subject: {doc['subject']}", f"In-Reply-To: {doc['in_reply_to'] or '(none, a new conversation)'}",
             f"Recipients in all: {len(recipients(doc))}", "", "----- the message, exactly as it will be sent -----", doc["body"].rstrip("\n"),
             "----- end of the message -----", ""]
    if doc["attachments"]:
        lines += [f"Attachments ({len(doc['attachments'])}), each a copy of a file of the project, sent only if it is still the same file:"]
        lines += [f"  {a['name']}: {a['bytes']} bytes, sha256 {a['sha256']} (from {a['path']})" for a in doc["attachments"]]
        lines += ["The file itself is not on this card: read it in the project before you approve.", ""]
    lines += [f"Hash of this effect (it covers every recipient above, the text and the attachments): {digest}",
              "Approve exactly this: " + operations.command_line("approve", "<project>", pending_id="<this pending decision's id>", sha256=digest),
              "It is sent once, whatever the number of approvals of this hash. Or answer with what to change, or reject it: nothing is "
              "sent until you approve."]
    return "\n".join(lines) + "\n"


def provider_args(doc: dict, subject_file: str, body_file: str, attachment_files) -> list:
    """The flags of the provider's `send`, without --dry-run or --confirmed, for this document: the recipients exactly as the document has
    them, the Message-ID and the key the document derives. `attachment_files` is the private path of each attachment, in order."""
    args = ["--from", doc["from"], "--to", *doc["to"]]
    if doc["cc"]:
        args += ["--cc", *doc["cc"]]
    if doc["bcc"]:
        args += ["--bcc", *doc["bcc"]]
    args += ["--subject-file", subject_file, "--body-file", body_file]
    for item, path in zip(doc["attachments"], attachment_files):
        args += ["--attach", f"{path}={item['name']}"]
    if doc["in_reply_to"]:
        args += ["--in-reply-to", doc["in_reply_to"]]
    if is_own(doc):      # the conversation of the message answered: Gmail's thread, Outlook's id of the message
        if doc["references"]:
            args += ["--references", *doc["references"]]
        if doc["account"] == "google" and doc["thread_id"]:
            args += ["--thread-id", doc["thread_id"]]
        if doc["account"] == "microsoft" and doc["reply"]:
            args += ["--reply-id", doc["reply"]["provider_id"]]
    return args + ["--message-id", doc["message_id"], "--idempotency-key", doc["idempotency_key"]]
