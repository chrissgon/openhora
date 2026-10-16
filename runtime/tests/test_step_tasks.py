"""Tests of the step task in the runtime (P5): the kind `ingest` on the engine (a stand-in converter, no container), a step task in a
plan (plan.combine, the plan hash, the approval), its owner (the runtime's pseudo-agent: never held for lack of an agent), its
admission against the files other tasks write, its place in the dispatcher's round, and the words kept equal across the modules that
copy them. On the stand-in tree of standin_tree.py. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_tasks.py
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

import standin_tree as st
from sources_fixture import standin_convert

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_runs = st.load("ops_runs")
ops_steps = st.load("ops_steps")
ops_waits = st.load("ops_waits")
parallel = st.load("parallel")
dispatcher = st.load("dispatcher")
autonomy = st.load("autonomy")
plan = st.load("plan")
sources = st.load("sources")
steps = st.load("steps")

CSV = "name,price\napple,1.20\npear,3.10\n"
PACKS = {"biz": ["demo-asks", "demo-writes"], "eng": ["demo-code"]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    built["path"] = project
    built["files"] = tmp_path / "files"
    built["files"].mkdir()
    return built


def agents(world, **extra) -> None:
    """Area agents: business and engineering, supervised."""
    path = world["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = {"business": {"pack": "biz", "mode": "supervised", "max_runs_per_day": 50},
                          "engineering": {"pack": "eng", "mode": "supervised", "max_runs_per_day": 50}}
    raw.update(extra)
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])


def ctx_of(world):
    return ops_core.context(world["path"])


@contextlib.contextmanager
def alive(world, *task_ids):
    """The tasks are `running` and a live process holds their locks, as the processes that run them would: a task that is running
    whose lock nobody holds is an orphan, and every round and every run ends it."""
    cfg = ctx_of(world)["cfg"]
    fds = [ops_core._try_lock(cfg, f"task-{i}.lock") for i in task_ids]
    try:
        yield
    finally:
        for fd in fds:
            os.close(fd)


def csv_file(world, name="survey.csv", text=CSV) -> str:
    path = world["files"] / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def add_step(world, source="survey", file=None, key="ingest-survey", request_id=None, depends_on=None, hand=True, **args):
    """An ingest step task. `file` is a path: the task names its basename and the hash of its bytes, and (with `hand`, and when the file
    exists) the file is handed over into the task's drop, where the kind reads it."""
    ctx = ctx_of(world)
    body = {"source": source, **args}
    if file:
        exists = os.path.isfile(file)
        body.update(file=os.path.basename(file), sha256=hashlib.sha256(Path(file).read_bytes()).hexdigest() if exists else "0" * 64)
    made = steps.add_task(ctx["store"], ctx["conn"], "ingest", body, key=key, title="Ingest the survey", text="Bring the survey in.",
                          request_id=request_id, depends_on=depends_on)
    if file and hand and os.path.isfile(file):
        ops.hand_over(world["path"], made["task"], file)
    return made


def task(world, task_id):
    ctx = ctx_of(world)
    return ctx["store"].task_get(ctx["conn"], task_id)


# --- the kind `ingest` on the engine -----------------------------------------------------------------------------------------------


def test_ingest_runs_on_the_engine_and_brings_a_version_of_the_source_into_the_sources_folder(world):
    made = add_step(world, file=csv_file(world))
    assert made["state"] == "ready"
    out = ops.run_step(world["path"], made["task"])
    assert out["ran"] == made["task"] and out["step"] == "ingest" and out["ok"] is True and out["done"] is True
    assert out["task_state"] == "done" and out["steps"] == {"ingest": "done"}
    row = task(world, made["task"])
    assert row["state"] == "done" and row["step_state"]["steps"]["ingest"]["result"] == {"source": "survey", "version": 1, "made": True, "unchanged": False}
    ctx = ctx_of(world)
    version = ctx["store"].source_latest(ctx["conn"], "survey")
    assert version["version"] == 1 and version["converted_name"] == "converted.csv"
    assert (Path(ctx["cfg"]["sources_dir"]) / "survey" / "1" / "converted.csv").is_file()
    assert ctx["store"].task_runs_list(ctx["conn"], made["task"]) == []          # no run row: code ran it, no model
    assert ctx["store"].task_get(ctx["conn"], made["request"])["state"] == "done"


def test_ingest_writes_nothing_in_the_project_and_nothing_a_step_leaves_goes_into_the_sources_folder_but_the_version(world):
    project, sources_dir = Path(world["path"]), Path(ctx_of(world)["cfg"]["sources_dir"])
    made = add_step(world, file=csv_file(world))                       # the hand-over puts the file in the task's drop
    before = sorted(str(p.relative_to(project)) for p in project.rglob("*") if p.is_file())
    assert ".workbench-local/drop/%d/survey.csv" % made["task"] in before
    ops.run_step(world["path"], made["task"])
    after = sorted(str(p.relative_to(project)) for p in project.rglob("*") if p.is_file())
    assert after == before
    inside = sorted(str(p.relative_to(sources_dir)) for p in sources_dir.rglob("*") if p.is_file())
    assert inside and all(n.startswith("survey/1/") or n == sources.MARKER for n in inside if not n.startswith(".")), inside
    assert not any("step" in n for n in inside)       # the engine's state is in the store, never in the folder


def test_a_second_ingest_of_the_same_bytes_makes_no_new_version_and_a_changed_file_makes_the_next(world):
    path = csv_file(world)
    ops.run_step(world["path"], add_step(world, file=path)["task"])
    again = add_step(world, file=path, key="again")
    out = ops.run_step(world["path"], again["task"])
    assert out["ok"] is True and task(world, again["task"])["step_state"]["steps"]["ingest"]["result"] == {
        "source": "survey", "version": 1, "made": False, "unchanged": True}
    csv_file(world, text=CSV + "plum,2.00\n")
    third = add_step(world, file=path, key="third")
    ops.run_step(world["path"], third["task"])
    assert task(world, third["task"])["step_state"]["steps"]["ingest"]["result"]["version"] == 2


