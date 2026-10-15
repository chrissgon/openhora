"""Tests of the key proxy with a real docker daemon: a run container holds a placeholder and never the key, and a
call through the key proxy reaches a provider with the key attached. The provider is a stand-in on the eval's
internal network, with a certificate made for the test; no model and no real provider is called, and the key
is a fake one.

They build the images on first use and are skipped unless WB_EVAL_DOCKER_TESTS=1:
  WB_EVAL_DOCKER_TESTS=1 uv run --with pytest pytest evals/tests/test_keyproxy_docker.py
CI runs them in its container job, on Linux, for the definition on that machine's own architecture.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WB_EVAL_DOCKER_TESTS") != "1", reason="set WB_EVAL_DOCKER_TESTS=1 (needs docker)")

SCRIPT = Path(__file__).resolve().parents[1] / "executor.py"
spec = importlib.util.spec_from_file_location("executor_keys", SCRIPT)
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)
REPO = SCRIPT.parents[1]
if os.environ.get("WB_EVAL_DOCKER_TESTS") == "1" and not os.environ.get(ex.PLATFORM_ENV):
    try:
        native = subprocess.run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"],
                                capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        native = ""
    if native and native != ex.IMAGE_PLATFORM:
        os.environ[ex.PLATFORM_ENV] = native  # no emulation: the definition is what is under test here

ROUTE = ex.route()
SECRET = ROUTE["secret"]
FAKE_KEY = "fake-floor-key-for-the-docker-tests-0005"
TAG = uuid.uuid4().hex[:8]
STANDIN = f"wb-eval-standin-{TAG}"  # the stand-in provider, on the internal network
KEYS = f"wb-eval-keys-test-{TAG}"  # this test's key proxy: never the one a real run uses

# The stand-in provider: HTTPS on 8443. It writes one line per request to its log (the path, and whether the key
# arrived), and answers a chat call with a streamed reply in the provider's event format. It never answers with
# the Authorization it received: a run must not learn the key from it either.
STANDIN_SERVER = r'''
import http.server, json, os, ssl, sys
EXPECTED = "Bearer " + os.environ["STANDIN_EXPECTED_KEY"]

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def answer(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        auth = self.headers.get_all("Authorization") or []
        seen = {"method": self.command, "path": self.path, "authorized": auth == [EXPECTED], "headers": len(auth)}
        print("seen " + json.dumps(seen), flush=True)
        try:
            stream = json.loads(body or b"{}").get("stream") is True
        except ValueError:
            stream = False
        if self.path.startswith("/api/v1/chat/completions") and stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            base = {"id": "gen-standin", "object": "chat.completion.chunk", "created": 1, "model": "standin/model"}
            events = [dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "content": "pong from the stand-in"}, "finish_reason": None}]),
                      dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}],
                           usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14})]
            for e in events:
                data = ("data: " + json.dumps(e) + "\n\n").encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                self.wfile.flush()
            done = b"data: [DONE]\n\n"
            self.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(done), done))
            return
        out = json.dumps({"path": self.path, "authorized": auth == [EXPECTED]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    do_GET = do_POST = answer

server = http.server.ThreadingHTTPServer(("0.0.0.0", 8443), H)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("/standin/cert.pem", "/standin/key.pem")
server.socket = context.wrap_socket(server.socket, server_side=True)
print("standin listening", flush=True)
server.serve_forever()
'''


def docker(*args, env=None, check=True):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=600, env={**os.environ, **(env or {})})
    assert not check or r.returncode == 0, r.stderr
    return r


@pytest.fixture(scope="module")
def environment():
    return ex.ensure()


@pytest.fixture(scope="module")
def standin(environment, tmp_path_factory):
    """The stand-in provider, started on the internal network; its certificate is for its own name."""
    if not shutil.which("openssl"):
        pytest.skip("openssl is needed to make the stand-in provider's certificate")
    folder = tmp_path_factory.mktemp("standin")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", f"/CN={STANDIN}",
                    "-addext", f"subjectAltName=DNS:{STANDIN}", "-keyout", str(folder / "key.pem"), "-out", str(folder / "cert.pem")],
                   check=True, capture_output=True)
    (folder / "server.py").write_text(STANDIN_SERVER)
    os.chmod(folder / "key.pem", 0o644)  # read by the image's user, inside the container only
    n = ex.names()
    docker("run", "-d", "--rm", "--platform", ex.image_platform(), "--name", STANDIN, "--network", n["network"],
           "-e", "STANDIN_EXPECTED_KEY", "-v", f"{os.path.realpath(folder)}:/standin:ro", n["image"],
           "python3", "/standin/server.py", env={"STANDIN_EXPECTED_KEY": FAKE_KEY})
    try:
        for _ in range(100):
            if "standin listening" in docker("logs", STANDIN, check=False).stdout:
                break
            time.sleep(0.1)
        yield folder / "cert.pem"
    finally:
        docker("rm", "-f", STANDIN, check=False)


@pytest.fixture(scope="module")
def keys(standin):
    """This test's key proxy, holding the fake key, in front of the stand-in. ex.names() names it for every
    command of this module, so the runs below are pointed at it as a real run is at the real one."""
    real_names = ex.names
    ex.names = lambda folder=ex.DEFINITION: {**real_names(folder), "keys": KEYS}
    try:
        assert ex.keyproxy(env={**os.environ, SECRET: FAKE_KEY}, upstream=f"https://{STANDIN}:8443", cafile=str(standin), egress=False) == KEYS
        yield KEYS
    finally:
        docker("rm", "-f", KEYS, check=False)
        ex.names = real_names


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "eval-run"
    (folder / "case").mkdir(parents=True)
    (folder / "out").mkdir()
    (folder / "prompt.md").write_text("Answer with one word.\n")
    return folder


def inside(root, script, network, runner=None, timeout=180):
    # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
    argv, name = ex.command(["bash", "-c", script], str(root), cwd=str(root / "case"), env={SECRET: FAKE_KEY},
                            pass_names=[SECRET], network=network, runner=runner)
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env={**os.environ, SECRET: FAKE_KEY})
    finally:
        ex.remove(name)


def seen():
    """What the stand-in provider received: one dict per request."""
    lines = docker("logs", STANDIN, check=False).stdout.splitlines()
    return [json.loads(line[5:]) for line in lines if line.startswith("seen ")]


@pytest.mark.parametrize("network", ["proxy", "open"])
def test_a_run_container_holds_a_placeholder_and_the_proxys_address_never_the_key(keys, root, network):
    r = inside(root, "env; echo --; tr '\\0' '\\n' < /proc/1/environ; echo --; tr '\\0' '\\n' < /proc/self/environ", network)
    assert r.returncode == 0, r.stderr
    assert FAKE_KEY not in r.stdout and FAKE_KEY not in r.stderr
    assert f"{SECRET}={ROUTE['placeholder']}" in r.stdout
    assert f"{ROUTE['base_url_env']}=http://{KEYS}:{ROUTE['port']}/api/v1" in r.stdout


@pytest.mark.parametrize("network", ["proxy", "open"])
def test_a_call_through_the_key_proxy_reaches_the_provider_with_the_key_attached(keys, root, network):
    before = len(seen())
    r = inside(root, 'curl -s -m 30 -H "Authorization: Bearer $OPENROUTER_API_KEY" -H "Content-Type: application/json" '
                     '-d \'{"model": "standin/model"}\' "$OPENROUTER_BASE_URL/chat/completions"; echo; '
                     'curl -s -m 30 -o /dev/null -w "%{http_code}" "http://' + KEYS + ':' + str(ROUTE["port"]) + '/elsewhere"', network)
    answer, other = r.stdout.strip().splitlines()
    assert json.loads(answer) == {"path": "/api/v1/chat/completions", "authorized": True}, r.stdout + r.stderr
    assert other == "403"  # another path is refused by the key proxy, and never reaches the provider
    calls = seen()[before:]
    assert calls == [{"method": "POST", "path": "/api/v1/chat/completions", "authorized": True, "headers": 1}]
    logs = docker("logs", KEYS, check=False)
    assert FAKE_KEY not in logs.stdout + logs.stderr and "Bearer" not in logs.stdout + logs.stderr


def test_the_floor_adapter_sends_its_calls_through_the_key_proxy(keys, root):
    """The floor runner of the image, through the agents-dir adapter, as a floor run starts it: its calls reach the
    stand-in through the key proxy, with the key the proxy holds, and the reply it streams back is the run's reply."""
    before = len(seen())
    runner = REPO / "adapters" / "agents-dir" / "run-prompt.sh"
    model = "openrouter/deepseek/deepseek-v4.1-flash"
    r = inside(root, f"bash /wb/run-prompt.sh --prompt-file /eval/prompt.md --cwd /eval/case --model {model} --out /eval/out; "
                     "echo rc=$?", "proxy", runner=str(runner), timeout=300)
    calls = [c for c in seen()[before:] if c["path"].startswith("/api/v1/")]
    assert calls and all(c["authorized"] and c["headers"] == 1 for c in calls), (calls, r.stdout, r.stderr)
    assert any(c["method"] == "POST" and c["path"] == "/api/v1/chat/completions" for c in calls)
    assert "rc=0" in r.stdout, r.stdout + (root / "out" / "stderr.log").read_text(errors="ignore")[-2000:]
    assert "pong from the stand-in" in (root / "out" / "response.md").read_text()
    for path in (root / "out").rglob("*"):
        if path.is_file():
            assert FAKE_KEY not in path.read_text(errors="ignore")


