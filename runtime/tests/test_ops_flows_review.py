"""Tests added after the review of P6a: the case of the paths a run may not write, a workflow with sources or `web: false` that is never
started at once, an approval that never fails after it is committed, the staging folder cleaned, the sources a bound flow names checked,
a kind that brings a source in, the write of a workflow on a poor disk, and a file parameter that survives "Save this plan as a workflow".
On the stand-in tree of standin_tree.py. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_flows_review.py
"""
from __future__ import annotations

import errno
import json
import os

import pytest

import standin_tree as st
from test_ops_flows import (CSV, FILE_FLOW, WEB_WITH_SOURCES, csv_file, new_request, ops, ops_core, ops_flows, pending, plan,  # noqa: F401
                            tasks_of, world, write_flow)
from test_protected_paths import CHECKS, copy_of
from test_protected_paths import tree as protected_tree  # noqa: F401
from test_run_limits import base_of, finished
from test_run_limits import tree as limits_tree  # noqa: F401

changeset = st.load("changeset")
flow_files = st.load("flow_files")
path_rule = st.load("path_rule")
steps = st.load("steps")
workcopy = st.load("workcopy")


# --- major 1: the case of a path ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("rel", ["docs/workbench/Flows/evil.json", "DOCS/WORKBENCH/FLOWS/evil.json", "docs/workbench/fLoWs", "docs/workbench/Runtime.json",
                                 "docs/workbench/RUNTIME.JSON"])
def test_a_path_of_the_workflows_or_the_configuration_in_any_case_is_class_other(rel):
    assert path_rule.classify(rel) == "other"
    assert path_rule.classify(rel, {"versioned": [rel]}) == "other"        # a versioned folder does not change it


def test_what_a_run_leaves_in_the_workflows_folder_under_another_case_is_not_returned(limits_tree):
    tree = limits_tree
    left = {"docs/workbench/Flows/evil.json": "{}\n", "docs/business/icp.md": "# Profile\n"}
    result = finished(tree, left, created=list(left))
    returned, kept, _ = workcopy.returning(str(tree["project"]), result, base_of(tree, *left), None, "demo-writes", cfg={})
    assert [r["path"] for r in returned] == ["docs/business/icp.md"]
    assert [k["path"] for k in kept] == ["docs/workbench/Flows/evil.json"]
    assert not (tree["project"] / "docs" / "workbench" / "flows").exists() or not any((tree["project"] / "docs" / "workbench" / "flows").iterdir())


def test_the_change_set_never_carries_a_workflow_under_another_case(protected_tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {"README.md": "x\n"})
    (run_dir / "cwd" / "docs" / "workbench" / "Flows").mkdir(parents=True)
    (run_dir / "cwd" / "docs" / "workbench" / "Flows" / "evil.json").write_text("{}\n")
    (run_dir / "cwd" / "README.md").write_text("y\n")
    made = changeset.compute(str(run_dir), base, ["README.md"], {}, CHECKS)
    assert [f["path"] for f in made["files"]] == ["README.md"] and "docs/workbench/Flows/evil.json" not in made["versioned"]
    with pytest.raises(changeset.ChangesetError, match="not a versioned path"):
        changeset.verify_for_commit({"files": [{"path": "docs/workbench/Flows/evil.json"}], "removed": []},
                                    {"versioned": ["docs/workbench/Flows/evil.json"]}, ())


# --- major 2: a workflow with sources or `web: false` is planned -----------------------------------------------------------------------


def test_a_workflow_that_lists_sources_or_says_web_false_is_never_started_by_request_at_once(world):
    tree = world["tree"]
    research = {"key": "research", "skill": "core-research", "title": "Research", "text": "Research."}
    split_form = {"flow": "split-form", "title": "Split", "tasks": [
        research, {"key": "market", "skill": "demo-web", "title": "Market", "text": "Size it.", "depends_on": ["research"],
                   "sources": ["survey"], "web": False}]}
    failing_form = {"flow": "failing-form", "title": "Failing", "tasks": [
        {"key": "market", "skill": "demo-web", "title": "Market", "text": "Size it.", "sources": ["survey"]}]}
    web_only = {"flow": "web-only", "title": "Web off", "tasks": [{"key": "market", "skill": "demo-web", "title": "Market", "text": "Size it.", "web": False}]}
    for data in (split_form, failing_form, web_only):
        (tree / "flows" / f"{data['flow']}.json").write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ops_core.OpsError, match="sources or a task that runs without the web: record the request, then route it"):
            ops.request(world["path"], "go", flow=data["flow"])
    assert ops_core.context(world["path"])["store"].tasks_list(ops_core.context(world["path"])["conn"]) == []     # nothing was created
    ops.source_import(world["path"], "survey", file=csv_file(world))          # the sources a flow lists are checked when its plan is built
    rid = new_request(world)
    shown = pending(world, ops.route(world["path"], rid, flow="split-form")["pending_id"])
    tasks = {t["key"]: t for t in shown["payload"]["tasks"]}
    assert tasks["market"]["web_off"] is True and tasks["market"]["sources"] == ["survey"] and tasks["market"]["web"] is False
    failing = pending(world, ops.route(world["path"], new_request(world), flow="failing-form")["pending_id"])
    assert "A task that uses the web receives sources" in failing["body"]        # the D16 highlight, for the person to decide


