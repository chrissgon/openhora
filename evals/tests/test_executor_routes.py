"""Offline tests of the key proxy routes of evals/executor.py: a route describes a provider, the gate file's entry of a
model chooses its route and its pin, and each run gets a key proxy and a network of its own. No docker is called, and
every key is a fake one.

Run: uv run --with pytest pytest evals/tests/test_executor_routes.py
"""
from __future__ import annotations

import importlib.util
import json
import re
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


@pytest.fixture(autouse=True)
def gate(tmp_path, monkeypatch):
    """The model list the executor reads: "strong" on the Anthropic route, "floor" on the OpenRouter route, pinned."""
    entry = {"aliases": [], "adapter": "h", "price_source": "https://example.test/price", "run_token_budget": 4321}
    models = {"strong": {**entry, "pass_env": [STRONG], "route": "anthropic", "provider_pin": None, "upstream_models": ["strong-1"]},
              "floor": {**entry, "pass_env": [FLOOR], "route": "openrouter", "provider_pin": "deepinfra",
                        "upstream_models": ["vendor/floor-1", "vendor/floor-2"]}}
    (tmp_path / "gate.json").write_text(json.dumps({"models": models}))
    monkeypatch.setattr(ex, "GATE_FILE", str(tmp_path / "gate.json"))


def run_folder(tmp_path):
    root = tmp_path / "eval-abc"
    (root / "case").mkdir(parents=True)
    (root / "out").mkdir()
    (root / "prompt.md").write_text("hello\n")
    return root


def env_pairs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]


def tag():
    return ex.names()["tag"]


PROXY_VARIABLES = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY")


def no_proxy_variable(given):
    """True when none of the environment variables a run is given is a proxy variable, in either case."""
    return not [e for e in given if e.split("=", 1)[0].upper() in PROXY_VARIABLES]


# --- routes describe providers; the model's entry chooses -----------------------------------------------------


def test_there_is_a_route_file_per_provider_and_none_names_a_model_or_a_pin():
    assert ex.route_names() == ["anthropic", "openrouter"]
    for name, r in ex.routes().items():
        assert "provider_only" not in r and "model" not in r and "upstream_models" not in r
        assert kp.load_route(str(FOLDER / ex.route_file(name)))["secret"] == r["secret"]
    assert ex.route(name="anthropic")["secret"] == STRONG and ex.route(name="openrouter")["secret"] == FLOOR
    with pytest.raises(ex.ExecutorError):
        ex.route(name="nonesuch")
    assert not list(FOLDER.glob("keyproxy*.json"))  # the tier-keyed route files are gone


def test_a_route_file_dropped_in_the_folder_is_a_provider_and_a_model_names_it(tmp_path, monkeypatch):
    """A second provider is a file: the model's entry names it, and no other file of the harness changes."""
    folder = tmp_path / "keyproxy"
    folder.mkdir()
    for f in FOLDER.glob("route-*.json"):
        (folder / f.name).write_text(f.read_text())
    (folder / "route-example.json").write_text(json.dumps({**json.loads((FOLDER / "route-openrouter.json").read_text()),
                                                           "secret": "EXAMPLE_API_KEY", "port": 8899}))
    monkeypatch.setattr(ex, "KEYPROXY", str(folder))
    monkeypatch.setattr(ex.route, "__defaults__", (str(folder), "openrouter"))
    monkeypatch.setattr(ex.routes, "__defaults__", (str(folder),))
    monkeypatch.setattr(ex.route_names, "__defaults__", (str(folder),))
    assert ex.route_names() == ["anthropic", "example", "openrouter"]
    assert ex.route_network("example", ex.names()) == f"wb-eval-route-example-{tag()}"


def test_the_pin_the_upstream_names_and_the_budget_come_from_the_models_entry(monkeypatch):
    floor = ex.model_entry("floor")
    assert floor["route"] == "openrouter" and floor["provider_pin"] == "deepinfra"
    assert floor["upstream_models"] == ["vendor/floor-1", "vendor/floor-2"] and floor["run_token_budget"] == 4321
    assert ex.model_entry("strong")["provider_pin"] is None


