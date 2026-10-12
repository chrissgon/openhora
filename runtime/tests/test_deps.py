"""Tests of runtime/deps.py: a project's dependencies, installed by code in a step that sees only the dependency
files, cached by their content and the image, and copied into a run. Offline: the install is a stand-in `run` that
records its arguments and creates the produced folder (no container, no network); every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_deps.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import standin_tree as st

deps = st.load("deps")

IMAGE = "sha256:" + "4" * 64
SETTINGS = [".h", "h-settings.json"]
PY = {"recipe": "python-requirements", "file": "requirements.txt", "files": ["requirements.txt"]}
NODE = {"recipe": "node-npm", "file": None, "files": ["package.json", "package-lock.json"]}


class Install:
    """A stand-in for lab.run_command: records each call and what the install folder held, and makes the folder
    the recipe produces (with a settings folder and a link inside, as a package could)."""

    def __init__(self, fail=None):
        self.calls, self.seen, self.fail = [], [], fail

    def __call__(self, argv, root, *, cwd=None, network="none", timeout=None):
        self.calls.append({"argv": list(argv), "root": root, "cwd": cwd, "network": network, "timeout": timeout})
        self.seen.append(sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file()))
        if self.fail:
            return {"returncode": 1, "stdout": "", "stderr": "\n".join(f"line {n}" for n in range(30)) + "\n" + self.fail,
                    "timed_out": False}
        produced = Path(cwd) / (".venv" if "venv" in argv or "pip" in argv else "node_modules")
        (produced / "bin").mkdir(parents=True, exist_ok=True)
        (produced / "bin" / "tool").write_text("#!/bin/sh\n")
        (produced / "lib" / ".h").mkdir(parents=True, exist_ok=True)
        (produced / "lib" / ".h" / "settings.json").write_text("{}")
        (produced / "h-settings.json").write_text("{}")
        if not (produced / "outside").exists():
            os.symlink("/", produced / "outside")
        return {"returncode": 0, "stdout": "", "stderr": "", "timed_out": False}


def ensure(tmp_path, entry=PY, files=None, image=IMAGE, run=None):
    files = files if files is not None else [("requirements.txt", b"pytest==9.1.1\n")]
    return deps.ensure(str(tmp_path / "data"), entry, files, image, run=run or Install(), settings=SETTINGS)


def test_the_install_step_sees_only_the_dependency_files(tmp_path):
    run = Install()
    out = ensure(tmp_path, run=run)
    assert [c["argv"] for c in run.calls] == [["python3", "-m", "venv", ".venv"],
                                             [".venv/bin/python", "-m", "pip", "install", "--no-input", "-r",
                                              "requirements.txt"]]
    assert run.seen[0] == ["case/requirements.txt"]  # only the dependency file, in a folder named case
    assert all(c["network"] == "open" and c["timeout"] == deps.INSTALL_TIMEOUT for c in run.calls)
    assert all(Path(c["cwd"]) == Path(c["root"]) / "case" for c in run.calls)
    assert out["cached"] is False and out["produces"] == ".venv"
    assert (Path(out["tree"]) / ".venv" / "bin" / "tool").is_file()
    record = json.loads((tmp_path / "data" / "deps" / out["key"] / "deps.json").read_text())
    assert record["files"] == [{"path": "requirements.txt", "sha256": record["files"][0]["sha256"]}]
    assert record["image_digest"] == IMAGE and record["recipe"] == "python-requirements"
    assert not (tmp_path / "data" / "deps" / f"tmp-{out['key']}").exists()


def test_the_same_dependency_files_are_installed_once_and_a_changed_file_installs_again(tmp_path):
    run = Install()
    first = ensure(tmp_path, run=run)
    again = ensure(tmp_path, run=run)
    assert again["cached"] is True and again["key"] == first["key"] and len(run.calls) == 2
    changed = ensure(tmp_path, files=[("requirements.txt", b"pytest==9.1.2\n")], run=run)
    assert changed["cached"] is False and changed["key"] != first["key"] and len(run.calls) == 4


def test_another_image_installs_again(tmp_path):
    run = Install()
    first = ensure(tmp_path, run=run)
    other = ensure(tmp_path, image="sha256:" + "6" * 64, run=run)
    assert other["cached"] is False and other["key"] != first["key"] and len(run.calls) == 4


def test_a_failed_install_caches_nothing_and_says_why(tmp_path):
    with pytest.raises(deps.DepsError) as failed:
        ensure(tmp_path, run=Install(fail="no matching distribution"))
    assert failed.value.kind == "install" and "no matching distribution" in failed.value.reason
    assert "line 9" not in failed.value.reason and "line 11" in failed.value.reason  # the last 20 lines only
    left = os.listdir(tmp_path / "data" / "deps")
    assert [n for n in left if not n.endswith(".lock")] == []
    timed_out = lambda *a, **k: {"returncode": None, "stdout": "", "stderr": "", "timed_out": True}
    with pytest.raises(deps.DepsError, match="timed out"):
        ensure(tmp_path, run=timed_out)


def test_a_dependency_set_whose_files_are_missing_installs_nothing(tmp_path):
    held = {"package.json": b"{}"}
    assert deps.files_for(NODE, held.get) is None
    held["package-lock.json"] = b"{}"
    assert deps.files_for(NODE, held.get) == [("package.json", b"{}"), ("package-lock.json", b"{}")]


def test_an_unknown_recipe_or_key_in_the_configuration_is_refused():
    assert deps.declared({}) == [] and deps.declared({"raw": {}}) == []
    assert deps.declared({"dependencies": [{"recipe": "python-requirements"}]}) == [
        {"recipe": "python-requirements", "file": "requirements.txt", "files": ["requirements.txt"]}]
    assert deps.declared({"dependencies": [{"recipe": "node-npm"}]})[0]["files"] == ["package.json", "package-lock.json"]
    for bad in ({"dependencies": {"recipe": "node-npm"}}, {"dependencies": ["node-npm"]},
                {"dependencies": [{"recipe": "cargo"}]}, {"dependencies": [{"recipe": "node-npm", "file": "x.json"}]},
                {"dependencies": [{"recipe": "python-requirements", "pin": True}]},
                {"dependencies": [{"recipe": "python-requirements", "file": "../outside.txt"}]},
                {"dependencies": [{"recipe": "python-requirements", "file": "/abs/requirements.txt"}]}):
        with pytest.raises(deps.DepsError) as refused:
            deps.declared(bad)
        assert refused.value.kind == "config"


def test_a_tools_settings_inside_an_installed_folder_are_removed_before_it_is_cached(tmp_path):
    out = ensure(tmp_path)
    tree = Path(out["tree"]) / ".venv"
    assert not (tree / "h-settings.json").exists() and not (tree / "lib" / ".h").exists()
    assert (tree / "bin" / "tool").is_file() and os.path.islink(tree / "outside")  # a link is kept as a link


def test_a_link_where_the_dependency_folder_should_be_is_removed_never_followed(tmp_path):
    out = ensure(tmp_path)
    copy = tmp_path / "copy"
    (copy / ".git" / "info").mkdir(parents=True)
    assert deps.place(out, str(copy)) == ".venv"
    assert (copy / ".venv" / "bin" / "tool").is_file() and os.path.islink(copy / ".venv" / "outside")
    assert "/.venv/" in (copy / ".git" / "info" / "exclude").read_text()
    deps.remove(str(copy), ".venv")
    assert not os.path.lexists(copy / ".venv")
    victim = tmp_path / "victim"
    (victim / "keep").mkdir(parents=True)
    os.symlink(victim, copy / ".venv")
    deps.remove(str(copy), ".venv")
    assert not os.path.lexists(copy / ".venv") and (victim / "keep").is_dir()
    produced = Install()
    produced_link = lambda argv, root, **k: (os.symlink(str(victim), os.path.join(k["cwd"], ".venv"))
                                             if not os.path.lexists(os.path.join(k["cwd"], ".venv")) else None) or {
        "returncode": 0, "stdout": "", "stderr": "", "timed_out": False}
    with pytest.raises(deps.DepsError, match="no folder"):
        ensure(tmp_path, files=[("requirements.txt", b"other\n")], run=produced_link)
    assert (victim / "keep").is_dir() and produced.calls == []
