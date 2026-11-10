"""A platform's fetch file is read by the fetcher and the reference store, never staged into a skill's run and never part of a case's context
hash: editing one changes no skill's evidence (principle 12)."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PLATFORMS = ROOT / "shared" / "references" / "platforms"
FETCH_FILES = sorted(PLATFORMS.glob("*.fetch.json"))


def load(rel, name):
    for folder in (str(ROOT / "evals"), str(ROOT / "scripts")):
        if folder not in sys.path:
            sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def stems():
    return [p.name[: -len(".fetch.json")] for p in FETCH_FILES]


def test_there_is_a_fetch_file():
    assert FETCH_FILES


@pytest.mark.parametrize("platform", stems())
def test_the_staging_of_a_platform_never_holds_its_fetch_file(platform):
    stage = load("scripts/stage_skills.py", "stage_skills_for_fetch_files")
    if (PLATFORMS / (platform + ".md")).is_file():
        held = stage.platform_references([platform])
        assert held == ["platforms/%s.md" % platform, "platforms/%s.json" % platform]
        assert not [h for h in held if ".fetch." in h]


@pytest.mark.parametrize("platform", [s for s in stems() if (PLATFORMS / (s + ".md")).is_file()])
def test_a_case_context_is_the_same_before_and_after_the_fetch_files_content_changes(tmp_path, platform):
    status = load("evals/eval_status.py", "eval_status_for_fetch_files")
    root = tmp_path / "tree"
    shutil.copytree(ROOT / "shared", root / "shared", ignore=shutil.ignore_patterns("__pycache__", "tests"))
    skill = root / "skills" / "mkt-social-copy"
    shutil.copytree(ROOT / "skills" / "mkt-social-copy", skill, ignore=shutil.ignore_patterns("__pycache__", "evidence"))
    case = {"id": 1, "platforms": [platform]}
    before = status.case_context(str(root), str(skill), case, True)
    assert before is not status.UNKNOWN_CONTEXT
    path = root / "shared" / "references" / "platforms" / ("%s.fetch.json" % platform)
    data = json.loads(path.read_text())
    data.update(extractors=["Planted"], checked="a planted edit")
    path.write_text(json.dumps(data))
    assert status.case_context(str(root), str(skill), case, True) == before
    md = root / "shared" / "references" / "platforms" / ("%s.md" % platform)
    md.write_text(md.read_text() + "\nA planted line.\n")
    assert status.case_context(str(root), str(skill), case, True) != before, "the test can tell a staged file's change"


def test_no_skill_or_skill_reference_names_a_fetch_file():
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "skills").rglob("*") if p.is_file() and p.suffix in (".md", ".json", ".py", ".txt")
            and "evidence" not in p.parts and ".fetch.json" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == []
    for ref in (ROOT / "shared" / "references").glob("*.md"):
        assert ".fetch.json" not in ref.read_text(encoding="utf-8")
