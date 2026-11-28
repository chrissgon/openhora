"""The LinkedIn provider and its authorization script tell an unsafe credentials directory from a missing token (T34).
Offline: a loopback address nobody listens on, temporary folders, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/publisher/tests/test_publisher_unsafe_dir.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINKEDIN = HERE.parent / "linkedin.py"
AUTH = HERE.parent / "auth.py"
PLANTED_VALUE = "zz-not-a-real-value-41"
DEAD_BASE = "http://127.0.0.1:9"


def run(script, argv, folder, tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("LINKEDIN_ACCESS_TOKEN", "CREDENTIALS_DIRECTORY")}
    env.update(OPENHORA_CREDENTIALS_DIR=str(folder), LINKEDIN_API_BASE=DEAD_BASE, HOME=str(tmp_path / "home"))
    return subprocess.run([sys.executable, str(script), *argv], capture_output=True, text=True, timeout=60, env=env)


def make(tmp_path, folder_mode, file_mode=None):
    folder = tmp_path / "credentials"
    folder.mkdir()
    if file_mode is not None:
        (folder / "LINKEDIN_ACCESS_TOKEN").write_text(PLANTED_VALUE, encoding="utf-8")
        (folder / "LINKEDIN_ACCESS_TOKEN").chmod(file_mode)
    folder.chmod(folder_mode)
    return folder


def test_publisher_an_unsafe_credentials_directory_says_unsafe_and_names_the_chmod(tmp_path):
    folder = make(tmp_path, 0o755, 0o644)
    done = run(LINKEDIN, ["--check"], folder, tmp_path)
    assert done.returncode == 3
    assert "unsafe" in done.stderr and "chmod" in done.stderr
    assert "no LinkedIn access token" not in done.stderr and PLANTED_VALUE not in done.stderr + done.stdout


def test_publisher_the_authorization_check_says_unsafe_and_names_the_chmod(tmp_path):
    folder = make(tmp_path, 0o755, 0o644)
    done = run(AUTH, ["--provider", "linkedin", "--check"], folder, tmp_path)
    assert done.returncode == 3
    out = json.loads(done.stdout)
    assert out["found"] is False and out["state"] == "unsafe"
    assert "unsafe" in done.stderr and "chmod" in done.stderr and "no LinkedIn token" not in done.stderr
    assert PLANTED_VALUE not in done.stderr + done.stdout


def test_publisher_a_missing_token_keeps_its_message(tmp_path):
    folder = make(tmp_path, 0o700)
    done = run(LINKEDIN, ["--check"], folder, tmp_path)
    assert done.returncode == 3 and "no LinkedIn access token" in done.stderr and "unsafe" not in done.stderr
    checked = run(AUTH, ["--provider", "linkedin", "--check"], folder, tmp_path)
    assert checked.returncode == 3 and json.loads(checked.stdout)["found"] is False
    assert "no LinkedIn token" in checked.stderr
