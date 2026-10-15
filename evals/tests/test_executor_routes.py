"""Offline tests of the two key proxy routes of evals/executor.py: the floor model's key and the strong model's
credential are each held by a key proxy of their own, on networks of their own. No docker is called, and every key
is a fake one.

Run: uv run --with pytest pytest evals/tests/test_executor_routes.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "executor.py"
spec = importlib.util.spec_from_file_location("executor_routes", SCRIPT)
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

FOLDER = Path(__file__).resolve().parents[1] / "container" / "keyproxy"
_spec = importlib.util.spec_from_file_location("keyproxy_routes", FOLDER / "keyproxy.py")
kp = importlib.util.module_from_spec(_spec)
_writes = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # a cache folder in evals/container/ would change the definition's hash
try:
    _spec.loader.exec_module(kp)
finally:
    sys.dont_write_bytecode = _writes

STRONG = "CLAUDE_CODE_OAUTH_TOKEN"
FLOOR = "OPENROUTER_API_KEY"
STRONG_KEY = "fake-strong-token-for-the-route-tests-0006"
FLOOR_KEY = "fake-floor-key-for-the-route-tests-0007"


def run_folder(tmp_path):
    root = tmp_path / "eval-abc"
    (root / "case").mkdir(parents=True)
    (root / "out").mkdir()
    (root / "prompt.md").write_text("hello\n")
    return root


def env_pairs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]


def tag():
    return ex.names()["image"].split(":", 1)[1]


PROXY_VARIABLES = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY")


def no_proxy_variable(given):
    """True when none of the environment variables a run is given is a proxy variable, in either case."""
    return not [e for e in given if e.split("=", 1)[0].upper() in PROXY_VARIABLES]


def test_a_strong_run_on_the_proxy_network_gets_a_placeholder_and_its_own_proxy_and_never_the_value(tmp_path):
    root = run_folder(tmp_path)
    argv, _ = ex.command(["true"], str(root), env={STRONG: STRONG_KEY}, pass_names=[STRONG], network="proxy")
    given = env_pairs(argv)
    assert f"{STRONG}=held-by-the-eval-key-proxy" in given and STRONG not in given
    assert f"ANTHROPIC_BASE_URL=http://wb-eval-keys-strong-{tag()}:8891" in given
    assert argv[argv.index("--network") + 1] == f"wb-eval-strong-held-{tag()}"  # its route's held network, nothing else
    assert argv.count("--network") == 1
    assert no_proxy_variable(given)
    assert STRONG_KEY not in " ".join(argv)


def test_a_strong_run_on_the_open_network_joins_the_strong_open_network(tmp_path):
    root = run_folder(tmp_path)
    argv, _ = ex.command(["true"], str(root), env={STRONG: STRONG_KEY}, pass_names=[STRONG], network="open")
    assert argv[argv.index("--network") + 1] == f"wb-eval-strong-open-{tag()}"
    assert f"{STRONG}=held-by-the-eval-key-proxy" in env_pairs(argv) and STRONG_KEY not in " ".join(argv)


@pytest.mark.parametrize("network", ["proxy", "open", "none"])
def test_a_floor_run_gets_its_placeholder_its_proxys_address_and_the_network_of_its_kind(tmp_path, network):
    """The arguments of a floor run in full: on the proxy network the held network, on the open network the open one."""
    root = run_folder(tmp_path)
    n = ex.names()
    argv, _ = ex.command(["true"], str(root), env={FLOOR: FLOOR_KEY, "MODEL_KEY": "v"}, pass_names=[FLOOR, "MODEL_KEY"],
                         network=network)
    tail = argv[argv.index(f"{FLOOR}=held-by-the-eval-key-proxy") - 1:]
    expected = ["-e", f"{FLOOR}=held-by-the-eval-key-proxy", "-e", "MODEL_KEY"]
    if network == "none":
        expected += ["--network", "none"]
    else:
        expected += ["-e", f"OPENROUTER_BASE_URL=http://{n['keys']}:8890/api/v1"]
        # a held run on the proxy network is on the held network and has no proxy variable at all (package SEC)
        expected += ["--network", n["held_network"] if network == "proxy" else n["open_network"]]
    assert tail == expected + [n["image"], "true"]
    assert FLOOR_KEY not in " ".join(argv)


def test_a_command_passed_both_keys_is_refused(tmp_path):
    root = run_folder(tmp_path)
    with pytest.raises(ex.ExecutorError):
        ex.command(["true"], str(root), env={STRONG: STRONG_KEY, FLOOR: FLOOR_KEY}, pass_names=[STRONG, FLOOR], network="proxy")


def test_held_route_names_no_proxy_without_a_network_or_without_a_value():
    assert ex.held_route([STRONG], {STRONG: STRONG_KEY}, "none") is None
    assert ex.held_route([FLOOR], {FLOOR: FLOOR_KEY}, "none") is None
    assert ex.held_route([STRONG], {STRONG: ""}, "proxy") is None
    assert ex.held_route([STRONG], {}, "proxy") is None
    assert ex.held_route([STRONG], {STRONG: STRONG_KEY}, "proxy") == "strong"
    assert ex.held_route([FLOOR], {FLOOR: FLOOR_KEY}, "open") == "floor"


def test_the_strong_proxy_url_has_no_path_and_the_floor_one_keeps_its_prefix():
    strong, floor = ex.keyproxy_url(name="strong"), ex.keyproxy_url()
    assert strong.endswith(":8891") and strong == f"http://wb-eval-keys-strong-{tag()}:8891"
    assert floor.endswith(":8890/api/v1")


class FakeDocker:
    """docker as the key proxy's start sees it, for the strong route."""

    def __init__(self):
        self.calls, self.envs = [], []

    def __call__(self, *args, env=None, check=True, timeout=1800):
        import subprocess
        self.calls.append(args)
        self.envs.append(dict(env or {}))
        out, err, code = "", "", 0
        if args[0] == "inspect":
            code, err = 1, "No such object"
        elif args[0] == "logs":
            err = "keyproxy: listening on port 8891, forwarding /v1/ to https://api.anthropic.com through the egress proxy\n"
        return subprocess.CompletedProcess(["docker", *args], code, out, err)


