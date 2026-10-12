"""Offline tests for providers/publisher/linkedin.py and auth.py.

Run: uv run --with pytest pytest providers/publisher/tests

No network and no real credentials: a local fake LinkedIn server answers on
127.0.0.1 (LINKEDIN_API_BASE), the token is a fake one in LINKEDIN_ACCESS_TOKEN,
and the idempotency ledger lives in a temporary directory (PUBLISHER_LINKEDIN_LEDGER).
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "linkedin.py"
AUTH_SCRIPT = HERE.parent / "auth.py"
FAKE_TOKEN = "FAKE-test-token-9f8e7d6c5b4a-never-print-me"
SUB = "782bbtaQ"
AUTHOR = f"urn:li:person:{SUB}"
POST_URN = "urn:li:share:7000000000000000001"
IMAGE_URN = "urn:li:image:C4E10AQFoyyAjHPMQuQ"
RESERVED_TEXT = "a\\b|c{d}e@f[g]h(i)j<k>l#m*n_o~p"
RESERVED_ESCAPED = "a\\\\b\\|c\\{d\\}e\\@f\\[g\\]h\\(i\\)j\\<k\\>l\\#m\\*n\\_o\\~p"
THREAD_URN = "urn:li:activity:7000000000000000009"
COMMENT_ID = "7100000000000000001"
COMMENT_URN = f"urn:li:comment:({THREAD_URN},{COMMENT_ID})"
PARENT_URN = f"urn:li:comment:({THREAD_URN},7100000000000000000)"
POST_COMMENTS_PATH = "/v2/socialActions/urn%3Ali%3Ashare%3A7000000000000000001/comments"
COMMENT_TEXT = "Link: https://example.com/a_(b) #tag @name"


def load_module():
    spec = importlib.util.spec_from_file_location("linkedin_provider", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLinkedIn:
    """A tiny LinkedIn stand-in that records every request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.post_status = 201
        self.post_delay = 0.0
        self.userinfo_status = 200
        self.redirect_userinfo = False
        self.comment_status = 201
        self.comment_statuses = []  # when set, each comment request takes the next status from this list first
        self.comment_delay = 0.0
        self.comment_message = "Comment create throttled: creation rate limit exceeded for member"
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _record(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                fake.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })
                return body

            def _send(self, status, payload=None, headers=None):
                data = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                if payload is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                self._record()
                if self.path == "/v2/userinfo":
                    if fake.redirect_userinfo:
                        return self._send(302, None, {"Location": f"{fake.base}/captured"})
                    if fake.userinfo_status != 200:
                        return self._send(fake.userinfo_status, {"message": "Invalid access token", "status": 401})
                    return self._send(200, {"sub": SUB, "name": "Test Member", "given_name": "Test"})
                self._send(404, {"message": "not found"})

            def do_POST(self):  # noqa: N802
                self._record()
                if self.path == "/rest/images?action=initializeUpload":
                    return self._send(200, {"value": {
                        "uploadUrlExpiresAt": 1650567510704,
                        "uploadUrl": f"{fake.base}/dms-uploads/C4E10AQFoyyAjHPMQuQ/uploaded-image/0?ut=abc",
                        "image": IMAGE_URN,
                    }})
                if self.path == "/rest/posts":
                    if fake.post_delay:
                        time.sleep(fake.post_delay)
                    if fake.post_status != 201:
                        return self._send(fake.post_status, {"message": "MISSING_FIELD", "status": fake.post_status})
                    return self._send(201, None, {"x-restli-id": POST_URN})
                if (self.path.startswith("/v2/socialActions/") or self.path.startswith("/rest/socialActions/")) and self.path.endswith("/comments"):
                    if fake.comment_delay:
                        time.sleep(fake.comment_delay)
                    status = fake.comment_statuses.pop(0) if fake.comment_statuses else fake.comment_status
                    if status != 201:
                        return self._send(status, {"message": fake.comment_message, "status": status})
                    return self._send(201, {"commentUrn": COMMENT_URN, "id": COMMENT_ID, "object": THREAD_URN,
                                            "actor": AUTHOR, "message": {"attributes": [], "text": "x"}},
                                      {"x-restli-id": COMMENT_ID})
                self._send(404, {"message": "not found"})

            def do_PUT(self):  # noqa: N802
                self._record()
                if self.path.startswith("/dms-uploads/"):
                    return self._send(201)
                self._send(404, {"message": "not found"})

            def log_message(self, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def paths(self):
        return [(r["method"], r["path"]) for r in self.requests]


@pytest.fixture()
def fake():
    server = FakeLinkedIn()
    yield server
    server.close()


@pytest.fixture()
def env(tmp_path, fake):
    base_env = {k: v for k, v in os.environ.items()
                if not k.startswith(("LINKEDIN_", "PUBLISHER_"))}
    base_env.update({
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "LINKEDIN_API_BASE": fake.base,
        "LINKEDIN_ACCESS_TOKEN": FAKE_TOKEN,
        "LINKEDIN_TOKEN_EXPIRES_AT": (datetime.now(timezone.utc) + timedelta(days=45, hours=1)).isoformat(),
        "PUBLISHER_LINKEDIN_LEDGER": str(tmp_path / "ledger" / "publisher-linkedin.json"),
    })
    return base_env


@pytest.fixture()
def text_file(tmp_path):
    path = tmp_path / "post.txt"
    path.write_text(RESERVED_TEXT + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def image_file(tmp_path):
    path = tmp_path / "cover.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes" * 4)
    return path


def run(script, args, env):
    proc = subprocess.run([sys.executable, str(script), *args], env=env,
                          capture_output=True, text=True, timeout=60)
    # No run may ever print the token, not even partially.
    for stream in (proc.stdout, proc.stderr):
        assert FAKE_TOKEN not in stream
        assert FAKE_TOKEN[:12] not in stream
    return proc


def publish_args(text_file, *extra):
    """publish arguments; a fresh idempotency key is added unless the test passes one."""
    args = ["publish", "--platform", "linkedin", "--text-file", str(text_file), *extra]
    if "--idempotency-key" not in extra:
        args += ["--idempotency-key", f"test-{uuid.uuid4().hex}"]
    return args


def ledger(env):
    path = Path(env["PUBLISHER_LINKEDIN_LEDGER"])
    return json.loads(path.read_text())["entries"] if path.exists() else {}


def post_count(fake):
    return len([p for p in fake.paths() if p == ("POST", "/rest/posts")])


def comment_count(fake):
    return len([p for m, p in fake.paths() if m == "POST" and (p.startswith("/v2/socialActions/") or p.startswith("/rest/socialActions/"))])


@pytest.fixture()
def comment_file(tmp_path):
    path = tmp_path / "comment.txt"
    path.write_text(COMMENT_TEXT + "\n", encoding="utf-8")
    return path


def comment_args(comment_file, *extra):
    """comment arguments; a fresh idempotency key is added unless the test passes one."""
    args = ["comment", "--platform", "linkedin", "--text-file", str(comment_file), *extra]
    if "--idempotency-key" not in extra:
        args += ["--idempotency-key", f"c-{uuid.uuid4().hex}"]
    return args


def assert_rest_headers(request):
    h = request["headers"]
    assert h["authorization"] == f"Bearer {FAKE_TOKEN}"
    assert h["linkedin-version"] == "202609"
    assert h["x-restli-protocol-version"] == "2.0.0"
    assert h["content-type"] == "application/json"


def expected_post(image_urn=None):
    body = {
        "author": AUTHOR,
        "commentary": RESERVED_ESCAPED,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn}}
    return body


# --- unit ----------------------------------------------------------------------


def test_escape_every_reserved_character():
    module = load_module()
    assert module.escape_little_text(RESERVED_TEXT) == RESERVED_ESCAPED
    assert module.escape_little_text("plain text, ok! 100% sure.") == "plain text, ok! 100% sure."
    assert module.escape_little_text("\\*") == "\\\\\\*"


# --- help and guards -------------------------------------------------------------


def test_help_documents_env_and_verbs(env):
    proc = run(SCRIPT, ["--help"], env)
    assert proc.returncode == 0
    for word in ("publish", "--check", "--dry-run", "--confirmed", "LINKEDIN_API_BASE",
                 "PUBLISHER_LINKEDIN_LEDGER", "LINKEDIN_ACCESS_TOKEN", "202609"):
        assert word in proc.stdout


def test_refuses_without_confirmed(env, fake, text_file):
    proc = run(SCRIPT, publish_args(text_file), env)
    assert proc.returncode == 2
    assert "--confirmed" in proc.stderr
    assert fake.requests == []
    assert proc.stdout == ""


def test_refuses_future_at(env, fake, text_file):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    proc = run(SCRIPT, publish_args(text_file, "--at", future, "--confirmed"), env)
    assert proc.returncode == 2
    assert "scheduler" in proc.stderr
    assert fake.requests == []


