"""Offline tests of evals/eval_status.py (content hash, case hashes, evidence, gate, snapshot tables, measurement)
and of the eval-status check in scripts/validate.py. No model is called: evidence is written by hand here. The
score and the bands are tested in test_bands.py."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name):
    folder = "evals" if name == "eval_status" else "scripts"
    spec = importlib.util.spec_from_file_location(name, REPO / folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


es = load("eval_status")
validate = load("validate")

INVENTORY = "# Inventory\n\n## Evaluation status\n\nIntro kept by hand.\n\n" + es.BEGIN + "\nold\n" + es.END + "\n\n## Progress\n"


@pytest.fixture
def root(tmp_path):
    for name in ("core-demo", "eng-other"):
        skill = tmp_path / "skills" / name
        (skill / "evals" / "files").mkdir(parents=True)
        (skill / "scripts").mkdir()
        (skill / "SKILL.md").write_text(f"# {name}\n")
        (skill / "scripts" / "check.py").write_text("print('ok')\n")
        (skill / "evals" / "files" / "input.md").write_text("fixture\n")
        (skill / "evals" / "evals.json").write_text(json.dumps({"evals": [
            {"id": 1, "prompt": "p", "assertions": ["a"]}, {"id": 2, "prompt": "q", "assertions": ["a"]}]}))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "inventory.md").write_text(INVENTORY)
    return tmp_path


def test_the_hash_is_stable_and_ignores_the_record_and_caches(root):
    skill = root / "skills" / "core-demo"
    first = es.content_hash(str(skill))
    assert first == es.content_hash(str(skill)) and len(first) == 64
    (skill / "evals" / "result.json").write_text("{}")
    (skill / "scripts" / "__pycache__").mkdir()
    (skill / "scripts" / "__pycache__" / "check.cpython-311.pyc").write_text("x")
    (skill / "scripts" / "stray.pyc").write_text("x")
    (skill / ".DS_Store").write_text("x")
    (root / "skills" / "eng-other" / "SKILL.md").write_text("# changed elsewhere\n")
    (root / "outside.md").write_text("x")
    assert es.content_hash(str(skill)) == first


@pytest.mark.parametrize("rel", ["SKILL.md", "scripts/check.py"])
def test_the_hash_changes_with_any_file_a_model_reads(root, rel):
    skill = root / "skills" / "core-demo"
    first = es.content_hash(str(skill))
    (skill / rel).write_text((skill / rel).read_text() + "\n")
    assert es.content_hash(str(skill)) != first


def test_the_hash_leaves_out_all_of_evals_and_the_installers_marker(root):
    """No model that uses the skill reads its cases, its evidence, its version file or its old record."""
    skill = root / "skills" / "core-demo"
    first = es.content_hash(str(skill))
    (skill / "evals" / "evals.json").write_text(json.dumps({"evals": [{"id": 1, "prompt": "another prompt"}]}))
    (skill / "evals" / "files" / "input.md").write_text("another fixture\n")
    (skill / "evals" / "files" / "added.md").write_text("x\n")
    (skill / "evals" / "evidence").mkdir()
    (skill / "evals" / "evidence" / "lab-20300102T030405Z-0a1b2c3d.jsonl").write_text("{}\n")
    (skill / "evals" / "versions.jsonl").write_text("{}\n")
    (skill / "evals" / "result.json").write_text("{}")
    (skill / ".installed-by-openhora").write_text("")  # a copy an installer made has the hash of its source
    (skill / "scripts" / ".pytest_cache").mkdir()
    (skill / "scripts" / ".pytest_cache" / "v").write_text("x")
    assert es.content_hash(str(skill)) == first
    # Only the evals folder of the skill itself, and only the marker at its top.
    (skill / "references" / "evals").mkdir(parents=True)
    (skill / "references" / "evals" / "note.md").write_text("x\n")
    second = es.content_hash(str(skill))
    (skill / "references" / ".installed-by-openhora").write_text("")
    assert len({first, second, es.content_hash(str(skill))}) == 3


def test_the_marker_names_are_the_new_one_and_the_one_before_the_rename():
    assert es.INSTALL_MARKER == ".installed-by-openhora"
    assert es.LEGACY_INSTALL_MARKER == ".installed-by-ai-workbench"
    assert es.INSTALL_MARKERS == (es.INSTALL_MARKER, es.LEGACY_INSTALL_MARKER)


@pytest.mark.parametrize("marker", [".installed-by-openhora", ".installed-by-ai-workbench"])
def test_either_marker_at_the_top_of_a_copy_leaves_the_hash_of_its_source(root, marker):
    """A copy installed before the rename carries the old marker and keeps its hash (the compatibility stage, T23)."""
    skill = root / "skills" / "core-demo"
    first = es.content_hash(str(skill))
    (skill / marker).write_text("")
    assert es.content_hash(str(skill)) == first
    # Only at the top of the folder: the same name deeper in is a file a model could read.
    (skill / "references").mkdir()
    (skill / "references" / marker).write_text("")
    assert es.content_hash(str(skill)) != first


@pytest.mark.parametrize("marker", [".installed-by-openhora", ".installed-by-ai-workbench"])
def test_content_changes_ignores_either_marker(root, marker):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "base"], cwd=root, check=True)
    (root / "skills" / "core-demo" / marker).write_text("")
    assert es.content_changes(str(root), "HEAD", "core-demo") == set()


def test_the_hash_changes_when_a_file_is_added_or_renamed(root):
    skill = root / "skills" / "core-demo"
    first = es.content_hash(str(skill))
    (skill / "references").mkdir()
    (skill / "references" / "guide.md").write_text("g\n")
    second = es.content_hash(str(skill))
    (skill / "references" / "guide.md").rename(skill / "references" / "other.md")
    assert len({first, second, es.content_hash(str(skill))}) == 3


def test_the_hash_leaves_out_the_tests_of_the_skills_scripts(root):
    skill = root / "skills" / "core-demo"
    first = es.content_hash(str(skill))
    tests = skill / "scripts" / "tests"
    (tests / "fixtures").mkdir(parents=True)
    (tests / "test_check.py").write_text("def test_ok():\n    assert True\n")
    (tests / "conftest.py").write_text("")
    (tests / "fixtures" / "input.md").write_text("fixture\n")
    assert es.content_hash(str(skill)) == first  # added
    (tests / "test_check.py").write_text("def test_ok():\n    assert 1 == 1\n")
    assert es.content_hash(str(skill)) == first  # changed
    (tests / "test_check.py").unlink()
    (tests / "fixtures" / "input.md").unlink()
    assert es.content_hash(str(skill)) == first  # removed
    (skill / "scripts" / "check.py").write_text("print('changed')\n")
    assert es.content_hash(str(skill)) != first


def test_only_the_tests_folder_directly_under_scripts_is_left_out(root):
    skill = root / "skills" / "core-demo"
    first = es.content_hash(str(skill))
    (skill / "assets" / "scripts" / "tests").mkdir(parents=True)
    (skill / "assets" / "scripts" / "tests" / "test_app.py").write_text("x\n")
    second = es.content_hash(str(skill))
    (skill / "scripts" / "tests_helper.py").write_text("x\n")
    assert len({first, second, es.content_hash(str(skill))}) == 3


def test_nothing_writes_or_reads_a_record_any_more(root, capsys):
    """The runner writes evidence; the command that built a record is gone (default 27), and since the snapshot
    tables replaced the generated block (B16) nothing reads one: the 48 old records are history."""
    with pytest.raises(SystemExit) as e:
        es.main(["record", "--skill", "core-demo", "--benchmark", "b.json"], root=str(root))
    assert e.value.code == 2
    for name in ("build_record", "update_baseline", "write_record", "load_record", "record_problems", "skill_status",
                 "record_statuses", "RECORD_REL", "STATUSES"):
        assert not hasattr(es, name), name
    assert "result.json" not in Path(es.__file__).read_text().split("def ", 1)[1]  # no code after the help names it
    (root / "skills" / "core-demo" / "evals" / "result.json").write_text("{not even json")
    configure(root, measurement_sha256=None)
    assert es.main(["inventory", "--write"], root=str(root)) == 0 and check(root)[0] == []


def test_inventory_writes_the_two_tables_and_check_ignores_the_commit_line(root, capsys):
    configure(root)
    assert es.main(["inventory", "--check"], root=str(root)) == 1
    assert "behind the evidence" in capsys.readouterr().err
    assert es.main(["inventory", "--write"], root=str(root)) == 0
    assert json.loads(capsys.readouterr().out) == {"written": True, "counts": {"needs a test": 2, "watch": 0, "reliable": 0}}
    text = (root / "docs" / "inventory.md").read_text()
    assert "Intro kept by hand." in text and "\nold\n" not in text and text.endswith("## Progress\n")
    assert "Generated at commit `none` by `python3 evals/eval_status.py inventory --write`." in text  # not a git checkout
    assert ("| Skill | Version | Band | Cause | Score | Mean | Runs (N) | Last full test | "
            "Field: uses, judged, mean (self-reported) |") in text
    assert "| `core-demo` | n/a | needs a test | metadata.version is missing" not in text
    assert "| `core-demo` | n/a | needs a test |" in text and "Counts: 2 needs a test, 0 watch, 0 reliable; 2 skills." in text
    assert "Model table: no skill has lab or field evidence yet." in text
    assert es.main(["inventory", "--check"], root=str(root)) == 0
    (root / "docs" / "inventory.md").write_text(text.replace("commit `none`", "commit `0123456789ab`"))
    assert es.main(["inventory", "--check"], root=str(root)) == 0  # another commit, the same tables
    assert es.main(["inventory", "--write"], root=str(root)) == 0
    assert es.inventory_current(str(root))


def test_the_model_table_has_a_row_per_skill_and_model_with_evidence(root, capsys):
    configure(root, measurement_sha256=None)
    skill_dir, _ = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, FULL_LINES("2030-01-01"))])
    hashes = platform_cases(root)
    evidence(root, [event_line(test=T2, kind="partial", version="1.2.0", gate=DROP, cases={"7": hashes["7"]},
                               baseline={"7": "none"}, web_cases=[]),
                    run_line(test=T2, kind="partial", version="1.2.0", case=7, case_sha256=hashes["7"], platform="chirp",
                             score=1.0, results=[1, 1])], name=f"lab-{T2}.jsonl")
    es.main(["inventory", "--write"], root=str(root))
    text = (root / "docs" / "inventory.md").read_text()
    assert "| `core-demo` | 1.2.0 | watch | the pessimistic score 0.55 is under 0.70 | 0.55 | 1.00 | 2 | 2030-01-01, passed | 0, 0, n/a |" in text
    assert ("| `core-demo` | `s-model` | watch | the pessimistic score 0.55 is under 0.70 | passed, 1.00 vs 0.00 | 0.55 | 1.00 | 2 | "
            "0, 0, n/a | `chirp`: 1.00 (1) |") in text
    assert "Model table: no skill" not in text
    # A skill that changed with no new evidence puts the snapshot behind, and that is a warning, never an error.
    (root / "skills" / "core-demo" / "SKILL.md").write_text('---\nname: core-demo\nmetadata:\n  version: "2.0.0"\n---\n')
    errors, warnings = check(root)
    assert errors == [] and any(w.startswith("[snapshot] the snapshot tables are behind the evidence") for w in warnings)


def test_inventory_without_markers_is_an_error(root):
    (root / "docs" / "inventory.md").write_text("# Inventory\n")
    with pytest.raises(SystemExit) as e:
        es.main(["inventory", "--check"], root=str(root))
    assert e.value.code == 1


def test_usage_errors_exit_2(root):
    for argv in (["hash"], ["record", "--skill", "core-demo"], ["inventory"], ["status", "--skill", "nope"], ["frobnicate"]):
        with pytest.raises(SystemExit) as e:
            es.main(argv, root=str(root))
        assert e.value.code == 2


# --- the eval-status check of scripts/validate.py -------------------------------------------------

def check(root):
    report = validate.Report()
    validate.check_eval_status(report, root=str(root))
    return [f"{e['where']}: {e['message']}" for e in report.errors], [w["message"] for w in report.warnings]


# --- the eval gate configuration (evals/eval-gate.json) -----------------------------------------

def configure(root, **changes):
    config = {"strong_model": "s-model", "strong_harness": "h", "floor_model": "f-model", "floor_harness": "fh",
              "floor_pass_env": ["FLOOR_KEY"], "strong_pass_env": [], "grader": "s-model", "threshold": 0.8, "strong_tolerance": 0,
              "measurement_version": 2, "measurement_floor": 2, "measurement_sha256": "0" * 64, **changes}
    config = {k: v for k, v in config.items() if v is not None}  # None leaves a key out
    (root / "evals").mkdir(exist_ok=True)
    (root / "evals" / "eval-gate.json").write_text(json.dumps(config))


@pytest.mark.parametrize("content, why", [
    ("{not json", "not valid JSON"),
    ('{"floor_model": "f"}', "missing field 'strong_model'"),
    (None, "threshold must be between 0 and 1"),
])
def test_validate_fails_on_an_invalid_gate_configuration(root, content, why):
    configure(root, threshold=3)
    if content is not None:
        (root / "evals" / "eval-gate.json").write_text(content)
    errors, _ = check(root)
    assert len(errors) == 1 and errors[0].startswith("evals/eval-gate.json") and why in errors[0]
    assert es.load_gate(str(root)) == {}


def test_the_repository_gate_configuration_is_valid():
    assert es.gate_problems(str(REPO)) == [] and es.load_gate(str(REPO))["floor_model"]


# --- the gate asks the threshold of both models; a record says how it was measured ----------------

def test_a_configuration_needs_a_measurement_version_above_the_earlier_rule(root):
    configure(root, measurement_version=1)
    assert es.gate_problems(str(root)) == ["measurement_version must be above 1"]


@pytest.mark.parametrize("floor", [0, 3, True, "2"])
def test_the_measurement_floor_is_a_version_up_to_the_measurement_version(root, floor):
    configure(root, measurement_floor=floor)
    assert len(es.gate_problems(str(root))) == 1 and "measurement_floor" in es.gate_problems(str(root))[0]
    configure(root, measurement_floor=None)
    assert es.gate_problems(str(root)) == ["missing field 'measurement_floor'"]


def test_the_fingerprint_is_optional_and_checked_when_present(root):
    configure(root, measurement_sha256=None)
    assert es.gate_problems(str(root)) == [] and es.load_gate(str(root))["measurement_floor"] == 2
    configure(root, measurement_sha256="abc")
    assert es.gate_problems(str(root)) == ["measurement_sha256 must be 64 hexadecimal characters"]


def test_no_evidence_is_written_while_the_gate_file_carries_no_fingerprint(root, capsys):
    assert es.evidence_refusal(str(root)) is None  # no gate file: a tree with no measurement to protect
    configure(root)
    assert es.evidence_refusal(str(root)) is None
    configure(root, measurement_sha256=None)
    assert "carries no measurement_sha256: measurement version 2 is open" in es.evidence_refusal(str(root))
    configure(root, threshold=3)
    assert "is not valid" in es.evidence_refusal(str(root))


def test_the_repository_measurement_is_at_version_5_or_later_with_its_floor(root):
    """Phase B changes what the grader is shown, so nothing measured before it counts: version 5 or later, and a floor
    of 5 or later."""
    gate = es.load_gate(str(REPO))
    assert gate["measurement_version"] >= 5 and gate["measurement_floor"] >= 5


# --- the keys that control a test event ------------------------------------------------------------

def test_the_control_of_an_event_has_defaults_and_the_gate_file_overrides_them(root):
    assert es.event_config({}) == {"runs": 3, "timeout_seconds": 900, "retries": 2, "max_resumes": 3, "total_jobs": 10,
                                   "web_jobs": {"strong": 2, "floor": 2}, "baseline_runs": 3, "baseline_margin": None}
    configure(root, runs=5, max_resumes=1, web_jobs={"strong": 1, "floor": 4})
    assert es.gate_problems(str(root)) == []
    control = es.event_config(es.load_gate(str(root)))
    assert (control["runs"], control["max_resumes"], control["web_jobs"], control["retries"]) == (5, 1, {"strong": 1, "floor": 4}, 2)


@pytest.mark.parametrize("change, why", [
    ({"runs": 0}, "runs must be a whole number from 1 to 10"),
    ({"runs": True}, "runs must be a whole number"),
    ({"timeout_seconds": 5}, "timeout_seconds must be a whole number from 30"),
    ({"retries": 6}, "retries must be a whole number from 0 to 5"),
    ({"max_resumes": -1}, "max_resumes must be a whole number"),
    ({"total_jobs": 0}, "total_jobs must be a whole number"),
    ({"web_jobs": {"strong": 2}}, "web_jobs must give a whole number"),
    ({"web_jobs": {"strong": 2, "floor": 0}}, "web_jobs must give a whole number"),
    ({"web_cases": {"core-demo": []}}, "web_cases must map a skill name"),
    ({"web_cases": ["core-demo"]}, "web_cases must map a skill name"),
    ({"strong_web_pass_env": ["not a name"]}, "strong_web_pass_env must list variable names"),
    ({"run": 3}, "unknown field 'run'"),
])
def test_a_control_key_outside_its_form_makes_the_gate_file_invalid(root, change, why):
    configure(root, **change)
    problems = es.gate_problems(str(root))
    assert len(problems) == 1 and why in problems[0] and es.load_gate(str(root)) == {}


def test_a_case_may_use_the_web_only_when_the_gate_file_lists_it(root):
    assert es.web_case_allowed({}, "core-demo", 1) is True  # no gate file: no list, nothing refused
    configure(root)
    gate = es.load_gate(str(root))
    assert es.web_case_allowed(gate, "core-demo", 1) is False  # a gate file with no list: no case
    configure(root, web_cases={"core-demo": [1, "b"]})
    gate = es.load_gate(str(root))
    assert es.web_case_allowed(gate, "core-demo", 1) and es.web_case_allowed(gate, "core-demo", "1") and es.web_case_allowed(gate, "core-demo", "b")
    assert not es.web_case_allowed(gate, "core-demo", 2) and not es.web_case_allowed(gate, "eng-other", 1)


# --- the evidence store: the hashes, the version, the model ids, the closed forms of a line ---------------

def test_each_case_has_its_own_hash_over_the_whole_case_and_its_fixtures(root):
    skill = root / "skills" / "core-demo"
    cases = [{"id": 1, "prompt": "p", "files": ["evals/files"], "assertions": ["a", {"text": "b", "tags": ["guard"]}],
              "workbench_files": ["scripts/validate.py"]},
             {"id": 2, "prompt": "q", "assertions": ["a"]}]
    write = lambda: (skill / "evals" / "evals.json").write_text(json.dumps({"evals": cases}))
    write()
    first = es.case_hashes(str(skill))
    assert set(first) == {"1", "2"} and first["1"] != first["2"] and all(len(h) == 64 for h in first.values())
    assert es.case_hashes(str(skill)) == first  # stable
    # A change to one case drops the evidence of that case only: every part of the case object counts.
    for change in ({"prompt": "another"}, {"assertions": ["a", {"text": "b", "tags": ["format"]}]}, {"setup": ["true"]},
                   {"allow_web": True}, {"grader_files": ["input.md"]}, {"skills": ["eng-other"]}, {"tags": ["guard"]},
                   {"workbench_files": ["scripts/validate.py", "templates"]}, {"expected_output": "x"}):
        saved, cases[0] = cases[0], {**cases[0], **change}
        write()
        now = es.case_hashes(str(skill))
        assert now["1"] != first["1"] and now["2"] == first["2"], change
        cases[0] = saved
    write()
    assert es.case_hashes(str(skill)) == first
    # The bytes of its fixture files count; a cache beside them does not.
    (skill / "evals" / "files" / "input.md").write_text("another fixture\n")
    assert es.case_hashes(str(skill))["1"] != first["1"] and es.case_hashes(str(skill))["2"] == first["2"]
    (skill / "evals" / "files" / "input.md").write_text("fixture\n")
    (skill / "evals" / "files" / "__pycache__").mkdir()
    (skill / "evals" / "files" / "__pycache__" / "x.pyc").write_text("x")
    (skill / "evals" / "files" / ".DS_Store").write_text("x")
    assert es.case_hashes(str(skill)) == first
    (skill / "evals" / "files" / "more.md").write_text("x\n")
    assert es.case_hashes(str(skill))["1"] != first["1"]


def test_a_repository_file_a_case_brings_enters_its_hash_as_a_path_never_as_content(root):
    skill = root / "skills" / "core-demo"
    (root / "scripts").mkdir()
    (root / "scripts" / "validate.py").write_text("print('one')\n")
    (skill / "evals" / "evals.json").write_text(json.dumps({"evals": [{"id": 1, "prompt": "p", "workbench_files": ["scripts/validate.py"]}]}))
    first = es.case_hashes(str(skill))
    (root / "scripts" / "validate.py").write_text("print('edited')\n")
    assert es.case_hashes(str(skill)) == first  # an edit of that file changes no hash and no evidence


def test_the_files_allow_web_applies_to_every_case_of_the_file(root):
    skill = root / "skills" / "core-demo"
    first = es.case_hashes(str(skill))
    data = json.loads((skill / "evals" / "evals.json").read_text())
    (skill / "evals" / "evals.json").write_text(json.dumps({**data, "allow_web": True}))
    assert all(es.case_hashes(str(skill))[k] != first[k] for k in first)
    assert es.case_hashes(str(root / "skills" / "missing")) == {}


@pytest.mark.parametrize("text, version", [
    ('---\nname: x\nmetadata:\n  version: "1.2.3"\n---\n', "1.2.3"),
    ('---\nname: x\nmetadata:\n  version: "0.2"   # two parts, as before the version rules\n---\n', "0.2.0"),
    ("---\nname: x\nmetadata:\n  version: 10.20.30\n---\n", "10.20.30"),
    ('---\nname: x\nmetadata:\n  version: "one"\n---\n', None),
    ("---\nname: x\n---\nversion: 1.2.3 in the body is not it\n", None),
    ("# no frontmatter\n", None),
])
def test_the_version_of_a_skill_is_read_as_three_parts(root, text, version):
    skill = root / "skills" / "core-demo"
    (skill / "SKILL.md").write_text(text)
    assert es.skill_version(str(skill)) == version


def test_a_model_is_written_under_its_listed_id_and_anything_else_as_unknown(root):
    assert es.model_id({}, "anything/at-all") == "anything/at-all"  # no gate file: no list
    configure(root)
    gate = es.load_gate(str(root))
    assert es.model_id(gate, "s-model") == "s-model" and es.model_id(gate, "f-model") == "f-model"
    assert es.model_id(gate, "a-private-model-name") == "unknown"
    configure(root, models={"s-model": ["provider/s-model"], "f-model": ["vendor/f-model", "f"], "third": []})
    gate = es.load_gate(str(root))
    assert gate and es.model_id(gate, "provider/s-model") == "s-model" and es.model_id(gate, "f") == "f-model"
    assert es.model_id(gate, "third") == "third" and es.model_id(gate, "fourth") == "unknown"


@pytest.mark.parametrize("models, why", [
    ({"s-model": [], "f-model": ["s-model"]}, "names an id or an alias twice"),
    ({"s-model": []}, "floor_model 'f-model' is not in models"),
    ({"s-model": "alias", "f-model": []}, "models must map each known model id"),
    ({"s-model": [], "f-model": [], "unknown": []}, "models must map each known model id"),
    ({}, "models must map each known model id"),
])
def test_the_model_list_names_every_configured_model_once(root, models, why):
    configure(root, models=models)
    assert len(es.gate_problems(str(root))) >= 1 and why in es.gate_problems(str(root))[0]


def test_the_fingerprint_follows_the_files_that_decide_what_a_run_measures(root):
    (root / "evals" / "container").mkdir(parents=True)
    (root / "evals" / "grading-prompt.md").write_text("template\n")
    (root / "evals" / "container" / "Dockerfile").write_text("FROM x\n")
    for harness in ("one", "two"):
        (root / "adapters" / harness).mkdir(parents=True)
        (root / "adapters" / harness / "adapter.json").write_text("{}")
        (root / "adapters" / harness / "eval.json").write_text("{}")
    (root / "adapters" / "one" / "run-prompt.sh").write_text("echo\n")
    first = es.measurement_fingerprint(str(root))
    assert len(first) == 64 and es.measurement_fingerprint(str(root)) == first
    seen = {first}
    for rel, text in (("evals/grading-prompt.md", "another template\n"), ("evals/container/Dockerfile", "FROM y\n"),
                      ("adapters/one/run-prompt.sh", "echo changed\n"), ("adapters/one/eval.json", '{"skills_dir": ".x/skills"}'),
                      ("evals/measure.py", "# the measuring module\n"), ("evals/measurement.json", '{"file_limit": 1}'),
                      ("evals/executor.py", "# the executor\n"), ("scripts/stage_skills.py", "# the staging\n")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
        seen.add(es.measurement_fingerprint(str(root)))
    assert len(seen) == 9
    # What decides nothing either: the rest of the runner, the gate file, a shared reference, redact.py, and the
    # manifest of an eval adapter (its eval block is in eval.json; adapter.json holds installation text and secrets).
    for rel in ("evals/eval_run.py", "evals/eval-gate.json", "shared/references/security.md", "scripts/redact.py",
                "adapters/one/adapter.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("anything\n")
    assert es.measurement_fingerprint(str(root)) in seen
    seen = {es.measurement_fingerprint(str(root))}
    # What decides nothing: a skill, a document, the files of an adapter that runs no eval.
    (root / "adapters" / "two" / "adapter.json").write_text('{"changed": true}')
    (root / "adapters" / "two" / "eval.json").write_text('{"changed": true}')
    (root / "skills" / "core-demo" / "SKILL.md").write_text("# edited\n")
    assert es.measurement_fingerprint(str(root)) in seen and len(seen) == 1


def test_a_test_id_is_its_utc_time_and_eight_random_characters():
    import datetime
    a = es.new_test_id(datetime.datetime(2030, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc))
    assert a.startswith("20300102T030405Z-") and es.TEST_ID_RE.fullmatch(a)
    assert len({es.new_test_id() for _ in range(50)}) == 50


TEST_ID = "20300102T030405Z-0a1b2c3d"
H = {c: c * 64 for c in "abcdef"}


def event_line(**changes):
    line = {"record": "test", "skill": "core-demo", "test": TEST_ID, "kind": "full", "version": "1.0.0", "content_sha256": H["a"],
            "date": "2030-01-02", "models": {"strong": "s-model", "floor": "f-model"}, "adapters": {"strong": "h", "floor": "fh"},
            "adapter_sha256": {"h": H["b"], "fh": H["c"]}, "grader": "s-model", "runs": 3, "timeout_seconds": 900, "retries": 2,
            "measurement_version": 5, "measurement_sha256": H["d"], "image_digest": "sha256:" + H["e"], "image_platform": "linux/arm64",
            "grading_template_sha256": H["f"], "tools": {"git": "git version 2.47.3"}, "cases": {"1": H["a"], "2": H["b"]},
            "baseline": {"1": "run", "2": "reused"}, "web_cases": [2],
            "counts": {"s-model": {"with": dict.fromkeys(es.COUNT_KEYS, 0), "without": dict.fromkeys(es.COUNT_KEYS, 0)},
                       "f-model": {"with": {**dict.fromkeys(es.COUNT_KEYS, 0), "invoked": 6}}},
            "extra_pass_env": [], "complete": True,
            "gate": {"passed": True, "with": 0.9, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05}}
    line.update(changes)
    return {k: v for k, v in line.items() if v is not DROP}


DROP = object()


def run_line(**changes):
    line = {"record": "run", "skill": "core-demo", "version": "1.0.0", "content_sha256": H["a"], "model": "s-model", "adapter": "h",
            "kind": "full", "test": TEST_ID, "date": "2030-01-02", "measurement_version": 5, "measurement_sha256": H["d"],
            "case": 1, "case_sha256": H["a"], "variant": "with", "outcome": "graded", "score": 0.5, "results": [1, 0]}
    line.update(changes)
    return {k: v for k, v in line.items() if v is not DROP}


def evidence(root, lines, name=f"lab-{TEST_ID}.jsonl", skill="core-demo"):
    folder = root / "skills" / skill / "evals" / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("".join(json.dumps(line) + "\n" for line in lines))
    return folder / name


def test_a_well_formed_evidence_file_is_valid_and_changes_no_status(root, capsys):
    configure(root)
    path = evidence(root, [event_line(), run_line(), run_line(variant="without", score=0.0, results=[0, 0]),
                           run_line(model="f-model", adapter="fh", case=2, case_sha256=H["b"], context_sha256=H["c"], score=1.0, results=[1, 1]),
                           run_line(outcome="timeout", score=0, results=[0, 0]),
                           run_line(guard_failed=[2])])
    assert es.evidence_file_problems(str(path), str(root)) == []
    assert es.evidence_problems(str(root)) == ({}, 1) and es.main(["evidence"], root=str(root)) == 0
    assert json.loads(capsys.readouterr().out) == {"files": 1, "problems": {}}
    assert es.main(["evidence", "--skill", "eng-other"], root=str(root)) == 0
    assert [str(p) for p in map(Path, es.evidence_files(str(root / "skills" / "core-demo")))] == [str(path)]
    # An evidence file of version 1.0.0 is no evidence for a skill with no version: it still needs a test.
    assert es.all_status(str(root))["skills"][0]["band"] == "needs a test"


@pytest.mark.parametrize("change, why", [
    ({"note": "free text"}, "unknown key 'note'"),
    ({"score": DROP}, "missing key 'score'"),
    ({"skill": "Core Demo"}, "skill must be a skill name"),
    ({"version": "1.0"}, "version must be X.Y.Z"),
    ({"content_sha256": "abc"}, "content_sha256 must be 64 hexadecimal characters"),
    ({"model": "a-private-model"}, "model must be an id of the gate file's model list"),
    ({"adapter": "../h"}, "adapter must be an adapter's folder name"),
    ({"kind": "smoke"}, "kind must be full or partial"),
    ({"date": "2030-13-01"}, "date must be YYYY-MM-DD"),
    ({"date": "02/01/2030"}, "date must be YYYY-MM-DD"),
    ({"measurement_version": "5"}, "measurement_version must be a whole number"),
    ({"case": 1.5}, "case must be a case id"),
    ({"variant": "ablated"}, "variant must be with or without"),
    ({"outcome": "refused"}, "outcome must be graded or timeout"),
    ({"score": 1.2}, "score must be a number from 0 to 1"),
    ({"score": True}, "score must be a number from 0 to 1"),
    ({"score": 0.9}, "score must be the share of results that are 1"),
    ({"results": []}, "results must be a list of 0 and 1"),
    ({"results": [1, 2]}, "results must be a list of 0 and 1"),
    ({"results": [True, False]}, "results must be a list of 0 and 1"),
    ({"outcome": "timeout", "score": 0.5}, "a timeout has score 0 and results all 0"),
    ({"guard_failed": [1]}, "guard_failed must be a list of positions of assertions whose result is 0"),
    ({"guard_failed": [3]}, "guard_failed must be a list of positions"),
    ({"guard_failed": [2], "variant": "without"}, "guard_failed belongs to a with-skill run only"),
    ({"platform": "Chirp!"}, "platform must be a platform name"),
    ({"context_sha256": "x"}, "context_sha256 must be 64 hexadecimal characters"),
    ({"version": "1.0.1"}, "version differs from the event line of the file"),
    ({"test": "20300102T030405Z-ffffffff"}, "test differs from the event line of the file"),
    ({"kind": "partial"}, "kind differs from the event line of the file"),
    ({"measurement_sha256": H["a"]}, "measurement_sha256 differs from the event line of the file"),
    ({"model": "unknown"}, "model is not one of the event's models"),
    ({"adapter": "other"}, "adapter is not one of the event's adapters"),
    ({"case": 3}, "case and case_sha256 are not a case of the event line"),
    ({"case_sha256": H["f"]}, "case and case_sha256 are not a case of the event line"),
])
def test_a_run_line_with_an_unknown_key_or_a_value_outside_its_form_is_an_error(root, capsys, change, why):
    configure(root)
    path = evidence(root, [event_line(), run_line(), run_line(**change)])
    problems = es.evidence_file_problems(str(path), str(root))
    assert len(problems) == 1 and problems[0].startswith("line 3: ") and why in problems[0]
    assert es.main(["evidence"], root=str(root)) == 1 and why in capsys.readouterr().err


@pytest.mark.parametrize("change, why", [
    ({"operator": "someone"}, "unknown key 'operator'"),
    ({"grader": DROP}, "missing key 'grader'"),
    ({"record": "run"}, "record must be \"test\""),
    ({"test": "yesterday"}, "test must be a test id"),
    ({"models": {"floor": "f-model"}}, "models must be"),
    ({"models": {"strong": "a-private-model", "floor": "f-model"}}, "models must be"),
    ({"adapters": {"strong": "h"}}, "adapters must be an adapter's folder name for each tier"),
    ({"adapter_sha256": {"h": H["b"]}}, "adapter_sha256 must be the sha256 of the run-prompt.sh of each adapter"),
    ({"grader": "a-private-grader"}, "grader must be a listed model id"),
    ({"runs": 0}, "runs must be a whole number, 1 or more"),
    ({"retries": -1}, "retries must be a whole number, 0 or more"),
    ({"image_digest": None}, "image_digest must be sha256:"),
    ({"image_platform": "arm64"}, "image_platform must be a platform"),
    ({"tools": {"git": "a version line\nwith a second line"}}, "tools must be"),
    ({"cases": {}}, "cases must be"),
    ({"baseline": {"1": "run"}}, "baseline must be run, reused or none for each case"),
    ({"baseline": {"1": "run", "2": "skipped"}}, "baseline must be run, reused or none"),
    ({"web_cases": [9]}, "web_cases must be a list of ids of cases"),
    ({"counts": {"s-model": {"with": {"retries": 0}}}}, "counts must be"),
    ({"counts": {"s-model": {"without": {**dict.fromkeys(es.COUNT_KEYS, 0), "invoked": 1}}}}, "counts must be"),
    ({"counts": {"private": {"with": dict.fromkeys(es.COUNT_KEYS, 0)}}}, "counts must be"),
    ({"extra_pass_env": ["not a name"]}, "extra_pass_env must be a list of variable names"),
    ({"complete": "yes"}, "complete must be true or false"),
    ({"gate": DROP}, "a complete full test carries its gate"),
    ({"gate": {"passed": True}}, "gate must be"),
    ({"gate": {"passed": True, "with": 0.9, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05, "note": "anything"}}, "gate must be"),
    ({"kind": "partial"}, "gate belongs to a full test only"),
    ({"complete": False}, "gate is written by a complete full test only"),
    ({"upstream": {"f-model": "a provider\nname"}}, "upstream must be"),
    ({"skill": "eng-other"}, "skill must be the folder's name, core-demo"),
    ({"test": "20300102T030405Z-ffffffff"}, "test differs from the file's name"),
])
def test_an_event_line_with_an_unknown_key_or_a_value_outside_its_form_is_an_error(root, change, why):
    configure(root)
    path = evidence(root, [event_line(**change)])
    problems = es.evidence_file_problems(str(path), str(root))
    assert problems and problems[0].startswith("line 1: ") and why in problems[0], problems


def test_an_event_with_another_number_of_runs_than_the_configured_one_is_no_evidence(root, capsys):
    """A trial of 2 runs per case, copied into a skill by hand, is refused: evidence comes only from an event
    that used the configured values, and its score and gate would otherwise be computed from it."""
    configure(root)  # no "runs" key: the default, 3
    path = evidence(root, [event_line(runs=2), run_line()])
    assert es.evidence_file_problems(str(path), str(root)) == [
        'line 1: runs is 2, and the configured number is 3 ("runs" of evals/eval-gate.json): an event with another '
        "number of runs is a trial, and writes no evidence"]
    assert es.main(["evidence"], root=str(root)) == 1 and "runs is 2, and the configured number is 3" in capsys.readouterr().err
    configure(root, runs=2)  # the number the gate file configures is the one an event line must carry
    assert es.evidence_file_problems(str(path), str(root)) == []
    path = evidence(root, [event_line(), run_line()])
    assert "runs is 3, and the configured number is 2" in es.evidence_file_problems(str(path), str(root))[0]


def test_the_forms_that_are_optional_or_depend_on_the_kind(root):
    configure(root)
    for line in (event_line(kind="partial", gate=DROP), event_line(complete=False, gate=DROP),  # an abandoned full test
                 event_line(gate={"passed": False, "with": 0.5, "baseline": None, "threshold": 0.8, "tolerance": 0.05, "note": "baseline expired"}),
                 event_line(upstream={"f-model": "a-provider"}), event_line(models={"strong": "s-model"}, adapters={"strong": "h"},
                                                                            adapter_sha256={"h": H["b"]}, counts={})):
        assert es.event_line_problems(line, {"s-model", "f-model"}) == [], line
    assert es.run_line_problems(run_line(model="unknown")) == [] and es.run_line_problems(run_line(case="a-case"), None, None) == []


def test_a_file_that_is_no_evidence_file_is_an_error(root, capsys):
    configure(root)
    assert "the name must be lab-<test id>.jsonl" in es.evidence_file_problems(str(evidence(root, [event_line()], "notes.jsonl")), str(root))[0]
    (root / "skills" / "core-demo" / "evals" / "evidence" / "notes.jsonl").unlink()
    path = evidence(root, [])
    assert es.evidence_file_problems(str(path), str(root)) == ["the file is empty: an evidence file has an event line"]
    path.write_text("{not json\n" + json.dumps(run_line()) + "\n[1]\n")
    problems = es.evidence_file_problems(str(path), str(root))
    assert problems[:2] == ["line 1: not valid JSON", "line 3: must be a JSON object"] and "unknown key" in problems[2]
    # A contributed field file is validated by its own form; anything else in the folder is flagged.
    path.unlink()
    field = evidence(root, [{"record": "use"}], "field-0123456789ab.jsonl")
    found, checked = es.evidence_problems(str(root))
    assert checked == 1 and "first 12 characters of the file's sha256" in found[str(field.relative_to(root))][0]
    field.unlink()
    evidence(root, [event_line()], "lab-notes.txt")
    found, checked = es.evidence_problems(str(root))
    assert checked == 1 and list(found) == [str(Path("skills") / "core-demo" / "evals" / "evidence" / "lab-notes.txt")]
    assert es.main(["evidence", "--file", str(root / "skills" / "core-demo" / "evals" / "evidence" / "lab-notes.txt")], root=str(root)) == 1


def test_the_hash_command_prints_the_content_hash_the_version_and_the_case_hashes(root, capsys):
    (root / "skills" / "core-demo" / "SKILL.md").write_text('---\nname: core-demo\nmetadata:\n  version: "0.4"\n---\n')
    assert es.main(["hash", "--skill", "core-demo"], root=str(root)) == 0
    out = json.loads(capsys.readouterr().out)
    skill = str(root / "skills" / "core-demo")
    assert out == {"skill": "core-demo", "content_sha256": es.content_hash(skill), "version": "0.4.0", "cases": es.case_hashes(skill)}


def test_the_48_old_records_stay_as_history_and_no_evidence_is_converted_from_them():
    records = sorted(REPO.glob("skills/*/evals/result.json"))
    assert len(records) >= 48
    # Evidence exists only as files the runner wrote for a test event (lab-<UTC start>-<hex>.jsonl), never as a
    # conversion of an old record, and every committed file is valid.
    evidence = list(REPO.glob("skills/*/evals/evidence/*"))
    assert all(p.name.startswith("lab-") and p.suffix == ".jsonl" for p in evidence), evidence
    assert es.evidence_problems(str(REPO))[0] == {}
    gate = es.load_gate(str(REPO))
    assert set(gate["models"]) >= {gate["strong_model"], gate["floor_model"], gate["grader"]}
    assert es.model_id(gate, "deepseek/deepseek-v4.1-flash") == gate["floor_model"]  # the same model without the router's prefix


# --- the gate from the lines: epochs, the floor, a major version ---------------------------------------

def gate_tree(root, events, cfg_changes=None, version="1.2.0"):
    """A skill with two cases and the given evidence: [(test id, kind, version, date, complete, [(case, variant,
    score, date)])]. Returns (skill folder, configuration)."""
    skill = root / "skills" / "core-demo"
    (skill / "SKILL.md").write_text(f'---\nname: core-demo\nmetadata:\n  version: "{version}"\n---\n')
    hashes = es.case_hashes(str(skill))
    for test, kind, ver, date, complete, lines in events:
        event = event_line(test=test, kind=kind, version=ver, date=date, complete=complete, cases=hashes,
                           baseline={k: "run" for k in hashes}, web_cases=[],
                           gate={"passed": True, "with": 1.0, "baseline": 0.0, "threshold": 0.8, "tolerance": 0.05}
                           if kind == "full" and complete else DROP)
        evidence(root, [event] + [run_line(test=test, kind=kind, version=ver, date=d, case=c, case_sha256=hashes[str(c)],
                                           variant=v, score=sc, results=[1] if sc == 1 else [0]) for c, v, sc, d in lines],
                 name=f"lab-{test}.jsonl")
    cfg = {"strong_model": "s-model", "floor_model": "f-model", "grader": "s-model", "threshold": 0.8, "strong_tolerance": 0.05,
           "measurement_floor": 5, **(cfg_changes or {})}
    return str(skill), cfg


T1, T2, T3 = "20300101T000000Z-00000001", "20300201T000000Z-00000002", "20300301T000000Z-00000003"
FULL_LINES = lambda d, w=1, b=0: [(1, "with", w, d), (2, "with", w, d), (1, "without", b, d), (2, "without", b, d)]


def test_the_gate_reads_every_full_test_of_the_newest_version_and_no_partial_test(root):
    skill, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, FULL_LINES("2030-01-01")),
                                  (T2, "partial", "1.2.0", "2030-02-01", True, [(1, "with", 0, "2030-02-01")]),
                                  (T3, "full", "1.2.1", "2030-03-01", True, [(1, "with", 0, "2030-03-01"), (2, "with", 1, "2030-03-01")])])
    gate = es.gate_of(skill, cfg)
    # Z change 1.2.0 to 1.2.1: one X.Y, so both full tests count; the partial test's zero does not.
    assert (gate["computed"], gate["version"], gate["test"], gate["with"], gate["baseline"]) == (True, "1.2", T3, 0.75, 0.0)
    assert gate["passed"] is False and gate["cases"] == ["1", "2"] and gate["pending"] == []


def test_a_newer_x_y_starts_a_new_gate_and_a_major_version_has_none_until_its_full_test(root):
    lines = FULL_LINES("2030-01-01")
    skill, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, lines),
                                  (T2, "full", "1.3.0", "2030-02-01", True, [(1, "with", 0, "2030-02-01"), (2, "with", 0, "2030-02-01")])],
                           version="1.3.0")
    assert es.gate_of(skill, cfg)["with"] == 0.0  # only the lines of 1.3
    skill, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, lines)], version="2.0.0")
    gate = es.gate_of(skill, cfg)
    assert gate["computed"] is False and gate["cause"] == "no full test of the current major version"


def test_a_raised_measurement_floor_leaves_every_earlier_line_without_weight(root):
    skill, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, FULL_LINES("2030-01-01"))], {"measurement_floor": 6})
    gate = es.gate_of(skill, cfg)
    assert gate["computed"] is False and "have no run with the skill" in gate["cause"]
    assert es.baseline_lines(skill, cfg) == {}


def test_after_an_epoch_the_baselines_expire_and_the_written_result_stands_with_its_note(root):
    epoch = {"date": "2030-01-15", "models": ["s-model"], "skills": "all", "cause": "the model changed under its id"}
    skill, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, FULL_LINES("2030-01-01"))], {"epochs": [epoch]})
    gate = es.gate_of(skill, cfg)
    assert gate["note"] == "baseline expired" and gate["passed"] is True and gate["computed"] is False
    assert es.baseline_lines(skill, cfg) == {}
    # An epoch of another model or of another skill reaches nothing here.
    for other in ({**epoch, "models": ["f-model"]}, {**epoch, "skills": ["eng-other"]}, {**epoch, "date": "2029-12-31"}):
        assert es.gate_of(skill, {**cfg, "epochs": [other]})["computed"] is True


def test_runs_before_an_epoch_are_not_of_the_epoch_of_the_newest_full_test(root):
    epoch = {"date": "2030-01-15", "models": "all", "skills": ["core-demo"], "cause": "the image changed"}
    skill, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, FULL_LINES("2030-01-01", w=0)),
                                  (T2, "full", "1.2.0", "2030-02-01", True, FULL_LINES("2030-02-01"))], {"epochs": [epoch]})
    gate = es.gate_of(skill, cfg)
    assert gate["computed"] and gate["with"] == 1.0 and gate["baseline"] == 0.0  # the zeros of before the epoch are not in it


def test_a_deleted_case_leaves_the_gate_to_the_cases_that_remain(root):
    skill, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True,
                                   [(1, "with", 1, "2030-01-01"), (2, "with", 0, "2030-01-01"), (1, "without", 0, "2030-01-01"),
                                    (2, "without", 0, "2030-01-01")])])
    assert es.gate_of(skill, cfg)["with"] == 0.5
    data = json.loads((root / "skills" / "core-demo" / "evals" / "evals.json").read_text())
    (root / "skills" / "core-demo" / "evals" / "evals.json").write_text(json.dumps({"evals": data["evals"][:1]}))
    gate = es.gate_of(skill, cfg)
    assert gate["cases"] == ["1"] and gate["with"] == 1.0 and gate["passed"] is True


def test_the_gate_command_prints_it(root, capsys):
    configure(root)
    assert es.main(["gate", "--skill", "core-demo"], root=str(root)) == 0
    assert json.loads(capsys.readouterr().out)["cause"] == "no full test of the current major version"
    with pytest.raises(SystemExit) as e:
        es.main(["gate"], root=str(root))
    assert e.value.code == 2


# --- the platforms' cases (the plan's decision 14c, item B7a) ------------------------------------------

def platform_cases(root, name="chirp", cases=None):
    folder = root / "skills" / "core-demo" / "evals" / "platforms"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"skill_name": "core-demo", "platform": name,
                                                     "evals": cases or [{"id": 7, "prompt": "post it", "assertions": ["a", "b"]}]}))
    return es.case_hashes(str(root / "skills" / "core-demo"), name)


def test_a_line_of_a_platforms_case_belongs_to_a_partial_test_with_the_skill(root):
    configure(root)
    assert es.run_line_problems(run_line(kind="partial", platform="chirp")) == []
    assert "a line of a platform's case runs in a partial test" in es.run_line_problems(run_line(platform="chirp"))[0]
    assert "a line of a platform's case runs in a partial test" in es.run_line_problems(
        run_line(kind="partial", variant="without", platform="chirp"))[0]
    assert "platform must be a platform name" in es.run_line_problems(run_line(kind="partial", platform="Chirp"))[0]
    path = evidence(root, [event_line(kind="partial", gate=DROP), run_line(kind="partial", platform="chirp")])
    assert es.evidence_file_problems(str(path), str(root)) == []


def test_status_shows_a_mean_and_runs_per_platform_and_model_and_the_gate_never_reads_them(root, capsys):
    skill = root / "skills" / "core-demo"
    skill_dir, cfg = gate_tree(root, [(T1, "full", "1.2.0", "2030-01-01", True, FULL_LINES("2030-01-01"))])
    before = es.gate_of(skill_dir, cfg)
    hashes = platform_cases(root)
    lines = [run_line(test=T2, kind="partial", version="1.2.0", case=7, case_sha256=hashes["7"], platform="chirp", score=s,
                      results=r, model=m) for s, r, m in ((1.0, [1, 1], "s-model"), (0.5, [1, 0], "s-model"), (0.0, [0, 0], "f-model"))]
    lines.append(run_line(test=T2, kind="partial", version="1.2.0", case=7, case_sha256=H["f"], platform="chirp", score=1.0,
                          results=[1, 1]))  # a case changed since: weight 0
    evidence(root, [event_line(test=T2, kind="partial", version="1.2.0", gate=DROP, cases={"7": hashes["7"]},
                               baseline={"7": "none"}, web_cases=[])] + lines, name=f"lab-{T2}.jsonl")
    assert es.platform_results(skill_dir, cfg) == {"chirp": {"f-model": {"mean": 0.0, "runs": 1}, "s-model": {"mean": 0.75, "runs": 2}}}
    assert es.gate_of(skill_dir, cfg) == before  # a platform's lines change neither the gate nor its pool
    assert es.platform_results(skill_dir, {**cfg, "measurement_floor": 6}) == {}
    (skill / "SKILL.md").write_text('---\nname: core-demo\nmetadata:\n  version: "2.0.0"\n---\n')
    assert es.platform_results(skill_dir, cfg) == {}  # nothing is carried across a major version
    (skill / "SKILL.md").write_text('---\nname: core-demo\nmetadata:\n  version: "1.2.0"\n---\n')
    configure(root)
    rows = {r["skill"]: r for r in es.all_status(str(root))["skills"]}
    models = rows["core-demo"]["models"]
    assert models["s-model"]["platforms"] == {"chirp": {"mean": 0.75, "runs": 2}}
    assert models["f-model"]["platforms"] == {"chirp": {"mean": 0.0, "runs": 1}} and rows["eng-other"]["models"] == {}
    assert "score" not in json.dumps(models["f-model"]["platforms"])
    assert es.main(["hash", "--skill", "core-demo"], root=str(root)) == 0
    assert json.loads(capsys.readouterr().out)["platform_cases"] == {"chirp": hashes}


# --- the fingerprint and the three kinds of measurement change (item B10) --------------------------------

def measured(root, **changes):
    """A tree whose gate file carries the fingerprint its files compute: a closed measurement version 5."""
    (root / "evals").mkdir(exist_ok=True)
    (root / "evals" / "grading-prompt.md").write_text("template\n")
    (root / "evals" / "measure.py").write_text("# measures\n")
    configure(root, measurement_version=5, measurement_floor=5, models={"s-model": ["provider/s-model"], "f-model": []},
              measurement_sha256=es.measurement_fingerprint(str(root)), **changes)


def gate_file(root):
    return json.loads((root / "evals" / "eval-gate.json").read_text())


def measurement(root, capsys, *args):
    code = es.main(["measurement", *args], root=str(root))
    return code, json.loads(capsys.readouterr().out)


def test_the_validator_fails_when_the_fingerprint_differs_from_the_committed_one(root):
    es.main(["inventory", "--write"], root=str(root))
    measured(root)
    assert check(root)[0] == []
    (root / "evals" / "measure.py").write_text("# measures otherwise\n")
    errors, _ = check(root)
    assert len(errors) == 1 and errors[0].startswith("evals/eval-gate.json: [measurement] the measurement fingerprint")
    assert "measurement --kind grader|execution|infrastructure" in errors[0]
    configure(root, measurement_version=5, measurement_floor=5, measurement_sha256=None)  # an open version: nothing compared
    assert check(root)[0] == [] and es.fingerprint_problem(str(root)) is None


def test_a_grader_side_change_raises_the_version_and_the_floor(root, capsys):
    measured(root)
    (root / "evals" / "grading-prompt.md").write_text("the grader is shown more\n")
    code, out = measurement(root, capsys, "--kind", "grader", "--cause", "The facts block lists the pushed branches.",
                            "--date", "2030-05-06")
    cfg = gate_file(root)
    assert code == 0 and (cfg["measurement_version"], cfg["measurement_floor"]) == (6, 6) and "epochs" not in cfg
    assert cfg["measurement_sha256"] == es.measurement_fingerprint(str(root)) == out["measurement_sha256"]
    assert es.gate_problems(str(root)) == [] and es.fingerprint_problem(str(root)) is None
    assert out["decisions_entry"].startswith("## 2030-05-06: measurement change, grader (measurement version 5 to 6)\n\n"
                                             "The facts block lists the pushed branches.\n")
    assert "Measurement version and floor: 6." in out["decisions_entry"]


def test_an_execution_side_change_raises_the_version_and_enters_an_epoch(root, capsys):
    measured(root)
    code, out = measurement(root, capsys, "--kind", "execution", "--cause", "gh 2.103 in the image.", "--date", "2030-05-06",
                            "--skills", "eng-other,core-demo")
    cfg = gate_file(root)
    assert code == 0 and (cfg["measurement_version"], cfg["measurement_floor"]) == (6, 5)
    assert cfg["epochs"] == [{"date": "2030-05-06", "models": "all", "skills": ["core-demo", "eng-other"], "cause": "gh 2.103 in the image."}]
    assert out["epoch"] == cfg["epochs"][0] and "Epoch 2030-05-06: skills core-demo, eng-other; models all." in out["decisions_entry"]
    # A hosted model that changed under its id: the same command, an epoch of that model; an alias is written as its id.
    code, _ = measurement(root, capsys, "--kind", "execution", "--cause", "The provider changed the model.", "--date", "2030-06-01",
                          "--models", "provider/s-model")
    cfg = gate_file(root)
    assert code == 0 and cfg["measurement_version"] == 7
    assert cfg["epochs"][1] == {"date": "2030-06-01", "models": ["s-model"], "skills": "all", "cause": "The provider changed the model."}
    assert es.gate_problems(str(root)) == [] and es.epoch_after(cfg, "core-demo", "s-model", "2030-05-31")
    assert not es.epoch_after(cfg, "core-demo", "f-model", "2030-05-31")
    for bad in (["--skills", "no-such-skill"], ["--models", "a-private-model"]):
        with pytest.raises(SystemExit) as e:
            es.main(["measurement", "--kind", "execution", "--cause", "x", *bad], root=str(root))
        assert e.value.code == 1


def test_an_infrastructure_change_writes_the_new_fingerprint_alone(root, capsys):
    measured(root)
    before = gate_file(root)
    with pytest.raises(SystemExit) as e:  # nothing changed: nothing to commit
        es.main(["measurement", "--kind", "infrastructure", "--cause", "x"], root=str(root))
    assert e.value.code == 1
    (root / "evals" / "measure.py").write_text("# measures, with a comment\n")
    code, out = measurement(root, capsys, "--kind", "infrastructure", "--cause", "A comment.", "--date", "2030-05-06")
    after = gate_file(root)
    unchanged = lambda cfg: {k: v for k, v in cfg.items() if k != "measurement_sha256"}
    assert code == 0 and unchanged(after) == unchanged(before)
    assert after["measurement_sha256"] == es.measurement_fingerprint(str(root)) != before["measurement_sha256"]
    assert out["decisions_entry"].startswith("## 2030-05-06: measurement change, infrastructure\n")


def test_an_open_version_is_closed_once_and_takes_no_change_of_a_kind(root, capsys):
    configure(root, measurement_version=5, measurement_floor=5, measurement_sha256=None)
    with pytest.raises(SystemExit) as e:
        es.main(["measurement", "--kind", "grader", "--cause", "x"], root=str(root))
    assert e.value.code == 1
    code, out = measurement(root, capsys, "--close", "--cause", "The last item of phase B.", "--date", "2030-05-06")
    assert code == 0 and gate_file(root)["measurement_sha256"] == es.measurement_fingerprint(str(root))
    assert out["decisions_entry"].startswith("## 2030-05-06: measurement version 5 closed\n") and es.evidence_refusal(str(root)) is None
    with pytest.raises(SystemExit) as e:
        es.main(["measurement", "--close", "--cause", "again"], root=str(root))
    assert e.value.code == 1


@pytest.mark.parametrize("args", [["measurement"], ["measurement", "--kind", "grader"], ["measurement", "--kind", "other", "--cause", "x"],
                                  ["measurement", "--close", "--kind", "grader", "--cause", "x"],
                                  ["measurement", "--kind", "grader", "--cause", "x", "--skills", "core-demo"],
                                  ["status", "--kind", "grader"], ["inventory", "--close"]])
def test_the_measurement_command_refuses_what_does_not_fit(root, args):
    measured(root)
    with pytest.raises(SystemExit) as e:
        es.main(args, root=str(root))
    assert e.value.code in (1, 2)


@pytest.mark.parametrize("epochs, why", [
    ("all", "epochs[0] must be"), ([{"date": "2030-01-01"}], "must be"),
    ([{"date": "soon", "models": "all", "skills": "all", "cause": "x"}], "date must be"),
    ([{"date": "2030-01-01", "models": [], "skills": "all", "cause": "x"}], "models must be"),
    ([{"date": "2030-01-01", "models": "all", "skills": ["Not A Name"], "cause": "x"}], "skills must be"),
    ([{"date": "2030-01-01", "models": "all", "skills": "all", "cause": "two\nlines"}], "cause must be"),
])
def test_an_epoch_outside_its_form_makes_the_gate_file_invalid(root, epochs, why):
    configure(root, epochs=epochs)
    assert any(why in p for p in es.gate_problems(str(root))), es.gate_problems(str(root))


def test_the_gate_file_is_written_in_its_own_layout_and_reads_back_the_same():
    cfg = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    text = es.format_gate({**cfg, "epochs": [{"date": "2030-01-01", "models": "all", "skills": ["core-demo"], "cause": "x"}]})
    assert json.loads(text)["epochs"][0]["skills"] == ["core-demo"] and json.loads(text)["models"] == cfg["models"]
    assert '"web_cases": {\n    "biz-icp-positioning": [1, 3],' in text and '"epochs": [\n    {\n' in text