def test_an_ingest_whose_file_was_not_handed_over_fails_with_a_closed_code_and_a_retry_resumes_it(world):
    path = csv_file(world, "late.csv")
    made = add_step(world, file=path, source="late", hand=False)
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["failed"] == "ingest" and out["code"] == "file_missing" and out["task_state"] == "failed"
    row = task(world, made["task"])
    assert row["state"] == "failed" and row["note"].startswith("ingest: file_missing file -- hand the file over: hand-over --task")
    assert path not in row["note"] and row["step_state"]["failure"]["code"] == "file_missing"
    assert row["step_state"]["steps"]["ingest"]["status"] == "failed"
    ops.hand_over(world["path"], made["task"], path)                              # the person hands the file over, then retries
    ctx = ctx_of(world)
    assert ctx["store"].task_retry(ctx["conn"], made["task"])["state"] == "ready"
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is True and task(world, made["task"])["state"] == "done"


def test_an_ingest_reads_only_the_file_of_its_own_drop_and_only_when_its_bytes_are_the_ones_the_plan_approved(world):
    ctx = ctx_of(world)
    approved = csv_file(world, "survey.csv")
    made = add_step(world, file=approved, hand=False)
    other = world["files"] / "elsewhere"
    other.mkdir()
    (other / "survey.csv").write_text("name,price\nplum,9.99\n", encoding="utf-8")      # the same name, other bytes
    ops.hand_over(world["path"], made["task"], str(other / "survey.csv"))
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["code"] == "file_changed" and task(world, made["task"])["state"] == "failed"
    assert "approved" in task(world, made["task"])["note"]
    assert ctx["store"].source_latest(ctx["conn"], "survey") is None                 # no other bytes were imported
    # a path of the person's machine is no argument at all, and the file is not read from where it lies
    for args in ({"source": "survey", "file": "/data/survey.csv", "sha256": "a" * 64}, {"source": "survey", "file": "../survey.csv", "sha256": "a" * 64}):
        with pytest.raises(steps.StepFailure) as refused:
            steps.plan_task("ingest", args, key="x", title="X", text="X.")
        assert refused.value.code == "bad_args"


def test_the_drop_of_a_step_task_takes_a_file_and_a_link_in_it_is_not_read(world):
    path = csv_file(world, "survey.csv")
    made = add_step(world, file=path, hand=False)
    drop_dir = Path(world["path"]) / ".workbench-local" / "drop" / str(made["task"])
    drop_dir.mkdir(parents=True)
    (drop_dir / "survey.csv").symlink_to(path)                                         # a link to the right bytes is still a link
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["code"] == "file_missing"


@pytest.mark.parametrize("level", ["local", "drop", "task", "file"])
def test_an_ingest_never_reads_through_a_link_at_any_level_of_its_drop(world, level):
    """A link at .workbench-local, at drop, at the task's folder or at the file, each to a real folder or file outside the project that holds
    the right bytes, is file_missing: the drop is opened from the project's root one part at a time with O_NOFOLLOW."""
    path = csv_file(world, "survey.csv")
    made = add_step(world, file=path, hand=False)
    task_id = str(made["task"])
    outside = world["files"].parent / "outside"
    project = Path(world["path"])
    local = project / ".workbench-local"
    if level == "local":
        (outside / "drop" / task_id).mkdir(parents=True)
        (outside / "drop" / task_id / "survey.csv").write_text(CSV, encoding="utf-8")
        local.symlink_to(outside)
    elif level == "drop":
        (outside / task_id).mkdir(parents=True)
        (outside / task_id / "survey.csv").write_text(CSV, encoding="utf-8")
        local.mkdir()
        (local / "drop").symlink_to(outside)
    elif level == "task":
        outside.mkdir()
        (outside / "survey.csv").write_text(CSV, encoding="utf-8")
        (local / "drop").mkdir(parents=True)
        (local / "drop" / task_id).symlink_to(outside)
    else:
        outside.mkdir()
        (outside / "survey.csv").write_text(CSV, encoding="utf-8")
        (local / "drop" / task_id).mkdir(parents=True)
        (local / "drop" / task_id / "survey.csv").symlink_to(outside / "survey.csv")
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["code"] == "file_missing" and task(world, made["task"])["state"] == "failed"
    assert ctx_of(world)["store"].source_latest(ctx_of(world)["conn"], "survey") is None


def test_a_notion_source_is_refreshed_and_a_file_source_is_checked_with_no_file_in_the_arguments(world):
    made = add_step(world, file=csv_file(world))
    ops.run_step(world["path"], made["task"])
    refresh = add_step(world, key="refresh")
    out = ops.run_step(world["path"], refresh["task"])
    assert out["ok"] is True and task(world, refresh["task"])["step_state"]["steps"]["ingest"]["result"]["unchanged"] is True


@pytest.mark.parametrize("args", [{"source": "Bad Id"}, {"source": "survey", "file": "relative.csv"}, {"source": "survey", "file": "a.csv", "url": "x"},
                                  {"source": "survey", "file": "a.csv", "sha256": "z" * 64}, {"source": "survey", "sha256": "a" * 64},
                                  {"source": "survey", "file": "a.csv", "url": "x", "sha256": "a" * 64},
                                  {"source": "survey", "other": 1}, {"file": "a.csv", "sha256": "a" * 64}, {"source": "survey", "url": " "}])
def test_the_arguments_of_an_ingest_are_checked_when_the_task_is_made(world, args):
    ctx = ctx_of(world)
    with pytest.raises(steps.StepFailure) as refused:
        steps.add_task(ctx["store"], ctx["conn"], "ingest", args, key="x", title="X", text="X.")
    assert refused.value.code == "bad_args"
    assert ctx["store"].tasks_list(ctx["conn"]) == []


def test_an_unknown_kind_in_a_task_row_fails_the_task_and_never_leaves_it_running(world):
    ctx = ctx_of(world)
    made = ctx["store"].step_task_add(ctx["conn"], key="x", title="X", text="X.", step="vanished-kind")
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["code"] == "unknown_kind" and out["task_state"] == "failed"
    assert task(world, made["task"])["note"] == "start: unknown_kind step"


