"""Tests of the MCP mode (runtime/mcp.py): the protocol's handshake, the tools read from the table of operations, the
channel rule (nothing is approved, rejected, cancelled or retried from here, as a tool or typed into say), the jobs, the errors and the standard output. A stand-in
operations object records every call, so a test sees exactly what the shell asked the operations layer; the tests that
need the real operations use the stand-in tree of standin_tree.py. The messages travel over in-process byte streams; the
one subprocess test starts the command with a stand-in operations module and checks what reaches its standard output.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mcp.py
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import standin_tree as st
from test_effects import gate_project, provider_calls, tree  # noqa: F401  (the effect fixture of test_effects.py)
from test_service import Standin, WAIT

mcp = st.load("mcp")
ops = st.load("ops")
operations = st.load("operations")
plans = st.load("plan")
service = st.load("service")

STANDARD_LIBRARY = {"__future__", "datetime", "hashlib", "io", "json", "os", "signal", "sys", "threading", "time", "traceback"}
SENTENCE = "an effect is approved in the terminal, with its hash"
INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "client", "version": "1"}}
STATUS = {"requests": [{"id": 1, "tasks": [{"id": 2, "state": "running"}]}], "pending": [{"id": 1}], "documents": []}


def rpc(method, params=None, ident=1):
    message = {"jsonrpc": "2.0", "method": method}
    if ident is not None:
        message["id"] = ident
    if params is not None:
        message["params"] = params
    return message


def lines(*messages) -> bytes:
    return b"".join((m if isinstance(m, bytes) else json.dumps(m).encode("utf-8")) + b"\n" for m in messages)


def talk(server, *messages, handshake=True) -> list:
    """The parsed answers to the messages, over an in-process pair; the handshake goes first unless told otherwise."""
    sent = ([rpc("initialize", INIT, 0), rpc("notifications/initialized", None, None)] if handshake else []) + list(messages)
    out = io.StringIO()
    mcp.serve_stream(server, io.BytesIO(lines(*sent)), out)
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    return answers[1:] if handshake else answers


def tool(server, name, arguments=None, ident=1):
    [answer] = talk(server, rpc("tools/call", {"name": name, "arguments": arguments or {}}, ident))
    return answer


def result_of(answer):
    assert "error" not in answer, answer
    [content] = answer["result"]["content"]
    assert content["type"] == "text" and answer["result"]["isError"] is False
    return json.loads(content["text"])


def refusal_of(answer):
    """The sentence of a tool result that is a refusal (isError true)."""
    assert "error" not in answer, answer
    [content] = answer["result"]["content"]
    assert content["type"] == "text" and answer["result"]["isError"] is True
    return content["text"]


@pytest.fixture
def world(tmp_path):
    fake = Standin(tmp_path / "data")
    fake.answers["status"] = STATUS
    projects = []
    for name in ("alpha", "beta"):
        folder = tmp_path / name
        folder.mkdir()
        projects.append({"id": mcp.project_id(str(folder)), "name": name, "path": str(folder)})
    lines_ = []
    server = mcp.Server(fake, projects[:1], log=lines_.append, grace=0.05)
    return type("World", (), {"server": server, "fake": fake, "projects": projects, "log": lines_, "tmp": tmp_path})


def two(world):
    """The same stand-in, serving both projects."""
    return mcp.Server(world.fake, world.projects, log=world.log.append, grace=0.05)


# --- the handshake ----------------------------------------------------------------------------------------------------


def test_the_handshake_negotiates_the_version_and_offers_the_tools_capability(world):
    out = io.StringIO()
    mcp.serve_stream(world.server, io.BytesIO(lines(rpc("initialize", INIT, "a"), rpc("notifications/initialized", None, None),
                                                    rpc("ping", None, 5))), out)
    first, second = [json.loads(line) for line in out.getvalue().splitlines()]
    assert first["jsonrpc"] == "2.0" and first["id"] == "a"
    found = first["result"]
    assert found["protocolVersion"] == "2025-06-18" and found["capabilities"] == {"tools": {"listChanged": False}}
    assert found["serverInfo"]["name"] and "terminal or on the local page" in found["instructions"]
    assert second == {"jsonrpc": "2.0", "id": 5, "result": {}}  # the notification got no answer
    older = talk(world.server, handshake=False, *[rpc("initialize", {**INIT, "protocolVersion": "2024-11-05"}, 1)])
    assert older[0]["result"]["protocolVersion"] == "2024-11-05"
    unknown = talk(world.server, handshake=False, *[rpc("initialize", {**INIT, "protocolVersion": "1999-01-01"}, 1)])
    assert unknown[0]["result"]["protocolVersion"] == mcp.PROTOCOLS[0]
    bad = talk(world.server, handshake=False, *[rpc("initialize", {"capabilities": {}}, 1)])
    assert bad[0]["error"]["code"] == -32602


def test_a_request_before_initialize_is_refused_but_ping_is_answered(world):
    first, second = talk(world.server, rpc("tools/list", None, 1), rpc("ping", None, 2), handshake=False)
    assert first["error"]["code"] == -32002 and second["result"] == {}
    assert world.fake.calls == []


def test_notifications_are_accepted_whatever_their_name_and_never_answered(world):
    out = talk(world.server, rpc("notifications/cancelled", {"requestId": 3}, None), rpc("notifications/anything", None, None),
               rpc("not/a/method", None, None), rpc("ping", None, 9))
    assert out == [{"jsonrpc": "2.0", "id": 9, "result": {}}]


# --- the tools --------------------------------------------------------------------------------------------------------


def test_the_tools_are_the_rows_of_the_table_that_list_the_mcp_channel_and_the_two_of_the_shell(world):
    [answer] = talk(world.server, rpc("tools/list", None, 7))
    names = [t["name"] for t in answer["result"]["tools"]]
    rows = [r["name"] for r in operations.OPERATIONS if "mcp" in r["channels"]]
    assert names == rows + ["projects", "job"] and answer["id"] == 7
    assert names == ["request", "route", "status", "task", "flows", "flow-check", "progress", "pending", "answer", "release", "say",
                     "agents", "conversation", "skills", "costs", "connections", "artifacts", "artifact", "version", "sources", "instructions", "routines", "projects", "job"]
    # what the table does not list for the channel has no tool: the decisions of the terminal and the page
    for never in ("accept-config", "run-next", "deps", "proof", "approve-policy", "revoke-policy", "standing",
                  "execute-under-policy", "contained-run", "poll", "handler", "pin", "stop-runs", "set-mode", "hand-over",
                  "verdict", "sync", "dispatch", "config", "approve", "reject", "cancel", "retry"):
        assert never not in names and "mcp" not in operations.by_name(never)["channels"], never
    by_name = {t["name"]: t for t in answer["result"]["tools"]}
    for row in operations.OPERATIONS:
        if "mcp" not in row["channels"]:
            continue
        schema = by_name[row["name"]]["inputSchema"]
        assert row["help"] in by_name[row["name"]]["description"] and schema["additionalProperties"] is False
        assert set(schema["properties"]) == {"project"} | {a["name"] for a in row["args"]}
        assert {a["name"] for a in row["args"] if a.get("required")} == set(schema["required"])
        assert ("tool job" in by_name[row["name"]]["description"]) == bool(row.get("job"))
    assert "channel" not in {p for t in by_name.values() for p in t["inputSchema"]["properties"]}  # a client names no channel
    assert by_name["answer"]["inputSchema"]["required"] == ["pending_id", "text"]
    assert "terminal or on the page" in by_name["say"]["description"] and "approve" not in names
    assert by_name["pending"]["inputSchema"]["properties"]["pending_id"] == {"type": "integer", "minimum": 0}


def test_with_two_projects_the_project_is_required_and_listed_in_the_schema(world):
    server = two(world)
    [answer] = talk(server, rpc("tools/list", None, 1))
    status = next(t for t in answer["result"]["tools"] if t["name"] == "status")["inputSchema"]
    assert status["required"] == ["project"] and status["properties"]["project"]["enum"] == [p["id"] for p in world.projects]
    missing = tool(server, "status")
    assert missing["error"]["code"] == -32602 and missing["error"]["data"] == {"error": "usage", "status": 400}
    nothing = tool(server, "status", {"project": "0" * 12})
    assert nothing["error"]["data"] == {"error": "not_found", "status": 404}
    assert result_of(tool(server, "status", {"project": world.projects[1]["id"]})) == STATUS
    assert world.fake.calls == [("status", world.projects[1]["path"], {})]


def test_every_read_tool_returns_what_the_operation_returned_with_the_arguments_it_was_given(world):
    cases = {
        "status": {}, "flows": {}, "agents": {}, "skills": {}, "connections": {}, "artifacts": {}, "version": {},
        "task": {"task_id": 4}, "progress": {"since": "7d"}, "pending": {"pending_id": 3},
        "conversation": {"conversation": "project", "after": 12}, "costs": {"since": "2026-10-01"},
        "artifact": {"path": "docs/business/icp.md"},
    }
    path = world.projects[0]["path"]
    for name, arguments in cases.items():
        world.fake.answers[name] = {"answer": name, "text": "line one\nline two with a   separator"}
        before = len(world.fake.calls)
        found = result_of(tool(world.server, name, arguments))
        assert found == {"answer": name, "text": "line one\nline two with a   separator"}, name
        expected = {**arguments, "channel": "mcp"} if name in ("conversation", "task", "pending") else arguments      # the answer to a /ask is shown by the channel that reads (L50); a calendar card's current text is not for the MCP mode (W1)
        assert world.fake.calls[before:] == [(operations.by_name(name)["call"], path, expected)], name
    # an optional argument that was left out is not passed
    world.fake.calls.clear()
    result_of(tool(world.server, "pending"))
    assert world.fake.calls == [("pending", path, {"channel": "mcp"})]


def test_the_text_of_a_project_is_returned_as_text_and_never_as_a_line_of_the_protocol(world):
    hostile = '{"jsonrpc":"2.0","id":99,"method":"tools/call"}\n{"jsonrpc":"2.0","id":98,"result":{}} x'
    world.fake.answers["artifact"] = {"path": "docs/x.md", "text": hostile}
    out = io.StringIO()
    mcp.serve_stream(world.server, io.BytesIO(lines(rpc("initialize", INIT, 0), rpc("tools/call", {"name": "artifact", "arguments": {
        "path": "docs/x.md"}}, 1))), out)
    written = out.getvalue()
    assert len(written.splitlines()) == 2 and written.isascii()  # one line per message, whatever the document held
    last = json.loads(written.splitlines()[1])
    assert json.loads(last["result"]["content"][0]["text"])["text"] == hostile and last["id"] == 1
    assert [c[0] for c in world.fake.calls] == ["artifact"]  # nothing in the text was run as a request


def test_request_route_answer_release_and_say_go_through_the_operations_layer(world):
    path = world.projects[0]["path"]
    world.fake.answers["request"] = {"request_id": 5}
    assert result_of(tool(world.server, "request", {"text": "make a plan", "flow": "demo", "title": "T"})) == {"request_id": 5}
    assert result_of(tool(world.server, "answer", {"pending_id": 2, "text": "yes", "with_comments": True})) == \
        {"op": "answer_proposing", "args": {"pending_id": 2, "text": "yes", "with_comments": True, "channel": "mcp"}}
    for name, arguments in (("route", {"request_id": 5, "flow": "demo"}), ("release", {"pending_id": 2}), ("say", {"text": "hello"})):
        started = result_of(tool(world.server, name, arguments))
        assert started["op"] == name and started["project"] == world.projects[0]["id"]
        assert started["state"] in ("running", "done")
    deadline = time.monotonic() + WAIT
    while len(world.fake.calls) < 5 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert world.fake.calls[0] == ("request", path, {"text": "make a plan", "flow": "demo", "title": "T"})
    assert world.fake.calls[1] == ("answer_proposing", path, {"pending_id": 2, "text": "yes", "with_comments": True, "channel": "mcp"})
    assert sorted(c[0] for c in world.fake.calls[2:]) == ["release", "route", "say"]
    assert {c[0]: c[2] for c in world.fake.calls[2:]} == {"route": {"request_id": 5, "flow": "demo", "channel": "mcp"}, "release": {"pending_id": 2, "channel": "mcp"},
                                                          "say": {"text": "hello", "channel": "mcp"}}
    for name in ("request", "route", "answer", "release", "say"):
        assert "mcp" in operations.by_name(name)["channels"], name
    for name in ("approve", "reject", "cancel", "retry"):
        assert "mcp" not in operations.by_name(name)["channels"], name


def test_a_bad_argument_is_an_invalid_parameter_and_calls_nothing(world):
    for name, arguments in (("pending", {"pending_id": "3"}), ("pending", {"pending_id": -1}), ("pending", {"pending_id": True}),
                            ("pending", {"channel": "terminal"}), ("answer", {"pending_id": 1}), ("answer", {"text": "x"}),
                            ("request", {"text": 5}), ("status", {"unknown": 1}), ("answer", {"pending_id": 1, "text": "x",
                                                                                               "with_comments": "yes"}),
                            ("projects", {"x": 1}), ("job", {}), ("job", {"job": "1"}), ("job", {"job": 1, "x": 2})):
        answer = tool(world.server, name, arguments)
        assert answer["error"]["code"] == -32602 and answer["error"]["data"]["status"] == 400, (name, arguments)
    unknown = tool(world.server, "run-next")
    assert unknown["error"]["code"] == -32602 and unknown["error"]["data"] == {"error": "not_found", "status": 404}
    assert tool(world.server, "accept-config", {"sha256": "ab"})["error"]["code"] == -32602
    [odd] = talk(world.server, rpc("tools/call", {"name": 5}, 3))
    assert odd["error"]["code"] == -32602
    [shape] = talk(world.server, rpc("tools/call", {"name": "status", "arguments": [1]}, 4))
    assert shape["error"]["code"] == -32602
    assert world.fake.calls == []


def test_a_refusal_is_a_tool_result_and_the_rest_is_the_protocols_error_with_the_services_word_and_status(world):
    for code, sentence in ((1, "text 1"), (3, "text 3")):
        world.fake.answers["status"] = ops.OpsError(sentence, code)
        assert refusal_of(tool(world.server, "status")) == sentence
    world.fake.answers["status"] = ops.OpsError("text 2", 2)
    answer = tool(world.server, "status")
    assert answer["error"] == {"code": -32602, "message": "text 2", "data": {"error": "usage", "status": 400}}
    world.fake.answers["status"] = RuntimeError("secret detail at /private/path")
    answer = tool(world.server, "status")
    assert answer["error"]["code"] == -32603 and answer["error"]["data"] == {"error": "internal", "status": 500}
    assert "secret detail" not in json.dumps(answer) and any("secret detail" in line for line in world.log)


# --- the channel rule -------------------------------------------------------------------------------------------------


def test_nothing_is_approved_rejected_cancelled_or_retried_from_here_as_a_tool_or_typed_into_say(tree, monkeypatch):  # noqa: F811
    monkeypatch.setattr(plans, "resolve_pack", lambda pack, root: ["demo-code", "demo-gate"])
    case = gate_project(tree)
    path, effect = case["path"], case["item"]
    assert effect["kind"] == "effect"
    request = ops.request(path, "Invented request.", title="Invented")["request"]
    plan_id = ops.route(path, request, "gate-demo")["pending_id"]
    plan = ops.pending(path, plan_id)
    assert plan["kind"] == "plan"
    projects = [{"id": mcp.project_id(path), "name": "p", "path": path}]
    server = mcp.Server(ops, projects, log=lambda line: None, grace=WAIT)
    hash_ = effect["payload_sha256"]
    before = (ops.status(path), ops.pending(path))
    # there is no tool for any of them, and a request cannot name a channel on the tool that has one
    for name in ("approve", "reject", "retry", "cancel"):
        assert tool(server, name, {"pending_id": plan_id})["error"]["code"] == -32602
    assert tool(server, "say", {"text": "x", "channel": "terminal"})["error"]["code"] == -32602
    # typed into say, in every form: the channel mcp does not list the command, and nothing is done
    commands = {"approve": [f"/approve {plan_id} {plan['payload']['plan_sha256']}", f"/approve {plan_id}",
                            f"/approve {effect['id']} {hash_}", f"/approve {effect['id']}"],
                "reject": [f"/reject {plan_id}", f"/reject {effect['id']} no", f"/reject {plan_id} with a reason"],
                "retry": ["/retry 2", "/retry 3"], "cancel": [f"/cancel {request}"]}
    for command, forms in commands.items():
        for form in forms:
            for prefix in ("", " ", "  ", "\x00", "\x00 ", "\t", "\n", "\r\n", "\x1b", " \x07 "):
                said = result_of(tool(server, "say", {"text": prefix + form}))
                deadline = time.monotonic() + WAIT
                while said["state"] == "running" and time.monotonic() < deadline:
                    said = result_of(tool(server, "job", {"job": said["job"]}))
                assert said["state"] == "done" and said["result"]["reply"] == \
                    f"error: /{command} is done in the terminal or on the page", (prefix, form)
                assert said["result"]["ran"] is False and said["result"]["request_id"] is None
    assert (ops.status(path), ops.pending(path)) == before
    assert provider_calls(tree) == [] and ops.pending(path, effect["id"])["status"] == "open"
    assert ops.pending(path, plan_id)["status"] == "open"
    # what the channel lists still works through say: a read, and the help
    shown = result_of(tool(server, "say", {"text": "/pending"}))
    deadline = time.monotonic() + WAIT
    while shown["state"] == "running" and time.monotonic() < deadline:
        shown = result_of(tool(server, "job", {"job": shown["job"]}))
    assert shown["result"]["reply"].lstrip().startswith("{") and str(plan_id) in shown["result"]["reply"]
    # the terminal and the page still approve a plan through say, and the conversation's own shell too
    for channel in ("terminal", "page", None):
        if channel is not None:
            second = ops.route(path, ops.request(path, "Another.", title="Another")["request"], "gate-demo")["pending_id"]
            hash2 = ops.pending(path, second)["payload"]["plan_sha256"]
            ops.say(path, f"/approve {second} {hash2}", channel=channel)
            assert ops.pending(path, second)["status"] == "resolved", channel
    # an effect is still refused for them by the rule of ops.approve: a line is the conversation's channel
    said = ops.say(path, f"/approve {effect['id']} {hash_}", channel="terminal")["reply"]
    assert said.startswith("error: " + SENTENCE) and provider_calls(tree) == []


def test_say_is_called_as_the_channel_mcp_and_the_client_cannot_change_it(world):
    deadline = time.monotonic() + WAIT
    result_of(tool(world.server, "say", {"text": "hello"}))
    while not world.fake.named("say") and time.monotonic() < deadline:
        time.sleep(0.01)
    [(_, _, kwargs)] = world.fake.named("say")
    assert kwargs == {"text": "hello", "channel": "mcp"}
    assert "mcp" not in ops.EFFECT_CHANNELS  # the rule of the operations layer, which this shell does not restate
    assert [r["name"] for r in operations.OPERATIONS if r.get("channel_arg")] == ["route", "task", "pending", "answer", "release", "approve", "reject", "retry", "cancel", "stop-task", "set-mode", "set-model", "give-consent", "dispatch", "say", "ask", "conversation", "source-add", "attachments", "items", "attachment-hold", "attachment-add", "attachment-discard", "remind", "reminders", "reminder-forget", "reminder-restore", "file-create", "file-replace", "file-save", "file-trash", "file-read", "research", "instructions-set",
                                                                                         "instructions-add", "routine-create", "routine-change", "routine-pause", "event-create", "event-change", "event-cancel", "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash"]
    assert "mcp" not in operations.by_name("approve")["channels"]
    # set-mode takes the channel (R4-C3) to refuse `accept` from any but the terminal; it has no tool and no chat command
    assert "mcp" not in operations.by_name("set-mode")["channels"] and "chat" not in operations.by_name("set-mode")["channels"]
    # the page's consent (give-consent, D38) is the page's alone: no tool, no chat command, no messaging
    assert operations.by_name("give-consent")["channels"] == ("page",)
    # `dispatch` takes the channel to know whether the shell can wait for the runs it starts (the page cannot); the MCP mode has no tool for it
    assert "mcp" not in operations.by_name("dispatch")["channels"]
    # `route` takes the channel only to know whether the shell drains the queue (A-23): the MCP mode does not
    assert operations.by_name("route")["queues"] is True and "queues" not in operations.by_name("approve")


# --- the jobs ---------------------------------------------------------------------------------------------------------


def test_a_job_tool_returns_a_job_at_once_and_the_tool_job_polls_it(world):
    entered, release = threading.Event(), threading.Event()

    def route(project, **kwargs):
        entered.set()
        assert release.wait(WAIT)
        return {"routed": kwargs["request_id"]}

    world.fake.answers["route"] = route
    started = result_of(tool(world.server, "route", {"request_id": 9}))
    assert entered.wait(WAIT)
    assert started["state"] == "running" and started["op"] == "route" and started["result"] is None and started["error"] is None
    assert started["poll"] == {"tool": "job", "arguments": {"job": started["job"]}}
    assert started["project"] == world.projects[0]["id"]
    again = result_of(tool(world.server, "job", started["poll"]["arguments"]))
    assert again["state"] == "running" and again["job"] == started["job"]
    release.set()
    deadline = time.monotonic() + WAIT
    while again["state"] == "running" and time.monotonic() < deadline:
        again = result_of(tool(world.server, "job", {"job": started["job"]}))
        time.sleep(0.01)
    assert again["state"] == "done" and again["result"] == {"routed": 9} and again["ended_at"] and "poll" not in again
    assert tool(world.server, "job", {"job": 999})["error"]["data"] == {"error": "not_found", "status": 404}


def test_a_job_that_ends_at_once_is_returned_ended_and_a_failure_is_the_error(world):
    done = result_of(tool(world.server, "release", {"pending_id": 1}))
    assert done["state"] == "done" and done["result"]["op"] == "release"
    world.fake.answers["release"] = ops.OpsError("nothing to release", 1)
    assert refusal_of(tool(world.server, "release", {"pending_id": 1})) == "nothing to release"
    world.fake.answers["release"] = KeyError("boom at /private/path")
    crashed = tool(world.server, "release", {"pending_id": 1})
    assert crashed["error"]["data"] == {"error": "internal", "status": 500} and "boom" not in json.dumps(crashed)
    [job] = [j for j in world.server.jobs.values() if j["error"] and j["error"]["error"] == "internal"]
    assert job["state"] == "failed"


def test_a_second_job_that_calls_a_model_waits_for_the_first(world):
    entered, release = threading.Event(), threading.Event()

    def say(project, **kwargs):
        entered.set()
        assert release.wait(WAIT)
        return {"reply": "ok"}

    world.fake.answers["say"] = say
    first = result_of(tool(world.server, "say", {"text": "one"}))
    assert entered.wait(WAIT)
    busy = tool(world.server, "say", {"text": "two"})
    assert "job" in refusal_of(busy) and "is running for this project" in refusal_of(busy)
    assert [c[2]["text"] for c in world.fake.named("say")] == ["one"]
    release.set()
    deadline = time.monotonic() + WAIT
    while world.server.jobs[first["job"]]["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert result_of(tool(world.server, "say", {"text": "three"}))["op"] == "say"


# --- errors of the protocol -------------------------------------------------------------------------------------------


def test_malformed_messages_get_the_protocols_error_and_the_server_goes_on(world):
    out = io.StringIO()
    big = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + b"a" * (mcp.LINE_LIMIT + 10) + b'"}}\n'
    sent = (b"this is not json\n" + b'{"jsonrpc":"2.0","id":1,\n' + b"\xff\xfe\n" + b"\n" + b"   \n" + b"[]\n" + b"5\n" + b'"text"\n'
            + b'{"id":2,"method":"ping"}\n' + b'{"jsonrpc":"1.0","id":3,"method":"ping"}\n'
            + b'{"jsonrpc":"2.0","id":true,"method":"ping"}\n' + b'{"jsonrpc":"2.0","id":[1],"method":"ping"}\n'
            + b'{"jsonrpc":"2.0","id":4,"method":5}\n' + b'{"jsonrpc":"2.0","id":5}\n'
            + big + lines(rpc("initialize", INIT, 6)) + b'{"jsonrpc":"2.0","id":7,"method":"resources/list"}\n'
            + b'{"jsonrpc":"2.0","id":8,"method":"tools/list","params":5}\n'
            + b'{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"arguments":{}}}\n'
            + b'{"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"status","x":1}}\n'
            + b'{"jsonrpc":"2.0","id":11,"result":{}}\n' + lines(rpc("ping", None, 12)))
    mcp.serve_stream(world.server, io.BytesIO(sent), out)
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    codes = [(a.get("id"), a["error"]["code"] if "error" in a else "ok") for a in answers]
    assert codes == [
        (None, -32700), (None, -32700), (None, -32700),            # three lines that are not JSON
        (None, -32600), (None, -32600), (None, -32600),            # [] , 5, "text"
        (None, -32600), (None, -32600), (None, -32600), (None, -32600),  # no jsonrpc, wrong version, id true, id a list
        (4, -32600), (5, -32600),                                  # method 5, no method
        (None, -32600),                                            # a line over the limit
        (6, "ok"), (7, -32601), (8, -32602), (9, -32602), (10, -32602), (12, "ok")]
    assert all(a["jsonrpc"] == "2.0" and ("result" in a) != ("error" in a) for a in answers)
    assert world.fake.calls == []


def test_a_batch_is_answered_as_a_list_and_only_for_its_requests(world):
    out = io.StringIO()
    mcp.serve_stream(world.server, io.BytesIO(lines(rpc("initialize", INIT, 0), [rpc("ping", None, 1), rpc("notifications/x", None, None),
                                                                                  rpc("nope", None, 2)], [rpc("notifications/y", None, None)])), out)
    first, batch = [json.loads(line) for line in out.getvalue().splitlines()]
    assert first["id"] == 0 and [a["id"] for a in batch] == [1, 2] and batch[1]["error"]["code"] == -32601


def test_the_end_of_the_input_ends_the_loop(world):
    out = io.StringIO()
    mcp.serve_stream(world.server, io.BytesIO(b""), out)
    assert out.getvalue() == ""


# --- standard output carries only the protocol ------------------------------------------------------------------------


def test_the_log_goes_to_standard_error_and_holds_no_argument_result_or_secret(world, capsys):
    secret = "sk-test-0123456789abcdef"
    world.fake.answers["say"] = {"reply": secret}
    server = mcp.Server(world.fake, world.projects[:1], grace=0.05)  # the default log: standard error
    tool(server, "request", {"text": "an argument that is private"})
    tool(server, "say", {"text": "another private text"})
    tool(server, "status")
    seen = capsys.readouterr()
    assert seen.out == "" and "tools/call request ok" in seen.err and "tools/call say ok" in seen.err
    assert "private" not in seen.err and secret not in seen.err
    bad = tool(server, "not-a-tool-" + "x" * 300)
    assert "x" * 50 not in capsys.readouterr().err and bad["error"]["code"] == -32602


def test_the_command_writes_only_messages_to_its_standard_output(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f'''
        import os, subprocess, sys
        sys.path.insert(0, {str(st.RUNTIME)!r})
        import mcp, operations

        class Fake:
            OpsError = type("OpsError", (Exception,), {{"code": 1}})
            operations = operations
            def config(self, project):
                print("NOISE from config")
                return {{"path": project, "sha256": "a" * 64, "accepted": True, "data_dir": project}}
            def status(self, project):
                print("NOISE from status")
                subprocess.run(["echo", "NOISE from a child"])
                subprocess.run(["echo", "NOISE from a program"])
                sys.stdout.write("NOISE written")
                return {{"requests": [], "pending": []}}
            def stop_runs(self):
                return {{}}

        mcp.ops = Fake()
        sys.exit(mcp.main(["--project", {str(folder)!r}]))
    '''), encoding="utf-8")
    sent = lines(rpc("initialize", INIT, 0), rpc("notifications/initialized", None, None),
                 rpc("tools/call", {"name": "status", "arguments": {}}, 1))
    ran = subprocess.run([sys.executable, str(driver)], input=sent, capture_output=True, timeout=60)
    assert ran.returncode == 0
    out = ran.stdout.decode("utf-8")
    answers = [json.loads(line) for line in out.splitlines()]
    assert [a["id"] for a in answers] == [0, 1] and "NOISE" not in out
    assert json.loads(answers[1]["result"]["content"][0]["text"]) == {"requests": [], "pending": []}
    assert ran.stderr.decode("utf-8").count("NOISE") == 5 and "serving 1 project(s)" in ran.stderr.decode("utf-8")


def test_the_command_line_and_its_exit_codes(tmp_path):
    run = lambda *argv: subprocess.run([sys.executable, str(st.RUNTIME / "mcp.py"), *argv], input=b"", capture_output=True,  # noqa: E731
                                       timeout=60)
    helped = run("--help")
    assert helped.returncode == 0 and b"Usage:" in helped.stdout and helped.stderr == b""
    none = run()
    assert none.returncode == 2 and none.stdout == b"" and b"Usage:" in none.stderr
    for argv in (("--port", "1"), ("--project",), ("--token-file", "x", "--project", str(tmp_path))):
        refused = run(*argv)
        assert refused.returncode == 2 and refused.stdout == b"" and b"error:" in refused.stderr, argv
    nothing = run("--project", str(tmp_path / "nothing"))
    assert nothing.returncode == 3 and nothing.stdout == b"" and b"error:" in nothing.stderr


# --- the configuration, as the service takes it ----------------------------------------------------------------------


def test_a_folder_that_is_not_a_project_ends_the_start_and_an_unaccepted_configuration_refuses_every_tool(tree):  # noqa: F811
    path = str(tree["project"])
    out = io.StringIO()
    assert mcp.serve([str(tree["tree"] / "nothing")], io.BytesIO(lines(rpc("initialize", INIT, 0))), out, ops_module=ops) == 3
    assert out.getvalue() == ""
    digest = ops.project_config.load(path)["sha256"]
    server = mcp.Server(ops, mcp._projects_of([path], ops), log=lambda line: None, grace=WAIT)
    [listed] = result_of(tool(server, "projects"))["projects"]
    assert listed["id"] == mcp.project_id(path) == service.project_id(path)
    assert listed["config"] == {"sha256": digest, "accepted": False} and "accept-config" in listed["message"]
    offered = [r for r in operations.OPERATIONS if "mcp" in r["channels"]]
    assert len(offered) == 22
    for row in offered:  # every tool of the table, reads and writes alike
        arguments = {a["name"]: (1 if a["kind"] == "int" else "docs/x.md" if a["name"] == "path" else "x")
                     for a in row["args"] if a.get("required")}
        sentence = refusal_of(tool(server, row["name"], arguments))
        assert digest in sentence and "accept-config" in sentence, row["name"]
    ops.accept_config(path, digest, widen=ops.config(path)["widening_sha256"])
    [listed] = result_of(tool(server, "projects"))["projects"]
    assert listed["config"]["accepted"] is True and listed["open_pending"] == 0 and listed["running_task"] is None
    assert result_of(tool(server, "status"))["pending"] == []


def test_the_start_ends_the_runs_the_jobs_started_before_it_returns(world):
    entered, release = threading.Event(), threading.Event()

    def say(project, **kwargs):
        entered.set()
        release.wait(WAIT)
        return {}

    world.fake.answers["say"] = say
    out = io.StringIO()
    stop_seen = []
    original = world.fake.stop_runs

    def stop_runs(project=None):
        stop_seen.append(True)
        release.set()
        return original()

    world.fake.stop_runs = stop_runs
    mcp.serve([world.projects[0]["path"]], io.BytesIO(lines(rpc("initialize", INIT, 0), rpc("tools/call", {
        "name": "say", "arguments": {"text": "x"}}, 1))), out, ops_module=world.fake, log=world.log.append, grace=0.05)
    assert entered.is_set() and stop_seen and release.is_set()  # the job was running when the input ended; stop_runs freed it


# --- the file itself --------------------------------------------------------------------------------------------------


def test_the_shell_imports_only_the_operations_layer_the_shell_kit_and_the_standard_library_and_holds_no_token():
    source = (st.RUNTIME / "mcp.py").read_text(encoding="utf-8")
    tree_ = ast.parse(source)
    imported = set()
    for node in ast.walk(tree_):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    local = {n[:-3] for n in os.listdir(st.RUNTIME) if n.endswith(".py")}
    assert imported & local == {"ops", "shell_kit"} and imported - local <= STANDARD_LIBRARY
    assert "secrets" not in imported and "hmac" not in imported  # there is no token to make or compare
    assert "http" not in imported and "socket" not in imported  # a pipe, not a port


def test_the_tool_names_are_valid_and_do_not_clash_with_the_shells_own():
    rows = [r["name"] for r in operations.OPERATIONS if "mcp" in r["channels"]]
    assert not set(rows) & set(mcp.OWN_TOOLS)
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", n) for n in rows + list(mcp.OWN_TOOLS))
    kinds = {a["kind"] for r in operations.OPERATIONS if "mcp" in r["channels"] for a in r["args"]}
    assert kinds <= set(mcp.EXPOSED_KINDS)
    assert "project" not in {a["name"] for r in operations.OPERATIONS for a in r["args"]}