def test_a_workbench_flow_shadowed_by_a_project_file_is_refused_by_request_as_by_route(world):
    write_flow(world, "demo", {**WEB_WITH_SOURCES, "flow": "demo"})
    with pytest.raises(ops_core.OpsError, match="never read: rename it"):
        ops.request(world["path"], "go", flow="demo")


def test_route_with_a_parameter_and_no_flow_is_a_usage_error(world):
    rid = new_request(world)
    with pytest.raises(ops_core.OpsError, match="name the flow") as refused:
        ops.route(world["path"], rid, params=["topic=a"])
    assert refused.value.code == 2


# --- minor 1 and 2: the approval never fails after it is committed; the staging folder is cleaned -----------------------------------------


def staging(world, rid):
    return world["project"] / ".workbench-local" / "drop" / f"request-{rid}"


def planned_file_flow(world, name="survey.csv", text=CSV):
    write_flow(world, "survey-file", FILE_FLOW)
    rid = new_request(world)
    ops.stage_file(world["path"], rid, csv_file(world, name, text))
    opened = ops.route(world["path"], rid, flow="survey-file", params=[f"survey={name}"])["pending_id"]
    return rid, opened


def test_a_staged_file_that_cannot_be_read_after_the_approval_is_reported_and_the_approval_stands(world, monkeypatch):
    rid, opened = planned_file_flow(world)
    real, calls = ops_flows.staged, []

    def staged(project, request_id):
        calls.append(request_id)
        if len(calls) > 1:       # the check before the approval passed; the read after it finds the file gone
            raise ops_core.OpsError("survey.csv is not a regular file of at most 26214400 bytes", 1)
        return real(project, request_id)
    monkeypatch.setattr(ops_flows, "staged", staged)
    done = ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    ingest = tasks_of(world, rid)["ingest-survey"]["id"]
    [failed] = done["files"]["failed"]
    assert done["files"]["placed"] == [] and failed["task"] == ingest and failed["file"] == "survey.csv" and failed["reason"] == "OpsError"
    assert "hand-over" in failed["next"] and f"--task {ingest}" in failed["next"]
    assert set(tasks_of(world, rid)) == {"ingest-survey", "reading"} and pending(world, opened)["status"] == "resolved"
    assert not staging(world, rid).exists()


def test_the_staging_folder_goes_with_a_rejected_plan_a_cancelled_request_and_what_the_plan_does_not_name(world):
    write_flow(world, "survey-file", FILE_FLOW)
    # a rejected plan
    rid = new_request(world)
    ops.stage_file(world["path"], rid, csv_file(world, "a.csv"))
    opened = ops.route(world["path"], rid, flow="demo")["pending_id"]
    assert staging(world, rid).is_dir()
    ops.reject(world["path"], opened)
    assert not staging(world, rid).exists()
    # a cancelled request
    rid = new_request(world)
    ops.stage_file(world["path"], rid, csv_file(world, "b.csv"))
    ops.cancel(world["path"], rid)
    assert not staging(world, rid).exists()
    # an approval of a plan that names no file
    rid = new_request(world)
    ops.stage_file(world["path"], rid, csv_file(world, "c.csv"))
    opened = ops.route(world["path"], rid, flow="demo")["pending_id"]
    done = ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    assert "files" not in done and not staging(world, rid).exists()
    # an approval of a plan that names one file of two
    rid = new_request(world)
    ops.stage_file(world["path"], rid, csv_file(world, "survey.csv"))
    ops.stage_file(world["path"], rid, csv_file(world, "extra.csv", "x,y\n1,2\n"))
    opened = ops.route(world["path"], rid, flow="survey-file", params=["survey=survey.csv"])["pending_id"]
    done = ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    ingest = tasks_of(world, rid)["ingest-survey"]
    assert done["files"]["placed"] == [{"task": ingest["id"], "file": "survey.csv"}]
    assert not staging(world, rid).exists()
    assert not (world["project"] / ".workbench-local" / "drop" / str(ingest["id"]) / "extra.csv").exists()


# --- minor 3: the sources a bound flow names are source ids the project holds, or ones a step brings in ---------------------------------------


SOURCE_FLOW = {"flow": "by-source", "title": "By source", "params": {"src": {"description": "a source id"}}, "tasks": [
    {"key": "reading", "skill": "demo-writes", "title": "Read", "text": "Read it.", "sources": ["{src}"]}]}


