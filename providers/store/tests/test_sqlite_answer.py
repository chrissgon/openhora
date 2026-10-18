"""Offline tests for the records of an answer run in providers/store/sqlite.py (package AQ-1, the ask operation): `answer_run_start`
opens a run on a request the question made, with the router's one-at-a-time check, and `answer_run_finish` ends it and the request
together. No column, state or trigger is new, so there is no migration. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_answer.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_answer", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

SHA = "b" * 64
SKILL = {"skill": "demo-answers", "model": "m", "adapter": "h", "skill_version": "0.1.0", "skill_sha256": SHA, "billing": "metered",
         "autonomy": "proven"}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def question(conn, text="What is the notice period?"):
    return store.request_add(conn, title="Question: " + text, text=text)["request"]


def test_an_answer_run_is_a_run_row_of_the_request_and_ending_it_makes_the_request_done(conn):
    request = question(conn)
    started = store.answer_run_start(conn, request, **SKILL)
    run = store.task_run_get(conn, started["run_id"])
    assert (run["task_id"], run["status"], run["skill"], run["web"], run["billing"], run["autonomy"]) == \
        (request, "running", "demo-answers", 0, "metered", "proven")
    assert store.task_get(conn, request)["state"] == "requested"
    done = store.answer_run_finish(conn, started["run_id"], status="ok", attempts=1, cost_usd=0.02, tokens=900, duration_ms=1500,
                                   skill_loaded=True, run_dir="/runs/1")
    assert done == {"run_id": started["run_id"], "request_id": request, "state": "done", "cancelled": False}
    ended = store.task_run_get(conn, started["run_id"])
    assert (ended["status"], ended["ending"], ended["failure"], ended["cost_usd"], ended["tokens"], ended["attempts"]) == \
        ("ok", "done", None, 0.02, 900, 1)
    assert store.task_get(conn, request)["state"] == "done"
    assert store.pending_list(conn) == []     # a question opens no decision of the person's


def test_a_failed_answer_run_cancels_its_request_by_code(conn):
    request = question(conn)
    run = store.answer_run_start(conn, request, **SKILL)["run_id"]
    done = store.answer_run_finish(conn, run, status="failed", failure="timeout", attempts=1, error="the run timed out")
    assert done["state"] == "cancelled" and done["cancelled"] is False
    ended = store.task_run_get(conn, run)
    assert (ended["status"], ended["failure"], ended["ending"], ended["error"]) == ("failed", "timeout", None, "the run timed out")
    assert store.task_get(conn, request)["state"] == "cancelled"


def test_one_conversation_model_call_runs_at_a_time_whether_it_is_a_router_run_or_an_answer_run(conn):
    first, second = question(conn), question(conn, "And the deposit?")
    run = store.answer_run_start(conn, first, **SKILL)["run_id"]
    with pytest.raises(store.StoreError, match="one router run at a time"):
        store.answer_run_start(conn, second, **SKILL)
    with pytest.raises(store.StoreError, match="one router run at a time"):
        store.route_run_start(conn, second, skill="demo-router", model="m", adapter="h")
    store.answer_run_finish(conn, run, status="ok")
    assert store.answer_run_start(conn, second, **SKILL)["request_id"] == second   # the slot is free again


def test_an_answer_run_starts_only_on_a_request_waiting_for_its_route(conn):
    request = question(conn)
    store.answer_run_finish(conn, store.answer_run_start(conn, request, **SKILL)["run_id"], status="ok")
    with pytest.raises(store.StoreError, match="is done"):
        store.answer_run_start(conn, request, **SKILL)
    with pytest.raises(store.StoreError, match="not a request"):
        task_id = store.request_add(conn, title="T", text="T.", flow="x", tasks=[{"key": "a", "skill": "demo-a", "title": "A", "text": "do a."}])["tasks"][0]["id"]
        store.answer_run_start(conn, task_id, **SKILL)


def test_a_run_ends_once_and_a_status_is_ok_or_failed_with_a_kind(conn):
    run = store.answer_run_start(conn, question(conn), **SKILL)["run_id"]
    for bad in ({"status": "ok", "failure": "timeout"}, {"status": "failed"}, {"status": "done"}, {"status": "failed", "failure": "nope"}):
        with pytest.raises(store.StoreError):
            store.answer_run_finish(conn, run, **bad)
    store.answer_run_finish(conn, run, status="ok")
    with pytest.raises(store.StoreError, match="already ended"):
        store.answer_run_finish(conn, run, status="ok")
    with pytest.raises(store.StoreError, match="no task run"):
        store.answer_run_finish(conn, 999, status="ok")


def test_a_request_being_cancelled_has_its_answer_run_recorded_cancelled(conn):
    request = question(conn)
    run = store.answer_run_start(conn, request, **SKILL)["run_id"]
    store.request_stop(conn, request, by="page")
    done = store.answer_run_finish(conn, run, status="ok", tokens=10)
    assert done["cancelled"] is True and done["state"] == "cancelled"
    assert store.task_run_get(conn, run)["status"] == "cancelled" and store.task_run_get(conn, run)["tokens"] == 10
    assert store.task_get(conn, request)["state"] == "cancelled"


def test_a_run_of_a_request_is_read_by_runs_since_with_no_agent_for_the_layer_above_to_attribute(conn):
    request = question(conn)
    run = store.answer_run_start(conn, request, **SKILL)["run_id"]
    assert store.task_runs_running(conn)[0]["task_id"] == request
    store.answer_run_finish(conn, run, status="ok")
    assert [r["id"] for r in store.runs_since(conn, "2000-01-01T00:00:00Z")] == [run]
    [row] = store.runs_since(conn, "2000-01-01T00:00:00Z")
    assert row["agent"] is None and row["request_id"] == request and row["skill"] == "demo-answers"   # the layer above attributes it


def test_a_question_and_its_run_are_one_transaction_when_no_request_is_given(conn):
    started = store.answer_run_start(conn, skill="demo-answers", model="m", adapter="h", title="Question: how long?", text="How long?")
    request = store.task_get(conn, started["request_id"])
    assert (request["state"], request["parent_id"], request["title"], request["text"]) == ("requested", None, "Question: how long?", "How long?")
    assert store.task_run_get(conn, started["run_id"])["task_id"] == started["request_id"]
    # a start that is refused leaves no request behind: the one-at-a-time check and the request are one transaction
    before = len(store.tasks_list(conn))
    with pytest.raises(store.StoreError, match="one router run at a time"):
        store.answer_run_start(conn, skill="demo-answers", model="m", adapter="h", title="Question: and then?", text="And then?")
    assert len(store.tasks_list(conn)) == before
    with pytest.raises(store.StoreError):
        store.answer_run_start(conn, skill="demo-answers", model="m", adapter="h", title=None, text="no title")
    store.answer_run_finish(conn, started["run_id"], status="ok")
    assert store.task_get(conn, started["request_id"])["state"] == "done"


def test_route_run_start_keeps_its_behaviour_after_its_checks_moved_into_a_shared_step(conn):
    request = question(conn)
    started = store.route_run_start(conn, request, skill="demo-router", model="m", adapter="h")
    assert started["request_id"] == request
    with pytest.raises(store.StoreError, match="one router run at a time"):
        store.route_run_start(conn, question(conn, "Another?"), skill="demo-router", model="m", adapter="h")
    store.route_run_finish(conn, started["run_id"], status="ok", ending="done")
    store.request_cancel(conn, request, by="test")
    with pytest.raises(store.StoreError, match="only a request waiting for its plan is routed"):
        store.route_run_start(conn, request, skill="demo-router", model="m", adapter="h")