STRONG_ROUTE = ex.route(name="strong")
FAKE_STRONG_KEY = "fake-strong-token-for-the-docker-tests-0008"
KEYS_STRONG = f"wb-eval-keys-strong-test-{TAG}"  # this test's strong key proxy: never the one a real run uses


@pytest.fixture(scope="module")
def strong_keys(keys, standin):
    """This test's strong key proxy, holding a fake token, beside the floor one. ex.names() names both for every
    command of this module."""
    floor_names = ex.names
    ex.names = lambda folder=ex.DEFINITION: {**floor_names(folder), "keys_strong": KEYS_STRONG}
    try:
        assert ex.keyproxy(env={**os.environ, STRONG_ROUTE["secret"]: FAKE_STRONG_KEY}, upstream=f"https://{STANDIN}:8443",
                           cafile=str(standin), egress=False, name="strong") == KEYS_STRONG
        yield KEYS_STRONG
    finally:
        docker("rm", "-f", KEYS_STRONG, check=False)
        ex.names = floor_names


def resolves(network, host):
    """True when a container on network can resolve host by name."""
    r = docker("run", "--rm", "--platform", ex.image_platform(), "--network", network, ex.names()["image"], "python3", "-c",
               "import socket, sys; socket.gethostbyname(sys.argv[1])", host, check=False)
    return r.returncode == 0


