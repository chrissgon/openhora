"""Tests of the per-run key proxy with a real docker daemon: a run container holds a placeholder and never the key, a call
through its key proxy reaches a provider with the key attached, a run reaches its own key proxy and nothing else, no two
runs share a proxy or a network, and a run's proxy and network are gone when it ends. The provider is a stand-in on the
route's internal network, with a certificate made for the test; no model and no real provider is called, and every key is a
fake one.

They build the images on first use and are skipped unless WB_EVAL_DOCKER_TESTS=1:
  WB_EVAL_DOCKER_TESTS=1 uv run --with pytest pytest evals/tests/test_keyproxy_docker.py
CI runs them in its container job, on Linux, for the definition on that machine's own architecture.
"""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WB_EVAL_DOCKER_TESTS") != "1", reason="set WB_EVAL_DOCKER_TESTS=1 (needs docker)")

_spec = importlib.util.spec_from_file_location("docker_support", Path(__file__).resolve().parent / "docker_support.py")
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)
ex = ds.load_executor("executor_keys")
REPO = ds.REPO
docker, inside, held_run, run_folder = ds.docker, ds.inside, ds.held_run, ds.run_folder

FLOOR_MODEL = "openrouter/deepseek/deepseek-v4.1-flash"
STRONG_MODEL = "claude-sonnet-5-5"
FLOOR, STRONG = "OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"
CHAT = "/api/v1/chat/completions"


@pytest.fixture(scope="module")
def environment():
    return ex.ensure()


@pytest.fixture(scope="module")
def standin(environment, tmp_path_factory):
    """The stand-in provider, on the internal network of each route a key proxy reaches its provider on."""
    n = ex.names()
    provider = ds.Standin(ex, tmp_path_factory.mktemp("standin"), [ex.route_network("openrouter", n), ex.route_network("anthropic", n)]).start()
    try:
        yield provider
    finally:
        provider.stop()


@pytest.fixture
def root(tmp_path):
    return run_folder(tmp_path)


@pytest.fixture
def held(standin, tmp_path):
    """Start a held run for a model: (run id, held) for each call; every one is released at the end of the test."""
    started = []

    def start(model=FLOOR_MODEL, key=FLOOR, network="proxy", budget=None):
        folder = tmp_path / f"meter-{len(started)}"
        folder.mkdir()
        run_id, found = held_run(ex, standin, model, key, standin.key, folder, network, budget)
        started.append(run_id)
        return run_id, found
    yield start
    for run_id in started:
        ex.release(run_id)


def curl(url, extra="", wait=15):
    return f"curl -s -m {wait} {extra} -o /dev/null -w '%{{http_code}}' {url}"


# --- what a run holds and what it can do through its key proxy ------------------------------------------------


@pytest.mark.parametrize("network", ["proxy", "open"])
def test_a_run_container_holds_a_placeholder_and_its_own_proxys_address_never_the_key(held, root, standin, network):
    run_id, _ = held(network=network)
    route = ex.route(name="openrouter")
    r = inside(ex, root, "env; echo --; tr '\\0' '\\n' < /proc/1/environ; echo --; tr '\\0' '\\n' < /proc/self/environ",
               run_id, FLOOR_MODEL, FLOOR, standin.key, network)
    assert r.returncode == 0, r.stderr
    assert standin.key not in r.stdout and standin.key not in r.stderr
    assert f"{FLOOR}={route['placeholder']}" in r.stdout
    assert f"{route['base_url_env']}=http://wb-eval-keys-{run_id}:{route['port']}/api/v1" in r.stdout


@pytest.mark.parametrize("network", ["proxy", "open"])
def test_a_call_through_the_key_proxy_reaches_the_provider_with_the_key_attached_and_only_for_its_model(held, root, standin, network):
    run_id, found = held(network=network)
    before = len(standin.seen())
    body = json.dumps({"model": "deepseek/deepseek-v4.1-flash"})
    other = json.dumps({"model": "some/other-model"})
    script = (f"curl -s -m 30 -H 'Authorization: Bearer made-up' -H 'Content-Type: application/json' -d '{body}' \"$OPENROUTER_BASE_URL/chat/completions\" | head -c 60; echo; "
              f"curl -s -m 30 -o /dev/null -w '%{{http_code}}' -H 'Content-Type: application/json' -d '{other}' \"$OPENROUTER_BASE_URL/chat/completions\"; echo; "
              f"curl -s -m 30 -o /dev/null -w '%{{http_code}}' -d '{body}' http://{found['keys']}:8890/elsewhere; echo")
    r = inside(ex, root, script, run_id, FLOOR_MODEL, FLOOR, standin.key, network)
    first, refused, elsewhere = r.stdout.strip().splitlines()
    assert first.startswith('{"id":"gen-fixture"'), r.stdout + r.stderr
    assert refused == "403" and elsewhere == "403"  # another model, and another path: refused by the key proxy
    calls = standin.seen()[before:]
    assert [(c["method"], c["path"], c["model"], c["authorized"], c["authorizations"]) for c in calls] == [
        ("POST", CHAT, "deepseek/deepseek-v4.1-flash", True, 1)]
    logs = docker("logs", found["keys"], check=False)
    assert standin.key not in logs.stdout + logs.stderr and "Bearer" not in logs.stdout + logs.stderr


