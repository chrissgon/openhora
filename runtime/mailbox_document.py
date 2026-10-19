#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of a change to the person's own mailbox, and nothing that writes (package W3): what the step kind `mailbox-change` builds and the effect kind
`mailbox` approves. The effect document (its keys, its checks, the credential scan of the words the person gave), the card the person reads, the one line that
says what is approved, the closed facts a decision's payload records, and the arguments of the mailbox writer's verbs. It holds no function that calls a provider or
executes an effect: that is runtime/effect_mailbox.py, reached from the operation `approve` only. The step kind imports this module and not that one, so a step kind
has no function in reach that could write (limit L30; limit L55).

The word is `mailbox`: archive, move to a folder or label, mark as read or unread, move to the trash, and save a draft. The code of this word SENDS NOTHING (a draft is
saved, never sent) and REMOVES NOTHING FOR GOOD (the trash is the provider's: Gmail's trash empties itself after 30 days and so does Outlook's Deleted Items (Microsoft's restore page for Outlook.com says 30 days); the code never deletes: the person
empties it). A move goes only to a mail folder or label the project's `accounts` names (`mail_folders`), or to the provider's own archive and trash.

The document. `effect` ("mailbox"), `task` (the step task that prepared it), `account` (`google` or `microsoft`), `implementation` (the mailbox writer of that account, a
provider of providers/writer/: `gmail` or `outlook-mail`), `address` (the account's address as the project's `accounts` lists it), `action` (`archive`, `move`, `mark`,
`trash` or `draft`), `folder` (the name `accounts.<a>.mail_folders` gives the target of a move, else null) and `folder_id` (what the request names: a Gmail label id
for a move; for Outlook `archive` for an archive, `deleteditems` for a trash, the folder id of a move; else null), `state` (`read` or `unread` for a mark), `remove_inbox`
(a Gmail move that also leaves the inbox), `messages` (the messages, 1 to 20, each as it was READ FROM THE MAILBOX when the task prepared: its id, the reference the person
named it by, its subject and sender as the service holds them now, its date, the time of the snapshot the reference came from, and the base the change is checked against
(Gmail: the labels; Outlook: the changeKey and the folder)), `draft` (the draft, for `draft`, else null), `zone` (the host's zone, the one every date of the document is
written in), `read_at` (when the task read the messages), `idempotency_key` (derived from everything above: one request is done once) and `dry_run_sha256` (the hash of
what the writer's dry run printed: the exact requests it would send).

Standard library only, plus the credential scan of runtime/workcopy.py, the checks of the e-mail of runtime/send_document.py, the error class of runtime/effects.py and the
phrase table. Runs on Python 3.9.
"""
from __future__ import annotations

import base64
import datetime
import email
import email.policy
import email.utils
import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import mail_address  # noqa: E402
import phrases  # noqa: E402
import send_document  # noqa: E402  (the checks of a subject, a body, recipients and a Message-ID)
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "mailbox"
ACTIONS = ("archive", "move", "mark", "trash", "draft")
ACCOUNTS = ("google", "microsoft")
IMPLEMENTATION = {"google": "gmail", "microsoft": "outlook-mail"}      # the writer of each account (providers/writer/)
SECRET = {"google": "GOOGLE_ACCOUNT_TOKEN", "microsoft": "MICROSOFT_ACCOUNT_TOKEN"}   # the one secret a writer of that account is started with
TITLE_KEY = {"archive": "TITLE_BOX_ARCHIVE", "move": "TITLE_BOX_MOVE", "mark": "TITLE_BOX_MARK", "trash": "TITLE_BOX_TRASH", "draft": "TITLE_BOX_DRAFT"}
STATES = ("read", "unread")
KEYS = ("effect", "task", "account", "implementation", "address", "action", "folder", "folder_id", "state", "remove_inbox", "messages", "draft", "zone", "read_at",
        "idempotency_key", "dry_run_sha256")
MESSAGE_KEYS = ("n", "ref", "id", "subject", "sender", "date", "snapshot_at", "labels", "change_key", "folder_id", "is_read", "internet_id")
DRAFT_KEYS = ("to", "cc", "bcc", "subject", "body", "reply")
REPLY_KEYS = ("ref", "id", "thread_id", "message_id", "sender", "reply_to", "subject", "date", "snapshot_at")
MESSAGES_MAX = 20            # messages in one card: the platform's cap, and the writers hold the same
SUBJECT_SHOWN = 80           # characters of a subject on a card
SENDER_SHOWN = 254
SHA256 = re.compile(r"[0-9a-f]{64}")
KEY = re.compile(r"box-[0-9a-f]{32}")
NAME = re.compile(r"[a-z0-9-]{1,32}")
REF = re.compile(r"[a-z0-9][a-z0-9-]{0,39}#[1-9][0-9]{0,3}")
ZONE = re.compile(r"[A-Za-z0-9_+/:-]{1,64}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
LOCAL = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
GMAIL_ID = re.compile(r"(?!-)[A-Za-z0-9_-]{1,64}")      # (an id never starts with a hyphen: the writer's flag parser would read it, and its own patterns refuse it)
GMAIL_LABEL = re.compile(r"(?!-)[A-Za-z0-9_-]{1,64}")
GRAPH_ID = re.compile(r"(?!-)[A-Za-z0-9_=+-]{1,600}")
GRAPH_FOLDER = re.compile(r"(?!-)[A-Za-z0-9_=-]{1,300}")
CHANGE_KEY = re.compile(r"(?!-)[A-Za-z0-9_=+/.-]{1,200}")
INTERNET_ID = re.compile(r"[\x21-\x7e]{1,998}")
# Where a move may go: never a label that means something else in Gmail (the trash and the spam folder are reached by their own actions or not at all, an unread flag is
# not a place), and in Outlook a well-known name of this closed list or a folder id (every other all-lowercase name, `drafts`, `outbox`..., is not a place for a move).
GMAIL_REFUSED_TARGETS = ("INBOX", "TRASH", "SPAM", "SENT", "DRAFT", "UNREAD", "CHAT")
OUTLOOK_NAMES = ("archive", "inbox")      # the provider's own folders a move may name (Deleted Items is the trash's, Junk is never a place to move to)
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")      # control, format (a right-to-left override, a zero-width character), separators, surrogate, private use


def sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _usage(reason: str):
    return effects.EffectError("usage", reason)


FORBIDDEN_MOVE_FOLDERS = ("deleteditems", "junkemail", "recoverableitemsdeletions", "recoverableitemspurges", "drafts", "outbox", "sentitems")      # Outlook folders a mail_folders id may never be (trash is mail-trash's)


def text_problem(text, *, lines: bool = False):
    """Why a draft's subject or text cannot be shown on a card and saved as it is shown, or None: W2's check (send_document.text_problem) of a text of an e-mail from
    the person's own account: a control, format, separator, surrogate or private-use character, a filler that draws nothing (U+3164 and its kind), and, for a text of
    lines, a line that could pass for the frame of the card. The card also puts the gutter mark in front of every line of the text (send_document.guttered)."""
    return send_document.text_problem(text, multiline=lines) or None


def destination_ok(account: str, value) -> bool:
    """Whether `value` may be the target of a move: a Gmail label id that is not one of GMAIL_REFUSED_TARGETS, an Outlook well-known name of OUTLOOK_NAMES or a folder id."""
    if not isinstance(value, str):
        return False
    if account == "google":
        return GMAIL_LABEL.fullmatch(value) is not None and value.upper() not in GMAIL_REFUSED_TARGETS
    return GRAPH_FOLDER.fullmatch(value) is not None and not (value.isalpha() and value.casefold() not in OUTLOOK_NAMES)


# --- the words of other people, as a card shows them ---------------------------------------------------------------------------------------------------------


def clean_line(value, maximum: int) -> str:
    """Another person's text on one line for the card: a control character or a line or paragraph separator is a space, the other hidden characters (a
    right-to-left override, a zero-width character) are removed, the space is folded, and the text is cut at `maximum` (an ellipsis marks a cut)."""
    text = "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else "" if unicodedata.category(c) in HIDDEN else c for c in str(value if value is not None else ""))
    text = " ".join(text.split())
    return text if len(text) <= maximum else text[:maximum - 1].rstrip() + "…"


def local_text(stamp, zone_fallback=None) -> str:
    """`YYYY-MM-DD HH:MM` in the machine's zone of an instant `YYYY-MM-DDTHH:MM:SSZ`; `-` when there is none."""
    if not isinstance(stamp, str) or not STAMP.fullmatch(stamp):
        return "-"
    moment = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def zone_name() -> str:
    """The name of the machine's zone: TZ when it is a zone name, else the zone the machine's local-time file points to, else the offset. Display only."""
    for found in (os.environ.get("TZ", "").lstrip(":"), os.path.realpath("/etc/localtime").partition("zoneinfo/")[2]):
        if found and ZONE.fullmatch(found) and "/" in found and ".." not in found:
            return found
    offset = datetime.datetime.now().astimezone().utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset else 0
    return f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def utc_text(stamp) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` of an ISO-8601 time with or without an offset (a time without one is read as UTC); EffectError usage when it is not a time."""
    try:
        moment = datetime.datetime.fromisoformat(stamp[:-1] + "+00:00" if isinstance(stamp, str) and stamp.endswith("Z") else stamp)
    except (ValueError, TypeError):
        raise _usage("the time of a reading is an ISO-8601 time") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reply_subject(subject: str) -> str:
    """`Re: <subject>` unless the subject already starts with `Re:` (any case), cut at the subject limit of an e-mail."""
    text = clean_line(subject, send_document.SUBJECT_MAX) or "-"
    out = text if re.match(r"re:", text, re.I) else f"Re: {text}"
    return out[:send_document.SUBJECT_MAX].rstrip()


# --- a message as the mailbox holds it now ------------------------------------------------------------------------------------------------------------


def message_item(account: str, n: int, ref: str, snapshot_at: str, live: dict) -> dict:
    """The entry of the document for message `n` (1-based), from what the writer's `message-meta` printed (`live`, found) and the reading time of the snapshot the
    reference came from. The subject and the sender are another person's words: cleaned, cut, and replaced by nothing when they look like a credential. EffectError
    usage when the writer's answer is not in its form."""
    if not isinstance(live, dict) or live.get("found") is not True or not isinstance(live.get("id"), str):
        raise _usage("the writer's answer about a message is not in its form")
    subject = clean_line(live.get("subject"), SUBJECT_SHOWN)
    sender = live.get("from_address") if isinstance(live.get("from_address"), str) else ""
    if workcopy.scan(f"{subject}\n{sender}".encode("utf-8")):
        subject, sender = "", ""
    item = {"n": n, "ref": ref, "id": live["id"], "subject": subject, "sender": sender[:SENDER_SHOWN], "date": local_text(live.get("date")), "snapshot_at": snapshot_at,
            "labels": None, "change_key": None, "folder_id": None, "is_read": None, "internet_id": None}
    if account == "google":
        labels = live.get("labels")
        if not isinstance(labels, list) or not all(isinstance(v, str) for v in labels):
            raise _usage("the writer's answer about a message has no labels")
        item["labels"] = sorted(labels)
    else:
        item.update(change_key=live.get("change_key"), folder_id=live.get("folder_id"), is_read=live.get("is_read"), internet_id=live.get("message_id"))
    return item


def base_of(account: str, item: dict):
    """What a change is checked against: Gmail's labels, Outlook's changeKey and folder (and the read state, for a mark)."""
    if account == "google":
        return list(item["labels"])
    return {"change_key": item["change_key"], "folder_id": item["folder_id"], "is_read": item["is_read"]}


# --- the document ---------------------------------------------------------------------------------------------------------------------------------------


def key_of(doc: dict) -> str:
    """`box-` and 32 hex digits: the key of one request, from everything the person approves of it (the key and the dry-run hash are not content)."""
    said = {k: doc[k] for k in KEYS if k not in ("idempotency_key", "dry_run_sha256")}
    return "box-" + sha(json.dumps(said, sort_keys=True, ensure_ascii=True, separators=(",", ":")))[:32]


def document(*, task_id: int, account: str, address: str, action: str, folder=None, folder_id=None, state=None, remove_inbox: bool = False, messages=None, draft=None,
             zone: str, read_at: str, dry_run_sha256: str) -> dict:
    """The effect document, checked. EffectError usage when a piece is not in its form, a limit is passed, or the words hold what looks like a credential."""
    doc = {"effect": WORD, "task": task_id, "account": account, "implementation": IMPLEMENTATION.get(account, ""), "address": address, "action": action, "folder": folder,
           "folder_id": folder_id, "state": state, "remove_inbox": remove_inbox, "messages": messages, "draft": draft, "zone": zone, "read_at": read_at,
           "idempotency_key": "", "dry_run_sha256": dry_run_sha256}
    doc["idempotency_key"] = key_of(doc)
    check(doc)
    return doc


def _check_message(account: str, item, n: int) -> None:
    if not isinstance(item, dict) or set(item) != set(MESSAGE_KEYS) or item["n"] != n or type(item["n"]) is not int:
        raise _usage("a message of the document has exactly its keys, numbered from 1 in order")
    if not isinstance(item["ref"], str) or not REF.fullmatch(item["ref"]):
        raise _usage("a message is named by a reference <source id>#<number>")
    pattern = GMAIL_ID if account == "google" else GRAPH_ID
    if not isinstance(item["id"], str) or not pattern.fullmatch(item["id"]):
        raise _usage("a message has the id the service gave it")
    for name, limit in (("subject", SUBJECT_SHOWN), ("sender", SENDER_SHOWN)):
        if not isinstance(item[name], str) or len(item[name]) > limit or any(unicodedata.category(c) in HIDDEN for c in item[name]):
            raise _usage(f"the {name} of a message is one clean line of at most {limit} characters")
    if not isinstance(item["date"], str) or not (LOCAL.fullmatch(item["date"]) or item["date"] == "-"):
        raise _usage("the date of a message is a local date and time")
    if not isinstance(item["snapshot_at"], str) or not STAMP.fullmatch(item["snapshot_at"]):
        raise _usage("snapshot_at is the time the snapshot was read")
    if account == "google":
        if not isinstance(item["labels"], list) or not all(isinstance(v, str) and GMAIL_LABEL.fullmatch(v) for v in item["labels"]) or item["labels"] != sorted(set(item["labels"])) \
                or any(item[k] is not None for k in ("change_key", "folder_id", "is_read", "internet_id")):
            raise _usage("a Gmail message has its sorted labels as its base, and no Outlook field")
    else:
        if item["labels"] is not None or not isinstance(item["change_key"], str) or not CHANGE_KEY.fullmatch(item["change_key"]) or not isinstance(item["folder_id"], str) \
                or not GRAPH_FOLDER.fullmatch(item["folder_id"]) or type(item["is_read"]) is not bool \
                or not (item["internet_id"] is None or (isinstance(item["internet_id"], str) and INTERNET_ID.fullmatch(item["internet_id"]))):
            raise _usage("an Outlook message has its changeKey and folder as its base, and no Gmail field")


def _check_draft(account: str, draft) -> None:
    if not isinstance(draft, dict) or set(draft) != set(DRAFT_KEYS):
        raise _usage("a draft has exactly its keys")
    for name in ("to", "cc", "bcc"):
        found = draft[name]
        if not isinstance(found, list) or not all(isinstance(a, str) for a in found):
            raise _usage(f"{name} is a list of addresses")
        try:
            if [mail_address.normalize_address(a) for a in found] != found:
                raise mail_address.AddressError("an address is in its normal form")
        except mail_address.AddressError as e:
            raise _usage(f"{name}: {e.reason}") from None
    send_document.check_recipients("", draft["to"], draft["cc"], draft["bcc"])
    send_document.check_subject(draft["subject"])
    send_document.check_body(draft["body"])
    for what, found in (("subject", text_problem(draft["subject"])), ("body", text_problem(draft["body"], lines=True))):
        if found:
            raise _usage(f"the {what} of a draft: {found}")
    reply = draft["reply"]
    if reply is not None:
        if not isinstance(reply, dict) or set(reply) != set(REPLY_KEYS):
            raise _usage("the message a draft answers has exactly its keys")
        pattern = GMAIL_ID if account == "google" else GRAPH_ID
        if not REF.fullmatch(str(reply["ref"])) or not isinstance(reply["id"], str) or not pattern.fullmatch(reply["id"]):
            raise _usage("the message a draft answers is named by a reference and an id")
        if account == "google":
            if not isinstance(reply["thread_id"], str) or not GMAIL_ID.fullmatch(reply["thread_id"]):
                raise _usage("a Gmail reply needs the thread of the message it answers")
            send_document.check_reference(reply["message_id"])
            if reply["message_id"] is None:
                raise _usage("a Gmail reply needs the Message-ID of the message it answers")
        try:
            sender = mail_address.normalize_address(reply["sender"])
        except (mail_address.AddressError, TypeError):
            raise _usage("the message a draft answers has no plain sender address to answer") from None
        if draft["to"] != [sender] or draft["cc"] or draft["bcc"]:
            raise _usage("a reply goes to the sender of the message it answers, and to no one else")
        if reply["reply_to"] is not None and (not isinstance(reply["reply_to"], str) or reply["reply_to"].lower() == sender.lower()):
            raise _usage("reply_to is the Reply-To address when it differs from the sender, else null")
        if draft["subject"] != reply_subject(reply["subject"]):
            raise _usage("the subject of a reply is Re: and the subject of the message it answers")
        for name in ("subject", "date"):
            if not isinstance(reply[name], str) or any(unicodedata.category(c) in HIDDEN for c in reply[name]):
                raise _usage("the message a draft answers is shown by clean lines")
    if workcopy.scan(f"{draft['subject']}\n{draft['body']}".encode("utf-8")):
        raise _usage("the subject or the body " + (workcopy.scan(f"{draft['subject']}\n{draft['body']}".encode("utf-8")) or "") + ": it is not saved anywhere")


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the write."""
    if not isinstance(doc, dict) or set(doc) != set(KEYS) or doc["effect"] != WORD:
        raise _usage("the effect document of a change to the mailbox has exactly its keys")
    if not isinstance(doc["task"], int) or isinstance(doc["task"], bool) or doc["task"] < 1:
        raise _usage("task is a task id")
    account = doc["account"]
    if account not in ACCOUNTS or doc["implementation"] != IMPLEMENTATION[account]:
        raise _usage("the account is google or microsoft, with the writer that serves it")
    try:
        if mail_address.normalize_address(doc["address"]) != doc["address"]:
            raise mail_address.AddressError("")
    except (mail_address.AddressError, TypeError):
        raise _usage("address is the account's address") from None
    action = doc["action"]
    if action not in ACTIONS:
        raise _usage(f"the action is one of {', '.join(ACTIONS)}")
    google = account == "google"
    if type(doc["remove_inbox"]) is not bool:
        raise _usage("remove_inbox is true or false")
    if action == "move":
        if not isinstance(doc["folder"], str) or not NAME.fullmatch(doc["folder"]) or not destination_ok(account, doc["folder_id"]):
            raise _usage("a move goes to a folder the project lists, under its name and its id (and not to a label that means something else)")
    elif doc["folder"] is not None or doc["remove_inbox"]:
        raise _usage("only a move has a folder, and only a Gmail move leaves the inbox")
    if action == "move" and not google and doc["remove_inbox"]:
        raise _usage("only a Gmail move leaves the inbox: Outlook moves a message, it does not label it")
    expected_id = {("archive", False): "archive", ("trash", False): "deleteditems"}.get((action, google))
    if action != "move" and doc["folder_id"] != expected_id:
        raise _usage("an archive or a trash names the provider's own folder, and Gmail names none")
    if action == "mark":
        if doc["state"] not in STATES:
            raise _usage("a mark is read or unread")
    elif doc["state"] is not None:
        raise _usage("only a mark has a state")
    if not isinstance(doc["zone"], str) or not ZONE.fullmatch(doc["zone"]):
        raise _usage("zone is the name of the machine's zone")
    if not isinstance(doc["read_at"], str) or not STAMP.fullmatch(doc["read_at"]):
        raise _usage("read_at is the time the messages were read")
    if action == "draft":
        if doc["messages"] is not None:
            raise _usage("a draft names no message of its own: the message it answers is inside the draft")
        _check_draft(account, doc["draft"])
    else:
        if doc["draft"] is not None:
            raise _usage("only a draft has a draft")
        messages = doc["messages"]
        if not isinstance(messages, list) or not 1 <= len(messages) <= MESSAGES_MAX:
            raise _usage(f"a change names 1 to {MESSAGES_MAX} messages")
        for n, item in enumerate(messages, 1):
            _check_message(account, item, n)
        if len({m["id"] for m in messages}) != len(messages):
            raise _usage("a message is named once")
    if not isinstance(doc["dry_run_sha256"], str) or not SHA256.fullmatch(doc["dry_run_sha256"]):
        raise _usage("dry_run_sha256 is the hash of what the writer's dry run printed")
    if not isinstance(doc["idempotency_key"], str) or not KEY.fullmatch(doc["idempotency_key"]) or doc["idempotency_key"] != key_of(doc):
        raise _usage("the key is the one the content derives")
    return doc


# --- what the person reads -------------------------------------------------------------------------------------------------------------------------------


def title(doc: dict) -> str:
    """The title of the pending decision: a sentence of the phrase table, written by code (the person's words are never in it)."""
    return phrases.en(TITLE_KEY[doc["action"]])


def describe(doc: dict) -> str:
    """What is approved, in one line. It holds none of the words of the person or of the mail: the state file is versioned."""
    n = len(doc["messages"]) if doc["messages"] else 1
    verb = {"archive": f"archive {n} message(s) of", "move": f"move {n} message(s) of", "mark": f"mark {n} message(s) as {doc['state']} in", "trash": f"move {n} message(s) to the trash of",
            "draft": "save a draft in"}[doc["action"]]
    where = f" to the folder '{doc['folder']}'" if doc["action"] == "move" else ""
    return f"{verb} the mailbox of the {doc['account']} account {doc['address']}{where}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the words of the person or of the mail."""
    return {"action": doc["action"], "account": doc["account"], "count": len(doc["messages"]) if doc["messages"] else 1, "folder": doc["folder"], "state": doc["state"]}


def facts(doc: dict, kind: str, got: dict) -> dict:
    """What the execution records of a write that landed: `kind` is "done" or "replayed"; `got` is what the writer printed. Closed words, numbers and ids."""
    out = {"done": True, "replayed": kind == "replayed", "action": doc["action"], "account": doc["account"], "count": len(doc["messages"]) if doc["messages"] else 1,
           "folder": doc["folder"], "state": doc["state"], "idempotency_key": doc["idempotency_key"]}
    if doc["action"] == "draft":
        draft_id = got.get("draft_id")
        out["draft_id"] = draft_id if isinstance(draft_id, str) else None
    return out


def _action_line(doc: dict) -> list:
    n = str(len(doc["messages"]))
    action = doc["action"]
    if action == "archive":
        return ["CARD_BOX_ARCHIVE", {"n": n}]
    if action == "move":
        return ["CARD_BOX_MOVE", {"folder": doc["folder"], "n": n}]
    if action == "mark":
        return ["CARD_BOX_READ" if doc["state"] == "read" else "CARD_BOX_UNREAD", {"n": n}]
    return ["CARD_BOX_TRASH_GMAIL" if doc["account"] == "google" else "CARD_BOX_TRASH_OUTLOOK", {"n": n}]


def card_lines(doc: dict, digest: str) -> list:
    """The card, line by line: [[key, {field: text}], ...], every key of the family CARD_ (runtime/phrases.py card_valid). The account first; then what is done and to
    how many messages; then EVERY message by the subject and sender the mailbox holds now (the lines of phrases.CARD_PRIVATE: a messaging app draws them only for a sender
    who may read the mail), and when it was read. A draft is shown whole, recipients first, and says it is not sent."""
    account = ["CARD_ACCOUNT", {"account": doc["account"], "address": doc["address"]}]
    if doc["action"] == "draft":
        draft = doc["draft"]
        out = [["CARD_BOX_CODE_DRAFT", {"address": doc["address"]}], account]
        reply = draft["reply"]
        if reply is not None:
            out.append(["CARD_BOX_DRAFT_REPLY", {"address": reply["sender"], "ref": reply["ref"], "date": reply["date"], "subject": reply["subject"] or "-"}])
            if reply["reply_to"]:
                out.append(["CARD_BOX_DRAFT_REPLY_DIFFERS", {"other": reply["reply_to"]}])
        # a reply's recipient and subject come from the message it answers, which is another person's text: its lines are the private ones (phrases.CARD_PRIVATE)
        out.append(["CARD_BOX_DRAFT_REPLY_TO" if reply is not None else "CARD_BOX_DRAFT_TO", {"to": ", ".join(draft["to"])}])
        if draft["cc"]:
            out.append(["CARD_BOX_DRAFT_CC", {"cc": ", ".join(draft["cc"])}])
        if draft["bcc"]:
            out.append(["CARD_BOX_DRAFT_BCC", {"bcc": ", ".join(draft["bcc"])}])
        return out + [["CARD_BOX_DRAFT_REPLY_SUBJECT" if reply is not None else "CARD_BOX_DRAFT_SUBJECT", {"subject": draft["subject"]}], ["CARD_BOX_DRAFT_TEXT", {"body": send_document.guttered(draft["body"])}], ["CARD_BOX_DRAFT_END", {}]]
    out = [["CARD_BOX_CODE", {"address": doc["address"]}], account, _action_line(doc)]
    for item in doc["messages"]:
        out.append(["CARD_BOX_ITEM", {"i": str(item["n"]), "date": item["date"], "sender": item["sender"] or "-", "subject": item["subject"] or "-"}])
    oldest = min(m["snapshot_at"] for m in doc["messages"])
    return out + [["CARD_BOX_READ_AT", {"read_at": doc["read_at"]}], ["CARD_BOX_SNAPSHOT", {"snapshot_at": oldest}]]


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving, in English: the lines of the card (runtime/phrases.py card_text). A messaging app says the same lines in the project's
    language; the hash on the card is the effect's own, in every language."""
    return phrases.card_text(card_lines(doc, digest))


# --- the writer's verbs ------------------------------------------------------------------------------------------------------------------------------------


def verb_of(doc: dict) -> str:
    """The verb of the writer that does this action on this account (providers/writer/README.md)."""
    action = doc["action"]
    if doc["account"] == "google":
        return {"archive": "modify", "move": "modify", "mark": "modify", "trash": "trash", "draft": "draft-create"}[action]
    if action == "draft":
        return "draft-reply" if doc["draft"]["reply"] is not None else "draft-create"
    return {"archive": "move", "move": "move", "mark": "mark", "trash": "move"}[action]


def labels_after(doc: dict) -> tuple:
    """(add, remove) label ids of a Gmail label change."""
    action = doc["action"]
    if action == "archive":
        return [], ["INBOX"]
    if action == "move":
        return [doc["folder_id"]], (["INBOX"] if doc["remove_inbox"] else [])
    return ([], ["UNREAD"]) if doc["state"] == "read" else (["UNREAD"], [])


def spec_of(doc: dict) -> dict:
    """What the writer is handed as a file (never on a command line): the ids with the base each message was read in, and what to do; or the draft."""
    account, action = doc["account"], doc["action"]
    if action == "draft":
        draft = doc["draft"]
        spec = {k: draft[k] for k in ("to", "cc", "bcc", "subject", "body")}
        if account == "google":
            reply = draft["reply"]
            spec.update(in_reply_to=reply["message_id"] if reply else None, thread_id=reply["thread_id"] if reply else None)
        return spec
    messages = doc["messages"]
    ids = [m["id"] for m in messages]
    if account == "google":
        base = {m["id"]: list(m["labels"]) for m in messages}
        if action == "trash":
            return {"ids": ids, "base": base}
        add, remove = labels_after(doc)
        return {"ids": ids, "base": base, "add": add, "remove": remove}
    if action == "mark":
        return {"ids": ids, "base": {m["id"]: {"change_key": m["change_key"], "is_read": m["is_read"]} for m in messages}, "read": doc["state"] == "read"}
    return {"ids": ids, "base": {m["id"]: {"change_key": m["change_key"], "folder_id": m["folder_id"]} for m in messages},
            "internet_ids": {m["id"]: m["internet_id"] for m in messages}, "to": doc["folder_id"]}


def provider_args(doc: dict, spec_file) -> list:
    """The flags of the writer's verb for this document, without --dry-run or --confirmed. `spec_file` is the private path of the spec."""
    args = ["--account", doc["address"]]
    if doc["action"] == "draft" and doc["draft"]["reply"] is not None and doc["account"] == "microsoft":
        args += ["--message", doc["draft"]["reply"]["id"]]
    return args + ["--spec-file", spec_file, "--idempotency-key", doc["idempotency_key"]]


def meta_args(doc: dict) -> list:
    """The flags of the writer's `message-meta` for the messages of a document (and the ledger of its key)."""
    args = ["--account", doc["address"], "--ids", ",".join(m["id"] for m in doc["messages"]), "--key", doc["idempotency_key"]]
    return args


def _path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _addresses_of(header) -> list:
    return [address for _, address in email.utils.getaddresses([str(header)])] if header is not None else []


MIME_HEADERS = ("from", "to", "cc", "bcc", "subject", "message-id", "in-reply-to", "references", "mime-version", "content-type", "content-transfer-encoding", "date")


def _gmail_draft_matches(draft: dict, body, address: str) -> bool:
    """Whether the draft the Gmail writer would save is the document's: the MIME it carries is from the account, has the document's recipients (the Bcc too), subject
    and text, the thread and In-Reply-To of a reply, no header but those a draft has, and nothing else is in the request."""
    if not isinstance(body, dict) or set(body) != {"message"} or not isinstance(body["message"], dict):
        return False
    message = body["message"]
    reply = draft["reply"]
    if set(message) - {"raw", "threadId"} or message.get("threadId") != (reply["thread_id"] if reply else None):
        return False
    try:
        parsed = email.message_from_bytes(base64.urlsafe_b64decode(str(message.get("raw", "")).encode("ascii")), policy=email.policy.default)
        text = parsed.get_body(("plain",)).get_content()
    except (ValueError, AttributeError, UnicodeError):
        return False
    if {name.lower() for name in parsed.keys()} - set(MIME_HEADERS) or _addresses_of(parsed["From"]) != [address]:
        return False
    return (_addresses_of(parsed["To"]) == draft["to"] and _addresses_of(parsed["Cc"]) == draft["cc"] and _addresses_of(parsed["Bcc"]) == draft["bcc"]
            and str(parsed["Subject"]) == draft["subject"] and text.replace("\r\n", "\n").rstrip("\n") == draft["body"].rstrip("\n")
            and (parsed["In-Reply-To"] == (reply["message_id"] if reply else None)))


def _graph_draft_matches(draft: dict, body) -> bool:
    """Whether the Outlook draft request is the document's: its recipients (the Bcc too), subject and text, and no key but those of a draft."""
    if not isinstance(body, dict) or set(body) - {"subject", "body", "toRecipients", "ccRecipients", "bccRecipients", "singleValueExtendedProperties"}:
        return False
    wrap = lambda addresses: [{"emailAddress": {"address": a}} for a in addresses]      # noqa: E731
    return (body.get("toRecipients") == wrap(draft["to"]) and body.get("ccRecipients") == wrap(draft["cc"]) and body.get("bccRecipients") == wrap(draft["bcc"])
            and body.get("subject") == draft["subject"] and body.get("body") == {"contentType": "text", "content": draft["body"]})


def requests_match(doc: dict, would) -> bool:
    """Whether what the writer's dry run says it would send is what the document says: the methods, the paths and the bodies of the action, and nothing that sends or
    removes. A request the writer would add to these, or leave out, is not. The step kind asks it of the dry run it asked for before it writes the document."""
    requests = would.get("requests") if isinstance(would, dict) else None
    if not isinstance(requests, list) or not all(isinstance(r, dict) and isinstance(r.get("path"), str) for r in requests):
        return False
    got = [(r.get("method"), r["path"], r.get("body")) for r in requests]
    action, google = doc["action"], doc["account"] == "google"
    ids = [m["id"] for m in doc["messages"]] if doc["messages"] else []
    if google:
        base = "/gmail/v1/users/me"
        if action == "trash":
            return got == [("POST", f"{base}/messages/{_path(i)}/trash", None) for i in ids]
        if action == "draft":
            return len(got) == 1 and got[0][0] == "POST" and got[0][1] == f"{base}/drafts" and _gmail_draft_matches(doc["draft"], got[0][2], doc["address"])
        add, remove = labels_after(doc)
        return got == [("POST", f"{base}/messages/batchModify", {"ids": ids, "addLabelIds": add, "removeLabelIds": remove})]
    if action == "mark":
        return got == [("PATCH", f"/me/messages/{_path(i)}", {"isRead": doc["state"] == "read"}) for i in ids]
    if action != "draft":
        return got == [("POST", f"/me/messages/{_path(i)}/move", {"destinationId": doc["folder_id"]}) for i in ids]
    draft = doc["draft"]
    if draft["reply"] is None:
        return len(got) == 1 and got[0][:2] == ("POST", "/me/messages") and _graph_draft_matches(draft, got[0][2])
    first = got[0][2] if len(got) == 2 and isinstance(got[0][2], dict) else {}
    return len(got) == 2 and got[0][:2] == ("POST", f"/me/messages/{_path(draft['reply']['id'])}/createReply") and set(first) == {"message"} \
        and _graph_draft_matches(draft, first["message"]) and got[1][0] == "PATCH" and _graph_draft_matches(draft, got[1][2])


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
