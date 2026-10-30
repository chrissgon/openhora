# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's dispatcher: it walks the table of the order in which a line is claimed (packages S41-2 and S41-8; runtime/turn_order.py) and runs the code of each row.

WHAT IT HOLDS. The order of who takes a line is data, `turn_order.ORDER`, stages `bridge` (the handling of one update, `Bridge._handle`) and `bridge-say` (the start of `Bridge.say`). This module
holds the code of every row of those stages, in `ROWS`, and `dispatch`, which runs the rows of a stage in the table's order and stops at the first that takes the line. A row is a function
`row(bridge, turn) -> bool`: True when it took the line. The conditions and the calls are the ones `Bridge._handle` and `Bridge.say` had before the table existed, copied and not changed,
side effects in between included (the reminder question dropped by any other line, the write question forgotten, the rewrite of a reply to a card that the rows after it see); the claimers'
own bodies (`project_line`, `remind.answer`, `plan_decide`, `word_reply`, ...) stay in the bridge and in their modules, and a row only calls them.

THE FRAME (S41-8). The seven rows that answered what is open are one row, `frame`, and `frame` is the one dispatcher over the pending kinds of PLAN-BRAIN section 3: `turn_order.FRAME_KINDS`, in
that order, each a `Kind` of `KINDS` with two functions, `applies(bridge, turn)` (reads the turn, changes nothing the line did not already change, returns the match: None or False when the kind
does not read this line, else a truthy value that `take` receives) and `take(bridge, turn, found)` (the call; True when it took the line, False when the line goes on, as the write kind does
after it dropped its question). The envelope checks every kind made for itself (a tap is no line, an empty line, a command, a forwarded message, an e-mail that is not a reply) are the properties of
`Turn`, which are read the same way by every kind and read once when they read the world outside the turn. Where two kinds tested different things (the raw text of the update, the first line of an
e-mail reply), each keeps its own, named. The two checks the acts make again at act time (`Bridge.word_act` against the ledger, the decision and the last message as they are now, `Bridge.still_last`; `Bridge.plan_decide` against the
live plan's item and hash and, for a yes, the last message again) are the bridge's and are not here. A greeting in question form ("oi, tudo bem?") is never the OK of a plan (L64H, `greeting.as_question`).

THE LAYER. A `messaging_*` module may not import the operations layer (scripts/tests/test_layer_map.py). This module takes the bridge as an argument and reads everything else through it, so it
imports no operations module; the order of the operations layer's own claimers is the second stage of the table, dispatched by a module of that layer (package S41-3).

A TURN is what the rows share: the update, the sender and the chat, the senders' projects, and what the parse read of the line (`intent`, `kind`, `project`, `replied`; read once, by the first row
that calls `_read`: one of the three envelope rows). A row that rewrites the line (`reply-to-card`) writes the rewrite into the turn, and every later row reads it from there. A turn holds no store: it
holds the bridge only to read, once, what the envelope reads of it (the platform's capabilities, the ledger records of the replied and of the last message, the question about a reminder that was open
when the line came).

TRACE is None; a test may set it to a function that receives `(name, turn)` for the row that took a line; for the row `frame`, `turn.frame_kind` names the kind. Production never sets it. The table
cannot be reordered at run time by this module: `dispatch` reads `turn_order.names(stage)` and `frame` reads `turn_order.kinds()` each time and call `ROWS[name]` and `KINDS[name]`; the tests replace a
row's function or a kind's on purpose and put it back.

