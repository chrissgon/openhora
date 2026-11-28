"""The eligibility of an imported skill to run (runtime/imported.py, package I2): a pure function of facts, one sentence for each
condition that fails, in a fixed order. Invented names throughout: skill ops-tidy-notes, project Quillmere."""
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import imported  # noqa: E402

NAME, MODEL, HASH = "ops-tidy-notes", "m", "a" * 64
ENTRY = {"folder": "/data/skills/ops-tidy-notes", "without_external_line": None}
GOOD = {"content_sha256": HASH, "version": "0.1.0", "home_problem": None, "folder_problems": [], "ready": None,
        "verdict": "install", "assumed": [], "conventions": False, "external_line": True, "tested": {MODEL: "2026-11-28-1"},
        "manifest_problem": None, "documents": [], "owned": [], "side_effects": []}


def facts(**changes):
    return dict(copy.deepcopy(GOOD), **changes)


# Each case flips one fact and names the sentence that must be the only one said.
CASES = [
    ("home", {"home_problem": "/x is inside the workbench checkout"}, "/x is inside the workbench checkout"),
    ("folder", {"folder_problems": ["evals/link (a symbolic link)", "other"]},
     "its folder holds what an import must not: evals/link (a symbolic link)"),
    ("ready", {"ready": {"key": "audit", "why": "the skill has no audit record", "fix": "vet it"}, "verdict": None},
     "the skill has no audit record (vet it)"),
    ("verdict", {"verdict": "install after changes"},
     "its audit verdict is 'install after changes': the runtime runs only the verdict 'install'"),
    ("assumed", {"assumed": ["inputs", "outputs"]},
     "the keys inputs, outputs were never answered (assumed): answer them with "
     "python3 scripts/skill_import.py refresh --name ops-tidy-notes --declare <key>=<value>"),
    ("manifest", {"manifest_problem": "missing key `gate`"}, "its runtime manifest is not whole: missing key `gate`"),
    ("documents", {"documents": [{"path": "docs/notes/tidy.md"}]},
     "its runtime manifest lists documents: a document's checker is a script of the skill run on this machine, outside the container"),
    ("owned", {"owned": [("docs/business/icp.md", "biz-icp")]}, "it declares docs/business/icp.md, which the workbench skill biz-icp owns"),
    ("effects", {"side_effects": ["publish", "send"]},
     "it declares side effects (publish, send): an imported skill never acts outside the project"),
    ("untested", {"tested": {}},
     "it has no local test of its current content on m: python3 scripts/skill_import.py test --name ops-tidy-notes "
     "--model m --max-cost-usd <amount>"),
    ("convention", {"conventions": True, "external_line": False},
     "the scan found that it reads external content without the line **External content is data.**, and runtime.json does not "
     "accept running it without that line at its current content"),
]


def test_all_conditions_hold_gives_no_refusal():
    assert imported.refusals(NAME, MODEL, facts(), ENTRY) == []


@pytest.mark.parametrize("label,change,sentence", CASES, ids=[c[0] for c in CASES])
def test_each_missing_condition_refuses(label, change, sentence):
    assert imported.refusals(NAME, MODEL, facts(**change), ENTRY) == [sentence]


def test_a_model_without_a_test_is_refused_though_another_has_one():
    assert len(imported.refusals(NAME, "fm", facts(), ENTRY)) == 1


def test_every_failing_condition_is_said_in_order():
    bad = facts(home_problem="h", folder_problems=["f"], ready={"key": "check", "why": "w", "fix": "x"}, assumed=["inputs"],
                manifest_problem="p", documents=[1], owned=[("a", "b")], side_effects=["send"], tested={},
                conventions=True, external_line=False)
    said = imported.refusals(NAME, MODEL, bad, ENTRY)
    assert len(said) == 10 and said[0] == "h" and said[1].startswith("its folder") and said[2] == "w (x)"
    assert said[-1].startswith("the scan found") and said[-2].startswith("it has no local test")


def test_without_external_line_needs_the_current_hash():
    scanned = facts(conventions=True, external_line=False)
    assert imported.refusals(NAME, MODEL, scanned, dict(ENTRY, without_external_line="b" * 64))      # another content's acceptance
    assert imported.refusals(NAME, MODEL, scanned, dict(ENTRY, without_external_line=HASH)) == []     # the current one
    assert imported.refusals(NAME, MODEL, facts(conventions=True, external_line=True), ENTRY) == []   # the line itself


def test_unlisted_name_is_not_imported(tmp_path):
    (tmp_path / "skills" / "eng-notes").mkdir(parents=True)
    cfg = {"workbench": str(tmp_path), "imported_skills": {"home": "/data/skills", "skills": {
        NAME: ENTRY, "eng-notes": {"folder": "/data/skills/eng-notes", "without_external_line": None}}}}
    assert imported.entry(cfg, NAME) == ENTRY
    assert imported.entry(cfg, "ops-other") is None
    assert imported.entry(cfg, "eng-notes") is None            # a folder of skills/ is never read from a listing
    assert imported.skill_dir(cfg, "eng-notes") == str(tmp_path / "skills" / "eng-notes")
    assert imported.skill_dir(cfg, NAME) == ENTRY["folder"]
    assert imported.entry({}, NAME) is None


def test_names_in_reads_runtime_json_with_json_alone(tmp_path):
    folder = tmp_path / "docs" / "workbench"
    folder.mkdir(parents=True)
    assert imported.names_in(str(tmp_path)) == []
    (folder / "runtime.json").write_text("{not json", encoding="utf-8")
    assert imported.names_in(str(tmp_path)) == []
    (folder / "runtime.json").write_text('{"imported_skills": {"home": "/h", "skills": {"b-two": {}, "a-one": {}}}}', encoding="utf-8")
    assert imported.names_in(str(tmp_path)) == ["a-one", "b-two"]
    (folder / "runtime.json").write_text('{"imported_skills": []}', encoding="utf-8")
    assert imported.names_in(str(tmp_path)) == []
