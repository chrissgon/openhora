"""Tests of the flow schema of P6a (runtime/flow_files.py): step tasks beside skill tasks, parameters bound from a request, the
date variables filled from a clock, the sources a task receives, the template hash a routine will cover, and the project's own
flow files. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_params.py
"""
from __future__ import annotations

import datetime
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
flow_files = importlib.import_module("flow_files")
drop = importlib.import_module("drop")
sources = importlib.import_module("sources")

SHA = "a" * 64


@pytest.fixture
def tree(tmp_path):
    """A checkout with one skill and one workbench flow, and a project beside it."""
    root, project = tmp_path / "tree", tmp_path / "project"
    (root / "skills" / "demo-skill").mkdir(parents=True)
    (root / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\n---\n")
    (root / "flows").mkdir()
    (root / "flows" / "plain.json").write_text(json.dumps(
        {"flow": "plain", "title": "Plain", "tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "do a."}]}))
    project.mkdir()
    return root, project


def write(project, name, data):
    folder = project / "docs" / "workbench" / "flows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(data))


SURVEY = {
    "flow": "survey", "title": "A survey, then its analysis",
    "params": {"topic": {"description": "what the survey is about", "default": "customer churn"},
               "survey": {"description": "the survey export", "type": "file"}},
    "tasks": [
        {"key": "ingest-survey", "step": "ingest", "title": "Bring the {topic} survey in",
         "args": {"source": "survey", "file": "{survey}", "sha256": "{survey.sha256}"}},
        {"key": "analysis", "skill": "demo-skill", "title": "Analysis of {today}", "text": "Analyse the {topic} survey of week {week}.",
         "depends_on": ["ingest-survey"]}]}


def test_the_words_the_schema_shares_with_other_modules_are_the_same():
    assert flow_files.FILE_NAME.pattern == drop.NAME.pattern
    assert flow_files.SOURCE_ID.pattern == sources.SOURCE_ID.pattern
    assert flow_files.INGEST == "ingest"


def test_a_step_task_beside_a_skill_task_is_loaded_with_its_kind_arguments_and_a_text_that_is_its_title(tree):
    root, project = tree
    write(project, "survey", SURVEY)
    flow = flow_files.load("survey", str(root), str(project))
    assert flow["origin"] == "project" and list(flow["params"]) == ["topic", "survey"]
    step = flow["tasks"][0]
    assert step == {"key": "ingest-survey", "step": "ingest", "args": SURVEY["tasks"][0]["args"], "title": "Bring the {topic} survey in",
                    "text": "Bring the {topic} survey in", "depends_on": [], "milestone": False}
    assert "skill" not in step and flow["tasks"][1]["skill"] == "demo-skill"
    assert flow_files.needs_plan(flow) and flow_files.file_params(flow) == ["survey"]


def test_a_workbench_flow_keeps_its_form_and_the_workbench_wins_over_a_project_file_of_the_same_name(tree):
    root, project = tree
    write(project, "plain", {**SURVEY, "flow": "plain"})
    flow = flow_files.load("plain", str(root), str(project))
    assert flow["origin"] == "workbench" and flow["params"] == {} and not flow_files.needs_plan(flow)
    assert flow_files.all_names(str(root), str(project)) == [("plain", "workbench"), ("plain", "project")]
    assert flow_files.all_names(str(root)) == [("plain", "workbench")]
    with pytest.raises(flow_files.FlowError, match="no flow file docs/workbench/flows/missing.json"):
        flow_files.load("missing", str(root), str(project))


@pytest.mark.parametrize("change, word", [
    ({"tasks": [{"key": "a", "skill": "demo-skill", "step": "ingest", "title": "A", "text": "x"}]}, "\"skill\" or \"step\", not both"),
    ({"tasks": [{"key": "a", "step": "ingest", "title": "A", "sources": ["x"]}]}, "a step task has no key 'sources'"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x", "args": {}}]}, "a skill task has no key 'args'"),
    ({"tasks": [{"key": "a", "step": "Bad Kind", "title": "A"}]}, "name of a step kind"),
    ({"tasks": [{"key": "a", "step": "ingest", "title": "A", "args": []}]}, "\"args\" must be an object"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x", "web": True}]}, "only ever false"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x", "sources": ["Bad Id"]}]}, "is not a source id"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "uses {nothing}"}]}, "declares no parameter 'nothing'"),
    ({"params": {"topic": {"description": "t"}}, "tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x"}]},
     "declared and no task uses it"),
    ({"params": {"today": {"description": "t"}}, "tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "{today}"}]},
     "not today or week"),
    ({"params": {"topic": {"description": "t"}}, "tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "{topic.sha256}"}]},
     "only a file parameter has a hash"),
    ({"params": {"f": {"description": "t", "type": "file", "default": "x.csv"}}, "tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "{f}"}]},
     "a file parameter has no default"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "{today.sha256}"}]}, "a date variable has no .sha256"),
])
def test_a_flow_file_with_a_malformed_task_parameter_or_placeholder_is_refused_with_the_problem_named(tree, change, word):
    root, _ = tree
    base = {"flow": "demo", "title": "Demo", "tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x"}]}
    found = flow_files.problems({**base, **change}, "demo", str(root))
    assert any(word in line for line in found), found


