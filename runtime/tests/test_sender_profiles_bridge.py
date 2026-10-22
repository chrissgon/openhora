"""The messaging bridge with a profile for each sender (package POL-2; runtime/messaging_bridge.py, runtime/messaging_cards.py), over the REAL operations
layer and a stand-in messenger provider: the owner and an employee on one platform, each asked about what their own profile permits, at the moment of
acting; a card acted on only in the chat it was sent to; a sender narrowed or removed after a card went out; the first act on a decision that several
senders received, and a profile that is sent a card only for a decision it can act on. Offline, no model; invented ids.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sender_profiles_bridge.py
"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import threading
from pathlib import Path

import pytest

import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging import FIXTURE, wait_for
from test_messaging_policy import decisions
from test_sender_profiles import OWNER, OWNER_KEY, POLICIES, STAFF, STAFF_KEY, accept, write_config

ops = st.load("ops")
ops_core = st.load("ops_core")
operations = st.load("operations")
bridge = st.load("messaging_bridge")
cards = st.load("messaging_cards")
guard = st.load("messaging_guard")
phrases = st.load("phrases")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")

OTHER = "55119000000003"
CLERK = "55119000000004"
NOT_ENABLED = "You do not have permission for that here yet."      # S10: the plain sentence a phone is told (limit L62)
POLICIES_ALL = {**POLICIES, "clerk": {"groups": ["read-limited", "talk", "answer", "approve-acceptances"], "notices": "actionable"},
                "watcher": {"groups": ["read-limited", "talk", "answer"], "notices": "actionable"}}


class Lab:
    pass


@pytest.fixture
def lab(tree, tmp_path, monkeypatch):  # noqa: F811
    path, plan_id, digest, accept_id, effect = decisions(tree)
    root = tmp_path / "bench-messenger"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))
    data = tmp_path / "ledger-data"
    data.mkdir()
    w = Lab()
    w.path, w.plan, w.digest, w.acceptance, w.effect, w.folder, w.log = path, plan_id, digest, accept_id, effect, folder, []
    w.tmp = tmp_path
    projects = [{"id": shell_kit.project_id(path), "name": "northwind-shop", "path": path}]
    w.bridge = bridge.Bridge(ops, projects, providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(data), "telegram"), "telegram", w.log.append,
                             clock=lambda: "2026-10-11T10:00:00+00:00")

    def sent(chat=None):
        file = folder / "sent.jsonl"
        rows = [json.loads(line) for line in file.read_text().splitlines()] if file.is_file() else []
        return [r for r in rows if chat is None or r["chat"] == chat]
    w.sent = sent
    w.texts = lambda chat=None: [r["message"]["text"] for r in sent(chat)]

    def say(sender, text=None, action=None, **fields):
        update = {"update_id": 1, "sender": sender, "chat": sender, "private": True, "text": text, "action": action,
                  "action_ref": "ref-1" if action else None, "reply_to": None}
        update.update(fields)
        w.bridge.handle(update)
    w.say = say

    def settle():
        """Wait until every job thread the bridge started has ended. A reply is sent inside the job's call, so a reply seen is not yet the end of the
        job: the project's model slot is released after the call returns, and a command sent at once can find it held (Busy)."""
        for thread in list(w.bridge.threads):
            thread.join(30)
    w.settle = settle

    def card(chat, kind="plan"):
        for row in reversed(sent(chat)):
            if f"{kind} #" in row["message"]["text"]:
                return row["message"]
        return None
    w.card = card

    def action(chat, label, kind="plan"):
        found = card(chat, kind)
        return next((a["id"] for a in found["actions"] if a["label"] == label), None) if found else None
    w.action = action

    def status(number):
        return ops.pending(path, number)["status"]
    w.status = status

    def who(number):
        ctx = ops_core.context(path)
        return ctx["store"].pending_get(ctx["conn"], number)["actor"]
    w.who = who
    yield w
    w.bridge.stopping.set()
    w.settle()


