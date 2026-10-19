#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations over the person's own mailbox (package W3): save a draft, archive messages, move them to a folder or label, mark them as read or unread, move them to the
trash. Each one PREPARES and nothing else: it resolves the messages the person named, checks its arguments, makes one request with one step task of the kind
`mailbox-change` (runtime/step_mailbox.py), runs the preparation in this process with no model, and stops at the card that asks the person to approve it
(runtime/account_start.py). It returns {"request", "task", "pending", "word", "on_cards"}; the messaging bridge then sends the decision's card as it sends every card and
says `account_start.reply_text`. Nothing is written to any mailbox here, nothing is sent and nothing is deleted: the write is runtime/effect_mailbox.py `execute`, reached
only by `approve` with the hash of the card (limit L55).

  mail_draft(project, account, [to, cc, bcc, subject, body] | [message, body])
        a draft in the account's Drafts, never sent: a new one (`to`, `subject` and `body`; `cc` and `bcc` optional; comma-separated plain addresses, at most 20 in all), or a
        reply (`message` is the reference of the message it answers, and `body`): it goes to that message's From address, never to its Reply-To
  mail_archive(project, account, messages)
        take 1 to 20 messages out of the inbox (Gmail removes the label INBOX; Outlook moves them to its Archive folder)
  mail_move(project, account, messages, folder)
        move 1 to 20 messages to a mail folder or label the project's `accounts` names (`folder` is that name)
  mail_mark(project, account, messages, state)
        mark 1 to 20 messages as `read` or `unread`
  mail_trash(project, account, messages)
        move 1 to 20 messages to the provider's trash (Gmail's Trash and Outlook's Deleted Items, which each empties after 30 days). This code deletes nothing

`messages` is a list of references, comma-separated: `<source id>#<n>`, the n-th message of the newest snapshot of a registered mail source (runtime/item_refs.py). The
reference is resolved HERE, with the caller's own right to read the snapshot (a messaging sender needs the group `ask-mail`), and the step reads each message from the mailbox
again; the card lists every message by the subject and sender the mailbox holds now.

