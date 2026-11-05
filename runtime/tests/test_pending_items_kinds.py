"""The store of open questions holds three kinds (package BL2a, runtime/pending_items.py): `router`, `plan-confirm` and `research-run`; a key holds one item of each kind, `put` replaces only the
same kind, and the router's lookups never meet an item of another kind. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_pending_items_kinds.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

pending_items = st.load("pending_items")
KEY = ("0123456789ab", "messaging", "telegram:55119000000099")


@pytest.fixture(autouse=True)
def empty():
    pending_items.clear()
    yield
    pending_items.clear()


def make(kind, **state):
    return pending_items.new_item(kind, *KEY, subject=["pending", 7] if kind == "router" else None, state=state)


def test_the_three_kinds_and_no_other():
    assert pending_items.KINDS == ("router", "plan-confirm", "research-run")
    with pytest.raises(ValueError):
        pending_items.new_item("draft", *KEY)


def test_put_replaces_only_an_item_of_the_same_kind_and_returns_its_id():
    router, plan, run = make("router", request_id=1, asked_at="x"), make("plan-confirm", op="items"), make("research-run", request_id=2)
    assert [pending_items.put(item) for item in (router, plan, run)] == [None, None, None] and pending_items.count() == 3
    newer = make("plan-confirm", op="status")
    assert pending_items.put(newer) == plan["id"] and pending_items.count() == 3
    assert pending_items.find(KEY, "plan-confirm")["state"] == {"op": "status"} and pending_items.find(KEY, "router") is router and pending_items.find(KEY, "research-run") is run


def test_find_pop_and_drop_key_by_kind():
    plan, run = make("plan-confirm", op="items"), make("research-run", request_id=2)
    pending_items.put(plan)
    pending_items.put(run)
    assert pending_items.find(KEY, "router") is None and pending_items.find(("other", "messaging", ""), "plan-confirm") is None
    assert pending_items.drop_key(KEY, "plan-confirm") == [plan["id"]] and pending_items.find(KEY, "plan-confirm") is None and pending_items.find(KEY, "research-run") is run
    assert pending_items.pop(run["id"]) is run and pending_items.pop(run["id"]) is None and pending_items.count() == 0
    pending_items.put(plan)
    pending_items.put(run)
    assert sorted(pending_items.drop_key(KEY)) == sorted([plan["id"], run["id"]]), "with no kind it drops every item of the key, as before"


def test_an_items_repr_shows_its_kind_and_id_only_whatever_its_state_holds():
    plan = make("plan-confirm", said="a line the person typed", words={"question": "a span"})
    assert repr(plan) == f"<item plan-confirm {plan['id']}>" and "typed" not in repr(plan) and "span" not in repr(plan)
