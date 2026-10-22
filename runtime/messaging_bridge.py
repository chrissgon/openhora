# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's logic (runtime/messaging.py is its shell): notices out, intents in, every operation through
one call path. No model sits between a messaging app and the operations layer; free text goes to `say`.

The one call path (`Bridge.run_op`): every operation a person asks for from a messaging app is called from there, with
the channel `messaging`, after `operations.permitted` (the channel policy, decision M-8) said yes for it. The policy is
read from the project's accepted configuration at each call, so a change the person accepted takes effect at once, and
a configuration that is not accepted refuses everything. The operations layer enforces the same policy itself for a
command typed into `say` and for `approve`, so a mistake here cannot widen it.

Senders. An update from a sender who is not in `messaging.senders.<platform>` of at least one served project, or from a
chat that is not private, is dropped with no reply and no log of who or what. A sender who is listed in several
projects chooses with /project; the default is the first.

Reads. The bridge reads `pending` itself, outside the policy's `read` group, to build cards and to bind an approval to
the card the person saw; `read` only decides what a person may ask for (/pending, `status`, and the like), and a policy
without it also switches the notices off.

Skip and re-check. A project whose configuration is not accepted, or that lists no sender for the platform, is skipped, not
a reason to stop: the bridge says why in one log line when the project's state changes, looks again every notice period
(`recheck`, at the start of each tick), and serves the project from its accepted file the moment it is ready. With every
project skipped it keeps running.

Notices. Each tick, per project, every open decision gets one card per listed sender, once per content (the ledger,
runtime/messaging_ledger.py). A changed plan, or any decision whose content hash changed, gets a new card. At most 10
cards per project and tick; the rest are announced in one line.

Deferred. A provider whose platform lets a business write first only inside a window (the official WhatsApp API) answers a send
`ok: false, kind: "deferred"`. That is not an error: the card is not recorded in the ledger, so it is tried again at the next
notice period and at once when the person writes (the chat is remembered), and the bridge logs one line for a card and a chat
at most every 24 hours, never every tick.

Approvals. A tap or /approve is bound to the card the person saw. A plan is approved with the hash the ledger recorded
(ops.approve refuses a plan that changed). An acceptance has no hash, so the bridge compares the decision's text now with
the hash recorded for the card and approves nothing when they differ. An effect is approved here only when the project's accepted
policy grants the messaging channel that effect's word (`approve-effect-<word>`, operations.GRANTS; POL-1) and ALL of these hold:
the card the person saw carried the whole text (the ledger's `whole`), the decision says the whole effect fits on a card
(`effect_on_cards`: not an e-mail with an attachment, not a post with an image), and the card's hash is the decision's own
`payload_sha256` (a card made for an earlier content is `CHANGED`, nothing runs and a new card is sent). A line typed with a hash must carry the
card's hash. Otherwise the reply says to approve it on the platform's page (decision D8, the default; no command and no hash on a phone, limit L62). The approval runs in a job thread:
an effect may take minutes.

Who acted (POL-2). The update's sender is the one the PROVIDER authenticated (Telegram's user id, a snowflake, the signed phone digits), and a card is
sent to a private chat whose id is that sender's: the bridge makes the sender's key (`<platform>:<id>`, operations.sender_key) and asks the policy for
THAT sender, so each listed sender has the profile `runtime.json` gives them (`messaging.senders`), else the channel's. Nothing a sender sends can name
a profile or change one: a profile changes only by accept-config in the terminal. Every check reads the accepted configuration when the sender ACTS
(`settings` at each call), never when the card was sent, so a sender removed or narrowed since loses the act at once; a card is acted on only in the
chat it was sent to (the ledger's `chat` must be the acting sender's); the operations layer is told the sender and records it with the decision
(ops_actor); and a profile with `notices: actionable` is sent a card only for a decision it can act on or answer.

A platform that declares `actions_need_reply` (e-mail) acts on a typed approve, reject, release or answer only when the update is a reply to the
ledger's card of that very decision in that chat, and the action is bound to that card, not to the newest one.

Unread messages. A provider that gives up a message it could not read (the e-mail provider, after the server refused it for an hour) writes an error
event of kind `skipped`; the listen session only counts them (`take_unread`). At the end of each tick (`notify_unread`) the bridge sends the senders
the "N more waiting" line goes to (`hears_count`) one fixed sentence of its own, never the provider's reason, a uid, a Message-ID, an address or a
subject, at most once an hour to a chat, and only to a sender who still hears the count when the line goes out (the policy is read again then); the count of what
a chat has not been told lives in memory, so a restart forgets it (the provider's log line stays). A line that failed to send is tried again an hour later.

Files (ATT-1b). A file a listed sender sends is fetched only when THAT sender's profile permits `attachment-hold` (the group `add-sources`, or the grant
`add-sources-direct`); runtime/messaging_attach.py does the work, from the update to the fetch, the hold, the card or the add, and from the card's answer to the
add or the discard. The bridge dispatches to it in three places: an update of the kind `attachment`, a tap on a card of the kind `attachment`, and `/add <n>` and
`/discard <n>`; `/pending` also lists the files that wait.

Waiting lines (BQ-1). A text line that would run `say` (a plain line, `/new`, `/ask`) and meets a busy project is kept, not refused: when a model job of the
project holds its slot (`shell_kit.Busy`), or the operation answers `RunBusy` (a run of another shell holds the planning agent), the bridge keeps the line in
MEMORY (at most 1 per chat, 5 per project; beyond that the sentence it always gave) and answers `QUEUED`. The oldest line of a project whose slot is free is
started at each iteration of the loops and at the end of each job, through `run_op`, so the sender's policy is read again when the line runs: a sender removed
from the configuration meanwhile is dropped with no reply, one narrowed is refused with the policy's sentence. A line waiting `QUEUE_WAIT` seconds is dropped
with `QUEUE_EXPIRED`; a stop tells each waiting chat `QUEUE_STOPPED`; a crash loses them. The text is never logged and never written to the ledger (the ledger holds
no text of a project). A tap, and every command the bridge or the table handles (`/progress`, `/cancel`, `/approve`...), is never kept.

Reminders (RM-1). `/remind <time> <text>`, `/reminders` and `/forget <n>` are done by runtime/messaging_remind.py through the one call path (the group
`reminders`, in no default policy, so a sender must be given it and the person confirms that with `accept-config --widen`). At the end of each tick
`Reminders.deliver` sends what is due: only to the private chat of the sender it was made for, with that sender's own words (none in `notices: count`),
after the operations layer read the configuration and the sender's profile again, so a sender removed or narrowed before the time gets nothing.
A reminder is a notice and never an effect (limit L51).
Reminders in the person's own words (NR-1). A plain line that code matched to a reminder operation, and `/remind <rest>` outside the strict grammar, arrive as
the intent `natural` and are done by `remind.natural` with no model, no route lock and no model slot; a question the bridge asked about a reminder is kept as a draft
in `self.remind.drafts` (memory only) and the next update of that chat finishes it or drops it (`remind.answer`).

Language (LR-1). Every sentence the bridge says is the phrase table's (runtime/phrases.py) in the project's language: `Bridge.cfg` reads the key `language` from
`config` when the sentence is said (an unaccepted file too), `Bridge.t` picks the sentence, and `cards.build` is handed the settings for the frames of a card. A project with
no `language` gets the English constants below, byte for byte; a tag with no table gets English. The decision's own text, the project's name, the commands, ids and the
text of an `OpsError` are not translated (contracts/runtime.md, "The language of a deliverable").

Words that decide a card (S2, limit L64; the words are runtime/card_words.py). A plain line that is, whole, only an approve or a reject form ("Aprovo", "sim", "pode marcar", "nao",
"aprovo o 2") decides a decision card exactly as that card's own button would (`word_line` -> `Bridge.act`, which asks the policy for the sender, binds the act to the card's hash and
runs the same operation), and only when ALL of these hold: the update is a private line of a listed sender in the chat the card was sent to and is not a forwarded message; the card is
the LAST message the platform sent to that chat (`last_sent`, memory only: every message, a reply or a delivered reminder included, so any later message ends it and a restart forgets it);
it is the only decision card of that sender in that chat that a word could decide (sent whole, offering the act); the decision is open and its content hash is the card's (`CHANGED` and a
new card otherwise). Several such cards: one numbered list is sent (kind and title, no id) and nothing is decided; for `LIST_SECONDS`, while the list is the last message, a position
("aprovo o 2") decides that card; "approve all" is never done (`WORD_ONE_AT_A_TIME`); "todos nao" rejects every card of the list, each through its own card. A line that is a reply
(the reply gesture) to a decision card decides THAT card, whether or not it is the last message. A platform that declares `actions_need_reply` (e-mail) is decided only by a reply to
the card. Anything else is not touched: the line goes on as it always did. A card on a platform with no buttons ends with `REPLY_WORDS_LINE` in place of "Send /approve 12".
A table command typed on a phone (`/cancel 8`) is answered with a sentence in the project's language (`command_sentence`), never the operation's JSON.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
import re
import threading
import time
import traceback

import card_words
import greeting
import messaging_attach as attach
import messaging_cards as cards
import messaging_failure as failure
import messaging_guard as guard
import messaging_outcome as outcome
import messaging_pending as pending_view
import messaging_inbound as inbound
import messaging_provider as provider
import messaging_remind as remind
import messaging_typing as indicator
import natural
import natural_time
import phone_errors
import phone_refusal
import phrases
import shell_kit

CHANNEL = "messaging"
CARDS_PER_TICK = 10
POLL_SECONDS = 25
DEFERRED_LOG_EVERY = 86400.0   # seconds between two log lines about one deferred card
RETRY_SECONDS = 5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROPPED = "dropped an update from an unlisted sender"
# The sentences a person reads are the phrase table's (runtime/phrases.py, package LR-1): these names keep the English text (a test, a card and the docs read
# them) and each place below says the sentence in the project's language. NOT_ACCEPTED_WHY and the other *_WHY texts are for the log, and stay English.
STALE = phrases.en("STALE")
NO_CARD = phrases.en("NO_CARD")
CHANGED = phrases.en("CHANGED")
STILL_WORKING = phrases.en("STILL_WORKING")
RUN_BUSY = phrases.en("RUN_BUSY")
NOT_ACCEPTED = phrases.en("NOT_ACCEPTED").replace("{where}", "").rstrip()      # the sentence up to the place it points to ({where}: the page, with its link)
NOT_ACCEPTED_WHY = "its configuration is not accepted (run accept-config in the terminal)"
NO_SENDER_WHY = "runtime.json messaging.senders.{platform} lists no sender"
UNREADABLE_WHY = "its configuration cannot be read"
EFFECT_REPLY = phrases.en("EFFECT_REPLY").replace("{where}", "").rstrip()      # the sentence up to the place it points to ({where}: the page, with its link)
TOO_LONG = phrases.en("TOO_LONG").replace("{where}", "").rstrip()      # the sentence up to the place it points to ({where}: the page, with its link)
WRONG_HASH = phrases.en("WRONG_HASH")
NOT_OPEN = phrases.en("NOT_OPEN")
NOT_OFFERED = phrases.en("NOT_OFFERED")
REPLY_TO_CARD = phrases.en("REPLY_TO_CARD")
FWD_NOT_A_REQUEST = phrases.en("FWD_NOT_A_REQUEST")
UNREAD_ONE = phrases.en("UNREAD_ONE")
UNREAD_MANY = phrases.en("UNREAD_MANY")
UNREAD_EVERY = 3600.0   # seconds between two such lines to one chat
QUEUED = phrases.en("QUEUED")
QUEUE_EXPIRED = phrases.en("QUEUE_EXPIRED")
QUEUE_STOPPED = phrases.en("QUEUE_STOPPED")
QUEUE_WAIT = 1800     # seconds a line may wait for the project
QUEUE_PER_CHAT = 1    # waiting lines of one chat
QUEUE_PER_PROJECT = 5
QUEUE_RETRY = 1.0     # seconds before a line that met `RunBusy` is started again
QUEUE_POLL = 2        # seconds a polling loop waits for the messenger while a line waits out a `RunBusy` pause (a held slot is looked at when its job ends)
QUEUE_STOP_WAIT = 10.0   # seconds, in all, the stop messages may take (they go out together); the runs end after that
LIST_SECONDS = 600.0   # seconds the numbered list of cards waits for a position: the conversation spec's choice (3.5, LIST_TTL), not measured
LIST_MAX = 10          # cards the numbered list names (the newest)
NOT_DECISION = ("reminder", "question", "attachment")   # the kinds of ledger record that are not a decision card a word could decide
RESEND_EVERY = 60.0   # seconds: a decision named in words has its card sent again at most this often to one chat
QUEUE_COMMANDS = ("new", "ask")   # the slash commands that may wait: the ones that run the planning agent or the answer run; the others are not lines but acts


