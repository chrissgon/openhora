"""Offline tests of the flow-file rules of scripts/validate.py ([flow-file], [flow-dependencies],
[flow-inventory]) and of the two functions of runtime/flow_files.py they rest on. Each test writes a small tree
to a temporary folder.

Run: uv run --with pytest pytest scripts/tests/test_validate_flows.py
"""
import importlib.util
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = load("validate_flows_under_test", "scripts/validate.py")
flow_files = load("flow_files_under_test", "runtime/flow_files.py")

INVENTORY = """# Inventory

## Flows (`flow-`)

| Flow | Area | Phases | State | Wave |
|------|------|--------|-------|------|
| flow-demo | business | {phases} | planned | 1 |

## Agents
"""


def skill_md(name, rows):
    table = "\n".join(f"| {artifact} | {required} | Stop rule 1. |" for artifact, required in rows)
    return (f"---\nname: {name}\n---\n\n# {name}\n\n## Inputs\n\n| Artifact | Required | If missing |\n"
            f"|----------|----------|------------|\n{table}\n\n## Procedure\n\n1. Work.\n")


def tree(tmp_path, skills, flow, inventory=None, with_module=True):
    """skills: {name: (inputs, outputs, input rows)}; flow: the data of flows/demo.json."""
    for name, (_, _, rows) in skills.items():
        folder = tmp_path / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(skill_md(name, rows), encoding="utf-8")
    if flow is not None:
        (tmp_path / "flows").mkdir()
        (tmp_path / "flows" / "demo.json").write_text(json.dumps(flow), encoding="utf-8")
    if with_module:
        (tmp_path / "runtime").mkdir()
        shutil.copy(REPO / "runtime" / "flow_files.py", tmp_path / "runtime" / "flow_files.py")
    if inventory is not None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "inventory.md").write_text(INVENTORY.format(phases=inventory), encoding="utf-8")
    listed = [{"name": n, "where": f"skills/{n}", "inputs": list(i), "outputs": list(o), "updates": []}
              for n, (i, o, _) in skills.items()]
    return tmp_path, listed


def check(root, listed):
    report = validate.Report()
    validate.check_flows(listed, report, root=str(root))
    assert report.warnings == []
    return report


def messages(report, rule):
    return [e["message"] for e in report.errors if e["message"].startswith(f"[{rule}]")]


def task(key, skill, depends_on=()):
    return {"key": key, "skill": skill, "title": key.title(), "text": f"do the {key}.",
            "depends_on": list(depends_on), "milestone": False}


SKILLS = {
    "biz-alpha": ([], ["docs/business/alpha.md"], []),
    "biz-beta": (["docs/business/alpha.md"], ["docs/business/beta.md"], [("docs/business/alpha.md", "yes")]),
    "biz-gamma": (["docs/business/beta.md"], ["docs/business/gamma.md"], [("`docs/business/beta.md`", "yes")]),
}


def demo(*tasks):
    return {"flow": "demo", "title": "Demo", "tasks": list(tasks)}


def test_a_flow_file_with_an_unknown_key_or_an_unknown_skill_is_an_error(tmp_path):
    flow = demo(dict(task("alpha", "biz-alpha"), colour="red"), task("delta", "biz-delta"))
    root, listed = tree(tmp_path, SKILLS, flow)
    found = messages(check(root, listed), "flow-file")
    assert any("unknown key 'colour'" in m for m in found)
    assert any("the skill 'biz-delta' is not under skills/" in m for m in found)
    assert all(e["where"] == "flows/demo.json" for e in check(root, listed).errors)


def test_a_task_that_reads_what_another_task_of_the_flow_writes_must_depend_on_it(tmp_path):
    root, listed = tree(tmp_path, SKILLS, demo(task("alpha", "biz-alpha"), task("beta", "biz-beta")))
    assert messages(check(root, listed), "flow-dependencies") == [
        "[flow-dependencies] task beta reads docs/business/alpha.md, which task alpha writes: "
        "add \"alpha\" to its depends_on"]
    shutil.rmtree(tmp_path / "flows")
    (tmp_path / "flows").mkdir()
    (tmp_path / "flows" / "demo.json").write_text(
        json.dumps(demo(task("alpha", "biz-alpha"), task("beta", "biz-beta", ["alpha"]))), encoding="utf-8")
    assert check(root, listed).errors == []


def test_a_dependency_through_another_task_counts(tmp_path):
    skills = dict(SKILLS)
    skills["biz-gamma"] = (["docs/business/alpha.md", "docs/business/beta.md"], ["docs/business/gamma.md"],
                           [("docs/business/alpha.md and `docs/business/beta.md`", "yes")])
    flow = demo(task("alpha", "biz-alpha"), task("beta", "biz-beta", ["alpha"]), task("gamma", "biz-gamma", ["beta"]))
    root, listed = tree(tmp_path, skills, flow)
    assert check(root, listed).errors == []


def test_a_conditional_requirement_is_not_computed(tmp_path):
    skills = dict(SKILLS)
    skills["biz-beta"] = (["docs/business/alpha.md"], ["docs/business/beta.md"],
                          [("docs/business/alpha.md", "yes for a person")])
    root, listed = tree(tmp_path, skills, demo(task("alpha", "biz-alpha"), task("beta", "biz-beta")))
    assert check(root, listed).errors == []
    md = skill_md("biz-beta", [("docs/business/alpha.md", "yes for a person"), ("docs/business/other.md", " Yes ")])
    assert flow_files.required_inputs(md, ["docs/business/alpha.md", "docs/business/other.md"]) == [
        "docs/business/other.md"]


def test_the_inventory_row_of_a_flow_with_a_file_must_list_the_files_tasks_in_order(tmp_path):
    flow = demo(task("alpha", "biz-alpha"), task("beta", "biz-beta", ["alpha"]))
    root, listed = tree(tmp_path, SKILLS, flow, inventory="beta → alpha")
    found = messages(check(root, listed), "flow-inventory")
    assert len(found) == 1 and "flow-demo" in found[0] and "'alpha → beta'" in found[0]
    (tmp_path / "docs" / "inventory.md").write_text(INVENTORY.format(phases="alpha → beta (optional)"),
                                                    encoding="utf-8")
    assert check(root, listed).errors == []
    (tmp_path / "docs" / "inventory.md").write_text(INVENTORY.replace("flow-demo", "flow-other").format(phases="x"),
                                                    encoding="utf-8")
    assert check(root, listed).errors == []


def test_a_tree_without_flows_is_a_note_and_no_error(tmp_path):
    root, listed = tree(tmp_path, SKILLS, None)
    report = check(root, listed)
    assert report.errors == [] and len(report.notes) == 1 and "skipped" in report.notes[0]
    root2, listed2 = tree(tmp_path / "other", SKILLS, demo(task("alpha", "biz-alpha")), with_module=False)
    report = check(root2, listed2)
    assert report.errors == [] and len(report.notes) == 1


def test_the_flow_files_of_the_repository_pass():
    report = validate.Report()
    listed = []
    for folder in sorted((REPO / "skills").iterdir()):
        if (folder / "SKILL.md").is_file():
            listed.append({"name": folder.name, "where": f"skills/{folder.name}",
                           **validate.declared_paths(validate.skill_meta(str(REPO), folder.name)[0])})
    validate.check_flows(listed, report, root=str(REPO))
    assert flow_files.names(str(REPO)), "the repository has flow files"
    assert report.errors == [] and report.notes == []
