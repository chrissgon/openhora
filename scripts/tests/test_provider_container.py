"""Tests of providers/_container.py, the one home of a sandboxed container job: the `docker run` command and each of its
limits (compared, argument by argument, with what the renderer's and the transcriber's `container_argv` wrote at commit
6794905e of the short-video branch), the bind-mount path rule, the environment a provider and the docker client get, and the
lifecycle (run, timeout, signal, a start that fails, stop, reap) against a fake `docker` script on PATH. Offline: no docker,
no network, no image.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_provider_container.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import stat
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


box = _load("workbench_container_under_test", "providers/_container.py")
resolve = box._resolver()

# The expected commands, computed once from the branch's functions at 6794905e with fixed inputs, and kept as literals:
#   providers/renderer/_docker.py container_argv(name, image_id, inner_args, job_dir=, out_dir=, recording=, memory_mb=,
#       cpus=, scratch_mb=, deadline=, platform=)   with uid 1000 and gid 1001
#   providers/transcriber/whispercpp.py container_argv(...)   the same
GOLDEN = {
    'renderer_linux': [
        'docker', 'run', '--rm', '--init', '--pull', 'never', '--name', 'openhora-renderer-abc', '--label',
        'org.openhora.renderer=1', '--label', 'org.openhora.renderer.deadline=1760000000', '--network', 'none',
        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '512', '--memory',
        '6144m', '--memory-swap', '6144m', '--cpus', '8', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=256m',
        '--tmpfs', '/scratch:rw,noexec,nosuid,nodev,size=2048m,mode=1777', '--user', '1000:1001', '-v',
        '/data/rec.mov:/in/recording:ro', '-v', '/work/job:/job:ro', '-v', '/work/out:/out:rw', 'sha256:img',
        'render', '--x',
    ],
    'whispercpp_linux': [
        'docker', 'run', '--rm', '--init', '--pull', 'never', '--name', 'openhora-transcriber-abc', '--label',
        'org.openhora.transcriber=1', '--label', 'org.openhora.transcriber.deadline=1760000000', '--network', 'none',
        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '256', '--memory',
        '4096m', '--memory-swap', '4096m', '--cpus', '4', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
        '--tmpfs', '/scratch:rw,noexec,nosuid,nodev,size=256m,mode=1777', '--user', '1000:1001', '-v',
        '/data/in.wav:/in/input:ro', '-v', '/models/m.bin:/models/model.bin:ro', '-v', '/work/out:/out:rw',
        'sha256:img', '4', 'en', 'word', '-', '600', '900',
    ],
    'renderer_darwin': [
        'docker', 'run', '--rm', '--init', '--pull', 'never', '--name', 'openhora-renderer-abc', '--label',
        'org.openhora.renderer=1', '--label', 'org.openhora.renderer.deadline=1760000000', '--network', 'none',
        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '512', '--memory',
        '6144m', '--memory-swap', '6144m', '--cpus', '8', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=256m',
        '--tmpfs', '/scratch:rw,noexec,nosuid,nodev,size=2048m,mode=1777', '-v', '/data/rec.mov:/in/recording:ro',
        '-v', '/work/job:/job:ro', '-v', '/work/out:/out:rw', 'sha256:img', 'render', '--x',
    ],
    'whispercpp_darwin': [
        'docker', 'run', '--rm', '--init', '--pull', 'never', '--name', 'openhora-transcriber-abc', '--label',
        'org.openhora.transcriber=1', '--label', 'org.openhora.transcriber.deadline=1760000000', '--network', 'none',
        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '256', '--memory',
        '4096m', '--memory-swap', '4096m', '--cpus', '4', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
        '--tmpfs', '/scratch:rw,noexec,nosuid,nodev,size=256m,mode=1777', '-v', '/data/in.wav:/in/input:ro', '-v',
        '/models/m.bin:/models/model.bin:ro', '-v', '/work/out:/out:rw', 'sha256:img', '4', 'en', 'word', '-', '600',
        '900',
    ],
    'renderer_no_recording_linux': [
        'docker', 'run', '--rm', '--init', '--pull', 'never', '--name', 'n', '--label', 'org.openhora.renderer=1',
        '--label', 'org.openhora.renderer.deadline=5', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges', '--pids-limit', '512', '--memory', '3072m', '--memory-swap', '3072m',
        '--cpus', '2', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=256m', '--tmpfs',
        '/scratch:rw,noexec,nosuid,nodev,size=512m,mode=1777', '--user', '1000:1001', '-v', '/j:/job:ro', '-v',
        '/o:/out:rw', 'i',
    ],
}


def fixed_ids(monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1001)


def renderer(platform, recording="/data/rec.mov"):
    mounts = ([(recording, "/in/recording", "ro")] if recording else []) + [("/work/job", "/job", "ro"), ("/work/out", "/out", "rw")]
    return box.argv("openhora-renderer-abc", "sha256:img", ["render", "--x"], label="org.openhora.renderer", deadline=1760000000,
                    mounts=mounts, memory_mb=6144, cpus=8, scratch_mb=2048, pids_limit=512, tmp_mb=256, platform=platform)


def transcriber(platform):
    return box.argv("openhora-transcriber-abc", "sha256:img", ["4", "en", "word", "-", "600", "900"],
                    label="org.openhora.transcriber", deadline=1760000000,
                    mounts=[("/data/in.wav", "/in/input", "ro"), ("/models/m.bin", "/models/model.bin", "ro"), ("/work/out", "/out", "rw")],
                    memory_mb=4096, cpus=4, scratch_mb=256, platform=platform)


# --- the golden: the helper writes the command the two providers wrote -------------------------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_the_renderer_command_is_the_one_the_renderer_wrote(monkeypatch, platform):
    fixed_ids(monkeypatch)
    assert renderer(platform) == GOLDEN["renderer_" + platform]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_the_transcriber_command_is_the_one_the_transcriber_wrote(monkeypatch, platform):
    fixed_ids(monkeypatch)
    assert transcriber(platform) == GOLDEN["whispercpp_" + platform]


def test_a_job_with_no_recording_is_the_renderers_command_without_that_mount(monkeypatch):
    fixed_ids(monkeypatch)
    command = box.argv("n", "i", [], label="org.openhora.renderer", deadline=5, mounts=[("/j", "/job", "ro"), ("/o", "/out", "rw")],
                       memory_mb=3072, cpus=2, scratch_mb=512, pids_limit=512, tmp_mb=256, platform="linux")
    assert command == GOLDEN["renderer_no_recording_linux"]


def option(command, flag, nth=0):
    """The value that follows the nth occurrence of `flag`."""
    positions = [i for i, word in enumerate(command) if word == flag]
    return command[positions[nth] + 1]


@pytest.mark.parametrize("maker", [renderer, transcriber])
def test_each_limit_keeps_its_flag_and_value_in_both_commands(monkeypatch, maker):
    fixed_ids(monkeypatch)
    command = maker("linux")
    assert command[:7] == ["docker", "run", "--rm", "--init", "--pull", "never", "--name"]
    assert option(command, "--network") == "none"
    assert "--read-only" in command
    assert option(command, "--cap-drop") == "ALL"
    assert option(command, "--security-opt") == "no-new-privileges"
    assert option(command, "--memory") == option(command, "--memory-swap"), "swap is not allowed beyond memory"
    assert option(command, "--user") == "1000:1001"
    tmpfs = [command[i + 1] for i, w in enumerate(command) if w == "--tmpfs"]
    assert tmpfs[0].startswith("/tmp:rw,noexec,nosuid,nodev,size=") and tmpfs[1].startswith("/scratch:rw,noexec,nosuid,nodev,size=")
    assert tmpfs[1].endswith(",mode=1777")


def test_the_limits_of_the_renderer_and_of_the_transcriber_are_the_numbers_they_wrote(monkeypatch):
    fixed_ids(monkeypatch)
    r, t = renderer("linux"), transcriber("linux")
    assert (option(r, "--pids-limit"), option(r, "--memory"), option(r, "--cpus")) == ("512", "6144m", "8")
    assert option(r, "--tmpfs", 0) == "/tmp:rw,noexec,nosuid,nodev,size=256m"
    assert option(r, "--tmpfs", 1) == "/scratch:rw,noexec,nosuid,nodev,size=2048m,mode=1777"
    assert (option(t, "--pids-limit"), option(t, "--memory"), option(t, "--cpus")) == ("256", "4096m", "4")
    assert option(t, "--tmpfs", 0) == "/tmp:rw,noexec,nosuid,nodev,size=64m"
    assert option(t, "--tmpfs", 1) == "/scratch:rw,noexec,nosuid,nodev,size=256m,mode=1777"


def test_the_defaults_are_the_stricter_limits_and_are_named_constants():
    assert (box.PIDS_LIMIT, box.TMP_SIZE_MB, box.MOUNT_SCRATCH) == (256, 64, "/scratch")
    command = box.argv("n", "i", [], label="org.openhora.job", deadline=7, mounts=[], memory_mb=100, cpus=1, scratch_mb=10, platform="darwin")
    assert option(command, "--pids-limit") == "256" and option(command, "--tmpfs", 0).endswith("size=64m")


def test_the_run_label_and_the_deadline_label_are_set_on_the_container():
    command = box.argv("n", "i", [], label="org.openhora.job", deadline=1234, mounts=[], memory_mb=100, cpus=1, scratch_mb=10, platform="darwin")
    labels = [command[i + 1] for i, w in enumerate(command) if w == "--label"]
    assert labels == ["org.openhora.job=1", "org.openhora.job.deadline=1234"] and box.deadline_label("x.y") == "x.y.deadline"


def test_no_user_flag_off_linux_and_the_image_and_args_come_last(monkeypatch):
    fixed_ids(monkeypatch)
    assert "--user" not in renderer("darwin") and "--user" in renderer("linux")
    assert transcriber("linux")[-7:] == ["sha256:img", "4", "en", "word", "-", "600", "900"]


def test_the_image_is_never_pulled_and_the_network_is_off_whatever_the_caller_passes(monkeypatch):
    with pytest.raises(TypeError):
        box.argv("n", "i", [], label="l", deadline=1, mounts=[], memory_mb=1, cpus=1, scratch_mb=1, network="host")
    with pytest.raises(TypeError):
        box.argv("n", "i", [], label="l", deadline=1, mounts=[], memory_mb=1, cpus=1, scratch_mb=1, pull="always")


@pytest.mark.parametrize("bad", ["relative/path", "", "/a:b", "/a\nb", "/a\x00b", "/a\x7fb", None, 5])
def test_a_mount_path_that_is_relative_or_holds_a_colon_or_a_control_character_is_refused(bad):
    with pytest.raises(box.ContainerError) as caught:
        box.mount_path(bad, "recording")
    assert caught.value.code == "bad_mount_path" and caught.value.what == "recording"
    with pytest.raises(box.ContainerError):
        box.argv("n", "i", [], label="l", deadline=1, mounts=[(bad, "/in", "ro")], memory_mb=1, cpus=1, scratch_mb=1, platform="darwin")


def test_a_good_mount_path_passes_unchanged_and_a_mount_mode_is_ro_or_rw():
    assert box.mount_path("/a b/c-d.mov", "x") == "/a b/c-d.mov"
    with pytest.raises(box.ContainerError) as caught:
        box.argv("n", "i", [], label="l", deadline=1, mounts=[("/a", "/b", "rwx")], memory_mb=1, cpus=1, scratch_mb=1, platform="darwin")
    assert caught.value.code == "bad_mount"
    with pytest.raises(box.ContainerError):
        box.argv("n", "i", [], label="l", deadline=1, mounts=[("/a", "relative", "ro")], memory_mb=1, cpus=1, scratch_mb=1, platform="darwin")


# --- the environment ---------------------------------------------------------------------------------------------------------------


NOISE = {"AWS_SECRET_ACCESS_KEY": "s3cr3t", "OPENHORA_TOKEN": "t0k", "SEARCH_WEB_PROVIDER": "other", "RENDERER_PROVIDER": "r",
         "TRANSCRIBER_SPEECH_PROVIDER": "t", "MAILBOX_PROVIDER": "m", "ANTHROPIC_API_KEY": "k"}


def test_the_provider_environment_is_the_minimum_plus_what_resolve_returns_for_the_class():
    env = dict(NOISE, PATH="/bin", HOME="/h", DOCKER_HOST="unix:///x", OPENHORA_STATE_DIR="/s", XDG_STATE_HOME="/xs",
               GENERATOR_IMAGE_PROVIDER="one", GENERATOR_PROVIDER="two")
    assert resolve.variables("generator:image") == ["GENERATOR_IMAGE_PROVIDER", "GENERATOR_PROVIDER"]
    got = box.provider_environment("generator:image", env)
    assert got == {"PATH": "/bin", "HOME": "/h", "DOCKER_HOST": "unix:///x", "OPENHORA_STATE_DIR": "/s", "XDG_STATE_HOME": "/xs",
                   "GENERATOR_IMAGE_PROVIDER": "one", "GENERATOR_PROVIDER": "two"}
    assert set(got) <= set(box.ENV_MINIMUM) | set(resolve.variables("generator:image"))


def test_no_other_provider_variable_present_in_the_process_environment_passes(monkeypatch):
    for key, value in dict(NOISE, PATH="/bin", GENERATOR_PROVIDER="two").items():
        monkeypatch.setenv(key, value)
    got = box.provider_environment("generator:image")
    providers = {k for k in got if k.endswith("_PROVIDER")}
    assert providers == {"GENERATOR_PROVIDER"}, providers
    for secret in ("AWS_SECRET_ACCESS_KEY", "OPENHORA_TOKEN", "ANTHROPIC_API_KEY"):
        assert secret not in got


def test_the_variables_follow_the_class_whatever_it_is():
    env = dict(NOISE, SEARCH_WEB_PROVIDER="web", SEARCH_PROVIDER="s", GENERATOR_PROVIDER="g", INTEGRATION_VCS_PROVIDER="github")
    assert {k for k in box.provider_environment("search:web", env) if k.endswith("_PROVIDER")} == {"SEARCH_WEB_PROVIDER", "SEARCH_PROVIDER"}
    assert {k for k in box.provider_environment("integration:vcs", env) if k.endswith("_PROVIDER")} == {"INTEGRATION_VCS_PROVIDER"}
    assert {k for k in box.provider_environment("store:runtime", dict(env, STORE_PROVIDER="sqlite")) if k.endswith("_PROVIDER")} == {"STORE_PROVIDER"}


def test_a_variable_that_is_unset_or_empty_is_left_out_and_an_unknown_class_is_refused():
    assert box.provider_environment("generator:image", {"GENERATOR_PROVIDER": "", "PATH": "/bin"}) == {"PATH": "/bin"}
    with pytest.raises(resolve.UnknownClass):
        box.provider_environment("converter:document", {})
    with pytest.raises(resolve.UnknownClass):
        box.provider_environment("nonsense", {})


def test_the_module_names_no_provider():
    text = (REPO / "providers" / "_container.py").read_text(encoding="utf-8")
    for word in ("TRANSCRIBER", "RENDERER_", "whisper", "ffmpeg"):
        assert word not in text, word


def test_the_docker_client_gets_its_own_short_list_and_nothing_else():
    env = dict(NOISE, PATH="/bin", HOME="/h", DOCKER_CONTEXT="c", OPENHORA_STATE_DIR="/s", GENERATOR_PROVIDER="g")
    assert box.docker_environment(env) == {"PATH": "/bin", "HOME": "/h", "DOCKER_CONTEXT": "c"}


def test_docker_binary_is_found_on_the_path_or_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(box.ContainerError) as caught:
        box.docker_binary()
    assert caught.value.code == "docker_missing"
    fake = tmp_path / "docker"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    assert box.docker_binary() == str(fake)


# --- a fake container tool ---------------------------------------------------------------------------------------------------------

FAKE = r'''#!{python}
import hashlib, json, os, sys, time
STATE = {state!r}
CONTAINERS = os.path.join(STATE, "containers")
args = sys.argv[1:]
with open(os.path.join(STATE, "log.jsonl"), "a") as log:
    log.write(json.dumps({{"args": args, "env": sorted(os.environ)}}) + "\n")


def flag(name):
    return os.path.exists(os.path.join(STATE, name))


def containers():
    out = []
    for n in sorted(os.listdir(CONTAINERS)):
        with open(os.path.join(CONTAINERS, n)) as f:
            out.append(json.load(f))
    return out


def drop(c):
    os.unlink(os.path.join(CONTAINERS, c["id"]))


if args[0] == "run":
    if flag("fail-run"):
        sys.stderr.write("docker: Error response from daemon: no such image\n")
        sys.exit(125)
    name = args[args.index("--name") + 1]
    labels = {{}}
    for i, a in enumerate(args):
        if a == "--label":
            k, _, v = args[i + 1].partition("=")
            labels[k] = v
    cid = hashlib.sha1(name.encode()).hexdigest()[:12]
    with open(os.path.join(CONTAINERS, cid), "w") as f:
        json.dump({{"id": cid, "name": name, "labels": labels}}, f)
    if flag("flood"):
        sys.stderr.write("x" * 200000 + "THE-END")
    if flag("stderr"):
        sys.stderr.write(open(os.path.join(STATE, "stderr")).read())
    if flag("sleep"):
        time.sleep(60)
    os.unlink(os.path.join(CONTAINERS, cid))
    sys.exit(int(open(os.path.join(STATE, "exit")).read()) if flag("exit") else 0)
elif args[0] == "rm":
    found = [c for c in containers() if args[-1] in (c["name"], c["id"])]
    if not found:
        sys.stderr.write("Error: No such container: " + args[-1] + "\n")
        sys.exit(1)
    for c in found:
        drop(c)
elif args[0] == "ps":
    if flag("fail-ps"):
        sys.exit(1)
    label = args[args.index("--filter") + 1].split("=", 1)[1]
    key = label.rsplit("=", 1)[0]
    for c in containers():
        if c["labels"].get(key) == "1":
            print(c["id"], c["labels"].get(key + ".deadline", ""))
else:
    sys.exit(2)
'''


class Fake:
    def __init__(self, root):
        self.state = root / "state"
        (self.state / "containers").mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        script = self.bin / "docker"
        script.write_text(FAKE.format(python=sys.executable, state=str(self.state)))
        script.chmod(script.stat().st_mode | stat.S_IXUSR)

    def set(self, flag, text=""):
        (self.state / flag).write_text(text)

    def add(self, name, label, deadline=None, run_label=True):
        cid = __import__("hashlib").sha1(name.encode()).hexdigest()[:12]
        labels = {label: "1"} if run_label else {}
        if deadline is not None:
            labels[label + ".deadline"] = str(deadline)
        (self.state / "containers" / cid).write_text(json.dumps({"id": cid, "name": name, "labels": labels}))
        return cid

    def names(self):
        return sorted(json.loads(p.read_text())["name"] for p in (self.state / "containers").iterdir())

    def log(self):
        path = self.state / "log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def commands(self):
        return [entry["args"] for entry in self.log()]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    tool = Fake(tmp_path)
    monkeypatch.setenv("PATH", str(tool.bin) + os.pathsep + os.environ.get("PATH", ""))
    return tool


def job(name="job-1", label="org.openhora.job"):
    return box.argv(name, "sha256:img", ["go"], label=label, deadline=2000000000, mounts=[("/tmp", "/in", "ro")], memory_mb=100,
                    cpus=1, scratch_mb=10, platform="darwin")


# --- the lifecycle -----------------------------------------------------------------------------------------------------------------


def test_a_job_that_ends_returns_its_code_and_stderr_and_leaves_no_container(fake):
    fake.set("exit", "3")
    fake.set("stderr", "tool: bad input\n")
    done = box.run(job(), "job-1", 30)
    assert done == box.Finished(3, "tool: bad input\n", False) and fake.names() == []
    started = fake.commands()[0]
    assert started[0] == "run" and started[started.index("--name") + 1] == "job-1" and started[-2:] == ["sha256:img", "go"]


def test_the_client_is_started_with_the_docker_environment_only(fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("OPENHORA_TOKEN", "t")
    monkeypatch.setenv("RENDERER_PROVIDER", "r")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    box.run(job(), "job-1", 30)
    seen = set(fake.log()[0]["env"])
    assert {"DOCKER_HOST", "PATH"} <= seen
    assert not {"ANTHROPIC_API_KEY", "OPENHORA_TOKEN", "RENDERER_PROVIDER"} & seen


def test_a_job_past_its_time_is_stopped_and_removed_by_name(fake):
    fake.set("sleep")
    with pytest.raises(box.ContainerError) as caught:
        box.run(job("slow-1"), "slow-1", 0.5)
    assert caught.value.code == "time_limit" and fake.names() == []
    assert ["rm", "-f", "slow-1"] in fake.commands()


def test_a_stop_signal_removes_the_container_by_name_and_restores_the_handlers(fake):
    fake.set("sleep")
    before = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))
    timer = threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        with pytest.raises(box.ContainerError) as caught:
            box.run(job("sig-1"), "sig-1", 30)
    finally:
        timer.cancel()
    assert caught.value.code == "stopped" and fake.names() == [] and ["rm", "-f", "sig-1"] in fake.commands()
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before


def test_a_start_that_fails_leaves_no_container(fake):
    fake.set("fail-run")
    done = box.run(job("never-1"), "never-1", 30)
    assert done.returncode == 125 and "no such image" in done.stderr and fake.names() == []


def test_a_client_that_cannot_be_started_is_refused_and_leaves_no_container(tmp_path, monkeypatch):
    bad = tmp_path / "bin"
    bad.mkdir()
    (bad / "docker").write_text("#!/nonexistent/interpreter\n")
    (bad / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", str(bad))
    with pytest.raises(box.ContainerError) as caught:
        box.run(job(), "job-1", 5)
    assert caught.value.code == "docker_unusable"
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(box.ContainerError) as caught:
        box.run(job(), "job-1", 5)
    assert caught.value.code == "docker_missing"


def test_only_the_last_bytes_of_stderr_are_kept_and_the_flood_is_read_to_the_end(fake):
    fake.set("flood")
    done = box.run(job(), "job-1", 30)
    assert done.truncated and len(done.stderr.encode()) <= box.STDERR_CAP and done.stderr.endswith("THE-END")
    assert fake.names() == []


def test_stop_and_remove_end_a_container_by_name_and_never_raise(fake):
    fake.add("keep-1", "org.openhora.job", 1)
    fake.add("gone-1", "org.openhora.job", 1)
    box.stop("gone-1")
    assert fake.names() == ["keep-1"] and ["rm", "-f", "gone-1"] in fake.commands()
    box.remove("gone-1")                         # already gone: the tool answers 1, nothing is raised
    box.remove("keep-1")
    assert fake.names() == []


def test_remove_does_not_raise_when_there_is_no_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    box.remove("anything")
    box.stop("anything")


def test_reap_removes_the_containers_of_the_run_label_whose_deadline_has_passed(fake):
    label = "org.openhora.job"
    past = fake.add("past-1", label, 500)
    fake.add("future-1", label, 5000)
    other = fake.add("other-1", "org.openhora.other", 500)
    unlabelled = fake.add("plain-1", label, None, run_label=False)
    nodeadline = fake.add("nodeadline-1", label, None)
    removed = box.reap(label, now=1000)
    assert sorted(removed) == sorted([past, nodeadline])
    assert fake.names() == ["future-1", "other-1", "plain-1"], (other, unlabelled)
    ps = [c for c in fake.commands() if c[0] == "ps"][0]
    assert ps[:3] == ["ps", "-a", "--filter"] and ps[3] == "label=org.openhora.job=1" and "org.openhora.job.deadline" in ps[-1]


def test_reap_uses_the_clock_when_it_is_not_given_one(fake):
    fake.add("old-1", "org.openhora.job", 1)
    fake.add("far-1", "org.openhora.job", 4102444800)      # the year 2100
    assert len(box.reap("org.openhora.job")) == 1 and fake.names() == ["far-1"]


def test_reap_that_cannot_list_is_refused(fake):
    fake.set("fail-ps")
    with pytest.raises(box.ContainerError) as caught:
        box.reap("org.openhora.job", now=1)
    assert caught.value.code == "docker_ps_failed"


def test_reap_ignores_a_line_that_is_not_a_container_id(fake):
    # a name with an uppercase letter or a dash at the start is not a hexadecimal id
    assert box.CONTAINER_ID.fullmatch("0123abcdef01") and not box.CONTAINER_ID.fullmatch("--force") and not box.CONTAINER_ID.fullmatch("ABCDEF1234")


# --- what the helper is not --------------------------------------------------------------------------------------------------------


def test_the_eval_executor_does_not_use_the_helper():
    for rel in ("evals/executor.py", "evals/measure.py", "scripts/stage_skills.py"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "_container" not in text, rel
    for path in (REPO / "evals" / "container").rglob("*"):
        if path.is_file() and path.suffix in (".py", ".sh", ".json"):
            assert "providers/_container" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_the_helper_imports_only_the_standard_library_and_the_resolver():
    import ast
    tree = ast.parse((REPO / "providers" / "_container.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= set(sys.stdlib_module_names) | {"__future__"} if hasattr(sys, "stdlib_module_names") else True
    assert not names & {"evals", "runtime", "adapters", "scripts"}
