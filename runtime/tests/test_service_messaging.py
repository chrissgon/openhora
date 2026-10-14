"""`service.py --messaging <platform>` (MSG-3a): the bridge as a child process of the local service. Offline: a stand-in
script plays the bridge (named through the keyword parameter `bridge_argv` of service.serve, which only tests pass),
the operations object is the tests' stand-in, and nothing reaches the real state folder or any network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_service_messaging.py
"""
from __future__ import annotations

import io
import json
import os
import signal
import sys
import textwrap
import threading
import time

import pytest

import standin_tree as st
from test_service import STATUS, WAIT, FakeServer, Standin, run_serve

service = st.load("service")
service_bridge = st.load("service_bridge")

# What the stand-in bridge does, by BRIDGE_MODE: it writes what it was started with to BRIDGE_RECORD, then
#   wait    stays until its standard input ends or SIGTERM arrives, then exits 0 (the real bridge's two stops)
#   exit4   exits 4 at once (another bridge serves the platform)
#   group   starts a `sleep` in its own group, ignores the end of its input and waits for SIGTERM's default (death)
#   ignore  ignores SIGTERM and the end of its input, and never exits by itself
STAND_IN = textwrap.dedent('''
    import json, os, signal, stat, subprocess, sys, time
    mode = os.environ["BRIDGE_MODE"]
    stopped = []
    if mode == "wait":  # before the record exists, so a stop sent as soon as a test sees the record finds the handler
        signal.signal(signal.SIGTERM, lambda *a: stopped.append(1))
    if mode == "ignore":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    record = {"argv": sys.argv[1:], "executable": sys.executable, "pid": os.getpid(), "sid": os.getsid(0),
              "pgid": os.getpgrp(), "ppid": os.getppid(),
              "stdout_is_null": os.fstat(1).st_rdev == os.stat(os.devnull).st_rdev and stat.S_ISCHR(os.fstat(1).st_mode),
              "stdin_is_pipe": stat.S_ISFIFO(os.fstat(0).st_mode),
              "env": {k: v for k, v in os.environ.items() if k.startswith(("SNAP_", "LATE_", "BRIDGE_"))}}
    if mode == "group":
        record["grandchild"] = subprocess.Popen(["sleep", "60"]).pid
    with open(os.environ["BRIDGE_RECORD"] + ".tmp", "w") as f:
        json.dump(record, f)
    os.rename(os.environ["BRIDGE_RECORD"] + ".tmp", os.environ["BRIDGE_RECORD"])
    if mode == "exit4":
        print("error: another messaging bridge already serves telegram on this machine", file=sys.stderr)
        sys.exit(4)
    if mode == "ignore":
        while True:
            time.sleep(1)
    if mode == "group":
        while True:
            time.sleep(1)
    while not stopped:  # stops from its SIGTERM handler only, so the exit is always 0 (the end of its input is ignored)
        time.sleep(0.02)
    sys.exit(0)
''')


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))  # no test reaches the real state folder


@pytest.fixture
def world(tmp_path):
    class W:
        pass
    w = W()
    w.tmp = tmp_path
    w.script = tmp_path / "stand_in_bridge.py"
    w.script.write_text(STAND_IN, encoding="utf-8")
    w.record = tmp_path / "record.json"
    w.projects = []
    for name in ("alpha", "beta"):
        (tmp_path / name).mkdir()
        w.projects.append(str(tmp_path / name))
    w.fake = Standin(tmp_path / "data")
    w.fake.answers["status"] = STATUS
    w.environment = lambda mode: {**os.environ, "BRIDGE_MODE": mode, "BRIDGE_RECORD": str(w.record), "SNAP_KEY": "snapshot"}
    w.program = [sys.executable, str(w.script)]
    return w


def started(world):
    end = time.monotonic() + WAIT
    while time.monotonic() < end:
        if world.record.exists():
            return json.loads(world.record.read_text())
        time.sleep(0.02)
    raise AssertionError("the stand-in bridge did not start")


def gone(pid):
    end = time.monotonic() + WAIT
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.05)
    return False


def listing(run):
    svc = run.service
    headers = {"Host": "127.0.0.1:4321", "Authorization": f"Bearer {svc.token}", "Origin": "http://127.0.0.1:4321"}
    status, _, payload = service.handle(svc, "GET", "/api/v1/projects", headers, b"")
    assert status == 200
    return json.loads(payload)


def serve(world, mode, **kwargs):
    return run_serve(world.fake, world.projects, FakeServer, messaging="telegram", environment=world.environment(mode),
                     bridge_argv=world.program, **kwargs)