def test_bind_fills_parameters_files_and_dates_in_titles_texts_and_arguments_and_reports_what_it_used(tree):
    root, project = tree
    write(project, "survey", SURVEY)
    flow = flow_files.load("survey", str(root), str(project))
    clock = datetime.datetime(2026, 10, 15, 8, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-3), "BRT"))
    got = flow_files.bind(flow, {"survey": "survey.csv"}, clock, {"survey.csv": SHA})
    step, task = got["flow"]["tasks"]
    assert step["args"] == {"source": "survey", "file": "survey.csv", "sha256": SHA}
    assert step["title"] == "Bring the customer churn survey in"          # the default of the parameter
    assert task["title"] == "Analysis of 2026-10-15" and task["text"] == "Analyse the customer churn survey of week 2026-W42."
    assert got["bound"] == {"params": {"topic": "customer churn", "survey": "survey.csv"},
                            "files": {"survey": {"name": "survey.csv", "sha256": SHA}},
                            "dates": {"today": "2026-10-15", "week": "2026-W42", "zone": "BRT (UTC-03:00)"}}
    assert not flow_files.placeholders(got["flow"])
    assert flow["tasks"][0]["args"]["file"] == "{survey}"                  # the template is not changed by binding it


def test_a_parameter_given_replaces_the_default_and_a_title_takes_the_value_on_one_line(tree):
    root, project = tree
    write(project, "survey", SURVEY)
    flow = flow_files.load("survey", str(root), str(project))
    clock = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    got = flow_files.bind(flow, {"survey": "s.csv", "topic": "two\nlines"}, clock, {"s.csv": SHA})
    assert got["flow"]["tasks"][0]["title"] == "Bring the two lines survey in"
    assert got["flow"]["tasks"][1]["text"].startswith("Analyse the two\nlines survey")
    assert got["bound"]["dates"]["zone"] == "UTC+00:00"


@pytest.mark.parametrize("params, files, word", [
    ({"survey": "s.csv", "other": "x"}, {"s.csv": SHA}, "has no parameter other"),
    ({}, {}, "needs a value for survey"),
    ({"survey": "s.csv"}, {}, "no file 's.csv' is handed over"),
    ({"survey": "../s.csv"}, {}, "a file is a plain name"),
    ({"survey": "s.csv", "topic": ""}, {"s.csv": SHA}, "a value is text"),
    ({"survey": "s.csv", "topic": "bad\x00"}, {"s.csv": SHA}, "no control character"),
    ({"survey": "s.csv", "topic": "x" * (flow_files.MAX_PARAM + 1)}, {"s.csv": SHA}, "a value is text"),
])
def test_a_missing_unknown_or_refused_parameter_is_a_flow_error_that_names_it(tree, params, files, word):
    root, project = tree
    write(project, "survey", SURVEY)
    flow = flow_files.load("survey", str(root), str(project))
    with pytest.raises(flow_files.FlowError, match=word):
        flow_files.bind(flow, params, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), files)