def test_past_at_publishes_now(env, fake, text_file):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    proc = run(SCRIPT, publish_args(text_file, "--at", past, "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert ("POST", "/rest/posts") in fake.paths()


def test_rejects_two_images(env, fake, text_file, image_file):
    proc = run(SCRIPT, publish_args(text_file, "--media", str(image_file), "--media", str(image_file),
                                    "--confirmed"), env)
    assert proc.returncode == 2
    assert fake.requests == []


def test_rejects_wrong_platform(env, fake, text_file):
    args = ["publish", "--platform", "x", "--text-file", str(text_file), "--confirmed"]
    assert run(SCRIPT, args, env).returncode == 2


def test_rejects_non_loopback_api_base(env, text_file):
    env["LINKEDIN_API_BASE"] = "https://evil.example.com"
    proc = run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    assert proc.returncode == 2
    assert "loopback" in proc.stderr


def test_not_configured_without_token(env, fake, text_file):
    del env["LINKEDIN_ACCESS_TOKEN"]
    proc = run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    assert proc.returncode == 3
    assert fake.requests == []


def test_expired_token_is_not_configured(env, fake, text_file):
    env["LINKEDIN_TOKEN_EXPIRES_AT"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    proc = run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    assert proc.returncode == 3
    assert "expired" in proc.stderr
    assert fake.requests == []


# --- dry run -------------------------------------------------------------------


def test_dry_run_text_prints_exact_body_and_posts_nothing(env, fake, text_file):
    proc = run(SCRIPT, publish_args(text_file, "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["dry_run"] is True
    assert len(out["requests"]) == 1
    req = out["requests"][0]
    assert req["method"] == "POST" and req["url"] == f"{fake.base}/rest/posts"
    body = dict(req["body"])
    assert body.pop("author").startswith("urn:li:person:<")
    assert body == {k: v for k, v in expected_post().items() if k != "author"}
    assert req["headers"]["Authorization"] == "Bearer <redacted>"
    assert req["headers"]["LinkedIn-Version"] == "202609"
    assert fake.requests == []


def test_dry_run_with_image_uses_placeholder(env, fake, text_file, image_file):
    proc = run(SCRIPT, publish_args(text_file, "--media", str(image_file), "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    reqs = json.loads(proc.stdout)["requests"]
    assert [r["method"] for r in reqs] == ["POST", "PUT", "POST"]
    assert reqs[0]["body"]["initializeUploadRequest"]["owner"].startswith("urn:li:person:<")
    assert reqs[2]["body"]["content"]["media"]["id"] == "<image URN returned by initializeUpload>"
    assert fake.requests == []


def test_dry_run_without_token_still_prints(env, fake, text_file):
    del env["LINKEDIN_ACCESS_TOKEN"]
    proc = run(SCRIPT, publish_args(text_file, "--dry-run"), env)
    assert proc.returncode == 0
    body = json.loads(proc.stdout)["requests"][0]["body"]
    assert body["author"].startswith("urn:li:person:<")
    assert fake.requests == []


def test_dry_run_reads_no_token(env, fake, text_file):
    # L05: the dry run read the token and called /v2/userinfo.
    env["LINKEDIN_TOKEN_EXPIRES_AT"] = "not a date"  # reading the token would report this
    proc = run(SCRIPT, publish_args(text_file, "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    assert "token" not in proc.stderr.lower()
    assert fake.requests == []


# --- publish -------------------------------------------------------------------


def test_publish_text_sends_exact_request(env, fake, text_file):
    proc = run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert fake.paths() == [("GET", "/v2/userinfo"), ("POST", "/rest/posts")]
    assert fake.requests[0]["headers"]["authorization"] == f"Bearer {FAKE_TOKEN}"
    post = fake.requests[1]
    assert_rest_headers(post)
    assert json.loads(post["body"]) == expected_post()
    out = json.loads(proc.stdout)
    assert out["post_urn"] == POST_URN
    assert out["post_url"] == f"https://www.linkedin.com/feed/update/{POST_URN}/"
    assert out["token_expires_at"].startswith(
        (datetime.now(timezone.utc) + timedelta(days=45, hours=1)).date().isoformat())
    assert out["token_expires_in_days"] == 45
    assert out["replayed"] is False


def test_publish_with_image_upload_sequence(env, fake, text_file, image_file):
    proc = run(SCRIPT, publish_args(text_file, "--media", str(image_file), "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert [m for m, _ in fake.paths()] == ["GET", "POST", "PUT", "POST"]
    _, init, upload, post = fake.requests
    assert init["path"] == "/rest/images?action=initializeUpload"
    assert_rest_headers(init)
    assert json.loads(init["body"]) == {"initializeUploadRequest": {"owner": AUTHOR}}
    assert upload["path"] == "/dms-uploads/C4E10AQFoyyAjHPMQuQ/uploaded-image/0?ut=abc"
    assert upload["headers"]["authorization"] == f"Bearer {FAKE_TOKEN}"
    assert upload["body"] == image_file.read_bytes()
    assert post["path"] == "/rest/posts"
    assert json.loads(post["body"]) == expected_post(IMAGE_URN)


def test_service_error_exits_1(env, fake, text_file):
    fake.post_status = 400
    proc = run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    assert proc.returncode == 1
    assert "400" in proc.stderr and "MISSING_FIELD" in proc.stderr


def test_rejected_token_exits_3(env, fake, text_file):
    fake.userinfo_status = 401
    proc = run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    assert proc.returncode == 3
    assert ("POST", "/rest/posts") not in fake.paths()


# --- idempotency ---------------------------------------------------------------


def test_idempotency_key_posts_once(env, fake, text_file):
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed")
    first = run(SCRIPT, args, env)
    assert first.returncode == 0, first.stderr
    second = run(SCRIPT, args, env)
    assert second.returncode == 0, second.stderr
    assert [p for p in fake.paths() if p == ("POST", "/rest/posts")] == [("POST", "/rest/posts")]
    assert json.loads(second.stdout)["post_urn"] == POST_URN
    assert json.loads(second.stdout)["replayed"] is True
    ledger = json.loads(Path(env["PUBLISHER_LINKEDIN_LEDGER"]).read_text())
    assert ledger["entries"]["launch-1"]["post_urn"] == POST_URN
    assert FAKE_TOKEN not in Path(env["PUBLISHER_LINKEDIN_LEDGER"]).read_text()
    # A different key publishes again.
    third = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-2", "--confirmed"), env)
    assert third.returncode == 0
    assert len([p for p in fake.paths() if p == ("POST", "/rest/posts")]) == 2


def test_dry_run_reports_existing_key(env, fake, text_file):
    run(SCRIPT, publish_args(text_file, "--idempotency-key", "k", "--confirmed"), env)
    proc = run(SCRIPT, publish_args(text_file, "--idempotency-key", "k", "--dry-run"), env)
    assert json.loads(proc.stdout)["existing_post_urn"] == POST_URN


def test_idempotency_key_is_required(env, fake, text_file):
    # M06: the key was optional, so a retry could publish twice.
    args = ["publish", "--platform", "linkedin", "--text-file", str(text_file)]
    for extra in (["--confirmed"], ["--dry-run"], ["--idempotency-key", " ", "--confirmed"]):
        proc = run(SCRIPT, args + extra, env)
        assert proc.returncode == 2, extra
        assert "--idempotency-key" in proc.stderr
    assert fake.requests == []


def test_timeout_leaves_pending_and_blocks_a_second_post(env, fake, text_file):
    # M06: the ledger was written after the POST; a timeout then a retry published twice.
    fake.post_delay = 2.0
    env["LINKEDIN_HTTP_TIMEOUT"] = "0.5"
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed")
    first = run(SCRIPT, args, env)
    assert first.returncode == 1
    assert "timed out" in first.stderr
    assert ledger(env)["launch-1"]["status"] == "pending"
    fake.post_delay = 0.0
    second = run(SCRIPT, args, env)
    assert second.returncode == 1
    assert "pending" in second.stderr and "resolve" in second.stderr
    assert post_count(fake) == 1


def test_resolve_a_pending_key(env, fake, text_file):
    fake.post_delay = 2.0
    env["LINKEDIN_HTTP_TIMEOUT"] = "0.5"
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed")
    assert run(SCRIPT, args, env).returncode == 1
    fake.post_delay = 0.0
    resolve = ["resolve", "--idempotency-key", "launch-1"]
    assert run(SCRIPT, resolve + ["--post-id", POST_URN], env).returncode == 2  # needs --confirmed
    assert run(SCRIPT, resolve + ["--post-id", POST_URN, "--confirmed"], env).returncode == 0
    replay = run(SCRIPT, args, env)
    assert replay.returncode == 0 and json.loads(replay.stdout)["replayed"] is True
    assert post_count(fake) == 1
    # A key found not published is released and may be posted again.
    fake.post_delay = 2.0
    args2 = publish_args(text_file, "--idempotency-key", "launch-2", "--confirmed")
    assert run(SCRIPT, args2, env).returncode == 1
    fake.post_delay = 0.0
    done = run(SCRIPT, ["resolve", "--idempotency-key", "launch-2", "--not-published", "--confirmed"], env)
    assert done.returncode == 0, done.stderr
    assert "launch-2" not in ledger(env)
    assert run(SCRIPT, args2, env).returncode == 0
    assert post_count(fake) == 3
    # Only a pending key can be resolved.
    assert run(SCRIPT, resolve + ["--not-published", "--confirmed"], env).returncode == 2


def test_two_runs_at_once_publish_once(env, fake, text_file):
    fake.post_delay = 1.0
    args = [sys.executable, str(SCRIPT), *publish_args(text_file, "--idempotency-key", "same", "--confirmed")]
    procs = [subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    results = [(p.wait(timeout=30), p.stderr.read()) for p in procs]
    for p in procs:
        p.stdout.close()
        p.stderr.close()
    assert sorted(code for code, _ in results) == [0, 1]
    assert any("pending" in err for code, err in results if code == 1)
    assert post_count(fake) == 1
    assert ledger(env)["same"]["status"] == "published"


def test_failure_before_the_post_releases_the_key(env, fake, text_file):
    fake.userinfo_status = 401
    args = publish_args(text_file, "--idempotency-key", "k", "--confirmed")
    assert run(SCRIPT, args, env).returncode == 3
    assert "k" not in ledger(env)
    fake.userinfo_status = 200
    fake.post_status = 400
    assert run(SCRIPT, args, env).returncode == 1
    assert "k" not in ledger(env)
    fake.post_status = 201
    assert run(SCRIPT, args, env).returncode == 0
    assert ledger(env)["k"]["status"] == "published"


def test_ledger_is_private(env, fake, text_file):
    run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    path = Path(env["PUBLISHER_LINKEDIN_LEDGER"])
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


# --- redirects -----------------------------------------------------------------


def test_redirect_is_not_followed_with_the_token(env, fake, text_file):
    # L04: urllib followed redirects and forwarded the Authorization header.
    fake.redirect_userinfo = True
    proc = run(SCRIPT, publish_args(text_file, "--confirmed"), env)
    assert proc.returncode == 1
    assert "redirect" in proc.stderr
    assert fake.paths() == [("GET", "/v2/userinfo")]
    assert post_count(fake) == 0


# --- check ---------------------------------------------------------------------


def test_check_reports_member_and_expiry(env, fake):
    proc = run(SCRIPT, ["--check"], env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ready"] is True
    assert out["member_name"] == "Test Member"
    assert out["person_urn"] == AUTHOR
    assert out["token_expires_in_days"] == 45
    assert "warning" not in out


def test_check_warns_under_seven_days(env, fake):
    env["LINKEDIN_TOKEN_EXPIRES_AT"] = (datetime.now(timezone.utc) + timedelta(days=3, hours=1)).isoformat()
    proc = run(SCRIPT, ["--check"], env)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["token_expires_in_days"] == 3
    assert "warning" in proc.stderr


def test_check_with_a_platform_answers_whether_this_provider_serves_it(env, fake):
    proc = run(SCRIPT, ["--check", "--platform", "linkedin"], env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["platform"] == "linkedin"
    proc = run(SCRIPT, ["--check", "--platform", "chirp"], env)
    assert proc.returncode == 2 and "is not served by this provider" in proc.stderr and not proc.stdout.strip()


def test_the_served_platforms_are_declared_on_one_line_the_resolver_reads_as_text():
    lines = [line for line in SCRIPT.read_text(encoding="utf-8").splitlines() if line.startswith("PLATFORMS")]
    assert lines == ['PLATFORMS = ("linkedin",)']


def test_check_exits_3_when_the_person_has_something_to_do(env, fake):
    """The contract's one reading: 3 is "not configured" (no token, an expired one, a rejected one)."""
    fake.userinfo_status = 401  # the service rejects the token
    proc = run(SCRIPT, ["--check"], env)
    assert proc.returncode == 3 and "rejected the token" in proc.stderr
    env["LINKEDIN_TOKEN_EXPIRES_AT"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    proc = run(SCRIPT, ["--check"], env)
    assert proc.returncode == 3 and "expired" in proc.stderr
    del env["LINKEDIN_ACCESS_TOKEN"]
    proc = run(SCRIPT, ["--check"], env)
    assert proc.returncode == 3 and "auth.py --provider linkedin" in proc.stderr
    assert not proc.stdout.strip()


def test_check_exits_1_when_the_service_could_not_be_asked(env, fake):
    """1 is "whether the provider is ready is not known": the service is down or answered something else."""
    fake.userinfo_status = 503
    proc = run(SCRIPT, ["--check"], env)
    assert proc.returncode == 1 and "503" in proc.stderr
    env["LINKEDIN_API_BASE"] = "http://127.0.0.1:1"  # nothing listens there
    proc = run(SCRIPT, ["--check"], env)
    assert proc.returncode == 1 and "cannot reach LinkedIn" in proc.stderr


# --- auth.py -------------------------------------------------------------------


def test_auth_help_documents_setup(env):
    proc = run(AUTH_SCRIPT, ["--help"], env)
    assert proc.returncode == 0
    for word in ("Share on LinkedIn", "OpenID Connect", "http://localhost:8765/callback",
                 "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"):
        assert word in proc.stdout


def test_auth_without_client_env_is_not_configured(env):
    proc = run(AUTH_SCRIPT, ["--provider", "linkedin", "--no-browser"], env)
    assert proc.returncode == 3
    assert "LINKEDIN_CLIENT_ID" in proc.stderr


class FakeTokenEndpoint:
    """A token endpoint that answers 302 to /elsewhere, which hands out a token: what a hijacked or
    misconfigured endpoint would do. Both live on 127.0.0.1."""

    def __init__(self, redirect: bool):
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                fake.requests.append({"method": self.command, "path": self.path,
                                      "body": self.rfile.read(length).decode() if length else ""})
                if self.path == "/token" and redirect:
                    self.send_response(302)
                    self.send_header("Location", f"{fake.base}/elsewhere")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = json.dumps({"access_token": "FAKE-token-from-" + self.path.strip("/"),
                                   "expires_in": 5184000}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer  # noqa: N815

            def log_message(self, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def load_auth():
    spec = importlib.util.spec_from_file_location("linkedin_auth", AUTH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_password(self, service, username):
        return self.values.get((service, username))


def auth_with(monkeypatch, environ, stored=None):
    """auth.py with a resolver that reads this environment and this fake store, never the machine's."""
    auth = load_auth()
    resolver = auth.secret_resolver()
    real_resolve = resolver.resolve
    store = FakeStore({("openhora", "publisher-linkedin"): stored} if stored else {})
    monkeypatch.setattr(resolver, "resolve", lambda name, **kw: real_resolve(name, environ=environ, store=store))
    monkeypatch.setattr(auth, "secret_resolver", lambda: resolver)
    monkeypatch.delenv("LINKEDIN_TOKEN_EXPIRES_AT", raising=False)
    return auth


def test_auth_check_finds_a_token_given_through_the_environment(monkeypatch, capsys):
    """PUB5: --check read the OS secret store directly, so a token from the environment (a cloud session,
    CI) was reported as not stored, while the provider, which reads through the resolver, worked."""
    auth = auth_with(monkeypatch, {"LINKEDIN_ACCESS_TOKEN": FAKE_TOKEN})
    assert auth.main(["--provider", "linkedin", "--check"]) == 0
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert report["found"] is True and report["stored"] is False
    assert report["source"] == "environment (LINKEDIN_ACCESS_TOKEN)" and report["expired"] is False
    assert FAKE_TOKEN not in out.out + out.err
    assert "get_password" not in AUTH_SCRIPT.read_text(encoding="utf-8")  # the store is read by the resolver only


def test_auth_check_reads_the_stored_record_and_its_expiry(monkeypatch, capsys):
    soon = (datetime.now(timezone.utc) + timedelta(days=30, hours=1)).isoformat()
    record = json.dumps({"access_token": FAKE_TOKEN, "expires_at": soon, "scope": "openid"})
    auth = auth_with(monkeypatch, {}, stored=record)
    assert auth.main(["--provider", "linkedin", "--check"]) == 0
    out = capsys.readouterr()
    report = json.loads(out.out)
    assert (report["stored"], report["source"], report["expires_in_days"]) == (True, "secret store", 30)
    assert FAKE_TOKEN not in out.out + out.err


def test_auth_check_exits_3_when_the_person_has_something_to_do(monkeypatch, capsys):
    """The contract's one reading of --check: no token, an unreadable record or an expired token is 3."""
    auth = auth_with(monkeypatch, {})
    assert auth.main(["--provider", "linkedin", "--check"]) == 3
    assert json.loads(capsys.readouterr().out) == {"provider": "linkedin", "found": False, "stored": False}
    auth = auth_with(monkeypatch, {}, stored="not json")
    assert auth.main(["--provider", "linkedin", "--check"]) == 3
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    auth = auth_with(monkeypatch, {}, stored=json.dumps({"access_token": FAKE_TOKEN, "expires_at": past}))
    assert auth.main(["--provider", "linkedin", "--check"]) == 3
    assert '"expired": true' in capsys.readouterr().out


def test_a_silent_connection_does_not_block_the_callback(monkeypatch):
    """PUB3: the listener serves one connection at a time and had no timeout, so a local connection that
    sent nothing held it for ever: the real callback waited behind it, and so did the shutdown."""
    auth = load_auth()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(auth, "CALLBACK_HOST", "127.0.0.1")
    monkeypatch.setattr(auth, "CALLBACK_PORT", port)
    monkeypatch.setattr(auth, "CALLBACK_HANDLER_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(auth, "CALLBACK_TIMEOUT_SECONDS", 10)
    got: dict = {}
    waiter = threading.Thread(target=lambda: got.update(code=auth.wait_for_code("st")), daemon=True)
    waiter.start()
    silent = None
    for _ in range(100):  # until the listener is up
        try:
            silent = socket.create_connection(("127.0.0.1", port), timeout=5)
            break
        except OSError:
            time.sleep(0.05)
    assert silent is not None
    try:
        time.sleep(0.1)  # the listener is now inside the silent connection
        url = f"http://127.0.0.1:{port}/callback?" + urllib.parse.urlencode({"state": "st", "code": "c"})
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.status == 200
        waiter.join(5)
        assert not waiter.is_alive() and got == {"code": "c"}
    finally:
        silent.close()


def test_the_callback_page_is_titled_openhora(monkeypatch):
    auth = load_auth()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(auth, "CALLBACK_HOST", "127.0.0.1")
    monkeypatch.setattr(auth, "CALLBACK_PORT", port)
    monkeypatch.setattr(auth, "CALLBACK_TIMEOUT_SECONDS", 10)
    got: dict = {}
    waiter = threading.Thread(target=lambda: got.update(code=auth.wait_for_code("st")), daemon=True)
    waiter.start()
    url = f"http://127.0.0.1:{port}/callback?" + urllib.parse.urlencode({"state": "st", "code": "c"})
    page = None
    for _ in range(100):  # until the listener is up
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                page = response.read().decode()
            break
        except OSError:
            time.sleep(0.05)
    assert page is not None and "<title>openhora</title>" in page and "ai-workbench" not in page
    waiter.join(5)
    assert not waiter.is_alive() and got == {"code": "c"}


def test_token_exchange_refuses_a_redirect(monkeypatch):
    # PUB4: the exchange used the default opener, which follows redirects: the answer of wherever the
    # redirect pointed was taken as the member's token, for a request that carried the client secret.
    auth = load_auth()
    endpoint = FakeTokenEndpoint(redirect=True)
    try:
        monkeypatch.setattr(auth, "LINKEDIN_TOKEN_URL", f"{endpoint.base}/token")
        with pytest.raises(auth.AuthError) as err:
            auth.exchange_code("FAKE-code", "FAKE-client-id", "FAKE-client-secret")
        assert "redirect" in str(err.value) and "FAKE-client-secret" not in str(err.value)
        assert [r["path"] for r in endpoint.requests] == ["/token"]  # /elsewhere was never asked
    finally:
        endpoint.close()


def test_token_exchange_takes_the_endpoint_s_own_answer(monkeypatch):
    auth = load_auth()
    endpoint = FakeTokenEndpoint(redirect=False)
    try:
        monkeypatch.setattr(auth, "LINKEDIN_TOKEN_URL", f"{endpoint.base}/token")
        token = auth.exchange_code("FAKE-code", "FAKE-client-id", "FAKE-client-secret")
        assert token["access_token"] == "FAKE-token-from-token"
        assert "client_secret=FAKE-client-secret" in endpoint.requests[0]["body"]
    finally:
        endpoint.close()


def test_a_scheduled_copy_needs_the_resolver_in_its_snapshot(env, fake, tmp_path):
    """The scheduler runs a copy of this script from <job>/files/; the resolver must be copied with it."""
    import shutil
    files = tmp_path / "job" / "files"
    files.mkdir(parents=True)
    alone = files / "linkedin.py"
    shutil.copyfile(SCRIPT, alone)
    proc = run(alone, ["--check"], env)
    assert proc.returncode != 0 and "snapshot" in proc.stderr
    shutil.copyfile(HERE.parents[1] / "secrets" / "resolver.py", files / "resolver.py")
    proc = run(alone, ["--check"], env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ready"] is True


# --- hashtags in post commentary ---------------------------------------------------


def test_hashtags_use_the_documented_template():
    module = load_module()
    render = module.post_commentary
    assert render("Ship it #DesignTokens #design_systems now") == \
        "Ship it {hashtag|\\#|DesignTokens} {hashtag|\\#|design\\_systems} now"
    assert render("(#tag). #end") == "\\({hashtag|\\#|tag}\\). {hashtag|\\#|end}"
    assert render("#tag\nnext") == "{hashtag|\\#|tag}\nnext"
    # Not hashtags: inside a word, digits only, non-ASCII letters, a bare sign. They stay escaped.
    for text in ("a#b", "#1 priority", "#café", "# alone", "C#"):
        assert render(text) == module.escape_little_text(text), text
    # A mention stays plain text.
    assert render("@name") == "\\@name"
    # Everything else is escaped exactly as before.
    assert render(RESERVED_TEXT) == RESERVED_ESCAPED


def test_publish_sends_hashtag_template(env, fake, tmp_path):
    path = tmp_path / "tags.txt"
    path.write_text("Launch #DesignTokens @team", encoding="utf-8")
    proc = run(SCRIPT, publish_args(path, "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(fake.requests[1]["body"])["commentary"] == "Launch {hashtag|\\#|DesignTokens} \\@team"


# --- comment ---------------------------------------------------------------------


def test_help_documents_comment(env):
    proc = run(SCRIPT, ["--help"], env)
    for word in ("comment", "--first-comment-file", "--on-key", "--parent-comment-id", "--comment-id",
                 ".first-comment"):
        assert word in proc.stdout


def test_help_names_the_generic_identifiers_and_their_aliases(env):
    """The class's verbs take --post-id, --comment-id and --parent-comment-id (providers/CONTRACT.md); the
    names in use before stay as aliases, so a command written with them keeps working."""
    out = run(SCRIPT, ["--help"], env).stdout
    for generic, alias in (("--post-id", "--post-urn"), ("--comment-id", "--comment-urn"),
                           ("--parent-comment-id", "--parent-comment")):
        assert generic in out and alias in out


def test_the_old_flag_names_are_aliases_of_the_generic_ones(env, fake, comment_file):
    def dry(*flags):
        proc = run(SCRIPT, comment_args(comment_file, *flags, "--idempotency-key", "c1", "--dry-run"), env)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    generic = dry("--post-id", POST_URN, "--parent-comment-id", PARENT_URN)
    assert generic["post_urn"] == POST_URN and generic["parent_comment"] == PARENT_URN
    assert dry("--post-urn", POST_URN, "--parent-comment", PARENT_URN) == generic
    assert fake.requests == []


def test_a_reply_sent_with_the_old_flag_names_is_the_same_request(env, fake, comment_file):
    proc = run(SCRIPT, comment_args(comment_file, "--post-urn", POST_URN, "--parent-comment", PARENT_URN,
                                    "--idempotency-key", "c-old", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert fake.requests[1]["path"] == ("/v2/socialActions/urn%3Ali%3Acomment%3A%28urn%3Ali%3Aactivity%3A"
                                        "7000000000000000009%2C7100000000000000000%29/comments")
    again = run(SCRIPT, comment_args(comment_file, "--post-id", POST_URN, "--parent-comment-id", PARENT_URN,
                                     "--idempotency-key", "c-old", "--confirmed"), env)
    assert again.returncode == 0 and json.loads(again.stdout)["replayed"] is True, "one key, one comment"


def test_resolve_takes_the_old_flag_names_too(env, fake, comment_file):
    """Whatever resolve answers about a key, it answers the same under either name of the flag."""
    for key, alias, generic, value in (("old-post", "--post-urn", "--post-id", POST_URN),
                                       ("old-comment", "--comment-urn", "--comment-id", COMMENT_URN)):
        answers = [run(SCRIPT, ["resolve", "--idempotency-key", key, flag, value, "--dry-run"], env)
                   for flag in (alias, generic)]
        assert "unrecognized arguments" not in answers[0].stderr
        assert (answers[0].returncode, answers[0].stdout, answers[0].stderr) == \
               (answers[1].returncode, answers[1].stdout, answers[1].stderr)
    assert fake.requests == []


def test_comment_sends_exact_request(env, fake, comment_file):
    proc = run(SCRIPT, comment_args(comment_file, "--post-id", POST_URN, "--idempotency-key", "c1",
                                    "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert fake.paths() == [("GET", "/v2/userinfo"), ("POST", POST_COMMENTS_PATH)]
    req = fake.requests[1]
    h = {k.lower(): v for k, v in req["headers"].items()}
    assert h["authorization"] == f"Bearer {FAKE_TOKEN}" and "linkedin-version" not in h  # /v2 is unversioned
    # The comment text is sent as written: comments are not little text.
    assert json.loads(req["body"]) == {"actor": AUTHOR, "object": POST_URN, "message": {"text": COMMENT_TEXT}}
    out = json.loads(proc.stdout)
    assert out["comment_urn"] == COMMENT_URN
    assert out["post_urn"] == POST_URN
    assert out["parent_comment"] is None
    assert out["idempotency_key"] == "c1"
    assert out["replayed"] is False
    assert out["token_expires_in_days"] == 45
    assert ledger(env)["c1"]["status"] == "published"
    assert ledger(env)["c1"]["comment_urn"] == COMMENT_URN


def test_reply_targets_the_encoded_parent_comment(env, fake, comment_file):
    proc = run(SCRIPT, comment_args(comment_file, "--post-id", POST_URN, "--parent-comment-id", PARENT_URN,
                                    "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    req = fake.requests[1]
    assert req["path"] == ("/v2/socialActions/urn%3Ali%3Acomment%3A%28urn%3Ali%3Aactivity%3A"
                           "7000000000000000009%2C7100000000000000000%29/comments")
    assert json.loads(req["body"]) == {"actor": AUTHOR, "object": POST_URN, "message": {"text": COMMENT_TEXT},
                                       "parentComment": PARENT_URN}
    assert json.loads(proc.stdout)["parent_comment"] == PARENT_URN


def test_comment_replays_its_key(env, fake, comment_file):
    args = comment_args(comment_file, "--post-id", POST_URN, "--idempotency-key", "c1", "--confirmed")
    assert run(SCRIPT, args, env).returncode == 0
    again = run(SCRIPT, args, env)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["replayed"] is True
    assert json.loads(again.stdout)["comment_urn"] == COMMENT_URN
    assert comment_count(fake) == 1
    # The same key on another post is a mistake, not a replay.
    other = comment_args(comment_file, "--post-id", "urn:li:share:1", "--idempotency-key", "c1", "--confirmed")
    assert run(SCRIPT, other, env).returncode == 2
    # A post key cannot be reused for a comment, nor a comment key for a post.
    run(SCRIPT, publish_args(comment_file, "--idempotency-key", "p1", "--confirmed"), env)
    assert run(SCRIPT, comment_args(comment_file, "--post-id", POST_URN, "--idempotency-key", "p1",
                                    "--confirmed"), env).returncode == 2
    assert run(SCRIPT, publish_args(comment_file, "--idempotency-key", "c1", "--confirmed"), env).returncode == 2
    assert comment_count(fake) == 1 and post_count(fake) == 1


def test_comment_on_key_uses_the_published_post(env, fake, text_file, comment_file):
    assert run(SCRIPT, publish_args(text_file, "--idempotency-key", "p1", "--confirmed"), env).returncode == 0
    proc = run(SCRIPT, comment_args(comment_file, "--on-key", "p1", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert fake.requests[-1]["path"] == POST_COMMENTS_PATH
    assert json.loads(fake.requests[-1]["body"])["object"] == POST_URN
    assert json.loads(proc.stdout)["post_urn"] == POST_URN


def test_comment_on_key_refuses_an_unpublished_post(env, fake, text_file, comment_file):
    proc = run(SCRIPT, comment_args(comment_file, "--on-key", "never-published", "--confirmed"), env)
    assert proc.returncode == 2
    assert "not a published post" in proc.stderr
    # A pending post is refused too.
    fake.post_delay = 2.0
    env["LINKEDIN_HTTP_TIMEOUT"] = "0.5"
    assert run(SCRIPT, publish_args(text_file, "--idempotency-key", "p1", "--confirmed"), env).returncode == 1
    fake.post_delay = 0.0
    proc = run(SCRIPT, comment_args(comment_file, "--on-key", "p1", "--confirmed"), env)
    assert proc.returncode == 2
    assert "pending" in proc.stderr
    assert comment_count(fake) == 0


def test_comment_refuses_invalid_urns(env, fake, comment_file):
    bad = [
        ["--post-id", "urn:li:share:123/../../v2/me"],
        ["--post-id", "urn:li:person:123"],
        ["--post-id", "urn:li:share:12a"],
        ["--post-id", POST_URN, "--parent-comment-id", "urn:li:comment:(urn:li:activity:1,2)/x"],
        ["--post-id", POST_URN, "--parent-comment-id", "urn:li:comment:(urn:li:person:1,2)"],
        ["--post-id", POST_URN, "--on-key", "p1"],
        [],
    ]
    for extra in bad:
        proc = run(SCRIPT, comment_args(comment_file, *extra, "--confirmed"), env)
        assert proc.returncode == 2, extra
    assert fake.requests == []


def test_comment_refuses_empty_text_and_missing_key(env, fake, tmp_path, comment_file):
    empty = tmp_path / "empty.txt"
    empty.write_text("\n  \n", encoding="utf-8")
    assert run(SCRIPT, comment_args(empty, "--post-id", POST_URN, "--confirmed"), env).returncode == 2
    args = ["comment", "--platform", "linkedin", "--text-file", str(comment_file), "--post-id", POST_URN,
            "--confirmed"]
    proc = run(SCRIPT, args, env)
    assert proc.returncode == 2 and "--idempotency-key" in proc.stderr
    assert fake.requests == []


def test_comment_refuses_without_confirmed(env, fake, comment_file):
    proc = run(SCRIPT, comment_args(comment_file, "--post-id", POST_URN), env)
    assert proc.returncode == 2
    assert "--confirmed" in proc.stderr
    assert fake.requests == [] and proc.stdout == ""


def test_comment_dry_run_reads_no_token(env, fake, comment_file):
    del env["LINKEDIN_ACCESS_TOKEN"]
    env["LINKEDIN_TOKEN_EXPIRES_AT"] = "not a date"  # reading the token would report this
    proc = run(SCRIPT, comment_args(comment_file, "--post-id", POST_URN, "--parent-comment-id", PARENT_URN,
                                    "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    assert "token" not in proc.stderr.lower()
    out = json.loads(proc.stdout)
    assert out["dry_run"] is True
    (req,) = out["requests"]
    assert req["url"].endswith("/v2/socialActions/urn%3Ali%3Acomment%3A%28urn%3Ali%3Aactivity%3A"
                               "7000000000000000009%2C7100000000000000000%29/comments")
    assert req["headers"]["Authorization"] == "Bearer <redacted>"
    body = dict(req["body"])
    assert body.pop("actor").startswith("urn:li:person:<")
    assert body == {"object": POST_URN, "message": {"text": COMMENT_TEXT}, "parentComment": PARENT_URN}
    # With --on-key, a post not published yet is a placeholder in the dry run.
    proc = run(SCRIPT, comment_args(comment_file, "--on-key", "later", "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["requests"][0]["body"]["object"].startswith("<post URN")
    assert fake.requests == []


def test_comment_timeout_stays_pending_until_resolve(env, fake, comment_file):
    fake.comment_delay = 2.0
    env["LINKEDIN_HTTP_TIMEOUT"] = "0.5"
    args = comment_args(comment_file, "--post-id", POST_URN, "--idempotency-key", "c1", "--confirmed")
    first = run(SCRIPT, args, env)
    assert first.returncode == 1 and "timed out" in first.stderr
    assert ledger(env)["c1"]["status"] == "pending"
    assert ledger(env)["c1"]["kind"] == "comment"
    fake.comment_delay = 0.0
    second = run(SCRIPT, args, env)
    assert second.returncode == 1
    assert "pending" in second.stderr and "--comment-id" in second.stderr
    assert comment_count(fake) == 1
    resolve = ["resolve", "--idempotency-key", "c1", "--confirmed"]
    assert run(SCRIPT, resolve + ["--post-id", POST_URN], env).returncode == 2  # a comment key
    assert run(SCRIPT, resolve + ["--comment-id", "urn:li:comment:(bad)"], env).returncode == 2
    done = run(SCRIPT, resolve + ["--comment-id", COMMENT_URN], env)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"idempotency_key": "c1", "status": "published", "comment_urn": COMMENT_URN}
    replay = run(SCRIPT, args, env)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["replayed"] is True
    assert json.loads(replay.stdout)["comment_urn"] == COMMENT_URN
    assert comment_count(fake) == 1


def test_resolve_refuses_comment_urn_for_a_post_key(env, fake, text_file):
    fake.post_delay = 2.0
    env["LINKEDIN_HTTP_TIMEOUT"] = "0.5"
    assert run(SCRIPT, publish_args(text_file, "--idempotency-key", "p1", "--confirmed"), env).returncode == 1
    proc = run(SCRIPT, ["resolve", "--idempotency-key", "p1", "--comment-id", COMMENT_URN, "--confirmed"], env)
    assert proc.returncode == 2 and "--post-id" in proc.stderr
    both = ["resolve", "--idempotency-key", "p1", "--post-id", POST_URN, "--comment-id", COMMENT_URN,
            "--confirmed"]
    assert run(SCRIPT, both, env).returncode == 2
    assert ledger(env)["p1"]["status"] == "pending"


def test_comment_403_names_the_scope(env, fake, comment_file):
    fake.comment_status = 403
    fake.comment_message = "Not enough permissions to access: partnerApiSocialActions.CREATE"
    proc = run(SCRIPT, comment_args(comment_file, "--post-id", POST_URN, "--idempotency-key", "c1",
                                    "--confirmed"), env)
    assert proc.returncode == 1
    assert "403" in proc.stderr and "w_member_social" in proc.stderr
    assert "c1" not in ledger(env)  # LinkedIn refused it: the key is free again


@pytest.mark.parametrize("status", [408, 429])
def test_comment_408_or_429_keeps_the_key_pending(env, fake, comment_file, status):
    # FR-I12: every 4xx answer deleted the pending entry, so a rerun sent the comment again. A 408 or a 429
    # does not say that the request was refused: the key stays pending until resolve settles it.
    fake.comment_status = status
    args = comment_args(comment_file, "--post-id", POST_URN, "--idempotency-key", "c1", "--confirmed")
    proc = run(SCRIPT, args, env)
    assert proc.returncode == 1
    assert str(status) in proc.stderr and "stays pending" in proc.stderr and "resolve" in proc.stderr
    if status == 429:
        assert "throttled" in proc.stderr and "minute" in proc.stderr
    assert ledger(env)["c1"]["status"] == "pending"
    fake.comment_status = 201
    blocked = run(SCRIPT, args, env)
    assert blocked.returncode == 1 and "pending" in blocked.stderr
    assert comment_count(fake) == 1  # nothing was sent a second time
    released = run(SCRIPT, ["resolve", "--idempotency-key", "c1", "--not-published", "--confirmed"], env)
    assert released.returncode == 0, released.stderr
    retry = run(SCRIPT, args, env)
    assert retry.returncode == 0, retry.stderr
    assert comment_count(fake) == 2


@pytest.mark.parametrize("status", [408, 429])
def test_post_408_or_429_keeps_the_key_pending(env, fake, text_file, status):
    fake.post_status = status
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed")
    first = run(SCRIPT, args, env)
    assert first.returncode == 1 and "stays pending" in first.stderr
    assert ledger(env)["launch-1"]["status"] == "pending"
    fake.post_status = 201
    second = run(SCRIPT, args, env)
    assert second.returncode == 1 and "pending" in second.stderr and "resolve" in second.stderr
    assert post_count(fake) == 1  # not posted again on the rerun
    done = run(SCRIPT, ["resolve", "--idempotency-key", "launch-1", "--post-id", POST_URN, "--confirmed"], env)
    assert done.returncode == 0, done.stderr
    replay = run(SCRIPT, args, env)
    assert replay.returncode == 0 and json.loads(replay.stdout)["replayed"] is True and post_count(fake) == 1


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_a_refused_post_releases_the_key(env, fake, text_file, status):
    fake.post_status = status
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed")
    assert run(SCRIPT, args, env).returncode == 1
    assert "launch-1" not in ledger(env)


def test_resolve_dry_run_changes_nothing(env, fake, text_file):
    # PUB2: resolve ignored --dry-run. With --confirmed next to it, the pending entry was deleted and the next
    # run published a second time.
    fake.post_delay = 2.0
    env["LINKEDIN_HTTP_TIMEOUT"] = "0.5"
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed")
    assert run(SCRIPT, args, env).returncode == 1
    fake.post_delay = 0.0
    before = Path(env["PUBLISHER_LINKEDIN_LEDGER"]).read_bytes()
    resolve = ["resolve", "--idempotency-key", "launch-1", "--not-published"]
    for extra in (["--dry-run", "--confirmed"], ["--dry-run"]):
        shown = run(SCRIPT, resolve + extra, env)
        assert shown.returncode == 0, shown.stderr
        out = json.loads(shown.stdout)
        assert out["dry_run"] is True and out["would_record"] == "released"
        assert out["pending_entry"]["status"] == "pending"
        assert Path(env["PUBLISHER_LINKEDIN_LEDGER"]).read_bytes() == before
    blocked = run(SCRIPT, args, env)
    assert blocked.returncode == 1 and "pending" in blocked.stderr
    assert post_count(fake) == 1  # the key is still held: nothing was published again
    shown = run(SCRIPT, ["resolve", "--idempotency-key", "launch-1", "--post-id", POST_URN, "--dry-run"], env)
    assert json.loads(shown.stdout)["would_record"] == "published"
    assert run(SCRIPT, ["resolve", "--idempotency-key", "nope", "--not-published", "--dry-run"], env).returncode == 2
    assert run(SCRIPT, resolve + ["--confirmed"], env).returncode == 0
    assert "launch-1" not in ledger(env)


# --- publish with a first comment ------------------------------------------------------


def test_publish_with_first_comment_in_one_command(env, fake, text_file, comment_file):
    args = publish_args(text_file, "--first-comment-file", str(comment_file), "--idempotency-key", "p1",
                        "--confirmed")
    proc = run(SCRIPT, args, env)
    assert proc.returncode == 0, proc.stderr
    assert fake.paths() == [("GET", "/v2/userinfo"), ("POST", "/rest/posts"), ("POST", POST_COMMENTS_PATH)]
    assert json.loads(fake.requests[1]["body"]) == expected_post()
    assert json.loads(fake.requests[2]["body"]) == {"actor": AUTHOR, "object": POST_URN,
                                                    "message": {"text": COMMENT_TEXT}}
    out = json.loads(proc.stdout)
    assert out["post_urn"] == POST_URN and out["replayed"] is False
    assert out["first_comment"] == {"comment_urn": COMMENT_URN, "idempotency_key": "p1.first-comment",
                                    "replayed": False}
    entries = ledger(env)
    assert entries["p1"]["status"] == "published"
    assert entries["p1.first-comment"]["status"] == "published"
    # Running it again sends nothing: both are replayed.
    again = run(SCRIPT, args, env)
    assert again.returncode == 0, again.stderr
    out = json.loads(again.stdout)
    assert out["replayed"] is True and out["first_comment"]["replayed"] is True
    assert post_count(fake) == 1 and comment_count(fake) == 1


def test_first_comment_failure_then_rerun_posts_only_the_comment(env, fake, text_file, comment_file):
    fake.comment_status = 403  # a refusal: the comment's key is released, so the rerun sends it again
    args = publish_args(text_file, "--first-comment-file", str(comment_file), "--idempotency-key", "p1",
                        "--confirmed")
    first = run(SCRIPT, args, env)
    assert first.returncode == 1
    out = json.loads(first.stdout)
    assert out["post_urn"] == POST_URN and out["post_url"]
    assert out["first_comment"] is None
    assert "403" in out["first_comment_error"]
    assert "published" in first.stderr and "Rerun the same command" in first.stderr
    fake.comment_status = 201
    second = run(SCRIPT, args, env)
    assert second.returncode == 0, second.stderr
    out = json.loads(second.stdout)
    assert out["replayed"] is True
    assert out["first_comment"]["comment_urn"] == COMMENT_URN and out["first_comment"]["replayed"] is False
    assert post_count(fake) == 1
    assert comment_count(fake) == 2  # the refused one and the one that went out


def test_first_comment_is_retried_while_the_post_is_not_available_yet(env, fake, text_file, comment_file):
    fake.comment_statuses = [404, 404]
    fake.comment_message = "Unable to obtain activity for urn"
    env["PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS"] = "0,0,0"
    r = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(comment_file), "--idempotency-key", "p1",
                                 "--confirmed"), env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["first_comment"]["comment_urn"] == COMMENT_URN
    assert r.stderr.count("retrying the first comment") == 2
    assert post_count(fake) == 1 and comment_count(fake) == 3


def test_first_comment_404_on_every_attempt_fails_and_can_be_rerun(env, fake, text_file, comment_file):
    fake.comment_status = 404
    env["PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS"] = "0,0"
    args = publish_args(text_file, "--first-comment-file", str(comment_file), "--idempotency-key", "p1", "--confirmed")
    r = run(SCRIPT, args, env)
    assert r.returncode == 1 and "404" in json.loads(r.stdout)["first_comment_error"]
    assert comment_count(fake) == 3  # one attempt and two retries
    fake.comment_status = 201
    r = run(SCRIPT, args, env)
    assert r.returncode == 0 and json.loads(r.stdout)["first_comment"]["replayed"] is False
    assert post_count(fake) == 1


def test_first_comment_other_refusals_are_not_retried(env, fake, text_file, comment_file):
    fake.comment_status = 403
    env["PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS"] = "0,0"
    r = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(comment_file), "--idempotency-key", "p1",
                                 "--confirmed"), env)
    assert r.returncode == 1 and comment_count(fake) == 1


def test_bad_retry_delays_are_refused(env, fake, text_file, comment_file):
    fake.comment_status = 404
    """PUB6: the setting was read inside the first-comment step, after the post was public. It is a usage
    error found before anything is sent: no request, no ledger entry, in a dry run too."""
    for bad in ("soon", "5,-1", "1,2,3,4,5,6,7,8,9", "301"):
        env["PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS"] = bad
        for mode in ("--confirmed", "--dry-run"):
            r = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(comment_file),
                                         "--idempotency-key", "p1", mode), env)
            assert r.returncode == 2 and "PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS" in r.stderr, (bad, mode)
            assert not r.stdout.strip()
    assert fake.requests == [] and ledger(env) == {}
    # A post without a first comment does not read the setting at all.
    r = run(SCRIPT, publish_args(text_file, "--idempotency-key", "p2", "--confirmed"), env)
    assert r.returncode == 0, r.stderr


def test_first_comment_unknown_outcome_blocks_only_the_comment(env, fake, text_file, comment_file):
    fake.comment_status = 500
    args = publish_args(text_file, "--first-comment-file", str(comment_file), "--idempotency-key", "p1",
                        "--confirmed")
    assert run(SCRIPT, args, env).returncode == 1
    assert ledger(env)["p1.first-comment"]["status"] == "pending"
    fake.comment_status = 201
    again = run(SCRIPT, args, env)
    assert again.returncode == 1
    assert "pending" in json.loads(again.stdout)["first_comment_error"]
    assert post_count(fake) == 1 and comment_count(fake) == 1


def test_publish_dry_run_shows_the_first_comment(env, fake, text_file, comment_file):
    proc = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(comment_file),
                                    "--idempotency-key", "p1", "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    post, comment = out["requests"]
    assert post["url"].endswith("/rest/posts")
    assert comment["method"] == "POST" and "/v2/socialActions/" in comment["url"]
    assert comment["body"]["object"] == "<post URN returned by the Posts API>"
    assert comment["body"]["message"] == {"text": COMMENT_TEXT}
    assert out["first_comment_idempotency_key"] == "p1.first-comment"
    assert out["first_comment_existing_status"] is None
    assert fake.requests == []
    # Once the post is out, the dry run shows its real URN.
    run(SCRIPT, publish_args(text_file, "--idempotency-key", "p1", "--confirmed"), env)
    proc = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(comment_file),
                                    "--idempotency-key", "p1", "--dry-run"), env)
    comment = json.loads(proc.stdout)["requests"][1]
    assert comment["url"].endswith(POST_COMMENTS_PATH)
    assert comment["body"]["object"] == POST_URN


def test_first_comment_file_must_exist_and_have_text(env, fake, text_file, tmp_path):
    missing = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(tmp_path / "no.txt"),
                                       "--confirmed"), env)
    assert missing.returncode == 2 and "--first-comment-file" in missing.stderr
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    assert run(SCRIPT, publish_args(text_file, "--first-comment-file", str(empty), "--confirmed"),
               env).returncode == 2
    assert fake.requests == []


def test_comment_dry_run_accepts_the_short_comment_urn_of_a_copied_link(tmp_path, monkeypatch):
    text = tmp_path / "reply.txt"
    text.write_text("Thanks!")
    monkeypatch.setenv("PUBLISHER_LINKEDIN_LEDGER", str(tmp_path / "ledger.json"))
    r = subprocess.run([sys.executable, str(SCRIPT), "comment", "--platform", "linkedin", "--text-file", str(text),
                        "--idempotency-key", "reply-1", "--post-id", "urn:li:activity:7400000000000000001",
                        "--parent-comment-id", "urn:li:comment:(activity:7400000000000000001,7400000000000000002)",
                        "--dry-run"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "urn:li:comment:(urn:li:activity:7400000000000000001,7400000000000000002)" in r.stdout


def test_comment_legacy_v2_dry_run_targets_the_unversioned_endpoint(tmp_path, monkeypatch):
    text = tmp_path / "reply.txt"
    text.write_text("Thanks!")
    monkeypatch.setenv("PUBLISHER_LINKEDIN_LEDGER", str(tmp_path / "ledger.json"))
    r = subprocess.run([sys.executable, str(SCRIPT), "comment", "--platform", "linkedin", "--text-file", str(text),
                        "--idempotency-key", "reply-2", "--post-id", "urn:li:activity:7400000000000000001",
                        "--parent-comment-id", "urn:li:comment:(urn:li:activity:7400000000000000001,7400000000000000002)",
                        "--legacy-v2", "--dry-run"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    req = json.loads(r.stdout)["requests"][0]
    assert "/v2/socialActions/" in req["url"] and "LinkedIn-Version" not in req["headers"]


def test_comments_endpoint_rest_keeps_the_versioned_path(tmp_path, monkeypatch):
    text = tmp_path / "reply.txt"
    text.write_text("Thanks!")
    monkeypatch.setenv("PUBLISHER_LINKEDIN_LEDGER", str(tmp_path / "ledger.json"))
    r = subprocess.run([sys.executable, str(SCRIPT), "comment", "--platform", "linkedin", "--text-file", str(text),
                        "--idempotency-key", "reply-3", "--post-id", "urn:li:activity:7400000000000000001",
                        "--comments-endpoint", "rest", "--dry-run"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    req = json.loads(r.stdout)["requests"][0]
    assert "/rest/socialActions/" in req["url"] and req["headers"]["LinkedIn-Version"]


# --- the ledger lives in a data folder; a ledger at its old place in the cache folder is copied once ---

def default_ledger_env(env, tmp_path):
    """The environment without a ledger override: (env, new ledger path, old ledger path)."""
    e = {k: v for k, v in env.items() if k != "PUBLISHER_LINKEDIN_LEDGER"}
    e["XDG_DATA_HOME"] = str(tmp_path / "data")
    if sys.platform == "darwin":
        new = tmp_path / "home" / "Library" / "Application Support" / "ai-workbench" / "publisher-linkedin.json"
    else:
        new = tmp_path / "data" / "ai-workbench" / "publisher-linkedin.json"
    return e, new, tmp_path / "cache" / "ai-workbench" / "publisher-linkedin.json"


def test_default_ledger_is_in_the_data_folder_not_the_cache(env, fake, text_file, tmp_path):
    e, new, old = default_ledger_env(env, tmp_path)
    proc = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed"), e)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(new.read_text())["entries"]["launch-1"]["post_urn"] == POST_URN
    assert not (tmp_path / "cache").exists()
    assert "ledger moved" not in proc.stderr  # nothing to migrate
    assert oct(new.stat().st_mode & 0o777) == "0o600" and oct(new.parent.stat().st_mode & 0o777) == "0o700"
    second = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed"), e)
    assert json.loads(second.stdout)["replayed"] is True and post_count(fake) == 1


def test_old_ledger_is_read_by_a_dry_run_and_copied_by_the_first_real_verb(env, fake, text_file, tmp_path):
    e, new, old = default_ledger_env(env, tmp_path)
    # The post went out before the move: the provider of that time recorded it in the cache folder.
    first = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed"),
                {**env, "PUBLISHER_LINKEDIN_LEDGER": str(old)})
    assert first.returncode == 0 and post_count(fake) == 1 and not new.exists()
    before = old.read_bytes()
    # A dry run reads the old ledger where the new one does not exist yet, and writes nothing: no copy, no folder.
    dry = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--dry-run"), e)
    assert json.loads(dry.stdout)["existing_post_urn"] == POST_URN  # found on the very first read
    assert "ledger moved" not in dry.stderr and not new.exists() and not new.parent.exists()
    comment = tmp_path / "c.txt"
    comment.write_text("Thanks!")
    on_key = run(SCRIPT, ["comment", "--platform", "linkedin", "--text-file", str(comment), "--idempotency-key", "c-1",
                          "--on-key", "launch-1", "--dry-run"], e)
    assert json.loads(on_key.stdout)["post_urn"] == POST_URN and "ledger moved" not in on_key.stderr
    resolve = run(SCRIPT, ["resolve", "--idempotency-key", "launch-1", "--not-published", "--dry-run"], e)
    assert resolve.returncode == 2 and "ledger moved" not in resolve.stderr  # the key is published: nothing to do
    assert not new.parent.exists()
    # The first real verb copies it, and finds the key there.
    proc = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed"), e)
    assert proc.returncode == 0, proc.stderr
    assert "ledger moved" in proc.stderr and str(old) in proc.stderr and str(new) in proc.stderr
    assert new.read_bytes() == before and oct(new.stat().st_mode & 0o777) == "0o600"
    assert json.loads(proc.stdout)["replayed"] is True and json.loads(proc.stdout)["post_urn"] == POST_URN
    assert post_count(fake) == 1  # not published twice
    again = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed"), e)
    assert again.returncode == 0 and "ledger moved" not in again.stderr  # copied once
    assert old.read_bytes() == before  # never edited, never deleted
    # After the copy the new ledger is the only one read and written.
    assert run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-2", "--confirmed"), e).returncode == 0
    assert set(json.loads(new.read_text())["entries"]) == {"launch-1", "launch-2"}
    assert old.read_bytes() == before


def test_existing_new_ledger_is_never_replaced_by_the_old_one(env, fake, text_file, tmp_path):
    e, new, old = default_ledger_env(env, tmp_path)
    other = "urn:li:share:7000000000000000009"
    for path, urn in ((old, other), (new, POST_URN)):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"version": 2, "entries": {
            "launch-1": {"status": "published", "post_urn": urn, "created_at": "2026-10-01T00:00:00Z"}}}))
    dry = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--dry-run"), e)
    assert json.loads(dry.stdout)["existing_post_urn"] == POST_URN and "ledger moved" not in dry.stderr


def test_old_ledger_that_is_not_json_stops_the_run(env, fake, text_file, tmp_path):
    e, new, old = default_ledger_env(env, tmp_path)
    old.parent.mkdir(parents=True)
    old.write_text("{not json")
    proc = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed"), e)
    assert proc.returncode == 1 and "cannot be copied" in proc.stderr
    assert fake.requests == [] and not new.exists() and old.read_text() == "{not json"


def test_ledger_flag_pins_the_ledger_and_refuses_another(env, fake, text_file, tmp_path):
    # FR-I12: a scheduler starts its jobs without the caller's environment, so a job approved where
    # PUBLISHER_LINKEDIN_LEDGER was set looked its key up in the default ledger at its slot, and the other way
    # round: one key, two ledgers, two posts. A command that runs later carries the ledger's path.
    pinned = tmp_path / "pinned" / "ledger.json"
    scheduled = {k: v for k, v in env.items() if k != "PUBLISHER_LINKEDIN_LEDGER"}  # the variable is not inherited
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--ledger", str(pinned))
    dry = run(SCRIPT, args + ["--dry-run"], scheduled)
    assert dry.returncode == 0 and json.loads(dry.stdout)["ledger"] == str(pinned)
    first = run(SCRIPT, args + ["--confirmed"], scheduled)
    assert first.returncode == 0, first.stderr
    assert json.loads(pinned.read_text())["entries"]["launch-1"]["post_urn"] == POST_URN
    assert not (tmp_path / "home").exists() or not list((tmp_path / "home").rglob("publisher-linkedin.json"))
    # The same command by hand, where the variable names another ledger: refused before anything is sent.
    for extra in (["--confirmed"], ["--dry-run"]):
        other = run(SCRIPT, args + extra, env)
        assert other.returncode == 2 and "--ledger" in other.stderr and "PUBLISHER_LINKEDIN_LEDGER" in other.stderr
    assert post_count(fake) == 1 and ledger(env) == {}
    # The variable naming the same file changes nothing: the key is found, the post is replayed.
    same = run(SCRIPT, args + ["--confirmed"], {**env, "PUBLISHER_LINKEDIN_LEDGER": str(pinned)})
    assert same.returncode == 0 and json.loads(same.stdout)["replayed"] is True and post_count(fake) == 1
    relative = run(SCRIPT, publish_args(text_file, "--ledger", "ledger.json", "--dry-run"), scheduled)
    assert relative.returncode == 2 and "absolute" in relative.stderr
    # Without the flag a dry run still says which ledger this environment uses, for a caller to carry.
    shown = run(SCRIPT, publish_args(text_file, "--dry-run"), env)
    assert json.loads(shown.stdout)["ledger"] == env["PUBLISHER_LINKEDIN_LEDGER"]


def test_ledger_override_reads_no_old_ledger(env, fake, text_file, tmp_path):
    _, _, old = default_ledger_env(env, tmp_path)
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"version": 2, "entries": {"launch-1": {"status": "published", "post_urn": POST_URN}}}))
    dry = run(SCRIPT, publish_args(text_file, "--idempotency-key", "launch-1", "--dry-run"), env)
    assert json.loads(dry.stdout)["existing_post_urn"] is None and "ledger moved" not in dry.stderr


def test_a_corrupt_ledger_stops_every_verb_before_anything_is_sent(env, fake, text_file, comment_file):
    path = Path(env["PUBLISHER_LINKEDIN_LEDGER"])
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    for args in (publish_args(text_file, "--confirmed"), publish_args(text_file, "--dry-run"),
                 comment_args(comment_file, "--post-id", POST_URN, "--confirmed"),
                 ["resolve", "--idempotency-key", "k", "--not-published", "--confirmed"]):
        proc = run(SCRIPT, args, env)
        assert proc.returncode == 1 and "not valid JSON" in proc.stderr, args
    assert fake.requests == [] and path.read_text() == "{not json"


# --- a key holds one content: what was sent is hashed in the ledger ----------------------------------------


def test_a_reused_key_with_other_text_is_refused_and_sends_nothing(env, fake, text_file, tmp_path):
    args = publish_args(text_file, "--idempotency-key", "launch-1", "--confirmed")
    assert run(SCRIPT, args, env).returncode == 0
    assert len(ledger(env)["launch-1"]["payload_sha256"]) == 64
    other = tmp_path / "other.txt"
    other.write_text("A different post.\n")
    proc = run(SCRIPT, publish_args(other, "--idempotency-key", "launch-1", "--confirmed"), env)
    assert proc.returncode == 1 and "launch-1" in proc.stderr and "nothing was sent" in proc.stderr
    assert proc.stdout == "" and post_count(fake) == 1
    same = run(SCRIPT, args, env)  # the same content still replays
    assert same.returncode == 0 and json.loads(same.stdout)["replayed"] is True and post_count(fake) == 1


def test_a_reused_key_with_another_image_is_refused(env, fake, text_file, image_file, tmp_path):
    assert run(SCRIPT, publish_args(text_file, "--media", str(image_file), "--idempotency-key", "k",
                                    "--confirmed"), env).returncode == 0
    second = tmp_path / "second.png"
    second.write_bytes(b"\x89PNG\r\n\x1a\n" + b"other-bytes" * 4)
    for extra in (["--media", str(second)], []):
        proc = run(SCRIPT, publish_args(text_file, *extra, "--idempotency-key", "k", "--confirmed"), env)
        assert proc.returncode == 1 and "'k'" in proc.stderr, extra
    assert post_count(fake) == 1


def test_a_reused_comment_key_with_other_text_is_refused(env, fake, comment_file, tmp_path):
    args = comment_args(comment_file, "--post-id", POST_URN, "--idempotency-key", "reply-1", "--confirmed")
    assert run(SCRIPT, args, env).returncode == 0
    other = tmp_path / "other-comment.txt"
    other.write_text("Another reply.\n")
    proc = run(SCRIPT, comment_args(other, "--post-id", POST_URN, "--idempotency-key", "reply-1", "--confirmed"), env)
    assert proc.returncode == 1 and "reply-1" in proc.stderr and comment_count(fake) == 1
    assert json.loads(run(SCRIPT, args, env).stdout)["replayed"] is True and comment_count(fake) == 1


def test_an_entry_written_before_the_hash_replays_as_before(env, fake, text_file):
    path = Path(env["PUBLISHER_LINKEDIN_LEDGER"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 2, "entries": {
        "old": {"status": "published", "post_urn": POST_URN, "created_at": "2026-10-01T00:00:00Z"}}}))
    proc = run(SCRIPT, publish_args(text_file, "--idempotency-key", "old", "--confirmed"), env)
    assert proc.returncode == 0 and json.loads(proc.stdout)["replayed"] is True and post_count(fake) == 0


def test_resolve_keeps_the_hash_of_what_was_sent(env, fake, text_file, tmp_path):
    fake.post_delay = 2.0
    env["LINKEDIN_HTTP_TIMEOUT"] = "0.5"
    assert run(SCRIPT, publish_args(text_file, "--idempotency-key", "k", "--confirmed"), env).returncode == 1
    sent = ledger(env)["k"]["payload_sha256"]
    fake.post_delay = 0.0
    assert run(SCRIPT, ["resolve", "--idempotency-key", "k", "--post-id", POST_URN, "--confirmed"], env).returncode == 0
    assert ledger(env)["k"]["payload_sha256"] == sent
    other = tmp_path / "other.txt"
    other.write_text("A different post.\n")
    assert run(SCRIPT, publish_args(other, "--idempotency-key", "k", "--confirmed"), env).returncode == 1


# --- a verb takes its own flags; --check takes no verb ---------------------------------------------------


def test_check_with_a_verb_is_a_usage_error(env, fake, text_file):
    for args in (["--check", *publish_args(text_file, "--confirmed")], ["--check", "resolve", "--idempotency-key", "k"],
                 ["--check", "--text-file", str(text_file)], ["--check", "--idempotency-key", "k"]):
        proc = run(SCRIPT, args, env)
        assert proc.returncode == 2 and "--check" in proc.stderr, args
        assert proc.stdout == ""
    assert fake.requests == [] and ledger(env) == {}


def test_a_flag_of_another_verb_is_refused(env, fake, text_file, comment_file):
    cases = [
        (publish_args(text_file, "--on-key", "k", "--confirmed"), "--on-key"),
        (publish_args(text_file, "--post-id", POST_URN, "--confirmed"), "--post-id"),
        (publish_args(text_file, "--not-published", "--confirmed"), "--not-published"),
        (comment_args(comment_file, "--post-id", POST_URN, "--media", str(text_file), "--confirmed"), "--media"),
        (comment_args(comment_file, "--post-id", POST_URN, "--first-comment-file", str(comment_file), "--confirmed"),
         "--first-comment-file"),
        (comment_args(comment_file, "--post-id", POST_URN, "--at", "2026-01-01T00:00:00Z", "--confirmed"), "--at"),
        (["resolve", "--idempotency-key", "k", "--not-published", "--text-file", str(text_file), "--confirmed"],
         "--text-file"),
        (["resolve", "--idempotency-key", "k", "--not-published", "--parent-comment-id", PARENT_URN, "--confirmed"],
         "--parent-comment-id"),
    ]
    for args, flag in cases:
        proc = run(SCRIPT, args, env)
        assert proc.returncode == 2 and flag in proc.stderr and args[0] in proc.stderr, (args, proc.stderr)
    assert fake.requests == [] and ledger(env) == {}


def test_resolve_checks_the_post_id_as_strictly_as_comment(env, fake):
    path = Path(env["PUBLISHER_LINKEDIN_LEDGER"])
    path.parent.mkdir(parents=True)
    pending = {"version": 2, "entries": {"k": {"status": "pending", "started_at": "2026-10-01T00:00:00Z"}}}
    path.write_text(json.dumps(pending))
    for bad in ("urn:li:share:12/../../v2/me", "urn:li:person:abc", "urn:li:share:", "urn:li:share:12 "):
        for mode in ("--dry-run", "--confirmed"):
            proc = run(SCRIPT, ["resolve", "--idempotency-key", "k", "--post-id", bad, mode], env)
            assert proc.returncode == 2 and "--post-id" in proc.stderr, (bad, mode)
    assert json.loads(path.read_text()) == pending
    ok = run(SCRIPT, ["resolve", "--idempotency-key", "k", "--post-id", "urn:li:activity:7000000000000000009",
                      "--confirmed"], env)
    assert ok.returncode == 0, ok.stderr


# --- the ledger is written durably, and its own folder is private ----------------------------------------


def test_ledger_save_syncs_and_leaves_no_temporary_file_on_error(tmp_path, monkeypatch):
    module = load_module()
    path = tmp_path / "l" / "ledger.json"
    path.parent.mkdir()
    monkeypatch.setenv("PUBLISHER_LINKEDIN_LEDGER", str(path))
    synced = []
    real_fsync = module.os.fsync
    monkeypatch.setattr(module.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))
    module.ledger_save({"entries": {"k": {"status": "published"}}})
    assert synced and json.loads(path.read_text())["entries"] == {"k": {"status": "published"}}
    before = path.read_bytes()

    def broken_dump(*args, **kwargs):
        raise TypeError("cannot serialize")

    monkeypatch.setattr(module.json, "dump", broken_dump)
    with pytest.raises(TypeError):
        module.ledger_save({"entries": {}})
    assert sorted(p.name for p in path.parent.iterdir()) == ["ledger.json"] and path.read_bytes() == before


def test_the_provider_s_own_ledger_folder_is_tightened_and_a_given_one_is_left_alone(env, fake, text_file, tmp_path):
    e, new, _ = default_ledger_env(env, tmp_path)
    new.parent.mkdir(parents=True)
    os.chmod(new.parent, 0o755)
    assert run(SCRIPT, publish_args(text_file, "--confirmed"), e).returncode == 0
    assert oct(new.parent.stat().st_mode & 0o777) == "0o700"
    shared = tmp_path / "shared"
    shared.mkdir()
    os.chmod(shared, 0o755)
    given = {**env, "PUBLISHER_LINKEDIN_LEDGER": str(shared / "ledger.json")}
    assert run(SCRIPT, publish_args(text_file, "--confirmed"), given).returncode == 0
    assert oct(shared.stat().st_mode & 0o777) == "0o755"  # not ours: a folder the user chose
    assert oct((shared / "ledger.json").stat().st_mode & 0o777) == "0o600"


# --- publish honours --legacy-v2 for its first comment; the contract states the platform's flags and media count ---


def test_publish_legacy_v2_sends_the_first_comment_to_the_unversioned_endpoint(env, fake, text_file, comment_file):
    proc = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(comment_file), "--comments-endpoint", "rest",
                                    "--legacy-v2", "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    comment = json.loads(proc.stdout)["requests"][-1]
    assert "/v2/socialActions/" in comment["url"] and "LinkedIn-Version" not in comment["headers"]
    rest = run(SCRIPT, publish_args(text_file, "--first-comment-file", str(comment_file), "--comments-endpoint", "rest",
                                    "--dry-run"), env)
    assert "/rest/socialActions/" in json.loads(rest.stdout)["requests"][-1]["url"]


def test_media_must_exist_and_be_an_image(env, fake, text_file, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("x")
    for media, said in ((tmp_path / "none.png", "not found"), (other, "JPG, PNG or GIF")):
        proc = run(SCRIPT, publish_args(text_file, "--media", str(media), "--confirmed"), env)
        assert proc.returncode == 2 and said in proc.stderr
    assert fake.requests == []


def test_the_contract_row_states_own_flags_and_the_platform_s_media_count():
    contract = (HERE.parents[1] / "CONTRACT.md").read_text(encoding="utf-8")
    row = next(line for line in contract.splitlines() if line.startswith("| `publisher:<platform>` | `--check"))
    assert "flags of its own" in row and "portable caller does not pass" in row and "`--comments-endpoint`" in row
    assert "`media.max_count`" in row and "[--media <path>...]" in row
    data = json.loads((HERE.parents[2] / "shared" / "references" / "platforms" / "linkedin.json").read_text())
    assert data["media"]["max_count"] == 1  # this implementation refuses a second --media (test_rejects_two_images)
