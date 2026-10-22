#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The conversation with the planning agent: one turn of it (`say`) and the memory a plain line carries to the router.

A sibling of runtime/ops.py, which exposes `say` and `chat_memory` under their names; no shell imports this file. The
names every module of the layer shares are read as `core.<name>` (runtime/ops_core.py); an operation or a helper that
stays in runtime/ops.py is reached at call time through `_ops()`, never imported at module level, so that the two
files do not import each other.

A line typed while the router is answering another request of the project is not refused: it is stored with its reply
pending (the queue below) and `route_queued` answers it when the route lock is free (a run of a task never holds it);
a plain line that asks about the state is answered at once, by code, from the store's records; a reply of the router that is a direct turn (route `none`,
shape `direct`) is answered the same way, with the router's `Next` line; a reply that names no route opens a
question with a sentence and two actions. The reasons and the shapes are in contracts/runtime.md, "The conversation".

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import importlib
import inspect
import json
import os
import re
import time
import unicodedata

import ops_core as core
import autonomy
import greeting
import lab
import language as language_rules
import line_stage
import natural
import operations
import ops_actor
import ops_natural
import pending_items
import phone_delete
import phone_questions
import phone_refusal
import phrases
import plan
import router
import skill_meta


def _ops():
    """runtime/ops.py, found at call time: the operations `say` calls and the helpers of the route stay there."""
    return importlib.import_module("ops")


# --- stage 6: the conversation with the planning agent ----------------------------------------------------------------

CONVERSATION = "project"  # one conversation per project until the local interface (stage 9)
MEMORY_TURNS = 6
MEMORY_CHARS = 4000
MEMORY_CUT = 600
MEMORY_HEAD = "Earlier in this conversation, oldest first:"
MEMORY_TAIL = "The request now:"
# The conversation's sentences are the phrase table's (runtime/phrases.py, package LR-1): these names keep the English text (a test pins that it is what
# operations.chat_line spells), and each place below says the sentence in the project's language.
PLAN_NEXT = phrases.en("PLAN_NEXT")
ANSWERED_AS = phrases.en("ANSWERED_AS")   # what `conversation` shows in place of an answer to a reader that did not ask
ASK_NEXT = phrases.en("ASK_NEXT")
_question_clock = lambda: datetime.datetime.now(datetime.timezone.utc)      # noqa: E731  (the clock of the age of a bound question, against pending_items.ROUTER_WINDOW; a test replaces it)
NOT_NAMED = phrases.en("BODY_NOT_NAMED")
NOT_NAMED_ACTIONS = ["choose-flow", "cancel"]    # the words of the payload's `actions`: the page draws one button for each
NOT_NAMED_NEXT = phrases.en("NOT_NAMED_NEXT")
RAW_MAX = 32 * 1024                              # bytes of the router's block kept in the payload's `raw`
QUEUING_CHANNELS = ("page",)  # the shells that drain the queue: only the local service runs `route_queued` on a loop
QUEUE_GROUPS = {"talk": "say", "request": "route"}  # the groups an entry stores, and the operation each stands for
DRAIN = "queue"               # the channel the drain acts as: it may queue again (the lock can be taken meanwhile), never jump the queue
QUEUED_REQUEST = phrases.en("QUEUED_REQUEST")
PROPOSES = phrases.en("PROPOSES")
RUN_BUSY = "the planning agent is answering another request of this project"

# The queue: lines of the person and requests that wait for the planning agent while the router holds the project's
# route lock. One cursor of the store holds it (JSON, oldest first), changed under a file lock of the data folder so that
# the service's threads and the terminal never overwrite one another.
CODE_CLOSED = "conversation:code-closed:{id}"      # a mark per request that code answered and cancelled (`_close_by_code`); no value but "1", so that no thread rewrites another's
QUEUE = "conversation:queue"
QUEUE_LOCK_NAME = "queue.lock"
QUEUE_LOCK_WAIT = 5.0       # seconds a change of the queue waits for another to finish
QUEUE_MAX = 20              # entries: the cursor holds at most 4 KiB
QUEUE_STALE_MARGIN = 60.0   # seconds added to the run timeout before an entry that was taken is taken to be dead
QUEUE_STALE_FALLBACK = 1800.0  # the run timeout, only when the gate file cannot be read
STARTED = "started"         # the key of an entry a drain has taken, with the time it took it

# The forms of a question about the state that are answered by code, with no model and no request: lower case, no
# accents, no punctuation (_normal). The list is closed; a line that is none of them goes to the planning agent.
STATE_WORDS = 12            # a longer line is a request
TAIL = r"[a-z0-9]+(?: [a-z0-9]+){0,5}"   # what a question is about: at most six words
# A line with a sentence mark inside it ("how are we on the roadmap, delete the old plan") is more than the form, and a
# tail that holds a verb of work is a request that starts like a question: neither is answered as the state.
INTERIOR_MARK = re.compile(r"[.,;:!?]")
WORK_WORDS = frozenset((
    "add build change create delete draft drop fix make move publish remove rename replace send set start stop update "
    "write adicione apague atualize crie corrija escreva envie faca mude publique remova troque").split())
STATE_QUESTIONS = (
    r"status", r"(project )?status( of the project| do projeto)?", r"qual (e )?o status( do projeto)?",
    r"(what is|what s|whats) (the )?(project )?status( of the project)?",
    r"how (are we|is it|is the project) (doing|going)( (with|on|about|regarding|in) " + TAIL + ")?",
    r"how are we( (with|on|about|regarding) " + TAIL + ")?",
    r"como (estamos|esta|estao|esta o projeto)( (com|sobre|em relacao (a|ao|as|aos)) " + TAIL + ")?",
    r"o que (falta|resta|ja foi feito|esta (rodando|em andamento|pendente|aguardando))",
    r"o que (esta )?(rodando|aguarda|espera)( agora)?",
    r"what (is|s) (running|left|next|pending|waiting|done|happening)( now)?",
    r"what waits( for me)?", r"what (are we|am i) waiting for", r"what do you need from me",
    r"o que (voce|vc) precisa de mim", r"(show (me )?)?(the )?(progress|status report)", r"progresso|andamento",
)
STATE_RE = re.compile("|".join(f"(?:{form})" for form in STATE_QUESTIONS))
LISTED = 5                  # titles named in a sentence of a state answer
TITLE_CUT = 80


def chat_memory(messages: list, settled: set, quiet=frozenset()) -> str:
    """The conversation's memory for the router (the router's measured form; T23 workaround 2, kept on 2026-10-16: the adapter
    takes the request as one argument, and reading it on standard input is not proven, so the memory travels inside it, bounded): the plain lines and the router's replies after the newest
    reply whose request reached `planned`, `done` or `cancelled` (settled: those request ids); commands and their
    replies and the questions about the state (answered by code) are left out. The newest MEMORY_TURNS, oldest first, each `<role>: <text>` on one line cut to MEMORY_CUT
    characters, the whole cut to MEMORY_CHARS by dropping the oldest. Empty when there is none: the first line of an
    exchange reaches the router plain. `quiet`: the requests that code closed (`_close_by_code`) after it answered the line itself: their replies are neither a settled mark nor
    part of the memory, as they were when they were stored with no request (S4)."""
    # the conversation's memory as a bounded text in the request (T23, workaround 2, kept)
    start = 0
    for n, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("task_id") in settled:
            start = n + 1
    private = ops_natural.private_ids(messages)      # a reminder in a language no table ships: the router named it after the line was stored
    kept = [m for m in messages[start:] if (m["role"] == "user" and m.get("id") not in private and not m["text"].startswith("/") and not state_question(m["text"])
                                            and natural.match(m["text"]) is None and natural.candidate(m["text"]) is None
                                            and not ops_natural.is_placeholder(m["text"])) or
            (m["role"] == "assistant" and m.get("task_id") is not None and m.get("task_id") not in quiet)][-MEMORY_TURNS:]
    lines = [f"{m['role']}: {' '.join(m['text'].split())[:MEMORY_CUT]}" for m in kept]
    while lines and len("\n".join([MEMORY_HEAD, *lines])) > MEMORY_CHARS:
        lines.pop(0)
    return "\n".join([MEMORY_HEAD, *lines]) if lines else ""


