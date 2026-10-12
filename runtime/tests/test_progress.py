"""Tests of runtime/progress.py and the operation `progress` (stage 6, WP-6.2): progress and the summary of a period are
computed from the store's records, and no number is estimated. Rows are plain dictionaries written here; the
operation runs on the stand-in tree. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_progress.py
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys

import pytest

import standin_tree as st

progress = st.load("progress")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def at(days_ago: float = 0, hours_ago: float = 0) -> str:
    return (NOW - datetime.timedelta(days=days_ago, hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


REQUESTS = [{"id": 12, "parent_id": None, "title": "Brand", "state": "planned"},
            {"id": 20, "parent_id": None, "title": "Old", "state": "done"},
            {"id": 30, "parent_id": None, "title": "Dropped", "state": "cancelled"}]
TASKS = REQUESTS + [
    {"id": 13, "parent_id": 12, "title": "Strategy", "skill": "brand-strategy", "state": "done", "note": None},
    {"id": 14, "parent_id": 12, "title": "Name", "skill": "brand-name", "state": "waiting", "note": None},
    {"id": 15, "parent_id": 12, "title": "Identity", "skill": "brand-identity", "state": "ready", "note": None},
    {"id": 16, "parent_id": 12, "title": "Voice", "skill": "brand-voice", "state": "failed", "note": "timeout"},
    {"id": 17, "parent_id": 12, "title": "Guide", "skill": "brand-guidelines", "state": "ready", "note": None},
    {"id": 21, "parent_id": 20, "title": "Market", "skill": "biz-market-analysis", "state": "done", "note": None}]


def test_the_period_is_seven_days_by_default_and_takes_days_or_a_date():
    assert progress.window(None, NOW) == (NOW - datetime.timedelta(days=7), NOW)
    assert progress.window("3d", NOW) == (NOW - datetime.timedelta(days=3), NOW)
    assert progress.window("365d", NOW)[0] == NOW - datetime.timedelta(days=365)
    assert progress.window("2026-11-02", NOW) == (datetime.datetime(2026, 11, 2, tzinfo=UTC), NOW)


def test_a_period_in_another_form_is_refused_with_the_three_forms():
    for bad in ("0d", "366d", "week", "2026-13-01", "-3d", "3 d", "2026/11/02"):
        with pytest.raises(ValueError) as refused:
            progress.window(bad, NOW)
        assert "<n>d" in str(refused.value) and "YYYY-MM-DD" in str(refused.value) and "7 days" in str(refused.value)


def test_progress_counts_each_request_from_its_task_rows_and_nothing_else():
    out = progress.progress(REQUESTS, TASKS, [], NOW)
    assert out["requests"] == [{"id": 12, "title": "Brand", "state": "planned", "total": 5, "done": 1, "running": 0,
                                "waiting": 1, "blocked": 0, "failed": 1, "next": [15, 17]}]
    assert out["stuck"] == [{"task_id": 16, "state": "failed", "note": "timeout"}]
    assert progress.progress([], [], [], NOW) == {"requests": [], "waiting_for_you": [], "stuck": []}


def test_what_waits_for_the_person_is_listed_oldest_first_with_its_age():
    pending = [{"id": 31, "kind": "review", "task_id": 14, "title": "Brand name", "status": "open",
                "created_at": at(hours_ago=5.5)},
               {"id": 29, "kind": "question", "task_id": 15, "title": "Which colours", "status": "open",
                "created_at": at(days_ago=2)},
               {"id": 28, "kind": "review", "task_id": 13, "title": "Strategy", "status": "resolved",
                "created_at": at(days_ago=3)}]
    out = progress.progress(REQUESTS, TASKS, pending, NOW)["waiting_for_you"]
    assert out == [{"pending_id": 29, "kind": "question", "task_id": 15, "title": "Which colours", "age_hours": 48},
                   {"pending_id": 31, "kind": "review", "task_id": 14, "title": "Brand name", "age_hours": 5}]


def runs():
    return [{"id": 1, "model": "ref", "status": "ok", "failure": None, "cost_usd": 0.02, "ended_at": at(days_ago=1)},
            {"id": 2, "model": "floor", "status": "ok", "failure": None, "cost_usd": 0.01, "ended_at": at(days_ago=2)},
            {"id": 3, "model": "floor", "status": "failed", "failure": "timeout", "cost_usd": None,
             "ended_at": at(days_ago=3)},
            {"id": 4, "model": "ref", "status": "ok", "failure": None, "cost_usd": None, "ended_at": at(days_ago=4)},
            {"id": 5, "model": "ref", "status": "ok", "failure": None, "cost_usd": 9.0, "ended_at": at(days_ago=9)},
            {"id": 6, "model": "ref", "status": "running", "failure": None, "cost_usd": None, "ended_at": None}]


def decisions():
    return [{"id": 40, "kind": "review", "task_id": 13, "status": "resolved", "resolution": "released",
             "resolved_by": "user", "resolved_at": at(days_ago=1)},
            {"id": 41, "kind": "review", "task_id": 21, "status": "resolved", "resolution": "released",
             "resolved_by": "mode:business", "resolved_at": at(days_ago=2)},
            {"id": 42, "kind": "question", "task_id": 14, "status": "resolved", "resolution": "answered",
             "resolved_by": "user", "resolved_at": at(days_ago=2)},
            {"id": 43, "kind": "plan", "task_id": 12, "status": "resolved", "resolution": "approved",
             "resolved_by": "user", "resolved_at": at(days_ago=6)},
            {"id": 44, "kind": "review", "task_id": 16, "status": "resolved", "resolution": "released",
             "resolved_by": "user", "resolved_at": at(days_ago=20)},
            {"id": 45, "kind": "review", "task_id": 14, "title": "Brand name", "status": "open", "resolution": None,
             "created_at": at(hours_ago=5), "resolved_at": None}]


def test_the_summary_counts_only_rows_that_ended_inside_the_period():
    start, end = progress.window(None, NOW)
    effects = [{"id": 1, "executed_at": at(days_ago=1)}, {"id": 2, "executed_at": at(days_ago=30)},
               {"id": 3, "executed_at": None}]
    out = progress.summary(TASKS, runs(), decisions(), effects, start, end)
    assert out["from"] == "2026-11-02" and out["to"] == "2026-11-09"
    assert out["runs"] == {"total": 4, "ok": 3, "failed": 1, "by_model": {"ref": 2, "floor": 2},
                           "by_failure": {"timeout": 1}}
    assert out["deliveries"] == [{"task_id": 21, "title": "Market", "skill": "biz-market-analysis",
                                  "released_by": "mode:business"},
                                 {"task_id": 13, "title": "Strategy", "skill": "brand-strategy", "released_by": "user"}]
    assert out["tasks_done"] == 2 and out["effects_executed"] == 1
    assert out["decisions"]["approved"] == 1 and out["decisions"]["answered"] == 1
    assert out["undated"] == 2  # the running run and the effect without its time


def test_a_run_without_a_cost_is_counted_as_without_cost_and_never_as_zero():
    start, end = progress.window(None, NOW)
    out = progress.summary(TASKS, runs(), [], [], start, end)
    assert out["cost_usd"] == {"known": 0.03, "runs_without_cost": 2}
    unknown = progress.summary(TASKS, [dict(runs()[2])], [], [], start, end)
    assert unknown["cost_usd"] == {"known": 0, "runs_without_cost": 1}


def test_a_release_by_a_mode_is_counted_apart_from_a_release_by_the_person():
    start, end = progress.window(None, NOW)
    out = progress.summary(TASKS, [], decisions(), [], start, end)["decisions"]
    assert out == {"answered": 1, "released_by_you": 1, "released_by_mode": 1, "approved": 1, "rejected": 0}


def numbers(value) -> set:
    """Every number written anywhere in a value: its integers and decimals, and those inside its texts."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found |= numbers(key) | numbers(item)
    elif isinstance(value, list):
        for item in value:
            found |= numbers(item)
    elif isinstance(value, bool) or value is None:
        pass
    elif isinstance(value, (int, float)):
        found.add(float(value))
    else:
        found |= {float(n) for n in re.findall(r"\d+(?:\.\d+)?", str(value))}
    return found


