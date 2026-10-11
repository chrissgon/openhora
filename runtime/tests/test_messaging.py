"""Tests of the messaging bridge (runtime/messaging_*.py) over a stand-in operations object and a stand-in messenger
provider (runtime/tests/fixtures/messenger_standin.py, started through providers/resolve.py exactly as the real one is).
Offline: no network, no model. The channel rule and the policy against the real operations layer are in
test_messaging_policy.py; the shell is in test_messaging_shell.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import threading
import time

import pytest

import standin_tree as st
from test_service import Standin, WAIT

ops = st.load("ops")
operations = st.load("operations")
bridge = st.load("messaging_bridge")
cards = st.load("messaging_cards")
inbound = st.load("messaging_inbound")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")

FIXTURE = st.RUNTIME / "tests" / "fixtures" / "messenger_standin.py"
SENDER = "4242"
OPEN_POLICY = ["read", "talk", "answer", "release", "approve-plans", "approve-acceptances", "reject-cancel-retry"]
PLAN_HASH = "p" * 64
SECRET_TEXT = "Northwind shop launch plan, the private paragraph"


def decision(kind, number, title="Northwind shop", body=SECRET_TEXT, actions=None, **more):
    words = {"plan": ["approved", "rejected"], "acceptance": ["accepted", "rejected"], "effect": ["approved", "rejected"],
             "question": ["answered"], "review": ["answered", "released"]}[kind]
    item = {"id": number, "kind": kind, "title": title, "body": body, "status": "open", "task_id": 1, "payload": {},
            "actions": words if actions is None else actions, "created_at": "2026-10-11T10:00:00+00:00"}
    if kind == "plan":
        item["payload"] = {"plan_sha256": more.pop("plan_sha256", PLAN_HASH)}
    item.update(more)
    return item


class World:
    pass


class Fake(Standin):
    """The stand-in operations object, with a `config` that is a function of the test's state."""
    config_answer = None

    def config(self, project):
        with self.lock:
            self.calls.append(("config", project, {}))
        return self.config_answer(project)


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "bench"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    w = World()
    w.tmp, w.root, w.standin = tmp_path, root, folder
    w.items = {}
    w.fake = Fake(tmp_path / "data")
    w.config = {"messaging": {"senders": {"telegram": [SENDER]}, "notices": "text", "page_url": None},
                "channels": {"messaging": OPEN_POLICY}}
    w.fake.config_answer = lambda project: {"path": project, "sha256": "a" * 64, "accepted": True,
                                            "data_dir": str(tmp_path / "data"), **w.config}
    w.fake.answers["pending"] = lambda project, pending_id=None, **k: (
        w.items[pending_id] if pending_id is not None else {"pending": [dict(i) for i in w.items.values() if i["status"] == "open"]})
    w.fake.answers["say"] = {"reply": "Noted.", "request_id": 1, "pending_id": None, "ran": True, "queued": False}
    project = tmp_path / "northwind-shop"
    project.mkdir()
    w.projects = [{"id": shell_kit.project_id(str(project)), "name": "northwind-shop", "path": str(project),
                   "data_dir": str(tmp_path / "data")}]
    w.log = []
    w.make = lambda: bridge.Bridge(w.fake, w.projects, providers.Messenger("telegram", root=str(root)),
                                   ledgers.Ledger(str(tmp_path / "data"), "telegram"), "telegram", w.log.append,
                                   clock=lambda: "2026-10-11T10:00:00+00:00")
    w.bridge = w.make()

    def caps(**values):
        (folder / "caps.json").write_text(json.dumps(values))
        w.bridge.messenger._caps = None
    w.caps = caps

    def sent():
        path = folder / "sent.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    w.sent = sent
    w.texts = lambda: [s["message"]["text"] for s in sent()]
    w.cards = lambda: [s for s in sent() if s["message"]["actions"] or "·" in s["message"]["text"]]

    def say(text=None, action=None, **fields):
        update = {"update_id": 1, "sender": SENDER, "chat": SENDER, "private": True, "text": text, "action": action,
                  "action_ref": "ref-1" if action else None, "reply_to": None}
        update.update(fields)
        w.bridge.handle(update)
    w.say = say
    w.calls = lambda name: [c for c in w.fake.calls if c[0] == name]
    return w


def wait_for(condition, seconds=WAIT):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


# --- notices: the cards --------------------------------------------------------------------------------------------


def test_a_new_plan_gets_one_card_with_approve_and_reject_and_the_same_plan_gets_none_the_next_tick(world):
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    [card] = world.sent()
    message = card["message"]
    assert card["chat"] == SENDER and message["text"].startswith("northwind-shop · plan #1\n\n")
    assert SECRET_TEXT in message["text"]
    assert [a["label"] for a in message["actions"]] == ["Approve", "Reject"]
    assert all(len(a["id"].encode()) <= 64 for a in message["actions"])
    world.bridge.tick()
    assert len(world.sent()) == 1
    world.items[1] = decision("plan", 1, plan_sha256="q" * 64)  # the plan changed: a new card
    world.bridge.tick()
    assert len(world.sent()) == 2


