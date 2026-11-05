"""The person's own to-do list (package CB-5: runtime/ops_todo.py, runtime/step_tasks_item.py, runtime/tasks_document.py, runtime/effect_tasks.py, runtime/tasks_reader.py, and the
seam `tasks_read` of runtime/ops_step_seams.py), end to end against the stand-in services of providers/tasks/tests/ on 127.0.0.1 (Google Tasks and Microsoft To Do): the real readers and
writers run as the processes the runtime starts, with the minimum environment and the one account secret. No Google or Microsoft host is reached, no credential is real, no model runs, every
name is fictional and every address is on `.example`.

What is held here (the spec's "Tests" of CB-5): a typed `todo-add` is one card and nothing is written before the approval; the approval by the hash makes exactly one insert; a
`todo-done` whose task moved between the card and the approval writes nothing and sends the task back to start over; a list the configuration does not name makes nothing, and an
account with no `task_lists` makes nothing (limit L55); the title of a card is code's and every title on it is the person's or the service's; no request of any path is a delete, a
move or a clear; `todo-list` reads live and numbers per service; `todo:<n>` answers only the list this sender was shown; the Microsoft default list is resolved to its id before the
writer is asked.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tasks_ops.py
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import phrase_kit as pk
import standin_tree as st
from test_ask import accept

sys.path.insert(0, str(st.REPO / "providers" / "tasks" / "tests"))
import fake_graph_tasks as fm  # noqa: E402
import fake_gtasks as fg  # noqa: E402

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
effects = st.load("effects")
phrases = st.load("phrases")
project_config = st.load("project_config")
ops_step_effects = st.load("ops_step_effects")
ops_todo = st.load("ops_todo")
tasks_document = st.load("tasks_document")
tasks_reader = st.load("tasks_reader")

GOOGLE = {"address": fg.ACCOUNT, "task_lists": {"tarefas": "default", "mercado": fg.OTHER_LIST}}
MICROSOFT = {"address": fm.ADDRESS, "task_lists": {"trabalho": "default"}}
SENDER = "telegram:830461975213"
OTHER = "telegram:777"
TEST_VARIABLES = tuple(f"{role}_TASKS_{vendor}_{what}" for role in ("INTEGRATION", "WRITER") for vendor in ("GOOGLE", "MICROSOFT") for what in ("API_BASE", "TOKEN_URL"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    shutil.copytree(st.REPO / "providers", tree / "providers", ignore=shutil.ignore_patterns("tests", "__pycache__", "vcs"), dirs_exist_ok=True)
    google, microsoft = fg.FakeGoogleTasks(), fm.FakeGraphTasks()
    for fake in (google, microsoft):      # the writers' ledger stamps the real time: the stand-ins' clocks follow it
        fake.clock = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    google.add_task(fg.DEFAULT_LIST, "t1", "comprar café")
    google.add_task(fg.DEFAULT_LIST, "t2", "ligar para o dentista")
    google.add_task(fg.OTHER_LIST, "t3", "comprar pão")  # validate: allow english-only -- a Portuguese line is the input under test
    microsoft.add_task(fm.DEFAULT_LIST, "m1", "enviar o relatório")
    state = tmp_path / "writer-state"
    state.mkdir()
    os.chmod(state, 0o700)
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for fake, vendor in ((google, "GOOGLE"), (microsoft, "MICROSOFT")):
        for role in ("INTEGRATION", "WRITER"):
            for name, value in fake.env(f"{role}_TASKS_{vendor}").items():
                monkeypatch.setenv(name, value)
    monkeypatch.setenv("GOOGLE_ACCOUNT_TOKEN", google.record_json())
    monkeypatch.setenv("MICROSOFT_ACCOUNT_TOKEN", microsoft.record_json())
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    resolver = project_config.resolver(str(tree))      # the test variables reach the processes the runtime starts; the interpreter is this one (no uv, no network)
    monkeypatch.setattr(resolver, "ENV_MINIMUM", resolver.ENV_MINIMUM + TEST_VARIABLES)
    monkeypatch.setattr(resolver, "interpreter_for", lambda path: [sys.executable])
    monkeypatch.setattr(project_config, "resolver", lambda workbench: resolver)
    monkeypatch.setattr(ops_todo, "_root", lambda: str(tree))
    ops_todo.forget_lists()
    world_ = {**built, "path": str(built["project"]), "google": google, "microsoft": microsoft, "tmp": tmp_path, "state": state, "tree": tree}
    configure(world_)
    yield world_
    google.close()
    microsoft.close()
    ops_todo.forget_lists()


PROFILES = {"owner": ["read", "talk", "tasks-read", "tasks-write", "approve-effect-tasks"], "reader": ["read", "talk", "tasks-read"],
            "writer": ["read", "talk", "tasks-write", "approve-effect-tasks"], "plain": ["read", "talk"]}
SENDERS = {"telegram": [{"id": "830461975213", "policy": "owner"}, {"id": "777", "policy": "plain"}, {"id": "888", "policy": "reader"}, {"id": "999", "policy": "writer"}]}


def configure(world, accounts=None, **extra):
    """Write the accounts and the profiles into the project's runtime.json and accept it as the person does (the widening list included)."""
    accept(world["path"], accounts=accounts if accounts is not None else {"google": GOOGLE, "microsoft": MICROSOFT, "default": "google"},
           policies=PROFILES, messaging={"senders": SENDERS}, language="pt-BR", **extra)