def test_a_bug_in_a_kind_fails_the_task_with_a_note_and_the_next_run_goes_on(world, monkeypatch):
    made = add_step(world, file=csv_file(world))

    def boom(ctx, state):
        raise RuntimeError("an invented bug with /private/path and a secret")
    monkeypatch.setitem(steps.REGISTRY, "ingest", steps.Kind(name="ingest", order=("ingest",), executors={"ingest": boom}))
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["failed"] == "ingest" and out["code"] == "step_error" and out["task_state"] == "failed"
    row = task(world, made["task"])
    assert row["state"] == "failed" and row["note"] == "ingest: step_error ingest" and "secret" not in repr(row)
    assert row["step_state"]["steps"]["ingest"]["status"] == "failed" and row["step_state"]["failure"]["code"] == "step_error"
    ctx = ctx_of(world)
    assert ctx["store"].task_retry(ctx["conn"], made["task"])["state"] == "ready"


def test_a_bug_of_the_engine_itself_still_ends_the_task_failed_with_a_note(world, monkeypatch):
    made = add_step(world, file=csv_file(world))

    def boom(ctx, kind, state):
        raise RuntimeError("an invented bug of the engine with a secret")
    monkeypatch.setattr(steps, "run", boom)
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["code"] == "internal" and out["task_state"] == "failed"
    assert task(world, made["task"])["note"].startswith("internal error (RuntimeError)") and "secret" not in task(world, made["task"])["note"]


