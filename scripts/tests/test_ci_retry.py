"""Tests of scripts/ci_retry.py, the bounded retry of the CI steps that build an image from the Debian snapshot archive. Offline:
the commands are small shell scripts, the waits are recorded instead of slept, and a planted failure stands in for the archive's
transient errors (a counter file makes the first attempts fail and a later one pass).

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_ci_retry.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ci_retry.py"
_spec = importlib.util.spec_from_file_location("ci_retry", SCRIPT)
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)


def flaky(tmp_path, failures, code=100):
    """A command that fails with `code` on its first `failures` runs and passes after them, counting its runs in a file."""
    count = tmp_path / "count"
    count.write_text("0")
    body = f'n=$(cat "{count}"); n=$((n+1)); echo $n > "{count}"; echo "run $n"; [ $n -gt {failures} ] || exit {code}'
    return ["sh", "-c", body], count  # security-scan: allow shell-string -- the test's own fixed script, with a temp path only


def run(argv, slept=None):
    return cr.main(argv, sleep=(slept.append if slept is not None else lambda s: None))


def test_a_command_that_passes_runs_once_and_says_nothing(tmp_path, capsys):
    command, count = flaky(tmp_path, 0)
    assert run(["--attempts", "3", "--", *command]) == 0
    assert count.read_text().strip() == "1"
    assert "::" not in capsys.readouterr().err


def test_a_transient_failure_is_retried_with_a_warning_and_the_step_passes(tmp_path, capsys):
    command, count = flaky(tmp_path, 2)
    slept = []
    assert run(["--attempts", "3", "--delay", "30", "--", *command], slept) == 0
    assert count.read_text().strip() == "3"
    assert slept == [30, 60]  # the wait doubles
    err = capsys.readouterr().err
    assert "::warning::ci_retry: attempt 1 of 3 failed (exit 100); attempt 2 in 30 s" in err
    assert "::warning::ci_retry: attempt 2 of 3 failed (exit 100); attempt 3 in 60 s" in err
    assert "::warning::ci_retry: passed on attempt 3 of 3" in err


def test_a_failure_on_every_attempt_fails_with_the_commands_own_code_and_an_error(tmp_path, capsys):
    command, count = flaky(tmp_path, 99, code=7)
    assert run(["--attempts", "3", "--delay", "0", "--", *command]) == 7
    assert count.read_text().strip() == "3"  # bounded: never more than --attempts
    assert "::error::ci_retry: failed on every one of 3 attempts (last exit 7)" in capsys.readouterr().err


def test_the_wait_never_exceeds_the_maximum():
    assert cr.waits(6, 60, 300) == [60, 120, 240, 300, 300]
    assert cr.waits(1, 60, 300) == []


def test_an_attempt_past_its_timeout_is_stopped_with_what_it_started_and_counts_as_failed(tmp_path):
    marker = tmp_path / "child-alive"
    # the shell starts a child that would write the marker after 3 s; stopping the group must stop it too
    command = ["sh", "-c", f'(sleep 3; touch "{marker}") & sleep 30']  # security-scan: allow shell-string -- fixed text and a temp path
    started = time.monotonic()
    assert run(["--attempts", "2", "--delay", "0", "--attempt-timeout", "0.5", "--", *command]) == cr.EXIT_TIMEOUT
    assert time.monotonic() - started < 20
    time.sleep(3.5)
    assert not marker.exists()


def test_a_program_that_cannot_start_is_not_retried(tmp_path, capsys):
    slept = []
    assert run(["--attempts", "3", "--", str(tmp_path / "no-such-program")], slept) == cr.EXIT_NOT_FOUND
    assert slept == []
    assert "::error::ci_retry: cannot start the command" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--attempts", "0", "--", "true"], ["--", ], ["--attempts", "2", "true"],
                                  ["--delay", "-1", "--", "true"], ["--attempt-timeout", "0", "--", "true"]])
def test_a_bad_option_exits_2(argv):
    with pytest.raises(SystemExit) as e:
        run(argv)
    assert e.value.code == cr.EXIT_USAGE


def test_the_script_runs_from_the_command_line_and_has_help(tmp_path):
    command, count = flaky(tmp_path, 1)
    done = subprocess.run([sys.executable, str(SCRIPT), "--attempts", "2", "--delay", "0", "--", *command],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "run 1" in done.stdout and "run 2" in done.stdout  # the command's output is passed through, not captured
    assert "::warning::ci_retry: passed on attempt 2 of 2" in done.stderr
    shown = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert shown.returncode == 0 and "Usage:" in shown.stdout
