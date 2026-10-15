"""Offline tests of what the key proxy (evals/container/keyproxy/keyproxy.py) does for one run: it serves one model,
counts the tokens of every response by the four kinds the runtime prices, writes the count where the run cannot read
it, and stops answering at the run's budget. The responses are fixtures in the providers' documented formats
(evals/tests/fixtures/usage/), served by a stand-in provider on this machine that speaks HTTPS with a certificate
made for the test. No docker, no model, no real provider, no real key.

Run: uv run --with pytest pytest evals/tests/test_keyproxy_meter.py
"""
from __future__ import annotations

import gzip
import http.client
import http.server
import importlib.util
import io
import json
import shutil
import ssl
import subprocess
import sys
import socket
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "container" / "keyproxy"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "usage"
_spec = importlib.util.spec_from_file_location("keyproxy_meter", FOLDER / "keyproxy.py")
kp = importlib.util.module_from_spec(_spec)
_writes = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # a cache folder in evals/container/ would change the definition's hash
try:
    _spec.loader.exec_module(kp)
finally:
    sys.dont_write_bytecode = _writes

KEY = "fake-key-held-by-the-proxy-0009"
OPENROUTER, ANTHROPIC = str(FOLDER / "route-openrouter.json"), str(FOLDER / "route-anthropic.json")
CHAT, MESSAGES, COUNT = "/api/v1/chat/completions", "/v1/messages", "/v1/messages/count_tokens"

# What each fixture holds, by kind: the sum the proxy must count.
EXPECTED = {
    "anthropic_message.json": {"input": 2095, "output": 503, "cache_read": 1200, "cache_write": 300},
    "anthropic_stream.sse": {"input": 472, "output": 15, "cache_read": 2000, "cache_write": 1000},
    "openrouter_completion.json": {"input": 110, "output": 22, "cache_read": 64, "cache_write": 20},  # 194 prompt tokens, 64 + 20 of them cached
    "openrouter_stream.sse": {"input": 221, "output": 40, "cache_read": 100, "cache_write": 0},  # 321 prompt tokens, 100 of them cached
}
STYLE = {"anthropic": "anthropic-messages", "openrouter": "openrouter-chat"}


def fixture(name):
    return (FIXTURES / name).read_bytes()


def kinds(meter):
    return {k: meter[k] for k in kp.KINDS}


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("openssl is needed to make the stand-in provider's certificate")
    folder = tmp_path_factory.mktemp("tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    return cert, key


class Provider(http.server.ThreadingHTTPServer):
    """The stand-in provider: it records each request and answers with the response set in .reply, in blocks of .block
    bytes (a stream arrives in pieces), with the headers set in .headers."""
    daemon_threads = True
    request_queue_size = 64  # the test connects from several threads at once

    def __init__(self, tls):
        super().__init__(("127.0.0.1", 0), ProviderHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(tls[0]), str(tls[1]))
        self.socket = context.wrap_socket(self.socket, server_side=True)
        self.seen, self.reply, self.headers, self.block, self.cut = [], fixture("openrouter_completion.json"), {"Content-Type": "application/json"}, 64, False
        self.pause_after = None  # write this many blocks of the answer, then wait for the gate
        self.gate = None  # an Event: the answer waits for it, so that requests stay under way


class ProviderHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.seen.append({"path": self.path, "body": body, "headers": dict(self.headers.items())})
        if self.server.gate is not None and self.server.pause_after is None:
            self.server.gate.wait(20)
        reply = self.server.reply
        self.send_response(200)
        for k, v in self.server.headers.items():
            self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if self.server.cut:  # the provider goes away mid-answer
            half = reply[: len(reply) // 2]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(half), half))
            self.wfile.flush()
            self.close_connection = True
            self.connection.close()
            return
        for number, i in enumerate(range(0, len(reply), self.server.block)):
            if self.server.pause_after is not None and number == self.server.pause_after:
                self.server.gate.wait(20)  # the test holds the rest of the answer back
            block = reply[i:i + self.server.block]
            try:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(block), block))
                self.wfile.flush()
            except OSError:
                return
        self.wfile.write(b"0\r\n\r\n")


