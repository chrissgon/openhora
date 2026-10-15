"""Tests of the host side of the project-script runner (providers/script/container.py): the exact `docker run` command of a script, of the
egress proxy and of the dependency build (a golden list for each, and the properties that matter, one by one: no environment variable
of this process, no mount but the script, no mount at all in the build, a network that is `none` or the step's internal one), the
frames and the folders they are written to, and the orchestration (the network of a step, the proxy, the clean-up, the cached build)
against a fake container tool. Offline: no docker, no network.

Run: uv run --with pytest==9.1.1 pytest providers/script/tests/test_script_host.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location("script_container_under_test", HERE.parent / "container.py")
host = importlib.util.module_from_spec(spec)
sys.modules["script_container_under_test"] = host
spec.loader.exec_module(host)
box = host.box

IMAGE = "sha256:" + "1" * 64
DEPS = "sha256:" + "2" * 64
STEP_ID = "0123456789abcdef"
RUN = f"openhora-script-run-{STEP_ID}"
NET = f"openhora-script-in-{STEP_ID}"
OUT = f"openhora-script-out-{STEP_ID}"
LOCK = "requests==2.32.3 --hash=sha256:" + "a" * 64 + "\n"
LOCK_SHA = hashlib.sha256(LOCK.encode()).hexdigest()


def option(command, name, nth=0):
    return [command[i + 1] for i, w in enumerate(command) if w == name][nth]


def values(command, name):
    return [command[i + 1] for i, w in enumerate(command) if w == name]


# --- the command of a script ---------------------------------------------------------------------------------------------------------


def test_the_command_of_a_script_with_no_network_is_the_helpers_limits_and_one_read_only_mount():
    got = host.run_command(RUN, IMAGE, "py", "/work/in/script", deadline=1760000000, platform="darwin")
    assert got == [
        "docker", "run", "--rm", "--init", "--pull", "never", "--name", RUN, "--label", "org.openhora.script=1", "--label",
        "org.openhora.script.deadline=1760000000", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt",
        "no-new-privileges", "--pids-limit", "128", "--memory", "1024m", "--memory-swap", "1024m", "--cpus", "1",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m", "--tmpfs", "/scratch:rw,noexec,nosuid,nodev,size=128m,mode=1777",
        "-v", "/work/in/script:/in/script:ro", "--log-opt", "max-size=1m", "--log-opt", "max-file=1", IMAGE,
        "python3", "-I", "/opt/script/_inner.py", "run", "--kind", "py"]


def test_on_linux_the_command_runs_as_the_callers_user_like_every_other_job():
    got = host.run_command(RUN, IMAGE, "sh", "/work/in/script", deadline=5, platform="linux")
    assert option(got, "--user") == f"{os.getuid()}:{os.getgid()}" and got[-2:] == ["--kind", "sh"]


def test_a_script_with_destinations_joins_only_the_internal_network_of_its_step_and_gets_the_proxy_variables():
    env = {"HTTPS_PROXY": "http://egress:3128", "SCRIPT_DESTINATIONS": "a.example:443"}
    got = host.run_command(RUN, IMAGE, "py", "/work/in/script", deadline=5, network=NET, env=env, platform="darwin")
    assert option(got, "--network") == NET and got.count("--network") == 1 and "none" not in values(got, "--network")
    assert values(got, "-e") == ["HTTPS_PROXY=http://egress:3128", "SCRIPT_DESTINATIONS=a.example:443"]
    assert got[got.index(IMAGE) - 1] == "SCRIPT_DESTINATIONS=a.example:443"          # the options come before the image, the program after


@pytest.mark.parametrize("network", ["bridge", "host", "none", "container:abc", "default", "openhora-script-out-" + STEP_ID, "openhora-script-in-xyz",
                                     "openhora-script-in-" + STEP_ID + "-x", ""])
def test_a_script_cannot_be_put_on_any_network_but_the_internal_one_of_its_step(network):
    with pytest.raises(host.ProviderError) as refused:
        host.run_command(RUN, IMAGE, "py", "/work/in/script", deadline=5, network=network, platform="darwin")
    assert refused.value.word == "internal"


def test_the_kind_is_py_or_sh_and_nothing_else():
    with pytest.raises(host.ProviderError):
        host.run_command(RUN, IMAGE, "rb", "/work/in/script", deadline=5)


def test_every_command_keeps_every_limit_of_the_helper_whatever_is_added():
    commands = [host.run_command(RUN, IMAGE, "py", "/w/s", deadline=5, platform="darwin"),
                host.run_command(RUN, IMAGE, "py", "/w/s", deadline=5, network=NET, env={"HTTPS_PROXY": "http://egress:3128"}, platform="darwin"),
                host.proxy_command("openhora-script-proxy-" + STEP_ID, IMAGE, ["a.example:443"], OUT, deadline=5, lifetime=400, platform="darwin")]
    for command in commands:
        for word in ("--init", "--read-only", "--rm"):
            assert word in command, word
        assert option(command, "--pull") == "never" and option(command, "--cap-drop") == "ALL"
        assert option(command, "--security-opt") == "no-new-privileges"
        assert option(command, "--memory") == option(command, "--memory-swap") and option(command, "--pids-limit").isdigit()
        assert all(t.split(":", 1)[1].startswith("rw,noexec,nosuid,nodev") for t in values(command, "--tmpfs"))
        assert "--privileged" not in command and "--cap-add" not in command and "--device" not in command
        assert "--pid" not in command and "--ipc" not in command and "--userns" not in command and "--add-host" not in command
        assert option(command, "--label") == "org.openhora.script=1" and values(command, "--label")[1].startswith("org.openhora.script.deadline=")


def test_the_environment_of_this_process_never_enters_a_command(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "planted-" + "a1" * 10)
    monkeypatch.setenv("NOTION_TOKEN", "planted-" + "b2" * 10)
    monkeypatch.setenv("HTTPS_PROXY", "http://planted.example:1")
    commands = [host.run_command(RUN, IMAGE, "py", "/w/s", deadline=5, platform="darwin"),
                host.run_command(RUN, IMAGE, "py", "/w/s", deadline=5, network=NET, env={"HTTPS_PROXY": "http://egress:3128"}, platform="darwin"),
                host.proxy_command("p", IMAGE, ["a.example:443"], OUT, deadline=5, lifetime=400, platform="darwin"),
                host.build_command("b", IMAGE, deadline=5, network=NET, env={"HTTPS_PROXY": "http://egress:3128"}, platform="darwin")]
    for command in commands:
        text = " ".join(command)
        assert "OPENAI" not in text and "NOTION" not in text and "planted" not in text
        for i, word in enumerate(command):
            if word == "-e":
                assert "=" in command[i + 1], "a bare `-e NAME` would copy the docker client's own variable"


def test_a_variable_outside_the_list_or_with_a_control_character_is_refused():
    assert host.env_args({}) == []
    for bad in ({"OPENAI_API_KEY": "x"}, {"PATH": "/bin"}, {"HTTPS_PROXY": "a\nb"}, {"HTTPS_PROXY": 5}, {"LD_PRELOAD": "/x"}, {"HTTPS_PROXY": "x" * 2001}):
        with pytest.raises(host.ProviderError) as refused:
            host.env_args(bad)
        assert refused.value.word == "bad_environment"
    assert not any(w in n for n in host.ENV_ALLOWED for w in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "AUTH", "CRED", "PRIVATE"))


# --- the command of the proxy and of the build ---------------------------------------------------------------------------------------


def test_the_command_of_the_proxy_has_no_mount_at_all_and_the_egress_network_in_place_of_none():
    got = host.proxy_command("openhora-script-proxy-" + STEP_ID, IMAGE, ["a.example:443", "b.example:8443"], OUT, deadline=5, lifetime=420, platform="darwin")
    assert "-v" not in got and "--mount" not in got and "--volume" not in got
    assert option(got, "--network") == OUT and got.count("--network") == 1
    assert got[got.index(IMAGE):] == [IMAGE, "python3", "-I", "/opt/script/egress_proxy.py", "--listen", "0.0.0.0:3128", "--max-seconds", "420",
                                       "--allow", "a.example:443", "--allow", "b.example:8443"]
    assert "--allow-private" not in got
    assert "--allow-private" in host.proxy_command("p", IMAGE, ["a.example:443"], OUT, deadline=5, lifetime=4, allow_private=True, platform="darwin")
    assert option(got, "--memory") == "128m" and option(got, "--pids-limit") == "64"


def test_the_proxy_joins_a_network_that_is_a_plain_name_only():
    for bad in ("", "bad name", "--privileged", "a;b", "-x"):
        with pytest.raises(host.ProviderError):
            host.proxy_command("p", IMAGE, ["a.example:443"], bad, deadline=5, lifetime=4)


def test_the_build_container_carries_no_mount_and_no_volume_and_reads_the_lock_from_standard_input():
    got = host.build_command("openhora-script-build-" + STEP_ID, IMAGE, deadline=5, network=NET, env={"HTTPS_PROXY": "http://egress:3128"}, platform="darwin")
    assert "-v" not in got and "--mount" not in got and "--volume" not in got and "--volumes-from" not in got
    assert not any(":" in w and w.startswith("/") and w.split(":")[0] != "" and w.count(":") >= 1 and not w.startswith("/tmp:") and not w.startswith("/scratch:")
                   for w in got if w.startswith("/")), "no host path in the command"
    assert "-i" in got and "--rm" not in got and "--read-only" not in got            # stdin in; the file system is kept as a layer
    assert any(t.startswith("/tmp:") and t.endswith(f"size={host.BUILD_TMP_MB}m") for t in values(got, "--tmpfs")), "room for pip to unpack wheels"
    assert option(got, "--network") == NET and got[got.index(IMAGE):] == [IMAGE, "python3", "-I", "/opt/script/_inner.py", "build"]
    assert option(got, "--cap-drop") == "ALL" and option(got, "--security-opt") == "no-new-privileges" and option(got, "--pull") == "never"


def test_the_build_joins_the_internal_network_of_its_step_only():
    for bad in ("bridge", "host", "none", ""):
        with pytest.raises(host.ProviderError):
            host.build_command("b", IMAGE, deadline=5, network=bad)


def test_shape_refuses_a_command_that_has_no_network_none_to_replace():
    with pytest.raises(host.ProviderError):
        host.shape(["docker", "run", "--network", "bridge", IMAGE], [], network=NET)
    with pytest.raises(host.ProviderError):
        host.shape(["docker", "run", "--rm", IMAGE], [], network=NET)


def test_the_names_of_everything_a_run_makes_are_not_the_ones_the_eval_orphan_sweep_selects():
    spec = importlib.util.spec_from_file_location("orphans_under_test", REPO / "runtime" / "orphans.py")
    orphans = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orphans)
    names = host.names_of(STEP_ID)
    for name in names.values():
        assert name.startswith("openhora-script-") and not name.startswith("wb-eval-")
        assert orphans.run_of_name("container", name) is None and orphans.run_of_name("network", name) is None


# --- the frames and the folders ----------------------------------------------------------------------------------------------------


def frames(*files):
    out = b"OHF1\n"
    for name, data in files:
        out += b"FILE %s %d\n" % (name.encode(), len(data)) + data
    return out + b"END\n"


INFO = ("info.json", b'{"exit": 0}')


def test_frames_with_one_result_and_the_account_are_read():
    assert host.parse_frames(frames(("result.md", b"# hi\n"), INFO)) == {"result.md": b"# hi\n", "info.json": b'{"exit": 0}'}
    assert host.parse_frames(frames(INFO)) == {"info.json": b'{"exit": 0}'}


@pytest.mark.parametrize("data", [
    b"", b"nonsense", b"OHF1\n", b"OHF1\nEND\n", frames(("result.md", b"a"))[:-1], frames(("result.md", b"a"), INFO) + b"more",
    frames(("result.md", b"a"), ("result.md", b"b"), INFO), frames(("result.md", b"a"), ("result.txt", b"b"), INFO),
    frames(("other.md", b"a"), INFO), frames(("../result.md", b"a"), INFO), frames(("result.md", b"a" * (host.RESULT_CAP + 1)), INFO),
    frames(("info.json", b"x" * (host.INFO_CAP + 1))), b"OHF1\nFILE result.md 99\nshort\nEND\n", b"OHF1\nFILE result.md -1\nEND\n",
    b"OHF1\nFILE result.md 5\n12345" + b"junk"])
def test_a_stream_that_breaks_a_rule_is_refused_whole(data):
    with pytest.raises(host.ProviderError) as refused:
        host.parse_frames(data)
    assert refused.value.word == "bad_output"


def test_a_result_of_exactly_the_cap_is_read_and_the_runtime_decides_it_is_too_large():
    got = host.parse_frames(frames(("result.md", b"a" * host.RESULT_CAP), INFO))
    assert len(got["result.md"]) == 1024 * 1024 + 1


def test_the_out_folder_must_be_a_real_empty_folder_of_this_user_with_mode_0700(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    good.chmod(0o700)
    host.check_out_dir(str(good))
    for make in (lambda p: None, lambda p: (p.mkdir(), p.chmod(0o755)), lambda p: (p.mkdir(), p.chmod(0o700), (p / "x").write_text("1")),
                 lambda p: p.symlink_to(good)):
        bad = tmp_path / f"bad{len(list(tmp_path.iterdir()))}"
        make(bad)
        with pytest.raises(host.ProviderError):
            host.check_out_dir(str(bad))


def test_outputs_are_written_as_new_regular_files_of_mode_0600_and_never_over_a_link(tmp_path):
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    assert host.write_outputs(str(out), {"result.md": b"x", "info.json": b"{}"}) == ["info.json", "result.md"]
    assert oct((out / "result.md").stat().st_mode & 0o777) == "0o600" and (out / "result.md").read_bytes() == b"x"
    with pytest.raises(FileExistsError):
        host.write_outputs(str(out), {"result.md": b"y"})
    other = tmp_path / "o2"
    other.mkdir(mode=0o700)
    (other / "result.md").symlink_to(tmp_path / "target")
    with pytest.raises(OSError):
        host.write_outputs(str(other), {"result.md": b"y"})
    assert not (tmp_path / "target").exists()


def test_a_file_to_run_is_a_regular_file_of_at_most_the_cap_opened_without_following_a_link(tmp_path):
    good = tmp_path / "s.py"
    good.write_bytes(b"x" * 10)
    assert host.check_file(str(good), "--script") == b"x" * 10
    link = tmp_path / "l.py"
    link.symlink_to(good)
    big = tmp_path / "big.py"
    big.write_bytes(b"x" * (host.FILE_CAP + 1))
    for bad in (str(link), str(big), str(tmp_path), str(tmp_path / "none.py"), "relative.py", None):
        with pytest.raises(host.ProviderError) as refused:
            host.check_file(bad, "--script")
        assert refused.value.code == host.EXIT_USAGE


def test_destinations_are_checked_and_normalised_for_the_proxy_and_at_most_eight():
    assert host.check_destinations(["B.example.:443", "a.example:80", "a.example:80"]) == ["a.example:80", "b.example:443"]
    assert host.check_destinations([]) == []
    for bad in (["127.0.0.1:80"], ["api.example"], [f"h{i}.example:1" for i in range(9)], ["*.example:1"]):
        with pytest.raises(host.ProviderError):
            host.check_destinations(bad)


# --- the orchestration, against a fake container tool ----------------------------------------------------------------------------------


class Done:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


class FakeDocker:
    """Records every docker command; answers the few the runner asks."""

    def __init__(self, internal="true", images=None, fail=(), options=None):
        self.calls, self.internal, self.images, self.fail = [], internal, images or {}, set(fail)
        self.options = json.dumps(options if options is not None else {"com.docker.network.bridge.gateway_mode_ipv4": "isolated",
                                                                       "com.docker.network.enable_ipv6": "false"})

    def __call__(self, args, timeout=60):
        self.calls.append(list(args))
        verb = " ".join(args[:2])
        if verb in self.fail:
            return Done(1, "", "boom")
        if args[:2] == ["network", "inspect"]:
            return Done(0, self.internal + " " + self.options + "\n")
        if args[:2] == ["image", "inspect"]:
            fmt, tag = args[3], args[4]
            found = self.images.get(tag)
            if found is None:
                return Done(1)
            if "Labels" not in fmt:
                return Done(0, found["id"] + "\n")
            return Done(0, (found["lock"] if host.LABEL_LOCK in fmt else found.get("definition", host.definition_hash())) + "\n")
        return Done(0, "")

    def verbs(self):
        return [" ".join(c[:2]) for c in self.calls]


READY = "import sys, time\nprint('ready api.example:443=8.8.8.8', flush=True)\ntime.sleep(60)\n"
REFUSED = "print('refused not_public api.example', flush=True)\n"


def popen_of(script):
    def popen(argv, **kwargs):
        return subprocess.Popen([sys.executable, "-u", "-c", script], **kwargs)
    return popen


@pytest.fixture
def quiet(monkeypatch):
    """No real docker, no real wait: the helper's removal and reap are recorded, the docker binary is any file."""
    removed = []
    monkeypatch.setattr(box, "remove", lambda name: removed.append(name))
    monkeypatch.setattr(box, "docker_binary", lambda: sys.executable)
    monkeypatch.setattr(host, "reap_all", lambda docker=None: {"containers": [], "networks": []})
    monkeypatch.setattr(host, "new_token", lambda: STEP_ID)
    return removed