def test_the_proxy_counts_the_tokens_of_the_run_where_the_run_cannot_see_them(held, root, standin, tmp_path):
    run_id, found = held()
    script = ("for i in 1 2; do curl -s -m 30 -o /dev/null -H 'Content-Type: application/json' "
              "-d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}' \"$OPENROUTER_BASE_URL/chat/completions\"; done; "
              "ls /meter 2>&1 | head -1; find / -name '*.json' -path '*meter*' -not -path '/proc/*' -not -path '/usr/*' -not -path '/opt/*' 2>/dev/null | wc -l")
    r = inside(ex, root, script, run_id, FLOOR_MODEL, FLOOR, standin.key)
    assert "No such file" in r.stdout and r.stdout.split()[-1] == "0", r.stdout  # /eval never holds the meter
    for _ in range(50):  # written when each response ends
        meter = ex.read_meter(found["meter"])
        if meter and meter["responses"] == 2:
            break
        time.sleep(0.1)
    assert meter and meter["input"] == 110 * 2 and meter["output"] == 22 * 2 and meter["cache_read"] == 64 * 2
    assert meter["cache_write"] == 20 * 2 and meter["total"] == 216 * 2 and meter["unknown_responses"] == 0
    assert not list(root.rglob("*meter*")) and not list((root / "case").iterdir())


def test_a_run_past_its_budget_gets_the_stated_error(held, root, standin):
    run_id, found = held(budget=300)
    call = ("curl -s -m 30 -w ' [%{http_code}]' -H 'Content-Type: application/json' "
            "-d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}' \"$OPENROUTER_BASE_URL/chat/completions\"; echo")
    r = inside(ex, root, "; ".join([call] * 3), run_id, FLOOR_MODEL, FLOOR, standin.key)
    codes = re.findall(r" \[(\d{3})\]$", r.stdout, re.M)
    assert codes == ["200", "200", "429"], r.stdout  # 216 and 432 tokens: the first is under 300, the second passes it, the third is stopped
    assert "budget of 300 tokens is reached" in r.stdout


def test_the_floor_adapter_sends_its_calls_through_the_key_proxy(held, root, standin):
    """The floor runner of the image, through the agents-dir adapter, as a floor run starts it: its calls reach the
    stand-in through the key proxy, with the key the proxy holds, and the reply it streams back is the run's reply."""
    run_id, found = held()
    before = len(standin.seen())
    runner = REPO / "adapters" / "agents-dir" / "run-prompt.sh"
    r = inside(ex, root, f"bash /wb/run-prompt.sh --prompt-file /eval/prompt.md --cwd /eval/case --model {FLOOR_MODEL} --out /eval/out; echo rc=$?",
               run_id, FLOOR_MODEL, FLOOR, standin.key, "proxy", runner=str(runner), timeout=300)
    calls = [c for c in standin.seen()[before:] if c["path"].startswith("/api/v1/")]
    assert calls and all(c["authorized"] and c["authorizations"] == 1 for c in calls), (calls, r.stdout, r.stderr)
    assert any(c["method"] == "POST" and c["path"] == CHAT for c in calls)
    assert "rc=0" in r.stdout, r.stdout + (root / "out" / "stderr.log").read_text(errors="ignore")[-2000:]
    assert "pong from" in (root / "out" / "response.md").read_text()
    for path in (root / "out").rglob("*"):
        if path.is_file():
            assert standin.key not in path.read_text(errors="ignore")
    meter = ex.read_meter(found["meter"])
    assert meter and meter["responses"] >= 1 and meter["total"] > 0 and meter["unknown_responses"] == 0


# --- a held run reaches its own key proxy and nothing else --------------------------------------------------------