def test_the_dates_are_those_of_the_clock_in_its_own_zone_and_a_clock_without_a_zone_is_refused():
    late = datetime.datetime(2026, 12, 31, 23, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
    assert flow_files.dates(late)["today"] == "2026-12-31" and flow_files.dates(late)["week"] == "2026-W53"
    assert flow_files.dates(late.astimezone(datetime.timezone.utc))["today"] == "2027-01-01"
    assert flow_files.dates(datetime.datetime(2027, 1, 3, tzinfo=datetime.timezone.utc))["week"] == "2026-W53"
    assert flow_files.dates(datetime.datetime(2027, 1, 4, tzinfo=datetime.timezone.utc))["week"] == "2027-W01"
    with pytest.raises(ValueError, match="no time zone"):
        flow_files.dates(datetime.datetime(2026, 1, 1))


def test_a_task_receives_the_sources_it_lists_and_those_of_the_ingest_steps_before_it_once_each():
    flow = {"flow": "f", "title": "F", "params": {}, "tasks": [
        {"key": "first", "step": "ingest", "args": {"source": "notes"}, "title": "T", "text": "T", "depends_on": [], "milestone": False},
        {"key": "second", "step": "ingest", "args": {"source": "survey"}, "title": "T", "text": "T", "depends_on": ["first"], "milestone": False},
        {"key": "alone", "skill": "s", "title": "T", "text": "T", "depends_on": [], "milestone": False},
        {"key": "after", "skill": "s", "title": "T", "text": "T", "depends_on": ["second"], "milestone": False, "sources": ["survey", "extra"]},
        {"key": "later", "skill": "s", "title": "T", "text": "T", "depends_on": ["after"], "milestone": False}]}
    assert flow_files.sources_of(flow) == {"alone": [], "after": ["survey", "extra", "notes"], "later": ["survey", "notes"]}


def test_the_template_hash_moves_with_the_workflow_and_never_with_the_title_the_origin_or_the_dates(tree):
    root, project = tree
    write(project, "survey", SURVEY)
    flow = flow_files.load("survey", str(root), str(project))
    first = flow_files.template_sha256(flow)
    assert first == flow_files.template_sha256({**flow, "title": "Another title", "origin": "workbench"})
    clock = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    again = flow_files.bind(flow, {"survey": "s.csv"}, clock, {"s.csv": SHA})["flow"]
    assert flow_files.template_sha256(flow) == first            # binding does not touch the template
    assert flow_files.template_sha256(again) != first           # the filled flow is another thing: only the template is covered
    other = json.loads(json.dumps(flow))
    other["tasks"][1]["text"] += " Be brief."
    assert flow_files.template_sha256(other) != first
    other = json.loads(json.dumps(flow))
    other["params"]["topic"]["default"] = "another topic"
    assert flow_files.template_sha256(other) != first


def test_a_project_flow_that_is_a_link_or_too_large_or_not_json_is_never_read(tree):
    root, project = tree
    folder = project / "docs" / "workbench" / "flows"
    folder.mkdir(parents=True)
    (folder / "big.json").write_text(" " * (flow_files.PROJECT_FILE_BYTES + 1))
    (folder / "bad.json").write_text("{")
    outside = project.parent / "outside.json"
    outside.write_text(json.dumps(SURVEY | {"flow": "linked"}))
    (folder / "linked.json").symlink_to(outside)
    assert flow_files.project_names(str(project)) == ["bad", "big"]          # a link is not listed
    for name, word in (("big", "larger than"), ("bad", "not valid JSON"), ("linked", "no flow file")):
        with pytest.raises(flow_files.FlowError, match=word):
            flow_files.load(name, str(root), str(project))
    other = project.parent / "elsewhere"
    other.mkdir()
    (project / "docs" / "workbench" / "flows").rename(project / "docs" / "workbench" / "moved")
    (project / "docs" / "workbench" / "flows").symlink_to(other)
    assert flow_files.project_names(str(project)) == []
    with pytest.raises(flow_files.FlowError, match="a link out of the project"):
        flow_files.load("survey", str(root), str(project))
