"""Offline tests of two rules of scripts/validate.py: agent-skill (an error: every skill an agent cites exists) and
capability-invokes (a warning: a capability does not invoke another skill). Each test writes a small tree to a
temporary folder and points the module at it.

Run: uv run --with pytest pytest scripts/tests/test_validate_agent_invokes.py
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validate_agent_invokes_under_test", REPO / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "ROOT", str(tmp_path))
    monkeypatch.setattr(validate, "SKILLS", str(tmp_path / "skills"))
    monkeypatch.setattr(validate, "AGENTS", str(tmp_path / "agents"))
    return tmp_path


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")


def add_skill(root, name, body="# Demo\n\nText.\n", kind="capability"):
    write(root, f"skills/{name}/SKILL.md",
          f"---\nname: {name}\ndescription: >\n  Does a thing. Use this skill when asked.\nlicense: MIT\nmetadata:\n"
          f"  area: engineering\n  kind: {kind}\n  inputs: []\n  outputs: []\n  updates: []\n  requires: []\n"
          f"  side_effects: []\n  version: \"0.1.0\"\n---\n\n{body}")


def add_agent(root, name="helper", skills="[eng-demo]", body="# Helper\n\nText.\n"):
    write(root, f"agents/{name}.md",
          f"---\nname: {name}\ndescription: >\n  A helper. Delegate to it when needed.\nmetadata:\n  skills: {skills}\n"
          f"  version: \"0.1.0\"\n---\n\n{body}")


def agent_findings(root):
    report = validate.Report()
    validate.check_agent_skills(report, root=str(root))
    assert report.warnings == []  # an agent-skill finding is an error
    return [(e["where"], e["rule"], e["message"]) for e in report.errors]


def invokes(root, name="eng-demo", others=("eng-other", "core-orchestrator")):
    for other in others:
        add_skill(root, other)
    report = validate.Report()
    validate.check_capability_invokes(name, report, validate.built_skills(str(root)), root=str(root))
    assert report.errors == []
    return report.warnings


# --- agent-skill ------------------------------------------------------------------------------------------

def test_a_valid_agent_has_no_finding(tree):
    add_skill(tree, "eng-demo")
    add_skill(tree, "eng-other")
    add_agent(tree, skills="[eng-demo, eng-other]", body="# Helper\n\nRead the skill `eng-demo`, then `eng-other`.\n")
    assert agent_findings(tree) == []


def test_a_name_in_the_skills_list_that_is_not_a_skill_fails_with_agent_line_and_name(tree):
    add_skill(tree, "eng-demo")
    add_agent(tree, skills="[eng-demo, eng-ghost]")
    assert agent_findings(tree) == [
        ("agents/helper.md:6", "agent-skill",
         "[agent-skill] metadata.skills lists eng-ghost, which is not a folder of skills/ or a file of flows/")]


def test_a_block_list_is_read_too(tree):
    add_skill(tree, "eng-demo")
    write(tree, "agents/helper.md", "---\nname: helper\ndescription: >\n  A helper.\nmetadata:\n  skills:\n    - eng-demo\n"
                                    "    - eng-gone\n  version: \"0.1.0\"\n---\n\nText.\n")
    assert [(w, m.split(",")[0]) for w, _, m in agent_findings(tree)] == [
        ("agents/helper.md:8", "[agent-skill] metadata.skills lists eng-gone")]


def test_a_backticked_name_in_the_body_must_exist_unless_planned_allowed_or_in_a_fence(tree):
    add_skill(tree, "eng-demo")
    add_agent(tree, body="# Helper\n\nRead `eng-demo`, then `eng-missing`.\nLater `eng-soon` (planned).\n"
                         "An example `eng-invented` <!-- validate: allow agent-skill -- an invented example -->\n"
                         "A path `docs/eng-thing.md` and a word eng-bare.\n\n```text\nrun `eng-in-a-fence`\n```\n")
    assert [(w, m) for w, _, m in agent_findings(tree)] == [
        ("agents/helper.md:12", "[agent-skill] the body cites eng-missing, which is not a folder of skills/ or a file of flows/")]


def test_a_flow_file_name_counts_bare_or_with_the_flow_prefix_and_a_folder_without_skill_md_does_not(tree):
    add_skill(tree, "eng-demo")
    write(tree, "flows/code-change.json", {"tasks": []})
    write(tree, "skills/eng-empty/notes.md", "no SKILL.md here\n")
    add_agent(tree, skills="[eng-demo, code-change, flow-code-change, flow-nothing, eng-empty]")
    assert [m.split(",")[0] for _, _, m in agent_findings(tree)] == [
        "[agent-skill] metadata.skills lists flow-nothing", "[agent-skill] metadata.skills lists eng-empty"]


def test_a_skills_value_that_is_not_a_list_is_reported_and_no_agents_folder_is_fine(tree):
    assert agent_findings(tree) == []
    add_agent(tree, skills="eng-demo")
    assert [m for _, _, m in agent_findings(tree)] == ["[agent-skill] metadata.skills must be a list of skill names"]


def test_agent_skill_is_an_error_with_the_rule_name(tree):
    assert "agent-skill" in validate.ERROR_RULES and "agent-skill" not in validate.WARNING_RULES


def test_the_agents_of_this_repository_cite_only_existing_skills():
    report = validate.Report()
    validate.check_agent_skills(report, root=str(REPO))
    assert report.errors == [] and report.warnings == []


# --- capability-invokes -----------------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "Run the skill `eng-other` and read its output.",
    "Then invoke the skill `eng-other`.",
    "Call skill `eng-other` with the plan.",
    "The step uses the skill `eng-other` to write it.",
    "Execute this skill `eng-other`.",
    "Type `/eng-other` to continue.",
    "Hand it over to `eng-other`.",
    "Hand the request to `eng-other` at once.",
])
def test_a_sentence_that_invokes_another_skill_is_warned(tree, line):
    add_skill(tree, "eng-demo", body=f"# Demo\n\n{line}\n")
    found = invokes(tree)
    assert [w["rule"] for w in found] == ["capability-invokes"]
    assert found[0]["where"] == "skills/eng-demo" and "eng-other (SKILL.md:" in found[0]["message"]


@pytest.mark.parametrize("line", [
    "Stop and tell the user that `eng-other` writes it and to run it first.",
    "- Prices and revenue model: `eng-other` (planned).",
    "- A bug with no root cause yet: `eng-other` first.",
    "Writes docs/x.md; `eng-other` reads it.",
    "Next: run `eng-other`, then ask again.",
    "The reply says: run the skill `eng-other` first.",
    "Recommend that the user run the skill `eng-other`.",
    "Run the skill `eng-ghost`.",
    "Run the skill `eng-demo`.",
    "Run `eng-other` after the change.",
    "The router hands requests over, as in a table.",
    "Run the skill `eng-other`. <!-- validate: allow capability-invokes -- the user asked for it -->",
])
def test_citing_a_skill_as_owner_or_first_step_is_not_an_invocation(tree, line):
    add_skill(tree, "eng-demo", body=f"# Demo\n\n{line}\n")
    assert invokes(tree) == []


def test_the_frontmatter_fences_table_rows_and_gotchas_are_not_read(tree):
    body = ("# Demo\n\n| Input | Missing |\n|---|---|\n| docs/a.md | Run the skill `eng-other`. |\n\n"
            "```text\nRun the skill `eng-other`.\n```\n\n## Gotchas\n\n- Once the run called the skill `eng-other`.\n")
    add_skill(tree, "eng-demo", body=body)
    assert invokes(tree) == []
    add_skill(tree, "eng-demo", body=body + "\n## Notes\n\nRun the skill `eng-other`.\n")
    found = invokes(tree)
    assert len(found) == 1 and "eng-other (SKILL.md:" in found[0]["message"]


def test_the_message_lists_each_hit_with_its_line(tree):
    add_skill(tree, "eng-demo", body="# Demo\n\nRun the skill `eng-other`.\nThen hand it over to `eng-other`.\n")
    found = invokes(tree)
    assert len(found) == 1 and found[0]["message"].endswith("eng-other (SKILL.md:19); eng-other (SKILL.md:20)")


def test_a_flow_and_the_router_may_invoke(tree):
    flow_body = "# Flow\n\nRun the skill `eng-other`.\n"
    add_skill(tree, "flow-demo", body=flow_body, kind="flow")
    add_skill(tree, "core-orchestrator", body="# Router\n\nHand the request over to `eng-other`.\n")
    assert invokes(tree, name="flow-demo", others=("eng-other",)) == []
    report = validate.Report()
    validate.check_capability_invokes("core-orchestrator", report, validate.built_skills(str(tree)), root=str(tree))
    assert report.warnings == [] and report.errors == []


def test_capability_invokes_is_a_warning_listed_by_flags(tree):
    assert "capability-invokes" in validate.WARNING_RULES and "capability-invokes" not in validate.ERROR_RULES


def test_the_skills_of_this_repository_invoke_no_other_skill():
    built = validate.built_skills(str(REPO))
    report = validate.Report()
    for name in built:
        validate.check_capability_invokes(name, report, built, root=str(REPO))
    assert report.warnings == [] and report.errors == []
