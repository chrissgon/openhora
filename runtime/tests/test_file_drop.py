"""Tests of the file drop (runtime/drop.py, ops.hand_over, the copy list and the prompt): the stand-in tree and
adapter (standin_tree.py), no container, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_drop.py
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
drop = st.load("drop")
workcopy = st.load("workcopy")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    hand = tmp_path / "hand"
    hand.mkdir()
    return {**built, "hand": hand}


def planned(tree) -> dict:
    out = ops.request(str(tree["project"]), "Find the first market.", flow="demo")
    return {t["key"]: t["id"] for t in out["tasks"]}


def handed_file(tree, name, text="a file made elsewhere\n") -> str:
    path = tree["hand"] / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def seen_by(run: dict) -> list:
    """The files the stand-in adapter found in the run's copy."""
    return (Path(run["run_dir"]) / "outputs" / "files.txt").read_text().split()


def test_a_file_handed_to_a_task_enters_that_tasks_run_and_no_other(tree):
    ids = planned(tree)
    project = str(tree["project"])
    to_market = ops.hand_over(project, ids["market"], handed_file(tree, "logo.svg"))
    to_profile = ops.hand_over(project, ids["profile"], handed_file(tree, "brief.txt"))
    assert to_market["path"] == f".workbench-local/drop/{ids['market']}/logo.svg" and to_market["bytes"] == 22
    asked = ops.run_next(project)
    files = seen_by(asked)
    assert "./" + to_market["path"] in files and "./" + to_profile["path"] not in files
    ops.answer(project, asked["pending_id"], "Clinics in Portugal.")
    ops.release(project, ops.run_next(project)["pending_id"])
    profile = ops.run_next(project)
    assert profile["skill"] == "demo-writes"
    files = seen_by(profile)
    assert "./" + to_profile["path"] in files and "./" + to_market["path"] not in files


def test_the_prompt_lists_the_files_handed_over_and_is_unchanged_without_any(tree):
    answered = [{"body": "Which country?", "answer": "Portugal."}]
    plain = ops.task_prompt("Find the market.", "do it.", answered)
    assert ops.task_prompt("Find the market.", "do it.", answered, handed=[]) == plain
    assert ops.task_prompt("Find the market.", "do it.", answered, handed=None) == plain
    listed = ops.task_prompt("Find the market.", "do it.", answered, handed=[".workbench-local/drop/2/logo.svg"])
    assert listed.startswith("Find the market.\n\nFor this task: do it.\n\nThe user handed over these files for this "
                             "task. They are in the project at:\n- .workbench-local/drop/2/logo.svg\n\nIn an earlier run")
    assert listed.replace("The user handed over these files for this task. They are in the project at:\n"
                          "- .workbench-local/drop/2/logo.svg\n\n", "") == plain


def test_what_a_run_leaves_in_the_drop_never_comes_back(tree, tmp_path):
    ids = planned(tree)
    project = str(tree["project"])
    rel = ops.hand_over(project, ids["market"], handed_file(tree, "logo.svg"))["path"]
    original = (tree["project"] / rel).read_bytes()
    cwd = tmp_path / "copy"
    for name, text in ((rel, "changed by the run\n"), (f".workbench-local/drop/{ids['market']}/new.txt", "new\n"),
                       ("docs/business/market.md", "# Market\n")):
        (cwd / name).parent.mkdir(parents=True, exist_ok=True)
        (cwd / name).write_text(text, encoding="utf-8")
    result = {"cwd": str(cwd), "staged": [], "changes": {
        "created": [f".workbench-local/drop/{ids['market']}/new.txt", "docs/business/market.md"],
        "modified": [rel], "deleted": [], "unchanged": []}}
    returned, kept, _state = workcopy.returning(project, result, {}, None, "demo-asks")
    assert returned == [{"path": "docs/business/market.md", "class": "document"}] and kept == []
    assert (tree["project"] / rel).read_bytes() == original
    assert not (tree["project"] / ".workbench-local" / "drop" / str(ids["market"]) / "new.txt").exists()


def test_a_link_a_folder_a_large_file_and_a_bad_name_are_refused(tree, monkeypatch):
    ids = planned(tree)
    project = str(tree["project"])
    target = handed_file(tree, "real.txt")
    os.symlink(target, tree["hand"] / "link.txt")
    (tree["hand"] / "folder").mkdir()
    refusals = {
        "link": str(tree["hand"] / "link.txt"),
        "folder": str(tree["hand"] / "folder"),
        "name": handed_file(tree, "has space.txt"),
        "dot": handed_file(tree, ".hidden"),
    }
    for why, source in refusals.items():
        with pytest.raises(ops.OpsError) as refused:
            ops.hand_over(project, ids["market"], source)
        assert ("link or not a regular file" if why in ("link", "folder") else "is refused") in str(refused.value), why
    monkeypatch.setattr(drop, "MAX_BYTES", 10)
    with pytest.raises(ops.OpsError) as refused:
        ops.hand_over(project, ids["market"], handed_file(tree, "large.txt", "x" * 11))
    assert "larger than 10" in str(refused.value)
    monkeypatch.setattr(drop, "MAX_BYTES", 25 * 1024 * 1024)
    s = ops_core.context(project)
    s["store"].request_cancel(s["conn"], next(iter(s["store"].tasks_list(s["conn"])))["id"], by="user")
    with pytest.raises(ops.OpsError) as refused:
        ops.hand_over(project, ids["market"], target)
    assert "is cancelled" in str(refused.value)
    assert not (tree["project"] / ".workbench-local" / "drop").exists()