def ctx_of(world):
    return ops_core.context(world["path"])


def item_of(world, started):
    ctx = ctx_of(world)
    return ctx["store"].pending_get(ctx["conn"], started["pending"])


def effect_doc(world, started):
    ctx = ctx_of(world)
    return json.loads((Path(ops_step_effects.effect_dir(ctx["cfg"], started["task"], 0)) / "effect.json").read_text(encoding="ascii"))


def approve(world, started, channel="terminal", sender=None):
    item = item_of(world, started)
    return ops.approve(world["path"], started["pending"], item["payload_sha256"], channel=channel, sender=sender)


def open_decisions(world):
    ctx = ctx_of(world)
    return ctx["store"].pending_list(ctx["conn"], "open")


def writes(fake):
    return fake.writes()


def calls_of(fake):
    """Every request after the token POST, as (method, path)."""
    return [(r["method"], r["path"]) for r in fake.requests if "/token" not in r["path"] and "oauth2" not in r["path"]]


# --- add ------------------------------------------------------------------------------------------------------------------------------------


def test_a_typed_add_is_one_card_and_a_write_only_after_the_approval_of_the_hash_of_its_exact_document(world):
    google = world["google"]
    started = ops.todo_add(world["path"], "google", "comprar leite")
    assert started["status"] == "card" and started["word"] == "tasks" and started["on_cards"] is True
    assert writes(google) == [], "the preparation only reads and previews: nothing is written before the approval"
    item, doc = item_of(world, started), effect_doc(world, started)
    assert item["kind"] == "effect" and pk.said(item["title"], "TITLE_TODO_ADD") and item["payload"]["card"]
    assert item["body"] == phrases.card_text(item["payload"]["card"]) and pk.said(item["body"], "CARD_TODO_TITLE", title="comprar leite")
    assert pk.said(item["body"], "CARD_TODO_LIST", list="tarefas", service="Google Tasks")
    assert doc["effect"] == "tasks" and doc["operation"] == "add" and doc["title"] == "comprar leite" and doc["list"] == "tarefas" and doc["list_id"] == "default"
    assert doc["address"] == fg.ACCOUNT and doc["asker"] == "terminal" and item["payload_sha256"] == tasks_document.sha(effects._text(doc))
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["done"] is True and done["result"]["replayed"] is False and done["result"]["operation"] == "add"
    assert [(m, p, b) for m, p, _q, b in writes(google)] == [("POST", "/tasks/v1/lists/@default/tasks", {"title": "comprar leite"})]
    assert [t["title"] for t in google.tasks[fg.DEFAULT_LIST].values()].count("comprar leite") == 1 and google.unexpected() == []


