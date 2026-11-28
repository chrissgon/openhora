"""Tests of the project key imported_skills (package I2): the skills from outside that the project lists by name.
Offline: the stand-in tree (runtime/tests/standin_tree.py). Invented names: skill ops-tidy-notes, project Quillmere.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_project_config_imported.py
"""
from __future__ import annotations

import json
import os

import pytest

import standin_tree as st

lab = st.load("lab")
project_config = st.load("project_config")
HASH = "c" * 64


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    built["home"] = tmp_path / "outside" / "skills"
    built["home"].mkdir(parents=True)
    return built


def configure(tree, value="absent") -> str:
    project = str(tree["project"])
    file = project_config.path(project)
    with open(file, encoding="utf-8") as f:
        good = json.load(f)
    if value != "absent":
        good["imported_skills"] = value
    with open(file, "w", encoding="utf-8") as f:
        json.dump(good, f)
    return project


def refused(tree, value) -> str:
    with pytest.raises(project_config.ConfigError) as e:
        project_config.load(configure(tree, value))
    assert str(e.value).startswith("runtime.json imported_skills"), str(e.value)
    return str(e.value)


def test_absent_lists_nothing(tree):
    assert "imported_skills" in project_config.TASK_RUNTIME_KEYS
    assert project_config.load(configure(tree))["imported_skills"] == {"home": None, "skills": {}}


def test_a_listing_is_read_with_its_folder_and_its_acceptance(tree):
    home = str(tree["home"])
    got = project_config.load(configure(tree, {"home": home, "skills": {
        "ops-tidy-notes": {}, "ops-sort-links": {"without_external_line": HASH}}}))["imported_skills"]
    real = os.path.realpath(home)
    assert got["home"] == real
    assert got["skills"]["ops-tidy-notes"] == {"folder": os.path.join(real, "ops-tidy-notes"), "without_external_line": None, "agent": None}
    assert got["skills"]["ops-sort-links"]["without_external_line"] == HASH


def test_an_empty_listing_is_accepted(tree):
    assert project_config.load(configure(tree, {"home": str(tree["home"]), "skills": {}}))["imported_skills"]["skills"] == {}


@pytest.mark.parametrize("bad", [[], "x", {"skills": {}}, {"home": "/h", "skills": {}, "extra": 1}], ids=["list", "text", "no home", "extra key"])
def test_the_shape_is_closed(tree, bad):
    refused(tree, bad)


def test_home_must_be_absolute_and_not_a_link(tree, tmp_path):
    refused(tree, {"home": "relative/skills", "skills": {}})
    link = tmp_path / "link"
    link.symlink_to(tree["home"])
    assert "symbolic link" in refused(tree, {"home": str(link), "skills": {}})


def test_home_is_never_inside_the_workbench(tree):
    inside = tree["tree"] / "outside-looking"
    inside.mkdir()
    assert "workbench" in refused(tree, {"home": str(inside), "skills": {}})
    assert "workbench" in refused(tree, {"home": str(tree["tree"]), "skills": {}})


def test_skills_must_be_an_object(tree):
    refused(tree, {"home": str(tree["home"]), "skills": ["ops-tidy-notes"]})


@pytest.mark.parametrize("name", ["Ops-Tidy", "ops tidy", "ops--tidy", "-ops", "a" * 65, "", "ops-tidy\n"])
def test_a_name_must_be_a_skill_name(tree, name):
    refused(tree, {"home": str(tree["home"]), "skills": {name: {}}})


def test_a_folder_of_the_workbench_is_never_listed(tree):
    assert "demo-asks" in refused(tree, {"home": str(tree["home"]), "skills": {"demo-asks": {}}})


@pytest.mark.parametrize("entry", [{"other": 1}, [], {"without_external_line": "abc"}, {"without_external_line": "A" * 64},
                                   {"without_external_line": 5}], ids=["key", "list", "short", "upper", "number"])
def test_an_entry_is_empty_or_one_hash(tree, entry):
    refused(tree, {"home": str(tree["home"]), "skills": {"ops-tidy-notes": entry}})


def test_the_agent_key_is_an_agent_name(tree):
    home = str(tree["home"])
    got = project_config.load(configure(tree, {"home": home, "skills": {"ops-tidy-notes": {"agent": "delivery"}}}))["imported_skills"]
    assert got["skills"]["ops-tidy-notes"]["agent"] == "delivery"
    assert project_config.load(configure(tree, {"home": home, "skills": {"ops-tidy-notes": {}}}))["imported_skills"]["skills"]["ops-tidy-notes"]["agent"] is None
    for bad in ["Delivery", "two words", "", 3, None, "x" * 65]:
        assert "agent" in refused(tree, {"home": home, "skills": {"ops-tidy-notes": {"agent": bad}}})