def configure(lab, senders, policies=POLICIES_ALL, channel="staff", notices="text"):
    accept(lab.path, policies=policies, channels={"messaging": channel} if channel else None,
           messaging={"senders": {"telegram": senders}, "notices": notices})


def two(lab):
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}])


# --- the owner and the employee on one platform -------------------------------------------------------------------------------


def test_each_sender_is_sent_a_card_drawn_for_their_own_profile_and_acts_only_as_far_as_it_goes(lab):
    two(lab)
    lab.bridge.tick()
    owner, staff = lab.card(OWNER), lab.card(STAFF)
    assert [a["label"] for a in owner["actions"]] == ["Approve", "Reject"], "the owner's profile approves plans and rejects"
    assert staff["actions"] == [] and "Act on it on the platform's page." in staff["text"], "the employee's lists neither"
    # the employee types the approval: refused for THEIR profile, with the hash and everything else right; nothing happens
    lab.say(STAFF, f"/approve {lab.plan} {lab.digest}")
    assert NOT_ENABLED in lab.texts(STAFF)[-1] and lab.status(lab.plan) == "open"
    lab.say(STAFF, f"/reject {lab.plan}")
    assert NOT_ENABLED in lab.texts(STAFF)[-1] and lab.status(lab.plan) == "open"
    lab.say(STAFF, f"/release {lab.plan}")
    assert NOT_ENABLED in lab.texts(STAFF)[-1] and lab.status(lab.plan) == "open"
    # the owner taps their button: approved, recorded as the owner's act
    lab.say(OWNER, action=lab.action(OWNER, "Approve"))
    assert lab.texts(OWNER)[-1] == f"Approved #{lab.plan}." and lab.status(lab.plan) == "resolved"
    assert lab.who(lab.plan) == f"messaging:telegram:owner:{OWNER}"
    assert OWNER not in json.dumps(ops.pending(lab.path, lab.plan)) and ops.pending(lab.path, lab.plan)["acted_by"] == "owner on telegram"


def test_the_employee_reads_what_waits_and_never_the_spend_and_the_owner_reads_both(lab):
    two(lab)
    lab.say(STAFF, "/pending")
    assert f"#{lab.plan} plan" in lab.texts(STAFF)[0]
    lab.say(STAFF, "/progress")                     # a line that is a command of the table runs in a job thread of the bridge
    assert wait_for(lambda: any(NOT_ENABLED in t for t in lab.texts(STAFF)))
    assert not any("cost known" in t for t in lab.texts(STAFF)), "the employee never reads the spend"
    lab.settle()                                    # the reply is sent inside the job: the owner's line waits until the job has ended and released the slot
    lab.say(OWNER, "/progress")
    assert wait_for(lambda: any("cost known" in t for t in lab.texts(OWNER)))


def test_a_tap_of_the_employee_on_a_card_sent_to_the_owner_is_refused_by_the_ledger_and_by_the_explicit_check(lab, monkeypatch):
    two(lab)
    lab.bridge.tick()
    owners_button = lab.action(OWNER, "Approve")
    assert owners_button
    # the ledger finds a card by chat and action: the employee's chat has no such action
    lab.say(STAFF, action=owners_button)
    assert lab.texts(STAFF)[-1] == bridge.STALE and lab.status(lab.plan) == "open"


