"""Offline tests for recurring jobs (schedule --every) in providers/scheduler/launchd.py.

Run: uv run --with pytest pytest providers/scheduler/tests

Nothing is loaded into launchd: SCHEDULER_LAUNCHCTL (honoured only with SCHEDULER_TEST=1)
points at a fake launchctl that records its arguments, and the job and agent folders live
in a temporary directory.
"""
from __future__ import annotations

import hashlib
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

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "launchd.py"
LABEL = "dev.ai-workbench.scheduler.tick"

# Appends the snapshotted input to the output file, then prints a JSON line.
APPEND = ("import sys, json; open(sys.argv[2], 'a').write(open(sys.argv[1]).read() + '\\n'); "
          "print(json.dumps({'ok': True}))")


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


def command_file(tmp_path, code=APPEND, extra=None, content="tick"):
    inp = tmp_path / "input.txt"
    inp.write_text(content)
    marker = tmp_path / "ran.txt"
    spec = {"argv": [sys.executable, "-c", code, str(inp), str(marker)], "cwd": str(tmp_path),
            "snapshot": [str(inp)], "outputs": [str(marker)], **(extra or {})}
    path = tmp_path / "tick.json"
    path.write_text(json.dumps(spec))
    return path, inp, marker


def dry_run(env, path, every=15, job_id="tick"):
    return run(env, "schedule", "--id", job_id, "--every", str(every), "--command-file", str(path), "--dry-run")


def confirm(env, path, every=15, job_id="tick"):
    preview = dry_run(env, path, every, job_id)
    assert preview.returncode == 0, preview.stderr
    digest = json.loads(preview.stdout)["approved"]
    return run(env, "schedule", "--id", job_id, "--every", str(every), "--command-file", str(path),
               "--confirmed", "--approved", digest)


def folder(env, job_id="tick"):
    return Path(env["SCHEDULER_HOME"]) / job_id


def job(env, job_id="tick"):
    return json.loads((folder(env, job_id) / "job.json").read_text())


def runs(env, job_id="tick"):
    path = folder(env, job_id) / "runs.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def plist_file(env):
    return Path(env["SCHEDULER_AGENTS_DIR"]) / f"{LABEL}.plist"