def test_without_the_option_no_child_starts_and_the_field_is_null(world):
    run = run_serve(world.fake, world.projects, FakeServer)
    try:
        assert listing(run)["messaging"] is None and run.service.bridge is None
        assert set(json.loads(run.out.getvalue())) == {"url", "token_file", "projects"}
    finally:
        assert run.finish() == 0
    assert not world.record.exists()


def test_the_child_is_started_with_every_project_the_platform_and_the_flag_in_its_own_session(world):
    run = serve(world, "wait", notice_every=7)
    try:
        record = started(world)
        assert record["argv"] == ["--project", world.projects[0], "--project", world.projects[1], "--platform", "telegram",
                                  "--stop-on-stdin-eof", "--notice-every", "7"]
        assert record["sid"] == record["pid"] == record["pgid"] != os.getsid(0), "its own session and group"
        assert record["stdout_is_null"] and record["stdin_is_pipe"]
        assert record["env"]["SNAP_KEY"] == "snapshot"
        printed = json.loads(run.out.getvalue())
        assert printed["messaging"] == "telegram" and list(printed)[-1] == "messaging"
        assert listing(run)["messaging"] == {"platform": "telegram", "state": "running", "exit_code": None}
        assert listing(run)["projects"], "the projects are still listed beside the field"
    finally:
        assert run.finish() == 0
    assert gone(record["pid"])


def test_the_real_command_uses_the_same_interpreter_and_the_bridge_script_without_notice_every():
    argv = service_bridge.command("telegram", ["/p/a"])
    assert argv[0] == sys.executable and argv[1] == str(st.RUNTIME / "messaging.py")
    assert argv[2:] == ["--project", "/p/a", "--platform", "telegram", "--stop-on-stdin-eof"]
    assert "--notice-every" not in argv


def test_the_child_gets_the_snapshot_and_a_variable_set_after_it_is_absent(world, monkeypatch):
    snapshot = world.environment("wait")
    monkeypatch.setenv("LATE_KEY", "written by a run in progress")  # after the snapshot was taken
    run = run_serve(world.fake, world.projects, FakeServer, messaging="telegram", environment=snapshot, bridge_argv=world.program)
    try:
        record = started(world)
        assert "LATE_KEY" not in record["env"] and record["env"]["SNAP_KEY"] == "snapshot"
        assert "LATE_KEY" not in {k for k in snapshot}
    finally:
        assert run.finish() == 0