def script_file(tmp_path):
    path = tmp_path / "script"
    path.write_text("print(1)\n")
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    return str(path), str(out)


def ran(command_log):
    return lambda command, name, timeout, stdout_cap=None: (command_log.append((command, name, timeout, stdout_cap)),
                                                              box.Finished(0, "", False, frames(("result.md", b"done\n"), ("info.json", json.dumps(
                                                                  {"exit": 0, "signal": None, "duration_ms": 9, "results": ["result.md"], "refused": []}).encode()))))[1]


def test_a_script_without_destinations_runs_on_no_network_and_starts_nothing_else(tmp_path, quiet):
    script, out = script_file(tmp_path)
    log, docker = [], FakeDocker()
    done = host.run_script(script, "py", out, destinations=[], run=ran(log), docker=docker, base=IMAGE, platform="darwin")
    (command, name, timeout, cap), = log
    assert option(command, "--network") == "none" and name == RUN and timeout == host.DEFAULT_TIMEOUT and cap == host.STDOUT_CAP
    assert docker.calls == [] and done["exit"] == 0 and done["results"] == ["result.md"] and done["outputs"] == ["info.json", "result.md"]
    assert (Path(out) / "result.md").read_bytes() == b"done\n" and done["image"] == IMAGE


def test_a_script_with_destinations_gets_an_internal_network_checked_before_anything_starts_and_a_proxy_then_everything_is_removed(tmp_path, quiet):
    script, out = script_file(tmp_path)
    log, docker = [], FakeDocker()
    host.run_script(script, "py", out, destinations=["API.example:443"], run=ran(log), docker=docker, base=IMAGE, popen=None, platform="darwin") \
        if False else None
    # the proxy is a process: a stand-in that says `ready`
    egress = host.Egress
    original = host.Egress.__init__

    def init(self, *a, **k):
        k["popen"] = popen_of(READY)
        original(self, *a, **k)

    host.Egress.__init__ = init
    try:
        host.run_script(script, "py", out, destinations=["API.example:443"], run=ran(log), docker=docker, base=IMAGE, platform="darwin")
    finally:
        host.Egress.__init__ = original
    assert egress is host.Egress
    assert docker.verbs()[:2] == ["network create", "network inspect"]
    create = docker.calls[0]
    assert "--internal" in create and create[-1] == NET and "org.openhora.script=1" in create
    assert values(create, "-o") == ["com.docker.network.bridge.gateway_mode_ipv4=isolated"], "the host has no address on the step's network"
    assert docker.calls[2][:3] == ["network", "create", "--driver"] and docker.calls[2][-1] == OUT and "--internal" not in docker.calls[2]
    assert docker.calls[3] == ["network", "connect", "--alias", "egress", NET, "openhora-script-proxy-" + STEP_ID]
    (command, name, _, _), = log
    assert option(command, "--network") == NET
    env = dict(w.split("=", 1) for w in values(command, "-e"))
    assert env["HTTPS_PROXY"] == "http://egress:3128" and env["SCRIPT_DESTINATIONS"] == "api.example:443"
    assert quiet == ["openhora-script-proxy-" + STEP_ID]
    assert docker.calls[-2:] == [["network", "rm", NET], ["network", "rm", OUT]]