def test_the_strong_key_proxy_starts_on_its_own_networks_with_its_own_route(monkeypatch):
    n = ex.names()
    docker = FakeDocker()
    monkeypatch.setattr(ex, "docker", docker)
    assert ex.keyproxy(env={STRONG: STRONG_KEY, "PATH": "/usr/bin"}, name="strong") == n["keys_strong"]
    run = next(c for c in docker.calls if c[0] == "run")
    assert all(STRONG_KEY not in a for c in docker.calls for a in c)
    assert docker.envs[docker.calls.index(run)][STRONG] == STRONG_KEY
    assert run[run.index("--network") + 1] == n["strong_network"] and run[run.index("--name") + 1] == n["keys_strong"]
    assert run[run.index(n["keys_image"]) + 1:] == ("--route", "/etc/keyproxy/keyproxy-strong.json")
    assert ("network", "connect", n["strong_open_network"], n["keys_strong"]) in docker.calls
    assert ("network", "connect", n["strong_held_network"], n["keys_strong"]) in docker.calls  # where its held runs reach it


def test_the_strong_route_is_valid_and_a_bad_base_path_is_refused(tmp_path):
    route = kp.load_route(str(FOLDER / "keyproxy-strong.json"))
    assert route["secret"] == STRONG and route["base_path"] == "" and route["prefix"] == "/v1/"
    bad = {**json.loads((FOLDER / "keyproxy-strong.json").read_text()), "base_path": "v1"}
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(kp.RouteError):
        kp.load_route(str(tmp_path / "bad.json"))


# --- package SEC: a held run reaches only its key proxy --------------------------------------------------

