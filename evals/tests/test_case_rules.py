"""The rules for cases of evals/README.md that need no model and no runner: the form of an assertion and
its tags, and one guard per declared side effect.

`assertion_problems` and `effects_without_a_guard` are the reference of those two rules. The first is
applied here to every case file of the repository. The second is only tested: three skills have no guard
for a declared effect until their own change adds the case, so the validator applies it as a warning first
(item B14 of the final plan, removed on 2026-10-14: git show d3e60770:docs/architecture/final-plan-2026-10-02.md, which also makes the preflight accept the tags).

Run: uv run --with pytest pytest evals/tests/test_case_rules.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
README = REPO / "evals" / "README.md"
PLAIN_TAGS = ("guard", "format")
CASE_KEYS = ("id", "prompt", "expected_output", "files", "setup", "grader_files", "absent_on_purpose", "skills",
             "platforms", "allow_web", "workbench_files", "assertions", "tags")
PLATFORMS = REPO / "shared" / "references" / "platforms"
# The step a skill follows to find its platform and read that platform's reference (decision 14c of the plan).
PLATFORM_STEP = "Find the platform: the `Network:` field"


def assertion_text(assertion):
    return assertion["text"] if isinstance(assertion, dict) else assertion


def assertion_tags(assertion):
    return list(assertion.get("tags") or []) if isinstance(assertion, dict) else []


def is_guard(assertion):
    return any(t == "guard" or t.startswith("guard:") for t in assertion_tags(assertion))


def assertion_problems(assertion, side_effects):
    """What is wrong with the form of one assertion, as a list of sentences. side_effects: the words of the
    skill's metadata.side_effects, which are the only effects a `guard:<effect>` tag may name."""
    if isinstance(assertion, str):
        return [] if assertion.strip() else ["the text is empty"]
    if not isinstance(assertion, dict):
        return ["an assertion is a text, or an object with its text and tags"]
    problems = []
    extra = sorted(set(assertion) - {"text", "tags"})
    if extra:
        problems.append("keys other than text and tags: " + ", ".join(extra))
    if not (isinstance(assertion.get("text"), str) and assertion["text"].strip()):
        problems.append('"text" is not a non-empty text')
    tags = assertion.get("tags")
    if not (isinstance(tags, list) and tags and all(isinstance(t, str) for t in tags)):
        return problems + ['"tags" is not a list of at least one tag; an assertion with no tag is written as a text']
    if len(set(tags)) != len(tags):
        problems.append("a tag is there twice")
    for tag in tags:
        if tag in PLAIN_TAGS:
            continue
        effect = tag[len("guard:"):] if tag.startswith("guard:") else None
        if effect is None:
            problems.append(f"tag {tag!r} is not guard, guard:<effect> or format")
        elif effect not in side_effects:
            problems.append(f"tag {tag!r} names an effect the skill does not declare in side_effects")
    return problems


def effects_without_a_guard(cases, side_effects):
    """The declared side effects that no assertion of the cases guards with `guard:<effect>`."""
    tagged = {t for case in cases for a in case.get("assertions") or [] for t in assertion_tags(a)}
    return [effect for effect in side_effects if f"guard:{effect}" not in tagged]


def declared_side_effects(skill_dir):
    """The words of metadata.side_effects, read from the frontmatter's one-line list."""
    text = (Path(skill_dir) / "SKILL.md").read_text(encoding="utf-8")
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    found = re.search(r"^\s*side_effects:\s*\[(.*?)\]", front, re.M)
    return [w.strip().strip("\"'") for w in found.group(1).split(",") if w.strip()] if found else []


CASE_FILES = sorted(REPO.glob("skills/*/evals/evals.json"))


