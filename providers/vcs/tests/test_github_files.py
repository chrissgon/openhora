"""Offline tests for github.py read-file and commit-files.

Run: uv run --with pytest pytest providers/vcs/tests

No network and no real credentials. read-file talks to a fake GitHub on 127.0.0.1
(VCS_GITHUB_API_BASE) with a fake token. commit-files pushes to a local bare repository
(VCS_TEST=1, VCS_GIT_REMOTE), with a throwaway git configuration (GIT_CONFIG_GLOBAL) that signs
commits with a throwaway SSH key, so the real signing path runs without touching the user's setup.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "github.py"
FAKE_TOKEN = "FAKE-test-github-token-7d6e5f4a3b2c-never-print-me"
REPO = "example-org/site"
ALLOW = ["--allow", "data/pick.json", "--allow", "data/pick-queue.json", "--allow", "data/posts.json",
         "--allow", "assets/posts/*"]


def run(args, env, timeout=90):
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True,
                          timeout=timeout)
    for stream in (proc.stdout, proc.stderr):
        assert FAKE_TOKEN not in stream and FAKE_TOKEN[:16] not in stream
        assert "PRIVATE KEY" not in stream
    return proc


# --- read-file -------------------------------------------------------------------


class FakeContents:
    """GET /repos/{owner}/{repo}/contents/{path}, shaped like the 2026-03-10 REST API."""

    def __init__(self):
        self.requests: list[dict] = []
        self.files: dict[str, object] = {}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, payload=None, headers=None):
                data = json.dumps(payload).encode() if payload is not None else b""
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                fake.requests.append({"path": parsed.path, "query": urllib.parse.parse_qs(parsed.query),
                                      "headers": {k.lower(): v for k, v in self.headers.items()}})
                prefix = f"/repos/{REPO}/contents/"
                if not parsed.path.startswith(prefix):
                    return self._send(404, {"message": "Not Found"})
                path = urllib.parse.unquote(parsed.path[len(prefix):])
                item = fake.files.get(path)
                if item is None:
                    return self._send(404, {"message": "Not Found"})
                if item == "redirect":
                    return self._send(302, None, {"Location": "http://127.0.0.1:1/elsewhere"})
                if isinstance(item, list):
                    return self._send(200, item)
                if isinstance(item, dict):
                    return self._send(200, item)
                encoded = base64.b64encode(item).decode()
                content = "\n".join(encoded[i:i + 60] for i in range(0, len(encoded), 60)) + "\n"
                name = path.rsplit("/", 1)[-1]
                return self._send(200, {
                    "type": "file", "encoding": "base64", "size": len(item), "name": name, "path": path,
                    "content": content, "sha": hashlib.sha1(item).hexdigest(),
                    "url": f"https://api.github.com/repos/{REPO}/contents/{path}",
                    "git_url": None, "html_url": None, "download_url": None, "_links": {}})

            def log_message(self, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def contents():
    server = FakeContents()
    yield server
    server.close()


@pytest.fixture()
def api_env(tmp_path, contents):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "VCS_"))}
    env.update({"HOME": str(tmp_path / "home"), "XDG_CACHE_HOME": str(tmp_path / "cache"),
                "VCS_GITHUB_API_BASE": contents.base, "GITHUB_TOKEN": FAKE_TOKEN,
                "VCS_GITHUB_LEDGER": str(tmp_path / "ledger" / "vcs-github.json")})
    return env


PICK = '{"round": 12, "pillar": "Case studies", "options": {"A": "Évals", "B": "b", "C": "c"}}\n'


def test_read_file_returns_the_text(api_env, contents):
    contents.files["data/pick.json"] = PICK.encode()
    proc = run(["read-file", "--repo", REPO, "--path", "data/pick.json", "--ref", "master"], api_env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out == {"repo": REPO, "path": "data/pick.json", "ref": "master",
                   "sha": hashlib.sha1(PICK.encode()).hexdigest(), "size": len(PICK.encode()), "content": PICK}
    request = contents.requests[0]
    assert request["path"] == f"/repos/{REPO}/contents/data/pick.json"
    assert request["query"] == {"ref": ["master"]}
    assert request["headers"]["authorization"] == f"Bearer {FAKE_TOKEN}"
    assert request["headers"]["x-github-api-version"] == "2026-03-10"


def test_read_file_default_branch_and_anonymous(api_env, contents):
    del api_env["GITHUB_TOKEN"]
    contents.files["README.md"] = b"# hi\n"
    proc = run(["read-file", "--repo", REPO, "--path", "README.md"], api_env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ref"] is None
    assert "anonymously" in proc.stderr
    assert "authorization" not in contents.requests[0]["headers"]
    assert contents.requests[0]["query"] == {}


def test_read_file_refuses_binary_directory_and_submodule(api_env, contents):
    contents.files["assets/posts/a.png"] = b"\x89PNG\r\n\x1a\n\x00\x00"
    contents.files["latin1.txt"] = "caf\xe9".encode("latin-1")
    contents.files["data"] = [{"type": "file", "name": "pick.json", "path": "data/pick.json"}]
    contents.files["vendor/lib"] = {"type": "submodule", "path": "vendor/lib", "sha": "a" * 40}
    for path in ("assets/posts/a.png", "latin1.txt", "data", "vendor/lib"):
        proc = run(["read-file", "--repo", REPO, "--path", path], api_env)
        assert proc.returncode == 2, (path, proc.stderr)
        assert proc.stdout == ""


def test_read_file_large_missing_and_redirect(api_env, contents):
    contents.files["big.json"] = {"type": "file", "encoding": "none", "size": 2_000_000, "path": "big.json",
                                  "content": "", "sha": "b" * 40}
    contents.files["moved.json"] = "redirect"
    big = run(["read-file", "--repo", REPO, "--path", "big.json"], api_env)
    assert big.returncode == 1 and "1 MB" in big.stderr
    missing = run(["read-file", "--repo", REPO, "--path", "nope.json"], api_env)
    assert missing.returncode == 1 and "404" in missing.stderr
    moved = run(["read-file", "--repo", REPO, "--path", "moved.json"], api_env)
    assert moved.returncode == 1 and "redirect" in moved.stderr
    assert len(contents.requests) == 3


def test_read_file_has_a_size_cap(api_env, contents):
    """VS15: read-file read whatever the service answered, of any size."""
    cap = 1024 * 1024
    contents.files["data/at-cap.txt"] = b"a" * cap
    contents.files["data/over-cap.txt"] = b"a" * (cap + 1)
    contents.files["data/huge-answer.txt"] = {"type": "file", "encoding": "base64", "size": 2, "path": "x",
                                              "content": "aGk=", "sha": "c" * 40, "noise": "n" * (5 * cap)}
    at_cap = run(["read-file", "--repo", REPO, "--path", "data/at-cap.txt"], api_env)
    assert at_cap.returncode == 0 and json.loads(at_cap.stdout)["size"] == cap
    for path in ("data/over-cap.txt", "data/huge-answer.txt"):
        proc = run(["read-file", "--repo", REPO, "--path", path], api_env)
        assert proc.returncode == 1 and "cap" in proc.stderr and proc.stdout == "", (path, proc.stderr)
    assert "1 MiB" in run(["--help"], api_env).stdout


def test_read_file_validates_path_and_ref_before_any_request(api_env, contents):
    bad_paths = ["../etc/passwd", "/abs.json", "a//b", "data/", ".git/config", "a/.git/x", "a b.json",
                 "data/../x", ".", "-rf", "a?b", "a%2e", "x\n"]
    for path in bad_paths:
        proc = run(["read-file", "--repo", REPO, "--path", path], api_env)
        assert proc.returncode == 2, path
    for ref in ("..", "a..b", "-x", "a b", "main.lock", "a//b", "refs/heads/.x", "x?y"):
        proc = run(["read-file", "--repo", REPO, "--path", "README.md", "--ref", ref], api_env)
        assert proc.returncode == 2, ref
    proc = run(["read-file", "--repo", "../x", "--path", "README.md"], api_env)
    assert proc.returncode == 2
    assert contents.requests == []


# --- commit-files: fixtures ---------------------------------------------------------

needs_tools = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")),
                                 reason="needs git and ssh-keygen")

MOVER_HOOK = """#!/bin/sh
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX
[ -n "$MOVER_MODE" ] || exit 0
if [ "$MOVER_MODE" = once ] && [ -f "$MOVER_MARKER" ]; then exit 0; fi
touch "$MOVER_MARKER"
echo moved >> "$MOVER_DIR/moved.txt"
git -C "$MOVER_DIR" add -- moved.txt >/dev/null 2>&1
git -C "$MOVER_DIR" commit -q -m "workflow moved the branch" >/dev/null 2>&1
git -C "$MOVER_DIR" push -q origin HEAD:refs/heads/main >/dev/null 2>&1
exit 0
"""


def git(env, cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=True).stdout


class Remote:
    """A bare repository standing in for the repository on the host, and a git setup around it."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.key = tmp / "signing-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(self.key)],
                       check=True, timeout=30)
        template = tmp / "template"
        (template / "hooks").mkdir(parents=True)
        hook = template / "hooks" / "post-checkout"
        hook.write_text(MOVER_HOOK)
        hook.chmod(0o755)
        self.gitconfig = tmp / "gitconfig"
        self.write_config(sign=True)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GITHUB_", "VCS_", "GIT_", "SSH_AUTH_SOCK"))}
        self.env.update({"HOME": str(tmp / "home"), "XDG_CACHE_HOME": str(tmp / "cache"),
                         "GIT_CONFIG_GLOBAL": str(self.gitconfig), "GIT_CONFIG_NOSYSTEM": "1"})
        (tmp / "home").mkdir()
        self.bare = tmp / "remote.git"
        git(self.env, tmp, "init", "-q", "--bare", str(self.bare))
        seed = tmp / "seed"
        git(self.env, tmp, "clone", "-q", self.bare.as_uri(), str(seed))
        (seed / "data").mkdir()
        (seed / "data" / "pick.json").write_text(PICK)
        (seed / "data" / "posts.json").write_text("[]\n")
        (seed / "README.md").write_text("# profile\n")
        (seed / "outside").mkdir()
        (seed / "outside" / "keep.txt").write_text("keep\n")
        (seed / "assets").mkdir()
        os.symlink("../outside", seed / "assets" / "link")
        git(self.env, seed, "add", "-A")
        git(self.env, seed, "commit", "-q", "-m", "seed")
        git(self.env, seed, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.mover = tmp / "mover"
        git(self.env, tmp, "clone", "-q", self.bare.as_uri(), str(self.mover))

    def write_config(self, sign: bool):
        self.gitconfig.write_text(
            "[user]\n\tname = Test Person\n\temail = test@example.com\n"
            f"\tsigningkey = {self.key}\n"
            f"[commit]\n\tgpgsign = {'true' if sign else 'false'}\n[gpg]\n\tformat = ssh\n"
            f"[init]\n\tdefaultBranch = main\n\ttemplateDir = {self.tmp / 'template'}\n")

    def head(self) -> str:
        return git(self.env, self.bare, "rev-parse", "refs/heads/main").strip()

    def count(self) -> int:
        return int(git(self.env, self.bare, "rev-list", "--count", "refs/heads/main").strip())

    def changed(self, rev="refs/heads/main") -> list[str]:
        return sorted(git(self.env, self.bare, "diff-tree", "--no-commit-id", "--name-only", "-r", rev).split())

    def provider_env(self) -> dict:
        env = dict(self.env)
        env.update({"VCS_TEST": "1", "VCS_GIT_REMOTE": str(self.bare), "GITHUB_TOKEN": FAKE_TOKEN,
                    "VCS_GITHUB_LEDGER": str(self.tmp / "ledger" / "vcs-github.json"),
                    "MOVER_DIR": str(self.mover), "MOVER_MARKER": str(self.tmp / "moved-once")})
        return env


@pytest.fixture()
def remote(tmp_path):
    if not (shutil.which("git") and shutil.which("ssh-keygen")):
        pytest.skip("needs git and ssh-keygen")
    return Remote(tmp_path)


@pytest.fixture()
def out_files(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    queue = out / "pick-queue.json"
    queue.write_text('[{"pillar": "Engineering", "options": {"A": "x", "B": "y", "C": "z"}}]\n')
    image = out / "post.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    message = out / "message.txt"
    message.write_text("chore(data): queue item 12\n\nApproved at the gate.\n")
    return {"queue": queue, "image": image, "message": message}


def commit_args(out, key="vote-12-queue", *extra, files=None):
    files = files if files is not None else [f"data/pick-queue.json={out['queue']}",
                                             f"assets/posts/vote-12.png={out['image']}"]
    args = ["commit-files", "--repo", REPO, "--branch", "main", "--message-file", str(out["message"]),
            "--idempotency-key", key, *ALLOW]
    for item in files:
        args += ["--file", item]
    return [*args, *extra]


def ledger(env):
    path = Path(env["VCS_GITHUB_LEDGER"])
    return json.loads(path.read_text())["entries"] if path.exists() else {}


def work_root(env) -> Path:
    return Path(env["XDG_CACHE_HOME"]) / "ai-workbench" / "vcs-github-work"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- commit-files: tests -----------------------------------------------------------


@needs_tools
def test_dry_run_prints_the_diff_and_pushes_nothing(remote, out_files):
    env = remote.provider_env()
    before = remote.head()
    proc = run(commit_args(out_files, "k1", "--dry-run"), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["dry_run"] is True and out["base_commit"] == before and out["unchanged"] is False
    assert out["files"] == [
        {"path": "data/pick-queue.json", "sha256": sha256(out_files["queue"]), "bytes": out_files["queue"].stat().st_size},
        {"path": "assets/posts/vote-12.png", "sha256": sha256(out_files["image"]),
         "bytes": out_files["image"].stat().st_size}]
    assert "data/pick-queue.json" in out["diff_stat"] and "assets/posts/vote-12.png" in out["diff_stat"]
    assert '+[{"pillar": "Engineering"' in out["diff"] and out["diff_truncated"] is False
    assert out["message"].startswith("chore(data): queue item 12")
    assert remote.head() == before
    assert ledger(env) == {}
    assert list(work_root(env).iterdir()) == []  # the private clone is removed


@needs_tools
def test_dry_run_diff_is_capped(remote, out_files, tmp_path):
    big = tmp_path / "big.json"
    big.write_text("".join(f'{{"n": {i}, "pad": "{"x" * 60}"}}\n' for i in range(1000)))
    proc = run(commit_args(out_files, "k1", "--dry-run", files=[f"data/posts.json={big}"]), remote.provider_env())
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["diff_truncated"] is True
    assert len(out["diff"].encode()) <= 20 * 1024


@needs_tools
def test_confirmed_pushes_one_signed_commit_with_exactly_the_files(remote, out_files):
    env = remote.provider_env()
    count = remote.count()
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["pushed"] is True and out["replayed"] is False and out["unchanged"] is False
    assert out["commit"] == remote.head() and out["branch"] == "main" and out["attempts"] == 1
    assert out["signature"] == "ssh"
    assert out["files"] == [{"path": "data/pick-queue.json", "sha256": sha256(out_files["queue"])},
                            {"path": "assets/posts/vote-12.png", "sha256": sha256(out_files["image"])}]
    assert remote.count() == count + 1
    assert remote.changed() == ["assets/posts/vote-12.png", "data/pick-queue.json"]
    raw = git(remote.env, remote.bare, "cat-file", "commit", "refs/heads/main")
    assert "BEGIN SSH SIGNATURE" in raw
    assert "chore(data): queue item 12" in raw
    assert git(remote.env, remote.bare, "show", "refs/heads/main:data/pick-queue.json") == out_files["queue"].read_text()
    assert ledger(env)["k1"]["status"] == "committed" and ledger(env)["k1"]["commit"] == out["commit"]
    assert list(work_root(env).iterdir()) == []
    assert Path(env["VCS_GITHUB_LEDGER"]).stat().st_mode & 0o777 == 0o600


@needs_tools
def test_paths_outside_allow_are_refused_before_cloning(remote, out_files):
    env = remote.provider_env()
    before = remote.head()
    for repo_path in (".github/workflows/ci.yml", "README.md", "assets/posts/sub/x.png", "data/pick.json.bak",
                      "assets/link/x.png", "../x"):
        proc = run(commit_args(out_files, "k1", "--confirmed", files=[f"{repo_path}={out_files['queue']}"]), env)
        assert proc.returncode == 2, repo_path
    assert not work_root(env).exists()  # nothing was cloned
    assert remote.head() == before and ledger(env) == {}


@needs_tools
def test_argument_errors_touch_nothing(remote, out_files, tmp_path):
    env = remote.provider_env()
    huge = tmp_path / "huge.png"
    huge.write_bytes(b"\0" * (5 * 1024 * 1024 + 1))
    empty = tmp_path / "empty.txt"
    empty.write_text("\n")
    q = out_files["queue"]
    cases = [
        commit_args(out_files, "k1"),  # neither --confirmed nor --dry-run
        commit_args(out_files, "k1", "--confirmed", files=[f"assets/posts/x.png={huge}"]),
        commit_args(out_files, "k1", "--confirmed", files=[f"data/posts.json={tmp_path / 'missing.json'}"]),
        commit_args(out_files, "k1", "--confirmed", files=["data/posts.json"]),
        commit_args(out_files, "k1", "--confirmed", files=[f"data/posts.json={q}", f"data/posts.json={q}"]),
        commit_args(out_files, "k1", "--confirmed", files=[]),
        [a if a != str(out_files["message"]) else str(empty) for a in commit_args(out_files, "k1", "--confirmed")],
        commit_args(out_files, "", "--confirmed"),
        [a for a in commit_args(out_files, "k1", "--confirmed") if a not in ALLOW],
        commit_args(out_files, "k1", "--confirmed", "--allow", "assets/**"),
        [a if a != "main" else "main..x" for a in commit_args(out_files, "k1", "--confirmed")],
    ]
    for args in cases:
        proc = run(args, env)
        assert proc.returncode == 2, (args, proc.stderr)
    assert not work_root(env).exists()
    no_test = dict(env)
    del no_test["VCS_TEST"]
    proc = run(commit_args(out_files, "k1", "--dry-run"), no_test)
    assert proc.returncode == 2 and "VCS_TEST=1" in proc.stderr


@needs_tools
def test_a_symlink_in_the_repository_is_never_written_through(remote, out_files):
    env = remote.provider_env()
    args = commit_args(out_files, "k1", "--confirmed", "--allow", "assets/link/*",
                       files=[f"assets/link/x.png={out_files['image']}"])
    proc = run(args, env)
    assert proc.returncode == 1 and "symlink" in proc.stderr
    assert "k1" not in ledger(env)
    assert git(remote.env, remote.bare, "rev-list", "--count", "refs/heads/main").strip() == "1"


@needs_tools
def test_a_moved_branch_is_retried_once_from_a_fresh_clone(remote, out_files):
    env = remote.provider_env()
    env["MOVER_MODE"] = "once"
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["attempts"] == 2 and "retrying once" in proc.stderr
    assert remote.count() == 3  # seed, the workflow's commit, ours
    parent = git(remote.env, remote.bare, "rev-parse", "refs/heads/main~1").strip()
    assert remote.changed(parent) == ["moved.txt"]
    assert remote.changed() == ["assets/posts/vote-12.png", "data/pick-queue.json"]


@needs_tools
def test_a_second_rejection_exits_1_and_releases_the_key(remote, out_files):
    env = remote.provider_env()
    env["MOVER_MODE"] = "always"
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 1
    assert "rejected again" in proc.stderr
    assert remote.changed() == ["moved.txt"]  # the workflow's commits only
    assert ledger(env) == {}
    del env["MOVER_MODE"]
    assert run(commit_args(out_files, "k1", "--confirmed"), env).returncode == 0


@needs_tools
def test_replay_returns_the_same_commit_without_pushing(remote, out_files):
    env = remote.provider_env()
    first = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert first.returncode == 0, first.stderr
    head, count = remote.head(), remote.count()
    second = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert second.returncode == 0, second.stderr
    out = json.loads(second.stdout)
    assert out["replayed"] is True and out["commit"] == json.loads(first.stdout)["commit"] == head
    assert remote.count() == count
    assert not work_root(env).exists() or list(work_root(env).iterdir()) == []
    # The same key with other content is refused.
    out_files["queue"].write_text("[]\n")
    other = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert other.returncode == 2 and "new key" in other.stderr
    assert remote.count() == count
    # A dismissal cannot reuse a commit key.
    why = out_files["message"]
    dismissal = run(["dismiss-alert", "--repo", REPO, "--number", "3", "--reason", "not_used", "--comment-file",
                     str(why), "--idempotency-key", "k1", "--confirmed"], {**env, "VCS_GITHUB_API_BASE": "http://127.0.0.1:9"})
    assert dismissal.returncode == 2 and "commit" in dismissal.stderr


@needs_tools
def test_the_same_files_again_is_unchanged(remote, out_files, tmp_path):
    env = remote.provider_env()
    same = tmp_path / "pick.json"
    same.write_text(PICK)
    count = remote.count()
    proc = run(commit_args(out_files, "k1", "--confirmed", files=[f"data/pick.json={same}"]), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["unchanged"] is True and out["pushed"] is False and out["commit"] == remote.head()
    assert remote.count() == count


@needs_tools
def test_an_unsigned_commit_is_never_pushed(remote, out_files):
    remote.write_config(sign=False)
    env = remote.provider_env()
    before = remote.head()
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 3
    assert "not signed" in proc.stderr and "commit.gpgsign" in proc.stderr
    assert remote.head() == before and ledger(env) == {}


@needs_tools
def test_git_gets_neither_the_callers_git_variables_nor_the_secrets(remote, out_files, tmp_path):
    # VS3: git, ssh and the user's hooks got the caller's whole environment. Started from a git hook, where
    # GIT_DIR and GIT_INDEX_FILE are set, the provider committed in that other repository; and the token of
    # the provider reached every hook.
    other = tmp_path / "other"
    git(remote.env, tmp_path, "init", "-q", str(other))
    dump = tmp_path / "hook-env.txt"
    hook = remote.tmp / "template" / "hooks" / "pre-commit"
    hook.write_text('#!/bin/sh\nenv > "$ENV_DUMP"\nexit 0\n')
    hook.chmod(0o755)
    env = remote.provider_env()
    env.update({"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other), "GIT_INDEX_FILE": str(other / ".git/index"),
                "GIT_AUTHOR_NAME": "Someone Else", "VCS_GITHUB_TOKEN": FAKE_TOKEN,
                "LINKEDIN_ACCESS_TOKEN": "FAKE-another-registered-secret", "ENV_DUMP": str(dump)})
    before = remote.count()
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert remote.count() == before + 1  # the commit went to the remote the provider cloned
    assert remote.changed() == ["assets/posts/vote-12.png", "data/pick-queue.json"]
    author = git(remote.env, remote.bare, "log", "-1", "--format=%an", "refs/heads/main").strip()
    assert author == "Test Person"  # the user's git configuration, not the caller's GIT_AUTHOR_NAME
    assert git(remote.env, other, "rev-list", "--all", "--count").strip() == "0"  # nothing landed in the other one
    seen = dict(line.split("=", 1) for line in dump.read_text().splitlines() if "=" in line)
    assert FAKE_TOKEN not in dump.read_text() and "FAKE-another-registered-secret" not in dump.read_text()
    for name in ("VCS_GITHUB_TOKEN", "GITHUB_TOKEN", "LINKEDIN_ACCESS_TOKEN"):
        assert name not in seen, name
    # git sets some of these itself for a hook (its own repository, the author it resolved); never the caller's.
    assert seen.get("GIT_DIR") != str(other / ".git") and seen.get("GIT_WORK_TREE") != str(other)
    assert seen.get("GIT_INDEX_FILE") != str(other / ".git/index")
    assert seen.get("GIT_AUTHOR_NAME") != "Someone Else"
    assert seen["GIT_CONFIG_GLOBAL"] == str(remote.gitconfig)  # where the user's configuration lives is kept
    assert seen["ENV_DUMP"] == str(dump)  # everything else passes through


GIT_THAT_LOSES_THE_CONNECTION = """#!/bin/sh
# Stands for a push whose connection dies after the remote took the commit: the real push runs, then git
# reports an SSH failure and exits as it does when ssh goes away.
if [ "$1" = push ]; then
  "$REAL_GIT" "$@"
  echo "ssh: connect to host github.com port 22: Operation timed out" >&2
  echo "fatal: Could not read from remote repository." >&2
  exit 128
fi
exec "$REAL_GIT" "$@"
"""


@needs_tools
def test_an_ssh_failure_after_the_push_started_keeps_the_key_pending(remote, out_files, tmp_path):
    # VS1: any SSH failure text was read as "nothing was sent" and released the key, also on the stderr of a
    # push that had started. Here the remote takes the commit and the connection then dies.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text(GIT_THAT_LOSES_THE_CONNECTION)
    wrapper.chmod(0o755)
    env = remote.provider_env()
    env.update({"REAL_GIT": shutil.which("git"), "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"})
    before = remote.head()
    first = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert first.returncode == 1
    assert "Operation timed out" in first.stderr and "outcome is unknown" in first.stderr
    assert remote.head() != before  # the remote did take the commit
    entry = ledger(env)["k1"]
    assert entry["status"] == "pending" and entry["attempted_commit"] == remote.head()
    again = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert again.returncode == 1 and "pending" in again.stderr and "--commit" in again.stderr
    done = run(["resolve", "--idempotency-key", "k1", "--commit", remote.head(), "--confirmed"], env)
    assert done.returncode == 0, done.stderr
    replay = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert replay.returncode == 0 and json.loads(replay.stdout)["replayed"] is True
    assert remote.count() == 2  # the seed and one commit: never a second one


@needs_tools
def test_an_ssh_failure_before_the_clone_still_releases_the_key(remote, out_files, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text('#!/bin/sh\nif [ "$1" = clone ]; then echo "ssh: Could not resolve hostname github.com" >&2; '
                       'exit 128; fi\nexec "$REAL_GIT" "$@"\n')
    wrapper.chmod(0o755)
    env = remote.provider_env()
    env.update({"REAL_GIT": shutil.which("git"), "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"})
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 1 and "could not reach GitHub" in proc.stderr
    assert ledger(env) == {}  # nothing left the machine


@needs_tools
def test_an_unknown_push_outcome_stays_pending_until_resolved(remote, out_files):
    env = remote.provider_env()
    hook = remote.bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nsleep 30\n")
    hook.chmod(0o755)
    env["VCS_GIT_TIMEOUT"] = "3"
    before = remote.head()
    first = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert first.returncode == 1 and "timed out" in first.stderr
    entry = ledger(env)["k1"]
    assert entry["status"] == "pending" and len(entry["attempted_commit"]) == 40
    blocked = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert blocked.returncode == 1 and "pending" in blocked.stderr and "--not-committed" in blocked.stderr
    assert remote.head() == before
    resolve = ["resolve", "--idempotency-key", "k1"]
    assert run(resolve + ["--not-committed"], env).returncode == 2  # needs --confirmed
    assert run(resolve + ["--dismissed", "--confirmed"], env).returncode == 2  # a commit key
    assert run(resolve + ["--commit", "abc", "--confirmed"], env).returncode == 2
    assert run(resolve + ["--commit", "a" * 40, "--not-committed", "--confirmed"], env).returncode == 2
    released = run(resolve + ["--not-committed", "--confirmed"], env)
    assert released.returncode == 0, released.stderr
    assert json.loads(released.stdout)["status"] == "released" and ledger(env) == {}
    # A second pending key, settled as committed, then replays that commit.
    assert run(commit_args(out_files, "k2", "--confirmed"), env).returncode == 1
    sha = "b" * 40
    done = run(["resolve", "--idempotency-key", "k2", "--commit", sha, "--confirmed"], env)
    assert done.returncode == 0, done.stderr
    replay = run(commit_args(out_files, "k2", "--confirmed"), env)
    assert replay.returncode == 0 and json.loads(replay.stdout)["commit"] == sha
    assert json.loads(replay.stdout)["replayed"] is True
    # The released key works once the remote answers again.
    hook.unlink()
    del env["VCS_GIT_TIMEOUT"]
    again = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert again.returncode == 0, again.stderr
    assert remote.head() == json.loads(again.stdout)["commit"]
    assert run(resolve + ["--not-committed", "--confirmed"], env).returncode == 2  # only pending keys


# --- VS2: what is pushed is what was given -----------------------------------------------


@needs_tools
def test_a_hook_that_changes_a_file_stops_the_push(remote, out_files):
    # The commit runs the user's hooks, and only path names were checked afterwards: a pre-commit hook changed
    # a file's content and the provider printed the original sha256 with "pushed": true.
    hook = remote.tmp / "template" / "hooks" / "pre-commit"
    hook.write_text('#!/bin/sh\necho "added by a hook" >> data/pick-queue.json\ngit add data/pick-queue.json\n')
    hook.chmod(0o755)
    env = remote.provider_env()
    before = remote.head()
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 1
    assert "data/pick-queue.json in the commit is not the file that was given" in proc.stderr
    assert sha256(out_files["queue"]) in proc.stderr and "Nothing was pushed" in proc.stderr
    assert remote.head() == before and not proc.stdout.strip()
    assert ledger(env) == {}  # nothing left the machine: the key is free
    assert list(work_root(env).iterdir()) == []
    hook.unlink()
    again = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert again.returncode == 0, again.stderr


@needs_tools
def test_an_attribute_that_changes_a_file_stops_the_push(remote, out_files):
    # A line-ending rule of the repository gives a blob with another hash than the one the person approved.
    (remote.mover / ".gitattributes").write_text("*.json text eol=lf\n")
    git(remote.env, remote.mover, "add", ".gitattributes")
    git(remote.env, remote.mover, "commit", "-q", "-m", "normalise line endings")
    git(remote.env, remote.mover, "push", "-q", "origin", "HEAD:refs/heads/main")
    out_files["queue"].write_bytes(b'[{"pillar": "Engineering"}]\r\n')
    env = remote.provider_env()
    before = remote.head()
    files = [f"data/pick-queue.json={out_files['queue']}"]
    proc = run(commit_args(out_files, "k1", "--confirmed", files=files), env)
    assert proc.returncode == 1 and "is not the file that was given" in proc.stderr
    assert remote.head() == before and ledger(env) == {}
    # The same bytes, once the branch already holds their normalised form: not "unchanged", refused.
    (remote.mover / "data" / "pick-queue.json").write_bytes(b'[{"pillar": "Engineering"}]\n')
    git(remote.env, remote.mover, "add", "data/pick-queue.json")
    git(remote.env, remote.mover, "commit", "-q", "-m", "the queue, with unix line endings")
    git(remote.env, remote.mover, "push", "-q", "origin", "HEAD:refs/heads/main")
    held = remote.head()
    proc = run(commit_args(out_files, "k2", "--confirmed", files=files), env)
    assert proc.returncode == 1 and "is not the file that was given" in proc.stderr
    assert remote.head() == held and ledger(env) == {}


# --- VS5: a tag is not a branch ---------------------------------------------------------------


@needs_tools
def test_a_tag_is_refused_as_branch(remote, out_files):
    # "clone --branch v1" takes a tag, and the push then created refs/heads/v1 and printed "pushed": true.
    git(remote.env, remote.bare, "tag", "v1", "refs/heads/main")
    env = remote.provider_env()
    refs_before = git(remote.env, remote.bare, "for-each-ref", "--format=%(refname)")
    args = commit_args(out_files, "k1")
    args[args.index("--branch") + 1] = "v1"
    for mode in ("--dry-run", "--confirmed"):
        proc = run([*args, mode], env)
        assert proc.returncode == 2, (mode, proc.stderr)
        assert "is not a branch" in proc.stderr and not proc.stdout.strip()
    assert git(remote.env, remote.bare, "for-each-ref", "--format=%(refname)") == refs_before
    assert "refs/heads/v1" not in refs_before
    assert ledger(env) == {} and list(work_root(env).iterdir()) == []


# --- VS6: a signal cleans up and stops git -----------------------------------------------------


@needs_tools
def test_sigterm_stops_git_removes_the_clone_and_keeps_the_key_pending(remote, out_files, tmp_path):
    # git runs in its own session and the provider had no signal handler: SIGTERM (what a scheduler sends a
    # job at its limit) killed the provider at once, left the clone behind, and the push landed after it died.
    started, finished = tmp_path / "receive-started", tmp_path / "receive-finished"
    hook = remote.bare / "hooks" / "pre-receive"
    hook.write_text(f'#!/bin/sh\ntouch "{started}"\nsleep 4\ntouch "{finished}"\n')
    hook.chmod(0o755)
    env = remote.provider_env()
    before = remote.head()
    proc = subprocess.Popen([sys.executable, str(SCRIPT), *commit_args(out_files, "k1", "--confirmed")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(300):  # until the remote is receiving the push
            if started.exists():
                break
            time.sleep(0.1)
        assert started.exists(), "the push never started"
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 128 + signal.SIGTERM, err
    assert "stopped by signal" in err and "Traceback" not in err and not out.strip()
    assert list(work_root(env).iterdir()) == []  # the clone is gone
    entry = ledger(env)["k1"]
    assert entry["status"] == "pending" and len(entry["attempted_commit"]) == 40 and entry["error"] == "interrupted"
    time.sleep(5)  # longer than the remote's hook would have needed
    assert not finished.exists(), "git went on after the provider was stopped"
    assert remote.head() == before
    again = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert again.returncode == 1 and "pending" in again.stderr


@needs_tools
def test_sigterm_during_the_clone_releases_the_key(remote, out_files, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "clone-started"
    wrapper = bin_dir / "git"
    wrapper.write_text(f'#!/bin/sh\nif [ "$1" = clone ]; then touch "{marker}"; sleep 30; fi\nexec "$REAL_GIT" "$@"\n')
    wrapper.chmod(0o755)
    env = remote.provider_env()
    env.update({"REAL_GIT": shutil.which("git"), "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"})
    proc = subprocess.Popen([sys.executable, str(SCRIPT), *commit_args(out_files, "k1", "--confirmed")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(300):
            if marker.exists():
                break
            time.sleep(0.1)
        assert marker.exists()
        proc.send_signal(signal.SIGTERM)
        _, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 128 + signal.SIGTERM, err
    assert list(work_root(env).iterdir()) == []
    assert ledger(env) == {}  # nothing was sent: the key is free


# --- VS13: a wildcard does not match a dotfile -------------------------------------------------


@needs_tools
def test_a_wildcard_does_not_admit_a_dotfile(remote, out_files):
    # fnmatch lets '*' and '?' match a leading '.', so --allow '*' admitted .gitattributes, a file that changes
    # how git treats every other path.
    env = remote.provider_env()
    q = out_files["queue"]
    for allow, path in (("*", ".gitattributes"), ("?gitattributes", ".gitattributes"), ("data/*", "data/.env"),
                        ("*/x.json", ".github/x.json"), ("[.]env", ".env")):
        args = commit_args(out_files, "k1", "--dry-run", files=[f"{path}={q}"])
        args = [a for a in args if a not in ALLOW] + ["--allow", allow]
        proc = run(args, env)
        assert proc.returncode == 2 and "outside the allowed paths" in proc.stderr, (allow, path, proc.stderr)
    assert not work_root(env).exists()  # refused before cloning
    # A pattern whose part starts with '.' names dotfiles on purpose.
    args = [a for a in commit_args(out_files, "k1", "--dry-run", files=[f".gitattributes={q}"]) if a not in ALLOW]
    proc = run([*args, "--allow", ".*"], env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["files"][0]["path"] == ".gitattributes"
    assert "leading '.'" in run(["--help"], env).stdout


# --- VS14: only a definite refusal releases the key ----------------------------------------------

GIT_WHOSE_REMOTE_DID_NOT_REPORT = """#!/bin/sh
if [ "$1" = push ]; then
  "$REAL_GIT" "$@" >/dev/null 2>&1
  printf 'To %s\\n!\\tHEAD:refs/heads/main\\t[remote failure] (remote failed to report status)\\nDone\\n' "$VCS_GIT_REMOTE"
  echo "error: failed to push some refs" >&2
  exit 1
fi
exec "$REAL_GIT" "$@"
"""


@needs_tools
def test_a_push_whose_remote_did_not_report_keeps_the_key_pending(remote, out_files, tmp_path):
    # Every '!' line of the push report other than [rejected] released the key; git also prints '!' for a remote
    # that did not report its status, after which the commit may well be on the branch.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "git"
    wrapper.write_text(GIT_WHOSE_REMOTE_DID_NOT_REPORT)
    wrapper.chmod(0o755)
    env = remote.provider_env()
    env.update({"REAL_GIT": shutil.which("git"), "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"})
    before = remote.head()
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 1 and "outcome is unknown" in proc.stderr, proc.stderr
    assert remote.head() != before  # the remote took it
    entry = ledger(env)["k1"]
    assert entry["status"] == "pending" and entry["attempted_commit"] == remote.head()


@needs_tools
def test_a_push_the_remote_refused_releases_the_key(remote, out_files):
    hook = remote.bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'declined by policy' >&2\nexit 1\n")
    hook.chmod(0o755)
    env = remote.provider_env()
    before = remote.head()
    proc = run(commit_args(out_files, "k1", "--confirmed"), env)
    assert proc.returncode == 1 and "[remote rejected]" in proc.stderr, proc.stderr
    assert remote.head() == before and ledger(env) == {}  # a definite refusal: the key is free


# --- WP-4.1: deletions, the executable bit, a branch started from a base -------------------------


def mode_of(remote, path, rev="refs/heads/main"):
    out = git(remote.env, remote.bare, "ls-tree", rev, "--", path).split()
    return out[0] if out else None


def refs(remote):
    return git(remote.env, remote.bare, "for-each-ref", "--format=%(refname) %(objectname)")


@needs_tools
def test_delete_removes_a_file_in_the_same_signed_commit(remote, out_files):
    env = remote.provider_env()
    count = remote.count()
    files = [f"data/pick-queue.json={out_files['queue']}"]
    proc = run(commit_args(out_files, "k1", "--confirmed", "--delete", "data/posts.json", files=files), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["pushed"] is True and out["signature"] == "ssh" and out["deletes"] == ["data/posts.json"]
    assert remote.count() == count + 1  # one commit holds both
    assert remote.changed() == ["data/pick-queue.json", "data/posts.json"]
    assert mode_of(remote, "data/posts.json") is None and mode_of(remote, "data/pick-queue.json") == "100644"
    assert "BEGIN SSH SIGNATURE" in git(remote.env, remote.bare, "cat-file", "commit", "refs/heads/main")
    assert ledger(env)["k1"]["deletes"] == ["data/posts.json"]


@needs_tools
def test_a_delete_outside_allow_or_also_given_as_a_file_is_refused_before_cloning(remote, out_files):
    env = remote.provider_env()
    before = refs(remote)
    files = [f"data/pick-queue.json={out_files['queue']}"]
    for extra in (["--delete", "README.md"], ["--delete", "data/pick-queue.json"], ["--delete", "../x"],
                  ["--delete", "data/posts.json", "--delete", "data/posts.json"], ["--delete", ".git/config"]):
        proc = run(commit_args(out_files, "k1", "--confirmed", *extra, files=files), env)
        assert proc.returncode == 2, (extra, proc.stderr)
    assert not work_root(env).exists()  # nothing was cloned
    assert refs(remote) == before and ledger(env) == {}


@needs_tools
def test_deleting_a_path_the_branch_does_not_hold_changes_nothing(remote, out_files):
    env = remote.provider_env()
    before = refs(remote)
    for key, path in (("k1", "data/pick-queue.json"), ("k2", "assets/posts/none.png")):
        proc = run(commit_args(out_files, key, "--confirmed", "--delete", path, files=[]), env)
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["unchanged"] is True and out["pushed"] is False and out["commit"] == remote.head()
    assert refs(remote) == before


@needs_tools
def test_a_delete_through_a_symlink_or_of_a_folder_is_refused_and_nothing_is_pushed(remote, out_files):
    env = remote.provider_env()
    before = refs(remote)
    for allow, path in (("assets/link/*", "assets/link/keep.txt"), ("assets/link", "assets/link"),
                        ("data", "data"), ("outside", "outside")):
        args = commit_args(out_files, "k1", "--confirmed", "--allow", allow, "--delete", path, files=[])
        proc = run(args, env)
        assert proc.returncode == 1, (path, proc.stderr)
        assert "symlink" in proc.stderr and "Nothing was pushed" in proc.stderr, proc.stderr
    assert refs(remote) == before and ledger(env) == {}
    assert list(work_root(env).iterdir()) == []
    assert git(remote.env, remote.bare, "show", "refs/heads/main:outside/keep.txt") == "keep\n"


@needs_tools
def test_mode_755_makes_a_new_file_executable_and_644_clears_the_bit(remote, out_files):
    env = remote.provider_env()
    files = [f"data/pick-queue.json={out_files['queue']}"]
    first = run(commit_args(out_files, "k1", "--confirmed", "--mode", "data/pick-queue.json=755", files=files), env)
    assert first.returncode == 0, first.stderr
    assert mode_of(remote, "data/pick-queue.json") == "100755"
    # Without --mode an existing file keeps its mode.
    out_files["queue"].write_text("[]\n")
    kept = run(commit_args(out_files, "k2", "--confirmed", files=files), env)
    assert kept.returncode == 0, kept.stderr
    assert mode_of(remote, "data/pick-queue.json") == "100755"
    cleared = run(commit_args(out_files, "k3", "--confirmed", "--mode", "data/pick-queue.json=644", files=files), env)
    assert cleared.returncode == 0, cleared.stderr
    out = json.loads(cleared.stdout)
    assert out["pushed"] is True and out["unchanged"] is False
    assert mode_of(remote, "data/pick-queue.json") == "100644"
    assert remote.changed() == ["data/pick-queue.json"]
    assert ledger(env)["k3"]["modes"] == [{"path": "data/pick-queue.json", "mode": "644"}]


@needs_tools
def test_a_mode_for_a_path_that_is_not_a_file_of_the_call_is_refused(remote, out_files):
    env = remote.provider_env()
    before = refs(remote)
    files = [f"data/pick-queue.json={out_files['queue']}"]
    for extra in (["--mode", "data/posts.json=755"], ["--mode", "data/pick-queue.json=700"],
                  ["--mode", "data/pick-queue.json"], ["--mode", "data/pick-queue.json=755",
                                                       "--mode", "data/pick-queue.json=644"],
                  ["--delete", "data/posts.json", "--mode", "data/posts.json=644"]):
        proc = run(commit_args(out_files, "k1", "--confirmed", *extra, files=files), env)
        assert proc.returncode == 2, (extra, proc.stderr)
    assert not work_root(env).exists()
    assert refs(remote) == before and ledger(env) == {}


def branch_args(out_files, key, branch, *extra):
    args = commit_args(out_files, key, *extra, files=[f"data/pick-queue.json={out_files['queue']}"])
    args[args.index("--branch") + 1] = branch
    return args


@needs_tools
def test_from_branch_creates_the_branch_from_the_base_when_the_remote_lacks_it(remote, out_files):
    env = remote.provider_env()
    main = remote.head()
    proc = run(branch_args(out_files, "k1", "wb/request-1", "--from-branch", "main", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    new = git(remote.env, remote.bare, "rev-parse", "refs/heads/wb/request-1").strip()
    assert out["commit"] == new and out["branch"] == "wb/request-1" and out["pushed"] is True
    assert git(remote.env, remote.bare, "rev-parse", "refs/heads/wb/request-1~1").strip() == main
    assert remote.head() == main  # the base is not touched
    assert remote.changed("refs/heads/wb/request-1") == ["data/pick-queue.json"]
    assert ledger(env)["k1"]["from_branch"] == "main"
    replay = run(branch_args(out_files, "k1", "wb/request-1", "--from-branch", "main", "--confirmed"), env)
    assert replay.returncode == 0 and json.loads(replay.stdout)["replayed"] is True


@needs_tools
def test_from_branch_is_not_used_when_the_branch_already_exists(remote, out_files):
    env = remote.provider_env()
    git(remote.env, remote.bare, "branch", "feature", "refs/heads/main")
    feature = git(remote.env, remote.bare, "rev-parse", "refs/heads/feature").strip()
    (remote.mover / "moved.txt").write_text("main moved\n")
    git(remote.env, remote.mover, "add", "moved.txt")
    git(remote.env, remote.mover, "commit", "-q", "-m", "main moves on")
    git(remote.env, remote.mover, "push", "-q", "origin", "HEAD:refs/heads/main")
    main = remote.head()
    dry = run(branch_args(out_files, "k1", "feature", "--from-branch", "main", "--dry-run"), env)
    assert dry.returncode == 0 and json.loads(dry.stdout)["branch_exists"] is True
    assert json.loads(dry.stdout)["base_commit"] == feature
    proc = run(branch_args(out_files, "k1", "feature", "--from-branch", "main", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    assert git(remote.env, remote.bare, "rev-parse", "refs/heads/feature~1").strip() == feature
    assert remote.head() == main
    assert remote.changed("refs/heads/feature") == ["data/pick-queue.json"]


@needs_tools
def test_without_from_branch_a_missing_branch_is_still_an_error(remote, out_files):
    env = remote.provider_env()
    before = refs(remote)
    proc = run(branch_args(out_files, "k1", "wb/request-2", "--confirmed"), env)
    assert proc.returncode == 1 and "failed" in proc.stderr, proc.stderr
    # A base that does not exist is an error too.
    base = run(branch_args(out_files, "k2", "wb/request-2", "--from-branch", "no-such-base", "--confirmed"), env)
    assert base.returncode == 1 and "no-such-base" in base.stderr, base.stderr
    bad = run(branch_args(out_files, "k3", "wb/request-2", "--from-branch", "main..x", "--confirmed"), env)
    assert bad.returncode == 2
    assert refs(remote) == before and ledger(env) == {}
    assert list(work_root(env).iterdir()) == []


@needs_tools
def test_dry_run_shows_deletes_modes_and_whether_the_branch_exists_and_pushes_nothing(remote, out_files):
    env = remote.provider_env()
    before = refs(remote)
    args = branch_args(out_files, "k1", "wb/request-3", "--from-branch", "main", "--delete", "data/posts.json",
                       "--mode", "data/pick-queue.json=755", "--dry-run")
    proc = run(args, env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["dry_run"] is True and out["branch_exists"] is False and out["from_branch"] == "main"
    assert out["deletes"] == ["data/posts.json"]
    assert out["modes"] == [{"path": "data/pick-queue.json", "mode": "755"}]
    assert out["base_commit"] == remote.head() and out["unchanged"] is False
    assert "data/posts.json" in out["diff_stat"] and "new file mode 100755" in out["diff"]
    plain = run(commit_args(out_files, "k1", "--dry-run"), env)
    assert json.loads(plain.stdout)["branch_exists"] is True and json.loads(plain.stdout)["deletes"] == []
    assert refs(remote) == before and ledger(env) == {}
    assert list(work_root(env).iterdir()) == []


@needs_tools
def test_a_key_recorded_before_deletes_existed_still_replays(remote, out_files):
    env = remote.provider_env()
    files = [{"path": "data/pick-queue.json", "sha256": sha256(out_files["queue"])},
             {"path": "assets/posts/vote-12.png", "sha256": sha256(out_files["image"])}]
    entry = {"kind": "commit", "repo": REPO, "branch": "main", "files": files,
             "message_sha256": sha256(out_files["message"]), "status": "committed", "commit": "c" * 40,
             "pushed": True, "unchanged": False, "signature": "ssh", "recorded_at": "2026-10-01T00:00:00Z"}
    path = Path(env["VCS_GITHUB_LEDGER"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "entries": {"old": entry}}))
    count = remote.count()
    proc = run(commit_args(out_files, "old", "--confirmed"), env)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["replayed"] is True and out["commit"] == "c" * 40 and out["deletes"] == []
    assert remote.count() == count
    # The same key with a deletion added is another change set.
    other = run(commit_args(out_files, "old", "--confirmed", "--delete", "data/posts.json"), env)
    assert other.returncode == 2 and "new key" in other.stderr


@needs_tools
def test_a_key_used_with_other_deletes_is_refused(remote, out_files):
    env = remote.provider_env()
    files = [f"data/pick-queue.json={out_files['queue']}"]
    first = run(commit_args(out_files, "k1", "--confirmed", "--delete", "data/posts.json", files=files), env)
    assert first.returncode == 0, first.stderr
    count = remote.count()
    for extra in (["--delete", "data/pick.json"], [], ["--delete", "data/posts.json", "--from-branch", "main"],
                  ["--delete", "data/posts.json", "--mode", "data/pick-queue.json=755"]):
        proc = run(commit_args(out_files, "k1", "--confirmed", *extra, files=files), env)
        assert proc.returncode == 2 and "new key" in proc.stderr, (extra, proc.stderr)
    assert remote.count() == count
    same = run(commit_args(out_files, "k1", "--confirmed", "--delete", "data/posts.json", files=files), env)
    assert same.returncode == 0 and json.loads(same.stdout)["replayed"] is True
