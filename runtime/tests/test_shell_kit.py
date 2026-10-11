"""Tests of the kit the two shells share (runtime/shell_kit.py): that the local service and the MCP mode import it and
hold no copy of what it owns, that it imports nothing of the runtime, and what its pieces do (the status words of the
operations layer's codes, the project id and list, the job registry, the end of the runs).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_shell_kit.py
"""
from __future__ import annotations

import ast
import threading
import types

import pytest

import standin_tree as st

kit = st.load("shell_kit")
service = st.load("service")
mcp = st.load("mcp")
ops = st.load("ops")
operations = st.load("operations")

# Every name the shells used to define each for themselves and the kit owns now. Defined once in the runtime package,
# in the kit, and in no other module.
OWNED = {
    "project_id", "projects_of", "status_of", "STATUS_OF_CODE", "EXPOSED_KINDS", "JOBS_KEPT", "STOP_WAIT", "INTERNAL",
    "Jobs", "Busy", "Stopping", "start_job", "end_runs", "projects_list", "job_shown", "default_log",
    # the private names of the old copies: they must not come back
    "_public", "_run_job", "_projects_of", "_projects_list", "_end_runs", "_word_of", "_default_log", "_job_value",
}
SHELLS = ("service.py", "mcp.py")


def _definitions(path):
    """The names a file defines anywhere in it: a def, a class, an assignment to a name."""
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names += [t.id for t in targets if isinstance(t, ast.Name)]
    return names


