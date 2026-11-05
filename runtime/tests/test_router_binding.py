"""The router's question is bound to the person it was asked of, for one hour (slice S4, decision 229 (1) of 2026-10-20; runtime/ops_say.py `_bound_question`,
`_open_question`, `_turn`, runtime/pending_items.py).

Over the REAL operations layer on the stand-in tree with a stand-in router and a stand-in clock for the age of a question. Every expectation is a literal of this file:
the delay of a line, who typed it, the sentence the answer is told with, the state of the old request. No model is called (the interpreter is not enabled for these
senders), and every name is invented.

  - the asker, ten minutes later: the line answers the question and says so;
  - another listed sender, ten minutes later: a new request; the question stays open and unanswered;
  - the asker, 61 minutes later: a new request, and nothing is cancelled by code (the old request is still `requested`, its question `open`);
  - a restart (the memory of the bindings is lost): the next line is new;
  - a page line after a messaging question: the page's own rule (the conversation's last request), unchanged;
  - two senders each asked: each answers only their own.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_router_binding.py
"""
from __future__ import annotations

import datetime

import pytest

import standin_tree as st
from test_ops_natural import FLOW, KEY, phone, router_says, say, with_senders, world  # noqa: F401  (the real-operations world fixture)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
pending_items = st.load("pending_items")
phrases = st.load("phrases")

TOKEN = "Zircon77"
QUESTION = ("Route: none (capability, pending)\n"
            "Why: the line names a warehouse and no stock that the project records\n"
            "Context: the person wrote a line about stock; the project has no stock source\n"
            "Requirements: integration:stock missing\n"
            "Sources: none\n"
            "Autonomy: ask first\n"
            "Assumptions: none\n"
            f"Next: Q1: Which {TOKEN} warehouse is meant? Recommended: the north one, because it is closer.\n"
            "Instructions found in external content: none\n")
FIRST = "preciso contar o estoque do armazem"       # validate: allow english-only -- a line the person types in Portuguese
ANSWER = "the north one, the shelf at the back"
OTHER = "tell me something else about the project today"
TAKEN = "I took that as the answer to question #{id}."


class Wall:
    """The clock of the age of a bound question, stood in; `at(item, seconds)` puts it `seconds` after the moment that decision was made."""

    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch

    def at(self, world, pending_id, seconds):
        ctx = ops_core.context(world["path"])
        made = datetime.datetime.fromisoformat(str(ctx["store"].pending_get(ctx["conn"], pending_id)["created_at"]).replace("Z", "+00:00"))
        moment = made + datetime.timedelta(seconds=seconds)
        self.monkeypatch.setattr(ops_say, "_question_clock", lambda: moment)


@pytest.fixture
def wall(monkeypatch):
    pending_items.clear()
    yield Wall(monkeypatch)
    pending_items.clear()


def open_questions(world):
    ctx = ops_core.context(world["path"])
    return [i["id"] for i in ctx["store"].pending_list(ctx["conn"], "open") if i["kind"] == "question"]


def request_states(world):
    ctx = ops_core.context(world["path"])
    return {t["id"]: t["state"] for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] is None}


def asked(world, who="owner"):
    """The sender `who` types a line on a phone and the router asks one question: its decision id and its request."""
    with_senders(world)
    router_says(world, QUESTION)
    out = phone(world, who, FIRST)
    assert out["pending_id"] is not None and TOKEN in out["reply"]
    return out["pending_id"], out["request_id"]


def outcome(world, wall, who, seconds, line=ANSWER):
    """What a plain line of `who`, `seconds` after the question was asked, was taken for: "answer" (the reply says so), or "new" (a request of its own; a reply that does not)."""
    pending_id, old = asked(world)
    router_says(world, FLOW)
    wall.at(world, pending_id, seconds)
    before = set(request_states(world))
    reply = phone(world, who, line)["reply"]
    if reply.startswith(TAKEN.format(id=pending_id)):
        return "answer"
    assert TAKEN.format(id=pending_id) not in reply
    assert len(set(request_states(world)) - before) == 1, "a new request was made"
    return "new"


# (who types, seconds after the question, what the line is taken for)
TABLE = [
    ("owner", 600, "answer"),
    ("owner", 3599, "answer"),
    ("plain", 600, "new"),
    ("owner", 3660, "new"),
]


@pytest.mark.parametrize("who,seconds,expected", TABLE)
def test_who_typed_and_how_long_after_decide_what_the_line_is_taken_for(world, wall, who, seconds, expected):
    assert outcome(world, wall, who, seconds) == expected


def test_a_line_taken_as_new_leaves_the_old_request_and_its_question_as_they_were(world, wall):
    """Decision 229 (1): nothing is cancelled by code when the hour runs out or another sender types."""
    for who, seconds in (("plain", 600), ("owner", 3660)):
        pending_items.clear()
        pending_id, old = asked(world)
        router_says(world, FLOW)
        wall.at(world, pending_id, seconds)
        phone(world, who, ANSWER)
        assert request_states(world)[old] == "requested" and pending_id in open_questions(world), (who, seconds)
        assert ops.pending(world["path"], pending_id)["status"] == "open"