def networks_of(container):
    """The names of the networks a container is on (only the names: nothing of its environment is read)."""
    r = docker("inspect", "--format", "{{range $name, $net := .NetworkSettings.Networks}}{{$name}} {{end}}", container)
    return r.stdout.split()


def address_of(container, network):
    r = docker("inspect", "--format", '{{(index .NetworkSettings.Networks "%s").IPAddress}}' % network, container)
    return r.stdout.strip()


def resolves(network, host):
    """True when a container on network can resolve host by name."""
    r = docker("run", "--rm", "--platform", ex.image_platform(), "--network", network, ex.names()["image"], "python3", "-c",
               "import socket, sys; socket.gethostbyname(sys.argv[1])", host, check=False)
    return r.returncode == 0


def test_the_egress_proxy_is_on_no_run_network_and_a_key_proxy_is_on_its_route_and_its_runs(held):
    n = ex.names()
    run_id, found = held()
    assert {n["network"], ex.route_network("openrouter", n), ex.route_network("anthropic", n)} <= set(networks_of(n["proxy"]))
    assert found["network"] not in networks_of(n["proxy"])
    assert set(networks_of(found["keys"])) == {ex.route_network("openrouter", n), found["network"]}
    assert n["network"] not in networks_of(found["keys"])  # the network of the runs without a held key has no key proxy on it
    assert docker("network", "inspect", "--format", "{{.Internal}}", found["network"]).stdout.strip() == "true"
    for label in ("wb.eval=1", f"wb.eval.run={run_id}"):
        assert docker("ps", "-q", "--filter", f"label={label}", "--filter", f"name={found['keys']}").stdout.strip()
        assert docker("network", "ls", "-q", "--filter", f"label={label}", "--filter", f"name={found['network']}").stdout.strip()


def test_a_web_runs_network_is_not_internal_and_holds_only_its_own_key_proxy(held):
    _, found = held(network="open")
    assert docker("network", "inspect", "--format", "{{.Internal}}", found["network"]).stdout.strip() == "false"
    assert found["network"] in networks_of(found["keys"])


def test_a_held_run_reaches_its_key_proxy_and_neither_the_egress_proxy_nor_a_provider(held, root, standin):
    n = ex.names()
    run_id, found = held()
    egress = address_of(n["proxy"], ex.route_network("openrouter", n))
    assert egress
    script = (
        # the key proxy, by name: reached (a path outside the list is its own 403), and a chat call goes through
        curl(f"http://{found['keys']}:8890/elsewhere") + "; echo; "
        + curl(f"http://{found['keys']}:8890{CHAT}", "-X POST -H 'Content-Type: application/json' -d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}'") + "; echo; "
        # the egress proxy: its name does not resolve, and its address on the route network is not reachable
        + f"getent hosts {n['proxy']} >/dev/null; echo rc=$?; "
        + curl(f"-x http://{n['proxy']}:{ex.PROXY_PORT} https://openrouter.ai/api/v1/models", wait=8) + "; echo; "
        + curl(f"-x http://{egress}:{ex.PROXY_PORT} https://openrouter.ai/api/v1/models", wait=8) + "; echo; "
        # a provider, directly, with a credential of its own, and an address
        + curl("https://openrouter.ai/api/v1/chat/completions", "-X POST -H 'Authorization: Bearer made-up'", wait=8) + "; echo; "
        + curl("https://api.anthropic.com/v1/messages", "-X POST -H 'x-api-key: made-up'", wait=8) + "; echo; "
        + curl("https://1.1.1.1", wait=8) + "; echo; "
        # the stand-in provider sits on the route network, not on this run's
        + f"getent hosts {standin.name} >/dev/null; echo rc=$?; "
        # no variable of the run names a proxy
        + "env | cut -d= -f1 | grep -c -i proxy; echo done")
    r = inside(ex, root, script, run_id, FLOOR_MODEL, FLOOR, standin.key)
    out = r.stdout.split()
    assert out[0] == "403" and out[1] == "200", (r.stdout, r.stderr)  # its key proxy answers; the call reaches the stand-in
    assert [x for x in out if x.startswith("rc=")] == ["rc=2", "rc=2"]
    codes = [x for x in out[2:] if x.isdigit() and len(x) == 3]
    assert codes and set(codes) == {"000"}, r.stdout  # nothing else got an answer
    assert out[-2:] == ["0", "done"]


