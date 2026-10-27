"""The scenario kit of the entry replay (package S41-1; PLAN-BRAIN section 4 step 1): one world, one pre-state, one line, one normalised outcome.

THE POINT. Later packages (S41-2 and on) move the ORDER in which the claimers of a line (the bridge's `_handle` and `say`, the operations layer's `ops_say.say`, `_turn` and
`ops_natural.take`; since S41-3 the rows of the stage `ops` of runtime/turn_order.py, dispatched by `ops_turn.dispatch`) take it. Each must leave every outcome unchanged. This kit builds a scenario world on the real operations layer, the real messaging bridge and a stand-in messenger,
puts it into a named pre-state, delivers one line (as a messaging update, or through `ops.say` for the page and the terminal), waits until every thread has settled and returns the
outcome as plain data: the claimer trace, the operations called, the messages sent, the ledger records added, the drafts and plans left, the conversation rows stored, the jobs
started, and the counts of model and provider calls. `entry_corpus.jsonl` holds the scenarios, `entry_golden.jsonl` the outcomes recorded on the old tree, and
`test_entry_replay.py` compares the two field by field.

NO CALLS. The model is a stand-in (`StandInModel`: the one function `interpreter_route.complete` that the interpreter, the e-mail compose and the e-mail revise reach, answering from the
recorded DeepSeek answers where an answers file holds the line, else `route`); a provider started as a process by the runtime (a model provider, a writer) raises and is counted; the
research run and the planning agent are the stand-ins of the world. The messenger is the stand-in of runtime/tests/fixtures/messenger_standin.py, called in this process (its verbs
read and write the same files as the process would; `FastMessenger` is what saves one process start per message). Every name, id, address and sender is invented. Offline.

THE CLAIMER TRACE (test-side only, nothing in runtime/ changes). `trace_claimers` wraps the methods and functions that claim a line today and records the first one that took it, per
layer; a claimer that is a branch of its dispatcher (a kind of intent, an inline test) is named from the facts the wrappers saw. `CLAIMER_NAMES` are exactly the row names that S41-2 and
S41-3 give `turn_order.ORDER`, so that their tables can assert equality.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_entry_replay.py
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import socket
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import standin_tree as st
import test_calendar_write as tcw
import test_sources_mail as tsm
from plan_bridge_kit import build as build_bridge, finish as finish_bridge, wait_for
from plan_confirm_kit import PROF, ZONE, accept
from sources_fixture import make_pdf
from test_channel_email_reply import EMAIL_CAPS
from test_ask import LEASE, NOTES, add_source
from test_ops_natural import ASKER, OWNER, READER, world as ops_world
from test_file_read import ACCOUNTS as DRIVE_ACCOUNTS, Drives, LINE_1 as FILE_LIST_LINE, WANTED, item as drive_item
from test_research import FakeRun, LINE_1 as RESEARCH_LINE
from test_service import WAIT

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURE = HERE / "fixtures" / "messenger_standin.py"

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
ops_natural_writes = st.load("ops_natural_writes")
ops_say = st.load("ops_say")
ops_turn = st.load("ops_turn")
ops_research = st.load("ops_research")
ops_file_read = st.load("ops_file_read")
ops_card_revise = st.load("ops_card_revise")
ops_step_seams = st.load("ops_step_seams")
effect_calendar = st.load("effect_calendar")
effects = st.load("effects")
ops_items = st.load("ops_items")
event_lookup = st.load("event_lookup")
interpreter = st.load("interpreter")
interpreter_route = st.load("interpreter_route")
mail_refresh = st.load("mail_refresh")
natural = st.load("natural")
natural_writes = st.load("natural_writes")
phone_delete = st.load("phone_delete")
phrases = st.load("phrases")
plan_confirm = st.load("plan_confirm")
pending_items = st.load("pending_items")
drafts = st.load("drafts")
lab = st.load("lab")
bridge = st.load("messaging_bridge")
inbound = st.load("messaging_inbound")
ack = st.load("messaging_ack")
providers = st.load("messaging_provider")
sources_module = st.load("sources")

# --- the vocabulary of a scenario ---------------------------------------------------------------------------------------------------------------------

UNLISTED = "55119000000099"                 # a sender the project does not list
OWNER_KEY = f"telegram:{OWNER}"
CHANNELS = ("messaging", "page", "terminal", "ops", "mcp", "chat")      # `ops`: a messaging sender's line given straight to ops.say, as the bridge gives it, without the bridge's own gate before it
PLATFORMS = ("buttons", "email")
SENDERS = ("owner", "reader", "asker", "unlisted", "group", "reader_interpret")      # `group` is the owner's id in a group chat (not the sender's own private chat)
PRESTATES = ("none", "card_last", "two_cards", "card_list_shown", "plan_last", "plan_not_last", "research_running", "reminder_draft", "reminder_expired", "write_draft_title",
             "router_question", "event_list_shown", "file_list_shown", "attachment_held", "config_unaccepted",
             "plan_then_card", "research_and_card", "route_busy", "route_busy_ask_choice",
             "expired_and_write_draft", "reminder_and_write_draft", "reminder_and_expired", "plan_and_write_draft", "plan_and_file_held",
             "question_of_other_project")      # the last two are the spec's list plus the two states the guards of L64 need: a plan live with a card sent after it, and a search that runs with a card last
OPS_PRESTATES = ("none", "router_question", "write_draft_title", "reminder_draft", "route_busy", "route_busy_ask_choice")      # the pre-states a line of the page, the terminal, mcp or chat can be in
OPS_CHANNELS = ("page", "terminal", "mcp", "chat")      # the shells whose line is given to ops.say with no sender (S41-1c adds mcp and chat); `reader_interpret` holds read and interpret, not talk, and is listed only in the worlds of its own scenarios
REPLY_TO = (None, "card", "plan", "list", "question", "nothing")      # `nothing`: a message id that no message of the chat has
KINDS = ("text", "action", "attachment")
ACTIONS = (None, "yes", "no", "approve", "reject", "release", "invalid")      # a button of the question or a card; "invalid" is an update whose attachments are not valid

# The name of every claimer, as S41-2 (bridge) and S41-3 (operations) will name the rows of `turn_order.ORDER` (the two specs list them: they are asserted equal there).
BRIDGE_NAMES = ("drop-unlisted", "drop-invalid-attachments", "ignore", "forwarded-refusal", "reply-to-card", "reminder-draft-answer", "reminder-expired-yes", "write-draft-answer",
                "plan-confirm-word", "card-word", "research-stop", "card-revise", "project-switch", "help-in-words", "attachment-line", "attachment-arrived", "attachment-typed",
                "remind-typed", "write-form", "reminder-form", "say-natural", "reminders-list", "forget-typed", "tap", "usage", "help-typed", "project-typed", "pending-typed",
                "decision-typed", "reply", "say")
BRIDGE_SAY_NAMES = ("delete-refusal-before-queue", "closed-form-without-slot", "say-queue")
OPS_NAMES = ("confirmed-plan", "command", "greeting", "plan-bare-word", "delete-file", "router-question", "state-question", "draft-answer", "event-list-number", "file-list-number",
             "write-form-ops", "tier-1-form", "talk-refusal", "interpreter", "planning-agent")
CLAIMER_NAMES = BRIDGE_NAMES + BRIDGE_SAY_NAMES + OPS_NAMES

# What is hidden when two outcomes are compared: every run of digits (an id, a position, a day, an hour, a count) and every word made only of hexadecimal characters that is six or more
# long (a hash, the random identifier of a plan or of a folder, a project's key). A different WORD is never hidden: a phrase key that changes shows as a different text. One regex,
# named here, used for the text of a message, of a reply, of a stored row and of an argument.
MASK = re.compile(r"\b[0-9a-f]{6,}\b|[0-9]+")
NEUTRAL_KEYS = ("NAT_PRIVATE_LINE", "NAT_PRIVATE_REPLY", "NW_PRIVATE_LINE", "NW_PRIVATE_REPLY", "IX_PRIVATE_LINE", "NAT_READ_REPLY")
OUTCOME_FIELDS = ("trace", "ops_calls", "sent", "ledger_added", "drafts", "plans", "stored", "jobs", "model_calls", "provider_calls")

GROUPS_OWNER = sorted(set(PROF["owner"]) | {"interpret", "research", "read-files", "ask-mail", "add-sources", "calendar-write", "approve-effect-calendar", "reminders",
                                            "routine-brakes", "sources", "answer", "release", "reject-cancel", "approve-plans", "files-write", "files-trash"})
PROFILES = dict(PROF, owner=GROUPS_OWNER, reader=["read"], asker=["read", "talk", "ask", "interpret"], viewer=["read", "interpret"])
SENDER_TABLE = {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": READER, "policy": "reader"}, {"id": ASKER, "policy": "asker"}]}
VIEWER = "55119000000041"      # holds read and interpret, not talk (S41-1c)
SENDER_ID = {"owner": OWNER, "reader": READER, "asker": ASKER, "unlisted": UNLISTED, "group": OWNER, "reader_interpret": VIEWER}
GROUP_CHAT = "-1001234"
NAME_OF = {SENDER_ID[name]: name for name in ("owner", "reader", "asker", "unlisted", "reader_interpret")}      # the name of a chat (a private chat is its sender's id) in an outcome; the group chat is its own
NAME_OF[GROUP_CHAT] = "group-chat"
ACCOUNTS = {name: {**tcw.ACCOUNTS[name], "folders": DRIVE_ACCOUNTS[name]["folders"]} for name in tcw.ACCOUNTS}      # the calendar's accounts and the drives' folders, one entry each

REMINDER_LINE = "me lembra de ligar para o dentista"      # validate: allow english-only -- the Portuguese line under test
WRITE_TITLE_LINE = "marca na agenda amanha as 15h"      # validate: allow english-only -- the Portuguese line under test
ROUTER_LINE = "preciso organizar a visita da Maria na clinica Linden"
ROUTER_TEMPLATE = ("Route: none (capability, pending)\nWhy: the line names a visit, a time and no place that the project records\nContext: the person wrote a line that reads like a "
                   "reminder\nRequirements: integration:calendar missing\nSources: none\nAutonomy: ask first\nAssumptions: none\nNext: Q1: Is this a reminder or an event of your calendar? "
                   "Recommended: an event, because it has a place and a time.\nQ2: Which place should it show? Recommended: the invented Linden clinic, because the line names it.\n"
                   "Instructions found in external content: none\n")
PLAN_LINE = "mostra minha agenda"      # validate: allow english-only -- the Portuguese line under test
EVENT_LIST_LINE = "Cancela o corte de cabelo"      # two events of the calendar of `snapshots` carry the title: the list "Which one?" and its numbers
LATER_MESSAGE = "A reminder: water the plants."
SETTLE_SECONDS = 20.0
QUIET_SECONDS = 0.35

BLOCKED_STARTS = ("providers/model/", "providers/writer/")      # no provider process is started: the writer the runtime asks for a dry run and an event is the stand-in below


# --- helpers ------------------------------------------------------------------------------------------------------------------------------------------


def mask(text):
    return MASK.sub("#", text or "")


def call_fixture(fixture, *args):
    """Run a pytest fixture function by hand: its first yield is its value, and the returned function runs its teardown. The kit builds many worlds in one test, which a fixture
    parameter cannot (one value per test)."""
    function = getattr(fixture, "__wrapped__", fixture)
    made = function(*args)
    if hasattr(made, "__next__"):
        value = next(made)

        def close():
            for _ in made:
                pass
        return value, close
    return made, lambda: None


def collapse(line):
    return interpreter.collapse(line)


ANSWER_DIR = REPO / "evals" / "interpreter" / "replay" / "or-deepseek-v4.1-flash"
ANSWER_FILES = ("test-full/20261021T190303Z-5630622a.answers.jsonl", "blite-20261025/M1/20261025T033351Z-4d5c4ce4.answers.jsonl", "blite-20261025/M2/20261025T033519Z-4ffcb9b2.answers.jsonl",
                "blite2-20261025/M1/20261026T011821Z-25ff628e.answers.jsonl", "blite2-20261025/M2/20261026T011939Z-af4c6192.answers.jsonl")      # named, never globbed: a new measurement must not change the golden
ANSWER_CORPORA = ("ix-test-v1.jsonl", "dev-long-v1.jsonl", "dev-long-v2.jsonl", "dev.jsonl", "dev-relabelled.jsonl")      # the corpora whose item ids those files answer


def load_answers() -> dict:
    """{collapsed line: the text of the first recorded answer (run 1)} of the DeepSeek replay files of ANSWER_FILES, joined to their corpora by item id. Read once."""
    table, corpora = {}, {}
    for name in ANSWER_CORPORA:
        for raw in (REPO / "evals" / "interpreter" / name).read_text(encoding="utf-8").splitlines():
            if raw.strip():
                row = json.loads(raw)
                if isinstance(row, dict) and "id" in row and "line" in row:
                    corpora.setdefault(row["id"], row["line"])
    for name in ANSWER_FILES:
        for raw in (ANSWER_DIR / name).read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            line = corpora.get(row.get("item"))
            if line and row.get("ok") and row.get("run") == 1 and isinstance(row.get("text"), str):
                table.setdefault(collapse(line), row["text"])
    return table


_ANSWERS = []


def answers() -> dict:
    if not _ANSWERS:
        _ANSWERS.append(load_answers())
    return _ANSWERS[0]


def answers_sha256() -> str:
    """The hash of the table of recorded answers the stand-in reads, with the hand-written ones: the golden is valid only for this table."""
    table = {**answers(), **OVERRIDES}
    return hashlib.sha256(json.dumps(sorted(table.items()), ensure_ascii=False).encode("utf-8")).hexdigest()


class StandInModel:
    """The one function every model call of the runtime reaches, `interpreter_route.complete`, answered from a table keyed by the collapsed line (the recorded DeepSeek text where an
    answers file holds the line, else `{"kind": "route"}`), counting its calls."""

    def __init__(self):
        self.calls = 0
        self.lines = []

    def complete(self, route_id, system, user, **kw):
        self.calls += 1
        line = user.rsplit("\nline: ", 1)[-1] if "\nline: " in user else ""
        self.lines.append(line)
        text = OVERRIDES.get(collapse(line)) if line else None
        text = answers().get(collapse(line)) if line and text is None else text
        return {"ok": True, "text": text if text is not None else json.dumps({"v": 1, "kind": "route"}), "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}


def op_text(name, slots=None, **more):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots or {}, **more}, ensure_ascii=False)


# The lines whose answer a pre-state needs and no recorded answer holds: hand-written model texts, keyed by the collapsed line (the checks of the interpreter believe them or not).
OVERRIDES = {}      # filled once the interpreter is loaded, below


class Counter:
    def __init__(self):
        self.value = 0
        self.lock = threading.Lock()

    def bump(self):
        with self.lock:
            self.value += 1


def block_providers(monkeypatch, counter):
    """A process the runtime starts for a model provider (under providers/model/, or the resolver asked for a model class) or for a writer raises, and so does a connection to anything:
    each is counted in `counter` (the outcome's `provider_calls`)."""
    real = subprocess.Popen

    class Guard(real):
        def __init__(self, args, *a, **k):
            joined = " ".join(str(x) for x in (args if isinstance(args, (list, tuple)) else [args]))
            if any(host in joined for host in BLOCKED_STARTS) or re.search(r"--class[ =]model\b|\bmodel:", joined):
                counter.bump()
                raise OSError("a provider was started by a test of the entry replay")
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", Guard)

    def no_network(self, *args, **kwargs):
        counter.bump()
        raise OSError("the entry replay opens no connection")
    monkeypatch.setattr(socket.socket, "connect", no_network)


ROUTER_ANSWERS = ("um evento", "an event, 13:00, the Linden clinic", "sim, um evento no google", "o evento")      # validate: allow english-only -- the Portuguese lines under test
OVERRIDES.update({collapse(line): json.dumps({"v": 1, "kind": "answer", "answers_item": "i1"}) for line in ROUTER_ANSWERS})
OVERRIDES.update({collapse(RESEARCH_LINE): op_text("research", {"question": RESEARCH_LINE}), collapse(FILE_LIST_LINE): op_text("file-read", {"file": WANTED}),
                  collapse(EVENT_LIST_LINE): op_text("event-cancel")})


# --- the stand-in messenger, in this process ----------------------------------------------------------------------------------------------------------


def _standin_module():
    spec = importlib.util.spec_from_file_location("entry_kit_messenger_standin", FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FastMessenger:
    """The four verbs of the stand-in messenger provider, called in this process: the same files in STANDIN_DIR, the same answers, one process start less per message. Installed over
    `Messenger._call` of the bridge's messenger (the real `capabilities`, `send`, `fetch` and `ack` of messaging_provider.py still run around it)."""

    def __init__(self):
        self.module = _standin_module()
        self.lock = threading.Lock()

    def __call__(self, verb, args, timeout=60):
        opts = {args[i]: args[i + 1] for i in range(0, len(args), 2)}
        standin = self.module
        with self.lock:
            if verb == "capabilities":
                return {**standin.DEFAULT_CAPS, **standin.read("caps.json", {})}
            if verb == "send":
                with open(opts["--message-file"], encoding="utf-8") as f:
                    message = json.load(f)
                count = standin.append("sent.jsonl", {"chat": opts["--chat"], "message": message})
                return {"message_id": str(100 + count)}
            if verb == "ack":
                standin.append("acks.jsonl", {"ref": opts["--action-ref"]})
                return {"acked": True}
            if verb == "typing":
                standin.append("typing.jsonl", {"chat": opts["--chat"]})
                return {"typing": True}
            if verb == "fetch-attachment":
                spoken = io.StringIO()
                with contextlib.redirect_stdout(spoken), contextlib.redirect_stderr(io.StringIO()):
                    code = standin.fetch(argparse.Namespace(ref=opts["--ref"], out=opts["--out"], max_bytes=int(opts["--max-bytes"])))
                if code != 0:
                    raise providers.MessengerError("failed", "the stand-in refused the fetch")
                return json.loads(spoken.getvalue())
        raise providers.MessengerError("usage", f"the stand-in does not serve {verb}")


# --- the calendar writer, in this process -------------------------------------------------------------------------------------------------------------


EVENTS = ((21, "09:00", "10:00", "Dentist", "evden"), (22, "13:00", "14:00", "corte de cabelo", "evhair22"), (22, "18:00", "19:00", "Yoga", "evyoga"),
          (23, "13:00", "14:00", "corte de cabelo", "evhair23"), (25, "08:00", "09:00", "Consulta Dra Lima", "evcons"))      # the calendar of test_event_lookup.py


class WriterStandIn:
    """The one place the runtime starts a calendar writer, `effect_calendar.provider_call`, answered in this process: the dry run of a write verb is the writer's own code run in
    this process (it reads no credential and opens no connection: it prints the request it would send and its hash), `event-get` is read from the in-memory calendar above through the
    writer's own `read_event`, and a verb that would write is refused as a writer that is not connected. No process is started and nothing leaves this process."""

    def __init__(self):
        self.modules = {}
        self.lock = threading.Lock()
        self.items = {ident: {"id": ident, "etag": f"etag-{ident}", "status": "confirmed", "summary": title, "start": {"dateTime": f"2026-10-{day}T{start}:00-03:00"},
                              "end": {"dateTime": f"2026-10-{day}T{end}:00-03:00"}, "organizer": {"email": "pat@example.com", "self": True}}
                      for day, start, end, title, ident in EVENTS}

    def module(self, implementation):
        if implementation not in self.modules:
            spec = importlib.util.spec_from_file_location(f"entry_kit_writer_{implementation.replace('-', '_')}", REPO / "providers" / "writer" / f"{implementation}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.modules[implementation] = module
        return self.modules[implementation]

    def __call__(self, root, implementation, verb, args, secrets=(), timeout=0):
        if "--dry-run" in args:
            spoken = io.StringIO()
            with self.lock, contextlib.redirect_stdout(spoken), contextlib.redirect_stderr(io.StringIO()):
                code = self.module(implementation).main([verb, *args])
            if code != 0:
                raise effects.EffectError("provider", f"{verb}: the dry run was refused")
            return json.loads(spoken.getvalue())
        if verb == "event-get":
            event_id = args[args.index("--event") + 1]
            item = self.items.get(event_id) if implementation == "google-calendar" else None
            if item is None:
                return {"found": False, "reason": "gone"}
            return {"found": True, "event": self.module(implementation).read_event(item)}
        raise effects.EffectError("not-configured", f"{verb}: no writer is connected in the entry replay")


# --- the claimer trace --------------------------------------------------------------------------------------------------------------------------------


class Recorder:
    """What one scenario's wrappers saw: the claim events in the order they happened (for the code that is nested in no other wrapped call of its thread), the calls of the
    operations layer, the jobs started, and the facts the inferred names read. Everything records only while `live`: the line is being delivered, not a pre-state built."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.ops_calls = []
        self.jobs = []
        self.facts = {}
        self.local = threading.local()
        self.live = False

    def depth(self):
        return getattr(self.local, "depth", 0)

    def event(self, layer, name):
        if self.live and self.depth() == 0:
            with self.lock:
                self.events.append((layer, name))

    def fact(self, key, value=True):
        if self.live:
            with self.lock:
                self.facts.setdefault(key, value)

    def call(self, name, args):
        if self.live:
            with self.lock:
                self.ops_calls.append([name, args])


CURRENT = []


def rec():
    return CURRENT[-1]


def wrap(monkeypatch, owner, name, effect, when, label=None):
    """Replace `owner.name` by a wrapper that records and keeps the call as it was. `effect` is `("event", layer)` (the claim `label` of a layer) or `("fact", key)`; `when` is `called`
    (at entry), `truthy`, `not-none`, `none` or `false` (what the call returned). The wrapped call is one level of nesting for the events of its own thread."""
    original = getattr(owner, name)
    kind, where = effect

    def record():
        if kind == "event":
            rec().event(where, label)
        else:
            rec().fact(where)

    def wrapper(*args, **kwargs):
        recorder = rec()
        if when == "called":
            record()
        recorder.local.depth = recorder.depth() + 1
        try:
            result = original(*args, **kwargs)
        finally:
            recorder.local.depth -= 1
        if (when == "truthy" and result) or (when == "not-none" and result is not None) or (when == "none" and result is None) or (when == "false" and result is False):
            record()
        return result
    wrapper.__wrapped__ = original
    monkeypatch.setattr(owner, name, wrapper)
    return original


def trace_claimers(monkeypatch):
    """Wrap, without changing them, the methods and functions that claim a line today (the names are in CLAIMER_NAMES). Test-side only."""
    bridge_event = lambda name: ("event", "bridge")      # noqa: E731
    # the bridge's claimers, in the order `_handle` calls them
    wrap(monkeypatch, bridge.Bridge, "config_pending", bridge_event(0), "called", "drop-unlisted")
    wrap(monkeypatch, bridge.provider, "valid_attachments", bridge_event(0), "none", "drop-invalid-attachments")
    wrap(monkeypatch, bridge.remind.Reminders, "answer", bridge_event(0), "truthy", "reminder-draft-answer")
    wrap(monkeypatch, bridge.remind.Reminders, "late", bridge_event(0), "truthy", "reminder-expired-yes")
    wrap(monkeypatch, bridge.Bridge, "write_answers", bridge_event(0), "truthy", "write-draft-answer")
    wrap(monkeypatch, bridge.Bridge, "plan_line", bridge_event(0), "truthy", "plan-confirm-word")
    wrap(monkeypatch, bridge.Bridge, "word_line", bridge_event(0), "truthy", "card-word")
    wrap(monkeypatch, bridge.Bridge, "research_stop_line", bridge_event(0), "truthy", "research-stop")
    wrap(monkeypatch, bridge.Bridge, "revise_line", bridge_event(0), "truthy", "card-revise")
    wrap(monkeypatch, bridge.Bridge, "project_line", bridge_event(0), "truthy", "project-switch")
    wrap(monkeypatch, bridge.Bridge, "greets", ("fact", "greets_false"), "false")      # "help" in words is the fixed help only when the line is no greeting
    wrap(monkeypatch, bridge.attach.Attachments, "line", bridge_event(0), "truthy", "attachment-line")
    wrap(monkeypatch, bridge.remind.Reminders, "natural", bridge_event(0), "truthy", "reminder-form")
    # the parse: an update that is nothing, or a forward, is claimed by the envelope (the typed lines the operations layer hands back never parse to either)
    original_parse = inbound.parse

    def parse(update):
        found = original_parse(update)
        recorder = rec()
        if found.get("kind") == "ignore":
            recorder.event("bridge", "ignore")
        elif found.get("kind") == "forwarded":
            recorder.event("bridge", "forwarded-refusal")
        recorder.fact("intent", dict(found))
        return found
    monkeypatch.setattr(inbound, "parse", parse)
    # the sub-claims of Bridge.say
    original_say = bridge.Bridge.say

    def say(self, project, chat, text):
        recorder = rec()
        recorder.local.in_say = getattr(recorder.local, "in_say", 0) + 1
        try:
            return original_say(self, project, chat, text)
        finally:
            recorder.local.in_say -= 1
    monkeypatch.setattr(bridge.Bridge, "say", say)
    original_reply = bridge.Bridge.reply

    def reply(self, chat, text, project=None, guard=False, attachment=None):
        recorder = rec()
        if getattr(recorder.local, "in_say", 0) and text in phrases.every("PHONE_NO_FILE_DELETE"):
            recorder.event("bridge-say", "delete-refusal-before-queue")
        return original_reply(self, chat, text, project, guard=guard, attachment=attachment)
    monkeypatch.setattr(bridge.Bridge, "reply", reply)
    original_job = bridge.Bridge.start_job

    def start_job(self, project, op, call, queues=False):
        recorder = rec()
        if recorder.live:
            with recorder.lock:
                recorder.jobs.append(op)
            if getattr(recorder.local, "in_say", 0):
                recorder.event("bridge-say", "say-queue" if op == "say" else "closed-form-without-slot")
        return original_job(self, project, op, call, queues=queues)
    monkeypatch.setattr(bridge.Bridge, "start_job", start_job)
    original_keep = bridge.Bridge.keep_or_refuse

    def keep_or_refuse(self, *args, **kwargs):
        recorder = rec()
        if getattr(recorder.local, "in_say", 0):
            recorder.event("bridge-say", "say-queue")
        return original_keep(self, *args, **kwargs)
    monkeypatch.setattr(bridge.Bridge, "keep_or_refuse", keep_or_refuse)
    # the operations layer's claimers
    ops_event = ("event", "ops")
    wrap(monkeypatch, ops_say, "_say_confirmed", ops_event, "called", "confirmed-plan")
    wrap(monkeypatch, ops_say, "_say_command", ops_event, "called", "command")
    wrap(monkeypatch, ops_say, "_greeting_reply", ops_event, "called", "greeting")
    wrap(monkeypatch, ops_say, "state_reply", ops_event, "called", "state-question")
    wrap(monkeypatch, ops_natural, "_complete", ops_event, "called", "draft-answer")
    wrap(monkeypatch, ops_natural_writes, "answer", ops_event, "not-none", "draft-answer")
    wrap(monkeypatch, event_lookup, "take", ops_event, "not-none", "event-list-number")
    wrap(monkeypatch, ops_file_read, "take", ops_event, "not-none", "file-list-number")
    wrap(monkeypatch, ops_natural_writes, "open_line", ops_event, "not-none", "write-form-ops")
    wrap(monkeypatch, ops_natural, "run", ops_event, "called", "tier-1-form")
    wrap(monkeypatch, ops_interpret, "turn", ops_event, "not-none", "interpreter")
    original_ask = plan_confirm.ask

    def plan_ask(*args, **kwargs):
        if kwargs.get("state_question"):
            rec().event("ops", "state-question")
        return original_ask(*args, **kwargs)
    monkeypatch.setattr(plan_confirm, "ask", plan_ask)
    original_route = ops_say._say_route

    def say_route(project, ctx, said, line_id, channel, answer_to=None, **kwargs):
        rec().event("ops", "router-question" if answer_to is not None else "planning-agent")
        return original_route(project, ctx, said, line_id, channel, answer_to=answer_to, **kwargs)
    monkeypatch.setattr(ops_say, "_say_route", say_route)
    original_turn = ops_turn.dispatch      # S41-3: `ops_say._turn` is the stage `ops` of the table, dispatched by `ops_turn.dispatch`: the same arguments, the same tuple

    def turn(project, ctx, said, channel, line_id, sender=None, extras=None):
        recorder = rec()
        if recorder.live:
            recorder.fact("turn_said", said)
            recorder.fact("turn_channel", channel)
            recorder.fact("turn_talks", ops_say.may_talk(ctx, channel, sender))
            recorder.fact("turn_plan_live", channel == "messaging" and plan_confirm.live(project, sender) is not None)
            recorder.fact("turn_delete", channel == "messaging" and phone_delete.asks(said))
        return original_turn(project, ctx, said, channel, line_id, sender, extras)
    monkeypatch.setattr(ops_turn, "dispatch", turn)


def infer_bridge(recorder, update) -> str:
    """The name of the bridge claimer that took an update when no wrapped method did: a branch of `_handle` named by the kind of the intent and the facts the wrappers saw."""
    facts = recorder.facts
    intent = facts.get("intent") or {}
    kind = intent.get("kind")
    if kind in ("text", "natural") and facts.get("greets_false") and (natural.match(intent.get("text") or "") or {}).get("op") == "commands":
        return "help-in-words"
    if kind == "natural" and update.get("reply_to") and facts.get("reply_to_card"):
        kind = "reply"
    if kind == "natural":
        return "write-form" if intent.get("op") == "write" else "say-natural"
    return {"attachment": "attachment-arrived", "add": "attachment-typed", "discard": "attachment-typed", "remind": "remind-typed", "reminders": "reminders-list",
            "forget": "forget-typed", "action": "tap", "usage": "usage", "help": "help-typed", "project": "project-typed", "pending": "pending-typed",
            "approve": "decision-typed", "reject": "decision-typed", "release": "decision-typed", "answer": "decision-typed", "reply": "reply", "text": "say"}.get(kind, "")


def infer_ops(recorder) -> str:
    """The name of the operations-layer claimer when the branch is inline in the turn (`ops_turn.dispatch`): the facts of the turn."""
    facts = recorder.facts
    if "turn_said" not in facts:
        return ""
    said, channel = facts["turn_said"], facts["turn_channel"]
    if facts["turn_talks"] and channel == "messaging" and facts["turn_plan_live"] and natural.confirm_kind(said) in ("yes", "no"):
        return "plan-bare-word"
    if facts["turn_talks"] and channel == "messaging" and facts["turn_delete"]:
        return "delete-file"
    if not facts["turn_talks"]:
        return "talk-refusal"
    return ""


def trace_of(recorder, scenario, update) -> list:
    """The names, in layer order, of the claimers that took the line: the marker of a reply to a card, the bridge's first claimer, the claim inside `Bridge.say`, the operations layer's
    first claimer. A layer the line never reached has none."""
    first = {}
    for layer, name in recorder.events:
        first.setdefault(layer, name)
    names = []
    if recorder.facts.get("reply_to_card"):
        names.append("reply-to-card")
    if scenario["channel"] == "messaging":
        taker = first.get("bridge") or (infer_bridge(recorder, update) if "intent" in recorder.facts else "")
        if taker:
            names.append(taker)
        if first.get("bridge-say"):
            names.append(first["bridge-say"])
    taker = first.get("ops") or infer_ops(recorder)
    if taker:
        names.append(taker)
    return names


# --- the spies on the operations layer ----------------------------------------------------------------------------------------------------------------


def clean(value, root):
    """Plain data for the outcome: a path of the scratch tree is replaced, a sender key kept (invented), a hash and a digit run are masked in a text."""
    if isinstance(value, str):
        for base in (root, os.path.realpath(root)):
            value = value.replace(base, "<tmp>")
        for name, ident in SENDER_ID.items():
            value = value.replace(ident, f"<{name}>")
        return mask(value)
    if isinstance(value, dict):
        return {str(k): clean(v, root) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [clean(v, root) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return mask(str(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    return mask(repr(value))


def spy_operations(monkeypatch, root):
    """A spy on the operations layer that passes the call through: the bridge's one call path (`Bridge.run_op`), the operations it calls directly, the one place a read runs and the one
    function every natural write calls. The calls are `[name, arguments]`, the project's path replaced."""
    def spy(name, call_name, owner, strip=("project",)):
        original = getattr(owner, call_name)

        def wrapper(*args, **kwargs):
            shown = {k: v for k, v in kwargs.items() if k not in ("channel",)}
            if args and not isinstance(args[0], str) or (args and len(args) > 1):
                shown["_args"] = [a for a in args[1:] if not isinstance(a, dict) or "path" not in a]
            rec().call(name, clean(shown, root))
            return original(*args, **kwargs)
        wrapper.__wrapped__ = original
        monkeypatch.setattr(owner, call_name, wrapper)
    original_run = bridge.Bridge.run_op

    def run_op(self, project, op, kind=None, sender=None, allow_as=None, **args):
        rec().call("run_op:" + op, clean({"sender": sender, **args}, root))
        return original_run(self, project, op, kind, sender, allow_as, **args)
    monkeypatch.setattr(bridge.Bridge, "run_op", run_op)
    for name in ("approve", "reject", "release", "card_revise", "card_revise_check", "natural_write", "plan_drop", "research_stop"):
        if hasattr(ops, name):
            spy(name, name, ops)
    original_read = ops_natural._read

    def read(project, ctx, name, row, args, channel, sender):
        rec().call("read:" + name, clean({"args": args, "sender": sender}, root))
        return original_read(project, ctx, name, row, args, channel, sender)
    monkeypatch.setattr(ops_natural, "_read", read)
    original_operation = ops_natural_writes._call_operation

    def call_operation(project, op, args, channel, sender):
        rec().call("write:" + op, clean({"args": args, "sender": sender}, root))
        return original_operation(project, op, args, channel, sender)
    monkeypatch.setattr(ops_natural_writes, "_call_operation", call_operation)


# --- the world ----------------------------------------------------------------------------------------------------------------------------------------


class World:
    """One scenario's world. `close` ends every thread and undoes what was patched."""

    def __init__(self):
        self.closers = []
        self.refs = {}
        self.held = []

    def close(self):
        if getattr(self, "release", None) is not None:
            self.release.set()
        if getattr(self, "b", None) is not None:
            finish_bridge(self.b)
        for closer in reversed(self.closers):
            closer()


def reset_globals():
    drafts.clear()
    pending_items.clear()
    ops_interpret.forget_all()
    ops_card_revise.forget_all()
    event_lookup._LISTS.clear()
    ops_file_read._LISTS.clear()
    ops_items._CHECKED.clear()
    mail_refresh.forget()
    natural_writes.clear_facts()


def open_world(scenario, tmp_path, monkeypatch) -> World:
    """The world of a scenario: the real operations layer over the chat tree of test_ops_natural.py (the router and the answer skill are its stand-ins), the senders and groups of
    PROFILES, a calendar of two accounts, the research skill and the stand-in run, the stand-in model, the guards on the providers, and, for a messaging line, the real bridge over the
    stand-in messenger. Nothing is delivered yet."""
    w = World()
    recorder = Recorder()
    CURRENT.append(recorder)
    w.closers.append(CURRENT.pop)
    w.recorder, w.scenario, w.root = recorder, scenario, str(tmp_path)
    w.monkeypatch, w.tmp_path = monkeypatch, tmp_path
    monkeypatch.setenv("TZ", ZONE)      # the zone a card says (calendar_document.zone_name reads TZ, else /etc/localtime of the machine): pinned, so that no host's zone is in an outcome
    time.tzset()
    built, close_world = call_fixture(ops_world, tmp_path, monkeypatch)
    w.closers.append(close_world)
    w.world, w.path = built, built["path"]
    reset_globals()
    w.closers.append(reset_globals)
    monkeypatch.setattr(plan_confirm, "ACTIVE", True)
    monkeypatch.setattr(ops, "_use_start", lambda *args, **kwargs: None)      # the record of a field use runs scripts/evidence.py of the tree the run reads: none in the world, and it must say nothing
    now = [1000.0]
    monkeypatch.setattr(pending_items, "clock", lambda: now[0])
    monkeypatch.setattr(ack, "ACK_DELAY", 3600.0)      # the acknowledgement of a slow line is a clock's: the replay never waits for it
    table = SENDER_TABLE if scenario["sender"] != "reader_interpret" else {"telegram": [*SENDER_TABLE["telegram"], {"id": VIEWER, "policy": "viewer"}]}      # the other worlds are as they were
    accept(w.path, policies=PROFILES, messaging={"senders": table}, accounts=ACCOUNTS)
    monkeypatch.setattr(ops_interpret, "_zone", lambda now_: ZONE)
    w.model = StandInModel()
    monkeypatch.setattr(interpreter_route, "complete", w.model.complete)
    w.provider_starts = Counter()
    block_providers(monkeypatch, w.provider_starts)
    folder = st.skill(built["tree"], ops_research.SKILL, "docs/workbench/state.md", "docs/workbench/research/<topic>.md", area="core")
    skill_md = folder / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8").replace("  requires: []", "  requires: [search:web]"), encoding="utf-8")
    base_standing = lab.standing

    def standing(skill):
        found = base_standing(skill)
        found["models"]["m"].update(web_measured=True, band="reliable")
        return found
    monkeypatch.setattr(lab, "standing", standing)
    monkeypatch.setattr(effect_calendar, "provider_call", WriterStandIn())      # no calendar writer process is ever started

    def no_drive(self, account, args):
        raise ops_step_seams.StepServiceError("provider_failed", "no drive is connected in the entry replay")      # the one read a file write makes before its card: the writer of files is not started
    monkeypatch.setattr(ops_step_seams.FilesReader, "meta", no_drive)
    drives = Drives()
    drives.folders[("google", "GDRIVEFOLDER0002")].append(drive_item("gfile0000000003", WANTED))      # two files carry the name: a read of it is a list ("Which one?")
    monkeypatch.setattr(ops_file_read, "provider_call", drives)      # two fictional drives in memory: the search a file read makes never leaves this process
    w.run = FakeRun()
    w.real_run = lab.run_skill      # the router and the answer skill run through the world's own stand-in adapter; only the research skill is the stand-in run

    def run_skill(skill, *args, **kwargs):
        return (w.research_run if skill == ops_research.SKILL else w.real_run)(skill, *args, **kwargs)
    w.research_run = w.run
    monkeypatch.setattr(lab, "run_skill", run_skill)
    trace_claimers(monkeypatch)
    spy_operations(monkeypatch, str(tmp_path))
    if scenario["channel"] == "messaging":
        b = build_bridge(w.world, tmp_path, monkeypatch)
        w.b = b
        b.bridge.messenger._call = FastMessenger()
        caps = dict(EMAIL_CAPS) if scenario["platform"] == "email" else {}
        caps.update(attachments=True, max_attachment_bytes=20 * 1024 * 1024)
        b.caps(**caps)
        (b.folder / "files").mkdir()
        (b.folder / "files" / "r1").write_bytes(make_pdf("The Q3 plan: grow the newsletter by a third."))
    return w


# --- the pre-states -----------------------------------------------------------------------------------------------------------------------------------


def settle(w, extra=()):
    """Every thread the bridge started has ended (a deadline, never an unbounded wait); `extra` threads (a research run that is held) are not waited for."""
    b = w.b

    def quiet():
        alive = [t for t in list(b.bridge.threads) if t.is_alive() and t not in extra]
        return not alive and (not b.bridge.exclusive or bool(extra))
    return wait_for(quiet, SETTLE_SECONDS)


def say_ops(w, text, channel):
    return ops.say(w.path, text, channel=channel)


def card_ids(w, chat=OWNER):
    """The platform's message ids of the decision cards sent to `chat` (the owner's): a tick sends each card to every listed sender who may see it."""
    return [c["message_id"] for c in w.b.bridge.ledger.data["cards"] if c.get("pending_id") is not None and c.get("kind") != "plan-confirm" and c.get("chat") == chat]


def event_card(w, title, start):
    return ops.event_create(w.path, "google", title, start, channel="messaging", sender=OWNER_KEY)


def send_cards(w):
    w.b.bridge.tick()
    settle(w, extra=w.held)
    ids = card_ids(w)
    w.refs["card"] = ids[-1] if ids else None


def say_yes(w):
    """The owner's yes to the question of the plan: the word, and on a platform whose acts are replies (e-mail) a reply to the question."""
    w.b.say("sim", reply_to=w.b.question_id() if w.scenario["platform"] == "email" else None)


def confirm(w, line):
    """The owner says `line` in words; when the question "Posso?" reaches the chat the owner says yes (a line the operations layer answers at once has no question). The jobs have settled."""
    def questions():
        return len([c for c in w.b.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm"])
    before = questions()
    w.b.say(line)
    settle(w)
    if questions() > before:
        say_yes(w)
        settle(w)


def prestate_card_last(w):
    event_card(w, "Haircut with Joe", "2026-10-19T13:00")
    send_cards(w)


def prestate_two_cards(w):
    event_card(w, "Haircut with Joe", "2026-10-19T13:00")
    event_card(w, "Dentist for Maria", "2026-10-20T09:00")
    send_cards(w)


def prestate_card_list_shown(w):
    prestate_two_cards(w)
    w.b.say("sim")
    settle(w)
    shown = w.b.bridge.card_lists.get(OWNER)
    w.refs["list"] = shown["message_id"] if shown else None


def prestate_plan_last(w):
    w.b.ask(PLAN_LINE)
    w.refs["plan"] = w.b.question_id()


def prestate_plan_not_last(w):
    prestate_plan_last(w)
    w.b.bridge.reply(OWNER, LATER_MESSAGE)


def prestate_research_running(w):
    release, started = threading.Event(), threading.Event()
    w.release = release
    w.monkeypatch.setattr(ack, "ACK_DELAY", 0.2)      # the search tells the person the word that stops it, after this long: the pre-state waits for that message, as the guard tests of the brake do

    class Held(FakeRun):
        def __call__(self, *args, **kwargs):
            started.set()
            release.wait(WAIT)
            return super().__call__(*args, **kwargs)
    w.research_run = Held()
    w.monkeypatch.setattr(lab, "stop_runs", lambda *a, **k: release.set())
    w.b.ask(RESEARCH_LINE)
    say_yes(w)
    w.refs["plan"] = None
    assert wait_for(started.is_set, SETTLE_SECONDS), "the pre-state research_running: the search began after the owner's yes"      # never go on with a state that was not reached
    wait_for(lambda: bool(w.b.bridge.exclusive), SETTLE_SECONDS)
    told = phrases.text("ACK_RESEARCH", ops_core.context(w.path)["cfg"])
    wait_for(lambda: told in w.b.texts(OWNER), SETTLE_SECONDS)      # the acknowledgement is the last message now, and the question is not
    w.monkeypatch.setattr(ack, "ACK_DELAY", 3600.0)
    w.held = [t for t in list(w.b.bridge.threads) if t.is_alive()]


def prestate_plan_then_card(w):
    prestate_plan_last(w)
    event_card(w, "Haircut with Joe", "2026-10-19T13:00")
    send_cards(w)


def prestate_research_and_card(w):
    prestate_research_running(w)
    event_card(w, "Haircut with Joe", "2026-10-19T13:00")
    send_cards(w)


def keep_write_draft(w):
    """The owner's open question about a write, as the operations layer keeps it (drafts.py): taken out of the store so that the next lines do not drop it, put back with `restore_write_draft`.
    Two states that no single line builds (a line that opens one drops the other) are made by this, in memory, exactly as the stores hold them."""
    return drafts.get("messaging", OWNER_KEY, "write")


def restore_write_draft(w, held):
    drafts.put("messaging", OWNER_KEY, held, "write")


def prestate_expired_and_write_draft(w):
    """An expired question about a reminder and an open question about a write, live at once."""
    prestate_write_draft_title(w)
    w.b.bridge.remind.expired[OWNER] = w.b.bridge.monotonic()


def prestate_reminder_and_write_draft(w):
    """An open question about a reminder (when?) and an open question about a write (the title), live at once."""
    prestate_write_draft_title(w)
    held = keep_write_draft(w)
    prestate_reminder_draft(w)
    restore_write_draft(w, held)


def prestate_reminder_and_expired(w):
    """An open question about a reminder and the memory of another that expired, live at once."""
    prestate_reminder_draft(w)
    w.b.bridge.remind.expired[OWNER] = w.b.bridge.monotonic()


def prestate_plan_and_write_draft(w):
    """A plan ("Posso?") that is the last message and an open question about a write, live at once."""
    prestate_write_draft_title(w)
    held = keep_write_draft(w)
    prestate_plan_last(w)
    restore_write_draft(w, held)


def prestate_plan_and_file_held(w):
    """A file the owner sent, held with its card, and then a plan ("Posso?") that is the last message."""
    prestate_attachment_held(w)
    prestate_plan_last(w)


def prestate_question_of_other_project(w):
    """The router's question, bound to a project that does not list the sender (a project the bridge serves whose configuration cannot be read lists nobody): a reply to it is dropped."""
    prestate_router_question(w)
    w.b.bridge.projects.append({"id": "other-project", "name": "other-shop", "path": str(w.tmp_path / "no-such-project")})
    for card in w.b.bridge.ledger.data["cards"]:
        if card.get("kind") == "question" and card.get("chat") == OWNER:
            card["project"] = "other-project"


def hold_route(w):
    """A run of the router holds the project's route lock now (a line that routes meets it busy): taken here, let go by `drain` after the line."""
    w.route_fd = ops_core._try_lock(ops_core.context(w.path)["cfg"], "route.lock")
    assert w.route_fd is not None


def prestate_route_busy(w):
    hold_route(w)


def prestate_route_busy_ask_choice(w):
    """The choice of a file for an `ask` is open on the page (the draft of the question that several files could answer), and the router is busy: an answer to it waits in the queue."""
    add_source(w.world, "lease-contract", LEASE)
    add_source(w.world, "meeting-notes", NOTES)
    drafts.put("page", "", {"kind": "which", "line": "what is the notice period?", "ids": ["lease-contract", "meeting-notes"], "project": ops_natural.project_key(w.path)}, "ops",
               ttl=ops_natural.DRAFT_TTL)
    hold_route(w)


def drain(w):
    """After a line that was queued: the router is free again, and the queue is drained as the service drains it (`route_queued`, one entry per call), until nothing is left to route."""
    drained = []
    fd = getattr(w, "route_fd", None)
    if fd is None:
        return drained
    os.close(fd)
    w.route_fd = None
    for _ in range(6):
        done = ops.route_queued(w.path)
        drained.append(done)
        if done.get("routed") is None:
            break
    return drained


def prestate_reminder_draft(w):
    w.b.say(REMINDER_LINE)
    settle(w)


def prestate_reminder_expired(w):
    prestate_reminder_draft(w)
    w.b.bridge.monotonic = lambda base=time.monotonic() + 700.0: base
    w.b.bridge.remind.sweep()


def prestate_write_draft_title(w):
    w.b.say(WRITE_TITLE_LINE)
    settle(w)


def prestate_router_question(w):
    (w.world["adapter"] / "router-reply.md").write_text(ROUTER_TEMPLATE, encoding="utf-8")
    w.b.say(ROUTER_LINE)
    settle(w)
    w.refs["question"] = w.b.bridge.last_sent.get(OWNER)


def snapshots(w):
    """The calendar of five events of test_event_lookup.py as real snapshots (the stand-in providers of test_sources_mail.py), without the stand-in calendar server."""
    snaps = tcw.Snapshots(w.world, w.monkeypatch)
    import datetime
    snaps.now = datetime.datetime(2026, 10, 21, 17, 0, tzinfo=datetime.timezone.utc)
    w.monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: snaps.now)
    provided = []
    for day, start, end, title, ident in EVENTS:
        provided.append(tsm.event(len(provided) + 1, f"2026-10-{day}T{start}:00-03:00", f"2026-10-{day}T{end}:00-03:00", title, id=ident))
    snaps.calendar("agenda", "google", tcw.fgw.CALENDAR, provided)
    w.snaps = snaps


def prestate_event_list_shown(w):
    snapshots(w)
    if w.scenario["channel"] == "messaging":
        confirm(w, EVENT_LIST_LINE)
    else:
        say_ops(w, EVENT_LIST_LINE, w.scenario["channel"])


def prestate_file_list_shown(w):
    add_source(w.world, "lease-contract", LEASE)
    add_source(w.world, "meeting-notes", NOTES)
    if w.scenario["channel"] == "messaging":
        confirm(w, FILE_LIST_LINE)
    else:
        say_ops(w, FILE_LIST_LINE, w.scenario["channel"])


def prestate_attachment_held(w):
    update = {"update_id": 1, "sender": OWNER, "chat": OWNER, "private": True, "text": None, "action": None, "action_ref": None, "reply_to": None,
              "attachments": [{"ref": "r1", "name": "Q3 plan.pdf", "size": None, "type": "application/pdf"}]}
    w.b.bridge.handle(update)
    settle(w)


def prestate_config_unaccepted(w):
    file = Path(w.path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw["language"] = "pt-BR"      # a changed file nobody accepted: the project is not served until its hash is accepted
    file.write_text(json.dumps(raw))


PRESTATE_FUNCTIONS = {name: globals()[f"prestate_{name}"] for name in PRESTATES if name != "none"}
PRESTATE_FUNCTIONS["none"] = lambda w: None


# --- delivering the line, and the outcome -------------------------------------------------------------------------------------------------------------


def reply_to_of(w, scenario):
    """The platform's message id the line replies to: a card, the question of a plan, the numbered list, the router's question; a name with no message behind it is a message that is not there."""
    want = scenario.get("reply_to")
    if not want:
        return None
    return w.refs.get(want) or "999"      # `nothing`, and a state that has no such message


def action_of(w, scenario):
    """The id of the button a tap names: the Yes or No of the plan's question, the Approve or Reject of the newest card; a button that was never drawn is an id nobody holds."""
    word = scenario.get("action")
    chat = GROUP_CHAT if scenario["sender"] == "group" else SENDER_ID[scenario["sender"]]
    for card in reversed(w.b.bridge.ledger.data["cards"]):
        for action_id, said in (card.get("actions") or {}).items():
            if said == word and card.get("chat") == chat:
                return action_id
    return "99:" + str(word)


def deliver(w, scenario):
    """The one line: a messaging update through `Bridge.handle`, or `ops.say` for the page and the terminal. Returns what the operations layer returned (None for messaging)."""
    channel = scenario["channel"]
    if channel == "ops":
        return ops.say(w.path, scenario["text"], channel="messaging", sender=f"telegram:{SENDER_ID[scenario['sender']]}")
    if channel != "messaging":
        try:
            return say_ops(w, scenario["text"], channel)
        except (ops_core.OpsError, ops_core.RunBusy) as e:      # a refusal of the shell is an outcome (the message, never a crash)
            return {"reply": f"<{type(e).__name__}> {e}", "ran": None, "queued": None}
    sender = SENDER_ID[scenario["sender"]]
    group = scenario["sender"] == "group"
    chat = GROUP_CHAT if group else sender
    update = {"update_id": 2, "sender": sender, "chat": chat, "private": not group, "text": scenario["text"], "action": None, "action_ref": None, "reply_to": reply_to_of(w, scenario)}
    if scenario["kind"] == "action":
        update.update(text=None, action=action_of(w, scenario), action_ref="ref-2")
    elif scenario["kind"] == "attachment":
        update.update(attachments=[{"ref": 5}] if scenario["action"] == "invalid" else [{"ref": "r1", "name": "Q3 plan.pdf", "size": None, "type": "application/pdf"}])
    if scenario.get("forwarded"):
        update["forwarded"] = True
    w.update = update
    shown = update.get("reply_to")
    card = w.b.bridge.ledger.by_message(chat, shown) if shown and isinstance(shown, str) else None
    if update["text"] and card and card.get("kind") != "reminder" and inbound_kind(update) == "natural":
        w.recorder.fact("reply_to_card")
    w.b.bridge.handle(update)
    return None


def inbound_kind(update):
    return inbound.parse(update).get("kind")


def stored_rows(w):
    try:
        ctx = ops_core.context(w.path)
    except ops_core.NotAccepted:      # a project whose configuration nobody accepted stores nothing
        return []
    return ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)


def key_of_text(text):
    for key in NEUTRAL_KEYS:
        if text in phrases.every(key):
            return key
    return None


def sent_rows(w):
    path = w.b.folder / "sent.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def plan_items():
    found = []
    for item in list(pending_items._ITEMS.values()):
        state = item.get("state") if isinstance(item, dict) else getattr(item, "state", None)
        kind = item["kind"] if isinstance(item, dict) else item.kind
        found.append({"kind": kind, "op": (state or {}).get("op") if isinstance(state, dict) else None})
    return sorted(found, key=lambda x: json.dumps(x, sort_keys=True))


def draft_rows(w):
    found = []
    for (channel, sender), entry in list(drafts._DRAFTS.items()):
        draft = entry.get("draft") or {}
        found.append({"channel": channel, "sender": NAME_OF.get(str(sender).split(":")[-1], "other"), "owner": entry.get("owner"), "op": draft.get("op") or draft.get("kind")})
    if getattr(w, "b", None) is not None:
        found += [{"channel": "expired", "sender": NAME_OF.get(chat, "other"), "owner": "remind", "op": None} for chat in sorted(w.b.bridge.remind.expired)]
    return sorted(found, key=lambda x: json.dumps(x, sort_keys=True, default=str))


def shown(w, text):
    """A text of the outcome: the scratch folder of the scenario (it can be in a sentence of the runtime: an error that names a path) is replaced, then the digits and hexadecimal words."""
    text = text or ""
    for root in (w.root, os.path.realpath(w.root)):
        text = text.replace(root, "<tmp>")
    return mask(text)


def outcome(w, before, returned):
    """The normalised outcome of the line (OUTCOME_FIELDS); every collection is sorted."""
    scenario, recorder = w.scenario, w.recorder
    sent, ledger_added = [], []
    if scenario["channel"] == "messaging":
        for row in sent_rows(w)[before["sent"]:]:
            message = row["message"]
            sent.append({"to": NAME_OF.get(row["chat"], "other"), "text": shown(w, message.get("text")), "buttons": [a.get("label") for a in (message.get("actions") or [])],
                         "document": (message.get("document") or {}).get("name") if isinstance(message.get("document"), dict) else message.get("document"), "flags": {}})
        for card in w.b.bridge.ledger.data["cards"][before["ledger"]:]:
            ledger_added.append({"kind": card.get("kind"), "actions": sorted((card.get("actions") or {}).values()), "approvable": card.get("approvable"), "whole": card.get("whole")})
    else:
        flags = {"ran": returned.get("ran"), "queued": returned.get("queued"), "request": returned.get("request_id") is not None, "pending": returned.get("pending_id") is not None,
                 "resend": returned.get("resend") is not None, "plan_confirm": (returned.get("plan_confirm") or {}).get("op")}
        sent.append({"to": scenario["channel"], "text": shown(w, returned.get("reply")), "buttons": [], "document": None, "flags": flags})
        for done in getattr(w, "drained", []):      # what the drain of the queue answered, after the line was queued
            sent.append({"to": scenario["channel"] + "-drain", "text": shown(w, str(sorted((k, v) for k, v in done.items() if k in ("routed", "queued", "ran", "reason")))), "buttons": [], "document": None,
                         "flags": {"routed": done.get("routed"), "ran": done.get("ran")}})
    stored = []
    for row in stored_rows(w):
        if row["id"] in before["stored"]:
            continue
        key = key_of_text(row["text"])
        stored.append({"role": row["role"], "text": key if key else shown(w, row["text"]), "neutral": key is not None})
    update = getattr(w, "update", {})
    return {"trace": trace_of(recorder, scenario, update),
            "ops_calls": sorted(recorder.ops_calls, key=lambda x: json.dumps(x, sort_keys=True)),
            "sent": sorted(sent, key=lambda x: json.dumps(x, sort_keys=True)),
            "ledger_added": sorted(ledger_added, key=lambda x: json.dumps(x, sort_keys=True)),
            "drafts": draft_rows(w), "plans": plan_items(),
            "stored": sorted(stored, key=lambda x: json.dumps(x, sort_keys=True)),
            "jobs": sorted(recorder.jobs), "model_calls": w.model.calls - before["model"], "provider_calls": w.provider_starts.value}


def run_scenario(scenario, tmp_path, monkeypatch, line_hook=None) -> dict:
    """Build the world, put it in the scenario's pre-state, deliver the line, settle every thread and return the outcome. One scenario, one world, nothing shared. `line_hook(monkeypatch)`
    patches the code under test after the pre-state is built and before the line is delivered (the sensitivity checks of test_entry_replay.py: a claimer that takes nothing, two that swap places)."""
    w = open_world(scenario, tmp_path, monkeypatch)
    try:
        if scenario["channel"] != "messaging" and scenario["prestate"] not in OPS_PRESTATES:
            raise ValueError(f"{scenario['id']}: no pre-state {scenario['prestate']} on a {scenario['channel']} line")
        if scenario["channel"] != "messaging" and scenario["prestate"] == "router_question":
            (w.world["adapter"] / "router-reply.md").write_text(ROUTER_TEMPLATE, encoding="utf-8")
            say_ops(w, ROUTER_LINE, scenario["channel"])
        elif scenario["channel"] != "messaging" and scenario["prestate"] == "write_draft_title":
            say_ops(w, WRITE_TITLE_LINE, scenario["channel"])
        elif scenario["channel"] != "messaging" and scenario["prestate"] == "reminder_draft":
            say_ops(w, REMINDER_LINE, scenario["channel"])
        else:
            PRESTATE_FUNCTIONS[scenario["prestate"]](w)
        before = {"sent": len(sent_rows(w)) if w.scenario["channel"] == "messaging" else 0,
                  "ledger": len(w.b.bridge.ledger.data["cards"]) if w.scenario["channel"] == "messaging" else 0,
                  "stored": {row["id"] for row in stored_rows(w)}, "model": w.model.calls}
        if line_hook is not None:
            line_hook(monkeypatch)
        w.recorder.live = True
        returned = deliver(w, scenario)
        w.drained = drain(w)
        if scenario["channel"] == "messaging":
            settle(w, extra=w.held)
            if w.held:
                w.release.set()
                settle(w)
        w.recorder.live = False
        return outcome(w, before, returned or {})
    finally:
        w.recorder.live = False
        w.close()


# --- the corpus and the golden ------------------------------------------------------------------------------------------------------------------------


CORPUS_FILE = HERE / "entry_corpus.jsonl"
GOLDEN_FILE = HERE / "entry_golden.jsonl"
SCENARIO_KEYS = ("id", "channel", "platform", "sender", "prestate", "text", "reply_to", "forwarded", "kind", "action")


def read_jsonl(path):
    return [json.loads(raw) for raw in Path(path).read_text(encoding="utf-8").splitlines() if raw.strip()]


def corpus_sha256(path=CORPUS_FILE) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_scenario(scenario):
    """The problems of a scenario's shape: an empty list when it is well formed."""
    problems = []
    if set(scenario) != set(SCENARIO_KEYS):
        problems.append(f"keys {sorted(scenario)}")
    if scenario.get("channel") not in CHANNELS:
        problems.append("channel")
    if scenario.get("platform") not in PLATFORMS:
        problems.append("platform")
    if scenario.get("sender") not in SENDERS:
        problems.append("sender")
    if scenario.get("prestate") not in PRESTATES:
        problems.append("prestate")
    if scenario.get("reply_to") not in REPLY_TO:
        problems.append("reply_to")
    if scenario.get("kind") not in KINDS:
        problems.append("kind")
    if scenario.get("action") not in ACTIONS:
        problems.append("action")
    if scenario.get("channel") in OPS_CHANNELS and (scenario.get("prestate") not in OPS_PRESTATES or scenario.get("platform") != "buttons" or scenario.get("sender") != "owner"):
        problems.append("a page, terminal, mcp or chat line is the owner's, on no platform, in a pre-state of OPS_PRESTATES")
    if scenario.get("channel") == "ops" and (scenario.get("prestate") != "none" or scenario.get("platform") != "buttons" or scenario.get("sender") not in ("owner", "reader", "asker", "reader_interpret")
                                              or scenario.get("kind") != "text" or scenario.get("reply_to") or scenario.get("forwarded")):
        problems.append("an ops line is a listed sender's plain text, in the pre-state none")
    if not isinstance(scenario.get("text"), (str, type(None))):
        problems.append("text")
    if scenario.get("kind") == "action" and scenario.get("action") in (None, "invalid"):
        problems.append("a tap names its button")
    if scenario.get("kind") != "attachment" and scenario.get("action") == "invalid":
        problems.append("invalid attachments need kind attachment")
    return problems
