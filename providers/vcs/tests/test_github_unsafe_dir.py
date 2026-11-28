"""The GitHub provider tells an unsafe credentials directory from a missing token (T34). Offline: a loopback address
nobody listens on, a temporary credentials folder, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/vcs/tests/test_github_unsafe_dir.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "github.py"
PLANTED_VALUE = "zz-not-a-real-value-41"
DEAD_BASE = "http://127.0.0.1:9"


def load_module():
    spec = importlib.util.spec_from_file_location("github_provider_unsafe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("VCS_GITHUB_TOKEN", "GITHUB_TOKEN", "VCS_GITHUB_PR_TOKEN", "CREDENTIALS_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def credentials(tmp_path, folder_mode, file_mode=None, name="VCS_GITHUB_TOKEN"):
    folder = tmp_path / "credentials"
    folder.mkdir()
    if file_mode is not None:
        (folder / name).write_text(PLANTED_VALUE, encoding="utf-8")
        (folder / name).chmod(file_mode)
    folder.chmod(folder_mode)
    return folder


def test_github_an_unsafe_credentials_directory_says_unsafe_and_names_the_chmod(tmp_path):
    folder = credentials(tmp_path, 0o755, 0o644)
    env = {k: v for k, v in os.environ.items() if k not in ("VCS_GITHUB_TOKEN", "GITHUB_TOKEN", "CREDENTIALS_DIRECTORY")}
    env.update(OPENHORA_CREDENTIALS_DIR=str(folder), VCS_GITHUB_API_BASE=DEAD_BASE)
    done = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, timeout=60, env=env)
    assert done.returncode == 3
    assert "unsafe" in done.stderr and "chmod" in done.stderr
    assert "no GitHub token" not in done.stderr and PLANTED_VALUE not in done.stderr + done.stdout


def test_github_a_missing_token_keeps_its_message(tmp_path):
    folder = credentials(tmp_path, 0o700)
    env = {k: v for k, v in os.environ.items() if k not in ("VCS_GITHUB_TOKEN", "GITHUB_TOKEN", "CREDENTIALS_DIRECTORY")}
    env.update(OPENHORA_CREDENTIALS_DIR=str(folder), VCS_GITHUB_API_BASE=DEAD_BASE)
    done = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, timeout=60, env=env)
    assert done.returncode == 3 and "no GitHub token" in done.stderr and "unsafe" not in done.stderr


def test_an_optional_token_and_a_locked_store_still_read_without_a_token(tmp_path, clean_env):
    module = load_module()

    class Locked:
        state, value, detail = "locked", "", "the store is locked"

    class Resolver:
        def resolve_state(self, name, allow_store=True):
            return Locked()

    clean_env.setattr(module, "secret_resolver", lambda: Resolver())
    assert module.load_token(False, required=False) == ("", "")
    with pytest.raises(module.ProviderError) as caught:
        module.load_token(False)
    assert caught.value.code == 3 and "locked" in str(caught.value)


def test_an_unsafe_directory_raises_even_when_the_token_is_optional(tmp_path, clean_env):
    folder = credentials(tmp_path, 0o755, 0o644)
    clean_env.setenv("OPENHORA_CREDENTIALS_DIR", str(folder))
    module = load_module()
    with pytest.raises(module.ProviderError) as caught:
        module.load_token(True, required=False)
    assert caught.value.code == 3 and "unsafe" in str(caught.value)


def test_github_the_pull_request_token_name_is_checked_too(tmp_path, clean_env):
    folder = credentials(tmp_path, 0o755, 0o644, name="VCS_GITHUB_PR_TOKEN")
    clean_env.setenv("OPENHORA_CREDENTIALS_DIR", str(folder))
    module = load_module()
    with pytest.raises(module.ProviderError) as caught:
        module.load_pr_token(True)
    assert caught.value.code == 3 and "unsafe" in str(caught.value) and "chmod" in str(caught.value)


def test_github_an_older_resolver_without_resolve_state_keeps_the_old_reading(tmp_path, clean_env):
    module = load_module()

    class Old:
        def resolve(self, name, allow_store=True):
            return (PLANTED_VALUE, "environment")

    clean_env.setattr(module, "secret_resolver", lambda: Old())
    assert module.load_token(True) == (PLANTED_VALUE, "environment")