def test_a_held_strong_run_reaches_its_key_proxy_and_neither_the_egress_proxy_nor_a_provider(held, root, standin):
    n = ex.names()
    run_id, found = held(STRONG_MODEL, STRONG)
    egress = address_of(n["proxy"], ex.route_network("anthropic", n))
    script = (
        curl(f"http://{found['keys']}:8891/v1/models") + "; echo; "
        + curl(f"http://{found['keys']}:8891/v1/messages?beta=true", "-X POST -H 'x-api-key: made-up' -d '{\"model\": \"claude-sonnet-5-5\"}'") + "; echo; "
        + f"getent hosts {n['proxy']} >/dev/null; echo rc=$?; "
        + curl(f"-x http://{egress}:{ex.PROXY_PORT} https://api.anthropic.com/v1/messages", "-X POST -H 'x-api-key: made-up'", wait=8) + "; echo; "
        + curl("https://api.anthropic.com/v1/messages", "-X POST -H 'x-api-key: made-up'", wait=8) + "; echo; "
        + curl("https://openrouter.ai/api/v1/models", wait=8) + "; echo; "
        + "env | cut -d= -f1 | grep -c -i proxy; echo done")
    r = inside(ex, root, script, run_id, STRONG_MODEL, STRONG, standin.key)
    out = r.stdout.split()
    assert out[:2] == ["403", "200"], (r.stdout, r.stderr)
    assert [x for x in out if x.startswith("rc=")] == ["rc=2"]
    codes = [x for x in out[2:] if x.isdigit() and len(x) == 3]
    assert codes and set(codes) == {"000"}, r.stdout
    assert out[-2:] == ["0", "done"]


def test_two_concurrent_held_runs_cannot_reach_each_others_key_proxy(held, standin, tmp_path):
    n = ex.names()
    (a_id, a), (b_id, b) = held(), held()
    assert a["keys"] != b["keys"] and a["network"] != b["network"]
    assert not resolves(a["network"], b["keys"]) and not resolves(b["network"], a["keys"])  # each name resolves on its own network only
    assert resolves(a["network"], a["keys"]) and resolves(b["network"], b["keys"])
    b_address = address_of(b["keys"], ex.route_network("openrouter", n))
    root_a = run_folder(tmp_path, "run-a")
    script = (f"getent hosts {b['keys']} >/dev/null; echo rc=$?; "
              + curl(f"http://{b_address}:8890{CHAT}", "-X POST -d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}'", wait=5) + "; echo; "
              + curl(f"http://{a['keys']}:8890/elsewhere") + "; echo")
    before = len(standin.seen())
    r = inside(ex, root_a, script, a_id, FLOOR_MODEL, FLOOR, standin.key)
    assert r.stdout.split() == ["rc=2", "000", "403"], (r.stdout, r.stderr)  # B's name, B's address: nothing; its own: answers
    assert len(standin.seen()) == before
    for run_id in (a_id, b_id):
        assert not ex.read_meter(a["meter"] if run_id == a_id else b["meter"])["responses"]  # and neither spent anything


def test_a_run_without_a_held_key_cannot_reach_any_key_proxy(held, root, standin):
    """The runs that use the egress proxy's network share it with no key proxy: they could otherwise call one and
    spend its key."""
    n = ex.names()
    run_id, found = held()
    address = address_of(found["keys"], ex.route_network("openrouter", n))
    script = (f"getent hosts {found['keys']} >/dev/null; echo rc=$?; "
              + curl(f"http://{found['keys']}:8890{CHAT}", "--noproxy '*' -X POST -d '{}'", wait=5) + "; echo; "
              + curl(f"http://{address}:8890{CHAT}", "--noproxy '*' -X POST -d '{}'", wait=5) + "; echo; "
              # through the egress proxy, as the run's proxy variables send it: the proxy's own refusal, not the key proxy's
              + curl(f"http://{found['keys']}:8890{CHAT}", "-X POST -d '{}'", wait=5) + "; echo")
    # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
    argv, name = ex.command(["bash", "-c", script], str(root), cwd=str(root / "case"), env={}, pass_names=[], network="proxy")
    assert argv[argv.index("--network") + 1] == n["network"]  # on the run network, with no held key
    before = len(standin.seen())
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        ex.remove(name)
    out = r.stdout.split()
    assert out[0] == "rc=2" and set(out[1:3]) == {"000"} and out[3] != "200", (r.stdout, r.stderr)
    assert len(standin.seen()) == before  # nothing reached the stand-in


# --- a run's key proxy and network are gone when it ends -------------------------------------------------------------


