"""Offline tests of a skill from outside in the lab (package IMPORT-CLI): `eval_run.py --skill-dir`, its refusals, the local evidence
it writes under imported/<name>/ with "imported": true, `eval_status.py status --skill-dir`, the validator's refusal of such a file
under skills/, and the warning a full or a quick test prints on content the version file does not name (a follow-up of package P11).
No model is called: a stand-in adapter answers, as in test_eval_run.py, and the fixtures are those of scripts/tests/fixtures/import/.

Run: uv run --with pytest pytest evals/tests/test_imported_skill.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "scripts" / "tests" / "fixtures" / "import"


def load(module, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{module}.py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


tb = load("test_bands", "bands_tests_for_imported_skill")
t = load("test_eval_run", "eval_run_tests_for_imported_skill")
er, es = t.er, tb.es


@pytest.fixture(autouse=True)
def own_lock_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er.KIT, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er, "RETRY_PAUSE", 0)
    monkeypatch.setattr(er.KIT, "RETRY_PAUSE", 0)


def local_base():
    return Path(os.environ["WB_LOCAL_EVIDENCE_DIR"])


def standin(tmp_path, monkeypatch, runner=None):
    """A temporary tree as the root of the runner, with a stand-in adapter h and a gate file; no skill under skills/."""
    t.as_in_the_container(monkeypatch)
    adapter = tmp_path / "adapters" / "h"
    adapter.mkdir(parents=True)
    (adapter / "eval.json").write_text(t.EVAL_JSON)
    (adapter / "run-prompt.sh").write_text(runner or t.SCORES)
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(er.KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path, tolerance=0.05, runs=3)


def imported(tmp_path, tmp_path_factory, name="demo", cases=None, verdict="install", audit=True, check=True):
    """A skill folder outside the root (named like the skill the stand-in adapter looks for), with its version file, its cases, a check
    that passed and an audit record, both at its current content."""
    folder = tmp_path_factory.mktemp("home") / name
    (folder / "evals" / "import").mkdir(parents=True)
    (folder / "SKILL.md").write_text(t.SKILL_MD.replace("name: demo", f"name: {name}"))
    cases = cases or [{"id": 1, "prompt": "p", "assertions": ["a"]}, {"id": 2, "prompt": "q", "assertions": ["a"]}]
    (folder / "evals" / "evals.json").write_text(json.dumps({"skill_name": name, "evals": cases}))
    content = es.content_hash(str(folder))
    (folder / "evals" / "versions.jsonl").write_text(json.dumps({"version": "0.3.0", "content_sha256": content, "class": "new", "date": "2030-01-01"}) + "\n")
    if audit:
        (folder / "evals" / "import" / "audit.json").write_text(json.dumps(
            {"verdict": verdict, "record": "vetting-2030-01-02.md", "record_sha256": "0" * 64, "content_sha256": content, "date": "2030-01-02"}))
    if check:
        (folder / "evals" / "import" / "check.json").write_text(json.dumps({"ok": True, "content_sha256": content, "date": "2030-01-02"}))
    return folder


def reseal(folder, verdict="install"):
    """A check and an audit at the content the folder has now (what a person does after an edit)."""
    content = es.content_hash(str(folder))
    (folder / "evals" / "import" / "audit.json").write_text(json.dumps(
        {"verdict": verdict, "record": "r.md", "record_sha256": "0" * 64, "content_sha256": content, "date": "2030-01-03"}))
    (folder / "evals" / "import" / "check.json").write_text(json.dumps({"ok": True, "content_sha256": content, "date": "2030-01-03"}))


def run_main(capsys, *argv):
    code = er.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- the options -------------------------------------------------------------------------------------------------------------

def test_skill_dir_names_the_skill_by_its_folder_and_is_exclusive_with_skill(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    o = er.parse(["--skill-dir", str(folder), "--quick"])
    assert (o["skill"], o["skill_dir"], o["quick"]) == ("demo", str(folder), True) and er.skill_folder(o) == str(folder)
    with pytest.raises(SystemExit) as e:
        er.parse(["--skill-dir", str(folder), "--skill", "demo"])
    assert e.value.code == 2 and "exclusive" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--pass-env", "SOME_VARIABLE"], ["--harness", "h"], ["--platform", "net"], ["--routing", "--pack", "default"],
                                   ["--regrade", "/x"], ["--resume", "/x"], ["--close", "/x"]])
def test_what_a_skill_from_outside_never_takes_is_refused(tmp_path, tmp_path_factory, monkeypatch, capsys, extra):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    with pytest.raises(SystemExit) as e:
        er.parse(["--skill-dir", str(folder), "--model", "m"] + extra)
    assert e.value.code == 2 and "--skill-dir does not go with" in capsys.readouterr().err


def test_a_folder_that_is_not_a_skill_a_misnamed_one_and_one_named_like_a_skill_of_the_repository_are_refused(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    home = tmp_path_factory.mktemp("home")
    (home / "empty").mkdir()
    (home / "Bad_Name").mkdir()
    (home / "Bad_Name" / "SKILL.md").write_text("x\n")
    for folder, why in ((home / "empty", "no SKILL.md"), (home / "Bad_Name", "lowercase")):
        with pytest.raises(SystemExit):
            er.parse(["--skill-dir", str(folder)])
        assert why in capsys.readouterr().err
    (tmp_path / "skills" / "demo").mkdir(parents=True)
    taken = imported(tmp_path, tmp_path_factory)
    with pytest.raises(SystemExit):
        er.parse(["--skill-dir", str(taken)])
    assert "name of a skill of the repository" in capsys.readouterr().err


def test_a_folder_inside_the_checkout_is_refused(tmp_path, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    (tmp_path / "somewhere" / "demo").mkdir(parents=True)
    (tmp_path / "somewhere" / "demo" / "SKILL.md").write_text("x\n")
    with pytest.raises(SystemExit):
        er.parse(["--skill-dir", str(tmp_path / "somewhere" / "demo")])
    assert "inside a checkout of the workbench" in capsys.readouterr().err


def test_a_folder_inside_another_checkout_of_the_workbench_is_refused(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    other = tmp_path_factory.mktemp("elsewhere")
    for rel in ("evals/eval-gate.json", "scripts/skill_import.py"):
        (other / rel).parent.mkdir(parents=True, exist_ok=True)
        (other / rel).write_text("")
    folder = other / "imports" / "demo"
    (folder).mkdir(parents=True)
    (folder / "SKILL.md").write_text(t.SKILL_MD)
    with pytest.raises(SystemExit) as e:
        er.parse(["--skill-dir", str(folder)])
    assert e.value.code == 2 and "inside a checkout of the workbench" in capsys.readouterr().err


def test_allow_web_cases_goes_with_skill_dir_only(tmp_path, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        er.parse(["--skill", "demo", "--allow-web-cases"])
    assert "goes with --skill-dir" in capsys.readouterr().err


# --- the real check of the cases of a fixture (the repository's own root, no model) --------------------------------------------

def fixture_folder(tmp_path, name="eng-web-notes"):
    folder = tmp_path / "home" / name
    shutil.copytree(FIX / "web-notes", folder)
    text = (folder / "SKILL.md").read_text().replace("name: web-notes", f"name: {name}")
    (folder / "SKILL.md").write_text(text)
    data = json.loads((FIX / "cases" / "evals.json").read_text())
    data["skill_name"] = name
    (folder / "evals").mkdir()
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    shutil.copytree(FIX / "cases" / "files", folder / "evals" / "files")
    return folder


def test_check_cases_and_dry_run_work_on_a_fixture_with_no_audit(tmp_path, capsys):
    folder = fixture_folder(tmp_path)
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--check-cases")
    assert code == 0, err
    assert json.loads(out)["cases"] == 2 and json.loads(out)["errors"] == []
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "claude-sonnet-5-5", "--dry-run")
    plan = json.loads(out)
    assert code == 0, err
    assert plan["evidence_home"]["home"] == "local" and plan["imported"]["kept_as"] == "imported/eng-web-notes"
    assert any("no audit record" in why for why in plan["imported"]["refused"])  # a plan says what an event would be refused for
    assert [r["case"] for r in plan["runs"]] == [1, 2] and all(r["variant"] == "with_skill" for r in plan["runs"])


def test_a_case_that_copies_workbench_files_is_refused_even_in_a_plan(tmp_path, capsys):
    folder = fixture_folder(tmp_path)
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"][0]["workbench_files"] = ["contracts/state.md"]
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--check-cases")
    assert code == 2 and "workbench_files is not allowed" in err
    with pytest.raises(SystemExit) as e:
        er.main(["--skill-dir", str(folder), "--quick", "--model", "claude-sonnet-5-5", "--dry-run"])
    assert e.value.code == 2


def test_a_web_case_needs_the_flag_and_the_preflight_leaves_the_gate_files_list_to_it(tmp_path, capsys):
    folder = fixture_folder(tmp_path)
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"][1]["allow_web"] = True
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--check-cases")
    assert code == 2 and "web_cases" in err
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--check-cases", "--allow-web-cases")
    assert code == 0, err


# --- the refusals at the start of an event ----------------------------------------------------------------------------------

def refused(capsys, folder, *extra):
    with pytest.raises(SystemExit) as e:
        er.main(["--skill-dir", str(folder), "--quick", "--model", "m"] + list(extra))
    assert e.value.code == 2
    return capsys.readouterr().err


def test_an_event_is_refused_with_no_audit_record(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory, audit=False)
    assert "no audit record" in refused(capsys, folder)
    assert t.calls(tmp_path) == [] and not list(local_base().glob("**/*.jsonl"))


def test_an_event_is_refused_with_a_verdict_of_do_not_install_and_after_a_change_that_voids_the_audit(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    bad = imported(tmp_path, tmp_path_factory, verdict="do not install")
    assert "do not install" in refused(capsys, bad)
    changed = imported(tmp_path, tmp_path_factory, name="demo")
    (changed / "SKILL.md").write_text((changed / "SKILL.md").read_text() + "A line added after the audit.\n")
    assert "audit is void" in refused(capsys, changed)
    unknown = imported(tmp_path, tmp_path_factory, verdict="maybe")
    assert "no verdict of" in refused(capsys, unknown)
    assert t.calls(tmp_path) == []


def test_an_event_is_refused_when_the_folder_holds_a_link_or_a_special_file(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    secret = tmp_path / "private.txt"
    secret.write_text("not for a run\n")
    os.symlink(secret, folder / "evals" / "private-link")
    assert "evals/private-link" in refused(capsys, folder)
    os.remove(folder / "evals" / "private-link")
    os.mkfifo(folder / "evals" / "pipe")
    assert "a pipe" in refused(capsys, folder)
    assert t.calls(tmp_path) == []


def test_a_web_case_runs_only_with_the_flag_and_the_verdict_install(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    cases = [{"id": 1, "prompt": "p", "assertions": ["a"], "allow_web": True}, {"id": 2, "prompt": "q", "assertions": ["a"]}]
    folder = imported(tmp_path, tmp_path_factory, cases=cases, verdict="install after changes")
    assert "--allow-web-cases" in refused(capsys, folder)
    assert "needs the verdict" in refused(capsys, folder, "--allow-web-cases")
    folder = imported(tmp_path, tmp_path_factory, cases=cases, verdict="install")
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m", "--allow-web-cases", "--dry-run")
    assert code == 0 and json.loads(out)["imported"]["refused"] == []
    assert [r["allow_web"] for r in json.loads(out)["runs"]] == [True, False]


def test_an_event_is_refused_without_a_check_that_passed_at_the_current_content(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory, check=False)
    assert "has not passed" in refused(capsys, folder)
    (folder / "evals" / "import" / "check.json").write_text(json.dumps({"ok": False, "content_sha256": es.content_hash(str(folder))}))
    assert "has not passed" in refused(capsys, folder)
    (folder / "evals" / "import" / "check.json").write_text(json.dumps({"ok": True, "content_sha256": "0" * 64}))
    assert "has not passed" in refused(capsys, folder)
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m", "--dry-run")  # a plan says so without refusing
    assert code == 0 and any("has not passed" in why for why in json.loads(out)["imported"]["refused"])
    assert t.calls(tmp_path) == []


@pytest.mark.parametrize("name", [".installed-by-openhora", "__pycache__", ".DS_Store", ".git", ".GIT", "HEAD", "commondir"])
def test_an_event_is_refused_when_the_content_holds_an_install_marker_or_a_cache_name(tmp_path, tmp_path_factory, monkeypatch, capsys, name):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    target = folder / "scripts" / name
    target.parent.mkdir(exist_ok=True)
    if name == "__pycache__":
        target.mkdir()
    else:
        target.write_text("a marker that the content hash leaves out\n")
    assert name in refused(capsys, folder) and "install marker" in refused(capsys, folder)
    assert t.calls(tmp_path) == []


def test_the_event_runs_from_one_copy_made_at_its_start_and_a_change_of_the_folder_meanwhile_is_not_evidence(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    start = es.content_hash(str(folder))
    seen, real = [], er.stage_run

    def spy(case_dir, eval_cfg, variant_dir, deps, case, platform=None):
        if variant_dir:
            seen.append((variant_dir, es.content_hash(variant_dir)))
        (folder / "SKILL.md").write_text((folder / "SKILL.md").read_text() + "An edit made while the event runs.\n")
        return real(case_dir, eval_cfg, variant_dir, deps, case, platform)
    monkeypatch.setattr(er, "stage_run", spy)
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")
    result = json.loads(out)
    assert seen and all(path != str(folder) for path, _ in seen)  # every run was staged from the copy
    assert {h for _, h in seen} == {start}  # the copy is the content that was checked and audited, whatever happened to the folder
    assert not os.path.exists(seen[0][0])  # the copy is removed when the invocation ends
    assert result["evidence"]["written"] is False and "changed during the event" in result["evidence"]["reason"]
    assert es.content_hash(str(folder)) != start


# --- the stand-in quick event ---------------------------------------------------------------------------------------------------

def test_a_quick_test_of_a_skill_from_outside_writes_local_evidence_under_imported_and_nothing_in_the_checkout(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")
    assert code == 0, err
    result = json.loads(out)
    assert result["complete"] is True and result["evidence"]["written"] is True and result["evidence"]["home"] == "local"
    files = sorted((local_base() / "imported" / "demo").glob("lab-*.jsonl"))
    assert len(files) == 1 and result["evidence"]["path"] == str(files[0])
    assert not (local_base() / "demo").exists()  # never beside the skills of the repository
    lines = [json.loads(l) for l in files[0].read_text().splitlines()]
    event, runs = lines[0], lines[1:]
    assert event["imported"] is True and event["kind"] == "quick" and event["skill"] == "demo" and event["runs"] == 1 and event["complete"] is True
    assert event["baseline"] == {"1": "none", "2": "none"} and "gate" not in event
    assert {(l["case"], l["variant"], l["kind"], l["model"]) for l in runs} == {(c, "with", "quick", "m") for c in (1, 2)}
    assert es.evidence_file_problems(str(files[0]), str(tmp_path), "demo") == []  # a person's local file is read by its own event line
    assert sorted(t.calls(tmp_path)) == ["p with m", "q with m"]  # the skill was staged under its folder's name
    assert not (tmp_path / "skills").exists()
    assert not [p for p in tmp_path.glob("**/evidence/*.jsonl") if "evals-workspace" not in p.parts]  # only the run folder's own copy
    assert "stays on this machine" in err and "--skill-dir" in err and "preliminary" in err


def test_resume_alone_resumes_an_imported_event_and_the_audit_is_checked_again(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    t.mark(tmp_path, "down-q-with-m")  # the run of case 2 fails in its adapter: the event stays open
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")
    assert code == 1
    event = tmp_path / json.loads(out)["iteration_dir"]
    audit = folder / "evals" / "import" / "audit.json"
    good = audit.read_text()
    audit.write_text(json.dumps({**json.loads(good), "verdict": "do not install"}))
    with pytest.raises(SystemExit) as e:
        er.main(["--resume", str(event)])
    assert e.value.code == 2 and "do not install" in capsys.readouterr().err  # the audit is read again at the resumption
    audit.write_text(good)
    t.mark(tmp_path, "down-q-with-m", on=False)
    code, out, err = run_main(capsys, "--resume", str(event))  # no --skill-dir: the event keeps the options it started with
    assert code == 0 and json.loads(out)["evidence"]["written"] is True
    assert len(list((local_base() / "imported" / "demo").glob("lab-*.jsonl"))) == 1


def test_the_status_of_a_skill_from_outside_says_preliminary_quick_test_only_and_that_it_counts_on_this_machine_only(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    assert es.imported_status(str(tmp_path), str(folder), es.load_gate(str(tmp_path)), str(local_base()))["models"] == {}
    assert run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")[0] == 0
    status = es.imported_status(str(tmp_path), str(folder), es.load_gate(str(tmp_path)), str(local_base()))
    assert status["imported"] is True and status["skill"] == "demo" and status["version"] == "0.3.0" and status["folder"] == str(folder)
    figures = status["models"]["m"]
    assert figures["preliminary"] == "preliminary: quick test only" and figures["kinds"] == ["quick"]
    assert figures["scope"] == "your machine only, not checkable by others" and figures["cases"] == "measured against your own cases, which nobody else has read"
    assert figures["runs"] == 2 and figures["mean"] == 1.0 and figures["tests"] == 1 and figures["last_full_test"] is None
    assert figures["band"] == "needs a test"  # a quick test alone never moves the band
    commands = [figures["command"]] + [c["command"] for c in figures["causes"]]
    assert all("--skill-dir" in c and f"--skill {folder.name}" not in c for c in commands if c)
    assert es.local_skill_evidence("demo", str(local_base())) == []  # nothing of it is the evidence of a skill named demo
    # the command line prints the same
    assert es.main(["status", "--skill-dir", str(folder)], root=str(tmp_path)) == 0
    assert json.loads(capsys.readouterr().out)["models"]["m"]["preliminary"] == "preliminary: quick test only"


def test_other_tests_than_quick_ones_are_preliminary_until_a_full_test_or_a_closed_pool_stands_behind_them(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    assert run_main(capsys, "--skill-dir", str(folder), "--model", "m", "--cases", "1")[0] == 0
    figures = es.imported_status(str(tmp_path), str(folder), es.load_gate(str(tmp_path)), str(local_base()))["models"]["m"]
    assert figures["preliminary"] == "preliminary: no full test and no closed pool yet" and figures["kinds"] == ["partial"]
    assert run_main(capsys, "--skill-dir", str(folder), "--model", "m")[0] == 0
    figures = es.imported_status(str(tmp_path), str(folder), es.load_gate(str(tmp_path)), str(local_base()))["models"]["m"]
    assert figures["preliminary"] is None and figures["last_full_test"]["passed"] is True and figures["scope"].startswith("your machine only")
    assert figures["kinds"] == ["full", "partial"]


def test_a_second_event_after_a_hand_edit_names_the_lines_the_version_file_does_not_name(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    assert run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")[0] == 0
    (folder / "SKILL.md").write_text((folder / "SKILL.md").read_text() + "An edit made by hand.\n")
    # the audit is void now: the edit is refused until it is vetted again
    assert "audit is void" in refused(capsys, folder)
    reseal(folder)
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")
    assert code == 0 and "unbumped edit" in err and "skill_import.py bump --name demo" in err and "not a refusal" in err
    figures = es.imported_status(str(tmp_path), str(folder), es.load_gate(str(tmp_path)), str(local_base()))["models"]["m"]
    assert figures["unnamed_lines"] == 2 and "skill_import.py bump" in figures["cause"]
    assert all("eval_status.py bump" not in c["command"] for c in figures["causes"])


# --- the evidence of a skill from outside never enters the repository ------------------------------------------------------------------

def test_the_closed_form_of_the_marker(tmp_path):
    root = tmp_path
    folder = tb.skill(root)
    tb.versions(folder, ("1.0.0", "new"))
    path = tb.full(folder, score=0.9)
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    assert es.evidence_file_problems(str(path), str(root), "core-demo") == []
    lines[0]["imported"] = True
    path.write_text("".join(json.dumps(l) + "\n" for l in lines))
    assert es.evidence_file_problems(str(path), str(root), "core-demo") == []  # a person's local file carries it legally
    lines[0]["imported"] = False
    path.write_text("".join(json.dumps(l) + "\n" for l in lines))
    assert any("imported must be true" in p for p in es.evidence_file_problems(str(path), str(root), "core-demo"))
    assert "imported" in es.EVENT_OPTIONAL


def test_the_validator_refuses_a_committed_evidence_file_that_carries_the_marker(tmp_path):
    root = tmp_path
    folder = tb.skill(root)
    tb.versions(folder, ("1.0.0", "new"))
    path = tb.full(folder, score=0.9)
    found, checked = es.evidence_problems(str(root))
    assert found == {} and checked == 1
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    lines[0]["imported"] = True
    path.write_text("".join(json.dumps(l) + "\n" for l in lines))
    found, _ = es.evidence_problems(str(root))
    (rel, problems), = found.items()
    assert rel.endswith(path.name) and any("stays in the person's local evidence folder" in p for p in problems)


# --- the warning of a full or a quick test on content the version file does not name (follow-up of package P11) ---------------------------------

def bumped(skill):
    """The version file names the skill's current content as its last line."""
    skill_md = skill / "SKILL.md"
    (skill / "evals" / "versions.jsonl").write_text(json.dumps({"version": "0.3.0", "content_sha256": es.content_hash(str(skill)), "class": "new",
                                                               "date": "2030-01-01"}) + "\n")
    return skill_md