def test_a_sender_who_may_approve_still_cannot_act_on_a_card_that_was_sent_to_another_chat(lab, monkeypatch):
    """The policy alone would let this sender approve a plan (their profile lists approve-plans); only the rule that a card is acted on in its own
    chat stops them when the ledger, or a bug, answers with the owner's card."""
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": CLERK, "policy": "approver"}],
              policies={**POLICIES_ALL, "approver": ["read-limited", "talk", "answer", "approve-plans"]})
    lab.bridge.tick()
    owners_card = next(c for c in lab.bridge.ledger.data["cards"] if c["chat"] == OWNER and c["kind"] == "plan")
    owners_button = lab.action(OWNER, "Approve")
    with monkeypatch.context() as patched:
        patched.setattr(lab.bridge.ledger, "by_action", lambda chat, action_id: owners_card)
        before = len(lab.texts(CLERK))
        lab.say(CLERK, action=owners_button)
        assert lab.texts(CLERK)[before:] == [bridge.STALE] and lab.status(lab.plan) == "open" and lab.who(lab.plan) is None
        patched.setattr(lab.bridge.ledger, "last_card", lambda project, pending_id, chat: owners_card)
        lab.say(CLERK, f"/approve {lab.plan} {owners_card['content_sha256']}")
        assert lab.texts(CLERK)[-1] == bridge.NO_CARD and lab.status(lab.plan) == "open", "a typed approval binds to the sender's own card, never another chat's"
    lab.say(CLERK, f"/approve {lab.plan} {lab.digest}")                      # with their own card, the same sender may
    assert lab.status(lab.plan) == "resolved" and lab.who(lab.plan).endswith(f":approver:{CLERK}")


def test_a_typed_approval_of_the_owner_needs_the_owners_own_card_and_the_hash_of_it(lab):
    two(lab)
    lab.say(OWNER, f"/approve {lab.plan}")
    assert lab.texts(OWNER)[-1] == bridge.NO_CARD and lab.status(lab.plan) == "open"
    lab.bridge.tick()
    lab.say(OWNER, f"/approve {lab.plan} {'0' * 64}")
    assert lab.texts(OWNER)[-1] == bridge.WRONG_HASH and lab.status(lab.plan) == "open"
    lab.say(OWNER, f"/approve {lab.plan} {lab.digest}")
    assert lab.texts(OWNER)[-1] == f"Approved #{lab.plan}." and lab.who(lab.plan).endswith(f":owner:{OWNER}")


def test_a_sender_narrowed_after_the_card_was_sent_is_refused_at_the_tap_and_a_sender_removed_is_dropped(lab):
    two(lab)
    lab.bridge.tick()
    button = lab.action(OWNER, "Approve")
    # narrowed: the owner's profile loses approve-plans (a narrowing is accepted without the hash of a list: nothing is widened)
    accept(lab.path, policies={**POLICIES_ALL, "owner": ["read", "talk", "answer"]})
    lab.say(OWNER, action=button)
    assert NOT_ENABLED in lab.texts(OWNER)[-1] and lab.status(lab.plan) == "open"
    # the profile is given back: the same button works again (the permission is read when the person acts, not when the card was sent)
    accept(lab.path, policies=POLICIES_ALL)
    # removed from the list of senders: the update is dropped with no reply, and nothing happens
    configure(lab, [{"id": STAFF, "policy": "staff"}])
    seen = len(lab.texts(OWNER))
    lab.say(OWNER, action=button)
    assert len(lab.texts(OWNER)) == seen and bridge.DROPPED in lab.log and lab.status(lab.plan) == "open"
    # listed again: the old card still approves, once
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}])
    lab.say(OWNER, action=button)
    assert lab.status(lab.plan) == "resolved"


def test_a_file_edited_but_not_accepted_refuses_every_sender_whatever_their_profile(lab):
    two(lab)
    lab.bridge.tick()
    button = lab.action(OWNER, "Approve")
    write_config(lab.path, policies={**POLICIES_ALL, "owner": [*POLICIES["owner"], "brakes"]})
    seen = len(lab.texts(OWNER))
    lab.say(OWNER, action=button)
    assert len(lab.texts(OWNER)) == seen and bridge.DROPPED in lab.log, "a project whose file is not accepted serves nobody: the update is dropped"
    ctx = ops_core.context(lab.path, check_config=False)
    assert ctx["store"].pending_get(ctx["conn"], lab.plan)["status"] == "open"