def test_twelve_new_decisions_make_ten_cards_and_the_line_about_the_two_waiting(world):
    for number in range(1, 13):
        world.items[number] = decision("question", number, title=f"Q{number}")
    world.bridge.tick()
    sent = world.sent()
    assert len(sent) == 11 and sent[-1]["message"]["text"] == "And 2 more waiting. Send /pending to list them."
    assert all("· question #" in s["message"]["text"] for s in sent[:10])
    world.bridge.tick()  # the two left come now, one line is not repeated for the same number
    assert len(world.sent()) == 13


def test_notices_in_count_mode_carry_none_of_the_projects_text(world):
    world.config["messaging"]["notices"] = "count"
    world.items[1] = decision("plan", 1, title="Secret title", body="Secret body")
    world.items[2] = decision("question", 2, title="Another secret", body="Another body")
    world.bridge.tick()
    blob = json.dumps(world.sent())
    assert "Secret" not in blob and "secret" not in blob and "body" not in blob and SECRET_TEXT not in blob
    assert "A plan waits for you." in blob and "A question waits for you." in blob


def test_the_closed_default_policy_draws_no_action_and_says_where_to_act(world):
    del world.config["channels"]
    world.config["messaging"]["page_url"] = "https://page.example/open"
    world.items[1] = decision("plan", 1)
    world.items[2] = decision("question", 2)
    world.bridge.tick()
    plan, question = [s["message"] for s in world.sent()]
    assert plan["actions"] == [] and "/approve" not in plan["text"] and "Act on it on the page or in the terminal." in plan["text"]
    assert plan["link"] == {"label": "Open the page", "url": "https://page.example/open"}
    assert question["actions"] == [] and "Reply to this message to answer." in question["text"]
    assert "Act on it on the page" not in question["text"] and question["link"] is None


def test_without_buttons_the_actions_are_typed_lines_and_with_one_button_the_second_is_a_line(world):
    world.caps(buttons=False)
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    [first] = world.sent()
    assert first["message"]["actions"] == []
    assert "Send /approve 1" in first["message"]["text"] and "Send /reject 1" in first["message"]["text"]
    world.caps(buttons=True, max_buttons=1)
    world.items[2] = decision("plan", 2, plan_sha256="r" * 64)
    world.bridge.tick()
    second = world.sent()[-1]["message"]
    assert [a["label"] for a in second["actions"]] == ["Approve"] and "Send /reject 2" in second["text"]
    assert "Send /approve 2" not in second["text"]


def test_a_long_text_is_cut_with_a_line_about_the_page_or_sent_as_a_document(world):
    world.caps(max_text=300, documents=False)
    world.items[1] = decision("plan", 1, body="x" * 2000)
    world.bridge.tick()
    [cut] = world.sent()
    assert len(cut["message"]["text"]) <= 300 and cut["message"]["text"].rstrip().endswith("(continues on the page)")
    assert cut["message"]["document"] is None
    world.caps(max_text=300, documents=True)
    world.items[2] = decision("plan", 2, body="y" * 2000, plan_sha256="s" * 64)
    world.bridge.tick()
    doc = world.sent()[-1]["message"]
    assert len(doc["text"]) <= 300 and doc["document"]["text"].endswith("y" * 2000) and doc["document"]["name"] == "plan-2.txt"


def test_an_effect_card_has_no_approve_and_carries_the_exact_command_and_the_link(world):
    world.config["messaging"]["page_url"] = "https://page.example/open"
    world.items[7] = decision("effect", 7, title="Pull request", payload_sha256="e" * 64)
    world.bridge.tick()
    [card] = world.sent()
    message = card["message"]
    assert [a["label"] for a in message["actions"]] == ["Reject"]
    assert "Approve it on the page or in the terminal:" in message["text"]
    command = operations.command_line("approve", world.projects[0]["path"], checkout=bridge.ROOT, pending_id=7, sha256="e" * 64)
    assert message["text"].rstrip().endswith(command) and "e" * 64 in command
    assert message["link"]["url"] == "https://page.example/open"
    world.say("/approve 7")  # typed: no operation, the command again
    assert world.calls("approve") == [] and command in world.texts()[-1]


# --- the ledger -----------------------------------------------------------------------------------------------------