def test_a_run_of_one_tier_cannot_reach_the_other_tiers_key_proxy(keys, strong_keys):
    n = ex.names()
    assert resolves(n["network"], keys) and resolves(n["strong_network"], strong_keys)  # each reaches its own
    assert not resolves(n["network"], strong_keys)  # the floor model's network: no strong key proxy
    assert not resolves(n["strong_network"], keys)  # the strong model's network: no floor key proxy


# --- package SEC: a held run reaches its key proxy and nothing else ---------------------------------------


def networks_of(container):
    """The names of the networks a container is on (only the names: nothing of its environment is read)."""
    r = docker("inspect", "--format", "{{range $name, $net := .NetworkSettings.Networks}}{{$name}} {{end}}", container)
    return r.stdout.split()


def address_of(container, network):
    r = docker("inspect", "--format", '{{(index .NetworkSettings.Networks "%s").IPAddress}}' % network, container)
    return r.stdout.strip()


def held_inside(root, script, key_name, key_value, timeout=180):
    """script in a held run of the route that key_name belongs to, on the proxy network."""
    # security-scan: allow shell-string -- every script is a literal of this test file, run inside the container
    argv, name = ex.command(["bash", "-c", script], str(root), cwd=str(root / "case"), env={key_name: key_value},
                            pass_names=[key_name], network="proxy")
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env={**os.environ, key_name: key_value})
    finally:
        ex.remove(name)


def code(url, extra=""):
    return f"curl -s -m 8 {extra} -o /dev/null -w '%{{http_code}}' {url}"


def test_the_egress_proxy_is_on_neither_held_network_and_each_key_proxy_is_on_its_own(strong_keys, keys):
    n = ex.names()
    assert {n["network"], n["strong_network"]} <= set(networks_of(n["proxy"]))
    assert n["held_network"] not in networks_of(n["proxy"]) and n["strong_held_network"] not in networks_of(n["proxy"])
    floor, strong = networks_of(keys), networks_of(strong_keys)
    assert {n["network"], n["open_network"], n["held_network"]} <= set(floor) and n["strong_held_network"] not in floor
    assert {n["strong_network"], n["strong_open_network"], n["strong_held_network"]} <= set(strong) and n["held_network"] not in strong
    for network in (n["held_network"], n["strong_held_network"]):
        inspected = docker("network", "inspect", "--format", "{{.Internal}}", network)
        assert inspected.stdout.strip() == "true"  # no route out of it


