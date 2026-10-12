"""Offline tests of scripts/evidence.py, the field recorder (the reliability model, section 7; item B15 of
docs/architecture/final-plan-2026-10-02.md). Each test builds a small workbench in a temporary folder (the
recorder, the status script, a gate file, an adapter folder, one skill with its version file) and a project
beside it, and runs the recorder as a project would: flags only, no prompt, no network.

Run: uv run --with pytest pytest scripts/tests/test_evidence.py
"""
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("eval_status_evidence_test", REPO / "evals" / "eval_status.py")
es = importlib.util.module_from_spec(spec)
spec.loader.exec_module(es)

SKILL = '---\nname: core-demo\ndescription: A demo.\nmetadata:\n  version: "1.2.0"\n---\n\n# Demo\n\nIt does one job.\n'
GATE = {"strong_model": "s-model", "strong_harness": "h", "floor_model": "f-model", "floor_harness": "h",
        "floor_pass_env": [], "strong_pass_env": [], "grader": "s-model", "threshold": 0.8, "strong_tolerance": 0.05,
        "measurement_version": 5, "measurement_floor": 5,
        "models": {"s-model": ["provider/s-model"], "f-model": []}}


@pytest.fixture
def tree(tmp_path):
    wb = tmp_path / "workbench"
    (wb / "scripts").mkdir(parents=True)
    (wb / "evals").mkdir()
    shutil.copy(REPO / "scripts" / "evidence.py", wb / "scripts" / "evidence.py")
    shutil.copy(REPO / "evals" / "eval_status.py", wb / "evals" / "eval_status.py")
    (wb / "evals" / "eval-gate.json").write_text(json.dumps(GATE))
    (wb / "adapters" / "demo-harness").mkdir(parents=True)
    skill = wb / "skills" / "core-demo"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL)
    (skill / "evals" / "evals.json").write_text(json.dumps({"evals": [{"id": 1, "prompt": "p", "assertions": ["a"]}]}))
    line = {"version": "1.2.0", "content_sha256": es.content_hash(str(skill)), "class": "new", "date": "2030-01-01"}
    (skill / "evals" / "versions.jsonl").write_text(json.dumps(line) + "\n")
    # The skill as an installer copies it into a harness's folder: no evals/, and the installer's marker.
    installed = tmp_path / "home" / "skills" / "core-demo"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text(SKILL)
    (installed / ".installed-by-openhora").write_text("")
    project = tmp_path / "project"
    project.mkdir()
    return {"wb": wb, "skill": skill, "installed": installed, "project": project}


def run(tree, *args, code=0):
    r = subprocess.run([sys.executable, str(tree["wb"] / "scripts" / "evidence.py"), *map(str, args)],
                       capture_output=True, text=True, timeout=60, cwd=tree["project"])
    assert r.returncode == code, r.stderr
    return r


def start(tree, *extra):
    return run(tree, "record", "--start", "--skill-dir", tree["installed"], "--project", tree["project"], *extra).stdout.strip()


def lines(tree, skill="core-demo"):
    path = tree["project"] / ".workbench-local" / "evidence" / f"{skill}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_help_and_usage_errors(tree):
    assert "record --start" in run(tree, "--help").stdout
    assert "export --project" in run(tree, "record", "--help").stdout
    run(tree, code=2)
    run(tree, "record", "--start", "--skill-dir", tree["installed"], code=2)  # no --project
    run(tree, "record", "--start", "--verdict", "worked", "--use", "0" * 8, "--project", tree["project"], code=2)
    run(tree, "record", "--start", "--skill-dir", tree["installed"], "--project", tree["project"], "--note", "x", code=2)
    run(tree, "record", "--start", "--skill-dir", tree["installed"], "--project", tree["project"], "--model", code=2)
    run(tree, "frobnicate", code=2)


