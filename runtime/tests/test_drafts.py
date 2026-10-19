"""The one store of the questions a line leaves open (package NR-2, runtime/drafts.py): one draft for a channel and a sender, a new one replaces the old, an owner
sees only its own, a draft with a time to live is gone after it, the store is bounded, the bridge's view of it is a mapping from a chat to its draft, and nothing
of it is ever written to a file. Pure and offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_drafts.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

drafts = st.load("drafts")


@pytest.fixture(autouse=True)
def empty(monkeypatch):
    drafts.clear()
    now = {"t": 100.0}
    monkeypatch.setattr(drafts, "clock", lambda: now["t"])
    yield now
    drafts.clear()


def test_one_draft_for_a_channel_and_a_sender_and_a_new_question_replaces_the_old_one():
    drafts.put("messaging", "telegram:1", {"need": "confirm"}, "remind")
    drafts.put("messaging", "telegram:1", {"kind": "which"}, "ops")
    assert drafts.count() == 1 and drafts.get("messaging", "telegram:1") == {"kind": "which"}
    drafts.put("page", "", {"kind": "which"}, "ops")
    drafts.put("messaging", "telegram:2", {"need": "time"}, "remind")
    assert drafts.count() == 3 and drafts.get("messaging", "telegram:2") == {"need": "time"}


def test_an_owner_sees_and_takes_only_its_own_and_the_other_ones_stays():
    drafts.put("messaging", "telegram:1", {"need": "confirm"}, "remind")
    assert drafts.get("messaging", "telegram:1", "ops") is None and drafts.pop("messaging", "telegram:1", "ops") is None
    assert drafts.get("messaging", "telegram:1", "remind") == {"need": "confirm"}
    assert drafts.pop("messaging", "telegram:1", "remind") == {"need": "confirm"} and drafts.count() == 0
    with pytest.raises(ValueError):
        drafts.put("messaging", "telegram:1", {}, "someone")


def test_a_draft_with_a_time_to_live_is_gone_after_it_and_one_without_waits_for_its_owner_to_sweep_it(empty):
    drafts.put("messaging", "telegram:1", {"kind": "which"}, "ops", ttl=600)
    drafts.put("messaging", "telegram:2", {"need": "confirm"}, "remind")
    empty["t"] += 599
    assert drafts.get("messaging", "telegram:1") is not None
    empty["t"] += 2
    assert drafts.get("messaging", "telegram:1") is None and drafts.pop("messaging", "telegram:1") is None
    assert drafts.get("messaging", "telegram:2") == {"need": "confirm"}, "the bridge keeps its own clock and sweeps its own"


def test_the_store_is_bounded_and_the_oldest_goes_first():
    for n in range(drafts.MAX + 7):
        drafts.put("messaging", f"telegram:{n}", {"need": "confirm"}, "remind")
    assert drafts.count() == drafts.MAX and drafts.get("messaging", "telegram:0") is None and drafts.get("messaging", f"telegram:{drafts.MAX + 6}") is not None


def test_the_view_of_the_bridge_is_a_mapping_from_a_chat_to_its_draft_over_the_same_store():
    view = drafts.View("messaging", "remind", lambda chat: f"telegram:{chat}", lambda sender: sender[9:] if sender.startswith("telegram:") else None)
    assert view == {} and not view and len(view) == 0
    view["7"] = {"need": "confirm", "text": "x"}
    assert view == {"7": {"need": "confirm", "text": "x"}} and set(view) == {"7"} and view.keys() == {"7"} and "7" in view and "8" not in view
    assert drafts.get("messaging", "telegram:7", "remind") == {"need": "confirm", "text": "x"}, "one store"
    drafts.put("messaging", "telegram:9", {"kind": "which"}, "ops")
    drafts.put("messaging", "discord:5", {"need": "time"}, "remind")
    assert set(view) == {"7"}, "the view shows its owner's drafts, on its platform, and nothing else"
    assert view.get("9") is None and view.pop("7") == {"need": "confirm", "text": "x"} and view.pop("7", None) is None
    with pytest.raises(KeyError):
        view["7"]
    view["1"] = {"need": "time"}
    view.clear()
    assert dict(view) == {} and drafts.get("messaging", "telegram:9", "ops") is not None and drafts.get("messaging", "discord:5") is not None, "clear forgets its own"
