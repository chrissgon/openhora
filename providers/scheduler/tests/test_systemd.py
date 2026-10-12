"""Offline tests for providers/scheduler/systemd.py.

Run: uv run --with pytest pytest providers/scheduler/tests

Nothing reaches a service manager: SCHEDULER_SYSTEMCTL and SCHEDULER_LOGINCTL (honoured only
with SCHEDULER_TEST=1) point at fakes that record their arguments, and the job and unit folders
live in a temporary directory. The runner is called directly, as the service would call it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pwd
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
SCRIPT = HERE / "systemd.py"
LAUNCHD = HERE / "launchd.py"
UNIT = "dev.ai-workbench.scheduler.{}"

# Appends the snapshotted input to the output file, then prints a JSON line.
APPEND = ("import sys, json; open(sys.argv[2], 'a').write(open(sys.argv[1]).read() + '\\n'); "
          "print(json.dumps({'post_url': 'https://example.test/post'}))")


@pytest.fixture
def env(tmp_path):
    calls = tmp_path / "systemctl-calls.txt"
    fake = tmp_path / "systemctl"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\nexit "${{FAKE_SYSTEMCTL_EXIT:-0}}"\n')
    fake.chmod(0o755)
    login = tmp_path / "loginctl"
    login.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path / "loginctl-calls.txt"}"\n'
                     'echo "${FAKE_LINGER:-yes}"\n')
    login.chmod(0o755)
    values = {
        **os.environ,
        "SCHEDULER_HOME": str(tmp_path / "jobs"),
        "SCHEDULER_UNITS_DIR": str(tmp_path / "units"),
        "SCHEDULER_SYSTEMCTL": str(fake),
        "SCHEDULER_LOGINCTL": str(login),
        "SCHEDULER_NOTIFY": "0",
        "SCHEDULER_TEST": "1",
    }
    values["_calls"] = str(calls)
    return values


def run(env, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def command_file(tmp_path, code=APPEND, extra=None, content="hello", recurring=False):
    inp = tmp_path / "input.txt"
    inp.write_text(content)
    marker = tmp_path / "ran.txt"
    spec = {"argv": [sys.executable, "-c", code, str(inp), str(marker)], "cwd": str(tmp_path),
            "snapshot": [str(inp)], "outputs": [str(marker)], **(extra or {})}
    if not recurring and "grace_minutes" not in spec:
        spec["grace_minutes"] = 120
    path = tmp_path / "cmd.json"
    path.write_text(json.dumps(spec))
    return path, inp, marker


def when(args):
    return ["--every", str(args)] if isinstance(args, int) else ["--at", iso(args)]


def dry_run(env, path, schedule, job_id="job-1"):
    return run(env, "schedule", "--id", job_id, *when(schedule), "--command-file", str(path), "--dry-run")


def confirm(env, path, schedule, job_id="job-1"):
    preview = dry_run(env, path, schedule, job_id)
    assert preview.returncode == 0, preview.stderr
    digest = json.loads(preview.stdout)["approved"]
    return run(env, "schedule", "--id", job_id, *when(schedule), "--command-file", str(path),
               "--confirmed", "--approved", digest)


def soon():
    return datetime.now(timezone.utc) + timedelta(minutes=1)


def folder(env, job_id="job-1"):
    return Path(env["SCHEDULER_HOME"]) / job_id


def job(env, job_id="job-1"):
    return json.loads((folder(env, job_id) / "job.json").read_text())


def runs(env, job_id="job-1"):
    path = folder(env, job_id) / "runs.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def unit_file(env, kind, job_id="job-1"):
    return Path(env["SCHEDULER_UNITS_DIR"]) / f"{UNIT.format(job_id)}.{kind}"


def calls(env):
    path = Path(env["_calls"])
    return path.read_text().splitlines() if path.exists() else []


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def load(path, name, monkeypatch=None, env=None):
    if monkeypatch is not None:
        for key in ("SCHEDULER_HOME", "SCHEDULER_UNITS_DIR", "SCHEDULER_SYSTEMCTL", "SCHEDULER_LOGINCTL",
                    "SCHEDULER_NOTIFY", "SCHEDULER_TEST"):
            monkeypatch.setenv(key, env[key])
    spec = importlib.util.spec_from_file_location(name, path)
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


# --- dry run and the approval digest ------------------------------------------------


def test_one_shot_dry_run_prints_digest_and_units_and_writes_nothing(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=2)
    result = dry_run(env, path, at)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert len(out["approved"]) == 64 and out["approved"] == json.loads(dry_run(env, path, at).stdout)["approved"]
    timer = out["units"]["timer"].splitlines()
    assert f"OnCalendar={at.strftime('%Y-%m-%d %H:%M:%S')} UTC" in timer
    assert "Persistent=true" in timer and "AccuracySec=1s" in timer and "WantedBy=timers.target" in timer
    assert f"Unit={UNIT.format('job-1')}.service" in timer
    assert "Description=openhora scheduler timer for job job-1" in timer
    assert "# Written by the openhora scheduler for job job-1; cancel it with the provider, do not edit." in timer
    assert "Description=openhora scheduler job job-1" in out["units"]["service"].splitlines()
    assert not any(line.startswith(("OnActiveSec", "OnUnitActiveSec")) for line in timer)
    assert out["unit_paths"]["timer"] == str(unit_file(env, "timer"))
    assert not Path(env["SCHEDULER_HOME"]).exists() and not Path(env["SCHEDULER_UNITS_DIR"]).exists()
    assert calls(env) == []


def test_digest_means_the_same_as_launchd(env, tmp_path, monkeypatch):
    # The same fields, the same way: launchd.py's function gives the same digest for a job planned here.
    monkeypatch.setenv("SCHEDULER_TEST", "1")
    launchd = load(LAUNCHD, "launchd_for_parity")
    path, _, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc) + timedelta(days=1)
    planned = json.loads(dry_run(env, path, at).stdout)
    assert launchd.approval_digest(planned["job"]) == planned["approved"]
    fields = {key: planned["job"][key] for key in ("id", "at", "grace_minutes", "argv", "cwd", "outputs", "program")}
    fields["files"] = {source: entry["sha256"] for source, entry in planned["job"]["files"].items()}
    fields["runner"] = planned["job"]["runner"]["sha256"]
    expected = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert planned["approved"] == expected
    rpath, _, _ = command_file(tmp_path, recurring=True)
    recurring = json.loads(dry_run(env, rpath, 15).stdout)
    assert launchd.approval_digest(recurring["job"]) == recurring["approved"]


def test_recurring_dry_run_uses_monotonic_timers(env, tmp_path):
    path, _, _ = command_file(tmp_path, recurring=True)
    out = json.loads(dry_run(env, path, 15).stdout)
    timer = out["units"]["timer"].splitlines()
    assert "OnActiveSec=15min" in timer and "OnUnitActiveSec=15min" in timer
    assert not any(line.startswith(("OnCalendar", "Persistent")) for line in timer)
    planned = out["job"]
    assert (planned["kind"], planned["every_minutes"], planned["timeout_minutes"]) == ("recurring", 15, 30)
    assert json.loads(dry_run(env, path, 20).stdout)["approved"] != out["approved"]
    assert calls(env) == []


def test_limits_and_confirmation_rules(env, tmp_path):
    path, inp, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc) + timedelta(days=1)
    base = ["schedule", "--id", "job-1", "--at", iso(at), "--command-file", str(path)]
    assert run(env, *base).returncode == 2
    missing = run(env, *base, "--confirmed")
    assert missing.returncode == 2 and "--approved" in missing.stderr
    digest = json.loads(dry_run(env, path, at).stdout)["approved"]
    inp.write_text("changed after the dry run")
    changed = run(env, *base, "--confirmed", "--approved", digest)
    assert changed.returncode == 2 and "changed since the dry run" in changed.stderr
    assert dry_run(env, path, datetime.now(timezone.utc) - timedelta(minutes=1)).returncode == 2
    rpath, _, _ = command_file(tmp_path, recurring=True)
    for every in (4, 1441):
        assert dry_run(env, rpath, every).returncode == 2
    bad, _, _ = command_file(tmp_path, extra={"grace_minutes": 10}, recurring=True)
    assert "grace_minutes" in dry_run(env, bad, 15).stderr
    unlisted = tmp_path / "other.txt"
    unlisted.write_text("x")
    rpath, _, _ = command_file(tmp_path, recurring=True)
    spec = json.loads(rpath.read_text())
    spec["argv"].append(f"--text-file={unlisted}")
    rpath.write_text(json.dumps(spec))
    refused = dry_run(env, rpath, 15)
    assert refused.returncode == 2 and "not in the command file's snapshot" in refused.stderr
    assert not Path(env["SCHEDULER_HOME"]).exists() and calls(env) == []


# --- confirmed schedule -------------------------------------------------------------


def test_confirmed_schedule_writes_private_units_and_enables_the_timer(env, tmp_path):
    path, inp, _ = command_file(tmp_path)
    result = confirm(env, path, datetime.now(timezone.utc) + timedelta(days=1))
    assert result.returncode == 0, result.stderr
    data = job(env)
    service = unit_file(env, "service").read_text().splitlines()
    assert "Type=oneshot" in service and "UMask=0077" in service
    exec_start = next(line for line in service if line.startswith("ExecStart="))
    assert exec_start.endswith(f'"{data["runner"]["copy"]}" "run" "--id" "job-1"')
    assert f"StandardOutput=append:{folder(env) / 'systemd.out.log'}" in service
    assert any(line.startswith("Environment=") and f'"SCHEDULER_HOME={env["SCHEDULER_HOME"]}"' in line
               for line in service)
    for kind in ("service", "timer"):
        assert mode(unit_file(env, kind)) == 0o600
    for d in (Path(env["SCHEDULER_HOME"]), folder(env), folder(env) / "files", folder(env) / "runner"):
        assert mode(d) == 0o700, d
    for name in ("job.json", "systemd.out.log", "systemd.err.log"):
        assert mode(folder(env) / name) == 0o600, name
    assert mode(Path(data["files"][str(inp)]["copy"])) == 0o400
    assert Path(data["runner"]["copy"]).read_bytes() == SCRIPT.read_bytes()
    assert calls(env) == ["--user daemon-reload", f"--user enable --now {UNIT.format('job-1')}.timer"]
    assert data["status"] == "scheduled" and data["unit"] == UNIT.format("job-1")


def test_enable_failure_marks_the_job_failed_and_removes_the_units(env, tmp_path):
    env["FAKE_SYSTEMCTL_EXIT"] = "5"
    path, _, _ = command_file(tmp_path)
    result = confirm(env, path, datetime.now(timezone.utc) + timedelta(days=1))
    assert result.returncode == 1
    assert job(env)["status"] == "failed" and "daemon-reload exited 5" in job(env)["error"]
    assert not unit_file(env, "service").exists() and not unit_file(env, "timer").exists()


def test_systemctl_override_needs_the_test_flag(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    at = datetime.now(timezone.utc) + timedelta(days=1)
    digest = json.loads(dry_run(env, path, at).stdout)["approved"]
    del env["SCHEDULER_TEST"]
    result = run(env, "schedule", "--id", "job-1", "--at", iso(at), "--command-file", str(path),
                 "--confirmed", "--approved", digest)
    assert result.returncode == 2 and "SCHEDULER_TEST" in result.stderr
    assert calls(env) == [] and not folder(env).exists()


def test_unit_values_are_escaped(env, tmp_path, monkeypatch):
    module = load(SCRIPT, "systemd_quote", monkeypatch, env)
    assert module.unit_quote('/a b/%i/$HOME/"q"\\', exec_line=True) == '"/a b/%%i/$$HOME/\\"q\\"\\\\"'
    assert module.unit_quote("PATH=$x%") == '"PATH=$x%%"'
    with pytest.raises(module.ProviderError):
        module.unit_quote("line\nbreak")
    monkeypatch.setenv("SCHEDULER_HOME", str(tmp_path / "with space"))
    with pytest.raises(module.ProviderError):
        module.plain_path(module.job_dir("job-1") / "systemd.out.log", "the job folder")


def test_default_folders_follow_xdg(env, tmp_path, monkeypatch):
    module = load(SCRIPT, "systemd_xdg", monkeypatch, env)
    for key in ("SCHEDULER_HOME", "SCHEDULER_UNITS_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert module.home() == tmp_path / "home" / ".local" / "share" / "ai-workbench" / "scheduler"
    assert module.units_dir() == tmp_path / "home" / ".config" / "systemd" / "user"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert module.home() == tmp_path / "data" / "ai-workbench" / "scheduler"
    assert module.units_dir() == tmp_path / "config" / "systemd" / "user"


# --- one-shot firings ---------------------------------------------------------------


def test_one_shot_firing_runs_the_copy_once_and_removes_the_units(env, tmp_path):
    path, inp, marker = command_file(tmp_path)
    assert confirm(env, path, soon()).returncode == 0
    inp.write_text("edited later")
    first = run(env, "run", "--id", "job-1")
    assert first.returncode == 0, first.stderr
    assert marker.read_text() == "hello\n"
    data = job(env)
    assert data["status"] == "done" and data["post_url"] == "https://example.test/post"
    assert not unit_file(env, "service").exists() and not unit_file(env, "timer").exists()
    timer = f"{UNIT.format('job-1')}.timer"
    assert calls(env)[-3:] == [f"--user disable --now {timer}", f"--user clean --what=state {timer}",
                               "--user daemon-reload"]
    assert not any(line.startswith("--user stop") for line in calls(env))  # never stops its own service
    for name in ("run.stdout.log", "run.stderr.log"):
        assert mode(folder(env) / name) == 0o600
    marker.unlink()
    assert run(env, "run", "--id", "job-1").returncode == 0
    assert not marker.exists() and job(env)["status"] == "done"


def test_late_firing_after_grace_is_missed(env, tmp_path):
    path, _, marker = command_file(tmp_path, extra={"grace_minutes": 0})
    assert confirm(env, path, soon()).returncode == 0
    data = job(env)
    data["at"] = iso(datetime.now(timezone.utc) - timedelta(minutes=10))
    (folder(env) / "job.json").write_text(json.dumps(data))
    assert run(env, "run", "--id", "job-1").returncode == 1
    assert job(env)["status"] == "missed" and not marker.exists()
    assert not unit_file(env, "timer").exists()


def test_one_shot_refuses_a_changed_copy_or_runner(env, tmp_path):
    path, inp, marker = command_file(tmp_path)
    assert confirm(env, path, soon()).returncode == 0
    copy = Path(job(env)["files"][str(inp)]["copy"])
    copy.chmod(0o600)
    copy.write_text("tampered")
    assert run(env, "run", "--id", "job-1").returncode == 1
    assert job(env)["status"] == "refused" and not marker.exists()
    path, _, _ = command_file(tmp_path)
    assert confirm(env, path, soon(), job_id="job-2").returncode == 0
    changed = tmp_path / "systemd.py"
    changed.write_text(SCRIPT.read_text() + "\n# changed on another branch\n")
    result = subprocess.run([sys.executable, str(changed), "run", "--id", "job-2"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 1 and "runner" in job(env, "job-2")["reason"]


def test_notifications_are_recorded_privately(env, tmp_path):
    env["SCHEDULER_NOTIFY"] = "1"
    path, _, _ = command_file(tmp_path)
    assert confirm(env, path, soon()).returncode == 0
    assert run(env, "run", "--id", "job-1").returncode == 0
    log = Path(env["SCHEDULER_HOME"]) / "notifications.jsonl"
    (line,) = [json.loads(x) for x in log.read_text().splitlines()]
    assert line["title"] == "openhora: job-1 done" and line["message"] == "https://example.test/post"
    assert mode(log) == 0o600


# --- recurring firings --------------------------------------------------------------


def test_recurring_firings_are_recorded_and_the_timer_stays(env, tmp_path):
    path, inp, marker = command_file(tmp_path, recurring=True, content="tick")
    assert confirm(env, path, 15).returncode == 0
    inp.write_text("edited later")
    before = len(calls(env))
    for _ in range(2):
        assert run(env, "run", "--id", "job-1").returncode == 0
    assert marker.read_text() == "tick\ntick\n"
    records = runs(env)
    assert [r["status"] for r in records] == ["done", "done"]
    assert all(r["exit_code"] == 0 and r["started_at"] <= r["ended_at"] for r in records)
    assert mode(folder(env) / "runs.jsonl") == 0o600 and mode(folder(env) / "run.lock") == 0o600
    assert job(env)["status"] == "scheduled" and unit_file(env, "timer").exists()
    assert len(calls(env)) == before


def test_recurring_failure_caps_the_tails(env, tmp_path):
    code = "import sys; sys.stdout.write('o' * 10000); sys.stderr.write('e' * 10000); sys.exit(4)"
    path, _, _ = command_file(tmp_path, code=code, recurring=True)
    assert confirm(env, path, 15).returncode == 0
    assert run(env, "run", "--id", "job-1").returncode == 1
    (record,) = runs(env)
    assert record["status"] == "failed" and record["exit_code"] == 4
    assert record["stdout_tail"] == "o" * 4096 and record["stderr_tail"] == "e" * 4096


def test_overlapping_firing_is_skipped(env, tmp_path):
    started = tmp_path / "started"
    code = (f"import sys, time; open({str(started)!r}, 'w').write('1'); time.sleep(3); "
            "open(sys.argv[2], 'a').write(open(sys.argv[1]).read())")
    path, _, marker = command_file(tmp_path, code=code, recurring=True, content="tick")
    assert confirm(env, path, 15).returncode == 0
    first = subprocess.Popen([sys.executable, str(SCRIPT), "run", "--id", "job-1"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 10
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert started.exists()
    second = run(env, "run", "--id", "job-1")
    assert second.returncode == 0, second.stderr
    first.communicate(timeout=20)
    assert first.returncode == 0
    records = runs(env)
    assert [r["status"] for r in records] == ["skipped-overlap", "done"]
    assert str(first.pid) in records[0]["reason"]
    assert marker.read_text() == "tick"


def test_stale_lock_is_taken_over(env, tmp_path):
    path, _, marker = command_file(tmp_path, recurring=True)
    assert confirm(env, path, 15).returncode == 0
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (folder(env) / "run.lock").write_text(f"{dead.pid}\n")
    assert run(env, "run", "--id", "job-1").returncode == 0
    (record,) = runs(env)
    assert record["status"] == "done" and record["stale_lock_pid"] == str(dead.pid)
    assert marker.exists()


def test_tampered_snapshot_is_refused_and_disables_the_timer(env, tmp_path):
    path, inp, marker = command_file(tmp_path, recurring=True, content="tick")
    assert confirm(env, path, 15).returncode == 0
    assert run(env, "run", "--id", "job-1").returncode == 0
    copy = Path(job(env)["files"][str(inp)]["copy"])
    copy.chmod(0o600)
    copy.write_text("tampered")
    assert run(env, "run", "--id", "job-1").returncode == 1
    assert [r["status"] for r in runs(env)] == ["done", "refused"]
    data = job(env)
    assert data["status"] == "refused" and "changed after scheduling" in data["reason"]
    assert not unit_file(env, "timer").exists() and not unit_file(env, "service").exists()
    assert calls(env)[-2:] == [f"--user disable --now {UNIT.format('job-1')}.timer", "--user daemon-reload"]
    assert marker.read_text() == "tick\n"
    # A firing already queued finds the job refused and does nothing.
    assert run(env, "run", "--id", "job-1").returncode == 0
    assert len(runs(env)) == 2


def test_timeout_kills_the_process_group(env, tmp_path, monkeypatch):
    child_pid = tmp_path / "child.pid"
    code = ("import subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(child_pid)!r}, 'w').write(str(p.pid)); print('started', flush=True); time.sleep(60)")
    path, _, _ = command_file(tmp_path, code=code, extra={"timeout_minutes": 20}, recurring=True)
    assert confirm(env, path, 15).returncode == 0
    module = load(SCRIPT, "systemd_timeout", monkeypatch, env)
    module.TIMEOUT_UNIT_SECONDS = 0.05  # 20 "minutes" -> 1 second
    module.KILL_GRACE_SECONDS = 2
    began = time.monotonic()
    assert module.main(["run", "--id", "job-1"]) == 1
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
    assert job(env)["status"] == "scheduled" and unit_file(env, "timer").exists()


# --- list, cancel, check ----------------------------------------------------------------


def test_list_shows_both_kinds(env, tmp_path):
    path, _, _ = command_file(tmp_path)
    assert confirm(env, path, datetime.now(timezone.utc) + timedelta(days=1), job_id="post").returncode == 0
    rpath, _, _ = command_file(tmp_path, recurring=True)
    assert confirm(env, rpath, 15, job_id="tick").returncode == 0
    listed = {j["id"]: j for j in json.loads(run(env, "list").stdout)["jobs"]}
    assert (listed["post"]["status"], listed["post"]["units_present"]) == ("scheduled", True)
    assert "last_run" not in listed["post"]
    assert (listed["tick"]["every_minutes"], listed["tick"]["last_run"]) == (15, None)
    assert run(env, "run", "--id", "tick").returncode == 0
    (tick,) = [j for j in json.loads(run(env, "list").stdout)["jobs"] if j["id"] == "tick"]
    assert tick["last_run"]["status"] == "done" and "stdout_tail" not in tick["last_run"]


def test_cancel_stops_and_removes_the_units(env, tmp_path):
    path, _, marker = command_file(tmp_path, recurring=True)
    assert confirm(env, path, 15).returncode == 0
    assert run(env, "cancel", "--id", "job-1").returncode == 2
    assert run(env, "cancel", "--id", "job-1", "--confirmed").returncode == 0
    assert job(env)["status"] == "cancelled"
    assert not unit_file(env, "timer").exists() and not unit_file(env, "service").exists()
    name = UNIT.format("job-1")
    assert calls(env)[-3:] == [f"--user disable --now {name}.timer", f"--user stop {name}.service",
                               "--user daemon-reload"]
    assert run(env, "run", "--id", "job-1").returncode == 0
    assert runs(env) == [] and not marker.exists()
    (listed,) = json.loads(run(env, "list").stdout)["jobs"]
    assert (listed["status"], listed["units_present"]) == ("cancelled", False)


def test_check_with_linger(env):
    result = run(env, "--check")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    user = pwd.getpwuid(os.getuid()).pw_name
    assert out["ready"] is True and out["linger"] is True and out["user"] == user and "fix" not in out
    assert calls(env) == ["--user --no-pager list-timers"]
    login_calls = (Path(env["_calls"]).parent / "loginctl-calls.txt").read_text().splitlines()
    assert login_calls == [f"show-user {user} --property=Linger --value"]


def test_check_without_linger_says_how_to_enable_it(env):
    env["FAKE_LINGER"] = "no"
    result = run(env, "--check")
    assert result.returncode == 3
    out = json.loads(result.stdout)
    assert out["ready"] is False and out["linger"] is False
    assert f"loginctl enable-linger {out['user']}" in out["fix"]
    assert "enable-linger" in result.stderr


def test_check_without_a_user_manager(env):
    env["FAKE_SYSTEMCTL_EXIT"] = "1"
    result = run(env, "--check")
    assert result.returncode == 3 and "user service manager" in result.stderr
