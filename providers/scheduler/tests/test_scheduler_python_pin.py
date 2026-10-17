"""A scheduled job keeps the interpreter it was approved with (F2-C): offline tests of both scheduler providers.

Run: uv run --with pytest pytest providers/scheduler/tests/test_scheduler_python_pin.py

A command a job runs starts its providers with `uv run`, and uv chooses the interpreter at each start. The
scheduler therefore records the interpreter that UV_PYTHON names when the job is scheduled, puts it into the
approved digest, checks it at every firing and hands it to the command as UV_PYTHON. The interpreters here are
fake executables in a temporary folder; no real interpreter, launchd or systemd is reached.
"""
from __future__ import annotations

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
PIN_WARNING = ("the interpreter of uv run inside this job is chosen by uv at each firing; "
               "set UV_PYTHON to an absolute interpreter path to pin it")

# A job record as the code before this change wrote it, and the digest that code gave it (computed on the base).
LEGACY_ONE_SHOT = {
    "id": "post-1", "at": "2030-01-01T09:00:00+00:00", "grace_minutes": 10,
    "argv": ["/usr/bin/python3", "/jobs/post-1/files/run.py"], "cwd": "/work", "outputs": ["/work/out.txt"],
    "program": {"path": "/usr/bin/python3", "sha256": "a" * 64},
    "files": {"/work/run.py": {"copy": "/jobs/post-1/files/run.py", "sha256": "b" * 64, "bytes": 3}},
    "runner": {"source": "/x", "copy": "/y", "sha256": "c" * 64},
}
LEGACY_RECURRING = {**{k: v for k, v in LEGACY_ONE_SHOT.items() if k not in ("at", "grace_minutes")},
                    "id": "tick", "kind": "recurring", "every_minutes": 15, "timeout_minutes": 30}
