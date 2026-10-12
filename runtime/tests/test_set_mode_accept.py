"""Tests of `set-mode --accept` (R4-C3, the maintainer's word, A-62): one terminal command sets a wider mode and accepts
the hash it makes, on one condition checked under the configuration lock (the configuration was the accepted one before
the change, so the only difference accepted is this mode). The rule it keeps (principle 11): a change that widens what
an agent may do is accepted only by the person, in the terminal; a page, the conversation and the MCP mode can never
pass `accept`. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_set_mode_accept.py
"""
from __future__ import annotations

import ast
import fcntl
import json
import os
import shlex
import threading
import types

import pytest

import standin_tree as st
from test_autonomy import tree  # noqa: F401  (planning supervised, brand autonomous; the configuration accepted)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_config = st.load("ops_config")
operations = st.load("operations")
project_config = st.load("project_config")
cli = st.load("cli")


def config_path(tree):
    return tree["project"] / "docs" / "workbench" / "runtime.json"


def cursor(tree, name):
    ctx = ops_core.context(str(tree["project"]), check_config=False)
    return ctx["store"].cursor_get(ctx["conn"], name)


def modes(tree):
    raw = json.loads(config_path(tree).read_text(encoding="utf-8"))
    return {k: v["mode"] for k, v in raw["area_agents"].items()}


def edit_by_hand(tree):
    """Another change of the file that nobody accepted: a cap raised."""
    raw = json.loads(config_path(tree).read_text(encoding="utf-8"))
    raw["area_agents"]["brand"]["max_runs_per_day"] = 99
    config_path(tree).write_text(json.dumps(raw), encoding="utf-8")


def service_world(tree, monkeypatch):
    monkeypatch.setenv("WORKBENCH_STARTED_WITH_UV", "0")
    import test_service as ts
    project = str(tree["project"])
    projects = [{"id": ts.service.project_id(project), "name": "p", "path": project}]
    return ts, types.SimpleNamespace(svc=ts.service.Service(ops, projects, ts.TOKEN, ts.PORT, None, log=lambda line: None),
                                     projects=projects)


# --- the operation, from the terminal --------------------------------------------------------------------------------


def test_a_wider_mode_with_accept_is_set_and_accepted_by_the_person_in_one_step(tree):
    project = str(tree["project"])
    before = cursor(tree, project_config.ACCEPTED)
    out = ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")
    after = project_config.load(project)
    assert out["accepted"] is True and out["by"] == "person" and out["next"] is None
    assert out["agent"] == "planning" and out["mode"] == "milestones" and out["config_sha256"] == after["sha256"]
    assert out["checkpoints"] == {"written": True, "value": "milestones"}
    assert modes(tree) == {"planning": "milestones", "brand": "autonomous"}  # only that word changed
    assert cursor(tree, project_config.ACCEPTED) == after["sha256"] != before
    assert cursor(tree, ops_config.ACCEPTED_BY) == "person"
    assert ops.status(project)["config"]["sha256"] == after["sha256"]  # nothing refuses afterwards
    assert ops.config(project)["accepted"] is True


def test_a_wider_mode_without_accept_still_leaves_the_hash_unaccepted(tree):
    project = str(tree["project"])
    before = cursor(tree, project_config.ACCEPTED)
    out = ops.set_mode(project, "planning", "milestones", channel="terminal")
    assert out["accepted"] is False and out["by"] is None and "accept-config" in out["next"]
    assert cursor(tree, project_config.ACCEPTED) == before
    with pytest.raises(ops.OpsError) as refused:
        ops.status(project)
    assert refused.value.code == 3


def test_accept_on_a_configuration_with_another_unaccepted_change_refuses_and_writes_nothing(tree):
    project = str(tree["project"])
    edit_by_hand(tree)
    file_before = config_path(tree).read_text(encoding="utf-8")
    accepted_before = cursor(tree, project_config.ACCEPTED)
    by_before = cursor(tree, ops_config.ACCEPTED_BY)
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")
    assert refused.value.code == 3 and "accept-config" in str(refused.value)  # read the file, then accept-config
    assert config_path(tree).read_text(encoding="utf-8") == file_before  # the mode was not even written
    assert cursor(tree, project_config.ACCEPTED) == accepted_before
    assert cursor(tree, ops_config.ACCEPTED_BY) == by_before


