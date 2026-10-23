"""Docker tests of a local model's model server (backlog N14): opt-in, because they need docker, images already on the machine and,
for the second group, a real model file. Nothing here calls a hosted model, a key or the network beyond what is named below.

Group 1, WB_LOCAL_MODEL_DOCKER_TESTS=1: the model server is a stand-in (evals/tests/local_model_standin/, built locally from an image that
is already on the machine, never pulled). The run is the real thing: run-prompt.sh in the eval image, started by the executor on the
run's internal network, with OpenCode talking to the stand-in. It shows that a run gets a reply and a `usage` through the server, that
neither the run container nor the server can reach the host, the gateway, Docker's model runner or a public address, that two concurrent
local runs cannot reach each other's server, and that nothing is left after a run, a failed start or a stopped run.

Group 2, WB_LOCAL_MODEL_REAL_SERVER_TESTS=1: the pinned llama.cpp server image (evals/local-model-server.json, pulled once with
`python3 evals/executor.py pull-local-server`) and one tiny GGUF from the ggml-org organisation on Hugging Face, at a pinned commit,
its sha256 checked before use (WB_LOCAL_MODEL_TINY_GGUF names a copy already on the machine; otherwise it is downloaded once, 1.2 MB).
It shows the server becoming healthy as a user that is not root on a read-only root, answering a chat completion with a `usage` to a
container on its network, and how long the load takes, the first time and the second.

The eval image is the one of the current definition (evals/executor.py names()); WB_LOCAL_MODEL_TEST_IMAGE names another image that has
bash, curl, python3 and opencode (a machine that has not built the current definition). WB_LOCAL_MODEL_TEST_BASE names the image the
stand-in is built from (it needs python3; default: the key proxy's image of the definition). Everything the tests create is labelled
wb.eval=1 and wb.n14.test=1 and is removed when they end.

Run: WB_LOCAL_MODEL_DOCKER_TESTS=1 uv run --with pytest pytest evals/tests/test_local_model_docker.py -s
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STANDIN = HERE / "local_model_standin"
STANDIN_ON = os.environ.get("WB_LOCAL_MODEL_DOCKER_TESTS") == "1"
REAL_ON = os.environ.get("WB_LOCAL_MODEL_REAL_SERVER_TESTS") == "1"
TEST_LABEL = "wb.n14.test=1"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ds = load(HERE / "docker_support.py", "docker_support_for_local_models")
lm = load(REPO / "evals" / "local_models.py", "local_models_for_docker_tests")
gg = load(HERE / "test_local_models.py", "local_models_tests_for_docker")
docker = ds.docker

TINY = {"url": "https://huggingface.co/ggml-org/models-moved/resolve/ae8874f38083c93b5449892ad5dc37b7b97e7b65/tinyllamas/stories260K.gguf",
        "sha256": "047bf46455a544931cff6fef14d7910154c56afbc23ab1c5e56a72e69912c04b", "size": 1185376}

stand_in = pytest.mark.skipif(not STANDIN_ON, reason="set WB_LOCAL_MODEL_DOCKER_TESTS=1 (needs docker and images already on the machine)")
real_server = pytest.mark.skipif(not REAL_ON, reason="set WB_LOCAL_MODEL_REAL_SERVER_TESTS=1 (needs the pinned server image and a tiny GGUF)")


@pytest.fixture(scope="module")
def ex():
    module = ds.load_executor("executor_local_model_docker")
    return module


@pytest.fixture(scope="module")
def run_image(ex):
    image = os.environ.get("WB_LOCAL_MODEL_TEST_IMAGE") or ex.names()["image"]
    if docker("image", "inspect", image, check=False).returncode != 0:
        pytest.skip(f"the eval image {image} is not on this machine (build it, or name another with WB_LOCAL_MODEL_TEST_IMAGE)")
    return image


@pytest.fixture(scope="module")
def standin_image(ex):
    base = os.environ.get("WB_LOCAL_MODEL_TEST_BASE") or ex.names()["keys_image"]
    if docker("image", "inspect", base, check=False).returncode != 0:
        pytest.skip(f"the stand-in's base image {base} is not on this machine (name one with python3 in WB_LOCAL_MODEL_TEST_BASE)")
    tag = f"wb-n14-standin:{hashlib.sha256((STANDIN / 'server.py').read_bytes() + (STANDIN / 'Dockerfile').read_bytes()).hexdigest()[:12]}"
    built = docker("image", "inspect", tag, check=False).returncode != 0
    if built:
        docker("build", "--pull=false", "-q", "--label", "wb.eval=1", "--label", TEST_LABEL, "--build-arg", f"BASE={base}", "-t", tag, str(STANDIN))
    yield tag
    if built:
        docker("rmi", "-f", tag, check=False)


@pytest.fixture()
def weights(tmp_path):
    return gg.gguf(tmp_path / "weights" / "example-coder.gguf")


@pytest.fixture()
def patched(ex, run_image, standin_image, monkeypatch):
    """The executor of these tests: the eval image of the machine, and the stand-in in the model server's place."""
    names = ex.names()
    monkeypatch.setattr(ex, "names", lambda folder=ex.DEFINITION: {**names, "image": run_image})
    monkeypatch.setattr(ex, "local_server", lambda accelerator="cpu", platform=None, pins=None: {
        "image": standin_image, "index_digest": "sha256:" + "0" * 64, "manifest_digest": "sha256:" + "0" * 64, "platform": ex.image_platform()})
    return ex


