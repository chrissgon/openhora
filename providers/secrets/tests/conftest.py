"""Every test of this suite reaches no network but loopback: the guard of providers/loopback_only.py."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("providers_loopback_only",
                                               Path(__file__).resolve().parents[2] / "loopback_only.py")
loopback_only = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loopback_only)


@pytest.fixture(scope="session")
def _loopback_site(tmp_path_factory):
    return loopback_only.write_site(str(tmp_path_factory.mktemp("loopback_site")))


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch, _loopback_site):
    loopback_only.guard(monkeypatch, _loopback_site)


@pytest.fixture(autouse=True)
def _no_test_reaches_a_real_password_manager(monkeypatch, tmp_path):
    """The resolver asks a password manager only for a name in the mapping file (package S16). No test may find the person's real file,
    so the tool it names is never started from here: the config folder is an empty one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config-directory"))
    monkeypatch.delenv("WB_EVAL_CONTAINER", raising=False)
