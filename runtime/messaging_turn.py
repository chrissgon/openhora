# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's dispatcher: it walks the table of the order in which a line is claimed (package S41-2; runtime/turn_order.py) and runs the code of each row.

WHAT IT HOLDS. The order of who takes a line is data, `turn_order.ORDER`, stages `bridge` (the handling of one update, `Bridge._handle`) and `bridge-say` (the start of `Bridge.say`). This module
holds the code of every row of those stages, in `ROWS`, and `dispatch`, which runs the rows of a stage in the table's order and stops at the first that takes the line. A row is a function
`row(bridge, turn) -> bool`: True when it took the line. The conditions and the calls are the ones `Bridge._handle` and `Bridge.say` had before the table existed, copied and not changed,
side effects in between included (the reminder question dropped by any other line, the write question forgotten, the rewrite of a reply to a card that the rows after it see); the claimers'
own bodies (`plan_line`, `word_line`, `research_stop_line`, `revise_line`, `project_line`, `remind.answer`, ...) stay in the bridge and in their modules, and a row only calls them. Package S41-8
changes the frame rows; this package changes no outcome (runtime/tests/test_entry_replay.py proves it on the entry corpus).

THE LAYER. A `messaging_*` module may not import the operations layer (scripts/tests/test_layer_map.py). This module takes the bridge as an argument and reads everything else through it, so it
imports no operations module; the order of the operations layer's own claimers is the second stage of the table, dispatched by a module of that layer (package S41-3).

A TURN is what the rows share: the update, the sender and the chat, the senders' projects, and what the parse read of the line (`intent`, `kind`, `project`, `replied`; read once, by the first row
that needs them, `_read`). A row that rewrites the line (`reply-to-card`) writes the rewrite into the turn, and every later row reads it from there. A turn holds no store and no method.

TRACE is None; a test may set it to a function that receives `(name, turn)` for the row that took a line. Production never sets it. The table cannot be reordered at run time by this module:
`dispatch` reads `turn_order.names(stage)` each time and calls `ROWS[name]`; the tests replace a row's function on purpose and put it back.

