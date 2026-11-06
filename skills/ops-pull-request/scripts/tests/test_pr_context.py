"""Tests for skills/ops-pull-request/scripts/pr-context.sh. Offline; every name and number below is fictional.

Run: uv run --with pytest pytest skills/ops-pull-request/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@localhost",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def repo_with_change(tmp_path: Path, text: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "app.py")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "app.py").write_text("x = 1\n" + text, encoding="utf-8")
    return repo


# ---------- ops-pull-request/pr-context.sh (M22) ----------

PR_CONTEXT = ROOT / "skills/ops-pull-request/scripts/pr-context.sh"
BASH = __import__("shutil").which("bash")


def only_tools(tmp_path: Path, *names: str) -> dict:
    """An environment whose PATH holds only the named tools, so no host CLI or network tool is reachable."""
    import os
    import shutil
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for n in names:
        (bin_dir / n).symlink_to(shutil.which(n))
    return {**os.environ, "PATH": str(bin_dir)}


def test_pr_context_refuses_option_like_base(tmp_path):
    repo = repo_with_change(tmp_path, "y = 2\n")
    env = only_tools(tmp_path, "git", "python3", "sed", "dirname")
    for base in ("--upload-pack=touch pwned", "-x", "main..evil", "a b"):
        r = subprocess.run([BASH, str(PR_CONTEXT), "--base", base], cwd=repo, env=env,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 2, (base, r.stderr)
        assert "is not a branch name" in r.stderr
    assert not (repo / "pwned").exists()
    git(repo, "branch", "-q", "-M", "main")
    git(repo, "switch", "-q", "-c", "feature")
    git(repo, "commit", "-q", "-am", "feature work")
    r = subprocess.run([BASH, str(PR_CONTEXT), "--base", "main"], cwd=repo, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["compared_with"] == "main" and len(out["commits"]) == 1


def run_pr_context(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, str(PR_CONTEXT), *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=60)


def test_pr_context_help_exits_0_and_prints_usage(tmp_path):
    repo = repo_with_change(tmp_path, "")
    r = run_pr_context(repo, only_tools(tmp_path, "git", "python3", "sed", "dirname"), "--help")
    assert r.returncode == 0
    assert "Usage: bash pr-context.sh" in r.stdout and r.stderr == ""


def test_pr_context_usage_errors_exit_2_with_a_message_on_stderr(tmp_path):
    repo = repo_with_change(tmp_path, "")
    env = only_tools(tmp_path, "git", "python3", "sed", "dirname")
    r = run_pr_context(repo, env, "--base")
    assert r.returncode == 2 and "--base needs a value" in r.stderr and r.stdout == ""
    r = run_pr_context(repo, env, "--head", "feature")
    assert r.returncode == 2 and "unknown option '--head'" in r.stderr and r.stdout == ""
    assert "Traceback" not in r.stderr


def test_pr_context_reports_the_origin_address(tmp_path):
    repo = repo_with_change(tmp_path, "y = 2\n")
    git(repo, "branch", "-q", "-M", "main")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "switch", "-q", "-c", "feature")
    git(repo, "commit", "-q", "-am", "feature work")
    r = run_pr_context(repo, only_tools(tmp_path, "git", "python3", "sed", "dirname"))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["remote"] == str(origin)


def test_pr_context_finds_the_template_and_works_without_a_remote_or_host_tool(tmp_path):
    repo = repo_with_change(tmp_path, "y = 2\n")
    git(repo, "branch", "-q", "-M", "main")
    (repo / ".github").mkdir()
    (repo / ".github" / "pull_request_template.md").write_text("## Summary\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("- Merges are squash merges.\n- Unrelated line.\n", encoding="utf-8")
    git(repo, "add", ".github", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "docs: template")
    git(repo, "switch", "-q", "-c", "feature")
    git(repo, "commit", "-q", "-am", "feature work")
    r = run_pr_context(repo, only_tools(tmp_path, "git", "python3", "sed", "dirname"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["base"] == "main" and out["compared_with"] == "main"
    assert out["template"] == {"path": ".github/pull_request_template.md", "content": "## Summary\n"}
    assert out["pushed"] is False and out["open_pull_request"] is None
    assert out["remote"] is None
    assert out["merge_rules"] == ["AGENTS.md: - Merges are squash merges."]
    assert out["commits"][0].endswith("feature work") and out["files"] == ["M\tapp.py"]
