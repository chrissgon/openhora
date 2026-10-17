"""Offline tests of `scripts/validate.py --foreign <folder>`: the per-skill checks of the validator on a skill from outside the
repository (package IMPORT-CLI), and the unchanged normal run.

Run: uv run --with pytest pytest scripts/tests/test_validate_foreign.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "import"

spec = importlib.util.spec_from_file_location("validate_under_test", REPO / "scripts" / "validate.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
es = v.load_eval_status()


def skill(tmp_path, name="eng-web-notes", extra_meta="", body=None, cases=True, gate=False):
    """A normalized-looking skill folder: the fixture's body, a frontmatter of the workbench's form, a version file at its content."""
    folder = tmp_path / "home" / name
    shutil.copytree(FIX / "web-notes", folder)
    text = (folder / "SKILL.md").read_text()
    body = text.split("\n---", 2)[-1] if body is None else body
    front = (f"---\nname: {name}\ndescription: >\n  Turn a saved web page into short study notes. Use when someone gives you an article.\nlicense: MIT\n"
             f"metadata:\n  area: engineering\n  kind: capability\n  inputs: []\n  outputs: []\n  updates: []\n  requires: []\n"
             f"  side_effects: []\n{extra_meta}  version: \"0.1.0\"\n---")
    (folder / "SKILL.md").write_text(front + body + ("\n## Confirmation gate\n\nAsk first.\n" if gate else ""))
    if cases:
        data = json.loads((FIX / "cases" / "evals.json").read_text())
        data["skill_name"] = name
        (folder / "evals").mkdir(exist_ok=True)
        (folder / "evals" / "evals.json").write_text(json.dumps(data))
        shutil.copytree(FIX / "cases" / "files", folder / "evals" / "files", dirs_exist_ok=True)
    seal(folder)
    return folder


def seal(folder):
    (folder / "evals").mkdir(exist_ok=True)
    (folder / "evals" / "versions.jsonl").write_text(json.dumps({"version": "0.1.0", "content_sha256": es.content_hash(str(folder)), "class": "new",
                                                               "date": "2030-01-01"}) + "\n")


def foreign(folder, *extra):
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "validate.py"), "--foreign", str(folder), "--json", *extra],
                          capture_output=True, text=True, cwd=REPO)
    return done.returncode, json.loads(done.stdout)


def messages(report, kind):
    return [f"{item['where']}: {item['message']}" for item in report[kind]]


def test_a_clean_skill_from_outside_passes_and_the_summary_lists_what_was_skipped(tmp_path):
    folder = skill(tmp_path)
    code, report = foreign(folder)
    assert code == 0, report
    assert report["summary"]["ok"] is True and report["summary"]["errors"] == 0 and report["summary"]["foreign"] == str(folder)
    assert "the artifact contract against the table of owning skills" in report["summary"]["skipped"]
    assert "the class checks against a base commit" in report["summary"]["skipped"]
    assert report["errors"] == []


def test_the_per_skill_checks_apply_to_the_folder(tmp_path):
    folder = skill(tmp_path)
    text = (folder / "SKILL.md").read_text().replace("name: eng-web-notes", "name: eng-other").replace("kind: capability", "kind: banana")
    (folder / "SKILL.md").write_text(text)
    seal(folder)
    code, report = foreign(folder)
    errors = " | ".join(messages(report, "errors"))
    assert code == 1 and "must equal folder name" in errors and "metadata.kind" in errors


def test_a_gate_heading_is_required_when_an_effect_is_declared_and_a_guard_is_required_per_effect(tmp_path):
    folder = skill(tmp_path)
    text = (folder / "SKILL.md").read_text().replace("side_effects: []", "side_effects: [push]")
    (folder / "SKILL.md").write_text(text)
    seal(folder)
    code, report = foreign(folder)
    errors = " | ".join(messages(report, "errors"))
    assert code == 1 and "no '## Confirmation gate' section" in errors and "[guard-effect]" in errors and "guard:<effect>" in errors
    (folder / "SKILL.md").write_text(text + "\n## Confirmation gate\n\nAsk first.\n")
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"][0]["assertions"].append({"text": "The reply asks for an explicit yes before it pushes", "tags": ["guard:push"]})
    data["evals"][0]["tags"] = ["guard:push"]
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    seal(folder)
    code, report = foreign(folder)
    assert code == 0, report


def test_a_guard_is_asked_for_when_the_skill_has_stop_rules_a_gate_or_reads_external_content(tmp_path):
    folder = skill(tmp_path, gate=False)
    (folder / "SKILL.md").write_text((folder / "SKILL.md").read_text() + "\n## Stop rules\n\n1. No page, no notes: stop and ask.\n")
    seal(folder)
    code, report = foreign(folder)
    assert code == 0 and any("[guard-missing]" in m or "no assertion is tagged guard" in m for m in messages(report, "warnings"))


def test_the_case_findings_are_the_repositorys(tmp_path):
    folder = skill(tmp_path)
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"][0]["assertions"] = ["If the page is short, the notes are short", "The tests are run"]
    data["evals"][1]["prompt"] = "Use eng-web-notes to make cards from saved-page.md."
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    seal(folder)
    code, report = foreign(folder)
    warnings = " | ".join(messages(report, "warnings"))
    assert code == 0
    for rule in ("[eval-assertions-count]", "[eval-conditional-assertion]", "[eval-run-assertion]", "[eval-prompt-names-skill]"):
        assert rule in warnings


def test_a_harness_name_and_text_that_is_not_english_are_warnings_and_not_errors(tmp_path):
    folder = skill(tmp_path)
    settings = sorted(d.split("/")[0] for d in _skills_dirs())
    (folder / "references" / "style.md").write_text(f"Save the notes under the {settings[0]} folder.\n\nIsto n{chr(0xe3)}o {chr(0xe9)} ingl{chr(0xea)}s.\n")
    seal(folder)
    code, report = foreign(folder)
    warnings = messages(report, "warnings")
    assert code == 0 and report["summary"]["errors"] == 0
    assert any("[harness-name]" in w and "bound to that tool" in w and "references/style.md" in w for w in warnings)
    assert any("[english-only]" in w and "references/style.md" in w for w in warnings)


def _skills_dirs():
    out = set()
    for eval_json in sorted((REPO / "adapters").glob("*/eval.json")):
        out.add(json.loads(eval_json.read_text())["skills_dir"])
    return out


def test_the_content_must_be_the_last_line_of_the_version_file(tmp_path):
    folder = skill(tmp_path)
    (folder / "references" / "style.md").write_text("An edit made by hand.\n")
    code, report = foreign(folder)
    assert code == 1 and any("[version-file]" in m and "not the last line of evals/versions.jsonl" in m for m in messages(report, "errors"))
    (folder / "evals" / "versions.jsonl").unlink()
    code, report = foreign(folder)
    assert code == 1 and any("evals/versions.jsonl is missing" in m for m in messages(report, "errors"))
    (folder / "evals" / "versions.jsonl").write_text("not json\n")
    code, report = foreign(folder)
    assert code == 1 and any("not valid JSON" in m for m in messages(report, "errors"))


def test_a_path_the_workbench_already_owns_is_a_warning(tmp_path):
    taken = next(p for s in v.declarations(REPO) for p in s["outputs"])
    folder = skill(tmp_path)
    text = (folder / "SKILL.md").read_text().replace("outputs: []", f"outputs: [{taken}]")
    (folder / "SKILL.md").write_text(text)
    seal(folder)
    code, report = foreign(folder)
    assert code == 0 and any("[owner-clash]" in m and "one owner" in m for m in messages(report, "warnings"))


def test_a_skill_with_no_skill_md_and_a_skill_over_the_line_limit_are_errors(tmp_path):
    empty = tmp_path / "home" / "eng-empty"
    empty.mkdir(parents=True)
    code, report = foreign(empty)
    assert code == 1 and "missing SKILL.md" in " ".join(messages(report, "errors"))
    folder = skill(tmp_path)
    (folder / "SKILL.md").write_text((folder / "SKILL.md").read_text() + "\nA line.\n" * 520)
    seal(folder)
    code, report = foreign(folder)
    assert code == 1 and "limit is 500" in " ".join(messages(report, "errors"))


def test_strict_turns_warnings_into_errors_and_the_usage_is_checked(tmp_path):
    folder = skill(tmp_path, cases=False)
    code, report = foreign(folder)
    assert code == 0 and any("eval-cases-count" in m for m in messages(report, "warnings"))
    code, report = foreign(folder, "--strict")
    assert code == 1
    for argv in (["--foreign"], ["--foreign", str(folder), "--spec"]):
        done = subprocess.run([sys.executable, str(REPO / "scripts" / "validate.py"), *argv], capture_output=True, text=True, cwd=REPO)
        assert done.returncode == 2 and "--foreign takes a folder" in done.stderr


def test_nothing_of_the_folder_is_executed(tmp_path):
    marker = tmp_path / "ran"
    folder = skill(tmp_path)
    (folder / "scripts" / "boom.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    seal(folder)
    foreign(folder)
    assert not marker.exists()


def test_the_normal_run_is_unchanged_and_documents_the_new_option():
    doc = v.__doc__
    assert "--foreign <folder>" in doc and "The normal run, with no --foreign, is unchanged" in doc
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "validate.py"), "--bogus"], capture_output=True, text=True, cwd=REPO)
    assert done.returncode == 2 and "unknown option" in done.stderr