# --- a held run: its own network, its own key proxy's address, no proxy variable ---------------------------------


def test_a_strong_run_on_the_proxy_network_gets_a_placeholder_and_its_own_proxy_and_never_the_value(tmp_path):
    root = run_folder(tmp_path)
    run_id = ex.new_run_id()
    argv, _ = ex.command(["true"], str(root), env={STRONG: STRONG_KEY}, pass_names=[STRONG], network="proxy", model="strong", run_id=run_id)
    given = env_pairs(argv)
    assert f"{STRONG}=held-by-the-eval-key-proxy" in given and STRONG not in given
    assert f"ANTHROPIC_BASE_URL=http://wb-eval-keys-{run_id}:8891" in given
    assert argv[argv.index("--network") + 1] == f"wb-eval-held-{run_id}"  # its own network, nothing else
    assert argv.count("--network") == 1 and no_proxy_variable(given)
    assert STRONG_KEY not in " ".join(argv)


def test_a_strong_run_on_the_web_gets_its_own_network_too(tmp_path):
    root = run_folder(tmp_path)
    run_id = ex.new_run_id()
    argv, _ = ex.command(["true"], str(root), env={STRONG: STRONG_KEY}, pass_names=[STRONG], network="open", model="strong", run_id=run_id)
    assert argv[argv.index("--network") + 1] == f"wb-eval-held-{run_id}" and no_proxy_variable(env_pairs(argv))
    assert f"{STRONG}=held-by-the-eval-key-proxy" in env_pairs(argv) and STRONG_KEY not in " ".join(argv)


@pytest.mark.parametrize("network", ["proxy", "open", "none"])
def test_a_floor_run_gets_its_placeholder_its_proxys_address_and_the_network_of_its_kind(tmp_path, network):
    """The arguments of a floor run in full: held runs on their own network (the proxy network's and the web's)."""
    root = run_folder(tmp_path)
    run_id = ex.new_run_id()
    argv, _ = ex.command(["true"], str(root), env={FLOOR: FLOOR_KEY, "MODEL_KEY": "v"}, pass_names=[FLOOR, "MODEL_KEY"],
                         network=network, model="floor", run_id=run_id)
    tail = argv[argv.index(f"{FLOOR}=held-by-the-eval-key-proxy") - 1:]
    expected = ["-e", f"{FLOOR}=held-by-the-eval-key-proxy", "-e", "MODEL_KEY"]
    if network == "none":
        expected += ["--network", "none"]
    else:
        expected += ["-e", f"OPENROUTER_BASE_URL=http://wb-eval-keys-{run_id}:8890/api/v1", "--network", f"wb-eval-held-{run_id}"]
    assert tail == expected + [ex.names()["image"], "true"]
    assert FLOOR_KEY not in " ".join(argv)


def test_two_runs_never_share_a_container_a_key_proxy_or_a_network(tmp_path):
    root = run_folder(tmp_path)
    seen = []
    for _ in range(3):
        argv, name = ex.command(["true"], str(root), env={FLOOR: FLOOR_KEY}, pass_names=[FLOOR], network="proxy", model="floor")
        seen.append((name, argv[argv.index("--network") + 1],
                     next(e for e in env_pairs(argv) if e.startswith("OPENROUTER_BASE_URL="))))
    for position in range(3):
        assert len({row[position] for row in seen}) == 3
    assert all(re.fullmatch(r"wb-eval-run-[0-9a-f]{16}", row[0]) for row in seen)


def test_a_command_passed_both_keys_is_refused(tmp_path):
    root = run_folder(tmp_path)
    with pytest.raises(ex.ExecutorError):
        ex.command(["true"], str(root), env={STRONG: STRONG_KEY, FLOOR: FLOOR_KEY}, pass_names=[STRONG, FLOOR], network="proxy", model="floor")


