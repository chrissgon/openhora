"""Offline tests for providers/scheduler/launchd.py.

Run: uv run --with pytest pytest providers/scheduler/tests

Nothing is loaded into launchd: SCHEDULER_LAUNCHCTL (honoured only with SCHEDULER_TEST=1)
points at a fake launchctl that records its arguments, and the job and agent folders live
in a temporary directory.
"""
from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "launchd.py"


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def _no_uv_python(monkeypatch):
    """A job records the interpreter UV_PYTHON names (the commit hook runs with UV_PYTHON=3.11): no test inherits it.
    Here and not in conftest.py: the provider suites carry the same conftest.py (providers/store/tests/test_loopback_only.py)."""
    monkeypatch.delenv("UV_PYTHON", raising=False)


@pytest.fixture
def env(tmp_path):
    calls = tmp_path / "launchctl-calls.txt"
    fake = tmp_path / "launchctl"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nexit "${{FAKE_LAUNCHCTL_EXIT:-0}}"\n')
    fake.chmod(0o755)
    values = {
        **os.environ,
        "SCHEDULER_HOME": str(tmp_path / "jobs"),
        "SCHEDULER_AGENTS_DIR": str(tmp_path / "agents"),
        "SCHEDULER_LAUNCHCTL": str(fake),
        "SCHEDULER_NOTIFY": "0",
        "SCHEDULER_TEST": "1",
    }
    values["_calls"] = str(calls)
    return values


def run(env, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)


def command_file(tmp_path, argv_extra=(), grace=120, content="hello"):
    post = tmp_path / "post.txt"
    post.write_text(content)
    marker = tmp_path / "ran.txt"
    spec = {
        "argv": [sys.executable, "-c",
                 "import sys, json; open(sys.argv[2], 'w').write(open(sys.argv[1]).read()); "
                 "print(json.dumps({'post_url': 'https://example.test/post'}))",
                 str(post), str(marker), *argv_extra],
        "cwd": str(tmp_path),
        "snapshot": [str(post)],
        "outputs": [str(marker)],
        "grace_minutes": grace,
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(spec))
    return path, post, marker


def dry_run(env, path, at, job_id="post-1"):
    return run(env, "schedule", "--id", job_id, "--at", iso(at), "--command-file", str(path), "--dry-run")


def confirm(env, path, at, job_id="post-1"):
    """Schedule as a calling skill does: dry run, then --confirmed with the digest it printed."""
    preview = dry_run(env, path, at, job_id)
    assert preview.returncode == 0, preview.stderr
    digest = json.loads(preview.stdout)["approved"]
    return run(env, "schedule", "--id", job_id, "--at", iso(at), "--command-file", str(path),
               "--confirmed", "--approved", digest)


def schedule(env, tmp_path, at, job_id="post-1", **kw):
    path, post, marker = command_file(tmp_path, **kw)
    return confirm(env, path, at, job_id), post, marker


def job(env, job_id="post-1"):
    return json.loads((Path(env["SCHEDULER_HOME"]) / job_id / "job.json").read_text())


def test_schedule_refuses_without_confirmed(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc) + timedelta(days=1)
    result = run(env, "schedule", "--id", "post-1", "--at", iso(at), "--command-file", str(path))
    assert result.returncode == 2
    assert "--confirmed" in result.stderr
    assert not Path(env["SCHEDULER_HOME"]).exists()


def test_dry_run_prints_plist_and_writes_nothing(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc) + timedelta(days=2)
    result = run(env, "schedule", "--id", "post-1", "--at", iso(at), "--command-file", str(path), "--dry-run")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    local = at.astimezone()
    assert out["plist"]["StartCalendarInterval"] == {
        "Month": local.month, "Day": local.day, "Hour": local.hour, "Minute": local.minute}
    assert out["plist"]["ProgramArguments"][-3:] == ["run", "--id", "post-1"]
    assert not Path(env["SCHEDULER_HOME"]).exists()
    assert not Path(env["_calls"]).exists()