def test_a_network_that_is_not_internal_stops_everything_before_a_proxy_or_a_script_starts(tmp_path, quiet):
    script, out = script_file(tmp_path)
    for docker in (FakeDocker(internal="false"), FakeDocker(options={}), FakeDocker(options={"com.docker.network.bridge.gateway_mode_ipv4": "nat"}),
                   FakeDocker(options={"com.docker.network.bridge.gateway_mode_ipv4": "isolated", "com.docker.network.enable_ipv6": "true"})):
        log = []
        with pytest.raises(host.ProviderError) as refused:
            host.run_script(script, "py", out, destinations=["api.example:443"], run=ran(log), docker=docker, base=IMAGE, platform="darwin")
        assert refused.value.word == "network_not_internal" and log == []
        assert not any(v == "network connect" for v in docker.verbs()), "no proxy was started on a network that is not isolated"
    docker = FakeDocker(internal="false")
    with pytest.raises(host.ProviderError):
        host.run_script(script, "py", out, destinations=["api.example:443"], run=ran([]), docker=docker, base=IMAGE, platform="darwin")
    assert not any(v == "network connect" for v in docker.verbs()) and docker.calls[-1][:2] == ["network", "rm"]
    assert list(Path(out).iterdir()) == []


def test_a_declaration_the_proxy_refuses_ends_the_step_with_the_word_and_removes_the_networks(tmp_path, quiet, monkeypatch):
    script, out = script_file(tmp_path)
    log, docker = [], FakeDocker()
    original = host.Egress.__init__
    monkeypatch.setattr(host.Egress, "__init__", lambda self, *a, **k: original(self, *a, **{**k, "popen": popen_of(REFUSED)}))
    with pytest.raises(host.ProviderError) as refused:
        host.run_script(script, "py", out, destinations=["api.example:443"], run=ran(log), docker=docker, base=IMAGE, platform="darwin")
    assert refused.value.word == "destination_not_public" and log == []
    assert quiet == ["openhora-script-proxy-" + STEP_ID] and docker.calls[-2:] == [["network", "rm", NET], ["network", "rm", OUT]]


