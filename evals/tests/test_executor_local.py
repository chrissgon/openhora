"""Offline tests of the model server a local model gets (evals/executor.py hold_local(), release_local(), local_server_argv(),
command(local=...), pull_local_server()) and of the pins in evals/local-model-server.json. docker is a recording stand-in;
nothing is pulled and no server is started.

Run: uv run --with pytest pytest evals/tests/test_executor_local.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "executor.py"
spec = importlib.util.spec_from_file_location("executor_local", SCRIPT)
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

RUN = "0123456789abcdef"
LOG = "0.00.014.760 I srv  llama_server: listening on http://0.0.0.0:8080\n"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    ex._NATIVE["platform"] = "linux/arm64"
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)
    yield
    ex._NATIVE.clear()


class FakeDocker:
    """docker as the local functions see it. fail = {(command, subcommand or None): stderr}; health is the list of health
    statuses `inspect` answers in turn (the last one repeats); the state is "running" unless stopped is set."""

    def __init__(self, fail=None, health=("healthy",), state="running", logs="", present=True, digests=None):
        self.calls, self.envs, self.fail, self.health, self.state, self.logs = [], [], fail or {}, list(health), state, logs
        self.present, self.digests, self.inspected = present, digests, 0

    def __call__(self, *args, env=None, check=True, timeout=1800):
        self.calls.append(args)
        self.envs.append(dict(env or {}))
        key = (args[0], args[1] if args[0] in ("network", "image") else None)
        if key in self.fail:
            return subprocess.CompletedProcess(["docker", *args], 1, "", self.fail[key])
        out = ""
        if args[0] == "inspect":
            status = self.health[min(self.inspected, len(self.health) - 1)]
            self.inspected += 1
            out = f"{self.state} {status}\n"
        elif args[0] == "logs":
            return subprocess.CompletedProcess(["docker", *args], 0, "", self.logs)
        elif args[:2] == ("image", "inspect"):
            if not self.present:
                return subprocess.CompletedProcess(["docker", *args], 1, "", "No such image")
            if "--format" in args:
                out = json.dumps(self.digests if self.digests is not None else [f"{ex.LOCAL_REPOSITORY}@{args[-1].rsplit('@', 1)[1]}"])
        elif args[:1] == ("info",):
            out = "14\n" if "{{.NCPU}}" in args else "28.0.0\n"
        elif args[0] == "run" and "--version" in args:
            return subprocess.CompletedProcess(["docker", *args], 0, "", "version: 0.5.0-dev (build 11277, commit eae11d221)\nbuilt with GNU 14.2.0 for Linux aarch64\n")
        return subprocess.CompletedProcess(["docker", *args], 0, out, "")

    def named(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == prefix]


def spec_of(tmp_path, **changes):
    weights = tmp_path / "model.gguf"
    weights.write_bytes(b"GGUF")
    return {"alias": "example-coder@047bf46455a5", "weights": str(weights), "context": 32768, "memory_gb": 24, "accelerator": "cpu",
            "cpus": 8, "load_timeout_seconds": 900, **changes}


def pairs(argv):
    return [list(argv[i:i + 2]) for i in range(len(argv) - 1)]


# --- the pins ----------------------------------------------------------------------------------------------------------

def test_the_pinned_images_are_by_digest_with_a_manifest_digest_for_each_cpu_platform():
    pins = ex.local_server_pins()
    assert set(pins) == {"cpu", "cuda"}
    for accelerator, pin in pins.items():
        assert ex.LOCAL_IMAGE_RE.fullmatch(pin["image"]) and set(pin["platforms"]) == set(ex.IMAGE_PLATFORMS)
        assert pin["source"].startswith("https://") and pin["accessed"] == "2026-10-15"
    assert pins["cpu"]["image"].startswith("ghcr.io/ggml-org/llama.cpp:server-b") and ":server-cuda12-b" in pins["cuda"]["image"]
    server = ex.local_server("cpu", "linux/arm64")
    assert server["index_digest"] == pins["cpu"]["image"].rsplit("@", 1)[1] and server["manifest_digest"] == pins["cpu"]["platforms"]["linux/arm64"]
    assert ex.local_server("cpu", "linux/amd64")["manifest_digest"] == pins["cpu"]["platforms"]["linux/amd64"]


@pytest.mark.parametrize("change", [
    lambda p: p["cpu"].update(image="ghcr.io/ggml-org/llama.cpp:server-b1"),                       # no digest
    lambda p: p["cpu"].update(image="ghcr.io/someone/llama.cpp:server-b1@sha256:" + "a" * 64),   # another owner
    lambda p: p["cpu"].update(platforms={"linux/riscv64": "sha256:" + "a" * 64}),
    lambda p: p["cpu"].update(platforms={"linux/arm64": "sha256:short"}),
    lambda p: p["cpu"].pop("source"),
    lambda p: p["cpu"].update(accessed="today"),
    lambda p: p.update(vulkan={}),
])
def test_a_pin_file_that_is_not_in_its_form_is_refused(tmp_path, change):
    pins = json.loads(ex.LOCAL_SERVER_FILE and Path(ex.LOCAL_SERVER_FILE).read_text())
    change(pins)
    path = tmp_path / "pins.json"
    path.write_text(json.dumps(pins))
    with pytest.raises(ex.ExecutorError):
        ex.local_server_pins(str(path))
    with pytest.raises(ex.ExecutorError, match="not readable"):
        ex.local_server_pins(str(tmp_path / "absent.json"))


def test_a_platform_or_accelerator_that_is_not_pinned_is_an_error():
    with pytest.raises(ex.ExecutorError, match="not linux/s390x"):
        ex.local_server("cpu", "linux/s390x")
    with pytest.raises(ex.ExecutorError, match="no model server image is pinned"):
        ex.local_server("tpu")


def test_the_image_must_be_present_with_the_pinned_digest_and_is_never_pulled(monkeypatch):
    docker = FakeDocker(present=False)
    monkeypatch.setattr(ex, "docker", docker)
    with pytest.raises(ex.ExecutorError, match=r"is not present.*pull-local-server.*a test never pulls"):
        ex.verify_local_server("cpu")
    assert not docker.named("pull")
    with pytest.raises(ex.ExecutorError, match="--accelerator cuda"):
        ex.verify_local_server("cuda")
    wrong = FakeDocker(digests=[f"{ex.LOCAL_REPOSITORY}@sha256:" + "0" * 64])
    monkeypatch.setattr(ex, "docker", wrong)
    with pytest.raises(ex.ExecutorError, match="does not list the pinned digest"):
        ex.verify_local_server("cpu")
    monkeypatch.setattr(ex, "docker", FakeDocker())
    assert ex.verify_local_server("cpu")["image"] == ex.local_server_pins()["cpu"]["image"]


def test_pull_local_server_pulls_by_digest_for_the_platform_and_checks_the_digest(monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    got = ex.pull_local_server("cpu")
    pull = docker.named("pull")[0]
    assert pull[:3] == ("pull", "--platform", "linux/arm64") and pull[3] == ex.local_server_pins()["cpu"]["image"] and "@sha256:" in pull[3]
    assert got["manifest_digest"] == ex.local_server_pins()["cpu"]["platforms"]["linux/arm64"] and got["platform"] == "linux/arm64"
    docker = FakeDocker(digests=[])
    monkeypatch.setattr(ex, "docker", docker)
    with pytest.raises(ex.ExecutorError, match="does not list the pinned digest"):
        ex.pull_local_server("cpu")
    monkeypatch.setattr(ex, "docker", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "down"))
    with pytest.raises(ex.ExecutorError, match="daemon is not running"):
        ex.pull_local_server("cpu")


def test_the_command_pulls_only_on_its_own_subcommand(monkeypatch, capsys):
    monkeypatch.setattr(ex, "docker", FakeDocker())
    assert ex.main(["pull-local-server", "--accelerator", "cuda"]) == 0
    assert "server-cuda12-b" in capsys.readouterr().out
    assert ex.main(["pull-local-server", "--accelerator", "tpu"]) == 2
    assert "pull-local-server" in ex.__doc__


# --- the server's arguments -----------------------------------------------------------------------------------------

def test_the_model_server_is_started_with_exactly_the_arguments_of_the_spec(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    spec = spec_of(tmp_path)
    held = ex.hold_local(RUN, spec)
    image = ex.local_server_pins()["cpu"]["image"]
    run = docker.named("run")[0]
    weights = os.path.realpath(spec["weights"])
    user = f"{os.getuid()}:{os.getgid()}" if sys.platform.startswith("linux") else "65534:65534"
    assert list(run) == [
        "run", "-d", "--pull=never", "--rm", "--init", "--platform", "linux/arm64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m", "--memory", "24g", "--memory-swap", "24g",
        "--cpus", "8", "--log-opt", "max-size=10m", "--log-opt", "max-file=3", "--health-interval", "2s",
        "--label", "wb.eval=1", "--label", f"wb.eval.run={RUN}", "--user", user, "--name", f"wb-eval-model-{RUN}",
        "--network", f"wb-eval-held-{RUN}", "-v", f"{weights}:/models/model.gguf:ro", image,
        "-m", "/models/model.gguf", "--host", "0.0.0.0", "--port", "8080", "-c", "32768", "--alias", "example-coder@047bf46455a5",
        "--jinja", "--parallel", "1", "--threads", "8", "-ngl", "0", "--no-webui", "--no-slots", "--no-context-shift"]
    assert held == {"model": f"wb-eval-model-{RUN}", "network": f"wb-eval-held-{RUN}", "url": f"http://wb-eval-model-{RUN}:8080/v1",
                    "seconds": held["seconds"]}
    # the properties the argument list must have, stated one by one
    assert run.count("--network") == 1 and run.count("-v") == 1 and run[run.index("-v") + 1].endswith(":/models/model.gguf:ro")
    assert not {"-p", "--publish", "-P", "--add-host", "-e", "--env", "--env-file", "--privileged", "--network=host", "--gpus"} & set(run)
    assert "--restart" not in run and run[run.index("--memory") + 1] == run[run.index("--memory-swap") + 1]
    assert run.index("--pull=never") < run.index(image) and run.index("--read-only") < run.index(image)
    assert docker.envs[docker.calls.index(run)] == {}  # nothing travels in the docker client's environment either


def test_cuda_adds_the_gpus_and_the_cuda_image_only_with_cuda(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.hold_local(RUN, spec_of(tmp_path, accelerator="cuda"))
    run = docker.named("run")[0]
    assert run[run.index("--gpus") + 1] == "all" and ex.local_server_pins()["cuda"]["image"] in run and run[run.index("-ngl") + 1] == "999"
    assert ex.local_server_pins()["cpu"]["image"] not in run
    cpu = FakeDocker()
    monkeypatch.setattr(ex, "docker", cpu)
    ex.hold_local(RUN, spec_of(tmp_path))
    assert "--gpus" not in cpu.named("run")[0] and cpu.named("run")[0][cpu.named("run")[0].index("-ngl") + 1] == "0"


def test_the_network_is_internal_labelled_and_made_before_the_server(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.hold_local(RUN, spec_of(tmp_path))
    created = docker.named("network", "create")[0]
    assert created == ("network", "create", "--internal", "--label", "wb.eval=1", "--label", f"wb.eval.run={RUN}", f"wb-eval-held-{RUN}")
    assert docker.calls.index(created) < docker.calls.index(docker.named("run")[0])
    assert not docker.named("network", "connect")  # the server is on the run's network and no other


def test_the_user_is_the_caller_on_linux_and_nobody_elsewhere(monkeypatch):
    monkeypatch.setattr(ex.sys, "platform", "linux")
    assert ex.local_user() == ["--user", f"{os.getuid()}:{os.getgid()}"]
    monkeypatch.setattr(ex.sys, "platform", "darwin")
    assert ex.local_user() == ["--user", "65534:65534"]


def test_the_hash_of_the_arguments_does_not_depend_on_the_run_the_path_or_the_user(tmp_path):
    spec = spec_of(tmp_path)
    a = ex.local_server_argv("0" * 16, spec, "image", "linux/arm64", "/weights/model.gguf", ["--user", "0:0"])
    b = ex.local_server_argv("0" * 16, {**spec, "weights": "/elsewhere/other.gguf"}, "image", "linux/arm64", "/weights/model.gguf", ["--user", "0:0"])
    assert a == b
    assert ex.local_server_argv("f" * 16, spec, "image", "linux/arm64", "/weights/model.gguf", ["--user", "0:0"]) != a  # the run id is in the names


# --- readiness and the ways it fails --------------------------------------------------------------------------------

def test_the_server_is_ready_when_the_image_says_healthy_and_not_before(tmp_path, monkeypatch):
    docker = FakeDocker(health=("starting", "starting", "healthy"))
    monkeypatch.setattr(ex, "docker", docker)
    ex.hold_local(RUN, spec_of(tmp_path))
    assert len(docker.named("inspect")) == 3 and not docker.named("rm")


def test_an_image_without_a_healthcheck_is_ready_when_its_log_says_the_server_listens(tmp_path, monkeypatch):
    docker = FakeDocker(health=("none",), logs=LOG)
    monkeypatch.setattr(ex, "docker", docker)
    ex.hold_local(RUN, spec_of(tmp_path))
    assert docker.named("logs")


@pytest.mark.parametrize("fail, state, health, logs, message", [
    ({("network", "create"): "Error response: all predefined address pools have been fully subnetted"}, "running", ("healthy",), "", "address pools are used up"),
    ({("run", None): "no space left"}, "running", ("healthy",), "", "cannot start the model server: no space left"),
    ({}, "exited", ("starting",), "error: failed to load model: out of memory", "stopped before it was ready: error: failed to load model: out of memory"),
    ({}, "running", ("unhealthy",), "the health check failed", "is unhealthy: the health check failed"),
])
def test_a_server_that_cannot_start_or_load_fails_as_infrastructure_and_releases_what_it_made(tmp_path, monkeypatch, fail, state, health, logs, message):
    docker = FakeDocker(fail=fail, state=state, health=health, logs=logs)
    monkeypatch.setattr(ex, "docker", docker)
    with pytest.raises(ex.ExecutorError, match=message):
        ex.hold_local(RUN, spec_of(tmp_path))
    assert ("stop", "-t", "10", f"wb-eval-model-{RUN}") in docker.calls and ("rm", "-f", f"wb-eval-model-{RUN}") in docker.calls
    assert ("network", "rm", f"wb-eval-held-{RUN}") in docker.calls


def test_a_server_not_ready_in_time_fails_with_the_last_300_characters_of_its_log(tmp_path, monkeypatch):
    log = "x" * 500 + "THE END"
    docker = FakeDocker(health=("starting",), logs=log)
    monkeypatch.setattr(ex, "docker", docker)
    clock = iter(range(0, 10000, 400))
    monkeypatch.setattr(ex.time, "monotonic", lambda: next(clock))
    with pytest.raises(ex.ExecutorError) as e:
        ex.hold_local(RUN, spec_of(tmp_path, load_timeout_seconds=900))
    message = str(e.value)
    assert "not ready within 900 seconds (load_timeout_seconds)" in message and message.endswith("THE END")
    assert message.split(": ", 1)[1].count("x") == 293  # 300 characters of log, "THE END" included
    assert ("network", "rm", f"wb-eval-held-{RUN}") in docker.calls


def test_the_weights_must_exist(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    with pytest.raises(ex.ExecutorError, match="are not a file"):
        ex.hold_local(RUN, spec_of(tmp_path, weights=str(tmp_path / "absent.gguf")))
    assert not docker.calls


def test_release_stops_removes_and_drops_the_network_and_is_safe_twice(monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.release_local(RUN)
    assert docker.calls == [("stop", "-t", "10", f"wb-eval-model-{RUN}"), ("rm", "-f", f"wb-eval-model-{RUN}"), ("network", "rm", f"wb-eval-held-{RUN}")]
    gone = FakeDocker(fail={("network", "rm"): "Error: No such network"})
    monkeypatch.setattr(ex, "docker", gone)
    ex.release_local(RUN)
    assert len(gone.named("network", "rm")) == 1  # "no such network" is the end of it
    busy = FakeDocker(fail={("network", "rm"): "network has active endpoints"})
    monkeypatch.setattr(ex, "docker", busy)
    ex.release_local(RUN)
    assert len(busy.named("network", "rm")) == 5  # tried again, then given up: an orphan is found by its label


def test_the_version_line_is_read_in_a_container_with_no_network(monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    assert ex.local_server_version("cpu") == "version: 0.5.0-dev (build 11277, commit eae11d221)"
    run = docker.named("run")[0]
    assert run[run.index("--network") + 1] == "none" and ["--cap-drop", "ALL"] in pairs(run) and "--rm" in run and run[-1] == "--version"


def test_the_host_cpu_count_is_asked_of_docker(monkeypatch):
    monkeypatch.setattr(ex, "docker", FakeDocker())
    assert ex.host_cpus() == 14
    monkeypatch.setattr(ex, "docker", lambda *a, **k: subprocess.CompletedProcess(a, 0, "x\n", ""))
    with pytest.raises(ex.ExecutorError, match="how many CPUs"):
        ex.host_cpus()


# --- the run container ----------------------------------------------------------------------------------------------------

def run_argv(tmp_path, network="proxy", pass_names=(), env=None, local=True):
    runner = tmp_path / "run-prompt.sh"
    runner.write_text("#!/bin/bash\n")
    root = tmp_path / "run"
    (root / "case").mkdir(parents=True, exist_ok=True)
    return ex.command(["bash", "/wb/run-prompt.sh"], str(root), cwd=str(root / "case"), env=env or {"PATH": "/usr/bin"}, runner=str(runner),
                      pass_names=list(pass_names), network=network, model="local/example-coder@047bf46455a5", run_id=RUN,
                      **({"local": {"context": 32768}} if local else {}))


def test_a_local_run_is_on_its_own_network_only_with_no_proxy_and_no_key(tmp_path):
    argv, name = run_argv(tmp_path)
    assert name == f"wb-eval-run-{RUN}" and argv.count("--network") == 1 and argv[argv.index("--network") + 1] == f"wb-eval-held-{RUN}"
    assert f"LOCAL_MODEL_BASE_URL=http://wb-eval-model-{RUN}:8080/v1" in argv and "LOCAL_MODEL_CONTEXT=32768" in argv
    text = " ".join(argv)
    assert not any(k in text for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "wb-eval-proxy", "wb-eval-net-"))
    assert not any(a.endswith(("API_KEY", "_TOKEN")) or "KEY=" in a for a in argv)
    assert ["--cap-drop", "ALL"] in pairs(argv) and ["--security-opt", "no-new-privileges"] in pairs(argv) and "--pull=never" in argv
    assert argv.count("-e") == 4  # the two variables of every run, and the two of the model
    assert not {"-p", "--publish", "--add-host", "--privileged"} & set(argv)


def test_a_local_run_that_is_passed_a_hosted_key_never_has_a_key_proxy_for_it(tmp_path):
    argv, _ = run_argv(tmp_path, pass_names=["OPENROUTER_API_KEY"], env={"PATH": "/usr/bin", "OPENROUTER_API_KEY": "fake-real-key"})
    assert "fake-real-key" not in " ".join(argv) and not any(a.startswith("OPENROUTER_BASE_URL") for a in argv)  # the placeholder, if anything
    assert argv.count("--network") == 1 and argv[argv.index("--network") + 1] == f"wb-eval-held-{RUN}"


def test_a_command_with_no_network_stays_on_none_even_for_a_local_model(tmp_path):
    argv, _ = run_argv(tmp_path, network="none")
    assert argv[argv.index("--network") + 1] == "none" and not any(a.startswith("LOCAL_MODEL") for a in argv)


def test_without_local_the_arguments_are_those_of_a_hosted_run(tmp_path):
    argv, _ = run_argv(tmp_path, local=False)
    assert argv[argv.index("--network") + 1] == ex.names()["network"] and f"HTTPS_PROXY=http://{ex.names()['proxy']}:8888" in argv
    assert not any(a.startswith("LOCAL_MODEL") for a in argv)


def test_the_run_names_carry_the_model_server(tmp_path):
    assert ex.run_names(RUN)["model"] == f"wb-eval-model-{RUN}"
    with pytest.raises(ex.ExecutorError):
        ex.run_names("short")
