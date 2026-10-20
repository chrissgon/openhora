"""A stand-in for a chat-completions service on this machine, and the helper that runs providers/model/chat-http.py against it.

The stub records every request it receives (method, path, headers, body) and answers with the status, headers and body bytes
the test sets. Nothing here reaches a network but loopback (conftest.py applies providers/loopback_only.py to every test).
Every key, route and text is fictional.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CHAT = Path(__file__).resolve().parents[1] / "chat-http.py"
FAKE_KEY = "sk-test-not-a-key"


def canon(obj) -> bytes:
    """The test's own canonical JSON (the specification's, written out again here, never imported from the provider)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(obj) -> str:
    return hashlib.sha256(canon(obj)).hexdigest()


class Stub:
    def __init__(self):
        self.requests = []
        self.status, self.headers, self.body, self.delay = 200, {"Content-Type": "application/json"}, b"{}", 0.0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _answer(self):
                size = int(self.headers.get("Content-Length") or 0)
                stub.requests.append({"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                      "body": self.rfile.read(size) if size else b""})
                if stub.delay:
                    time.sleep(stub.delay)
                self.send_response(stub.status)
                for k, v in stub.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(stub.body)))
                self.end_headers()
                try:
                    self.wfile.write(stub.body)
                except OSError:
                    pass

            do_POST = do_GET = _answer

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def reply(self, status=200, body=b"{}", headers=None, delay=0.0):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.status, self.body, self.delay = status, body, delay
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    def ok(self, content="hello", **extra):
        doc = {"id": "gen-1", "provider": "Provider-A", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
               "usage": {"prompt_tokens": 120, "completion_tokens": 7, "prompt_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 20}}}
        doc.update(extra)
        self.reply(200, doc)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def route(stub=None, **over):
    base = {"id": "r-test", "base_url": stub.base_url if stub else "http://127.0.0.1:9/v1", "model": "vendor-x/model-a", "pin": "provider-a",
            "allow_fallbacks": False, "data_collection": "deny", "zdr": False, "cache_breakpoint": False}
    base.update(over)
    return base


def request(rt, accepted=None, **over):
    req = {"v": 1, "route": rt, "accepted": [sha(rt)] if accepted is None else accepted,
           "params": {"temperature": 0, "max_tokens": 300, "reasoning": "off"}, "system": "You are a test system.", "user": "A test user line.",
           "deadline_ms": 5000}
    req.update(over)
    return req


def run(args, req=None, *, key=FAKE_KEY, loopback=True, raw=None, extra_env=None, timeout=30, script=None):
    """Start the provider as a child with a minimal environment (PYTHONPATH keeps the loopback guard of conftest.py); returns the CompletedProcess."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "PYTHONPATH", "PYTHON_KEYRING_BACKEND") if k in os.environ}
    if key is not None:
        env["MODEL_TEXT_KEY"] = key
    if loopback:
        env["MODEL_TEXT_LOOPBACK_TEST"] = "1"
    env.update(extra_env or {})
    data = raw if raw is not None else (json.dumps(req) if req is not None else "")
    return subprocess.run([sys.executable, str(script or CHAT), *args], input=data, capture_output=True, text=True, env=env, timeout=timeout, check=False)


def leaked(markers, *streams) -> list:
    """The oracle of every secrecy test: which of the literal markers appear in any of the streams."""
    return [m for m in markers if any(m in (s or "") for s in streams)]


@pytest.fixture
def stub():
    """A running stand-in that answers 200 with a reply; closed after the test. Each test file imports it by name."""
    made = Stub()
    made.ok()
    yield made
    made.close()