def test_a_proxy_that_says_nothing_is_a_failure_and_a_run_that_runs_over_its_time_is_cleaned_up(tmp_path, quiet, monkeypatch):
    script, out = script_file(tmp_path)
    docker = FakeDocker()
    original = host.Egress.__init__
    monkeypatch.setattr(host, "PROXY_START_TIMEOUT", 1)
    monkeypatch.setattr(host.Egress, "__init__", lambda self, *a, **k: original(self, *a, **{**k, "popen": popen_of("import time\ntime.sleep(30)\n")}))
    with pytest.raises(host.ProviderError) as refused:
        host.run_script(script, "py", out, destinations=["api.example:443"], run=ran([]), docker=docker, base=IMAGE, platform="darwin")
    assert refused.value.word == "proxy_failed"
    monkeypatch.setattr(host.Egress, "__init__", lambda self, *a, **k: original(self, *a, **{**k, "popen": popen_of(READY)}))

    def over(command, name, timeout, stdout_cap=None):
        raise box.ContainerError("time_limit", "container")

    docker2 = FakeDocker()
    with pytest.raises(host.ProviderError) as refused:
        host.run_script(script, "py", out, destinations=["api.example:443"], run=over, docker=docker2, base=IMAGE, platform="darwin")
    assert refused.value.word == "time_limit" and docker2.calls[-2:] == [["network", "rm", NET], ["network", "rm", OUT]]


