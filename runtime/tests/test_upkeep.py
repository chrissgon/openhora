"""Retention and the dispatcher's upkeep (package P-OPS, finding I6): run folders past their age, old source versions, and the pass
that does both and sweeps orphan containers. Offline: a stand-in converter, a fake container tool, a fake store where only the answer
of one row matters; nothing real is touched.

  L29  upkeep deletes only inside data_dir and the sources folder, never follows a symbolic link, and never removes a run that is live,
       a version a task that is not finished received, or a shared container

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_upkeep.py
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
from sources_fixture import standin_convert

ops = st.load("ops")
ops_core = st.load("ops_core")
sources = st.load("sources")
project_config = st.load("project_config")
lease = st.load("lease")
upkeep = st.load("upkeep")
REPO = st.REPO
DAY = 86400.0
RUN_A = "0123456789abcdef"


def write_config(tmp_path, **overrides) -> str:
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True, exist_ok=True)
    config = {"workbench": str(REPO), "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "store" / "tasks.sqlite"),
              "sources_dir": str(tmp_path / "sources")}
    config.update(overrides)
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps({k: v for k, v in config.items() if v is not None}), encoding="utf-8")
    return str(project)


@pytest.fixture(autouse=True)
def isolated_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))


@pytest.fixture
def case(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    ops.accept_config(path, project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    (tmp_path / "files").mkdir()
    row = sources.register(ctx, "survey", "file", "survey.csv")
    return SimpleNamespace(path=path, ctx=ctx, cfg=ctx["cfg"], folder=Path(ctx["cfg"]["sources_dir"]), data=Path(ctx["cfg"]["data_dir"]),
                           tmp=tmp_path, row=row)


def import_version(case, n: int) -> dict:
    """Import version n (the text differs for each, so each is a new version)."""
    target = case.tmp / "files" / "survey.csv"
    target.write_text(f"name,price\napple,{n}.00\n", encoding="utf-8")
    return sources.import_version(case.ctx, case.row, str(target), convert=standin_convert, label="import" if n == 1 else "refresh")


def age(path: Path, days: float, now=None):
    """Make a folder and its entries `days` old at `now`."""
    stamp = (now or time.time()) - days * DAY
    for item in [path, *path.iterdir()]:
        os.utime(item, (stamp, stamp), follow_symlinks=False)


def make_run(base: Path, name: str, days: float, now=None) -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "prompt.md").write_text("x")
    (folder / "outputs").mkdir()
    (folder / "outputs" / "raw.json").write_text("{}")
    age(folder, days, now)
    return folder


class StoreError(Exception):
    pass


class FakeStore:
    """Only what the retention of run folders asks of the store: rows of task_runs and tasks, and the open pending decisions."""
    StoreError = StoreError

    def __init__(self, rows=None, tasks=None, pendings=None):
        self.rows, self.tasks, self.pendings = rows or {}, tasks or {}, pendings or []

    def task_run_get(self, conn, run_id):
        if run_id not in self.rows:
            raise StoreError(f"no task run {run_id}")
        return self.rows[run_id]

    def task_get(self, conn, task_id):
        return self.tasks.get(task_id, {"state": "done", "parent_id": None})   # a task nobody described is finished

    def pending_list(self, conn, status="open", task_id=None):
        return self.pendings


def fake_ctx(tmp_path, rows=None, tasks=None, pendings=None, **cfg):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    return {"cfg": {"data_dir": str(data), **cfg}, "store": FakeStore(rows, tasks, pendings), "conn": None}


# --- run folders -----------------------------------------------------------------------------------------------------------------


def test_run_folders_past_their_age_are_removed_and_a_younger_one_and_a_running_one_are_kept(tmp_path):
    ctx = fake_ctx(tmp_path, {3: {"status": "running", "task_id": 30}, 4: {"status": "finished", "task_id": 9}})
    base = Path(ctx["cfg"]["data_dir"]) / "task-runs"
    old, young = make_run(base, "1", 45), make_run(base, "2", 5)
    running, locked = make_run(base, "3", 90), make_run(base, "4", 90)
    last = make_run(base, "5", 31)
    children = make_run(base, "children", 90)
    locks = Path(ctx["cfg"]["data_dir"]) / "locks"
    locks.mkdir(mode=0o700)
    held = os.open(locks / "task-9.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)   # a live process holds the lock of the task of run 4
    try:
        result = upkeep.sweep_runs(ctx, now=time.time(), days=30)
    finally:
        os.close(held)
    assert sorted(Path(p).name for p in result["removed"]) == ["1", "5"]
    assert not old.exists() and not last.exists()
    assert young.exists(), "a run younger than the age stays"
    assert running.exists() and (running / "prompt.md").exists(), "a run that is running stays whatever its age"
    assert locked.exists(), "a run whose task's lock is held by a live process stays"
    assert children.exists(), "the dispatcher's output files have their own age"
    why = {Path(k["path"]).name: k["why"] for k in result["kept"]}
    assert why == {"3": "the run is running", "4": "a live process holds the task's lock"}


def test_a_run_folder_with_a_recent_file_is_recent_whatever_its_own_date(tmp_path):
    ctx = fake_ctx(tmp_path)
    base = Path(ctx["cfg"]["data_dir"]) / "task-runs"
    folder = make_run(base, "7", 60)
    (folder / "outputs" / "late.txt").write_text("a run still writing")
    result = upkeep.sweep_runs(ctx, now=time.time(), days=30)
    assert result["removed"] == [] and folder.exists()


def test_a_folder_with_no_row_is_removed_by_age_alone_and_a_store_that_fails_keeps_the_folder(tmp_path):
    ctx = fake_ctx(tmp_path)
    base = Path(ctx["cfg"]["data_dir"]) / "task-runs"
    gone = make_run(base, "8", 40)
    assert upkeep.sweep_runs(ctx, now=time.time(), days=30)["removed"] == [str(gone)]

    class Broken:
        StoreError = StoreError

        @staticmethod
        def task_run_get(conn, run_id):
            raise RuntimeError("the database is locked")
    ctx["store"] = Broken
    kept = make_run(base, "9", 40)
    result = upkeep.sweep_runs(ctx, now=time.time(), days=30)
    assert kept.exists() and result["kept"][0]["why"].startswith("the store could not be asked")


def test_the_contained_runs_go_by_age_too_and_the_highest_number_stays(tmp_path):
    ctx = fake_ctx(tmp_path)
    base = Path(ctx["cfg"]["data_dir"]) / "contained-runs"
    folders = [make_run(base, str(n), 50) for n in (1, 2, 3)]
    recent = make_run(base, "4", 1)
    result = upkeep.sweep_runs(ctx, now=time.time(), days=30)
    assert sorted(Path(p).name for p in result["removed"]) == ["1", "2", "3"] and recent.exists()
    assert not any(f.exists() for f in folders)
    # the highest number of all is kept when it is old too, so that the next folder is numbered after it
    only = fake_ctx(tmp_path / "second")
    base2 = Path(only["cfg"]["data_dir"]) / "contained-runs"
    old = [make_run(base2, str(n), 50) for n in (1, 2, 3)]
    upkeep.sweep_runs(only, now=time.time(), days=30)
    assert not old[0].exists() and not old[1].exists() and old[2].exists()


def test_a_link_in_place_of_a_run_folder_is_not_followed_and_not_removed(tmp_path):
    ctx = fake_ctx(tmp_path)
    base = Path(ctx["cfg"]["data_dir"]) / "task-runs"
    base.mkdir()
    outside = make_run(tmp_path / "elsewhere", "precious", 400)
    (base / "11").symlink_to(outside, target_is_directory=True)
    inner = make_run(base, "12", 50)
    (inner / "outputs" / "escape").symlink_to(outside, target_is_directory=True)
    age(inner / "outputs", 50)
    age(inner, 50)
    result = upkeep.sweep_runs(ctx, now=time.time(), days=30)
    assert (outside / "prompt.md").exists() and (outside / "outputs" / "raw.json").exists(), "nothing outside was touched"
    assert (base / "11").is_symlink(), "the link is left as it is"
    assert not inner.exists() and result["removed"] == [str(inner)], "the folder went, with the link in it, and not what it pointed to"


def test_a_data_folder_that_does_not_exist_yet_is_not_an_error(tmp_path):
    ctx = {"cfg": {"data_dir": str(tmp_path / "none")}, "store": FakeStore(), "conn": None}
    assert upkeep.sweep_runs(ctx, now=time.time(), days=30) == {"removed": [], "kept": []}


def test_the_folder_of_a_run_that_ended_at_a_gate_is_kept_while_its_task_or_request_is_open_or_a_pending_decision_names_it(tmp_path):
    """The reviewer's case: a run that ended ok at a confirmation gate, 31 days ago, its task waiting, its lock file present and not held.
    Its effect document and its change set live in the folder; approving, and the next code task of the request, need them."""
    rows = {n: {"status": "ok", "task_id": n} for n in (1, 2, 3, 4, 5)}
    tasks = {1: {"state": "waiting", "parent_id": 90},      # waiting at the gate, in an open request
             2: {"state": "done", "parent_id": 91},         # finished itself, in a request still open (the next code task builds on it)
             3: {"state": "failed", "parent_id": 92},       # can be retried
             4: {"state": "done", "parent_id": 93},         # finished, in a finished request
             5: {"state": "cancelled", "parent_id": 93},    # finished, but a pending decision still names its run
             91: {"state": "ready", "parent_id": None}, 93: {"state": "done", "parent_id": None}}
    ctx = fake_ctx(tmp_path, rows, tasks, pendings=[{"run_id": 5, "task_id": 5}])
    base = Path(ctx["cfg"]["data_dir"]) / "task-runs"
    folders = {n: make_run(base, str(n), 31) for n in rows}
    locks = Path(ctx["cfg"]["data_dir"]) / "locks"
    locks.mkdir(mode=0o700)
    (locks / "task-1.lock").write_text("")        # present and not held
    result = upkeep.sweep_runs(ctx, now=time.time(), days=30)
    assert [folders[n].exists() for n in (1, 2, 3, 4, 5)] == [True, True, True, False, True]
    why = {Path(k["path"]).name: k["why"] for k in result["kept"]}
    assert why == {"1": "its task is waiting, not finished", "2": "its request is not finished", "3": "its task is failed, not finished",
                   "5": "an open pending decision references the run"}


def test_a_real_run_that_ended_at_a_gate_keeps_its_folder_until_the_request_is_cancelled(case):
    store, conn = case.ctx["store"], case.ctx["conn"]
    made = store.request_add(conn, title="Study", text="Study.", flow="demo", tasks=[
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "do it.", "depends_on": [], "milestone": False}])
    task = made["tasks"][0]["id"]
    store.task_claim(conn, task)
    run = store.task_run_start(conn, task, skill="demo-asks", model="m", adapter="a")["run_id"]
    store.task_run_finish(conn, run, status="ok", task_state="waiting",
                          pending={"kind": "effect", "title": "Open a pull request", "body": "x"})
    folder = make_run(case.data / "task-runs", str(run), 31)
    (case.data / "effects").mkdir(exist_ok=True)
    assert upkeep.sweep_runs(case.ctx, now=time.time(), days=30)["removed"] == [] and folder.exists()
    store.request_cancel(conn, made["request"], by="person")
    assert upkeep.sweep_runs(case.ctx, now=time.time(), days=30)["removed"] == [str(folder)]


# --- source versions -------------------------------------------------------------------------------------------------------------


def start_task_that_received(case, version: int):
    """A task that is running and recorded that it received `version` of the source (the rows task_sources)."""
    store, conn = case.ctx["store"], case.ctx["conn"]
    made = store.request_add(conn, title="Study", text="Study the fruit market.", flow="demo", tasks=[
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "do it.", "depends_on": [], "milestone": False,
         "sources": ["survey"]}])
    task = made["tasks"][0]["id"]
    store.task_claim(conn, task)
    run = store.task_run_start(conn, task, skill="demo-asks", model="m", adapter="a")["run_id"]
    row = store.source_version_get(conn, "survey", version)
    store.task_source_record(conn, run_id=run, task_id=task, source_id="survey", version=version, sha256=row["converted_sha256"])
    return made["request"], task, run


def folders(case):
    return sorted(int(p.name) for p in (case.folder / "survey").iterdir() if p.name.isdigit())


def test_the_oldest_versions_beyond_the_number_kept_are_removed_and_the_rows_stay(case):
    for n in range(1, 7):
        import_version(case, n)
    assert folders(case) == [1, 2, 3, 4, 5, 6]
    result = upkeep.sweep_versions(case.ctx, kept=3)
    assert sorted(r["version"] for r in result["removed"]) == [1, 2, 3] and result["problem"] is None
    assert folders(case) == [4, 5, 6]
    assert case.ctx["store"].source_version_count(case.ctx["conn"], "survey") == 6, "the store never deletes a version's row"
    assert upkeep.sweep_versions(case.ctx, kept=3)["removed"] == [], "a second pass finds nothing more"
    # the newest version still reads as it was, and the next import is numbered after the highest recorded one
    assert sources.list_catalog(case.ctx)[0]["status"] == "ok"
    assert import_version(case, 7)["version"] == 7 and folders(case) == [4, 5, 6, 7]


def test_a_version_a_task_that_is_running_received_is_kept_until_the_task_is_finished(case):
    for n in range(1, 7):
        import_version(case, n)
    request, task, run = start_task_that_received(case, 1)
    result = upkeep.sweep_versions(case.ctx, kept=2)
    assert folders(case) == [1, 5, 6], "version 1 is old but a running task received it"
    assert result["kept"] == [{"source": "survey", "version": 1, "why": "a task that is not finished received it"}]
    # the run ends in failure: the task can be retried, so it is not finished and its version stays
    case.ctx["store"].task_run_finish(case.ctx["conn"], run, status="failed", task_state="failed", failure="internal")
    upkeep.sweep_versions(case.ctx, kept=2)
    assert folders(case) == [1, 5, 6]
    # the request is cancelled: the task is finished, and nothing waits for the version any more
    case.ctx["store"].request_cancel(case.ctx["conn"], request, by="person")
    assert case.ctx["store"].task_get(case.ctx["conn"], task)["state"] == "cancelled"
    upkeep.sweep_versions(case.ctx, kept=2)
    assert folders(case) == [5, 6]


def test_a_task_that_is_waiting_or_ready_and_not_finished_keeps_its_version_and_a_done_task_does_not(case):
    for n in range(1, 4):
        import_version(case, n)
    states = {1: "waiting", 2: "done"}   # task 1 received version 1, task 2 version 2
    case.ctx["store"] = SimpleNamespace(
        **{name: getattr(case.ctx["store"], name) for name in ("sources_list", "source_versions")},
        tasks_list=lambda conn: [{"id": i, "state": s} for i, s in states.items()],
        task_sources_of=lambda conn, task_id: [{"source_id": "survey", "version": task_id}])
    assert upkeep.protected_versions(case.ctx) == {("survey", 1)}
    result = upkeep.sweep_versions(case.ctx, kept=1)
    assert folders(case) == [1, 3] and result["removed"] == [{"source": "survey", "version": 2}]


def test_a_version_folder_that_is_a_link_is_not_followed(case):
    for n in range(1, 5):
        import_version(case, n)
    outside = case.tmp / "elsewhere"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    shutil.rmtree(case.folder / "survey" / "1")
    (case.folder / "survey" / "1").symlink_to(outside, target_is_directory=True)
    upkeep.sweep_versions(case.ctx, kept=2)
    assert (outside / "precious.txt").read_text() == "keep" and (case.folder / "survey" / "1").is_symlink()
    assert folders(case) == [1, 3, 4], "the link stayed, and the real old version beside it went"


def test_another_hosts_live_lease_stops_the_removal_and_names_the_host(case):
    for n in range(1, 5):
        import_version(case, n)
    (case.folder / lease.LEASE_NAME).write_text(json.dumps(
        {"host_id": "00ff00ff00ff00ff", "host_name": "laptop-two", "pid": 4242, "taken_at": "x", "expires_at": time.time() + 200}), encoding="utf-8")
    result = upkeep.sweep_versions(case.ctx, kept=2)
    assert result["removed"] == [] and "laptop-two" in result["problem"] and folders(case) == [1, 2, 3, 4]


def test_the_removal_waits_when_an_import_holds_the_sources_lock(case):
    for n in range(1, 5):
        import_version(case, n)
    with sources.intake.Lock(sources.sources_lock_path(case.cfg)):
        result = upkeep.sweep_versions(case.ctx, kept=2)
    assert result["removed"] == [] and "sources lock" in result["problem"] and folders(case) == [1, 2, 3, 4]


def test_a_source_with_fewer_versions_than_the_number_kept_loses_none(case):
    import_version(case, 1)
    assert upkeep.sweep_versions(case.ctx, kept=5)["removed"] == [] and folders(case) == [1]


# --- the keys of runtime.json ----------------------------------------------------------------------------------------------------


def test_the_retention_keys_have_defaults_and_bounds_and_are_known_keys_of_the_file(tmp_path):
    loaded = project_config.load(write_config(tmp_path))
    assert (loaded["run_retention_days"], loaded["source_versions_kept"]) == (30, 5)
    custom = project_config.load(write_config(tmp_path, run_retention_days=7, source_versions_kept=10))
    assert (custom["run_retention_days"], custom["source_versions_kept"]) == (7, 10)
    for key, bad in (("run_retention_days", 0), ("run_retention_days", 3651), ("run_retention_days", "30"), ("run_retention_days", True),
                     ("source_versions_kept", 1), ("source_versions_kept", 1001), ("source_versions_kept", 2.5)):
        with pytest.raises(project_config.ConfigError) as refused:
            project_config.load(write_config(tmp_path, **{key: bad}))
        assert key in str(refused.value)
    assert "run_retention_days" in project_config.TASK_RUNTIME_KEYS and "source_versions_kept" in project_config.TASK_RUNTIME_KEYS


# --- the pass --------------------------------------------------------------------------------------------------------------------


class RecordingDocker:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return (0, "")


def test_a_pass_does_the_three_parts_once_an_hour_and_records_it(case):
    for n in range(1, 5):
        import_version(case, n)
    make_run(case.data / "task-runs", "1", 80)
    tool = RecordingDocker()
    cfg = {**case.cfg, "run_retention_days": 30, "source_versions_kept": 2}
    ctx = {**case.ctx, "cfg": cfg}
    now = time.time()
    first = upkeep.run(ctx, now=now, tool=tool)
    assert "skipped" not in first and [Path(p).name for p in first["runs"]["removed"]] == ["1"]
    assert [v["version"] for v in first["versions"]["removed"]] == [1, 2] and folders(case) == [3, 4]
    assert json.loads((case.data / upkeep.STATE_FILE).read_text())["at"] == now
    assert upkeep.run(ctx, now=now + 3599, tool=tool) == {"skipped": "done less than an hour ago"}
    assert "skipped" not in upkeep.run(ctx, now=now + 3601, tool=tool)
    assert "skipped" not in upkeep.run(ctx, now=now + 3602, tool=tool, force=True)


def test_the_automatic_pass_sends_no_image_command_at_all(case):
    """The images of earlier definitions are removed only by `python3 scripts/doctor.py --remove-old-images --confirmed`: a pass of the
    upkeep (the dispatcher's round runs it every hour) lists and removes containers and sends nothing about images."""
    tool = RecordingDocker()
    ctx = {**case.ctx, "cfg": {**case.cfg, "run_retention_days": 30, "source_versions_kept": 2}}
    assert "skipped" not in upkeep.run(ctx, now=time.time(), tool=tool, force=True)
    assert tool.calls, "the sweep of containers asked the tool"
    assert not [c for c in tool.calls if c[0] in ("image", "rmi", "system") or "prune" in c or "--force" in c]


def test_two_processes_do_not_run_the_pass_together(case):
    (case.data / "locks").mkdir(mode=0o700, exist_ok=True)
    held = os.open(case.data / "locks" / upkeep.LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert upkeep.run(case.ctx, now=time.time(), tool=RecordingDocker()) == {"skipped": "another process is doing the upkeep"}
    finally:
        os.close(held)


def test_a_part_that_fails_does_not_stop_the_others_and_nothing_is_raised(case, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("the disk said no")
    monkeypatch.setattr(upkeep, "sweep_runs", explode)
    old = make_run(case.data / "task-runs", "3", 80)
    result = upkeep.run(case.ctx, now=time.time(), tool=RecordingDocker())
    assert result["runs"]["problem"] == "RuntimeError: the disk said no" and "removed" in result["versions"]
    monkeypatch.setattr(upkeep, "run", explode)
    assert upkeep.run_quietly(case.ctx) == {"skipped": "RuntimeError: the disk said no"}
    assert old.exists()


def test_the_pass_sweeps_containers_with_the_tool_it_is_given_and_not_at_all_when_it_is_switched_off(case, monkeypatch):
    tool = RecordingDocker()
    result = upkeep.run(case.ctx, now=time.time(), tool=tool, force=True)
    assert [c[0] for c in tool.calls] == ["ps", "network"] and result["containers"]["removed"] == []
    monkeypatch.setenv(upkeep.CONTAINERS_ENV, "off")
    off = upkeep.run(case.ctx, now=time.time() + 7200)
    assert off["containers"]["disabled"] is True


# --- L29 -------------------------------------------------------------------------------------------------------------------------


def test_limit_29_upkeep_removes_only_inside_the_data_and_sources_folders_never_follows_a_link_and_never_removes_what_is_live(case):
    for n in range(1, 6):
        import_version(case, n)
    request, task, run = start_task_that_received(case, 1)
    outside = case.tmp / "elsewhere"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    (outside / "task-runs").mkdir()
    runs = case.data / "task-runs"
    old, live_row = make_run(runs, str(run), 90), make_run(runs, "99", 90)
    (runs / "98").symlink_to(outside, target_is_directory=True)
    cfg = {**case.cfg, "run_retention_days": 30, "source_versions_kept": 2}
    ctx = {**case.ctx, "cfg": cfg}

    class Docker(RecordingDocker):
        def __call__(self, *args):
            self.calls.append(args)
            if args[0] == "ps":
                rows = [{"Names": "wb-eval-proxy-a1b2c3d4e5f6", "Labels": "wb.eval=1", "CreatedAt": "2020-01-01 00:00:00 +0000 UTC"},
                        {"Names": "wb-eval-keys-a1b2c3d4e5f6", "Labels": "wb.eval=1,wb.eval.run=" + RUN_A, "CreatedAt": "2020-01-01 00:00:00 +0000 UTC"},
                        {"Names": f"wb-eval-keys-{RUN_A}", "Labels": f"wb.eval=1,wb.eval.run={RUN_A}", "CreatedAt": "2020-01-01 00:00:00 +0000 UTC"}]
                return 0, "\n".join(json.dumps(r) for r in rows)
            return 0, ""
    tool = Docker()
    result = upkeep.run(ctx, now=time.time(), tool=tool, force=True)
    # run `run` is `running` (its task was claimed and the run opened): kept whatever its age; the run with no row goes by age
    assert old.exists() and not live_row.exists()
    assert (runs / "98").is_symlink() and (outside / "precious.txt").read_text() == "keep"
    assert (case.folder / "survey" / "1").exists(), "the version a running task received stays"
    assert folders(case) == [1, 4, 5]
    removed = [c for c in tool.calls if c[0] == "rm"]
    assert removed == [("rm", "-f", f"wb-eval-keys-{RUN_A}")], "only the run's own key proxy went; the shared holders and the proxy stayed"
    assert result["containers"]["removed"][0]["name"] == f"wb-eval-keys-{RUN_A}"
    # nothing outside the two folders was reached
    assert sorted(p.name for p in outside.iterdir()) == ["precious.txt", "task-runs"]


def test_a_pass_that_removes_nothing_takes_no_lease_and_one_that_removes_takes_it_and_tells_a_takeover(case):
    for n in range(1, 4):
        import_version(case, n)
    (case.folder / lease.LEASE_NAME).unlink()
    assert upkeep.sweep_versions(case.ctx, kept=5)["removed"] == [] and not (case.folder / lease.LEASE_NAME).exists()
    assert upkeep.sweep_versions(case.ctx, kept=2, dry_run=True)["removed"] and not (case.folder / lease.LEASE_NAME).exists()
    (case.folder / lease.LEASE_NAME).write_text(json.dumps(
        {"host_id": "00ff00ff00ff00ff", "host_name": "old-desktop", "pid": 1, "taken_at": "x", "expires_at": time.time() - 5}), encoding="utf-8")
    result = upkeep.sweep_versions(case.ctx, kept=2)
    assert [r["version"] for r in result["removed"]] == [1] and result["lease_took_over"] == "old-desktop"
    assert json.loads((case.folder / lease.LEASE_NAME).read_text())["host_id"] == lease.host_identity(case.cfg["data_dir"])["id"]
    assert upkeep._counts(result)["lease_took_over"] == "old-desktop"


def test_the_switch_of_the_automatic_container_sweep_is_a_key_of_runtime_json(tmp_path):
    assert project_config.load(write_config(tmp_path))["sweep_orphan_containers"] is True
    assert project_config.load(write_config(tmp_path, sweep_orphan_containers=False))["sweep_orphan_containers"] is False
    with pytest.raises(project_config.ConfigError) as refused:
        project_config.load(write_config(tmp_path, sweep_orphan_containers="no"))
    assert "sweep_orphan_containers" in str(refused.value)
    assert "sweep_orphan_containers" in project_config.TASK_RUNTIME_KEYS


# --- step tasks (P5): no run row, no run folder in data_dir; their drop lives in the project -----------------------------------------


def test_upkeep_leaves_a_step_tasks_drop_folder_and_its_task_lock_alone_and_a_step_task_that_is_not_finished_keeps_what_it_may_need(case):
    """A step task runs no skill: it has no row in task_runs and no folder under task-runs, and the file it reads is in the project's
    drop folder (.workbench-local/drop/<task id>/), outside data_dir and the sources folder, which upkeep never reaches. Its lock is
    task-<id>.lock like any task's, and upkeep neither takes, deletes nor reads it as stale."""
    store, conn = case.ctx["store"], case.ctx["conn"]
    made = store.request_add(conn, title="Ingest", text="Import the survey.", flow="demo", tasks=[
        {"key": "ingest", "step": "ingest", "args": {"source": "survey", "file": "survey.csv"}, "footprint": [], "agent": "runtime",
         "title": "Import", "text": "Import the survey.", "depends_on": [], "milestone": False}])
    task = made["tasks"][0]["id"]
    drop = Path(case.cfg["project"]) / ".workbench-local" / "drop" / str(task)
    drop.mkdir(parents=True)
    (drop / "survey.csv").write_text("name,price\napple,1.00\n")
    age(drop, 400)
    lock = case.data / "locks" / f"task-{task}.lock"
    lock.parent.mkdir(mode=0o700, exist_ok=True)
    lock.write_text("")
    old = make_run(case.data / "task-runs", "77", 90)           # a folder of no run the store knows: removed by age, as before
    cfg = {**case.cfg, "run_retention_days": 30, "source_versions_kept": 2}
    result = upkeep.run({**case.ctx, "cfg": cfg}, now=time.time(), tool=RecordingDocker(), force=True)
    assert "skipped" not in result and not old.exists()
    assert (drop / "survey.csv").exists() and lock.exists(), "nothing of a step task was touched"
    assert upkeep.task_lock_held(str(case.data), task) is False, "a lock file nobody holds is not held, and is left where it is"
    held = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert upkeep.task_lock_held(str(case.data), task) is True
    finally:
        os.close(held)
    assert upkeep.protected_versions(case.ctx) == set(), "a step task records no version it received"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
