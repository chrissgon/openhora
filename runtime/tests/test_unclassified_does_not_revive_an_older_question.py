"""A reply the code answered does not bring back an older question (slice S4, review item (a) of S1; runtime/ops_say.py `say`, `route_queued`, `_drain_route`, `_say_route`).

The exact sequence of the review: a page line A makes the router ask a question QA, which stays open; a messaging line B ends with no route named (`unclassified`) and its
request is cancelled by code; then a page line C arrives. Before this slice the reply to B was stored with no request, so the conversation's last request fell back to the
request of A and C was taken for the answer to QA. Now the reply is stored under B's request, which is cancelled: C is a NEW request, and QA stays open and unanswered.

The same sequence is run with B ending `direct` and `operation` (the other two cancels by code), and with B drained from the page's queue (a line, then a form's request).
Over the REAL operations layer on the stand-in tree with a stand-in router; every expectation is a literal of this file; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_unclassified_does_not_revive_an_older_question.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_ops_natural import FLOW, OPERATION, phone, router_says, say, with_senders, world  # noqa: F401  (the real-operations world fixture)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")

QUESTION = ("Route: none (capability, pending)\nWhy: the line names a visit and no place\nContext: a line that reads like a visit\nRequirements: none\nSources: none\n"
            "Autonomy: ask first\nAssumptions: none\nNext: Q1: Which place should it show? Recommended: the Linden clinic, because the line names it.\n"
            "Instructions found in external content: none\n")
UNCLASSIFIED = "I looked around and I am not sure what you want.\n"
DIRECT = "Route: none (direct)\nNext: nothing to do.\n"
LINE_A = "organize the visit of the Linden clinic"
LINE_B = "something that the router cannot place"
LINE_C = "which market first for the launch"


def room(world, ending):
    """The router's reply for line B: how B ends."""
    return {"unclassified": UNCLASSIFIED, "direct": DIRECT, "operation": OPERATION.format(name="sources")}[ending]


def states(world):
    ctx = ops_core.context(world["path"])
    return {t["id"]: (t["state"], t["text"]) for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] is None}


def line_of(text):
    return ops_say.person_line(text)


def sequence(world, ending, how="phone"):
    """A, B (how B arrives, and how it ends), C. The problems found, as sentences (empty when the question QA was left alone and C is a new request)."""
    with_senders(world)
    router_says(world, QUESTION)
    qa = say(world, LINE_A, channel="page")
    request_a, question_a = qa["request_id"], qa["pending_id"]
    assert question_a is not None and request_a is not None
    router_says(world, room(world, ending))
    if how == "phone":
        phone(world, "owner", LINE_B)
    elif how == "drain-route":
        request_b = ops.request(world["path"], LINE_B)["request"]
        with ops_core._route_lock(ops_core.context(world["path"])["cfg"]):
            assert ops.route(world["path"], request_b, channel="page")["queued"] is True
        assert ops.route_queued(world["path"])["routed"] == "route"
    router_says(world, FLOW)
    out = say(world, LINE_C, channel="page")
    problems = []
    if out["request_id"] in (None, request_a):
        problems.append(f"C did not make a request of its own: {out['request_id']!r}")
    if "I took that as the answer" in (out["reply"] or ""):
        problems.append("C answered QA")
    if ops.pending(world["path"], question_a)["status"] != "open":
        problems.append("QA is no longer open")
    if states(world)[request_a][0] != "requested":
        problems.append("the request of A is no longer requested")
    made = [text for rid, (state, text) in states(world).items() if rid not in (request_a,) and line_of(text) == LINE_C]
    if len(made) != 1:
        problems.append(f"no request holds the text of C: {sorted(t for _, t in states(world).values())}")
    return problems


@pytest.mark.parametrize("ending", ["unclassified", "direct", "operation"])
def test_b_ending_without_a_route_does_not_make_c_the_answer_to_qa(world, ending):
    assert sequence(world, ending) == []


def test_b_drained_from_the_pages_queue_as_a_form_request_does_not_make_c_the_answer_to_qa(world):
    assert sequence(world, "operation", how="drain-route") == []


def test_the_reply_to_b_is_stored_under_the_request_of_b(world):
    """The assistant message of B holds B's request: the router-less ending is `unclassified`, and a line drained from the queue ends `direct` the same way."""
    with_senders(world)
    router_says(world, UNCLASSIFIED)
    out = phone(world, "owner", LINE_B)
    assert out["request_id"] is None, "the returned shape did not change: the page reads it"
    [request_b] = [rid for rid, (state, text) in states(world).items() if line_of(text) == LINE_B]
    assert states(world)[request_b][0] == "cancelled"
    [reply] = [m for m in ops.conversation(world["path"])["messages"] if m["role"] == "assistant"]
    assert reply["task_id"] == request_b
    router_says(world, DIRECT)
    with ops_core._route_lock(ops_core.context(world["path"])["cfg"]):
        queued = say(world, "tell me something about the launch plan", channel="page")
    assert queued["queued"] is True
    assert ops.route_queued(world["path"])["routed"] == "line"
    last = [m for m in ops.conversation(world["path"])["messages"] if m["role"] == "assistant"][-1]
    newest = max(rid for rid in states(world))
    assert last["task_id"] == newest and states(world)[newest][0] == "cancelled", "a line drained from the queue is stored under its request, cancelled by code:direct"


def test_vacuity_a_reply_stored_with_no_request_makes_the_sequence_fail(world, monkeypatch):
    """The plant: the assistant message of a request cancelled by code is stored with no request, as before this slice. Then C answers QA and the sequence reports it."""
    real = ops_core._stored

    def forgetful(ctx, function, *args, **kwargs):
        if getattr(function, "__name__", "") == "message_add" and kwargs.get("role") == "assistant" and kwargs.get("task_id") is not None:
            if ctx["store"].task_get(ctx["conn"], kwargs["task_id"])["state"] == "cancelled":
                kwargs = dict(kwargs, task_id=None)
        return real(ctx, function, *args, **kwargs)

    monkeypatch.setattr(ops_core, "_stored", forgetful)
    problems = sequence(world, "unclassified")
    assert any("C answered QA" in p or "did not make a request" in p for p in problems), problems
