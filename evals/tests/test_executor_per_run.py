"""Offline tests of the key proxy and the network that each run gets (evals/executor.py hold() and release()), of the
labels and log limits every container of the harness carries, and of what is read back from a run's meter. docker is a
recording stand-in; every key is a fake one.

Run: uv run --with pytest pytest evals/tests/test_executor_per_run.py
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
spec = importlib.util.spec_from_file_location("executor_per_run", SCRIPT)
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

FLOOR, STRONG = "OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"
KEY = "fake-floor-key-for-the-per-run-tests-0012"


@pytest.fixture(autouse=True)
def gate(tmp_path, monkeypatch):
    entry = {"aliases": ["f-short"], "adapter": "h", "price_source": "https://example.test/price", "run_token_budget": 4321}
    models = {"floor": {**entry, "pass_env": [FLOOR], "route": "openrouter", "provider_pin": "deepinfra",
                        "upstream_models": ["vendor/floor-1", "vendor/floor-2"]},
              "strong": {**entry, "aliases": [], "pass_env": [STRONG], "route": "anthropic", "provider_pin": None,
                         "upstream_models": ["strong-1"]}}
    (tmp_path / "gate.json").write_text(json.dumps({"models": models}))
    monkeypatch.setattr(ex, "GATE_FILE", str(tmp_path / "gate.json"))
    monkeypatch.setattr(ex, "KEYPROXY_READY_SECONDS", 0.5)
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def arm64_host():
    """The tests below are about the executor, not about the machine they run on: docker host is taken for arm64."""
    ex._NATIVE["platform"] = "linux/arm64"
    yield
    ex._NATIVE.clear()


class FakeDocker:
    """docker as hold() and release() see it. fail = {(command, subcommand or None): stderr} makes that call fail."""

    def __init__(self, fail=None, listening=True):
        self.calls, self.envs, self.fail, self.listening = [], [], fail or {}, listening

    def __call__(self, *args, env=None, check=True, timeout=1800):
        self.calls.append(args)
        self.envs.append(dict(env or {}))
        key = (args[0], args[1] if args[0] in ("network", "image") else None)
        if key in self.fail:
            return subprocess.CompletedProcess(["docker", *args], 1, "", self.fail[key])
        err = "keyproxy: listening on port 8890, forwarding /api/v1/ to https://openrouter.ai through the egress proxy\n" \
            if args[0] == "logs" and self.listening else ""
        return subprocess.CompletedProcess(["docker", *args], 0, "", err)

    def named(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == prefix]


def meter_dir(tmp_path):
    folder = tmp_path / "meter"
    folder.mkdir()
    return str(folder)


def pairs(argv):
    return [list(argv[i:i + 2]) for i in range(len(argv) - 1)]


def test_a_run_gets_a_network_and_a_key_proxy_named_after_its_id_with_the_models_own_arguments(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    run_id, folder = ex.new_run_id(), meter_dir(tmp_path)
    held = ex.hold(run_id, "f-short", {FLOOR: KEY, "PATH": "/usr/bin"}, "proxy", meter_dir=folder)
    n = ex.names()
    assert held == {"keys": f"wb-eval-keys-{run_id}", "network": f"wb-eval-held-{run_id}", "route": "openrouter",
                    "meter": os.path.join(folder, f"{run_id}.json"), "model": "floor"}
    created = docker.named("network", "create")[0]
    assert "--internal" in created and created[-1] == f"wb-eval-held-{run_id}"
    assert ["--label", "wb.eval=1"] in pairs(created) and ["--label", f"wb.eval.run={run_id}"] in pairs(created)
    run = docker.named("run")[0]
    assert ex.NO_PULL in run and run.index(ex.NO_PULL) < run.index(n["keys_image"])  # an image is never fetched in a run's path
    assert run[run.index("--network") + 1] == ex.route_network("openrouter", n)  # first on its provider's route network
    assert ["--name", f"wb-eval-keys-{run_id}"] in pairs(run) and ["--cap-drop", "ALL"] in pairs(run)
    assert ["--label", "wb.eval=1"] in pairs(run) and ["--label", f"wb.eval.run={run_id}"] in pairs(run)
    assert ["--log-opt", "max-size=10m"] in pairs(run) and ["--log-opt", "max-file=3"] in pairs(run)
    assert not any(a in ("-p", "--publish", "--network=host") for a in run) and "--restart" not in run
    assert ["-e", FLOOR] in pairs(run) and f"HTTPS_PROXY=http://{n['proxy']}:{ex.PROXY_PORT}" in run
    assert all(KEY not in a for c in docker.calls for a in c)  # the key travels in the docker client's environment only
    assert docker.envs[docker.calls.index(run)][FLOOR] == KEY
    assert f"{os.path.realpath(folder)}:/meter" in run  # the meter folder: mounted into the key proxy
    tail = run[run.index(n["keys_image"]) + 1:]
    assert list(tail) == ["--route=/etc/keyproxy/route-openrouter.json", f"--run={run_id}", "--model=floor",
                          f"--meter=/meter/{run_id}.json", "--budget-tokens=4321",
                          "--upstream-model=vendor/floor-1", "--upstream-model=vendor/floor-2", "--pin=deepinfra"]
    assert ("network", "connect", f"wb-eval-held-{run_id}", f"wb-eval-keys-{run_id}") in docker.calls  # and then on the run's own
    assert oct(os.stat(folder).st_mode & 0o777) == "0o700"  # the caller's alone, never world-writable
    if sys.platform.startswith("linux"):  # a bind mount keeps numeric owners there: the proxy writes as the caller
        assert ["--user", f"{os.getuid()}:{os.getgid()}"] in pairs(run)
    else:
        assert "--user" not in run


def test_a_web_runs_network_is_not_internal_and_the_anthropic_route_has_no_pin(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    run_id = ex.new_run_id()
    ex.hold(run_id, "strong", {STRONG: "fake-token-0013"}, "open", meter_dir=meter_dir(tmp_path))
    assert "--internal" not in docker.named("network", "create")[0]
    tail = docker.named("run")[0]
    assert not [a for a in tail if a.startswith("--pin")] and "--upstream-model=strong-1" in tail
    assert "--route=/etc/keyproxy/route-anthropic.json" in tail


def test_a_test_stand_in_replaces_the_provider_and_the_budget_can_be_given(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    cafile = tmp_path / "ca.pem"
    cafile.write_text("pem")
    ex.hold(ex.new_run_id(), "floor", {FLOOR: KEY}, "proxy", meter_dir=meter_dir(tmp_path), upstream="https://standin:8443",
            cafile=str(cafile), egress=False, budget=77)
    run = docker.named("run")[0]
    assert "--upstream=https://standin:8443" in run and "--cafile=/etc/keyproxy/upstream-ca.pem" in run and "--budget-tokens=77" in run
    assert not any(a.startswith("HTTPS_PROXY") for a in run)  # reached directly, not through the egress proxy
    assert f"{os.path.realpath(cafile)}:/etc/keyproxy/upstream-ca.pem:ro" in run


@pytest.mark.parametrize("failing, message", [
    (("network", "create"), "cannot create the run's network"),
    (("run", None), "cannot start the key proxy"),
    (("network", "connect"), "cannot connect the key proxy to the run's network"),
])
def test_a_key_proxy_that_cannot_start_leaves_nothing_behind(tmp_path, monkeypatch, failing, message):
    docker = FakeDocker(fail={failing: "boom"})
    monkeypatch.setattr(ex, "docker", docker)
    run_id = ex.new_run_id()
    with pytest.raises(ex.ExecutorError) as e:
        ex.hold(run_id, "floor", {FLOOR: KEY}, "proxy", meter_dir=meter_dir(tmp_path))
    assert message in str(e.value) and KEY not in str(e.value)
    assert ("rm", "-f", f"wb-eval-keys-{run_id}") in docker.calls  # the proxy, if it started, is removed
    assert any(c[:3] == ("network", "rm", f"wb-eval-held-{run_id}") for c in docker.calls)  # and the network


def test_a_key_proxy_that_never_listens_is_an_error_that_names_no_key_and_is_removed(tmp_path, monkeypatch):
    docker = FakeDocker(listening=False)
    monkeypatch.setattr(ex, "docker", docker)
    run_id = ex.new_run_id()
    with pytest.raises(ex.ExecutorError) as e:
        ex.hold(run_id, "floor", {FLOOR: KEY}, "proxy", meter_dir=meter_dir(tmp_path))
    assert "did not start" in str(e.value) and KEY not in str(e.value)
    assert ("rm", "-f", f"wb-eval-keys-{run_id}") in docker.calls


def test_when_docker_has_no_address_pool_left_the_error_is_clear_and_no_run_goes_on_another_network(tmp_path, monkeypatch):
    """About 31 bridge networks fit the default pools. At the limit the run's network cannot be made: a stated
    infrastructure error, and nothing starts, so a run is never put on a network that is not its own."""
    pool = "Error response from daemon: all predefined address pools have been fully subnetted"
    docker = FakeDocker(fail={("network", "create"): pool})
    monkeypatch.setattr(ex, "docker", docker)
    with pytest.raises(ex.ExecutorError) as e:
        ex.hold(ex.new_run_id(), "floor", {FLOOR: KEY}, "proxy", meter_dir=meter_dir(tmp_path))
    assert "address pools are used up" in str(e.value) and "about 31" in str(e.value)
    assert not docker.named("run")  # no key proxy, so no run after it either


def test_a_model_without_a_route_a_missing_key_and_a_missing_meter_folder_are_refused_before_docker_is_called(tmp_path, monkeypatch):
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    folder = meter_dir(tmp_path)
    for kwargs, env in (({"model": "not-listed"}, {FLOOR: KEY}), ({"model": "floor"}, {}), ({"model": "floor"}, {FLOOR: "  "}),
                        ({"model": "floor", "meter_dir": str(tmp_path / "none")}, {FLOOR: KEY}),
                        ({"model": "floor", "meter_dir": None}, {FLOOR: KEY}), ({"model": "floor", "budget": 0}, {FLOOR: KEY})):
        with pytest.raises(ex.ExecutorError):
            ex.hold(ex.new_run_id(), kwargs.pop("model"), env, "proxy", **{"meter_dir": folder, **kwargs})
    with pytest.raises(ex.ExecutorError):
        ex.hold("../../etc", "floor", {FLOOR: KEY}, "proxy", meter_dir=folder)  # a run id is 16 hexadecimal characters
    assert docker.calls == []


def test_release_removes_the_key_proxy_and_the_network_is_safe_twice_and_retries_a_busy_network(monkeypatch):
    run_id = ex.new_run_id()
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.release(run_id)
    # SIGTERM first (the proxy records the answers it still holds as unknown), then the removal, then the network
    assert docker.calls == [("stop", "-t", str(ex.STOP_SECONDS), f"wb-eval-keys-{run_id}"), ("rm", "-f", f"wb-eval-keys-{run_id}"),
                            ("network", "rm", f"wb-eval-held-{run_id}")]
    gone = FakeDocker(fail={("network", "rm"): "Error response from daemon: network wb-eval-held-x not found"})
    monkeypatch.setattr(ex, "docker", gone)
    ex.release(run_id)  # nothing to remove: not an error
    assert len(gone.named("network", "rm")) == 1
    busy = FakeDocker(fail={("network", "rm"): "network has active endpoints"})
    monkeypatch.setattr(ex, "docker", busy)
    ex.release(run_id)  # tried again, then given up quietly: P-OPS removes an orphan by its label
    assert len(busy.named("network", "rm")) == 5


# --- labels and log limits on every container the harness starts ---------------------------------------------------


def test_every_run_container_carries_the_labels_of_the_harness_and_of_its_run(tmp_path):
    root = tmp_path / "eval-abc"
    (root / "case").mkdir(parents=True)
    run_id = ex.new_run_id()
    for network in ("none", "proxy", "open"):
        argv, name = ex.command(["true"], str(root), network=network, run_id=run_id)
        assert ["--label", "wb.eval=1"] in pairs(argv) and ["--label", f"wb.eval.run={run_id}"] in pairs(argv)
        assert name == f"wb-eval-run-{run_id}" and ex.run_id_of(name) == run_id
        assert argv[argv.index("run") + 1] == ex.NO_PULL  # a run never makes docker fetch an image
    other, _ = ex.command(["true"], str(root))
    assert ["--label", f"wb.eval.run={run_id}"] not in pairs(other)  # a run's label is its own


def test_the_meter_folder_is_never_mounted_into_a_run(tmp_path, monkeypatch):
    root = tmp_path / "eval-abc"
    (root / "case").mkdir(parents=True)
    folder = ex.meter_folder(str(tmp_path))
    argv, _ = ex.command(["true"], str(root), env={FLOOR: KEY}, pass_names=[FLOOR], network="proxy", model="floor")
    assert folder not in " ".join(argv) and "/meter" not in " ".join(argv)
    assert [argv[i + 1].split(":")[1] for i, a in enumerate(argv) if a == "-v"] == ["/eval"]


def test_the_egress_proxy_starts_with_a_log_limit_and_the_labels(monkeypatch):
    docker = FakeDocker()

    def daemon(*args, env=None, check=True, timeout=1800):
        result = docker(*args, env=env, check=check, timeout=timeout)
        if args[:2] in (("network", "inspect"), ("image", "inspect")) or args[0] == "inspect":
            return subprocess.CompletedProcess(["docker", *args], 1, "", "No such object")
        if args[:2] == ("image", "inspect") or "{{.Id}}" in args:
            return subprocess.CompletedProcess(["docker", *args], 0, "sha256:abc\n", "")
        return result
    monkeypatch.setattr(ex, "docker", daemon)
    monkeypatch.setattr(ex, "published_image", lambda *a, **k: None)
    try:
        ex.ensure()
    except ex.ExecutorError:
        pass  # the stand-in has no image id to answer with; the proxy's start is what is looked at
    run = next(c for c in docker.calls if c[0] == "run")
    assert ["--log-opt", "max-size=10m"] in pairs(run) and ["--log-opt", "max-file=3"] in pairs(run)
    assert ["--label", "wb.eval=1"] in pairs(run) and ["--name", ex.names()["proxy"]] in pairs(run)
    assert ex.NO_PULL in run


# --- what is read back from the run's meter --------------------------------------------------------------------------


def test_the_meter_a_key_proxy_wrote_is_read_back_and_one_that_is_not_in_its_form_is_not(tmp_path):
    good = {"run": "x", "input": 1, "output": 2, "cache_read": 3, "cache_write": 4, "total": 10, "responses": 2, "unknown_responses": 0}
    path = tmp_path / "m.json"
    path.write_text(json.dumps(good))
    assert ex.read_meter(str(path)) == good
    for bad in ({**good, "input": -1}, {**good, "output": True}, {**good, "cache_read": "3"}, {**good, "unknown_responses": None},
                {k: v for k, v in good.items() if k != "cache_write"}, [1, 2]):
        path.write_text(json.dumps(bad))
        assert ex.read_meter(str(path)) is None
    path.write_text("{")
    assert ex.read_meter(str(path)) is None and ex.read_meter(str(tmp_path / "missing.json")) is None


# --- the platform of the docker host: an emulated image is a trial ----------------------------------------------------


@pytest.mark.parametrize("answer, expected", [("aarch64", "linux/arm64"), ("arm64", "linux/arm64"), ("x86_64", "linux/amd64"),
                                              ("amd64", "linux/amd64"), ("riscv64", None), ("", None)])
def test_the_hosts_platform_is_read_from_docker_and_mapped(monkeypatch, answer, expected):
    def docker(*args, env=None, check=True, timeout=1800):
        assert args == ("info", "--format", "{{.Architecture}}")
        return subprocess.CompletedProcess(["docker", *args], 0, answer + "\n", "")
    monkeypatch.setattr(ex, "docker", docker)
    assert ex.host_platform() == expected


def test_ensure_names_the_hosts_platform_beside_the_images(monkeypatch):
    class Daemon:
        def __init__(self):
            self.calls = []

        def __call__(self, *args, env=None, check=True, timeout=1800):
            self.calls.append(args)
            out, code = "", 0
            if args[:2] == ("info", "--format"):
                out = "x86_64\n" if "{{.Architecture}}" in args else "29.0\n"
            elif args[:2] == ("image", "inspect") and "--format" in args:
                out = "sha256:abc\n"
            elif args[0] == "inspect" or args[:2] in (("network", "inspect"), ("image", "inspect")):
                code = 1
            return subprocess.CompletedProcess(["docker", *args], code, out, "No such object" if code else "")
    monkeypatch.setattr(ex, "docker", Daemon())
    environment = ex.ensure()
    assert environment["host_platform"] == "linux/amd64" and environment["image_platform"] in ex.IMAGE_PLATFORMS
