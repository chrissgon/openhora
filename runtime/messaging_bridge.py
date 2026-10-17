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
card's hash. Otherwise the reply is the command to run in the terminal (decision D8, the default). The approval runs in a job thread:
an effect may take minutes.

Who acted (POL-2). The update's sender is the one the PROVIDER authenticated (Telegram's user id, a snowflake, the signed phone digits), and a card is
sent to a private chat whose id is that sender's: the bridge makes the sender's key (`<platform>:<id>`, operations.sender_key) and asks the policy for
THAT sender, so each listed sender has the profile `runtime.json` gives them (`messaging.senders`), else the channel's. Nothing a sender sends can name
a profile or change one: a profile changes only by accept-config in the terminal. Every check reads the accepted configuration when the sender ACTS
(`settings` at each call), never when the card was sent, so a sender removed or narrowed since loses the act at once; a card is acted on only in the
chat it was sent to (the ledger's `chat` must be the acting sender's); the operations layer is told the sender and records it with the decision
(ops_actor); and a profile with `notices: actionable` is sent a card only for a decision it can act on or answer.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import inspect
import os
import re
import threading
import time
import traceback

import messaging_cards as cards
import messaging_inbound as inbound
import messaging_provider as provider
import shell_kit

CHANNEL = "messaging"
CARDS_PER_TICK = 10
POLL_SECONDS = 25
DEFERRED_LOG_EVERY = 86400.0   # seconds between two log lines about one deferred card
RETRY_SECONDS = 5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROPPED = "dropped an update from an unlisted sender"
STALE = "This button is no longer valid. Send /pending."
NO_CARD = "Act on the card sent to you (send /pending)."
CHANGED = "This decision changed since you saw it."
STILL_WORKING = "Still working on the last message."
RUN_BUSY = "The planning agent is answering another request. Send it again in a moment."
NOT_ACCEPTED = "This project's configuration is not accepted: run accept-config in the terminal."
NOT_ACCEPTED_WHY = "its configuration is not accepted (run accept-config in the terminal)"
NO_SENDER_WHY = "runtime.json messaging.senders.{platform} lists no sender"
UNREADABLE_WHY = "its configuration cannot be read"
EFFECT_REPLY = "An effect is approved on the page or in the terminal, with its hash:"
TOO_LONG = "Too long to approve here: approve it on the page or in the terminal, with its hash:"
WRONG_HASH = "The hash you typed is not the one of the card you saw. Send /pending."
NOT_OPEN = "Pending decision {number} is {status}, not open."
NOT_OFFERED = "That card did not offer an approval. Send /pending for the current one."


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
    document = out.get("document")
    if isinstance(document, dict):
        out["document"] = {**document, "name": scrub(document.get("name")), "text": scrub(document.get("text"))}
    return out


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
    def __init__(self, ops_module, projects, messenger, ledger, platform: str, log=None, clock=None):
        super().__init__(ops_module, projects, log)
        self.messenger, self.ledger, self.platform = messenger, ledger, platform
        self.clock = clock or shell_kit.now
        self.chosen = {}       # sender -> project id
        self.more = {}         # (project id, chat) -> the number last announced as waiting to that chat (set once the line went out)
        self.policy_noted = set()
        self.everyone = list(self.projects)   # every project given; `self.projects` is the part that is ready to serve
        self.skipped = {}                     # project id -> why it is skipped now (absent: served)
        self.deferred = {}                    # (project id, pending id, chat) -> when it was last logged as deferred
        self.deferred_chats = set()           # chats with a card kept for later: an update from one asks for a notice at once

    # --- the projects and their settings ---------------------------------------------------------------------

    def settings(self, project: dict):
        """The accepted settings of a project for this platform, or None when its configuration is not accepted."""
        found = self.ops.config(project["path"])
        if not found.get("accepted"):
            return None
        messaging = found.get("messaging") or {}
        return {"senders": list((messaging.get("senders") or {}).get(self.platform) or []),
                "notices": messaging.get("notices") or "text", "page_url": messaging.get("page_url"),
                "policy": found.get("channels") or {}, "profiles": found.get("policies") or {},
                "sender_profiles": (messaging.get("sender_profiles") or {}).get(self.platform) or {},
                "channel_profile": (found.get("channel_profiles") or {}).get(CHANNEL)}

    def key(self, sender: str) -> str:
        """The key of a sender in the policy: `<platform>:<id>` (operations.sender_key)."""
        return self.ops.operations.sender_key(self.platform, sender)

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
        built = cards.build(project["name"], item, self.messenger.capabilities(), settings["policy"], settings["notices"], settings["page_url"],
                            operations=operations, sender=key)
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

    def deliver(self, chat: str, message: dict):
        """The one point where the bridge sends anything: every reply, card and file passes the filter that keeps the home folder off a phone."""
        return self.messenger.send(chat, scrub_message(message))

    def reply(self, chat: str, text: str):
        """Send a reply. True when every piece went out, False when a send failed (logged), None when the platform deferred it
        (it cannot take a message yet: not an error, not logged, and the caller may try again)."""
        caps = self.messenger.capabilities()
        for piece in cards.split(text or "(no reply)", caps["max_text"]):
            try:
                self.deliver(chat, {"text": piece, "actions": [], "link": None, "document": None})
            except provider.MessengerError as e:
                if e.kind == "deferred":
                    return None
                self.log(f"a reply could not be sent ({e.kind})")
                return False
        return True

    def allow(self, project: dict, op: str, kind=None, sender=None) -> dict:
        """The project's accepted settings when the policy permits the operation (for this kind of decision) to THIS sender (their profile, read now),
        else Refused with the sentence the operations layer uses too."""
        if sender is None:
            raise RuntimeError("the bridge asks the policy for a sender, never for the channel alone")
        settings = self.settings(project)
        if settings is None:
            raise Refused(NOT_ACCEPTED)
        operations = self.ops.operations
        if not operations.permitted(op, CHANNEL, settings["policy"], kind, self.key(sender)):
            raise Refused(operations.not_enabled(op, CHANNEL))
        return settings

    def run_op(self, project: dict, op: str, kind=None, sender=None, **args):
        """The one call path: the policy first (for the sender's profile), then the operation, as the channel `messaging` and, when it takes one,
        as that sender (the layer asks the policy again for them and records who acted)."""
        self.allow(project, op, kind, sender)         # raises when no sender is named
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
        command = None
        if item["kind"] == "effect":
            command = operations.command_line("approve", project["path"], checkout=ROOT, pending_id=item["id"],
                                              sha256=item.get("payload_sha256"))
        caps = self.messenger.capabilities()
        sender = self.key(chat)
        card = cards.build(project["name"], item, caps, settings["policy"], settings["notices"],
                           settings["page_url"], operations=operations, effect_command=command, sender=sender)
        document = card["message"]["document"]
        if document and card["gated"] and card["approvable"]:
            # An approval needs the whole text DELIVERED: the file goes first, as a message of its own, and the card with the buttons only after
            # the provider confirmed it. A file that failed (or a send that could not be told) makes a card with no approval that says so.
            state = self.send_document(project, item, chat, document)
            if state is None:
                return False
            card = cards.build(project["name"], item, caps, settings["policy"], settings["notices"], settings["page_url"],
                               operations=operations, effect_command=command, delivery=state, sender=sender)
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
                             "approvable": bool(card.get("approvable")), "blocked": card.get("blocked"),
                             "effect_word": item.get("effect_word")})
        except OSError as e:  # the card went out and the process keeps the record in memory; it is not sent again
            self.log(f"the ledger could not be written ({e.__class__.__name__})")
        return True

    def send_document(self, project: dict, item: dict, chat: str, document: dict):
        """The whole text of a decision as a file, before its card. "sent" when the provider confirmed the document, "failed" when it did not
        (a document that failed after the text, or a send that raised), None when the platform deferred it (nothing is recorded; it is tried
        again). A provider that cannot tell is "failed": the card is then not approvable here."""
        try:
            sent = self.deliver(chat, cards.document_message(project["name"], item, document))
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
        built = cards.build(project["name"], item, self.messenger.capabilities(), settings["policy"], settings["notices"],
                            settings["page_url"], operations=self.ops.operations, sender=self.key(chat))
        return bool(built["approvable"])

    def tick(self) -> None:
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
                elif self.more.get(key) != left and self.reply(chat, cards.MORE_LINE.format(n=left)) is not None:
                    self.more[key] = left      # a deferred line is not recorded: it is tried again at the next notice period

    # --- updates in ------------------------------------------------------------------------------------------

    def handle(self, update: dict) -> None:
        sender, chat = str(update.get("sender")), str(update.get("chat"))
        listed = self.projects_for(sender) if update.get("private") and chat == sender else []
        if not listed:
            self.log(DROPPED)
            return
        intent = inbound.parse(update)
        project = self.project_of(sender, listed)
        kind = intent["kind"]
        if kind == "ignore":
            return
        if kind == "action":
            self.tapped(chat, intent["action"], update.get("action_ref"))
        elif kind == "usage":
            self.reply(chat, intent["text"])
        elif kind == "help":
            self.reply(chat, inbound.HELP)
        elif kind == "project":
            self.choose(sender, chat, listed, intent["name"])
        elif kind == "pending":
            self.listing(project, chat)
        elif kind in ("approve", "reject", "release"):
            self.act(project, chat, kind, intent["id"], note=intent.get("note"), typed_hash=intent.get("sha256"))
        elif kind == "answer":
            self.act(project, chat, "answer", intent["id"], text=intent["text"])
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

    def tapped(self, chat: str, action_id: str, action_ref) -> None:
        if action_ref:
            try:
                self.messenger.ack(action_ref)
            except provider.MessengerError as e:
                self.log(f"a button could not be acknowledged ({e.kind})")
        card = self.ledger.by_action(chat, action_id)
        project = next((p for p in self.projects if card and p["id"] == card["project"]), None)
        if card is None or project is None or card.get("chat") != chat:      # a card is acted on only in the chat it was sent to, by that chat's sender
            self.reply(chat, STALE)
            return
        if not self.listed_in(project, chat):
            self.log(DROPPED)
            return
        self.act(project, chat, card["actions"][action_id], card["pending_id"], card=card)

    def choose(self, sender: str, chat: str, listed: list, name: str) -> None:
        if not name:
            current = self.project_of(sender, listed)
            self.reply(chat, "Your lines go to " + current["name"] + ". Projects: " + ", ".join(p["name"] for p in listed) + ".")
            return
        found = next((p for p in listed if name.lower() in (p["name"].lower(), p["id"])), None)
        if found is None:
            self.reply(chat, "No such project. Projects: " + ", ".join(p["name"] for p in listed) + ".")
            return
        self.chosen[sender] = found["id"]
        self.reply(chat, "Your lines now go to " + found["name"] + ".")

    def listing(self, project: dict, chat: str) -> None:
        try:
            found = self.run_op(project, "pending", sender=chat)["pending"]
        except (Refused, self.ops.OpsError) as e:
            self.reply(chat, str(e))
            return
        if not found:
            self.reply(chat, f"{project['name']}: nothing waits for you.")
            return
        settings = self.settings(project)
        if settings is not None:      # a profile that is sent only what it can act on is listed only that
            found = [i for i in found if self.wants(project, settings, self.ops.pending(project["path"], pending_id=i["id"]), chat)]
            if not found:
                self.reply(chat, f"{project['name']}: nothing waits for you to act on.")
                return
        self.reply(chat, f"{project['name']}: " + "\n".join(f"#{i['id']} {i['kind']}: {i['title']}" for i in found))
        try:
            self.notify_project(project, only_chat=chat, retry_blocked=True)
        except self.ops.OpsError as e:
            self.log(f"cards could not be sent ({e.__class__.__name__})")

    def act(self, project: dict, chat: str, op: str, pending_id: int, card=None, note=None, text=None, typed_hash=None) -> None:
        """approve, reject, release or answer one decision, bound to the card the person saw."""
        try:
            card = card or self.ledger.last_card(project["id"], pending_id, chat)
            if card is not None and card.get("chat") != chat:      # never another chat's card
                card = None
            if op in ("answer", "reject", "release") and card is None:     # a decision is acted on from the card its sender was sent, as an approval is
                self.reply(chat, NO_CARD)
                return
            if op == "answer":
                self.run_op(project, "answer", sender=chat, pending_id=pending_id, text=text)
                self.reply(chat, f"Answered #{pending_id}.")
                return
            item = self.ops.pending(project["path"], pending_id=pending_id)
            if op == "approve":
                self.approve(project, chat, item, card, typed_hash)
            elif op == "reject":
                self.run_op(project, "reject", sender=chat, pending_id=pending_id, **({"note": note} if note else {}))
                self.reply(chat, f"Rejected #{pending_id}.")
            else:
                self.release(project, chat, pending_id)
        except Refused as e:
            self.reply(chat, str(e))
        except self.ops.OpsError as e:
            self.reply(chat, str(e))
            if op == "approve":
                self.renew(project, chat, pending_id, card)

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
            self.reply(chat, f"Pending decision {number} is a {kind}: approve takes a plan or an acceptance.")
            return
        self.allow(project, "approve", kind, chat)
        if card is None:
            self.reply(chat, NO_CARD)
            return
        if typed_hash is not None and typed_hash != card["content_sha256"]:
            self.reply(chat, WRONG_HASH)         # a hash typed with /approve is the card's, for an effect, a plan and an acceptance
            return
        if kind == "plan" and item.get("plan_networked") is True:       # a plan that reaches the network: its destinations must have been shown, whole
            self.allow(project, "approve", "plan:networked", chat)
            if card.get("whole") is not True or self.settings(project)["notices"] != "text":
                command = self.ops.operations.command_line("approve", project["path"], checkout=ROOT, pending_id=number,
                                                           sha256=card["content_sha256"])
                self.reply(chat, f"{TOO_LONG}\n{command}")
                return
            if card.get("approvable") is not True:       # only a gated card (an effect, a networked plan) must have offered the approval;
                self.reply(chat, NOT_OFFERED)           # a plain plan or an acceptance is checked against the policy when the person acts
                return
        if kind == "acceptance" and cards.content_sha256(item) != card["content_sha256"]:
            self.reply(chat, CHANGED)
            self.renew(project, chat, number, card)
            return
        args = {"pending_id": number}
        if kind == "plan":
            args["sha256"] = card["content_sha256"]
        self.run_op(project, "approve", kind=kind, sender=chat, **args)
        self.reply(chat, f"Approved #{number}.")

    def approve_effect(self, project: dict, chat: str, item: dict, card, typed_hash=None) -> None:
        """An effect, from a tap or a typed line. By default (the policy does not grant the word) the reply is the command, as it always was.
        Granted, every one of these must hold or nothing runs: a card (NO_CARD), a card that carried the whole text and a decision whose
        whole effect fits on a card (TOO_LONG), a typed hash that is the card's, a card whose hash is the decision's own payload hash
        (CHANGED, and a new card), a decision still open. The call is the operations layer's approve with the CARD's hash, in a job thread."""
        number = item["id"]
        word = item.get("effect_word")
        ask = "effect:" + word if isinstance(word, str) and word else "effect"
        command = self.ops.operations.command_line("approve", project["path"], checkout=ROOT, pending_id=number,
                                                   sha256=item.get("payload_sha256"))
        settings = self.settings(project)
        if settings is None:
            raise Refused(NOT_ACCEPTED)
        if not self.ops.operations.permitted("approve", CHANNEL, settings["policy"], ask, self.key(chat)) or settings["notices"] != "text":
            self.reply(chat, f"{EFFECT_REPLY}\n{command}")     # not granted, or a card that carries none of the text: the command, as it always was
            return
        if card is None:
            self.reply(chat, NO_CARD)
            return
        if card.get("whole") is not True or item.get("effect_on_cards") is not True:
            self.reply(chat, f"{TOO_LONG}\n{command}")
            return
        if typed_hash is not None and typed_hash != card["content_sha256"]:
            self.reply(chat, WRONG_HASH)
            return
        if card.get("approvable") is not True:       # only a card that offered the approval can be approved by a typed line
            self.reply(chat, NOT_OFFERED)
            return
        if item.get("status", "open") != "open":
            self.reply(chat, NOT_OPEN.format(number=number, status=item.get("status")))
            return
        if card["content_sha256"] != item.get("payload_sha256"):
            self.reply(chat, CHANGED)
            self.renew(project, chat, number, card)
            return
        shown = card["content_sha256"]

        def call():
            try:
                self.run_op(project, "approve", kind=ask, sender=chat, pending_id=number, sha256=shown)
                self.reply(chat, f"Approved #{number}.")
            except Refused as e:
                self.reply(chat, str(e))
            except self.ops.OpsError as e:
                self.reply(chat, str(e))
                self.renew(project, chat, number, card)
        self.start(project, chat, "approve", call)

    def release(self, project: dict, chat: str, pending_id: int) -> None:
        def call():
            try:
                self.run_op(project, "release", sender=chat, pending_id=pending_id)
                self.reply(chat, f"Released #{pending_id}.")
            except Refused as e:
                self.reply(chat, str(e))
            except self.ops.OpsError as e:
                self.reply(chat, RUN_BUSY if type(e).__name__ == "RunBusy" else str(e))
        self.start(project, chat, "release", call)

    def say(self, project: dict, chat: str, text: str) -> None:
        def call():
            try:
                result = self.run_op(project, "say", sender=chat, text=text)
                self.reply(chat, result.get("reply") or "(no reply)")
            except Refused as e:
                self.reply(chat, str(e))
            except self.ops.OpsError as e:
                self.reply(chat, RUN_BUSY if type(e).__name__ == "RunBusy" else f"error: {e}")
        self.start(project, chat, "say", call)

    def start(self, project: dict, chat: str, op: str, call) -> None:
        """A call that may take minutes runs in a thread; a model call takes the project's slot, one at a time."""
        try:
            self.start_job(project["id"], op, call)
        except shell_kit.Busy:
            self.reply(chat, STILL_WORKING)
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
            update = session.next_update(max(wait, 0.05))
            if update is not None:
                self.handle_safely(update)
                if update.get("chat") in self.deferred_chats:   # the person wrote: a kept card can go out now
                    self.deferred_chats.discard(update.get("chat"))
                    due = 0.0

    def serve_loop(self, stop: threading.Event, notice_every: float, poll: int = POLL_SECONDS) -> None:
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
            try:
                self.poll_once(wait)
            except provider.MessengerError as e:
                if e.kind == "not-configured":
                    raise Fatal(e.reason) from None
                self.log(f"the messenger did not answer ({e.kind}); trying again")
                stop.wait(RETRY_SECONDS)
