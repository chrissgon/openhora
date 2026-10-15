"""Tests of the workflows in the operations layer (P6a): a project workflow beside the workbench's, the flow check at the moment
it is saved, the code-made split, parameters and dates bound when a plan is made, a file handed over for a request that
reaches the task which reads it, "Save this plan as a workflow", and the task that runs a skill without the web. On the stand-in
tree of standin_tree.py (no model, no container, no network). Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_flows.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

import standin_tree as st
from sources_fixture import standin_convert

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_flows = st.load("ops_flows")
ops_models = st.load("ops_models")
ops_reads = st.load("ops_reads")
plan = st.load("plan")
sources = st.load("sources")
path_rule = st.load("path_rule")
flow_files = st.load("flow_files")
skill_meta = st.load("skill_meta")

CSV = "name,price\napple,1.20\npear,3.10\n"
CLOCK = datetime.datetime(2026, 10, 15, 8, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-3), "BRT"))
LIMITS = {"timeout_seconds": 60, "retries": 2}


def web_skill(tree, name, inputs, outputs):
    """A stand-in skill that requires the web."""
    folder = st.skill(tree, name, inputs, outputs)
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    (folder / "SKILL.md").write_text(text.replace("  requires: []", "  requires: [search:web]"), encoding="utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    web_skill(tree, "demo-web", "docs/workbench/state.md, docs/workbench/research/<topic>.md", "docs/business/web-market.md")
    web_skill(tree, "core-research", "docs/workbench/state.md", "docs/workbench/research/<topic>.md")
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: sorted(p.name for p in (Path(root) / "skills").iterdir()))
    monkeypatch.setattr(ops_flows, "now", lambda: CLOCK)
    current = lab.standing

    def standing(skill):    # the pair was measured with the web, as the real skills that require it are
        found = current(skill)
        found["models"]["m"]["web_measured"] = True
        return found
    monkeypatch.setattr(lab, "standing", standing)
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    built["path"] = project
    built["files"] = tmp_path / "files"
    built["files"].mkdir()
    return built


def write_flow(world, name, data):
    folder = world["project"] / "docs" / "workbench" / "flows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


WEB_WITH_SOURCES = {
    "flow": "survey-web", "title": "A survey, then the market",
    "params": {"topic": {"description": "the market to size"}},
    "tasks": [
        {"key": "ingest-survey", "step": "ingest", "title": "Bring the survey in", "args": {"source": "survey"}},
        {"key": "market", "skill": "demo-web", "title": "Size the market", "text": "Size the {topic} market on {today}.",
         "depends_on": ["ingest-survey"]}]}

FILE_FLOW = {
    "flow": "survey-file", "title": "Ingest a survey file, then read it",
    "params": {"survey": {"description": "the survey export", "type": "file"}},
    "tasks": [
        {"key": "ingest-survey", "step": "ingest", "title": "Bring the survey in",
         "args": {"source": "survey", "file": "{survey}", "sha256": "{survey.sha256}"}},
        {"key": "reading", "skill": "demo-writes", "title": "Read it", "text": "Read the survey.", "depends_on": ["ingest-survey"]}]}


def new_request(world, text="Study the survey."):
    return ops.request(world["path"], text, title="Study")["request"]


def pending(world, pending_id):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_get(ctx["conn"], pending_id)


def csv_file(world, name="survey.csv", text=CSV):
    path = world["files"] / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def tasks_of(world, request):
    ctx = ops_core.context(world["path"])
    return {t["key"]: t for t in ctx["store"].tasks_list(ctx["conn"], request) if t["parent_id"]}


# --- the flow check, the split, and what a saved workflow is -----------------------------------------------------------------------


def test_a_project_workflow_is_listed_beside_the_workbenchs_with_its_check_and_its_parameters(world):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    listed = {f["flow"]: f for f in ops.flows(world["path"])["flows"]}
    assert {"demo", "code-demo", "gate-demo", "survey-web"} <= set(listed)
    mine = listed["survey-web"]
    assert mine["origin"] == "project" and mine["tasks"] == 2 and mine["steps"] == ["ingest"]
    assert mine["params"] == [{"name": "topic", "description": "the market to size", "type": "text", "required": True}]
    assert mine["check"]["ok"] is False and mine["check"]["findings"][0]["task"] == "market"
    assert listed["demo"]["origin"] == "workbench" and listed["demo"]["check"]["ok"] is True
    write_flow(world, "broken", {"flow": "broken", "title": "x", "tasks": []})
    again = {f["flow"]: f for f in ops.flows(world["path"])["flows"]}
    assert again["broken"]["title"] is None and "at least one task" in again["broken"]["error"] and again["demo"]["title"] == "Demo flow"


def test_a_project_workflow_with_the_name_of_a_workbench_flow_is_never_read(world):
    write_flow(world, "demo", {**WEB_WITH_SOURCES, "flow": "demo"})
    both = {f["origin"]: f for f in ops.flows(world["path"])["flows"] if f["flow"] == "demo"}
    assert both["workbench"]["title"] == "Demo flow"          # the workbench's is read
    assert both["project"]["title"] is None and "never read" in both["project"]["error"]
    rid = new_request(world)
    with pytest.raises(ops_core.OpsError, match="never read: rename it"):
        ops.route(world["path"], rid, flow="demo")


def test_ingest_then_a_skill_that_requires_the_web_is_refused_when_saved_with_the_split_offered_and_the_split_passes(world):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    found = ops.check_flow(world["path"], "survey-web")
    assert found["ok"] is False and found["findings"][0]["split"] is True and "flow-save" in found["next"] and "--split" in found["next"]
    with pytest.raises(ops_core.OpsError, match="the flow check refuses this workflow.*requires the web and receives the source survey.*split"):
        ops.flow_save(world["path"], "survey-web-split", flow="survey-web")
    assert not (world["project"] / "docs" / "workbench" / "flows" / "survey-web-split.json").exists()    # nothing was written
    saved = ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)
    assert saved["split"] is True and saved["tasks"] == 3 and saved["path"] == "docs/workbench/flows/survey-web-split.json"
    assert "--param topic=<value>" in saved["next"]
    on_disk = json.loads((world["project"] / "docs" / "workbench" / "flows" / "survey-web-split.json").read_text(encoding="utf-8"))
    assert [t["key"] for t in on_disk["tasks"]] == ["ingest-survey", "market-research", "market"] and on_disk["flow"] == "survey-web-split"
    assert on_disk["tasks"][2]["web"] is False and on_disk["params"]["topic"]["description"] == "the market to size"
    assert hashlib.sha256((world["project"] / saved["path"]).read_bytes()).hexdigest() == saved["sha256"]
    assert ops.check_flow(world["path"], "survey-web-split")["ok"] is True
    with pytest.raises(ops_core.OpsError, match="exists: use replace"):
        ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)
    assert ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True, replace=True)["sha256"] == saved["sha256"]


def test_a_skill_that_reads_no_brief_is_refused_with_a_question_and_a_flow_that_needs_a_name_or_a_source_is_refused_too(world):
    write_flow(world, "bare", {"flow": "bare", "title": "Bare", "tasks": [
        {"key": "ingest-survey", "step": "ingest", "title": "Ingest", "args": {"source": "survey"}},
        {"key": "research", "skill": "core-research", "title": "Research", "text": "Research.", "depends_on": ["ingest-survey"]}]})
    with pytest.raises(ops_core.OpsError, match="Choose one"):
        ops.flow_save(world["path"], "bare-saved", flow="bare", split=True)
    with pytest.raises(ops_core.OpsError, match="a plan"):
        ops.flow_save(world["path"], "x")
    with pytest.raises(ops_core.OpsError, match="a plan .* or a flow"):
        ops.flow_save(world["path"], "x", pending_id=1, flow="bare")
    with pytest.raises(ops_core.OpsError, match="not a flow name"):
        ops.flow_save(world["path"], "Not A Name", flow="bare")
    with pytest.raises(ops_core.OpsError, match="name of a workbench flow"):
        ops.flow_save(world["path"], "demo", flow="bare")
    with pytest.raises(ops_core.OpsError, match="no flow file"):
        ops.check_flow(world["path"], "missing")


def test_a_run_never_writes_the_project_s_workflows_the_path_rule_returns_nothing_from_that_folder():
    for rel in ("docs/workbench/flows/x.json", "docs/workbench/flows/nested/x.md", "docs/workbench/flows"):
        assert path_rule.classify(rel) == "other", rel
    assert path_rule.classify("docs/workbench/flowsx.md") == "document" and path_rule.classify("docs/workbench/runtime.json") == "other"


# --- parameters and dates, bound when a plan is made --------------------------------------------------------------------------------


def test_the_split_workflow_plans_as_a_manual_request_with_a_parameter_bound_the_dates_filled_and_the_hash_covering_them(world):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)
    rid = new_request(world)
    out = ops.route(world["path"], rid, flow="survey-web-split", params=["topic=dental clinics"])
    assert out["routed"] is True and out["source"] == "named" and out["flow"] == "survey-web-split"
    item = pending(world, out["pending_id"])
    tasks = {t["key"]: t for t in item["payload"]["tasks"]}
    assert list(tasks) == ["ingest-survey", "market-research", "market"]
    assert tasks["market"]["text"] == "Size the dental clinics market on 2026-10-15."
    assert tasks["market-research"]["web"] is True and "sources" not in tasks["market-research"]       # the web, no source
    assert tasks["market"]["web"] is False and tasks["market"]["web_off"] is True and tasks["market"]["sources"] == ["survey"]
    assert tasks["ingest-survey"]["agent"] == "runtime" and tasks["market"]["depends_on"] == ["ingest-survey", "market-research"]
    assert item["payload"]["bound"] == {"params": {"topic": "dental clinics"}, "files": {},
                                        "dates": {"today": "2026-10-15", "week": "2026-W42", "zone": "BRT (UTC-03:00)"}}
    body = item["body"]
    assert "Parameter topic: dental clinics" in body and "Dates: today 2026-10-15, week 2026-W42, in the time zone BRT (UTC-03:00)." in body
    assert "Runs without the web although its skill requires it: Size the market." in body
    assert "A task that uses the web receives sources" not in body          # the split cleared what the highlight is for
    stated = item["payload"]["plan_sha256"]
    assert stated == plan.plan_hash(item["payload"]["tasks"])


def test_the_plan_hash_moves_with_the_parameter_and_with_the_date_and_a_missing_or_unknown_parameter_is_refused(world, monkeypatch):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)

    def hash_for(topic, request=None):
        rid = request or new_request(world)
        return pending(world, ops.route(world["path"], rid, flow="survey-web-split", params=[f"topic={topic}"])["pending_id"])["payload"]["plan_sha256"]

    first = hash_for("dental clinics")
    assert hash_for("dental clinics") == first                                 # the same values, the same hash
    assert hash_for("veterinary clinics") != first                             # another parameter, another hash
    monkeypatch.setattr(ops_flows, "now", lambda: CLOCK + datetime.timedelta(days=1))
    assert hash_for("dental clinics") != first                                 # another day: the filled tasks differ
    rid = new_request(world)
    with pytest.raises(ops_core.OpsError, match="needs a value for topic"):
        ops.route(world["path"], rid, flow="survey-web-split")
    with pytest.raises(ops_core.OpsError, match="has no parameter other"):
        ops.route(world["path"], rid, flow="survey-web-split", params=["topic=a", "other=b"])
    with pytest.raises(ops_core.OpsError, match="given twice"):
        ops.route(world["path"], rid, flow="survey-web-split", params=["topic=a", "topic=b"])
    with pytest.raises(ops_core.OpsError, match="not name=value"):
        ops.route(world["path"], rid, flow="survey-web-split", params=["topic"])
    with pytest.raises(ops_core.OpsError, match="has no parameter; it was given topic"):
        ops.route(world["path"], rid, flow="demo", params=["topic=a"])


def test_a_workflow_with_a_parameter_or_a_step_or_of_the_project_is_planned_and_never_started_by_request_at_once(world):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    with pytest.raises(ops_core.OpsError, match="workflow of this project: record the request, then route it"):
        ops.request(world["path"], "go", flow="survey-web")
    assert ops.request(world["path"], "go", flow="demo")["flow"] == "demo"      # the workbench flow of skills with no parameter: as before
    tree = world["tree"]
    (tree / "flows" / "with-step.json").write_text(json.dumps({"flow": "with-step", "title": "With a step", "tasks": [
        {"key": "ingest-survey", "step": "ingest", "title": "Ingest", "args": {"source": "survey"}}]}), encoding="utf-8")
    (tree / "flows" / "with-param.json").write_text(json.dumps({"flow": "with-param", "title": "With a parameter", "params": {
        "topic": {"description": "t", "default": "x"}}, "tasks": [
        {"key": "a", "skill": "demo-writes", "title": "A", "text": "do {topic}."}]}), encoding="utf-8")
    for name in ("with-step", "with-param"):
        with pytest.raises(ops_core.OpsError, match="has parameters, steps, sources or a task that runs without the web: record the request, then route it"):
            ops.request(world["path"], "go", flow=name)
    rid = new_request(world)
    assert ops.route(world["path"], rid, flow="with-param")["routed"] is True       # a default fills the parameter


def test_a_workbench_flow_with_a_placeholder_nobody_filled_cannot_become_a_plan(world):
    tree = world["tree"]
    (tree / "flows" / "with-param.json").write_text(json.dumps({"flow": "with-param", "title": "With a parameter", "params": {
        "topic": {"description": "t", "default": "x"}}, "tasks": [{"key": "a", "skill": "demo-writes", "title": "A", "text": "do {topic}."}]}),
        encoding="utf-8")
    loaded = flow_files.load("with-param", str(tree))
    with pytest.raises(plan.PlanError, match="has parameters or dates to fill \\(topic\\)"):
        plan.from_flow(loaded, str(tree), ["demo-writes"])


# --- a skill that runs without the web its skill requires ---------------------------------------------------------------------------


def test_an_approved_plan_stores_the_word_and_the_run_is_routed_without_the_web_and_supervised_while_the_research_keeps_the_web(world):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)
    rid = new_request(world)
    opened = ops.route(world["path"], rid, flow="survey-web-split", params=["topic=dental clinics"])["pending_id"]
    ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    rows = tasks_of(world, rid)
    assert rows["market"]["web_off"] == 1 and rows["market-research"]["web_off"] is None and rows["ingest-survey"]["web_off"] is None
    ctx = ops_core.context(world["path"])
    for key, skill, web in (("market", "demo-web", False), ("market-research", "core-research", True)):
        declared = skill_meta.declared(os.path.join(str(world["tree"]), "skills", skill))
        routing = ops_models.route(ctx, skill, declared, None, rows[key])
        assert routing["web"] is web, key
    off = ops_models.route(ctx, "demo-web", skill_meta.declared(os.path.join(str(world["tree"]), "skills", "demo-web")), None, rows["market"])
    assert off["autonomy"] == "supervised" and off["proven"] is False
    assert any("without the web its skill requires" in r for r in off["reasons"])
    on = ops_models.route(ctx, "demo-web", skill_meta.declared(os.path.join(str(world["tree"]), "skills", "demo-web")), None,
                          dict(rows["market"], web_off=None))
    assert on["web"] is True and on["autonomy"] == "proven"        # the same skill with the web is the proven pair


def test_a_file_handed_to_a_task_that_runs_without_the_web_says_so_and_a_web_task_says_it_will_be_visible(world):
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    ops.flow_save(world["path"], "survey-web-split", flow="survey-web", split=True)
    rid = new_request(world)
    opened = ops.route(world["path"], rid, flow="survey-web-split", params=["topic=a"])["pending_id"]
    ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    rows = tasks_of(world, rid)
    ctx = ops_core.context(world["path"])
    assert ops_reads.drop_note(rows["market"]) == {"web": False, "takes": True, "line": None}
    assert ops_reads.drop_note(rows["market-research"])["web"] is True
    handed = ops.hand_over(world["path"], rows["market"]["id"], csv_file(world))
    assert "web" not in handed and ctx                                         # no warning about the open network for a task with no web
    other = ops.hand_over(world["path"], rows["market-research"]["id"], csv_file(world, "second.csv"))
    assert other["web"] is True


# --- a file handed over for a request reaches the task that reads it, with its hash ---------------------------------------------------


def test_a_file_parameter_names_the_file_handed_over_and_the_plan_carries_its_hash_then_the_file_moves_into_the_task_that_reads_it(world):
    write_flow(world, "survey-file", FILE_FLOW)
    digest = hashlib.sha256(CSV.encode()).hexdigest()
    rid = new_request(world)
    with pytest.raises(ops_core.OpsError, match="no file 'survey.csv' is handed over for this request"):
        ops.route(world["path"], rid, flow="survey-file", params=["survey=survey.csv"])
    staged = ops.stage_file(world["path"], rid, csv_file(world))
    assert staged["name"] == "survey.csv" and staged["sha256"] == digest and staged["path"] == f".workbench-local/drop/request-{rid}/survey.csv"
    assert "route" in staged["next"] and "--param" in staged["next"]
    opened = ops.route(world["path"], rid, flow="survey-file", params=["survey=survey.csv"])["pending_id"]
    item = pending(world, opened)
    step = next(t for t in item["payload"]["tasks"] if t["key"] == "ingest-survey")
    assert step["args"] == {"source": "survey", "file": "survey.csv", "sha256": digest}           # the hash of exactly that file
    assert item["payload"]["bound"]["files"] == {"survey": {"name": "survey.csv", "sha256": digest}}
    assert f"File survey: survey.csv (sha256 {digest})" in item["body"]
    done = ops.approve(world["path"], opened, item["payload"]["plan_sha256"])
    ingest = tasks_of(world, rid)["ingest-survey"]
    assert done["files"] == {"placed": [{"task": ingest["id"], "file": "survey.csv"}], "failed": []}
    target = world["project"] / ".workbench-local" / "drop" / str(ingest["id"]) / "survey.csv"
    assert target.read_text(encoding="utf-8") == CSV
    assert not (world["project"] / ".workbench-local" / "drop" / f"request-{rid}").exists()       # moved, not copied
    out = ops.run_step(world["path"], ingest["id"])
    assert out["task_state"] == "done" and out["ok"] is True                                   # the step read it, hash and all


def test_a_staged_file_that_changed_before_the_approval_stops_it_and_a_file_taken_away_stops_it_too(world):
    write_flow(world, "survey-file", FILE_FLOW)
    rid = new_request(world)
    ops.stage_file(world["path"], rid, csv_file(world))
    opened = ops.route(world["path"], rid, flow="survey-file", params=["survey=survey.csv"])["pending_id"]
    staged = world["project"] / ".workbench-local" / "drop" / f"request-{rid}" / "survey.csv"
    staged.write_text("name,price\nfig,9.99\n", encoding="utf-8")                              # other bytes than the plan carries
    with pytest.raises(ops_core.OpsError, match="is not the file the plan carries \\(its hash changed\\): nothing was approved"):
        ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])
    assert pending(world, opened)["status"] == "open" and tasks_of(world, rid) == {}              # nothing was created
    staged.unlink()
    with pytest.raises(ops_core.OpsError, match="is not handed over for this request: nothing was approved"):
        ops.approve(world["path"], opened, pending(world, opened)["payload"]["plan_sha256"])


def test_the_staging_folder_takes_a_file_only_for_a_request_that_waits_for_its_plan_and_only_once_by_name(world):
    rid = new_request(world)
    first = csv_file(world)
    ops.stage_file(world["path"], rid, first)
    with pytest.raises(ops_core.OpsError, match="already there: a hand-over never replaces a file"):
        ops.stage_file(world["path"], rid, first)
    with pytest.raises(ops_core.OpsError, match="not a regular file"):
        ops.stage_file(world["path"], rid, str(world["files"]))
    with pytest.raises(ops_core.OpsError, match="credential"):
        ops.stage_file(world["path"], rid, csv_file(world, "keys.txt", "api_key = sk-" + "a1" * 20 + "\n"))
    task_row = tasks_of(world, ops.request(world["path"], "x", flow="demo")["request"])["market"]
    with pytest.raises(ops_core.OpsError, match="is a task: a file is staged for a request"):
        ops.stage_file(world["path"], task_row["id"], first)
    ops.cancel(world["path"], rid)
    with pytest.raises(ops_core.OpsError, match="is cancelled: a file is staged for a request that waits for its plan"):
        ops.stage_file(world["path"], rid, csv_file(world, "again.csv"))


def test_a_plan_made_another_way_that_names_a_file_keeps_the_hand_over_after_the_approval(world):
    flow = {"flow": "x", "title": "X", "tasks": [{"key": "ingest-survey", "step": "ingest", "title": "Ingest", "text": "Ingest.",
                                                  "args": {"source": "survey", "file": "survey.csv", "sha256": "a" * 64}, "depends_on": [], "milestone": False}]}
    ctx = ops_core.context(world["path"])
    rid = new_request(world)
    tasks = plan.from_flow(flow, str(world["tree"]), ["demo-asks"])
    built = plan.build(ctx["store"].task_get(ctx["conn"], rid), tasks, None, "named", LIMITS, [], flow="x")
    opened = ctx["store"].plan_open(ctx["conn"], rid, title=built["title"], body=built["body"], payload=built["payload"])
    done = ops.approve(world["path"], opened["pending_id"], built["payload"]["plan_sha256"])
    assert "files" not in done and tasks_of(world, rid)["ingest-survey"]["state"] == "ready"     # P5's path: hand-over --task, later


# --- "Save this plan as a workflow" --------------------------------------------------------------------------------------------------


def free_text_plan(world, route_skill="demo-asks", sources=None, request_text="Study the dental market, and say what to sell first."):
    """A plan the router would have made from a free-text request (the stand-in route of the tests), opened and approved."""
    ctx = ops_core.context(world["path"])
    request = ops.request(world["path"], request_text, title="Study")["request"]
    row = ctx["store"].task_get(ctx["conn"], request)
    route = {"kind": "route", "line": f"Route: {route_skill} (capability)", "checked": {"ok": True, "skill": route_skill}}
    if sources:
        route["sources"] = {"*": sources}
    routed = [{"item": request_text, "reply": "", "route": route}]
    out = plan.combine(row, routed, {}, {}, str(world["tree"]), pack=[route_skill], limits=LIMITS, past=[])
    opened = ctx["store"].plan_open(ctx["conn"], request, title=out["plan"]["title"], body=out["plan"]["body"], payload=out["plan"]["payload"])
    return request, opened["pending_id"], out


def test_the_approved_free_text_plan_is_saved_as_a_project_workflow_that_passes_the_check_and_plans_again_from_its_name(world):
    request, pid, built = free_text_plan(world)
    with pytest.raises(ops_core.OpsError, match="not an approved plan: approve the plan, then save it"):
        ops.flow_save(world["path"], "dental-study", pending_id=pid)                 # still open: not yet approved by the person
    ops.approve(world["path"], pid, built["plan"]["payload"]["plan_sha256"])
    saved = ops.flow_save(world["path"], "dental-study", pending_id=pid)
    assert saved["split"] is False and saved["params"] == ["request"] and saved["tasks"] == 1
    on_disk = json.loads((world["project"] / saved["path"]).read_text(encoding="utf-8"))
    assert on_disk["params"]["request"]["default"] == "Study the dental market, and say what to sell first."
    assert on_disk["tasks"] == [{"key": "demo-asks", "skill": "demo-asks", "title": "Study", "text": "{request}", "depends_on": [], "milestone": False}]
    assert on_disk["title"] == "Study"
    assert ops.check_flow(world["path"], "dental-study")["ok"] is True
    again = new_request(world, "Again, please.")
    shown = pending(world, ops.route(world["path"], again, flow="dental-study")["pending_id"])
    [task] = shown["payload"]["tasks"]
    assert task["text"] == "Study the dental market, and say what to sell first." and task["skill"] == "demo-asks"      # the default
    other = pending(world, ops.route(world["path"], new_request(world), flow="dental-study",
                                     params=["request=Now the veterinary market."])["pending_id"])
    assert other["payload"]["tasks"][0]["text"] == "Now the veterinary market."
    assert other["payload"]["plan_sha256"] != shown["payload"]["plan_sha256"]
    with pytest.raises(ops_core.OpsError, match="exists: use replace"):
        ops.flow_save(world["path"], "dental-study", pending_id=pid)


def test_a_free_text_plan_keeps_the_highlight_for_a_web_task_with_sources_and_cannot_be_saved_unless_the_code_splits_it(world):
    request, pid, built = free_text_plan(world, route_skill="demo-web", sources=["survey"])
    body = built["plan"]["body"]
    assert "A task that uses the web receives sources" in body and "| Sources |" in body        # manual use: the person decides (D16)
    ops.approve(world["path"], pid, built["plan"]["payload"]["plan_sha256"])
    with pytest.raises(ops_core.OpsError, match="the flow check refuses this workflow.*demo-web.*requires the web and receives the source survey"):
        ops.flow_save(world["path"], "web-study", pending_id=pid)
    saved = ops.flow_save(world["path"], "web-study", pending_id=pid, split=True)
    on_disk = json.loads((world["project"] / saved["path"]).read_text(encoding="utf-8"))
    assert saved["split"] is True and [t["key"] for t in on_disk["tasks"]] == ["demo-web-research", "demo-web"]
    assert on_disk["tasks"][1]["web"] is False and on_disk["tasks"][1]["sources"] == ["survey"]
    ops.source_import(world["path"], "survey", file=csv_file(world))      # a source the plan names must be one the project holds when it runs again
    shown = pending(world, ops.route(world["path"], new_request(world), flow="web-study")["pending_id"])
    assert "A task that uses the web receives sources" not in shown["body"]
