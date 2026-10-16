"""Tests of the flow files (flows/<name>.json, runtime/flow_files.py) and of what the runtime reads from a
skill's frontmatter (runtime/skill_meta.py). Offline; every name outside this repository's own is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_files.py
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
flow_files = importlib.import_module("flow_files")
skill_meta = importlib.import_module("skill_meta")


def test_the_flow_file_of_this_repository_is_well_formed_and_names_built_skills():
    flow = flow_files.load("market-positioning")
    assert [(t["key"], t["skill"], t["depends_on"], t["milestone"]) for t in flow["tasks"]] == [
        ("market", "biz-market-analysis", [], False), ("positioning", "biz-icp-positioning", ["market"], True)]
    assert "market-positioning" in flow_files.names()


def flow(tmp_path, data, name="demo"):
    (tmp_path / "flows").mkdir(exist_ok=True)
    (tmp_path / "skills" / "demo-skill").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\n---\n")
    (tmp_path / "flows" / f"{name}.json").write_text(json.dumps(data))
    return flow_files.load(name, str(tmp_path))


GOOD = {"flow": "demo", "title": "Demo", "tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "do a."},
                                                    {"key": "b", "skill": "demo-skill", "title": "B", "text": "do b.", "depends_on": ["a"]}]}


def test_a_flow_file_is_loaded_with_every_key_of_every_task(tmp_path):
    assert flow(tmp_path, GOOD)["tasks"][0] == {"key": "a", "skill": "demo-skill", "title": "A", "text": "do a.",
                                                "depends_on": [], "milestone": False}


@pytest.mark.parametrize("change, word", [
    ({"flow": "other"}, "the file's name"), ({"title": ""}, "title"), ({"tasks": []}, "at least one task"),
    ({"extra": 1}, "unknown key 'extra'"),
    ({"tasks": [{"key": "a", "skill": "no-such-skill", "title": "A", "text": "x"}]}, "is not under skills/"),
    ({"tasks": [{"key": "A b", "skill": "demo-skill", "title": "A", "text": "x"}]}, "lowercase words"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x", "depends_on": ["b"]},
                {"key": "b", "skill": "demo-skill", "title": "B", "text": "x"}]}, "not a task earlier in the list"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x"}, {"key": "a", "skill": "demo-skill", "title": "A", "text": "x"}]}, "used twice"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x", "milestone": "yes"}]}, "true or false"),
    ({"tasks": [{"key": "a", "skill": "demo-skill", "title": "A", "text": "x", "prompt": "y"}]}, "unknown key 'prompt'"),
])
def test_a_flow_file_that_is_not_well_formed_is_refused_with_every_problem_named(tmp_path, change, word):
    with pytest.raises(flow_files.FlowError) as e:
        flow(tmp_path, {**GOOD, **change})
    assert word in str(e.value)
    with pytest.raises(flow_files.FlowError):
        flow_files.load("Not A Name", str(tmp_path))


def test_what_a_skill_declares_is_read_from_its_frontmatter_and_a_placeholder_is_one_segment():
    meta = skill_meta.declared(str(REPO / "skills" / "biz-icp-positioning"))
    assert meta["outputs"] == ["docs/business/icp.md", "docs/business/positioning.md"] and meta["web"] is True
    assert meta["updates"] == ["docs/workbench/state.md"] and meta["side_effects"] == [] and meta["version"]
    assert skill_meta.matches(meta["inputs"], "docs/workbench/research/dental-clinics.md")
    assert not skill_meta.matches(meta["inputs"], "docs/workbench/research/a/b.md")
    assert not skill_meta.matches(meta["inputs"], "docs/workbench/research/.md")
    assert skill_meta.matches(["docs/brand/pieces/"], "docs/brand/pieces/logo/a.svg")
    with pytest.raises(skill_meta.SkillError):
        skill_meta.declared(str(REPO / "skills"))


def test_every_built_skill_declares_its_lists_in_the_form_the_runtime_reads():
    for folder in sorted((REPO / "skills").iterdir()):
        if (folder / "SKILL.md").is_file():
            assert skill_meta.declared(str(folder))["name"] == folder.name


def test_the_code_change_flow_is_valid_and_its_last_task_is_a_milestone():
    flow = flow_files.load("code-change")
    assert [(t["key"], t["skill"]) for t in flow["tasks"]] == [("implement", "eng-implement"),
                                                                  ("pull-request", "ops-pull-request")]
    assert flow["tasks"][-1]["milestone"] is True and flow["tasks"][-1]["depends_on"] == ["implement"]
    assert not any(t["skill"] in t["text"] for t in flow["tasks"])  # a task's text names no skill
    manifest = importlib.import_module("manifest")
    assert "code" in manifest.PACKS_IN_USE
    assert {"eng-implement", "ops-pull-request"} <= set(manifest.skills_in_use(str(REPO)))
    gate = manifest.load(str(REPO), "ops-pull-request")["gate"]
    assert gate == {"effect": "create", "payload_file": "<tmp>/payload.md"}
    assert manifest.load(str(REPO), "eng-implement")["gate"] is None


def real_info(*skills):
    info = {}
    for name in skills:
        folder = REPO / "skills" / name
        meta = skill_meta.declared(str(folder))
        info[name] = {"inputs": meta["inputs"], "outputs": meta["outputs"], "updates": meta["updates"],
                      "skill_md": (folder / "SKILL.md").read_text(encoding="utf-8")}
    return info


def chain(*tasks):
    return {"flow": "demo", "tasks": [{"key": k, "skill": sk, "depends_on": d} for k, sk, d in tasks]}


def test_a_required_row_of_alternatives_is_met_by_one_path_written_or_updated_upstream():
    skills = {"reader": {"inputs": ["docs/a.md", "docs/b.md"], "outputs": [],
                         "skill_md": "## Inputs\n\n| Artifact | Required | If missing |\n|---|---|---|\n| `docs/a.md`, or `docs/b.md` | yes | Stop |\n"},
              "writer": {"inputs": [], "outputs": ["docs/b.md"], "skill_md": ""},
              "editor": {"inputs": [], "outputs": [], "updates": ["docs/b.md"], "skill_md": ""},
              "other": {"inputs": [], "outputs": ["docs/a.md"], "skill_md": ""}}
    assert flow_files.dependency_problems(chain(("writer", "writer", []), ("reader", "reader", ["writer"])), skills) == []
    assert flow_files.dependency_problems(chain(("editor", "editor", []), ("reader", "reader", ["editor"])), skills) == []
    # an unrelated writer is a miss, and the text says what to add
    parallel = chain(("reader", "reader", []), ("writer", "writer", []))
    assert flow_files.dependency_problems(parallel, skills) == ['task reader reads docs/b.md, which task writer writes: add "writer" to its depends_on']
    # a row that no task upstream meets reports every path that a task of the flow writes, later or unrelated
    both = chain(("reader", "reader", []), ("other", "other", []), ("writer", "writer", ["reader"]))
    assert flow_files.dependency_problems(both, skills) == [
        'task reader reads docs/a.md, which task other writes: add "other" to its depends_on',
        "task reader reads docs/b.md, which only a later task writer writes: reorder the tasks"]
    # a row that nobody in the flow writes is not computed
    assert flow_files.dependency_problems(chain(("reader", "reader", [])), skills) == []


def test_the_real_flows_in_the_right_order_have_no_problem_and_the_alternatives_row_of_implement_is_met_upstream():
    skills = real_info("product-feature-spec", "eng-architecture", "eng-unit-tests", "eng-implement", "eng-code-review",
                       "eng-root-cause", "product-backlog")
    right = chain(("spec", "product-feature-spec", []), ("design", "eng-architecture", ["spec"]), ("tests", "eng-unit-tests", ["design"]),
                  ("implement", "eng-implement", ["tests"]), ("review", "eng-code-review", ["implement"]))
    assert flow_files.dependency_problems(right, skills) == []
    fix = chain(("cause", "eng-root-cause", []), ("tests", "eng-unit-tests", ["cause"]), ("implement", "eng-implement", ["tests"]),
                ("review", "eng-code-review", ["implement"]))
    assert flow_files.dependency_problems(fix, skills) == []


@pytest.mark.parametrize("tasks, reader, path, later", [
    ([("design", "eng-architecture", []), ("spec", "product-feature-spec", ["design"])], "design",
     "docs/product/specs/<feature>.md", "spec"),                                               # architecture before the specification
    ([("implement", "eng-implement", []), ("cause", "eng-root-cause", ["implement"])], "implement",
     "docs/engineering/plans/<task>.md", "cause"),                                               # implement before the root cause
    ([("backlog", "product-backlog", []), ("spec", "product-feature-spec", ["backlog"])], "backlog",
     "docs/product/specs/<feature>.md", "spec"),                                                 # the backlog before the specification
    ([("design", "eng-architecture", []), ("tests", "eng-unit-tests", ["design"]), ("spec", "product-feature-spec", ["tests"])], "design",
     "docs/product/specs/<feature>.md", "spec"),                                                 # a reversal through another task
])
def test_a_flow_in_the_wrong_order_is_refused_with_the_task_that_only_comes_later(tasks, reader, path, later):
    skills = real_info(*{sk for _, sk, _ in tasks})
    found = flow_files.dependency_problems(chain(*tasks), skills)
    assert f"task {reader} reads {path}, which only a later task {later} writes: reorder the tasks" in found