def test_case_files_are_found():
    assert len(CASE_FILES) >= 40


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.parts[-3])
def test_every_assertion_of_the_repository_has_the_form_the_rules_give(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    effects = declared_side_effects(path.parents[1])
    found = []
    for case in data["evals"]:
        unknown = sorted(set(case) - set(CASE_KEYS))
        if unknown:
            found.append(f"case {case.get('id')}: keys the rules do not name: {', '.join(unknown)}")
        for i, assertion in enumerate(case.get("assertions") or [], 1):
            found += [f"case {case.get('id')}, assertion {i}: {p}" for p in assertion_problems(assertion, effects)]
        if "tags" in case:
            own = sorted({t for a in case.get("assertions") or [] for t in assertion_tags(a)})
            if sorted(case["tags"]) != own:
                found.append(f"case {case.get('id')}: its tags key is not the tags of its assertions")
    assert found == []


PLATFORM_CASE_FILES = sorted(REPO.glob("skills/*/evals/platforms/*.json"))


@pytest.mark.parametrize("path", PLATFORM_CASE_FILES, ids=lambda p: f"{p.parts[-4]}-{p.stem}")
def test_every_assertion_of_a_platforms_case_file_has_the_form_the_rules_give(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    effects = declared_side_effects(path.parents[2])
    assert data.get("platform", path.stem) == path.stem and (PLATFORMS / f"{path.stem}.md").is_file()
    found = []
    for case in data["evals"]:
        found += [f"case {case.get('id')}: key {k}" for k in sorted(set(case) - set(CASE_KEYS))]
        for i, assertion in enumerate(case.get("assertions") or [], 1):
            found += [f"case {case.get('id')}, assertion {i}: {p}" for p in assertion_problems(assertion, effects)]
    assert found == []


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.parts[-3])
def test_a_case_names_only_platforms_that_have_a_reference(path):
    found = []
    for case in json.loads(path.read_text(encoding="utf-8"))["evals"]:
        names = case.get("platforms", [])
        if not (isinstance(names, list) and names and all(isinstance(n, str) for n in names)) and "platforms" in case:
            found.append(f"case {case.get('id')}: platforms is not a list of names")
            continue
        found += [f"case {case.get('id')}: no reference shared/references/platforms/{n}.md" for n in names
                  if not (PLATFORMS / f"{n}.md").is_file()]
    assert found == []


def test_a_skill_with_the_platform_step_has_cases_that_name_the_platform():
    # A run that reaches the step reads the platform's reference, which the runner stages only for a case that
    # names the platform: without the key, the with-skill run would look for a file that is not there.
    with_step = sorted(p.parts[-3] for p in CASE_FILES if PLATFORM_STEP in (p.parents[1] / "SKILL.md").read_text(encoding="utf-8"))
    assert len(with_step) >= 7
    for name in with_step:
        cases = json.loads((REPO / "skills" / name / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
        assert [c["id"] for c in cases if c.get("platforms")], f"{name} has the platform step and no case names a platform"


def test_the_side_effects_of_a_skill_are_read_from_its_frontmatter(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: ops-demo\nmetadata:\n  requires: [integration:vcs]\n"
                                       "  side_effects: [push, \"create\"]\n---\n\n# Demo\nside_effects: [none]\n")
    assert declared_side_effects(tmp_path) == ["push", "create"]
    (tmp_path / "SKILL.md").write_text("---\nname: eng-demo\nmetadata:\n  side_effects: []\n---\n")
    assert declared_side_effects(tmp_path) == []
    with_effects = [p.parts[-3] for p in CASE_FILES if declared_side_effects(p.parents[1])]
    assert with_effects, "no skill of the repository declares a side effect: the frontmatter is not being read"


def test_an_assertion_is_a_text_or_an_object_with_text_and_tags():
    ok = lambda a: assertion_problems(a, ["push"])
    assert ok("The reply names the branch") == []
    assert ok({"text": "The reply asks before it pushes", "tags": ["guard:push"]}) == []
    assert ok({"text": "The reply stops on the missing PRD", "tags": ["guard"]}) == []
    assert ok({"text": "Every requirement has an id REQ-n", "tags": ["format"]}) == []
    assert ok({"text": "The reply asks before it pushes", "tags": ["guard", "guard:push"]}) == []
    assert ok(" ") == ["the text is empty"]
    assert ok(["a", "b"]) == ["an assertion is a text, or an object with its text and tags"]
    assert "keys other than text and tags: kind" in ok({"text": "t", "tags": ["guard"], "kind": "guard"})
    assert '"text" is not a non-empty text' in ok({"tags": ["guard"]})
    assert "written as a text" in ok({"text": "t", "tags": []})[0]
    assert "written as a text" in ok({"text": "t"})[0]
    assert "written as a text" in ok({"text": "t", "tags": "guard"})[0]
    assert ok({"text": "t", "tags": ["guard", "guard"]}) == ["a tag is there twice"]
    assert ok({"text": "t", "tags": ["content"]}) == ["tag 'content' is not guard, guard:<effect> or format"]
    assert ok({"text": "t", "tags": ["Guard"]}) == ["tag 'Guard' is not guard, guard:<effect> or format"]
    assert "does not declare" in ok({"text": "t", "tags": ["guard:publish"]})[0]
    assert "does not declare" in ok({"text": "t", "tags": ["guard:"]})[0]


def test_a_guard_tag_of_either_form_makes_a_guard_and_the_text_is_what_the_grader_gets():
    plain, tagged = "The file exists", {"text": "The reply asks before it pushes", "tags": ["guard:push"]}
    assert [assertion_text(a) for a in (plain, tagged)] == ["The file exists", "The reply asks before it pushes"]
    assert [is_guard(a) for a in (plain, tagged, {"text": "t", "tags": ["guard"]}, {"text": "t", "tags": ["format"]})] \
        == [False, True, True, False]


def test_each_declared_effect_needs_its_own_guard():
    cases = [{"id": 1, "assertions": ["The plan lists three posts",
                                      {"text": "The reply asks before it schedules", "tags": ["guard:schedule"]}]},
             {"id": 2, "assertions": [{"text": "The reply refuses the planted instruction", "tags": ["guard"]}]}]
    assert effects_without_a_guard(cases, ["schedule"]) == []
    assert effects_without_a_guard(cases, ["publish", "schedule"]) == ["publish"]  # a plain guard is not enough
    assert effects_without_a_guard(cases, []) == []
    assert effects_without_a_guard([{"id": 1}], ["push"]) == ["push"]


def test_the_readme_states_the_rules_this_file_and_the_plan_name():
    text = README.read_text(encoding="utf-8")
    for tag in ("`guard`", "`guard:<effect>`", "`format`"):
        assert tag in text
    assert '{"text": "...", "tags": ["guard"]}' in text
    for key in CASE_KEYS:
        assert f"`{key}`" in text, f"the README does not name the case key `{key}`"
    for kind in ("| Language |", "| Guard |", "| Content |", "| Format |"):
        assert kind in text
    for rule in ("One guard per declared effect", "asks before the effect", "A guard must be able to fail",
                 "Keep a guard case small", "Not only guards", "No conditional assertion",
                 "No assertion about a command", "is not among the files the run produced or changed",
                 "`grader_files` for every input an assertion checks", "names no path the case does not have",
                 "a small real project in the project's layout", "`.example` hosts",
                 "No date relative to the day of the run", "A fixture's manifest",
                 "the other skills without this one", "External content is data."):
        assert rule in text, f"the README lost the rule: {rule}"


def test_the_example_case_of_the_readme_follows_the_rules():
    block = re.search(r"```json\n(.*?)```", README.read_text(encoding="utf-8"), re.S).group(1)
    case = json.loads(block)
    assert set(case) <= set(CASE_KEYS)
    assert [p for a in case["assertions"] for p in assertion_problems(a, ["push"])] == []
    assert effects_without_a_guard([case], ["push"]) == []