def test_a_container_that_fails_or_prints_a_bad_stream_leaves_the_out_folder_empty(tmp_path, quiet):
    script, out = script_file(tmp_path)
    bad = lambda command, name, timeout, stdout_cap=None: box.Finished(0, "", False, b"junk")   # noqa: E731
    failed = lambda command, name, timeout, stdout_cap=None: box.Finished(7, "oom killed", False, b"")   # noqa: E731
    with pytest.raises(host.ProviderError) as refused:
        host.run_script(script, "py", out, run=bad, docker=FakeDocker(), base=IMAGE, platform="darwin")
    assert refused.value.word == "bad_output"
    with pytest.raises(host.ProviderError) as refused:
        host.run_script(script, "py", out, run=failed, docker=FakeDocker(), base=IMAGE, platform="darwin")
    assert refused.value.word == "container_failed" and "oom killed" in str(refused.value)
    assert list(Path(out).iterdir()) == []


def test_an_image_given_for_a_run_must_be_one_this_provider_built(tmp_path, quiet):
    script, out = script_file(tmp_path)
    foreign = FakeDocker(images={DEPS: {"id": DEPS, "lock": ""}})
    for image in ("ubuntu", "sha256:xyz", DEPS):
        with pytest.raises(host.ProviderError) as refused:
            host.run_script(script, "py", out, image=image, lock_sha256=LOCK_SHA, run=ran([]), docker=foreign, base=IMAGE, platform="darwin")
        assert refused.value.word == "bad_image"
    other_lock = FakeDocker(images={DEPS: {"id": DEPS, "lock": "f" * 64}})          # built for another lock file than the approved one
    old_definition = FakeDocker(images={DEPS: {"id": DEPS, "lock": LOCK_SHA, "definition": "e" * 64}})     # built from another image definition
    for docker in (other_lock, old_definition):
        with pytest.raises(host.ProviderError) as refused:
            host.run_script(script, "py", out, image=DEPS, lock_sha256=LOCK_SHA, run=ran([]), docker=docker, base=IMAGE, platform="darwin")
        assert refused.value.word == "bad_image"
    with pytest.raises(host.ProviderError) as refused:                               # an image is never given without the approved lock's hash
        host.run_script(script, "py", out, image=DEPS, run=ran([]), docker=other_lock, base=IMAGE, platform="darwin")
    assert refused.value.code == host.EXIT_USAGE
    log = []
    mine = FakeDocker(images={DEPS: {"id": DEPS, "lock": LOCK_SHA}})
    host.run_script(script, "py", out, image=DEPS, lock_sha256=LOCK_SHA, run=ran(log), docker=mine, base=IMAGE, platform="darwin")
    assert log[0][0][log[0][0].index("--init") + 0] and DEPS in log[0][0] and IMAGE not in log[0][0]


