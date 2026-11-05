"""Tests of the whole-suite sharding: the pytest plugin that keeps the K-th of N shards of the collected tests
(scripts/pytest_plugins/wb_shard.py) and its launcher (scripts/shard_tests.py). Offline; the suites are written in a temporary folder.

Run: uv run --with pytest --with pytest-xdist pytest scripts/tests/test_shard_tests.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGINS = REPO / "scripts" / "pytest_plugins"
LAUNCHER = REPO / "scripts" / "shard_tests.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wb_shard = load("wb_shard_under_test", PLUGINS / "wb_shard.py")
launcher = load("shard_tests_under_test", LAUNCHER)


@pytest.fixture
def suite(tmp_path):
    """Three files of eight tests each: seven parametrized and one plain."""
    folder = tmp_path / "suite"
    folder.mkdir()
    for number in range(3):
        (folder / f"test_f{number}.py").write_text(
            "import pytest\n\n\n"
            '@pytest.mark.parametrize("x", range(7))\n'
            "def test_param(x):\n    assert x >= 0\n\n\n"
            "def test_plain():\n    assert True\n"
        )
    return folder


def run(args, env=None):
    return subprocess.run(args, capture_output=True, text=True, timeout=120, env=env)


def names_in(path):
    return {f"{case.get('classname')}::{case.get('name')}" for case in ET.parse(path).getroot().iter("testcase")}


def test_parse_takes_k_of_n_and_refuses_the_rest():
    assert wb_shard.parse("1/1") == (1, 1)
    assert wb_shard.parse("1/3") == (1, 3)
    assert wb_shard.parse("3/3") == (3, 3)
    for bad in (None, "", "0/3", "4/3", "a/3", "3", "1/0", "-1/3", " 1/3"):
        with pytest.raises(ValueError):
            wb_shard.parse(bad)


def test_every_item_is_in_exactly_one_shard():
    for n in range(1, 6):
        for length in range(0, 41):
            items = [f"t{i}" for i in range(length)]
            kept_all = []
            for k in range(1, n + 1):
                kept, dropped = wb_shard.split(items, k, n)
                assert sorted(kept + dropped) == sorted(items)
                kept_all.extend(kept)
            assert sorted(kept_all) == sorted(items)
            assert len(kept_all) == len(set(kept_all))


def test_a_new_file_anywhere_in_the_collection_lands_in_exactly_one_shard():
    items = [f"t{i}" for i in range(30)]
    new = ["new::a", "new::b", "new::c", "new::d"]
    for name, position in zip(new, (0, 7, 19, 30)):
        items.insert(position, name)
    n = 3
    kept_all = []
    for k in range(1, n + 1):
        kept, dropped = wb_shard.split(items, k, n)
        assert sorted(kept + dropped) == sorted(items)
        kept_all.extend(kept)
    assert sorted(kept_all) == sorted(items)
    for name in new:
        assert sum(name in wb_shard.split(items, k, n)[0] for k in range(1, n + 1)) == 1


def shards_junit(suite, tmp_path, extra):
    sets = []
    for k in range(1, 4):
        xml = tmp_path / f"j{k}.xml"
        result = run([sys.executable, str(LAUNCHER), "--shard", f"{k}/3", "--", "-q", "-p", "no:cacheprovider", *extra,
                      f"--junitxml={xml}", str(suite)])
        assert result.returncode == 0, result.stdout + result.stderr
        sets.append(names_in(xml))
    return sets


def test_three_shards_under_xdist_run_every_test_once(suite, tmp_path):
    pytest.importorskip("xdist")
    sets = shards_junit(suite, tmp_path, ["-n", "2"])
    assert all(sets)
    assert not (sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
    assert len(sets[0] | sets[1] | sets[2]) == 24


def test_three_shards_without_xdist_run_every_test_once(suite, tmp_path):
    sets = shards_junit(suite, tmp_path, [])
    assert all(sets)
    assert not (sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
    assert len(sets[0] | sets[1] | sets[2]) == 24


def test_a_bad_shard_is_refused_and_runs_nothing(suite):
    for bad in ("4/3", "0/3"):
        result = run([sys.executable, str(LAUNCHER), "--shard", bad, "--", "-q", "-p", "no:cacheprovider", str(suite)])
        output = result.stdout + result.stderr
        assert result.returncode == 4, output
        assert "K/N" in output
        assert "passed" not in output
    result = run([sys.executable, str(LAUNCHER), "--", "-q", "-p", "no:cacheprovider", str(suite)])
    assert result.returncode == 2


def test_the_plugin_does_nothing_without_its_option(suite):
    env = {**os.environ, "PYTHONPATH": str(PLUGINS)}
    result = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "wb_shard", str(suite)], env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "24 passed" in result.stdout
