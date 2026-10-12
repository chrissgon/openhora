"""Tests of the project key max_running (PAR-2): the most task runs of a project at one time, 1 to 14, default 3.
Offline: the stand-in tree (runtime/tests/standin_tree.py).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_project_config_max_running.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

lab = st.load("lab")
ops_core = st.load("ops_core")
project_config = st.load("project_config")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def configure(tree, **extra) -> str:
    path = str(tree["project"])
    file = project_config.path(path)
    with open(file, encoding="utf-8") as f:
        good = json.load(f)
    good.pop("max_running", None)
    with open(file, "w", encoding="utf-8") as f:
        json.dump({**good, **extra}, f)
    return path


def test_max_running_defaults_to_3_and_is_a_known_key(tree):
    assert "max_running" in project_config.TASK_RUNTIME_KEYS
    assert project_config.load(configure(tree))["max_running"] == 3


def test_max_running_accepts_1_to_14(tree):
    for value in (1, 4, 14):
        assert project_config.load(configure(tree, max_running=value))["max_running"] == value


def test_max_running_outside_1_to_14_or_not_an_integer_is_refused(tree):
    for bad in (0, -1, 15, 2.5, "3", True, None):
        path = configure(tree, max_running=bad)
        with pytest.raises(project_config.ConfigError) as raised:
            project_config.load(path)
        assert "runtime.json max_running must be an integer from 1 to 14" in str(raised.value), bad