def test_a_full_and_a_quick_test_on_an_unbumped_edit_warn_on_stderr_and_still_run(tmp_path, monkeypatch, capsys):
    skill = t.scores_demo(tmp_path, monkeypatch)
    skill_md = bumped(skill)
    code, out, err = run_main(capsys, "--skill", "demo", "--quick", "--scratch")
    assert code == 0 and "unbumped edit" not in err  # the content is the last line of the version file
    skill_md.write_text(skill_md.read_text() + "An edit that was not bumped.\n")
    for argv in (["--quick", "--scratch"], ["--scratch"]):
        code, out, err = run_main(capsys, "--skill", "demo", *argv)
        assert code == 0 and "WARNING unbumped edit" in err
        assert "python3 evals/eval_status.py bump --skill demo" in err and "not a refusal" in err and "no stored gate" in err
        assert "complete" in out  # the test ran


def test_a_partial_test_a_skill_with_no_version_file_and_a_resumed_event_print_no_such_warning(tmp_path, monkeypatch, capsys):
    skill = t.scores_demo(tmp_path, monkeypatch)
    code, out, err = run_main(capsys, "--skill", "demo", "--quick", "--scratch")
    assert code == 0 and "unbumped edit" not in err  # no version file: the validator's to report
    skill_md = bumped(skill)
    skill_md.write_text(skill_md.read_text() + "An edit that was not bumped.\n")
    code, out, err = run_main(capsys, "--skill", "demo", "--cases", "1", "--scratch")
    assert code == 0 and "unbumped edit" not in err  # a partial test is not full or quick


