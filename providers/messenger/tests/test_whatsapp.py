"""Offline tests for providers/messenger/whatsapp.py: no network, no WhatsApp, no Go toolchain, no real number.

The Go commands are replaced (subprocess is patched) or a stand-in program is built from a shell script; the program's own
behaviour is tested by `go test ./...` in providers/messenger/whatsapp/. Every test points OPENHORA_STATE_DIR at a
temporary folder. Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp.py
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROVIDERS = Path(__file__).resolve().parents[2]
SCRIPT = PROVIDERS / "messenger" / "whatsapp.py"
GO_SOURCE = PROVIDERS / "messenger" / "whatsapp"


def load(name="messenger_whatsapp_under_test"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wa = load()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A state folder in a temporary place, a copy of the Go sources the test may change, and a clean Go environment."""
    state = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    sources = tmp_path / "go-sources"
    shutil.copytree(GO_SOURCE, sources, ignore=shutil.ignore_patterns("*_test.go"))
    monkeypatch.setattr(wa, "GO_DIR", str(sources))
    old = os.umask(0o077)
    yield state
    os.umask(old)


def install_program(state, body="#!/bin/sh\nexit 0\n", sources=None):
    """A stand-in program in the place `build` puts the real one, with a build record that matches it."""
    own = state / "whatsapp"
    os.makedirs(own / "bin", mode=0o700, exist_ok=True)
    program = own / "bin" / "whatsapp-bridge"
    program.write_text(body)
    program.chmod(0o700)
    wa.record_build(str(own), str(program), "go version go-test", sources)
    return program


def terminal(monkeypatch):
    """Make the captured standard output look like a terminal (whoami writes only to one)."""
    monkeypatch.setattr(type(sys.stdout), "isatty", lambda self: True)


def run_main(argv, capsys):
    code = wa.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


# --- capabilities and the interface ---------------------------------------------------------------------------------------


def test_capabilities_are_the_documented_ones_and_fit_what_the_bridge_checks(capsys):
    code, out, _ = run_main(["capabilities", "--platform", "whatsapp"], capsys)
    caps = json.loads(out)
    assert code == 0 and caps == {"max_text": 4096, "buttons": False, "max_buttons": 0, "max_button_label": 0, "lists": False,
                                  "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": True, "listen": True}
    types = {"max_text": int, "buttons": bool, "max_buttons": int, "max_button_label": int, "lists": bool, "max_list_rows": int,
             "url_buttons": bool, "reply_context": bool, "documents": bool, "listen": bool}
    assert {k: type(v) for k, v in caps.items()} == types


def test_the_platform_line_is_the_one_the_resolver_reads_as_text():
    text = SCRIPT.read_text()
    assert re.search(r'^PLATFORMS = \("whatsapp",\)$', text, re.M)
    assert re.search(r"^# dependencies = \[\]$", text, re.M) and re.search(r'^# requires-python = ">=3\.9"$', text, re.M)
    spec = importlib.util.spec_from_file_location("providers_resolve_for_whatsapp_test", PROVIDERS / "resolve.py")
    resolve = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = resolve
    spec.loader.exec_module(resolve)
    assert "whatsapp" in " ".join(str(x) for x in resolve.implementations("messenger:whatsapp"))
    assert resolve.interpreter_for(str(SCRIPT)) == [sys.executable]   # no dependency: the caller's interpreter, not uv


@pytest.mark.parametrize("verb", ["receive", "send", "ack"])
def test_the_one_shot_verbs_exit_2(verb, capsys):
    code, out, err = run_main([verb, "--platform", "whatsapp"], capsys)
    assert code == 2 and out == "" and "works only in listen mode" in err


def test_a_platform_other_than_whatsapp_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        wa.main(["status", "--platform", "telegram"])
    assert e.value.code == 2


# --- the state folder -----------------------------------------------------------------------------------------------------


