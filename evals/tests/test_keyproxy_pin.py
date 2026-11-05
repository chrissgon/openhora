"""Offline tests of the key proxy's provider pin (evals/container/keyproxy/keyproxy.py, --pin: the pin of a model
comes from the gate file's entry of that model, never from the route file), against a stand-in provider on this
machine that speaks HTTPS with a certificate made for the test. No docker, no real provider, no real key.

Run: uv run --with pytest pytest evals/tests/test_keyproxy_pin.py
"""
from __future__ import annotations

import http.client
import http.server
import importlib.util
import io
import json
import shutil
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "container" / "keyproxy"
ROUTE = str(FOLDER / "route-openrouter.json")
_spec = importlib.util.spec_from_file_location("keyproxy_pin", FOLDER / "keyproxy.py")
kp = importlib.util.module_from_spec(_spec)
_writes = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # a cache folder in evals/container/ would change the definition's hash
try:
    _spec.loader.exec_module(kp)
finally:
    sys.dont_write_bytecode = _writes

KEY = "fake-floor-key-held-by-the-proxy-0003"
PIN = "deepinfra"
MODEL = "vendor/model"


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    """A certificate for 127.0.0.1, made for the test: (certificate, private key)."""
    if not shutil.which("openssl"):
        pytest.skip("openssl is needed to make the stand-in provider's certificate")
    folder = tmp_path_factory.mktemp("tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    return cert, key


class Provider(http.server.ThreadingHTTPServer):
    """The stand-in provider: it records each request and answers 200."""
    daemon_threads = True

    def __init__(self, tls):
        super().__init__(("127.0.0.1", 0), ProviderHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(tls[0]), str(tls[1]))
        self.socket = context.wrap_socket(self.socket, server_side=True)
        self.seen = []


class ProviderHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers.items()),
                                 "body": body})
        out = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = answer


def serve(server):
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


@pytest.fixture
def provider(tls):
    server = serve(Provider(tls))
    yield server
    server.shutdown()
    server.server_close()


def proxy(provider, tls, pin=PIN):
    """A key proxy on 127.0.0.1 in front of the stand-in, started with the model's pin, or with none."""
    route = kp.load_route(ROUTE, f"https://127.0.0.1:{provider.server_address[1]}")
    return serve(kp.KeyProxy(("127.0.0.1", 0), route, KEY, str(tls[0]), None, io.StringIO(), upstream_models=[MODEL], pin=pin))


@pytest.fixture
def pinned(provider, tls):
    server = proxy(provider, tls)
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def unpinned(provider, tls):
    server = proxy(provider, tls, pin=None)
    yield server
    server.shutdown()
    server.server_close()


def call(server, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=20)
    conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def test_a_route_file_names_no_pin_and_one_that_does_is_refused(tmp_path):
    route = json.loads(Path(ROUTE).read_text())
    assert "provider_only" not in route  # the pin is the model's, in the gate file
    route["provider_only"] = PIN
    path = tmp_path / "route-x.json"
    path.write_text(json.dumps(route))
    with pytest.raises(kp.RouteError):
        kp.load_route(str(path))


def test_a_chat_completion_reaches_the_provider_pinned_whatever_the_run_asked_for(provider, pinned):
    sent = {"model": MODEL, "messages": [], "provider": {"order": ["x"]}}
    resp, _ = call(pinned, "POST", "/api/v1/chat/completions", json.dumps(sent).encode())
    assert resp.status == 200
    got = json.loads(provider.seen[-1]["body"])
    assert got["provider"] == {"only": [PIN], "allow_fallbacks": False}
    assert got["model"] == MODEL and got["messages"] == []


def test_a_chat_completion_whose_body_is_not_json_is_refused_and_nothing_is_forwarded(provider, pinned):
    resp, _ = call(pinned, "POST", "/api/v1/chat/completions", b"not json")
    assert resp.status == 400
    assert provider.seen == []


def test_a_request_the_pin_does_not_cover_is_refused_before_it(provider, pinned):
    resp, _ = call(pinned, "GET", "/api/v1/chat/completions")  # a model endpoint takes a POST and its body
    assert resp.status == 405 and provider.seen == []
    resp, _ = call(pinned, "POST", "/api/v1/other", b'{"model": "vendor/model"}')  # not one of the route's paths
    assert resp.status == 403 and provider.seen == []


def test_without_a_pin_a_chat_completion_reaches_the_provider_byte_for_byte(provider, unpinned):
    body = b'{"model":  "vendor/model", "messages": [], "provider": {"order": ["x"]}}'
    resp, _ = call(unpinned, "POST", "/api/v1/chat/completions", body)
    assert resp.status == 200
    assert provider.seen[-1]["body"] == body


@pytest.mark.parametrize("value", ["", 5, "deep{infra", "-deepinfra", " deepinfra"])
def test_a_pin_that_names_no_one_provider_is_refused(provider, tls, value):
    route = kp.load_route(ROUTE, f"https://127.0.0.1:{provider.server_address[1]}")
    with pytest.raises(kp.RouteError):
        kp.KeyProxy(("127.0.0.1", 0), route, KEY, str(tls[0]), None, io.StringIO(), upstream_models=[MODEL], pin=value)


def test_the_length_the_provider_receives_is_the_length_of_the_body_it_receives(provider, pinned):
    sent = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
    resp, _ = call(pinned, "POST", "/api/v1/chat/completions", json.dumps(sent).encode())
    assert resp.status == 200
    seen = provider.seen[-1]
    assert int(seen["headers"]["Content-Length"]) == len(seen["body"])
    assert len(seen["body"]) != len(json.dumps(sent).encode())  # the pin made it longer, and the length followed
