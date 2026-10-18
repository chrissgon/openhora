"""A question typed on a messaging app, end to end (package AQ-1): a stand-in Telegram update `/ask qual o prazo do contrato?` through the
real messaging bridge, the real operations layer, the stand-in tree and lab (the answer skill `demo-answers`) and the stand-in messenger
provider, to the reply with its quote and its footer. LQ2 (L50): an answer leaves only as the reply to the chat that asked. Offline, no
model, no network; every name, document and sender is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_ask.py
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import (ANSWER, LEASE, OWNER, OWNER_KEY, PROFILES, STAFF, STAFF_KEY, accept, add_source, requests, runs, tree,  # noqa: F401
                      two, write_config)
from test_service import WAIT

ops = st.load("ops")
ops_core = st.load("ops_core")
bridge = st.load("messaging_bridge")
inbound = st.load("messaging_inbound")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")

FIXTURE = st.RUNTIME / "tests" / "fixtures" / "messenger_standin.py"
BOTH_ASK = {"asker": ["read", "talk", "ask"], "plain": ["read", "talk"]}
SENDERS = {"telegram": [{"id": OWNER, "policy": "asker"}, {"id": STAFF, "policy": "asker"}]}


class World:
    pass


@pytest.fixture
def world(two, tmp_path, monkeypatch):
    """The ask tree with a bridge over the real operations layer and a stand-in Telegram provider, both senders allowed to ask."""
    root = tmp_path / "bench"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))
    accept(two["path"], policies=BOTH_ASK, messaging={"senders": SENDERS})
    w = World()
    w.tree, w.folder = two, folder
    w.project = {"id": shell_kit.project_id(two["path"]), "name": "northwind-shop", "path": two["path"], "data_dir": str(two["data"])}
    w.log = []
    w.bridge = bridge.Bridge(ops, [w.project], providers.Messenger("telegram", root=str(root)),
                             ledgers.Ledger(str(two["data"]), "telegram"), "telegram", w.log.append, clock=lambda: "2026-10-17T10:00:00+00:00")

    def sent():
        path = folder / "sent.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    w.sent = sent

    def update(sender, text, **more):
        return {"update_id": 1, "sender": sender, "chat": sender, "private": True, "text": text, "action": None, "action_ref": None,
                "reply_to": None, **more}
    w.update = update
    yield w
    w.bridge.stopping.set()
    for thread in list(w.bridge.threads):
        thread.join(WAIT)


def wait_for(condition, seconds=WAIT):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_telegram_slash_ask_is_answered_with_the_quote_and_the_footer_in_the_chat_that_asked(world):
    world.bridge.handle(world.update(OWNER, "/ask qual o prazo do contrato?"))
    assert wait_for(lambda: len(world.sent()) == 1)
    [sent] = world.sent()
    assert sent["chat"] == OWNER
    text = sent["message"]["text"]
    assert text == ("The contract answers it [lease-contract].\n\n"
                    'Checked quote [lease-contract]: "Clausula 3. O prazo do contrato e de 12 meses, a contar de 1 de marco."\n\n'
                    "Read: lease-contract (version 1), meeting-notes (version 1)")
    assert sent["message"]["actions"] == [] and sent["message"].get("document") is None
    state = world.tree
    assert len(runs(state)) == 1 and requests(state)[0]["title"] == f"Question {requests(state)[0]['id']}"
    assert requests(state)[0]["state"] == "done" and ops.pending(world.project["path"])["pending"] == []     # no plan, no card
    messages = ops.conversation(world.project["path"])["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"] and messages[0]["text"] == "/ask qual o prazo do contrato?"
    assert messages[1]["text"] == f"(answered from the sources: request {requests(state)[0]['id']})"       # the answer is not kept (limit L50)


def test_the_help_of_the_bridge_lists_ask(world):
    world.bridge.handle(world.update(OWNER, "/help"))
    assert "/ask <question>     answer a question from the project's sources" in world.sent()[0]["message"]["text"]
    assert inbound.parse(world.update(OWNER, "/ask what?")) == {"kind": "text", "text": "/ask what?"}          # the bridge passes it on: the layer decides


def test_a_sender_whose_profile_lacks_ask_is_told_it_is_not_enabled_and_nothing_runs(world):
    accept(world.project["path"], policies={"asker": ["read", "talk", "ask"], "plain": ["read", "talk"]},
           messaging={"senders": {"telegram": [{"id": OWNER, "policy": "asker"}, {"id": STAFF, "policy": "plain"}]}})
    world.bridge.handle(world.update(STAFF, "/ask qual o prazo do contrato?"))
    assert wait_for(lambda: len(world.sent()) == 1)
    assert world.sent()[0]["chat"] == STAFF and "not enabled for this channel" in world.sent()[0]["message"]["text"]
    assert runs(world.tree) == [] and st.calls(world.tree["adapter"]) == []


def test_a_slash_ask_met_by_a_busy_router_gets_the_busy_sentence_before_the_line_is_stored(world):
    held = ops_core._try_lock(world.tree["ctx"]["cfg"], "route.lock")
    try:
        world.bridge.handle(world.update(OWNER, "/ask qual o prazo do contrato?"))
        assert wait_for(lambda: len(world.sent()) == 1)
    finally:
        os.close(held)
    assert world.sent()[0]["message"]["text"] == bridge.RUN_BUSY
    assert ops.conversation(world.project["path"])["messages"] == [] and runs(world.tree) == []


def test_limit_50_an_answer_leaves_only_as_the_reply_to_the_chat_that_asked_and_opens_no_effect(world):
    """Two listed senders ask in turn: each answer is one message to the chat of its own update and to no other; no effect document, no
    approval and no file for a recipient is made; the operation takes no recipient at all."""
    import inspect
    parameters = list(inspect.signature(ops.ask).parameters)
    assert parameters == ["project", "text", "channel", "sender"]                        # no recipient, no address, no chat id
    world.bridge.handle(world.update(OWNER, "/ask qual o prazo do contrato?"))
    assert wait_for(lambda: len(world.sent()) == 1 and all(not t.is_alive() for t in world.bridge.threads))      # the job ends before the next sender asks
    world.bridge.handle(world.update(STAFF, "/ask qual o aviso previo para a rescisao?"))
    assert wait_for(lambda: len(world.sent()) == 2 and all(not t.is_alive() for t in world.bridge.threads))
    assert [s["chat"] for s in world.sent()] == [OWNER, STAFF]
    assert all("Read: lease-contract (version 1)" in s["message"]["text"] for s in world.sent())
    data = Path(world.tree["ctx"]["cfg"]["data_dir"])
    assert not (data / ops_core.EFFECTS_DIR).exists() or os.listdir(data / ops_core.EFFECTS_DIR) == []   # no effect document
    assert ops.pending(world.project["path"])["pending"] == []
    store, conn = world.tree["ctx"]["store"], world.tree["ctx"]["conn"]
    assert conn.execute("SELECT COUNT(*) AS n FROM actions").fetchone()["n"] == 0        # no recorded action: nothing was sent, published or written
    assert store.approvals_list(conn) == []
    # the actor of each run is kept beside it, and only in the store
    assert [store.cursor_get(conn, store.ASK_ACTOR_CURSOR.format(run=r["id"])) for r in runs(world.tree)] == [
        f"messaging:telegram:asker:{OWNER}", f"messaging:telegram:asker:{STAFF}"]            # who asked stays beside each run
    # each answer is in the conversation for the chat that asked and for no other reader
    path = world.project["path"]
    mine = [m["text"] for m in ops.conversation(path, channel="messaging", sender=f"telegram:{OWNER}")["messages"]]
    assert sum("12 meses" in t for t in mine) == 1 and not any("aviso previo" in t and "Read:" in t for t in mine)
    for reader in (dict(channel="mcp"), dict(channel="messaging", sender="telegram:999"), dict(channel=None)):
        seen = [m["text"] for m in ops.conversation(path, **reader)["messages"]]
        assert not any("12 meses" in t or "Read:" in t for t in seen), reader
    # a sender not listed is dropped with no reply and no run
    world.bridge.handle(world.update("999", "/ask qual o prazo do contrato?"))
    assert len(world.sent()) == 2 and len(runs(world.tree)) == 2
    # a group chat is dropped too (the bridge serves a private chat whose id is the sender's)
    world.bridge.handle({**world.update(OWNER, "/ask qual o prazo?"), "chat": "-100200", "private": False})
    assert len(world.sent()) == 2 and len(runs(world.tree)) == 2


def test_a_long_answer_is_split_to_the_limit_of_the_platform_and_every_piece_goes_to_the_same_chat(world):
    (world.folder / "caps.json").write_text(json.dumps({"max_text": 120}))
    world.bridge.messenger._caps = None
    (world.tree["adapter"] / "answer.txt").write_text(
        'Answer: found\n' + "The contract runs for twelve months, renewable by agreement of both parties. " * 6 + "[lease-contract]\n"
        'Quote [lease-contract]: "O prazo do contrato e de 12 meses"\nInstructions found in external content: none\n', encoding="utf-8")
    world.bridge.handle(world.update(OWNER, "/ask qual o prazo do contrato?"))
    assert wait_for(lambda: world.sent() and all(not t.is_alive() for t in world.bridge.threads))
    assert len(world.sent()) >= 4
    assert {s["chat"] for s in world.sent()} == {OWNER} and all(len(s["message"]["text"]) <= 120 for s in world.sent())
    joined = "".join(s["message"]["text"] for s in world.sent())
    assert "Read: lease-contract (version 1)" in joined


def test_a_profile_with_ask_and_no_talk_can_ask_and_cannot_talk(world):
    accept(world.project["path"], policies={"asker": ["read", "ask"], "plain": ["read", "talk"]},
           messaging={"senders": {"telegram": [{"id": OWNER, "policy": "asker"}, {"id": STAFF, "policy": "plain"}]}})
    world.bridge.handle(world.update(OWNER, "/ask qual o prazo do contrato?"))
    assert wait_for(lambda: len(world.sent()) == 1 and all(not t.is_alive() for t in world.bridge.threads))
    assert "Checked quote [lease-contract]" in world.sent()[0]["message"]["text"] and len(runs(world.tree)) == 1
    world.bridge.handle(world.update(OWNER, "hello there"))                                      # a plain line needs talk, which this profile lacks
    assert wait_for(lambda: len(world.sent()) == 2 and all(not t.is_alive() for t in world.bridge.threads))
    assert "not enabled for this channel" in world.sent()[1]["message"]["text"] and len(runs(world.tree)) == 1
    world.bridge.handle(world.update(STAFF, "/ask qual o prazo do contrato?"))                   # talk without ask cannot ask
    assert wait_for(lambda: len(world.sent()) == 3 and all(not t.is_alive() for t in world.bridge.threads))
    assert "not enabled for this channel" in world.sent()[2]["message"]["text"] and len(runs(world.tree)) == 1