def serve(server):
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


@pytest.fixture
def provider(tls):
    server = serve(Provider(tls))
    yield server
    server.shutdown()
    server.server_close()


class Run:
    """One run's key proxy in front of the stand-in, with its meter file and its log."""
    count = 0

    def __init__(self, provider, tls, tmp_path, route, models, budget=None, pin=None):
        Run.count += 1  # a file of its own: a proxy of an earlier run of the test may still be writing its own
        self.meter_path = tmp_path / "meter" / f"run-{Run.count}.json"
        self.meter_path.parent.mkdir(exist_ok=True)
        self.log = io.StringIO()
        self.meter = kp.Meter(str(self.meter_path), "0123456789abcdef", models[0], budget)
        assert self.meter.write()
        loaded = kp.load_route(route, f"https://127.0.0.1:{provider.server_address[1]}")
        self.server = serve(kp.KeyProxy(("127.0.0.1", 0), loaded, KEY, str(tls[0]), None, self.log,
                                        upstream_models=models, pin=pin, meter=self.meter))

    def post(self, path, doc, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        conn.request("POST", path, body=json.dumps(doc).encode() if not isinstance(doc, bytes) else doc,
                     headers={"Content-Type": "application/json", **(headers or {})})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def file(self):
        return json.loads(self.meter_path.read_text())

    def idle(self):
        """The meter file once no request is under way (it is written when a request ends, after the client has its answer)."""
        for _ in range(200):
            found = self.file()
            if found["in_flight"] == 0:
                return found
            time.sleep(0.05)
        raise AssertionError(self.file())

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def make(provider, tls, tmp_path):
    runs = []

    def make(route=OPENROUTER, models=("deepseek/deepseek-v4.1-flash",), **kw):
        runs.append(Run(provider, tls, tmp_path, route, list(models), **kw))
        return runs[-1]
    yield make
    for run in runs:
        run.stop()


# --- one model ---------------------------------------------------------------------------------------------


def test_a_request_that_names_another_model_is_refused_and_nothing_is_forwarded(provider, make):
    run = make()
    for doc in ({"model": "deepseek/another-model"}, {"model": ["deepseek/deepseek-v4.1-flash"]}, {"model": None},
                {"model": "DeepSeek/deepseek-v4.1-flash"}, {"messages": []}, {}):
        status, data = run.post(CHAT, doc)
        assert status == 403, doc
        assert b"serves one model" in data
    assert provider.seen == []
    assert run.file()["refused"] == {"model": 6, "budget": 0, "uncountable": 0}


def test_a_body_that_is_not_a_json_object_a_get_and_an_encoded_body_are_refused(provider, make):
    run = make()
    assert run.post(CHAT, b"not json")[0] == 400
    assert run.post(CHAT, b"[1, 2]")[0] == 400
    assert run.post(CHAT, b"")[0] == 400
    assert run.post(CHAT, {"model": "deepseek/deepseek-v4.1-flash"}, {"Content-Encoding": "gzip"})[0] == 415
    conn = http.client.HTTPConnection("127.0.0.1", run.server.server_address[1], timeout=20)
    conn.request("GET", CHAT)
    assert conn.getresponse().status == 405
    conn.close()
    assert provider.seen == []


def test_the_model_a_run_names_is_forwarded_and_a_list_of_names_serves_each(provider, make):
    run = make(models=("deepseek/deepseek-v4.1-flash", "deepseek/other"))
    for name in ("deepseek/deepseek-v4.1-flash", "deepseek/other"):
        assert run.post(CHAT, {"model": name})[0] == 200
    assert [json.loads(s["body"])["model"] for s in provider.seen] == ["deepseek/deepseek-v4.1-flash", "deepseek/other"]


def test_the_count_tokens_endpoint_needs_the_model_too_and_is_never_counted(provider, make):
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    provider.reply = fixture("anthropic_message.json")
    assert run.post(COUNT, {"messages": []})[0] == 403
    assert run.post(COUNT, {"model": "claude-haiku"})[0] == 403
    assert run.post(COUNT, {"model": "claude-sonnet-5-5"})[0] == 200
    assert run.file()["responses"] == 0 and run.file()["total"] == 0  # not a response that spends tokens


# --- the count -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_the_count_equals_the_usage_of_the_response_fixture_streamed_or_not(provider, make, name):
    anthropic = name.startswith("anthropic")
    run = make(ANTHROPIC if anthropic else OPENROUTER, ("claude-sonnet-5-5",) if anthropic else ("deepseek/deepseek-v4.1-flash",))
    provider.reply = fixture(name)
    provider.headers = {"Content-Type": "text/event-stream" if name.endswith(".sse") else "application/json"}
    status, data = run.post(MESSAGES if anthropic else CHAT, {"model": run.meter.model})
    assert status == 200 and data == fixture(name)  # the run receives the answer unchanged
    meter = run.file()
    assert kinds(meter) == EXPECTED[name] and meter["total"] == sum(EXPECTED[name].values())
    assert meter["responses"] == 1 and meter["unknown_responses"] == 0 and meter["unknown"] == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
@pytest.mark.parametrize("block", [1, 7, 4096])
def test_the_count_does_not_depend_on_how_the_answer_arrives(provider, make, name, block):
    anthropic = name.startswith("anthropic")
    run = make(ANTHROPIC if anthropic else OPENROUTER, ("claude-sonnet-5-5",) if anthropic else ("deepseek/deepseek-v4.1-flash",))
    provider.reply, provider.block = fixture(name), block
    provider.headers = {"Content-Type": "text/event-stream" if name.endswith(".sse") else "application/json"}
    assert run.post(MESSAGES if anthropic else CHAT, {"model": run.meter.model})[0] == 200
    assert kinds(run.file()) == EXPECTED[name]


@pytest.mark.parametrize("encode, label", [(gzip.compress, "gzip"), (zlib.compress, "deflate")])
def test_a_compressed_answer_is_counted_and_passes_through_compressed(provider, make, encode, label):
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    provider.reply = encode(fixture("anthropic_stream.sse"))
    provider.headers = {"Content-Type": "text/event-stream", "Content-Encoding": label}
    status, data = run.post(MESSAGES, {"model": "claude-sonnet-5-5"})
    assert status == 200 and data == provider.reply
    assert kinds(run.file()) == EXPECTED["anthropic_stream.sse"]


def test_the_count_is_the_sum_of_every_response_and_survives_concurrent_calls(provider, make):
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    provider.reply, provider.headers = fixture("anthropic_message.json"), {"Content-Type": "application/json"}
    with ThreadPoolExecutor(8) as pool:
        statuses = list(pool.map(lambda _: run.post(MESSAGES, {"model": "claude-sonnet-5-5"})[0], range(16)))
    assert statuses == [200] * 16
    meter = run.file()
    assert meter["responses"] == 16 and meter["total"] == 16 * sum(EXPECTED["anthropic_message.json"].values())
    assert kinds(meter) == {k: 16 * v for k, v in EXPECTED["anthropic_message.json"].items()}


def test_a_response_the_proxy_cannot_read_is_unknown_and_named_never_guessed(provider, make):
    cases = [
        (b'{"type": "message", "content": []}', {"Content-Type": "application/json"}, "no usage object"),
        (b'{"usage": {"input_tokens": "many", "output_tokens": 3}}', {"Content-Type": "application/json"}, "whole number"),
        (b"not json at all", {"Content-Type": "application/json"}, "not JSON"),
        (b"<html></html>", {"Content-Type": "text/html"}, "neither JSON nor an event stream"),
        (gzip.compress(b"{}"), {"Content-Type": "application/json", "Content-Encoding": "br"}, "content encoding"),
        (b"event: ping\ndata: {\"type\": \"ping\"}\n\n", {"Content-Type": "text/event-stream"}, "no message_start"),
    ]
    for reply, headers, why in cases:  # a run of its own for each: the first unreadable answer ends the counting (below)
        run = make(ANTHROPIC, ("claude-sonnet-5-5",))
        provider.reply, provider.headers = reply, headers
        assert run.post(MESSAGES, {"model": "claude-sonnet-5-5"})[0] == 200  # the run still gets its answer
        meter = run.file()
        assert meter["responses"] == 1 and meter["unknown_responses"] == 1 and meter["total"] == 0  # nothing guessed into the count
        assert meter["unknown"][0]["path"] == MESSAGES and why in meter["unknown"][0]["why"], (meter["unknown"], why)


def test_once_an_answer_cannot_be_read_the_run_is_stopped_with_a_stated_error(provider, make):
    """Fail closed: a run whose tokens can no longer be counted gets no more answers, so it cannot spend where nothing
    is counted (an answer in an encoding the proxy does not decode, a usage object of another shape)."""
    run = make(ANTHROPIC, ("claude-sonnet-5-5",), budget=10_000_000)
    provider.reply, provider.headers = b'{"type": "message"}', {"Content-Type": "application/json"}
    assert run.post(MESSAGES, {"model": "claude-sonnet-5-5"})[0] == 200
    provider.reply = fixture("anthropic_message.json")  # the provider is fine again; the proxy is not going to ask
    before = len(provider.seen)
    for path in (MESSAGES, COUNT):
        status, data = run.post(path, {"model": "claude-sonnet-5-5"})
        assert status == 429 and "can no longer be counted" in json.loads(data)["error"]["message"]
    assert len(provider.seen) == before
    meter = run.file()
    assert meter["counting_failed"] is True and meter["refused"]["uncountable"] == 2 and meter["total"] == 0


def test_an_answer_that_is_cut_off_is_unknown(provider, make):
    run = make(OPENROUTER)
    provider.reply, provider.cut = fixture("openrouter_stream.sse"), True
    provider.headers = {"Content-Type": "text/event-stream"}
    try:
        run.post(CHAT, {"model": "deepseek/deepseek-v4.1-flash"})
    except (http.client.HTTPException, OSError):
        pass  # the run sees the provider's failure as it happened
    for _ in range(100):  # the proxy writes the meter when the relay ends
        if run.file()["unknown_responses"]:
            break
        threading.Event().wait(0.05)
    meter = run.file()
    assert meter["unknown_responses"] == 1 and meter["total"] == 0 and "cut off" in meter["unknown"][0]["why"]


def test_an_error_response_counts_nothing(provider, make):
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    provider.reply = b'{"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}'
    provider.headers = {"Content-Type": "application/json"}
    original = ProviderHandler.do_POST

    def refusing(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        body = self.server.reply
        self.send_response(529)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    ProviderHandler.do_POST = refusing
    try:
        status, _ = run.post(MESSAGES, {"model": "claude-sonnet-5-5"})
    finally:
        ProviderHandler.do_POST = original
    assert status == 529 and run.file()["responses"] == 0


def test_the_meter_file_is_replaced_whole_and_holds_no_content_and_the_log_none_either(provider, make):
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    provider.reply, provider.headers = fixture("anthropic_message.json"), {"Content-Type": "application/json"}
    run.post(MESSAGES, {"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": "a secret prompt"}]})
    run.idle()
    text = run.meter_path.read_text()
    assert "pong from the fixture" not in text and "secret prompt" not in text and KEY not in text
    assert not list(run.meter_path.parent.glob("*.tmp"))
    log = run.log.getvalue()
    assert "POST /v1/messages 200" in log and "pong from the fixture" not in log and "secret prompt" not in log and KEY not in log


