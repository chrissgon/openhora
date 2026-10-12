"""Offline tests of both scheduler providers (launchd.py and systemd.py): the one-shot path (what happens to a
job between "running" and its end) and the rules both share (ids, the command file, the lock, bounded files).

Run: uv run --with pytest pytest providers/scheduler/tests

Every test runs once per provider. Nothing is loaded into launchd or systemd: the service managers are fake
scripts that record their arguments (honoured only with SCHEDULER_TEST=1), and the job and unit folders live
in a temporary directory.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
OK = "import json; print(json.dumps({'post_url': 'https://example.test/post'}))"


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
        if name == "launchd":
            self.env.update({"SCHEDULER_AGENTS_DIR": str(tmp_path / "agents"), "SCHEDULER_LAUNCHCTL": str(fake)})
        else:
            self.env.update({"SCHEDULER_UNITS_DIR": str(tmp_path / "units"), "SCHEDULER_SYSTEMCTL": str(fake),
                             "SCHEDULER_LOGINCTL": str(login)})

    def run(self, *args):
        return subprocess.run([sys.executable, str(self.script), *args], env=self.env, capture_output=True,
                              text=True, timeout=120)

    def command_file(self, code=OK, **extra) -> Path:
        spec = {"argv": [sys.executable, "-c", code], "cwd": str(self.tmp), "snapshot": [], **extra}
        path = self.tmp / "job.json"
        path.write_text(json.dumps(spec))
        return path

    def schedule(self, path: Path, job_id="post-1"):
        at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        base = ["schedule", "--id", job_id, "--at", at, "--command-file", str(path)]
        dry = self.run(*base, "--dry-run")
        if dry.returncode != 0:
            return dry, None
        return self.run(*base, "--confirmed", "--approved", json.loads(dry.stdout)["approved"]), json.loads(dry.stdout)

    def folder(self, job_id="post-1") -> Path:
        return Path(self.env["SCHEDULER_HOME"]) / job_id

    def job(self, job_id="post-1") -> dict:
        return json.loads((self.folder(job_id) / "job.json").read_text())

    def set_job(self, job_id="post-1", **fields) -> None:
        path = self.folder(job_id) / "job.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), **fields}))

    def module(self, monkeypatch):
        for key, value in self.env.items():
            if key.startswith("SCHEDULER_"):
                monkeypatch.setenv(key, value)
        spec = importlib.util.spec_from_file_location(f"{self.name}_one_shot", self.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


@pytest.fixture(params=["launchd", "systemd"])
def s(request, tmp_path):
    return Scheduler(request.param, tmp_path)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# --- SC1: output that is not UTF-8 ---------------------------------------------------


def test_output_that_is_not_utf8_does_not_leave_the_job_running(s):
    # The command's output was decoded as text: bytes that are not UTF-8 raised UnicodeDecodeError after the job
    # was marked "running", and nothing ever changed that status.
    code = ("import sys; sys.stdout.buffer.write(b'\\xff\\xfe caf\\xe9\\n'); "
            "sys.stderr.buffer.write(b'warn \\xff\\n')")
    done, _ = s.schedule(s.command_file(code))
    assert done.returncode == 0, done.stderr
    fired = s.run("run", "--id", "post-1")
    assert fired.returncode == 0, fired.stderr
    assert "Traceback" not in fired.stderr
    data = s.job()
    assert data["status"] == "done" and data["exit_code"] == 0
    assert (s.folder() / "run.stdout.log").read_bytes() == b"\xff\xfe caf\xe9\n"  # kept as the command wrote it
    assert (s.folder() / "run.stderr.log").read_bytes() == b"warn \xff\n"


def test_post_url_is_still_read_next_to_bytes_that_are_not_utf8(s):
    code = ("import sys, json; sys.stdout.buffer.write(json.dumps({'post_url': 'https://example.test/p', "
            "'note': 'X'}).replace('X', '\\udcff').encode('utf-8', 'surrogateescape'))")
    assert s.schedule(s.command_file(code))[0].returncode == 0
    assert s.run("run", "--id", "post-1").returncode == 0
    assert s.job()["post_url"] == "https://example.test/p"


def test_an_error_while_the_job_runs_is_recorded_as_failed(s, monkeypatch):
    # Whatever breaks between "running" and the end, the job ends: it never stays "running".
    assert s.schedule(s.command_file())[0].returncode == 0
    module = s.module(monkeypatch)

    def broken(*_args, **_kw):
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(module, "run_command", broken)
    assert module.main(["run", "--id", "post-1"]) == 1
    data = s.job()
    assert data["status"] == "failed" and "RuntimeError" in data["reason"]


# --- SC5: the one-shot limit -----------------------------------------------------------


def test_the_one_shot_limit_kills_the_process_group_and_keeps_the_output(s, monkeypatch):
    # The limit was a fixed 600 s that no document stated; past it only the direct child was killed and what
    # the command had printed was lost, so a job that had already published ended "failed" with nothing kept.
    child_pid = s.tmp / "child.pid"
    code = ("import subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(child_pid)!r}, 'w').write(str(p.pid)); "
            "print('{\"post_url\": \"https://example.test/out\"}', flush=True); time.sleep(60)")
    done, _ = s.schedule(s.command_file(code, timeout_minutes=20))
    assert done.returncode == 0, done.stderr
    assert s.job()["timeout_minutes"] == 20
    module = s.module(monkeypatch)
    module.TIMEOUT_UNIT_SECONDS = 0.05  # 20 "minutes" -> 1 second
    module.KILL_GRACE_SECONDS = 2
    began = time.monotonic()
    assert module.main(["run", "--id", "post-1"]) == 1
    assert time.monotonic() - began < 15
    data = s.job()
    assert data["status"] == "failed" and data["reason"].startswith("timeout")
    assert "timeout_minutes (20)" in data["reason"]
    assert data["post_url"] == "https://example.test/out"  # what it printed before the limit is kept and read
    assert b"example.test/out" in (s.folder() / "run.stdout.log").read_bytes()
    grandchild = int(child_pid.read_text())
    deadline = time.monotonic() + 5
    while pid_alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_alive(grandchild)


def test_the_default_one_shot_limit_is_stated_and_timeout_minutes_is_checked(s, monkeypatch):
    module = s.module(monkeypatch)
    assert module.DEFAULT_ONE_SHOT_TIMEOUT_MINUTES == 10
    help_text = s.run("--help").stdout
    assert "timeout_minutes" in help_text and "default 10" in help_text
    plain, dry = s.schedule(s.command_file())
    assert plain.returncode == 0 and "timeout_minutes" not in s.job()  # a job without it is the job it always was
    _, longer = s.schedule(s.command_file(timeout_minutes=30), job_id="post-2")
    assert longer["job"]["timeout_minutes"] == 30
    _, other = s.schedule(s.command_file(timeout_minutes=40), job_id="post-3")
    assert other["approved"] != longer["approved"]  # the limit is part of what is approved
    for bad in (0, 241, True, "10"):
        at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        refused = s.run("schedule", "--id", "post-4", "--at", at, "--command-file",
                        str(s.command_file(timeout_minutes=bad)), "--dry-run")
        assert refused.returncode == 2 and "timeout_minutes" in refused.stderr, bad


# --- SC2: a job in "running" -----------------------------------------------------------


def test_a_running_job_whose_runner_is_gone_can_be_cancelled_and_scheduled_again(s):
    # After a crash or a power loss the job stayed "running": cancel exited 0 and changed nothing, and the id
    # could not be scheduled again until job.json was edited by hand.
    path = s.command_file()
    assert s.schedule(path)[0].returncode == 0
    s.set_job(status="running", started_at="2026-10-01T09:00:00Z")
    blocked, _ = s.schedule(path)
    assert blocked.returncode == 2 and "running" in blocked.stderr and "resolve" in blocked.stderr
    assert s.run("cancel", "--id", "post-1").returncode == 2  # needs --confirmed
    cancelled = s.run("cancel", "--id", "post-1", "--confirmed")
    assert cancelled.returncode == 0, cancelled.stderr
    data = s.job()
    assert data["status"] == "cancelled" and data["interrupted"] is True
    assert "outcome is unknown" in data["reason"] and "finished_at" in data
    again, _ = s.schedule(path)
    assert again.returncode == 0, again.stderr
    assert s.job()["status"] == "scheduled"


def test_a_running_job_whose_runner_is_gone_can_be_resolved(s):
    assert s.schedule(s.command_file())[0].returncode == 0
    base = ["resolve", "--id", "post-1"]
    assert s.run(*base, "--done", "--confirmed").returncode == 2  # a scheduled job has nothing to resolve
    s.set_job(status="running", started_at="2026-10-01T09:00:00Z")
    assert s.run(*base, "--done").returncode == 2  # needs --confirmed
    assert s.run(*base, "--confirmed").returncode == 2  # needs the outcome
    assert s.run(*base, "--done", "--failed", "--confirmed").returncode == 2
    shown = s.run(*base, "--failed", "--dry-run")
    assert shown.returncode == 0 and json.loads(shown.stdout)["dry_run"] is True
    assert s.job()["status"] == "running"  # a dry run changes nothing
    done = s.run(*base, "--done", "--confirmed")
    assert done.returncode == 0, done.stderr
    data = s.job()
    assert data["status"] == "done" and data["resolved"] is True and "finished_at" in data
    assert s.run(*base, "--failed", "--confirmed").returncode == 2  # only a running job


def test_resolve_refuses_while_the_runner_is_alive(s):
    assert s.schedule(s.command_file())[0].returncode == 0
    s.set_job(status="running", started_at="2026-10-01T09:00:00Z")
    lock = os.open(s.folder() / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)  # what a live runner holds
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(lock, f"{os.getpid()}\n".encode())
        refused = s.run("resolve", "--id", "post-1", "--failed", "--confirmed")
        assert refused.returncode == 1 and "still runs" in refused.stderr
        assert s.job()["status"] == "running"
    finally:
        os.close(lock)
    assert s.run("resolve", "--id", "post-1", "--failed", "--confirmed").returncode == 0
    assert s.job()["status"] == "failed"


def test_a_second_runner_does_not_run_the_command_again(s):
    marker = s.tmp / "ran.txt"
    code = f"open({str(marker)!r}, 'a').write('x')"
    assert s.schedule(s.command_file(code))[0].returncode == 0
    lock = os.open(s.folder() / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)  # another runner holds the job
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        second = s.run("run", "--id", "post-1")
        assert second.returncode == 0 and not marker.exists()
        assert s.job()["status"] == "scheduled"
    finally:
        os.close(lock)
    assert s.run("run", "--id", "post-1").returncode == 0
    assert marker.read_text() == "x" and s.job()["status"] == "done"


# --- SC4: a file argument in a spelling the scheduler does not understand --------------------


def test_a_file_in_a_spelling_that_cannot_be_verified_is_refused(s):
    # Only a bare path and --flag=<path> were recognised: "-f/abs/file", "key=/abs/file" and "a,b" passed
    # through with an empty snapshot, and the job read the live files at its slot.
    post, other = s.tmp / "post.txt", s.tmp / "other.txt"
    post.write_text("hello")
    other.write_text("world")
    spellings = (f"-f{post}", f"text={post}", f"--file=data/post.txt={post}", f"{post},{other}",
                 f"{post}:{other}", f"--files={post};{other}", "post.txt,other.txt", "-fpost.txt")
    for arg in spellings:
        # In the snapshot or not: the argument cannot be swapped for the copy, so the job is refused.
        for snapshot in ([], [str(post), str(other)]):
            path = s.command_file(snapshot=snapshot, argv=[sys.executable, "-c", OK, arg])
            done, _ = s.schedule(path)
            assert done.returncode == 2, (arg, done.stderr)
            assert "in a spelling the scheduler cannot verify" in done.stderr, arg
    assert not Path(s.env["SCHEDULER_HOME"]).exists()


def test_arguments_that_name_no_file_pass_as_they_are(s):
    (s.tmp / "post.txt").write_text("hello")
    (s.tmp / "LICENSE").write_text("text")
    plain = ["--at=2026-10-14T09:00:00-03:00", "https://example.test/a:b", "key=value", "a,b;c", "-v",
             "--path", str(s.tmp), "a note: post.txt, and more", "-x", "--title", "LICENSE: what it means",
             "post.txt,missing.txt"]
    done, planned = s.schedule(s.command_file(argv=[sys.executable, "-c", OK, *plain]))
    assert done.returncode == 0, done.stderr
    assert planned["job"]["argv"][3:] == plain


# --- SC10: an id is checked whole --------------------------------------------------------


def test_an_id_with_a_trailing_newline_is_refused(s):
    # ID_PATTERN ends in "$" and was used with .match: "$" also matches before a final newline, so "post-1\n"
    # passed and became a folder, a label and a unit name with a newline in it.
    at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    for bad in ("post-1\n", "post-1\n\n", "Post-1", "-post"):
        refused = s.run("schedule", "--id", bad, "--at", at, "--command-file", str(s.command_file()), "--dry-run")
        assert refused.returncode == 2 and "--id" in refused.stderr, repr(bad)
    assert s.schedule(s.command_file())[0].returncode == 0
    for verb in (["cancel", "--confirmed"], ["resolve", "--done", "--confirmed"], ["run"]):
        refused = s.run(verb[0], "--id", "post-1\n", *verb[1:])
        assert refused.returncode == 2 and "--id" in refused.stderr, verb


# --- SC12: grace_minutes and --at --------------------------------------------------------


def test_grace_minutes_is_an_integer_up_to_a_week(s, monkeypatch):
    # A bool is an int in Python, so "grace_minutes": true passed as a grace of 1 minute, and nothing bounded it.
    assert s.module(monkeypatch).MAX_GRACE_MINUTES == 10080
    help_text = s.run("--help").stdout
    assert "grace_minutes" in help_text and "0 to 10080" in help_text
    at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    for bad in (True, False, 10081, -1, 1.5, "120"):
        refused = s.run("schedule", "--id", "post-1", "--at", at, "--command-file",
                        str(s.command_file(grace_minutes=bad)), "--dry-run")
        assert refused.returncode == 2 and "grace_minutes" in refused.stderr, bad
    for good in (0, 10080):
        shown = s.run("schedule", "--id", "post-1", "--at", at, "--command-file",
                      str(s.command_file(grace_minutes=good)), "--dry-run")
        assert shown.returncode == 0 and json.loads(shown.stdout)["job"]["grace_minutes"] == good, shown.stderr


def test_a_time_without_an_offset_is_refused(s):
    # The help says "with offset", but a naive --at was read as the machine's local time.
    naive = (datetime.now(timezone.utc) + timedelta(hours=20)).replace(tzinfo=None, microsecond=0).isoformat()
    refused = s.run("schedule", "--id", "post-1", "--at", naive, "--command-file", str(s.command_file()), "--dry-run")
    assert refused.returncode == 2 and "offset" in refused.stderr
    for aware in (naive + "+00:00", naive + "Z", naive + "-03:00"):
        shown = s.run("schedule", "--id", "post-1", "--at", aware, "--command-file", str(s.command_file()),
                      "--dry-run")
        assert shown.returncode == 0, (aware, shown.stderr)


# --- SC11: every change to a scheduled job is made under its lock -----------------------------


def lock_held(folder: Path) -> bool:
    """Whether some open file description holds run.lock (flock conflicts across descriptions, in one process too)."""
    fd = os.open(folder / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def watch_writes(s, module, monkeypatch) -> list:
    """Record, for every write of job.json, the status written and whether run.lock was held."""
    seen, original = [], module.write_job

    def write_job(job):
        seen.append((job["status"], lock_held(s.folder(job["id"]))))
        original(job)

    monkeypatch.setattr(module, "write_job", write_job)
    return seen


def test_a_one_shot_run_records_its_outcome_under_the_lock(s, monkeypatch):
    # The runner released run.lock before it wrote the outcome, so a cancel or resolve that found the lock free
    # could read "running" and write over the outcome the runner was about to record.
    assert s.schedule(s.command_file())[0].returncode == 0
    module = s.module(monkeypatch)
    seen = watch_writes(s, module, monkeypatch)
    assert module.main(["run", "--id", "post-1"]) == 0
    assert seen == [("running", True), ("done", True)]
    assert not lock_held(s.folder())


def test_a_missed_or_refused_one_shot_is_recorded_under_the_lock(s, monkeypatch):
    assert s.schedule(s.command_file(grace_minutes=0))[0].returncode == 0
    s.set_job(at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())
    module = s.module(monkeypatch)
    seen = watch_writes(s, module, monkeypatch)
    assert module.main(["run", "--id", "post-1"]) == 1
    assert seen == [("missed", True)]


def test_cancel_and_resolve_write_under_the_lock(s, monkeypatch):
    assert s.schedule(s.command_file())[0].returncode == 0
    module = s.module(monkeypatch)
    seen = watch_writes(s, module, monkeypatch)
    assert module.main(["cancel", "--id", "post-1", "--confirmed"]) == 0
    assert seen == [("cancelled", True)]
    assert s.schedule(s.command_file(), job_id="post-2")[0].returncode == 0
    s.set_job("post-2", status="running", started_at="2026-10-01T09:00:00Z")
    seen.clear()
    assert module.main(["resolve", "--id", "post-2", "--failed", "--confirmed"]) == 0
    assert seen == [("failed", True)]
    assert s.schedule(s.command_file(), job_id="post-3")[0].returncode == 0
    s.set_job("post-3", status="running", started_at="2026-10-01T09:00:00Z")
    seen.clear()
    assert module.main(["cancel", "--id", "post-3", "--confirmed"]) == 0
    assert seen == [("cancelled", True)] and s.job("post-3")["interrupted"] is True


def test_cancel_does_not_write_over_a_runner_that_still_holds_the_job(s, monkeypatch):
    # cancel wrote "cancelled" without the lock: a runner that had just taken the job went on to run the command
    # of a job recorded as cancelled, then wrote its own outcome over it.
    assert s.schedule(s.command_file())[0].returncode == 0
    module = s.module(monkeypatch)
    module.CANCEL_WAIT_SECONDS = 0.3
    lock = os.open(s.folder() / "run.lock", os.O_RDWR | os.O_CREAT, 0o600)  # a runner that will not let go
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert module.main(["cancel", "--id", "post-1", "--confirmed"]) == 1
        assert s.job()["status"] == "scheduled"  # nothing written while the runner holds the job
        assert "bootout" in s.calls.read_text() or "stop" in s.calls.read_text()  # but it was stopped
    finally:
        os.close(lock)
    assert module.main(["cancel", "--id", "post-1", "--confirmed"]) == 0
    assert s.job()["status"] == "cancelled"


# --- SC3: a command that outlived its runner ------------------------------------------------


def schedule_every(s, path: Path, job_id="tick"):
    base = ["schedule", "--id", job_id, "--every", "15", "--command-file", str(path)]
    dry = s.run(*base, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    return s.run(*base, "--confirmed", "--approved", json.loads(dry.stdout)["approved"])


def firings(s, job_id="tick") -> list:
    return [json.loads(line) for line in (s.folder(job_id) / "runs.jsonl").read_text().splitlines()]


def test_a_firing_records_its_commands_process_group_while_it_runs(s):
    seen = s.tmp / "seen.txt"
    code = (f"import os; open({str(seen)!r}, 'w').write("
            f"open({str(s.folder('tick') / 'run.group')!r}).read().strip() + ' ' + str(os.getpgrp()))")
    assert schedule_every(s, s.command_file(code)).returncode == 0
    assert s.run("run", "--id", "tick").returncode == 0, firings(s)
    recorded, actual = seen.read_text().split()
    assert recorded == actual  # the command's own process group, beside run.lock
    assert not (s.folder("tick") / "run.group").exists()  # and gone once the command ended
    assert firings(s)[-1]["status"] == "done"


def test_a_command_that_outlived_its_runner_is_not_overlapped(s):
    # The command runs in its own session. When its runner dies (SIGKILL after the service's stop timeout, a
    # crash), the kernel drops run.lock but the command goes on: the next firing took the free lock, recorded
    # stale_lock_pid and started the command again next to the old one.
    marker = s.tmp / "ran.txt"
    assert schedule_every(s, s.command_file(f"open({str(marker)!r}, 'a').write('x')")).returncode == 0
    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        (s.folder("tick") / "run.group").write_text(f"{orphan.pid}\n")  # what a runner that died mid-firing leaves
        fired = s.run("run", "--id", "tick")
        assert fired.returncode == 0, fired.stderr
        assert not marker.exists()
        record = firings(s)[-1]
        assert record["status"] == "skipped-overlap" and f"process group {orphan.pid}" in record["reason"]
        assert s.job("tick")["status"] == "scheduled"  # the job keeps firing
    finally:
        orphan.kill()
        orphan.wait()
    assert s.run("run", "--id", "tick").returncode == 0  # the group is gone: the next firing runs
    assert marker.read_text() == "x" and firings(s)[-1]["status"] == "done"
    assert not (s.folder("tick") / "run.group").exists()


# --- SC14: files that grow are bounded --------------------------------------------------------

MIB = 1024 * 1024


def test_a_one_shot_commands_output_is_kept_up_to_a_mebibyte(s, monkeypatch):
    # run.stdout.log and run.stderr.log held whatever the command printed, however much.
    code = ("import sys; sys.stdout.write('a' * (3 * 1024 * 1024 // 2) + 'END'); "
            "sys.stderr.write('e' * (2 * 1024 * 1024) + 'LAST')")
    assert s.schedule(s.command_file(code))[0].returncode == 0
    assert s.run("run", "--id", "post-1").returncode == 0
    for name, end in (("run.stdout.log", b"END"), ("run.stderr.log", b"LAST")):
        path = s.folder() / name
        data = path.read_bytes()
        assert data.endswith(end) and data.startswith(b"[") and b"cut" in data.split(b"\n", 1)[0], name
        assert MIB < len(data) <= MIB + 200, name
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    small = s.command_file("print('short')")
    assert s.schedule(small, job_id="post-2")[0].returncode == 0
    assert s.run("run", "--id", "post-2").returncode == 0
    assert (s.folder("post-2") / "run.stdout.log").read_bytes() == b"short\n"  # under the bound: as it was
    assert s.module(monkeypatch).OUTPUT_MAX_BYTES == MIB


def test_the_service_logs_are_cut_to_their_last_mebibyte_at_each_run(s):
    # launchd.err.log and systemd.err.log (and .out.log) are appended to by the service and were never pruned.
    marker = s.tmp / "ran.txt"
    assert schedule_every(s, s.command_file(f"open({str(marker)!r}, 'a').write('x')")).returncode == 0
    for kind in ("out", "err"):
        path = s.folder("tick") / f"{s.name}.{kind}.log"
        with path.open("ab") as fh:  # as the service writes it: appended
            fh.write(b"old line\n" * (300 * 1024) + b"TAIL\n")
    assert s.run("run", "--id", "tick").returncode == 0
    for kind in ("out", "err"):
        path = s.folder("tick") / f"{s.name}.{kind}.log"
        data = path.read_bytes()
        assert data.endswith(b"TAIL\n") and b"cut" in data.split(b"\n", 1)[0]
        assert len(data) <= MIB + 200
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert marker.read_text() == "x"


def test_notifications_are_kept_up_to_a_mebibyte(s):
    if s.name != "systemd":
        pytest.skip("launchd.py notifies through the desktop and writes no notifications file")
    s.env["SCHEDULER_NOTIFY"] = "1"
    path = Path(s.env["SCHEDULER_HOME"]) / "notifications.jsonl"
    assert s.schedule(s.command_file())[0].returncode == 0
    old = json.dumps({"at": "2026-01-01T00:00:00Z", "title": "old", "message": "x" * 200}) + "\n"
    path.write_text(old * (6 * 1024))  # about 1.4 MiB of earlier outcomes
    assert s.run("run", "--id", "post-1").returncode == 0
    data = path.read_bytes()
    assert len(data) <= MIB
    lines = [json.loads(line) for line in data.decode().splitlines()]  # whole lines only
    assert lines[-1]["title"] == "openhora: post-1 done" and lines[0]["title"] == "old"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_history_keeps_the_newest_hundred_folders(s):
    # Every id scheduled again moved its finished folder to .history/, which was never pruned.
    history = Path(s.env["SCHEDULER_HOME"]) / ".history"
    history.mkdir(parents=True, mode=0o700)
    for n in range(102):
        folder = history / f"old-{n:03d}"
        (folder / "files").mkdir(parents=True)
        (folder / "files" / "post.txt").write_text("x")
        (folder / "files" / "post.txt").chmod(0o400)
        os.utime(folder, (1_700_000_000 + n, 1_700_000_000 + n))
    path = s.command_file()
    assert s.schedule(path)[0].returncode == 0
    assert s.run("run", "--id", "post-1").returncode == 0
    again, _ = s.schedule(path)  # moves the finished job to .history/
    assert again.returncode == 0, again.stderr
    kept = sorted(p.name for p in history.iterdir())
    assert len(kept) == 100
    assert "old-000" not in kept and "old-001" not in kept and "old-002" not in kept and "old-003" in kept
    assert any(name.startswith("post-1-") for name in kept)  # the folder just archived is kept
    assert stat.S_IMODE(history.stat().st_mode) == 0o700