def test_the_first_act_on_a_decision_several_senders_received_resolves_it_and_the_others_are_refused(lab):
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": OTHER, "policy": "owner"}])
    lab.bridge.tick()
    first, second = lab.action(OTHER, "Approve"), lab.action(OWNER, "Approve")
    lab.say(OTHER, action=first)
    assert lab.status(lab.plan) == "resolved" and lab.who(lab.plan).endswith(f":owner:{OTHER}")
    tasks_before = [t["id"] for r in ops.status(lab.path)["requests"] for t in r["tasks"]]
    lab.say(OWNER, action=second)
    assert lab.texts(OWNER)[-1] == "Request #3 was already resolved." and lab.status(lab.plan) == "resolved"
    assert lab.who(lab.plan).endswith(f":owner:{OTHER}"), "the first act stays the record"
    assert [t["id"] for r in ops.status(lab.path)["requests"] for t in r["tasks"]] == tasks_before and tasks_before, "the plan was approved once"


def test_a_profile_with_notices_actionable_is_sent_a_card_only_for_a_decision_it_can_act_on_or_answer(lab):
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": CLERK, "policy": "clerk"}, {"id": STAFF, "policy": "watcher"}, OTHER])
    lab.bridge.tick()
    kinds = lambda chat: sorted(c["kind"] for c in lab.bridge.ledger.data["cards"] if c["chat"] == chat)         # noqa: E731
    assert kinds(OWNER) == ["acceptance", "effect", "plan"]
    assert kinds(CLERK) == ["acceptance"], "the clerk can accept; a plan and an effect are not theirs to act on"
    assert kinds(STAFF) == [], "the watcher can answer questions only: no open question, no card"
    assert kinds(OTHER) == ["acceptance", "effect", "plan"], "a plain sender gets the channel's profile, whose notices are all"
    # /pending lists to a profile that is sent only what it can act on only that; the owner is listed everything
    lab.say(CLERK, "/pending")
    assert f"#{lab.acceptance} acceptance" in lab.texts(CLERK)[-1] and f"#{lab.plan} plan" not in lab.texts(CLERK)[-1]
    lab.say(STAFF, "/pending")
    assert lab.texts(STAFF)[-1] == "northwind-shop: nothing waits for you to act on."
    lab.say(OWNER, "/pending")
    assert any(t.startswith("northwind-shop: #") and f"#{lab.plan} plan" in t for t in lab.texts(OWNER))


def test_a_sender_whose_profile_cannot_read_what_waits_is_sent_no_card(lab):
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "mute"}], policies={**POLICIES, "mute": ["talk"]})
    lab.bridge.tick()
    assert lab.texts(STAFF) == [] and lab.texts(OWNER), "reads are the profile's: notices need `read` or `read-limited`"


def test_approving_an_effect_for_the_owner_alone_the_card_is_built_for_the_sender(lab):
    """The owner's profile grants a write; the employee's does not. A pull request effect has no card that shows the change, so neither is offered the
    approval (POL-1), but the owner's card is drawn for the owner: the reject button follows their profile."""
    two(lab)
    lab.bridge.tick()
    owners, staffs = lab.card(OWNER, "request"), lab.card(STAFF, "request")
    assert [a["label"] for a in owners["actions"]] == ["Reject"] and staffs["actions"] == []
    lab.say(OWNER, f"/approve {lab.effect['id']} {lab.effect['payload_sha256']}")
    assert lab.status(lab.effect["id"]) == "open"
    assert lab.texts(OWNER)[-1].startswith(bridge.EFFECT_REPLY)      # a pull request is approved in the terminal or on the page: no profile grants it a card yet


def test_the_bridge_passes_the_sender_to_every_operation_that_asks_the_policy_or_records_who_acted():
    for name in ("answer", "release", "approve", "reject", "retry", "cancel", "stop-task", "say"):
        row = operations.by_name(name)
        assert row.get("channel_arg") is True, name
        assert "sender" in inspect.signature(getattr(ops, row["call"])).parameters, name