def say(project: str, text: str, channel: str | None = None, sender: str | None = None, can_send: dict | None = None) -> dict:
    """One turn of the conversation with the planning agent (decision D12), one more shell of this layer. The person's
    line is stored (for a messaging sender whom the interpreter reads, AFTER the decision and as a neutral word unless it went to the planning agent: runtime/ops_interpret.py, limit L63); a line that starts with "/" is one command of the table of operations (runtime/operations.py), which calls its operation once; a plain
    line that asks about the state (STATE_QUESTIONS) is answered at once by code from the store's records (state_reply):
    no model, no request; any other plain line answers the router's open question on the conversation's last request,
    or else is a new request routed with the conversation's memory in front of it (one or more runs of the router: a
    model call), refused when the planning agent may not start. A line that would route while the router answers
    another request of the project (it holds the route lock) is queued, not refused, when the shell that carries it drains the queue (QUEUING_CHANNELS:
    the local service): it is stored, its reply is pending (`queued` true, `reply` None), and `route_queued` answers it
    when the lock is free; it also waits when older entries still wait, so that the queue is first in, first out. A shell that drains nothing (the terminal, the conversation's own shell, the MCP mode) is
    refused (RunBusy, code 1) before anything is stored, as it always was. A reply of the router that is a direct turn is answered
    by code too, and the request the line recorded is cancelled by code. The reply is stored too. A model's reply is
    shown, never executed.
    `channel` is the shell that carries the line (the terminal, the local page, the MCP mode; the conversation's own
    shell passes none and is `chat`): a command in the line is done only when its row lists that channel, so a shell
    that may not approve, reject, retry or cancel cannot do it by typing the command here either. `sender` (POL-2) is the messaging sender who typed the
    line (`<platform>:<sender id>`, operations.sender_key): a command in it is checked against THAT sender's profile and done as that sender.
    `can_send` (S18) is what the messaging bridge says its app can carry as a file (the provider's capabilities: ops_file_read._limits); only the bridge passes it, and only a messaging
    call keeps it. A reply that carries a file hands it back in "attachment" ({"name", "kind", "data"}: bytes in memory, for the bridge to send and drop; never stored).
    Returns {"reply", "request_id", "pending_id", "ran", "queued"}."""
    channel = channel or "chat"
    ops_actor.require(channel, sender)
    ctx = core.context(project)
    said = core._text(text, "the line")
    store = ctx["store"]
    importlib.import_module("event_lookup").begin_turn(ctx, channel, sender)      # S11: a list of events is valid for the line right after it
    importlib.import_module("ops_file_read").begin_turn(ctx, channel, sender)      # S17: so is a list of files
    handled = asks_natural(ctx, said, channel, sender) and not ops_natural.peek_model(ctx, said, _natural_channel(channel), sender) or _greets(ctx, said, channel, sender) or (channel == "messaging" and may_talk(ctx, channel, sender) and phone_delete.asks(said))      # S14b: a request to delete a file is answered by code, so it waits for no run and no queue. S5: a greeting is answered by code too, never queued
    if _turn_routes(said) and not asks_state(ctx, said, channel, sender) and not handled:
        # First in, first out: for a shell that queues, a line behind older entries waits behind them even when the
        # router is free again; a shell that drains nothing is refused while the router answers another request.
        if channel in QUEUING_CHANNELS and (route_busy(ctx) or _queue_read(ctx, peek=True)):
            stored = _enqueue_line(ctx, said)
            return {"reply": None, "request_id": None, "pending_id": None, "ran": False, "queued": True,
                    "message_id": stored["id"]}
        if channel not in QUEUING_CHANNELS and route_busy(ctx):
            raise core.RunBusy(RUN_BUSY, 1)
    kept = ops_natural.stored_line(ctx, said, _natural_channel(channel), sender)
    # A plain line of a sender whom the interpreter reads (S1, limit L63) is stored AFTER the decision: as a neutral word unless the interpreter sent it to the planning agent
    # (`extras["interpreted"]`), so that a line the model service read is never kept in the store. Every other line is stored first, as it always was.
    deferred = not said.startswith("/") and importlib.import_module("ops_interpret").enabled(ctx, channel, sender)
    stored = None if deferred else core._stored(ctx, store.message_add, conversation=CONVERSATION, role="user", text=kept)
    extras = {"deferred": True} if deferred else {}
    if can_send is not None and channel == "messaging":
        extras["can_send"] = can_send
    try:
        reply, request_id, pending_id, ran, run_id, offered = _turn(project, ctx, said, channel, stored["id"] if stored else None, sender, extras)
    finally:
        if deferred:
            core._stored(ctx, store.message_add, conversation=CONVERSATION, role="user", text=phrases.text("IX_PRIVATE_LINE", ctx["cfg"]) if extras.get("interpreted") else kept)
    core._stored(ctx, store.message_add, conversation=CONVERSATION, role="assistant",
                 text=extras.get("stored") or reply or phrases.text("NO_REPLY", ctx["cfg"]), task_id=extras.get("task_id", request_id), run_id=extras.get("run_id", run_id))
    return {"reply": reply, "request_id": request_id, "pending_id": pending_id, "ran": ran, "queued": False,
            **({"instruction_proposal": offered} if offered else {}), **({"resend": extras["resend"]} if "resend" in extras else {}),
            **({"attachment": extras["attachment"]} if channel == "messaging" and "attachment" in extras else {})}


def person_line(text: str) -> str:
    """The person's own line out of the text of a request: the text itself, or, for a line routed with the conversation's memory in front of it, the line
    after `MEMORY_TAIL`. The memory's lines are one line each, so the first marker is the real one; what a router names is believed against this line alone."""
    if text.startswith(MEMORY_HEAD):
        marker = f"\n\n{MEMORY_TAIL}\n"
        at = text.find(marker)
        if at >= 0:
            return text[at + len(marker):]
    return text


def _natural_channel(channel: str) -> str:
    """The channel a natural request is checked under: the queue's drain acts as the page (the one channel that queues)."""
    return "page" if channel == DRAIN else channel


def may_talk(ctx: dict, channel: str, sender=None) -> bool:
    """Whether the sender of a line may talk to the planning agent: a messaging sender needs the group `talk` (the bridge asks it for a plain line; the
    layer asks it again, so that a line admitted under another group - a read, a notice, the choice of a file - never reaches the router or answers its
    question). Every other channel is as it always was."""
    return channel != "messaging" or operations.permitted("say", channel, ctx["cfg"]["channels"], None, sender)