GOLDEN = json.loads((Path(__file__).resolve().parent / "goldens" / "executor_argv_before_sec.json").read_text())
CASES = {
    "plain_proxy": dict(env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="proxy"),
    "plain_open": dict(env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="open"),
    "plain_none": dict(env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="none"),
    "floor_open": dict(env={FLOOR: "fake-k", "MODEL_KEY": "v"}, pass_names=[FLOOR, "MODEL_KEY"], network="open"),
    "strong_open": dict(env={STRONG: "fake-k"}, pass_names=[STRONG], network="open"),
    "floor_none": dict(env={FLOOR: "fake-k"}, pass_names=[FLOOR], network="none"),
}
HELD_CASES = {
    "floor_proxy": dict(env={FLOOR: "fake-k", "MODEL_KEY": "v"}, pass_names=[FLOOR, "MODEL_KEY"], network="proxy"),
    "strong_proxy": dict(env={STRONG: "fake-k"}, pass_names=[STRONG], network="proxy"),
}


def like_a_golden(argv, root, name):
    """argv with what changes from run to run replaced as the golden file writes it, and without the two
    arguments that are added on Linux only."""
    kept, skip = [], 0
    for i, a in enumerate(argv):
        if skip:
            skip -= 1
        elif a == "--user":
            skip = 1
        elif a == "HOME=/home/eval" and argv[i - 1] == "-e":
            kept.pop()
        else:
            kept.append(a)
    return [a.replace(tag(), "<TAG>").replace(name, "<NAME>").replace(str(Path(root).resolve()), "<ROOT>")
            .replace(ex.image_platform(), "<PLATFORM>") for a in kept]


def command_of(tmp_path, case):
    root = run_folder(tmp_path)
    argv, name = ex.command(["true"], str(root), **case)
    return like_a_golden(argv, root, name)


@pytest.mark.parametrize("label", sorted(CASES))
def test_every_run_the_held_network_does_not_touch_has_the_arguments_it_had_before(tmp_path, label):
    """The goldens are the arguments command() produced before package SEC: a run with no held key on the proxy
    network, and every run on the open or the no network, is built exactly as it was."""
    assert command_of(tmp_path, CASES[label]) == GOLDEN["unchanged"][label]


@pytest.mark.parametrize("label, held_network", [("floor_proxy", "wb-eval-held-<TAG>"), ("strong_proxy", "wb-eval-strong-held-<TAG>")])
def test_a_held_run_on_the_proxy_network_differs_from_the_old_one_in_its_network_and_its_proxy_variables_only(tmp_path, label, held_network):
    """Against the golden of the defect: the same arguments, with the route's held network in place of the internal
    one, and without HTTPS_PROXY, HTTP_PROXY, https_proxy, http_proxy, NO_PROXY and no_proxy."""
    old = GOLDEN["before_sec_held_proxy"][label]
    expected, i = [], 0
    while i < len(old):
        if old[i] == "-e" and old[i + 1].split("=")[0].upper() in PROXY_VARIABLES:
            i += 2
            continue
        expected.append(old[i])
        i += 1
    assert len(old) - len(expected) == 12  # six variables, each with its -e
    expected[expected.index("--network") + 1] = held_network
    assert command_of(tmp_path, HELD_CASES[label]) == expected


def test_a_held_run_names_only_its_routes_held_network_and_no_proxy_variable_in_any_case(tmp_path):
    """The two things the egress proxy needs to be reached: its network, and its address in a variable."""
    for label, case in HELD_CASES.items():
        argv = command_of(tmp_path / label, case)
        assert argv.count("--network") == 1 and argv[argv.index("--network") + 1].endswith("held-<TAG>")
        assert "wb-eval-proxy-<TAG>" not in " ".join(argv) and "8888" not in " ".join(argv)
        assert no_proxy_variable(env_pairs(argv))


def test_every_route_has_a_held_network_of_its_own_and_the_names_are_different():
    n = ex.names()
    assert ex.held_network("floor") == n["held_network"] == f"wb-eval-held-{tag()}"
    assert ex.held_network("strong") == n["strong_held_network"] == f"wb-eval-strong-held-{tag()}"
    every = [n[k] for k in ("network", "open_network", "held_network", "strong_network", "strong_open_network", "strong_held_network")]
    assert len(set(every)) == 6