def test_the_ledger_is_0600_holds_no_project_text_and_survives_a_restart(world):
    world.items[1] = decision("plan", 1)
    world.items[2] = decision("question", 2)
    world.bridge.tick()
    path = world.tmp / "data" / "messaging-telegram.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    text = path.read_text()
    assert SECRET_TEXT not in text and "Northwind" not in text and PLAN_HASH in text
    again = world.make()
    again.tick()
    assert len(world.sent()) == 2  # no duplicate card after a restart
    world.items[3] = decision("question", 3)
    again.tick()
    assert len(world.sent()) == 3
    assert ledgers.Ledger(str(world.tmp / "data"), "telegram").offset == 0


# --- who may write ---------------------------------------------------------------------------------------------------


def test_an_unlisted_sender_and_a_group_chat_produce_no_operation_and_no_reply(world):
    world.say("hello", sender="999000111")
    world.say("hello", sender=SENDER, chat="-100777", private=False)
    world.say("/approve 1", sender="999000111", chat="999000111")
    world.say(None, action="1:approve", sender="999000111", chat="999000111")
    assert world.sent() == [] and world.fake.calls == [("config", world.projects[0]["path"], {})] * len(world.fake.calls)
    assert world.log and set(world.log) == {"dropped an update from an unlisted sender"}
    assert not any(secret in "".join(world.log) for secret in ("999000111", "100777", "hello", "approve"))


# --- taps and typed commands -----------------------------------------------------------------------------------------


def test_a_tapped_approve_runs_approve_with_the_ledger_hash_as_the_channel_messaging(world):
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    action = world.sent()[0]["message"]["actions"][0]["id"]
    world.fake.answers["approve"] = {"approved": True}
    world.say(None, action=action)
    [(_, _, kwargs)] = world.calls("approve")
    assert kwargs == {"pending_id": 1, "sha256": PLAN_HASH, "channel": "messaging"}
    assert world.standin.joinpath("acks.jsonl").read_text().strip() == json.dumps({"ref": "ref-1"})
    assert world.texts()[-1] == "Approved #1."


def test_a_stale_button_is_answered_and_a_changed_plan_is_refused_with_a_new_card(world):
    world.say(None, action="99:approve")
    assert world.texts() == ["This button is no longer valid. Send /pending."] and world.calls("approve") == []
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    action = world.sent()[-1]["message"]["actions"][0]["id"]
    world.items[1] = decision("plan", 1, plan_sha256="q" * 64)  # changed after its card
    world.fake.answers["approve"] = ops.OpsError(f"the plan's hash is {'q' * 64} and you typed {PLAN_HASH}: nothing was approved", 1)
    world.say(None, action=action)
    [(_, _, kwargs)] = world.calls("approve")
    assert kwargs["sha256"] == PLAN_HASH  # what the person saw, never the new hash
    assert "nothing was approved" in world.texts()[-2] or "nothing was approved" in world.texts()[-1]
    newest = world.sent()[-1]["message"]
    assert "plan #1" in newest["text"] and newest["actions"] and newest["actions"][0]["id"] != action


def test_an_acceptance_whose_content_changed_after_its_card_is_not_approved_and_a_new_card_is_sent(world):
    world.items[3] = decision("acceptance", 3, body="Accept 2 deliveries.")
    world.bridge.tick()
    action = world.sent()[0]["message"]["actions"][0]["id"]
    world.items[3] = decision("acceptance", 3, body="Accept 5 deliveries.")
    world.say(None, action=action)
    assert world.calls("approve") == []
    texts = world.texts()
    assert "This decision changed since you saw it." in texts and "Accept 5 deliveries." in texts[-1]
    fresh = world.sent()[-1]["message"]["actions"][0]["id"]
    world.fake.answers["approve"] = {"accepted": True}
    world.say(None, action=fresh)
    [(_, _, kwargs)] = world.calls("approve")
    assert kwargs == {"pending_id": 3, "channel": "messaging"}  # an acceptance has no hash


def test_typed_commands_are_bound_to_the_last_card_and_approve_needs_one(world):
    world.items[1] = decision("plan", 1)
    world.say("/approve 1")
    assert world.texts() == ["Send /pending first, so you see what you approve."] and world.calls("approve") == []
    world.bridge.tick()
    world.fake.answers["approve"] = {"approved": True}
    world.say("/approve 1")
    assert world.calls("approve")[0][2] == {"pending_id": 1, "sha256": PLAN_HASH, "channel": "messaging"}
    world.fake.answers["reject"] = {"rejected": True}
    world.say("/reject 1 not now")
    assert world.calls("reject")[0][2] == {"pending_id": 1, "note": "not now"}
    world.items[2] = decision("review", 2)
    world.fake.answers["release"] = {"released": True}
    world.say("/release 2")
    assert wait_for(lambda: world.calls("release")) and world.calls("release")[0][2] == {"pending_id": 2}
    assert wait_for(lambda: world.texts()[-1] == "Released #2.")
    world.say("/approve")
    assert world.texts()[-1] == "Usage: /approve <id>"