LEGACY_DIGESTS = {
    "one-shot": "00c3c13de6c9aa168a5ab098078ec9d03691e7461183c08f2b676e60ec23656e",
    "recurring": "43223010e49d0e71239f533a0e7087da4561e20116d26b6eb3a64b3581bb48cb",
}


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
        self.at = (datetime.now(timezone.utc) + timedelta(minutes=1)).replace(microsecond=0).isoformat()  # fixed: digests compare
        self.unload_word = "bootout" if name == "launchd" else "disable"

    def run(self, *args):
        return subprocess.run([sys.executable, str(self.script), *args], env=self.env, capture_output=True,
                              text=True, timeout=120)

    def interpreter(self, content: str = "#!/bin/sh\nexit 0\n") -> Path:
        """A fake interpreter behind a symlink; returns the symlink (what a person puts in UV_PYTHON)."""
        real = self.tmp / "real" / "python3.12"
        real.parent.mkdir(exist_ok=True)
        real.write_text(content)
        real.chmod(0o755)
        link = self.tmp / "bin" / "python3"
        link.parent.mkdir(exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(real)
        return link

    def command_file(self, code: str) -> Path:
        spec = {"argv": [sys.executable, "-c", code], "cwd": str(self.tmp), "snapshot": []}
        path = self.tmp / "job.json"
        path.write_text(json.dumps(spec))
        return path

    def plan(self, path: Path, job_id="post-1", every=None) -> subprocess.CompletedProcess:
        when = ["--every", str(every)] if every else ["--at", self.at]
        return self.run("schedule", "--id", job_id, *when, "--command-file", str(path), "--dry-run")

    def schedule(self, path: Path, job_id="post-1", every=None):
        dry = self.plan(path, job_id, every)
        assert dry.returncode == 0, dry.stderr
        when = ["--every", str(every)] if every else ["--at", self.at]
        done = self.run("schedule", "--id", job_id, *when, "--command-file", str(path), "--confirmed",
                        "--approved", json.loads(dry.stdout)["approved"])
        return done, json.loads(dry.stdout)

    def job(self, job_id="post-1") -> dict:
        return json.loads((Path(self.env["SCHEDULER_HOME"]) / job_id / "job.json").read_text())

    def firings(self, job_id="tick") -> list:
        path = Path(self.env["SCHEDULER_HOME"]) / job_id / "runs.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture(autouse=True)
def _no_uv_python(monkeypatch):
    """A job records the interpreter UV_PYTHON names (the commit hook runs with UV_PYTHON=3.11): no test inherits it.
    Here and not in conftest.py: the provider suites carry the same conftest.py (providers/store/tests/test_loopback_only.py)."""
    monkeypatch.delenv("UV_PYTHON", raising=False)


@pytest.fixture(params=["launchd", "systemd"])
def s(request, tmp_path):
    return Scheduler(request.param, tmp_path)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_python_pin", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRINT_ENV = "import os; open(%r, 'w').write(os.environ.get('UV_PYTHON', 'unset'))"


# --- 1. the pin is recorded at creation, from the real binary --------------------------------------


def test_uv_python_behind_a_symlink_records_the_real_binary_and_changes_the_digest(s):
    link = s.interpreter()
    path = s.command_file("print(1)")
    unpinned = json.loads(s.plan(path).stdout)
    s.env["UV_PYTHON"] = str(link)
    dry = s.plan(path)
    assert dry.returncode == 0, dry.stderr
    out = json.loads(dry.stdout)
    real = Path(os.path.realpath(link))
    assert out["job"]["python"] == {"path": str(real), "sha256": sha(real)}
    assert real != link and "warnings" not in out
    assert out["approved"] != unpinned["approved"]
    assert out["approved"] == json.loads(s.plan(path).stdout)["approved"]  # and it is stable


def test_a_job_planned_without_the_pin_keeps_the_digest_it_had(s):
    module = load(s.name)
    assert module.approval_digest(dict(LEGACY_ONE_SHOT)) == LEGACY_DIGESTS["one-shot"]
    assert module.approval_digest(dict(LEGACY_RECURRING)) == LEGACY_DIGESTS["recurring"]
    pinned = {**LEGACY_ONE_SHOT, "python": {"path": "/opt/py/python3.12", "sha256": "d" * 64}}
    assert module.approval_digest(pinned) != LEGACY_DIGESTS["one-shot"]


# --- 2. no pin: a warning, never a refusal ----------------------------------------------------


@pytest.mark.parametrize("value", [None, "3.11", "", "relative/python3", "/nonexistent/python3"])
def test_without_an_absolute_interpreter_nothing_is_recorded_and_the_dry_run_warns(s, value):
    if value is not None:
        s.env["UV_PYTHON"] = value
    out = json.loads(s.plan(s.command_file("print(1)")).stdout)
    assert "python" not in out["job"]
    assert out["warnings"] == [PIN_WARNING]


def test_a_file_that_is_not_executable_is_not_a_pin(s):
    link = s.interpreter()
    Path(os.path.realpath(link)).chmod(0o644)
    s.env["UV_PYTHON"] = str(link)
    dry = s.plan(s.command_file("print(1)"))
    assert dry.returncode == 0 and "python" not in json.loads(dry.stdout)["job"]


# --- 3. approved and re-verified at confirmation ----------------------------------------------


def test_the_confirmed_schedule_keeps_the_pin_in_the_job_record(s):
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    done, planned = s.schedule(s.command_file("print(1)"))
    assert done.returncode == 0, done.stderr
    assert s.job()["python"] == planned["job"]["python"]
    assert json.loads(done.stdout)["python"] == planned["job"]["python"]


def test_an_interpreter_changed_between_the_dry_run_and_the_confirmation_is_refused(s):
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    path = s.command_file("print(1)")
    dry = json.loads(s.plan(path).stdout)
    s.interpreter("#!/bin/sh\nexit 1\n")  # the real binary's bytes change
    done = s.run("schedule", "--id", "post-1", "--at", s.at, "--command-file", str(path), "--confirmed",
                 "--approved", dry["approved"])
    assert done.returncode != 0 and "changed since the dry run" in done.stderr
    assert not (Path(s.env["SCHEDULER_HOME"]) / "post-1" / "job.json").exists()


# --- 4. at a firing ------------------------------------------------------------------------


def test_an_unchanged_interpreter_is_handed_to_the_command_as_uv_python(s):
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    seen = s.tmp / "seen.txt"
    assert s.schedule(s.command_file(PRINT_ENV % str(seen)))[0].returncode == 0
    s.env["UV_PYTHON"] = "3.9"  # whatever the service manager hands the runner, the job's own pin is what the command gets
    assert s.run("run", "--id", "post-1").returncode == 0
    assert s.job()["status"] == "done"
    assert seen.read_text() == os.path.realpath(link)


def test_a_changed_interpreter_refuses_a_one_shot_job_and_names_it(s):
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    ran = s.tmp / "ran.txt"
    assert s.schedule(s.command_file(f"open({str(ran)!r}, 'w').write('x')"))[0].returncode == 0
    s.interpreter("#!/bin/sh\nexit 1\n")
    s.run("run", "--id", "post-1")
    job = s.job()
    assert job["status"] == "refused"
    assert f"the interpreter {os.path.realpath(link)} changed after scheduling" in job["reason"]
    assert not ran.exists()


def test_a_changed_interpreter_refuses_and_unloads_a_recurring_job(s):
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    ran = s.tmp / "ran.txt"
    assert s.schedule(s.command_file(f"open({str(ran)!r}, 'w').write('x')"), "tick", every=15)[0].returncode == 0
    s.interpreter("#!/bin/sh\nexit 1\n")
    before = s.calls.read_text()
    assert s.run("run", "--id", "tick").returncode != 0
    last = s.firings()[-1]
    assert last["status"] == "refused" and "the interpreter" in last["reason"]
    assert s.job("tick")["status"] == "refused"
    assert s.unload_word in s.calls.read_text()[len(before):]
    assert not ran.exists()


def test_a_missing_interpreter_is_a_change_too(s):
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    assert s.schedule(s.command_file("print(1)"))[0].returncode == 0
    Path(os.path.realpath(link)).unlink()
    s.run("run", "--id", "post-1")
    assert s.job()["status"] == "refused" and "changed after scheduling" in s.job()["reason"]


# --- 5. a job without the pin behaves as before ----------------------------------------------


def test_a_job_without_the_pin_runs_lists_and_cancels_as_before(s):
    s.env["UV_PYTHON"] = "3.11"
    seen = s.tmp / "seen.txt"
    done, planned = s.schedule(s.command_file(PRINT_ENV % str(seen)))
    assert done.returncode == 0, done.stderr
    assert "python" not in s.job() and "python" not in planned["job"]
    assert s.run("run", "--id", "post-1").returncode == 0
    assert s.job()["status"] == "done"
    assert seen.read_text() == "3.11"  # the runner added nothing of its own: what it was given passes through
    listed = json.loads(s.run("list").stdout)["jobs"]
    assert [job["id"] for job in listed] == ["post-1"] and "python" not in listed[0]
    assert s.schedule(s.command_file("print(1)"), "post-2")[0].returncode == 0
    assert s.run("cancel", "--id", "post-2", "--confirmed").returncode == 0
    assert s.job("post-2")["status"] == "cancelled"


def test_the_runner_adds_no_uv_python_when_the_job_has_no_pin(s):
    # The job was approved without a pin: what the service manager gives the runner passes through, nothing is added.
    seen = s.tmp / "seen.txt"
    assert s.schedule(s.command_file(PRINT_ENV % str(seen)))[0].returncode == 0
    assert s.run("run", "--id", "post-1").returncode == 0
    assert seen.read_text() == "unset"


def test_list_shows_the_pin(s):
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    assert s.schedule(s.command_file("print(1)"))[0].returncode == 0
    (job,) = json.loads(s.run("list").stdout)["jobs"]
    assert job["python"]["path"] == os.path.realpath(link)


# --- 6. parity ------------------------------------------------------------------------------


def test_both_providers_compute_the_same_digest_for_a_pinned_job():
    pinned_one = {**LEGACY_ONE_SHOT, "python": {"path": "/opt/py/python3.12", "sha256": "d" * 64}}
    pinned_every = {**LEGACY_RECURRING, "python": {"path": "/opt/py/python3.12", "sha256": "d" * 64}}
    launchd, systemd = load("launchd"), load("systemd")
    for job in (pinned_one, pinned_every):
        assert launchd.approval_digest(job) == systemd.approval_digest(job)
    assert launchd.approval_digest(pinned_one) != launchd.approval_digest(LEGACY_ONE_SHOT)
    assert launchd.approval_digest(pinned_every) != launchd.approval_digest(LEGACY_RECURRING)


def test_a_job_scheduled_from_inside_a_pinned_job_records_the_same_pin(s):
    # The vote step of the tick calls schedule with the environment it inherited: the pin it was given.
    link = s.interpreter()
    s.env["UV_PYTHON"] = str(link)
    first = json.loads(s.plan(s.command_file("print(1)")).stdout)["job"]["python"]
    s.env["UV_PYTHON"] = first["path"]  # what the pinned job's command has in its environment
    assert json.loads(s.plan(s.command_file("print(1)"), "post-2").stdout)["job"]["python"] == first