def test_held_route_names_no_proxy_without_a_network_or_without_a_value():
    assert ex.held_route([STRONG], {STRONG: STRONG_KEY}, "none", "strong") is None
    assert ex.held_route([FLOOR], {FLOOR: FLOOR_KEY}, "none", "floor") is None
    assert ex.held_route([STRONG], {STRONG: ""}, "proxy", "strong") is None
    assert ex.held_route([STRONG], {}, "proxy", "strong") is None
    assert ex.held_route([STRONG], {STRONG: STRONG_KEY}, "proxy", "strong") == "anthropic"
    assert ex.held_route([FLOOR], {FLOOR: FLOOR_KEY}, "open", "floor") == "openrouter"


def test_the_proxy_url_of_a_run_has_no_path_for_the_anthropic_route_and_keeps_the_prefix_for_openrouter():
    run_id = ex.new_run_id()
    assert ex.keyproxy_url(run_id, "anthropic") == f"http://wb-eval-keys-{run_id}:8891"
    assert ex.keyproxy_url(run_id, "openrouter") == f"http://wb-eval-keys-{run_id}:8890/api/v1"
    with pytest.raises(ex.ExecutorError):
        ex.keyproxy_url("not-a-run-id", "openrouter")


def test_the_anthropic_route_is_valid_and_a_bad_base_path_is_refused(tmp_path):
    route = kp.load_route(str(FOLDER / "route-anthropic.json"))
    assert route["secret"] == STRONG and route["base_path"] == "" and route["prefix"] == "/v1/"
    bad = {**json.loads((FOLDER / "route-anthropic.json").read_text()), "base_path": "v1"}
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(kp.RouteError):
        kp.load_route(str(tmp_path / "bad.json"))


# --- a held run reaches only its key proxy: the arguments it had before package SEC ------------------------------

GOLDEN = json.loads((Path(__file__).resolve().parent / "goldens" / "executor_argv_before_sec.json").read_text())
CASES = {
    "plain_proxy": dict(env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="proxy"),
    "plain_open": dict(env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="open"),
    "plain_none": dict(env={"MODEL_KEY": "v"}, pass_names=["MODEL_KEY"], network="none"),
    "floor_open": dict(env={FLOOR: "fake-k", "MODEL_KEY": "v"}, pass_names=[FLOOR, "MODEL_KEY"], network="open", model="floor"),
    "strong_open": dict(env={STRONG: "fake-k"}, pass_names=[STRONG], network="open", model="strong"),
    "floor_none": dict(env={FLOOR: "fake-k"}, pass_names=[FLOOR], network="none", model="floor"),
}
HELD_CASES = {
    "floor_proxy": dict(env={FLOOR: "fake-k", "MODEL_KEY": "v"}, pass_names=[FLOOR, "MODEL_KEY"], network="proxy", model="floor"),
    "strong_proxy": dict(env={STRONG: "fake-k"}, pass_names=[STRONG], network="proxy", model="strong"),
}


def like_a_golden(argv, root, name, run_id=None):
    """argv with what changes from run to run replaced as the golden file writes it, without the two arguments that
    are added on Linux only and without the labels (package P2b adds them to every container)."""
    kept, skip = [], 0
    for i, a in enumerate(argv):
        if skip:
            skip -= 1
        elif a in ("--user", "--label"):
            skip = 1
        elif a == ex.NO_PULL:
            continue
        elif a == "HOME=/home/eval" and argv[i - 1] == "-e":
            kept.pop()
        else:
            kept.append(a)
    out = [a.replace(tag(), "<TAG>").replace(name, "<NAME>").replace(str(Path(root).resolve()), "<ROOT>")
           .replace(ex.image_platform(), "<PLATFORM>") for a in kept]
    return [a.replace(run_id, "<RUN>") for a in out] if run_id else out


def command_of(tmp_path, case):
    root = run_folder(tmp_path)
    run_id = ex.new_run_id()
    argv, name = ex.command(["true"], str(root), run_id=run_id, **case)
    return like_a_golden(argv, root, name, run_id)


