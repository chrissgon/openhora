"""What the three operations of the to-do list are in the registry and in the policy tables (package CB-5: the rows `todo-list`, `todo-add` and `todo-done` of runtime/operations.py, the
groups `tasks-read`, `tasks-write` and `approve-effect-tasks`, the effect word `tasks`, the section `task_lists` of the accepted `accounts`, the gate rows of runtime/turn_gate.py and the
structure of the new modules). Pure: no service, no model, every name fictional.

What is held here, each against the test's OWN literals: the class of each row is pinned (R for the read, E for the two that open a card), the rows are of catalog version 2 so that the
served catalog stays byte for byte the one the newest enabling entry pins and no line reaches them (L54); the origins of each slot come from the gate; no group is in a default policy, none
is on the MCP mode and the approval grant is the messaging app's only; the word `tasks` is in every table that ties an effect word to its module, its group and its card; `task_lists` is
an accepted section, a widening and the only list a card may name; the step kind reaches no provider and no module names a verb that removes (limits L30, L57 and L58).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tasks_rows.py
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

import phrase_kit as pk
import standin_tree as st
import test_limits_account_writes as limits

REPO = st.REPO
account_start = st.load("account_start")
effects = st.load("effects")
interpreter = st.load("interpreter")
interpreter_catalog = st.load("interpreter_catalog")
natural = st.load("natural")
operations = st.load("operations")
ops_step_seams = st.load("ops_step_seams")
ops_todo = st.load("ops_todo")
phrases = st.load("phrases")
plan_confirm = st.load("plan_confirm")
policy_widening = st.load("policy_widening")
project_config = st.load("project_config")
registry = st.load("registry")
steps = st.load("steps")
turn_gate = st.load("turn_gate")

NEW = ("todo-list", "todo-add", "todo-done")
NEW_MODULES = ("tasks_document.py", "effect_tasks.py", "step_tasks_item.py", "tasks_reader.py", "ops_todo.py")
# the test's own literals
ROWS = {
    "todo-list": {"class": "R", "order": 110, "slots": {"service": {"kind": "word", "param": "account", "since": 2}}},
    "todo-add": {"class": "E", "order": 111, "slots": {"title": {"kind": "span", "param": "title", "since": 2}, "service": {"kind": "word", "param": "account", "since": 2}}},
    "todo-done": {"class": "E", "order": 112, "slots": {"item": {"kind": "int", "param": "item", "since": 2}, "target": {"kind": "span", "param": "target", "since": 2},
                                                        "service": {"kind": "word", "param": "account", "since": 2}}},
}


def row(name):
    return next(r for r in operations.OPERATIONS if r["name"] == name)


# --- the rows -----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NEW)
def test_the_class_the_version_and_the_slots_of_each_row_are_pinned(name):
    rec = row(name)["natural"]
    assert (rec["class"], rec["since"], rec["order"], rec["privacy"], rec["cost"]) == (ROWS[name]["class"], 2, ROWS[name]["order"], "account", "provider")
    assert rec["slots"] == ROWS[name]["slots"] and 1 <= len(rec["about"]) <= 300 and "@" not in rec["about"]
    assert natural.CLASSES[name] == ROWS[name]["class"], "a class is a property of the operation on every path"
    assert natural.class_of(name) == ROWS[name]["class"]
    assert row(name)["channels"] == ("terminal", "page", "messaging") and row(name)["model"] is False and "mcp" not in row(name)["channels"]


def test_the_orders_are_the_next_free_ones_and_unique():
    orders = [r["natural"]["order"] for r in operations.OPERATIONS]
    assert len(set(orders)) == len(orders) and [r["natural"]["order"] for r in operations.OPERATIONS if r["natural"]["since"] == 2 and r["name"] in NEW] == [110, 111, 112]
    assert sorted(r["natural"]["order"] for r in operations.OPERATIONS if r["natural"]["since"] == 1) == list(range(1, 100)), "the ninety-nine rows of version 1 keep their places"
    assert all(110 <= order <= 129 for order in (r["natural"]["order"] for r in operations.OPERATIONS if r["name"] in NEW)), "the range the coordinator gave this package"


def test_the_served_catalog_holds_the_three_rows_since_the_flip_and_version_1_holds_none_of_them():
    assert operations.LINE_CATALOG == 2
    assert all(op in natural.NATURAL and op in natural.CLASSES for op in NEW)
    assert all(op not in natural.views(1)[1] and op in natural.views(1)[0] for op in NEW), "at version 1 the rows exist for a typed command and a line does not reach them"
    served = {r["op"] for r in interpreter.SERVED["ops"]} | {r["op"] for r in interpreter.SERVED["refused"]}
    assert set(NEW) <= served
    one = interpreter_catalog.generate(version=1)
    assert not {r["op"] for r in one["ops"] + one["refused"]} & set(NEW)
    generated = interpreter_catalog.generate(version=2)
    assert generated == interpreter.SERVED and interpreter_catalog.sha256(generated) == interpreter.SERVED_SHA256
    two = interpreter_catalog.generate(version=2)
    assert [r["op"] for r in two["ops"]][-3:] != [] and set(NEW) <= {r["op"] for r in two["ops"]}
    by = {r["op"]: r for r in two["ops"]}
    assert by["todo-list"]["class"] == "R" and by["todo-add"]["class"] == "E" and by["todo-done"]["class"] == "E"
    assert by["todo-done"]["what"] == row("todo-done")["natural"]["about"] and "to-do list" in by["todo-add"]["what"], "version 2 serves the text written for the model"
    assert [r["op"] for r in registry.rows(2) if r["op"] in NEW] == list(NEW), "the three rows are served in their orders (110 to 112; a later package's rows, such as FA-1's 150, come after them)"


def test_the_text_that_separates_the_confusables_names_what_each_row_is_not():
    about = {name: row(name)["natural"]["about"].lower() for name in NEW}
    assert "not a reminder" in about["todo-add"] and "calendar event" in about["todo-add"]
    assert "platform's own work" in about["todo-list"] and "task, status, pending" in about["todo-list"]
    assert "to-do list" in about["todo-done"] and "service" in about["todo-done"]
    assert "reminder-forget" in row("event-cancel")["natural"]["about"], "the neighbours' texts are as CB-0 wrote them"


def test_the_origins_of_each_slot_come_from_the_gate():
    assert registry.origins("todo-add", "title") == ("line-span", "card-copy", "card-words")      # card-words (CARD-MODEL-SEES) is a title origin of the gate's one row for the key; only a waiting event card's revision supplies it
    assert registry.origins("todo-add", "service") == ("config", "picked", "line-span", "card-copy")
    assert registry.origins("todo-done", "item") == ("line-number", "listed", "picked", "grounded")
    assert registry.origins("todo-done", "target") == ("line-span",)
    assert registry.origins("todo-done", "service") == ("config", "picked", "line-span", "card-copy")
    assert registry.origins("todo-list", "service") == ("line-span",)
    assert turn_gate.OPS["todo-add"] == ("account", "title", "list") and turn_gate.OPS["todo-done"] == ("account", "item", "list")
    assert turn_gate.ALLOWED["list"] == ("config", "picked", "line-span", "card-copy") and turn_gate.ALLOWED["item"] == ("line-number", "listed", "picked", "grounded")
    for op in ("todo-add", "todo-done"):
        for slot, spec in row(op)["natural"]["slots"].items():
            assert spec["param"] in turn_gate.OPS[op] or spec["param"] in registry.FINDER_PARAMS, (op, slot)


def test_the_gate_refuses_what_it_does_not_declare_for_a_task_row():
    ok = turn_gate.provenance("todo-add", {"account": "google", "title": "comprar café"}, {"account": "config", "title": "line-span"})
    assert ok == []
    assert turn_gate.provenance("todo-add", {"account": "google", "title": "x"}, {"account": "config", "title": "grounded"})
    assert turn_gate.provenance("todo-add", {"account": "google", "title": "x", "due": "amanhã"}, {"account": "config", "title": "line-span", "due": "line-span"})  # validate: allow english-only -- a Portuguese line is the input under test
    assert turn_gate.provenance("todo-done", {"account": "google", "item": "todo:1", "list": "tarefas"}, {"account": "config", "item": "listed", "list": "config"}) == []
    assert turn_gate.provenance("todo-done", {"account": "google", "item": "x"}, {"account": "config", "item": "line-span"})
    assert turn_gate.provenance("todo-list", {}, {}), "a read opens no card: it is not an operation opened from a line"


# --- the policy tables ----------------------------------------------------------------------------------------------------------------------


def test_the_groups_the_grant_and_the_word_are_in_every_table_that_ties_them():
    groups = operations.GROUPS
    assert groups["tasks-read"] == {"operations": ("todo-list",), "kind": None}
    assert groups["tasks-write"] == {"operations": ("todo-add", "todo-done"), "kind": None}
    assert groups["approve-effect-tasks"] == {"operations": ("approve",), "kind": "effect:tasks"}
    assert "approve-effect-tasks" in operations.GRANTS["messaging"] and "approve-effect-tasks" not in operations.GRANTS["mcp"]
    assert "approve-effect-tasks" in operations.IMPLIED["approve-effects"]
    assert operations.GRANT_TEXT["messaging:approve-effect-tasks"] and all(operations.GROUP_TEXT[g] for g in ("tasks-read", "tasks-write", "approve-effect-tasks"))
    assert "tasks" in operations.EFFECT_APPROVAL_WORDS and "tasks" in operations.ACCOUNT_APPROVAL_WORDS and "tasks" in project_config.ACCOUNT_EFFECT_WORDS
    assert "tasks" in steps.ACCOUNT_WORDS and account_start.GROUP_OF_WORD["tasks"] == "tasks-write" and "tasks" in account_start.WORDS
    assert effects.KINDS["tasks"] == "effect_tasks" and effects.module_for("tasks").APPROVAL_GROUP == "approve-effect-tasks" and "tasks" in effects.step_only_words()
    assert "tasks" not in effects.policy_kinds(), "no standing approval covers a task change"


def test_no_group_of_the_to_do_list_is_in_a_default_policy_or_on_the_mcp_mode():
    for group in ("tasks-read", "tasks-write", "approve-effect-tasks"):
        assert all(group not in groups for groups in operations.DEFAULT_POLICY.values()), group
    for name in NEW:
        for policy in ({"mcp": ["read", "tasks-read", "tasks-write"]}, None):
            assert operations.permitted(name, "mcp", policy) is False
        assert operations.permitted(name, "messaging", {"messaging": list(operations.DEFAULT_POLICY["messaging"])}, None, "telegram:1") is False
    assert operations.permitted("todo-list", "messaging", {"messaging": ["read", "tasks-read"]}) is True
    assert operations.permitted("todo-add", "messaging", {"messaging": ["read", "tasks-read"]}) is False
    assert operations.permitted("todo-add", "messaging", {"messaging": ["read", "tasks-write"]}) is True
    assert operations.permitted("approve", "messaging", {"messaging": ["read", "approve-effect-tasks"]}, "effect:tasks") is True
    assert operations.permitted("approve", "messaging", {"messaging": ["read", "approve-effect-calendar"]}, "effect:tasks") is False, "the calendar's grant does not cover a task"
    assert operations.permitted("approve", "messaging", {"messaging": ["read", "approve-effect-tasks"]}, "effect:calendar") is False


def test_the_word_tasks_is_in_the_validators_list_and_the_contract_table():
    text = (REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    assert "| `tasks` |" in text and "`tasks` arrived the same way" in text
    validate = st.REPO / "scripts" / "validate.py"
    tree = ast.parse(validate.read_text(encoding="utf-8"))
    values = {t.id: [e.value for e in node.value.elts if isinstance(e, ast.Constant)] for node in tree.body if isinstance(node, ast.Assign) for t in node.targets if isinstance(t, ast.Name) and isinstance(node.value, ast.Tuple)}
    assert values["SIDE_EFFECTS"][-1] == "tasks" and values["RUNTIME_ONLY_EFFECTS"][-1] == "tasks"


# --- the accepted section -------------------------------------------------------------------------------------------------------------------


def accounts_of(value):
    return project_config._accounts(value)


def test_task_lists_is_an_accepted_section_with_names_and_ids_checked():
    ok = accounts_of({"google": {"address": "pat@example.com", "task_lists": {"tarefas": "default", "mercado": "Abc_123-x"}}, "microsoft": {"address": "casey@mail.example", "task_lists": {"trabalho": "AAMkAD=="}}})
    assert ok["google"]["task_lists"] == {"tarefas": "default", "mercado": "Abc_123-x"} and ok["microsoft"]["task_lists"] == {"trabalho": "AAMkAD=="}
    assert accounts_of({"google": {"address": "pat@example.com"}})["google"]["task_lists"] == {}, "a section is always present"
    for bad in ({"Minha Lista": "default"}, {"x" * 33: "default"}, {"tarefas": "has/slash"}, {"tarefas": ""}, {"tarefas": 7}):
        with pytest.raises(project_config.ConfigError):
            accounts_of({"google": {"address": "pat@example.com", "task_lists": bad}})
    with pytest.raises(project_config.ConfigError):
        accounts_of({"google": {"address": "pat@example.com", "task_lists": {"a": "b/c"}}})
    assert "task_lists" in project_config.ACCOUNT_KEYS and "task_lists" in project_config.ACCOUNT_SECTIONS


def test_a_list_is_a_target_only_when_the_file_names_it_and_the_first_is_the_default():
    cfg = {"accounts": accounts_of({"google": {"address": "pat@example.com", "task_lists": {"tarefas": "default", "mercado": "Abc_123"}}, "microsoft": {"address": "casey@mail.example"}})}
    assert project_config.account_target(cfg, "google", "task_lists", None) == ("default", None)
    assert project_config.account_target(cfg, "google", "task_lists", "mercado") == ("Abc_123", None)
    for account, name in (("google", "compras"), ("microsoft", None), ("microsoft", "tarefas"), ("yahoo", None)):
        found, why = project_config.account_target(cfg, account, "task_lists", name)
        assert found is None and why, (account, name)


def test_adding_a_task_list_to_the_file_is_a_widening_and_a_file_with_none_adds_nothing():
    plain = {"accounts": accounts_of({"google": {"address": "pat@example.com", "calendars": {"pessoal": "primary"}}})}
    with_lists = {"accounts": accounts_of({"google": {"address": "pat@example.com", "calendars": {"pessoal": "primary"}, "task_lists": {"tarefas": "default", "mercado": "Abc_123"}}})}
    before = {i["group"] for i in policy_widening.account_items(plain)}
    after = policy_widening.account_items(with_lists)
    added = [i for i in after if i["group"] not in before]
    assert [i["group"] for i in added] == ["google:task-list:mercado=Abc_123", "google:task-list:tarefas=default", "google:default-task-list=tarefas"]
    assert all("task" in i["means"] for i in added) and "'mercado'" in added[0]["means"] and "'tarefas'" in added[1]["means"]
    held = policy_widening.dump_accounts(plain)
    assert [i["group"] for i in policy_widening.account_widening(held, with_lists)] == [i["group"] for i in added]
    changed = {"accounts": accounts_of({"google": {"address": "pat@example.com", "calendars": {"pessoal": "primary"}, "task_lists": {"tarefas": "Other_ID", "mercado": "Abc_123"}}})}
    assert [i["group"] for i in policy_widening.account_widening(policy_widening.dump_accounts(with_lists), changed)] == ["google:task-list:tarefas=Other_ID"], "an id changed behind a name is another item"
    assert policy_widening.account_widening(policy_widening.dump_accounts(with_lists), with_lists) == []


# --- the structure --------------------------------------------------------------------------------------------------------------------------


def source_of(name):
    return (REPO / "runtime" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", NEW_MODULES)
def test_no_new_module_names_a_verb_that_removes_moves_or_opens_a_task_again(name):
    assert limits.delete_findings(source_of(name), name) == []
    tree = ast.parse(source_of(name))
    strings = [n.value.lower() for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if s in ("task-delete", "task-remove", "task-move", "task-clear", "task-reopen", "task-uncomplete", "delete", "remove", "clear", "move")], name


def test_vacuity_the_scan_sees_a_planted_removal():
    assert limits.delete_findings('METHOD = "DELETE"\n', "planted.py")
    assert limits.delete_findings("def task_delete():\n    pass\n", "planted.py")
    assert limits.delete_findings('VERBS = {"remove": "task-delete"}\n', "planted.py")


def test_the_step_kind_is_registered_reaches_no_provider_and_cannot_be_planned_or_run_unattended():
    kind = steps.kind_of("tasks-item")
    assert kind.order == ("prepare", "tasks") and kind.gates["tasks"].word == "tasks" and kind.gates["tasks"].redo == "prepare"
    assert kind.unattended is False and kind.effectful == () and kind.footprint({}) == () and steps.is_account_step("tasks-item") is True
    with pytest.raises(steps.StepFailure) as refused:
        steps.plan_task("tasks-item", {"account": "google", "operation": "add", "title": "x"}, key="k", title="t", text="x")
    assert refused.value.code == "not_plannable", "a change to the person's own account is started by its own operation, never by a plan or a flow"
    imported = {n for n in ast.walk(ast.parse(source_of("step_tasks_item.py"))) if isinstance(n, (ast.Import, ast.ImportFrom))}
    names = {a.name.split(".")[0] for n in imported if isinstance(n, ast.Import) for a in n.names} | {n.module.split(".")[0] for n in imported if isinstance(n, ast.ImportFrom) and n.module}
    assert names - {"os", "re", "sys", "__future__"} == {"steps", "tasks_document"}


def test_the_writer_is_named_by_the_effect_and_the_seam_alone():
    importers = []
    for path in sorted((REPO / "runtime").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "effect_tasks" for a in node.names):
                importers.append(path.name)
    assert importers == ["ops_step_seams.py"], importers
    consts = []
    for path in sorted((REPO / "runtime").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts += [path.name for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value in ("writer:tasks", "task-insert", "task-complete")]
    assert set(consts) <= {"effect_tasks.py", "tasks_document.py"}, consts


def test_the_seam_a_step_kind_is_given_can_only_read_and_preview():
    seam = ops_step_seams.TasksReader({"cfg": {"accounts": None}})
    assert {name for name in dir(seam) if not name.startswith("_")} == {"enabled", "address", "list_name", "target", "resolve_list", "task_get", "dry_run"}
    assert ops_step_seams.TASKS_READ_VERBS == ("task-get",)


def test_the_reader_offers_two_reads_and_refuses_any_other_verb(monkeypatch):
    tasks_reader = st.load("tasks_reader")
    assert tasks_reader.VERBS == ("lists", "open")
    for verb in ("task-insert", "task-complete", "delete", "insert"):
        with pytest.raises(tasks_reader.ReaderError) as refused:
            tasks_reader.provider_call("/nowhere", "google", verb, [])
        assert refused.value.code == "refused"
    with pytest.raises(tasks_reader.ReaderError):
        tasks_reader.provider_call("/nowhere", "notion", "lists", [])


def test_the_reader_checks_every_answer_before_any_module_sees_it(monkeypatch):
    tasks_reader = st.load("tasks_reader")
    answers = {"lists": {"lists": [{"id": "L1", "name": "Tarefas", "default": None}, {"id": "L2", "name": "x\u202e\ny", "default": True}], "external_content": True},
               "open": {"list": "L1", "tasks": [{"id": "t1", "title": "comprar\u202e café\nagora", "updated": "2026-10-27T12:00:00.000Z", "etag": '"E1"'}], "truncated": False}}
    monkeypatch.setattr(tasks_reader, "provider_call", lambda root, account, verb, args, timeout=0: answers[verb])
    assert tasks_reader.lists("/r", "google") == [{"id": "L1", "name": "Tarefas", "default": False}, {"id": "L2", "name": "x y", "default": True}]
    got = tasks_reader.open_tasks("/r", "google", "L1")
    assert got["tasks"][0]["title"] == "comprar café agora" and got["list"] == "L1"
    assert tasks_reader.default_list("/r", "microsoft") == "L2" and tasks_reader.default_list("/r", "google") == "default"
    for bad in ({"lists": "no"}, {"lists": [{"id": "-x"}]}, {"lists": [{"name": "no id"}]}):
        answers["lists"] = bad
        with pytest.raises(tasks_reader.ReaderError):
            tasks_reader.lists("/r", "google")
    answers["open"] = {"list": "L1", "tasks": [{"id": "t1", "etag": ""}], "truncated": False}
    with pytest.raises(tasks_reader.ReaderError):
        tasks_reader.open_tasks("/r", "google", "L1")
    answers["lists"] = {"lists": [{"id": "A", "name": "a", "default": False}]}
    with pytest.raises(tasks_reader.ReaderError):
        tasks_reader.default_list("/r", "microsoft")      # no list the service marks as the default one


# --- the sentence of the read ---------------------------------------------------------------------------------------------------------------


def test_the_read_asks_posso_first_and_says_what_it_understood_in_both_languages():
    assert plan_confirm.SENTENCES["todo-list"] == "UNDERSTOOD_TODO_LIST" and "todo-list" not in plan_confirm.ALWAYS
    ctx = {"cfg": {"language": "pt-BR", "channels": {}}}
    pk.assert_said(plan_confirm.understood(ctx, "todo-list", {}, "o que tem na lista de tarefas"), "UNDERSTOOD_TODO_LIST", ctx["cfg"])
    pk.assert_said(plan_confirm.understood({"cfg": {"language": "en", "channels": {}}}, "todo-list", {}, "my tasks"), "UNDERSTOOD_TODO_LIST", {"language": "en"})
    assert plan_confirm.needed({"cfg": {"channels": {"messaging": ["read", "tasks-read"]}}}, "todo-list", "messaging", "telegram:1", False) is True
    assert plan_confirm.needed({"cfg": {"channels": {}}}, "todo-list", "terminal", None, False) is False


def test_a_line_that_reaches_a_card_operation_while_the_catalog_is_at_1_is_asked_again_and_opens_nothing(monkeypatch):
    """Tier-1 forms and the natural writes' own parse do not consult the table of what a line may reach: the operation checks it (L54). The catalog is at 2 since CB-9, so the views of version 1 are put back."""
    classes1, table1 = natural.views(1)
    monkeypatch.setattr(natural, "CLASSES", classes1)
    monkeypatch.setattr(natural, "NATURAL", table1)
    cfg = {"language": "pt-BR", "channels": {}}
    for op, args in (("todo-add", {"title": "comprar café"}), ("todo-done", {"target": "café"})):
        extras = {}
        text = ops_todo.reply("/nowhere", {"cfg": cfg}, op, args, "adiciona comprar café", "messaging", "telegram:1", extras)
        assert text == phrases.text("IX_ASK_AGAIN", cfg) and "resend" not in extras, op