Who may call what is the table of operations (runtime/operations.py: the group `mail-organize`, in no default policy, never on the MCP mode) and, for a messaging sender,
runtime/account_start.py (the profile of THAT sender, read from the configuration loaded for this call). The words of the person (a draft's text) reach a model nowhere on this
path: the card is made by code from the arguments.

Sibling of runtime/ops.py, which exposes the operations under their names. It reaches no operation of ops.py. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import account_start  # noqa: E402
import item_refs  # noqa: E402
import mailbox_document  # noqa: E402
import ops_core as core  # noqa: E402
import phrases  # noqa: E402
import send_document  # noqa: E402

KIND = "mailbox-change"
ACCOUNT_OF = {"gmail": "google", "outlook": "microsoft"}      # the implementation of a mail source -> the account it belongs to
REF_KEY = {"malformed": "ACCT_MBOX_REF_MALFORMED", "zero": "ACCT_MBOX_REF_ZERO", "not_readable": "ACCT_MBOX_REF_NOT_READABLE", "past_end": "ACCT_MBOX_REF_PAST_END",
           "no_source": "ACCT_MBOX_REF_NO_SOURCE", "not_snapshot": "ACCT_MBOX_REF_NOT_SNAPSHOT", "wrong_kind": "ACCT_MBOX_REF_WRONG_KIND", "no_version": "ACCT_MBOX_REF_NO_VERSION",
           "stale": "ACCT_MBOX_REF_STALE", "no_index": "ACCT_MBOX_REF_NO_INDEX", "integrity": "ACCT_MBOX_REF_INTEGRITY", "created_unavailable": "ACCT_MBOX_REF_EVENT",
           "created_unknown": "ACCT_MBOX_REF_EVENT"}      # every ItemRefError code of runtime/item_refs.py, by the sentence the person reads
USAGE_CODES = ("malformed", "zero")      # the codes that are a mistake in what the person typed, exit 2; every other is a refusal, exit 1
SPLIT = re.compile(r"[,\s]+")
NOT_SHOWN = re.compile(r"[^A-Za-z0-9_.#:-]")      # what a reference the person typed may show of itself in a sentence: its own characters, the others a question mark


def _shown(value, width: int = 40) -> str:
    return NOT_SHOWN.sub("?", str(value)[:width])


def _ref_error(error: "item_refs.ItemRefError", ref: str) -> "core.OpsError":
    """The sentence (in the phrase table, so a project's language says it) for a reference that cannot be resolved."""
    shown, source = _shown(ref), _shown(ref.partition("#")[0])
    key = REF_KEY.get(error.code, "ACCT_MBOX_REF_MALFORMED")
    return core.OpsError(phrases.en(key).format(ref=shown, source=source), 2 if error.code in USAGE_CODES else 1)


def _entry(ctx: dict, ref: str, account: str, channel, sender, reply: bool = False) -> dict:
    """The entry of the step's arguments for one reference: its reference, its id and the snapshot's time; for the message a reply answers also what a reply needs of
    the index (never a subject or any text)."""
    try:
        # who asked is passed as the caller gave it, never mapped to a channel with more rights: only a call that names no channel is the operations' own, the terminal
        got = item_refs.resolve(ctx, ref, channel=channel if channel is not None else "terminal", sender=sender, kinds=("mail",))
    except item_refs.ItemRefError as e:
        raise _ref_error(e, ref) from None
    if got.get("kind") != "item" or got.get("type") != "mail":
        raise _ref_error(item_refs.ItemRefError("wrong_kind", ""), ref)
    shown = _shown(ref)
    if ACCOUNT_OF.get(got.get("implementation")) != account:
        raise core.OpsError(phrases.en("ACCT_MBOX_OTHER_ACCOUNT").format(ref=shown, account=account), 1)
    entry = got["entry"]
    if not entry.get("id"):
        raise core.OpsError(phrases.en("ACCT_MBOX_NO_ID").format(ref=shown), 1)
    try:
        read_at = mailbox_document.utc_text(got["read_at"])
    except Exception:      # a reading time this code cannot read is a snapshot it cannot trust
        raise _ref_error(item_refs.ItemRefError("stale", ""), ref) from None
    kept = {"ref": f"{got['source']}#{got['n']}", "id": entry["id"], "snapshot_at": read_at}
    if reply:
        kept.update(thread_id=entry.get("thread_id"), message_id=entry.get("message_id"), from_address=entry.get("from_address"), reply_to_address=entry.get("reply_to_address"))
    return kept


def _entries(ctx: dict, references, account: str, channel, sender, reply: bool = False) -> list:
    if not isinstance(references, str):
        raise core.OpsError(phrases.en("ACCT_MBOX_NO_MESSAGES"), 2)
    refs = [r for r in SPLIT.split(references.strip()) if r]
    if not refs:
        raise core.OpsError(phrases.en("ACCT_MBOX_NO_MESSAGES"), 2)
    if len(refs) > mailbox_document.MESSAGES_MAX:
        raise core.OpsError(phrases.en("ACCT_MBOX_TOO_MANY").format(max=mailbox_document.MESSAGES_MAX, n=len(refs)), 2)
    twice = next((r for r in refs if refs.count(r) > 1), None)
    if twice is not None:
        raise core.OpsError(phrases.en("ACCT_MBOX_DUPLICATE").format(ref=_shown(twice)), 2)
    return [_entry(ctx, r, account, channel, sender, reply) for r in refs]


def _start(project: str, operation: str, action: str, account, make_args, channel, sender) -> dict:
    """The one start of the family. The policy of the channel is checked FIRST (a sender that may not organize the mailbox learns nothing from a reference), then the
    references are resolved with the caller's own right to read the snapshots, then the step is made."""
    key_words, title_key = f"mail-{operation}", {"archive": "TITLE_BOX_ARCHIVE", "move": "TITLE_BOX_MOVE", "mark": "TITLE_BOX_MARK", "trash": "TITLE_BOX_TRASH", "draft": "TITLE_BOX_DRAFT"}[action]
    ctx = core.context(project)
    account_start._policy(ctx, key_words, channel, sender)      # the same check start() makes, made before the references are read
    args = make_args(ctx)
    return account_start.start(project, KIND, {"account": account, "action": action, **args}, key_words=key_words, title_key=title_key, account=account, channel=channel,
                               sender=sender)


def mail_archive(project: str, account: str, messages: str, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare the archive of 1 to 20 messages and stop at its card. See the module's text."""
    return _start(project, "archive", "archive", account, lambda ctx: {"messages": _entries(ctx, messages, account, channel, sender)}, channel, sender)


def mail_move(project: str, account: str, messages: str, folder: str, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare the move of 1 to 20 messages to a folder or label of the project's `accounts` and stop at its card."""
    return _start(project, "move", "move", account, lambda ctx: {"messages": _entries(ctx, messages, account, channel, sender), "folder": folder}, channel, sender)


def mail_mark(project: str, account: str, messages: str, state: str, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare marking 1 to 20 messages as read or unread and stop at its card."""
    return _start(project, "mark", "mark", account, lambda ctx: {"messages": _entries(ctx, messages, account, channel, sender), "state": state}, channel, sender)


def mail_trash(project: str, account: str, messages: str, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare moving 1 to 20 messages to the provider's trash and stop at its card. Nothing is deleted for good."""
    return _start(project, "trash", "trash", account, lambda ctx: {"messages": _entries(ctx, messages, account, channel, sender)}, channel, sender)


def _addresses(text, name: str) -> list:
    try:
        return send_document.addresses(text if text is not None else "", name)
    except Exception as e:      # an EffectError of the e-mail checks: its reason names the rule and the entry, never more
        raise core.OpsError(str(getattr(e, "reason", "") or e), 2) from None


def mail_draft(project: str, account: str, to: str | None = None, cc: str | None = None, bcc: str | None = None, subject: str | None = None, body: str | None = None,
               message: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare a draft (new, or a reply to `message`) and stop at its card. A draft is saved, never sent. See the module's text."""
    if body is None:
        raise core.OpsError("a draft needs a body (--body)", 2)

    def make(ctx):
        if message is not None:
            if any(v is not None for v in (to, cc, bcc, subject)):
                raise core.OpsError("a reply goes to the sender of the message it answers, with its subject: give only the message and the body", 2)
            entries = _entries(ctx, message, account, channel, sender, reply=True)
            if len(entries) != 1:
                raise core.OpsError("a reply answers one message: name one reference", 2)
            return {"reply": entries[0], "body": body}
        if to is None or subject is None:
            raise core.OpsError("a new draft needs --to, --subject and --body (or --message and --body for a reply)", 2)
        return {"to": _addresses(to, "to"), "cc": _addresses(cc, "cc"), "bcc": _addresses(bcc, "bcc"), "subject": subject, "body": body}

    return _start(project, "draft", "draft", account, make, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
