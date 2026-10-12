"""Offline tests for the derived waits between requests (migration 8 of providers/store/sqlite.py): the after_request
column of a request and the task_waits table, and the functions that are their contract. Every name and text is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_waits.py

The runtime derives the waits (runtime/plan.py); the store only keeps them and refuses to give out a task that has an open
one. Each test has its own database and calls the functions in process, the way runtime/ops.py does.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_waits", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def one(conn, skill, *, after=None, waits=None):
    """A request whose plan is one task of this skill (key: the skill's name). Returns (request id, task id)."""
    out = store.request_add(conn, title=skill, text="x", flow="demo", after=after, waits=waits,
                            tasks=[{"key": skill, "skill": skill, "title": skill, "text": "x"}])
    return out["request"], out["tasks"][0]["id"]


def state(conn, task_id):
    return store.task_get(conn, task_id)["state"]


def finish(conn, task_id):
    """Run a task to its review and release it: the task is done."""
    claimed = store.task_claim(conn, task_id)["task"]
    run = store.task_run_start(conn, claimed["id"], skill=claimed["skill"], model="m", adapter="h")
    done = store.task_run_finish(conn, run["run_id"], status="ok", ending="done", task_state="waiting",
                                 pending={"kind": "review", "title": "t", "body": "draft"})
    return store.pending_resolve(conn, done["pending_id"], resolution="released", by="user")


def input_wait(key, awaited, path="docs/brand/identity.md"):
    return {"key": key, "kind": "input", "awaited_id": awaited, "path": path, "reason": f"{path}, written by task #{awaited}"}


def test_migration_8_adds_the_after_column_the_waits_table_and_a_trigger_that_refuses_to_delete(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
    assert "after_request" in columns
    assert {r[1] for r in conn.execute("PRAGMA table_info(task_waits)")} == {
        "id", "task_id", "awaited_id", "kind", "path", "reason", "status", "created_at", "ended_at", "ended_by"}
    _, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        with conn:
            conn.execute("DELETE FROM task_waits")


def test_a_task_that_begins_with_a_wait_is_planned_and_no_function_of_the_store_gives_it_out(conn):
    _, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    assert state(conn, design) == "planned" and state(conn, brand) == "ready"
    assert store.task_peek_next(conn)["task"]["id"] == brand
    assert store.task_claim(conn, design) == {"task": None, "running": None, "reason": "not-ready"}
    # The task is made `ready` by hand, as a bug elsewhere could: the store still refuses to give it out.
    with conn:
        conn.execute("UPDATE tasks SET state = 'ready' WHERE id = ?", (design,))
    assert store.task_claim(conn, design) == {"task": None, "running": None, "reason": "waiting"}
    assert store.task_claim_next(conn)["task"]["id"] == brand


def test_the_wait_is_read_with_its_reason_and_the_request_of_the_awaited_task(conn):
    request, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    [wait] = store.waits_list(conn)
    assert (wait["task_id"], wait["awaited_id"], wait["kind"], wait["status"], wait["request_id"]) == (
        design, brand, "input", "open", request)
    assert wait["reason"] == f"docs/brand/identity.md, written by task #{brand}" and wait["path"] == "docs/brand/identity.md"
    assert store.waits_list(conn, task_id=brand) == [] and store.waits_list(conn, status="cleared") == []
    with pytest.raises(store.StoreError):
        store.waits_list(conn, status="nope")


def test_the_wait_clears_when_the_awaited_task_is_done_and_the_task_becomes_ready(conn):
    _, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    out = finish(conn, brand)
    assert design in out["ready"] and state(conn, design) == "ready"
    [wait] = store.waits_list(conn, status="all")
    assert wait["status"] == "cleared" and wait["ended_by"] == "runtime" and wait["ended_at"]


def test_the_wait_clears_when_the_awaited_request_is_cancelled(conn):
    request, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    store.request_cancel(conn, request, by="user")
    assert state(conn, design) == "ready" and store.waits_list(conn) == []


def test_a_cancelled_task_waits_for_nothing_and_its_wait_ends_with_it(conn):
    _, brand = one(conn, "brand-identity")
    request, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    store.request_cancel(conn, request, by="user")
    assert state(conn, design) == "cancelled" and store.waits_list(conn) == []
    [wait] = store.waits_list(conn, status="cleared")
    assert wait["task_id"] == design and wait["ended_by"] == "runtime"
    assert state(conn, brand) == "ready"  # the task it waited for is untouched


def test_a_task_that_failed_keeps_the_task_that_waits_for_it_waiting(conn):
    _, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    claimed = store.task_claim(conn, brand)["task"]
    run = store.task_run_start(conn, claimed["id"], skill=claimed["skill"], model="m", adapter="h")
    store.task_run_finish(conn, run["run_id"], status="failed", failure="timeout", task_state="failed")
    assert state(conn, design) == "planned" and len(store.waits_list(conn)) == 1


def test_a_wait_on_a_task_of_the_same_request_is_refused_and_so_is_a_kind_that_does_not_fit(conn):
    request, first = one(conn, "brand-identity")
    with pytest.raises(store.StoreError, match="another request"):
        store.request_add(conn, title="t", text="x", flow="demo", waits=[input_wait("a", 9999)],
                          tasks=[{"key": "a", "skill": "s", "title": "t", "text": "x"}])
    with pytest.raises(store.StoreError, match="another request"):
        store.request_add(conn, title="t", text="x", flow="demo",
                          waits=[{"key": "a", "kind": "after", "awaited_id": first, "reason": "after request"}],
                          tasks=[{"key": "a", "skill": "s", "title": "t", "text": "x"}])  # after awaits a request
    with pytest.raises(store.StoreError):
        store.request_add(conn, title="t", text="x", flow="demo", waits=[dict(input_wait("zzz", first))],
                          tasks=[{"key": "a", "skill": "s", "title": "t", "text": "x"}])  # a key the plan lacks
    assert [t["id"] for t in store.tasks_list(conn)] == [request, first]  # nothing of the refused calls was kept


def test_an_after_request_holds_every_task_of_the_request_until_that_request_is_done(conn):
    first, brand = one(conn, "brand-identity")
    wait = {"key": "design-system", "kind": "after", "awaited_id": first, "reason": f"after request #{first}"}
    second, design = one(conn, "design-system", after=first, waits=[wait])
    assert store.task_get(conn, second)["after_request"] == first and state(conn, design) == "planned"
    [row] = store.waits_list(conn)
    assert (row["kind"], row["awaited_id"], row["request_id"], row["path"]) == ("after", first, first, None)
    finish(conn, brand)  # the first request is done with its only task
    assert state(conn, first) == "done" and state(conn, design) == "ready" and store.waits_list(conn) == []


def test_after_names_a_request_other_than_the_one_being_made(conn):
    request, task = one(conn, "brand-identity")
    for bad in (task, 9999, request + 100, True, "2"):
        with pytest.raises(store.StoreError):
            store.request_add(conn, title="t", text="x", after=bad)
    assert store.request_add(conn, title="t", text="x", after=request)["state"] == "requested"
    with pytest.raises(store.StoreError, match="itself"):
        store.request_after_set(conn, request, request)


def test_request_after_set_sets_clears_and_refuses_a_request_that_is_over(conn):
    first, _ = one(conn, "brand-identity")
    second = store.request_add(conn, title="t", text="x")["request"]
    assert store.request_after_set(conn, second, first)["after_request"] == first
    assert store.request_after_set(conn, second, None)["after_request"] is None
    store.request_cancel(conn, first, by="user")
    with pytest.raises(store.StoreError, match="cancelled"):
        store.request_after_set(conn, first, second)


def test_waits_sync_opens_a_wait_for_a_task_that_was_ready_and_sends_it_back_to_planned(conn):
    _, design = one(conn, "design-system")
    assert state(conn, design) == "ready"
    _, brand = one(conn, "brand-identity")
    want = [{"task_id": design, "awaited_id": brand, "kind": "input", "path": "docs/brand/identity.md",
             "reason": "docs/brand/identity.md, written by task #%d" % brand}]
    out = store.waits_sync(conn, want, [design, brand])
    assert out["demoted"] == [design] and len(out["opened"]) == 1 and state(conn, design) == "planned"
    assert store.task_claim_next(conn)["task"]["id"] == brand
    # The same derivation again changes nothing.
    again = store.waits_sync(conn, want, [design, brand])
    assert again["opened"] == [] and again["cleared"] == [] and again["demoted"] == []


def test_waits_sync_clears_a_wait_that_is_no_longer_derived_and_frees_the_task(conn):
    _, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    out = store.waits_sync(conn, [], [design, brand])  # the file appeared: the runtime derives no wait
    assert len(out["cleared"]) == 1 and out["ready"] == [design] and state(conn, design) == "ready"
    [wait] = store.waits_list(conn, status="all")
    assert wait["status"] == "cleared" and wait["ended_by"] == "runtime"


def test_waits_sync_touches_only_the_tasks_it_evaluated_and_only_while_they_have_not_started(conn):
    _, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    other_wait = input_wait("mkt-calendar", brand, "docs/brand/voice.md")
    _, third = one(conn, "mkt-calendar", waits=[other_wait])
    out = store.waits_sync(conn, [], [design])  # only the design task is evaluated
    assert len(out["cleared"]) == 1 and state(conn, third) == "planned" and len(store.waits_list(conn)) == 1
    claimed = store.task_claim(conn, design)["task"]  # design is running now: nothing may be derived for it
    want = [{"task_id": claimed["id"], "awaited_id": brand, "kind": "input", "path": "docs/brand/identity.md",
             "reason": "docs/brand/identity.md, written by task #%d" % brand}]
    assert store.waits_sync(conn, want, [design])["opened"] == [] and state(conn, design) == "running"


def test_waits_sync_refuses_a_wait_on_itself_and_a_kind_that_does_not_fit_the_awaited_row(conn):
    request, task = one(conn, "brand-identity")
    base = {"task_id": task, "awaited_id": task, "kind": "input", "path": "docs/brand/identity.md", "reason": "r"}
    with pytest.raises(store.StoreError):
        store.waits_sync(conn, [base], [task])
    with pytest.raises(store.StoreError):
        store.waits_sync(conn, [dict(base, awaited_id=request)], [task])  # an input wait awaits a task
    with pytest.raises(store.StoreError):
        store.waits_sync(conn, [dict(base, kind="go_ahead")], [task])
    assert store.waits_list(conn, status="all") == []


def test_the_go_ahead_at_approval_drops_the_derived_wait_and_remembers_the_decision(conn):
    _, brand = one(conn, "brand-identity")
    request = store.request_add(conn, title="Design", text="x")["request"]
    opened = store.plan_open(conn, request, title="Plan", body="b", payload={
        "flow": "demo", "tasks": [{"key": "design-system", "skill": "design-system", "title": "D", "text": "x",
                                   "depends_on": [], "milestone": False}], "plan_sha256": "0" * 64})
    out = store.plan_approve(conn, opened["pending_id"], by="user", waits=[input_wait("design-system", brand)],
                             go_ahead=["design-system"])
    design = out["tasks"][0]["id"]
    assert out["ready"] == [design] and state(conn, design) == "ready"
    rows = {(w["kind"], w["status"]): w for w in store.waits_list(conn, status="all")}
    assert set(rows) == {("input", "dropped")} and rows[("input", "dropped")]["ended_by"] == "user"
    # The decision stands when the runtime derives the same wait again: the same path, the same awaited task.
    want = [{"task_id": design, "awaited_id": brand, "kind": "input", "path": "docs/brand/identity.md", "reason": "r"}]
    assert store.waits_sync(conn, want, [design])["opened"] == [] and state(conn, design) == "ready"
    # A new writer of the same path, or another path, is another wait: the person agreed to the waits they were shown.
    _, other = one(conn, "brand-identity")
    again = store.waits_sync(conn, [dict(want[0], awaited_id=other)], [design])
    assert len(again["opened"]) == 1 and again["demoted"] == [design] and state(conn, design) == "planned"
    third = [dict(want[0], awaited_id=brand, path="docs/brand/voice.md")]
    assert len(store.waits_sync(conn, third, [design])["opened"]) == 1


def test_a_go_ahead_names_a_task_of_the_plan(conn):
    request = store.request_add(conn, title="Design", text="x")["request"]
    opened = store.plan_open(conn, request, title="Plan", body="b", payload={
        "flow": "demo", "tasks": [{"key": "design-system", "skill": "design-system", "title": "D", "text": "x",
                                   "depends_on": [], "milestone": False}], "plan_sha256": "0" * 64})
    with pytest.raises(store.StoreError, match="not a task of the plan"):
        store.plan_approve(conn, opened["pending_id"], by="user", go_ahead=["brand-identity"])
    assert store.pending_get(conn, opened["pending_id"])["status"] == "open" and len(store.tasks_list(conn)) == 1


def test_an_approved_plan_begins_with_its_waits_in_the_same_transaction(conn):
    _, brand = one(conn, "brand-identity")
    request = store.request_add(conn, title="Design", text="x")["request"]
    opened = store.plan_open(conn, request, title="Plan", body="b", payload={
        "flow": "demo", "tasks": [{"key": "design-system", "skill": "design-system", "title": "D", "text": "x",
                                   "depends_on": [], "milestone": False}], "plan_sha256": "0" * 64})
    out = store.plan_approve(conn, opened["pending_id"], by="user", waits=[input_wait("design-system", brand)])
    assert out["ready"] == [] and [t["state"] for t in out["tasks"]] == ["planned"]
    assert store.task_peek_next(conn)["task"]["id"] == brand


def test_a_request_from_the_board_keeps_the_request_its_words_say_it_runs_after(conn):
    first, _ = one(conn, "brand-identity")
    made = store.request_from_board(conn, title="Design", text="x after #%d" % first, remote_id="r1", remote_version="v1",
                                    by="board", after=first)
    assert store.task_get(conn, made["request"])["after_request"] == first
    with pytest.raises(store.StoreError):
        store.request_from_board(conn, title="t", text="x", remote_id="r2", remote_version="v1", by="board", after=9999)


def test_the_export_lists_the_waits(tmp_path):
    path = tmp_path / "s.sqlite"
    store.init_db(path)
    c = store.open_db(path)
    _, brand = one(c, "brand-identity")
    one(c, "design-system", waits=[input_wait("design-system", brand)])
    rows = c.execute("SELECT COUNT(*) FROM task_waits").fetchone()[0]
    assert rows == 1 and any(q[0] == "task_waits" for q in store.EXPORT_QUERIES)


def test_go_ahead_on_a_created_task_drops_its_input_waits_and_remembers_the_decision(conn):
    _, brand = one(conn, "brand-identity")
    _, design = one(conn, "design-system", waits=[input_wait("design-system", brand)])
    out = store.waits_go_ahead(conn, design, by="user")
    assert out["state"] == "ready" and out["paths"] == ["docs/brand/identity.md"] and design in out["ready"]
    assert out["reasons"] == [f"docs/brand/identity.md, written by task #{brand}"] and len(out["dropped"]) == 1
    assert store.waits_list(conn) == []
    kinds = {(w["kind"], w["status"], w["ended_by"]) for w in store.waits_list(conn, status="all")}
    assert kinds == {("input", "dropped", "user")}
    # The runtime deriving the same wait again does not bring it back; a new writer of the path is another wait.
    want = [{"task_id": design, "awaited_id": brand, "kind": "input", "path": "docs/brand/identity.md", "reason": "r"}]
    assert store.waits_sync(conn, want, [design])["opened"] == [] and state(conn, design) == "ready"
    replaced_request, replacement = one(conn, "brand-identity")
    assert len(store.waits_sync(conn, [dict(want[0], awaited_id=replacement)], [design])["opened"]) == 1
    assert state(conn, design) == "planned" and replaced_request


def test_go_ahead_leaves_an_after_override_and_refuses_a_task_that_waits_only_for_a_request(conn):
    first, brand = one(conn, "brand-identity")
    after = {"key": "design-system", "kind": "after", "awaited_id": first, "reason": f"after request #{first}"}
    _, design = one(conn, "design-system", after=first, waits=[after])
    with pytest.raises(store.StoreError, match="after"):
        store.waits_go_ahead(conn, design, by="user")
    assert state(conn, design) == "planned" and len(store.waits_list(conn)) == 1
    # A task held by both keeps the override when the derived wait is dropped.
    _, third = one(conn, "mkt-calendar", after=first, waits=[
        {"key": "mkt-calendar", "kind": "after", "awaited_id": first, "reason": "after"}, input_wait("mkt-calendar", brand)])
    store.waits_go_ahead(conn, third, by="user")
    assert [w["kind"] for w in store.waits_list(conn, task_id=third)] == ["after"] and state(conn, third) == "planned"


def test_go_ahead_is_refused_for_a_task_that_does_not_wait_and_for_a_request(conn):
    request, brand = one(conn, "brand-identity")
    for target in (brand, request, 9999):
        with pytest.raises(store.StoreError):
            store.waits_go_ahead(conn, target, by="user")
    assert store.waits_list(conn, status="all") == []


def test_a_go_ahead_on_a_key_with_no_input_wait_is_refused_and_the_plan_stays_open(conn):
    first, brand = one(conn, "brand-identity")
    request = store.request_add(conn, title="Design", text="x")["request"]
    opened = store.plan_open(conn, request, title="Plan", body="b", payload={
        "flow": "demo", "tasks": [{"key": "design-system", "skill": "design-system", "title": "D", "text": "x",
                                   "depends_on": [], "milestone": False}], "plan_sha256": "0" * 64})
    with pytest.raises(store.StoreError, match="waits for no task to derive"):
        store.plan_approve(conn, opened["pending_id"], by="user", go_ahead=["design-system"])
    after = {"key": "design-system", "kind": "after", "awaited_id": first, "reason": "after"}
    with pytest.raises(store.StoreError, match="waits for no task to derive"):  # an after is not a derived wait
        store.plan_approve(conn, opened["pending_id"], by="user", waits=[after], go_ahead=["design-system"])
    assert store.pending_get(conn, opened["pending_id"])["status"] == "open" and len(store.tasks_list(conn)) == 3 and brand


def test_go_ahead_with_after_drops_the_after_wait_of_that_task_only_and_it_stays_dropped(conn):
    first, brand = one(conn, "brand-identity")
    wait = {"key": "design-system", "kind": "after", "awaited_id": first, "reason": f"after request #{first}"}
    second, design = one(conn, "design-system", after=first, waits=[wait])
    with pytest.raises(store.StoreError, match="no request"):
        store.waits_go_ahead(conn, brand, by="user", after=True)
    out = store.waits_go_ahead(conn, design, by="user", after=True)
    assert out["state"] == "ready" and store.waits_list(conn) == []
    want = [{"task_id": design, "awaited_id": first, "kind": "after", "path": None, "reason": "r"}]
    assert store.waits_sync(conn, want, [design])["opened"] == [] and store.task_get(conn, second)["after_request"] == first


def test_a_retried_task_and_added_sub_tasks_begin_with_their_waits_in_the_same_transaction(conn):
    _, brand = one(conn, "brand-identity")
    request, design = one(conn, "design-system")
    claimed = store.task_claim(conn, design)["task"]
    run = store.task_run_start(conn, claimed["id"], skill=claimed["skill"], model="m", adapter="h")
    store.task_run_finish(conn, run["run_id"], status="failed", failure="timeout", task_state="failed")
    wait = {"kind": "input", "awaited_id": brand, "path": "docs/brand/identity.md", "reason": "r"}
    out = store.task_retry(conn, design, waits=[wait])
    assert out["state"] == "planned" and state(conn, design) == "planned" and len(store.waits_list(conn)) == 1
    added = store.tasks_add(conn, request, [{"key": "more", "skill": "s", "title": "t", "text": "x"}],
                            waits=[dict(wait, key="more")])
    assert [t["state"] for t in added["tasks"]] == ["planned"] and len(store.waits_list(conn)) == 2
    with pytest.raises(store.StoreError):  # a wait on a task of the task's own request is refused
        store.task_retry(conn, store.tasks_list(conn, request)[1]["id"], waits=[wait])
