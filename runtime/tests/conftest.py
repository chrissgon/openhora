"""Two rules for the tests of the runtime. The first: nothing a test does to the process outlives it.

The service, `ops.stop_runs` and the lab's `session()` end by setting a STOPPING flag, a module-level event that a
later `run_group` reads as "no child starts any more" (it then answers as a timeout). Run in one process in file order,
the tests that clear it happen to follow the ones that set it; split across workers (pytest-xdist), a test lands behind
any other. So each test ends with the flag clear, in the two modules that hold one. The second is at the end of this file.
"""
import os
import sys
from pathlib import Path

import pytest

STOPPING_OWNERS = ("ops_runs", "workbench_eval_execution")


@pytest.fixture(autouse=True)
def a_stopping_flag_does_not_outlive_its_test():
    yield
    for name in STOPPING_OWNERS:
        flag = getattr(sys.modules.get(name), "STOPPING", None)
        if hasattr(flag, "clear"):
            flag.clear()


# The Python 3.9 job (.github/workflows/checks.yml) tests what the scheduler starts with the system interpreter. The
# test_interface_*.py files drive Node over JavaScript, CSS and HTML, and Python's version changes nothing for them, so
# that job sets WB_SKIP_JS_ONLY_TESTS=1 and they are not collected there; every other job and a plain run collect
# them. A file that loads a Python module of the runtime (standin_tree's load(), a script of scripts/, a sys.path
# entry) is not JS-only and is always collected, so a new interface test that exercises Python stays on 3.9.
PYTHON_MARKERS = ("st.load(", "load_script(", "sys.path.insert", "spec_from_file_location")


def pytest_ignore_collect(collection_path, config):
    if os.environ.get("WB_SKIP_JS_ONLY_TESTS") != "1":
        return None
    path = Path(str(collection_path))
    if path.parent == Path(__file__).resolve().parent and path.name.startswith("test_interface_") and path.suffix == ".py":
        text = path.read_text(encoding="utf-8")
        if not any(marker in text for marker in PYTHON_MARKERS):
            return True
    return None
