"""The suites of scripts/ never read the person's password-manager mapping file (package S16). The conftest of this folder points
XDG_CONFIG_HOME at an empty folder for the whole session, so a file under the real home folder is not found and the tool it names is
never started. A fake home with a mapping and a FAKE `op` that records its calls: no call. No real 1Password, no real secret.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_password_manager_isolation.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fake_op = load("fake_op_for_scripts_isolation", REPO / "providers" / "secrets" / "tests" / "fake_op.py")
doctor = load("doctor_for_isolation", REPO / "scripts" / "doctor.py")
SENTINEL = "zz-not-a-real-value-iso"


@pytest.fixture
def machine(tmp_path, monkeypatch):
    op = fake_op.FakeOp(tmp_path / "bin")
    op.answer("*", stdout=SENTINEL)
    home = tmp_path / "home"
    (home / ".config" / "openhora").mkdir(parents=True)
    mapping = home / ".config" / "openhora" / "password-manager.json"
    mapping.write_text(json.dumps({"backend": "1password", "references": {"VCS_GITHUB_TOKEN": "op://Example Vault/github-read/credential"}}),
                       encoding="utf-8")
    mapping.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{op.folder}{os.pathsep}/usr/bin{os.pathsep}/bin")
    monkeypatch.setitem(sys.modules, "keyring", None)   # no OS secret store is reached
    for name in ("VCS_GITHUB_TOKEN", "GITHUB_TOKEN", "OPENHORA_CREDENTIALS_DIR", "CREDENTIALS_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    return op, mapping


def test_the_session_points_the_config_folder_at_an_empty_one(machine):
    folder = Path(os.environ["XDG_CONFIG_HOME"])
    assert folder.is_dir() and not (folder / "openhora").exists()


def test_a_mapping_under_the_real_home_is_never_read_by_the_doctor_or_the_probe(machine):
    op, mapping = machine
    rows = {row["name"]: row for row in doctor.secrets_report({})}
    assert rows["VCS_GITHUB_TOKEN"]["state"] == "missing" and rows["VCS_GITHUB_TOKEN"]["backend"] is None
    assert doctor.manager_probe()["state"] == "na"
    assert mapping.exists() and op.calls() == []
