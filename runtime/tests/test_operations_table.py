"""Tests of the table of operations (runtime/operations.py): the one place that says what the operations layer offers
to a shell. The terminal's parser, the conversation's commands, its help, the texts that name a command and the
generated documentation all derive from it, so these tests keep the table honest against the code it describes.
Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_operations_table.py
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import re

import pytest

import standin_tree as st
from test_effects import gate_project, provider_calls, tree  # noqa: F401  (the effect fixture of test_effects.py)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
ops_reads = st.load("ops_reads")
ops_config = st.load("ops_config")
ops_sources = st.load("ops_sources")
ops_steps = st.load("ops_steps")
ops_flows = st.load("ops_flows")
ops_routines = st.load("ops_routines")
ops_cancel = st.load("ops_cancel")
ops_instructions = st.load("ops_instructions")
ops_contained = st.load("ops_contained")
ops_ask = st.load("ops_ask")
ops_attachments = st.load("ops_attachments")
ops_reminders = st.load("ops_reminders")
ops_calendar = st.load("ops_calendar")
ops_files = st.load("ops_files")
ops_mail_send = st.load("ops_mail_send")
ops_mailbox = st.load("ops_mailbox")
ops_items = st.load("ops_items")
operations = st.load("operations")
cli = st.load("cli")
effects = st.load("effects")

# Public functions of ops.py that are not an operation of a shell: what the other modules and the tests use.
NOT_OPERATIONS = {"store_module", "context", "task_prompt", "code_task", "chat_memory", "state_question", "state_reply", "queued_ids",
                  "route_busy", "queue_route", "held_commands", "held_next", "drop_note", "asks_state", "waiting", "queue_stale", "with_routing",
                  "write_checkpoints", "own_key_name",
                  # ops_say.py and ops_ask.py (NR-2): the line of a request, whether a plain line is a natural request, whether the asker holds ask-mail
                  "person_line", "asks_natural", "holds_mail", "may_talk", "natural_needs", "natural_reply",
                  # ops_say.py and ops_items.py (NR-5): the bridge's entries for a write asked in words, and how the numbered items are written as lines
                  "natural_write", "natural_draft", "natural_forget", "render",
                  # ops_sources.py: what the planner and a run ask of the sources, beside the five operations
                  "catalog_block", "router_block", "known_ids", "forced_for", "copies_for", "record_copies", "prompt_lines",
                  # ops_cancel.py: what a run, the router and the board ask of a cancel, beside cancel and stop_task
                  "cancel_request", "stop_one", "watch", "stop_requested", "cancelled_run", "step_stopped", "after_sync", "lock_name", "request_cancel",
                  # ops_steps.py: the brake and what the dispatcher asks of the step tasks, beside run_step
                  "import_bytes", "set_steps_mode", "steps_mode", "unattended", "may_dispatch", "held_reason", "annotate",
                  # ops_flows.py: what the plan, the approval and the request ask of the flows, beside the four operations
                  "parse_params", "now", "staged", "direct", "bound", "before_approve", "after_approve", "discard_staged",
                  # ops_routines.py: the tick a round calls, the fire, and what a routine's task asks of its routine, beside the seven operations
                  "effective_model", "content_of", "local_reason", "tick", "fire", "routine_of_task", "consent_in_force",
                  # ops_instructions.py: what a run's prompt, a routine's content and the answer ask of the standing instructions, beside the
                  # four operations; ops.py `answer` is the step that records an answer, which the row `answer` now reaches through answer_proposing
                  "for_run", "guard", "contained_prompt", "hash_of", "proposal", "answer", "vet",
                  # ops_ask.py and ops_contained.py (AQ-1): the owners of the runs of a request, the hint of a direct reply, and the core the contained
                  # run and ask share; ops_core.py: the attribution of those runs to an agent
                  "run_owners", "hint", "routed", "execute", "attributed", "asked_by", "with_asker",
                  # ops_reminders.py: what the messaging bridge asks of the store to send a reminder, and the clock, beside the three operations (no sender can type them)
                  "reminders_due", "reminders_sent", "reminders_retry", "local_at", "local_of", "day_start"}  # ops_config.py: the one writer of the accepted hash and the Checkpoints line
KINDS = ("int", "str", "text", "file", "list", "flag", "choice", "pairs")
CHANNELS = ("terminal", "chat", "page", "mcp", "messaging")
# Modules that still hold the terminal's command as a string, outside the operations layer's own texts.
HOLDS_THE_COMMAND = {"lab.py": "an error message of the lab facade, in the region of the execution kit's move (WP-R.8)"}


def literal(name: str):
    tree_ = ast.parse((st.RUNTIME / "operations.py").read_text(encoding="utf-8"))
    for node in tree_.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a top-level assignment")


def chat_rows() -> list:
    return [r for r in operations.OPERATIONS if "chat" in r["channels"]]


def example(row: dict, optional: bool) -> dict:
    values = {}
    for arg in row["args"]:
        if arg["kind"] not in operations.POSITIONAL or not (arg.get("required") or optional):
            continue
        values[arg["name"]] = 7 if arg["kind"] == "int" else "some words"
    return values


def test_the_table_is_a_pure_literal_and_its_rows_are_well_formed():
    assert literal("OPERATIONS") == operations.OPERATIONS and literal("CHAT_OWN") == operations.CHAT_OWN
    names = [r["name"] for r in operations.OPERATIONS]
    assert len(names) == len(set(names))
    for row in operations.OPERATIONS:
        assert set(row) <= {"name", "call", "args", "channels", "model", "help", "channel_arg", "chat_reply", "exit_unless", "job", "queues", "exclusive"}, row["name"]
        assert row["help"].strip() and set(row["channels"]) <= set(CHANNELS) and row["channels"], row["name"]
        assert row["model"] in (True, False) or isinstance(row["model"], str), row["name"]
        for arg in row["args"]:
            assert arg["kind"] in KINDS and set(arg) <= {"name", "kind", "required", "flag", "label", "choices"}, row["name"]
            assert (arg["kind"] == "choice") == ("choices" in arg), row["name"]
        positional = [a for a in row["args"] if a["kind"] in operations.POSITIONAL]
        assert all(a["kind"] == "int" for a in positional[:-1]) or len(positional) <= 1 or "chat" not in row["channels"], \
            f"{row['name']}: in the conversation only the last argument may take the rest of the line"


def test_every_row_calls_a_function_of_the_operations_layer_that_accepts_its_arguments():
    for row in operations.OPERATIONS:
        function = getattr(ops, row["call"])
        params = inspect.signature(function).parameters
        assert list(params)[0] == "project", row["name"]
        wanted = {a["name"] for a in row["args"]} | ({"channel"} if row.get("channel_arg") else set())
        assert wanted <= set(params), f"{row['name']}: {sorted(wanted - set(params))} is not a parameter of {row['call']}"
        required = {n for n, p in params.items() if p.default is inspect.Parameter.empty and n != "project"}
        given = {a["name"] for a in row["args"] if a.get("required")}
        assert required <= given, f"{row['name']}: {sorted(required - given)} must be a required argument of the row"


def test_every_public_function_of_the_operations_layer_is_a_row_or_listed_as_not_one():
    # the layer is seven files (CONS-1B, ADJ-R1, R4-C3, P6a): ops.py and the siblings it re-exports from; a function counts where it is defined
    public = {n for module in (ops, ops_say, ops_reads, ops_core, ops_config, ops_sources, ops_steps, ops_flows, ops_routines, ops_instructions, ops_contained, ops_ask, ops_cancel, ops_attachments, ops_reminders, ops_calendar, ops_files, ops_mail_send, ops_mailbox, ops_items) for n, f in inspect.getmembers(module, inspect.isfunction)
              if not n.startswith("_") and f.__module__ == module.__name__}
    called = {r["call"] for r in operations.OPERATIONS}
    assert called <= public
    assert public - called == NOT_OPERATIONS


def test_the_same_flag_of_two_rows_is_the_same_kind_and_the_parser_offers_exactly_the_terminal_verbs():
    seen = {}
    for row in operations.OPERATIONS:
        for arg in row["args"]:
            flag = operations.flag_of(arg)
            assert seen.setdefault(flag, (arg["kind"], arg.get("choices"))) == (arg["kind"], arg.get("choices")), flag
    assert set(build_choices()) == set(operations.terminal_verbs())
    assert operations.terminal_verbs() == tuple(build_choices())
    documented = cli.__doc__
    for verb in operations.terminal_verbs():
        assert re.search(rf"(?m)^{re.escape(verb)}\s", documented), f"cli.py --help describes no {verb}"


def build_choices() -> tuple:
    return cli.build_parser()._actions[0].choices


def test_a_chat_command_is_read_back_from_the_line_that_writes_it():
    assert [r["name"] for r in chat_rows()] == ["status", "progress", "pending", "answer", "release", "approve", "reject",
                                                "retry", "cancel", "stop-task", "ask", "attachments"]
    for row in chat_rows():
        for optional in (False, True):
            values = example(row, optional)
            line = operations.chat_line(row["name"], **values)
            assert operations.parse_chat(line) == (row["name"], values), line
    assert operations.chat_line("approve", pending_id=12, sha256="abc") == "/approve 12 abc"
    assert operations.parse_chat("/answer 4 a long text  with words") == ("answer", {"pending_id": 4, "text": "a long text  with words"})
    assert operations.parse_chat("/pending") == ("pending", {}) and operations.parse_chat("/new an idea") == ("new", "an idea")
    assert operations.parse_chat("/help me") == ("help", "me")


def test_a_line_that_does_not_fit_is_not_a_command():
    for line in ("/frobnicate", "/new", "/release", "/release seven", "/release 1 2", "/pending 1 2", "/status now", "/answer 3",
                 "/retry", "/cancel 1 now", "/accept-config 1234", "/execute-under-policy a b", "/approve-policy x",
                 "/set-mode a b", "/pin", "not a command", "/approve x"):
        assert operations.parse_chat(line) is None, line


def test_the_help_is_built_from_the_rows_and_holds_every_command_once():
    text = operations.chat_help()
    lines = text.splitlines()
    assert lines[0].startswith("Commands, one per line") and len(lines) == 1 + len(operations.chat_commands())
    assert [c["usage"].split()[0] for c in operations.chat_commands()][0] == "/help"
    assert [c["usage"].split()[0] for c in operations.chat_commands()][-1] == "/new"
    assert "/accept-config" not in text and "/execute-under-policy" not in text
    assert "/approve <id> [sha256]" in text and "/retry <task id>" in text and "/progress [since]" in text


def test_a_command_the_conversation_does_not_offer_gets_the_help_and_runs_nothing(tree):  # noqa: F811
    case = gate_project(tree)
    for line in ("/accept-config 1234", f"/execute-under-policy {case['path']} x", "/set-mode a b", "/pin"):
        out = ops.say(case["path"], line)
        assert out["reply"] == operations.chat_help() and out["ran"] is False, line
    assert ops.pending(case["path"], case["item"]["id"])["status"] == "open" and provider_calls(tree) == []


def test_an_effect_is_approved_in_the_terminal_and_never_from_the_conversation(tree, capsys):  # noqa: F811
    case = gate_project(tree)
    item = case["item"]
    said = ops.say(case["path"], f"/approve {item['id']} {item['payload_sha256']}")
    assert said["reply"].startswith("error: an effect is approved in the terminal, with its hash")
    assert f"cli.py approve --project {case['path']} --id {item['id']}" in said["reply"]
    assert provider_calls(tree) == [] and ops.pending(case["path"], item["id"])["status"] == "open"
    with pytest.raises(ops.OpsError, match="an effect is approved in the terminal"):
        ops.approve(case["path"], item["id"], item["payload_sha256"], channel="chat")
    assert provider_calls(tree) == []
    capsys.readouterr()
    argv = ["approve", "--project", case["path"], "--id", str(item["id"]), "--sha256", item["payload_sha256"]]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["pull_request"]["number"] == 7
    assert [c["argv"][0] for c in provider_calls(tree)].count("open-pr") == 1


def test_an_effect_approved_with_no_channel_is_refused_and_nothing_is_executed(tree):  # noqa: F811
    case = gate_project(tree)
    item = case["item"]
    with pytest.raises(ops.OpsError, match="an effect is approved in the terminal"):
        ops.approve(case["path"], item["id"], item["payload_sha256"])
    assert provider_calls(tree) == [] and ops.pending(case["path"], item["id"])["status"] == "open"


def test_a_wrong_id_gets_the_same_refusal_from_the_terminal_and_the_conversation(tree, capsys):  # noqa: F811
    case = gate_project(tree)
    said = ops.say(case["path"], "/approve 9999")["reply"]
    capsys.readouterr()
    assert cli.main(["approve", "--project", case["path"], "--id", "9999"]) == 1
    assert capsys.readouterr().err.strip() == said and said.startswith("error: ")


def test_the_handler_verb_flag_is_the_handlers_and_not_the_command_word(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(ops, "handler_call", lambda project, name, verb, args=None: seen.append((name, verb, args)) or {})
    cli.run(["handler", "--project", str(tmp_path), "--name", "weekly", "--verb", "preview", "--arg", "week=3", "--arg", "x=y=z"])
    assert seen == [("weekly", "preview", {"week": "3", "x": "y=z"})]
    with pytest.raises(cli.Usage, match="--arg takes"):
        cli.run(["handler", "--project", str(tmp_path), "--name", "a", "--verb", "b", "--arg", "oops"])
    with pytest.raises(cli.Usage, match="handler needs --name"):
        cli.run(["handler", "--project", str(tmp_path), "--verb", "b"])


def test_the_texts_that_name_a_command_are_built_by_the_table():
    assert operations.command_line("accept-config", "/p q", sha256="ab") == "python3 runtime/cli.py accept-config --project '/p q' --sha256 ab"
    assert operations.command_line("run-next", "/p", model="auto") == "python3 runtime/cli.py run-next --project /p --model auto"
    assert operations.command_line("sync", "/p", dry_run=True, take=None) == "python3 runtime/cli.py sync --project /p --dry-run"
    assert operations.command_line("handler", "/p", name="n", verb="v", args={"a": "b"}) == \
        "python3 runtime/cli.py handler --project /p --name n --verb v --arg a=b"
    with pytest.raises(ValueError):
        operations.command_line("status", "/p", nothing=1)
    assert ops.PLAN_NEXT.format(pending=5) == "Approve with /approve 5"
    assert ops.ASK_NEXT == "Answer with a plain line, or start again with /new <text>"
    body = st.load("effect_pull_request").body({"repo": "r", "base": "b", "head": "h", "project_commit": "c", "title": "t", "body": "x",
                         "files": [], "removed": []}, "f" * 64)
    assert f"Approve exactly this: python3 runtime/cli.py approve --project <project> --id <this pending decision's id> --sha256 {'f' * 64}" in body


def test_no_module_of_the_runtime_but_the_table_spells_the_terminals_command_outside_a_docstring():
    found = {}
    for path in sorted(st.RUNTIME.glob("*.py")):
        tree_ = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree_)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree_):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings \
                    and "runtime/cli.py" in node.value:
                found.setdefault(path.name, []).append(node.lineno)
    assert set(found) == {"operations.py"} | set(HOLDS_THE_COMMAND) & set(found), found


def test_the_generated_tables_say_what_the_table_functions_say():
    spec = importlib.util.spec_from_file_location("architecture_tables_for_operations", st.REPO / "scripts" / "architecture_tables.py")
    tables = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tables)
    root = str(st.REPO)
    commands = tables.say_commands(root)
    assert [line for line in commands.splitlines()[2:]] == [f"| `{c['usage']}` | {c['help']} |" for c in operations.chat_commands()]
    verbs = tables.cli_verbs(root).splitlines()[2:]
    assert [line.split("|")[1].strip(" `") for line in verbs] == list(operations.terminal_verbs())
    assert len(tables.operations(root).splitlines()) == 2 + len(operations.OPERATIONS)
