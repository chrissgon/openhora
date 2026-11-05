"""The conftest of this folder clears the STOPPING flags after every test.

One test, so the result does not depend on how pytest-xdist splits the tests between workers. It checks that the
autouse fixture is in force for it, sets both flags, calls the function the fixture calls at the end of every test,
and asserts both flags clear.
"""
import importlib.util
from pathlib import Path

import standin_tree as st

# Loaded by path: with other conftest.py files in a run, the name `conftest` may be another folder's module.
_SPEC = importlib.util.spec_from_file_location("runtime_tests_conftest", Path(__file__).with_name("conftest.py"))
conftest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(conftest)


def test_the_stopping_flags_are_cleared_by_the_function_the_autouse_fixture_calls(request):
    assert "a_stopping_flag_does_not_outlive_its_test" in request.fixturenames
    runs, kit = st.load("ops_runs"), st.load("lab").load()  # the lab facade loads the kit under the name conftest reads
    runs.STOPPING.set()
    kit.STOPPING.set()
    assert runs.STOPPING.is_set() and kit.STOPPING.is_set()
    conftest.clear_stopping_flags()
    assert not runs.STOPPING.is_set()
    assert not kit.STOPPING.is_set()