def load_execution(name="execution_docker"):
    spec = importlib.util.spec_from_file_location(name, REPO / "evals" / "execution.py")
    kit = importlib.util.module_from_spec(spec)
    sys.modules[name] = kit
    spec.loader.exec_module(kit)
    return kit


@pytest.fixture
def kit(standin, monkeypatch):
    """The execution kit, with the executor's hold() pointed at the stand-in (a real run passes no upstream)."""
    kit = load_execution()
    module = kit.load_executor()  # the kit's executor is its own copy: the stand-in is wired into that one
    real = module.hold
    monkeypatch.setattr(module, "hold", lambda run_id, model, env, network="proxy", **kw: real(
        run_id, model, env, network, upstream=standin.upstream, cafile=standin.cafile, egress=False, **kw))
    return kit


def run_in_kit(kit, root, script, standin, timeout=60, model=FLOOR_MODEL, key=FLOOR, network="proxy"):
    # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
    return kit.run_group(["bash", "-c", script], timeout, env={key: standin.key, "PATH": os.environ["PATH"]},
                         box={"root": str(root), "pass": [key], "network": network, "model": model})


def labelled():
    return ds.leftovers(ex)


def test_a_run_group_starts_its_proxy_and_network_and_removes_them_when_the_command_ends(kit, root, standin):
    before = labelled()
    r = run_in_kit(kit, root, "curl -s -m 20 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' "
                              "-d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}' \"$OPENROUTER_BASE_URL/chat/completions\"", standin)
    assert r.returncode == 0 and r.stdout == "200", (r.stdout, r.stderr)
    after = labelled()
    assert sorted(after[0]) == sorted(before[0]) and sorted(after[1]) == sorted(before[1])  # no container, no network left
    assert kit.HELD == set()


def test_the_meter_of_a_run_group_is_left_beside_its_outputs_and_the_run_never_sees_it(kit, root, standin):
    box = {"root": str(root), "pass": [FLOOR], "network": "proxy", "model": FLOOR_MODEL}
    # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
    r = kit.run_group(["bash", "-c", "for i in 1 2 3; do curl -s -m 20 -o /dev/null -H 'Content-Type: application/json' "
                                     "-d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}' \"$OPENROUTER_BASE_URL/chat/completions\"; done"],
                      60, env={FLOOR: standin.key, "PATH": os.environ["PATH"]}, box=box)
    assert r.returncode == 0, r.stderr
    assert box["meter"]["responses"] == 3 and box["meter"]["total"] == 3 * 216 and box["meter"]["unknown_responses"] == 0
    kit.write_meter(str(root / "out"), box)
    assert json.loads((root / "out" / "meter.json").read_text())["total"] == 648


def test_a_timed_out_run_leaves_no_proxy_and_no_network(kit, root, standin):
    before = labelled()
    with pytest.raises(subprocess.TimeoutExpired):
        run_in_kit(kit, root, "curl -s -m 20 -o /dev/null \"$OPENROUTER_BASE_URL/chat/completions\"; sleep 120", standin, timeout=4)
    after = labelled()
    assert sorted(after[0]) == sorted(before[0]) and sorted(after[1]) == sorted(before[1])


def test_a_stopped_run_leaves_no_proxy_and_no_network(kit, root, standin):
    before = labelled()
    done = []
    thread = threading.Thread(target=lambda: done.append(run_in_kit(kit, root, "sleep 120", standin, timeout=300)), daemon=True)
    thread.start()
    try:
        for _ in range(200):  # the run is up when its container, its proxy and its network are
            containers, networks = labelled()
            if len(containers) >= len(before[0]) + 2 and len(networks) > len(before[1]):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("the run never started")
        assert kit.HELD  # registered, so that a stop finds it
        kit.stop_all_groups(grace=2)
        thread.join(60)
        assert not thread.is_alive()
    finally:
        for run_id in list(kit.HELD):  # a failed test leaves nothing behind either
            ex.release(run_id)
        for name in [c for c in labelled()[0] if c.startswith("wb-eval-run-") and c not in before[0]]:
            ex.remove(name)
    after = labelled()
    assert sorted(after[0]) == sorted(before[0]) and sorted(after[1]) == sorted(before[1])


