#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The answers to a question the interpreter read (ANY-QUESTION): a card's own lines, and how the person's recent cards ended.

The interpreter's decision `question` (runtime/interpreter.py) is answered by code, never by the model: `runtime/ops_interpret.py` (`_question`) and the card call (`runtime/ops_event_revise.py`)
read these two answers and nothing else of this file. Neither changes anything (limit L55): they read a decision as the sender may read it (`ops_grants.private_view`: a private line the sender may not
see is cut, as on the card they were shown), they write no decision, approve nothing, reject nothing and run nothing, and the card they are about is sent again by the caller, unchanged.

  card_lines(card, field)                     the lines of a card a field asks about (the card's first line for `approve`); [] when the card has none (pure)
  card_answer(ctx, pending_id, field, sender) the sentence that says them, QUESTION_CARD_NONE when the card does not hold the field, None when the card is gone or is not an open effect
  family_of(card), state_of(row)              the family of a card (event, mail, file, todo) and how a decision ended (open, approved, rejected, replaced, cancelled) (pure)
  question_done(rows, op, now)                the cards of the last DONE_DAYS days of the op's family (any family when op is None), newest first, at most DONE_MAX (pure)
  done_reply(ctx, op, sender, extras, now)    the list as a sentence; it reads the person's cards, so the caller asks first ("Posso?", limit L65) and the conversation keeps a neutral word

"approved" says the decision was approved; whether its write landed is not read here. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural  # noqa: E402
import ops_core as core  # noqa: E402
import ops_grants  # noqa: E402
import phrases  # noqa: E402

REPLACED_NOTE = "replaced by a revised card"      # ops_card_revise.NOTE (runtime/ops_card_revise.py:83), copied: importing it would close a cycle; a test holds the two equal
FIELD_KEYS = {
    "title": ("CARD_CAL_TITLE", "CARD_CAL_AFTER_TITLE", "CARD_CAL_KEPT_TITLE", "CARD_CAL_DROP_TITLE", "CARD_TODO_TITLE"),
    "when": ("CARD_CAL_WHEN", "CARD_CAL_AFTER_WHEN", "CARD_CAL_KEPT_WHEN", "CARD_CAL_SERIES_SINCE"),
    "place": ("CARD_CAL_WHERE", "CARD_CAL_AFTER_WHERE", "CARD_CAL_KEPT_WHERE", "CARD_CAL_DROP_WHERE"),
    "to": ("CARD_MAIL_TO", "CARD_MAIL_CC", "CARD_MAIL_BCC", "CARD_MAIL_REPLY_TO", "CARD_MAIL_REPLY_TO_AT", "CARD_BOX_DRAFT_TO", "CARD_BOX_DRAFT_REPLY_TO", "CARD_BOX_DRAFT_CC", "CARD_BOX_DRAFT_BCC"),
    "from": ("CARD_MAIL_FROM_ACCOUNT", "CARD_ACCOUNT"),
    "subject": ("CARD_MAIL_SUBJECT", "CARD_MAIL_SUBJECT_REPLY", "CARD_BOX_DRAFT_SUBJECT", "CARD_BOX_DRAFT_REPLY_SUBJECT"),
}
PHONE_HEAD = {"CARD_CAL_CHANGE": "PHONE_CAL_CHANGE"}      # the head line a phone shows in place of the card's (messaging_cards.PHONE_LINE); a test holds the pair equal
FAMILIES = {"event": ("CARD_CAL_",), "mail": ("CARD_MAIL_", "CARD_BOX_"), "file": ("CARD_FILE_",), "todo": ("CARD_TODO_",)}
DONE_DAYS, DONE_MAX = 7, 3
STATE_KEY = {"open": "DONE_STATE_OPEN", "approved": "DONE_STATE_APPROVED", "rejected": "DONE_STATE_REJECTED", "replaced": "DONE_STATE_REPLACED", "cancelled": "DONE_STATE_CANCELLED"}
STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"      # the store's `iso` (providers/store/sqlite.py:808-810)
TITLE_MAX = 80


def card_lines(card, field) -> list:
    """The lines of `card` a question about `field` asks for: for `approve` the card's first line (it says what approving does); for a field of FIELD_KEYS the lines whose key is one of its keys, in the
    card's order; [] for `other`, for anything else and for a card that holds none."""
    if not isinstance(card, (list, tuple)) or not card:
        return []
    if field == "approve":
        head = card[0]
        return [[PHONE_HEAD.get(head[0], head[0]), head[1]]]
    keys = FIELD_KEYS.get(field)
    if keys is None:
        return []
    return [line for line in card if line[0] in keys]


def card_answer(ctx: dict, pending_id, field, sender):
    """The sentence that says what the open effect card `pending_id` holds for `field`, as `sender` may read it (a private line the sender may not read is cut): QUESTION_CARD_SAYS, or
    QUESTION_CARD_APPROVE for `approve`; QUESTION_CARD_NONE when the card does not say that; None when the decision is gone or is not an open effect. Nothing is written."""
    cfg = ctx["cfg"]
    try:
        item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    except core.OpsError:
        return None
    if not isinstance(item, dict) or item.get("kind") != "effect" or item.get("status") != "open":
        return None
    view = ops_grants.private_view(ctx, item, "messaging", sender)
    payload = view.get("payload") if isinstance(view.get("payload"), dict) else {}
    card = payload.get("card")
    if not phrases.card_valid(card):
        return phrases.text("QUESTION_CARD_NONE", cfg)
    lines = card_lines(card, field)
    if not lines:
        return phrases.text("QUESTION_CARD_NONE", cfg)
    return phrases.localize_dates(phrases.text("QUESTION_CARD_APPROVE" if field == "approve" else "QUESTION_CARD_SAYS", cfg, lines=phrases.card_text(lines, cfg)), cfg)


def family_of(card):
    """The family of a card (a key of FAMILIES): the one whose prefix the card's first key that is not CARD_ACCOUNT starts with; None when there is none."""
    if not isinstance(card, (list, tuple)):
        return None
    for line in card:
        if not isinstance(line, (list, tuple)) or not line or not isinstance(line[0], str):
            continue
        if line[0] == "CARD_ACCOUNT":
            continue
        for name, prefixes in FAMILIES.items():
            if line[0].startswith(prefixes):
                return name
        return None
    return None


def state_of(row) -> str:
    """How a decision stands: open, approved, rejected, replaced (rejected by a revised card), or cancelled (anything else closed)."""
    status, resolution = row.get("status"), row.get("resolution")
    if status == "open":
        return "open"
    if status == "resolved" and resolution == "approved":
        return "approved"
    if status == "resolved" and resolution == "rejected":
        return "replaced" if row.get("answer") == REPLACED_NOTE else "rejected"
    return "cancelled"


def question_done(rows, op, now) -> list:
    """The cards of the last DONE_DAYS days before `now` (aware UTC), newest first, at most DONE_MAX: [{"pending_id", "state", "title"}] of the effect rows whose card is valid and of the op's family
    (any family when `op` is None). [] for an op that is not an act of a family listed here. A row whose `created_at` does not parse is skipped."""
    family = None
    if op is not None:
        if natural.class_of(op) != "E" or op.split("-", 1)[0] not in FAMILIES:
            return []
        family = op.split("-", 1)[0]
    found = []
    for row in rows:
        if not isinstance(row, dict) or row.get("kind") != "effect":
            continue
        payload = row.get("payload")
        card = payload.get("card") if isinstance(payload, dict) else None
        if not phrases.card_valid(card):
            continue
        kind = family_of(card)
        if kind is None or (family is not None and kind != family):
            continue
        try:
            made = datetime.datetime.strptime(row.get("created_at"), STAMP).replace(tzinfo=datetime.timezone.utc)
        except (TypeError, ValueError):
            continue
        if not datetime.timedelta(0) <= now - made <= datetime.timedelta(days=DONE_DAYS):
            continue
        found.append({"pending_id": row["id"], "state": state_of(row), "title": row.get("title")})
    found.sort(key=lambda entry: entry["pending_id"], reverse=True)
    return found[:DONE_MAX]


def done_reply(ctx: dict, op, sender, extras: dict, now=None) -> str:
    """The sentence that lists the person's latest cards of the op's family and how each ended, as `sender` may read them; the conversation keeps a neutral word (`extras["stored"]`). Nothing is written."""
    cfg = ctx["cfg"]
    rows = core._stored(ctx, ctx["store"].pending_list, "all")
    shown = [ops_grants.private_view(ctx, row, "messaging", sender) for row in rows]
    found = question_done(shown, op, now or datetime.datetime.now(datetime.timezone.utc))
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    if not found:
        return phrases.text("DONE_NONE", cfg)
    lines = [phrases.text("DONE_LINE", cfg, number=str(entry["pending_id"]), what=phrases.heading(" ".join(str(entry["title"] or "").split())[:TITLE_MAX], cfg), state=phrases.text(STATE_KEY[entry["state"]], cfg)) for entry in found]
    return phrases.text("DONE_HEAD", cfg) + "\n" + "\n".join(lines)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