Standard library only (and the modules the bridge reads). Runs on Python 3.9.
"""
from __future__ import annotations

import card_words
import command_words
import greeting
import messaging_inbound as inbound
import messaging_provider as provider
import natural
import phone_delete
import turn_order

TRACE = None      # None, or a function that a test sets to receive `(name, turn)` of the row that took a line

FREE = ("text", "natural", "reply")      # the kinds of line a plan, a card word and a research stop may take


class Turn:
    """What the rows of one dispatch share (see the module text). `intent`, `kind`, `project` and `replied` are read by `_read`, once; `rewritten` is set by the row `reply-to-card`; `frame_kind` by the
    row `frame` (the kind that took the line).

    The ENVELOPE, as properties. What a kind may ask of the line, in one place. `said` is the text of the parse's intent (empty when none), `plain` is it non-empty and not a command, `raw` the
    text of the update itself (the write question reads this one), `forwarded` is the update's own mark (the update says it is a forward, fail closed) and `forwarded_file` the intent's (a forwarded
    file: it answers no question and drops none), `first_line` is the line as a word is read from it (an e-mail reply says its word on its first line; the signature and the quoted card are not
    words), `email` whether the platform's acts are replies. Four of them read the world outside the turn and are read ONCE per dispatch, on first use: `email` (the capabilities), `drafted` (whether a
    question about a reminder was open when the line came: it stays so after `remind.answer` dropped it, so that the two kinds after it read nothing of such a chat), `replied_record` and
    `last_record` (the ledger's records of the message the line replies to and of the chat's last message; `record` keeps a record that was found, one read for each message id, so a kind that asks again for the
    same message gets the first answer; a record not found is read again). Everything else is computed from the turn each time it is asked, so a rewrite of the line is always seen."""

    def __init__(self, update=None, sender: str = "", chat: str = "", listed=None, project=None, text=None, bridge=None):
        self.update, self.sender, self.chat, self.listed = update, sender, chat, listed if listed is not None else []
        self.project, self.text, self.bridge = project, text, bridge
        self.intent, self.kind, self.replied = None, None, None
        self.rewritten, self.frame_kind = False, None
        self._once, self._records = {}, {}

    def _read_once(self, key, read):
        if key not in self._once:
            self._once[key] = read()
        return self._once[key]

    @property
    def said(self) -> str:
        return self.intent.get("text") or ""

    @property
    def plain(self) -> bool:
        said = self.said
        return bool(said.strip()) and not said.lstrip().startswith("/")

    @property
    def raw(self) -> str:
        return self.update.get("text") or ""

    @property
    def forwarded(self) -> bool:
        return "forwarded" in self.update and self.update["forwarded"] is not False

    @property
    def forwarded_file(self) -> bool:
        return bool(self.intent.get("forwarded"))

    @property
    def email(self) -> bool:
        return self._read_once("email", lambda: bool(self.bridge.messenger.capabilities().get("actions_need_reply")))

    @property
    def first_line(self) -> str:
        return card_words.reply_line(self.said) if self.email else self.said

    @property
    def drafted(self) -> bool:
        """Whether this chat had a question open about a reminder when the line came, and the line may answer one (a tap is no line, and a forwarded file answers no question)."""
        return self._read_once("drafted", lambda: _open_frame(self) and self.chat in self.bridge.remind.drafts)

    def record(self, message_id):
        """The ledger's record of a message of this chat (None for no id). A record that was found is kept for the rest of the dispatch, one read for each id; a record that is absent is never kept, so
        one that lands while the line is handled (a send that returns) is seen by the next kind, as when each kind read the ledger for itself. An id that is not a string is never kept."""
        if not message_id:
            return None
        if isinstance(message_id, str) and message_id in self._records:
            return self._records[message_id]
        found = self.bridge.ledger.by_message(self.chat, message_id)
        if found is not None and isinstance(message_id, str):
            self._records[message_id] = found
        return found

    @property
    def replied_record(self):
        return self.record(self.update.get("reply_to"))

    @property
    def last_record(self):
        """The record of the chat's last message as it is when asked (`last_sent` is read each time: a message sent meanwhile is another id and gets its own read)."""
        return self.record(self.bridge.last_sent.get(self.chat))


def _read(bridge, turn) -> None:
    """The parse of the update, the project it is for and its kind, done once, by the first of the three envelope rows that
    call it (`ignore`, `forwarded-refusal`, `reply-to-card`; a row disabled by a test leaves the reading to the next). The frame and kind rows never call it: they read the turn, so one of those three
    must have run before them."""
    if turn.intent is None:
        turn.project = bridge.project_of(turn.sender, turn.listed)
        turn.intent = inbound.parse(turn.update)
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
    turn.bridge = bridge
    shown = turn.replied_record if turn.kind == "natural" and turn.replied else None
    if shown and shown.get("kind") != "reminder":          # a reply to a card answers THAT card, not a reminder (NR-1); the question about a reminder is answered by `remind.answer`
        turn.intent = {"kind": "reply", "reply_to": turn.replied, "text": turn.update.get("text") or ""}
        turn.kind = "reply"
        turn.rewritten = True
    return False          # it rewrites the line and takes none: the rows after it read the rewrite from the turn