def test_past_time_refused(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    result = dry_run(env, path, datetime.now(timezone.utc) - timedelta(minutes=1))
    assert result.returncode == 2
    assert "past" in result.stderr


def test_schedule_snapshots_files_and_loads_agent(env, tmp_path):
    result, post, _ = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(days=1))
    assert result.returncode == 0, result.stderr
    data = job(env)
    copy = Path(data["files"][str(post)]["copy"])
    assert copy.read_text() == "hello"
    assert str(copy) in data["argv"] and str(post) not in data["argv"]
    plist = plistlib.loads((Path(env["SCHEDULER_AGENTS_DIR"]) / "dev.ai-workbench.scheduler.post-1.plist").read_bytes())
    assert plist["Label"] == "dev.ai-workbench.scheduler.post-1"
    calls = Path(env["_calls"]).read_text()
    assert f"bootstrap gui/{os.getuid()}" in calls


def test_editing_the_original_after_scheduling_does_not_change_the_run(env, tmp_path):
    _, post, marker = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1))
    post.write_text("edited later")
    result = run(env, "run", "--id", "post-1")
    assert result.returncode == 0, result.stderr
    assert marker.read_text() == "hello"
    data = job(env)
    assert data["status"] == "done"
    assert data["post_url"] == "https://example.test/post"
    assert not (Path(env["SCHEDULER_AGENTS_DIR"]) / "dev.ai-workbench.scheduler.post-1.plist").exists()


def test_run_refuses_a_changed_copy(env, tmp_path):
    _, post, marker = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1))
    copy = Path(job(env)["files"][str(post)]["copy"])
    copy.chmod(0o600)
    copy.write_text("tampered")
    result = run(env, "run", "--id", "post-1")
    assert result.returncode == 1
    assert job(env)["status"] == "refused"
    assert not marker.exists()


def test_run_twice_runs_once(env, tmp_path):
    _, _, marker = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1))
    assert run(env, "run", "--id", "post-1").returncode == 0
    marker.unlink()
    assert run(env, "run", "--id", "post-1").returncode == 0
    assert not marker.exists()


def test_a_firing_more_than_a_day_early_is_left_for_its_time(env, tmp_path):
    _, _, marker = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(hours=27))
    assert run(env, "run", "--id", "post-1").returncode == 0
    assert job(env)["status"] == "scheduled"
    assert not marker.exists()


def load_module(monkeypatch, env, name="launchd_provider_clock"):
    for key in ("SCHEDULER_HOME", "SCHEDULER_AGENTS_DIR", "SCHEDULER_LAUNCHCTL", "SCHEDULER_NOTIFY", "SCHEDULER_TEST"):
        monkeypatch.setenv(key, env[key])
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_early_firing_within_a_day_waits_for_its_time_then_runs(env, tmp_path, monkeypatch):
    # SC6: the plist holds local wall time, so a change of the system time zone between scheduling and the slot
    # fires the job early. The runner logged "waiting" and returned, and launchd would fire it next a year later:
    # the job showed "scheduled" until it was missed. Within 26 hours (the widest gap between two time zones) the
    # runner now waits for the time, checking the wall clock in short steps, and runs the command.
    _, _, marker = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1))
    module = load_module(monkeypatch, env)
    at = datetime.fromisoformat(job(env)["at"].replace("Z", "+00:00"))
    clock, slept = [at - timedelta(hours=3)], []

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(module, "now", lambda: clock[0])
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=sleep, monotonic=time.monotonic))
    assert module.main(["run", "--id", "post-1"]) == 0
    data = job(env)
    assert data["status"] == "done" and marker.exists()
    assert data["started_at"] >= job(env)["at"]  # it ran at its time, not when it fired
    assert slept and max(slept) <= module.WAIT_STEP_SECONDS
    assert abs(sum(slept) - 3 * 3600) < 1
    assert module.EARLY_WAIT_LIMIT == timedelta(hours=26)


def test_late_fire_after_grace_is_missed(env, tmp_path):
    _, _, marker = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1), grace=0)
    data = job(env)
    data["at"] = iso(datetime.now(timezone.utc) - timedelta(minutes=10))
    (Path(env["SCHEDULER_HOME"]) / "post-1" / "job.json").write_text(json.dumps(data))
    assert run(env, "run", "--id", "post-1").returncode == 1
    assert job(env)["status"] == "missed"
    assert not marker.exists()