def test_limit_55_nothing_is_written_for_another_hash_or_an_edited_effect_file(world):
    google = world["google"]
    started = ops.todo_add(world["path"], "google", "comprar leite")
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], started["pending"], "0" * 64, channel="terminal")
    ctx = ctx_of(world)
    path = Path(ops_step_effects.effect_dir(ctx["cfg"], started["task"], 0)) / effects.EFFECT_FILE
    original = path.read_text(encoding="ascii")
    path.write_text(original.replace("comprar leite", "comprar vinho"), encoding="ascii")
    with pytest.raises(ops.OpsError) as refused:
        approve(world, started)
    assert "nothing was written" in str(refused.value) and writes(google) == []
    path.write_text(original, encoding="ascii")
    assert approve(world, started)["result"]["done"] is True and len(writes(google)) == 1


def test_a_lost_answer_is_unknown_and_approving_again_finds_the_task_and_writes_nothing_twice(world):
    google = world["google"]
    started = ops.todo_add(world["path"], "google", "comprar leite")
    google.lose_answer_once = True
    with pytest.raises(ops.OpsError) as unknown:
        approve(world, started)
    assert "unknown" in str(unknown.value)
    assert [t["title"] for t in google.tasks[fg.DEFAULT_LIST].values()].count("comprar leite") == 1, "the first request landed"
    done = approve(world, started)
    assert done["result"]["done"] is True and done["result"]["replayed"] is True
    assert [t["title"] for t in google.tasks[fg.DEFAULT_LIST].values()].count("comprar leite") == 1 and google.unexpected() == []


def test_a_list_the_file_does_not_name_and_an_account_with_no_task_lists_make_nothing(world):
    google = world["google"]
    with pytest.raises(ops.OpsError) as refused:
        ops.todo_add(world["path"], "google", "comprar leite", list="compras")
    assert "compras" in str(refused.value) and "task_lists" in str(refused.value)
    assert google.requests == [] and open_decisions(world) == []
    configure(world, accounts={"google": {"address": fg.ACCOUNT}, "microsoft": MICROSOFT})
    with pytest.raises(ops.OpsError) as none:
        ops.todo_add(world["path"], "google", "comprar leite")
    assert "none are listed" in str(none.value) and google.requests == [] and open_decisions(world) == []
    configure(world, accounts={"microsoft": MICROSOFT})
    with pytest.raises(ops.OpsError) as unlisted:
        ops.todo_add(world["path"], "google", "comprar leite")
    assert "google" in str(unlisted.value) and google.requests == [] and open_decisions(world) == []


def test_a_named_list_is_written_to_by_its_id_and_the_first_one_is_the_default(world):
    google = world["google"]
    named = ops.todo_add(world["path"], "google", "comprar pão francês", list="mercado")  # validate: allow english-only -- a Portuguese line is the input under test
    assert effect_doc(world, named)["list"] == "mercado" and effect_doc(world, named)["list_id"] == fg.OTHER_LIST
    approve(world, named)
    assert [(m, p) for m, p, _q, _b in writes(google)] == [("POST", f"/tasks/v1/lists/{fg.OTHER_LIST}/tasks")]


def test_microsoft_default_list_is_resolved_to_its_id_before_the_writer_is_asked(world):
    microsoft = world["microsoft"]
    started = ops.todo_add(world["path"], "microsoft", "enviar a fatura")
    doc = effect_doc(world, started)
    assert doc["list"] == "trabalho" and doc["list_id"] == fm.DEFAULT_LIST and doc["implementation"] == "microsoft-todo" and doc["address"] == fm.ADDRESS
    assert calls_of(microsoft) == [("GET", "/v1.0/me/todo/lists")], "only the list of lists was read to find the default one"
    approve(world, started)
    assert [(m, p, b) for m, p, _q, b in writes(microsoft)] == [("POST", f"/v1.0/me/todo/lists/{fm.DEFAULT_LIST}/tasks", {"title": "enviar a fatura"})]
    assert microsoft.unexpected() == []


