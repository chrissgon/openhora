"""A firing recomputes the approval digest from job.json and refuses a record that differs (T44): offline tests.

Run: uv run --with pytest pytest providers/scheduler/tests/test_scheduler_approval_digest.py

The dry run of `launchd.py` and of `systemd.py` computes `approval_digest(job)`; the confirmed schedule compares it
with `--approved` and stores it as `approved`. Every firing must compute it again from the record it is about to run
and refuse when it differs, so that a job.json edited after approval never runs as it now reads. A copy's path is not
in the digest, so each copy must be where the dry run put it. No real launchd or systemd is reached: the service
managers are fake executables in a temporary folder.
"""
from __future__ import annotations

import copy as copylib
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
MARKER_CODE = "import sys; open({marker!r}, 'w').write(open(sys.argv[1]).read())"
CHANGED = "changed after approval"
UNSIGNED = "holds no approved digest"
MOVED = "is not where it was approved"
BROKEN = "no longer holds the fields it was approved with"


class Scheduler:
    def __init__(self, name: str, tmp_path: Path):
        self.name, self.tmp = name, tmp_path
        self.script = HERE / f"{name}.py"
        self.calls = tmp_path / "manager-calls.txt"
        fake = tmp_path / "manager"
        fake.write_text(f'#!/bin/sh\necho "$@" >> "{self.calls}"\nexit 0\n')
        fake.chmod(0o755)
        login = tmp_path / "loginctl"
        login.write_text("#!/bin/sh\necho yes\n")
        login.chmod(0o755)
        self.env = {**os.environ, "SCHEDULER_HOME": str(tmp_path / "jobs"), "SCHEDULER_NOTIFY": "0",
                    "SCHEDULER_TEST": "1"}
        self.env.pop("UV_PYTHON", None)
        if name == "launchd":
            self.env.update({"SCHEDULER_AGENTS_DIR": str(tmp_path / "agents"), "SCHEDULER_LAUNCHCTL": str(fake)})
        else:
            self.env.update({"SCHEDULER_UNITS_DIR": str(tmp_path / "units"), "SCHEDULER_SYSTEMCTL": str(fake),
                             "SCHEDULER_LOGINCTL": str(login)})
        self.at = (datetime.now(timezone.utc) + timedelta(minutes=1)).replace(microsecond=0).isoformat()
        self.unload_word = "bootout" if name == "launchd" else "disable"
        self.marker = tmp_path / "marker.txt"
        self.post = tmp_path / "post.txt"

    def run(self, *args, env=None):
        return subprocess.run([sys.executable, str(self.script), *args], env=env or self.env, capture_output=True,
                              text=True, timeout=120)

    def command_file(self, code=None, snapshot_text="hello", extra=None) -> Path:
        """A command that copies the content of its snapshot file into the marker, so a test sees both that it ran
        and which content it read."""
        self.post.write_text(snapshot_text)
        code = code or MARKER_CODE.format(marker=str(self.marker))
        spec = {"argv": [sys.executable, "-c", code, str(self.post)], "cwd": str(self.tmp),
                "snapshot": [str(self.post)], **(extra or {})}
        path = self.tmp / "job.json"
        path.write_text(json.dumps(spec))
        return path

    def schedule(self, path: Path, job_id="post-1", every=None):
        when = ["--every", str(every)] if every else ["--at", self.at]
        dry = self.run("schedule", "--id", job_id, *when, "--command-file", str(path), "--dry-run")
        assert dry.returncode == 0, dry.stderr
        done = self.run("schedule", "--id", job_id, *when, "--command-file", str(path), "--confirmed",
                        "--approved", json.loads(dry.stdout)["approved"])
        assert done.returncode == 0, done.stderr
        return json.loads(dry.stdout)

    def job_path(self, job_id="post-1") -> Path:
        return Path(self.env["SCHEDULER_HOME"]) / job_id / "job.json"

    def job(self, job_id="post-1") -> dict:
        return json.loads(self.job_path(job_id).read_text())

    def edit(self, job_id, change) -> None:
        data = self.job(job_id)
        change(data)
        path = self.job_path(job_id)
        path.write_text(json.dumps(data))
        os.chmod(path, 0o600)

    def firings(self, job_id="tick") -> list:
        path = Path(self.env["SCHEDULER_HOME"]) / job_id / "runs.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def fire(self, job_id="post-1"):
        before = self.calls.read_text() if self.calls.exists() else ""
        fired = self.run("run", "--id", job_id)
        after = self.calls.read_text() if self.calls.exists() else ""
        self.unloaded = self.unload_word in after[len(before):]
        return fired

    def listed(self, job_id) -> dict:
        (found,) = [j for j in json.loads(self.run("list").stdout)["jobs"] if j["id"] == job_id]
        return found

    def assert_refused_one_shot(self, reason_part, marker=None):
        assert "Traceback" not in self.last.stderr
        assert self.last.returncode == 1
        job = self.job()
        assert job["status"] == "refused" and reason_part in job["reason"], job
        assert not self.marker.exists() and not (marker and marker.exists())
        assert self.unloaded
        listed = self.listed("post-1")
        assert listed["status"] == "refused" and reason_part in listed["reason"]

    def assert_refused_recurring(self, reason_part, marker=None):
        assert "Traceback" not in self.last.stderr
        assert self.last.returncode == 1
        last = self.firings()[-1]
        assert last["status"] == "refused" and last["exit_code"] is None and reason_part in last["reason"], last
        assert self.job("tick")["status"] == "refused"
        assert not self.marker.exists() and not (marker and marker.exists())
        assert self.unloaded
        assert self.listed("tick")["last_run"]["status"] == "refused"

    def fire_one_shot(self, change):
        self.schedule(self.command_file())
        self.edit("post-1", change)
        self.last = self.fire("post-1")

    def fire_recurring(self, change):
        self.schedule(self.command_file(), "tick", every=15)
        self.edit("tick", change)
        self.last = self.fire("tick")


