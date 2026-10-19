#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect, as the channel policy sees it (package POL-1): which word an `effect` decision carries, whether the whole of it can be on a
messaging card, and whether a channel outside the terminal and the page may approve it. A part of the operations layer that ops.py calls
from `approve` and `pending`; it reads the effect document by the decision's own hash and nothing else.

  effect_facts(ctx, item)                   {"word", "on_cards"} of an `effect` decision
  effect_kind(facts)                        the kind the policy is asked about: `effect:<word>`, or `effect` when the word is unknown
  effect_refusal(ctx, item, channel, facts, sender)  the sentence that refuses an effect to a channel outside operations.EFFECT_CHANNELS, or None
                                            (for a messaging app, the grant is asked of the sender's profile: POL-2; and an effect that saves a file a sender
                                            sent is approved only by that sender: the kind's `held_attachment`, package W4a)

The word is the `effect` key of the effect document (effects.KINDS), read only when the file's bytes have the hash of the decision
(effects.read_document: a file changed since the gate is not read), from the file the gate path recorded in the payload or the file of the
step path (ops_step_effects.effect_dir). Any failure is "no word" and `on_cards` False: the policy then asks about `effect` with no word,
which only the terminal, the page and its umbrella cover, and an effect that cannot be shown whole is never approvable from a card. The kind's
own `on_cards(doc)` (runtime/effect_send.py: False with an attachment; runtime/effect_publish.py: False with an image) is the one source of
"the whole of it fits on a card"; a kind without one is on cards.

It is a sibling of runtime/ops.py. The names every module of the layer shares are read as `core.<name>`. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attachments as att  # noqa: E402
import effects  # noqa: E402
import item_refs  # noqa: E402
import operations  # noqa: E402
import phrases  # noqa: E402
import steps  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_step_effects  # noqa: E402

NO_WORD = {"word": None, "on_cards": False}   # what an effect that cannot be read is: no word, and not on a card


def effect_document(ctx: dict, item: dict):
    """The effect document of an `effect` decision, read by the decision's own hash, or None."""
    sha = item.get("payload_sha256")
    payload = item.get("payload") or {}
    path = payload.get("effect_file") if isinstance(payload, dict) else None
    try:
        if not isinstance(path, str) or not path:
            found = ops_step_effects.step_effect_of(ctx, item)
            if found is None:
                return None
            path = os.path.join(ops_step_effects.effect_dir(ctx["cfg"], found[0]["id"], int(payload.get("cycle", 0))), effects.EFFECT_FILE)
        doc = effects.read_document(path, sha)
    except (effects.EffectError, core.OpsError, OSError, ValueError, TypeError, KeyError):
        return None
    return doc if isinstance(doc, dict) else None


def private_view(ctx: dict, item: dict, channel, sender=None) -> dict:
    """The decision as `channel` may read it: an `effect` whose card has lines that show the current text of something the person owns (phrases.CARD_PRIVATE) is
    shown to the MCP mode, and to a messaging reader who does not hold the group ask-mail, without those lines (the body and the card's lines both, and a note
    that some text is not shown). Anyone else, and any decision without such a line, gets it as it is, except that the MCP mode and a messaging reader other than the sender who asked never read `result.asker` (_without_asker). The stored decision, its hash and what a card is drawn
    from are untouched: this is a view."""
    if item.get("kind") != "effect" or channel not in ("mcp", "messaging"):
        return item
    item = _without_asker(item, channel, sender)
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    card = payload.get("card")
    reader = item_refs.may_read(ctx, channel, sender)
    if not phrases.card_valid(card):
        if reader or effect_facts(ctx, item).get("word") not in operations.ACCOUNT_APPROVAL_WORDS:
            return item
        # An account write whose card cannot be read as a card (a key outside the table, a field that is no text) is shown to no one who may not read the person's mail:
        # what it holds is unknown, so it is private (fail closed). Its body, its card and the record of its execution go.
        return {**item, "body": phrases.en("CARD_HIDDEN_NOTE_WHOLE"), "payload": {key: value for key, value in payload.items() if key not in ("card", "result")}}
    hidden = set() if reader else set(phrases.CARD_PRIVATE)
    if not reader and not _owns_held_file(ctx, item, channel, sender):
        hidden |= set(phrases.CARD_PRIVATE_OWNER)      # the name of a file a sender sent is the sender's (and a reader of the person's own items')
    cut = [line for line in card if line[0] in hidden]
    # A reader who cannot approve this card is not offered the line that says how: the MCP mode never approves, and a messaging reader approves only with the grant of the
    # word and a card shown whole.
    approvable = channel == "messaging" and not cut and operations.permitted("approve", channel, ctx["cfg"]["channels"], effect_kind(effect_facts(ctx, item)), sender)
    kept = [line for line in card if line not in cut and (approvable or not line[0].endswith("_APPROVE"))]
    if len(kept) == len(card):
        return item
    if not cut:
        return {**item, "body": phrases.card_text(kept), "payload": {**payload, "card": kept}}
    # The card's lines go, and so does the record of the execution (`result`): a reader who may not see the text of the card must not see it by way of the outcome.
    shown = {key: value for key, value in payload.items() if key != "result"}
    note = phrases.hidden_note_key(card, [line for line in card if line not in cut])
    return {**item, "body": phrases.card_text(kept) + "\n" + phrases.en(note), "payload": {**shown, "card": kept}}


def task_view(ctx: dict, row: dict, channel, sender=None) -> dict:
    """The task row as `channel` may read it. The row of a step task that writes to the person's own accounts carries the request itself (`step_args`: a title,
    notes, a file's name and text, a mail address, a subject, who asked) and the engine's state (`step_state`, whose failure sentence may quote a name), and its
    `note` the same sentence. The MCP mode, and a messaging reader who does not hold the group ask-mail, get the arguments reduced to the closed ones
    (steps.public_args; none for an e-mail from the person's own account), the failure reduced to its code, its step and its field, and the note to the step, the
    code and the field. The terminal, the page, the conversation and a reader of mail get the row as it is. Any other task is returned as it is."""
    kind = row.get("step_kind")
    if channel not in ("mcp", "messaging") or not steps.is_account_step(kind, row.get("step_args")) or item_refs.may_read(ctx, channel, sender):
        return row
    state = row.get("step_state") if isinstance(row.get("step_state"), dict) else None
    if state is not None and isinstance(state.get("failure"), dict):
        state = {**state, "failure": {key: value for key, value in state["failure"].items() if key in ("step", "code", "field", "provider", "at")}}
    note = row.get("note")
    return {**row, "step_args": steps.public_args(row.get("step_args"), kind), "step_state": state,
            "note": note.partition(" -- ")[0] if isinstance(note, str) else note}


def _without_asker(item: dict, channel, sender) -> dict:
    """The decision without `result.asker` (the sender key of the messaging sender who asked for a calendar write, W1) unless the reader is that sender. Always, also for
    a reader who may read the person's own mail and calendar: who asked is another person's account, not the person's calendar."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    result = payload.get("result")
    if not isinstance(result, dict) or "asker" not in result:
        return item
    asker = ops_actor.split(result["asker"])
    if channel == "messaging" and asker != ("", "") and asker == ops_actor.split(sender):
        return item
    return {**item, "payload": {**payload, "result": {key: value for key, value in result.items() if key != "asker"}}}


def _owns_held_file(ctx: dict, item: dict, channel, sender) -> bool:
    """Whether `sender`, on a messaging app, is the one who sent the held file the effect saves (W4a). False for any other channel, for a sender the store does not
    know as that file's, and when the effect saves no held file."""
    if channel != "messaging" or not sender:
        return False
    key = held_file_sender(ctx, item)
    return key is not None and ops_actor.split(key) == ops_actor.split(sender)


def save_facts(ctx: dict, item: dict, reader=None) -> dict:
    """What a card needs to know of an effect that saves a held file (W4a, Q9), as booleans: {"effect_sender_only": True} when the effect saves a file a sender
    sent (only that sender approves it), and, when `reader` (a messaging sender key) is named, {"reader_sent_file": whether the reader is that sender}. {} for
    any other effect. The sender's account stays in the store: it is compared here and never returned."""
    doc = effect_document(ctx, item)
    try:
        held = effects.module_for("files").held_attachment(doc) if isinstance(doc, dict) and doc.get("effect") == "files" else None
    except effects.EffectError:
        held = None
    if held is None:
        return {}
    found = {"effect_sender_only": True}
    if reader:
        sender = held_file_sender(ctx, item)
        found["reader_sent_file"] = sender is not None and ops_actor.split(sender) == ops_actor.split(reader)
    return found


def held_file_sender(ctx: dict, item: dict):
    """`<platform>:<sender id>` of the one who sent the held file an effect saves, or None (the effect saves no held file, or the store does not know it)."""
    doc = effect_document(ctx, item)
    try:
        number = effects.module_for("files").held_attachment(doc) if isinstance(doc, dict) and doc.get("effect") == "files" else None
        if number is None:
            return None
        row = ctx["store"].attachment_get(ctx["conn"], number)
        return f"{row['platform']}:{row['sender']}"
    except (effects.EffectError, ctx["store"].StoreError, TypeError, ValueError, KeyError):
        return None


def effect_facts(ctx: dict, item: dict) -> dict:
    """{"word": the word the policy is asked about or None, ("effect": the effect's own word, only when it is not the same), "on_cards": whether the whole effect can be on a messaging card} of an
    `effect` decision. The two words differ for a kind that has a grant of its own for a part of its documents (`approval_word(doc)` of the kind: an e-mail from the
    person's own account is `send-own`, so that the grant of the outbox's `send` does not cover it)."""
    doc = effect_document(ctx, item)
    effect = doc.get("effect") if doc else None
    if not isinstance(effect, str) or effect not in effects.KINDS:
        return dict(NO_WORD)
    word = effect
    try:
        module = effects.module_for(effect)
        on_cards = getattr(module, "on_cards", None)
        whole = True if on_cards is None else bool(on_cards(doc))
        named = getattr(module, "approval_word", None)
        if named is not None:
            word = named(doc)
            if word not in operations.EFFECT_APPROVAL_WORDS:
                return dict(NO_WORD)
    except Exception:   # a kind that fails to answer is not on a card: the check fails closed
        whole = False
    return {"word": word, "on_cards": whole, **({"effect": effect} if effect != word else {})}      # `effect` only when the policy's word is another than the effect's own


def effect_kind(facts) -> str:
    """The kind of `approve` the policy is asked about for this effect."""
    word = (facts or {}).get("word")
    return "effect:" + word if word else "effect"


def effect_refusal(ctx: dict, item: dict, channel, facts: dict, sender=None):
    """The sentence that refuses an `effect` to a channel outside operations.EFFECT_CHANNELS, or None when the project's accepted policy
    grants that channel this effect's word and the whole effect fits on a card. Fails closed: no channel, the conversation and the MCP mode
    are never granted (operations.policy_allows). The hash is checked by the caller (ops._approve_effect) and by the bridge's card."""
    if channel in operations.EFFECT_CHANNELS:
        return None
    command = core._command("approve", ctx["cfg"]["project"], pending_id=item["id"], sha256="<hash>")
    kind = effect_kind(facts)
    if not operations.permitted("approve", channel or "", ctx["cfg"]["channels"], kind, sender):
        group = "approve-effect-" + facts["word"] if facts.get("word") in operations.EFFECT_APPROVAL_WORDS else None
        return ("an effect is approved in the terminal, with its hash: " + command
                + (f" (or on the page; a messaging app approves it only when the project's configuration grants it {group})" if group else ""))
    if not facts.get("on_cards"):
        return ("this effect carries more than a card can show (the hash covers something the card does not carry: a file, an image, every row of "
                "a table, or the code of a change), so it is not approved from a card: approve it in the terminal or on the page, with its hash: "
                + command)
    if has_private_lines(item, facts.get("word") in operations.ACCOUNT_APPROVAL_WORDS) and not item_refs.may_read(ctx, channel, sender):
        return ("this card has lines that show the person's own e-mail, calendar or files, and a messaging app draws them only for a sender who holds the group "
                f"{phrases.CARD_PRIVATE_GROUP}, so this card is not whole for you and is not approved from here: approve it in the terminal or on the page, with its hash: " + command)
    return _sender_problem(ctx, item, facts, sender)


def has_private_lines(item: dict, account_write: bool = False) -> bool:
    """Whether the stored card of an effect has a line of phrases.CARD_PRIVATE: the lines a reader who does not hold the group ask-mail is not shown (private_view and
    the messaging card both leave them out). Read from the decision's own card, at the operations layer, so that the approval of a card that was not whole for the
    approver is refused here too, whatever the bridge drew. A decision with no well-formed card has none, except an account write (`account_write`: the effect's word is
    one of operations.ACCOUNT_APPROVAL_WORDS), whose card that cannot be read as a card is unknown and so private (fail closed)."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    card = payload.get("card")
    if not phrases.card_valid(card):
        return bool(account_write)
    return any(line[0] in phrases.CARD_PRIVATE for line in card)


def _sender_problem(ctx: dict, item: dict, facts: dict, sender):
    """The sentence that refuses the approval of an effect that writes a file a sender sent (a kind that exposes `held_attachment(doc)`, package W4a, Q9) to
    anyone but the sender who sent it, or None. The sender's account is in the store alone (limit L48): the row of the held file is read now, and a file that
    is gone, or is another sender's, is answered as one that does not exist, so that the answer tells nothing of it. Fails closed."""
    word = (facts or {}).get("word")
    if not word:
        return None
    try:
        asked = getattr(effects.module_for(word), "held_attachment", None)
    except effects.EffectError:
        return None
    if asked is None:
        return None
    doc = effect_document(ctx, item)
    number = asked(doc) if doc else None
    if number is None:
        return None
    try:
        row = ctx["store"].attachment_get(ctx["conn"], number)
        platform, ident = ops_actor.split(sender)
        if row["status"] == "held" and (row["platform"], row["sender"]) == (platform, ident):
            return None
    except (ctx["store"].StoreError, TypeError, ValueError, KeyError):
        pass
    return att.NO_SUCH.format(n=number)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