def test_a_title_with_a_hidden_character_or_too_long_makes_no_card(world):
    google = world["google"]
    for bad in ("comprar \u202eleite", "x" * 201, "  comprar leite", ""):
        with pytest.raises(ops.OpsError):
            ops.todo_add(world["path"], "google", bad)
    assert google.requests == [] and open_decisions(world) == []


def test_the_conversation_shell_is_never_a_carrier_of_a_write_and_the_mcp_mode_never_starts_one(world):
    for channel in ("chat", "mcp"):
        with pytest.raises(ops.OpsError):
            ops.todo_add(world["path"], "google", "comprar leite", channel=channel)
    assert world["google"].requests == [] and open_decisions(world) == []


# --- complete -------------------------------------------------------------------------------------------------------------------------------


def test_a_completion_by_the_words_of_the_title_is_one_card_and_one_patch_after_the_approval(world):
    google = world["google"]
    started = ops.todo_done(world["path"], "google", "dentista")
    assert started["status"] == "card" and started["origin"] == "grounded" and started["word"] == "tasks"
    assert writes(google) == []
    item, doc = item_of(world, started), effect_doc(world, started)
    assert pk.said(item["title"], "TITLE_TODO_DONE") and pk.said(item["body"], "CARD_TODO_NOW_TITLE", title="ligar para o dentista") and doc["task_id"] == "t2" and doc["operation"] == "complete"
    assert doc["base_etag"] == google.tasks[fg.DEFAULT_LIST]["t2"]["etag"] and doc["title"] == "ligar para o dentista" and doc["list"] == "tarefas"
    assert "t2" not in item["body"] and doc["base_etag"].strip('"') not in item["body"], "no id and no version is on the card (limit L62)"
    done = approve(world, started)
    assert done["result"]["done"] is True and done["result"]["operation"] == "complete"
    assert [(m, p, b) for m, p, _q, b in writes(google)] == [("PATCH", "/tasks/v1/lists/@default/tasks/t2", {"status": "completed"})]
    assert google.tasks[fg.DEFAULT_LIST]["t2"]["status"] == "completed" and google.tasks[fg.DEFAULT_LIST]["t1"]["status"] == "needsAction" and google.unexpected() == []


def test_limit_56_a_task_that_moved_between_the_card_and_the_approval_is_never_completed(world):
    google = world["google"]
    started = ops.todo_done(world["path"], "google", "dentista")
    google.tasks[fg.DEFAULT_LIST]["t2"]["etag"] = google.next_etag()      # edited meanwhile, by anyone
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert "not as the preparation read it" in str(stale.value) and writes(google) == []
    assert google.tasks[fg.DEFAULT_LIST]["t2"]["status"] == "needsAction"
    assert item_of(world, started)["resolution"] == "answered", "the decision is answered, and the task starts over"
    again = ops.todo_done(world["path"], "google", "dentista")
    assert approve(world, again)["result"]["done"] is True and len(writes(google)) == 1


def test_a_task_completed_meanwhile_by_someone_else_is_not_completed_again(world):
    google = world["google"]
    started = ops.todo_done(world["path"], "google", "dentista")
    task = google.tasks[fg.DEFAULT_LIST]["t2"]
    task["status"], task["etag"] = "completed", google.next_etag()
    with pytest.raises(ops.OpsError):
        approve(world, started)
    assert writes(google) == []


def test_a_task_that_is_gone_or_completed_at_the_preparation_makes_no_card(world):
    google = world["google"]
    google.tasks[fg.DEFAULT_LIST]["t2"]["status"] = "completed"
    assert ops.todo_done(world["path"], "google", "dentista")["status"] == "none", "a completed task is not an open one"
    assert open_decisions(world) == [] and writes(google) == []


