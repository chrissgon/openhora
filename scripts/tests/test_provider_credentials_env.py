"""A provider's process reaches the credentials directory (package S16): `provider_environment` keeps OPENHORA_CREDENTIALS_DIR and
CREDENTIALS_DIRECTORY (they carry a path, never a secret), so a provider that reads its secret through the resolver finds a credentials
directory that only these variables name. Before, both were stripped and the secret read as missing. A fake value (SENTINEL) in a
temporary folder; no real secret is read.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_provider_credentials_env.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SENTINEL = "zz-not-a-real-value-credentials-env"
RESOLVER = REPO / "providers" / "secrets" / "resolver.py"

spec = importlib.util.spec_from_file_location("workbench_resolve_credentials_env", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = resolve
spec.loader.exec_module(resolve)


def credentials_folder(tmp_path):
    folder = tmp_path / "creds"
    folder.mkdir(mode=0o700)
    folder.chmod(0o700)
    file = folder / "VCS_GITHUB_TOKEN"
    file.write_text(SENTINEL + "\n", encoding="utf-8")
    file.chmod(0o600)
    return folder


def test_the_two_variables_that_name_the_credentials_directory_pass_and_no_secret_does():
    env = {"PATH": "/bin", "OPENHORA_CREDENTIALS_DIR": "/c/one", "CREDENTIALS_DIRECTORY": "/c/two",
           "VCS_GITHUB_TOKEN": SENTINEL, "ANTHROPIC_API_KEY": SENTINEL, "OP_SERVICE_ACCOUNT_TOKEN": SENTINEL, "OP_SESSION_demo": SENTINEL}
    got = resolve.provider_environment("generator:image", env)
    assert got == {"PATH": "/bin", "OPENHORA_CREDENTIALS_DIR": "/c/one", "CREDENTIALS_DIRECTORY": "/c/two"}
    assert SENTINEL not in json.dumps(got)


def test_the_interpreter_a_scheduled_job_pins_passes_to_a_provider_process():
    """UV_PYTHON names an interpreter and carries no secret: a provider started through uv run keeps the pin (F2-C)."""
    env = {"PATH": "/bin", "UV_PYTHON": "/opt/py/python3.12", "VCS_GITHUB_TOKEN": SENTINEL}
    assert resolve.provider_environment("generator:image", env) == {"PATH": "/bin", "UV_PYTHON": "/opt/py/python3.12"}
    assert resolve.provider_environment("generator:image", {"PATH": "/bin"}) == {"PATH": "/bin"}


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="the credentials directory checks owners")
def test_a_provider_process_finds_a_credentials_directory_that_only_the_variable_names(tmp_path):
    folder = credentials_folder(tmp_path)
    home = tmp_path / "empty-home"
    home.mkdir()
    process_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "OPENHORA_CREDENTIALS_DIR": str(folder)}
    given = resolve.provider_environment("integration:vcs", process_env)
    assert given["OPENHORA_CREDENTIALS_DIR"] == str(folder)
    ran = subprocess.run([sys.executable, str(RESOLVER), "--check", "VCS_GITHUB_TOKEN"], env=given, capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0 and SENTINEL not in ran.stdout + ran.stderr
    assert json.loads(ran.stdout)["source"] == "credentials directory"
    # what it was before: the variable stripped, the same process finds nothing
    stripped = {k: v for k, v in given.items() if k != "OPENHORA_CREDENTIALS_DIR"}
    lost = subprocess.run([sys.executable, str(RESOLVER), "--check", "VCS_GITHUB_TOKEN"], env=stripped, capture_output=True, text=True, timeout=60)
    assert lost.returncode != 0
