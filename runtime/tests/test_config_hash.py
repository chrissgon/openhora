"""Tests of the configuration's hash (runtime/ops.py, runtime/project_config.py): no operation runs on a
docs/workbench/runtime.json the person did not accept by its hash, and only accept_config records that hash.
Offline: the stand-in tree (runtime/tests/standin_tree.py).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_config_hash.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")
project_config = st.load("project_config")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """The stand-in tree and project, with a configuration nobody accepted yet."""
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def sha(tree) -> str:
    return project_config.load(str(tree["project"]))["sha256"]


def refused(call, *needles) -> None:
    with pytest.raises(ops.OpsError) as raised:
        call()
    assert raised.value.code == 3, str(raised.value)
    for needle in needles:
        assert needle in str(raised.value)


def test_no_operation_runs_before_the_person_accepted_the_configuration(tree):
    path, digest = str(tree["project"]), sha(tree)
    for call in (lambda: ops.request(path, "Tell me which market to go after first.", "demo"),
                 lambda: ops.run_next(path), lambda: ops.pending(path), lambda: ops.pending(path, 1),
                 lambda: ops.answer(path, 1, "yes"), lambda: ops.release(path, 1), lambda: ops.retry(path, 1),
                 lambda: ops.cancel(path, 1), lambda: ops.status(path)):
        refused(call, digest, "accept-config", "none: no configuration was accepted yet")
    assert st.calls(tree["adapter"]) == []


def test_accepting_takes_the_hash_the_person_typed_and_refuses_another(tree):
    path, digest = str(tree["project"]), sha(tree)
    with pytest.raises(ops.OpsError) as raised:
        ops.accept_config(path, "0" * 64)
    assert raised.value.code == 1 and "nothing was accepted" in str(raised.value)
    refused(lambda: ops.status(path), "none: no configuration was accepted yet")
    out = ops.accept_config(path, digest)
    assert (out["accepted"], out["previous"]) == (digest, None) and out["path"].endswith("docs/workbench/runtime.json")
    assert ops.status(path)["config"]["sha256"] == digest


def test_a_configuration_that_changed_after_it_was_accepted_stops_every_operation_and_names_both_hashes(tree):
    path, old = str(tree["project"]), sha(tree)
    ops.accept_config(path, old)
    with open(project_config.path(path), "ab") as f:
        f.write(b" ")
    new = sha(tree)
    assert new != old
    refused(lambda: ops.status(path), old, new)
    refused(lambda: ops.request(path, "x", "demo"), old, new)
    assert ops.accept_config(path, new)["previous"] == old
    assert ops.status(path)["config"]["sha256"] == new


def test_the_shell_exposes_accept_config_and_exits_3_on_a_configuration_that_was_not_accepted(tree, capsys):
    path, digest = str(tree["project"]), sha(tree)
    assert cli.main(["status", "--project", path]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and digest in captured.err and "accept-config" in captured.err
    assert cli.main(["accept-config", "--project", path, "--sha256", digest]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] == digest
    assert cli.main(["status", "--project", path]) == 0
    assert json.loads(capsys.readouterr().out)["config"]["sha256"] == digest
    assert cli.main(["accept-config", "--project", path]) == 2  # --sha256 is required


def test_protected_paths_is_a_list_of_globs_or_absent(tree):
    path = str(tree["project"])
    file = project_config.path(path)
    good = json.loads(open(file, encoding="utf-8").read())
    assert project_config.load(path)["protected_paths"] == []
    with open(file, "w", encoding="utf-8") as f:
        json.dump({**good, "protected_paths": ["AGENTS.md", "docs/legal/*"]}, f)
    assert project_config.load(path)["protected_paths"] == ["AGENTS.md", "docs/legal/*"]
    for bad in ("AGENTS.md", ["AGENTS.md", ""], [1]):
        with open(file, "w", encoding="utf-8") as f:
            json.dump({**good, "protected_paths": bad}, f)
        with pytest.raises(project_config.ConfigError) as raised:
            project_config.load(path)
        assert "protected_paths must be a list of path globs" in str(raised.value)


def write_config(tree, **extra) -> str:
    path = str(tree["project"])
    file = project_config.path(path)
    good = json.loads(open(file, encoding="utf-8").read())
    with open(file, "w", encoding="utf-8") as f:
        json.dump({**good, **extra}, f)
    return path


def test_an_unknown_key_is_refused_with_the_nearest_known_name(tree, capsys):
    path = write_config(tree, protected_path=["AGENTS.md"])
    with pytest.raises(project_config.ConfigError) as raised:
        project_config.load(path)
    assert "'protected_path'" in str(raised.value) and "did you mean protected_paths?" in str(raised.value)
    assert cli.main(["status", "--project", path]) == 3  # exit 3, as every ConfigError
    captured = capsys.readouterr()
    assert captured.out == "" and "did you mean protected_paths?" in captured.err
    assert not tree["db"].exists()  # no operation ran: the store was never opened
    write_config(tree, protected_path=None, zzzzzzzz=1)
    with pytest.raises(project_config.ConfigError) as raised:
        project_config.load(path)
    assert "'protected_path'" in str(raised.value)  # the first unknown key, in sorted order
    file = project_config.path(path)
    clean = {k: v for k, v in json.loads(open(file, encoding="utf-8").read()).items()
             if k not in ("protected_path", "zzzzzzzz")}
    with open(file, "w", encoding="utf-8") as f:
        json.dump({**clean, "qqqqqqqqqqqq": 1}, f)
    with pytest.raises(project_config.ConfigError) as raised:
        project_config.load(path)
    assert "did you mean" not in str(raised.value)  # no near match, no hint


def test_the_first_runtimes_keys_stay_valid_in_the_same_file(tree):
    path = write_config(tree, agent="a", harness="h", mailbox="none", publisher="p", vote={"repo": "o/r"})
    assert project_config.load(path)["workbench"]


def test_every_key_the_first_runtime_reads_is_known():
    import re
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    DERIVED = {"paths", "providers", "limits", "_redact"}  # set by the loader of scripts/runtime.py itself
    known = set(project_config.FIRST_RUNTIME_KEYS) | set(project_config.TASK_RUNTIME_KEYS) | DERIVED
    pattern = re.compile(r'\bcfg(?:\[|\.get\()\s*"([A-Za-z_]+)"')
    found = set()
    for name in ("runtime.py", "runtime_vote.py", "vote_job.py"):
        found |= set(pattern.findall((scripts / name).read_text(encoding="utf-8")))
    assert found, "the scan found no key: the pattern is stale"
    assert found <= known, f"read from the file but not in the key tuples: {sorted(found - known)}"


def test_model_prices_is_a_known_key_and_a_misspelling_of_it_is_refused_with_its_name(tree):
    assert "model_prices" in project_config.TASK_RUNTIME_KEYS and "model_prices" not in project_config.FIRST_RUNTIME_KEYS
    path = write_config(tree, model_price={})
    with pytest.raises(project_config.ConfigError) as raised:
        project_config.load(path)
    assert "'model_price'" in str(raised.value) and "did you mean model_prices?" in str(raised.value)
    file = project_config.path(path)
    clean = {k: v for k, v in json.loads(open(file, encoding="utf-8").read()).items() if k != "model_price"}
    with open(file, "w", encoding="utf-8") as f:
        json.dump({**clean, "model_prices": {}}, f)
    assert project_config.load(path)["model_prices"] == {}
