#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Change a waiting card by words (slice S13): the calls the messaging bridge makes, and nothing that sends or writes.

The maintainer's rule (2026-10-22): "Caso eu queira ajustar alguma informacao antes de enviar, deve ser possível" and "Deveria sempre poder editar alguma informacao de algum card".
A plain line sent right after a card (or as a reply to it) that changes a word of what the card shows replaces the card with a new one; the old card is ended and can never be
approved. The bridge decides which card a line may be about (runtime/messaging_bridge.py `revise_waiting`, called by the kind `decision-card-revise` of runtime/messaging_turn.py); this file decides what the line is for that card.

  card_revise_check(project, pending_id, sha256, text, channel, sender)   None (the line is not about this card: it goes on as it always did), "mail" (a new e-mail card the model
                                                                          rewrites), "event" (an event card changed by the interpreter's verified decision, the model seeing the card) or "sentence" (a card
                                                                          of a write that cannot be changed by words yet, and a line that asks for a change: one sentence, RV_NOT_REVISABLE)
                                                                          or "replaced" (a card this feature ended and a line that asks for a change of it).
                                                                          Calls no model and changes nothing.
  card_revise(project, pending_id, sha256, text, channel, sender)         {"say": a sentence, "resend": the id of the new card or None} or {"pass": True} (the line is not a change
                                                                          of this card: the bridge goes on with it). Mail: runtime/mail_revise.py (one call to the model, validated
                                                                          by code); event: runtime/ops_event_revise.py (one interpreter call with the card in view, runtime/event_card.py; the verified spans and parts). Then the family
                                                                          opens the new card as it opens any card, and the old card is ended as rejected with a note that says it
                                                                          was replaced, so its hash is never approvable again. Nothing is sent, written or approved here.
  decided(project, channel, sender, line)                                 the interpreter's decision made for this line while it was checked as a change of a card and found to be
                                                                          something else, once, for 60 seconds, for this project and sender (so the line is not read by the model
                                                                          twice), or None