def load_module(monkeypatch, env):
    for key in ("SCHEDULER_HOME", "SCHEDULER_AGENTS_DIR", "SCHEDULER_LAUNCHCTL", "SCHEDULER_NOTIFY", "SCHEDULER_TEST"):
        monkeypatch.setenv(key, env[key])
    spec = importlib.util.spec_from_file_location("launchd_provider_recurring", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_dry_run_prints_digest_and_start_interval_and_writes_nothing(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    first = dry_run(env, path)
    assert first.returncode == 0, first.stderr
    out = json.loads(first.stdout)
    assert len(out["approved"]) == 64 and out["approved"] == json.loads(dry_run(env, path).stdout)["approved"]
    assert out["plist"]["StartInterval"] == 900
    assert "StartCalendarInterval" not in out["plist"]
    assert out["plist"]["ProgramArguments"][-3:] == ["run", "--id", "tick"]
    planned = out["job"]
    assert (planned["kind"], planned["every_minutes"], planned["timeout_minutes"]) == ("recurring", 15, 30)
    assert "at" not in planned and "grace_minutes" not in planned
    assert json.loads(dry_run(env, path, every=20).stdout)["approved"] != out["approved"]
    assert not Path(env["SCHEDULER_HOME"]).exists()
    assert not Path(env["_calls"]).exists()


def test_every_and_command_file_limits(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    for every in (4, 1441):
        result = dry_run(env, path, every=every)
        assert result.returncode == 2 and "--every" in result.stderr, every
    both = run(env, "schedule", "--id", "tick", "--every", "15", "--at", "2030-01-01T09:00:00Z",
               "--command-file", str(path), "--dry-run")
    assert both.returncode == 2 and "mutually exclusive" in both.stderr
    for extra, word in (({"grace_minutes": 10}, "grace_minutes"), ({"timeout_minutes": 241}, "timeout_minutes"),
                        ({"timeout_minutes": 0}, "timeout_minutes"), ({"timeout_minutes": True}, "timeout_minutes")):
        bad, _, _ = command_file(tmp_path, extra=extra)
        result = dry_run(env, bad)
        assert result.returncode == 2 and word in result.stderr, extra
    assert not Path(env["SCHEDULER_HOME"]).exists()


def test_one_shot_digest_and_job_are_unchanged(env, tmp_path):
    # The one-shot approval digest keeps the field set it had before recurring jobs existed.
    path, _, _ = command_file(tmp_path)
    at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    out = json.loads(run(env, "schedule", "--id", "tick", "--at", at, "--command-file", str(path), "--dry-run").stdout)
    planned = out["job"]
    assert "kind" not in planned and "StartInterval" not in out["plist"]
    fields = {key: planned[key] for key in ("id", "at", "grace_minutes", "argv", "cwd", "outputs", "program")}
    fields["files"] = {source: entry["sha256"] for source, entry in planned["files"].items()}
    fields["runner"] = planned["runner"]["sha256"]
    expected = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert out["approved"] == expected


def test_confirmed_schedule_writes_plist_with_start_interval(env, tmp_path):
    path, inp, _ = command_file(tmp_path)
    result = confirm(env, path)
    assert result.returncode == 0, result.stderr
    plist = plistlib.loads(plist_file(env).read_bytes())
    assert plist["StartInterval"] == 900 and "StartCalendarInterval" not in plist
    assert plist["Label"] == LABEL
    assert stat.S_IMODE(plist_file(env).stat().st_mode) == 0o600
    data = job(env)
    assert data["kind"] == "recurring" and data["status"] == "scheduled"
    assert str(inp) not in data["argv"] and data["files"][str(inp)]["copy"] in data["argv"]
    assert f"bootstrap gui/{os.getuid()}" in Path(env["_calls"]).read_text()


def test_confirmed_schedule_needs_the_dry_run_digest(env, tmp_path):
    path, inp, _ = command_file(tmp_path)
    digest = json.loads(dry_run(env, path).stdout)["approved"]
    inp.write_text("changed after the dry run")
    result = run(env, "schedule", "--id", "tick", "--every", "15", "--command-file", str(path),
                 "--confirmed", "--approved", digest)
    assert result.returncode == 2 and "changed since the dry run" in result.stderr
    assert not folder(env).exists()


def test_each_firing_is_recorded_and_the_job_keeps_firing(env, tmp_path):
    path, inp, marker = command_file(tmp_path)
    assert confirm(env, path).returncode == 0
    inp.write_text("edited later")
    for _ in range(2):
        assert run(env, "run", "--id", "tick").returncode == 0
    assert marker.read_text() == "tick\ntick\n"
    records = runs(env)
    assert [r["status"] for r in records] == ["done", "done"]
    for record in records:
        assert record["exit_code"] == 0 and record["stdout_tail"].strip() == '{"ok": true}'
        assert record["started_at"] <= record["ended_at"]
    assert stat.S_IMODE((folder(env) / "runs.jsonl").stat().st_mode) == 0o600
    assert stat.S_IMODE((folder(env) / "run.lock").stat().st_mode) == 0o600
    assert (folder(env) / "run.lock").read_text() == ""
    assert job(env)["status"] == "scheduled" and plist_file(env).exists()
    assert "bootout gui/" not in Path(env["_calls"]).read_text().split("bootstrap")[-1]


def test_failed_firing_is_recorded_and_tails_are_capped(env, tmp_path):
    code = "import sys; sys.stdout.write('o' * 10000); sys.stderr.write('e' * 10000); sys.exit(4)"
    path, _, _ = command_file(tmp_path, code=code)
    assert confirm(env, path).returncode == 0
    assert run(env, "run", "--id", "tick").returncode == 1
    (record,) = runs(env)
    assert record["status"] == "failed" and record["exit_code"] == 4
    assert record["stdout_tail"] == "o" * 4096 and record["stderr_tail"] == "e" * 4096
    assert job(env)["status"] == "scheduled" and plist_file(env).exists()


def test_overlapping_firing_is_skipped(env, tmp_path):
    started = tmp_path / "started"
    code = (f"import sys, time; open({str(started)!r}, 'w').write('1'); time.sleep(3); "
            "open(sys.argv[2], 'a').write(open(sys.argv[1]).read())")
    path, _, marker = command_file(tmp_path, code=code)
    assert confirm(env, path).returncode == 0
    first = subprocess.Popen([sys.executable, str(SCRIPT), "run", "--id", "tick"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 10
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert started.exists()
    second = run(env, "run", "--id", "tick")
    assert second.returncode == 0, second.stderr
    first.communicate(timeout=20)
    assert first.returncode == 0
    records = runs(env)
    assert [r["status"] for r in records] == ["skipped-overlap", "done"]
    assert str(first.pid) in records[0]["reason"]
    assert marker.read_text() == "tick"


def test_stale_lock_is_taken_over(env, tmp_path):
    path, _, marker = command_file(tmp_path)
    assert confirm(env, path).returncode == 0
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (folder(env) / "run.lock").write_text(f"{dead.pid}\n")
    assert run(env, "run", "--id", "tick").returncode == 0
    (record,) = runs(env)
    assert record["status"] == "done" and record["stale_lock_pid"] == str(dead.pid)
    assert marker.exists()


def test_tampered_snapshot_is_refused_and_unloads_the_job(env, tmp_path):
    path, inp, marker = command_file(tmp_path)
    assert confirm(env, path).returncode == 0
    assert run(env, "run", "--id", "tick").returncode == 0
    copy = Path(job(env)["files"][str(inp)]["copy"])
    copy.chmod(0o600)
    copy.write_text("tampered")
    assert run(env, "run", "--id", "tick").returncode == 1
    assert [r["status"] for r in runs(env)] == ["done", "refused"]
    data = job(env)
    assert data["status"] == "refused" and "changed after scheduling" in data["reason"]
    assert not plist_file(env).exists()
    assert Path(env["_calls"]).read_text().splitlines()[-1] == f"bootout gui/{os.getuid()}/{LABEL}"
    assert marker.read_text() == "tick\n"
    # A firing that launchd had already queued finds the job refused and does nothing.
    assert run(env, "run", "--id", "tick").returncode == 0
    assert len(runs(env)) == 2


def test_timeout_kills_the_process_group(env, tmp_path, monkeypatch):
    child_pid = tmp_path / "child.pid"
    code = ("import subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(child_pid)!r}, 'w').write(str(p.pid)); print('started', flush=True); time.sleep(60)")
    path, _, _ = command_file(tmp_path, code=code, extra={"timeout_minutes": 20})
    assert confirm(env, path).returncode == 0
    module = load_module(monkeypatch, env)
    module.TIMEOUT_UNIT_SECONDS = 0.05  # 20 "minutes" -> 1 second
    module.KILL_GRACE_SECONDS = 2
    began = time.monotonic()
    assert module.main(["run", "--id", "tick"]) == 1
    assert time.monotonic() - began < 15
    (record,) = runs(env)
    assert record["status"] == "failed" and record["reason"].startswith("timeout")
    assert record["exit_code"] is not None and record["exit_code"] < 0
    assert "started" in record["stdout_tail"]
    grandchild = int(child_pid.read_text())
    deadline = time.monotonic() + 5
    while pid_alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_alive(grandchild)
    assert job(env)["status"] == "scheduled" and plist_file(env).exists()


def test_list_shows_every_and_the_last_firing(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    assert confirm(env, path).returncode == 0
    (listed,) = json.loads(run(env, "list").stdout)["jobs"]
    assert (listed["kind"], listed["every_minutes"], listed["last_run"], listed["plist_present"]) == (
        "recurring", 15, None, True)
    assert run(env, "run", "--id", "tick").returncode == 0
    (listed,) = json.loads(run(env, "list").stdout)["jobs"]
    assert listed["last_run"]["status"] == "done" and listed["last_run"]["exit_code"] == 0
    assert "stdout_tail" not in listed["last_run"]


def test_cancel_unloads_a_recurring_job(env, tmp_path):
    path, _, marker = command_file(tmp_path)
    assert confirm(env, path).returncode == 0
    assert run(env, "cancel", "--id", "tick").returncode == 2
    assert run(env, "cancel", "--id", "tick", "--confirmed").returncode == 0
    assert job(env)["status"] == "cancelled" and not plist_file(env).exists()
    assert Path(env["_calls"]).read_text().splitlines()[-1] == f"bootout gui/{os.getuid()}/{LABEL}"
    assert run(env, "run", "--id", "tick").returncode == 0
    assert runs(env) == [] and not marker.exists()
    (listed,) = json.loads(run(env, "list").stdout)["jobs"]
    assert (listed["status"], listed["plist_present"]) == ("cancelled", False)