def test_a_timeout_outside_the_range_or_an_unknown_kind_is_a_usage_error(tmp_path, quiet):
    script, out = script_file(tmp_path)
    for kwargs in ({"timeout": 0}, {"timeout": host.MAX_TIMEOUT + 1}):
        with pytest.raises(host.ProviderError) as refused:
            host.run_script(script, "py", out, run=ran([]), docker=FakeDocker(), base=IMAGE, **kwargs)
        assert refused.value.code == host.EXIT_USAGE
    with pytest.raises(host.ProviderError):
        host.run_script(script, "ruby", out, run=ran([]), docker=FakeDocker(), base=IMAGE)


# --- the dependency build ------------------------------------------------------------------------------------------------------------------


class Pipe:
    """A stand-in for the build container's client process: records what is written to its standard input."""

    def __init__(self, code=0, stderr=b""):
        self.code, self.written, self.pid = code, b"", os.getpid()
        self.stdin = self
        r, w = os.pipe()
        os.write(w, stderr)
        os.close(w)
        self.stderr = os.fdopen(r, "rb")
        self.returncode = code

    def write(self, data):
        self.written += data

    def close(self):
        pass

    def wait(self, timeout=None):
        return self.code

    def poll(self):
        return self.code


def build(tmp_path, quiet, monkeypatch, docker, pipe, lock=LOCK, sha=LOCK_SHA, **kwargs):
    original = host.Egress.__init__
    monkeypatch.setattr(host.Egress, "__init__", lambda self, *a, **k: original(self, *a, **{**k, "popen": popen_of(READY)}))
    started = []

    def popen(argv, **kw):
        started.append((argv, kw))
        return pipe

    return host.build_deps(lock.encode(), sha, docker=docker, base=IMAGE, popen=popen, platform="darwin", **kwargs), started