def asks_natural(ctx: dict, said: str, channel: str, sender=None) -> bool:
    """Whether a plain line is handled by code as a natural request (a tier-1 form, or the answer to the sender's draft): it runs no model, so it takes
    no route lock and is never queued. As with the state, an open question of the router means the line is its answer, unless the sender may not talk
    (a sender who may not talk never answers it) or the line is a request code recognises (LIVE-2: a new line, never the answer, for every sender, the interpreter's
    included). On a phone only the question bound to THIS sender counts (S4)."""
    natural_channel = _natural_channel(channel)
    if not ops_natural.peek(ctx, said, natural_channel, sender):
        return False
    return not may_talk(ctx, channel, sender) or _open_question(ctx, channel, sender) is None or ops_natural.recognises(ctx, said, natural_channel, sender)


def natural_reply(project: str, name: str, channel: str = "messaging") -> str:
    """The sentence for an operation a line only names and the platform does not run from a line (an effect on the person's accounts, a gated act): the place
    and the exact command (ops_natural._gated). The messaging bridge says it for a calendar event. Not an operation of the table."""
    return ops_natural._gated(core.context(project), name, {}, channel)


def natural_write(project: str, line: str, channel: str = "messaging", sender=None, seed=None) -> dict:
    """A line that asks for a write to the person's own accounts, for the messaging bridge (package NR-5): the sender's live question is answered, or the line is read as a
    write, or the seed (a reminder question answered "event", the loose verb's question, the caption of a file) is. It OPENS the card of the exact content and executes
    nothing (limit L61). Returns {"reply", "resend", "asked"}; `reply` is None when the line is no write and answers no question. Not an operation of the table."""
    return importlib.import_module("ops_natural_writes").natural_write(project, line, channel=channel, sender=sender, seed=seed)


def natural_draft(project: str, sender, channel: str = "messaging") -> bool:
    """Whether this sender has a live question about a write (the bridge asks it before it reads a line as new). Not an operation of the table."""
    return importlib.import_module("ops_natural_writes").has_live(project, channel, sender)


def natural_forget(project: str, sender, channel: str = "messaging") -> None:
    """Drop the sender's open question about a write (a line that answers nothing drops it). Not an operation of the table."""
    importlib.import_module("ops_natural_writes").forget(channel, sender)


def natural_file_accounts(project: str) -> list:
    """The accounts ("google", "microsoft") the project lists with folders, in that order: the places a file a sender sent can be saved to (package ATT-3; the card of a
    file draws one button for each). Not an operation of the table."""
    ctx = core.context(project)
    return importlib.import_module("ops_natural_writes").accounts_with(ctx, "folders")


def natural_needs(project: str, text: str, sender=None, channel: str = "messaging"):
    """The operation whose group a sender must hold for a plain line to be handled by code (ops_natural.needs), or None: the bridge asks it before it asks
    `talk`. Not an operation of the table."""
    return ops_natural.needs(core.context(project), text, channel, sender)


GREETING_FAMILIES = (      # S5: (phrase key, the operations and kinds one of which the sender's policy must permit) in the order the summary names them
    ("GREET_MAIL", (("ask", "mail"),)), ("GREET_REMIND", (("remind", None),)), ("GREET_CALENDAR", (("event-create", None),)), ("GREET_SEND", (("mail-send", None),)),
    ("GREET_ORGANIZE", (("mail-draft", None),)), ("GREET_FILES", (("file-create", None),)))
GREETING_APPROVALS = ("plan", "acceptance", "effect:calendar", "effect:send-own", "effect:send", "effect:mailbox", "effect:files", "effect:write", "effect:publish", "effect:create")


def _greets(ctx: dict, said: str, channel: str, sender=None) -> bool:
    """Whether a plain line is a greeting that `_turn` answers by code (S5): the whole line is one (runtime/greeting.py) and the sender may talk. It runs no model, so it takes no route lock and is never queued."""
    return not said.startswith("/") and greeting.is_greeting(said, helps=channel == "messaging") and may_talk(ctx, channel, sender)


def _greeting_reply(ctx: dict, channel: str, sender=None) -> str:
    """The answer to a greeting (S5): a greeting in the project's language, then one plain line for each family of capabilities that THIS sender's policy permits on the channel the line came on
    (`operations.permitted`), the approval of a card by a word on a messaging app, and, for a sender the interpreter reads, the line about asking in one's own words; a sender who may use none of
    them gets the one line that says a request may be sent in a sentence. No slash command and no id; it reads no store and no source."""
    cfg, channel = ctx["cfg"], _natural_channel(channel)
    policy = cfg["channels"]
    lines = [phrases.text(key, cfg) for key, forms in GREETING_FAMILIES if any(operations.permitted(op, channel, policy, kind, sender) for op, kind in forms)]
    if channel == "messaging" and any(operations.permitted("approve", channel, policy, kind, sender) for kind in GREETING_APPROVALS):
        lines.append(phrases.text("GREET_APPROVE", cfg))
    if importlib.import_module("ops_interpret").enabled(ctx, channel, sender):
        lines.append(phrases.text("GREET_OWN_WORDS", cfg))
    return "\n".join([phrases.text("GREET_HEAD", cfg)] + (lines or [phrases.text("GREET_ASK_WORK", cfg)]))


def _turn(project: str, ctx: dict, said: str, channel: str, line_id: int, sender=None, extras=None) -> tuple:
    """(reply, request_id, pending_id, ran, run_id, proposal) of one stored line of the person: a command, a question about the
    state, the answer to the router's question, or a new request. `line_id` is the line's message id: the memory
    the router is given is the messages before it. proposal is None, or the proposal to add the line to the project's
    instructions (runtime/ops_instructions.py proposal) that an answer to the router's question may end with: its text
    closes the reply, and the line is the person's own text, never the reply's."""
    if said.startswith("/"):
        out = _say_command(project, ctx, said, channel, line_id, sender)
        parsed = operations.parse_chat(said)
        if extras is not None and parsed is not None and ops_natural.keeps_private(ctx, parsed[0], channel, sender):      # the card's private lines were drawn for this sender: the conversation keeps a word
            extras["stored"] = phrases.text("NAT_READ_REPLY", ctx["cfg"])
        return (*out, None)
    talks = may_talk(ctx, channel, sender)
    extras = extras if extras is not None else {}
    if talks and greeting.is_greeting(said, helps=channel == "messaging"):      # S5: a greeting, or a plain request for help, is answered by code before any open question and any model: never the answer to the router's question
        return _greeting_reply(ctx, channel, sender), None, None, False, None, None
    if talks and channel == "messaging" and phone_delete.asks(said):      # a file is not deleted from a message yet (S14, S14b): one plain sentence, no card, no request, no model, before an open question (a request to delete is never its answer), the lists of code and the interpreter
        return phrases.text("PHONE_NO_FILE_DELETE", ctx["cfg"]), None, None, False, None, None
    asked = _open_question(ctx, channel, sender) if talks else None      # a sender who may not talk never answers the router's question; on a phone it is the question bound to this sender (S4)
    if asked is not None and ops_natural.recognises(ctx, said, _natural_channel(channel), sender):      # a request code recognises is a new line, never the answer (LIVE-2), for the interpreter's senders too
        asked = None
    framed = asked is not None and bool(extras.get("deferred"))      # S4: of the lines no list of code claims, the interpreter tells the answer from a new line, by a typed frame (decision 229 (1))
    if asked is None and state_question(said):
        if channel == "messaging" and not operations.permitted("status", channel, ctx["cfg"]["channels"], None, sender):
            return phone_refusal.said(operations.not_enabled('status', channel), channel, ctx["cfg"]), None, None, False, None, None      # the state is read, so a profile that reads nothing is not told it
        return state_reply(project, cfg=ctx["cfg"]), None, None, False, None, None
    if asked is None:      # a tier-1 form or the answer to a draft: code, no model, no route lock (package NR-2); any other line drops the sender's draft
        natural_reply = ops_natural.take(project, ctx, said, _natural_channel(channel), sender, extras)
        if natural_reply is not None:
            return natural_reply, None, None, False, extras.get("run_id"), None
    if not talks:      # admitted under another group, and no form of it took the line: it is not a model's, so it is refused as the typed `talk` is
        return phone_refusal.said(operations.refusal('say', channel, ctx['cfg']['channels'], sender=sender), channel, ctx["cfg"]), None, None, False, None, None
    if extras.get("deferred"):      # S1 (limit L63): a plain line of a sender the interpreter reads, which no list of code took (the hybrid order of 2026-10-21)
        if framed:
            extras["frame_age"] = _question_age(ctx, sender)      # the typed frame's one item is built from this age alone (runtime/ops_interpret.py `router_frame`)
        read = importlib.import_module("ops_interpret").turn(project, ctx, said, sender, extras)
        if read is not None:
            return (*read, None)
        if framed and extras.get("frame") == "new":
            asked = None      # S4: the model said `route`: a new request
    out = _say_route(project, ctx, said, line_id, channel, answer_to=asked, sender=sender, extras=extras)
    if asked is not None and channel == "messaging":      # the person is told what their line was taken for
        out = (phrases.text("ANSWER_TAKEN", ctx["cfg"], id=asked) + "\n\n" + out[0], *out[1:])
    offered = importlib.import_module("ops_instructions").proposal(ctx, out[1], said, channel) if asked is not None else None
    return (out[0] + "\n\n" + offered["text"], *out[1:], offered) if offered else (*out, None)


