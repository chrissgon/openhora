#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Change a waiting card by words (slice S13): the calls the messaging bridge makes, and nothing that sends or writes.

The maintainer's rule (2026-10-22): "Caso eu queira ajustar alguma informacao antes de enviar, deve ser possível" and "Deveria sempre poder editar alguma informacao de algum card".
A plain line sent right after a card (or as a reply to it) that changes a word of what the card shows replaces the card with a new one; the old card is ended and can never be
approved. The bridge decides which card a line may be about (runtime/messaging_bridge.py `revise_line`); this file decides what the line is for that card.

  card_revise_check(project, pending_id, sha256, text, channel, sender)   None (the line is not about this card: it goes on as it always did), "mail" (a new e-mail card the model
                                                                          rewrites), "event" (an event card changed by the interpreter's verified decision) or "sentence" (a card
                                                                          of a write that cannot be changed by words yet, and a line that asks for a change: one sentence, RV_NOT_REVISABLE).
                                                                          Calls no model and changes nothing.
  card_revise(project, pending_id, sha256, text, channel, sender)         {"say": a sentence, "resend": the id of the new card or None} or {"pass": True} (the line is not a change
                                                                          of this card: the bridge goes on with it). Mail: runtime/mail_revise.py (one call to the model, validated
                                                                          by code); event: runtime/ops_event_revise.py (one interpreter call, the verified spans). Then the family
                                                                          opens the new card as it opens any card, and the old card is ended as rejected with a note that says it
                                                                          was replaced, so its hash is never approvable again. Nothing is sent, written or approved here.
  decided(sender, line)                                                   the interpreter's decision made for this line while it was checked as a change of a card and found to be
                                                                          something else, once (so the line is not read by the model twice), or None