def test_a_lock_that_was_built_is_not_built_again(tmp_path, quiet, monkeypatch):
    tag = host.deps_tag(LOCK_SHA)
    docker = FakeDocker(images={tag: {"id": DEPS, "lock": LOCK_SHA}})
    got, started = build(tmp_path, quiet, monkeypatch, docker, Pipe())
    assert got == {"image": DEPS, "tag": tag, "cached": True} and started == [] and not any(v.startswith("network") for v in docker.verbs())


def test_a_lock_is_built_in_a_container_with_no_mount_fed_on_standard_input_and_kept_as_an_image(tmp_path, quiet, monkeypatch):
    pipe, docker = Pipe(), FakeDocker()
    docker.images = {}
    tag = host.deps_tag(LOCK_SHA)

    original = FakeDocker.__call__

    def with_commit(self, args, timeout=60):
        if args[:1] == ["commit"]:
            self.images[tag] = {"id": DEPS, "lock": LOCK_SHA}
        return original(self, args, timeout)

    FakeDocker.__call__ = with_commit
    try:
        got, started = build(tmp_path, quiet, monkeypatch, docker, pipe)
    finally:
        FakeDocker.__call__ = original
    (argv, kwargs), = started
    assert "-v" not in argv and "--mount" not in argv and "--volume" not in argv and option(argv, "--network") == NET
    assert kwargs["stdin"] == subprocess.PIPE and pipe.written == LOCK.encode()
    commit = [c for c in docker.calls if c[0] == "commit"][0]
    assert commit[-2:] == ["openhora-script-build-" + STEP_ID, tag] and f"LABEL {host.LABEL_LOCK}={LOCK_SHA}" in commit
    changes = values(commit, "--change")
    assert "USER 65534:65534" in changes and all(f"ENV {name}=" in changes for name in host.ENV_ALLOWED), "what the build was given is not kept"
    assert "LABEL org.openhora.script=" in changes and "LABEL org.openhora.script.deadline=" in changes
    assert got == {"image": DEPS, "tag": tag, "cached": False}
    assert quiet.count("openhora-script-build-" + STEP_ID) == 1
    assert docker.calls.index(["network", "rm", NET]) > docker.calls.index(commit) and ["network", "rm", OUT] in docker.calls
    # the package index is the only destination, and the proxy variables are the script's
    assert "pypi.org:443" in host.PACKAGE_INDEX and "files.pythonhosted.org:443" in host.PACKAGE_INDEX and len(host.PACKAGE_INDEX) == 2


def test_a_build_that_fails_keeps_nothing_and_says_why_in_a_closed_word(tmp_path, quiet, monkeypatch):
    docker = FakeDocker()
    with pytest.raises(host.ProviderError) as refused:
        build(tmp_path, quiet, monkeypatch, docker, Pipe(code=1, stderr=b"ERROR: hash mismatch"))
    assert refused.value.word == "build_failed" and "hash mismatch" in str(refused.value)
    assert not any(c[0] == "commit" for c in docker.calls) and "openhora-script-build-" + STEP_ID in quiet


def test_a_lock_that_is_not_the_approved_one_or_not_a_lock_is_refused_before_anything_starts(tmp_path, quiet, monkeypatch):
    docker = FakeDocker()
    with pytest.raises(host.ProviderError) as refused:
        build(tmp_path, quiet, monkeypatch, docker, Pipe(), sha="b" * 64)
    assert refused.value.word == "lock_changed"
    bad = "requests>=2\n"
    with pytest.raises(host.ProviderError) as refused:
        build(tmp_path, quiet, monkeypatch, docker, Pipe(), lock=bad, sha=hashlib.sha256(bad.encode()).hexdigest())
    assert refused.value.word == "bad_lock" and docker.calls == []