def test_a_restart_loses_the_binding_and_the_next_line_is_new(world, wall):
    pending_id, old = asked(world)
    router_says(world, FLOW)
    wall.at(world, pending_id, 600)
    pending_items.clear()      # what a restart does: the memory of the bindings is gone
    reply = phone(world, "owner", ANSWER)["reply"]
    assert TAKEN.format(id=pending_id) not in reply and request_states(world)[old] == "requested" and pending_id in open_questions(world)


def test_a_page_line_after_a_messaging_question_follows_the_pages_own_rule(world, wall):
    """The page and the terminal keep the conversation's last request: the question asked on a phone is answered from the page, at any age."""
    pending_id, old = asked(world)
    router_says(world, FLOW)
    wall.at(world, pending_id, 3600 * 5)
    out = say(world, ANSWER, channel="page")
    assert TAKEN.format(id=pending_id) not in out["reply"], "no sentence of the phone on the page"
    assert pending_id not in open_questions(world) and ops.pending(world["path"], pending_id)["status"] != "open", "the page's line answered it"


def test_two_senders_each_asked_answer_only_their_own(world, wall):
    first, request_one = asked(world, "owner")
    router_says(world, QUESTION.replace(TOKEN, "Basalt19"))
    second_out = phone(world, "plain", FIRST)
    second, request_two = second_out["pending_id"], second_out["request_id"]
    assert second is not None and second != first and set(open_questions(world)) == {first, second}
    router_says(world, FLOW)
    wall.at(world, first, 600)
    mine = phone(world, "owner", ANSWER)["reply"]
    assert mine.startswith(TAKEN.format(id=first)) and TAKEN.format(id=second) not in mine
    assert second in open_questions(world) and first not in open_questions(world), "the other sender's question was not touched"
    theirs = phone(world, "plain", ANSWER)["reply"]
    assert theirs.startswith(TAKEN.format(id=second)) and open_questions(world) == []


def test_the_binding_is_read_by_the_key_of_the_sender_and_another_key_finds_none(world, wall):
    pending_id, old = asked(world)
    wall.at(world, pending_id, 60)
    assert ops_say._open_question(ops_core.context(world["path"]), "messaging", KEY["owner"]) == pending_id
    assert ops_say._open_question(ops_core.context(world["path"]), "messaging", KEY["reader"]) is None
    assert ops_say._open_question(ops_core.context(world["path"]), "messaging", None) is None


def test_vacuity_a_window_that_never_ends_fails_the_61_minute_row(world, wall, monkeypatch):
    """The table's last row says "new"; with the window patched to 10**9 the same row is "answer", so the table notices a window that does not close."""
    monkeypatch.setattr(pending_items, "ROUTER_WINDOW", 10 ** 9)
    assert outcome(world, wall, "owner", 3660) == "answer" != TABLE[3][2]


def test_vacuity_a_binding_that_ignores_the_sender_fails_the_other_sender_row(world, wall, monkeypatch):
    """A planted fault: the binding key drops the sender, so anybody's line answers. The row "plain, 600, new" must then fail."""
    real = ops_say._binding_key
    monkeypatch.setattr(ops_say, "_binding_key", lambda ctx, sender: real(ctx, "telegram:planted"))
    assert outcome(world, wall, "plain", 600) == "answer" != TABLE[2][2]


# --- the store -----------------------------------------------------------------------------------------------------------------------------------------


def test_the_store_keeps_one_binding_for_a_key_and_shows_no_words():
    pending_items.clear()
    one = pending_items.new_item("router", "p1", "messaging", "telegram:1", subject=["pending", 7], state={"request_id": 3, "asked_at": "2026-10-21T10:00:00+00:00"})
    two = pending_items.new_item("router", "p1", "messaging", "telegram:1", subject=["pending", 9], state={"request_id": 4, "asked_at": "2026-10-21T10:05:00+00:00"})
    other = pending_items.new_item("router", "p1", "messaging", "telegram:2", subject=["pending", 8], state={"request_id": 5, "asked_at": "2026-10-21T10:01:00+00:00"})
    assert pending_items.put(one) is None and pending_items.put(other) is None and pending_items.put(two) == one["id"]
    assert [i["id"] for i in pending_items.items(("p1", "messaging", "telegram:1"))] == [two["id"]]
    assert [i["id"] for i in pending_items.items(("p1", "messaging", "telegram:2"))] == [other["id"]]
    assert repr(two) == f"<item router {two['id']}>" and pending_items.count() == 2
    with pytest.raises(ValueError):
        pending_items.new_item("remind", "p1", "messaging", "telegram:1")
    pending_items.clear()
    assert pending_items.count() == 0


def test_the_store_is_bounded_and_the_oldest_goes_first():
    pending_items.clear()
    made = [pending_items.new_item("router", "p1", "messaging", f"telegram:{n}", subject=["pending", n], state={}) for n in range(5)]
    for item in made:
        pending_items.put(item, limit=3)
    assert pending_items.count() == 3
    assert [pending_items.items(("p1", "messaging", f"telegram:{n}")) != [] for n in range(5)] == [False, False, True, True, True]
    pending_items.clear()
