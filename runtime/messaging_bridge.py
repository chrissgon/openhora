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

Notices. Each tick, per project, every open decision gets one card per listed sender, once per content (the ledger,
runtime/messaging_ledger.py). A changed plan, or any decision whose content hash changed, gets a new card. At most 10
cards per project and tick; the rest are announced in one line.

Approvals. A tap or /approve is bound to the card the person saw. A plan is approved with the hash the ledger recorded
(ops.approve refuses a plan that changed). An acceptance has no hash, so the bridge compares the decision's text now with
the hash recorded for the card and approves nothing when they differ. An effect is never approved here (decision D8):
the reply is the command to run in the terminal.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
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
RETRY_SECONDS = 5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROPPED = "dropped an update from an unlisted sender"
STALE = "This button is no longer valid. Send /pending."
NO_CARD = "Send /pending first, so you see what you approve."
CHANGED = "This decision changed since you saw it."
STILL_WORKING = "Still working on the last message."
RUN_BUSY = "A run is in progress. Send it again when it ends."
NOT_ACCEPTED = "This project's configuration is not accepted: run accept-config in the terminal."
EFFECT_REPLY = "An effect is approved on the page or in the terminal, with its hash:"


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
        self.more = {}         # project id -> the number last announced as waiting
        self.policy_noted = set()

    # --- the projects and their settings ---------------------------------------------------------------------

    def settings(self, project: dict):
        """The accepted settings of a project for this platform, or None when its configuration is not accepted."""
        found = self.ops.config(project["path"])
        if not found.get("accepted"):
            return None
        messaging = found.get("messaging") or {}
        return {"senders": list((messaging.get("senders") or {}).get(self.platform) or []),
                "notices": messaging.get("notices") or "text", "page_url": messaging.get("page_url"),
                "policy": found.get("channels") or {}}

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

    def reply(self, chat: str, text: str) -> None:
        caps = self.messenger.capabilities()
        for piece in cards.split(text or "(no reply)", caps["max_text"]):
            try:
                self.messenger.send(chat, {"text": piece, "actions": [], "link": None, "document": None})
            except provider.MessengerError as e:
                self.log(f"a reply could not be sent ({e.kind})")
                return

    def allow(self, project: dict, op: str, kind=None) -> dict:
        """The project's accepted settings when the policy permits the operation (for this kind of decision), else
        Refused with the sentence the operations layer uses too."""
        settings = self.settings(project)
        if settings is None:
            raise Refused(NOT_ACCEPTED)
        operations = self.ops.operations
        if not operations.permitted(op, CHANNEL, settings["policy"], kind):
            raise Refused(operations.not_enabled(op, CHANNEL))
        return settings

    def run_op(self, project: dict, op: str, kind=None, **args):
        """The one call path: the policy first, then the operation, as the channel `messaging`."""
        self.allow(project, op, kind)
        row = self.ops.operations.by_name(op)
        if row.get("channel_arg"):
            args["channel"] = CHANNEL
        return getattr(self.ops, row["call"])(project["path"], **args)

    def send_card(self, project: dict, settings: dict, item: dict, chat: str) -> bool:
        operations = self.ops.operations
        command = None
        if item["kind"] == "effect":
            command = operations.command_line("approve", project["path"], checkout=ROOT, pending_id=item["id"],
                                              sha256=item.get("payload_sha256"))
        card = cards.build(project["name"], item, self.messenger.capabilities(), settings["policy"], settings["notices"],
                           settings["page_url"], operations=operations, effect_command=command)
        seq = self.ledger.next_seq()
        message = dict(card["message"])
        made = {f"{seq}:{a['op']}": a["op"] for a in message["actions"]}
        message["actions"] = [{"id": f"{seq}:{a['op']}", "label": a["label"]} for a in message["actions"]]
        try:
            message_id = self.messenger.send(chat, message)
        except provider.MessengerError as e:
            self.log(f"a card could not be sent ({e.kind})")
            if e.kind == "not-configured":
                raise Fatal(e.reason) from None
            return False
        try:
            self.ledger.add({"project": project["id"], "pending_id": item["id"], "kind": item["kind"],
                             "content_sha256": card["content_sha256"], "chat": chat, "message_id": message_id,
                             "actions": made, "sent_at": self.clock()})
        except OSError as e:  # the card went out and the process keeps the record in memory; it is not sent again
            self.log(f"the ledger could not be written ({e.__class__.__name__})")
        return True

    # --- notices ---------------------------------------------------------------------------------------------

    def notify_project(self, project: dict, only_chat=None, cap: int = CARDS_PER_TICK) -> int:
        """Send the cards a project's open decisions lack (to `only_chat`, or to every listed sender). Returns how many
        decisions are left over for the next tick."""
        settings = self.settings(project)
        if not settings or not settings["senders"]:
            return 0
        if not self.ops.operations.permitted("pending", CHANNEL, settings["policy"]):
            if project["id"] not in self.policy_noted:
                self.policy_noted.add(project["id"])
                self.log("notices are off: the project's channel policy does not permit reads")
            return 0
        chats = [only_chat] if only_chat else settings["senders"]
        left = sent = 0
        for listed in self.ops.pending(project["path"])["pending"]:
            item = self.ops.pending(project["path"], pending_id=listed["id"])
            if item.get("status", "open") != "open":
                continue
            digest = cards.content_sha256(item)
            lacking = [c for c in chats if not self.ledger.sent(project["id"], item["id"], digest, c)]
            if not lacking:
                continue
            if sent >= cap:
                left += 1
                continue
            for chat in lacking:
                self.send_card(project, settings, item, chat)
            sent += 1
        return left

    def tick(self) -> None:
        for project in self.projects:
            try:
                left = self.notify_project(project)
                settings = self.settings(project)
            except self.ops.OpsError as e:
                self.log(f"a project could not be read for notices ({e.__class__.__name__})")
                continue
            if left != self.more.get(project["id"], 0):
                self.more[project["id"]] = left
                if left and settings:
                    for chat in settings["senders"]:
                        self.reply(chat, cards.MORE_LINE.format(n=left))

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
            self.act(project, chat, kind, intent["id"], note=intent.get("note"))
        elif kind == "answer":
            self.act(project, chat, "answer", intent["id"], text=intent["text"])
        elif kind == "reply":
            card = self.ledger.by_message(chat, intent["reply_to"])
            if card and card["kind"] == "question":
                target = next((p for p in self.projects if p["id"] == card["project"]), project)
                if not self.listed_in(target, sender):
                    self.log(DROPPED)
                    return
                self.act(target, chat, "answer", card["pending_id"], text=intent["text"])
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
        if card is None or project is None:
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
            found = self.run_op(project, "pending")["pending"]
        except (Refused, self.ops.OpsError) as e:
            self.reply(chat, str(e))
            return
        if not found:
            self.reply(chat, f"{project['name']}: nothing waits for you.")
            return
        self.reply(chat, f"{project['name']}: " + "\n".join(f"#{i['id']} {i['kind']}: {i['title']}" for i in found))
        try:
            self.notify_project(project, only_chat=chat)
        except self.ops.OpsError as e:
            self.log(f"cards could not be sent ({e.__class__.__name__})")

    def act(self, project: dict, chat: str, op: str, pending_id: int, card=None, note=None, text=None) -> None:
        """approve, reject, release or answer one decision, bound to the card the person saw."""
        try:
            if op == "answer":
                self.run_op(project, "answer", pending_id=pending_id, text=text)
                self.reply(chat, f"Answered #{pending_id}.")
                return
            card = card or self.ledger.last_card(project["id"], pending_id, chat)
            item = self.ops.pending(project["path"], pending_id=pending_id)
            if op == "approve":
                self.approve(project, chat, item, card)
            elif op == "reject":
                self.run_op(project, "reject", pending_id=pending_id, **({"note": note} if note else {}))
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

    def approve(self, project: dict, chat: str, item: dict, card) -> None:
        kind, number = item["kind"], item["id"]
        if kind == "effect":
            command = self.ops.operations.command_line("approve", project["path"], checkout=ROOT, pending_id=number,
                                                       sha256=item.get("payload_sha256"))
            self.reply(chat, f"{EFFECT_REPLY}\n{command}")
            return
        if kind not in ("plan", "acceptance"):
            self.reply(chat, f"Pending decision {number} is a {kind}: approve takes a plan or an acceptance.")
            return
        self.allow(project, "approve", kind)
        if card is None:
            self.reply(chat, NO_CARD)
            return
        if kind == "acceptance" and cards.content_sha256(item) != card["content_sha256"]:
            self.reply(chat, CHANGED)
            self.renew(project, chat, number, card)
            return
        args = {"pending_id": number}
        if kind == "plan":
            args["sha256"] = card["content_sha256"]
        self.run_op(project, "approve", kind=kind, **args)
        self.reply(chat, f"Approved #{number}.")

    def release(self, project: dict, chat: str, pending_id: int) -> None:
        def call():
            try:
                self.run_op(project, "release", pending_id=pending_id)
                self.reply(chat, f"Released #{pending_id}.")
            except Refused as e:
                self.reply(chat, str(e))
            except self.ops.OpsError as e:
                self.reply(chat, RUN_BUSY if type(e).__name__ == "RunBusy" else str(e))
        self.start(project, chat, "release", call)

    def say(self, project: dict, chat: str, text: str) -> None:
        def call():
            try:
                result = self.run_op(project, "say", text=text)
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

    def poll_once(self, timeout: int) -> int:
        """One receive and the handling of what it returned. Returns the number of updates handled."""
        found = self.messenger.receive(self.ledger.offset, timeout)
        for update in found["updates"]:
            try:
                self.handle(update)
            except Fatal:
                raise
            except Exception:  # one update never ends the bridge; the class says what failed, never the content
                self.log("an update failed: " + traceback.format_exc().strip().splitlines()[-1].split(":")[0])
        try:
            self.ledger.set_offset(found["next_offset"])
        except OSError as e:
            self.log(f"the ledger could not be written ({e.__class__.__name__})")
        return len(found["updates"])

    def serve_loop(self, stop: threading.Event, notice_every: float, poll: int = POLL_SECONDS) -> None:
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