def test_accept_finds_a_file_changed_between_the_read_and_the_lock_and_accepts_nothing(tree, monkeypatch):
    project = str(tree["project"])
    real = ops_core.context

    def context(p, **kw):
        out = real(p, **kw)
        edit_by_hand(tree)  # after the configuration was read as the accepted one, before the lock is taken
        return out

    accepted = cursor(tree, project_config.ACCEPTED)
    monkeypatch.setattr(ops_core, "context", context)
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")
    assert refused.value.code == 1 and "changed" in str(refused.value)
    monkeypatch.setattr(ops_core, "context", real)
    assert cursor(tree, project_config.ACCEPTED) == accepted
    assert modes(tree)["planning"] == "supervised"


def test_accept_does_not_accept_a_file_edited_between_the_write_and_the_read_back(tree, monkeypatch):
    project = str(tree["project"])
    real = project_config.load
    calls = {"n": 0}

    def load(path):
        calls["n"] += 1
        if calls["n"] == 3:  # 1: context, 2: under the lock, 3: the read after the write
            edit_by_hand(tree)
        return real(path)

    accepted = cursor(tree, project_config.ACCEPTED)
    monkeypatch.setattr(ops.project_config, "load", load)
    out = ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")
    assert out["accepted"] is False and out["by"] is None and "accept-config" in out["next"]
    assert cursor(tree, project_config.ACCEPTED) == accepted


def test_a_narrowing_with_accept_behaves_as_today_and_code_accepts_it(tree):
    project = str(tree["project"])
    out = ops.set_mode(project, "brand", "supervised", accept=True, channel="terminal")
    assert out["accepted"] is True and out["by"] == "code:narrowing" and out["next"] is None
    assert cursor(tree, ops_config.ACCEPTED_BY) == "code:narrowing"


def test_the_same_mode_with_accept_changes_nothing(tree):
    project = str(tree["project"])
    file_before = config_path(tree).read_text(encoding="utf-8")
    out = ops.set_mode(project, "brand", "autonomous", accept=True, channel="terminal")
    assert out["unchanged"] is True and out["accepted"] is True and out["by"] is None
    assert config_path(tree).read_text(encoding="utf-8") == file_before


