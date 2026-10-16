"""The isolation every test of the repository shares: no test reaches the real OS secret store.

The resolver (providers/secrets/resolver.py) reads the keyring package when it is installed, as it is under
`uv run --with keyring`, and the secret store of the machine then answers (a prompt for the key "openhora" on a Mac).
A test must never be the one that asks. So, for the whole test process and for every process a test starts:

1. `PYTHON_KEYRING_BACKEND` is the library's null backend, set when this file is imported (before any test module imports
   the keyring library) and again at the start of every test, so a test that cleared the environment gets it back.
2. A keyring library already loaded in the process gets the null backend as its chosen one, for the length of each test.
3. A child process started with an `env` that a test or the code under test built (a minimal one such as
   `{"PATH": ..., "HOME": ...}` carries no variable of the parent) gets the variable too, unless that env sets it. This is
   done on `subprocess.Popen`, which `subprocess.run`, `check_output` and the rest go through. The caller's dict is copied,
   never changed. It is a property of the test run only: no production code is changed, and nothing outside a test sets it.

This file sits at the root, next to `pytest.ini`, which makes the root the rootdir and so makes pytest load this file
whichever test folder is named on the command line. `scripts/tests/test_test_isolation.py` fails when any test folder
would run without it. "Tests never touch the real secret store" is the rule stated in `contracts/secrets.md`.
"""
import os
import subprocess

import pytest

NULL_KEYRING_BACKEND = "keyring.backends.null.Keyring"
VARIABLE = "PYTHON_KEYRING_BACKEND"

os.environ[VARIABLE] = NULL_KEYRING_BACKEND


def _with_null_backend(env):
    """A copy of `env` that names the null backend unless it names a backend itself; None (inherit) stays None."""
    if env is None or VARIABLE in env:
        return env
    copy = dict(env)
    copy[VARIABLE] = NULL_KEYRING_BACKEND
    return copy


def _install_popen_env_guard():
    """Wrap `subprocess.Popen.__init__` once per process (a conftest can be imported again by a worker or a re-run)."""
    original = subprocess.Popen.__init__
    if getattr(original, "_null_keyring_guard", False):
        return

    def init(self, *args, **kwargs):
        if kwargs.get("env") is not None:
            kwargs["env"] = _with_null_backend(kwargs["env"])
        elif len(args) > 10 and args[10] is not None:   # Popen(args, bufsize, executable, stdin, stdout, stderr, preexec_fn, close_fds, shell, cwd, env)
            args = (*args[:10], _with_null_backend(args[10]), *args[11:])
        original(self, *args, **kwargs)

    init._null_keyring_guard = True
    init.__wrapped__ = original
    subprocess.Popen.__init__ = init


_install_popen_env_guard()


@pytest.fixture(autouse=True)
def no_test_reaches_the_real_secret_store(monkeypatch):
    monkeypatch.setenv(VARIABLE, NULL_KEYRING_BACKEND)
    try:
        import keyring.core
        from keyring.backends import null
    except Exception:   # no keyring library here: nothing to isolate in this process
        return
    monkeypatch.setattr(keyring.core, "_keyring_backend", null.Keyring())


def pytest_report_header(config):
    """A line the guard test (scripts/tests/test_test_isolation.py) looks for to know this file was loaded."""
    return f"secret store: {VARIABLE}={NULL_KEYRING_BACKEND} (conftest.py at the repository root)"