def test_failed_command_is_recorded(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    spec = json.loads(path.read_text())
    spec["argv"] = [sys.executable, "-c", "import sys; sys.exit(4)"]
    path.write_text(json.dumps(spec))
    at = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert confirm(env, path, at).returncode == 0
    assert run(env, "run", "--id", "post-1").returncode == 1
    data = job(env)
    assert data["status"] == "failed" and data["exit_code"] == 4


def test_cancel_and_list(env, tmp_path):
    schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(days=1))
    assert run(env, "cancel", "--id", "post-1").returncode == 2
    assert run(env, "cancel", "--id", "post-1", "--confirmed").returncode == 0
    listed = json.loads(run(env, "list").stdout)["jobs"]
    assert [(j["id"], j["status"], j["plist_present"]) for j in listed] == [("post-1", "cancelled", False)]


def test_bootstrap_failure_is_reported(env, tmp_path):
    env["FAKE_LAUNCHCTL_EXIT"] = "5"
    result, _, _ = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(days=1))
    assert result.returncode == 1
    assert job(env)["status"] == "failed"


# --- audit 2026-09-27, group G3 ----------------------------------------------------


def spec_file(tmp_path, argv, snapshot, name="cmd.json", outputs=()):
    path = tmp_path / name
    path.write_text(json.dumps({"argv": argv, "cwd": str(tmp_path), "snapshot": snapshot, "outputs": list(outputs)}))
    return path


COPY_VALUE = ("import sys, json; v = sys.argv[1].split('=', 1)[-1]; "
              "open(sys.argv[2], 'w').write(open(v).read()); print(json.dumps({}))")


def test_file_argument_missing_from_snapshot_is_refused(env, tmp_path):
    # H07: a post file passed as --text-file=/x and left out of the snapshot ran unverified.
    post = tmp_path / "post.txt"
    post.write_text("hello")
    at = datetime.now(timezone.utc) + timedelta(days=1)
    for arg in (f"--text-file={post}", str(post), "post.txt"):
        path = spec_file(tmp_path, [sys.executable, "-c", COPY_VALUE, arg, str(tmp_path / "out")], [])
        result = dry_run(env, path, at)
        assert result.returncode == 2, arg
        assert "not in the command file's snapshot" in result.stderr
    assert not Path(env["SCHEDULER_HOME"]).exists()


def test_snapshot_is_required(env, tmp_path):
    path = tmp_path / "cmd.json"
    path.write_text(json.dumps({"argv": ["/bin/true"], "cwd": str(tmp_path)}))
    result = dry_run(env, path, datetime.now(timezone.utc) + timedelta(days=1))
    assert result.returncode == 2
    assert "snapshot" in result.stderr


def test_flag_equals_and_relative_forms_run_on_the_copy(env, tmp_path):
    post = tmp_path / "post.txt"
    marker = tmp_path / "ran.txt"
    for form in (f"--text-file={post}", "--text-file=post.txt", "post.txt"):
        post.write_text("approved")
        path = spec_file(tmp_path, [sys.executable, "-c", COPY_VALUE, form, str(marker)], [str(post)],
                         outputs=[str(marker)])
        result = confirm(env, path, datetime.now(timezone.utc) + timedelta(minutes=1))
        assert result.returncode == 0, result.stderr
        copy = job(env)["files"][str(post)]["copy"]
        assert job(env)["argv"][3] in (f"--text-file={copy}", copy), form
        post.write_text("edited later")
        assert run(env, "run", "--id", "post-1").returncode == 0
        assert marker.read_text() == "approved", form