def _turn_routes(said: str) -> bool:
    """Whether a line makes a turn that runs a conversation model call (the router, or the answer run of /ask) under the route lock: a plain
    line, /new or /ask. Any other command of the table calls its own operation, which takes the locks it needs itself, and a line that
    is no command gets the help."""
    if not said.startswith("/"):
        return True
    parsed = operations.parse_chat(said)
    return parsed is not None and parsed[0] in ("new", "ask")


# --- the questions about the state, answered by code ------------------------------------------------------------------


def _normal(text: str) -> str:
    """Lower case, no accents, every run of other characters one space."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def state_question(said: str) -> bool:
    """Whether a plain line is one of the forms of STATE_QUESTIONS, in English or Portuguese, and short: the whole
    line is the form (with, for some, a tail of at most six words that names what the question is about). A line that
    starts like one and goes on to ask for work is not: "how are we going to launch the site", a line with a sentence
    mark inside it (only a final `?`, `.` or `!` is allowed), or a tail that holds a verb of work."""
    if said.startswith("/"):
        return False
    if INTERIOR_MARK.search(said.strip().rstrip("?.! \t")):
        return False
    normal = _normal(said)
    return bool(normal) and len(normal.split()) <= STATE_WORDS and STATE_RE.fullmatch(normal) is not None \
        and not WORK_WORDS & set(normal.split())


def asks_state(ctx: dict, said: str, channel=None, sender=None) -> bool:
    """Whether a plain line is answered as a question about the state: it is one of the forms, and the router has no
    open question on the conversation's last request (a one-word answer such as "progress" then reaches the router)."""
    return state_question(said) and _open_question(ctx, channel, sender) is None


def _short(text) -> str:
    one = " ".join(str(text or "").split())
    return one if len(one) <= TITLE_CUT else one[:TITLE_CUT - 1].rstrip() + "..."


PLAIN_TITLES = {"TITLE_ROUTER_ASKS": "PEND_CARD_TITLE", "TITLE_ROUTE_UNRECOGNISED": "PEND_NOT_UNDERSTOOD_TITLE"}      # the titles that name the platform's internals, said as what they mean


def _title(text, cfg=None) -> str:
    """A request's or a decision's title for a person: a title code wrote whole (a card's, "Mail: send from your account") in the project's language, the router's own titles as plain
    words, any other title (the person's or a model's) as it is; then cut (S14)."""
    said = phrases.heading(text, cfg)
    for key, plain in PLAIN_TITLES.items():
        if text == phrases.en(key):
            said = phrases.text(plain, cfg)
    return _short(said)


def _names(rows: list, cfg=None) -> str:
    """'a, b, c and 2 more' for the titles of rows."""
    titles = [_title(r["title"], cfg) for r in rows]
    shown = ", ".join(titles[:LISTED])
    return shown + (phrases.text("NAMES_MORE", cfg, n=len(titles) - LISTED) if len(titles) > LISTED else "")


def state_reply(project: str, proposed: str | None = None, cfg: dict | None = None) -> str:
    """Where the project stands, in prose, written by code from `status` and `progress` (the store's records): for each
    open request what finished, what runs, what waits for the person, what is ready or held, and what is stuck, then
    what waits for the person across the project. No model is called and nothing is estimated: every number and name
    is a value of the two reads. `proposed`, the router's `Next` line of a direct turn, closes it as what the planning
    agent proposes. The sentences are the phrase table's, in the project's language (`cfg`, read from the project when not given)."""
    cfg = cfg if cfg is not None else core._config_of(project)
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    state, progress = _ops().status(project), _ops().progress(project)["progress"]
    held = {h["task_id"]: h["reason"] for h in state.get("held") or []}
    lines = []
    open_requests = [r for r in state["requests"] if r["state"] not in ("done", "cancelled")]
    for r in open_requests:
        tasks = r["tasks"]
        by = lambda *states: [t for t in tasks if t["state"] in states]  # noqa: E731
        title = _title(r["title"], cfg)
        if r["state"] == "requested":
            lines.append(t("STATE_RECORDED", id=r["id"], title=title))
            continue
        done = by("done")
        lines.append(t("STATE_PROGRESS", id=r["id"], title=title, done=len(done), total=len(tasks), names=f" ({_names(done, cfg)})" if done else ""))
        for key, rows in (("STATE_RUNNING", by("running")), ("STATE_WAITING", by("waiting"))):
            if rows:
                lines.append(t(key, names=_names(rows, cfg)))
        for task in by("ready"):
            lines.append(t("STATE_READY", id=task["id"], title=_title(task["title"], cfg),
                           held=t("STATE_HELD", reason=held[task["id"]]) if task["id"] in held else ""))
        for task in by("blocked", "failed"):
            note = f': {_short(task["note"])}' if task.get("note") else ""
            lines.append(t("STATE_STUCK", id=task["id"], title=_title(task["title"], cfg), state=phrases.status(task["state"], cfg), note=note))
    if not open_requests:
        finished = sum(1 for r in state["requests"] if r["state"] == "done")
        lines.append(t("STATE_NONE_OPEN") + (t("STATE_FINISHED", n=finished) if finished else ""))
    waiting = [t("STATE_WAIT_ITEM", kind=phrases.kind_word(w["kind"], cfg), title=_title(w["title"], cfg), id=w["pending_id"]) for w in progress["waiting_for_you"]]
    lines.append(t("STATE_WAITS", items="; ".join(waiting) if waiting else t("STATE_NOTHING")))
    if proposed:
        lines += ["", t("PROPOSES") + proposed]
    return "\n".join(lines)