def test_a_completion_by_number_answers_only_the_list_this_sender_was_shown(world):
    google = world["google"]
    assert ops.todo_done(world["path"], "google", "todo:1")["status"] == "no-list"
    listed = ops.todo_list(world["path"])
    google_rows = next(s for s in listed["services"] if s["account"] == "google")
    flat = [row["title"] for item in google_rows["lists"] for row in item["tasks"]]
    assert flat == ["comprar café", "ligar para o dentista", "comprar pão"], "numbered across the lists of the service, in the order the file names them"  # validate: allow english-only -- a Portuguese line is the input under test
    assert [row["n"] for item in google_rows["lists"] for row in item["tasks"]] == [1, 2, 3]
    started = ops.todo_done(world["path"], "google", "todo:3")
    assert started["origin"] == "listed" and effect_doc(world, started)["title"] == "comprar pão" and effect_doc(world, started)["list"] == "mercado"  # validate: allow english-only -- a Portuguese line is the input under test
    assert ops.todo_done(world["path"], "google", "todo:9")["status"] == "none"
    approve(world, started)
    assert [(m, p) for m, p, _q, _b in writes(google)] == [("PATCH", f"/tasks/v1/lists/{fg.OTHER_LIST}/tasks/t3")]


def test_several_tasks_that_fit_are_listed_and_the_list_answers_a_number(world):
    result = ops.todo_done(world["path"], "google", "comprar")
    assert result["status"] == "several" and result["count"] == 2 and [m["title"] for m in result["matches"]] == ["comprar café", "comprar pão"]  # validate: allow english-only -- a Portuguese line is the input under test
    assert open_decisions(world) == []
    started = ops.todo_done(world["path"], "google", "todo:2")
    assert effect_doc(world, started)["title"] == "comprar pão"  # validate: allow english-only -- a Portuguese line is the input under test
    assert ops.todo_done(world["path"], "google", "zzz")["status"] == "none"


def test_the_words_of_the_title_are_whole_folded_words(world):
    assert ops.todo_done(world["path"], "google", "CAFE")["status"] == "card"      # case and accent do not matter
    assert ops.todo_done(world["path"], "google", "caf")["status"] == "none", "a piece of a word is not a word"
    assert ops.todo_done(world["path"], "google", "o dentista ligar")["status"] == "card", "every word, in any order"


def test_a_task_is_completed_in_microsoft_by_its_id_after_the_default_list_was_read(world):
    microsoft = world["microsoft"]
    started = ops.todo_done(world["path"], "microsoft", "relatório")
    doc = effect_doc(world, started)
    assert doc["list_id"] == fm.DEFAULT_LIST and doc["task_id"] == "m1"
    approve(world, started)
    assert [(m, p, b) for m, p, _q, b in writes(microsoft)] == [("PATCH", f"/v1.0/me/todo/lists/{fm.DEFAULT_LIST}/tasks/m1", {"status": "completed"})]
    assert microsoft.unexpected() == []


# --- list -----------------------------------------------------------------------------------------------------------------------------------


def test_a_list_reads_live_numbers_per_service_and_never_shows_an_id(world):
    google, microsoft = world["google"], world["microsoft"]
    got = ops.todo_list(world["path"])
    assert got["status"] == "ok" and got["count"] == 4 and [s["account"] for s in got["services"]] == ["google", "microsoft"]
    assert [row["n"] for row in next(s for s in got["services"] if s["account"] == "microsoft")["lists"][0]["tasks"]] == [1], "the numbers start again for each service"
    assert writes(google) == [] and writes(microsoft) == []
    shown = json.dumps(got)
    assert "t1" not in shown and "m1" not in shown and fg.DEFAULT_LIST not in shown
    assert ops.todo_list(world["path"], "microsoft")["count"] == 1
    with pytest.raises(ops.OpsError):
        ops.todo_list(world["path"], "yahoo")


def test_a_service_that_does_not_answer_is_said_and_the_other_is_still_listed(world):
    world["microsoft"].fail_get_next = 500
    got = ops.todo_list(world["path"])
    by = {s["account"]: s for s in got["services"]}
    assert by["microsoft"]["failed"] is True and by["google"]["failed"] is False and got["status"] == "ok" and by["google"]["lists"]
    configure(world, accounts={"google": {"address": fg.ACCOUNT, "task_lists": {"tarefas": "default"}}, "microsoft": MICROSOFT})
    world["microsoft"].fail_get_next = 500
    world["google"].fail_get_next = 500
    again = ops.todo_list(world["path"])
    assert again["status"] == "unavailable" and all(s["failed"] and not s["lists"] for s in again["services"])