# --- the stage `bridge`: the frame -------------------------------------------------------------------------------------------------------------------------


def _open_frame(turn) -> bool:
    """Whether the line may answer a question that is open: a tap is no line, and a forwarded file (FWD) answers no open question and drops none: it goes straight to its card."""
    return turn.kind != "action" and not turn.forwarded_file


class Kind:
    """One pending kind: `applies(bridge, turn)` and `take(bridge, turn, found)` (the module text). The two are attributes of the instance, so a test replaces one on purpose and puts it back."""

    def __init__(self, applies, take):
        self.applies, self.take = applies, take


# reminder-draft: the next line of a chat with a question open about a reminder (NR-1): it answers it, or drops it and goes on as a new line


def reminder_draft_applies(bridge, turn):
    return turn.drafted      # the question rows are one chain: a line of a chat with a reminder question open reaches neither of the next two kinds, whatever `answer` says


def reminder_draft_take(bridge, turn, found):
    return bool(bridge.remind.answer(turn.project, turn.chat, turn.kind, turn.raw, turn.replied))


# reminder-expired: a "yes" to a question that expired is told so (NR-1)


def reminder_expired_applies(bridge, turn):
    return _open_frame(turn) and not turn.drafted and turn.chat in bridge.remind.expired


def reminder_expired_take(bridge, turn, found):
    return bool(bridge.remind.late(turn.project, turn.chat, turn.kind, turn.raw))


# write-draft: a question about a write to the person's accounts is open (NR-5): the line answers it, or drops it and goes on as a new one


def write_draft_applies(bridge, turn):
    return _open_frame(turn) and not turn.drafted and turn.kind in FREE and not turn.raw.lstrip().startswith("/") and bridge.write_open(turn.project, turn.chat)


def write_draft_take(bridge, turn, found):
    if bridge.write_answers(turn.project, turn.chat, turn.raw):
        bridge.write(turn.project, turn.chat, turn.raw)          # a question about a write to the person's accounts is open and this line answers it (NR-5)
        return True
    bridge.write_forget(turn.project, turn.chat)          # any other line drops it, and is handled as a new one; a question it asks says the previous one was discarded
    bridge.remind.discarded.add(turn.chat)
    return False


# plan-confirm: the OK of a plan ("Posso?") the operations layer asked, or its refusal, or a correction (D5, limits L64 and L65): before the card words, which it never touches (a plan is no decision card)


def plan_confirm_applies(bridge, turn):
    """A yes or no word, as code reads it (`natural.confirm_kind`, the first line of an e-mail reply), in a plain line that is no forward: the word, else None."""
    if turn.kind not in FREE or not turn.plain or turn.forwarded:
        return None
    if greeting.as_question(turn.first_line):
        return None      # L64H: a greeting in question form is never the OK of a plan; it goes on as any other line and gets the greeting
    return natural.confirm_kind(turn.first_line)


def plan_confirm_take(bridge, turn, word):
    """Taken only when the question the word answers is the one the line replies to or, with no reply, the LAST message the platform sent to this chat (`last_sent`: None while a send is on its way, and
    after a restart); on a platform whose acts are replies (e-mail) only a reply counts; the question's project lists the sender and its chat is this chat. A decision card is never touched here: only a
    record of kind `plan-confirm` is taken, any other record returns False to the card words. A "no" drops the plan, a "yes" starts the confirmed call (`Bridge.plan_decide`, which looks at the live plan again)."""
    replied = turn.update.get("reply_to")
    last = None
    if replied:
        rec = turn.replied_record if isinstance(replied, str) else None
    elif turn.email:
        return False      # e-mail: an OK is a reply to the question (rule 50)
    else:
        rec = turn.last_record      # a restart forgets the last message and a send in flight clears it: a word then decides nothing
        last = rec.get("message_id") if rec else None      # the id the word was read against: `plan_decide` reads the last message again just before a yes starts (L64H)
    if rec is None or rec.get("kind") != "plan-confirm" or rec.get("chat") != turn.chat:
        return False
    target = next((p for p in turn.listed if p["id"] == rec.get("project")), None)
    if target is None:
        return False
    bridge.plan_decide(target, turn.chat, rec, word, turn.first_line, last=last)
    return True


