"""Tests of the network guard of the provider test suites (providers/loopback_only.py): every suite carries the same
conftest.py, and under it a test, and a provider it starts, reaches loopback and nothing else. Offline: the refused
addresses are refused before any packet leaves (192.0.2.1 is a documentation address, RFC 5737).

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_loopback_only.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

PROVIDERS = Path(__file__).resolve().parents[2]
REFUSED = ("192.0.2.1", 443)


def test_every_provider_suite_carries_the_same_guard():
    suites = sorted(p for p in PROVIDERS.glob("*/tests") if any(p.glob("test_*.py")))
    assert len(suites) >= 8
    texts = {(suite / "conftest.py").read_text(encoding="utf-8") if (suite / "conftest.py").is_file() else None
             for suite in suites}
    assert len(texts) == 1 and None not in texts, "a provider suite has no conftest.py or another one"
    assert "loopback_only.guard(monkeypatch, _loopback_site)" in texts.pop()


def test_a_test_reaches_loopback_and_nothing_else():
    with pytest.raises(OSError, match="only loopback is allowed"):
        socket.create_connection(REFUSED, timeout=1)
    with pytest.raises(OSError, match="only loopback is allowed"):
        socket.getaddrinfo("service.example", 443)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp, pytest.raises(OSError, match="only loopback"):
        udp.sendto(b"x", REFUSED)
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
        with socket.create_connection(("localhost", port), timeout=5):
            pass


def test_a_provider_started_with_the_tests_environment_is_guarded_too():
    code = "import socket\nsocket.create_connection(('192.0.2.1', 443), timeout=1)\n"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=dict(os.environ))
    assert done.returncode != 0 and "only loopback is allowed" in done.stderr