def test_a_source_a_parameter_fills_must_be_an_id_the_project_holds_or_one_a_step_of_the_flow_brings_in(world):
    write_flow(world, "by-source", SOURCE_FLOW)
    with pytest.raises(ops_core.OpsError, match="not a source id"):
        ops.route(world["path"], new_request(world), flow="by-source", params=["src=Bad Id"])
    with pytest.raises(ops_core.OpsError, match="the project does not hold"):
        ops.route(world["path"], new_request(world), flow="by-source", params=["src=survey"])
    ops.source_import(world["path"], "survey", file=csv_file(world))
    shown = pending(world, ops.route(world["path"], new_request(world), flow="by-source", params=["src=survey"])["pending_id"])
    assert shown["payload"]["tasks"][0]["sources"] == ["survey"]
    brought = {**SOURCE_FLOW, "flow": "brought", "tasks": [
        {"key": "ingest-notes", "step": "ingest", "title": "Ingest", "args": {"source": "{src}"}},
        {"key": "reading", "skill": "demo-writes", "title": "Read", "text": "Read it.", "depends_on": ["ingest-notes"], "sources": ["{src}"]}]}
    write_flow(world, "brought", brought)
    assert ops.route(world["path"], new_request(world), flow="brought", params=["src=notes"])["routed"] is True


# --- minor 4: a kind that brings a source in ---------------------------------------------------------------------------------------------


def test_only_a_kind_that_declares_it_brings_a_source_in_and_sources_of_reads_the_kinds_it_is_given():
    assert steps.sourcing_kinds() == ("ingest",)
    flow = {"flow": "f", "title": "F", "params": {}, "tasks": [
        {"key": "pull", "step": "pull-notes", "args": {"source": "notes"}, "title": "T", "text": "T", "depends_on": [], "milestone": False},
        {"key": "read", "skill": "s", "title": "T", "text": "T", "depends_on": ["pull"], "milestone": False}]}
    assert flow_files.sources_of(flow) == {"read": []}                              # the default is today's only kind
    assert flow_files.sources_of(flow, ("pull-notes",)) == {"read": ["notes"]}
    assert flow_files.sources_of(flow, steps.sourcing_kinds()) == {"read": []}


# --- minor 5: the write of a workflow --------------------------------------------------------------------------------------------------


def saved_flow(world):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    return ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)


def test_a_stale_temporary_file_is_no_obstacle_and_a_disk_without_hard_links_still_saves(world, monkeypatch):
    folder = world["project"] / "docs" / "workbench" / "flows"
    folder.mkdir(parents=True)
    (folder / f".survey-web-split.{os.getpid()}.tmp").write_text("left by a dead process")
    first = saved_flow(world)
    assert (world["project"] / first["path"]).is_file()
    (world["project"] / first["path"]).unlink()

    def no_links(*args, **kwargs):
        raise OSError(errno.EPERM, "no hard links here")
    monkeypatch.setattr(os, "link", no_links)
    again = ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)
    assert (world["project"] / again["path"]).is_file() and again["sha256"] == first["sha256"]
    with pytest.raises(ops_core.OpsError, match="exists: use replace"):
        ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)
    assert ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True, replace=True)["sha256"] == first["sha256"]


def test_a_disk_that_refuses_the_write_is_an_ops_error_not_an_oserror(world, monkeypatch):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)

    def refuse(*args, **kwargs):
        raise OSError(errno.ENOSPC, "no space")
    monkeypatch.setattr(ops_flows.tempfile, "mkstemp", refuse)
    with pytest.raises(ops_core.OpsError, match="could not be written: OSError"):
        ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)


# --- minor 8 and 9: the request's words, and a file parameter kept ----------------------------------------------------------------------


def test_the_requests_words_with_windows_line_ends_become_the_default_with_plain_ones(world):
    request = ops.request(world["path"], "Study the market.\r\nThen the next one.", title="Study")["request"]
    ctx = ops_core.context(world["path"])
    row = ctx["store"].task_get(ctx["conn"], request)
    route = {"kind": "route", "line": "Route: demo-asks (capability)", "checked": {"ok": True, "skill": "demo-asks"}}
    out = plan.combine(row, [{"item": "x", "reply": "", "route": route}], {}, {}, str(world["tree"]), pack=["demo-asks"],
                       limits={"timeout_seconds": 60, "retries": 2}, past=[])
    opened = ctx["store"].plan_open(ctx["conn"], request, title=out["plan"]["title"], body=out["plan"]["body"], payload=out["plan"]["payload"])
    ops.approve(world["path"], opened["pending_id"], out["plan"]["payload"]["plan_sha256"])
    saved = ops.flow_save(world["path"], "two-lines", pending_id=opened["pending_id"])
    default = json.loads((world["project"] / saved["path"]).read_text(encoding="utf-8"))["params"]["request"]["default"]
    assert default == "Study the market.\nThen the next one." and "\r" not in default


