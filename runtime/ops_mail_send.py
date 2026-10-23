#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations that send an e-mail from the person's own Google or Microsoft account (package W2, SPEC-SECRETARY-WRITES 3.2): a new e-mail and a reply. Each one
PREPARES and nothing else: it checks its arguments, makes one request with one step task of the kind `send-email` (runtime/step_send_email.py), runs the preparation in
this process with no model, and stops at the card that asks the person to approve it (runtime/account_start.py). It returns {"request", "task", "pending", "word",
"on_cards"}; the messaging bridge then sends the decision's card as it sends every card and says `account_start.reply_text`. Nothing is sent here: the send is
runtime/effect_send.py `execute`, reached only by `approve` with the hash of the card (limit L55), through the mailer of the account (providers/mailer/gmail.py or
outlook.py) with the account's token (limit L59).

  mail_send(project, account, to, subject, text[, cc, bcc, attach])
        a new e-mail from the address of `accounts.<account>` of the project. `to`, `cc` and `bcc` are comma-separated plain addresses (at most 20 in all; no Bcc from
        a Google account in this version), `subject` one line, `body` the text, `attach` files under docs/ of the project (never on a messaging card, which cannot
        carry the file the hash covers)
  mail_reply(project, account, message, text)
        a reply to the message `message` names, `<source id>#<n>` (the n-th message of the newest snapshot of a registered mail source of that account). It goes to the
        SENDER of that message as the index of the snapshot recorded it, and to no one else (limit L60): not to an address inside the text, not to a `Reply-To`, which
        the card shows and does not use; there is no reply to all. The subject is `Re: ` and the subject the index kept; In-Reply-To, References and, for Gmail, the
        conversation come from the index. The reference is resolved here with the caller's rights first (a messaging sender needs the group `ask-mail` to name a
        snapshot of the mailbox), and again by the preparation.

Who may call what is the table of operations (runtime/operations.py: the group `mail-send`, in no default policy, never on the MCP mode) and, for a messaging sender,
runtime/account_start.py (the profile of THAT sender, read from the configuration loaded for this call). The words of the person reach a model nowhere on this path:
the card is made by code from the arguments.

Sibling of runtime/ops.py, which exposes the operations under their names. It reaches no operation of ops.py. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import account_start  # noqa: E402
import item_refs  # noqa: E402
import mail_refs  # noqa: E402
import ops_core as core  # noqa: E402
import sources  # noqa: E402

KIND = "send-email"


def _start(project, operation: str, title_key: str, account, args: dict, channel, sender) -> dict:
    """The one start of the family: the arguments the call gave (those that are not None), under the operation's name and the title of its card."""
    given = {k: v for k, v in args.items() if v is not None}
    return account_start.start(project, KIND, {"account": account, **given}, key_words=operation, title_key=title_key, account=account, channel=channel, sender=sender)


def mail_send(project: str, account: str, to: str, subject: str, text: str, cc: str | None = None, bcc: str | None = None, attach: list | None = None,
              channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare a new e-mail from the person's own account and stop at its card. `text` is the body (the name every operation of the table gives a text). See the
    module's text."""
    return _start(project, "mail-send", "TITLE_MAIL_SEND", account, {"to": to, "cc": cc, "bcc": bcc, "subject": subject, "body": text, "attach": attach or None},
                  channel, sender)


def mail_reply(project: str, account: str, message: str, text: str, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare a reply to a message of a mail snapshot and stop at its card. See the module's text."""
    ctx = core.context(project)
    account_start.check_channel(ctx, "mail-reply", channel, sender)      # who may ask at all, before anything of the mailbox is read
    try:
        found = item_refs.resolve(ctx, message, channel=channel, sender=sender, kinds=("mail",))      # may THIS caller name that message? the preparation reads it again
    except item_refs.ItemRefError as e:
        raise core.OpsError(mail_refs.ref_sentence(e.code, message), 1) from None
    except sources.SourcesError as e:
        raise core.OpsError(" ".join(str(e).split())[:200], 1) from None
    return _start(project, "mail-reply", "TITLE_MAIL_REPLY", account, {"reply": message, "reply_pin": mail_refs.pin_of(found), "body": text, "channel": channel if channel is not None else "terminal",
                              "sender": sender if channel == "messaging" else None}, channel, sender)      # who asked goes with the arguments, as the caller gave it


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