def spec_of(weights, **changes):
    return {"alias": "example-coder@047bf46455a5", "weights": str(weights), "context": 4096, "memory_gb": 2, "accelerator": "cpu", "cpus": 2,
            "load_timeout_seconds": 120, **changes}


def run_in(ex, run_id, script, root, image_runner=None, timeout=120):
    """script in a container of the run run_id, started as a local run is (its network is the run's own; the server is up)."""
    # security-scan: allow shell-string -- every script is a literal of this file, run inside the test's own container
    argv, name = ex.command(["bash", "-c", script], str(root), cwd=str(Path(root) / "case"), env={"PATH": os.environ.get("PATH", "")},
                            runner=image_runner, pass_names=[], network="proxy", model="local/example-coder@047bf46455a5", run_id=run_id,
                            local={"context": 4096})
    argv[argv.index("--name"):argv.index("--name")] = ["--label", TEST_LABEL]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    finally:
        ex.remove(name)


def run_folder(tmp_path, name="run"):
    folder = tmp_path / name
    (folder / "case").mkdir(parents=True)
    (folder / "out").mkdir()
    (folder / "prompt.md").write_text("Say hello.\n")
    for p in (folder, folder / "case", folder / "out"):
        os.chmod(p, 0o777)  # the image's user is not the caller's
    return folder


def gone(ex, *run_ids):
    containers, networks = ds.leftovers(ex, run_ids)
    return containers == [] and networks == []


# --- group 1: the stand-in -------------------------------------------------------------------------------------------------------------