def test_the_warning_is_a_function_of_the_last_line_and_names_the_fix_for_each_kind_of_skill(tmp_path):
    folder = tb.skill(tmp_path)
    tb.versions(folder, ("1.0.0", "new"))
    last = json.loads((folder / "evals" / "versions.jsonl").read_text().splitlines()[-1])
    assert er.unbumped_warning(es, str(folder), "core-demo", last["content_sha256"]) is None
    text = er.unbumped_warning(es, str(folder), "core-demo", "f" * 64)
    assert text.startswith("WARNING unbumped edit") and "bump --skill core-demo" in text and "no stored gate" in text
    assert "skill_import.py bump --name core-demo" in er.unbumped_warning(es, str(folder), "core-demo", "f" * 64, imported=True)
    assert er.unbumped_warning(es, str(tmp_path / "no-such-skill"), "x", "f" * 64) is None


def test_the_help_and_the_docs_say_it_is_a_warning_and_not_a_refusal():
    doc = er.__doc__
    assert "--skill-dir" in doc and "never into the checkout" in doc and "--allow-web-cases" in doc
    assert "unbumped edit" in (REPO / "evals" / "README.md").read_text() and "not a refusal" in (REPO / "evals" / "README.md").read_text()


@pytest.mark.parametrize("shape", ["gate", "skills"])
def test_a_folder_inside_an_older_checkout_or_behind_a_link_to_one_is_refused(tmp_path, tmp_path_factory, monkeypatch, capsys, shape):
    standin(tmp_path, monkeypatch)
    older = tmp_path_factory.mktemp("older")
    if shape == "gate":
        (older / "evals").mkdir()
        (older / "evals" / "eval-gate.json").write_text("{}\n")
    else:  # an older checkout lacks the gate file and the import tool, and has skills/ and the validator
        (older / "skills").mkdir()
        (older / "scripts").mkdir()
        (older / "scripts" / "validate.py").write_text("")
    folder = older / "imports" / "demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(t.SKILL_MD)
    for path in (folder, tmp_path / "shortcut"):
        if path != folder:
            os.symlink(older, path)
            path = path / "imports" / "demo"
        with pytest.raises(SystemExit) as e:
            er.parse(["--skill-dir", str(path)])
        assert e.value.code == 2 and "inside a checkout of the workbench" in capsys.readouterr().err