class RecordingDocker:
    """docker for ensure() and clean(): nothing exists, every command succeeds, and each call is recorded."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, env=None, check=True, timeout=1800):
        import subprocess
        self.calls.append(args)
        out, code = "", 0
        if args[0] == "info":
            out = "29.0\n"
        elif args[:2] == ("image", "inspect") and "--format" in args:
            out = "sha256:abc\n"
        elif args[0] == "inspect" or args[:2] in (("network", "inspect"), ("image", "inspect")):
            code = 1
        return subprocess.CompletedProcess(["docker", *args], code, out, "No such object" if code else "")


def test_ensure_makes_each_routes_held_network_internal_and_never_connects_the_egress_proxy_to_it(monkeypatch):
    n = ex.names()
    docker = RecordingDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.ensure()
    created = {c[-1]: "--internal" in c for c in docker.calls if c[:2] == ("network", "create")}
    assert created == {n["network"]: True, n["keys_network"]: True, n["open_network"]: False, n["held_network"]: True,
                       n["strong_network"]: True, n["strong_open_network"]: False, n["strong_held_network"]: True}
    connected = [c for c in docker.calls if c[:2] == ("network", "connect")]
    assert connected and all(c[3] == n["proxy"] for c in connected)
    assert {c[2] for c in connected} == {n["network"], n["keys_network"], n["strong_network"]}
    assert not any(n["held_network"] in c or n["strong_held_network"] in c for c in connected)


def test_clean_removes_the_held_networks_too(monkeypatch):
    n = ex.names()
    docker = RecordingDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.clean()
    removed = {c[-1] for c in docker.calls if c[:2] == ("network", "rm")}
    assert {n["held_network"], n["strong_held_network"], n["keys_network"]} <= removed


def test_a_key_proxy_is_never_on_the_network_every_run_without_a_held_key_uses(monkeypatch):
    """The floor key proxy had been on "network" with the non-held proxy runs, which could call it and spend its key."""
    n = ex.names()
    assert ex.places("floor")[1] == n["keys_network"] != n["network"]
    assert ex.places("strong")[1] == n["strong_network"] != n["network"]
    for name, key, internal in (("floor", FLOOR, n["keys_network"]), ("strong", STRONG, n["strong_network"])):
        docker = FakeDocker()
        monkeypatch.setattr(ex, "docker", docker)
        ex.keyproxy(env={key: FLOOR_KEY, "PATH": "/usr/bin"}, name=name)
        run = next(c for c in docker.calls if c[0] == "run")
        assert run[run.index("--network") + 1] == internal
        connects = [c for c in docker.calls if c[:2] == ("network", "connect")]
        assert n["network"] not in [c[2] for c in connects] and n["network"] not in run
        assert [c[2] for c in connects] == [ex.places(name)[2], ex.held_network(name)]


@pytest.mark.parametrize("failing", ["open", "held"])
def test_a_key_proxy_that_cannot_join_a_network_is_removed_before_the_error(monkeypatch, failing):
    """A half-connected proxy must not stay for a later call to reuse by its label."""
    n = ex.names()
    docker = FakeDocker()
    target = n["open_network"] if failing == "open" else n["held_network"]

    def refusing(*args, env=None, check=True, timeout=1800):
        import subprocess
        result = docker(*args, env=env, check=check, timeout=timeout)
        if args[:2] == ("network", "connect") and args[2] == target:
            return subprocess.CompletedProcess(["docker", *args], 1, "", "network is gone")
        return result
    monkeypatch.setattr(ex, "docker", refusing)
    with pytest.raises(ex.ExecutorError) as e:
        ex.keyproxy(env={FLOOR: FLOOR_KEY, "PATH": "/usr/bin"})
    assert f"{failing} network" in str(e.value) and FLOOR_KEY not in str(e.value)
    assert docker.calls[-1] == ("rm", "-f", n["keys"])
    assert not any(c[0] == "logs" for c in docker.calls)  # it did not go on to wait for the proxy
