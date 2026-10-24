#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The message a reply answers, from a reference into a snapshot (package W2, SPEC-SECRETARY-WRITES 3.2 and 3.4), and nothing that calls a provider.

`mail-reply` names the message by `<source id>#<n>`, which runtime/item_refs.py resolves through the INDEX of the snapshot (never through its text). This module
holds the two pure halves that both the operation (runtime/ops_mail_send.py, with the channel and the sender who asked) and the read-only seam of the step
(runtime/ops_step_seams.py, which asks again at the preparation) share:

  ref_sentence(code, reference)       the sentence, in English and from the phrase table, of every code an ItemRefError can carry (REF_PHRASES maps each one; a
                                      test holds the map equal to the codes the module raises). A caller's text is shown cleaned and cut, never used.
  reply_facts(found, account)         what the index recorded of the message answered, as the effect document keeps it: the address of its sender (the one
                                      recipient of the reply), another address it asked replies to go to (shown, never used), its subject as the index cleaned it,
                                      the time of its snapshot, the service's id of the message, its Message-ID, for Gmail its conversation and `received`, the moment
                                      it came as the index recorded it (null when the index has none: a snapshot made before the key). MailRefError,
                                      with the sentence, when the message is of another account, has no single sender address, or lacks what the reply needs.

External content is data: the index holds another person's addresses and subject in a closed shape (runtime/item_refs.py reads them back through it); an address
inside a message body is never read here, and a `Reply-To` is carried so that the card can show it, never to address anything (limit L60).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mail_address  # noqa: E402
import phrases  # noqa: E402
import send_document  # noqa: E402
import snapshot_text  # noqa: E402

ACCOUNT_OF = {mailer: account for account, mailer in send_document.ACCOUNTS.items()}      # a mail source's implementation (the index says it) -> the account
# Every code of item_refs.ItemRefError, and the phrase of the table that says it (both columns). The two codes of a `created:` reference name an event.
REF_PHRASES = {"malformed": "ACCT_MAIL_REF_MALFORMED", "zero": "ACCT_MAIL_REF_ZERO", "not_readable": "ACCT_MAIL_REF_NOT_READABLE", "past_end": "ACCT_MAIL_REF_PAST_END",
               "no_source": "ACCT_MAIL_REF_NO_SOURCE", "not_snapshot": "ACCT_MAIL_REF_NOT_SNAPSHOT", "wrong_kind": "ACCT_MAIL_REF_WRONG_KIND",
               "no_version": "ACCT_MAIL_REF_NO_VERSION", "stale": "ACCT_MAIL_REF_STALE", "no_index": "ACCT_MAIL_REF_NO_INDEX", "integrity": "ACCT_MAIL_REF_INTEGRITY",
               "created_unavailable": "ACCT_MAIL_REF_WRONG_KIND", "created_unknown": "ACCT_MAIL_REF_WRONG_KIND"}
REF_SHOWN = 60


class MailRefError(Exception):
    """A reference that cannot be answered. `sentence` is English, from the phrase table, and what the operation raises."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


def shown(reference) -> str:
    """A reference the caller wrote, as a sentence may echo it: one line, cut, no control character. It is never used for anything else."""
    return snapshot_text.one_line(str(reference), REF_SHOWN) or "(empty)"


def ref_sentence(code: str, reference) -> str:
    """The English sentence of an ItemRefError code for the reference the caller gave; an unknown code is read as an integrity problem (fails closed)."""
    key = REF_PHRASES.get(code, "ACCT_MAIL_REF_INTEGRITY")
    return phrases.en(key).format(ref=shown(reference))


def reply_facts(found: dict, account: str) -> dict:
    """What a reply needs of the message `found` names (item_refs.resolve's answer for a mail item). MailRefError when it cannot be answered from `account`."""
    entry, reference = found["entry"], f"{found['source']}#{found['n']}"
    if ACCOUNT_OF.get(found.get("implementation")) != account:
        raise MailRefError(phrases.en("ACCT_MAIL_OTHER_ACCOUNT").format(ref=shown(reference), account=account))
    try:      # the index keeps the address as the provider printed it; a document holds addresses in their normal form (a capital in a domain is the same address)
        sender = mail_address.normalize_address(entry.get("from_address"))
    except mail_address.AddressError:
        raise MailRefError(phrases.en("ACCT_MAIL_NO_SENDER")) from None
    message_id, provider_id, thread = entry.get("message_id"), entry.get("id"), entry.get("thread_id")
    repliable = (isinstance(message_id, str) and send_document.REFERENCE.fullmatch(message_id) is not None and "=?" not in message_id
                 and isinstance(provider_id, str) and send_document.PROVIDER_ID.fullmatch(provider_id) is not None
                 and (account != "google" or (isinstance(thread, str) and send_document.THREAD_ID.fullmatch(thread) is not None)))
    if not repliable:
        raise MailRefError(phrases.en("ACCT_MAIL_NOT_REPLIABLE"))
    try:
        other = mail_address.normalize_address(entry.get("reply_to_address")) if entry.get("reply_to_address") else None
    except mail_address.AddressError:
        other = None      # an address that cannot be shown in its normal form is not shown: it was never going to be used
    subject = entry.get("subject") or ""
    return {"ref": reference, "address": sender, "reply_to": other if other and mail_address.address_key(other) != mail_address.address_key(sender) else None,
            "subject": subject, "read_at": found["read_at"], "provider_id": provider_id, "message_id": message_id,
            "thread_id": thread if account == "google" else None, "received": entry.get("received")}


def pin_of(found: dict):
    """What identifies the message a reference named when the operation resolved it: the service's id and the Message-ID, as the index recorded them. The operation
    writes it into the step's arguments; the preparation refuses a reference that now names another message (a refreshed snapshot renumbers its items)."""
    entry = found["entry"]
    if not isinstance(entry.get("id"), str) or not isinstance(entry.get("message_id"), str):
        return None      # a message the index could not identify cannot be answered anyway: the preparation says so
    return {"id": entry["id"], "message_id": entry["message_id"]}


def pin_problem(pin, facts: dict):
    """The sentence that refuses a preparation whose message is not the one pinned, or None."""
    if pin is None:
        return None
    if not isinstance(pin, dict) or pin.get("id") != facts.get("provider_id") or pin.get("message_id") != facts.get("message_id"):
        return phrases.en("ACCT_MAIL_REPLY_MOVED").format(ref=shown(facts.get("ref")))
    return None


def reply_subject(subject: str) -> str:
    """The subject of the reply: `Re: ` and the subject as the index cleaned it, unless it already starts with `Re:` (any case), which is kept as it is."""
    return subject if subject[:3].lower() == "re:" else (f"Re: {subject}" if subject else "Re:")


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
