"""A line in the person's own words through the real messaging bridge (package NR-2): the stand-in Telegram provider, the real operations layer, the stand-in tree with
a stand-in router and answer skill. A tier-1 form is checked against the group of the operation it names and not against `talk` (a viewer who may read the
sources and may not talk is answered; a plain line is still refused), and a decision named in words is answered with its card sent again, the decision itself
untouched. Offline, no model, no network; every name and sender is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural.py
"""
from __future__ import annotations

import json
import shutil

import pytest

import standin_tree as st
from test_ask import accept
from test_messaging_ask import FIXTURE, wait_for
from test_ops_natural import KEY, OWNER, PROFILES, READER, SENDERS, docs, router_says, with_senders, world  # noqa: F401
from test_service import WAIT

ops = st.load("ops")
bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
phrases = st.load("phrases")


class Rig:
    pass


@pytest.fixture
def rig(docs, tmp_path, monkeypatch):
    root = tmp_path / "bench"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))
    accept(docs["path"], policies={**PROFILES, "viewer": ["read", "sources"]},
           messaging={"senders": {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": READER, "policy": "viewer"}]}})
    r = Rig()
    r.world, r.folder = docs, folder
    r.project = {"id": shell_kit.project_id(docs["path"]), "name": "northwind-shop", "path": docs["path"], "data_dir": str(docs["data"])}
    r.bridge = bridge.Bridge(ops, [r.project], providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(docs["data"]), "telegram"), "telegram",
                             [].append, clock=lambda: "2026-10-17T10:00:00+00:00")

    def sent():
        path = folder / "sent.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    r.sent = sent
    r.update = lambda sender, text: {"update_id": 1, "sender": sender, "chat": sender, "private": True, "text": text, "action": None, "action_ref": None,
                                     "reply_to": None}
    yield r
    r.bridge.stopping.set()
    for thread in list(r.bridge.threads):
        thread.join(WAIT)


def test_a_tier_1_form_is_checked_against_its_own_group_not_talk_and_a_plain_line_still_needs_talk(rig):
    rig.bridge.handle(rig.update(READER, "quais arquivos voce tem?"))
    assert wait_for(lambda: len(rig.sent()) == 1)
    [first] = rig.sent()
    assert first["chat"] == READER and first["message"]["text"].startswith("- lease-contract (file, ") and "meeting-notes" in first["message"]["text"]
    rig.bridge.handle(rig.update(READER, "Which market first?"))
    assert wait_for(lambda: len(rig.sent()) == 2)
    assert "not enabled for this channel" in rig.sent()[1]["message"]["text"]
    assert st.calls(rig.world["adapter"]) == [], "neither line ran a model"


def test_the_bridge_needs_for_a_tier_1_line_is_the_group_of_the_operation(rig):
    assert rig.bridge.needs("quais arquivos voce tem?") == "sources" and rig.bridge.needs("Which market first?") is None
    assert rig.bridge.needs("/ask qual o prazo?") == "ask" and rig.bridge.needs("aprova o plano 3") == "pending"


def test_a_decision_named_in_words_is_answered_and_its_card_goes_out_again_and_nothing_is_decided(rig):
    router_says(rig.world, "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: the market task.\n")
    rig.bridge.handle(rig.update(OWNER, "Which market first?"))
    assert wait_for(lambda: len(rig.sent()) == 1 and not rig.bridge.exclusive)      # the plan, as the reply to the line
    rig.bridge.notify_project(rig.project)                                         # and its card, as the bridge's tick sends it
    assert any(s["message"].get("actions") for s in rig.sent())
    cards = len([s for s in rig.sent() if s["message"].get("actions")])
    rig.bridge.handle(rig.update(OWNER, "aprova o plano 1"))
    assert wait_for(lambda: len([s for s in rig.sent() if s["message"].get("actions")]) == cards + 1)
    texts = [s["message"]["text"] for s in rig.sent()]
    assert phrases.text("NAT_DECISION_CARD", None, id=1) in texts
    assert ops.pending(rig.project["path"], 1)["status"] == "open"
    assert ops.status(rig.project["path"])["requests"][0]["state"] == "requested", "nothing was approved: the tasks were not made"
    assert rig.sent()[-1]["chat"] == OWNER
