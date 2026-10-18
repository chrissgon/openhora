"""The router's fifth outcome (package NR-2): `Route: none (operation)` with the name of an operation, its arguments and an optional normalised time, read by
code (runtime/router.py `read_route`) and believed against the person's line (runtime/natural.py `check_operation`). A reply with no Operation line reads as
before. The router skill does not emit the outcome yet (package NR-3 teaches it): these tests are the plumbing, with a stand-in router. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_router_operation.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_ops_natural import FLOW, OPERATION, router_says, world  # noqa: F401

router = st.load("router")
ops = st.load("ops")

LINE = "recuerdame manana a las 13 cortarme el pelo"
JAPANESE = "明日の13時に髪を切ると私に思い出させて"


def read(reply, said=LINE, **kw):
    return router.read_route(reply, said=said, **kw)


def test_an_operation_with_arguments_and_a_normalised_time_is_read_with_the_words_checked_against_the_line():
    got = read(OPERATION.format(name="remind") + "Argument text: cortarme el pelo\nWhen: 2026-10-19 13:00\n")
    assert got == {"kind": "operation", "name": "remind", "args": {"text": "cortarme el pelo"}, "when": "2026-10-19 13:00"}
    assert read(OPERATION.format(name="sources"), "tell me which sources you hold") == {"kind": "operation", "name": "sources", "args": {}, "when": None}
    got = read(OPERATION.format(name="remind") + "Argument text: 髪を切る\nWhen: 2026-10-19 13:00\n", JAPANESE)
    assert got["kind"] == "operation" and got["args"] == {"text": "髪を切る"}


def test_the_other_lines_of_a_route_reply_are_not_read_for_an_operation():
    reply = OPERATION.format(name="ask") + "Why: a question about a document\nSources: lease-contract\nLanguage: pt-BR\nNext: answer it.\n"
    assert read(reply, "o que diz meu CV sobre Vue?") == {"kind": "operation", "name": "ask", "args": {}, "when": None}


@pytest.mark.parametrize("reply, why", [
    (OPERATION.format(name="remind") + "Operation: sources\n", "2 Operation lines"),
    ("Route: none (operation)\n", "no Operation line"),
    ("Route: none (operation)\nRoute: none (operation)\nOperation: sources\n", "mixes"),
    ("Route: none (operation)\nRoute: flow-demo (flow, pending)\nOperation: sources\n", "mixes"),
    ("Route: none (operation)\nRoute: none (direct)\nOperation: sources\n", "mixes"),
    (OPERATION.format(name="delete-everything"), "not an operation a line may reach"),
    (OPERATION.format(name="say"), "planning agent's own work"),
    (OPERATION.format(name="remind") + "Argument color: red\n", "no argument 'color'"),
    (OPERATION.format(name="remind") + "Argument text: cortarme el pelo\nArgument text: cortarme el pelo\n", "two Argument lines"),
    (OPERATION.format(name="remind") + "Argument text: recordar al dentista\n", "not a span of the line"),
    (OPERATION.format(name="remind") + "Argument text: cortarme el pelo\nWhen: 2026-10-19\n", "not YYYY-MM-DD HH:MM"),
    (OPERATION.format(name="remind") + "Argument text: cortarme el pelo\nWhen: 2026-10-19 13:00\nWhen: 2026-10-19 14:00\n", "2 When lines"),
    (OPERATION.format(name="remind") + "Argument text: cortarme el pelo\nWhen: 2026-02-30 13:00\n", "not a date"),
    (OPERATION.format(name="sources") + "When: 2026-10-19 13:00\n", "takes no time"),
    (OPERATION.format(name="reminder-forget") + "Argument id: 7\n", "not a number written in the line"),
])
def test_a_reply_that_cannot_be_believed_is_unclassified_and_says_why(reply, why):
    got = read(reply)
    assert got["kind"] == "unclassified" and why in got["why"], got


def test_a_reply_that_names_an_operation_is_unclassified_when_no_line_is_given_as_for_one_of_several_deliveries():
    assert router.read_route(OPERATION.format(name="sources"))["kind"] == "unclassified"
    assert router.read_route(OPERATION.format(name="sources"), said="")["kind"] == "unclassified"


def test_a_question_still_wins_and_every_older_reply_reads_as_it_did():
    assert read(OPERATION.format(name="sources") + "Next: Q1: Which one? Recommended: this one.\n") == {"kind": "question"}
    assert router.read_route(FLOW)["kind"] == "route"
    assert router.read_route("Route: none (direct)\nNext: do it.\n") == {"kind": "direct", "next": "do it."}
    assert router.read_route("Route: none\nWhy: x\n")["kind"] == "unclassified"
    assert router.read_route("Operation: sources\n")["kind"] == "unclassified", "an Operation line with no operation route is prose"
    assert router.read_route(FLOW + "Operation: sources\n")["kind"] == "route", "a route reply is a route: the Operation line of it is not read"


def test_the_route_operation_of_a_request_returns_the_operation_and_executes_nothing(world):
    path = world["path"]
    router_says(world, OPERATION.format(name="sources"))
    request = ops.request(path, "tell me which sources you hold")["request"]
    routed = ops.route(path, request)
    assert routed["kind"] == "operation" and routed["routed"] is False and routed["operation"] == {"name": "sources", "args": {}, "when": None}
    assert routed["status"] == "ok" and routed["ending"] == "done" and routed["pending_id"] is None
    assert ops.status(path)["requests"][0]["state"] == "requested", "route only names it; the conversation executes it"
    assert ops.pending(path)["pending"] == []


def test_the_router_prompt_is_unchanged_until_package_nr_3_the_block_of_operations_is_not_appended_yet(world):
    path = world["path"]
    router_says(world, FLOW)
    ops.say(path, "Which market first?")
    prompt = (world["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8")
    assert "Operation" not in prompt and "operation" not in prompt.lower().replace("operations layer", "")


def test_a_request_of_several_deliveries_never_reads_an_operation(world):
    path = world["path"]
    router_says(world, OPERATION.format(name="sources"))
    request = ops.request(path, "Do these:\n- tell me which sources you hold\n- tell me which sources you keep")["request"]
    routed = ops.route(path, request)
    assert routed.get("kind") != "operation" and routed["routed"] is False
    assert ops.pending(path)["pending"][0]["kind"] == "question"
