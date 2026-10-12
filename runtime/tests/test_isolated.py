"""Skill code runs isolated (runtime/isolated.py): an isolated interpreter, an environment of exactly the names the module
lists, a working folder the caller names, a fresh HOME that is removed, a timeout that raises, and no module of runtime/
that loads a file of skills/ as code in its own process. Offline: invented scripts in a temporary folder.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_isolated.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess

import pytest

import standin_tree as st

isolated = st.load("isolated")

REPORT = '''import json, os, sys
print(json.dumps({"env": sorted(os.environ), "home": os.environ.get("HOME"), "tmp": os.environ.get("TMPDIR"),
                  "cwd": os.getcwd(), "isolated": sys.flags.isolated, "argv": sys.argv[1:], "stdin": sys.stdin.read(),
                  "home_exists": os.path.isdir(os.environ["HOME"]), "path_has_script_dir": any(
                      p == os.path.dirname(os.path.abspath(__file__)) for p in sys.path)}))
'''


def script(tmp_path, body=REPORT):
    file = tmp_path / "s.py"
    file.write_text(body, encoding="utf-8")
    return str(file)


def test_the_script_sees_only_the_listed_environment_and_runs_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_PLANTED_SECRET", "planted")
    monkeypatch.setenv("CREDENTIAL_TOKEN", "planted")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    work = tmp_path / "work"
    work.mkdir()
    done = isolated.run_script(script(tmp_path), ["--a", "b c"], cwd=str(work), timeout=30, stdin="hello")
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout)
    names = set(seen["env"]) - {"__CF_USER_TEXT_ENCODING"}   # the one name the operating system adds on macOS
    assert names == set(isolated.NAMES)
    assert not [n for n in seen["env"] if n.startswith("WB_") or "CREDENTIAL" in n or n.startswith("PYTHON")]
    assert seen["isolated"] == 1 and seen["argv"] == ["--a", "b c"] and seen["stdin"] == "hello"
    assert os.path.realpath(seen["cwd"]) == os.path.realpath(str(work))
    assert seen["path_has_script_dir"] is False, "an isolated script does not import its neighbours"


def test_home_is_fresh_and_removed_and_the_callers_home_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "real-home"))
    first = json.loads(isolated.run_script(script(tmp_path), [], cwd=str(tmp_path), timeout=30).stdout)
    second = json.loads(isolated.run_script(script(tmp_path), [], cwd=str(tmp_path), timeout=30).stdout)
    assert first["home_exists"] is True
    assert first["home"] != str(tmp_path / "real-home") and first["home"] != second["home"]
    assert first["tmp"].startswith(first["home"])
    assert not os.path.exists(first["home"]), "the temporary HOME is removed after the call"


def test_a_failing_script_is_reported_and_a_slow_one_times_out(tmp_path):
    bad = isolated.run_script(script(tmp_path, "import sys\nprint('no')\nsys.exit(3)\n"), [], cwd=str(tmp_path), timeout=30)
    assert (bad.returncode, bad.stdout.strip()) == (3, "no")
    with pytest.raises(subprocess.TimeoutExpired):
        isolated.run_script(script(tmp_path, "import time\ntime.sleep(30)\n"), [], cwd=str(tmp_path), timeout=0.5)


def test_no_module_of_the_runtime_loads_a_file_of_skills_as_code():
    # What reaches a skill's script goes through runtime/isolated.py: no module here builds a path under skills/ and
    # loads it (spec_from_file_location, import_module, exec, runpy) in its own process.
    for module in sorted(st.RUNTIME.glob("*.py")) + sorted((st.RUNTIME / "handlers").glob("*.py")):
        source = module.read_text(encoding="utf-8")
        for call in re.finditer(r"(?:spec_from_file_location|runpy\.run_path|_load)\(([^\n]*)", source):
            assert '"skills"' not in call.group(1) and "'skills'" not in call.group(1), \
                f"{module.name} loads a file of skills/ as code: {call.group(0)[:80]}"
        assert "task_script" not in source, f"{module.name}: the backlog reader is no longer loaded as a module"


def test_the_path_of_a_skills_script_is_built_in_one_place_and_only_a_file_name_is_taken():
    assert isolated.skill_script("/r", "a-skill", "check.py") == os.path.join("/r", "skills", "a-skill", "scripts", "check.py")
    for bad in ("", "../x.py", "a/b.py", ".hidden", "a\\b.py"):
        with pytest.raises(ValueError):
            isolated.skill_script("/r", "a-skill", bad)
    for module in sorted(st.RUNTIME.glob("*.py")) + sorted((st.RUNTIME / "handlers").glob("*.py")):
        if module.name == "isolated.py":
            continue
        for line in module.read_text(encoding="utf-8").splitlines():
            assert not ('"skills"' in line and '"scripts"' in line and "join" in line), \
                f"{module.name} builds the path of a skill's script itself: {line.strip()[:80]}"
