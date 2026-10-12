"""The fidelity test per document type: every document a skill's runtime manifest marks `editable` (a person's edit
of it on a platform is taken back) must survive the trip through the platform's blocks (notion_blocks.round_trip):
it still passes its skill's checker, or, with no checker, it loses no word. A type with no fixture, or one that fails,
is set to `read_only` in its manifest, never fixed by changing the converter. Offline.

A fixture is a case of fixtures/round-trip.json whose skill and document match the entry, or a case of
fixtures/types/<skill>.json in the same form: the files a check needs, the document's path, the commands.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_document_types.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location("notion_blocks_for_types", REPO / "providers" / "documents" / "notion_blocks.py")
nb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nb)
MARKER = re.compile(r"^(?:[-*+]|\d+[.)]) ")
RULE_LINE = re.compile(r"^[|\-: ]*$")


def entries(platform: str) -> list:
    out = []
    for path in sorted((REPO / "skills").glob("*/evals/runtime-manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out += [(data["skill"], doc) for doc in data.get("documents") or [] if doc["platform"] == platform]
    return out


def fixture(skill: str, document: str):
    """The fixture case of a document type, or None."""
    files = [HERE / "fixtures" / "round-trip.json", HERE / "fixtures" / "types" / f"{skill}.json"]
    for file in files:
        if not file.is_file():
            continue
        for case in json.loads(file.read_text(encoding="ascii"))["cases"]:
            if case["skill"] == skill and case["document"] == document:
                return case
    return None


def words(text: str) -> list:
    out = []
    for line in text.splitlines():
        if RULE_LINE.fullmatch(line):
            continue
        out += MARKER.sub("", line.replace("|", "")).split()
    return out


def write_files(case, folder: Path) -> Path:
    for rel, text in case["files"].items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    return folder / case["document"]


def passes(skill, doc, folder) -> list:
    """(command, exit code, ok) of every checker of the entry, run from the folder that holds the fixture."""
    out = []
    for name, *args in doc["checks"]:
        args = [a.replace("{path}", doc["path"]) for a in args]
        done = subprocess.run([sys.executable, str(REPO / "skills" / skill / "scripts" / name), *args],
                              capture_output=True, text=True, cwd=folder, timeout=60)
        try:
            ok = json.loads(done.stdout).get("ok")
        except ValueError:
            ok = None
        out.append((name, done.returncode, ok))
    return out


EDITABLE = entries("editable")
CHECKED = [(s, d) for s, d in EDITABLE if d["checks"]]
UNCHECKED = [(s, d) for s, d in EDITABLE if not d["checks"]]


def test_every_editable_document_type_has_a_fixture():
    assert EDITABLE, "no manifest marks a document editable"
    missing = [f"{s}: {d['path']}" for s, d in EDITABLE if fixture(s, d["path"]) is None]
    assert not missing, f"an editable document type needs a fixture (or read_only in its manifest): {missing}"


@pytest.mark.parametrize("skill,doc", CHECKED, ids=[f"{s}:{d['path']}" for s, d in CHECKED])
def test_an_editable_document_still_passes_its_skills_checker_after_the_trip(skill, doc, tmp_path):
    case = fixture(skill, doc["path"])
    document = write_files(case, tmp_path)
    passing = [(name, 0, True) for name, *_ in doc["checks"]]
    assert passes(skill, doc, tmp_path) == passing, "the fixture itself must pass before the trip"
    after = nb.round_trip(document.read_text(encoding="utf-8"))
    document.write_text(after, encoding="utf-8")
    assert passes(skill, doc, tmp_path) == passing
    assert nb.round_trip(after) == after


@pytest.mark.parametrize("skill,doc", UNCHECKED, ids=[f"{s}:{d['path']}" for s, d in UNCHECKED])
def test_an_editable_document_with_no_checker_loses_no_text_on_the_trip(skill, doc):
    before = fixture(skill, doc["path"])["files"][doc["path"]]
    after = nb.round_trip(before)
    assert words(before) == words(after)
    assert nb.round_trip(after) == after


def test_a_read_only_document_type_needs_no_fixture():
    read_only = entries("read_only")
    assert read_only and not any(d in [e for _, e in EDITABLE] for _, d in read_only)
    assert any(fixture(s, d["path"]) is None for s, d in read_only)  # and nothing above asks one of it