def test_a_file_that_holds_a_credential_is_refused(tree):
    ids = planned(tree)
    token = "AKIA" + "Q" * 16  # a text in a credential's format, built at run time
    with pytest.raises(ops.OpsError) as refused:
        ops.hand_over(str(tree["project"]), ids["market"], handed_file(tree, "keys.txt", f"key {token}\n"))
    assert "holds what looks like a credential" in str(refused.value) and token not in str(refused.value)
    assert drop.files(str(tree["project"]), ids["market"]) == []


def test_a_second_file_of_the_same_name_is_refused(tree):
    ids = planned(tree)
    project = str(tree["project"])
    first = ops.hand_over(project, ids["market"], handed_file(tree, "logo.svg", "first\n"))
    with pytest.raises(ops.OpsError) as refused:
        ops.hand_over(project, ids["market"], handed_file(tree, "logo.svg", "second\n"))
    assert "never replaces a file" in str(refused.value)
    assert (tree["project"] / first["path"]).read_text() == "first\n"
    assert ops.hand_over(project, ids["profile"], handed_file(tree, "logo.svg"))["task"] == ids["profile"]


def web_task(tree) -> int:
    st.skill(tree["tree"], "demo-web", "docs/workbench/state.md", "docs/business/web.md")
    skill_md = tree["tree"] / "skills" / "demo-web" / "SKILL.md"
    skill_md.write_text(skill_md.read_text().replace("requires: []", "requires: [search:web]"), encoding="utf-8")
    (tree["tree"] / "flows" / "web.json").write_text(json.dumps({"flow": "web", "title": "Web", "tasks": [
        {"key": "look", "skill": "demo-web", "title": "Look", "text": "look it up."}]}), encoding="utf-8")
    return ops.request(str(tree["project"]), "Look it up.", flow="web")["tasks"][0]["id"]


def test_a_web_task_takes_a_hand_over_and_the_answer_carries_the_web_line(tree):
    """A-30 (the maintainer's decision of 2026-10-09): the file is the person's own choice, so a web task takes it; the
    answer says so, and `task` tells the page before the send."""
    assert drop.WEB_TASK_TAKES_DROP is True
    project = str(tree["project"])
    task_id = web_task(tree)
    assert ops.task(project, task_id)["drop"] == {"web": True, "takes": True, "line": drop.WEB_LINE}
    allowed = ops.hand_over(project, task_id, handed_file(tree, "logo.svg"))
    assert allowed["web"] is True and allowed["note"] == "this file will be visible to a run with the open network"
    assert [rel for _source, rel in drop.files(project, task_id)] == [allowed["path"]]
    plain = planned(tree)["market"]
    assert ops.task(project, plain)["drop"] == {"web": False, "takes": True, "line": None}
    assert "web" not in ops.hand_over(project, plain, handed_file(tree, "other.svg"))
    assert ops.task(project, ops.task(project, plain)["task"]["parent_id"])["drop"] is None  # a request takes no file


def test_a_web_task_refuses_a_hand_over_when_the_constant_is_set_false(tree, monkeypatch):
    monkeypatch.setattr(drop, "WEB_TASK_TAKES_DROP", False)
    project = str(tree["project"])
    task_id = web_task(tree)
    assert ops.task(project, task_id)["drop"] == {"web": True, "takes": False, "line": None}
    with pytest.raises(ops.OpsError) as refused:
        ops.hand_over(project, task_id, handed_file(tree, "logo.svg"))
    assert str(refused.value) == drop.WEB_REFUSAL and drop.files(project, task_id) == []


def test_a_hand_over_is_refused_in_a_git_repository_that_does_not_ignore_the_drop_and_allowed_in_a_folder_that_is_no_repository(tree):
    ids = planned(tree)
    project = str(tree["project"])
    assert ops.hand_over(project, ids["market"], handed_file(tree, "first.txt"))["task"] == ids["market"]
    subprocess.run(["git", "init", "-q", project], check=True)
    with pytest.raises(ops.OpsError) as refused:
        ops.hand_over(project, ids["market"], handed_file(tree, "second.txt"))
    assert "add .workbench-local/ to .gitignore" in str(refused.value)
    (tree["project"] / ".gitignore").write_text(".workbench-local/\n", encoding="utf-8")
    assert ops.hand_over(project, ids["market"], handed_file(tree, "second.txt"))["task"] == ids["market"]
