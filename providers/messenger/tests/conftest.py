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
def _no_real_secret_store_or_state(monkeypatch, tmp_path):
    """No test of this suite can reach the OS secret store, even where the keyring library is installed, nor the person's state
    folder: the null keyring backend (for this process and any child it starts) and a temporary OPENHORA_STATE_DIR. A test that
    needs another state folder sets its own after this fixture."""
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "isolated-state"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    try:
        import keyring
        from keyring.backends import null
        previous = keyring.get_keyring()
        keyring.set_keyring(null.Keyring())
    except Exception:  # no keyring library here: nothing to isolate
        yield
        return
    yield
    keyring.set_keyring(previous)