def test_main_takes_the_snapshot_first_and_hands_it_over_only_with_the_option(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(service, "serve", lambda projects, port, poll_every, dispatch_every, token_file, **extra: seen.append(extra) or 0)
    monkeypatch.setenv("SNAP_KEY", "before")
    assert service.main(["--project", str(tmp_path)]) == 0 and seen == [{}], "without the option the call is the old one"
    assert service.main(["--project", str(tmp_path), "--messaging", "telegram", "--notice-every", "9"]) == 0
    extra = seen[-1]
    assert extra["messaging"] == "telegram" and extra["notice_every"] == 9
    assert extra["environment"] is not os.environ and extra["environment"]["SNAP_KEY"] == "before"
    monkeypatch.setenv("LATE_KEY", "x")
    assert "LATE_KEY" not in extra["environment"]
    assert service.main(["--project", str(tmp_path), "--messaging", "telegram"]) == 0 and "notice_every" not in seen[-1]


def test_the_options_are_checked(tmp_path):
    parsed = service.parse(["--project", "a", "--messaging", "telegram", "--notice-every", "30"])
    assert parsed["messaging"] == "telegram" and parsed["notice_every"] == 30
    assert "messaging" not in service.parse(["--project", "a"]) and "notice_every" not in service.parse(["--project", "a"])
    for argv in (["--messaging", "telegram"], ["--project", "a", "--messaging"], ["--project", "a", "--messaging", "../x"],
                 ["--project", "a", "--messaging", "Telegram"], ["--project", "a", "--notice-every", "30"],
                 ["--project", "a", "--messaging", "telegram", "--notice-every", "1"],
                 ["--project", "a", "--messaging", "telegram", "--notice-every", "soon"]):
        with pytest.raises(service.Refused):
            service.parse(argv)


def test_when_the_child_exits_4_the_service_keeps_serving_logs_the_line_and_reports_stopped(world):
    run = serve(world, "exit4")
    try:
        started(world)
        end = time.monotonic() + WAIT
        while time.monotonic() < end and listing(run)["messaging"]["state"] != "stopped":
            time.sleep(0.05)
        assert listing(run)["messaging"] == {"platform": "telegram", "state": "stopped", "exit_code": 4}
        lines = [line for line in run.logs if "messaging bridge" in line]
        assert len(lines) == 1 and "code 4" in lines[0] and "another bridge serves this platform" in lines[0]
        assert listing(run)["projects"] and run.thread.is_alive(), "the page is still served"
    finally:
        assert run.finish() == 0


def test_every_exit_code_is_named(world):
    assert "another bridge serves this platform" in service_bridge.describe(4)
    assert "messenger is not configured" in service_bridge.describe(3) and "another program reads this bot" in service_bridge.describe(3)
    assert "usage" in service_bridge.describe(2)
    assert "SIGKILL" in service_bridge.describe(-signal.SIGKILL) and "SIGTERM" in service_bridge.describe(-signal.SIGTERM)
    assert "failed" in service_bridge.describe(1)


def test_a_child_that_cannot_be_started_is_logged_and_the_service_goes_on(world):
    run = run_serve(world.fake, world.projects, FakeServer, messaging="telegram", environment={},
                    bridge_argv=[str(world.tmp / "no-such-interpreter")])
    try:
        assert listing(run)["messaging"]["state"] == "stopped" and listing(run)["messaging"]["exit_code"] == -1
        assert any("could not be started" in line for line in run.logs)
    finally:
        assert run.finish() == 0


def test_the_stop_ends_the_childs_whole_group_with_sigterm_and_leaves_none_behind(world):
    run = serve(world, "group")
    record = started(world)
    assert run.finish() == 0
    assert gone(record["pid"]) and gone(record["grandchild"]), "SIGTERM went to the group, not only to the child"
    assert not [line for line in run.logs if "did not stop" in line]


def test_the_childs_stop_starts_before_the_services_runs_are_ended(world):
    run = serve(world, "wait")
    record = started(world)
    world.fake.stop_release.clear()  # ops.stop_runs will take a while
    run.stop.set()
    assert world.fake.stop_entered.wait(WAIT)
    assert gone(record["pid"]), "the child was stopped (its input closed, SIGTERM to its group) while the runs were still ending"
    assert run.thread.is_alive()
    world.fake.stop_release.set()
    run.thread.join(WAIT * 3)
    assert run.code == 0


def test_a_child_that_ignores_sigterm_is_killed_after_the_bound_and_the_line_is_written(world):
    run = serve(world, "ignore", bridge_stop_wait=0.6)
    record = started(world)
    began = time.monotonic()
    assert run.finish() == 0
    assert time.monotonic() - began >= 0.5, "it waited for the bound"
    assert gone(record["pid"])
    [line] = [line for line in run.logs if "did not stop" in line]
    assert "killed" in line and "unknown" in line and "stop-runs --all" in line


def test_a_child_that_exits_during_its_stop_is_not_reported_as_a_surprise(world):
    run = serve(world, "wait")
    started(world)
    assert run.finish() == 0
    [line] = [line for line in run.logs if "messaging bridge" in line and "exited" in line]
    # The stand-in stops from its SIGTERM handler alone, so the exit is deterministic. (The real bridge also stops on the
    # end of its input; when both arrive together it can show -15, harmless: `stopping` is set, so the line omits
    # "not restarted".)
    assert "code 0" in line and "not restarted" not in line


def test_a_sigterm_to_the_service_stops_the_child(world):
    """The real handler: serve() runs in the test's main thread, where it installs the handlers, and a timer sends
    the service's own process a SIGTERM once the child is up."""
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("the signal handlers are installed in the main thread only")
    outcome = {}

    def later():
        outcome["record"] = started(world)
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Thread(target=later, daemon=True)
    timer.start()
    code = service.serve(world.projects, port=0, poll_every=0, ops_module=world.fake, server_class=FakeServer,
                         out=io.StringIO(), log=lambda line: None, messaging="telegram",
                         environment=world.environment("group"), bridge_argv=world.program)
    timer.join(WAIT)
    assert code == 0
    assert gone(outcome["record"]["pid"]) and gone(outcome["record"]["grandchild"])


def test_the_state_of_a_stopped_child_never_reads_as_running(world):
    run = serve(world, "wait")
    try:
        started(world)
        child = run.service.bridge
        assert child.state()["state"] == "running"
        child.begin_stop()
        end = time.monotonic() + WAIT
        while time.monotonic() < end and child.state()["state"] != "stopped":
            time.sleep(0.05)
        assert child.state() == {"platform": "telegram", "state": "stopped", "exit_code": 0}
    finally:
        assert run.finish() == 0


def test_the_childs_stop_is_by_group_id_and_never_by_a_name():
    """The child's stop is by group id only: the module has no call that matches processes by a name or a pattern."""
    source = (st.RUNTIME / "service_bridge.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    for banned in ("pkill", "killall", "pgrep", "os.kill(", "psutil"):
        assert banned not in code.split('"""', 2)[2], banned


# MSG-13: several platforms from one service

def records_of(world, count):
    """Several children: each stand-in writes rec-<platform>.json; wait until `count` of them exist and read them."""
    end = time.monotonic() + WAIT
    found = {}
    while time.monotonic() < end and len(found) < count:
        for path in world.tmp.glob("rec-*.json"):
            found[path.name] = json.loads(path.read_text())
        time.sleep(0.02)
    assert len(found) == count, found
    return found


@pytest.fixture
def many(world):
    """The stand-in with its record named by platform (rec-<platform>.json) and per-platform behaviour by BRIDGE_MODE_<platform>."""
    script = '''
import json, os, signal, subprocess, sys, time
platform = sys.argv[sys.argv.index("--platform") + 1]
mode = os.environ.get("BRIDGE_MODE_" + platform.upper().replace("-", "_"), "wait")
stopped = []
if mode == "wait":
    signal.signal(signal.SIGTERM, lambda *a: stopped.append(1))
if mode == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
rec = {"argv": sys.argv[1:], "pid": os.getpid(), "sid": os.getsid(0), "pgid": os.getpgrp(), "mode": mode}
path = os.environ["BRIDGE_DIR"] + "/rec-" + platform + ".json"
with open(path + ".tmp", "w") as f:
    json.dump(rec, f)
os.rename(path + ".tmp", path)
if mode == "exit3":
    print("error: not configured", file=sys.stderr)
    sys.exit(3)
if mode == "ignore":
    while True:
        time.sleep(1)
while not stopped:
    time.sleep(0.02)
sys.exit(0)
'''
    world.script.write_text(script, encoding="utf-8")
    world.environment = lambda **modes: {**os.environ, "BRIDGE_DIR": str(world.tmp), **{"BRIDGE_MODE_" + k.upper().replace("-", "_"): v for k, v in modes.items()}}
    return world


def serve_set(world, platforms, modes=None, **kwargs):
    return run_serve(world.fake, world.projects, FakeServer, messaging=platforms, environment=world.environment(**(modes or {})),
                     bridge_argv=world.program, **kwargs)


def test_parse_takes_a_comma_list_or_a_repeated_option_in_order_and_one_platform_keeps_its_shape():
    base = ["--project", "a"]
    assert service.parse(base + ["--messaging", "telegram"])["messaging"] == "telegram"
    assert service.parse(base + ["--messaging", "telegram,whatsapp-twilio"])["messaging"] == ["telegram", "whatsapp-twilio"]
    assert service.parse(base + ["--messaging", "telegram", "--messaging", "whatsapp-twilio,signal"])["messaging"] == \
        ["telegram", "whatsapp-twilio", "signal"]
    assert service.parse(base + ["--messaging", ",".join(f"p{i}" for i in range(6))])["messaging"] == [f"p{i}" for i in range(6)]


@pytest.mark.parametrize("argv", [
    ["--messaging", "telegram,telegram"],
    ["--messaging", "telegram", "--messaging", "telegram"],
    ["--messaging", "telegram,"],
    ["--messaging", ",telegram"],
    ["--messaging", "telegram,,signal"],
    ["--messaging", "telegram,Signal"],
    ["--messaging", "telegram,../x"],
    ["--messaging", "a,b,c,d,e,f,g"],
    ["--messaging", "a", "--messaging", "b,c,d", "--messaging", "e,f,g"],
])
def test_a_duplicate_a_malformed_name_or_more_than_six_is_refused(argv):
    with pytest.raises(service.Refused):
        service.parse(["--project", "a"] + argv)


def test_main_exits_2_for_those_refusals(tmp_path, capsys):
    for value in ("telegram,telegram", "a,b,c,d,e,f,g", "telegram,Bad"):
        assert service.main(["--project", str(tmp_path), "--messaging", value]) == 2
    assert "error:" in capsys.readouterr().err


def test_main_hands_the_list_over_when_several(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(service, "serve", lambda projects, port, poll_every, dispatch_every, token_file, **extra: seen.append(extra) or 0)
    assert service.main(["--project", str(tmp_path), "--messaging", "telegram,whatsapp-twilio", "--notice-every", "9"]) == 0
    assert seen[-1]["messaging"] == ["telegram", "whatsapp-twilio"] and seen[-1]["notice_every"] == 9


@pytest.mark.parametrize("platforms", [["telegram", "whatsapp-twilio"], ["telegram", "whatsapp-twilio", "signal"]])
def test_several_platforms_start_one_child_each_with_its_arguments_in_its_own_session(many, platforms):
    run = serve_set(many, platforms, notice_every=7)
    try:
        found = records_of(many, len(platforms))
        sessions = set()
        for platform in platforms:
            record = found[f"rec-{platform}.json"]
            assert record["argv"] == ["--project", many.projects[0], "--project", many.projects[1], "--platform", platform,
                                      "--stop-on-stdin-eof", "--notice-every", "7"]
            assert record["sid"] == record["pid"] == record["pgid"] != os.getsid(0)
            sessions.add(record["sid"])
        assert len(sessions) == len(platforms), "each child has its own session"
        assert json.loads(run.out.getvalue())["messaging"] == platforms
        assert listing(run)["messaging"] == [{"platform": p, "state": "running", "exit_code": None} for p in platforms]
        assert listing(run)["projects"]
    finally:
        assert run.finish() == 0
    for record in found.values():
        assert gone(record["pid"])


def test_one_platform_in_a_list_of_one_keeps_the_object_shape(many):
    run = serve_set(many, ["telegram"])
    try:
        records_of(many, 1)
        assert listing(run)["messaging"] == {"platform": "telegram", "state": "running", "exit_code": None}
        assert json.loads(run.out.getvalue())["messaging"] == ["telegram"]
    finally:
        assert run.finish() == 0


def test_one_child_exiting_3_leaves_the_others_running_and_is_named(many):
    run = serve_set(many, ["telegram", "whatsapp-twilio", "signal"], {"whatsapp-twilio": "exit3"})
    try:
        records_of(many, 3)
        end = time.monotonic() + WAIT
        while time.monotonic() < end and listing(run)["messaging"][1]["state"] != "stopped":
            time.sleep(0.05)
        states = listing(run)["messaging"]
        assert states == [{"platform": "telegram", "state": "running", "exit_code": None},
                          {"platform": "whatsapp-twilio", "state": "stopped", "exit_code": 3},
                          {"platform": "signal", "state": "running", "exit_code": None}]
        [line] = [line for line in run.logs if "exited" in line]
        assert "(whatsapp-twilio)" in line and "code 3" in line
        assert run.thread.is_alive()
    finally:
        assert run.finish() == 0


def test_the_stop_ends_all_children_within_one_bound_and_kills_only_the_stubborn(many):
    bound = 1.0
    run = serve_set(many, ["telegram", "whatsapp-twilio", "signal"], {"telegram": "ignore", "signal": "ignore"}, bridge_stop_wait=bound)
    found = records_of(many, 3)
    began = time.monotonic()
    assert run.finish() == 0
    took = time.monotonic() - began
    assert bound - 0.2 <= took < 2 * bound, f"one bound for both stubborn children together, not {bound} s each ({took:.2f} s)"
    for record in found.values():
        assert gone(record["pid"])
    killed = [line for line in run.logs if "did not stop" in line]
    assert len(killed) == 2 and any("(telegram)" in line for line in killed) and any("(signal)" in line for line in killed)
    assert not any("(whatsapp-twilio)" in line for line in killed), "the child that stops on SIGTERM is not killed"


def test_every_child_is_signalled_before_the_first_is_waited_for(many):
    run = serve_set(many, ["telegram", "whatsapp-twilio"], {"telegram": "ignore"}, bridge_stop_wait=1.5)
    found = records_of(many, 2)
    world = many
    world.fake.stop_release.clear()
    run.stop.set()
    assert world.fake.stop_entered.wait(WAIT)
    assert gone(found["rec-whatsapp-twilio.json"]["pid"]), "the second child was stopped while runs were still ending, though the first ignores SIGTERM"
    world.fake.stop_release.set()
    run.thread.join(WAIT * 3)
    assert run.code == 0 and gone(found["rec-telegram.json"]["pid"])


def test_a_child_that_cannot_be_started_is_named_and_the_others_still_start(many):
    run = run_serve(many.fake, many.projects, FakeServer, messaging=["telegram", "signal"], environment=many.environment(),
                    bridge_argv=[str(many.tmp / "no-such-interpreter")])
    try:
        assert [s["state"] for s in listing(run)["messaging"]] == ["stopped", "stopped"]
        assert [s["exit_code"] for s in listing(run)["messaging"]] == [-1, -1]
        assert any("(telegram)" in line and "could not be started" in line for line in run.logs)
        assert any("(signal)" in line and "could not be started" in line for line in run.logs)
    finally:
        assert run.finish() == 0