def runtime_ledger():
    """The bridge's own rule, loaded from its file by parts so that this suite does not import the runtime as a package."""
    path = Path(*PROVIDERS.parent.parts, "runtime", "messaging" + "_ledger.py")
    spec = importlib.util.spec_from_file_location("ledger_for_whatsapp_parity", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("env", [
    {"OPENHORA_STATE_DIR": "{tmp}/chosen"},
    {"OPENHORA_STATE_DIR": "{tmp}/rel/../chosen"},
    {"XDG_STATE_HOME": "{tmp}/xdg"},
    {"XDG_STATE_HOME": "relative/xdg"},
    {"OPENHORA_STATE_DIR": "{tmp}/first", "XDG_STATE_HOME": "{tmp}/xdg"},
    {},
])
def test_the_state_folder_rule_is_the_bridges_rule(tmp_path, monkeypatch, env):
    for name in ("OPENHORA_STATE_DIR", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value.format(tmp=tmp_path))
    ledger = runtime_ledger()
    assert wa.state_dir() == ledger.state_dir()
    assert ledger.STATE_ENV == wa.STATE_ENV and ledger.LOCK == wa.LOCK


def test_the_folders_are_made_0700_and_checked_like_the_state_folder(home):
    state, own, bin_folder = wa.folders()
    for path in (state, own, bin_folder):
        assert stat.S_IMODE(os.lstat(path).st_mode) == 0o700
    assert (state, own, bin_folder) == (str(home), str(home / "whatsapp"), str(home / "whatsapp" / "bin"))


def test_a_folder_open_to_others_or_a_link_is_refused(home):
    wa.folders()
    os.chmod(home / "whatsapp", 0o750)
    with pytest.raises(wa.Refusal) as e:
        wa.folders()
    assert e.value.kind == "not-configured" and "chmod 700" in e.value.reason
    os.chmod(home / "whatsapp", 0o700)
    shutil.rmtree(home / "whatsapp" / "bin")
    elsewhere = home.parent / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    os.symlink(elsewhere, home / "whatsapp" / "bin")
    with pytest.raises(wa.Refusal) as e:
        wa.folders()
    assert "not a real directory" in e.value.reason
    os.chmod(home, 0o755)
    with pytest.raises(wa.Refusal):
        wa.folders()


def test_main_sets_umask_077(home, capsys):
    os.umask(0o022)
    wa.main(["capabilities"])
    assert os.umask(0o077) == 0o077


# --- build ----------------------------------------------------------------------------------------------------------------


class FakeGo:
    """Replaces subprocess.run for the Go commands and records each call."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, argv, cwd=None, env=None, capture_output=None, text=None, timeout=None, check=None):
        self.calls.append({"argv": argv, "cwd": cwd, "env": dict(env or {}), "timeout": timeout})
        verb = argv[1]
        if self.fail == verb:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=f"{verb} went wrong")
        if verb == "version":
            return subprocess.CompletedProcess(argv, 0, stdout="go version go1.27.1 darwin/arm64\n", stderr="")
        if verb == "build":
            Path(argv[argv.index("-o") + 1]).write_bytes(b"\x7fELF-not-really\n")
        return subprocess.CompletedProcess(argv, 0, stdout="all modules verified\n", stderr="")


POLLUTED = {"GOSUMDB": "off", "GONOSUMDB": "*", "GONOSUMCHECK": "1", "GOPRIVATE": "*", "GONOPROXY": "*", "GOINSECURE": "*",
            "GOFLAGS": "-mod=mod -insecure", "GOENV": "/tmp/evil.env", "GOWORK": "/tmp/evil.work", "CGO_ENABLED": "1",
            "GOTOOLCHAIN": "auto", "GOPROXY": "https://proxy.golang.org,direct"}


def test_build_runs_the_checked_commands_with_the_environment_that_keeps_go_sum_in_force(home, monkeypatch, capsys):
    for name, value in POLLUTED.items():
        monkeypatch.setenv(name, value)
    fake = FakeGo()
    monkeypatch.setattr(wa.shutil, "which", lambda name: "/opt/go/bin/go")
    monkeypatch.setattr(wa.subprocess, "run", fake)
    code, out, err = run_main(["build"], capsys)
    assert code == 0, err
    assert [c["argv"][:2] for c in fake.calls] == [["/opt/go/bin/go", "version"], ["/opt/go/bin/go", "mod"], ["/opt/go/bin/go", "build"]]
    assert fake.calls[1]["argv"] == ["/opt/go/bin/go", "mod", "verify"]
    build = fake.calls[2]["argv"]
    assert build[2:7] == ["-trimpath", "-buildvcs=false", "-mod=readonly", "-o", build[6]]
    assert build[-1] == "." and build[6].startswith(str(home / "whatsapp" / "bin" / "whatsapp-bridge"))
    for call in fake.calls:
        env = call["env"]
        assert call["cwd"] == wa.GO_DIR
        for removed in ("GOSUMDB", "GONOSUMDB", "GONOSUMCHECK", "GOPRIVATE", "GONOPROXY", "GOINSECURE"):
            assert removed not in env
        assert env["GOFLAGS"] == "-mod=readonly" and env["GOENV"] == "off" and env["GOWORK"] == "off" and env["CGO_ENABLED"] == "0"
        assert env["GOTOOLCHAIN"] == "auto"   # left to the person's environment and Go's default rule
    # the real environment of this process was not changed
    assert os.environ["GOSUMDB"] == "off"
    assert "Go: go version go1.27.1" in out


def test_build_writes_the_program_0700_and_the_record_0600_with_the_hashes(home, monkeypatch, capsys):
    monkeypatch.setattr(wa.shutil, "which", lambda name: "/opt/go/bin/go")
    monkeypatch.setattr(wa.subprocess, "run", FakeGo())
    code, out, _ = run_main(["build"], capsys)
    program, record = home / "whatsapp" / "bin" / "whatsapp-bridge", home / "whatsapp" / "build.json"
    assert code == 0 and str(program) in out
    assert stat.S_IMODE(program.stat().st_mode) == 0o700 and stat.S_IMODE(record.stat().st_mode) == 0o600
    recorded = json.loads(record.read_text())
    assert recorded["binary_sha256"] == wa.sha256_file(str(program))
    assert recorded["go_sum_sha256"] == wa.sha256_file(str(Path(wa.GO_DIR) / "go.sum"))
    assert recorded["sources_sha256"] == wa.sources_digest(wa.GO_DIR)
    assert recorded["go_version"] == "go version go1.27.1 darwin/arm64" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", recorded["built"])
    assert not [p for p in program.parent.iterdir() if ".tmp-" in p.name]
    # the build it made is the one listen accepts
    assert wa.check_build()[0] == str(program)


@pytest.mark.parametrize("failing,code", [("version", 1), ("mod", 1), ("build", 1)])
def test_a_failed_go_command_installs_nothing(home, monkeypatch, capsys, failing, code):
    monkeypatch.setattr(wa.shutil, "which", lambda name: "/opt/go/bin/go")
    monkeypatch.setattr(wa.subprocess, "run", FakeGo(fail=failing))
    got, _, err = run_main(["build"], capsys)
    assert got == code and f"{failing} went wrong" in err
    assert not (home / "whatsapp" / "build.json").exists() and not (home / "whatsapp" / "bin" / "whatsapp-bridge").exists()
    assert not [p for p in (home / "whatsapp" / "bin").iterdir()]


def test_build_without_go_exits_3_and_says_what_to_install(home, monkeypatch, capsys):
    monkeypatch.setattr(wa.shutil, "which", lambda name: None)
    code, _, err = run_main(["build"], capsys)
    assert code == 3 and "Install Go" in err


def test_go_environment_never_mutates_its_input():
    base = {"PATH": "/bin", "GOSUMDB": "off"}
    out = wa.go_environment(base)
    assert base == {"PATH": "/bin", "GOSUMDB": "off"} and "GOSUMDB" not in out and out["PATH"] == "/bin"


# --- the build record and listen's refusals --------------------------------------------------------------------------------


def lines(out):
    return [json.loads(x) for x in out.splitlines()]


def test_listen_refuses_when_the_program_is_missing(home, capsys):
    code, out, _ = run_main(["listen", "--platform", "whatsapp"], capsys)
    event = lines(out)
    assert code == 3 and len(event) == 1 and event[0]["event"] == "error" and event[0]["kind"] == "not-configured"
    assert "build" in event[0]["reason"]


def test_listen_refuses_a_program_whose_hash_differs_from_the_record(home, capsys):
    program = install_program(home)
    program.write_text("#!/bin/sh\necho tampered\n")
    program.chmod(0o700)
    code, out, _ = run_main(["listen"], capsys)
    event = lines(out)[0]
    assert code == 3 and event["kind"] == "not-configured" and "differs from what was built" in event["reason"] and "build" in event["reason"]


def test_listen_refuses_a_stale_build_after_go_sum_or_a_source_changed(home, capsys):
    install_program(home)
    assert wa.check_build()
    sums = Path(wa.GO_DIR) / "go.sum"
    original = sums.read_text()
    sums.write_text(original + "example.invalid/module v0.0.0 h1:AAAA=\n")
    code, out, _ = run_main(["listen"], capsys)
    event = lines(out)[0]
    assert code == 3 and event["kind"] == "not-configured" and "older than its sources" in event["reason"]
    sums.write_text(original)
    assert wa.check_build()
    (Path(wa.GO_DIR) / "main.go").write_text((Path(wa.GO_DIR) / "main.go").read_text() + "\n// changed\n")
    code, out, _ = run_main(["listen"], capsys)
    assert code == 3 and "older than its sources" in lines(out)[0]["reason"]


def test_a_test_file_is_not_part_of_the_build(home):
    install_program(home)
    (Path(wa.GO_DIR) / "extra_test.go").write_text("package main\n")
    assert wa.check_build()


def test_a_missing_or_garbled_record_is_not_configured(home, capsys):
    install_program(home)
    record = home / "whatsapp" / "build.json"
    for bad in ("", "[]", '{"binary_sha256": 1}', "not json"):
        record.write_text(bad)
        code, out, _ = run_main(["listen"], capsys)
        assert code == 3 and lines(out)[0]["kind"] == "not-configured", bad
    record.unlink()
    assert run_main(["listen"], capsys)[0] == 3


def test_a_program_open_to_others_or_not_executable_is_refused(home, capsys):
    program = install_program(home)
    os.chmod(program, 0o770)
    assert run_main(["listen"], capsys)[0] == 3
    os.chmod(program, 0o600)
    assert run_main(["listen"], capsys)[0] == 3


STATUS_PROGRAM = """#!/bin/sh
case "$1" in
  status) echo 'STATUS_JSON'; exit STATUS_CODE ;;
  listen) echo '{"event": "ready"}'; echo "$$" >&2; exec cat ;;