def test_a_plan_built_with_a_file_parameter_is_saved_with_the_parameter_and_runs_again_with_another_file(world):
    rid, opened = planned_file_flow(world)
    ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    saved = ops.flow_save(world["path"], "survey-again", pending_id=opened)
    on_disk = json.loads((world["project"] / saved["path"]).read_text(encoding="utf-8"))
    assert on_disk["params"] == {"survey": {"description": "a file of yours, handed over for the request (stage-file)", "type": "file"}}
    step = next(t for t in on_disk["tasks"] if t["key"] == "ingest-survey")
    assert step["args"] == {"source": "survey", "file": "{survey}", "sha256": "{survey.sha256}"}
    assert "survey.csv" not in json.dumps(on_disk) and flow_files.file_params(flow_files.load("survey-again", str(world["tree"]), str(world["project"]))) == ["survey"]
    other = "name,price\nfig,9.99\n"
    again = new_request(world)
    ops.stage_file(world["path"], again, csv_file(world, "other.csv", other))
    shown = pending(world, ops.route(world["path"], again, flow="survey-again", params=["survey=other.csv"])["pending_id"])
    args = next(t for t in shown["payload"]["tasks"] if t["key"] == "ingest-survey")["args"]
    import hashlib
    assert args == {"source": "survey", "file": "other.csv", "sha256": hashlib.sha256(other.encode()).hexdigest()}


# --- the four minors of the review of P6a ---------------------------------------------------------------------------------------------------


def test_a_flow_with_no_parameter_and_no_date_still_has_its_sources_checked_when_it_is_routed(world):
    write_flow(world, "plain-source", {"flow": "plain-source", "title": "Plain", "tasks": [
        {"key": "reading", "skill": "demo-writes", "title": "Read", "text": "Read it.", "sources": ["survey"]}]})
    with pytest.raises(ops_core.OpsError, match="receives the source survey, which the project does not hold"):
        ops.route(world["path"], new_request(world), flow="plain-source")
    ops.source_import(world["path"], "survey", file=csv_file(world))
    assert ops.route(world["path"], new_request(world), flow="plain-source")["routed"] is True


def test_saving_a_plan_rewrites_only_the_file_and_sha256_arguments_of_a_kind_that_brings_a_source(world):
    flow = json.loads(json.dumps(FILE_FLOW))
    flow["tasks"][0]["args"] = {"source": "survey", "file": "{survey}", "sha256": "{survey.sha256}"}
    write_flow(world, "survey-file", flow)
    rid = new_request(world)
    ops.stage_file(world["path"], rid, csv_file(world, "survey", CSV))          # a file whose name is also the source's id
    opened = ops.route(world["path"], rid, flow="survey-file", params=["survey=survey"])["pending_id"]
    ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    saved = ops.flow_save(world["path"], "kept", pending_id=opened)
    step = next(t for t in json.loads((world["project"] / saved["path"]).read_text(encoding="utf-8"))["tasks"] if t["key"] == "ingest-survey")
    assert step["args"] == {"source": "survey", "file": "{survey}", "sha256": "{survey.sha256}"}, "`source` stays the source, though it equals the name"
    mixed = ops_flows._with_file_parameters("other-kind", {"file": "survey"}, {"survey": {"name": "survey", "sha256": "a" * 64}})
    assert mixed == {"file": "survey"}, "a kind that brings no source keeps its arguments"


def test_the_staging_folder_that_is_a_link_is_looked_at_before_it_is_listed_and_nothing_behind_it_is_touched(world, tmp_path):
    rid = new_request(world)
    behind = tmp_path / "behind"
    behind.mkdir()
    (behind / "keep.txt").write_text("mine")
    folder = world["project"] / ".workbench-local" / "drop" / f"request-{rid}"
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.symlink_to(behind)
    ops_flows.discard_staged(ops_core.context(world["path"]), rid)
    assert (behind / "keep.txt").read_text() == "mine" and folder.is_symlink()


def test_a_failed_placement_names_the_command_that_hands_the_file_to_the_task(world, monkeypatch):
    rid, opened = planned_file_flow(world)
    monkeypatch.setattr(ops_flows.drop, "write_new", lambda *a, **k: (_ for _ in ()).throw(OSError("full")))   # the disk is full
    done = ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    [failed] = done["files"]["failed"]
    ingest = tasks_of(world, rid)["ingest-survey"]["id"]
    assert failed["task"] == ingest and failed["reason"] == "OSError"
    assert "hand-over" in failed["next"] and f"--task {ingest}" in failed["next"] and "<path>" in failed["next"]