@pytest.fixture(autouse=True)
def _no_uv_python(monkeypatch):
    """A job records the interpreter UV_PYTHON names (the commit hook runs with UV_PYTHON=3.11): no test inherits it."""
    monkeypatch.delenv("UV_PYTHON", raising=False)


@pytest.fixture(params=["launchd", "systemd"])
def s(request, tmp_path):
    return Scheduler(request.param, tmp_path)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name: str, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SCHEDULER_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location(f"{name}_approval_digest", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_of(job) -> Path:
    (entry,) = job["files"].values()
    return Path(entry["copy"])


def only_file(job) -> dict:
    return next(iter(job["files"].values()))


# --- 1. the approved record fires -------------------------------------------------------------


def test_an_unchanged_one_shot_record_fires(s):
    s.schedule(s.command_file())
    assert s.fire().returncode == 0
    assert s.job()["status"] == "done" and s.marker.read_text() == "hello"


def test_an_unchanged_recurring_record_fires(s):
    s.schedule(s.command_file(), "tick", every=15)
    assert s.fire("tick").returncode == 0
    assert s.firings()[-1]["status"] == "done" and s.marker.read_text() == "hello"


def test_a_field_outside_the_digest_does_not_refuse(s):
    s.schedule(s.command_file())
    s.edit("post-1", lambda d: d.update(at_local="2031-01-01T00:00:00+00:00", created_at="2031-01-01T00:00:00+00:00"))
    assert s.fire().returncode == 0
    assert s.job()["status"] == "done" and s.marker.read_text() == "hello"


# --- 2. a one-shot record edited after approval -----------------------------------------------


def test_a_changed_argv_is_refused(s):
    other = s.tmp / "other.txt"

    def change(data):
        data["argv"][2] = MARKER_CODE.format(marker=str(other))

    s.fire_one_shot(change)
    s.assert_refused_one_shot(CHANGED, other)


def test_a_changed_cwd_is_refused(s):
    elsewhere = s.tmp / "elsewhere"
    elsewhere.mkdir()
    s.fire_one_shot(lambda d: d.update(cwd=str(elsewhere)))
    s.assert_refused_one_shot(CHANGED)


def test_changed_outputs_are_refused(s):
    s.fire_one_shot(lambda d: d["outputs"].append(str(s.tmp / "extra.txt")))
    s.assert_refused_one_shot(CHANGED)


def test_a_changed_grace_is_refused(s):
    s.fire_one_shot(lambda d: d.update(grace_minutes=10080))
    s.assert_refused_one_shot(CHANGED)


def test_a_timeout_added_or_changed_is_refused(s):
    s.fire_one_shot(lambda d: d.update(timeout_minutes=240))
    s.assert_refused_one_shot(CHANGED)


def test_a_changed_timeout_is_refused(s):
    s.schedule(s.command_file(extra={"timeout_minutes": 5}))
    s.edit("post-1", lambda d: d.update(timeout_minutes=240))
    s.last = s.fire()
    s.assert_refused_one_shot(CHANGED)


def test_a_moved_time_is_refused_not_missed(s):
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat()
    s.fire_one_shot(lambda d: d.update(at=day_ago))
    s.assert_refused_one_shot(CHANGED)
    assert s.job()["status"] != "missed"


def test_a_program_replaced_consistently_with_its_hash_is_refused(s):
    fake = s.tmp / "fake-program"
    fake.write_text(f"#!/bin/sh\necho ran > {s.tmp / 'fake-ran.txt'}\n")
    fake.chmod(0o755)

    def change(data):
        data["argv"][0] = str(fake)
        data["program"] = {"path": str(fake), "sha256": sha(fake)}

    s.fire_one_shot(change)
    s.assert_refused_one_shot(CHANGED, s.tmp / "fake-ran.txt")


def test_a_pin_removed_or_added_is_refused(s):
    interpreter = s.tmp / "real-python"
    interpreter.write_text("#!/bin/sh\nexit 0\n")
    interpreter.chmod(0o755)
    s.env["UV_PYTHON"] = str(interpreter)
    s.schedule(s.command_file())
    assert "python" in s.job()
    s.edit("post-1", lambda d: d.pop("python"))
    s.last = s.fire()
    s.assert_refused_one_shot(CHANGED)


def test_a_pin_added_to_an_unpinned_job_is_refused(s):
    interpreter = s.tmp / "real-python"
    interpreter.write_text("#!/bin/sh\nexit 0\n")
    interpreter.chmod(0o755)
    s.fire_one_shot(lambda d: d.update(python={"path": str(interpreter), "sha256": sha(interpreter)}))
    s.assert_refused_one_shot(CHANGED)


# --- 3. a recurring record edited after approval ----------------------------------------------


def test_a_recurring_record_with_a_changed_argv_is_refused(s):
    other = s.tmp / "other.txt"

    def change(data):
        data["argv"][2] = MARKER_CODE.format(marker=str(other))

    s.fire_recurring(change)
    s.assert_refused_recurring(CHANGED, other)


def test_a_recurring_record_with_a_changed_interval_is_refused(s):
    s.fire_recurring(lambda d: d.update(every_minutes=1))
    s.assert_refused_recurring(CHANGED)


def test_a_recurring_record_with_a_changed_timeout_is_refused(s):
    s.fire_recurring(lambda d: d.update(timeout_minutes=31))
    s.assert_refused_recurring(CHANGED)


# --- 4. the payload ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["one-shot", "recurring"])
def test_a_rewritten_copy_with_its_hash_rewritten_is_refused(s, kind):
    job_id, every = ("post-1", None) if kind == "one-shot" else ("tick", 15)
    s.schedule(s.command_file(), job_id, every=every)
    job = s.job(job_id)
    target = copy_of(job)
    target.chmod(0o600)
    target.write_text("tampered")

    def change(data):
        only_file(data)["sha256"] = sha(target)

    s.edit(job_id, change)
    s.last = s.fire(job_id)
    if kind == "one-shot":
        s.assert_refused_one_shot(CHANGED)
    else:
        s.assert_refused_recurring(CHANGED)
    assert not s.marker.exists()


@pytest.mark.parametrize("kind", ["one-shot", "recurring"])
def test_a_copy_path_pointed_elsewhere_is_refused(s, kind):
    job_id, every = ("post-1", None) if kind == "one-shot" else ("tick", 15)
    s.schedule(s.command_file(), job_id, every=every)
    job = s.job(job_id)
    real = copy_of(job)
    pristine = s.tmp / "pristine-copy.txt"
    pristine.write_text(real.read_text())
    real.chmod(0o600)
    real.write_text("tampered")  # what argv names now holds other content; the pristine duplicate passes the hash check

    def change(data):
        only_file(data)["copy"] = str(pristine)

    s.edit(job_id, change)
    s.last = s.fire(job_id)
    if kind == "one-shot":
        s.assert_refused_one_shot(MOVED)
    else:
        s.assert_refused_recurring(MOVED)
    assert not s.marker.exists()


# --- 5. a record without its digest or its fields --------------------------------------------


@pytest.mark.parametrize("kind", ["one-shot", "recurring"])
def test_a_record_without_approved_is_refused(s, kind):
    job_id, every = ("post-1", None) if kind == "one-shot" else ("tick", 15)
    s.schedule(s.command_file(), job_id, every=every)
    s.edit(job_id, lambda d: d.pop("approved"))
    s.last = s.fire(job_id)
    if kind == "one-shot":
        s.assert_refused_one_shot(UNSIGNED)
    else:
        s.assert_refused_recurring(UNSIGNED)


@pytest.mark.parametrize("value,reason", [("ABC", UNSIGNED), ("UPPER", UNSIGNED), ("0" * 64, CHANGED)])
def test_an_approved_value_that_is_not_the_digest_is_refused(s, value, reason):
    s.schedule(s.command_file())
    approved = s.job()["approved"]
    s.edit("post-1", lambda d: d.update(approved=approved.upper() if value == "UPPER" else value))
    s.last = s.fire()
    s.assert_refused_one_shot(reason)


@pytest.mark.parametrize("kind", ["one-shot", "recurring"])
def test_a_missing_field_is_a_recorded_refusal(s, kind):
    job_id, every = ("post-1", None) if kind == "one-shot" else ("tick", 15)
    s.schedule(s.command_file(), job_id, every=every)
    s.edit(job_id, lambda d: d.pop("cwd"))
    s.last = s.fire(job_id)
    if kind == "one-shot":
        s.assert_refused_one_shot(BROKEN)
    else:
        s.assert_refused_recurring(BROKEN)


def test_files_replaced_by_a_list_is_a_recorded_refusal(s):
    s.fire_one_shot(lambda d: d.update(files=[]))
    s.assert_refused_one_shot(BROKEN)


# --- 6. the check travels with the job --------------------------------------------------------


def test_the_runner_copy_refuses_an_edited_record(s):
    s.schedule(s.command_file())
    other = s.tmp / "other.txt"

    def change(data):
        data["argv"][2] = MARKER_CODE.format(marker=str(other))

    s.edit("post-1", change)
    runner = s.job()["runner"]["copy"]
    fired = subprocess.run([sys.executable, runner, "run", "--id", "post-1"], env=s.env, capture_output=True,
                           text=True, timeout=120)
    assert fired.returncode == 1 and "Traceback" not in fired.stderr
    job = s.job()
    assert job["status"] == "refused" and CHANGED in job["reason"]
    assert not s.marker.exists() and not other.exists()


# --- 7. parity --------------------------------------------------------------------------------


def one_shot_record(tmp_path: Path, job_id="post-1") -> dict:
    return {
        "id": job_id, "at": "2030-01-01T09:00:00+00:00", "at_local": "2030-01-01T09:00:00+00:00",
        "grace_minutes": 10, "argv": ["/usr/bin/python3", str(tmp_path / job_id / "files" / "run.py")],
        "cwd": "/work", "outputs": ["/work/out.txt"],
        "program": {"path": "/usr/bin/python3", "sha256": "a" * 64},
        "files": {"/work/run.py": {"copy": str(tmp_path / job_id / "files" / "run.py"), "sha256": "b" * 64,
                                   "bytes": 3}},
        "runner": {"source": "/x", "copy": "/y", "sha256": "c" * 64},
    }


def recurring_record(tmp_path: Path) -> dict:
    base = {k: v for k, v in one_shot_record(tmp_path, "tick").items() if k not in ("at", "at_local", "grace_minutes")}
    return {**base, "kind": "recurring", "every_minutes": 15, "timeout_minutes": 30}


def _mutations(record: dict):
    def mutate(name, change):
        return name, change

    def drop(key):
        return lambda d: d.pop(key)

    def file_entry(d):
        return next(iter(d["files"].values()))

    common = [
        mutate("argv", lambda d: d["argv"].append("--x")),
        mutate("cwd", lambda d: d.update(cwd="/other")),
        mutate("outputs", lambda d: d["outputs"].append("/work/extra.txt")),
        mutate("python added", lambda d: d.update(python={"path": "/opt/py", "sha256": "d" * 64})),
        mutate("program.sha256", lambda d: d["program"].update(sha256="e" * 64)),
        mutate("files sha256", lambda d: file_entry(d).update(sha256="f" * 64)),
        mutate("runner.sha256", lambda d: d["runner"].update(sha256="0" * 64)),
        mutate("copy moved", lambda d: file_entry(d).update(copy="/elsewhere/run.py")),
        mutate("approved deleted", drop("approved")),
        mutate("approved bad", lambda d: d.update(approved="x")),
        mutate("cwd deleted", drop("cwd")),
        mutate("files as a list", lambda d: d.update(files=[])),
    ]
    if record.get("kind") == "recurring":
        return common + [
            mutate("every_minutes", lambda d: d.update(every_minutes=5)),
            mutate("timeout_minutes", lambda d: d.update(timeout_minutes=31)),
            mutate("kind deleted", drop("kind")),
        ]
    return common + [
        mutate("at", lambda d: d.update(at="2030-01-02T09:00:00+00:00")),
        mutate("grace_minutes", lambda d: d.update(grace_minutes=11)),
        mutate("timeout_minutes added", lambda d: d.update(timeout_minutes=5)),
    ]


@pytest.mark.parametrize("builder", [one_shot_record, recurring_record])
def test_both_providers_name_the_same_mismatch_for_the_same_record(builder, monkeypatch, tmp_path):
    launchd, systemd = load("launchd", monkeypatch, tmp_path), load("systemd", monkeypatch, tmp_path)
    record = builder(tmp_path)
    record["approved"] = launchd.approval_digest(record)
    assert launchd.record_changed_since_approval(copylib.deepcopy(record)) is None
    assert systemd.record_changed_since_approval(copylib.deepcopy(record)) is None
    for name, change in _mutations(record):
        mutated = copylib.deepcopy(record)
        change(mutated)
        first = launchd.record_changed_since_approval(copylib.deepcopy(mutated))
        second = systemd.record_changed_since_approval(copylib.deepcopy(mutated))
        assert first is not None, name
        assert first == second, name


# --- 7. the job id the unit names is the anchor -----------------------------------------------


def new_calls(s, before) -> str:
    return (s.calls.read_text() if s.calls.exists() else "")[len(before):]


def test_an_edited_id_does_not_rerun_another_job(s):
    command = s.command_file()
    s.schedule(command, "post-a")
    s.schedule(command, "post-b")
    assert s.fire("post-b").returncode == 0 and s.marker.read_text() == "hello"
    s.marker.unlink()
    s.edit("post-b", lambda d: d.update(status="scheduled"))  # B is armed again by hand
    s.edit("post-a", lambda d: d.update(id="post-b"))  # and A's record claims to be B
    b_before = s.job_path("post-b").read_bytes()
    before = s.calls.read_text() if s.calls.exists() else ""
    fired = s.fire("post-a")
    assert "Traceback" not in fired.stderr and fired.returncode == 1
    assert not s.marker.exists()  # B's command did not run a second time
    refused = s.job("post-a")
    assert refused["status"] == "refused" and CHANGED in refused["reason"], refused
    assert s.job_path("post-b").read_bytes() == b_before  # B's record is untouched
    assert "post-b" not in new_calls(s, before)  # and so is its unit or plist
    assert not (s.job_path("post-b").parent / "run.lock").exists() or s.job("post-b")["status"] == "scheduled"


@pytest.mark.parametrize("kind", ["one-shot", "recurring"])
def test_another_jobs_record_copied_into_a_folder_is_refused(s, kind):
    every = None if kind == "one-shot" else 15
    command = s.command_file()
    s.schedule(command, "post-a", every=every)
    s.schedule(command, "post-b", every=30 if every else None)
    b_before = s.job_path("post-b").read_bytes()
    s.job_path("post-a").write_bytes(b_before)
    os.chmod(s.job_path("post-a"), 0o600)
    before = s.calls.read_text() if s.calls.exists() else ""
    fired = s.fire("post-a")
    assert "Traceback" not in fired.stderr and fired.returncode == 1
    assert not s.marker.exists()
    assert s.job_path("post-b").read_bytes() == b_before
    assert "post-b" not in new_calls(s, before)
    if kind == "one-shot":
        assert s.job("post-a")["status"] == "refused" and CHANGED in s.job("post-a")["reason"]
    else:
        last = s.firings("post-a")[-1]
        assert last["status"] == "refused" and CHANGED in last["reason"], last
        assert s.job("post-a")["status"] == "refused"


@pytest.mark.parametrize("kind", ["one-shot", "recurring"])
def test_a_record_without_program_and_runner_hashes_is_a_recorded_refusal(s, kind):
    job_id, every = ("post-1", None) if kind == "one-shot" else ("tick", 15)
    s.schedule(s.command_file(), job_id, every=every)
    s.edit(job_id, lambda d: (d.pop("program"), d.pop("runner")))
    s.last = s.fire(job_id)
    if kind == "one-shot":
        s.assert_refused_one_shot(BROKEN)
    else:
        s.assert_refused_recurring(BROKEN)
