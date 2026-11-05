"""Offline tests of how providers/mailbox/gmail.py treats a token or an answer the HTTP library cannot carry: a token with a line break or a
character outside Latin-1 is refused where it is read, a header the library refuses names only the kind of the failure, an answer that is not
HTTP is exit 1, and an unexpected failure prints only its kind. No traceback may hold a token. A one-route stand-in on 127.0.0.1; made-up values.

Run: uv run --with pytest pytest providers/mailbox/tests/test_gmail_token_shape.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "gmail.py"
_spec = importlib.util.spec_from_file_location("gmail_token_shape_under_test", SCRIPT)
gmail = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gmail
_spec.loader.exec_module(gmail)

FINE_ACCESS = "fine-" + "access-token"      # a made-up value for the stand-in server
REFRESH, CLIENT_ID, CLIENT_SECRET = "FAKE-refresh-shape-test", "fake-client.apps.example", "FAKE-client-secret-shape-test"


class Token:
    """A token endpoint on loopback that answers with whatever `answer` holds (a dict, or raw bytes sent as they are)."""

    def __init__(self):
        self.answer = {}
        self.calls = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                owner.calls += 1
                if isinstance(owner.answer, bytes):
                    self.wfile.write(owner.answer)
                    return
                body = json.dumps(owner.answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def token():
    t = Token()
    yield t
    t.close()


BAD = ["good\r\nX-Injected: yes", "tök€n-non-latin1", "has a space", "", None, 7, ["x"], "x" * 5000]


@pytest.mark.parametrize("access", BAD)
def test_a_malformed_access_token_is_refused_where_it_is_read(token, access):
    token.answer = {"access_token": access, "scope": gmail.GMAIL_SCOPE}
    with pytest.raises(gmail.ProviderError) as refused:
        gmail.token_request(token.url + "/token", {"grant_type": "refresh_token"})
    assert "Injected" not in str(refused.value) and "non-latin1" not in str(refused.value)


@pytest.mark.parametrize("refresh", [b for b in BAD if b])
def test_a_malformed_refresh_token_in_the_answer_is_refused_before_anything_stores_it(token, refresh):
    token.answer = {"access_token": FINE_ACCESS, "refresh_token": refresh, "scope": gmail.GMAIL_SCOPE}
    with pytest.raises(gmail.ProviderError) as refused:
        gmail.token_request(token.url + "/token", {"grant_type": "authorization_code"})
    assert "unexpected shape" in str(refused.value) and "Injected" not in str(refused.value)


def test_a_well_formed_answer_is_still_accepted(token):
    token.answer = {"access_token": FINE_ACCESS, "refresh_token": FINE_ACCESS + "-r", "scope": gmail.GMAIL_SCOPE}
    assert gmail.token_request(token.url + "/token", {})["access_token"] == FINE_ACCESS


def test_http_names_only_the_kind_of_a_header_the_library_refuses():
    for headers in ({"Authorization": "Bearer abc\r\nX-Injected: 1"}, {"Authorization": "Bearer tök€n"}):
        with pytest.raises(gmail.ProviderError) as refused:
            gmail.http("GET", "http://127.0.0.1:1/x", headers)
        message = str(refused.value)
        assert "ValueError" in message or "UnicodeEncodeError" in message
        assert "Injected" not in message and "abc" not in message and "tök" not in message


def run(token, *argv):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_"))}
    env.update({"GMAIL_API_BASE": token.url, "GOOGLE_TOKEN_URL": token.url + "/token", "GMAIL_REFRESH_TOKEN": REFRESH,
                "GMAIL_CLIENT_ID": CLIENT_ID, "GMAIL_CLIENT_SECRET": CLIENT_SECRET})
    done = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60, env=env)
    return done.returncode, done.stdout + done.stderr


def test_the_command_line_leaves_no_traceback_for_a_bad_token_or_an_answer_that_is_not_http(token):
    token.answer = {"access_token": "good\r\nX-Injected: yes", "scope": gmail.GMAIL_SCOPE}
    code, text = run(token, "--check")
    assert code == 1 and "unexpected shape" in text and "Traceback" not in text and "Injected" not in text
    token.answer = b"this is not an HTTP answer\r\n\r\n"
    code, text = run(token, "--check")
    assert code == 1 and "BadStatusLine" in text and "Traceback" not in text
    for secret in (REFRESH, CLIENT_SECRET):
        assert secret not in text


def test_the_last_resort_prints_the_kind_and_never_the_message(monkeypatch, capsys):
    def explode(*args):
        raise RuntimeError(f"holds {REFRESH}")
    monkeypatch.setattr(gmail, "cmd_check", explode)
    assert gmail.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "unexpected RuntimeError" in err and REFRESH not in err and "Traceback" not in err
