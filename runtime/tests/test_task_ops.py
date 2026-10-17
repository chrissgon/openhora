"""Tests of the operations layer (runtime/ops.py) and of its terminal shell (runtime/cli.py): a request becomes
two tasks, each runs when it is ready, the person answers and releases, and the documents come back by the
path rule. Offline: a stand-in adapter and two invented skills (runtime/tests/standin_tree.py).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_task_ops.py
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])  # the person accepted the configuration
    return built


def project_of(tree) -> str:
    return str(tree["project"])


def requested(tree) -> dict:
    return ops.request(project_of(tree), "Tell me which market to go after first.", "demo")


def test_a_request_becomes_the_tasks_of_its_flow_file_and_only_the_first_is_ready(tree):
    out = requested(tree)
    assert out["flow"] == "demo" and out["state"] == "planned"
    assert [(t["key"], t["skill"], t["state"]) for t in out["tasks"]] == [("market", "demo-asks", "ready"),
                                                                           ("profile", "demo-writes", "planned")]
    seen = ops.status(project_of(tree))
    assert seen["requests"][0]["title"] == "Demo flow" and len(seen["requests"][0]["tasks"]) == 2 and seen["pending"] == []
    assert len(seen["config"]["sha256"]) == 64


def test_a_done_tasks_payload_lists_the_files_its_run_kept_with_their_reasons_and_the_run_folder(tree):
    """A-30 item 4: the done card shows "kept: n files" and where they are, from the decision's payload, still there
    after the delivery is released."""
    path = project_of(tree)
    task_id = requested(tree)["tasks"][0]["id"]
    first = ops.run_next(path)
    ops.answer(path, first["pending_id"], "Portugal, remote.")
    second = ops.run_next(path)
    ops.release(path, second["pending_id"])
    done = ops.task(path, task_id)
    assert done["task"]["state"] == "done"
    [review] = [p for p in done["pending"] if p["kind"] == "review"]
    assert review["status"] == "resolved" and review["payload"]["run_dir"] == second["run_dir"]
    assert review["payload"]["kept"] == [{"path": "notes.txt", "class": "other", "reason": "this class of path is not brought back yet"}]
    assert [r["path"] for r in review["payload"]["returned"]] == [r["path"] for r in second["returned"]]


def test_the_whole_path_of_a_request_ask_answer_write_release_and_the_next_task(tree):
    project, path = tree["project"], project_of(tree)
    requested(tree)
    # 1. The first run stops to ask: nothing comes back, and the task waits on a question.
    first = ops.run_next(path)
    assert (first["skill"], first["status"], first["ending"], first["task_state"]) == ("demo-asks", "ok", "question", "waiting")
    assert first["returned"] == [] and first["left_out"] == [
        {"path": ".", "reason": "the project is not a git checkout: no versioned file enters"},
        {"path": "docs/workbench/runtime.json", "reason": "the runtime's configuration never enters a run"}]
    assert first["entered"] == {"kind": "general", "agents_md": "whole", "files": 2}  # the state file and AGENTS.md
    item = ops.pending(path, first["pending_id"])
    assert item["kind"] == "question" and item["body"].startswith("Nothing was searched or written yet")
    assert ops.run_next(path)["reason"] == "no task is ready"  # a waiting task does not run
    with pytest.raises(ops.OpsError):
        ops.release(path, first["pending_id"])  # a question is answered, never released
    # 2. The answer makes the task ready; the new run is a fresh copy whose prompt carries the reply and the answer.
    assert ops.answer(path, first["pending_id"], "Portugal, remote.\r\nFree sources only.")["task_state"] == "ready"
    second = ops.run_next(path)
    assert (second["status"], second["ending"], second["task_state"]) == ("ok", "done", "waiting")
    prompt = open(os.path.join(second["run_dir"], "prompt.md"), encoding="utf-8").read()
    assert prompt.startswith("Tell me which market to go after first.\n\nFor this task: do the market analysis.\n")
    assert "--- your reply 1 ---\nNothing was searched or written yet" in prompt
    assert "--- the user's answer 1 ---\nPortugal, remote.\nFree sources only.\n" in prompt and "demo-asks" not in prompt
    # 3. What the run left came back by the path rule: the document, the machine file and the state file; the
    #    file outside docs/ is kept in the run folder and listed.
    assert second["returned"] == [{"path": "docs/business/market.lint.json", "class": "machine"},
                                  {"path": "docs/business/market.md", "class": "document"},
                                  {"path": "docs/workbench/state.md", "class": "state"}]
    assert second["kept"] == [{"path": "notes.txt", "class": "other", "reason": "this class of path is not brought back yet"}]
    assert (project / "docs" / "business" / "market.md").read_text().startswith("# Market analysis")
    assert "decision recorded by demo-asks" in (project / "docs" / "workbench" / "state.md").read_text()
    assert not (project / "notes.txt").exists() and not (project / ".h").exists()
    review = ops.pending(path, second["pending_id"])
    assert review["kind"] == "review" and review["payload"]["ending"] == "done" and review["payload"]["run_dir"] == second["run_dir"]
    # 4. Releasing the delivery finishes the task and makes the next one ready; it reads the document just returned.
    released = ops.release(path, second["pending_id"])
    assert released["task_state"] == "done" and len(released["ready"]) == 1 and released["completed"] == []
    third = ops.run_next(path)
    assert (third["skill"], third["ending"]) == ("demo-writes", "done")
    assert third["returned"] == [{"path": "docs/business/icp.md", "class": "document"}]
    assert (project / "docs" / "business" / "icp.md").is_file()
    assert ops.release(path, third["pending_id"])["completed"] == [1]
    assert [r["state"] for r in ops.status(path)["requests"]] == ["done"]
    assert st.calls(tree["adapter"]) == ["demo-asks 1", "demo-asks 2", "demo-writes 1"]


def test_a_file_that_changed_in_the_project_during_the_run_is_never_overwritten(tree, monkeypatch):
    project, path = tree["project"], project_of(tree)
    requested(tree)
    ops.answer(path, ops.run_next(path)["pending_id"], "here")
    real = lab.run_skill

    def edited_meanwhile(*args, **kwargs):
        result = real(*args, **kwargs)
        (project / "docs" / "workbench" / "state.md").write_text("# Workbench state\n\nedited by the person\n")
        (project / "docs" / "business").mkdir(exist_ok=True)
        (project / "docs" / "business" / "market.md").write_text("written by the person\n")
        return result

    monkeypatch.setattr(lab, "run_skill", edited_meanwhile)
    out = ops.run_next(path)
    # The state file is merged line by line on top of what the person wrote (L10), not kept whole: the person's
    # text stays, and the run's decision has no section to go into.
    assert out["returned"] == [{"path": "docs/business/market.lint.json", "class": "machine"},
                               {"path": "docs/workbench/state.md", "class": "state"}]
    kept = {item["path"]: item["reason"] for item in out["kept"]}
    assert kept["docs/business/market.md"] == "the project's file changed while the run was in progress"
    assert "docs/workbench/state.md" not in kept and out["state"]["accepted"] == 0
    assert [item["reason"] for item in out["state"]["rejected"]] == ["the project's state file has no such section"]
    assert (project / "docs" / "business" / "market.md").read_text() == "written by the person\n"
    assert (project / "docs" / "workbench" / "state.md").read_text().endswith("edited by the person\n")


def test_a_run_that_fails_fails_the_task_and_brings_nothing_back_and_retry_runs_it_again(tree):
    path = project_of(tree)
    requested(tree)
    st.fail(tree["adapter"], "auth", 1)
    out = ops.run_next(path)
    assert (out["status"], out["task_state"], out["failure"]["kind"], out["pending_id"]) == ("failed", "failed", "auth", None)
    task = ops.status(path)["requests"][0]["tasks"][0]
    assert task["state"] == "failed" and "refused the key" in task["note"]
    assert ops.run_next(path)["reason"] == "no task is ready"
    assert ops.retry(path, task["id"])["state"] == "ready"
    assert ops.run_next(path)["ending"] == "question"


def test_a_reply_no_rule_recognises_reaches_the_person_whole_as_unclassified(tree, monkeypatch):
    path = project_of(tree)
    requested(tree)
    real = lab.run_skill

    def odd_reply(*args, **kwargs):
        result = real(*args, **kwargs)
        result["response"] = "I looked around and I am not sure what you want."
        return result

    monkeypatch.setattr(lab, "run_skill", odd_reply)
    out = ops.run_next(path)
    assert (out["ending"], out["task_state"]) == ("unclassified", "waiting")
    item = ops.pending(path, out["pending_id"])
    assert item["kind"] == "review" and item["body"] == "I looked around and I am not sure what you want."
    assert item["payload"]["ending"] == "unclassified"


DRAFT_REPLY = "The analysis is written; OPEN-1 (which segment first) is a close call.\n\nDo you want to settle OPEN-1 now?"


def drafted(tree, monkeypatch) -> dict:
    """The first task asks, is answered, and its second run writes the document and still asks."""
    path = project_of(tree)
    requested(tree)
    ops.answer(path, ops.run_next(path)["pending_id"], "Portugal, remote.")
    real = lab.run_skill

    def still_asks(*args, **kwargs):
        result = real(*args, **kwargs)
        if result["changes"] and result["changes"]["created"]:
            result["response"] = DRAFT_REPLY
        return result

    monkeypatch.setattr(lab, "run_skill", still_asks)
    return ops.run_next(path)


def test_a_draft_with_open_questions_opens_a_review_with_the_whole_reply(tree, monkeypatch):
    out = drafted(tree, monkeypatch)
    assert (out["ending"], out["task_state"]) == ("draft_with_questions", "waiting")
    assert {"path": "docs/business/market.md", "class": "document"} in out["returned"]
    item = ops.pending(project_of(tree), out["pending_id"])
    assert item["kind"] == "review" and item["body"] == DRAFT_REPLY
    assert item["payload"]["ending"] == "draft_with_questions"


def test_the_review_of_a_draft_with_open_questions_is_released_as_it_stands(tree, monkeypatch):
    path = project_of(tree)
    out = drafted(tree, monkeypatch)
    released = ops.release(path, out["pending_id"])
    assert released["task_state"] == "done" and len(released["ready"]) == 1
    tasks = ops.status(path)["requests"][0]["tasks"]
    assert [t["state"] for t in tasks] == ["done", "ready"]
    assert (tree["project"] / "docs" / "business" / "market.md").is_file()


def test_the_review_of_a_draft_with_open_questions_is_answered_and_the_next_run_gets_the_text(tree, monkeypatch):
    path = project_of(tree)
    out = drafted(tree, monkeypatch)
    answered = ops.answer(path, out["pending_id"], "Leave OPEN-1 open.")
    assert answered["task_state"] == "ready" and answered["ready"] == []
    again = ops.run_next(path)
    assert again["skill"] == "demo-asks"
    prompt = open(os.path.join(again["run_dir"], "prompt.md"), encoding="utf-8").read()
    assert "--- your reply 2 ---\n" + DRAFT_REPLY in prompt
    assert "--- the user's answer 2 ---\nLeave OPEN-1 open.\n" in prompt


def test_a_run_that_wrote_nothing_and_asks_still_opens_a_question_that_cannot_be_released(tree):
    path = project_of(tree)
    requested(tree)
    out = ops.run_next(path)
    assert out["ending"] == "question" and ops.pending(path, out["pending_id"])["kind"] == "question"
    with pytest.raises(ops.OpsError):
        ops.release(path, out["pending_id"])
    assert ops.status(path)["requests"][0]["tasks"][0]["state"] == "waiting"


def test_a_task_whose_lock_is_held_is_alive_and_one_whose_lock_is_free_is_ended_at_the_next_run(tree):
    path = project_of(tree)
    requested(tree)
    ctx = ops_core.context(path)
    store = ctx["store"]
    claimed = store.task_claim(ctx["conn"], ctx["conn"].execute(store.NEXT_READY_TASK).fetchone()["id"])["task"]  # a run that began
    held = ops_core._try_lock(ctx["cfg"], f"task-{claimed['id']}.lock")  # its process is alive: it holds the task's lock
    out = ops.run_next(path)
    assert out["recovered"] == [] and out["ran"] is None and st.calls(tree["adapter"]) == []
    assert ops.status(path)["requests"][0]["tasks"][0]["state"] == "running"
    os.close(held)  # the process died: nobody holds the lock
    out = ops.run_next(path)
    assert out["recovered"] == [claimed["id"]] and out["ran"] is None
    assert ops.status(path)["requests"][0]["tasks"][0]["state"] == "failed"


def test_cancelling_a_request_closes_what_is_open_under_it(tree):
    path = project_of(tree)
    request = requested(tree)["request"]
    pending_id = ops.run_next(path)["pending_id"]
    out = ops.cancel(path, request)
    assert out["pending"] == [pending_id] and len(out["cancelled"]) == 3
    assert ops.pending(path) == {"pending": []} and ops.run_next(path)["reason"] == "no task is ready"


def test_a_project_that_is_not_configured_or_names_another_checkout_is_refused(tree, tmp_path):
    with pytest.raises(ops.OpsError) as e:
        ops.status(str(tmp_path / "nowhere"))
    assert e.value.code == 3
    config = tree["project"] / "docs" / "workbench" / "runtime.json"
    good = json.loads(config.read_text())
    for change, word in (({"workbench": str(tmp_path / "other")}, "names the workbench checkout"),
                         ({"data_dir": "relative/data"}, "needs data_dir"),
                         ({"store_db": str(tree["project"] / "docs" / "store.sqlite")}, "inside the project"),
                         ({"data_dir": str(tree["tree"] / "data")}, "inside the workbench checkout")):
        config.write_text(json.dumps({**good, **change}))
        with pytest.raises(ops.OpsError) as e:
            ops.status(project_of(tree))
        assert e.value.code == 3 and word in str(e.value)
    with pytest.raises(ops.OpsError) as e:
        config.write_text(json.dumps(good))
        ops.request(project_of(tree), "x", "no-such-flow")
    assert e.value.code == 2 and "flows/no-such-flow.json" in str(e.value)


def test_the_configuration_is_read_with_its_hash_and_unknown_keys_are_ignored(tmp_path):
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True)
    text = json.dumps({"workbench": str(tmp_path / "wb"), "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "s.sqlite"),
                       "sources_dir": str(tmp_path / "sources"), "agent": "social-manager", "area_agents": {}})
    (project / "docs" / "workbench" / "runtime.json").write_text(text)
    cfg = ops.project_config.load(str(project))
    assert cfg["sha256"] == hashlib.sha256(text.encode()).hexdigest() and cfg["raw"]["agent"] == "social-manager"
    assert cfg["path"].endswith("docs/workbench/runtime.json") and ops.project_config.REL == ops.path_rule.CONFIG
    (project / "docs" / "workbench" / "runtime.json").write_text("[1]")
    with pytest.raises(ops.project_config.ConfigError):
        ops.project_config.load(str(project))


def test_the_runtimes_own_configuration_never_enters_a_run(tree, tmp_path):
    meta = {"inputs": ["docs/workbench/"], "outputs": [], "updates": [], "area": "business"}
    cfg = ops.project_config.load(project_of(tree))
    enter = lambda: ops.workcopy.entering(project_of(tree), meta, web=True, cfg=cfg, settings_names=[],
                                          prepared_dir=str(tmp_path / "prepared"))
    entered = enter()
    assert [rel for _, rel in entered["files"]] == ["docs/workbench/state.md"] and "docs/workbench/runtime.json" not in entered["base"]
    link = tree["project"] / "docs" / "workbench" / "linked.md"
    os.symlink(tree["project"] / "AGENTS.md", link)
    assert [rel for _, rel in enter()["files"]] == ["docs/workbench/state.md"]


def test_the_shell_prints_one_json_object_and_uses_the_documented_exit_codes(tree, capsys, monkeypatch):
    path = project_of(tree)
    assert cli.main(["request", "--project", path, "--flow", "demo", "--text", "Which market first?"]) == 0
    assert json.loads(capsys.readouterr().out)["request"] == 1
    assert cli.main(["run-next", "--project", path]) == 0
    ran = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("From standard input.\n"))
    assert cli.main(["answer", "--project", path, "--id", str(ran["pending_id"]), "--text-file", "-"]) == 0
    capsys.readouterr()
    assert cli.main(["pending", "--project", path, "--id", str(ran["pending_id"])]) == 0
    assert json.loads(capsys.readouterr().out)["answer"] == "From standard input."
    for argv, code in ((["status"], 2), (["frobnicate", "--project", path], 2),
                       (["answer", "--project", path, "--id", "1", "--text", "a", "--text-file", "b"], 2),
                       (["release", "--project", path, "--id", "99"], 1), (["status", "--project", path + "-missing"], 3)):
        assert cli.main(argv) == code, argv
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err.startswith("error: ") and "Traceback" not in captured.err
    assert cli.main(["--help"]) == 0 and "run-next" in capsys.readouterr().out
    # Without --flow a request waits for its route (stage 3): no longer a usage error.
    assert cli.main(["request", "--project", path, "--text", "x"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "requested"


def test_every_script_of_the_runtime_prints_its_help_and_refuses_an_unknown_call():
    for name in ("lab", "ops", "cli", "flow_files", "path_rule", "state_merge", "endings", "project_config", "skill_meta", "service"):
        script = str(st.REPO / "runtime" / f"{name}.py")
        helped = subprocess.run([sys.executable, script, "--help"], capture_output=True, text=True, timeout=60)
        assert helped.returncode == 0 and helped.stdout.strip() and "Traceback" not in helped.stderr, name
        refused = subprocess.run([sys.executable, script, "--no-such-flag-of-this-script"], capture_output=True, text=True, timeout=60)
        assert refused.returncode == 2 and "Traceback" not in refused.stderr, name


def with_dependencies(tree, monkeypatch, fail=False) -> list:
    """The project as a git checkout with a committed requirements file and the set declared in its configuration;
    the install is a stand-in that makes the folder (the real lab.run_command still runs every git command, and the
    script of the change set)."""
    project = tree["project"]
    (project / "requirements.txt").write_text("pytest==9.1.1\n")
    (project / "app.py").write_text("print(1)\n")
    config = project / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    data["dependencies"] = [{"recipe": "python-requirements"}]
    config.write_text(json.dumps(data))
    git = ["git", "-C", str(project), "-c", "user.name=Demo", "-c", "user.email=demo@example.test",
           "-c", "commit.gpgsign=false"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "start"]):
        subprocess.run(git + args, check=True, capture_output=True)
    ops.accept_config(str(project), ops.project_config.load(str(project))["sha256"])
    installs, real = [], lab.run_command

    def run_command(argv, root, **kwargs):
        if argv[0] in ("git", "bash"):  # the base commit, and the difference a change set is taken from
            return real(argv, root, **kwargs)
        installs.append(list(argv))
        if fail:
            return {"returncode": 1, "stdout": "", "stderr": "no matching distribution", "timed_out": False}
        os.makedirs(os.path.join(kwargs["cwd"], ".venv", "bin"), exist_ok=True)
        with open(os.path.join(kwargs["cwd"], ".venv", "bin", "python"), "w") as f:
            f.write("#!/bin/sh\n")
        return {"returncode": 0, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(lab, "run_command", run_command)
    return installs


def test_the_dependency_folder_enters_after_the_base_commit_and_never_comes_back(tree, monkeypatch):
    installs = with_dependencies(tree, monkeypatch)
    project = project_of(tree)
    installed = ops.deps(project)["dependencies"]
    assert [(d["recipe"], d["applies"], d["cached"]) for d in installed] == [("python-requirements", True, False)]
    assert len(installs) == 2 and ops.deps(project)["dependencies"][0]["cached"] is True and len(installs) == 2
    requested(tree)
    out = ops.run_next(project)
    assert out["status"] == "ok" and len(installs) == 2  # the run took the cached folder
    seen = open(os.path.join(out["run_dir"], "outputs", "files.txt")).read().split("\n")
    assert "./.venv/bin/python" in seen and "./app.py" in seen
    cwd = os.path.join(out["run_dir"], "cwd")
    assert not os.path.lexists(os.path.join(cwd, ".venv")) and not os.path.lexists(os.path.join(project, ".venv"))
    committed = lab.run_command(["git", "ls-tree", "-r", "--name-only", "HEAD"], out["run_dir"], cwd=cwd)
    assert ".venv" not in committed["stdout"] and "app.py" in committed["stdout"]  # not in the base commit
    assert "/.venv/" in open(os.path.join(cwd, ".git", "info", "exclude")).read()


def test_a_failed_install_fails_the_run_before_any_model_call(tree, monkeypatch):
    with_dependencies(tree, monkeypatch, fail=True)
    project = project_of(tree)
    requested(tree)
    out = ops.run_next(project)
    assert out["status"] == "failed" and out["failure"]["kind"] == "internal"
    assert out["failure"]["reason"].startswith("dependencies:") and "no matching distribution" in out["failure"]["reason"]
    assert st.calls(tree["adapter"]) == [] and out["task_state"] == "failed"
    with pytest.raises(ops.OpsError, match="no matching distribution"):
        ops.deps(project)


# --- stage 9: what the local service asks of the operations layer -----------------------------------------------------


def open_decision(tree, kind: str) -> int:
    """The id of an open pending decision of this kind, made through the layer's own operations and the store's own
    functions (no stand-in): a plan by routing a request to a flow, an acceptance on a request, and the other kinds as
    the pending decision of a run that ended."""
    path = project_of(tree)
    ctx = ops_core.context(path)
    store, conn = ctx["store"], ctx["conn"]
    if kind == "plan":
        tasks = [{"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do it.", "depends_on": [], "milestone": False}]
        payload = {"tasks": tasks, "plan_sha256": ops.plan.plan_hash(tasks), "flow": "demo"}
        return store.plan_open(conn, ops.request(path, "Plan this.")["request"], title="Plan", body="The plan.",
                               payload=payload)["pending_id"]
    made = ops.request(path, f"A request that waits on a {kind}.", "demo")
    if kind == "acceptance":
        return store.acceptance_open(conn, task_id=made["request"], what="deliveries", title="Accept", body="Accept them.",
                                     payload={})["pending_id"]
    task = made["tasks"][0]["id"]
    assert store.task_claim(conn, task)["task"]["id"] == task
    run = store.task_run_start(conn, task, skill="demo-asks", model="m", adapter="h")["run_id"]
    pending = {"kind": kind, "title": f"A {kind}", "body": "Decide.", "payload": {}}
    return store.task_run_finish(conn, run, status="ok", task_state="waiting", pending=pending)["pending_id"]


EXPECTED_ACTIONS = {"plan": ["approved", "rejected"], "question": ["answered"], "review": ["answered", "released"],
                    "effect": ["approved", "rejected"], "acceptance": ["accepted", "rejected"], "your_document": []}


def test_each_kind_of_pending_decision_lists_the_resolutions_the_store_allows_and_no_other(tree):
    path = project_of(tree)
    ctx = ops_core.context(path)
    store, conn = ctx["store"], ctx["conn"]
    assert set(EXPECTED_ACTIONS) == set(store.PENDING_KINDS)  # a kind the store gains is a kind this test must know
    ids = {kind: open_decision(tree, kind) for kind in store.PENDING_KINDS}
    listed = {item["kind"]: item for item in ops.pending(path)["pending"]}
    assert {kind: item["actions"] for kind, item in listed.items()} == EXPECTED_ACTIONS
    assert {item["kind"]: item["actions"] for item in ops.status(path)["pending"]} == EXPECTED_ACTIONS
    whole = {kind: ops.pending(path, pending_id) for kind, pending_id in ids.items()}
    assert {kind: item["actions"] for kind, item in whole.items()} == EXPECTED_ACTIONS and whole["review"]["body"] == "Decide."
    # Built from the store's own tables: the words of a plan and an acceptance are its KIND_RESOLUTIONS, and every other
    # word comes from RESOLUTIONS or EFFECT_RESOLUTIONS, in the store's order.
    for kind in ("plan", "acceptance"):
        assert listed[kind]["actions"] == [w for (of, w) in store.KIND_RESOLUTIONS if of == kind]
    assert listed["question"]["actions"] == [w for w in store.RESOLUTIONS if w != "released"]
    assert listed["review"]["actions"] == list(store.RESOLUTIONS) and "released" in store.RESOLUTIONS
    assert set(listed["effect"]["actions"]) - {"approved"} <= set(store.EFFECT_RESOLUTIONS)
    # No other: every resolution word the store knows and the decision does not list is refused by the store for that kind
    # (an effect's comment, `answered`, is the one word the store takes that the page does not offer: decision of 2026-10-07).
    words = {*store.RESOLUTIONS, *store.EFFECT_RESOLUTIONS, *(w for _, w in store.KIND_RESOLUTIONS)}
    # (A `your_document` is not in this loop: nothing opens one before stage 10, which also gives it its delivery; the store
    # would take `answered` for it today, and it lists no action until then.)
    for kind in ("question", "review", "effect"):
        for word in sorted(words - set(EXPECTED_ACTIONS[kind]) - ({"answered"} if kind == "effect" else set())):
            fresh = open_decision(tree, kind)
            with pytest.raises(store.StoreError):
                store.pending_resolve(conn, fresh, resolution=word, by="user", answer="x")
            assert store.pending_get(conn, fresh)["status"] == "open", (kind, word)
    for kind, word in (("plan", "answered"), ("plan", "released"), ("acceptance", "approved"), ("acceptance", "answered")):
        with pytest.raises(store.StoreError):
            store.pending_resolve(conn, ids[kind], resolution=word, by="user", answer="x")
    assert ops.approve(path, ids["plan"])["plan_sha256"] == ops.plan.plan_hash(whole["plan"]["payload"]["tasks"]) and ops.answer(path, ids["question"], "Portugal.")["task_state"] == "ready"
    assert ops.release(path, ids["review"])["task_state"] == "done"
    assert ops.approve(path, ids["acceptance"])["task_id"]                      # the page's `accepted` is approve
    # a decision that is resolved lists none, in the task's own list
    resolved = ops.task(path, store.pending_get(conn, ids["question"])["task_id"])["pending"]
    assert [(p["id"], p["status"], p["actions"]) for p in resolved] == [(ids["question"], "resolved", [])]


def test_the_config_operation_reports_the_hash_and_whether_it_was_accepted_and_never_refuses(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    path = str(built["project"])
    digest = ops.project_config.load(path)["sha256"]
    before = ops.config(path)
    assert before == {"path": os.path.join(path, "docs", "workbench", "runtime.json"), "sha256": digest, "accepted": False,
                      "data_dir": str(built["data"]), "messaging": {"senders": {}, "notices": "text", "page_url": None},
                      "channels": {}, "grants": [], "widening": [], "widening_sha256": None, "warnings": []}   # POL-1: the answer also carries the grants of the file, what they widen, its hash and the warnings
    with pytest.raises(ops.OpsError) as refused:
        ops.pending(path)
    assert refused.value.code == 3
    ops.accept_config(path, digest)
    assert ops.config(path) == {**before, "accepted": True}
    with open(before["path"], "ab") as f:
        f.write(b" ")
    assert ops.config(path)["accepted"] is False and ops.config(path)["sha256"] != digest
    # what cannot be read at all is still refused, with the exit code every shell reads as "not configured"
    with pytest.raises(ops.OpsError) as missing:
        ops.config(str(tmp_path / "no-such-folder"))
    assert missing.value.code == 3
    monkeypatch.setattr(ops_core, "ROOT", str(tmp_path))
    with pytest.raises(ops.OpsError) as other:
        ops.config(path)
    assert other.value.code == 3 and "names the workbench checkout" in str(other.value)


def test_the_task_operation_returns_a_task_with_its_runs_and_pending_decisions(tree):
    path = project_of(tree)
    made = requested(tree)
    first = ops.run_next(path)
    request, task = made["request"], made["tasks"][0]["id"]
    found = ops.task(path, task)
    assert set(found) == {"task", "drop", "runs", "pending"} and found["task"]["id"] == task and found["task"]["state"] == "waiting"
    assert [(r["id"], r["status"], r["ending"], r["model"]) for r in found["runs"]] == [(first["run_id"], "ok", "question", "m")]
    assert set(found["runs"][0]) >= {"status", "failure", "ending", "attempts", "duration_ms", "tokens", "cost_usd", "model", "skill_version"}
    assert [(p["id"], p["kind"], p["status"], p["actions"]) for p in found["pending"]] == [(first["pending_id"], "question", "open", ["answered"])]
    ops.answer(path, first["pending_id"], "Portugal.")
    after = ops.task(path, task)
    assert [(p["status"], p["actions"]) for p in after["pending"]] == [("resolved", [])] and after["task"]["state"] == "ready"
    assert ops.task(path, request)["task"]["parent_id"] is None and ops.task(path, request)["runs"] == []   # the request's own
    with pytest.raises(ops.OpsError) as unknown:
        ops.task(path, 9999)
    assert unknown.value.code == 1
    assert cli.run(["task", "--project", path, "--task", str(task)])["task"]["id"] == task


def test_the_flows_operation_lists_the_flow_files_and_a_bad_one_with_its_error(tree):
    path = project_of(tree)
    listed = ops.flows(path)["flows"]
    assert [(f["flow"], f["title"], f["tasks"]) for f in listed] == [
        ("code-demo", "Code demo", 2), ("demo", "Demo flow", 2), ("gate-demo", "Gate demo", 2)] and "error" not in listed[0]
    (tree["tree"] / "flows" / "broken.json").write_text('{"flow": "broken", "title": "Broken", "tasks": []}', encoding="utf-8")
    (tree["tree"] / "flows" / "worse.json").write_text("not json", encoding="utf-8")
    listed = {f["flow"]: f for f in ops.flows(path)["flows"]}
    assert set(listed) == {"broken", "code-demo", "demo", "gate-demo", "worse"} and listed["demo"]["tasks"] == 2
    assert listed["broken"]["title"] is None and listed["broken"]["tasks"] == 0 and "at least one task" in listed["broken"]["error"]
    assert "not valid JSON" in listed["worse"]["error"]
    ops.accept_config  # the configuration check still runs: an unaccepted project is refused
    with open(ops.project_config.path(path), "ab") as f:
        f.write(b" ")
    with pytest.raises(ops.OpsError) as refused:
        ops.flows(path)
    assert refused.value.code == 3


def test_an_effect_is_approved_from_the_terminal_and_the_page_and_from_no_other_channel(tree):
    from test_effects import gate_project, provider_calls
    case = gate_project(tree)
    path, item = case["path"], case["item"]
    for channel in ("chat", "mcp", "web", "", None, "Terminal", "PAGE"):
        with pytest.raises(ops.OpsError, match="an effect is approved in the terminal"):
            ops.approve(path, item["id"], item["payload_sha256"], channel=channel)
    assert provider_calls(tree) == [] and ops.pending(path, item["id"])["status"] == "open"
    with pytest.raises(ops.OpsError, match="--sha256"):
        ops.approve(path, item["id"], None, channel="page")       # the hash is the person's; nothing fills it in
    with pytest.raises(ops.OpsError, match="you typed"):
        ops.approve(path, item["id"], "0" * 64, channel="page")
    assert provider_calls(tree) == []
    out = ops.approve(path, item["id"], item["payload_sha256"], channel="page")
    assert out["pull_request"]["number"] == 7 and [c["argv"][0] for c in provider_calls(tree)].count("open-pr") == 1
    assert ops.EFFECT_CHANNELS == ("terminal", "page")


def test_stop_runs_ends_the_run_this_process_started_and_leaves_nothing_running(tree, monkeypatch):
    import threading
    import time
    path = project_of(tree)
    requested(tree)
    st.fail(tree["adapter"], "timeout", 99)          # the stand-in adapter sleeps 30 s on every call
    result = {}

    def run():
        result["out"] = ops.run_next(path)

    runner = threading.Thread(target=run)
    started = time.monotonic()
    runner.start()
    try:
        deadline = time.monotonic() + 20
        while not st.calls(tree["adapter"]) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert st.calls(tree["adapter"]), "the run did not start"
        assert ops.stop_runs() == {"stopped": True} and ops.stop_runs(path) == {"stopped": True}
        runner.join(20)
        assert not runner.is_alive() and time.monotonic() - started < 25     # it did not wait out the 30 s
    finally:
        lab.LAB.STOPPING.clear()
        runner.join(5)
    assert result["out"]["status"] == "failed"
    assert cli.run(["stop-runs", "--project", path]) == {"stopped": True}
    lab.LAB.STOPPING.clear()