# --- the budget -----------------------------------------------------------------------------------------------


def test_a_run_past_its_budget_gets_a_stated_error_and_nothing_more_is_forwarded(provider, make):
    run = make(ANTHROPIC, ("claude-sonnet-5-5",), budget=5000)
    provider.reply, provider.headers = fixture("anthropic_message.json"), {"Content-Type": "application/json"}  # 4098 tokens a response
    assert run.post(MESSAGES, {"model": "claude-sonnet-5-5"})[0] == 200
    assert run.post(MESSAGES, {"model": "claude-sonnet-5-5"})[0] == 200  # 4098 is under 5000: this one is let through
    assert run.file()["total"] == 8196 and run.file()["budget_reached"] is True
    status, data = run.post(MESSAGES, {"model": "claude-sonnet-5-5"})
    assert status == 429
    error = json.loads(data)
    assert error["type"] == "error" and error["error"]["code"] == 429
    assert "budget of 5000 tokens is reached" in error["error"]["message"] and "8196 counted" in error["error"]["message"]
    assert len(provider.seen) == 2  # the third never reached the provider
    assert run.file()["refused"]["budget"] == 1 and run.file()["total"] == 8196
    assert run.post(COUNT, {"model": "claude-sonnet-5-5"})[0] == 429  # every model endpoint of the run is stopped