def test_a_run_whose_key_proxy_cannot_start_fails_as_infrastructure_and_leaves_nothing(kit, root, standin, monkeypatch):
    module = kit.load_executor()
    monkeypatch.setattr(module, "KEYPROXY_READY_SECONDS", 0)
    monkeypatch.setattr(module, "hold", lambda *a, **kw: (_ for _ in ()).throw(module.ExecutorError("the key proxy did not start: cannot start")))
    before = labelled()
    r = run_in_kit(kit, root, "echo ran", standin)
    assert r.returncode == 1 and "did not start" in r.stderr and "ran" not in r.stdout
    assert labelled() == before


def test_fourteen_concurrent_held_runs_work_each_with_a_proxy_and_a_network_of_its_own(kit, standin, tmp_path):
    """total_jobs is 14. Each run reaches only its own proxy, and the count of the networks stays inside docker's pools."""
    seen = {"networks": 0, "containers": 0}
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            containers, networks = labelled()
            seen["networks"], seen["containers"] = max(seen["networks"], len(networks)), max(seen["containers"], len(containers))
            time.sleep(0.2)
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    before = labelled()
    script = ("curl -s -m 30 -o /dev/null -w '%{http_code} ' -H 'Content-Type: application/json' "
              "-d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}' \"$OPENROUTER_BASE_URL/chat/completions\"; sleep 3; "
              "curl -s -m 30 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' "
              "-d '{\"model\": \"deepseek/deepseek-v4.1-flash\"}' \"$OPENROUTER_BASE_URL/chat/completions\"")
    roots = [run_folder(tmp_path, f"run-{i}") for i in range(14)]
    boxes = [{"root": str(r), "pass": [FLOOR], "network": "proxy", "model": FLOOR_MODEL} for r in roots]
    try:
        with concurrent.futures.ThreadPoolExecutor(14) as pool:
            # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
            results = list(pool.map(lambda box: kit.run_group(["bash", "-c", script], 120, env={FLOOR: standin.key, "PATH": os.environ["PATH"]}, box=box), boxes))
    finally:
        stop.set()
        watcher.join(5)
    assert [r.stdout for r in results] == ["200 200"] * 14, [(r.stdout, r.stderr) for r in results if r.stdout != "200 200"]
    assert all(box["meter"]["responses"] == 2 for box in boxes)  # each proxy counted its own run's calls and no other's
    assert seen["containers"] >= 28 and seen["networks"] >= len(before[1]) + 14  # a run container and a proxy each, a network each
    after = labelled()
    assert sorted(after[0]) == sorted(before[0]) and sorted(after[1]) == sorted(before[1])
    print(f"14 concurrent held runs: {seen['containers']} labelled containers and {seen['networks']} labelled networks at the peak")


# --- a run that ends in the middle of a request is never counted short in silence ------------------------------------------------

SLOW = ("curl -s -m 60 -o /dev/null -H 'Content-Type: application/json' "
        "-d '{\"model\": \"deepseek/deepseek-v4.1-flash\", \"standin_delay\": %d}' \"$OPENROUTER_BASE_URL/chat/completions\"")


def test_a_run_that_times_out_in_the_middle_of_a_request_has_the_answer_counted(kit, root, standin):
    """The run is gone at 3 seconds; the provider answers at 6. The runner waits for the proxy to finish reading it."""
    box = {"root": str(root), "pass": [FLOOR], "network": "proxy", "model": FLOOR_MODEL}
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
        kit.run_group(["bash", "-c", SLOW % 6], 3, env={FLOOR: standin.key, "PATH": os.environ["PATH"]}, box=box)
    assert time.monotonic() - started >= 5  # it waited for the answer, which the proxy read on after the run was gone
    assert box["meter"]["total"] == 216 and box["meter"]["unknown_responses"] == 0 and box["meter"]["in_flight"] == 0


def test_a_key_proxy_stopped_in_the_middle_of_a_request_records_the_answer_as_unknown(held, root, standin):
    """docker stop (SIGTERM) reaches the proxy through the container's init: the answer it still holds is flagged."""
    run_id, found = held()
    thread = threading.Thread(target=lambda: inside(ex, root, SLOW % 30, run_id, FLOOR_MODEL, FLOOR, standin.key, timeout=90), daemon=True)
    thread.start()
    for _ in range(200):
        meter = ex.read_meter(found["meter"])
        if meter and meter.get("in_flight") == 1:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the request never reached the key proxy")
    ex.release(run_id)  # stop, then remove
    final = ex.read_meter(found["meter"])
    assert final["unknown_responses"] == 1 and final["total"] == 0 and final["counting_failed"] is True, final
    ex.remove(f"wb-eval-run-{run_id}")  # the run's container, if it was still there
    thread.join(60)