A line is a change of a card only when ALL of these hold: the channel is a messaging app and the sender holds the group `interpret` with the newest entry of
runtime/interpreter_enable.json in force (a mail card also needs the entry to pin this checkout's revise prompt); the sender may prepare the same kind of card and may reject one; the
line is one line of at most INSTRUCTION_MAX characters, not a command, not an approve or reject word, not a greeting or a question about the state, and, for a mail card, not a
request code recognises (a tier-1 form, a write in words, the answer to the sender's draft; for an event card the write form of a change of an event is the change itself); the card
is an OPEN effect decision whose content hash is the `sha256` the bridge gives (the hash of the card the person saw).

The change (limit L55, principle 11: an effect only after the approval of its exact content). Recipients and the account of a mail card, and everything of an event card the line does not
name, are copied by code from the old card's document; the new card is checked equal to it in everything but the change before the old one is ended. An instruction that asks to
change who receives an e-mail gets one sentence and no new card (the person asks for a new e-mail). Any failure leaves the old card open and untouched and is one plain sentence.

Privacy (limit L63): nothing is logged, printed or stored here but the one decision in memory for the length of RETAIN seconds; the calls are counted in the interpreter's limits.

A sibling of runtime/ops.py, which exposes the three names. Standard library only. Runs on Python 3.9: python3 runtime/ops_card_revise.py --help
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import card_words  # noqa: E402
import greeting  # noqa: E402
import mail_revise  # noqa: E402
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import phrases  # noqa: E402

CHANNEL = "messaging"
OPERATION = {"send": "mail-send", "draft": "mail-draft"}
NOTE = "replaced by a revised card"
RETAIN = 60.0                 # seconds the interpreter's decision for a line that was not a change of a card is kept for the turn that follows
clock = time.monotonic        # a test replaces it
_lock = threading.Lock()
_decided = {}                 # sender -> (line, decision, time): memory only, once


def remember(sender, line: str, decision: dict) -> None:
    with _lock:
        _decided[sender] = (" ".join(line.split()), decision, clock())


def decided(sender, line: str):
    """The decision `remember` kept for this very line of this sender, once, or None."""
    with _lock:
        got = _decided.pop(sender, None)
    return got[1] if got and got[0] == " ".join(line.split()) and clock() - got[2] < RETAIN else None


def forget_all() -> None:
    with _lock:
        _decided.clear()


def _ops():
    return importlib.import_module("ops")


def _recognised(ctx: dict, line: str, sender) -> bool:
    """Whether code takes the line as something of its own (see the module's text): then it is not a change of a card."""
    natural_writes = importlib.import_module("natural_writes")
    ops_natural = importlib.import_module("ops_natural")
    ops_say = importlib.import_module("ops_say")
    return (card_words.card_word(line) is not None or natural_writes.candidate(line) is not None or ops_natural.recognises(ctx, line, CHANNEL, sender)
            or ops_say.state_question(line) or greeting.is_greeting(line, helps=True))


def _is_event_change(line: str) -> bool:
    """Whether code reads the line as the write form of a change of an event ("muda para as 10h"): for an event card that form is the change itself."""
    found = importlib.import_module("natural_writes").candidate(line)
    return bool(found) and found.get("op") == "event-change"


def entry_of(ctx: dict, channel, sender, revise: bool):
    """The entry of interpreter_enable.json in force (that pins the revise prompt when `revise`), or None; None too unless the sender is read by the interpreter."""
    interpret = importlib.import_module("ops_interpret")
    enable = importlib.import_module("interpreter_enable")
    if not interpret.enabled(ctx, channel, sender):
        return None
    got = (enable.revise_active if revise else enable.active)(interpret._tag(ctx["cfg"]))
    return got["entry"] if got else None


def _shape(ctx: dict, item: dict) -> tuple:
    """(kind, document, mail shape): "mail" with the shape of a new e-mail this path can reproduce, "event" for the card of a new event or of a change of one found in a snapshot, else
    "sentence" for any other effect card of a write to the person's accounts."""
    grants = importlib.import_module("ops_grants")
    doc = grants.effect_document(ctx, item)
    mail = mail_revise.shape(doc)
    if mail is not None:
        return "mail", doc, mail
    if isinstance(doc, dict) and doc.get("effect") == "calendar" and isinstance(doc.get("event"), dict):
        if doc.get("operation") == "create" or (doc.get("operation") == "change" and isinstance(doc.get("reference"), dict)):
            return "event", doc, None
    return "sentence", doc, None


def _taken(ctx: dict, pending_id, sha256, text, channel, sender):
    """(kind, entry, instruction, document, mail shape) when the line is about the card, else None (see the module's text)."""
    if channel != CHANNEL or not isinstance(text, str) or text.lstrip().startswith("/") or not isinstance(sha256, str):
        return None
    line = mail_revise.clean(text)
    if line is None or card_words.card_word(line) is not None or importlib.import_module("ops_say").state_question(line) or greeting.is_greeting(line, helps=True):
        return None
    try:
        item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    except core.OpsError:
        return None
    if item.get("kind") != "effect" or item.get("status", "open") != "open" or item.get("payload_sha256") != sha256:
        return None
    kind, doc, mail = _shape(ctx, item)
    if not isinstance(doc, dict):
        return None
    if kind == "sentence":
        return ("sentence", None, line, doc, None) if mail_revise.has_change_word(line) and not _recognised(ctx, line, sender) else None
    if _recognised(ctx, line, sender) and not (kind == "event" and _is_event_change(line)):
        return None
    entry = entry_of(ctx, channel, sender, revise=kind == "mail")
    if entry is None:
        return None
    try:
        ops_actor.guard(ctx, "reject", channel, sender)
    except core.OpsError:
        return None
    wanted = OPERATION[mail["kind"]] if kind == "mail" else "event-" + ("create" if doc["operation"] == "create" else "change")
    if operations.refusal(wanted, CHANNEL, ctx["cfg"]["channels"], sender=sender):
        return None
    return kind, entry, line, doc, mail


def card_revise_check(project: str, pending_id: int, sha256: str, text: str, channel: str = CHANNEL, sender=None):
    """See the module's text. Calls no model."""
    ops_actor.require(channel, sender)
    ctx = core.context(project)
    taken = _taken(ctx, pending_id, sha256, text, channel, sender)
    return taken[0] if taken else None


def say(ctx: dict, key: str) -> dict:
    return {"say": phrases.text(key, ctx["cfg"]), "resend": None}


def drop(project: str, pending_id, channel, sender) -> None:
    """End a card the revision opened and cannot use (a card is never left to be approved by mistake). Never raises."""
    try:
        _ops().reject(project, pending_id, note=NOTE, channel=channel, sender=sender)
    except Exception:      # noqa: BLE001 - nothing of the fault is kept
        pass


def replace(project: str, ctx: dict, old_id, new_id, channel, sender) -> dict:
    """End the old card and answer with the new one; when the old one cannot be ended (it was decided meanwhile) the new one is ended and the failure said."""
    try:
        _ops().reject(project, old_id, note=NOTE, channel=channel, sender=sender)
    except core.OpsError:
        drop(project, new_id, channel, sender)
        return say(ctx, "RV_FAILED")
    return {"say": phrases.text("RV_DONE", ctx["cfg"]), "resend": new_id}


def _mail(project: str, ctx: dict, pending_id, entry, line, mail, channel, sender) -> dict:
    if mail_revise.asks_recipients(line):
        # an address in a line that asks for no change and names no recipient is a new request in free words ("send an e-mail to ..."): it goes on to the turn that reads it
        return {"pass": True} if not mail_revise.recipient_words(line) and not mail_revise.has_change_word(line) else say(ctx, "RV_RECIPIENTS")
    interpret = importlib.import_module("ops_interpret")
    if not interpret._admit(ctx, sender):
        return say(ctx, "RV_FAILED")
    revised, ok = None, False
    try:
        got = mail_revise.call(entry, mail_revise.prompt_template(), mail_revise.message(interpret._tag(ctx["cfg"]), mail["subject"], mail["body"], line))
        ok = bool(got.get("ok"))
        if ok:
            revised = mail_revise.accept(got.get("text"), mail["to"], mail["subject"], mail["body"], line)
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the person's words
        ok, revised = False, None
    interpret._record(ok)
    if revised is not None and revised.get("same"):
        # a line with no quoted text and no word that asks for a change, after which the model changed nothing, was not meant as a change: it goes on
        return {"pass": True} if not mail_revise.literals(line) and not mail_revise.has_change_word(line) else say(ctx, "RV_FAILED")
    if revised is None:
        return say(ctx, "RV_FAILED")
    seed = {"op": OPERATION[mail["kind"]], "slots": {"account": mail["account"], "to": list(mail["to"]), "subject": revised["subject"], "body": revised["body"]}}
    try:
        opened = _ops().natural_write(project, "", channel=channel, sender=sender, seed=seed)
    except core.OpsError:
        opened = {}
    new_id = opened.get("resend")
    if not isinstance(new_id, int) or new_id == pending_id:
        _ops().natural_forget(project, sender, channel)
        return say(ctx, "RV_FAILED")
    grants = importlib.import_module("ops_grants")
    try:
        made = core._stored(ctx, ctx["store"].pending_get, new_id)
        found = mail_revise.shape(grants.effect_document(ctx, made))
    except core.OpsError:
        found, made = None, {}
    same = (found is not None and made.get("kind") == "effect" and made.get("status", "open") == "open"
            and (found["kind"], found["account"], found["address"], found["to"]) == (mail["kind"], mail["account"], mail["address"], mail["to"])
            and (found["subject"], found["body"].strip()) == (revised["subject"], revised["body"].strip()))
    if not same:
        drop(project, new_id, channel, sender)
        return say(ctx, "RV_FAILED")
    return replace(project, ctx, pending_id, new_id, channel, sender)


def card_revise(project: str, pending_id: int, sha256: str, text: str, channel: str = CHANNEL, sender=None) -> dict:
    """The change (see the module's text)."""
    ops_actor.require(channel, sender)
    ctx = core.context(project)
    taken = _taken(ctx, pending_id, sha256, text, channel, sender)
    if taken is None:
        return {"pass": True}
    kind, entry, line, doc, mail = taken
    if kind == "sentence":
        return say(ctx, "RV_NOT_REVISABLE")
    if kind == "mail":
        return _mail(project, ctx, pending_id, entry, line, mail, channel, sender)
    return importlib.import_module("ops_event_revise").revise(project, ctx, pending_id, entry, line, doc, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
