"""Tests of the conversation's commands as data (R4-C1, ruling R-45 of the round-4 design): the rows `/help` prints for the
`chat` channel, as `{command, arguments, help}` in the order `/help` prints them, built from the one source `/help` uses; the
read that gives them to the page (`GET /projects/{p}/commands`, the operation `commands`); `/help`'s own help line, which reads
`list the commands`; and the client's one call. Offline, no model; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_chat_commands.py
"""
from __future__ import annotations

import re
import types

import pytest

import standin_tree as st
from test_interface_plates_meters import needs_node, run_node
from test_service import PORT, TOKEN, api, call, world  # noqa: F401  (the service over a stand-in operations object)
from test_service_conversation import Page, served  # noqa: F401  (the service started over the real operations layer)
from test_chat import tree  # noqa: F401  (the conversation's stand-in project, its configuration accepted)

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
operations = st.load("operations")
service = st.load("service")

JS = st.REPO / "interface" / "js"
KEYS = {"command", "arguments", "help"}
ORDER = ["/help", "/status", "/progress", "/pending", "/answer", "/release", "/approve", "/reject", "/retry", "/cancel", "/stop-task", "/ask", "/new"]
ARGUMENTS = {"/help": "", "/status": "", "/progress": "[since]", "/pending": "[id]", "/answer": "<id> <text>", "/release": "<id>",
             "/approve": "<id> [sha256]", "/reject": "<id> [note]", "/retry": "<task id>", "/cancel": "<request id>", "/stop-task": "<task id>", "/ask": "<text>", "/new": "<text>"}


# --- the rows are what /help prints -----------------------------------------------------------------------------------


def test_the_rows_are_the_commands_in_the_order_help_prints_them_with_their_arguments_and_help_lines():
    rows = operations.chat_command_rows()
    assert [r["command"] for r in rows] == ORDER
    assert {r["command"]: r["arguments"] for r in rows} == ARGUMENTS
    assert all(set(r) == KEYS and all(isinstance(v, str) for v in r.values()) for r in rows)
    for row in rows:
        name = row["command"][1:]
        if name not in ("help", "new"):
            assert row["help"] == operations.by_name(name)["help"], f"{row['command']}: the help line is the table's"
    assert [r["help"] for r in rows if r["command"] in ("/help", "/new")] == [
        "list the commands", "start a new request, whatever is open (--after <id> before the text: run it after that request)"]


def test_every_line_help_prints_is_a_row_command_arguments_and_help_in_the_same_order():
    lines = operations.chat_help().splitlines()[1:]
    rows = operations.chat_command_rows()
    assert len(lines) == len(rows) == len(operations.chat_commands())
    for line, row in zip(lines, rows):
        assert line[:operations.HELP_WIDTH].rstrip() == f"{row['command']} {row['arguments']}".rstrip(), line
        assert line[operations.HELP_WIDTH:] == row["help"], line
    for row, command in zip(rows, operations.chat_commands()):
        assert f"{row['command']} {row['arguments']}".rstrip() == command["usage"] and row["help"] == command["help"]


def test_a_command_the_conversation_does_not_offer_is_in_no_row():
    commands = {r["command"] for r in operations.chat_command_rows()}
    assert commands == set(ORDER)
    assert not commands & {"/accept-config", "/execute-under-policy", "/set-mode", "/pin", "/run-next", "/commands"}


# --- /help describes itself as a list ---------------------------------------------------------------------------------------


def test_help_says_list_the_commands_at_its_one_source_and_only_that_line_of_the_text_changed():
    own = {c["name"]: c for c in operations.CHAT_OWN}
    assert own["help"]["help"] == "list the commands"
    text = operations.chat_help()
    assert "this text" not in text
    assert text.splitlines()[1] == "/help".ljust(operations.HELP_WIDTH) + "list the commands"
    assert text.splitlines()[0] == operations.HELP_HEAD
    assert text.splitlines()[2].startswith("/status".ljust(operations.HELP_WIDTH) + "requests, tasks and what waits for you")


def test_the_terminals_help_and_a_line_it_does_not_understand_print_that_text(tree):  # noqa: F811
    project = str(tree["project"])
    for line in ("/help", "/frobnicate"):
        out = ops.say(project, line)
        assert out["reply"] == operations.chat_help() and out["ran"] is False, line
        assert "/help".ljust(operations.HELP_WIDTH) + "list the commands" in out["reply"].splitlines()


# --- the read ---------------------------------------------------------------------------------------------------------------


