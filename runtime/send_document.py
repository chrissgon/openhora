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

Standard library only, plus the credential scan of runtime/workcopy.py and the error class of runtime/effects.py. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import mail_address  # noqa: E402
import operations  # noqa: E402  (the command line the preview shows)
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
    if not isinstance(subject, str) or not subject.strip() or len(subject) > SUBJECT_MAX or CONTROL.search(subject):
        raise _usage(f"the subject is one line of at most {SUBJECT_MAX} characters")
    return subject


def check_body(body) -> bytes:
    if not isinstance(body, str) or not body.strip() or "\x00" in body or CONTROL_TEXT.search(body):
        raise _usage("the body is non-empty text with no control character but a tab and a line break")
    data = body.encode("utf-8")
    if len(data) > BODY_MAX:
        raise _usage(f"the body is {len(data)} bytes, over the {BODY_MAX} one e-mail takes")
    return data


def check_reference(value):
    if value is not None and (not isinstance(value, str) or not REFERENCE.fullmatch(value)):
        raise _usage("in_reply_to is a Message-ID, one <local@domain> with no space")
    return value


def key_of(*, task_id: int, from_addr: str, to, cc, bcc, subject: str, body: str, in_reply_to, attachments) -> str:
    """`send-` and 32 hex digits: the key of one e-mail, from everything the person approves of it."""
    said = {"task": task_id, "from": from_addr, "to": list(to), "cc": list(cc), "bcc": list(bcc), "subject": subject, "body": body,
            "in_reply_to": in_reply_to, "attachments": [[a["name"], a["sha256"]] for a in attachments]}
    return "send-" + sha(json.dumps(said, sort_keys=True, ensure_ascii=True, separators=(",", ":")))[:32]


def message_id_of(key: str, from_addr: str) -> str:
    """`<oh.<32 hex>@domain>` derived from the key (providers/_email.py message_id with a seed: a test holds them equal)."""
    return f"<oh.{sha(key)[:32]}@{mail_address.domain_of(from_addr)}>"


def document(*, task_id: int, provider: str, from_addr: str, to: list, cc: list, bcc: list, subject: str, body: str, in_reply_to,
             attachments: list, dry_run_sha256: str) -> dict:
    """The effect document, checked. `attachments` is [{path, name, bytes, sha256}] (the media type is derived). EffectError usage when a
    piece is not in its form, a limit is passed, or the subject or the body holds what looks like a credential."""
    items = [{"path": a["path"], "name": a["name"], "media_type": _media_or_blank(a["name"]), "bytes": a["bytes"], "sha256": a["sha256"]}
             for a in attachments]
    key = key_of(task_id=task_id, from_addr=from_addr, to=to, cc=cc, bcc=bcc, subject=subject, body=body, in_reply_to=in_reply_to,
                 attachments=items)
    doc = {"effect": WORD, "task": task_id, "provider": provider, "from": from_addr, "to": list(to), "cc": list(cc), "bcc": list(bcc),
           "subject": subject, "body": body, "body_sha256": sha(body), "in_reply_to": in_reply_to, "attachments": items,
           "message_id": message_id_of(key, from_addr) if isinstance(from_addr, str) and "@" in from_addr else "", "idempotency_key": key,
           "dry_run_sha256": dry_run_sha256}
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


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the send."""
    if not isinstance(doc, dict) or set(doc) != set(KEYS) or doc["effect"] != WORD:
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
    key = key_of(task_id=doc["task"], from_addr=doc["from"], to=to, cc=cc, bcc=bcc, subject=doc["subject"], body=doc["body"],
                 in_reply_to=doc["in_reply_to"], attachments=attachments)
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
    """The title of the pending decision."""
    return f"Send e-mail: {doc['subject'][:80]}"


def describe(doc: dict) -> str:
    """What is approved, in one line."""
    n = len(recipients(doc))
    return f"send an e-mail from {doc['from']} to {n} recipient{'' if n == 1 else 's'}: {doc['subject'][:120]}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the text or an address."""
    return {"recipients": len(recipients(doc)), "bcc": len(doc["bcc"]), "attachments": len(doc["attachments"]), "bytes": len(doc["body"].encode("utf-8")),
            "body_sha256": doc["body_sha256"], "message_id": doc["message_id"]}


def facts(doc: dict, kind: str) -> dict:
    """What the execution records of a send that landed: `kind` is "sent" or "replayed"."""
    return {"sent": True, "replayed": kind == "replayed", "message_id": doc["message_id"], "recipients": len(recipients(doc)),
            "attachments": len(doc["attachments"]), "bytes": len(doc["body"].encode("utf-8")), "idempotency_key": doc["idempotency_key"]}


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving, the whole e-mail: the sender and every recipient first (so that nothing a long text can do
    hides one), the Bcc included, then the subject, the reply, the text exactly as it will be sent, each attachment by name, size and hash, and
    the hash of the effect with the command that approves it."""
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
    return args + ["--message-id", doc["message_id"], "--idempotency-key", doc["idempotency_key"]]