def test_limit_46_an_act_from_a_messaging_app_is_checked_against_the_profile_of_the_sender_who_acted_when_they_act_and_only_in_the_chat_of_its_card(lab):
    two(lab)
    lab.bridge.tick()
    button = lab.action(OWNER, "Approve")
    # the profile of the sender who acted: the employee's does not list the approval, the owner's does
    lab.say(STAFF, f"/approve {lab.plan} {lab.digest}")
    assert NOT_ENABLED in lab.texts(STAFF)[-1] and lab.status(lab.plan) == "open"
    # only in the chat of its card: the employee holding the owner's button, and a ledger that were to answer with the owner's card, change nothing
    lab.say(STAFF, action=button)
    assert lab.texts(STAFF)[-1] == bridge.STALE and lab.status(lab.plan) == "open"
    # when they act, not when the card was sent: narrowed since, the same button is refused; given back, it works
    accept(lab.path, policies={**POLICIES_ALL, "owner": ["read", "talk", "answer"]})
    lab.say(OWNER, action=button)
    assert NOT_ENABLED in lab.texts(OWNER)[-1] and lab.status(lab.plan) == "open"
    accept(lab.path, policies=POLICIES_ALL, channels={"messaging": "staff"})
    # nothing a sender sends names a profile: a text that carries the profile's name is a line, checked for the sender
    lab.say(STAFF, f"/approve {lab.plan} {lab.digest} profile owner")
    assert lab.status(lab.plan) == "open"
    lab.say(OWNER, action=button)
    assert lab.status(lab.plan) == "resolved"
    # the sender is recorded in the store, and in no file of the project
    assert lab.who(lab.plan) == f"messaging:telegram:owner:{OWNER}"
    state = (Path(lab.path) / "docs" / "workbench" / "state.md").read_text()
    assert OWNER not in state and STAFF not in state


def test_the_bridge_never_calls_an_operation_that_cannot_be_told_who_acts_and_the_count_of_waiting_decisions_goes_only_to_those_who_read_and_get_every_notice(lab):
    configure(lab, [{"id": OWNER, "policy": "owner"}], policies={**POLICIES_ALL, "owner": [*POLICIES["owner"], "routine-edit"]})
    row = operations.by_name("routine-create")
    assert row.get("channel_arg") and "sender" not in inspect.signature(getattr(ops, row["call"])).parameters
    with pytest.raises(RuntimeError, match="takes no sender"):
        lab.bridge.run_op({"id": "x", "path": lab.path, "name": "n"}, "routine-create", sender=OWNER)
    # twelve open decisions would make "And 2 more waiting": a profile with actionable notices, or one that cannot read, is not told
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "watcher"}, {"id": CLERK, "policy": "mute"}],
              policies={**POLICIES_ALL, "mute": ["talk"]})
    settings = lab.bridge.settings(lab.bridge.projects[0])
    assert [lab.bridge.hears_count(settings, c) for c in (OWNER, STAFF, CLERK)] == [OWNER, None, None]


def test_a_reject_a_release_and_an_answer_typed_by_id_need_the_card_the_sender_was_sent_as_an_approval_does(lab):
    two(lab)
    for line in (f"/reject {lab.plan}", f"/release {lab.plan}", f"/answer {lab.plan} yes"):
        lab.say(OWNER, line)
        assert lab.texts(OWNER)[-1] == bridge.NO_CARD, line
    assert lab.status(lab.plan) == "open"
    lab.bridge.tick()
    lab.say(OWNER, f"/reject {lab.acceptance}")
    assert lab.texts(OWNER)[-1] == f"Rejected #{lab.acceptance}." and lab.status(lab.acceptance) == "resolved"
    assert lab.who(lab.acceptance) == f"messaging:telegram:owner:{OWNER}"
    # the card is the sender's own: the owner's card does not let the clerk reject, whatever their profile lists
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": CLERK, "policy": "rejecter"}], policies={**POLICIES_ALL, "rejecter": ["read-limited", "reject-cancel"]})
    lab.say(CLERK, f"/reject {lab.plan}")
    assert lab.texts(CLERK)[-1] == bridge.NO_CARD and lab.status(lab.plan) == "open"


