"""Offline tests for the step task in providers/store/sqlite.py (P5, migration 12): the columns, the three functions ported from the
media pipeline's code task and renamed (step_task_add, is_step_task, step_task_move), the engine's state, and a step task in a plan.
Every name and text below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_steps.py
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_steps", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

COLUMNS = ("step_kind", "step_args", "step_footprint", "step_state")


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def skill_plan(extra=()):
    return [{"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Do the market analysis."}, *extra]


def step_item(key="ingest-survey", depends_on=(), args=None, footprint=None):
    return {"key": key, "step": "ingest", "args": args if args is not None else {"source": "survey"}, "footprint": footprint or [],
            "title": "Ingest the survey", "text": "Bring the survey in.", "depends_on": list(depends_on)}


def pending(title="Check it"):
    return {"kind": "question", "title": title, "body": "Look at it, then answer.", "payload": {"step": {"kind": "demo", "step": "review"}}}


def test_migration_12_adds_the_four_columns_and_a_store_at_11_migrates_and_keeps_every_row(tmp_path):
    path = tmp_path / "eleven.sqlite"
    old = sqlite3.connect(path)       # a store as P4 left it: migrations 1 to 11 applied, and no more
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 12):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-15T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('Old', 'An old request.', 'planned', 'a', 'a')")
    old.execute("INSERT INTO tasks (parent_id, key, skill, agent, title, text, state, created_at, updated_at) "
                "VALUES (1, 'market', 'biz-market-analysis', 'business', 'Market', 'x', 'ready', 'a', 'a')")
    old.commit()
    old.close()
    with pytest.raises(store.StoreError) as refused:
        store.open_db(path)
    assert refused.value.code == store.EXIT_NOT_CONFIGURED
    out = store.init_db(path)
    assert out["migrated_from"] == 11 and out["applied"] == [12, 13, 14, 15, 16, 17, 18, 19, 20, 21] and out["schema_version"] == 21
    conn = store.open_db(path)
    names = [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")]
    assert all(c in names for c in COLUMNS)
    old_task = store.task_get(conn, 2)
    assert old_task["skill"] == "biz-market-analysis" and all(old_task[c] is None for c in COLUMNS)
    assert store.is_step_task(old_task) is False       # an old row keeps NULL: it is a skill task


def test_the_version_row_and_the_migrations_table_name_the_step_task():
    assert store.SCHEMA_VERSION == 21 and "step task" in store.MIGRATIONS[12][0] and "without the web" in store.MIGRATIONS[13][0]
    assert store.STEP_OWNER == "runtime"


def test_a_step_task_alone_is_added_planned_then_ready_with_its_kind_arguments_and_footprint(conn):
    made = store.step_task_add(conn, key="ingest-survey", title="Ingest the survey", text="Bring the survey in.", step="ingest",
                               args={"source": "survey", "file": "/data/survey.csv"}, footprint=["docs/b/<topic>.md", "docs/a.md"])
    assert made["state"] == "ready"
    task = store.task_get(conn, made["task"])
    assert store.is_step_task(task) and task["skill"] is None and task["agent"] == "runtime"
    assert task["parent_id"] == made["request"] and task["key"] == "ingest-survey" and task["milestone"] == 0
    assert task["step_kind"] == "ingest" and task["step_args"] == {"file": "/data/survey.csv", "source": "survey"}
    assert task["step_footprint"] == ["docs/a.md", "docs/b/<topic>.md"] and task["step_state"] is None
    request = store.task_get(conn, made["request"])
    assert request["state"] == "planned" and request["flow"] is None and request["step_kind"] is None


def test_the_arguments_are_stored_as_canonical_json_so_the_same_arguments_are_the_same_text(conn):
    one = store.step_task_add(conn, key="one", title="One", text="One.", step="ingest", args={"b": 1, "a": 2})
    two = store.step_task_add(conn, key="two", title="Two", text="Two.", step="ingest", args={"a": 2, "b": 1})
    raw = [r["step_args"] for r in conn.execute("SELECT step_args FROM tasks WHERE id IN (?, ?) ORDER BY id", (one["task"], two["task"]))]
    assert raw[0] == raw[1] == '{"a":2,"b":1}'


def test_a_step_task_is_ready_only_when_every_task_it_depends_on_is_done(conn):
    first = store.step_task_add(conn, key="first", title="First", text="First.", step="ingest")
    second = store.step_task_add(conn, key="second", title="Second", text="Second.", step="ingest", request_id=first["request"],
                                 depends_on=["first"])
    assert (first["state"], second["state"]) == ("ready", "planned")
    assert conn.execute(store.NEXT_READY_TASK).fetchone()["id"] == first["task"]       # the oldest ready task: the planned one is not offered
    claimed = store.task_claim(conn, first["task"])
    assert claimed["task"]["state"] == "running"
    assert store.task_claim(conn, second["task"]) == {"task": None, "reason": "not-ready"}
    moved = store.step_task_move(conn, first["task"], state="done")
    assert moved["ready"] == [second["task"]] and store.task_get(conn, second["task"])["state"] == "ready"
    assert conn.execute(store.NEXT_READY_TASK).fetchone()["id"] == second["task"]
    assert store.task_claim(conn, second["task"])["task"]["state"] == "running"


def test_a_step_task_and_a_skill_task_wait_for_each_other_under_depends_on(conn):
    request = store.request_add(conn, title="Mixed", text="A mixed request.", flow="mixed", tasks=skill_plan())
    market = request["tasks"][0]["id"]
    step = store.step_task_add(conn, key="after-market", title="After", text="After.", step="ingest",
                               request_id=request["request"], depends_on=["market"])
    assert step["state"] == "planned"
    profile = store.tasks_add(conn, request["request"], [{"key": "profile", "skill": "biz-icp-positioning", "title": "Profile",
                                                          "text": "Choose.", "depends_on": ["after-market"]}])["tasks"][0]["id"]
    assert store.task_get(conn, profile)["state"] == "planned"
    store.task_claim(conn, market)
    run = store.task_run_start(conn, market, skill="biz-market-analysis", model="m", adapter="h")
    waiting = store.task_run_finish(conn, run["run_id"], status="ok", ending="done", task_state="waiting",
                                    pending={"kind": "review", "title": "t", "body": "b"})
    assert store.pending_resolve(conn, waiting["pending_id"], resolution="released", by="user")["ready"] == [step["task"]]
    store.task_claim(conn, step["task"])
    assert store.step_task_move(conn, step["task"], state="done")["ready"] == [profile]


def test_a_request_whose_tasks_are_all_done_is_done_and_a_step_task_counts(conn):
    made = store.step_task_add(conn, key="only", title="Only", text="Only.", step="ingest")
    store.task_claim(conn, made["task"])
    store.step_task_move(conn, made["task"], state="done")
    assert store.task_get(conn, made["request"])["state"] == "done"


def test_a_step_task_joins_a_planned_request_and_a_done_request_gets_work_again(conn):
    made = store.step_task_add(conn, key="a", title="A", text="A.", step="ingest")
    store.task_claim(conn, made["task"])
    store.step_task_move(conn, made["task"], state="done")
    again = store.step_task_add(conn, key="b", title="B", text="B.", step="ingest", request_id=made["request"])
    assert store.task_get(conn, made["request"])["state"] == "planned" and again["state"] == "ready"
    with pytest.raises(store.StoreError, match="already has a task 'b'"):
        store.step_task_add(conn, key="b", title="B", text="B.", step="ingest", request_id=made["request"])
    requested = store.request_add(conn, title="Waiting", text="It waits for its route.")["request"]
    with pytest.raises(store.StoreError, match="requested"):
        store.step_task_add(conn, key="c", title="C", text="C.", step="ingest", request_id=requested)


@pytest.mark.parametrize("bad", [
    {"step": "Ingest"}, {"step": "two words"}, {"step": ""}, {"args": [1]}, {"args": {"n": float("nan")}},
    {"footprint": ["/etc/passwd"]}, {"footprint": ["a/../b"]}, {"footprint": ["a b"]}, {"footprint": "docs/a.md"},
    {"footprint": ["docs/a.md", "docs/a.md"]}, {"footprint": [f"docs/f{i}.md" for i in range(21)]},
    {"key": "Bad Key"}, {"title": ""}, {"text": "  "}])
def test_a_step_task_with_a_bad_kind_arguments_footprint_or_name_is_refused_and_nothing_is_stored(conn, bad):
    fields = {"key": "ok", "title": "Ok", "text": "Ok.", "step": "ingest", "args": {}, "footprint": []}
    fields.update(bad)
    with pytest.raises(store.StoreError):
        store.step_task_add(conn, **fields)
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_the_arguments_over_the_cap_are_refused(conn):
    with pytest.raises(store.StoreError, match="cap"):
        store.step_task_add(conn, key="big", title="Big", text="Big.", step="ingest", args={"x": "y" * store.STEP_ARGS_MAX})


def test_step_task_move_goes_running_waiting_with_a_decision_failed_and_done_and_stores_the_state_with_the_move(conn):
    made = store.step_task_add(conn, key="s", title="S", text="S.", step="demo")
    task = made["task"]
    store.task_claim(conn, task)
    waiting = store.step_task_move(conn, task, state="waiting", pending=pending(), step_state={"version": 1, "steps": {"review": "waiting"}})
    assert waiting["state"] == "waiting" and waiting["pending_id"]
    row = store.task_get(conn, task)
    assert row["state"] == "waiting" and row["step_state"] == {"steps": {"review": "waiting"}, "version": 1}
    opened = store.pending_get(conn, waiting["pending_id"])
    assert opened["status"] == "open" and opened["run_id"] is None and opened["kind"] == "question"
    assert opened["payload"]["step"] == {"kind": "demo", "step": "review"}
    # the person answers: the standard resolution makes the task ready, with no run behind it
    answered = store.pending_resolve(conn, waiting["pending_id"], resolution="answered", by="user", answer="Looks right.")
    assert answered["task_state"] == "ready"
    store.task_claim(conn, task)
    failed = store.step_task_move(conn, task, state="failed", note="demo: timeout", step_state={"version": 1, "steps": {}})
    assert failed["state"] == "failed" and store.task_get(conn, task)["note"] == "demo: timeout"
    assert store.task_retry(conn, task)["state"] == "ready"
    assert store.task_get(conn, task)["step_state"] == {"steps": {}, "version": 1}      # a retry keeps the progress
    store.task_claim(conn, task)
    assert store.step_task_move(conn, task, state="done")["state"] == "done"
    with pytest.raises(store.StoreError, match="does not move"):
        store.step_task_move(conn, task, state="running")


def test_step_task_move_cancels_the_open_decisions_when_the_task_moves_except_the_one_it_resolves(conn):
    made = store.step_task_add(conn, key="s", title="S", text="S.", step="demo")
    store.task_claim(conn, made["task"])
    one = store.step_task_move(conn, made["task"], state="waiting", pending=pending("One"))["pending_id"]
    two = store.step_task_move(conn, made["task"], state="waiting", pending=pending("Two"))["pending_id"]
    assert store.pending_get(conn, one)["status"] == "cancelled" and store.pending_get(conn, two)["status"] == "open"
    store.step_task_move(conn, made["task"], state="running", resolve={"id": two, "answer": "Done."}, by="user")
    item = store.pending_get(conn, two)
    assert item["status"] == "resolved" and item["resolution"] == "answered" and item["resolved_by"] == "user"
    with pytest.raises(store.StoreError, match="not open"):
        store.step_task_move(conn, made["task"], state="running", resolve={"id": two, "answer": "Again."})


def test_step_task_move_refuses_a_wrong_pairing_a_skill_task_and_a_cancelled_task(conn):
    made = store.step_task_add(conn, key="s", title="S", text="S.", step="demo")
    with pytest.raises(store.StoreError):
        store.step_task_move(conn, made["task"], state="waiting")                # waiting needs a decision
    with pytest.raises(store.StoreError):
        store.step_task_move(conn, made["task"], state="failed", pending=pending())   # failed refuses one
    with pytest.raises(store.StoreError):
        store.step_task_move(conn, made["task"], state="ready")
    skill = store.request_add(conn, title="Skill", text="A skill request.", flow="f", tasks=skill_plan())["tasks"][0]["id"]
    with pytest.raises(store.StoreError, match="not a step task"):
        store.step_task_move(conn, skill, state="running")
    store.request_cancel(conn, made["request"], by="user")
    with pytest.raises(store.StoreError, match="cancelled"):
        store.step_task_move(conn, made["task"], state="running")
    with pytest.raises(store.StoreError, match="cancelled"):
        store.step_state_save(conn, made["task"], {"version": 1})


def test_step_state_save_stores_the_progress_without_moving_the_task_and_is_capped(conn):
    made = store.step_task_add(conn, key="s", title="S", text="S.", step="demo")
    store.task_claim(conn, made["task"])
    store.step_state_save(conn, made["task"], {"version": 1, "steps": {"one": {"status": "done"}}})
    row = store.task_get(conn, made["task"])
    assert row["state"] == "running" and row["step_state"]["steps"]["one"]["status"] == "done"
    with pytest.raises(store.StoreError, match="cap"):
        store.step_state_save(conn, made["task"], {"x": "y" * store.STEP_STATE_MAX})
    skill = store.request_add(conn, title="Skill", text="A skill request.", flow="f", tasks=skill_plan())["tasks"][0]["id"]
    with pytest.raises(store.StoreError, match="not a step task"):
        store.step_state_save(conn, skill, {})


def test_a_step_task_in_a_plan_is_created_with_the_owner_the_kind_the_arguments_and_the_footprint(conn):
    plan = skill_plan([step_item(depends_on=["market"], args={"source": "survey"}, footprint=["docs/x/<topic>.md"])])
    made = store.request_add(conn, title="Plan", text="A plan with a step.", flow="mixed", tasks=plan)
    by_key = {t["key"]: t for t in store.tasks_list(conn, made["request"]) if t["parent_id"]}
    step = by_key["ingest-survey"]
    assert step["state"] == "planned" and step["agent"] == "runtime" and step["skill"] is None
    assert step["step_kind"] == "ingest" and step["step_args"] == {"source": "survey"} and step["step_footprint"] == ["docs/x/<topic>.md"]
    assert step["depends_on"] == [by_key["market"]["id"]] and by_key["market"]["state"] == "ready" and by_key["market"]["step_kind"] is None


def test_a_plan_approval_creates_the_step_task_of_the_approved_payload(conn):
    request = store.request_add(conn, title="Ingest", text="Ingest the survey.")["request"]
    payload = {"flow": "ingest-flow", "tasks": [step_item()]}
    opened = store.plan_open(conn, request, title="Plan", body="Plan body.", payload=payload)
    done = store.plan_approve(conn, opened["pending_id"], by="user")
    assert done["tasks"][0]["skill"] is None and done["tasks"][0]["state"] == "ready" and done["ready"]
    assert store.is_step_task(store.task_get(conn, done["tasks"][0]["id"]))


def test_a_plan_item_that_mixes_a_skill_a_foreign_agent_or_sources_with_a_step_is_refused(conn):
    for bad in ({"skill": "biz-market-analysis"}, {"agent": "business"}, {"sources": ["survey"]}):
        with pytest.raises(store.StoreError):
            store.request_add(conn, title="Bad", text="Bad plan.", flow="f", tasks=[dict(step_item(), **bad)])
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_a_waiting_step_task_holds_no_slot_and_a_running_one_does_while_a_waiting_skill_task_still_does(conn):
    made = store.step_task_add(conn, key="s", title="S", text="S.", step="demo")
    store.task_claim(conn, made["task"])
    assert store.task_slot_holders(conn) == [{"id": made["task"], "agent": "runtime"}]
    store.step_task_move(conn, made["task"], state="waiting", pending=pending())
    assert store.task_slot_holders(conn) == []
    skill = store.request_add(conn, title="Skill", text="A skill request.", flow="f", tasks=[dict(skill_plan()[0], agent="business")])
    task = skill["tasks"][0]["id"]
    store.task_claim(conn, task)
    run = store.task_run_start(conn, task, skill="biz-market-analysis", model="m", adapter="h")
    store.task_run_finish(conn, run["run_id"], status="ok", ending="question", task_state="waiting", pending={"kind": "question", "title": "t", "body": "b"})
    assert store.task_slot_holders(conn) == [{"id": task, "agent": "business"}]


def test_a_step_task_that_died_running_is_failed_as_any_orphan_and_keeps_its_state(conn):
    made = store.step_task_add(conn, key="s", title="S", text="S.", step="demo")
    store.task_claim(conn, made["task"])
    store.step_state_save(conn, made["task"], {"version": 1, "steps": {"one": {"status": "done"}}})
    out = store.task_fail_orphans(conn, [made["task"]], [], "the run was interrupted")
    assert out == {"tasks": [made["task"]], "runs": []}
    row = store.task_get(conn, made["task"])
    assert row["state"] == "failed" and row["step_state"]["steps"]["one"]["status"] == "done"


def test_the_export_reads_the_step_columns_as_objects(conn, tmp_path, capsys):
    made = store.step_task_add(conn, key="s", title="S", text="S.", step="ingest", args={"source": "a"}, footprint=["docs/a.md"])
    store.task_claim(conn, made["task"])
    store.step_state_save(conn, made["task"], {"version": 1})
    import argparse
    assert store.cmd_export(argparse.Namespace(db=str(tmp_path / "state" / "tasks.sqlite"), since=None)) == 0
    tasks = json.loads(capsys.readouterr().out)["tasks"]
    step = next(t for t in tasks if t["step_kind"] == "ingest")
    assert step["step_args"] == {"source": "a"} and step["step_footprint"] == ["docs/a.md"] and step["step_state"] == {"version": 1}
