"""The guard of the test isolation: no test folder runs without the null keyring backend (package KEYCHAIN-ISOLATION).

The resolver reads the OS secret store through the keyring library when it is installed (`uv run --with keyring`), and a
test that reached it made the maintainer's Mac ask for the key "openhora". The rule is "tests never touch the real secret
store"; its one home is the conftest.py at the repository root, which pytest loads for a folder only when `pytest.ini`
makes the root the rootdir. These tests fail when a test folder would be run without it, when the root file stops
forcing the backend, and when a child process started with a minimal env would not get it. Offline.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_test_isolation.py
"""
import importlib.util
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NULL_BACKEND = "keyring.backends.null.Keyring"
HEADER = f"secret store: PYTHON_KEYRING_BACKEND={NULL_BACKEND}"


def load_test_dirs():
    spec = importlib.util.spec_from_file_location("test_dirs_for_isolation", ROOT / "scripts" / "test_dirs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.test_dirs(str(ROOT))


def read_vars(**more_env):
    """What a child sees of the variable, started through `subprocess.run` with an env of the test's own making."""
    code = "import os; print(os.environ.get('PYTHON_KEYRING_BACKEND', 'UNSET'))"
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PATH": os.environ["PATH"], **more_env}).stdout.strip()


def test_this_process_has_the_null_backend():
    assert os.environ["PYTHON_KEYRING_BACKEND"] == NULL_BACKEND


def test_the_root_conftest_and_ini_file_are_there():
    conftest = (ROOT / "conftest.py").read_text(encoding="utf-8")
    assert NULL_BACKEND in conftest and "os.environ[VARIABLE] = NULL_KEYRING_BACKEND" in conftest
    assert (ROOT / "pytest.ini").is_file(), "without an ini-file at the root, pytest does not load the root conftest.py for a folder run alone"


def test_no_folder_below_the_root_moves_the_rootdir():
    """A pytest.ini, tox.ini, setup.cfg or pyproject.toml with pytest settings inside a test folder (or a parent of one) becomes its own
    ini-file: the rootdir moves there and the root conftest.py is no longer loaded."""
    offenders = []
    for folder in load_test_dirs():
        path = ROOT / folder
        while path != ROOT:
            for name in ("pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"):
                candidate = path / name
                if candidate.is_file() and (name in ("pytest.ini", ".pytest.ini") or "pytest" in candidate.read_text(encoding="utf-8", errors="replace")):
                    offenders.append(str(candidate.relative_to(ROOT)))
            path = path.parent
    assert not offenders, f"these files move pytest's rootdir away from the repository root: {sorted(set(offenders))}"


def test_every_test_folder_loads_the_root_conftest_when_run_alone():
    """Start pytest on each folder as a person does (`pytest <folder>`), with collection of python files off so that it only
    prints its header: the header carries the root conftest's line and the ini-file."""
    folders = load_test_dirs()
    assert len(folders) > 40, "the list of test folders looks wrong"

    def header(folder):
        done = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:python", "-p", "no:cacheprovider", str(ROOT / folder)],
                              capture_output=True, text=True, timeout=120, cwd=str(ROOT / folder))
        return folder, done.stdout

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(header, folders))
    missing = [folder for folder, out in results if HEADER not in out or "configfile: pytest.ini" not in out]
    assert not missing, f"these test folders run without the root conftest.py (and so without the null keyring backend): {missing}"


def test_a_child_started_with_a_minimal_env_gets_the_null_backend():
    assert read_vars() == NULL_BACKEND
    assert subprocess.run([sys.executable, "-c", "import os; print(os.environ.get('PYTHON_KEYRING_BACKEND', 'UNSET'))"],
                          capture_output=True, text=True, env={}).stdout.strip() == NULL_BACKEND
    assert subprocess.check_output([sys.executable, "-c", "import os; print(os.environ.get('PYTHON_KEYRING_BACKEND', 'UNSET'))"],
                                   text=True, env={"PATH": os.environ["PATH"]}).strip() == NULL_BACKEND
    inherited = subprocess.run([sys.executable, "-c", "import os; print(os.environ.get('PYTHON_KEYRING_BACKEND', 'UNSET'))"],
                               capture_output=True, text=True).stdout.strip()
    assert inherited == NULL_BACKEND


def test_the_callers_env_dict_is_not_changed_and_a_backend_it_names_is_kept():
    env = {"PATH": os.environ["PATH"]}
    subprocess.run([sys.executable, "-c", "pass"], env=env)
    assert env == {"PATH": os.environ["PATH"]}
    assert read_vars(PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring") == "keyring.backends.fail.Keyring"
