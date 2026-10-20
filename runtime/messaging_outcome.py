#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a messaging app is told when an effect it approved has run (package LIVE-2): the outcome in plain words, not only "Approved #3."

The approval of an effect from a card runs the effect inside the approving call (ops_step_effects.approve): when the call returns, the write has landed, so the
bridge says what was done in the same job and the same chat. `sentence(item, result, cfg)` reads the decision (its card lines, which the person saw when they
approved) and what the effect module recorded (`result`: closed words, counts and the service's ids, never a name or an address) and returns one sentence of the
phrase table's family OUT_ in the project's language; the title and the moment of a new or changed event are said only when the card showed them (they are not
among the private lines of phrases.CARD_PRIVATE), and nothing else of the person's mail, files or events is. A decision of another kind, or a result it cannot read,
gets OUT_DONE. A failed approval is not here: its sentence is the operations layer's own (the bridge sends it and draws the card again).

There is no queue between the approval and the write today, so no "I will tell you when it is done" is promised. If a kind of effect ever runs later, it adds its own
sentence and a way to send the outcome when it lands; until then a result that is not a finished write is told as OUT_DONE would claim too much, so it is told as
the plain approval (APPROVED).

  sentence(item, result, cfg)   the outcome sentence, or None when the result is not one this module can say (the caller says APPROVED)

Standard library only. Runs on Python 3.9: python3 runtime/messaging_outcome.py --help
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402  (the same folder: the sentences, in the project's language)

CALENDAR_SERVICE = {"google": "OUT_CAL_GOOGLE", "microsoft": "OUT_CAL_MICROSOFT"}
ACCOUNT_SERVICE = {"google": "OUT_ACCT_GOOGLE", "microsoft": "OUT_ACCT_MICROSOFT"}
BOX = {"archive": "OUT_BOX_ARCHIVE", "move": "OUT_BOX_MOVE", "trash": "OUT_BOX_TRASH", "draft": "OUT_BOX_DRAFT"}
FILE = {"create": "OUT_FILE_CREATE", "replace": "OUT_FILE_REPLACE", "save": "OUT_FILE_SAVE"}


def _service(table: dict, account, cfg) -> str:
    key = table.get(account)
    return phrases.text(key, cfg) if key else ""


def _card_fields(item: dict) -> dict:
    """The fields of the card lines the person saw that this module may say: the title and the moment of an event (never a line of phrases.CARD_PRIVATE)."""
    payload = item.get("payload") if isinstance(item, dict) else None
    card = payload.get("card") if isinstance(payload, dict) else None
    if not phrases.card_valid(card):
        return {}
    shown = phrases.card_without_private(card)
    out = {}
    for key, fields in shown:
        if key == "CARD_CAL_TITLE":
            out["title"] = fields.get("title")
        elif key == "CARD_CAL_WHEN":
            out["when"] = fields.get("when")
    return out


def sentence(item, result, cfg=None):
    """The outcome of an approved effect in the project's language, or None (see the module's text). Dates are said in the language (phrases.localize_dates) by the
    bridge's send point, like every other text."""
    if not isinstance(item, dict) or not isinstance(result, dict):
        return None
    word = item.get("effect_word")
    if result.get("replayed") is True:
        return phrases.text("OUT_REPLAYED", cfg)
    if word == "calendar" and result.get("done") is True:
        operation = result.get("operation")
        service = _service(CALENDAR_SERVICE, result.get("account"), cfg)
        if operation == "cancel":
            return phrases.text("OUT_CAL_CANCEL", cfg, service=service)
        shown = _card_fields(item)
        key = "OUT_CAL_CREATE" if operation == "create" else "OUT_CAL_CHANGE" if operation == "change" else None
        if key is None:
            return None
        if shown.get("title") and shown.get("when"):
            return phrases.text(key, cfg, title=shown["title"], when=shown["when"], service=service)
        return phrases.text(key + "_BARE", cfg, service=service)
    if word == "mailbox" and result.get("done") is True:
        action = result.get("action")
        if action == "mark":
            key = "OUT_BOX_READ" if result.get("state") == "read" else "OUT_BOX_UNREAD"
        else:
            key = BOX.get(action)
        if key is None:
            return None
        return phrases.text(key, cfg, n=result.get("count") or 1)
    if word == "files" and result.get("written") is True:
        key = FILE.get(result.get("operation"))
        return phrases.text(key, cfg, service=_service(ACCOUNT_SERVICE, result.get("account"), cfg)) if key else None
    if word in ("send", "send-own") and result.get("sent") is True:
        return phrases.text("OUT_MAIL_REPLIED" if result.get("reply") is True else "OUT_MAIL_SENT", cfg)
    return None


if __name__ == "__main__":
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(__doc__.strip())
        sys.exit(0)
    print(__doc__.strip(), file=sys.stderr)
    sys.exit(2)