def test_the_operation_is_a_read_of_the_page_only_and_gives_the_rows(tree):  # noqa: F811
    row = operations.by_name("commands")
    assert row["channels"] == ("page",) and row["model"] is False and not row.get("job") and row["args"] == ()
    assert ops.commands(str(tree["project"])) == {"commands": operations.chat_command_rows()}


def test_the_route_is_a_read_that_takes_no_query_and_answers_the_rows_with_the_token_and_not_without(world):  # noqa: F811
    routes = [r for r in service.ROUTES if r["pattern"] == "/projects/{p}/commands"]
    assert len(routes) == 1 and routes[0]["method"] == "GET" and routes[0]["op"] == "commands" and routes[0]["take"] == ()
    project = world.projects[0]["path"]
    rows = {"commands": operations.chat_command_rows()}
    world.fake.answers["commands"] = rows  # the page filters this answer by its policy (MSG-3b): no policy here, so it comes back whole
    status, _, body = call(world, "GET", api(world, "/commands"))
    assert status == 200 and body == rows and world.fake.calls[-1] == ("commands", project, {})
    world.fake.calls.clear()
    assert call(world, "GET", api(world, "/commands"), auth=False)[0] == 401
    assert call(world, "GET", api(world, "/commands?x=1"))[0] == 400
    assert call(world, "POST", api(world, "/commands"), {})[0] == 405
    assert call(world, "GET", "/api/v1/projects/000000000000/commands")[0] == 404
    assert world.fake.calls == []


@pytest.fixture
def unaccepted(tmp_path, monkeypatch):
    """The service over the real operations and a project whose configuration nobody accepted (as test_service.py's `real`)."""
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    path = str(built["project"])
    projects = [{"id": service.project_id(path), "name": "project", "path": path}]
    return types.SimpleNamespace(svc=service.Service(ops, projects, TOKEN, PORT, str(tmp_path / "no-interface"), log=lambda _l: None),
                                 projects=projects, path=path)


def test_the_read_is_refused_with_412_not_configured_until_the_configuration_is_accepted(unaccepted):
    status, _, body = call(unaccepted, "GET", api(unaccepted, "/commands"))
    assert status == 412 and body["error"] == "not_configured" and "accept-config" in body["next"], body
    ops.accept_config(unaccepted.path, ops.project_config.load(unaccepted.path)["sha256"])
    status, _, body = call(unaccepted, "GET", api(unaccepted, "/commands"))
    assert status == 200 and body == {"commands": operations.chat_command_rows()}


def test_the_service_answers_what_help_prints_over_http_with_the_real_operations(served):  # noqa: F811
    page, tree_, run = served
    status, body = page.json("GET", "/commands")
    assert status == 200 and body == {"commands": operations.chat_command_rows()}
    assert [r["command"] for r in body["commands"]][0] == "/help" and body["commands"][0]["help"] == "list the commands"
    headers = page.call("GET", "/commands")[1]
    assert headers["Cache-Control"] == "no-store"
    token, page.token = page.token, "wrong"
    try:
        assert page.call("GET", "/commands")[0] == 401
    finally:
        page.token = token


# --- the client -------------------------------------------------------------------------------------------------------------

CLIENT = r"""
import { setToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";

const seen = [];
globalThis.fetch = async (url, init) => {
  seen.push({ url, method: init.method, headers: init.headers, body: init.body === undefined ? null : init.body });
  return { ok: true, status: 200, json: async () => ({ commands: [{ command: "/help", arguments: "", help: "list the commands" }] }) };
};
setToken("t".repeat(64));
const answer = await api.commands("0123456789ab");
console.log(JSON.stringify({ answer, seen }));
"""


@needs_node
def test_the_client_reads_the_commands_with_one_get_and_the_token_in_the_header(tmp_path):
    got = run_node(tmp_path, CLIENT)
    assert got["answer"] == {"commands": [{"command": "/help", "arguments": "", "help": "list the commands"}]}
    assert len(got["seen"]) == 1
    request = got["seen"][0]
    assert request["url"] == "/api/v1/projects/0123456789ab/commands" and request["method"] == "GET" and request["body"] is None
    assert request["headers"]["Authorization"] == "Bearer " + "t" * 64 and "token" not in request["url"]


def test_the_client_has_the_function_and_still_one_fetch_path():
    client = (JS / "api.js").read_text(encoding="utf-8")
    assert re.search(r"export function commands\(p, options\) \{\n  return send\(\"GET\", `/projects/\$\{enc\(p\)\}/commands`, options\);\n\}", client)
    assert len(re.findall(r"\btransport\(", client)) == 1 and not re.search(r"\bfetch\(", client)