Standard library only (and the modules the bridge reads). Runs on Python 3.9.
"""
from __future__ import annotations

import messaging_inbound as inbound
import messaging_provider as provider
import natural
import phone_delete
import turn_order

TRACE = None      # None, or a function that a test sets to receive `(name, turn)` of the row that took a line

FREE = ("text", "natural", "reply")      # the kinds of line a plan, a card word and a research stop may take


class Turn:
    """What the rows of one dispatch share (see the module text). `intent`, `kind`, `project` and `replied` are read by `_read`, once; `rewritten` is set by the row `reply-to-card`; `drafted` by the first
    frame row (whether a question about a reminder was open when the line came)."""

    def __init__(self, update=None, sender: str = "", chat: str = "", listed=None, project=None, text=None):
        self.update, self.sender, self.chat, self.listed = update, sender, chat, listed if listed is not None else []
        self.project, self.text = project, text
        self.intent, self.kind, self.replied = None, None, None
        self.rewritten, self.drafted = False, False


def _read(bridge, turn) -> None:
    """The parse of the update, the project it is for and its kind, done once, by the first row that needs them (the rows `ignore`, `forwarded-refusal` and `reply-to-card`; a row that is
    disabled by a test leaves the reading to the next)."""
    if turn.intent is None:
        turn.intent = inbound.parse(turn.update)
        turn.project = bridge.project_of(turn.sender, turn.listed)
        turn.kind = turn.intent["kind"]
        turn.replied = turn.update.get("reply_to")


# --- the stage `bridge`: the envelope ---------------------------------------------------------------------------------------------------------------------


def drop_unlisted(bridge, turn) -> bool:
    if not turn.listed:
        bridge.log(bridge.DROPPED)
        bridge.config_pending(turn.update, turn.sender, turn.chat)
        return True
    return False


def drop_invalid_attachments(bridge, turn) -> bool:
    if turn.update.get("attachments") is not None:
        found = provider.valid_attachments(turn.update["attachments"])
        if found is None:
            bridge.log("an update with attachments that are not valid was dropped")
            return True
        turn.update = dict(turn.update, attachments=found)
    return False


def ignore(bridge, turn) -> bool:
    _read(bridge, turn)
    return turn.kind == "ignore"


def forwarded_refusal(bridge, turn) -> bool:
    _read(bridge, turn)
    if turn.kind == "forwarded":
        bridge.reply(turn.chat, bridge.t("FWD_NOT_A_REQUEST", project=turn.project), turn.project)          # a forwarded message is never a request (FWD): one sentence, and nothing of it is read by a draft, a reminder, a write or a card
        return True
    return False


def reply_to_card(bridge, turn) -> bool:
    _read(bridge, turn)
    shown = bridge.ledger.by_message(turn.chat, turn.replied) if turn.kind == "natural" and turn.replied else None
    if shown and shown.get("kind") != "reminder":          # a reply to a card answers THAT card, not a reminder (NR-1); the question about a reminder is answered by `remind.answer`
        turn.intent = {"kind": "reply", "reply_to": turn.replied, "text": turn.update.get("text") or ""}
        turn.kind = "reply"
        turn.rewritten = True
    return False          # it rewrites the line and takes none: the rows after it read the rewrite from the turn


# --- the stage `bridge`: the frame ------------------------------------------------------------------------------------------------------------------------


def _open_frame(turn) -> bool:
    """Whether the line may answer a question that is open: a tap is no line, and a forwarded file (FWD) answers no open question and drops none: it goes straight to its card."""
    return turn.kind != "action" and not turn.intent.get("forwarded")


def reminder_draft_answer(bridge, turn) -> bool:
    bridge.remind.discarded.discard(turn.chat)          # before the question rows: a new line begins with no write question dropped by it
    if not _open_frame(turn):
        return False
    turn.drafted = turn.chat in bridge.remind.drafts          # the three question rows are one chain: a line of a chat with a reminder question open reaches neither of the next two, whatever `answer` says
    if turn.drafted:
        return bool(bridge.remind.answer(turn.project, turn.chat, turn.kind, turn.update.get("text") or "", turn.replied))          # the next line of a chat with a question open about a reminder (NR-1): it answers it, or drops it and goes on as a new line
    return False


def reminder_expired_yes(bridge, turn) -> bool:
    if not _open_frame(turn) or turn.drafted:
        return False
    return bool(turn.chat in bridge.remind.expired and bridge.remind.late(turn.project, turn.chat, turn.kind, turn.update.get("text") or ""))          # a "yes" to a question that expired is told so (NR-1)


def write_draft_answer(bridge, turn) -> bool:
    if not _open_frame(turn) or turn.drafted:
        return False
    text = turn.update.get("text") or ""
    if turn.kind in FREE and not text.lstrip().startswith("/") and bridge.write_open(turn.project, turn.chat):
        if bridge.write_answers(turn.project, turn.chat, text):
            bridge.write(turn.project, turn.chat, text)          # a question about a write to the person's accounts is open and this line answers it (NR-5)
            return True
        bridge.write_forget(turn.project, turn.chat)          # any other line drops it, and is handled as a new one; a question it asks says the previous one was discarded
        bridge.remind.discarded.add(turn.chat)
    return False


def plan_confirm_word(bridge, turn) -> bool:
    # the OK of a plan ("Posso?") the operations layer asked, or its refusal, or a correction (D5, limits L64 and L65): before the card words, which it never touches (a plan is no decision card)
    return turn.kind in FREE and bool(bridge.plan_line(turn.update, turn.intent, turn.kind, turn.project, turn.listed, turn.sender, turn.chat))


def card_word(bridge, turn) -> bool:
    # an approve or a reject word decided a decision card, or listed the cards to choose from (S2, limit L64)
    return turn.kind in FREE and bool(bridge.word_line(turn.update, turn.intent, turn.project, turn.listed, turn.sender, turn.chat))


def research_stop(bridge, turn) -> bool:
    # a stop word of the sender's own running research (BL2b): after the card words, so that "nao" with a card as the last message still rejects the card
    return turn.kind in FREE and bool(bridge.research_stop_line(turn.update, turn.intent, turn.kind, turn.project, turn.listed, turn.chat))


def card_revise(bridge, turn) -> bool:
    # a change of the card that waits, said in words (S13, limit L64)
    return bool(bridge.revise_line(turn.update, turn.intent, turn.kind, turn.project, turn.listed, turn.chat))


def project_switch(bridge, turn) -> bool:
    # "muda para o projeto X": the typed /project, said in words (S20)
    return bool(bridge.project_line(turn.intent, turn.kind, turn.listed, turn.sender, turn.chat))


def help_in_words(bridge, turn) -> bool:
    # "help" in words is the typed /help: the fixed list of this app, for every listed sender (it reads nothing of the project), except from a sender who may talk, whose help line is a greeting (S5)
    if turn.kind in ("text", "natural") and (natural.match(turn.intent["text"]) or {}).get("op") == "commands" and not bridge.greets(turn.project, turn.chat, turn.intent["text"]):
        bridge.reply(turn.chat, bridge.t("HELP", project=turn.project), turn.project)
        return True
    return False


def attachment_line(bridge, turn) -> bool:
    # "descarta", "adiciona ao projeto": a line about the file just sent (ATT-3)
    return turn.kind in ("text", "natural") and bool(bridge.attach.line(turn.project, turn.chat, turn.intent.get("text") or ""))


# --- the stage `bridge`: one row for each kind of line ----------------------------------------------------------------------------------------------------


def attachment_arrived(bridge, turn) -> bool:
    if turn.kind == "attachment":
        bridge.attach.arrived(turn.project, turn.chat, turn.intent)
        return True
    return False


def attachment_typed(bridge, turn) -> bool:
    if turn.kind in ("add", "discard"):
        bridge.attach.typed(turn.project, turn.chat, turn.kind, turn.intent["id"])
        return True
    return False


def remind_typed(bridge, turn) -> bool:
    if turn.kind == "remind":
        bridge.remind.created(turn.project, turn.chat, turn.intent)
        return True
    return False


def write_form(bridge, turn) -> bool:
    if turn.kind == "natural" and turn.intent.get("op") == "write":
        bridge.write(turn.project, turn.chat, turn.intent["text"])
        return True
    return False


def reminder_form(bridge, turn) -> bool:
    return turn.kind == "natural" and turn.intent.get("op") != "write" and bool(bridge.remind.natural(turn.project, turn.chat, turn.intent))


def say_natural(bridge, turn) -> bool:
    if turn.kind == "natural":
        bridge.say(turn.project, turn.chat, turn.intent["text"])
        return True
    return False


def reminders_list(bridge, turn) -> bool:
    if turn.kind == "reminders":
        bridge.remind.listing(turn.project, turn.chat)
        return True
    return False


def forget_typed(bridge, turn) -> bool:
    if turn.kind == "forget":
        bridge.remind.forget(turn.project, turn.chat, turn.intent["id"])
        return True
    return False


def tap(bridge, turn) -> bool:
    if turn.kind == "action":
        bridge.tapped(turn.chat, turn.intent["action"], turn.update.get("action_ref"))
        return True
    return False


def usage(bridge, turn) -> bool:
    if turn.kind == "usage":
        bridge.reply(turn.chat, bridge.t(inbound.usage_key(turn.intent["text"]), project=turn.project) if inbound.usage_key(turn.intent["text"]) else turn.intent["text"], turn.project)
        return True
    return False


def help_typed(bridge, turn) -> bool:
    if turn.kind == "help":
        bridge.reply(turn.chat, bridge.t("HELP", project=turn.project), turn.project)
        return True
    return False


def project_typed(bridge, turn) -> bool:
    if turn.kind == "project":
        bridge.choose(turn.sender, turn.chat, turn.listed, turn.intent["name"])
        return True
    return False


def pending_typed(bridge, turn) -> bool:
    if turn.kind == "pending":
        bridge.listing(turn.project, turn.chat)
        return True
    return False


def decision_typed(bridge, turn) -> bool:
    if turn.kind not in ("approve", "reject", "release", "answer"):
        return False
    intent, project, chat, replied = turn.intent, turn.project, turn.chat, None          # `project` and `replied` are this row's own: a card on another project does not change the turn's
    if bridge.messenger.capabilities().get("actions_need_reply"):
        replied = bridge.replied_card(turn.sender, chat, turn.update.get("reply_to"), intent["id"])
        if replied is None:
            bridge.reply(chat, bridge.t("REPLY_TO_CARD", project=project), project)
            return True
        project = replied[0]
    if turn.kind == "answer":
        bridge.act(project, chat, "answer", intent["id"], text=intent["text"])
    else:
        bridge.act(project, chat, turn.kind, intent["id"], card=replied[1] if replied else None, note=intent.get("note"),
                   typed_hash=intent.get("sha256"))
    return True


def reply(bridge, turn) -> bool:
    if turn.kind != "reply":
        return False
    card = bridge.ledger.by_message(turn.chat, turn.intent["reply_to"])
    if card and card["kind"] == "question":
        target = next((p for p in bridge.projects if p["id"] == card["project"]), turn.project)
        if not bridge.listed_in(target, turn.sender):
            bridge.log(bridge.DROPPED)
            return True
        bridge.act(target, turn.chat, "answer", card["pending_id"], card=card, text=turn.intent["text"])
    else:
        bridge.say(turn.project, turn.chat, turn.intent["text"])
    return True


def say(bridge, turn) -> bool:
    bridge.say(turn.project, turn.chat, turn.intent["text"])
    return True


# --- the stage `bridge-say`: the start of `Bridge.say` -----------------------------------------------------------------------------------------------------


def delete_refusal_before_queue(bridge, turn) -> bool:
    if phone_delete.asks(turn.text):      # S14b: a request to delete a file is answered at once, before any queue, run or model; a sender who may not talk gets the refusal of any line
        try:
            bridge.allow(turn.project, "say", None, turn.chat)
        except (bridge.Refused, bridge.ops.OpsError):
            return False
        try:
            bridge.allow(turn.project, "file-trash", None, turn.chat)      # R2-A: a sender who may move a file to the trash is not told it cannot be done: the line goes on, and the conversation opens the file's card
        except (bridge.Refused, bridge.ops.OpsError):
            bridge.reply(turn.chat, bridge.t("PHONE_NO_FILE_DELETE", project=turn.project), turn.project)
            return True
    return False


def closed_form_without_slot(bridge, turn) -> bool:
    found = None if turn.text.lstrip().startswith("/") else natural.match(turn.text)
    if found is not None and natural.class_of(found["op"]) in ("D", "W"):      # a decision or an act said in a closed form (S20) is answered by code with no model: it takes no model slot, so a brake said in words works while the planning agent answers, as the typed /reject does
        bridge.start(turn.project, turn.chat, found["op"], bridge.line(turn.project, turn.chat, turn.text, None))
        return True
    return False


def say_queue(bridge, turn) -> bool:
    bridge.say_queue(turn.project, turn.chat, turn.text)
    return True


ROWS = {
    "drop-unlisted": drop_unlisted, "drop-invalid-attachments": drop_invalid_attachments, "ignore": ignore, "forwarded-refusal": forwarded_refusal, "reply-to-card": reply_to_card,
    "reminder-draft-answer": reminder_draft_answer, "reminder-expired-yes": reminder_expired_yes, "write-draft-answer": write_draft_answer, "plan-confirm-word": plan_confirm_word,
    "card-word": card_word, "research-stop": research_stop, "card-revise": card_revise, "project-switch": project_switch, "help-in-words": help_in_words,
    "attachment-line": attachment_line, "attachment-arrived": attachment_arrived, "attachment-typed": attachment_typed, "remind-typed": remind_typed, "write-form": write_form,
    "reminder-form": reminder_form, "say-natural": say_natural, "reminders-list": reminders_list, "forget-typed": forget_typed, "tap": tap, "usage": usage, "help-typed": help_typed,
    "project-typed": project_typed, "pending-typed": pending_typed, "decision-typed": decision_typed, "reply": reply, "say": say,
    "delete-refusal-before-queue": delete_refusal_before_queue, "closed-form-without-slot": closed_form_without_slot, "say-queue": say_queue,
}


def dispatch(bridge, turn, stage: str = "bridge") -> str:
    """Run the rows of `stage` in the order of `turn_order.names(stage)` and return the name of the first that took the line (the last row of a stage always does). An exception of a row
    propagates, as it did when the rows were a chain (`Bridge.handle_safely` catches it)."""
    for name in turn_order.names(stage):
        if ROWS[name](bridge, turn):
            if TRACE is not None:
                TRACE(name, turn)
            return name
    raise RuntimeError(f"no row of the stage {stage} took the line")