# decision-card-word: an approve or a reject word decided a decision card, or listed the cards to choose from (S2, limit L64); the two-open guard PLAN_TWO_OPEN is inside `Bridge.word_last`


def decision_card_word_applies(bridge, turn):
    """A line that is, whole, one of the closed approve or reject forms (`card_words.card_word`; an e-mail reply says it on its first line), and no forward: the word, else None."""
    if turn.kind not in FREE:
        return None
    word = card_words.card_word(turn.first_line)
    if word is None or turn.forwarded:
        return None
    return word


def decision_card_word_take(bridge, turn, word):
    """A reply names the card it means (`Bridge.word_reply`); on e-mail a typed act is a reply to the card; otherwise the card must be the LAST message (`Bridge.word_last`). Every condition of L64 that this
    checks is checked again by `Bridge.word_act` against the ledger and the decision as they are now."""
    replied = turn.update.get("reply_to")
    if replied:
        return bridge.word_reply(turn.listed, turn.chat, word, turn.replied_record if isinstance(replied, str) else None)
    if turn.email:
        return False      # e-mail: a typed act is a reply to the card (rule 50)
    last = bridge.last_sent.get(turn.chat)
    if not last:
        return False      # a restart forgets the last message: a word then decides nothing
    return bridge.word_last(turn.listed, turn.chat, word, last)


# research-run: a stop word of the sender's own running research (BL2b): after the card words, so that "nao" with a card as the last message still rejects the card


def research_run_applies(bridge, turn):
    """A stop word (`command_words.stop_form`, or a no word) in a plain line that is no forward, when the operations layer can stop a research and, on a platform whose acts are replies (e-mail), the line
    replies to a message this bridge sent to the chat: the operations layer's stop function, else None."""
    if turn.kind not in FREE or not turn.plain or turn.forwarded:
        return None
    stopper = getattr(bridge.ops, "research_stop", None)
    if stopper is None:
        return None
    if turn.email:
        replied = turn.update.get("reply_to")
        if not (isinstance(replied, str) and replied in bridge.sent_ids.get(turn.chat, ())):
            return None
    if not (command_words.stop_form(turn.first_line) or natural.confirm_kind(turn.first_line) == "no"):
        return None
    return stopper


def research_run_take(bridge, turn, stopper):
    """True when a research run of this sender was running and was cancelled (the run answers `RS_CANCELLED` itself, so this says nothing). The operations layer checks the sender's key and policy: it never
    touches another sender's run."""
    for target in [turn.project] + [p for p in turn.listed if p["id"] != turn.project["id"]]:
        try:
            if stopper(target["path"], bridge.key(turn.chat)):
                return True
        except bridge.ops.OpsError:
            continue
    return False


# decision-card-revise: a change of the card that waits, said in words (S13, limit L64)


def decision_card_revise_applies(bridge, turn):
    """A plain line that is no forward, on a platform whose acts are not replies: a natural line only when it is the change of an event (the write forms are the write rows' own)."""
    kind = turn.kind
    if kind == "natural" and not (turn.intent.get("op") == "write" and turn.intent.get("write") == "event-change"):
        return None
    if kind not in ("text", "natural", "reply") or not turn.plain or turn.forwarded or turn.email:
        return None
    return True


def decision_card_revise_take(bridge, turn, found):
    """The card the line is about: the one it replies to or, with no reply, the card that is the LAST message (`Bridge.revise_waiting` checks that it is a decision card of this chat, whole, open and unchanged)."""
    replied = turn.update.get("reply_to")
    card = turn.replied_record if isinstance(replied, str) and replied else turn.last_record
    return bridge.revise_waiting(card, replied, turn.said, turn.kind, turn.listed, turn.chat)


KINDS = {
    "reminder-draft": Kind(reminder_draft_applies, reminder_draft_take), "reminder-expired": Kind(reminder_expired_applies, reminder_expired_take),
    "write-draft": Kind(write_draft_applies, write_draft_take), "plan-confirm": Kind(plan_confirm_applies, plan_confirm_take),
    "decision-card-word": Kind(decision_card_word_applies, decision_card_word_take), "research-run": Kind(research_run_applies, research_run_take),
    "decision-card-revise": Kind(decision_card_revise_applies, decision_card_revise_take),
}