def test_the_log_says_which_refusal_of_the_configuration_stopped_the_bridge_and_never_an_id(lab):
    two(lab)
    write_config(lab.path, messaging={"senders": {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": OWNER, "policy": "staff"}]}, "notices": "text"})
    lab.bridge.recheck()
    skipped = [line for line in lab.log if line.startswith("skipping")]
    assert skipped and "its configuration cannot be read: runtime.json messaging.senders.telegram: a sender is listed once on a platform" in skipped[-1]
    assert OWNER not in " ".join(lab.log)
    assert bridge.reason_of(Exception("runtime.json messaging.senders: 55119000000001 is odd")) == ": runtime.json messaging.senders: <digits> is odd"
    assert bridge.reason_of(Exception("/private/path/runtime.json is odd")) == ""


def test_the_bridge_asks_the_policy_for_a_sender_never_for_the_channel_alone(lab):
    two(lab)
    project = {"id": "x", "path": lab.path, "name": "n"}
    for call in (lambda: lab.bridge.allow(project, "pending"), lambda: lab.bridge.run_op(project, "pending")):
        with pytest.raises(RuntimeError, match="never for the channel alone"):
            call()


def everything_sent(lab) -> str:
    """Every message the stand-in messenger was handed, whole: texts, files and links."""
    return json.dumps(lab.sent(), ensure_ascii=False)


def test_no_message_the_bridge_sends_carries_the_home_folder_whatever_it_is_and_a_command_in_it_still_runs(lab, monkeypatch):
    """The home folder is the test's temporary folder (the project, the data and the checkout all lie under it). One filter at the one send point
    covers a reply, a card and a file; each case below is a different way a path reaches a phone."""
    home = str(lab.tmp)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setattr(bridge, "ROOT", str(lab.tmp / "checkout"))                  # the checkout a command is spelled with
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}],
              policies={**POLICIES_ALL, "owner": [*POLICIES["owner"], "approve-networked-plans"]}, notices="count")
    real_pending = ops.pending

    def networked(project, pending_id=None):
        found = real_pending(project, pending_id) if pending_id is not None else real_pending(project)
        return {**found, "plan_networked": True} if pending_id is not None and found.get("kind") == "plan" else found
    monkeypatch.setattr(ops, "pending", networked)
    lab.bridge.tick()                                                                   # the cards: an effect that no card approves carries a command
    lab.say(STAFF, f"/approve {lab.plan} {lab.digest}")                                 # a refused operation
    lab.say(OWNER, f"/approve {lab.effect['id']} {lab.effect['payload_sha256']}")       # an effect: the command to run in the terminal
    lab.say(OWNER, f"/approve {lab.plan} {lab.digest}")                                 # a plan that reaches the network: the command, too
    monkeypatch.setattr(ops, "reject", lambda project, pending_id, note=None, channel=None, sender=None: (_ for _ in ()).throw(
        ops.OpsError(f"nothing was done in {lab.path}/docs: see {home}/x", 1)))        # an OpsError that carries a path
    lab.say(OWNER, f"/reject {lab.acceptance}")
    lab.bridge.reply(OWNER, json.dumps({"approve": {"command": operations.command_line("routine-approve", lab.path, checkout=str(lab.tmp / "checkout"),
                                                                                       routine_id=1, sha256="a" * 64)}}), guard=True)           # the operations layer's own text, a draft routine's approve command: the net cuts it
    real_say = ops.say
    monkeypatch.setattr(ops, "say", lambda project, text, channel=None, sender=None: {"reply": "unclassified, name a flow"})
    lab.say(OWNER, "make a thing")                                                      # an unclassified route
    assert wait_for(lambda: "unclassified" in everything_sent(lab))
    lab.settle()
    monkeypatch.setattr(ops, "pending", real_pending)
    monkeypatch.setitem(ops.SERVICE, os.path.realpath(lab.path), {"dispatch": "off", "at": "2026-10-17T10:00:00Z"})      # the local service dispatches nothing
    ops.approve(lab.path, lab.plan, lab.digest, channel="terminal")                     # the person approves the plan in the terminal: its tasks are ready, and held
    monkeypatch.setattr(ops, "say", real_say)
    lab.say(OWNER, "/status")                                                           # a held task: its command
    assert wait_for(lambda: "dispatch off" in everything_sent(lab))
    blob = everything_sent(lab)
    assert home not in blob and lab.path not in blob and str(lab.tmp / "checkout") not in blob, "no message carries the home folder"
    # LIVE-2 (limit L62): a phone is told where, never the command. The two texts the test injects (a routine's approve command, a route command) are cut by the net under
    # the sentences, which says so once and records an event; every sentence of the bridge's own carries none to cut.
    assert "~/" not in blob and "cli.py" not in blob and "--project" not in blob and "--sha256" not in blob and "uv run" not in blob
    assert [e["kinds"] for e in guard.EVENTS if "command" in e["kinds"]], "the net recorded what it cut"
    assert phrases.text("PHONE_STRIPPED", None, where=phrases.where_page(None)) in blob