def test_record_start_writes_a_use_line_of_the_closed_form_and_prints_its_id(tree):
    use = start(tree)
    assert re.fullmatch(r"[0-9a-f]{8}", use)
    [line] = lines(tree)
    assert line == {"record": "use", "skill": "core-demo", "version": "1.2.0",
                    "content_sha256": es.content_hash(str(tree["skill"])), "model": "unknown", "adapter": "unknown",
                    "use": use, "week": line["week"]}
    assert re.fullmatch(r"\d{4}-W\d{2}", line["week"]) and es.field_line_problems(line, {"s-model", "f-model"}) == []
    assert start(tree) != use and len(lines(tree)) == 2  # one line per use, appended


def test_a_copy_installed_before_the_rename_keeps_the_hash_of_its_source(tree):
    """The legacy marker (T23) is left out of the hash as well: a copy made under the old name is still its source."""
    (tree["installed"] / ".installed-by-openhora").unlink()
    (tree["installed"] / ".installed-by-ai-workbench").write_text("")
    start(tree)
    assert lines(tree)[0]["content_sha256"] == es.content_hash(str(tree["skill"]))


def test_a_copied_skill_folder_with_its_marker_gives_the_hash_of_its_source(tree):
    start(tree)
    assert lines(tree)[0]["content_sha256"] == es.content_hash(str(tree["skill"]))
    (tree["installed"] / "SKILL.md").write_text(SKILL + "A local edit.\n")
    start(tree)
    assert lines(tree)[1]["content_sha256"] != es.content_hash(str(tree["skill"]))


@pytest.mark.parametrize("given, written", [
    ("s-model", "s-model"), ("provider/s-model", "s-model"), ("f-model", "f-model"), ("my-private-model", "unknown")])
def test_the_model_comes_from_the_flag_only_and_an_unlisted_one_is_unknown(tree, given, written):
    start(tree, "--model", given, "--adapter", "demo-harness")
    assert (lines(tree)[0]["model"], lines(tree)[0]["adapter"]) == (written, "demo-harness")


def test_an_adapter_that_is_not_a_folder_of_the_workbench_is_unknown(tree):
    start(tree, "--adapter", "some-tool")
    assert lines(tree)[0]["adapter"] == "unknown"


@pytest.mark.parametrize("word, score", [("worked", 1), ("corrected", 0.5), ("failed", 0)])
def test_a_verdict_is_a_word_of_a_closed_list_and_copies_its_use(tree, word, score):
    use = start(tree, "--model", "s-model")
    out = json.loads(run(tree, "record", "--verdict", word, "--use", use, "--project", tree["project"]).stdout)
    assert out == {"recorded": "verdict", "use": use, "score": score, "judge": "user"}
    first, verdict = lines(tree)
    assert verdict == {**first, "record": "verdict", "score": score, "judge": "user", "week": verdict["week"]}


def test_a_verdict_outside_the_list_or_for_an_unknown_use_is_refused(tree):
    use = start(tree)
    run(tree, "record", "--verdict", "ok", "--use", use, "--project", tree["project"], code=2)
    run(tree, "record", "--verdict", "worked", "--use", "user-42", "--project", tree["project"], code=2)
    run(tree, "record", "--verdict", "worked", "--use", "0123abcd", "--project", tree["project"], code=1)
    assert len(lines(tree)) == 1


def test_a_check_report_records_the_check_s_verdict(tree, tmp_path):
    use = start(tree)
    report = tmp_path / "report.json"
    for ok, score in ((True, 1), (False, 0)):
        report.write_text(json.dumps({"script": "lint_demo.py", "date": "2030-01-01", "arguments": {}, "ok": ok,
                                      "summary": "lint_demo", "errors": [] if ok else ["x"]}))
        run(tree, "record", "--check-report", report, "--use", use, "--project", tree["project"])
        assert lines(tree)[-1]["judge"] == "check" and lines(tree)[-1]["score"] == score
    report.write_text("{}")
    run(tree, "record", "--check-report", report, "--use", use, "--project", tree["project"], code=1)