def test_with_no_list_set_up_nothing_is_read_and_the_status_says_so(world):
    configure(world, accounts={"google": {"address": fg.ACCOUNT}})
    before = len(world["google"].requests)
    assert ops.todo_list(world["path"]) == {"status": "no-lists", "services": [], "count": 0}
    assert len(world["google"].requests) == before


# --- who may do what ------------------------------------------------------------------------------------------------------------------------


def test_a_messaging_sender_needs_the_group_of_each_operation_and_the_approval_grant(world):
    path = world["path"]
    with pytest.raises(ops.OpsError):
        ops.todo_add(path, "google", "comprar leite", channel="messaging", sender=f"telegram:777")      # `plain`: no group
    with pytest.raises(ops.OpsError):
        ops.todo_list(path, channel="messaging", sender="telegram:999")      # `writer`: tasks-write alone does not list
    with pytest.raises(ops.OpsError):
        ops.todo_add(path, "google", "comprar leite", channel="messaging", sender="telegram:888")      # `reader`: tasks-read alone does not write
    assert world["google"].requests == [] and open_decisions(world) == []
    started = ops.todo_add(path, "google", "comprar leite", channel="messaging", sender=SENDER)
    assert effect_doc(world, started)["asker"] == SENDER
    with pytest.raises(ops.OpsError):
        approve(world, started, channel="messaging", sender="telegram:888")      # no `approve-effect-tasks`
    assert writes(world["google"]) == []
    assert approve(world, started, channel="messaging", sender=SENDER)["result"]["done"] is True


def test_completing_by_words_or_number_reads_titles_so_it_needs_the_right_to_read_beside_the_right_to_write(world):
    path = world["path"]
    with pytest.raises(ops.OpsError):
        ops.todo_done(path, "google", "dentista", channel="messaging", sender="telegram:999")      # `writer` holds tasks-write and not tasks-read
    assert world["google"].requests == [] and open_decisions(world) == []
    assert ops.todo_done(path, "google", "dentista", channel="messaging", sender=SENDER)["status"] == "card"


def test_the_list_a_number_answers_is_one_line_long_and_a_card_opened_after_it_ends_it(world):
    path, ctx = world["path"], ctx_of(world)
    ops.todo_list(path, channel="messaging", sender=SENDER)
    ops_todo.begin_turn(ctx, "messaging", SENDER)      # the line right after the list: it still answers a number
    assert ops.todo_done(path, "google", "todo:1", channel="messaging", sender=SENDER)["status"] == "card"
    ops_todo.forget_lists()
    ops.todo_list(path, channel="messaging", sender=SENDER)
    ops_todo.begin_turn(ctx, "messaging", SENDER)
    ops_todo.begin_turn(ctx, "messaging", SENDER)      # a second line after it: the list is gone
    assert ops.todo_done(path, "google", "todo:1", channel="messaging", sender=SENDER)["status"] == "no-list"
    ops_todo.forget_lists()
    ops.todo_list(path, channel="messaging", sender=SENDER)
    ops.todo_add(path, "google", "comprar leite", channel="messaging", sender=SENDER)      # a card opened after the list ends it
    assert ops.todo_done(path, "google", "todo:1", channel="messaging", sender=SENDER)["status"] == "no-list"


def test_a_list_shown_to_one_sender_answers_no_other(world):
    path = world["path"]
    ops.todo_list(path, channel="messaging", sender=SENDER)
    ctx = ctx_of(world)
    assert ops_todo._live(ctx, "messaging", SENDER) is not None
    assert ops_todo._live(ctx, "messaging", "telegram:999") is None and ops_todo._live(ctx, "terminal", None) is None