def home_folders() -> list:
    """The person's home folder as it is spelled and as it resolves (a link), longest first; none for an empty home or the root."""
    found = []
    for spelled in (os.path.expanduser("~"), os.environ.get("HOME", "")):
        for path in (spelled, os.path.realpath(spelled) if spelled else ""):
            path = path.rstrip("/")
            if path and path not in found:
                found.append(path)
    return sorted(found, key=len, reverse=True)


def scrub(text):
    """The text with the home folder replaced by `~`, so that a message to a phone carries no username or folder layout, and a command in it still
    works when pasted in the person's shell: an unquoted `~/x` is expanded by the shell, and a quoted path (`'<home>/my folder'`, which the
    command builders quote when it has a space) becomes `~/'my folder'`, where the tilde stays outside the quotes."""
    if not isinstance(text, str):
        return text
    for home in home_folders():
        quoted = re.escape(home)
        text = re.sub(r"'" + quoted + r"(/[^']*)?'", lambda m: "~/'" + m.group(1)[1:] + "'" if m.group(1) else "~", text)
        text = re.sub(r"(?<![\w.~/-])" + quoted + r"(?=/|\.?(?:[\s'\"`)\]>:,;]|$))", "~", text)
    return text


def scrub_message(message: dict) -> dict:
    """A neutral message as it goes out: the text and the file (name and text) scrubbed; buttons and the link are the bridge's own and carry no path."""
    out = dict(message)
    out["text"] = scrub(out.get("text"))
    footer = out.get("footer")
    if isinstance(footer, list):      # the lines a card ends with, handed over beside the text (e-mail): scrubbed with it, so that the text still ends with them
        out["footer"] = [scrub(line) for line in footer]
        tail = "\n\n" + "\n".join(out["footer"])
        if not (out["footer"] and isinstance(out["text"], str) and out["text"].endswith(tail)):
            del out["footer"]         # a footer the text no longer ends with is not handed over (the provider would not move it)
    document = out.get("document")
    if isinstance(document, dict):
        out["document"] = {**document, "name": scrub(document.get("name")), "text": scrub(document.get("text"))}
    return out


def dated(message: dict, cfg) -> dict:
    """The message with its dates said in the project's language (phrases.localize_dates): the text, the footer lines and the document's text, the same way, so that a footer
    the text ends with is still the text's ending. Rendering only: the stored decision, its hash and the approval are of the stored text."""
    out = dict(message)
    out["text"] = phrases.localize_dates(out.get("text"), cfg)
    if isinstance(out.get("footer"), list):
        out["footer"] = [phrases.localize_dates(line, cfg) for line in out["footer"]]
    document = out.get("document")
    if isinstance(document, dict):
        out["document"] = {**document, "text": phrases.localize_dates(document.get("text"), cfg)}
    return out


