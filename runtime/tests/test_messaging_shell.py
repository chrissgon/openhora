"""The messaging bridge's shell (runtime/messaging.py): its command line and exit codes, the start line, the check of the
senders, and the stop on SIGTERM (the runs it started are ended). Offline: a stand-in operations module and a stand-in
messenger in a driver process.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_shell.py
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import standin_tree as st
from test_service import Standin

messaging = st.load("messaging")
ops = st.load("ops")
ledgers = st.load("messaging_ledger")
operations = st.load("operations")


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    """No test reaches the real state folder (the lock and the ledger live there); a subprocess inherits the variable."""
    folder = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(folder))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return folder


def run(*argv):
    return subprocess.run([sys.executable, str(st.RUNTIME / "messaging.py"), *argv], input=b"", capture_output=True, timeout=60)


def test_help_and_the_usage_errors_and_an_unconfigured_project(tmp_path):
    helped = run("--help")
    assert helped.returncode == 0 and b"Usage:" in helped.stdout and helped.stderr == b""
    none = run()
    assert none.returncode == 2 and none.stdout == b"" and b"Usage:" in none.stderr
    for argv in (("--project", str(tmp_path)), ("--platform", "telegram"), ("--platform",), ("--port", "1"),
                 ("--project", str(tmp_path), "--platform", "telegram", "--notice-every", "1"),
                 ("--project", str(tmp_path), "--platform", "telegram", "--notice-every", "soon")):
        refused = run(*argv)
        assert refused.returncode == 2 and refused.stdout == b"" and b"error:" in refused.stderr, argv
    nothing = run("--project", str(tmp_path / "nothing"), "--platform", "telegram")
    assert nothing.returncode == 3 and nothing.stdout == b"" and b"error:" in nothing.stderr


class Quiet:
    def capabilities(self):
        return {"max_text": 4096}

    def receive(self, offset, timeout):
        time.sleep(0.05)
        return {"updates": [], "next_offset": offset}


class Stand(Standin):
    def config(self, project):
        return self.answers["config"]


def test_a_project_without_senders_or_not_accepted_is_skipped_and_the_bridge_keeps_running(tmp_path, capsys):
    """MSG-3a: this was exit 2 (no sender) and exit 3 (not accepted) in MSG-1; now the project is skipped with one line and
    looked at again every notice period, and the bridge stops only when asked."""
    folder = tmp_path / "project"
    folder.mkdir()
    for config, words in (({"messaging": {"senders": {}}}, "messaging.senders.telegram"),
                          ({"messaging": {"senders": {"telegram": []}}}, "messaging.senders.telegram"),
                          ({}, "messaging.senders.telegram"),
                          ({"accepted": False}, "accept-config")):
        fake = Stand(tmp_path / "data")
        fake.answers["config"] = {"path": "x", "sha256": "a" * 64, "accepted": True, "data_dir": str(tmp_path / "data"), **config}
        fake.answers["pending"] = {"pending": []}
        stop, result = threading.Event(), {}
        thread = threading.Thread(target=lambda: result.update(code=messaging.serve(
            [str(folder)], "telegram", notice_every=0.1, ops_module=fake, messenger=Quiet(), stop=stop, poll=1,
            out=open(tmp_path / "out", "w"))))
        thread.start()
        time.sleep(0.6)
        assert thread.is_alive() and "code" not in result, "it keeps running"
        stop.set()
        thread.join(30)
        assert result["code"] == 0
        err = capsys.readouterr().err
        assert words in err and err.count("skipping") == 1, err
        assert (tmp_path / "out").read_text() == "" or "skipping" not in (tmp_path / "out").read_text()


def test_a_stop_signal_that_lands_outside_the_loop_still_ends_with_code_zero(tmp_path, monkeypatch):
    # The signal handler raises Stop in the main thread wherever it is. Right after the start line it can land before
    # serve's own try (a slow machine, a signal sent as soon as the line is read): that was a traceback and exit code 1.
    def stopped(*args, **kwargs):
        raise messaging.Stop()

    monkeypatch.setattr(messaging, "serve", stopped)
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        assert messaging.main(["--project", str(tmp_path), "--platform", "telegram"]) == 0
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def test_a_stop_signal_right_after_the_start_line_still_ends_the_runs(tmp_path):
    # The driver of the SIGTERM test below signals as soon as it has read the start line; on a slow machine the handler
    # then ran before the loop's try, and the runs were never ended (the marker was missing). The line is printed inside
    # the try, so the Stop it meets there ends the runs like any other.
    ended = []

    class Ops:
        OpsError = type("OpsError", (Exception,), {"code": 1})
        operations = operations

        def config(self, project):
            return {"path": project, "sha256": "a" * 64, "accepted": True, "data_dir": str(tmp_path / "data"),
                    "messaging": {"senders": {"telegram": ["830461975213"]}}}

        def stop_runs(self):
            ended.append(1)
            return {}

    class Messenger:
        def capabilities(self):
            return {"max_text": 4096, "buttons": True, "max_buttons": 6}

    class Out:
        def write(self, text):
            raise messaging.Stop()  # the signal arrives as the start line is written

        def flush(self):
            pass

    folder = tmp_path / "project"
    folder.mkdir()
    code = messaging.serve([str(folder)], "telegram", 5, ops_module=Ops(), messenger=Messenger(), out=Out(),
                           state_dir=ledgers.prepare_state_dir())
    assert code == 0 and ended, (code, ended)


def test_sigterm_stops_the_loop_and_ends_the_runs(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    marker = tmp_path / "stopped"
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f'''
        import sys, time
        sys.path.insert(0, {str(st.RUNTIME)!r})
        import messaging, operations

        class Fake:
            OpsError = type("OpsError", (Exception,), {{"code": 1}})
            operations = operations
            def config(self, project):
                return {{"path": project, "sha256": "a" * 64, "accepted": True, "data_dir": {str(tmp_path / "data")!r},
                        "messaging": {{"senders": {{"telegram": ["830461975213"]}}}}}}
            def pending(self, project, pending_id=None):
                return {{"pending": []}}
            def reminders_due(self, project, platform):
                return {{"send": [], "missed": 0, "dropped": 0}}
            def stop_runs(self):
                open({str(marker)!r}, "w").write("stopped")
                return {{}}

        class Messenger:
            def capabilities(self):
                return {{"max_text": 4096, "buttons": True, "max_buttons": 6}}
            def receive(self, offset, timeout):
                time.sleep(0.2)
                return {{"updates": [], "next_offset": offset}}

        messaging.ops = Fake()
        messaging.providers.Messenger = lambda platform: Messenger()
        sys.exit(messaging.main(["--project", {str(folder)!r}, "--platform", "telegram", "--notice-every", "5"]))
    '''), encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(driver)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        first = proc.stdout.readline().decode("utf-8")
        started = json.loads(first)
        assert started["platform"] == "telegram" and [list(p) for p in started["projects"]] == [["id", "name"]]
        assert "830461975213" not in first and "token" not in first.lower()
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    err = proc.stderr.read()
    assert code == 0 and marker.read_text() == "stopped", (code, err)
    assert b"830461975213" not in err