def test_the_tag_of_a_dependency_image_names_the_lock_and_the_definition_under_it():
    tag = host.deps_tag(LOCK_SHA)
    assert tag == f"openhora-script-deps:{LOCK_SHA[:16]}-{host.definition_hash()[:12]}"


def test_the_build_can_be_given_a_local_index_only_through_the_python_function(tmp_path, quiet, monkeypatch):
    docker = FakeDocker()
    pipe = Pipe()
    got, started = build(tmp_path, quiet, monkeypatch, docker, pipe, index_url="https://index.example/simple")
    assert "SCRIPT_INDEX_URL=https://index.example/simple" in values(started[0][0], "-e")
    text = (HERE.parent / "container.py").read_text(encoding="utf-8")
    assert "--index-url" not in text.split("def cmd_deps", 1)[1] and "index_url" not in text.split("def parse_args", 1)[1]


# --- reaping, the verbs ----------------------------------------------------------------------------------------------------------------------


def test_reap_removes_the_containers_and_the_networks_of_the_label_whose_deadline_has_passed(monkeypatch):
    class Listing(FakeDocker):
        def __call__(self, args, timeout=60):
            self.calls.append(list(args))
            if args[:2] == ["network", "ls"]:
                return Done(0, f"{'a' * 12} {int(time.time()) - 5}\n{'b' * 12} {int(time.time()) + 999}\n{'c' * 12} \nnot-an-id 1\n")
            return Done(0)

    monkeypatch.setattr(box, "reap", lambda label: ["deadbeef0001"])
    docker = Listing()
    assert host.reap_all(docker) == {"containers": ["deadbeef0001"], "networks": ["a" * 12, "c" * 12]}
    assert ["network", "rm", "a" * 12] in docker.calls and ["network", "rm", "b" * 12] not in docker.calls
    assert docker.calls[0][3] == "label=org.openhora.script=1"


def test_the_command_line_takes_destinations_as_a_list_and_has_no_switch_for_the_private_addresses():
    verb, args = host.parse_args(["run", "--script", "/s", "--kind", "py", "--out-dir", "/o", "--destination", "a.example:1", "--destination", "b.example:2"])
    assert verb == "run" and args["--destination"] == ["a.example:1", "b.example:2"]
    for bad in (["run", "--allow-private"], ["run", "--network", "bridge"], ["run", "--env", "A=1"], ["run", "-v", "/:/h"], ["bogus"]):
        with pytest.raises(host.ProviderError):
            host.parse_args(bad)


def test_main_reports_a_failure_as_a_closed_word_on_standard_error(capsys):
    assert host.main(["run"]) == host.EXIT_USAGE and "error: usage: --script is required" in capsys.readouterr().err
    assert host.main(["--help"]) == 0 and host.main([]) == host.EXIT_USAGE


def test_the_definition_pins_its_base_and_its_package_snapshot_and_the_image_runs_unprivileged():
    text = (HERE.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM debian@sha256:" in text and "snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" in text and "USER 65534:65534" in text
    assert "ADD http" not in text and "curl |" not in text and "latest" not in text.replace("latest of", "")
    assert set(host.DEFINITION_FILES) == {"Dockerfile", ".dockerignore", "_inner.py", "egress_proxy.py"}
    assert (HERE.parent / ".dockerignore").read_text().split() == ["*", "!_inner.py", "!egress_proxy.py"]


def test_the_resolver_finds_the_class_and_one_implementation_and_gives_it_the_minimum_environment():
    resolver = box._resolver()
    got = resolver.resolve("script:project", root=str(REPO), env={})
    assert got["implementation"] == "container" and got["path"] == str(HERE.parent / "container.py") and got["source"] == "only-implementation"
    assert resolver.implementations("script:project", root=str(REPO)) == ["container"], "the programs of the image are shared code, not providers"
    assert resolver.variables("script:project") == ["SCRIPT_PROJECT_PROVIDER", "SCRIPT_PROVIDER"]
    assert "script" in resolver.ROLES and "script:project" not in resolver.LISTED
    planted = {"OPENAI_API_KEY": "planted-" + "a1" * 10, "NOTION_TOKEN": "planted-" + "b2" * 10, "PATH": "/bin", "SCRIPT_PROVIDER": "container"}
    assert resolver.provider_environment("script:project", planted) == {"PATH": "/bin", "SCRIPT_PROVIDER": "container"}