DAY = 86400


def stale_copy(base, name="eval-import-stale", age=3 * DAY, mode=0o700, marker=True, lock=True, content="made by the runner"):
    """A per-event copy as a killed run leaves it: a folder with the runner's marker, a lock file and a file of the copy, `age` seconds old."""
    import time
    folder = Path(base) / name
    folder.mkdir()
    (folder / "demo").mkdir()
    (folder / "demo" / "SKILL.md").write_text(content)
    if marker:
        (folder / er.COPY_MARKER).write_text(json.dumps({"made_by": "eval_run.py", "token": "00ff"}))
    if lock:
        (folder / er.COPY_LOCK).write_text("")
    os.chmod(folder, mode)
    os.utime(folder, (time.time() - age,) * 2)
    return folder


def test_a_per_event_copy_left_by_a_killed_run_is_removed_when_it_is_the_runners_own_old_unlocked_and_nothing_else_is(tmp_path):
    import time
    now = time.time()
    stale_copy(tmp_path, "eval-import-old")
    stale_copy(tmp_path, "eval-import-new", age=60)
    (tmp_path / "eval-other-old").mkdir()
    os.utime(tmp_path / "eval-other-old", (now - 3 * DAY,) * 2)
    (tmp_path / "eval-import-file").write_text("not a folder")
    assert er.sweep_stale_copies(str(tmp_path), now=now) == ["eval-import-old"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["eval-import-file", "eval-import-new", "eval-other-old"]


def test_the_sweep_leaves_a_copy_of_another_user_a_copy_with_the_wrong_mode_and_a_folder_that_is_not_the_runners(tmp_path, monkeypatch):
    import time
    now = time.time()
    other_user = stale_copy(tmp_path, "eval-import-other-user")
    monkeypatch.setattr(er, "my_uid", lambda: os.getuid() + 1)  # the folder is then another user's
    assert er.sweep_stale_copies(str(tmp_path), now=now) == [] and other_user.exists()
    monkeypatch.undo()
    shutil.rmtree(other_user)  # a valid copy of this user's: the checks below are about what is not
    for name, mode in (("eval-import-open", 0o755), ("eval-import-group", 0o770), ("eval-import-read", 0o500)):
        stale_copy(tmp_path, name, mode=mode)
    stale_copy(tmp_path, "eval-import-no-marker", marker=False)
    wrong = stale_copy(tmp_path, "eval-import-wrong-marker")
    (wrong / er.COPY_MARKER).write_text(json.dumps({"made_by": "somebody else"}))
    bad = stale_copy(tmp_path, "eval-import-bad-marker")
    (bad / er.COPY_MARKER).write_text("not json")
    stale_copy(tmp_path, "eval-import-no-lock", lock=False)
    target = tmp_path / "somewhere-else"
    target.mkdir()
    (target / "keep").write_text("a folder the sweep must not touch")
    os.symlink(target, tmp_path / "eval-import-link")
    assert er.sweep_stale_copies(str(tmp_path), now=now) == []
    assert (target / "keep").exists() and (tmp_path / "eval-import-link").is_symlink()
    for name in ("eval-import-open", "eval-import-group", "eval-import-read", "eval-import-no-marker", "eval-import-wrong-marker",
                 "eval-import-bad-marker", "eval-import-no-lock"):
        assert (tmp_path / name).exists(), name
        os.chmod(tmp_path / name, 0o700)


def test_the_sweep_never_removes_a_copy_that_a_live_event_holds_locked(tmp_path):
    import fcntl
    import time
    folder = stale_copy(tmp_path, "eval-import-live")
    holder = open(folder / er.COPY_LOCK, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)  # what the running event holds for its whole life
    try:
        assert er.sweep_stale_copies(str(tmp_path), now=time.time()) == [] and (folder / "demo" / "SKILL.md").exists()
    finally:
        holder.close()
    assert er.sweep_stale_copies(str(tmp_path), now=time.time()) == ["eval-import-live"] and not folder.exists()


def test_an_event_holds_the_lock_of_its_copy_for_its_whole_life_and_releases_it_at_the_end(tmp_path, tmp_path_factory, monkeypatch, capsys):
    import fcntl
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    seen, real = [], er.stage_run

    def spy(case_dir, eval_cfg, variant_dir, deps, case, platform=None):
        if variant_dir:
            root = Path(variant_dir).parent
            with open(root / er.COPY_LOCK, "w") as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock = "free"
                except OSError:
                    lock = "held"
            seen.append((lock, json.loads((root / er.COPY_MARKER).read_text())["made_by"], oct(os.stat(root).st_mode & 0o777)))
        return real(case_dir, eval_cfg, variant_dir, deps, case, platform)
    monkeypatch.setattr(er, "stage_run", spy)
    assert run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")[0] == 0
    assert seen and {s[0] for s in seen} == {"held"} and {s[1] for s in seen} == {"eval_run.py"} and {s[2] for s in seen} == {"0o700"}


def test_a_copy_damaged_during_the_event_writes_no_evidence(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    start, real = es.content_hash(str(folder)), er.stage_run

    def spy(case_dir, eval_cfg, variant_dir, deps, case, platform=None):
        if variant_dir:  # the copy the runs are staged from is changed under the event; the original folder is not
            (Path(variant_dir) / "SKILL.md").write_text((Path(variant_dir) / "SKILL.md").read_text() + "damaged\n")
        return real(case_dir, eval_cfg, variant_dir, deps, case, platform)
    monkeypatch.setattr(er, "stage_run", spy)
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")
    result = json.loads(out)
    assert es.content_hash(str(folder)) == start  # the original is as it was
    assert result["evidence"]["written"] is False and "copy" in result["evidence"]["reason"] and "damaged" in result["evidence"]["reason"]
    assert not list((local_base() / "imported" / "demo").glob("lab-*.jsonl")) if (local_base() / "imported").exists() else True


def test_an_event_sweeps_the_stale_copies_and_the_docs_say_a_sigkill_can_leave_one(tmp_path, tmp_path_factory, monkeypatch, capsys):
    standin(tmp_path, monkeypatch)
    folder = imported(tmp_path, tmp_path_factory)
    base = Path(er.temp_base())
    stale = stale_copy(base, "eval-import-stale-" + tmp_path.name[:12])
    code, out, err = run_main(capsys, "--skill-dir", str(folder), "--quick", "--model", "m")
    assert code == 0 and not stale.exists()
    assert "SIGKILL" in er.__doc__ and "SIGKILL" in (REPO / "evals" / "README.md").read_text()