@stand_in
def test_a_run_of_run_prompt_in_the_eval_image_gets_a_reply_and_a_usage_through_the_model_server(patched, weights, tmp_path):
    ex = patched
    kit = load(REPO / "evals" / "execution.py", "execution_for_local_model_docker")
    er = load(REPO / "evals" / "eval_run.py", "eval_run_for_local_model_docker")
    kit.load_executor = lambda: ex  # the kit's executor is the patched one
    folder = run_folder(tmp_path)
    model = "local/example-coder@047bf46455a5"
    runner = str(REPO / "adapters" / "agents-dir" / "run-prompt.sh")
    stat = lm.stat_of(str(weights))
    box = {"root": str(folder), "runner": runner, "pass": [], "network": "proxy", "model": model,
           "local": {"alias": model[len("local/"):], "weights": str(weights), "stat": stat, "context": 4096, "memory_gb": 2,
                     "accelerator": "cpu", "cpus": 2, "load_timeout_seconds": 120}}
    cmd = ["bash", runner, "--prompt-file", str(folder / "prompt.md"), "--cwd", str(folder / "case"), "--model", model, "--out", str(folder / "out")]
    started = time.monotonic()
    result = kit.run_group(cmd, 240, cwd=str(folder), env={"PATH": os.environ.get("PATH", "")}, box=box)
    assert result.returncode == 0, result.stderr
    assert (folder / "out" / "response.md").read_text().strip() == "stand-in reply"
    timing = json.loads((folder / "out" / "timing.json").read_text())
    assert timing["total_tokens"] == 14 and timing["exit_code"] == 0
    usage = er.usage_from_stream((folder / "out" / "stream.jsonl").read_text())
    assert usage is not None and usage["input"] + usage["output"] > 0 and set(usage) == {"input", "output", "cache_read", "cache_write"}
    print(f"\nN14 dry run through the stand-in: reply and usage {usage} in {time.monotonic() - started:.1f} s, opencode needed no download")
    # nothing is left: the server, the run container and the network are gone
    left = docker("ps", "-a", "--filter", "label=wb.eval=1", "--filter", f"label={TEST_LABEL}", "--format", "{{.Names}}").stdout.split()
    assert [n for n in left if n.startswith(("wb-eval-model-", "wb-eval-run-"))] == []
    assert not kit.LOCAL_HELD and not kit.HELD


@stand_in
def test_neither_the_run_nor_the_server_reaches_the_host_the_gateway_the_model_runner_or_a_public_address(patched, weights, tmp_path):
    ex = patched
    run_id = ex.new_run_id()
    ex.hold_local(run_id, spec_of(weights))
    try:
        script = ('for h in host.docker.internal gateway.docker.internal model-runner.docker.internal 1.1.1.1 example.com 8.8.8.8; do '
                  'if curl -s -m 5 -o /dev/null "http://$h/"; then echo "REACHED $h"; else echo "blocked $h"; fi; done; '
                  f'curl -s -m 5 http://wb-eval-model-{run_id}:8080/health && echo " own server answers"')
        r = run_in(patched, run_id, script, run_folder(tmp_path))
        assert r.returncode == 0, r.stderr
        assert "REACHED" not in r.stdout and r.stdout.count("blocked") == 6 and "own server answers" in r.stdout, r.stdout
        from_server = docker("exec", f"wb-eval-model-{run_id}", "python3", "-c", PROBE, check=False)
        assert from_server.returncode == 0 and "REACHED" not in from_server.stdout and from_server.stdout.count("blocked") == 6, from_server.stdout + from_server.stderr
    finally:
        ex.release_local(run_id)
    assert gone(ex, run_id)


PROBE = '''
import socket, urllib.request
for h in ("host.docker.internal", "gateway.docker.internal", "model-runner.docker.internal", "1.1.1.1", "example.com", "8.8.8.8"):
    try:
        urllib.request.urlopen("http://" + h + "/", timeout=5)
        print("REACHED", h)
    except Exception:
        print("blocked", h)
'''


@stand_in
def test_two_concurrent_local_runs_cannot_reach_each_others_server(patched, weights, tmp_path):
    ex = patched
    a, b = ex.new_run_id(), ex.new_run_id()
    ex.hold_local(a, spec_of(weights))
    try:
        ex.hold_local(b, spec_of(weights))
        try:
            address = docker("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", f"wb-eval-model-{b}").stdout.strip()
            assert address
            script = (f'curl -s -m 5 http://wb-eval-model-{a}:8080/health >/dev/null && echo "own ok"; '
                      f'curl -s -m 5 http://wb-eval-model-{b}:8080/health >/dev/null && echo "REACHED other by name" || echo "blocked other by name"; '
                      f'curl -s -m 5 http://{address}:8080/health >/dev/null && echo "REACHED other by address" || echo "blocked other by address"')
            r = run_in(ex, a, script, run_folder(tmp_path))
            assert "own ok" in r.stdout and "blocked other by name" in r.stdout and "blocked other by address" in r.stdout and "REACHED" not in r.stdout, r.stdout + r.stderr
            # and the other way round, from the server of one to the other
            there = docker("exec", f"wb-eval-model-{a}", "python3", "-c",
                           f"import urllib.request\ntry:\n urllib.request.urlopen('http://{address}:8080/health', timeout=5); print('REACHED')\nexcept Exception:\n print('blocked')",
                           check=False)
            assert there.stdout.strip() == "blocked", there.stdout + there.stderr
        finally:
            ex.release_local(b)
    finally:
        ex.release_local(a)
    assert gone(ex, a, b)


