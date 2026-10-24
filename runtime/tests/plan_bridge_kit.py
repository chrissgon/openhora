"""The rig of the tests of the OK of a plan on the messaging bridge (package BL2b, limits L64 and L65; `Bridge.plan_line`, `ask_plan`, `plan_tapped`, `research_stop_line`).

The real messaging bridge over the real operations layer: the world of test_plan_confirm_kit (the real-operations world of test_ops_natural.py, the model and the clock of a plan's age stood in)
and the stand-in messenger provider of test_messaging.py, started through providers/resolve.py as the real one is. `brig.say` is an update of the owner's private chat; `brig.texts()` is what
the stand-in messenger was sent; `brig.reads` are the calls of the one place a read runs. A line that starts a job (a say, a confirmed plan) replies from its thread: every result is read with
`wait_for`, never at once. Offline: no network, no model; every name, id and sender is invented.
"""
from __future__ import annotations

import json
import shutil
import time

import pytest

import standin_tree as st
from plan_confirm_kit import OWNER as OWNER_KEY, ops, ops_natural, phrases, plan_confirm, rig, spy_read, world  # noqa: F401
from test_messaging_ask import FIXTURE
from test_ops_natural import OWNER as OWNER_ID, READER as READER_ID, ASKER as ASKER_ID  # noqa: F401
from test_service import WAIT

bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")


def wait_for(condition, seconds=WAIT):
    """True when `condition()` held within `seconds` (a deadline: no wait of a test is unbounded)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


class Brig:
    pass


def build(world, tmp_path, monkeypatch):
    """The real bridge for `world` (a world of test_ops_natural.py: `path` and `data`), the stand-in messenger and the helpers below. The caller joins the bridge's threads (`finish`)."""
    root = tmp_path / "bench"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))
    b = Brig()
    b.folder, b.log, b.world = folder, [], world
    b.project = {"id": shell_kit.project_id(world["path"]), "name": "northwind-shop", "path": world["path"], "data_dir": str(world["data"])}
    b.bridge = bridge.Bridge(ops, [b.project], providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(world["data"]), "telegram"), "telegram", b.log.append,
                             clock=lambda: "2026-10-17T10:00:00+00:00")

    def caps(**values):
        (folder / "caps.json").write_text(json.dumps(values))
        b.bridge.messenger._caps = None
    b.caps = caps

    def sent():
        path = folder / "sent.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    b.sent = sent
    b.texts = lambda chat=OWNER_ID: [s["message"]["text"] for s in sent() if s["chat"] == chat]

    def say(text=None, sender=OWNER_ID, chat=None, **fields):
        update = {"update_id": 1, "sender": sender, "chat": chat if chat is not None else sender, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None}
        update.update(fields)
        b.bridge.handle(update)
    b.say = say

    def tap(action_id, sender=OWNER_ID):
        say(None, sender=sender, action=action_id, action_ref="ref-1")
    b.tap = tap

    def question_id(chat=OWNER_ID):
        """The platform's message id of the newest question sent to the chat (the ledger's record of kind plan-confirm), or None."""
        found = [c for c in b.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm" and c["chat"] == chat]
        return found[-1]["message_id"] if found else None
    b.question_id = question_id

    def question_actions(chat=OWNER_ID):
        found = [c for c in b.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm" and c["chat"] == chat]
        return {word: action for action, word in (found[-1]["actions"].items() if found else [])}
    b.question_actions = question_actions

    def ask(line="mostra minha agenda", sender=OWNER_ID):
        """A sender asks in words and the question reaches the chat: the number of messages sent when it is there."""
        def records():
            return [c for c in b.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm" and c["chat"] == sender]
        before = len(records())
        say(line, sender=sender)
        assert wait_for(lambda: len(records()) > before), "the question was sent and bound in the ledger"
        return len(b.sent())
    b.ask = ask
    b.idle = lambda: wait_for(lambda: not b.bridge.exclusive and all(not t.is_alive() for t in list(b.bridge.threads)))
    return b


def finish(b):
    b.bridge.stopping.set()
    for thread in list(b.bridge.threads):
        thread.join(WAIT)


@pytest.fixture
def brig(rig, tmp_path, monkeypatch):
    """The bridge for the world of `rig` (D5 on), the stand-in messenger, and the helpers of `build`; `brig.reads` are the calls of the one place a read runs."""
    b = build(rig.world, tmp_path, monkeypatch)
    b.rig = rig
    b.reads = spy_read(rig)
    yield b
    finish(b)


def question_text(rig, what_key, **fields):
    """The question as the operations layer writes it, by phrase key and values."""
    return phrases.text("PLAN_HEAD", rig.cfg, what=phrases.text(what_key, rig.cfg, **fields)) + " " + phrases.text("PLAN_ASK", rig.cfg)
