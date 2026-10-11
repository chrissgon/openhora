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

import standin_tree as st
from test_service import Standin

messaging = st.load("messaging")
ops = st.load("ops")


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


class Stand(Standin):
    def config(self, project):
        return self.answers["config"]


def test_a_project_without_senders_for_the_platform_exits_2_naming_the_key_and_an_unaccepted_one_exits_3(tmp_path, capsys):
    folder = tmp_path / "project"
    folder.mkdir()
    for config, code, words in (({"messaging": {"senders": {}}}, 2, "messaging.senders.telegram"),
                                ({"messaging": {"senders": {"telegram": []}}}, 2, "messaging.senders.telegram"),
                                ({}, 2, "messaging.senders.telegram"),
                                ({"accepted": False}, 3, "accept-config")):
        fake = Stand(tmp_path / "data")
        fake.answers["config"] = {"path": "x", "sha256": "a" * 64, "accepted": True, "data_dir": str(tmp_path / "data"), **config}
        assert messaging.serve([str(folder)], "telegram", ops_module=fake, messenger=Quiet(), out=open(tmp_path / "out", "w")) == code
        assert words in capsys.readouterr().err
        assert (tmp_path / "out").read_text() == ""


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
                        "messaging": {{"senders": {{"telegram": ["4242"]}}}}}}
            def pending(self, project, pending_id=None):
                return {{"pending": []}}
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
        assert "4242" not in first and "token" not in first.lower()
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert code == 0 and marker.read_text() == "stopped"
    assert b"4242" not in proc.stderr.read()