def test_confirm_needs_the_dry_run_digest(env, tmp_path):
    path, post, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc) + timedelta(days=1)
    base = ["schedule", "--id", "post-1", "--at", iso(at), "--command-file", str(path), "--confirmed"]
    missing = run(env, *base)
    assert missing.returncode == 2 and "--approved" in missing.stderr
    digest = json.loads(dry_run(env, path, at).stdout)["approved"]
    post.write_text("changed after the dry run")
    changed = run(env, *base, "--approved", digest)
    assert changed.returncode == 2 and "changed since the dry run" in changed.stderr
    assert not (Path(env["SCHEDULER_HOME"]) / "post-1").exists()
    assert not Path(env["_calls"]).exists()


def test_program_changed_after_scheduling_is_refused(env, tmp_path):
    # M05: the scheduled program was not hashed.
    program = tmp_path / "prog.sh"
    marker = tmp_path / "ran.txt"
    program.write_text(f"#!/bin/sh\necho ran > {marker}\n")
    program.chmod(0o755)
    path = spec_file(tmp_path, [str(program)], [])
    assert confirm(env, path, datetime.now(timezone.utc) + timedelta(minutes=1)).returncode == 0
    program.write_text(f"#!/bin/sh\necho other > {marker}\n")
    assert run(env, "run", "--id", "post-1").returncode == 1
    data = job(env)
    assert data["status"] == "refused" and "program" in data["reason"]
    assert not marker.exists()


def test_launchd_calls_the_runner_copy_and_a_changed_runner_is_refused(env, tmp_path):
    # M05: the runner script was not hashed; launchd called it in the repository.
    _, _, marker = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1))
    data = job(env)
    plist = plistlib.loads((Path(env["SCHEDULER_AGENTS_DIR"]) / "dev.ai-workbench.scheduler.post-1.plist").read_bytes())
    runner_copy = Path(plist["ProgramArguments"][1])
    assert runner_copy == Path(data["runner"]["copy"])
    assert runner_copy.parent.parent == Path(env["SCHEDULER_HOME"]) / "post-1"
    assert runner_copy.read_bytes() == SCRIPT.read_bytes()
    changed = tmp_path / "launchd.py"
    changed.write_text(SCRIPT.read_text() + "\n# changed on another branch\n")
    result = subprocess.run([sys.executable, str(changed), "run", "--id", "post-1"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert job(env)["status"] == "refused" and "runner" in job(env)["reason"]
    assert not marker.exists()


def test_files_and_folders_are_private(env, tmp_path):
    # L01: job.json, logs and folders were 0644/0755.
    schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1))
    assert run(env, "run", "--id", "post-1").returncode == 0
    jobs = Path(env["SCHEDULER_HOME"])
    folder = jobs / "post-1"

    def mode(p):
        return stat.S_IMODE(p.stat().st_mode)

    for d in (jobs, folder, folder / "files", folder / "runner"):
        assert mode(d) == 0o700, d
    for f in ("job.json", "run.stdout.log", "run.stderr.log", "launchd.out.log", "launchd.err.log"):
        assert mode(folder / f) == 0o600, f
    assert mode(next((folder / "files").iterdir())) == 0o400
    assert not any(p.stat().st_mode & 0o077 for p in folder.rglob("*"))
    plist = Path(env["SCHEDULER_AGENTS_DIR"]) / "dev.ai-workbench.scheduler.post-1.plist"
    assert not plist.exists()  # removed after the run; its mode is checked below


def test_plist_is_private(env, tmp_path):
    schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(days=1))
    plist = Path(env["SCHEDULER_AGENTS_DIR"]) / "dev.ai-workbench.scheduler.post-1.plist"
    assert stat.S_IMODE(plist.stat().st_mode) == 0o600


def test_reschedule_a_finished_id(env, tmp_path):
    # L02: the old read-only copy made a second schedule of the same id fail.
    _, post, _ = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1))
    assert run(env, "run", "--id", "post-1").returncode == 0
    old_copy = Path(job(env)["files"][str(post)]["copy"])
    assert stat.S_IMODE(old_copy.stat().st_mode) == 0o400
    result, _, _ = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(minutes=1), content="second post")
    assert result.returncode == 0, result.stderr
    data = job(env)
    assert data["status"] == "scheduled"
    assert Path(data["files"][str(post)]["copy"]).read_text() == "second post"
    history = list((Path(env["SCHEDULER_HOME"]) / ".history").iterdir())
    assert len(history) == 1 and json.loads((history[0] / "job.json").read_text())["status"] == "done"
    assert [j["id"] for j in json.loads(run(env, "list").stdout)["jobs"]] == ["post-1"]


