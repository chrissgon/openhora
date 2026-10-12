"""Offline tests for the read-only verb `posts` of providers/publisher/linkedin.py.

Run: uv run --with pytest==9.1.1 pytest providers/publisher/tests/test_publisher_posts_verb.py

The ledger is a fixture written by the test in a temporary directory (PUBLISHER_LINKEDIN_LEDGER), with invented
keys and invented post ids. No network, no credential, no real ledger.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "linkedin.py"

SINCE = "2026-10-01T00:00:00+00:00"
FIXTURE = {
    "version": 2,
    "entries": {
        # before --since: not listed
        "2026-09-20-old-note": {"status": "published", "post_urn": "urn:li:share:7000000000000000101",
                                "created_at": "2026-09-20T09:00:00Z", "payload_sha256": "a" * 64},
        # listed, the later one first in the file to show the order is by time
        "2026-10-04-second-note": {"status": "published", "post_urn": "urn:li:share:7000000000000000103",
                                   "created_at": "2026-10-04T08:30:00Z", "payload_sha256": "b" * 64},
        "2026-10-02-first-note": {"status": "published", "post_urn": "urn:li:share:7000000000000000102",
                                  "created_at": "2026-10-02T07:15:00Z", "payload_sha256": "c" * 64},
        # exactly at --since: listed
        "2026-10-01-edge-note": {"status": "published", "post_urn": "urn:li:share:7000000000000000104",
                                 "created_at": "2026-10-01T00:00:00Z"},
        # a comment (the first comment of a post): never listed
        "2026-10-02-first-note.first-comment": {
            "kind": "comment", "status": "published", "post_urn": "urn:li:share:7000000000000000102",
            "comment_urn": "urn:li:comment:(urn:li:activity:7000000000000000202,7100000000000000001)",
            "created_at": "2026-10-02T07:16:00Z"},
        # pending and released attempts: never listed
        "2026-10-05-pending-note": {"status": "pending", "started_at": "2026-10-05T06:00:00Z"},
        # written before version 2: no status (published, it has a post id) and no time: undated, whatever --since
        "2026-05-01-early-note": {"post_urn": "urn:li:share:7000000000000000100"},
    },
}


def write_ledger(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "ledger" / "publisher-linkedin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path


def env_for(tmp_path: Path, ledger: Path) -> dict:
    base = {k: v for k, v in os.environ.items() if not k.startswith(("LINKEDIN_", "PUBLISHER_"))}
    base.update({"HOME": str(tmp_path / "home"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
                 "XDG_DATA_HOME": str(tmp_path / "data"), "PUBLISHER_LINKEDIN_LEDGER": str(ledger)})
    return base


def run(args, env):
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


def test_posts_lists_only_published_posts_since_the_given_time(tmp_path):
    ledger = write_ledger(tmp_path, FIXTURE)
    before = ledger.read_bytes()
    proc = run(["posts", "--platform", "linkedin", "--since", SINCE], env_for(tmp_path, ledger))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert (out["platform"], out["since"], out["ledger"]) == ("linkedin", SINCE, str(ledger))
    assert out["posts"] == [
        {"idempotency_key": "2026-10-01-edge-note",
         "post_url": "https://www.linkedin.com/feed/update/urn:li:share:7000000000000000104/",
         "published_at": "2026-10-01T00:00:00Z"},
        {"idempotency_key": "2026-10-02-first-note",
         "post_url": "https://www.linkedin.com/feed/update/urn:li:share:7000000000000000102/",
         "published_at": "2026-10-02T07:15:00Z"},
        {"idempotency_key": "2026-10-04-second-note",
         "post_url": "https://www.linkedin.com/feed/update/urn:li:share:7000000000000000103/",
         "published_at": "2026-10-04T08:30:00Z"},
    ]
    # the entry with no time is named, never given a derived one
    assert out["undated"] == ["2026-05-01-early-note"]
    # read-only: the ledger is byte for byte the same, and no lock or copy was made beside it
    assert ledger.read_bytes() == before
    assert sorted(p.name for p in ledger.parent.iterdir()) == [ledger.name]

    # an offset other than UTC compares as the same instant: 02:00+02:00 is 00:00Z
    proc = run(["posts", "--platform", "linkedin", "--since", "2026-10-02T09:15:00+02:00"], env_for(tmp_path, ledger))
    assert [p["idempotency_key"] for p in json.loads(proc.stdout)["posts"]] == [
        "2026-10-02-first-note", "2026-10-04-second-note"]

    # no ledger yet: nothing listed, nothing created
    missing = tmp_path / "none" / "publisher-linkedin.json"
    proc = run(["posts", "--platform", "linkedin", "--since", SINCE], env_for(tmp_path, missing))
    assert proc.returncode == 0, proc.stderr
    assert (json.loads(proc.stdout)["posts"], json.loads(proc.stdout)["undated"]) == ([], [])
    assert not missing.parent.exists()


def test_posts_reads_no_credential_and_makes_no_request(tmp_path, monkeypatch):
    ledger = write_ledger(tmp_path, FIXTURE)
    for key, value in env_for(tmp_path, ledger).items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("linkedin_posts_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(name):
        def call(*args, **kwargs):
            raise AssertionError(f"posts called {name}")
        return call

    for name in ("load_token", "secret_resolver", "http", "userinfo", "ledger_save", "ledger_locked",
                 "ledger_migrate", "ledger_update", "ledger_claim"):
        monkeypatch.setattr(module, name, forbidden(name))
    monkeypatch.setattr(module.urllib.request, "urlopen", forbidden("urlopen"))
    monkeypatch.setattr("socket.socket.connect", forbidden("socket.connect"))
    monkeypatch.setitem(sys.modules, "keyring", None)  # any import of the secret store's library fails
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "FAKE-posts-token-never-read")
    out = io.StringIO()
    with redirect_stdout(out):
        code = module.main(["posts", "--platform", "linkedin", "--since", SINCE])
    assert code == 0
    printed = out.getvalue()
    assert len(json.loads(printed)["posts"]) == 3
    assert "FAKE-posts-token" not in printed


def test_a_time_without_an_offset_is_refused(tmp_path):
    ledger = write_ledger(tmp_path, FIXTURE)
    env = env_for(tmp_path, ledger)
    for since in ("2026-10-01T00:00:00", "2026-10-01", "last week"):
        proc = run(["posts", "--platform", "linkedin", "--since", since], env)
        assert proc.returncode == 2, (since, proc.stdout, proc.stderr)
        assert proc.stdout == ""
        assert "--since" in proc.stderr
    # the verb's own usage errors use the same exit code
    assert run(["posts", "--platform", "linkedin"], env).returncode == 2
    assert run(["posts", "--platform", "example-network", "--since", SINCE], env).returncode == 2
    assert run(["posts", "--platform", "linkedin", "--since", SINCE, "--dry-run"], env).returncode == 2
    assert run(["publish", "--platform", "linkedin", "--since", SINCE], env).returncode == 2


@pytest.mark.parametrize("entry", [
    {"status": "published", "post_urn": "urn:li:share:7000000000000000105", "created_at": "not a time"},
    {"status": "published", "post_urn": "urn:li:share:7000000000000000105", "created_at": "2026-10-03T10:00:00"},
])
def test_a_published_post_whose_time_cannot_be_read_is_undated(tmp_path, entry):
    ledger = write_ledger(tmp_path, {"version": 2, "entries": {"2026-10-03-odd-note": entry}})
    proc = run(["posts", "--platform", "linkedin", "--since", SINCE], env_for(tmp_path, ledger))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert (out["posts"], out["undated"]) == ([], ["2026-10-03-odd-note"])


def test_the_help_names_the_verb():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert "posts     List the published posts" in proc.stdout
    assert "--since" in proc.stdout