def test_a_run_under_its_budget_is_never_stopped(provider, make):
    run = make(OPENROUTER, budget=10_000)
    provider.reply, provider.headers = fixture("openrouter_completion.json"), {"Content-Type": "application/json"}
    assert [run.post(CHAT, {"model": "deepseek/deepseek-v4.1-flash"})[0] for _ in range(5)] == [200] * 5
    assert run.file()["total"] == 5 * 216 and run.file()["budget_reached"] is False


# --- the command line -------------------------------------------------------------------------------------------


def test_the_proxy_does_not_start_without_a_model_a_valid_budget_or_a_writable_meter(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    base = ["--route", OPENROUTER, "--listen", "127.0.0.1", "--port", "0"]
    assert kp.main(base) == 2
    assert "no --upstream-model" in capsys.readouterr().err
    assert kp.main(base + ["--upstream-model", "m", "--budget-tokens", "0"]) == 2
    assert "--budget-tokens" in capsys.readouterr().err
    assert kp.main(base + ["--upstream-model", "m", "--meter", str(tmp_path / "missing" / "run.json")]) == 2
    err = capsys.readouterr().err
    assert "cannot write the meter file" in err and KEY not in err
    with pytest.raises(SystemExit):
        kp.main(["--upstream-model", "m"])  # a route is required: there is no default provider


def test_a_route_needs_its_usage_style_and_its_metered_paths(tmp_path):
    route = json.loads(Path(OPENROUTER).read_text())
    for key, bad in (("usage", "other"), ("usage", None), ("metered", []), ("metered", ["/api/v1/other"]), ("metered", None)):
        broken = {**route, key: bad}
        path = tmp_path / "route-x.json"
        path.write_text(json.dumps(broken))
        with pytest.raises(kp.RouteError):
            kp.load_route(str(path))


def test_the_upstream_is_asked_only_for_encodings_the_proxy_decodes_and_nothing_else_of_the_request_changes(provider, make):
    """The one header besides the credentials that the key proxy changes: so that no response is unreadable and the cost
    never falls back to the run's own report."""
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    provider.reply, provider.headers = fixture("anthropic_message.json"), {"Content-Type": "application/json"}
    assert run.post(MESSAGES, {"model": "claude-sonnet-5-5"}, {"Accept-Encoding": "gzip, deflate, br, zstd", "X-Title": "eval"})[0] == 200
    sent = provider.seen[-1]["headers"]
    assert sent["Accept-Encoding"] == "gzip, deflate" and sent["X-Title"] == "eval"  # what the run offered among what it decodes
    assert run.post(MESSAGES, {"model": "claude-sonnet-5-5"}, {"Accept-Encoding": "br, zstd;q=0.5"})[0] == 200  # nothing it decodes is left
    assert provider.seen[-1]["headers"]["Accept-Encoding"] == "identity"
    assert run.post(MESSAGES, {"model": "claude-sonnet-5-5"}, {"Accept-Encoding": "identity, gzip;q=1.0, br"})[0] == 200
    assert provider.seen[-1]["headers"]["Accept-Encoding"] == "gzip, identity"
    assert kinds(run.file()) == {k: 3 * v for k, v in EXPECTED["anthropic_message.json"].items()}


# --- review fixes: what the run cannot steer ---------------------------------------------------------------------------


def test_every_chat_completion_asks_the_provider_for_its_usage_whatever_the_run_asked_for(provider, make):
    run = make(OPENROUTER)
    for sent in ({"model": "deepseek/deepseek-v4.1-flash"}, {"model": "deepseek/deepseek-v4.1-flash", "usage": {"include": False}},
                 {"model": "deepseek/deepseek-v4.1-flash", "usage": None, "messages": []}):
        assert run.post(CHAT, sent)[0] == 200
        got = json.loads(provider.seen[-1]["body"])
        assert got["usage"] == {"include": True} and got["model"] == "deepseek/deepseek-v4.1-flash"
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))  # the Messages answer always carries its usage: the body is not touched
    body = json.dumps({"model": "claude-sonnet-5-5", "usage": "mine"}).encode()
    provider.reply = fixture("anthropic_message.json")
    assert run.post(MESSAGES, body)[0] == 200 and provider.seen[-1]["body"] == body