def test_scheduled_id_is_not_replaced(env, tmp_path):
    _, post, _ = schedule(env, tmp_path, datetime.now(timezone.utc) + timedelta(days=1))
    path, _, _ = command_file(tmp_path)
    result = dry_run(env, path, datetime.now(timezone.utc) + timedelta(days=1))
    assert result.returncode == 2 and "cancel it" in result.stderr
    assert Path(job(env)["files"][str(post)]["copy"]).read_text() == "hello"


def test_an_existing_output_is_not_mistaken_for_an_input(env, tmp_path):
    path, _, marker = command_file(tmp_path)
    marker.write_text("from an earlier run")
    spec = json.loads(path.read_text())
    assert json.loads(dry_run(env, path, datetime.now(timezone.utc) + timedelta(days=1)).stdout)["job"]["argv"][4] == str(marker)
    spec["outputs"] = []
    path.write_text(json.dumps(spec))
    refused = dry_run(env, path, datetime.now(timezone.utc) + timedelta(days=1))
    assert refused.returncode == 2 and "ran.txt" in refused.stderr


def test_launchctl_override_needs_the_test_flag(env, tmp_path):
    # L03: SCHEDULER_LAUNCHCTL was honoured in any environment.
    path, _, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc) + timedelta(days=1)
    digest = json.loads(dry_run(env, path, at).stdout)["approved"]
    del env["SCHEDULER_TEST"]
    result = run(env, "schedule", "--id", "post-1", "--at", iso(at), "--command-file", str(path),
                 "--confirmed", "--approved", digest)
    assert result.returncode == 2 and "SCHEDULER_TEST" in result.stderr
    assert not Path(env["_calls"]).exists()
    assert not (Path(env["SCHEDULER_HOME"]) / "post-1").exists()


def test_launchctl_timeout_marks_the_job_failed(env, tmp_path, monkeypatch, capsys):
    # L03: launchctl had no timeout.
    slow = tmp_path / "slow-launchctl"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    for key in ("SCHEDULER_HOME", "SCHEDULER_AGENTS_DIR", "SCHEDULER_NOTIFY", "SCHEDULER_TEST"):
        monkeypatch.setenv(key, env[key])
    monkeypatch.setenv("SCHEDULER_LAUNCHCTL", str(slow))
    spec = importlib.util.spec_from_file_location("launchd_provider", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.LAUNCHCTL_TIMEOUT_SECONDS = 0.3
    path, _, _ = command_file(tmp_path)
    at = iso(datetime.now(timezone.utc) + timedelta(days=1))
    base = ["schedule", "--id", "post-1", "--at", at, "--command-file", str(path)]
    assert module.main([*base, "--dry-run"]) == 0
    digest = json.loads(capsys.readouterr().out)["approved"]
    assert module.main([*base, "--confirmed", "--approved", digest]) == 1
    data = job(env)
    assert data["status"] == "failed" and "timed out" in data["error"]


# --- check: the contract's one reading of its exit codes -------------------------------------


def test_check_probes_the_users_domain(env):
    result = run(env, "--check")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ready"] is True
    assert Path(env["_calls"]).read_text().splitlines() == [f"print gui/{os.getuid()}"]


def test_check_exits_3_without_a_user_domain(env):
    env["FAKE_LAUNCHCTL_EXIT"] = "113"  # what launchctl answers for a domain that does not exist
    result = run(env, "--check")
    assert result.returncode == 3 and "launchd domain is not reachable" in result.stderr
    assert not result.stdout.strip()


def test_check_exits_3_when_launchctl_cannot_be_started(env):
    Path(env["SCHEDULER_LAUNCHCTL"]).chmod(0o644)  # there, and not executable: an OSError, not a traceback
    result = run(env, "--check")
    assert result.returncode == 3 and "Traceback" not in result.stderr
    assert "could not be started" in result.stderr