def _imports(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
    return found


def test_each_shared_name_is_defined_in_the_kit_and_in_no_other_module_of_the_runtime():
    owners = {}
    for path in sorted(st.RUNTIME.rglob("*.py")):
        if "tests" in path.relative_to(st.RUNTIME).parts:
            continue
        for name in _definitions(path):
            if name in OWNED:
                owners.setdefault(name, []).append(path.relative_to(st.RUNTIME).as_posix())
    assert {n for n, where in owners.items() if where != ["shell_kit.py"]} == set(), owners
    assert {"project_id", "projects_of", "status_of", "STATUS_OF_CODE", "EXPOSED_KINDS", "JOBS_KEPT", "Jobs", "Busy",
            "Stopping", "start_job", "end_runs", "projects_list"} <= set(owners)


@pytest.mark.parametrize("shell", SHELLS)
def test_a_shell_imports_the_kit_and_defines_none_of_what_it_owns(shell):
    path = st.RUNTIME / shell
    assert "shell_kit" in _imports(path)
    assert not set(_definitions(path)) & OWNED, set(_definitions(path)) & OWNED
    # the job registry is the kit's: a shell's state class is its subclass
    cls = {"service.py": service.Service, "mcp.py": mcp.Server}[shell]
    assert issubclass(cls, kit.Jobs)
    assert "start_job" not in vars(cls) and "end_runs" not in vars(cls) and "projects_list" not in vars(cls)


def test_the_two_shells_hold_the_kits_own_objects_not_copies():
    assert service.project_id is kit.project_id and mcp.project_id is kit.project_id
    assert service.EXPOSED_KINDS is kit.EXPOSED_KINDS and mcp.EXPOSED_KINDS is kit.EXPOSED_KINDS
    assert service.Busy is kit.Busy and service.Stopping is kit.Stopping
    assert mcp._projects_of is kit.projects_of


def test_the_kit_imports_nothing_of_the_runtime_and_only_the_standard_library():
    imported = _imports(st.RUNTIME / "shell_kit.py")
    local = {p.stem for p in st.RUNTIME.glob("*.py")}
    assert not imported & local, imported & local
    assert imported <= {"__future__", "datetime", "hashlib", "os", "sys", "threading", "time", "traceback"}
    assert not imported & {"providers", "evals", "adapters", "scripts", "sqlite3"}


def test_the_status_words_are_one_mapping_and_both_shells_answer_with_it():
    assert kit.STATUS_OF_CODE == {1: (409, "refused"), 2: (400, "usage"), 3: (412, "not_configured")}
    for code, (status, word) in kit.STATUS_OF_CODE.items():
        error = ops.OpsError("no", code)
        assert kit.status_of(error) == (status, word)
        assert service._ops_error(error)[0] == status
        assert mcp._fail_of(word, status, "no").word == word
    assert kit.status_of(ops.OpsError("x", 9)) == (500, "internal") == kit.status_of(ValueError("x"))
    assert service.WORDS["internal"] == mcp.WORDS["internal"] == kit.INTERNAL


def test_a_project_id_is_the_first_twelve_hex_characters_of_the_hash_of_the_real_path(tmp_path):
    folder = tmp_path / "one"
    folder.mkdir()
    link = tmp_path / "link"
    link.symlink_to(folder)
    first = kit.project_id(str(folder))
    assert len(first) == 12 and int(first, 16) >= 0 and kit.project_id(str(link)) == first
    assert kit.project_id(str(tmp_path / "two")) != first


def test_the_project_list_is_checked_once_per_real_path_and_a_folder_that_is_not_a_project_ends_it(tmp_path):
    calls = []

    class Fake:
        OpsError = ops.OpsError

        def config(self, path):
            calls.append(path)
            if path.endswith("bad"):
                raise ops.OpsError("not a project", 3)
            return {"data_dir": path + "/data"}

    (tmp_path / "a").mkdir()
    (tmp_path / "bad").mkdir()
    (tmp_path / "ln").symlink_to(tmp_path / "a")
    found = kit.projects_of([str(tmp_path / "a"), str(tmp_path / "ln"), str(tmp_path / "a")], Fake())
    assert [p["name"] for p in found] == ["a"] and len(calls) == 1 and found[0]["data_dir"].endswith("/a/data")
    with pytest.raises(ops.OpsError):
        kit.projects_of([str(tmp_path / "bad")], Fake())


class Ops:
    """The operations object a registry is given: the table's rows, OpsError, stop_runs."""
    OpsError = ops.OpsError
    operations = operations

    def __init__(self):
        self.stopped = 0

    def stop_runs(self, project=None):
        self.stopped += 1


def registry(log=None):
    return kit.Jobs(Ops(), [{"id": "aaaaaaaaaaaa", "name": "p", "path": "/p"}], log)


def test_a_job_runs_in_a_thread_is_polled_and_gives_back_its_model_slot():
    jobs = registry()
    gate = threading.Event()
    job, thread, shown = jobs.start_job("aaaaaaaaaaaa", "route", lambda: gate.wait(5) and {"ok": 1})
    assert shown["state"] == "running" and shown["result"] is None and set(shown) == set(kit.JOB_FIELDS)
    assert jobs.running("aaaaaaaaaaaa") and jobs.exclusive == {"aaaaaaaaaaaa": "job 1"}
    gate.set()
    thread.join(5)
    done = jobs.job_shown(job["job"])
    assert done["state"] == "done" and done["result"] == {"ok": 1} and done["error"] is None and done["ended_at"]
    assert not jobs.exclusive and not jobs.running("aaaaaaaaaaaa") and jobs.job_shown(99) is None


def test_a_second_model_job_is_busy_a_stopping_registry_starts_none_and_a_job_without_a_model_takes_no_slot():
    jobs = registry()
    gate = threading.Event()
    jobs.start_job("aaaaaaaaaaaa", "route", lambda: gate.wait(5))
    with pytest.raises(kit.Busy, match="job 1 is running for this project"):
        jobs.start_job("aaaaaaaaaaaa", "route", lambda: None)
    plain = next(r["name"] for r in operations.OPERATIONS if r.get("job") and not r["model"])
    other = jobs.start_job("aaaaaaaaaaaa", plain, lambda: 1)
    other[1].join(5)
    assert jobs.job_shown(other[0]["job"])["state"] == "done"
    jobs.stopping.set()
    with pytest.raises(kit.Stopping):
        jobs.start_job("aaaaaaaaaaaa", plain, lambda: None)
    gate.set()


def test_a_job_that_queues_starts_while_the_slot_is_held_and_leaves_the_slot_to_its_holder():
    """A-23: the row's `queues` key means the operation itself finds the run lock held and queues the call, so the
    registry does not refuse it for a held slot; it takes no slot of its own and gives none back."""
    jobs = registry()
    gate = threading.Event()
    holder = jobs.start_job("aaaaaaaaaaaa", "route", lambda: gate.wait(5))
    held = dict(jobs.exclusive)
    queued = jobs.start_job("aaaaaaaaaaaa", "say", lambda: {"queued": True}, queues=True)
    queued[1].join(5)
    assert jobs.job_shown(queued[0]["job"])["result"] == {"queued": True} and jobs.exclusive == held
    with pytest.raises(kit.Busy):
        jobs.start_job("aaaaaaaaaaaa", "say", lambda: None)                              # without the key it is still refused
    gate.set()
    holder[1].join(5)
    # with the slot free, a job that queues takes it like any other, so that a dispatch round waits for it
    wait = threading.Event()
    first = jobs.start_job("aaaaaaaaaaaa", "say", lambda: wait.wait(5), queues=True)
    assert jobs.exclusive == {"aaaaaaaaaaaa": f"job {first[0]['job']}"}
    wait.set()
    first[1].join(5)


def test_a_failure_of_a_job_is_the_jobs_own_a_refusal_with_its_word_and_anything_else_internal_with_the_trace_in_the_log():
    lines = []
    jobs = registry(lines.append)
    refused = jobs.start_job("aaaaaaaaaaaa", "route", lambda: (_ for _ in ()).throw(ops.OpsError("wrong hash", 1)))
    refused[1].join(5)
    assert jobs.job_shown(refused[0]["job"])["error"] == {"error": "refused", "message": "wrong hash", "status": 409}
    broken = jobs.start_job("aaaaaaaaaaaa", "route", lambda: {}["secret path"])
    broken[1].join(5)
    error = jobs.job_shown(broken[0]["job"])["error"]
    assert error == {"error": "internal", "message": "internal error", "status": 500} and "secret path" not in str(error)
    assert any("failed:" in line and "KeyError" in line for line in lines) and not jobs.exclusive


def test_only_the_last_finished_jobs_are_kept():
    jobs = registry()
    plain = next(r["name"] for r in operations.OPERATIONS if r.get("job") and not r["model"])
    for _ in range(kit.JOBS_KEPT + 5):
        jobs.start_job("aaaaaaaaaaaa", plain, lambda: None)[1].join(5)
    assert len(jobs.jobs) <= kit.JOBS_KEPT + 1 and 1 not in jobs.jobs and jobs.counter in jobs.jobs


def test_ending_the_runs_calls_stop_runs_at_least_once_waits_for_the_threads_and_counts_what_is_left():
    jobs = registry()
    assert jobs.end_runs() == 0 and jobs.ops.stopped == 1
    gate = threading.Event()
    extra = threading.Thread(target=gate.wait, args=(5,), daemon=True)
    extra.start()
    assert jobs.end_runs([extra], wait=0.2) == 1 and jobs.ops.stopped >= 2
    gate.set()
    extra.join(5)
    assert jobs.end_runs([extra]) == 0


def test_the_project_list_shows_each_projects_hash_and_counts_and_a_refused_project_only_its_message():
    class Listed(Ops):
        def config(self, path):
            if path == "/bad":
                raise ops.OpsError("not accepted", 3)
            return {"sha256": "a" * 64, "accepted": 1}

        def status(self, path):
            if path == "/half":
                raise ops.OpsError("no state", 3)
            return {"pending": [1, 2], "requests": [{"tasks": [{"id": 7, "state": "running"}]}]}

    jobs = kit.Jobs(Listed(), [{"id": "1", "name": "ok", "path": "/ok"}, {"id": "2", "name": "bad", "path": "/bad"},
                               {"id": "3", "name": "half", "path": "/half"}])
    listed = jobs.projects_list()["projects"]
    assert listed[0] == {"id": "1", "name": "ok", "folder": "/ok", "config": {"sha256": "a" * 64, "accepted": True},
                         "open_pending": 2, "running_task": 7, "routing_request": None}   # R4-L1: the new key, null while no router run holds a request
    assert listed[1] == {"id": "2", "name": "bad", "folder": "/bad", "config": {"accepted": False}, "message": "not accepted"}
    assert [e["folder"] for e in listed] == ["/ok", "/bad", "/half"], "A-34: every entry carries the folder, accepted or not"
    assert listed[2]["message"] == "no state" and "open_pending" not in listed[2] and listed[2]["config"]["accepted"]


def test_the_shells_registries_differ_only_by_what_each_shell_adds():
    ids = [{"id": "aaaaaaaaaaaa", "name": "p", "path": "/p"}]
    svc = service.Service(Ops(), ids, "t" * 64, 1)
    server = mcp.Server(Ops(), ids)
    job = {key: None for key in kit.JOB_FIELDS}
    job.update(job=4, state="running")
    assert "poll" not in svc.public(job) and server.public(job)["poll"] == {"tool": "job", "arguments": {"job": 4}}
    job["state"] = "done"
    assert svc.public(job) == server.public(job)


def test_a_job_the_registry_pruned_before_the_mcp_tool_reads_it_is_still_shown_or_refused_as_itself():
    class Pruned(mcp.Server):
        def job_shown(self, number):
            return None

    standin = Ops()
    standin.route = lambda project, **kwargs: {"done": True}

    def refuse(project, **kwargs):
        raise ops.OpsError("wrong hash", 1)

    for function, expected in ((standin.route, None), (refuse, "wrong hash")):
        standin.route = function
        server = Pruned(standin, [{"id": "aaaaaaaaaaaa", "name": "p", "path": "/p"}], grace=2.0)
        result = mcp.call_tool(server, "route", {"request_id": 1})
        if expected is None:
            assert '"state": "done"' in result["content"][0]["text"] and result["isError"] is False
        else:
            assert result["isError"] is True and expected in result["content"][0]["text"]