def test_run_step_refuses_a_skill_task_and_a_task_that_is_not_ready_and_run_task_hands_a_step_task_over(world):
    ctx = ctx_of(world)
    skill = ctx["store"].request_add(ctx["conn"], title="S", text="Skill.", flow="demo", tasks=[
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do it."}])["tasks"][0]["id"]
    refused = ops.run_step(world["path"], skill)
    assert refused["ran"] is None and "not a step task" in refused["reason"] and refused["held"] is False
    first = add_step(world, file=csv_file(world), key="a")
    second = add_step(world, key="b", request_id=first["request"], depends_on=["a"])
    not_ready = ops.run_step(world["path"], second["task"])
    assert not_ready["ran"] is None and "no task is ready" in not_ready["reason"] and not_ready["held"] is False
    assert task(world, second["task"])["state"] == "planned"


def test_run_task_and_run_next_hand_a_step_task_to_run_step(world):
    first = add_step(world, file=csv_file(world), key="a")
    second = add_step(world, key="b", request_id=first["request"], depends_on=["a"])
    done = ops.run_task(world["path"], first["task"])
    assert done["ran"] == first["task"] and done["step"] == "ingest" and done["task_state"] == "done"
    assert task(world, second["task"])["state"] == "ready"
    assert ops.run_next(world["path"])["ran"] == second["task"]


# --- the plan --------------------------------------------------------------------------------------------------------------------


REQUEST = {"id": 7, "title": "Study", "text": "Study the survey."}
LIMITS = {"timeout_seconds": 1800, "retries": 2}
FLOW = {"flow": "ingest-then-market", "title": "Ingest, then the market", "tasks": [
    {"key": "ingest", "step": "ingest", "args": {"source": "survey", "file": "survey.csv", "sha256": "a" * 64}, "title": "Ingest", "text": "Bring it in.",
     "depends_on": [], "milestone": False},
    {"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Do the market analysis.", "depends_on": ["ingest"],
     "milestone": False}]}


def combined(flow=FLOW, agent_skills=None, pack=("biz-market-analysis",), root=None):
    routed = [{"item": "the job", "reply": "", "route": {"kind": "route", "line": "Route: flow-x (flow, pending)",
                                                        "checked": {"ok": True, "flow": flow["flow"]}}}]
    return plan.combine(REQUEST, routed, {flow["flow"]: flow}, agent_skills if agent_skills is not None else {"business": ["biz-market-analysis"]},
                        root or str(st.REPO), pack=list(pack), limits=LIMITS, past=[])


def test_a_plan_with_a_step_task_passes_combine_and_the_step_belongs_to_the_runtime(monkeypatch):
    out = combined()
    by_key = {t["key"]: t for t in out["tasks"]}
    assert out["unrouted"] == [] and out["plan"] is not None
    step, skill = by_key["ingest"], by_key["market"]
    assert step["agent"] == "runtime" and step["step"] == "ingest" and step["footprint"] == [] and step["web"] is False
    assert step["args"] == {"source": "survey", "file": "survey.csv", "sha256": "a" * 64} and "skill" not in step
    assert skill["agent"] == "business" and skill["depends_on"] == ["ingest"]
    body = out["plan"]["body"]
    assert "step ingest" in body and "Steps (run by code, no model):" in body and '"source": "survey"' in body
    assert out["plan"]["payload"]["estimate"]["runs_at_least"] == 1             # one run of a skill: the step is code


def test_a_plan_with_a_step_task_passes_combine_in_a_project_with_no_area_agents_too():
    out = combined(agent_skills={})
    agent_of = {t["key"]: t["agent"] for t in out["tasks"]}
    assert agent_of == {"ingest": "runtime", "market": None}


def test_the_arguments_of_a_step_change_the_plan_hash_and_the_footprint_is_covered_by_it():
    one = combined()["plan"]["payload"]["plan_sha256"]
    other = dict(FLOW, tasks=[dict(FLOW["tasks"][0], args={"source": "survey", "file": "survey.csv", "sha256": "b" * 64}), FLOW["tasks"][1]])
    two = combined(other)["plan"]["payload"]["plan_sha256"]
    assert one != two and one == combined()["plan"]["payload"]["plan_sha256"]
    tasks = combined()["tasks"]
    changed = [dict(tasks[0], footprint=["docs/x.md"]), tasks[1]]
    assert plan.plan_hash(tasks) != plan.plan_hash(changed)


def test_a_step_of_a_flow_with_bad_arguments_or_an_unknown_kind_refuses_the_plan():
    for bad in ({"source": "Bad Id"}, {"source": "survey", "file": "relative"}, {"source": "survey", "file": "a.csv"}):
        flow = dict(FLOW, tasks=[dict(FLOW["tasks"][0], args=bad), FLOW["tasks"][1]])
        with pytest.raises(plan.PlanError, match="the step ingest of the flow"):
            plan.from_flow(flow, str(st.REPO), ["biz-market-analysis"])
    flow = dict(FLOW, tasks=[dict(FLOW["tasks"][0], step="vanished-kind"), FLOW["tasks"][1]])
    with pytest.raises(plan.PlanError, match="unknown_kind"):
        plan.from_flow(flow, str(st.REPO), ["biz-market-analysis"])


def test_an_approved_plan_creates_the_step_task_with_its_kind_arguments_footprint_and_owner_and_it_runs_after_its_dependency(world):
    agents(world)
    ctx = ctx_of(world)
    request = ops.request(world["path"], "Study the survey.", title="Study")["request"]
    shown = combined(dict(FLOW, tasks=[dict(FLOW["tasks"][0], args={"source": "survey", "file": "survey.csv", "sha256": hashlib.sha256(CSV.encode()).hexdigest()}),
                                       dict(FLOW["tasks"][1], skill="demo-asks")]),
                     agent_skills={"business": ["demo-asks"]}, pack=("demo-asks",), root=str(world["tree"]))
    # the plan a router or a flow produced, opened as the decision the person approves
    annotated = ops_waits.annotate(ctx, ctx["store"].task_get(ctx["conn"], request), {"kind": "plan", **shown["plan"]})
    assert annotated["payload"]["waits"] == [] and annotated["payload"]["plan_sha256"] == shown["plan"]["payload"]["plan_sha256"]
    opened = ctx["store"].plan_open(ctx["conn"], request, title=annotated["title"], body=annotated["body"],
                                    payload=annotated["payload"])
    done = ops.approve(world["path"], opened["pending_id"], shown["plan"]["payload"]["plan_sha256"])
    by_key = {t["key"]: t for t in ctx["store"].tasks_list(ctx["conn"], request) if t["parent_id"]}
    step = by_key["ingest"]
    assert done["ready"] == [step["id"]] or step["id"] in done["ready"]
    assert step["state"] == "ready" and step["agent"] == "runtime" and step["skill"] is None and step["step_kind"] == "ingest"
    assert step["step_args"]["source"] == "survey" and by_key["market"]["state"] == "planned" and by_key["market"]["depends_on"] == [step["id"]]
    csv_file(world)
    ops.hand_over(world["path"], step["id"], str(world["files"] / "survey.csv"))      # the file of the plan, in the step's own drop
    out = ops.run_step(world["path"], step["id"])
    assert out["task_state"] == "done" and task(world, by_key["market"]["id"])["state"] == "ready"


# --- the owner: the runtime's pseudo-agent ---------------------------------------------------------------------------------------


def snapshot(*ready, steps_stopped=False):
    return {"running": [], "holding": [], "ready": list(ready), "reviews": [], "agents": {}, "model": {}, "billing": {}, "waits": {},
            "max_running": 10, "per_run_usd": 0.0, "steps_stopped": steps_stopped}


def decide(snap, may_start=None):
    def refuse(*a, **k):
        raise AssertionError("an area agent's rule was asked about a step task")
    return dispatcher.decide(snap, lambda *a: "hold", may_start or refuse, parallel.admit)


def step_row(i, **extra):
    return {"id": i, "agent": "runtime", "parent_id": 1, "step_kind": "ingest", "skill": None, "code": False, "footprint": (), "unattended": True, **extra}


def test_a_step_task_is_never_held_for_lack_of_an_agent_and_asks_no_area_agent_rule():
    out = decide(snapshot(step_row(5)))
    assert out["start"] == [5] and out["held"] == []
    other = decide(snapshot({"id": 6, "agent": None, "parent_id": 1, "skill": "demo-asks", "code": False, "footprint": ()}),
                   may_start=lambda *a: (True, ""))
    assert other["held"] == [{"task_id": 6, "why": dispatcher.NO_AGENT}]         # a skill task with no agent still is


def test_the_runtime_has_a_running_cap_of_its_own_and_the_word_a_full_agent_gives(world):
    out = decide(snapshot(step_row(5), step_row(6), step_row(7)))
    assert out["start"] == [5, 6] and out["held"] == [{"task_id": 7, "why": dispatcher.AGENT_FULL}]
    assert parallel.RUNTIME_PARALLEL == 2
    # the cap is the runtime's own: an area agent's slots do not count, and the project's max_running still applies
    full = decide(dict(snapshot(step_row(5)), max_running=1, running=[{"id": 9, "agent": "business", "request_id": 2, "code": False, "footprint": ()}]))
    assert full["held"] == [{"task_id": 5, "why": dispatcher.PROJECT_FULL}]


def test_a_step_task_counts_no_run_of_an_agents_day_and_uses_no_credential():
    snap = snapshot(step_row(5), {"id": 6, "agent": "business", "parent_id": 1, "skill": "demo-asks", "code": False, "footprint": ()})
    snap["agents"] = {"business": {"facts": {"enabled": True, "checkpoints": "end", "standing": False}, "entry": {"max_parallel": 1},
                                   "spent": {"runs_counted": 0}}}
    snap["billing"] = {6: "subscription"}
    out = dispatcher.decide(snap, lambda *a: "hold", lambda name, entries, facts, spent, billing: (True, ""), parallel.admit)
    assert out["start"] == [5, 6]
    assert snap["agents"]["business"]["spent"] == {"runs_counted": 0}     # decide counts on its own copy


def test_the_brake_holds_every_step_task_with_stopped_and_a_kind_that_is_not_unattended_is_held_by_hand():
    stopped = decide(snapshot(step_row(5), step_row(6), steps_stopped=True))
    assert stopped["start"] == [] and stopped["held"] == [{"task_id": 5, "why": "stopped"}, {"task_id": 6, "why": "stopped"}]
    by_hand = decide(snapshot(step_row(5, unattended=False), step_row(6)))
    assert by_hand["start"] == [6] and by_hand["held"] == [{"task_id": 5, "why": dispatcher.BY_HAND}]
    assert dispatcher.BY_HAND == "start it by hand" and dispatcher.BY_HAND in dispatcher.REASONS
    held = dispatcher.held_of(snapshot(step_row(5, unattended=False)), {"held": [{"task_id": 5, "why": dispatcher.BY_HAND}]})
    assert held == [{"task_id": 5, "agent": "runtime", "reason": "start it by hand"}]
    # a task with no flag at all (a snapshot an older caller made) is not unattended: the dispatcher never guesses
    bare = {k: v for k, v in step_row(7).items() if k != "unattended"}
    assert decide(snapshot(bare))["held"] == [{"task_id": 7, "why": dispatcher.BY_HAND}]


def test_the_runtime_name_cannot_be_an_area_agent_and_every_copy_of_the_owner_and_its_cap_is_the_same():
    with pytest.raises(ValueError, match="the runtime's own"):
        autonomy.agents({"runtime": {"pack": "default"}})
    store = ctx_store()
    assert store.STEP_OWNER == steps.OWNER == parallel.RUNTIME == dispatcher.RUNTIME == autonomy.RESERVED_AGENTS[0] == "runtime"
    assert store.STEP_FOOTPRINT_MAX == steps.FOOTPRINT_MAX


def ctx_store():
    return ops_core.store_module()


def test_a_dispatch_in_a_project_with_no_area_agent_still_starts_a_ready_step_task_and_holds_a_skill_task(world, monkeypatch):
    ctx = ctx_of(world)
    skill = ctx["store"].request_add(ctx["conn"], title="S", text="Skill.", flow="demo", tasks=[
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do it."}])["tasks"][0]["id"]
    made = add_step(world, file=csv_file(world))
    started = []
    monkeypatch.setattr(ops_runs, "spawn", st.serial_spawn(ops_runs))
    out = ops.dispatch(world["path"], wait=False)
    assert [s["task_id"] for s in out["started"]] == [made["task"]] and task(world, made["task"])["state"] == "done"
    assert task(world, skill)["state"] == "ready"
    held = {h["task_id"]: h["reason"] for h in ops.status(world["path"])["held"]}
    assert held == {skill: dispatcher.NO_AGENT}


def test_a_dispatch_starts_a_step_task_with_run_step_beside_a_skill_task_with_run_task_and_the_eval_image_check_does_not_hold_it(world, monkeypatch):
    agents(world)
    ctx = ctx_of(world)
    skill = ctx["store"].request_add(ctx["conn"], title="S", text="Skill.", flow="demo", tasks=[
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do it.", "agent": "business"}])["tasks"][0]["id"]
    made = add_step(world, file=csv_file(world))
    calls = []

    class Child:
        pid, returncode = 0, 0

        def poll(self):
            return 0

    def spawn(cfg, project, task_id, verb="run-task"):
        calls.append((task_id, verb))
        child = Child()
        with ops_runs.SPAWNED_LOCK:
            ops_runs.SPAWNED.append((project, task_id, child))
        return child
    monkeypatch.setattr(ops_runs, "spawn", spawn)
    monkeypatch.setattr(ops, "_image_stop", lambda: ("image", "the eval image is missing", []))     # skill runs are held; steps are not
    out = ops.dispatch(world["path"], wait=False)
    assert calls == [(made["task"], "run-step")] and [s["task_id"] for s in out["started"]] == [made["task"]]
    assert out["stopped"] == "the eval image is missing"
    assert task(world, skill)["state"] == "ready"


def spawn_recorder(monkeypatch, calls):
    """ops_runs.spawn replaced by a recorder: a child that has ended and ran nothing."""
    class Child:
        pid, returncode = 0, 0

        def poll(self):
            return 0

    def spawn(cfg, project, task_id, verb="run-task"):
        calls.append((task_id, verb))
        child = Child()
        with ops_runs.SPAWNED_LOCK:
            ops_runs.SPAWNED.append((project, task_id, child))
        return child
    monkeypatch.setattr(ops_runs, "spawn", spawn)
    monkeypatch.setattr(ops, "_image_stop", lambda: None)
    monkeypatch.setattr(ops, "_credential_stop", lambda model=None: None)


def test_the_runtime_stopped_the_dispatcher_starts_no_step_task_with_agents_or_without_and_the_persons_own_start_still_runs_one(world, monkeypatch):
    calls = []
    spawn_recorder(monkeypatch, calls)
    made = add_step(world, file=csv_file(world))
    stopped = ops.set_mode(world["path"], "runtime", "stopped", channel="terminal")
    assert stopped == {"agent": "runtime", "mode": "stopped", "unchanged": False}
    out = ops.dispatch(world["path"], wait=False)                                  # no area agent configured
    assert calls == [] and out.get("started", []) == [] and task(world, made["task"])["state"] == "ready"
    assert {h["task_id"]: h["reason"] for h in ops.status(world["path"])["held"]} == {made["task"]: "stopped"}
    agents(world)
    out = ops.dispatch(world["path"], wait=False)                                  # with agents the brake is the same
    assert calls == [] and out["started"] == [] and {h["task_id"]: h["why"] for h in out["held"]} == {made["task"]: "stopped"}
    assert ops.run_next(world["path"])["ran"] == made["task"]                      # the person's own start is not stopped
    assert task(world, made["task"])["state"] == "done"
    assert ops.set_mode(world["path"], "runtime", "stopped", channel="terminal")["unchanged"] is True


def test_with_every_area_agent_stopped_a_step_task_still_starts_until_the_runtime_itself_is_stopped(world, monkeypatch):
    calls = []
    spawn_recorder(monkeypatch, calls)
    path = world["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = {"business": {"pack": "biz", "mode": "stopped"}}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    made = add_step(world, file=csv_file(world))
    ops.dispatch(world["path"], wait=False)
    assert calls == [(made["task"], "run-step")]          # an area agent's mode is not the runtime's: it has its own brake
    ctx = ctx_of(world)
    ctx["store"].step_task_move(ctx["conn"], made["task"], state="failed", note="ended")
    ctx["store"].task_retry(ctx["conn"], made["task"])
    ops.set_mode(world["path"], "runtime", "stopped", channel="terminal")
    calls.clear()
    assert ops.dispatch(world["path"], wait=False)["started"] == [] and calls == []
    assert ops.set_mode(world["path"], "runtime", "autonomous", channel="terminal")["unchanged"] is False
    ctx["store"].cursor_set(ctx["conn"], ops_runs.REFUSED_CURSOR, "{}")           # the child that ran nothing was recorded as refused
    ops.dispatch(world["path"], wait=False)
    assert calls == [(made["task"], "run-step")]


def test_the_brake_of_the_runtime_is_the_terminals_and_the_pages_a_stop_never_withheld_and_a_resume_by_the_pages_policy(world):
    with pytest.raises(ops.OpsError, match="one of stopped, autonomous"):
        ops.set_mode(world["path"], "runtime", "milestones", channel="terminal")
    path = world["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["channels"] = {"page": ["read"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    assert ops.set_mode(world["path"], "runtime", "stopped", channel="page")["mode"] == "stopped"      # a stop is never withheld
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(world["path"], "runtime", "autonomous", channel="page")                          # a resume needs the group set-mode
    assert refused.value.code == 1
    assert ops.set_mode(world["path"], "runtime", "autonomous", channel="terminal")["mode"] == "autonomous"
    raw["channels"] = {"page": ["read", "set-mode"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    ops.set_mode(world["path"], "runtime", "stopped", channel="page")
    assert ops.set_mode(world["path"], "runtime", "autonomous", channel="page")["mode"] == "autonomous"


def test_a_kind_that_is_not_unattended_is_never_started_by_the_dispatcher_but_run_next_and_run_step_run_it(world, monkeypatch):
    calls = []
    spawn_recorder(monkeypatch, calls)
    by_hand = steps.Kind(name="by-hand", order=("one",), executors={"one": lambda c, s: {"made": 1}})
    monkeypatch.setitem(steps.REGISTRY, "by-hand", by_hand)
    ctx = ctx_of(world)
    made = ctx["store"].step_task_add(ctx["conn"], key="manual", title="Manual", text="By hand.", step="by-hand")
    assert steps.kind_of("ingest").unattended is True and by_hand.unattended is False
    out = ops.dispatch(world["path"], wait=False)
    assert calls == [] and out.get("started", []) == []
    assert {h["task_id"]: h["reason"] for h in ops.status(world["path"])["held"]} == {made["task"]: "start it by hand"}
    agents(world)
    out = ops.dispatch(world["path"], wait=False)
    assert calls == [] and {h["task_id"]: h["why"] for h in out["held"]} == {made["task"]: "start it by hand"}
    assert ops.run_next(world["path"])["ran"] == made["task"] and task(world, made["task"])["state"] == "done"
    unknown = ctx["store"].step_task_add(ctx["conn"], key="gone", title="Gone", text="Gone.", step="vanished-kind")
    assert ops.dispatch(world["path"], wait=False).get("started", []) == [] and task(world, unknown["task"])["state"] == "ready"


def test_the_stop_of_a_step_task_takes_only_a_verdict_through_the_answer_and_the_run_goes_on_or_stops(world, monkeypatch):
    stopping = steps.Kind(name="reviewed", order=("make", "review", "finish"), stops=("review",), unattended=True,
                          executors={"make": lambda c, s: {"made": 1}, "finish": lambda c, s: {"finished": 1}},
                          decisions={"review": lambda c, s: {"title": "Look at it", "body": "It is made."}})
    monkeypatch.setitem(steps.REGISTRY, "reviewed", stopping)
    ctx = ctx_of(world)
    made = ctx["store"].step_task_add(ctx["conn"], key="r", title="R", text="Reviewed.", step="reviewed")["task"]
    out = ops.run_step(world["path"], made)
    pending = ctx["store"].pending_list(ctx["conn"])[0]
    assert out["stopped"] == "review" and pending["kind"] == "question" and pending["payload"]["verdicts"] == ["continue", "stop"]
    ops.answer(world["path"], pending["id"], "No, do not go on")                       # free text: the task is ready, and asks again
    out = ops.run_step(world["path"], made)
    again = ctx["store"].pending_list(ctx["conn"])[0]
    assert out["stopped"] == "review" and again["id"] != pending["id"] and task(world, made)["state"] == "waiting"
    ops.answer(world["path"], again["id"], "continue")
    out = ops.run_step(world["path"], made)
    assert out["done"] is True and task(world, made)["state"] == "done"


def test_a_step_the_dispatcher_started_asks_the_brake_and_the_kinds_flag_again_under_the_claim_lock(world, monkeypatch):
    """The race: the dispatcher decided on a snapshot, the person stopped the runtime before the child claimed the task."""
    calls, raced = [], []
    made = add_step(world, file=csv_file(world))

    class Child:
        pid, returncode = 0, 0

        def poll(self):
            return 0

    def spawn(cfg, project, task_id, verb="run-task"):
        calls.append((task_id, verb))
        ops.set_mode(world["path"], "runtime", "stopped", channel="terminal")            # between decide and claim
        raced.append(ops.run_step(world["path"], task_id, unattended=True))              # what the child does with --unattended
        child = Child()
        with ops_runs.SPAWNED_LOCK:
            ops_runs.SPAWNED.append((project, task_id, child))
        return child
    monkeypatch.setattr(ops_runs, "spawn", spawn)
    monkeypatch.setattr(ops, "_image_stop", lambda: None)
    ops.dispatch(world["path"], wait=False)
    assert calls == [(made["task"], "run-step")]                                          # the dispatcher did decide to start it
    assert raced == [{"ran": None, "reason": "stopped", "held": True, "task": made["task"], "recovered": []}]
    assert task(world, made["task"])["state"] == "ready" and task(world, made["task"])["step_state"] is None
    again = ops.run_step(world["path"], made["task"])                                     # the person's own start is not asked
    assert again["ok"] is True and task(world, made["task"])["state"] == "done"


def test_the_flag_asks_the_kinds_unattended_too_and_the_persons_start_does_not(world, monkeypatch):
    monkeypatch.setitem(steps.REGISTRY, "by-hand", steps.Kind(name="by-hand", order=("one",), executors={"one": lambda c, s: {"made": 1}}))
    ctx = ctx_of(world)
    made = ctx["store"].step_task_add(ctx["conn"], key="manual", title="Manual", text="By hand.", step="by-hand")["task"]
    held = ops.run_step(world["path"], made, unattended=True)
    assert held["ran"] is None and held["held"] is True and held["reason"] == "start it by hand" and task(world, made)["state"] == "ready"
    assert ops.run_step(world["path"], made)["ok"] is True                                # by hand
    ingest = add_step(world, file=csv_file(world), key="auto")["task"]
    assert ops.run_step(world["path"], ingest, unattended=True)["ok"] is True             # an unattended kind with the brake off runs
    # run-task on a step task is the dispatcher-style call (checked by default); run-next is the person's
    third = add_step(world, file=csv_file(world), key="third")["task"]
    ops.set_mode(world["path"], "runtime", "stopped", channel="terminal")
    assert ops.run_task(world["path"], third)["ran"] is None
    assert ops.run_next(world["path"])["ran"] == third


def test_the_dispatcher_starts_a_step_process_with_the_unattended_flag_and_a_skill_process_without_it(world, monkeypatch):
    seen = []

    class Popen:
        def __init__(self, argv, **kwargs):
            seen.append(argv)
            self.pid, self.returncode = 0, None

        def poll(self):
            return 0
    monkeypatch.setattr(ops_runs.subprocess, "Popen", Popen)
    cfg = ctx_of(world)["cfg"]
    world["real_spawn"](cfg, world["path"], 5, "run-step")
    world["real_spawn"](cfg, world["path"], 6)
    assert seen[0][-1] == "--unattended" and seen[0][2:5] == ["run-step", "--project", world["path"]]
    assert "--unattended" not in seen[1] and seen[1][2] == "run-task"
    cli = st.load("cli")
    parsed = cli.build_parser().parse_args(["run-step", "--project", world["path"], "--task", "5", "--unattended"])
    assert parsed.f_unattended is True and cli.build_parser().parse_args(["run-step", "--project", world["path"], "--task", "5"]).f_unattended is False


def test_the_agents_read_carries_the_brake_with_or_without_area_agents(world):
    assert ops.agents(world["path"])["steps"] == {"agent": "runtime", "mode": "autonomous"}
    ops.set_mode(world["path"], "runtime", "stopped", channel="terminal")
    assert ops.agents(world["path"]) == {"agents": [], "steps": {"agent": "runtime", "mode": "stopped"}}
    agents(world)
    read = ops.agents(world["path"])
    assert read["steps"] == {"agent": "runtime", "mode": "stopped"} and [a["name"] for a in read["agents"]] == ["business", "engineering"]
    ops.set_mode(world["path"], "runtime", "autonomous", channel="terminal")
    assert ops.agents(world["path"])["steps"]["mode"] == "autonomous"


def test_a_pipe_in_the_drop_is_refused_without_being_opened_so_it_cannot_hang_the_task(world):
    made = add_step(world, file=csv_file(world), hand=False)
    drop_dir = Path(world["path"]) / ".workbench-local" / "drop" / str(made["task"])
    drop_dir.mkdir(parents=True)
    os.mkfifo(drop_dir / "survey.csv")
    result = {}
    runner = threading.Thread(target=lambda: result.update(out=ops.run_step(world["path"], made["task"])), daemon=True)
    runner.start()
    runner.join(30)
    assert not runner.is_alive(), "the ingest waited for a writer on the pipe"
    assert result["out"]["ok"] is False and result["out"]["code"] == "file_missing" and task(world, made["task"])["state"] == "failed"


def test_a_file_over_the_cap_is_refused_having_read_no_more_than_the_cap(world, monkeypatch):
    made = add_step(world, file=csv_file(world))
    drop_module = st.load("drop")
    monkeypatch.setattr(drop_module, "MAX_BYTES", 10)
    read = []
    original = os.fdopen

    def counting(fd, *a, **k):
        f = original(fd, *a, **k)
        real = f.read
        f.read = lambda n=-1: (read.append(n), real(n))[1]
        return f
    monkeypatch.setattr(st.load("step_ingest").os, "fdopen", counting)
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["code"] == "file_too_large" and task(world, made["task"])["state"] == "failed"
    assert read == [11]                                                                      # the cap and one byte: never the whole file
    assert ctx_of(world)["store"].source_latest(ctx_of(world)["conn"], "survey") is None


def test_the_bytes_imported_are_the_bytes_that_were_hashed_even_when_the_file_is_swapped_after_the_check(world, monkeypatch):
    approved = csv_file(world)
    made = add_step(world, file=approved)
    drop_file = Path(world["path"]) / ".workbench-local" / "drop" / str(made["task"]) / "survey.csv"
    real = st.load("ops_sources").import_bytes

    def swapped(project, source_id, name, data):
        drop_file.write_text("name,price\nplum,9.99\n", encoding="utf-8")                  # another file in its place, after the hash was checked
        return real(project, source_id, name, data)
    monkeypatch.setattr(st.load("ops_sources"), "import_bytes", swapped)
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is True
    ctx = ctx_of(world)
    version = ctx["store"].source_latest(ctx["conn"], "survey")
    assert version["original_sha256"] == hashlib.sha256(CSV.encode()).hexdigest()           # the approved bytes, not the swapped file's


def test_the_errors_write_file_calls_a_link_are_the_platforms_own(tmp_path):
    import errno
    assert steps.LINK_ERRNOS == (errno.ELOOP, errno.ENOTDIR)


# --- admission against the files other tasks write ---------------------------------------------------------------------------------


def writer_step(world, path, key="writer", request_id=None):
    ctx = ctx_of(world)
    return ctx["store"].step_task_add(ctx["conn"], key=key, title="Writer", text="Writes.", step="ingest", footprint=[path],
                                      request_id=request_id)


def market_skill(world):
    ctx = ctx_of(world)
    return ctx["store"].request_add(ctx["conn"], title="S", text="Skill.", flow="demo", tasks=[
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do it.", "agent": "business"}])["tasks"][0]["id"]


def test_a_step_task_writing_a_path_is_held_against_a_skill_task_writing_it_and_the_reverse(world):
    agents(world)
    step = writer_step(world, "docs/business/market.md")["task"]       # demo-asks declares docs/business/market.md as its output
    skill = market_skill(world)
    ctx = ctx_of(world)
    cache = {}
    assert ops_runs.item_of(task(world, step), cache)["footprint"] == frozenset({"docs/business/market.md"})
    assert ops_runs.item_of(task(world, step), cache)["code"] is False
    ctx["store"].task_claim(ctx["conn"], step)                         # the step is running, a process holds its lock
    with alive(world, step):
        held = ops.run_task(world["path"], skill)
    assert held["ran"] is None and held["held"] is True and held["reason"] == parallel.IN_USE and task(world, skill)["state"] == "ready"
    # the reverse: the skill task running, the step task refused for the same path
    ctx["store"].step_task_move(ctx["conn"], step, state="failed", note="ended")
    ctx["store"].task_retry(ctx["conn"], step)
    ctx["store"].task_claim(ctx["conn"], skill)
    with alive(world, skill):
        refused = ops.run_step(world["path"], step)
    assert refused["ran"] is None and refused["held"] is True and refused["reason"] == parallel.IN_USE
    assert task(world, step)["state"] == "ready"


def test_the_admission_reads_the_footprint_of_the_task_row_and_two_step_tasks_of_one_request_run_together_when_they_overlap_nothing(world):
    one = writer_step(world, "docs/one.md", "one")
    two = writer_step(world, "docs/two.md", "two", request_id=one["request"])
    same = writer_step(world, "docs/one.md", "same", request_id=one["request"])
    items = {k: ops_runs.item_of(task(world, v["task"]), {}) for k, v in (("one", one), ("two", two), ("same", same))}
    assert all(i["code"] is False and i["agent"] == "runtime" for i in items.values())
    assert parallel.admit(items["two"], [items["one"]], [{"id": 1, "agent": "runtime"}], {}, 5) == (True, "")
    assert parallel.admit(items["same"], [items["one"]], [{"id": 1, "agent": "runtime"}], {}, 5) == (False, parallel.IN_USE)
    third = dict(items["two"], id=99)
    assert parallel.admit(third, [items["one"], dict(items["two"], id=50)], [{"id": 1, "agent": "runtime"}, {"id": 50, "agent": "runtime"}], {}, 5) == (False, parallel.AGENT_FULL)


def test_a_step_task_is_no_code_task_so_the_one_code_task_of_a_request_rule_does_not_hold_it(world):
    agents(world)
    ctx = ctx_of(world)
    code = ctx["store"].request_add(ctx["conn"], title="C", text="Code.", flow="code-demo", tasks=[
        {"key": "first", "skill": "demo-code", "title": "First", "text": "Do it.", "agent": "engineering"}])
    step = ctx["store"].step_task_add(ctx["conn"], key="beside", title="B", text="B.", step="ingest", request_id=code["request"])
    ctx["store"].task_claim(ctx["conn"], code["tasks"][0]["id"])
    running = ops_runs.running_and_effects(ctx, {})
    assert parallel.admit(ops_runs.item_of(task(world, step["task"]), {}), running, [], ctx["cfg"]["area_agents"], 5) == (True, "")


def test_a_step_task_waits_in_the_status_only_by_its_slots_and_the_files_in_use_never_by_no_agent(world):
    agents(world)
    held = writer_step(world, "docs/business/market.md")["task"]
    other = market_skill(world)
    ctx = ctx_of(world)
    ctx["store"].task_claim(ctx["conn"], other)
    with alive(world, other):
        out = ops.dispatch(world["path"], wait=False)
    assert out["started"] == []
    reasons = {h["task_id"]: h["why"] for h in out["held"]}
    assert reasons == {held: parallel.IN_USE}


# --- readers of tasks cope with a task that has no skill ---------------------------------------------------------------------


def test_the_readers_of_tasks_cope_with_a_step_task_in_every_state_it_takes(world):
    agents(world)
    ctx = ctx_of(world)
    made = add_step(world, file=csv_file(world))
    ops.status(world["path"])
    ops.task(world["path"], made["task"])
    ops.agents(world["path"])
    ops.progress(world["path"])
    ops.run_task(world["path"], made["task"])
    for read in (ops.status, ops.agents, ops.progress, ops.pending, ops.costs, ops.skills, ops.artifacts):
        read(world["path"])
    shown = ops.status(world["path"])
    row = next(t for r in shown["requests"] for t in r["tasks"] if t["id"] == made["task"])
    assert row["state"] == "done" and row["skill"] is None and row["agent"] == "runtime"
    ctx["store"].step_task_add(ctx["conn"], key="w", title="W", text="W.", step="demo", request_id=made["request"])
    waiting = ctx["store"].task_claim(ctx["conn"], ctx["store"].tasks_list(ctx["conn"], made["request"])[-1]["id"])["task"]["id"]
    ctx["store"].step_task_move(ctx["conn"], waiting, state="waiting", pending={"kind": "question", "title": "T", "body": "B"})
    for read in (ops.status, ops.agents, ops.progress, ops.pending):
        read(world["path"])
    listed = ops.status(world["path"])["pending"]
    assert [p["task_id"] for p in listed] == [waiting] and listed[0]["agent"] == "runtime"
    answered = ops.answer(world["path"], listed[0]["id"], "Looks right.")
    assert task(world, waiting)["state"] == "ready" and answered["state"] == {"written": True}
    state_file = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert f"Answer to a step task (pending decision {listed[0]['id']}): Looks right. (user)" in state_file
    assert "None" not in state_file


def test_retry_a_derived_after_wait_the_go_ahead_and_cancel_work_on_a_step_task(world):
    first = add_step(world, source="later", file=str(world["files"] / "later.csv"), key="first")
    ops.run_step(world["path"], first["task"])                                       # the file is missing: the task fails
    retried = ops.retry(world["path"], first["task"])
    assert retried["state"] == "ready" and retried["previous"] == "failed"
    ctx = ctx_of(world)
    second = add_step(world, source="other", key="second")                           # a request of its own
    ctx["store"].request_after_set(ctx["conn"], second["request"], first["request"])
    st.load("ops_waits").rederive(ctx)
    assert task(world, second["task"])["state"] == "planned"                         # it waits for request 1, as a skill task would
    went = ops.go_ahead(world["path"], second["task"], drop_after=True)
    assert went["state"] == "ready" and went["decision"] == {"written": True}
    state_file = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert f"Go ahead on step-ingest (task {second['task']})" in state_file and "None" not in state_file
    cancelled = ops.cancel(world["path"], first["request"])
    assert task(world, first["task"])["state"] == "cancelled" and first["task"] in cancelled["cancelled"]