def test_the_text_states_only_numbers_that_are_in_the_object():
    start, end = progress.window("2026-11-02", NOW)
    pending = decisions()
    now_progress = progress.progress(REQUESTS, TASKS, pending, NOW)
    period = progress.summary(TASKS, runs(), pending, [{"id": 7, "executed_at": at(days_ago=1)}], start, end)
    text = progress.render(now_progress, period)
    allowed = numbers(now_progress) | numbers(period)
    stated = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)}
    assert stated <= allowed, stated - allowed
    lines = text.splitlines()
    assert lines[0] == 'Request 12 "Brand": planned, 1 of 5 done, 1 waiting for you, next: 15, 17'
    assert lines[1] == 'Waiting for you: #45 review "Brand name" (task 14), 5 h'
    assert lines[2] == "Stuck: task 16 failed: timeout"
    assert lines[3].startswith("From 2026-11-02 to 2026-11-09: 2 tasks done, 4 runs (3 ok, 1 failed: timeout 1)")
    empty = progress.render(progress.progress([], [], [], NOW), progress.summary([], [], [], [], start, end))
    assert "Requests: none" in empty and "Waiting for you: none" in empty and "Stuck: none" in empty
    assert "Deliveries: none" in empty


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    return built


def test_the_progress_operation_reads_the_store_and_calls_no_model(tree, capsys, monkeypatch):
    project = str(tree["project"])
    request = ops.request(project, "Tell me which market to go after first.", "demo")
    store = ops_core.store_module()
    conn = store.open_db(str(tree["db"]))
    task = store.task_claim_next(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")["run_id"]
    store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting", cost_usd=None,
                          pending={"kind": "review", "title": "Market", "body": "Wrote it."})

    def no_run(*args, **kwargs):
        raise AssertionError("the progress operation started a run")
    monkeypatch.setattr(lab, "run_skill", no_run)
    out = ops.progress(project)
    assert st.calls(tree["adapter"]) == []
    assert out["progress"]["requests"][0]["id"] == request["request"]
    assert out["progress"]["waiting_for_you"][0]["kind"] == "review"
    assert out["summary"]["runs"]["total"] == 1 and out["summary"]["cost_usd"]["runs_without_cost"] == 1
    assert out["text"] == progress.render(out["progress"], out["summary"])
    with pytest.raises(ops.OpsError) as refused:
        ops.progress(project, "fortnight")
    assert refused.value.code == 2
    assert cli.main(["progress", "--project", project, "--since", "3d"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["runs"]["total"] == 1
    helped = subprocess.run([sys.executable, str(st.RUNTIME / "progress.py"), "--help"], capture_output=True, text=True,
                            timeout=60)
    assert helped.returncode == 0 and "window(since, now)" in helped.stdout
    assert subprocess.run([sys.executable, str(st.RUNTIME / "progress.py"), "--frobnicate"], capture_output=True,
                          timeout=60).returncode == 2