def test_the_command_line_sets_and_accepts(tree, capsys):
    project = str(tree["project"])
    assert cli.main(["set-mode", "--project", project, "--agent", "planning", "--mode", "milestones", "--accept"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True and out["by"] == "person"
    assert ops.config(project)["accepted"] is True
    edit_by_hand(tree)
    assert cli.main(["set-mode", "--project", project, "--agent", "planning", "--mode", "autonomous", "--accept"]) == 3


def test_the_terminal_help_names_the_option(capsys):
    assert cli.main(["--help"]) == 0
    helped = capsys.readouterr().out
    assert "set-mode --project <dir> --agent <name> --mode" in helped and "[--accept]" in helped
    assert "only when the file was the accepted one before the change" in helped
    row = operations.by_name("set-mode")
    assert {"name": "accept", "kind": "flag"} in [dict(a) for a in row["args"]]


# --- no other channel can pass accept ---------------------------------------------------------------------------------


@pytest.mark.parametrize("channel", [None, "page", "chat", "mcp", "elsewhere"])
def test_any_channel_but_the_terminal_is_refused_when_it_passes_accept(tree, channel):
    project = str(tree["project"])
    file_before = config_path(tree).read_text(encoding="utf-8")
    accepted = cursor(tree, project_config.ACCEPTED)
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(project, "planning", "milestones", accept=True, channel=channel)
    assert refused.value.code == 2 and "terminal" in str(refused.value)
    assert config_path(tree).read_text(encoding="utf-8") == file_before and cursor(tree, project_config.ACCEPTED) == accepted


def test_a_page_call_with_an_accept_field_is_refused_and_a_page_widening_stays_unaccepted(tree, monkeypatch):
    ts, world = service_world(tree, monkeypatch)
    file_before = config_path(tree).read_text(encoding="utf-8")
    accepted = cursor(tree, project_config.ACCEPTED)
    for value in (True, "true", 1, "--accept"):
        status, _, body = ts.call(world, "POST", ts.api(world, "/agents/planning/mode"), {"mode": "milestones", "accept": value})
        assert status == 400 and body["error"] == "usage" and "accept" in body["message"]
    assert config_path(tree).read_text(encoding="utf-8") == file_before and cursor(tree, project_config.ACCEPTED) == accepted
    # the same call without the field is the page's widening: written, and the hash stays unaccepted
    status, _, body = ts.call(world, "POST", ts.api(world, "/agents/planning/mode"), {"mode": "milestones"})
    assert status == 200 and body["accepted"] is False and body["by"] is None and "accept-config" in body["next"]
    assert cursor(tree, project_config.ACCEPTED) == accepted != project_config.load(str(tree["project"]))["sha256"]
    assert ts.call(world, "GET", ts.api(world, "/status"))[0] == 412


def test_no_route_of_the_service_takes_accept_and_no_other_shell_lists_set_mode(tree):
    service = st.load("service")
    routes = [r for r in service.ROUTES if r["op"] == "set-mode"]
    assert len(routes) == 1
    route, row = routes[0], operations.by_name("set-mode")
    allowed = [a["name"] for a in row["args"] if a["name"] not in route["bind"] and (route["take"] is None or a["name"] in route["take"])]
    assert allowed == ["mode"], allowed  # accept is not in the binding of the page
    assert tuple(row["channels"]) == ("terminal", "page") and row.get("channel_arg") is True
    assert "set-mode" not in {r["name"] for r in operations.OPERATIONS if "mcp" in r["channels"] or "chat" in r["channels"]}


# --- the command the page copies ---------------------------------------------------------------------------------------


def test_the_wider_commands_the_page_shows_carry_accept_and_work_in_one_step(tree, capsys, monkeypatch):
    monkeypatch.setenv("WORKBENCH_STARTED_WITH_UV", "0")
    project = str(tree["project"])
    agent = next(a for a in ops.agents(project)["agents"] if a["name"] == "planning")
    assert agent["wider"], agent
    for w in agent["wider"]:
        assert w["command"].endswith(f"--mode {w['mode']} --accept"), w
    wider = next(w for w in agent["wider"] if w["mode"] == "milestones")
    argv = shlex.split(wider["command"])
    argv = argv[argv.index("set-mode"):]  # past `python3 <checkout>/runtime/cli.py`
    assert "--accept" in argv
    assert cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["accepted"] is True and out["by"] == "person" and ops.config(project)["accepted"] is True


def test_the_command_a_widening_returns_when_it_is_not_accepted_is_still_accept_config(tree):
    out = ops.set_mode(str(tree["project"]), "planning", "milestones", channel="page")
    assert out["next"].split(" cli.py ")[-1].startswith("accept-config") or "cli.py accept-config" in out["next"]
    assert "--accept" not in out["next"]


# --- two at once never overlap -----------------------------------------------------------------------------------------


def test_two_set_modes_with_accept_at_once_never_accept_a_stale_copy(tree, monkeypatch):
    """B loads the accepted configuration; A widens planning with accept and finishes; B then asks to widen brand. B
    must not write its copy (it would drop A's word and have the person's flag accept the result): it finds the file
    moved under the lock and writes nothing."""
    project = str(tree["project"])
    real = ops_core.context
    state = {"n": 0}

    def context(p, **kw):
        out = real(p, **kw)
        state["n"] += 1
        if state["n"] == 1:
            monkeypatch.setattr(ops_core, "context", real)
            a = ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")
            assert a["accepted"] is True and a["by"] == "person"
            monkeypatch.setattr(ops_core, "context", context)
        return out

    monkeypatch.setattr(ops_core, "context", context)
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(project, "brand", "autonomous-with-policy", accept=True, channel="terminal")
    assert refused.value.code == 1 and "changed" in str(refused.value)
    monkeypatch.setattr(ops_core, "context", real)
    assert modes(tree) == {"planning": "milestones", "brand": "autonomous"}  # A's change stands, B wrote nothing
    assert cursor(tree, project_config.ACCEPTED) == project_config.load(project)["sha256"]


def test_set_mode_with_accept_takes_the_configuration_lock_and_gives_up_when_another_holds_it(tree, monkeypatch):
    project = str(tree["project"])
    cfg = project_config.load(project)
    monkeypatch.setattr(ops_core, "CONFIG_LOCK_WAIT", 0.2)
    fd = os.open(os.path.join(cfg["data_dir"], ops_core.CONFIG_LOCK_NAME), os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    file_before = config_path(tree).read_text(encoding="utf-8")
    try:
        with pytest.raises(ops.OpsError, match="in progress"):
            ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")
    finally:
        os.close(fd)
    assert config_path(tree).read_text(encoding="utf-8") == file_before
    assert ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")["accepted"] is True


def test_threads_that_widen_with_accept_at_the_same_time_leave_one_consistent_accepted_file(tree):
    project = str(tree["project"])
    results = []

    def widen(agent, mode):
        try:
            results.append(ops.set_mode(project, agent, mode, accept=True, channel="terminal"))
        except ops.OpsError as e:
            results.append(e)

    threads = [threading.Thread(target=widen, args=a) for a in (("planning", "milestones"), ("brand", "autonomous-with-policy"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == 2
    done = [r for r in results if isinstance(r, dict)]
    assert done and all(r["accepted"] is True and r["by"] == "person" for r in done)
    assert cursor(tree, project_config.ACCEPTED) == project_config.load(project)["sha256"]  # whatever the order, the file is accepted
    for r in results:
        if isinstance(r, ops.OpsError):
            assert r.code in (1, 3)  # the loser was refused and wrote nothing: 3 when it read the file while the winner held it


# --- the writer of the accepted hash, structurally ----------------------------------------------------------------------


def test_the_person_s_flag_reaches_the_acceptance_only_through_the_terminal_channel_and_the_condition():
    tree_ = ast.parse((st.RUNTIME / "ops_config.py").read_text(encoding="utf-8"))
    assigned = {t.id: n.value for n in tree_.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert ast.unparse(assigned["ACCEPT_CHANNELS"]) == "('terminal',)"
    function = next(f for f in tree_.body if isinstance(f, ast.FunctionDef) and f.name == "set_mode")
    body = [n for n in function.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    first = body[0]  # the refusal of a channel but the terminal is the first statement, before anything is read
    assert isinstance(first, ast.If) and ast.unparse(first.test) == "accept and channel not in ACCEPT_CHANNELS"
    assert isinstance(first.body[0], ast.Raise) and "2" in ast.unparse(first.body[0])
    calls = [n for n in ast.walk(function) if isinstance(n, ast.Call) and ast.unparse(n.func) == "_record_acceptance"]
    assert len(calls) == 1  # one call, under the one test that says who may be accepted
    guards = [n for n in ast.walk(function) if isinstance(n, ast.If) and calls[0] in list(ast.walk(n))]
    assert "narrowing or accept" in [ast.unparse(g.test) for g in guards]
    assert "narrowing = autonomy.narrows(old, mode)" in [ast.unparse(n) for n in ast.walk(function) if isinstance(n, ast.Assign)]
    callers = sorted(f.name for f in ast.walk(tree_) if isinstance(f, ast.FunctionDef)
                     for n in ast.walk(f) if isinstance(n, ast.Call) and ast.unparse(n.func) == "_record_acceptance")
    assert callers == ["accept_config", "set_mode"], callers


def test_a_file_edited_between_the_replace_and_the_hash_is_not_accepted(tree, monkeypatch):
    """The hash accepted is the hash of the bytes this call wrote, taken before the file is replaced: an edit that
    lands right after the replace (before anything reads the file back) must not be accepted as the person's act."""
    project = str(tree["project"])
    real = ops_config.os.replace
    done = {"edited": False}

    def replace(src, dst, *a, **kw):
        real(src, dst, *a, **kw)
        if dst == str(config_path(tree)) and not done["edited"]:
            done["edited"] = True
            edit_by_hand(tree)  # the file changes at once after the replace

    accepted = cursor(tree, project_config.ACCEPTED)
    by = cursor(tree, ops_config.ACCEPTED_BY)
    monkeypatch.setattr(ops_config.os, "replace", replace)
    out = ops.set_mode(project, "planning", "milestones", accept=True, channel="terminal")
    monkeypatch.setattr(ops_config.os, "replace", real)
    assert done["edited"] is True
    assert out["accepted"] is False and out["by"] is None and "accept-config" in out["next"]
    assert out["config_sha256"] == project_config.load(project)["sha256"] and out["config_sha256"] in out["next"]
    assert cursor(tree, project_config.ACCEPTED) == accepted and cursor(tree, ops_config.ACCEPTED_BY) == by


def test_the_hash_set_mode_accepts_is_the_hash_of_the_bytes_it_wrote(tree):
    out = ops.set_mode(str(tree["project"]), "planning", "milestones", accept=True, channel="terminal")
    import hashlib
    assert out["config_sha256"] == hashlib.sha256(config_path(tree).read_bytes()).hexdigest()


def test_no_module_but_ops_config_calls_record_acceptance():
    """The writer of the accepted hash is private to ops_config.py: any call whose name ends in record_acceptance, in a
    module of the runtime, its handlers or the scripts, fails here unless it is in ops_config.py."""
    found = []
    for folder in (st.RUNTIME, st.RUNTIME / "handlers", st.REPO / "scripts"):
        for path in sorted(folder.glob("*.py")):
            if path.name == "ops_config.py" and folder == st.RUNTIME:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("record_acceptance"):
                    found.append(f"{folder.name}/{path.name}:{node.lineno}")
    assert found == [], found