esac
"""


def status_program(paired=True, status="", code=0):
    answer = status or json.dumps({"paired": paired, "phone": "5511900000000" if paired else None})
    return STATUS_PROGRAM.replace("STATUS_JSON", answer).replace("STATUS_CODE", str(code))


def test_listen_without_a_session_file_is_paused_and_names_the_pair_command(home, capsys):
    install_program(home, "#!/bin/sh\nexit 0\n")
    code, out, _ = run_main(["listen", "--platform", "whatsapp"], capsys)
    event = lines(out)
    assert code == 3 and len(event) == 1 and event[0]["kind"] == "paused" and "pair --phone" in event[0]["reason"]


def test_listen_with_an_unpaired_session_is_paused(home, capsys):
    install_program(home, status_program(paired=False))
    (home / "whatsapp" / "session.db").write_bytes(b"")
    code, out, _ = run_main(["listen"], capsys)
    event = lines(out)
    assert code == 3 and event[0]["kind"] == "paused" and "pair --phone" in event[0]["reason"]


def test_listen_when_status_cannot_be_read_is_failed_and_exits_1(home, capsys):
    install_program(home, status_program(status="not json"))
    (home / "whatsapp" / "session.db").write_bytes(b"")
    code, out, _ = run_main(["listen"], capsys)
    assert code == 1 and lines(out)[0]["kind"] == "failed"
    install_program(home, status_program(paired=True, code=1))
    code, out, _ = run_main(["listen"], capsys)
    assert code == 1 and lines(out)[0]["kind"] == "failed"


def test_listen_replaces_itself_with_the_program_after_resetting_sigpipe(home, monkeypatch, capsys):
    program = install_program(home, status_program(paired=True))
    (home / "whatsapp" / "session.db").write_bytes(b"")
    seen = {}
    monkeypatch.setattr(wa.os, "execv", lambda path, argv: seen.update(path=path, argv=argv) or (_ for _ in ()).throw(SystemExit(0)))
    recorded = []
    monkeypatch.setattr(wa.signal, "signal", lambda sig, handler: recorded.append((sig, handler)))
    with pytest.raises(SystemExit):
        wa.main(["listen", "--platform", "whatsapp"])
    assert seen["path"] == str(program)
    assert seen["argv"] == [str(program), "listen", "--session", str(home / "whatsapp" / "session.db"), "--platform", "whatsapp"]
    assert recorded == [(signal.SIGPIPE, signal.SIG_DFL)]


def test_listen_really_becomes_the_program_with_the_bridges_pipes(home, tmp_path):
    """A real process: python whatsapp.py listen is replaced by the stand-in (same pid), which speaks on stdout and ends at
    the end of stdin."""
    install_program(home, status_program(paired=True))
    (home / "whatsapp" / "session.db").write_bytes(b"")
    env = dict(os.environ, OPENHORA_STATE_DIR=str(home))
    proc = subprocess.Popen([sys.executable, str(SCRIPT), "listen", "--platform", "whatsapp"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(tmp_path))
    try:
        first = proc.stdout.readline()
        assert json.loads(first) == {"event": "ready"}
        proc.stdin.write(b'{"id": 1}\n')
        proc.stdin.flush()
        assert proc.stdout.readline() == b'{"id": 1}\n'   # `cat` echoes: stdin and stdout reach the program directly
        proc.stdin.close()
        assert proc.wait(timeout=5) == 0
        assert proc.stderr.read().decode().strip() == str(proc.pid)   # the same process: the program is the leader
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_the_check_refuses_when_the_sources_folder_cannot_be_read(home):
    install_program(home)
    with pytest.raises(wa.Refusal):
        wa.check_build(str(home / "no-such-folder"))


# --- pair, status, whoami --------------------------------------------------------------------------------------------------


class Called:
    def __init__(self, code=0):
        self.argv, self.code = None, code

    def __call__(self, argv, **kw):
        self.argv = argv
        return self.code


def test_pair_passes_the_session_and_the_phone_and_returns_the_programs_code(home, monkeypatch, capsys):
    program = install_program(home)
    call = Called(code=0)
    monkeypatch.setattr(wa.subprocess, "call", call)
    code, _, _ = run_main(["pair", "--phone", "5511900000000"], capsys)
    assert code == 0 and call.argv == [str(program), "pair", "--session", str(home / "whatsapp" / "session.db"), "--phone", "5511900000000"]
    call.code = 2
    assert run_main(["pair", "--phone", "5511900000000"], capsys)[0] == 2


@pytest.mark.parametrize("phone", ["+5511900000000", "0123456789", "123", "55 11 9", "abcdefgh", "5511900000000000", "5511900000000;ls"])
def test_pair_refuses_a_phone_that_is_not_digits_with_the_country_code(home, monkeypatch, capsys, phone):
    install_program(home)
    call = Called()
    monkeypatch.setattr(wa.subprocess, "call", call)
    code, _, err = run_main(["pair", "--phone", phone], capsys)
    assert code == 2 and call.argv is None and "country code" in err


def test_pair_status_and_whoami_need_a_current_build(home, monkeypatch, capsys):
    terminal(monkeypatch)
    call = Called()
    monkeypatch.setattr(wa.subprocess, "call", call)
    for argv in (["pair", "--phone", "5511900000000"], ["status"], ["whoami"]):
        code, out, err = run_main(argv, capsys)
        assert code == 3 and out == "" and "build" in err and call.argv is None


def test_status_runs_the_programs_status_with_the_session(home, monkeypatch, capsys):
    program = install_program(home)
    call = Called(code=0)
    monkeypatch.setattr(wa.subprocess, "call", call)
    assert run_main(["status", "--platform", "whatsapp"], capsys)[0] == 0
    assert call.argv == [str(program), "status", "--session", str(home / "whatsapp" / "session.db")]


def test_whoami_passes_the_seconds_and_holds_the_platform_lock_while_it_runs(home, monkeypatch, capsys):
    terminal(monkeypatch)
    program = install_program(home)
    held = {}

    def call(argv, **kw):
        held["argv"] = argv
        fd = os.open(home / "messaging-whatsapp.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # a bridge starting now would be refused
        finally:
            os.close(fd)
        return 0
    monkeypatch.setattr(wa.subprocess, "call", call)
    assert run_main(["whoami", "--seconds", "30"], capsys)[0] == 0
    assert held["argv"] == [str(program), "whoami", "--session", str(home / "whatsapp" / "session.db"), "--seconds", "30"]
    fd = os.open(home / "messaging-whatsapp.lock", os.O_RDWR)   # released afterwards
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)
    held.clear()
    run_main(["whoami"], capsys)
    assert held["argv"][-2:] == ["--seconds", "120"]


def test_whoami_refuses_while_a_bridge_holds_the_lock(home, monkeypatch, capsys):
    terminal(monkeypatch)
    install_program(home)
    call = Called()
    monkeypatch.setattr(wa.subprocess, "call", call)
    fd = os.open(home / "messaging-whatsapp.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code, out, err = run_main(["whoami"], capsys)
    finally:
        os.close(fd)
    assert code == 2 and out == "" and call.argv is None and "stop it first" in err and "messaging-whatsapp.lock" in err


@pytest.mark.parametrize("seconds", ["0", "601", "-5"])
def test_whoami_seconds_are_bounded(home, monkeypatch, capsys, seconds):
    terminal(monkeypatch)
    install_program(home)
    call = Called()
    monkeypatch.setattr(wa.subprocess, "call", call)
    code, _, err = run_main(["whoami", "--seconds", seconds], capsys)
    assert code == 2 and call.argv is None and "1 to 600" in err


# --- the Go module as committed ---------------------------------------------------------------------------------------------


def test_the_go_module_pins_exact_versions_and_has_no_replace_or_cgo():
    mod = (GO_SOURCE / "go.mod").read_text()
    assert re.search(r"^go 1\.\d+\.\d+$", mod, re.M) and re.search(r"^toolchain go1\.\d+\.\d+$", mod, re.M)
    assert re.search(r"go\.mau\.fi/whatsmeow v0\.0\.0-\d{14}-[0-9a-f]{12}$", mod, re.M)
    assert re.search(r"modernc\.org/sqlite v\d+\.\d+\.\d+$", mod, re.M)
    assert not re.search(r"^\s*(replace|exclude|retract)\b", mod, re.M)
    sums = (GO_SOURCE / "go.sum").read_text()
    for name in ("go.mau.fi/whatsmeow", "modernc.org/sqlite"):
        assert re.search(rf"^{re.escape(name)} \S+ h1:", sums, re.M), name
    for source in GO_SOURCE.glob("*.go"):
        text = source.read_text()
        assert 'import "C"' not in text and "waLog.Stdout" not in text, source.name
        assert "mattn/go-sqlite3" not in text, source.name   # cgo driver


def test_the_provider_script_never_names_a_go_sum_bypass():
    text = SCRIPT.read_text()
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    # the names appear only in the list of what is removed and in the documentation
    assert 'GO_ENV_REMOVED = ("GOSUMDB", "GONOSUMDB", "GONOSUMCHECK", "GOPRIVATE", "GONOPROXY", "GOINSECURE", "GOFLAGS")' in code
    assert "-insecure" not in text and "GOFLAGS=-mod=mod" not in text


def test_whoami_refuses_when_its_output_is_not_a_terminal(home, monkeypatch, capsys):
    install_program(home)
    call = Called()
    monkeypatch.setattr(wa.subprocess, "call", call)
    code, out, err = run_main(["whoami"], capsys)   # captured output is not a terminal
    assert code == 2 and out == "" and call.argv is None and "terminal" in err


def test_build_refuses_to_record_when_the_sources_changed_while_it_ran(home, monkeypatch, capsys):
    monkeypatch.setattr(wa.shutil, "which", lambda name: "/opt/go/bin/go")
    fake = FakeGo()

    def touching(argv, **kw):
        done = fake(argv, **kw)
        if argv[1] == "build":
            main = Path(wa.GO_DIR) / "main.go"
            main.write_text(main.read_text() + "\n// changed during the build\n")
        return done
    monkeypatch.setattr(wa.subprocess, "run", touching)
    code, _, err = run_main(["build"], capsys)
    assert code == 1 and "changed while Go was building" in err
    assert not (home / "whatsapp" / "build.json").exists() and not (home / "whatsapp" / "bin" / "whatsapp-bridge").exists()
    assert not list((home / "whatsapp" / "bin").iterdir())


def test_the_phone_shape_is_the_go_programs_shape():
    go = (GO_SOURCE / "send.go").read_text()
    shape = re.search(r"phonePattern\s*= `\^(.+)\$`", go).group(1)
    assert wa.PHONE.pattern == shape