A line is a change of a card only when ALL of these hold: the channel is a messaging app and the sender holds the group `interpret` with the newest entry of
runtime/interpreter_enable.json in force (a mail card also needs the entry to pin this checkout's revise prompt, an event card the entry to pin this checkout's event card text); the sender may prepare the same kind of card and may reject one; the
line is one line of at most INSTRUCTION_MAX characters, not a command, not an approve or reject word, not a greeting or a question about the state, and, for a mail card, not a
request code recognises (a tier-1 form, a write in words, the answer to the sender's draft; for an event card the write form of a change of an event is the change itself); the card
is an OPEN effect decision whose content hash is the `sha256` the bridge gives (the hash of the card the person saw).

For a mail card the model is called only when the line holds a word that asks for a change, a quoted text or a word that asks to change who receives the e-mail (limit L63): any other
line, "lista os emails" or "obrigado" or a thought, is not an instruction for the card, reaches no model here and goes on as it always did. For a line that names another event than the
card's ("muda o dentista para as 10h" on the card of "evento social") the event card is left alone and the line goes on.

The change (limit L55, principle 11: an effect only after the approval of its exact content). Recipients and the account of a mail card, and everything of an event card the line does not
name, are copied by code from the old card's document, and the new card is checked equal to it in everything but the change. Everything that can fail fails BEFORE the old card is touched
(a sentence, and the old card is sent once more so that it is the last message and a word still decides it); then the old card is ended and the new one opened and checked, so the worst
case is no open card, never two: a card decided meanwhile is told so, a new card that cannot be opened is told as "ask again". An instruction that asks to change who receives an e-mail gets
one sentence and no new card (the person asks for a new e-mail). A change asked of a card this feature replaced is told that the card was replaced (`card_revise_check` gives "replaced").

Privacy (limit L63): nothing is logged, printed or stored here but the one decision in memory for the length of RETAIN seconds; the calls are counted in the interpreter's limits.

A sibling of runtime/ops.py, which exposes the three names; it reaches `reject`, `natural_write` and `natural_forget` of ops.py through ops_facade.py, at call time. Standard library only. Runs on Python 3.9: python3 runtime/ops_card_revise.py --help
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
import interpreter_enable  # noqa: E402
import mail_revise  # noqa: E402
import natural  # noqa: E402
import natural_writes  # noqa: E402
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_facade  # noqa: E402
import ops_grants  # noqa: E402
import ops_interpret  # noqa: E402
import ops_natural  # noqa: E402
import ops_say  # noqa: E402
import phrases  # noqa: E402
import turn_gate  # noqa: E402

CHANNEL = "messaging"
OPERATION = {"send": "mail-send", "draft": "mail-draft"}
NOTE = "replaced by a revised card"
RETAIN = 60.0                 # seconds the interpreter's decision for a line that was not a change of a card is kept for the turn that follows
clock = time.monotonic        # a test replaces it
_lock = threading.Lock()
_decided = {}                 # (project, channel, sender) -> (line, decision, time): memory only, once


def _key(project, channel, sender) -> tuple:
    return os.path.realpath(str(project)), channel, sender


def remember(project, channel, sender, line: str, decision: dict) -> None:
    with _lock:
        _decided[_key(project, channel, sender)] = (" ".join(line.split()), decision, clock())


def decided(project, channel, sender, line: str):
    """The decision `remember` kept for this very line of this sender in this project, once (the entry is dropped when it is read, whatever it held), or None. An entry older
    than RETAIN seconds is never returned."""
    with _lock:
        got = _decided.pop(_key(project, channel, sender), None)
    return got[1] if got and got[0] == " ".join(line.split()) and clock() - got[2] < RETAIN else None


def forget_all() -> None:
    with _lock:
        _decided.clear()


def _recognised(ctx: dict, line: str, sender, event: bool = False) -> bool:
    """Whether code takes the line as something of its own (see the module's text): then it is not a change of a card. On the card of an event a reminder said with a bare time ("vai ate as 17h",
    "termina as 14h") is about the card: it reaches the model that sees the card."""
    # S41-11: the write families' claim (`natural_writes.candidate`) is gone from this test: a line the gate reads as a write by one of its steps ("Mude o titulo do evento para X") must stay the change of
    # the card that waits, and `ops_natural.recognises` now holds those private words. CANDIDATE-OUT: what is left to ask here is the code guard `turn_gate.new_request` (bare reading included, as the
    # old claim named it), which holds the reminders' and the closed forms' words; the interpreter's own word for a new request is not read here.
    new = turn_gate.new_request(line)
    return (card_words.card_shape(line) is not None or ops_natural.peek(ctx, line, CHANNEL, sender, claim=False) or (new is not None and not (event and new == "bare"))
            or ops_say.state_question(line) or greeting.is_greeting(line, helps=True))


def _is_event_change(line: str) -> bool:
    """Whether code reads the line as the write form of a change of an event ("muda para as 10h"): for an event card that form is the change itself."""
    return bool(natural_writes.read(line, None, op="event-change"))      # S41-11: the family reads it with the operation fixed (the claimer that said so is gone)


def entry_of(ctx: dict, channel, sender, revise: bool):
    """The entry of interpreter_enable.json in force (that pins the revise prompt when `revise`, else the event card text), or None; None too unless the sender is read by the interpreter."""
    if not ops_interpret.enabled(ctx, channel, sender):
        return None
    got = (interpreter_enable.revise_active if revise else interpreter_enable.card_active)(ops_interpret._tag(ctx["cfg"]))
    return got["entry"] if got else None


def _shape(ctx: dict, item: dict) -> tuple:
    """(kind, document, mail shape): "mail" with the shape of a new e-mail this path can reproduce, "event" for the card of a new event or of a change of one found in a snapshot, else
    "sentence" for any other effect card of a write to the person's accounts."""
    doc = ops_grants.effect_document(ctx, item)
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
    if line is None or card_words.card_shape(line) is not None or ops_say.state_question(line) or greeting.is_greeting(line, helps=True):
        return None
    try:
        item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    except core.OpsError:
        return None
    if item.get("kind") != "effect" or item.get("payload_sha256") != sha256:
        return None
    if item.get("status", "open") != "open":
        # a card this feature replaced, and a line that asks for a change of it: the person is told it was replaced (the bridge asks this only for a reply to the card)
        asked = mail_revise.asks_change(line) or bool(mail_revise.literals(mail_revise.instruction(text)))
        return ("replaced", None, line, None, None) if asked and item.get("answer") == NOTE and item.get("resolution") == "rejected" else None
    kind, doc, mail = _shape(ctx, item)
    if not isinstance(doc, dict):
        return None
    if kind == "sentence":
        return ("sentence", None, line, doc, None) if mail_revise.asks_change(line) and not _recognised(ctx, line, sender) else None
    if _recognised(ctx, line, sender, event=kind == "event") and not (kind == "event" and _is_event_change(line)):
        return None
    raw = mail_revise.instruction(text)
    asks = mail_revise.asks_change(line) or bool(mail_revise.literals(raw)) or mail_revise.recipient_words(raw)
    if kind == "mail" and not asks:
        return None      # a line that asks for no change never reaches the model (limit L63): a request or a thought, not an instruction for this card
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
    return kind, entry, raw if kind == "mail" else line, doc, mail


def card_revise_check(project: str, pending_id: int, sha256: str, text: str, channel: str = CHANNEL, sender=None):
    """See the module's text. Calls no model."""
    with turn_gate.turn():      # S41-6: the line's refresh budget (limits L52 and L53); an inner reuse inside a line, an entry of its own when the entry is called directly
        ops_actor.require(channel, sender)
        ctx = core.context(project)
        taken = _taken(ctx, pending_id, sha256, text, channel, sender)
        return taken[0] if taken else None


def say(ctx: dict, key: str, again=None) -> dict:
    """One sentence; `again` is the id of the card that is still open and is sent once more after it (so that a word still decides it: the sentence is now the last message)."""
    return {"say": phrases.text(key, ctx["cfg"]), "resend": again}


def drop(project: str, pending_id, channel, sender) -> None:
    """End a card the revision opened and cannot use (a card is never left to be approved by mistake); tried twice. Never raises."""
    for _ in range(2):
        try:
            ops_facade.function("reject")(project, pending_id, note=NOTE, channel=channel, sender=sender)
            return
        except Exception:      # noqa: BLE001 - nothing of the fault is kept
            continue


def _closed(ctx: dict, pending_id) -> bool:
    """Whether the decision is no longer open (it was decided meanwhile)."""
    try:
        return core._stored(ctx, ctx["store"].pending_get, pending_id).get("status", "open") != "open"
    except core.OpsError:
        return False


def swap(project: str, ctx: dict, old_id, open_new, matches, done_key: str, channel, sender) -> dict:
    """Everything that can fail has failed before this is called (the answer is accepted, the new card is allowed). The OLD card is ended first, then the new one is opened and checked
    (`matches(new_id)`), so that the worst case is no open card at all and never two: a card that cannot be ended (it was decided meanwhile) stops the change before anything is
    opened and says what happened; a new card that cannot be opened or is not what was asked is ended and the person is told to ask again. `open_new()` returns the id of the new card."""
    try:
        ops_facade.function("reject")(project, old_id, note=NOTE, channel=channel, sender=sender)
    except core.OpsError:
        return say(ctx, "RV_DECIDED") if _closed(ctx, old_id) else say(ctx, "RV_FAILED", old_id)
    try:
        new_id = open_new()
    except core.OpsError:
        new_id = None
    if not isinstance(new_id, int) or new_id == old_id:
        return say(ctx, "RV_LOST")
    if not matches(new_id):
        drop(project, new_id, channel, sender)
        return say(ctx, "RV_LOST")
    return {"say": phrases.text(done_key, ctx["cfg"]), "resend": new_id}


def _mail(project: str, ctx: dict, pending_id, entry, line, mail, channel, sender) -> dict:
    if mail_revise.asks_recipients(line):
        return say(ctx, "RV_RECIPIENTS", pending_id)
    admission = turn_gate.admit(ctx, sender)
    if admission is None:
        return say(ctx, "RV_FAILED", pending_id)
    revised, ok = None, False
    try:
        got = turn_gate.call(admission, entry, mail_revise.prompt_template(), mail_revise.message(ops_interpret._tag(ctx["cfg"]), mail["subject"], mail["body"], line),
                        deadline_ms=mail_revise.DEADLINE_MS, params=mail_revise.PARAMS)
        ok = bool(got.get("ok"))
        if ok:
            revised = mail_revise.accept(got.get("text"), mail["to"], mail["subject"], mail["body"], line)
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the person's words
        ok, revised = False, None
    turn_gate.record(ok)
    if revised is not None and revised.get("same") and revised.get("holds"):
        return say(ctx, "RV_ALREADY", pending_id)      # the card already holds every text the line asks for: told so, and the card is sent again
    if revised is None or revised.get("same"):
        return say(ctx, "RV_FAILED", pending_id)
    seed = turn_gate.Seed({"op": OPERATION[mail["kind"]], "slots": {"account": mail["account"], "to": list(mail["to"]), "subject": revised["subject"], "body": revised["body"]}},
                          {"account": "card-copy", "to": "card-copy", "subject": "composed", "body": "composed"})      # S41-7: the account and the recipients are the card's own; the text is the reviser's wording (S13)
    arguments = {"account": mail["account"], "to": ",".join(mail["to"]), "subject": revised["subject"], ("text" if seed["op"] == "mail-send" else "body"): revised["body"]}
    problems = turn_gate.provenance(seed["op"], arguments, {**seed.origins, ("text" if seed["op"] == "mail-send" else "body"): seed.origins["body"]})      # S41-7: the revised card's arguments, checked before the old card is ended
    if problems:
        print(turn_gate.refusal_line(seed["op"], problems), file=sys.stderr)
        return say(ctx, "RV_FAILED", pending_id)      # nothing was ended and nothing opened: the card stays as it was

    def open_new():
        opened = ops_facade.function("natural_write")(project, "", channel=channel, sender=sender, seed=seed)
        if not isinstance(opened.get("resend"), int):
            ops_facade.function("natural_forget")(project, sender, channel)
        return opened.get("resend")

    def matches(new_id) -> bool:
        try:
            made = core._stored(ctx, ctx["store"].pending_get, new_id)
            found = mail_revise.shape(ops_grants.effect_document(ctx, made))
        except core.OpsError:
            return False
        return (found is not None and made.get("kind") == "effect" and made.get("status", "open") == "open"
                and (found["kind"], found["account"], found["address"], found["to"]) == (mail["kind"], mail["account"], mail["address"], mail["to"])
                and (found["subject"], found["body"].strip()) == (revised["subject"], revised["body"].strip()))
    return swap(project, ctx, pending_id, open_new, matches, "RV_DONE_MAIL", channel, sender)


def card_revise(project: str, pending_id: int, sha256: str, text: str, channel: str = CHANNEL, sender=None) -> dict:
    """The change (see the module's text)."""
    with turn_gate.turn():      # S41-6: the line's refresh budget (limits L52 and L53); the new card this opens (`natural_write`) is the same line
        ops_actor.require(channel, sender)
        ctx = core.context(project)
        taken = _taken(ctx, pending_id, sha256, text, channel, sender)
        if taken is None:
            return {"pass": True}
        kind, entry, line, doc, mail = taken
        if kind == "replaced":
            return say(ctx, "RV_REPLACED")
        if kind == "sentence":
            return say(ctx, "RV_NOT_REVISABLE")
        if kind == "mail":
            return _mail(project, ctx, pending_id, entry, line, mail, channel, sender)
        return importlib.import_module("ops_event_revise").revise(project, ctx, pending_id, entry, line, doc, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