def frame(bridge, turn) -> bool:
    """The row `frame`: the first kind of `turn_order.kinds()` that reads the line and takes it ends the row, and `turn.frame_kind` names it. A new line begins with no write question dropped by it
    (`remind.discarded`), before any kind reads it. A kind whose `take` returns False has done what it does with a line that is not its answer (the write kind drops its question), and the next kind reads it."""
    turn.bridge = bridge
    bridge.remind.discarded.discard(turn.chat)
    for name in turn_order.kinds():
        kind = KINDS[name]
        found = kind.applies(bridge, turn)
        if found and kind.take(bridge, turn, found):
            turn.frame_kind = name
            return True
    return False


def project_switch(bridge, turn) -> bool:
    # "muda para o projeto X": the typed /project, said in words (S20)
    return bool(bridge.project_line(turn.intent, turn.kind, turn.listed, turn.sender, turn.chat))


def help_in_words(bridge, turn) -> bool:
    # "help" in words is the typed /help: the fixed list of this app, for every listed sender (it reads nothing of the project), except from a sender who may talk, whose help line is a greeting (S5)
    if turn.kind in ("text", "natural") and greeting.help_form(turn.intent["text"]) and not bridge.greets(turn.project, turn.chat, turn.intent["text"]):
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


def reminder_form(bridge, turn) -> bool:
    # S41-11: only `/remind <free words>` (the intent `natural`, how "command") is read here; a reminder or a write said in words with no slash is read by the interpreter (L63)
    if turn.kind != "natural":
        return False
    return bool(bridge.remind.natural(turn.project, turn.chat, turn.intent))


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
    card = turn.record(turn.intent["reply_to"])
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
    found = None if turn.text.lstrip().startswith("/") else natural.decision(turn.text)
    if found is not None:      # a decision or an act said in a closed form (S20) is answered by code with no model: it takes no model slot, so a brake said in words works while the planning agent answers, as the typed /reject does
        bridge.start(turn.project, turn.chat, found["op"], bridge.line(turn.project, turn.chat, turn.text, None))
        return True
    return False


def decide_without_slot(bridge, turn) -> bool:
    # A11-2 (S41-11, SPEC-S41-11-BRAKE): a plain line of a sender who holds `interpret` (or a brake form of any sender) is decided in a job that takes no model slot, so a brake said in words works while the planning agent answers.
    # Only a line the decision hands back (with a route pass) goes on to `say-queue`, in a second job.
    if turn.text.lstrip().startswith("/") or not turn.text.strip() or not (bridge.reads_words(turn.project, turn.chat) or bridge.brake_form(turn.text)):
        return False      # a sender the interpreter does not read is decided only when the line is a brake form: its typed hint is answered at once (review C1-a)
    bridge.decide(turn.project, turn.chat, turn.text)
    return True


def say_queue(bridge, turn) -> bool:
    bridge.say_queue(turn.project, turn.chat, turn.text)
    return True


ROWS = {
    "drop-unlisted": drop_unlisted, "drop-invalid-attachments": drop_invalid_attachments, "ignore": ignore, "forwarded-refusal": forwarded_refusal, "reply-to-card": reply_to_card,
    "frame": frame, "project-switch": project_switch, "help-in-words": help_in_words,
    "attachment-line": attachment_line, "attachment-arrived": attachment_arrived, "attachment-typed": attachment_typed, "remind-typed": remind_typed,
    "reminder-form": reminder_form, "reminders-list": reminders_list, "forget-typed": forget_typed, "tap": tap, "usage": usage, "help-typed": help_typed,
    "project-typed": project_typed, "pending-typed": pending_typed, "decision-typed": decision_typed, "reply": reply, "say": say,
    "delete-refusal-before-queue": delete_refusal_before_queue, "closed-form-without-slot": closed_form_without_slot, "decide-without-slot": decide_without_slot, "say-queue": say_queue,
}


def dispatch(bridge, turn, stage: str = "bridge") -> str:
    """Run the rows of `stage` in the order of `turn_order.names(stage)` and return the name of the first that took the line (the last row of a stage always does). An exception of a row
    propagates, as it did when the rows were a chain (`Bridge.handle_safely` catches it)."""
    turn.bridge = bridge
    for name in turn_order.names(stage):
        if ROWS[name](bridge, turn):
            if TRACE is not None:
                TRACE(name, turn)
            return name
    raise RuntimeError(f"no row of the stage {stage} took the line")