def test_a_held_run_reaches_its_key_proxy_and_neither_the_egress_proxy_nor_a_provider(strong_keys, keys, root):
    n = ex.names()
    egress = address_of(n["proxy"], n["network"])
    assert egress
    script = (
        # the key proxy, by name: reached (a path outside the list is its own 403), and a chat call goes through
        code(f"http://{KEYS}:{ROUTE['port']}/elsewhere") + "; echo; "
        + code(f"http://{KEYS}:{ROUTE['port']}/api/v1/chat/completions", "-X POST -H 'Content-Type: application/json' -d '{}'") + "; echo; "
        # the egress proxy: its name does not resolve, and its address on the internal network is not reachable
        + f"getent hosts {n['proxy']} >/dev/null; echo rc=$?; "
        + code(f"-x http://{n['proxy']}:{ex.PROXY_PORT} https://openrouter.ai/api/v1/models") + "; echo; "
        + code(f"-x http://{egress}:{ex.PROXY_PORT} https://openrouter.ai/api/v1/models") + "; echo; "
        + code(f"-x http://{egress}:{ex.PROXY_PORT} https://api.anthropic.com/v1/messages", "-X POST -H 'x-api-key: made-up'") + "; echo; "
        # a provider, directly, with a credential of its own, and an address
        + code("https://openrouter.ai/api/v1/chat/completions", "-X POST -H 'Authorization: Bearer made-up'") + "; echo; "
        + code("https://api.anthropic.com/v1/messages", "-X POST -H 'x-api-key: made-up'") + "; echo; "
        + code("https://1.1.1.1") + "; echo; "
        # the internal network's other hosts (the stand-in provider sits there) and the other tier's key proxy
        + f"getent hosts {STANDIN} >/dev/null; echo rc=$?; "
        + f"getent hosts {KEYS_STRONG} >/dev/null; echo rc=$?; "
        # no variable of the run names a proxy
        + "env | cut -d= -f1 | grep -c -i proxy; echo done")
    r = held_inside(root, script, SECRET, FAKE_KEY)
    out = r.stdout.split()
    assert out[0] == "403" and out[1] == "200", (r.stdout, r.stderr)  # its key proxy answers; the call reaches the stand-in
    assert [x for x in out if x.startswith("rc=")] == ["rc=2", "rc=2", "rc=2"]
    codes = [x for x in out[2:] if x.isdigit() and len(x) == 3]
    assert codes and set(codes) == {"000"}, r.stdout  # nothing else got an answer
    assert out[-2:] == ["0", "done"]
    assert seen()[-1] == {"method": "POST", "path": "/api/v1/chat/completions", "authorized": True, "headers": 1}


def test_a_held_strong_run_reaches_its_key_proxy_and_neither_the_egress_proxy_nor_a_provider(strong_keys, root):
    n = ex.names()
    # the stand-in provider sits on the floor route's internal network; the strong key proxy's internal network
    # is its own, so the stand-in joins it for this test (the stand-in container is removed with the module)
    joined = docker("network", "connect", n["strong_network"], STANDIN, check=False)
    assert joined.returncode == 0 or "already exists" in joined.stderr, joined.stderr
    egress = address_of(n["proxy"], n["strong_network"])
    assert egress
    script = (
        code(f"http://{KEYS_STRONG}:{STRONG_ROUTE['port']}/v1/models") + "; echo; "
        + code(f"http://{KEYS_STRONG}:{STRONG_ROUTE['port']}/v1/messages?beta=true", "-X POST -H 'x-api-key: made-up' -d '{}'") + "; echo; "
        + f"getent hosts {n['proxy']} >/dev/null; echo rc=$?; "
        + code(f"-x http://{egress}:{ex.PROXY_PORT} https://api.anthropic.com/v1/messages", "-X POST -H 'x-api-key: made-up'") + "; echo; "
        + code("https://api.anthropic.com/v1/messages", "-X POST -H 'x-api-key: made-up'") + "; echo; "
        + code("https://openrouter.ai/api/v1/models") + "; echo; "
        + f"getent hosts {KEYS} >/dev/null; echo rc=$?; "
        + "env | cut -d= -f1 | grep -c -i proxy; echo done")
    r = held_inside(root, script, STRONG_ROUTE["secret"], FAKE_STRONG_KEY)
    out = r.stdout.split()
    assert out[:2] == ["403", "200"], (r.stdout, r.stderr)
    assert [x for x in out if x.startswith("rc=")] == ["rc=2", "rc=2"]
    codes = [x for x in out[2:] if x.isdigit() and len(x) == 3]
    assert codes and set(codes) == {"000"}, r.stdout
    assert out[-2:] == ["0", "done"]