def test_the_footer_a_card_hands_over_is_scrubbed_with_its_text_and_stays_an_exact_suffix_of_it(monkeypatch):
    monkeypatch.setattr(bridge, "home_folders", lambda: ["/Users/zed"])
    footer = ["Approve it on the page or in the terminal:", "`python3 /Users/zed/co/runtime/cli.py approve --project '/Users/zed/my proj' --id 7`"]
    message = {"text": "co · effect #7\n\nbody\n\n" + "\n".join(footer), "actions": [], "link": None, "document": None, "footer": footer}
    sent = bridge.scrub_message(message)
    assert "/Users/zed" not in sent["text"] and sent["footer"] == [bridge.scrub(line) for line in footer]
    assert sent["text"].endswith("\n\n" + "\n".join(sent["footer"])), "the provider moves the footer by this suffix"
    assert message["footer"] == footer, "the caller's message is not changed"
    broken = bridge.scrub_message({**message, "footer": ["not the end of the text"]})
    assert "footer" not in broken, "a footer the text does not end with is not handed over"


def test_the_filter_keeps_a_quoted_path_runnable_and_touches_nothing_that_is_not_the_home_folder():
    home = "/Users/zed"
    from_env = bridge.home_folders
    try:
        bridge.home_folders = lambda: [home]
        assert bridge.scrub("python3 /Users/zed/co/runtime/cli.py approve --project '/Users/zed/my proj' --sha256 abc") == \
            "python3 ~/co/runtime/cli.py approve --project ~/'my proj' --sha256 abc"
        assert bridge.scrub("'/Users/zed'") == "~" and bridge.scrub("/Users/zed") == "~" and bridge.scrub("in /Users/zed.") == "in ~."
        assert bridge.scrub("/Users/zedx/y /tmp/Users/zed /opt/Users/zed/z a/Users/zed") == "/Users/zedx/y /tmp/Users/zed /opt/Users/zed/z a/Users/zed"
        assert bridge.scrub_message({"text": "/Users/zed/a", "actions": [{"id": "1", "label": "Approve"}], "link": {"label": "x", "url": "https://h.example/u"},
                                     "document": {"name": "n.txt", "text": "see /Users/zed/b"}}) == \
            {"text": "~/a", "actions": [{"id": "1", "label": "Approve"}], "link": {"label": "x", "url": "https://h.example/u"},
             "document": {"name": "n.txt", "text": "see ~/b"}}
        assert bridge.scrub(None) is None
    finally:
        bridge.home_folders = from_env
    assert bridge.home_folders() and all(not p.endswith("/") for p in bridge.home_folders())