def queueable(text) -> bool:
    """Whether a line may wait for the project: a plain line, or the slash command `new` or `ask` (with or without `@bot`). Any other command is an
    act of the table (`/cancel`, `/approve`, `/progress`...) and is refused as it always was: a brake kept behind the run it should stop is of no use."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return bool(text)
    word = text[1:].split(None, 1)
    return bool(word) and word[0].split("@", 1)[0].lower() in QUEUE_COMMANDS


def reason_of(error) -> str:
    """Why a configuration cannot be read, for the log: the refusal of runtime.json (a sentence about a key, never a sender: digits of eight or more are
    masked all the same), else nothing."""
    text = " ".join(str(error).split())
    if not text.startswith("runtime.json "):
        return ""
    return ": " + re.sub(r"\d{8,}", "<digits>", text)[:200]


class Fatal(Exception):
    """The bridge cannot go on (the provider is not configured): the shell prints the sentence and exits 3."""


class Refused(Exception):
    """A request the bridge answers with a sentence and no operation."""


class Bridge(shell_kit.Jobs):
    Refused, NOT_ACCEPTED, NO_CARD = Refused, NOT_ACCEPTED, NO_CARD      # what messaging_attach reads of the bridge

    def __init__(self, ops_module, projects, messenger, ledger, platform: str, log=None, clock=None):
        super().__init__(ops_module, projects, log)
        try:
            natural_time.languages()      # the language tables are read and checked once, here: a table that breaks the schema stops the bridge with a sentence (NR-1)
        except ValueError as e:
            raise Fatal(f"the natural-request language tables are not valid: {e}") from None
        self.attach = attach.Attachments(self)
        self.remind = remind.Reminders(self)
        self.messenger, self.ledger, self.platform = messenger, ledger, platform
        self.remind.drafts.clear()      # a new bridge starts with no question open: they are lost on a restart (the store of drafts is shared with the operations layer)
        self.clock = clock or shell_kit.now
        self.chosen = {}       # sender -> project id
        self.more = {}         # (project id, chat) -> the number last announced as waiting to that chat (set once the line went out)
        self.policy_noted = set()
        self.everyone = list(self.projects)   # every project given; `self.projects` is the part that is ready to serve
        self.skipped = {}                     # project id -> why it is skipped now (absent: served)
        self.config_told = set()              # (chat, configuration hash) already told that the configuration must be accepted (memory only; S12)
        self.deferred = {}                    # (project id, pending id, chat) -> when it was last logged as deferred
        self.deferred_chats = set()           # chats with a card kept for later: an update from one asks for a notice at once
        self.unread_waiting = {}              # chat -> how many skipped messages it has not been told of (memory only)
        self.unread_told = {}                 # chat -> time.monotonic() of the last line about skipped messages
        self.monotonic = time.monotonic       # the clock of the waiting lines (a test moves it)
        self.resent = {}                      # (project id, chat, decision) -> when its card was last sent again to that chat (NR-2: at most once in RESEND_EVERY seconds)
        self.last_sent = {}                   # chat -> the id of the last message of any kind sent to it (memory only; S2, limit L64): a word decides a card only while the card is it
        self.send_seq = {}                    # chat -> how many sends to it have started (memory only): `last_sent` is stored only by the send that started last
        self.send_lock = threading.Lock()     # guards `send_seq` and `last_sent`: the update thread and the job threads all send
        self.card_lists = {}                  # chat -> the numbered list of cards last sent: {"message_id", "at" (monotonic), "cards": [(project id, pending id, content hash)]} (memory only)
        self.last_message = {}                # chat -> the id of the last message sent to it (memory only): the question a draft asked is answered by a reply to it
        self.waiting = []                     # the lines kept for a busy project, oldest first (memory only): {"n", "project", "chat", "text", "since", "after"}
        self.ticket = 0
        self.queue_lock = threading.Lock()    # guards `waiting` and `ticket`
        self.drain_lock = threading.Lock()    # one drain at a time, so that lines start in order
        self.scope = threading.local()        # the languages read for the update, the tick or the drain being handled on this thread (`read_once`)
        self.session_ready = None             # a listen provider: whether its session is ready (the loop sets it); no waiting line starts while it is not

    # --- the projects and their settings ---------------------------------------------------------------------

    def settings(self, project: dict):
        """The accepted settings of a project for this platform, or None when its configuration is not accepted."""
        found = self.ops.config(project["path"])
        if not found.get("accepted"):
            return None
        messaging = found.get("messaging") or {}
        return {"senders": list((messaging.get("senders") or {}).get(self.platform) or []), "language": found.get("language"),
                "notices": messaging.get("notices") or "text", "page_url": messaging.get("page_url"),
                "policy": found.get("channels") or {}, "profiles": found.get("policies") or {},
                "sender_profiles": (messaging.get("sender_profiles") or {}).get(self.platform) or {},
                "channel_profile": (found.get("channel_profiles") or {}).get(CHANNEL)}

    def cfg(self, project=None, chat=None) -> dict:
        """What the phrase table reads of a project: {"language": its `language` setting}, read from its configuration now (an unaccepted one included: the
        sentence that says so is said in the project's language too), or {} when it cannot be read. With no project, the first project served that lists `chat`.
        Inside `read_once` (an update, a tick, a drain, and the jobs they start) a project is read once and the answer is kept until the scope ends."""
        cache = getattr(self.scope, "cache", None)
        try:
            if project is None and chat is not None:
                project = next(iter(self.projects_for(chat)), None)
            if project is None:
                return {}
            if cache is not None and project["id"] in cache:
                return cache[project["id"]]
            read = self.ops.config(project["path"])
            page_url = (read.get("messaging") or {}).get("page_url")
            found = {"language": read.get("language"), **({"page_url": page_url} if page_url else {})}
            if cache is not None:
                cache[project["id"]] = found
            return found
        except Exception:      # a sentence is never held back by a configuration that cannot be read: it is said in English
            return {}

    @contextlib.contextmanager
    def read_once(self):
        """The scope inside which `cfg` reads a project's language once: the handling of one update, one tick, one drain. A job it starts keeps the languages
        read (`inherit`), so a long job says its last sentence in the language it began with."""
        if getattr(self.scope, "cache", None) is not None:
            yield
            return
        self.scope.cache = {}
        try:
            yield
        finally:
            self.scope.cache = None

    def inherit(self, call):
        """`call` as a job that sees the languages read by the thread that creates it."""
        cache = getattr(self.scope, "cache", None)
        if cache is None:
            return call

        def run():
            self.scope.cache = cache
            try:
                return call()
            finally:
                self.scope.cache = None
        return run

    def t(self, key: str, project=None, chat=None, cfg=None, **fields) -> str:
        """The sentence `key` in the project's language (runtime/phrases.py). `cfg` is the language already read (a settings dict), else it is read from
        `project`, else from the first served project that lists `chat`."""
        cfg = cfg if cfg is not None else self.cfg(project, chat)
        if "{where}" in phrases.en(key):      # a sentence that points to the page (package LIVE-2): the place is the project's page link, else the words
            return phrases.phone(key, cfg, **fields)
        return phrases.text(key, cfg, **fields)

    def key(self, sender: str) -> str:
        """The key of a sender in the policy: `<platform>:<id>` (operations.sender_key)."""
        return self.ops.operations.sender_key(self.platform, sender)

    def for_reader(self, project: dict, item: dict, key: str) -> dict:
        """The decision as the card for `key` (a sender key) is drawn: the save of a file a sender sent also says, as a boolean, whether `key` is that sender
        (`reader_sent_file`; the sender's account stays in the store, W4a). Any other decision is returned as it is."""
        if item.get("kind") != "effect" or item.get("effect_sender_only") is not True:
            return item
        asked = self.ops.pending(project["path"], pending_id=item["id"], reader=key)
        return {**item, "reader_sent_file": asked.get("reader_sent_file") is True}

    def wants(self, project: dict, settings: dict, item: dict, sender: str) -> bool:
        """Whether this sender is sent a card for the decision: their profile permits reading the pending decisions and, when the profile says
        `notices: actionable`, the card would offer them something to act on or answer."""
        operations = self.ops.operations
        key = self.key(sender)
        if not operations.permitted("pending", CHANNEL, settings["policy"], None, key):
            return False
        named = settings["sender_profiles"].get(sender) or settings["channel_profile"]
        if (settings["profiles"].get(named) or {}).get("notices") != "actionable":
            return True
        built = cards.build(project["name"], self.for_reader(project, item, key), self.messenger.capabilities(), settings["policy"], settings["notices"],
                            settings["page_url"], operations=operations, sender=key, cfg=settings)
        return bool(built["actionable"])

    def hears_count(self, settings: dict, sender: str):
        """The sender, when the "N more waiting" line may go to them: their profile reads what waits and sends them every notice (a count of decisions
        they are not sent a card for would tell a profile what it may not know)."""
        named = settings["sender_profiles"].get(sender) or settings["channel_profile"]
        if (settings["profiles"].get(named) or {}).get("notices") == "actionable":
            return None
        return sender if self.ops.operations.permitted("pending", CHANNEL, settings["policy"], None, self.key(sender)) else None

    def recheck(self) -> None:
        """Look at every project again: serve those with an accepted configuration that lists a sender for the platform,
        skip the others. One log line when a project's state changes, none otherwise."""
        ready = []
        for project in self.everyone:
            try:
                found = self.settings(project)
                why = NOT_ACCEPTED_WHY if found is None else (None if found["senders"] else NO_SENDER_WHY.format(platform=self.platform))
            except self.ops.OpsError as e:
                why = UNREADABLE_WHY + reason_of(e)
            if why is None:
                ready.append(project)
            if self.skipped.get(project["id"]) != why:
                if why:
                    self.log(f"skipping {project['name']}: {why}")
                    self.skipped[project["id"]] = why
                else:
                    self.log(f"{project['name']} is ready: now served")
                    del self.skipped[project["id"]]
        self.projects = ready

    def projects_for(self, sender: str) -> list:
        out = []
        for project in self.projects:
            try:
                settings = self.settings(project)
            except self.ops.OpsError:
                continue
            if settings and sender in settings["senders"]:
                out.append(project)
        return out

    def config_pending(self, update: dict, sender: str, chat: str) -> None:
        """A sender whose line cannot be served because the project's configuration is not accepted is told so, once per chat and per hash of the file (S12): one plain sentence
        in the project's language, with no hash, path or command (limit L62; those are in the terminal and in the log). The line is never acted on. Who is told is read from the
        file itself (the senders it lists for this platform), the one read of an unaccepted file: the sentence says nothing of the project; a chat that is not the sender's own
        private chat, an empty update and a sender no file lists are told nothing."""
        if not (update.get("private") and chat == sender and ((update.get("text") or "").strip() or update.get("action") or update.get("attachments"))):
            return
        for project in self.everyone:
            try:
                found = self.ops.config(project["path"])
            except self.ops.OpsError:
                continue
            listed = ((found.get("messaging") or {}).get("senders") or {}).get(self.platform) or []
            key = (chat, found.get("sha256"))
            if found.get("accepted") or sender not in listed or key in self.config_told:
                continue
            if self.reply(chat, self.t("CONFIG_PENDING", cfg={"language": found.get("language")}), project):
                self.config_told.add(key)
            return

    def listed_in(self, project: dict, sender: str) -> bool:
        """Whether the sender is listed for this very project: a card of one project is acted on only by its senders."""
        try:
            settings = self.settings(project)
        except self.ops.OpsError:
            return False
        return bool(settings) and sender in settings["senders"]

    def project_of(self, sender: str, listed: list) -> dict:
        wanted = self.chosen.get(sender)
        return next((p for p in listed if p["id"] == wanted), listed[0])

    # --- sending ---------------------------------------------------------------------------------------------

    def deliver(self, chat: str, message: dict, guard_text: bool = False):
        """The one point where the bridge sends anything: every reply, card and file passes the filter that keeps the home folder off a phone and says its dates in the
        project's language. With `guard_text` (the error text of the operations layer: platform text that is not built from a phrase key) it also passes the net that
        keeps a command or a path of this machine off a phone (messaging_guard, limit L62). A card and a reply that quotes the person's data never do: what is quoted is
        theirs, and a card shows what is approved exactly as it is."""
        cfg = self.cfg(chat=chat)
        message = dated(scrub_message(message), cfg)
        with self.send_lock:
            seq = self.send_seq[chat] = self.send_seq.get(chat, 0) + 1
            self.last_sent[chat] = None      # while a message is on its way no card is the last one (S2: a word that comes in that moment decides nothing)
            mine = getattr(self.scope, "seqs", None)
            if mine is not None:
                mine.append(seq)
        sent = self.messenger.send(chat, guard.guard_message(message, cfg, self.guarded) if guard_text else message)
        with self.send_lock:
            if self.send_seq.get(chat) == seq:      # a send that started later decides what the last message is, whichever of the two the platform finished first
                self.last_sent[chat] = str(sent) if sent else None
        return sent

    def guarded(self, kinds: list) -> None:
        """What the net under the phone's sentences (messaging_guard) cut from a message: the kinds only, never the text."""
        self.log(f"a message carried {' and '.join(kinds)} of this machine; it was cut before it was sent")

    def reply(self, chat: str, text: str, project=None, guard=False):
        """Send a reply. True when every piece went out, False when a send failed (logged), None when the platform deferred it
        (it cannot take a message yet: not an error, not logged, and the caller may try again). `project` names the language of the line that says there is
        no reply."""
        caps = self.messenger.capabilities()
        if text:
            text = phone_errors.said(phone_refusal.plain(text, self.cfg(project, chat)), self.cfg(project, chat))      # S14: an `error: ` text of the operations layer is the language's sentence on a phone (phone_errors). S10: the operations layer's own refusal (a Refused or an OpsError a path above passes on) is one plain sentence on a phone: never "error:", a command or an operation's name; any other text is as it was
        for piece in cards.split(text or self.t("NO_REPLY", project=project, chat=chat), caps["max_text"]):
            try:
                sent = self.deliver(chat, {"text": piece, "actions": [], "link": None, "document": None}, guard)
                self.last_message[chat] = str(sent) if sent else None
                self.scope.replied = str(sent) if sent else None      # this thread's own last piece, for `note_asked`: the shared dict above can be changed meanwhile by another thread's send
            except provider.MessengerError as e:
                if e.kind == "deferred":
                    return None
                self.log(f"a reply could not be sent ({e.kind})")
                return False
        return True

    def ask_yes(self, project: dict, chat: str, text: str) -> bool:
        """Send a question about a reminder with ONE button, "Yes" (NR-1), and bind it in the ledger (kind `reminder`; the ledger holds no text: the project, the chat, the
        message and the action id). False when the platform has no buttons, the text does not fit one message, or the send failed: the caller then sends the plain
        question, which is answered by a typed "yes". The tap is handled by `remind.tapped`."""
        caps = self.messenger.capabilities()
        if not (caps.get("buttons") and caps.get("max_buttons", 0) >= 1) or len(text) > int(caps.get("max_text") or 0):
            return False
        action = f"{self.ledger.next_seq()}:yes"
        try:
            sent = self.deliver(chat, {"text": text, "actions": [{"id": action, "label": phrases.text("NT_BTN_YES", self.cfg(project))}], "link": None, "document": None})
        except provider.MessengerError:
            return False
        self.last_message[chat] = str(sent) if sent else None
        try:
            self.ledger.add({"project": project["id"], "pending_id": None, "kind": "reminder", "content_sha256": "", "chat": chat, "message_id": sent, "actions": {action: "yes"},
                             "sent_at": self.clock(), "whole": True, "approvable": False, "blocked": None, "effect_word": None})
        except OSError as e:
            self.log(f"the ledger could not be written ({e.__class__.__name__})")
        return True

    def allow(self, project: dict, op: str, kind=None, sender=None) -> dict:
        """The project's accepted settings when the policy permits the operation (for this kind of decision) to THIS sender (their profile, read now),
        else Refused with the sentence the operations layer uses too."""
        if sender is None:
            raise RuntimeError("the bridge asks the policy for a sender, never for the channel alone")
        settings = self.settings(project)
        if settings is None:
            raise Refused(self.t("NOT_ACCEPTED", project=project))
        operations = self.ops.operations
        if not operations.permitted(op, CHANNEL, settings["policy"], kind, self.key(sender)):
            raise Refused(operations.not_enabled(op, CHANNEL))
        return settings

    def run_op(self, project: dict, op: str, kind=None, sender=None, allow_as=None, **args):
        """The one call path: the policy first (for the sender's profile), then the operation, as the channel `messaging` and, when it takes one,
        as that sender (the layer asks the policy again for them and records who acted). `allow_as` names the operation whose group the
        policy is asked for when it is not the one called: a typed `/ask` is a `say`, and needs the group `ask`, not `talk`."""
        self.allow(project, allow_as or op, kind, sender)         # raises when no sender is named
        row = self.ops.operations.by_name(op)
        function = getattr(self.ops, row["call"])
        if row.get("channel_arg"):
            args["channel"] = CHANNEL
            if sender is not None:
                params = inspect.signature(function).parameters.values()
                if any(p.name == "sender" for p in params):
                    args["sender"] = self.key(sender)
                elif not any(p.kind == p.VAR_KEYWORD for p in params):      # a real operation that cannot be told who acts would be asked for the channel alone: never
                    raise RuntimeError(f"the operation {op} takes no sender: the bridge does not call it")
        return function(project["path"], **args)

    def send_card(self, project: dict, settings: dict, item: dict, chat: str) -> bool:
        operations = self.ops.operations
        caps = self.messenger.capabilities()
        sender = self.key(chat)
        item = self.for_reader(project, item, sender)
        card = cards.build(project["name"], item, caps, settings["policy"], settings["notices"],
                           settings["page_url"], operations=operations, sender=sender, cfg=settings)
        document = card["message"]["document"]
        if document and card["gated"] and card["approvable"]:
            # An approval needs the whole text DELIVERED: the file goes first, as a message of its own, and the card with the buttons only after
            # the provider confirmed it. A file that failed (or a send that could not be told) makes a card with no approval that says so.
            state = self.send_document(project, item, chat, document, settings)
            if state is None:
                return False
            card = cards.build(project["name"], item, caps, settings["policy"], settings["notices"], settings["page_url"],
                               operations=operations, delivery=state, sender=sender, cfg=settings)
        seq = self.ledger.next_seq()
        message = dict(card["message"])
        made = {f"{seq}:{a['op']}": a["op"] for a in message["actions"]}
        message["actions"] = [{"id": f"{seq}:{a['op']}", "label": a["label"]} for a in message["actions"]]
        try:
            message_id = self.deliver(chat, message)
        except provider.MessengerError as e:
            if e.kind == "deferred":
                self.defer(project, item, chat)
                return False
            self.log(f"a card could not be sent ({e.kind})")
            if e.kind == "not-configured":
                raise Fatal(e.reason) from None
            return False
        # `whole` is recorded true only for a text that arrived: no file travelled in this message, or the provider confirmed the one that did.
        # A plain str (a provider that never said) is not a confirmation. A card sent while it was not approvable carries its file inline.
        confirmed = not message.get("document") or getattr(message_id, "document_failed", True) is False
        try:
            self.ledger.add({"project": project["id"], "pending_id": item["id"], "kind": item["kind"],
                             "content_sha256": card["content_sha256"], "chat": chat, "message_id": message_id,
                             "actions": made, "sent_at": self.clock(), "whole": bool(card.get("whole")) and confirmed,
                             "approvable": bool(card.get("approvable")), "offers": list(card.get("offers") or []), "blocked": card.get("blocked"),
                             "effect_word": item.get("effect_word")})
        except OSError as e:  # the card went out and the process keeps the record in memory; it is not sent again
            self.log(f"the ledger could not be written ({e.__class__.__name__})")
        return True

    def send_document(self, project: dict, item: dict, chat: str, document: dict, cfg=None):
        """The whole text of a decision as a file, before its card. "sent" when the provider confirmed the document, "failed" when it did not
        (a document that failed after the text, or a send that raised), None when the platform deferred it (nothing is recorded; it is tried
        again). A provider that cannot tell is "failed": the card is then not approvable here."""
        try:
            sent = self.deliver(chat, cards.document_message(project["name"], item, document, cfg))
        except provider.MessengerError as e:
            if e.kind == "deferred":
                self.defer(project, item, chat)
                return None
            self.log(f"the file of a card could not be sent ({e.kind})")
            if e.kind == "not-configured":
                raise Fatal(e.reason) from None
            return "failed"
        if getattr(sent, "document_failed", True) is not False:
            self.log("the file of a card was not delivered: its card has no approval")
            return "failed"
        return "sent"

    def defer(self, project: dict, item: dict, chat: str) -> None:
        """The platform cannot take this card now: keep it (nothing is recorded), remember the chat, and say so once a day."""
        self.deferred_chats.add(chat)
        key = (project["id"], item["id"], chat)
        now = time.monotonic()
        last = self.deferred.get(key)
        if last is None or now - last >= DEFERRED_LOG_EVERY:
            self.deferred[key] = now
            self.log("a card is kept for later: the platform cannot take it yet (deferred)")

    # --- notices ---------------------------------------------------------------------------------------------

    def notify_project(self, project: dict, only_chat=None, cap: int = CARDS_PER_TICK, retry_blocked: bool = False) -> int:
        """Send the cards a project's open decisions lack (to `only_chat`, or to every listed sender). Returns how many
        decisions are left over for the next tick."""
        settings = self.settings(project)
        if not settings or not settings["senders"]:
            return 0
        chats = [c for c in ([only_chat] if only_chat else settings["senders"])
                 if self.ops.operations.permitted("pending", CHANNEL, settings["policy"], None, self.key(c))]
        if not chats:
            if project["id"] not in self.policy_noted:
                self.policy_noted.add(project["id"])
                self.log("notices are off: the project's channel policy does not permit reads")
            return 0
        left = sent = 0
        for listed in self.ops.pending(project["path"])["pending"]:
            item = self.ops.pending(project["path"], pending_id=listed["id"])
            if item.get("status", "open") != "open":
                continue
            digest = cards.content_sha256(item)
            lacking = [c for c in chats if self.wants(project, settings, item, c)
                       and (not self.ledger.sent(project["id"], item["id"], digest, c) or self.outdated(project, settings, item, c, retry_blocked))]
            if not lacking:
                continue
            if sent >= cap:
                left += 1
                continue
            for chat in lacking:
                self.send_card(project, settings, item, chat)
            sent += 1
        return left

    def outdated(self, project: dict, settings: dict, item: dict, chat: str, retry_blocked: bool = False) -> bool:
        """An effect, or a plan that reaches the network, whose card was sent without an approval (the project had not granted it yet, or the notices
        carried no text) gets a new card once the policy lets this card offer one; a card that already offered it, or that still could not, is not
        sent again. A card whose file did not arrive (`blocked` "document") is not sent again either: it said where to approve, and a file that
        failed once would fail on every tick (the simplest rule; a changed content is a new card anyway). The person's own /pending
        (`retry_blocked`) tries such a card again, once per request: the file first, with the same confirmation rules."""
        if not cards.gated(item):
            return False
        last = self.ledger.last_card(project["id"], item["id"], chat)
        if last is None or last.get("approvable") or (last.get("blocked") and not retry_blocked):
            return False
        built = cards.build(project["name"], self.for_reader(project, item, self.key(chat)), self.messenger.capabilities(), settings["policy"], settings["notices"],
                            settings["page_url"], operations=self.ops.operations, sender=self.key(chat), cfg=settings)
        return bool(built["approvable"])

    def tick(self) -> None:
        with self.read_once():
            self._tick()

    def _tick(self) -> None:
        self.recheck()
        for project in self.projects:
            try:
                left = self.notify_project(project)
                settings = self.settings(project)
            except self.ops.OpsError as e:
                self.log(f"a project could not be read for notices ({e.__class__.__name__})")
                continue
            for chat in (self.hears_count(settings, c) for c in (settings["senders"] if settings else [])):
                if chat is None:
                    continue
                key = (project["id"], chat)
                if not left:
                    self.more.pop(key, None)
                elif self.more.get(key) != left and self.reply(chat, phrases.text("MORE_LINE", settings, n=left), project) is not None:
                    self.more[key] = left      # a deferred line is not recorded: it is tried again at the next notice period
        self.remind.deliver()
        self.notify_unread()

    def hearers(self) -> set:
        """The chats that may be told about a skipped message NOW: for every served project, the senders `hears_count` returns under the accepted
        settings read at this moment. A project whose settings cannot be read adds none."""
        heard = set()
        for project in self.projects:
            try:
                settings = self.settings(project)
            except self.ops.OpsError:
                continue
            for chat in (self.hears_count(settings, c) for c in (settings["senders"] if settings else [])):
                if chat is not None:
                    heard.add(chat)
        return heard

    def notify_unread(self) -> None:
        """Tell the senders who hear the count that the provider gave up a message (`UNREAD_ONE`, `UNREAD_MANY`). The hearers are read first, and
        only then is the count taken from the messenger (an error while reading them loses nothing). A skip adds its count to the chats that hear now;
        a chat that no longer hears (removed from the list, narrowed to `actionable`, no longer permitted to read) loses what it was owed, so a line
        held back for the hour is never sent to a sender the policy has since closed. A chat is told at most once in `UNREAD_EVERY`, the count carrying
        the rest; a deferred reply is tried again at the next tick, and a failed one (logged by `reply`) is tried again an hour later, never at every tick.
        Nothing of the provider's reason is used."""
        heard = self.hearers()
        taker = getattr(self.messenger, "take_unread", None)      # as `session` in serve_loop: a messenger object that counts nothing has nothing unread
        found = taker() if taker is not None else 0
        if found > 0:
            for chat in heard:
                self.unread_waiting[chat] = self.unread_waiting.get(chat, 0) + found
        for chat in [c for c in self.unread_waiting if c not in heard]:
            del self.unread_waiting[chat]
        now = time.monotonic()
        for chat, count in list(self.unread_waiting.items()):
            last = self.unread_told.get(chat)
            if last is not None and now - last < UNREAD_EVERY:
                continue
            sent = self.reply(chat, self.t("UNREAD_ONE", chat=chat) if count == 1 else self.t("UNREAD_MANY", chat=chat, n=count))
            if sent is None:
                continue
            self.unread_told[chat] = now
            if sent:
                del self.unread_waiting[chat]

    # --- updates in ------------------------------------------------------------------------------------------

    def handle(self, update: dict) -> None:
        with self.read_once():
            self._handle(update)

    def _handle(self, update: dict) -> None:
        sender, chat = str(update.get("sender")), str(update.get("chat"))
        listed = self.projects_for(sender) if update.get("private") and chat == sender else []
        if not listed:
            self.log(DROPPED)
            self.config_pending(update, sender, chat)
            return
        if update.get("attachments") is not None:
            found = provider.valid_attachments(update["attachments"])
            if found is None:
                self.log("an update with attachments that are not valid was dropped")
                return
            update = dict(update, attachments=found)
        intent = inbound.parse(update)
        project = self.project_of(sender, listed)
        kind = intent["kind"]
        if kind == "ignore":
            return
        if kind == "forwarded":
            self.reply(chat, self.t("FWD_NOT_A_REQUEST", project=project), project)          # a forwarded message is never a request (FWD): one sentence, and nothing of it is read by a draft, a reminder, a write or a card
            return
        replied = update.get("reply_to")
        shown = self.ledger.by_message(chat, replied) if kind == "natural" and replied else None
        if shown and shown.get("kind") != "reminder":          # a reply to a card answers THAT card, not a reminder (NR-1); the question about a reminder is answered by `remind.answer`
            intent = {"kind": "reply", "reply_to": replied, "text": update.get("text") or ""}
            kind = "reply"
        self.remind.discarded.discard(chat)
        if kind != "action" and not intent.get("forwarded"):          # a forwarded file (FWD) answers no open question and drops none: it goes straight to its card
            if chat in self.remind.drafts:
                if self.remind.answer(project, chat, kind, update.get("text") or "", replied):
                    return          # the next line of a chat with a question open about a reminder (NR-1): it answers it, or drops it and goes on as a new line
            elif chat in self.remind.expired and self.remind.late(project, chat, kind, update.get("text") or ""):
                return          # a "yes" to a question that expired is told so (NR-1)
            elif kind in ("text", "natural", "reply") and not (update.get("text") or "").lstrip().startswith("/") and self.write_open(project, chat):
                if self.write_answers(project, chat, update.get("text") or ""):
                    self.write(project, chat, update.get("text") or "")          # a question about a write to the person's accounts is open and this line answers it (NR-5)
                    return
                self.write_forget(project, chat)          # any other line drops it, and is handled as a new one; a question it asks says the previous one was discarded
                self.remind.discarded.add(chat)
        if kind in ("text", "natural", "reply") and self.word_line(update, intent, project, listed, sender, chat):
            pass          # an approve or a reject word decided a decision card, or listed the cards to choose from (S2, limit L64)
        elif kind in ("text", "natural") and (natural.match(intent["text"]) or {}).get("op") == "commands" and not self.greets(project, chat, intent["text"]):      # "help" in words is the typed /help: the fixed list of this app, for every listed sender (it reads nothing of the project), except from a sender who may talk, whose help line is a greeting (S5)
            self.reply(chat, self.t("HELP", project=project), project)
        elif kind in ("text", "natural") and self.attach.line(project, chat, intent.get("text") or ""):
            pass          # "descarta", "adiciona ao projeto": a line about the file just sent (ATT-3)
        elif kind == "attachment":
            self.attach.arrived(project, chat, intent)
        elif kind in ("add", "discard"):
            self.attach.typed(project, chat, kind, intent["id"])
        elif kind == "remind":
            self.remind.created(project, chat, intent)
        elif kind == "natural":
            if intent.get("op") == "write":
                self.write(project, chat, intent["text"])
            elif not self.remind.natural(project, chat, intent):
                self.say(project, chat, intent["text"])
        elif kind == "reminders":
            self.remind.listing(project, chat)
        elif kind == "forget":
            self.remind.forget(project, chat, intent["id"])
        elif kind == "action":
            self.tapped(chat, intent["action"], update.get("action_ref"))
        elif kind == "usage":
            self.reply(chat, self.t(inbound.usage_key(intent["text"]), project=project) if inbound.usage_key(intent["text"]) else intent["text"], project)
        elif kind == "help":
            self.reply(chat, self.t("HELP", project=project), project)
        elif kind == "project":
            self.choose(sender, chat, listed, intent["name"])
        elif kind == "pending":
            self.listing(project, chat)
        elif kind in ("approve", "reject", "release", "answer"):
            replied = None
            if self.messenger.capabilities().get("actions_need_reply"):
                replied = self.replied_card(sender, chat, update.get("reply_to"), intent["id"])
                if replied is None:
                    self.reply(chat, self.t("REPLY_TO_CARD", project=project), project)
                    return
                project = replied[0]
            if kind == "answer":
                self.act(project, chat, "answer", intent["id"], text=intent["text"])
            else:
                self.act(project, chat, kind, intent["id"], card=replied[1] if replied else None, note=intent.get("note"),
                         typed_hash=intent.get("sha256"))
        elif kind == "reply":
            card = self.ledger.by_message(chat, intent["reply_to"])
            if card and card["kind"] == "question":
                target = next((p for p in self.projects if p["id"] == card["project"]), project)
                if not self.listed_in(target, sender):
                    self.log(DROPPED)
                    return
                self.act(target, chat, "answer", card["pending_id"], card=card, text=intent["text"])
            else:
                self.say(project, chat, intent["text"])
        else:
            self.say(project, chat, intent["text"])

    def greets(self, project: dict, chat: str, text: str) -> bool:
        """S5: whether a help line in words ("ajuda", "what can you do") is a greeting that `say` answers with the summary of what this sender may do: the whole line is a greeting or
        a help form (runtime/greeting.py) and the sender holds `talk`. Any other sender keeps the fixed help of this app."""
        if not greeting.is_greeting(text):
            return False
        try:
            self.allow(project, "say", None, chat)
        except (Refused, self.ops.OpsError):
            return False
        return True

    # --- words that decide a card (S2, limit L64) ---------------------------------------------------------------------------

    @staticmethod
    def offers(card: dict) -> set:
        """The acts a ledger record says its card offered, among approve and reject: `approve` when it was `approvable`, and the acts listed in `offers` (a card made since S2) or
        behind a button (`actions`)."""
        acts = set(card.get("offers") or []) | set((card.get("actions") or {}).values())
        if card.get("approvable") is True:
            acts.add("approve")
        return acts & {"approve", "reject"}

    def word_cards(self, listed: list, chat: str) -> list:
        """[(project, record, decision)], oldest first, of the decision cards of this chat that a word could decide: the newest ledger record of each decision that is open now,
        sent whole, offering approve or reject, in a project that lists the sender. A question, a reminder and a file are not decision cards."""
        with self.ledger.lock:
            records = [dict(c) for c in self.ledger.data["cards"] if self.ledger._mine(c) and c.get("chat") == chat]
        newest = {}
        for rec in records:
            if rec.get("kind") in NOT_DECISION or rec.get("pending_id") is None or not rec.get("message_id"):
                continue
            key = (rec["project"], rec["pending_id"])
            newest.pop(key, None)
            newest[key] = rec
        found = []
        for rec in newest.values():
            project = next((p for p in listed if p["id"] == rec["project"]), None)
            if project is None or rec.get("whole") is not True or not self.offers(rec):
                continue
            try:
                item = self.ops.pending(project["path"], pending_id=rec["pending_id"])
            except self.ops.OpsError:
                continue
            if item.get("status", "open") == "open":
                found.append((project, rec, item))
        return found

    def word_line(self, update: dict, intent: dict, project: dict, listed: list, sender: str, chat: str) -> bool:
        """A line that is, whole, only an approve or reject form (card_words): True when it was taken (it decided a card, or sent the list of cards, or said it approves one at a
        time), False when the line is not for the cards and goes on as it always did. Every condition of L64 that this method checks is checked again by `word_act` against the
        ledger and the decision as they are now."""
        said = intent.get("text")
        if self.messenger.capabilities().get("actions_need_reply"):
            said = card_words.reply_line(said)      # S10: an e-mail reply decides with its first line; its signature and the quoted card are not words
        word = card_words.card_word(said)
        if word is None or ("forwarded" in update and update["forwarded"] is not False):
            return False
        if update.get("reply_to"):
            return self.word_reply(listed, chat, word, update["reply_to"])
        if self.messenger.capabilities().get("actions_need_reply"):
            return False      # e-mail: a typed act is a reply to the card (rule 50)
        last = self.last_sent.get(chat)
        if not last:
            return False      # a restart forgets the last message: a word then decides nothing
        found = self.word_cards(listed, chat)
        shown = self.card_lists.get(chat)
        if shown and shown["message_id"] == last and self.monotonic() - shown["at"] < LIST_SECONDS:
            return self.word_on_list(chat, word, found, shown)
        newest = next((c for c in found if str(c[1]["message_id"]) == last), None)
        if newest is None:
            return False      # the last message is not a card a word could decide
        if word["all"] and word["op"] == "approve":
            self.keep_cards(chat, self.t("WORD_ONE_AT_A_TIME", project=newest[0]), newest[0])
        elif len(found) > 1:
            self.send_list(chat, found)
        elif word["n"] is not None:
            return False      # a position chooses from the list only
        else:
            return self.word_act(newest[0], chat, newest[1], word["op"]) or False
        return True

    def word_reply(self, listed: list, chat: str, word: dict, replied) -> bool:
        """A word sent as a reply to a message: it decides THAT card when the message is a decision card of this chat (it need not be the last message: the reply names it)."""
        card = self.ledger.by_message(chat, replied) if isinstance(replied, str) else None
        project = next((p for p in listed if card and p["id"] == card["project"]), None)
        if card is None or project is None or card.get("kind") in NOT_DECISION or card.get("pending_id") is None:
            return False
        if word["all"] and word["op"] == "approve":
            self.keep_cards(chat, self.t("WORD_ONE_AT_A_TIME", project=project), project)
            return True
        if word["all"] or word["n"] is not None:
            return False
        return self.word_act(project, chat, card, word["op"])

    def word_on_list(self, chat: str, word: dict, found: list, shown: dict) -> bool:
        """The line came while the numbered list is the last message: a position decides that card; "all" is rejected for each card of the list and never approved; anything
        else, or a list that is no longer true (a card closed or changed), sends the list again (one card left: that card again)."""
        by_key = {(p["id"], r["pending_id"]): (p, r, i) for p, r, i in found}
        named = [by_key.get((pid, number)) for pid, number, _ in shown["cards"]]
        if any(n is None or n[1]["content_sha256"] != sha for n, (_, _, sha) in zip(named, shown["cards"])):
            if len(found) > 1:
                self.send_list(chat, found)
            elif found:
                self.resend(found[0][0], chat, found[0][1]["pending_id"])
            else:
                return False
            return True
        if word["all"] and word["op"] == "approve":
            self.keep_cards(chat, self.t("WORD_ONE_AT_A_TIME", project=named[0][0]), named[0][0])
        elif word["all"]:
            for project, card, _ in named:
                self.word_act(project, chat, card, "reject")
        elif word["n"] is not None and 1 <= word["n"] <= len(named):
            project, card, _ = named[word["n"] - 1]
            if not self.word_act(project, chat, card, word["op"]):
                self.send_list(chat, found)
        else:
            self.send_list(chat, found)
        return True

    def reply_alone(self, chat: str, text: str, project: dict, restore: bool = False):
        """Say `text` and return the id of the chat's last message after it when this reply was the whole of what was sent to the chat since the last message was read, else None.
        All under `send_lock` and the per-chat send sequence, so that a job thread that delivers at the same moment makes the answer None. With `restore` the last message is put
        back to what it was before the reply (a compare and set, in the same lock hold as the check) and that earlier id is returned."""
        with self.send_lock:
            before, start = self.last_sent.get(chat), self.send_seq.get(chat, 0)
        self.scope.seqs = mine = []
        try:
            said = self.reply(chat, text, project)
        finally:
            self.scope.seqs = None
        with self.send_lock:
            alone = said is True and mine == list(range(start + 1, start + 1 + len(mine))) and self.send_seq.get(chat) == start + len(mine)
            if not alone:
                return None
            if restore and before:
                self.last_sent[chat] = before
            return self.last_sent.get(chat)

    def keep_cards(self, chat: str, text: str, project: dict) -> None:
        """Say `text` about the cards a word was about and leave the last message as it was: the sentence is the answer to that word and shows no other subject, so the card (or
        the list) it was about is still the last thing the person was shown, and the next word may decide it. A compare and set: the last message is put back only when this reply
        was the only thing sent to the chat since it was read; a message another thread sent meanwhile stays the last one."""
        self.reply_alone(chat, text, project, restore=True)

    def send_list(self, chat: str, found: list) -> None:
        """The numbered list of the cards a word could decide (the newest LIST_MAX): the position, the kind and the title as /pending shows them, no id. It is remembered with
        the hash of each card, so that a position decides only the card it named; it is the last message only if nothing else was sent after it."""
        found = found[-LIST_MAX:]
        lines = []
        for number, (project, _, item) in enumerate(found, 1):
            cfg = self.cfg(project)
            lines.append(f"{number}. {phrases.kind_word(item['kind'], cfg)}: {phrases.heading(' '.join(str(item.get('title') or '').split())[:80], cfg)}")
        project = found[-1][0]
        listed = self.reply_alone(chat, self.t("WORD_LIST_HEAD", project=project) + "\n" + "\n".join(lines), project)
        if listed:
            self.card_lists[chat] = {"message_id": listed, "at": self.monotonic(), "cards": [(p["id"], r["pending_id"], r["content_sha256"]) for p, r, _ in found]}

    def word_act(self, project: dict, chat: str, card: dict, op: str) -> bool:
        """Decide `card` with `op` as its button would: the same call (`act`: the policy for the sender, the hash of the card, the operation). False, with nothing said and
        nothing done, when the card was not sent whole to this chat or did not offer the act; a decision no longer open or changed since the card is said so (NOT_OPEN,
        CHANGED and a new card) and nothing is decided."""
        if card.get("chat") != chat or card.get("whole") is not True or op not in self.offers(card):
            return False
        try:
            item = self.ops.pending(project["path"], pending_id=card["pending_id"])
        except self.ops.OpsError:
            return False
        if item.get("status", "open") != "open":
            self.reply(chat, self.t("NOT_OPEN", project=project, number=item["id"], status=phrases.status(item.get("status"), self.cfg(project))), project)
        elif cards.content_sha256(item) != card["content_sha256"]:
            self.reply(chat, self.t("CHANGED", project=project), project)
            self.renew(project, chat, item["id"], card)
        else:
            self.act(project, chat, op, card["pending_id"], card=card)
        return True

    @staticmethod
    def reason_of_hold(held: dict) -> str:
        """Why a task is held, as the dispatcher wrote it: a text of one line cut at 120 characters, nothing else (the reply that carries it also passes the net of `messaging_guard`)."""
        reason = held.get("reason")
        return " ".join(reason.split())[:120] if isinstance(reason, str) else ""

    def command_sentence(self, project: dict, text: str, said: str) -> str:
        """A table command typed on a phone (`/cancel 8`) is answered with a sentence in the project's language, never the operation's result as JSON: `said` is the reply of `say`
        and is returned as it is unless the line is a command of the table and the reply is the JSON of its result. The numbers are the ones the person typed."""
        if not (isinstance(text, str) and text.startswith("/") and isinstance(said, str) and said.lstrip().startswith(("{", "["))):
            return said
        try:
            out, parsed = json.loads(said), self.ops.operations.parse_chat(text)
        except ValueError:
            return said
        if not isinstance(out, (dict, list)) or parsed is None or not isinstance(parsed[1], dict):
            return said
        name, args = parsed
        if not isinstance(out, dict):
            return self.t("CMD_DONE", project=project)
        def number(*keys):      # a whole number, from the result or else from the line the person typed; never a list, a text or anything else of the result
            for source in (out, args):
                for key in keys:
                    value = source.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        return value
            return ""
        listed = lambda key: out[key] if isinstance(out.get(key), list) else []  # noqa: E731
        if name == "cancel":
            return self.t("CMD_CANCEL_ALREADY" if out.get("already") else "CMD_CANCELLED", project=project, n=number("request", "request_id"))
        if name == "stop-task":
            return self.t("CMD_TASK_NOT_RUNNING" if out.get("already") else "CMD_TASK_STOPPED", project=project, n=number("task", "task_id"))
        if name == "retry":
            return self.t("CMD_TASK_RETRY", project=project, n=number("task_id"))
        if name == "status":
            shut = ("done", "failed", "cancelled")
            lines = [self.t("CMD_STATUS", project=project, open=sum(1 for r in listed("requests") if isinstance(r, dict) and r.get("state") not in shut), waiting=len(listed("pending")))]
            lines += [self.t("CMD_STATUS_HELD", project=project, n=h["task_id"], reason=self.reason_of_hold(h)) for h in listed("held")[:3]
                      if isinstance(h, dict) and isinstance(h.get("task_id"), int) and not isinstance(h.get("task_id"), bool)]      # a held task says why, never the command that gets past it
            return "\n".join(lines)
        if name == "attachments":
            return self.t("CMD_ATTACHMENTS", project=project, n=len(listed("held")))
        return self.t("CMD_DONE", project=project)

    def replied_card(self, sender: str, chat: str, reply_to, pending_id: int):
        """(project, card) when `reply_to` names the ledger's card of decision `pending_id` in this chat and the card's project lists the
        sender; else None. Only a platform that declares `actions_need_reply` asks."""
        card = self.ledger.by_message(chat, reply_to) if isinstance(reply_to, str) and reply_to else None
        if card is None or card["pending_id"] != pending_id:
            return None
        target = next((p for p in self.projects if p["id"] == card["project"]), None)
        return (target, card) if target is not None and self.listed_in(target, sender) else None

    def tapped(self, chat: str, action_id: str, action_ref) -> None:
        if action_ref:
            try:
                self.messenger.ack(action_ref)
            except provider.MessengerError as e:
                self.log(f"a button could not be acknowledged ({e.kind})")
        card = self.ledger.by_action(chat, action_id)
        project = next((p for p in self.projects if card and p["id"] == card["project"]), None)
        if card is None or project is None or card.get("chat") != chat:      # a card is acted on only in the chat it was sent to, by that chat's sender
            self.reply(chat, self.t("STALE", project=project, chat=chat), project)
            return
        if not self.listed_in(project, chat):
            self.log(DROPPED)
            return
        if card.get("kind") == "reminder":
            self.remind.tapped(project, chat, card)
            return
        if card.get("kind") == "attachment":
            self.attach.tapped(project, chat, card, card["actions"][action_id])
            return
        self.act(project, chat, card["actions"][action_id], card["pending_id"], card=card)

    def choose(self, sender: str, chat: str, listed: list, name: str) -> None:
        names = ", ".join(p["name"] for p in listed)
        if not name:
            current = self.project_of(sender, listed)
            self.reply(chat, self.t("PROJECT_NOW", project=current, name=current["name"], projects=names), current)
            return
        found = next((p for p in listed if name.lower() in (p["name"].lower(), p["id"])), None)
        if found is None:
            self.reply(chat, self.t("PROJECT_NONE", project=self.project_of(sender, listed), projects=names), self.project_of(sender, listed))
            return
        self.chosen[sender] = found["id"]
        self.reply(chat, self.t("PROJECT_SET", project=found, name=found["name"]), found)

    def listing(self, project: dict, chat: str) -> None:
        try:
            found = self.run_op(project, "pending", sender=chat)["pending"]
        except (Refused, self.ops.OpsError) as e:
            self.oops(chat, e, project)
            return
        files = self.attach.waiting(project, chat)      # this sender's own files that wait for an answer and have a card in this chat (their profile permits `attachments`), else None
        if not found:
            self.reply(chat, self.t("NOTHING_WAITS", project=project, name=project["name"]), project)
            if files:
                self.reply(chat, files, project)
            return
        settings = self.settings(project)
        if settings is not None:      # a profile that is sent only what it can act on is listed only that
            found = [i for i in found if self.wants(project, settings, self.ops.pending(project["path"], pending_id=i["id"]), chat)]
            if not found:
                self.reply(chat, self.t("NOTHING_TO_ACT", cfg=settings, name=project["name"]), project)
                if files:
                    self.reply(chat, files, project)
                return
        lines = [self.pending_line(project, i, settings) for i in found] + [pending_view.footer(found, self.messenger.capabilities(), settings)]
        self.reply(chat, f"{project['name']}: " + "\n".join(line for line in lines if line), project)
        if files:
            self.reply(chat, files, project)
        try:
            self.notify_project(project, only_chat=chat, retry_blocked=True)
        except self.ops.OpsError as e:
            self.log(f"cards could not be sent ({e.__class__.__name__})")

    def pending_line(self, project: dict, listed: dict, settings) -> str:
        """One line of `/pending`: a question is said in plain words (messaging_pending: what it asks, or that the request was not understood), any other decision as its kind and its title."""
        if listed["kind"] == "question" and (settings or {}).get("notices") == "text":      # what is asked is the project's text: a project whose notices carry none of it lists the question as it always did
            try:
                said = pending_view.line(self.ops.pending(project["path"], pending_id=listed["id"]), settings)
            except self.ops.OpsError:
                said = None
            if said:
                return said
        return f"#{listed['id']} {phrases.kind_word(listed['kind'], settings)}: {phrases.heading(listed['title'], settings)}"

    def oops(self, chat: str, error, project: dict) -> None:
        """Say an error of the operations layer to the chat: its precise text on an English phone, the language's sentence on any other (phone_errors)."""
        self.reply(chat, phone_errors.said(str(error), self.cfg(project, chat), failure=True), project, guard=True)

    def act(self, project: dict, chat: str, op: str, pending_id: int, card=None, note=None, text=None, typed_hash=None) -> None:
        """approve, reject, release or answer one decision, bound to the card the person saw."""
        try:
            card = card or self.ledger.last_card(project["id"], pending_id, chat)
            if card is not None and card.get("chat") != chat:      # never another chat's card
                card = None
            if op in ("answer", "reject", "release") and card is None and not (op == "reject" and self.is_question(project, pending_id)):     # a decision is acted on from the card its sender was sent, as an approval is; a question is turned down with no hash and no effect (S14)
                self.reply(chat, self.t("NO_CARD", project=project), project)
                return
            if op == "answer":
                self.run_op(project, "answer", sender=chat, pending_id=pending_id, text=text)
                self.reply(chat, self.t("ANSWERED", project=project, id=pending_id), project)
                return
            item = self.ops.pending(project["path"], pending_id=pending_id)
            if op == "approve":
                self.approve(project, chat, item, card, typed_hash)
            elif op == "reject":
                self.run_op(project, "reject", sender=chat, pending_id=pending_id, **({"note": note} if note else {}))
                self.reply(chat, self.t("QUESTION_DISMISSED" if item["kind"] == "question" else "REJECTED", project=project, id=pending_id), project)
            else:
                self.release(project, chat, pending_id)
        except Refused as e:
            self.reply(chat, str(e), project, guard=True)
        except self.ops.OpsError as e:
            self.oops(chat, e, project)
            if op == "approve":
                self.renew(project, chat, pending_id, card)

    def is_question(self, project: dict, pending_id: int) -> bool:
        """Whether the pending decision is a question, as it is now (S14: a question is turned down without the card it was asked on)."""
        try:
            return self.ops.pending(project["path"], pending_id=pending_id).get("kind") == "question"
        except self.ops.OpsError:
            return False

    def renew(self, project: dict, chat: str, pending_id: int, card) -> None:
        """After a refusal, the decision as it is now, when it changed since the card: a new card."""
        try:
            item = self.ops.pending(project["path"], pending_id=pending_id)
            if item.get("status", "open") == "open" and (card is None or cards.content_sha256(item) != card["content_sha256"]):
                self.send_card(project, self.settings(project), item, chat)
        except self.ops.OpsError:
            pass

    def approve(self, project: dict, chat: str, item: dict, card, typed_hash=None) -> None:
        kind, number = item["kind"], item["id"]
        if kind == "effect":
            self.approve_effect(project, chat, item, card, typed_hash)
            return
        if kind not in ("plan", "acceptance"):
            self.reply(chat, self.t("NOT_APPROVABLE", project=project, number=number, kind=phrases.kind_word(kind, self.cfg(project))), project)
            return
        self.allow(project, "approve", kind, chat)
        if card is None:
            self.reply(chat, self.t("NO_CARD", project=project), project)
            return
        if typed_hash is not None and typed_hash != card["content_sha256"]:
            self.reply(chat, self.t("WRONG_HASH", project=project), project)         # a hash typed with /approve is the card's, for an effect, a plan and an acceptance
            return
        if kind == "plan" and item.get("plan_networked") is True:       # a plan that reaches the network: its destinations must have been shown, whole
            self.allow(project, "approve", "plan:networked", chat)
            if card.get("whole") is not True or self.settings(project)["notices"] != "text":
                self.reply(chat, self.t("TOO_LONG", project=project), project)      # the page shows it whole: no command, no hash (limit L62)
                return
            if card.get("approvable") is not True:       # only a gated card (an effect, a networked plan) must have offered the approval;
                self.reply(chat, self.t("NOT_OFFERED", project=project), project)           # a plain plan or an acceptance is checked against the policy when the person acts
                return
        if kind == "acceptance" and cards.content_sha256(item) != card["content_sha256"]:
            self.reply(chat, self.t("CHANGED", project=project), project)
            self.renew(project, chat, number, card)
            return
        args = {"pending_id": number}
        if kind == "plan":
            args["sha256"] = card["content_sha256"]
        self.run_op(project, "approve", kind=kind, sender=chat, **args)
        self.reply(chat, self.t("APPROVED", project=project, id=number), project)

    def approve_effect(self, project: dict, chat: str, item: dict, card, typed_hash=None) -> None:
        """An effect, from a tap or a typed line. By default (the policy does not grant the word) the reply says to approve it on the page (no command: LIVE-2).
        Granted, every one of these must hold or nothing runs: a card (NO_CARD), a card that carried the whole text and a decision whose
        whole effect fits on a card (TOO_LONG), a typed hash that is the card's, a card whose hash is the decision's own payload hash
        (CHANGED, and a new card), a decision still open. The call is the operations layer's approve with the CARD's hash, in a job thread."""
        number = item["id"]
        word = item.get("effect_word")
        ask = "effect:" + word if isinstance(word, str) and word else "effect"
        settings = self.settings(project)
        if settings is None:
            raise Refused(self.t("NOT_ACCEPTED", project=project))
        say = lambda key, **fields: self.reply(chat, self.t(key, cfg=settings, **fields), project)  # noqa: E731
        if not self.ops.operations.permitted("approve", CHANNEL, settings["policy"], ask, self.key(chat)) or settings["notices"] != "text":
            self.reply(chat, self.t("EFFECT_REPLY", cfg=settings), project)     # not granted, or a card that carries none of the text: it is approved on the page (no command on a phone, limit L62)
            return
        if card is None:
            say("NO_CARD")
            return
        if card.get("whole") is not True or item.get("effect_on_cards") is not True:
            self.reply(chat, self.t("TOO_LONG", cfg=settings), project)
            return
        if typed_hash is not None and typed_hash != card["content_sha256"]:
            say("WRONG_HASH")
            return
        if card.get("approvable") is not True:       # only a card that offered the approval can be approved by a typed line
            say("NOT_OFFERED")
            return
        if item.get("status", "open") != "open":
            say("NOT_OPEN", number=number, status=phrases.status(item.get("status"), settings))
            return
        if card["content_sha256"] != item.get("payload_sha256"):
            say("CHANGED")
            self.renew(project, chat, number, card)
            return
        shown = card["content_sha256"]

        def call():
            try:
                done = self.run_op(project, "approve", kind=ask, sender=chat, pending_id=number, sha256=shown)
                said = outcome.sentence(item, (done or {}).get("result") if isinstance(done, dict) else None, settings)
                self.reply(chat, said or self.t("APPROVED", cfg=settings, id=number), project)      # what was done in plain words, else the plain approval
            except Refused as e:
                self.reply(chat, str(e), project, guard=True)
            except self.ops.OpsError as e:
                self.reply(chat, self.failed(e, item, settings), project)      # what failed and what to check, in plain words (messaging_failure); the full text is the terminal's
                self.renew(project, chat, number, card)
        self.start(project, chat, "approve", call)

    def without_card_line(self, said: str, pending, project) -> str:
        """`said` without the line that tells a card of this decision waits for approval (ACCT_CARD_SENT): the card was just sent to this chat and says it itself. Called only
        when the card went out; where no card was shown the line stays, and so does any other line (a doubt about the date, a rolled day)."""
        if pending is None:
            return said
        card_line = self.t("ACCT_CARD_SENT", project=project, pending=pending)
        return "\n".join(line for line in said.split("\n") if line != card_line).strip("\n")

    def failed(self, error, item: dict, cfg) -> str:
        """The sentence for an approval that did not write: the operations layer's `phone` sentence when it wrote one, else the plain words messaging_failure picks from its
        code and words, with the effect's word. The error's own text (a step name, a hash, a command) stays in the terminal and the page."""
        said = getattr(error, "phone", None)
        return str(said) if said else failure.from_error(error, cfg, word=item.get("effect_word"), account=(item.get("payload") or {}).get("account"))

    def release(self, project: dict, chat: str, pending_id: int) -> None:
        def call():
            try:
                self.run_op(project, "release", sender=chat, pending_id=pending_id)
                self.reply(chat, self.t("RELEASED", project=project, id=pending_id), project)
            except Refused as e:
                self.reply(chat, str(e), project, guard=True)
            except self.ops.OpsError as e:
                self.oops(chat, e, project) if type(e).__name__ != "RunBusy" else self.reply(chat, self.t("RUN_BUSY", project=project), project)
        self.start(project, chat, "release", call)

    def say(self, project: dict, chat: str, text: str) -> None:
        """A free line to the planning agent. A line that may wait (`queueable`) and meets a project that is busy is kept (`keep`) and answered `QUEUED`;
        a line that comes while others wait goes behind them (also one that is being started), so that the lines start in the order they came."""
        if not queueable(text):
            self.start(project, chat, "say", self.line(project, chat, text, None))
            return
        with self.queue_lock:
            mine = [e for e in self.waiting if e["project"]["id"] == project["id"]]
        held = False
        if not mine:
            try:
                self.start_job(project["id"], "say", self.inherit(self.line(project, chat, text, None)))
                return
            except shell_kit.Busy:
                held = True
            except shell_kit.Stopping:
                return
        # beyond the caps the line gets the sentence it always got: the router's when the lines only wait out a `RunBusy` pause, else the slot's
        now = self.monotonic()
        busy_elsewhere = bool(mine) and not held and all(e["after"] > now for e in mine)
        self.keep_or_refuse(project, chat, text, "RUN_BUSY" if busy_elsewhere else "STILL_WORKING")
        self.drain()      # the job that held the slot may have ended between the refusal and the keeping

    def write_open(self, project: dict, chat: str) -> bool:
        """Whether this chat has a live question about a write to the person's accounts (memory only, the one store of drafts)."""
        found = getattr(self.ops, "natural_draft", None)          # an operations object without it (a test's) has no question open
        if found is None:
            return False
        try:
            return bool(found(project["path"], self.key(chat)))
        except self.ops.OpsError:
            return False

    def write_answers(self, project: dict, chat: str, text: str) -> bool:
        """Whether a plain line answers the chat's open question about a write (the operations layer decides: `natural_needs` names the draft's operation then)."""
        try:
            return self.ops.natural_needs(project["path"], text, sender=self.key(chat), channel=CHANNEL) is not None
        except self.ops.OpsError:
            return False

    def write_forget(self, project: dict, chat: str) -> None:
        found = getattr(self.ops, "natural_forget", None)
        if found is not None:
            found(project["path"], self.key(chat))

    def write(self, project: dict, chat: str, text: str, seed=None) -> None:
        """A line that asks for a write to the person's own accounts, or the answer to a question about one (package NR-5): handled by code in a job of its own, with no model,
        no route lock and no place in the router's queue, and not stored in the conversation. The card of the exact content is what it opens."""
        self.start(project, chat, "event-create", lambda: self.write_now(project, chat, text, seed))          # the job is labelled with a row that calls no model, so it takes no model slot

    def write_now(self, project: dict, chat: str, text: str, seed=None) -> bool:
        """The body of `write`, for a caller that is already in a job (the caption of a file that was just held, a button of its card). True when the card of the write
        was sent to the chat."""
        needed = None
        try:
            needed = seed["op"] if seed else self.needs(text, project, chat)
            if needed:
                self.allow(project, needed, sender=chat)          # the operation's own group, never `talk`: the layer asks it again
            result = self.ops.natural_write(project["path"], text, channel=CHANNEL, sender=self.key(chat), seed=seed)
        except Refused as e:
            self.reply(chat, self.t("ATT_SAVE_OFF", project=project) if needed == "file-save" else str(e), project, guard=True)          # a plain sentence for a save, never the name of an operation
            return False
        except self.ops.OpsError as e:
            self.reply(chat, f"error: {e}", project, guard=True)
            return False
        if result.get("silent"):          # the line opens nothing and says nothing (a caption never asks a question): the caller sends the file's card
            return False
        said = result.get("reply")
        if said is None:          # no write and no answer: a plain line, as it always was
            self.line(project, chat, text, None)()
            return False
        opened = result.get("resend") is not None
        if opened and not self.resend(project, chat, result["resend"]):
            said, opened = self.t("NW_CARD_NOT_SENT", project=project, pending=result["resend"]), False
        if result.get("asked") and chat in self.remind.discarded:
            self.remind.discarded.discard(chat)
            said = self.t("NT_DISCARDED", project=project) + " " + said
        said = self.without_card_line(said, result.get("resend"), project)      # the card went out and says it waits: the line that says so again is not sent
        if said.strip():
            if opened:
                self.keep_cards(chat, said, project)      # a doubt or a rolled day said with the card, in the same turn, is about that card: the card stays the last message (S2)
            else:
                self.reply(chat, said, project)
        if result.get("cards"):          # the files to choose among, or the file whose card says where to save it: their cards (ATT-3)
            self.attach.resend(project, chat, result["cards"])
        return result["resend"] if opened else None

    def line(self, project: dict, chat: str, text: str, entry):
        """The call that runs one line through `say`. `entry` is the kept line this run answers (None: the line has just come); it leaves the waiting
        list when the run begins. The policy is read by `run_op` now; a kept line also needs the project to be accepted and its sender still listed in
        it, else it is dropped with no reply, as an update from an unlisted sender is."""
        def call():
            if entry is not None:
                self.leave(entry)
            try:
                if entry is not None:
                    try:
                        settings = self.settings(project)
                    except self.ops.OpsError:
                        settings = None
                    if settings is None or chat not in settings["senders"]:
                        self.log(DROPPED)
                        return
                shown = None
                try:
                    try:
                        shown = indicator.Typing(self.messenger).begin(chat, text)      # S10: "typing..." while the reply is prepared, on a platform that has it
                    except Exception:      # never a lost reply
                        shown = None
                    result = self.run_op(project, "say", sender=chat, allow_as=self.needs(text, project, chat), text=text)
                finally:
                    if shown is not None:
                        shown.stop()      # before anything is sent: no call is made after this
                raw = result.get("reply") or self.t("NO_REPLY", project=project)
                said = self.command_sentence(project, text, raw)
                converted = said is not raw      # a sentence made from a command's result carries a text of the operations layer (a held task's reason): it passes the net of `messaging_guard`
                if result.get("resend") is not None and not self.resend(project, chat, result["resend"]):      # a decision named in words (NR-2): its card goes out again
                    said = self.t("NAT_DECISION_NO_CARD", project=project)      # and the sentence says so only when a card is there
                else:
                    said = self.without_card_line(said, result.get("resend"), project) or ("" if result.get("resend") is not None else said)
                if not said:
                    return
                self.scope.replied = None
                if self.reply(chat, said, project, guard=converted) is True and result.get("pending_id") is not None:
                    self.note_asked(project, chat, result["pending_id"], getattr(self.scope, "replied", None))      # the router's question reached this chat as the reply: its notice would be the same question twice
            except Refused as e:
                self.reply(chat, str(e), project, guard=True)
            except self.ops.OpsError as e:
                if type(e).__name__ != "RunBusy":
                    self.reply(chat, f"error: {e}", project, guard=True)
                elif entry is not None:       # a kept line met the busy router again: it waits on, with its place and its time
                    if not self.keep(project, chat, text, entry=entry, retry=True):
                        self.reply(chat, self.t("QUEUE_STOPPED", project=project), project)       # the bridge is stopping
                elif not queueable(text) or not self.keep(project, chat, text, retry=True):
                    self.reply(chat, self.t("RUN_BUSY", project=project), project)
                else:
                    self.reply(chat, self.t("QUEUED", project=project), project)
        return call

    def note_asked(self, project: dict, chat: str, pending_id: int, message_id=None) -> None:
        """The reply to a line was the router's question and it went out in `chat`: the ledger records that this decision, with this content, is in this chat
        already, so that the notice does not send the same question a second time (decision id, project and chat; another listed sender still gets it). The
        record is a card of kind `question` with `message_id`, the id of the last piece THIS reply sent (read by `reply` on the calling thread, never from the shared `last_message`; S4: decision 229 (1), "afterwards by reply-to") and no action: a reply
        to that message answers the question at any age, a tap cannot, and `/answer` from this chat finds the sender's own question. Anything else the reply said (a plan, an unrecognised route) keeps its card."""
        try:
            item = self.ops.pending(project["path"], pending_id=pending_id)
            if item.get("status", "open") != "open" or not cards.router_asks(item):
                return
            self.ledger.add({"project": project["id"], "pending_id": item["id"], "kind": "question", "content_sha256": cards.content_sha256(item),
                             "chat": chat, "message_id": message_id, "actions": {}, "sent_at": self.clock(), "whole": True, "approvable": False,
                             "blocked": None, "effect_word": None})
        except (self.ops.OpsError, OSError) as e:
            self.log(f"the question's reply could not be recorded ({e.__class__.__name__})")

    def leave(self, entry: dict) -> None:
        """A kept line whose run has begun is no longer waiting (until then it stays in the list, marked `starting`, so that a line that comes meanwhile
        goes behind it)."""
        with self.queue_lock:
            self.waiting = [e for e in self.waiting if e is not entry]
            entry["starting"] = False

    def needs(self, text: str, project=None, chat=None):
        """The operation whose group a line needs when it is not `say`'s own: a typed `/ask <question>` is a `say`, and needs the group `ask`, not
        `talk` (a profile may ask and not talk, or talk and not ask). A plain line (NR-2) that code takes with no model (a form of a read or a notice, a
        decision named in words, the answer to the sender's own draft) needs the group of that operation, never one whose row does not list this channel; the
        layer asks `talk` again for a line no form takes, so a sender without it never reaches the router. None for every other line. The one place that
        chooses: `keep_or_refuse` asks the policy for it when the line comes and `line` when it runs."""
        named = self.ops.operations.parse_chat(text)
        if named is not None:
            return "ask" if named[0] == "ask" else None
        if greeting.is_greeting(text):
            return None      # S5: a greeting, or a help line in words, is answered by `say` with the summary: it needs `talk`, whatever read the fixed help would have needed
        if project is not None and chat is not None and hasattr(self.ops, "natural_needs"):
            try:
                return self.ops.natural_needs(project["path"], text, sender=self.key(chat), channel=CHANNEL)
            except self.ops.OpsError:
                return None
        found = natural.needs(text)
        return found if found is not None and CHANNEL in self.ops.operations.by_name(found)["channels"] else None

    def resend(self, project: dict, chat: str, pending_id: int) -> bool:
        """Send the card of an open decision again to the chat that named it in words (NR-2): the same card, under the same rules, so the decision is
        made from it. True when the card is there for the sender: sent now, or sent less than RESEND_EVERY seconds ago (a line repeated is not a flood).
        False for a decision that is not open, or that the sender is not sent a card for."""
        key = (project["id"], chat, pending_id)
        now = self.monotonic()
        last = self.resent.get(key)
        if last is not None and now - last < RESEND_EVERY:
            return True
        try:
            item = self.ops.pending(project["path"], pending_id=pending_id)
            settings = self.settings(project)
            if settings is None or item.get("status", "open") != "open" or not self.wants(project, settings, item, chat):
                return False
            sent = self.send_card(project, settings, item, chat)
        except self.ops.OpsError as e:
            self.log(f"a card could not be sent again ({e.__class__.__name__})")
            return False
        if sent:
            self.resent[key] = now
        return bool(sent)

    def keep_or_refuse(self, project: dict, chat: str, text: str, refusal: str) -> None:
        """Keep the line and say so, or say `refusal` (the phrase table's key of the sentence the line always got when the project was busy: `RUN_BUSY` or
        `STILL_WORKING`). A sender whose policy refuses the line is told so now, and nothing is kept for it."""
        try:
            self.allow(project, self.needs(text, project, chat) or "say", sender=chat)
        except Refused as e:
            self.reply(chat, str(e), project, guard=True)
            return
        except self.ops.OpsError:
            self.reply(chat, self.t(refusal, project=project), project)
            return
        self.reply(chat, self.t("QUEUED" if self.keep(project, chat, text) else refusal, project=project), project)

    def keep(self, project: dict, chat: str, text: str, entry=None, retry: bool = False) -> bool:
        """Keep a line in memory for the project. A new line (no `entry`) is kept when the bridge is not stopping, the chat has none waiting and the
        project has fewer than QUEUE_PER_PROJECT; `entry` puts a line that was started and met a busy router back where it was. `retry` makes it wait
        QUEUE_RETRY seconds before it is started again. True when the line is kept. Nothing about the line is logged beyond a count."""
        with self.queue_lock:
            if self.stopping.is_set():
                return False
            if entry is None:
                if sum(1 for e in self.waiting if e["chat"] == chat) >= QUEUE_PER_CHAT \
                        or sum(1 for e in self.waiting if e["project"]["id"] == project["id"]) >= QUEUE_PER_PROJECT:
                    return False
                self.ticket += 1
                entry = {"n": self.ticket, "project": project, "chat": chat, "text": text, "since": self.monotonic(), "after": 0.0, "starting": False}
            if retry:
                entry["after"] = self.monotonic() + QUEUE_RETRY
            self.waiting.append(entry)
            self.waiting.sort(key=lambda e: e["n"])
        return True

    def drain(self) -> None:
        with self.read_once():
            self._drain()

    def _drain(self) -> None:
        """Drop the lines that waited QUEUE_WAIT seconds (each chat is told) and start the oldest line of every project whose slot is free (a listen
        provider whose session is not ready starts none). Called at each iteration of the loops and at the end of each job. One drain at a time: the lines
        of a project start in the order they were kept. A line being started stays in the list, marked, until its run begins."""
        if not self.waiting:
            return
        told, expired = [], []
        try:
            with self.drain_lock:
                now = self.monotonic()
                with self.queue_lock:
                    expired = [e for e in self.waiting if not e["starting"] and now - e["since"] >= QUEUE_WAIT]
                    self.waiting = [e for e in self.waiting if not any(e is x for x in expired)]
                told += [(e["chat"], "QUEUE_EXPIRED", e["project"]) for e in expired]
                ready = self.session_ready is None or self.session_ready()
                seen = []
                while ready:
                    with self.queue_lock:
                        oldest = next((e for e in self.waiting if e["project"]["id"] not in seen), None)
                        if oldest is None:
                            break
                        seen.append(oldest["project"]["id"])
                        if oldest["starting"] or oldest["after"] > now:     # being started, or it met a busy router a moment ago: the lines behind it wait too
                            continue
                        oldest["starting"] = True
                    try:
                        self.start_job(oldest["project"]["id"], "say", self.inherit(self.line(oldest["project"], oldest["chat"], oldest["text"], oldest)))
                    except shell_kit.Stopping:
                        self.leave(oldest)
                        told.append((oldest["chat"], "QUEUE_STOPPED", oldest["project"]))
                    except BaseException as e:      # Busy (the slot is taken), a thread that cannot start, or the shell's Stop: the line is not being started
                        with self.queue_lock:
                            oldest["starting"] = False      # it stays, in its place: later drains, its expiry and the stop's message reach it
                        if not isinstance(e, shell_kit.Busy):
                            raise
        finally:
            if expired:
                self.log(f"{len(expired)} waiting line(s) dropped after {QUEUE_WAIT // 60} minutes")
            for chat, key, project in told:
                self.reply(chat, self.t(key, project=project), project)

    def drain_safely(self) -> None:
        try:
            self.drain()
        except Exception:  # the loop goes on; the class says what failed, never the content
            self.log("the waiting lines could not be looked at: " + traceback.format_exc().strip().splitlines()[-1].split(":")[0])

    def job_ended(self, job: dict) -> None:
        """The kit calls this when a job ended and its slot is free: the oldest waiting line of the project is started."""
        self.drain_safely()

    def tell_stopped(self, chat: str, project=None) -> None:
        try:
            self.reply(chat, self.t("QUEUE_STOPPED", project=project, chat=chat), project)
        except Exception:  # best effort: the stop goes on, and the class says what failed, never the content
            self.log("a waiting line's chat could not be told of the stop: " + traceback.format_exc().strip().splitlines()[-1].split(":")[0])

    def close_queue(self) -> None:
        """At a stop (the end of `serve_loop`, before the runs end and the provider closes): every chat that has a line waiting is told QUEUE_STOPPED
        (best effort) and the lines are forgotten. The messages go out together and the stop waits QUEUE_STOP_WAIT seconds for all of them, so that a
        provider that does not answer cannot hold back the end of the runs. A line already being started runs: its job began before the stop."""
        with self.queue_lock:
            left = [e for e in self.waiting if not e["starting"]]
            self.waiting = [e for e in self.waiting if e["starting"]]
        senders = [threading.Thread(target=self.tell_stopped, args=(e["chat"], e["project"]), daemon=True) for e in left]
        for thread in senders:
            thread.start()
        end = time.monotonic() + QUEUE_STOP_WAIT
        for thread in senders:
            thread.join(max(0.0, end - time.monotonic()))
        late = sum(1 for thread in senders if thread.is_alive())
        if left:
            self.log(f"stopped with {len(left)} waiting line(s): their chats were told" + (f" ({late} message(s) not out in {QUEUE_STOP_WAIT:g} s)" if late else ""))

    def start(self, project: dict, chat: str, op: str, call) -> None:
        """A call that may take minutes runs in a thread; a model call takes the project's slot, one at a time."""
        try:
            self.start_job(project["id"], op, self.inherit(call))
        except shell_kit.Busy:
            self.reply(chat, self.t("STILL_WORKING", project=project), project)
        except shell_kit.Stopping:
            return

    # --- the loop --------------------------------------------------------------------------------------------

    def handle_safely(self, update: dict) -> None:
        try:
            self.handle(update)
        except Fatal:
            raise
        except Exception:  # one update never ends the bridge; the class says what failed, never the content
            self.log("an update failed: " + traceback.format_exc().strip().splitlines()[-1].split(":")[0])

    def poll_once(self, timeout: int) -> int:
        """One receive and the handling of what it returned. Returns the number of updates handled."""
        found = self.messenger.receive(self.ledger.offset, timeout)
        for update in found["updates"]:
            self.handle_safely(update)
        try:
            self.ledger.set_offset(found["next_offset"])
        except OSError as e:
            self.log(f"the ledger could not be written ({e.__class__.__name__})")
        return len(found["updates"])

    def listen_loop(self, stop: threading.Event, notice_every: float, session, poll: int = POLL_SECONDS) -> None:
        """The loop for a provider that listens: updates arrive from the session, never by receive, and the ledger's offset
        is not touched. Notices wait until the provider is ready (a card is never sent to one that is not) and are looked
        at again at once when it becomes ready, so a card that failed to go out is sent after a restart."""
        due, seen = 0.0, 0
        self.session_ready = session.is_ready      # no waiting line starts while the provider is not ready
        while not stop.is_set():
            if session.fatal:
                raise Fatal(session.fatal)
            if session.generation != seen:
                seen, due = session.generation, 0.0
            now = time.monotonic()
            if now >= due and session.is_ready():
                try:
                    self.tick()
                except provider.MessengerError as e:
                    self.log(f"a notice could not be sent ({e.kind})")
                due = time.monotonic() + notice_every
            wait = min(poll, 1.0, max(0.0, due - time.monotonic())) if session.is_ready() else min(poll, 1.0)
            self.drain_safely()
            update = session.next_update(max(wait, 0.05))
            if update is not None:
                self.handle_safely(update)
                if update.get("chat") in self.deferred_chats:   # the person wrote: a kept card can go out now
                    self.deferred_chats.discard(update.get("chat"))
                    due = 0.0

    def serve_loop(self, stop: threading.Event, notice_every: float, poll: int = POLL_SECONDS) -> None:
        """The loop until `stop` is set (or a signal raises the shell's Stop, or the provider is not configured). However it ends, the bridge is stopping
        from then on: no waiting line starts, and each chat with one is told (`close_queue`) while the provider is still open."""
        try:
            self.loop(stop, notice_every, poll)
        finally:
            self.stopping.set()
            self.close_queue()

    def loop(self, stop: threading.Event, notice_every: float, poll: int = POLL_SECONDS) -> None:
        session = getattr(self.messenger, "session", None)
        if session is not None:
            return self.listen_loop(stop, notice_every, session, poll)
        due = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now >= due:
                try:
                    self.tick()
                except provider.MessengerError as e:
                    self.log(f"a notice could not be sent ({e.kind})")
                due = time.monotonic() + notice_every
            wait = max(1, min(poll, int(due - time.monotonic())))
            self.drain_safely()
            if any(e["after"] > self.monotonic() for e in list(self.waiting)):      # a line waits out a `RunBusy` pause: look again soon (a held slot is looked at when its job ends)
                wait = min(wait, QUEUE_POLL)
            try:
                self.poll_once(wait)
            except provider.MessengerError as e:
                if e.kind == "not-configured":
                    raise Fatal(e.reason) from None
                self.log(f"the messenger did not answer ({e.kind}); trying again")
                stop.wait(RETRY_SECONDS)