@pytest.mark.parametrize("label", sorted(CASES))
def test_every_run_the_held_network_does_not_touch_has_the_arguments_it_had_before(tmp_path, label):
    """The goldens are the arguments command() produced before package SEC: a run with no held key on the proxy
    network, and every run on the open or the no network, is built exactly as it was."""
    case = CASES[label]
    held_open = label in ("floor_open", "strong_open")
    got = command_of(tmp_path, case)
    if held_open:  # a web run with a held key is on its own network now, with its own key proxy's address
        assert got[got.index("--network") + 1] == "wb-eval-held-<RUN>"
        old = GOLDEN["unchanged"][label]
        old = [a.replace("wb-eval-keys-strong-<TAG>", "wb-eval-keys-<RUN>").replace("wb-eval-keys-<TAG>", "wb-eval-keys-<RUN>") for a in old]
        old[old.index("--network") + 1] = "wb-eval-held-<RUN>"
        assert got == old
        return
    assert got == GOLDEN["unchanged"][label]


@pytest.mark.parametrize("label", ["floor_proxy", "strong_proxy"])
def test_a_held_run_on_the_proxy_network_differs_from_the_old_one_in_its_network_and_its_proxy_variables_only(tmp_path, label):
    """Against the golden of the defect: the same arguments, with the run's own network in place of the internal
    one, its own key proxy's name, and without HTTPS_PROXY, HTTP_PROXY, https_proxy, http_proxy, NO_PROXY and no_proxy."""
    old = GOLDEN["before_sec_held_proxy"][label]
    expected, i = [], 0
    while i < len(old):
        if old[i] == "-e" and old[i + 1].split("=")[0].upper() in PROXY_VARIABLES:
            i += 2
            continue
        expected.append(old[i].replace("wb-eval-keys-strong-<TAG>", "wb-eval-keys-<RUN>").replace("wb-eval-keys-<TAG>", "wb-eval-keys-<RUN>"))
        i += 1
    assert len(old) - len(expected) == 12  # six variables, each with its -e
    expected[expected.index("--network") + 1] = "wb-eval-held-<RUN>"
    assert command_of(tmp_path, HELD_CASES[label]) == expected


def test_a_held_run_names_only_its_own_network_and_no_proxy_variable_in_any_case(tmp_path):
    """The two things the egress proxy needs to be reached: its network, and its address in a variable."""
    for label, case in HELD_CASES.items():
        argv = command_of(tmp_path / label, case)
        assert argv.count("--network") == 1 and argv[argv.index("--network") + 1] == "wb-eval-held-<RUN>"
        assert "wb-eval-proxy-<TAG>" not in " ".join(argv) and "8888" not in " ".join(argv)
        assert no_proxy_variable(env_pairs(argv))


# --- the networks the harness keeps, and the ones each run makes ---------------------------------------------------


def test_every_provider_has_a_route_network_of_its_own_and_none_is_the_run_network():
    n = ex.names()
    every = [n["network"]] + [ex.route_network(name, n) for name in ex.route_names()]
    assert len(set(every)) == 3 and ex.route_network("openrouter", n) == f"wb-eval-route-openrouter-{tag()}"
    assert all(tag() in name for name in every)


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


def test_ensure_makes_the_run_network_and_a_route_network_per_provider_internal_and_labelled(monkeypatch):
    n = ex.names()
    docker = RecordingDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.ensure()
    created = {c[-1]: c for c in docker.calls if c[:2] == ("network", "create")}
    assert set(created) == {n["network"], ex.route_network("anthropic", n), ex.route_network("openrouter", n)}
    assert all("--internal" in c and ["--label", "wb.eval=1"] == list(c[c.index("--label"):c.index("--label") + 2]) for c in created.values())
    connected = [c for c in docker.calls if c[:2] == ("network", "connect")]
    assert connected and all(c[3] == n["proxy"] for c in connected)
    assert {c[2] for c in connected} == set(created)  # the egress proxy is on the run network and every route network
    assert not any("wb-eval-held-" in " ".join(c) for c in docker.calls)  # and on no run's own network


def test_clean_removes_the_egress_proxy_and_the_networks_of_the_definition(monkeypatch):
    n = ex.names()
    docker = RecordingDocker()
    monkeypatch.setattr(ex, "docker", docker)
    ex.clean()
    removed = {c[-1] for c in docker.calls if c[:2] == ("network", "rm")}
    assert removed == {n["network"], ex.route_network("anthropic", n), ex.route_network("openrouter", n)}
    assert ("rm", "-f", n["proxy"]) in docker.calls