@stand_in
def test_a_server_that_answers_503_while_it_loads_is_waited_for_past_what_the_default_health_check_would_allow(patched, tmp_path):
    """The pinned image's health check is `curl -f /health`, which fails with 503 while the weights load: with docker's defaults
    (no start period, 3 retries) at an interval of 2 s the container is `unhealthy` after about 6 s. The start period of the load
    limit keeps it `starting` instead. The stand-in answers 503 for 14 s, as its weights file says."""
    ex = patched
    slow = tmp_path / "slow" / "model.gguf"
    slow.parent.mkdir()
    slow.write_bytes(b"SLOW 14\n")
    run_id = ex.new_run_id()
    started = time.monotonic()
    held = ex.hold_local(run_id, spec_of(slow, load_timeout_seconds=90))
    try:
        assert 10 <= time.monotonic() - started < 60 and held["seconds"] >= 10, held
        health = docker("inspect", "--format", "{{.State.Health.Status}}", held["model"]).stdout.strip()
        assert health == "healthy"
    finally:
        ex.release_local(run_id)
    assert gone(ex, run_id)


@stand_in
def test_a_server_that_never_finishes_loading_fails_when_the_load_limit_is_reached(patched, tmp_path):
    ex = patched
    slow = tmp_path / "never" / "model.gguf"
    slow.parent.mkdir()
    slow.write_bytes(b"SLOW 600\n")
    run_id = ex.new_run_id()
    with pytest.raises(ex.ExecutorError, match=r"(not ready within 12 seconds|is unhealthy)"):
        ex.hold_local(run_id, spec_of(slow, load_timeout_seconds=12))
    assert gone(ex, run_id)


@stand_in
def test_a_failed_start_and_a_stopped_run_leave_nothing_behind(patched, weights, tmp_path, monkeypatch):
    ex = patched
    # a server that never becomes ready: the weights file is missing at the mount, so the start fails and releases what it made
    run_id = ex.new_run_id()
    monkeypatch.setattr(ex, "local_server", lambda accelerator="cpu", platform=None, pins=None: {
        "image": "wb-n14-image-that-does-not-exist:none", "index_digest": "sha256:" + "0" * 64, "manifest_digest": "sha256:" + "0" * 64,
        "platform": ex.image_platform()})
    with pytest.raises(ex.ExecutorError, match="cannot start the model server"):
        ex.hold_local(run_id, spec_of(weights))
    assert gone(ex, run_id)


@stand_in
def test_a_stopped_event_releases_the_server_of_a_run_still_in_progress(patched, weights, tmp_path):
    ex = patched
    kit = load(REPO / "evals" / "execution.py", "execution_for_local_model_stop")
    kit.load_executor = lambda: ex
    folder = run_folder(tmp_path)
    model = "local/example-coder@047bf46455a5"
    box = {"root": str(folder), "network": "proxy", "pass": [], "model": model,
           "local": {"alias": model[len("local/"):], "weights": str(weights), "stat": lm.stat_of(str(weights)), "context": 4096, "memory_gb": 2,
                     "accelerator": "cpu", "cpus": 2, "load_timeout_seconds": 120}}
    outcome = {}

    def work():
        try:
            outcome["result"] = kit.run_group(["bash", "-c", "sleep 120"], 200, cwd=str(folder), env={"PATH": os.environ.get("PATH", "")}, box=box)
        except BaseException as e:  # a stopped run ends however it ends
            outcome["error"] = e
    thread = threading.Thread(target=work)
    thread.start()
    try:
        deadline = time.monotonic() + 90
        while not kit.CONTAINERS and time.monotonic() < deadline:
            time.sleep(0.5)
        assert kit.CONTAINERS and kit.LOCAL_HELD, "the run did not start"
        run_ids = set(kit.LOCAL_HELD)
        assert not gone(ex, *run_ids)
        kit.stop_all_groups(grace=2.0)
    finally:
        thread.join(timeout=60)
        kit.STOPPING.clear()
    assert not thread.is_alive()
    assert gone(ex, *run_ids) and not kit.LOCAL_HELD and not kit.CONTAINERS