def test_when_the_run_hangs_up_in_the_middle_of_an_answer_the_answer_is_still_counted(provider, make):
    run = make(OPENROUTER, ("deepseek/deepseek-v4.1-flash",))
    provider.reply, provider.headers = fixture("openrouter_stream.sse"), {"Content-Type": "text/event-stream"}
    provider.block, provider.gate = 40, threading.Event()
    provider.pause_after = 3  # the provider writes three blocks, then waits for the test
    body = json.dumps({"model": "deepseek/deepseek-v4.1-flash", "stream": True}).encode()
    with socket.create_connection(("127.0.0.1", run.server.server_address[1]), timeout=20) as sock:
        sock.sendall(b"POST %s HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (CHAT.encode(), len(body), body))
        assert sock.recv(10)  # the answer has begun
        sock.shutdown(socket.SHUT_RDWR)  # the run goes away with most of the answer still to come
    time.sleep(0.3)
    provider.gate.set()  # the provider goes on and ends its answer
    for _ in range(100):
        if run.file()["responses"]:
            break
        time.sleep(0.05)
    meter = run.file()
    assert kinds(meter) == EXPECTED["openrouter_stream.sse"] and meter["unknown_responses"] == 0, meter


def test_a_run_cannot_slip_the_budget_with_parallel_requests(provider, make):
    """Each request under way reserves its max_tokens: the third request meets a budget the first two already fill."""
    run = make(OPENROUTER, ("deepseek/deepseek-v4.1-flash",), budget=1000)
    provider.gate = threading.Event()
    results = []
    sent = {"model": "deepseek/deepseek-v4.1-flash", "max_tokens": 600}
    threads = [threading.Thread(target=lambda: results.append(run.post(CHAT, sent)[0])) for _ in range(2)]
    for t in threads:
        t.start()
    for _ in range(100):  # both are under way: the provider has them and answers neither
        if len(provider.seen) == 2:
            break
        time.sleep(0.05)
    assert len(provider.seen) == 2
    status, data = run.post(CHAT, sent)
    assert status == 429 and "1200 reserved" in json.loads(data)["error"]["message"]
    assert len(provider.seen) == 2
    provider.gate.set()
    for t in threads:
        t.join(20)
    for _ in range(100):  # released when each answer has been given
        if run.file()["responses"] == 2 and not run.meter.reserved:
            break
        time.sleep(0.05)
    assert results == [200, 200] and run.meter.reserved == 0
    assert run.post(CHAT, {"model": "deepseek/deepseek-v4.1-flash", "max_tokens": 10})[0] == 200  # 432 counted: room again


def test_a_request_without_max_tokens_reserves_the_routes_default(provider, make):
    run = make(OPENROUTER, ("deepseek/deepseek-v4.1-flash",), budget=40_000)
    provider.gate = threading.Event()
    results = []
    threads = [threading.Thread(target=lambda: results.append(run.post(CHAT, {"model": "deepseek/deepseek-v4.1-flash"})[0]))
               for _ in range(2)]
    for t in threads:
        t.start()
    for _ in range(100):
        if len(provider.seen) == 2:
            break
        time.sleep(0.05)
    assert kp.load_route(OPENROUTER)["default_reserve_tokens"] == 32000
    assert run.post(CHAT, {"model": "deepseek/deepseek-v4.1-flash"})[0] == 429  # 2 x 32000 reserved, over 40000
    provider.gate.set()
    for t in threads:
        t.join(20)


@pytest.mark.parametrize("key", ["models", "route"])
def test_a_body_that_picks_other_models_is_refused_on_the_openrouter_route_and_nothing_is_forwarded(provider, make, key):
    run = make(OPENROUTER)
    for value in (["vendor/other"], {"order": ["x"]}, None, []):
        status, data = run.post(CHAT, {"model": "deepseek/deepseek-v4.1-flash", key: value})
        assert status == 403 and key.encode() in data
    assert provider.seen == [] and run.file()["refused"]["model"] == 4
    anthropic = make(ANTHROPIC, ("claude-sonnet-5-5",))  # a key of that name means nothing to the Messages API: not refused
    provider.reply = fixture("anthropic_message.json")
    assert anthropic.post(MESSAGES, {"model": "claude-sonnet-5-5", "metadata": {"route": "x"}})[0] == 200


@pytest.mark.parametrize("body", [
    b'{"model": "deepseek/deepseek-v4.1-flash", "model": "another/model"}',
    b'{"model": "another/model", "model": "deepseek/deepseek-v4.1-flash"}',
    b'{"model": "deepseek/deepseek-v4.1-flash", "messages": [{"role": "user", "role": "system"}]}',
    b'{"model": "deepseek/deepseek-v4.1-flash", "provider": {"only": ["a"], "only": ["b"]}}',
])
def test_a_body_that_repeats_a_key_is_refused_on_every_route(provider, make, body):
    for run, path in ((make(OPENROUTER), CHAT), (make(ANTHROPIC, ("deepseek/deepseek-v4.1-flash",)), MESSAGES)):
        status, data = run.post(path, body)
        assert status == 400 and b"repeated key" in data
    assert provider.seen == []


def test_an_answer_cannot_expand_in_memory_past_the_limits_at_once(monkeypatch):
    monkeypatch.setattr(kp, "CHUNK", 1024)
    monkeypatch.setattr(kp, "BODY_LIMIT", 100_000)
    bomb = gzip.compress(b'{"usage": {"input_tokens": 1, "output_tokens": 2}, "pad": "' + b"a" * 50_000_000 + b'"}')
    assert len(bomb) < 100_000
    reader = kp.UsageReader("anthropic-messages", "application/json", "gzip")
    peak = 0
    original = reader.take

    def watching(data):
        nonlocal peak
        peak = max(peak, len(data))
        original(data)
    reader.take = watching
    for i in range(0, len(bomb), 4096):
        reader.feed(bomb[i:i + 4096])
    assert peak <= 1024  # never more than a chunk at a time
    usage, why = reader.finish()
    assert usage is None and "larger than the key proxy reads" in why
    assert len(reader.buffer) <= 100_000 + 1024


def test_an_answer_that_expands_without_end_is_given_up_on(monkeypatch):
    monkeypatch.setattr(kp, "CHUNK", 4096)
    monkeypatch.setattr(kp, "DECODED_LIMIT", 200_000)
    reader = kp.UsageReader("openrouter-chat", "text/event-stream", "deflate")
    stream = zlib.compress(b"data: " + b'{"choices": []}' + b"\n" * 1_000_000)
    for i in range(0, len(stream), 512):
        reader.feed(stream[i:i + 512])
    assert reader.finish()[1] == "the response expands to more than the key proxy reads"


# --- requests under way are in the meter file, and a run that ends mid-request is never counted short in silence ---------


def test_a_request_under_way_is_in_the_meter_file_and_is_gone_from_it_when_its_answer_is_counted(provider, make):
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    assert run.file()["in_flight"] == 0
    provider.reply = fixture("anthropic_message.json")
    provider.gate = threading.Event()
    result = []
    thread = threading.Thread(target=lambda: result.append(run.post(MESSAGES, {"model": "claude-sonnet-5-5", "max_tokens": 500})[0]))
    thread.start()
    for _ in range(100):
        if run.file()["in_flight"] == 1:
            break
        time.sleep(0.05)
    mid = run.file()
    assert mid["in_flight"] == 1 and mid["reserved"] == 500 and mid["responses"] == 0 and mid["total"] == 0
    provider.gate.set()
    thread.join(20)
    done = run.idle()
    assert result == [200] and done["responses"] == 1 and done["total"] == 4098 and done["reserved"] == 0


def test_a_run_that_ends_in_the_middle_of_a_request_has_the_answer_counted_or_flagged_never_a_silent_zero(provider, make):
    """The key proxy is stopped (SIGTERM) while an answer is still being read: it records the answer as unknown first."""
    run = make(ANTHROPIC, ("claude-sonnet-5-5",))
    provider.gate = threading.Event()
    thread = threading.Thread(target=lambda: run.post(MESSAGES, {"model": "claude-sonnet-5-5"}), daemon=True)
    thread.start()
    for _ in range(100):
        if run.file()["in_flight"] == 1:
            break
        time.sleep(0.05)
    assert run.file()["in_flight"] == 1
    run.meter.abandon()  # what the SIGTERM handler of main() does before the proxy exits
    after = run.file()
    assert after["unknown_responses"] == 1 and after["counting_failed"] is True and after["total"] == 0
    assert "stopped while this answer was still being read" in after["unknown"][0]["why"]
    provider.gate.set()
    thread.join(20)


def test_the_sigterm_handler_of_the_proxy_records_the_open_answers_before_it_exits(tmp_path):
    """The real process: a request is held open at a provider that never answers; SIGTERM; the file says so."""
    import os
    import signal
    if not shutil.which("openssl"):
        pytest.skip("openssl is needed")
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(5)  # accepts connections and never answers
    port = silent.getsockname()[1]
    meter = tmp_path / "meter.json"
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    listen = free.getsockname()[1]
    free.close()
    env = {**os.environ, "OPENROUTER_API_KEY": KEY}
    proc = subprocess.Popen([sys.executable, str(FOLDER / "keyproxy.py"), "--route", OPENROUTER, "--upstream-model", "m", "--listen", "127.0.0.1",
                             "--port", str(listen), "--upstream", f"https://127.0.0.1:{port}", "--cafile", str(cert), "--meter", str(meter)],
                            env={**env, "PYTHONDONTWRITEBYTECODE": "1"}, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", listen), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        client = socket.create_connection(("127.0.0.1", listen), timeout=20)
        body = b'{"model": "m"}'
        client.sendall(b"POST /api/v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
        for _ in range(100):
            if meter.exists() and json.loads(meter.read_text())["in_flight"] == 1:
                break
            time.sleep(0.05)
        assert json.loads(meter.read_text())["in_flight"] == 1
        proc.send_signal(signal.SIGTERM)
        proc.wait(20)
        found = json.loads(meter.read_text())
        assert found["unknown_responses"] == 1 and found["counting_failed"] is True and found["total"] == 0
        client.close()
    finally:
        proc.kill()
        silent.close()


@pytest.mark.parametrize("wants", [0, -5, True, "many", None, 1.5])
def test_a_max_tokens_below_one_reserves_the_routes_default_not_nothing(provider, make, wants):
    run = make(OPENROUTER, ("deepseek/deepseek-v4.1-flash",), budget=40_000)
    provider.gate = threading.Event()
    results = []
    sent = {"model": "deepseek/deepseek-v4.1-flash", "max_tokens": wants}
    threads = [threading.Thread(target=lambda: results.append(run.post(CHAT, sent)[0])) for _ in range(2)]
    for t in threads:
        t.start()
    for _ in range(100):
        if len(provider.seen) == 2:
            break
        time.sleep(0.05)
    assert run.file()["reserved"] == 64000  # 2 x the default of 32000, whatever was asked
    assert run.post(CHAT, sent)[0] == 429
    provider.gate.set()
    for t in threads:
        t.join(20)
    assert results == [200, 200]