def test_the_closed_default_refuses_every_acting_command_in_the_bridge_and_calls_nothing(world):
    del world.config["channels"]
    world.items[1] = decision("plan", 1)
    world.items[2] = decision("review", 2)
    world.bridge.tick()
    for line in ("/approve 1", "/reject 1", "/release 2"):
        world.say(line)
        assert wait_for(lambda: "is not enabled for this channel" in world.texts()[-1]), line
        assert "(channels.messaging) turns it on" in world.texts()[-1]
    assert world.calls("approve") == world.calls("reject") == world.calls("release") == []
    world.say("/status")  # a typed command the bridge does not handle goes to say, where the operations layer decides
    assert wait_for(lambda: world.calls("say")) and world.calls("say")[0][2] == {"text": "/status", "channel": "messaging"}


def test_pending_lists_and_sends_the_cards_the_person_lacks(world):
    world.items[1] = decision("plan", 1, title="Plan one")
    world.say("/pending")
    texts = world.texts()
    assert texts[0] == "northwind-shop: #1 plan: Plan one" and "plan #1" in texts[1]
    world.items.clear()
    world.say("/pending")
    assert world.texts()[-1] == "northwind-shop: nothing waits for you."


# --- answers and free text --------------------------------------------------------------------------------------------


def test_a_reply_to_a_questions_card_answers_that_decision_and_free_text_goes_to_say(world):
    world.items[5] = decision("question", 5, title="Which market first?")
    world.bridge.tick()
    card_id = "101"
    assert world.sent()[0]["message"]["text"].endswith("Reply to this message to answer.")
    world.fake.answers["answer"] = {"answered": True}
    world.say("The home market.", reply_to=card_id)
    assert world.calls("answer")[0][2] == {"pending_id": 5, "text": "The home market."}
    world.say("Plan a launch for Northwind shop.")
    assert wait_for(lambda: world.calls("say"))
    assert world.calls("say")[0][2] == {"text": "Plan a launch for Northwind shop.", "channel": "messaging"}
    assert wait_for(lambda: world.texts()[-1] == "Noted.")
    world.say("/answer 5 Another way")
    assert world.calls("answer")[1][2] == {"pending_id": 5, "text": "Another way"}


def test_a_second_model_call_during_the_first_gets_still_working(world):
    entered, release = threading.Event(), threading.Event()

    def slow(project, text, channel):
        entered.set()
        release.wait(WAIT)
        return {"reply": "Done thinking.", "request_id": 1, "pending_id": None, "ran": True, "queued": False}
    world.fake.answers["say"] = slow
    world.say("first")
    assert entered.wait(WAIT)
    world.say("second")
    assert world.texts() == ["Still working on the last message."]
    release.set()
    assert wait_for(lambda: world.texts()[-1] == "Done thinking.")
    assert len(world.calls("say")) == 1


def test_a_run_in_progress_gets_its_sentence_and_every_reply_is_split_to_the_text_limit(world):
    world.fake.answers["say"] = ops.OpsError("another run of this project is in progress: one task at a time per project", 1)
    world.say("hello")
    assert wait_for(lambda: world.texts() and world.texts()[-1].startswith("error: another run"))
    world.fake.answers["say"] = {"reply": "w" * 9000}
    world.caps(max_text=4000)
    world.say("again")
    assert wait_for(lambda: len(world.sent()) >= 4)
    assert all(len(t) <= 4000 for t in world.texts()) and "".join(world.texts()[-3:]).count("w") == 9000


def test_an_unaccepted_configuration_refuses_every_operation_and_sends_no_notice(world):
    world.fake.config_answer = lambda project: {"path": "x", "sha256": "a" * 64, "accepted": False, "data_dir": str(world.tmp / "data")}
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    assert world.sent() == []
    world.say("hello")  # not even a listed sender: the senders are read only from an accepted file
    assert world.sent() == [] and world.calls("say") == []


def test_the_intents_of_a_line():
    parse = inbound.parse
    base = {"action": None, "reply_to": None}
    assert parse({**base, "text": "/approve 12"}) == {"kind": "approve", "id": 12}
    assert parse({**base, "text": "/approve@openhora_bot 12"}) == {"kind": "approve", "id": 12}
    assert parse({**base, "text": "/reject 3 too big"}) == {"kind": "reject", "id": 3, "note": "too big"}
    assert parse({**base, "text": "/answer 4"})["kind"] == "usage" and parse({**base, "text": "/release x"})["kind"] == "usage"
    assert parse({**base, "text": "/cancel 2"}) == {"kind": "text", "text": "/cancel 2"}
    assert parse({**base, "text": "hello", "reply_to": "9"}) == {"kind": "reply", "reply_to": "9", "text": "hello"}
    assert parse({**base, "text": None, "action": "7:approve"}) == {"kind": "action", "action": "7:approve"}
    assert parse({**base, "text": "  "})["kind"] == "ignore"