def test_export_keeps_the_closed_form_and_drops_a_locally_edited_skill(tree, tmp_path):
    use = start(tree, "--model", "s-model")
    run(tree, "record", "--verdict", "failed", "--use", use, "--project", tree["project"])
    start(tree)  # a use with no verdict is a use
    (tree["installed"] / "SKILL.md").write_text(SKILL + "A local edit.\n")
    start(tree)
    path = tree["project"] / ".workbench-local" / "evidence" / "core-demo.jsonl"
    with path.open("a") as f:
        f.write(json.dumps({**lines(tree)[0], "note": "it went well"}) + "\n")
    out = tmp_path / "contribution.jsonl"
    summary = json.loads(run(tree, "export", "--project", tree["project"], "--out", out).stdout)
    assert summary["lines"] == 3 and summary["skills"] == ["core-demo"]
    assert summary["dropped"] == {"not of the closed form": 1, "an edited or unknown skill": 1}
    exported = [json.loads(l) for l in out.read_text().splitlines()]
    assert [l["record"] for l in exported] == ["use", "verdict", "use"]
    assert all(set(l) <= set(es.FIELD_VERDICT_KEYS) for l in exported)
    run(tree, "export", "--project", tree["project"], "--out", out, code=1)  # never overwrites


def test_import_names_the_file_by_its_hash_and_stores_no_account_name(tree, tmp_path):
    use = start(tree, "--model", "s-model")
    run(tree, "record", "--verdict", "worked", "--use", use, "--project", tree["project"])
    out = tmp_path / "from-ana@mail.example.jsonl"
    run(tree, "export", "--project", tree["project"], "--out", out)
    result = json.loads(run(tree, "import", "--file", out).stdout)
    [rel] = result["written"]
    data = (tree["wb"] / rel).read_bytes()
    assert rel == f"skills/core-demo/evals/evidence/field-{hashlib.sha256(data).hexdigest()[:12]}.jsonl"
    assert b"ana" not in data and "ana" not in rel
    assert es.field_file_problems(str(tree["wb"] / rel), str(tree["wb"])) == []
    assert es.evidence_problems(str(tree["wb"])) == ({}, 1)
    assert json.loads(run(tree, "import", "--file", out).stdout)["written"] == [rel]  # the same file: nothing new


@pytest.mark.parametrize("change, why", [
    ({"note": "it went well"}, "unknown key 'note'"),
    ({"count": 12}, "unknown key 'count'"),
    ({"week": "2030-03-04"}, "week must be YYYY-Www"),
    ({"skill": "core-other"}, "not a skill of this workbench"),
    ({"version": "1.1.0"}, "not the hash the version file gives"),
])
def test_import_refuses_a_whole_file_with_one_line_outside_its_form(tree, tmp_path, change, why):
    start(tree)
    good = lines(tree)[0]
    path = tmp_path / "contribution.jsonl"
    path.write_text(json.dumps(good) + "\n" + json.dumps({**good, **change}) + "\n")
    r = run(tree, "import", "--file", path, code=1)
    assert why in r.stderr and json.loads(r.stdout)["written"] == []
    assert not (tree["skill"] / "evals" / "evidence").exists()


def test_the_recorder_says_when_the_project_would_commit_its_evidence(tree):
    subprocess.run(["git", "init", "-q", str(tree["project"])], check=True)
    r = run(tree, "record", "--start", "--skill-dir", tree["installed"], "--project", tree["project"])
    assert "not ignored by git" in r.stderr
    (tree["project"] / ".gitignore").write_text(".workbench-local/\n")
    r = run(tree, "record", "--start", "--skill-dir", tree["installed"], "--project", tree["project"])
    assert "not ignored" not in r.stderr


def test_the_block_of_the_project_instruction_file_names_the_recorder_s_real_commands():
    block = (REPO / "skills" / "core-project-init" / "assets" / "agents-md-section.md").read_text()
    assert ("scripts/evidence.py record --start --skill-dir <the installed skill's folder> --project ." in block)
    assert "scripts/evidence.py record --verdict <worked | corrected | failed> --use <id> --project ." in block
    help_text = (REPO / "scripts" / "evidence.py").read_text()
    for flag in ("--start", "--skill-dir", "--project", "--verdict", "--use", "worked|corrected|failed"):
        assert flag in help_text