# --- the queue: what waits for the planning agent while a run holds the project ---------------------------------------


@contextlib.contextmanager
def _queue_lock(cfg: dict):
    """The queue's file lock (<data_dir>/queue.lock), held while the queue is read and written: the service's threads
    and the terminal take it one after the other. Waits up to QUEUE_LOCK_WAIT seconds, then refuses."""
    os.makedirs(cfg["data_dir"], mode=0o700, exist_ok=True)
    lock = os.open(os.path.join(cfg["data_dir"], QUEUE_LOCK_NAME), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + QUEUE_LOCK_WAIT
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise core.OpsError("the queue is being changed by another process: try again in a moment", 1) from None
                time.sleep(0.05)
        yield
    finally:
        os.close(lock)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _queue_read(ctx: dict, peek: bool = False) -> list:
    """The queue, oldest first: [{"kind": "line", "id": message id} | {"kind": "route", "id": request id}], each with
    "at" and, once a drain took it, STARTED. `peek` reads with no write lock (the conversation read)."""
    read = ctx["store"].cursor_peek if peek else ctx["store"].cursor_get
    try:
        value = json.loads(core._stored(ctx, read, QUEUE) or "[]")
    except ValueError:
        return []
    return [e for e in value if isinstance(e, dict) and e.get("kind") in ("line", "route") and isinstance(e.get("id"), int)]


def _queue_write(ctx: dict, entries: list) -> None:
    core._stored(ctx, ctx["store"].cursor_set, QUEUE, json.dumps(entries, separators=(",", ":")))


def waiting(ctx: dict) -> bool:
    """Whether any line or request waits in the queue."""
    return bool(_queue_read(ctx, peek=True))


def queued_ids(ctx: dict) -> set:
    """The ids of the messages of the person that wait in the queue for their reply."""
    return {e["id"] for e in _queue_read(ctx, peek=True) if e["kind"] == "line"}


def route_busy(ctx: dict) -> bool:
    """Whether a run of the router holds the project's route lock now. A run of a task never does: a line typed during a
    task run is routed at once."""
    fd = core._try_lock(ctx["cfg"], "route.lock")
    if fd is None:
        return True
    os.close(fd)
    return False


def _full(entries: list):
    if len(entries) >= QUEUE_MAX:
        raise core.OpsError(f"{QUEUE_MAX} lines or requests already wait for the end of the run: nothing was stored", 1)


def _enqueue_line(ctx: dict, said: str) -> dict:
    """Store the person's line and queue it; refused (nothing stored) when the queue is full."""
    with _queue_lock(ctx["cfg"]):
        entries = _queue_read(ctx)
        _full(entries)
        stored = core._stored(ctx, ctx["store"].message_add, conversation=CONVERSATION, role="user", text=said)
        _queue_write(ctx, entries + [{"kind": "line", "id": stored["id"], "at": _now(), "group": "talk"}])
    return stored


def queue_route(ctx: dict, request_id: int) -> dict:
    """Queue a request for the router (`route` while the router answers another request): recorded once, routed when the lock is free.
    The entry stores the policy group that created it (`request`: the person asked for the route; `_say_route` re-tags it `talk`
    when a line made the request), which the drain checks again under the page's policy. Returns what `route` answers for it: {"routed": False, "queued": True, "request", "pending_id": None}."""
    with _queue_lock(ctx["cfg"]):
        entries = _queue_read(ctx)
        if not any(e["kind"] == "route" and e["id"] == request_id for e in entries):
            _full(entries)
            _queue_write(ctx, entries + [{"kind": "route", "id": request_id, "at": _now(), "group": "request"}])
    return {"routed": False, "queued": True, "request": request_id, "pending_id": None, "source": "queue"}


def _retag(ctx: dict, kind: str, ident: int, group: str) -> None:
    """Set the policy group of a queued entry (under the queue lock; the other keys stay)."""
    with _queue_lock(ctx["cfg"]):
        entries = _queue_read(ctx)
        for e in entries:
            if e["kind"] == kind and e["id"] == ident:
                e["group"] = group
        _queue_write(ctx, entries)


def _drain_refusal(ctx: dict, head: dict):
    """The sentence that refuses a queued entry under the page's policy as it is now (the only channel that queues), or
    None. The entry stores the group that created it (`talk` for a line, `request` for a route); an entry queued before
    the group was stored is a line (`talk`) or a route (`request`). The drain acts as DRAIN to keep the queue first in,
    first out; the policy it answers to is the page's."""
    group = head.get("group") if head.get("group") in QUEUE_GROUPS else ("talk" if head["kind"] == "line" else "request")
    return operations.refusal(QUEUE_GROUPS[group], "page", ctx["cfg"]["channels"])


def _unqueue(ctx: dict, kind: str, ident: int) -> None:
    with _queue_lock(ctx["cfg"]):
        _queue_write(ctx, [e for e in _queue_read(ctx) if not (e["kind"] == kind and e["id"] == ident)])


def queue_stale() -> float:
    """Seconds after which an entry a process took is taken to be what a dead process left, and is dropped: the run
    timeout the gate file gives (the value the runtime uses for a run, lab.reference) plus QUEUE_STALE_MARGIN. It is the
    one bound a router run cannot exceed, so a live run is never called dead while it holds the lock; only one entry is
    in flight, so a dead one blocks the others for no longer."""
    try:
        return float(lab.reference()["timeout_seconds"]) + QUEUE_STALE_MARGIN
    except (lab.LabError, KeyError, TypeError, ValueError):
        return QUEUE_STALE_FALLBACK + QUEUE_STALE_MARGIN


def _take(ctx: dict):
    """The oldest entry no process has taken, marked as taken now; None when there is none. A taken entry older than
    queue_stale() seconds is what a process that died left: it is dropped, and the person is told when it was a line."""
    now, stale = time.time(), queue_stale()
    with _queue_lock(ctx["cfg"]):
        entries = _queue_read(ctx)
        dead = [e for e in entries if now - e.get(STARTED, now) > stale]
        entries = [e for e in entries if e not in dead]
        # one entry at a time, oldest first: while one is taken (by the service loop or by `route-queued`), none is
        head = None if any(STARTED in e for e in entries) else next(iter(entries), None)
        if head is not None:
            head[STARTED] = now
        if head is not None or dead:
            _queue_write(ctx, entries)
    for e in dead:
        if e["kind"] == "line":
            core._stored(ctx, ctx["store"].message_add, conversation=CONVERSATION, role="assistant",
                         text=phrases.text("QUEUE_DEAD_LINE", ctx["cfg"]))
        else:
            _note_request(ctx, e["id"], phrases.text("QUEUE_DEAD_WHY", ctx["cfg"]))
    return head


def _note_request(ctx: dict, request_id: int, why: str) -> None:
    """Tell the person, in the conversation and on the request, why a queued request was not routed, so that the
    request that stays on "Route it" does not look forgotten."""
    try:
        core._stored(ctx, ctx["store"].message_add, conversation=CONVERSATION, role="assistant", task_id=request_id,
                     text=phrases.text("REQUEST_NOT_ROUTED", ctx["cfg"], id=request_id, why=why))
    except core.OpsError:
        pass


def _untake(ctx: dict, head: dict) -> None:
    with _queue_lock(ctx["cfg"]):
        entries = _queue_read(ctx)
        for e in entries:
            if e["kind"] == head["kind"] and e["id"] == head["id"]:
                e.pop(STARTED, None)
        _queue_write(ctx, entries)


def route_queued(project: str) -> dict:
    """Answer the oldest queued line or route the oldest queued request, when the router is free: one
    per call (the local service calls it every few seconds, the oldest first). A line is answered as `say` answers it
    (the router's memory is the messages before it), its reply stored; a request is routed as `route` routes it, its
    plan or question left for the person. Returns {"routed": "line" | "route" | None, "queued": what still waits, ...}."""
    ctx = core.context(project)
    if not _queue_read(ctx, peek=True):
        return {"routed": None, "queued": 0}
    if route_busy(ctx):
        return {"routed": None, "queued": len(_queue_read(ctx, peek=True)), "reason": "the planning agent is answering another request"}
    head = _take(ctx)
    if head is None:
        left = len(_queue_read(ctx))
        return {"routed": None, "queued": left, **({"reason": "another process is routing the first"} if left else {})}
    answered, out = False, None
    try:
        refused = _drain_refusal(ctx, head)  # the policy as it is now, after any accept-config
        if refused:
            raise core.OpsError(refused, 1)
        out = _drain_line(project, ctx, head["id"]) if head["kind"] == "line" else _drain_route(project, ctx, head["id"])
        answered = True
    except core.RunBusy:  # the lock was taken between the check and the run: the entry waits again
        _untake(ctx, head)
        return {"routed": None, "queued": len(_queue_read(ctx)), "reason": "the planning agent is answering another request"}
    except core.OpsError as e:  # the line or the request can no longer be routed (cancelled, answered elsewhere)
        try:
            if head["kind"] == "line":
                core._stored(ctx, ctx["store"].message_add, conversation=CONVERSATION, role="assistant",
                             text=phrases.text("QUEUE_DROPPED_LINE", ctx["cfg"], why=str(e)))
            else:
                _note_request(ctx, head["id"], str(e))
        finally:
            _unqueue(ctx, head["kind"], head["id"])
        return {"routed": None, "queued": len(_queue_read(ctx)), "dropped": {"kind": head["kind"], "id": head["id"]},
                "reason": str(e)}
    finally:
        if answered:  # an entry that was answered is never left behind to be reported as "not answered" later
            _unqueue(ctx, head["kind"], head["id"])
    return {**out, "queued": len(_queue_read(ctx))}


def _drain_line(project: str, ctx: dict, message_id: int) -> dict:
    found = [m for m in core._stored(ctx, ctx["store"].messages_list, CONVERSATION, limit=500, after_id=message_id - 1)
             if m["id"] == message_id]
    if not found:
        raise core.OpsError(f"message {message_id} is not in the conversation", 1)
    extras = {}
    reply, request_id, pending_id, ran, run_id, offered = _turn(project, ctx, found[0]["text"], DRAIN, message_id, None, extras)
    core._stored(ctx, ctx["store"].message_add, conversation=CONVERSATION, role="assistant",
                 text=extras.get("stored") or reply or phrases.text("NO_REPLY", ctx["cfg"]), task_id=extras.get("task_id", request_id), run_id=extras.get("run_id", run_id))
    return {"routed": "line", "message_id": message_id, "request_id": request_id, "pending_id": pending_id, "ran": ran,
            **({"instruction_proposal": offered} if offered else {})}


def _drain_route(project: str, ctx: dict, request_id: int) -> dict:
    done = _ops()._route_request(ctx, request_id)
    if done.get("kind") == "operation":      # the router named an operation of the table (NR-2): not dropped, and not left on "Route it": it is answered as a line would be
        line = person_line(core._stored(ctx, ctx["store"].task_get, request_id)["text"])
        _close_by_code(ctx, request_id, "code:operation")
        extras = {}
        reply = ops_natural.run_routed(project, ctx, done["operation"], line, _natural_channel(DRAIN), None, extras)
        core._stored(ctx, ctx["store"].message_add, conversation=CONVERSATION, role="assistant",
                     text=extras.get("stored") or reply or phrases.text("NO_REPLY", ctx["cfg"]), task_id=request_id, run_id=extras.get("run_id", done.get("run_id")))
        return {"routed": "route", "request_id": request_id, "pending_id": None, "ran": True, "operation": done["operation"]["name"]}
    return {"routed": "route", "request_id": request_id, "pending_id": done.get("pending_id"), "ran": True}


def _plan_line(task: dict, cfg, channel) -> str:
    """One task of a plan's reply: `- key: title (skill)`; on a phone the skill's name is its plain label, or left out when it has none (S14: no identifier of this machine)."""
    line = f"- {task['key']}: {task['title']} ({task.get('skill') or phrases.text('PLAN_STEP', cfg, step=task['step'])})"
    return phone_questions.scrub(line, cfg) if channel == "messaging" else line


def _close_by_code(ctx: dict, request_id: int, by: str) -> None:
    """Cancel a request that code answered itself (`by` starts with `code:`) and mark it, so that the router's memory does not read it as a settled exchange (S4)."""
    _close_request(ctx, request_id, by)


def _close_request(ctx: dict, request_id: int, by: str) -> dict:
    """The cancel of `_close_by_code` for any label (the person who dismissed a question is `by`, S14): the store's answer, {"request", "cancelled", "pending", ...}."""
    import ops_cancel      # at call time, like the other operations this sibling reaches
    done = core._stored(ctx, ops_cancel.request_cancel, request_id, by=by, context=ctx)
    core._stored(ctx, ctx["store"].cursor_set, CODE_CLOSED.format(id=request_id), "1")
    return done


def _last_request(ctx: dict):
    """The request of the conversation's newest message that names one, or None."""
    for m in reversed(core._stored(ctx, ctx["store"].messages_list, CONVERSATION, limit=500)):
        if m.get("task_id") is not None:
            return m["task_id"]
    return None


def _open_question(ctx: dict, channel, sender=None):
    """The router's open question that a plain line on this channel may answer. On a messaging app it is the question BOUND to this sender (S4, decision 229 (1) of 2026-10-20):
    asked of them, on this channel, within pending_items.ROUTER_WINDOW (one hour), nothing cancelled when it runs out; another sender, another channel or a restart finds none. The
    other channels keep the conversation's question - the router's open question on its last request - until it is answered or cancelled, as they always did."""
    if channel == "messaging":
        return _bound_question(ctx, sender)
    return _router_question(ctx, _last_request(ctx))


def _binding_key(ctx: dict, sender) -> tuple:
    return (ops_natural.project_key(ctx["cfg"]["project"]), "messaging", sender or "")


def _age_s(asked_at):
    """Seconds since a decision was made, by the clock of the store (`_question_clock`), or None when its time cannot be read."""
    try:
        return (_question_clock() - datetime.datetime.fromisoformat(str(asked_at).replace("Z", "+00:00"))).total_seconds()
    except (ValueError, TypeError):
        return None


def _bound_question(ctx: dict, sender):
    """The id of the router question bound to this sender, or None: the key's binding exists, its decision is still open and still the newest question of its request, and it is
    less than ROUTER_WINDOW old. A time that cannot be read keeps the question, as it always did. A read: nothing is changed or cancelled here."""
    found = pending_items.items(_binding_key(ctx, sender))
    if not found:
        return None
    item = found[0]
    asked = item["subject"][1]
    if _router_question(ctx, item["state"]["request_id"]) != asked:
        return None
    age = _age_s(item["state"]["asked_at"])
    return asked if age is None or age < pending_items.ROUTER_WINDOW else None


def _question_age(ctx: dict, sender) -> int:
    """The age in seconds of the sender's bound question for the typed frame: 0 to 86400 (0 when the time cannot be read)."""
    found = pending_items.items(_binding_key(ctx, sender))
    age = _age_s(found[0]["state"]["asked_at"]) if found else None
    return 0 if age is None else int(min(max(age, 0), 86400))


def _router_question(ctx: dict, request_id):
    """The newest open pending decision of the request, when it is a question on the request itself (the router
    asked); else None."""
    if request_id is None:
        return None
    request = core._stored(ctx, ctx["store"].task_get, request_id)
    if request["parent_id"] is not None or request["state"] != "requested":
        return None
    open_items = core._stored(ctx, ctx["store"].pending_list, "open", request_id)
    return open_items[-1]["id"] if open_items and open_items[-1]["kind"] == "question" else None


def _say_command(project: str, ctx: dict, said: str, channel: str, line_id: int, sender=None) -> tuple:
    """(reply, request_id, pending_id, ran, run_id) of a command line: the table of operations reads it
    (operations.parse_chat); an operation it names is called once with the arguments it read, when its row lists the
    channel that carries the line (`channel`) and the project's policy permits the command under that channel
    (operations.refusal with the carrying channel: page, mcp or messaging, never `chat`): a command that row does not
    list is refused with the place where it is done, a line it does not read gets the help. An effect is never approved
    from a line, by any channel and whatever the policy: the decision's kind is read first and an effect is refused, and
    the operation is called as `chat` (or `messaging`), which refuses an effect too."""
    parsed = operations.parse_chat(said)
    if parsed is None or parsed[0] == "help":
        return operations.chat_help(), None, None, False, None
    name, found = parsed
    if name == "new":
        after, found = operations.split_new(found)
        return _say_route(project, ctx, found, line_id, channel, after=after, sender=sender)
    if name == "ask" and channel == DRAIN:       # a queued /ask is answered on the page that queued it (the only channel that queues)
        channel = "page"
    row = operations.by_name(name)
    if channel not in row["channels"]:
        if channel == "messaging":      # a phone has no terminal (limit L62)
            return ops_natural.phone_sentence(ctx, name), None, None, False, None
        return f"error: /{name} is done in the terminal or on the page", None, None, False, None
    policy = ctx["cfg"]["channels"]
    refused = operations.refusal(name, channel, policy, sender=sender)  # the project's policy, under the channel that carries the line (and the sender's profile)
    if refused:
        return phone_refusal.said(refused, channel, ctx["cfg"]), None, None, False, None
    if channel == "messaging" and name == "approve":  # an acceptance approved from a line has no card to be bound to
        return "error: use the card's button, or /approve <id> as the whole line", None, None, False, None
    if name == "approve":  # the decision's kind is read first: the policy covers a kind, and an effect is never approved from a line
        try:
            kind = core._stored(ctx, ctx["store"].pending_get, found["pending_id"])["kind"]
        except core.OpsError as e:
            return f"error: {e}", None, None, False, None
        if kind == "effect" and channel == "messaging":  # a phone is told where, never the command or the hash (limit L62)
            return phrases.phone("PHONE_APPROVE_EFFECT", ctx["cfg"]), None, None, False, None
        if kind == "effect":  # from a line, on any channel and whatever the policy
            return ("error: an effect is approved in the terminal, with its hash: "
                    + core._command("approve", ctx["cfg"]["project"], pending_id=found["pending_id"], sha256="<hash>")), None, None, False, None
        refused = operations.refusal(name, channel, policy, kind, sender=sender)
        if refused:
            return phone_refusal.said(refused, channel, ctx["cfg"]), None, None, False, None
    function = getattr(_ops(), row["call"])
    if row.get("channel_arg"):
        found = dict(found, channel=channel if channel == "messaging" else "chat")  # a messaging app's own rule (ops_waits) narrows approve
        if channel == "messaging":
            if "sender" not in inspect.signature(function).parameters:       # an operation that cannot be told who acts would be asked for the channel alone
                return f"error: /{name} is not done from a messaging app", None, None, False, None
            found["sender"] = sender       # the operation asks the policy, and records the actor, for THIS sender
    try:
        with ops_actor.carried_by(channel):
            out = function(project, **found)
    except core.OpsError as e:
        return f"error: {e}", None, None, False, None
    if name == "ask":
        ops_natural.keep_which(ctx, _natural_channel(channel), sender, found["text"], out)      # the files to choose from: the next line may be the number of one
    if name == "ask" and out.get("run_id") is not None:
        # The answer is stored with the id of its answer run and no request (so it is not the router's memory): `conversation` shows it only
        # to the channel that asked (ops_ask.asked_by), and every other reader gets ANSWERED_AS (limit L50).
        return out["reply"], None, None, False, out["run_id"]
    if row.get("chat_reply"):
        return out[row["chat_reply"]], None, None, False, None
    return json.dumps(_phone_view(out) if channel == "messaging" else out, ensure_ascii=False, indent=1, default=str), None, None, False, None


PHONE_HIDDEN_KEYS = ("command", "commands", "path", "dir", "folder")      # the fields of an operation's result that are the platform's own terminal commands or paths of this machine


def _phone_view(value):
    """An operation's result as a messaging app is shown it (LIVE-2, limit L62): the fields that hold a terminal command or a path of this machine are left out, by name (a
    held task's `next` is its command), and nothing else is touched. The terminal, the page and the conversation get the result whole."""
    if isinstance(value, dict):
        held = "reason" in value and "task_id" in value
        return {k: _phone_view(v) for k, v in value.items() if k not in PHONE_HIDDEN_KEYS and not (held and k == "next")}
    if isinstance(value, list):
        return [_phone_view(v) for v in value]
    return value


def _planning_may_start(ctx: dict) -> tuple:
    """Whether the planning agent may run the router now (autonomy.may_start, by the billing of the credential the
    router's route uses, with the day's runs of the router counted against it)."""
    cfg, store = ctx["cfg"], ctx["store"]
    agents = cfg["area_agents"]
    meta = skill_meta.declared(os.path.join(core.ROOT, "skills", router.ROUTER_SKILL))
    billing = _ops()._route(ctx, router.ROUTER_SKILL, meta, core._keys())["billing"]
    now = datetime.datetime.now(datetime.timezone.utc)
    standing_rows = core._stored(ctx, store.approvals_list, status="active", scope="standing")
    runs = autonomy.with_billing(core.attributed(core._stored(ctx, store.runs_since, _ops()._midnight_utc()),
                                                 importlib.import_module("ops_ask").run_owners(ctx)), core._metered_models())
    facts = autonomy.facts(plan.PLANNING, agents, standing_rows, now)
    spent = autonomy.spend(runs, plan.PLANNING, cfg["raw"].get("max_cost_usd_per_run", _ops().PER_RUN_USD))
    ok, why = autonomy.may_start(plan.PLANNING, agents, facts, spent, billing)
    if not ok and plan.PLANNING not in agents:
        why = "no planning agent is configured (area_agents has no entry named planning)"
    return ok, why


def _say_route(project: str, ctx: dict, said: str, line_id: int, channel: str, answer_to=None, after=None, sender=None, extras=None) -> tuple:
    """A plain line: the answer to the router's question (then the router runs again), or a new request with the
    memory in front of it (the messages before the line). Either way the router runs only when the planning agent may
    start. A reply of the router that is a direct turn cancels the request by code and is answered from the store's
    records, with the router's `Next` line; one that names no route opens the question of an unrecognised route."""
    ok, why = _planning_may_start(ctx)
    if not ok:
        return phrases.text("PLANNING_NOT_STARTED", ctx["cfg"], why=why), None, None, False, None
    extras = extras if extras is not None else {}
    line_stage.publish("plan")      # S19: the planning agent is about to work
    if channel == "messaging":      # the sender's bound question is being answered or replaced: a new one is bound below, when the router asks again (S4)
        pending_items.drop_key(_binding_key(ctx, sender))
    if answer_to is not None:
        request_id = core._stored(ctx, ctx["store"].pending_get, answer_to)["task_id"]
        _ops().answer(project, answer_to, said, actor=ops_actor.label(ctx["cfg"], channel, sender))
    else:
        messages = [m for m in core._stored(ctx, ctx["store"].messages_list, CONVERSATION, limit=500) if line_id is None or m["id"] < line_id]      # None: the line is not stored yet (S1), so every message so far is before it
        closed = {t["id"] for t in core._stored(ctx, ctx["store"].tasks_list) if t["parent_id"] is None and t["state"] == "cancelled"
                  and core._stored(ctx, ctx["store"].cursor_peek, CODE_CLOSED.format(id=t["id"])) is not None}      # cancelled by code after code answered: not a settled exchange
        settled = {t["id"] for t in core._stored(ctx, ctx["store"].tasks_list)
                   if t["parent_id"] is None and t["state"] in ("planned", "done", "cancelled") and t["id"] not in closed}
        remembered = chat_memory(messages, settled, closed)
        text = f"{remembered}\n\n{MEMORY_TAIL}\n{said}" if remembered else said
        request_id = _ops().request(project, text, title=plan.title_of(said), after=after)["request"]
    already = any(e["kind"] == "route" and e["id"] == request_id for e in _queue_read(ctx, peek=True))
    routed = _ops().route(project, request_id, channel=channel)
    if routed.get("queued"):  # the router was taken after the check: the request waits for the end of its run
        if not already:  # an entry that was queued before keeps the group that created it (never widened by a line)
            _retag(ctx, "route", request_id, "talk")  # a line made this request: the drain checks `talk`, not `request`
        return phrases.text("QUEUED_REQUEST", ctx["cfg"], request=request_id), request_id, None, False, None
    if routed.get("kind") == "direct":
        _close_by_code(ctx, request_id, "code:direct")
        extras["task_id"] = request_id      # the reply is stored under the request it closed, so that the next line is not taken for the answer to an older question (S4)
        if channel == "messaging" and routed.get("next"):      # a phone is told the answer alone: the digest of the state is for the person who asked for the state (S14)
            return phone_questions.clean(routed["next"], ctx["cfg"]) + importlib.import_module("ops_ask").hint(ctx, channel, sender), None, None, True, routed.get("run_id")
        return (state_reply(project, routed.get("next"), ctx["cfg"]) + importlib.import_module("ops_ask").hint(ctx, channel, sender),
                None, None, True, routed.get("run_id"))
    if routed.get("kind") == "operation":
        # An operation of the table of natural requests (NR-2): the router only named it. The request the line recorded is cancelled by code, and the
        # dispatcher believes the operation against the line the request holds, checks the policy as the typed command is, and executes it.
        line = person_line(core._stored(ctx, ctx["store"].task_get, request_id)["text"])
        _close_by_code(ctx, request_id, "code:operation")
        reply = ops_natural.run_routed(project, ctx, routed["operation"], line, _natural_channel(channel), sender, extras)
        extras["task_id"] = request_id      # an `ask` reply too: it is shown by its run (limit L50) and, the request being closed by code, it is no part of the router's memory
        return reply, None, None, True, extras.get("run_id", routed.get("run_id"))
    item = core._stored(ctx, ctx["store"].pending_get, routed["pending_id"]) if routed.get("pending_id") else None
    if item is None:
        failure = (routed.get("failure") or {}).get("reason") or "the router's run failed"
        if channel == "messaging":      # a phone is not told the layer's English reason, nor the router by name (S14)
            return phrases.text("PHONE_ROUTER_FAILED", ctx["cfg"]), request_id, None, True, routed.get("run_id")
        return phrases.text("ROUTER_FAILED", ctx["cfg"], failure=failure), request_id, None, True, routed.get("run_id")
    if item["kind"] == "plan":
        payload = item["payload"]
        lines = [item["title"]]
        lines += [_plan_line(t, ctx["cfg"], channel) for t in payload.get("tasks") or []]
        lines.append(language_rules.payload_line(payload))     # the language the plan writes in, before the person approves
        estimate = payload.get("estimate") or {}
        lines += [phrases.text("PLAN_ESTIMATE", ctx["cfg"], runs=estimate.get("runs", estimate.get("runs_at_least")))
                  + (f" ({estimate['formula']})" if estimate.get("formula") else ""), ""]
        for n, u in enumerate(payload.get("unrouted") or [], 1):
            lines += ([phrases.text("PHONE_NOT_PLANNED", ctx["cfg"], n=n, item=u["item"]), phone_questions.clean(u["reply"].rstrip("\n"), ctx["cfg"]), ""] if channel == "messaging"
                      else [phrases.text("PLAN_NOT_PLANNED", ctx["cfg"], n=n, item=u["item"]), u["reply"].rstrip("\n"), ""])
        lines.append(phrases.text("PLAN_NEXT", ctx["cfg"], pending=item["id"]))
        reply = "\n".join(lines)
    elif (item.get("payload") or {}).get("ending") == "unclassified":
        if channel == "messaging":      # a phone gets one plain sentence and nothing is left open: no command, no request number, the request cancelled by code (S1, limits L62 and L63)
            _close_by_code(ctx, request_id, "code:unclassified-phone")
            extras["task_id"] = request_id
            return phrases.text("PHONE_NOT_UNDERSTOOD", ctx["cfg"]), None, None, True, routed.get("run_id")
        tail = phrases.text("NOT_NAMED_NEXT", ctx["cfg"], request=request_id, route=core._command("route", project, request_id=request_id, flow="<name>"))
        reply = phrases.body(item["body"], ctx["cfg"]).rstrip("\n") + "\n\n" + tail
    else:
        shown = phrases.asked_view(item["body"], ctx["cfg"]) if channel == "messaging" and phrases.is_router_question(item) else item["body"]      # a phone shows the question and its framing, never the template around it
        reply = shown.rstrip("\n") + "\n\n" + phrases.text("ASK_NEXT_PHONE" if channel == "messaging" else "ASK_NEXT", ctx["cfg"])
        if channel == "messaging" and phrases.is_router_question(item):      # the question is bound to the person it was asked of, for one hour (S4, decision 229 (1))
            pending_items.put(pending_items.new_item("router", *_binding_key(ctx, sender), subject=["pending", item["id"]], state={"request_id": request_id, "asked_at": item.get("created_at")}))
    return reply, request_id, item["id"], True, routed.get("run_id")