# --- group 2: the pinned server image and a tiny model ----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tiny_gguf(tmp_path_factory):
    explicit = os.environ.get("WB_LOCAL_MODEL_TINY_GGUF")
    path = Path(explicit) if explicit else tmp_path_factory.mktemp("tiny") / "stories260K.gguf"
    if not path.exists():
        with urllib.request.urlopen(TINY["url"], timeout=120) as r, open(path, "wb") as f:  # the one download of these tests, 1.2 MB
            data = r.read(TINY["size"] + 1)  # never more than the pinned size
            assert len(data) == TINY["size"], "the download is not the size of the pinned file"
            f.write(data)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == TINY["sha256"] and path.stat().st_size == TINY["size"], "the tiny model is not the file whose checksum is pinned"
    return path


@real_server
def test_the_pinned_server_becomes_healthy_as_a_user_on_a_read_only_root_and_answers_a_chat_completion_with_a_usage(ex, run_image, tiny_gguf, tmp_path):
    ex.verify_local_server("cpu")
    spec = {"alias": "tiny@047bf46455a5", "weights": str(tiny_gguf), "context": 128, "memory_gb": 2, "accelerator": "cpu", "cpus": 2,
            "load_timeout_seconds": 300}
    times = []
    for attempt in (1, 2):  # the second load reads the weights from the page cache
        run_id = ex.new_run_id()
        held = ex.hold_local(run_id, spec)
        times.append(held["seconds"])
        try:
            name = held["model"]
            info = json.loads(docker("inspect", "--format", "{{json .}}", name).stdout)
            assert info["State"]["Health"]["Status"] == "healthy" and info["HostConfig"]["ReadonlyRootfs"] is True
            assert info["Config"]["User"] in ("65534:65534", f"{os.getuid()}:{os.getgid()}") and not info["Config"]["User"].startswith("0")
            assert info["HostConfig"]["CapDrop"] == ["ALL"] and info["HostConfig"]["Memory"] == info["HostConfig"]["MemorySwap"] == 2 << 30
            assert docker("exec", name, "id", "-u", check=False).stdout.strip() not in ("0", "")
            assert docker("exec", name, "touch", "/should-not-be-written", check=False).returncode != 0
            body = json.dumps({"model": spec["alias"], "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 8, "temperature": 0})
            script = f"curl -s -m 120 http://{name}:8080/v1/chat/completions -H 'Content-Type: application/json' -d '{body}'"
            argv = ["docker", "run", "--rm", ex.NO_PULL, "--cap-drop", "ALL", "--label", "wb.eval=1", "--label", TEST_LABEL,
                    "--network", info["HostConfig"]["NetworkMode"], run_image, "bash", "-c", script]  # security-scan: allow shell-string -- built from a literal and the test's own request
            answered = subprocess.run(argv, capture_output=True, text=True, timeout=240)
            reply = json.loads(answered.stdout)
            assert reply["choices"][0]["message"]["role"] == "assistant"
            assert reply["usage"]["prompt_tokens"] > 0 and reply["usage"]["completion_tokens"] > 0 and reply["usage"]["total_tokens"] > 0
        finally:
            ex.release_local(run_id)
        assert gone(ex, run_id)
    print(f"\nN14 real server (llama.cpp {ex.local_server_version('cpu')}): healthy after {times[0]} s the first time and {times[1]} s the second "
          f"(1.2 MB model; the load of a real model is the size of the file read from disk, then from the page cache)")
