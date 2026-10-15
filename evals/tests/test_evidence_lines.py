"""Offline tests of evals/evidence_lines.py: the reading of an evidence file by what its own event line states
(backlog T24), and the two shapes of the model header (the old tiers and a list of models). No model is called."""
import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


es = load("eval_status_evidence_lines_test", "evals/eval_status.py")
el = es.EVIDENCE_LINES

COMMITTED = sorted(REPO.glob("skills/*/evals/evidence/lab-*.jsonl"))
H = {c: c * 64 for c in "abcdef"}


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def as_list_shape(lines):
    """The same file with the new header: a list of model ids and adapters keyed by model id."""
    event = copy.deepcopy(lines[0])
    event["adapters"] = {event["models"][tier]: event["adapters"][tier] for tier in event["models"]}
    event["models"] = list(event["models"].values())
    return [event] + lines[1:]


def tree(tmp_path, source, gate):
    """A tree with a copy of one committed evidence file and a gate file; returns (root, the copied path)."""
    skill = source.parents[2].name
    (tmp_path / "skills" / skill).mkdir(parents=True)
    (tmp_path / "skills" / skill / "SKILL.md").write_text("---\nname: " + skill + "\n---\n")
    target = tmp_path / "skills" / skill / "evals" / "evidence" / source.name
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "eval-gate.json").write_text(json.dumps(gate))
    return tmp_path, target


# --- T24 -------------------------------------------------------------------------------------------------

def test_the_repository_has_committed_evidence_to_test_against():
    assert COMMITTED and all(read(p)[0]["record"] == "test" for p in COMMITTED)


def test_a_committed_file_stays_valid_when_the_gate_file_changes_runs_and_drops_a_model(tmp_path):
    source = COMMITTED[0]
    event = read(source)[0]
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    root, path = tree(tmp_path, source, gate)
    assert es.evidence_file_problems(str(path), str(root)) == [] and es.evidence_problems(str(root)) == ({}, 1)
    # The gate file as a later change leaves it: another number of runs, and every model the file names removed.
    named = set(event["models"].values()) | {event["grader"]}
    later = copy.deepcopy(gate)
    later["runs"] = 5 if event["runs"] != 5 else 4
    later["models"] = {k: v for k, v in later["models"].items() if k not in named} or {"another-model": []}
    (root / "evals" / "eval-gate.json").write_text(json.dumps(later))
    assert not (named & set(es.known_models(es.load_gate(str(root)))))
    assert es.evidence_file_problems(str(path), str(root)) == []
    assert es.evidence_problems(str(root))[0] == {}
    assert es.main(["evidence"], root=str(root)) == 0


def test_every_committed_file_is_valid_by_its_own_event_line_with_no_gate_file(tmp_path):
    for source in COMMITTED:
        assert el.evidence_file_problems(str(source)) == [], source
    assert el.evidence_problems(str(REPO))[0] == {}


def test_a_malformed_model_id_is_still_refused(tmp_path):
    lines = read(COMMITTED[0])
    path = lambda: write(tmp_path / "skills" / "demo" / "evals" / "evidence" / COMMITTED[0].name, lines)
    event, run = lines[0], lines[1]
    event["grader"] = "a grader with spaces"
    assert any("grader must be a well-formed model id" in p for p in el.evidence_file_problems(str(path()), skill="demo"))
    lines = read(COMMITTED[0])
    lines[1]["model"] = "bad id!"
    assert any("model must be a well-formed model id" in p for p in el.evidence_file_problems(str(path()), skill="demo"))
    lines = read(COMMITTED[0])
    lines[0]["models"]["strong"] = "-leading-dash"
    assert any(p.startswith("line 1: models must be") for p in el.evidence_file_problems(str(path()), skill="demo"))


def test_a_run_line_names_a_model_of_its_event_line_or_unknown(tmp_path):
    lines = read(COMMITTED[0])
    run = lines[1]
    assert el.run_line_problems(run, lines[0]) == []
    assert el.run_line_problems({**run, "model": "unknown"}, lines[0]) == []
    assert el.run_line_problems({**run, "model": "some/well-formed-model"}, lines[0]) == ["model is not one of the event's models"]
    # The extra allowlist is the old, stricter reading; the validator never passes one.
    assert el.run_line_problems(run, None, {"another-model"}) == ["model must be a well-formed model id, or \"unknown\""]


def test_counts_and_upstream_name_only_models_the_event_line_names(tmp_path):
    event = read(COMMITTED[0])[0]
    other = {"with": dict.fromkeys(el.COUNT_KEYS, 0)}
    assert el.event_line_problems({**event, "counts": {**event["counts"], "an-unnamed-model": other}})[0].startswith("counts must be")
    assert el.event_line_problems({**event, "counts": {**event["counts"], event["grader"]: other}}) == []
    assert el.event_line_problems({**event, "upstream": {"an-unnamed-model": "a-provider"}})[0].startswith("upstream must be")
    assert el.event_line_problems({**event, "upstream": {event["grader"]: "a-provider"}}) == []


# --- the two shapes of the header ----------------------------------------------------------------------------

def test_the_old_header_gives_its_pairs_in_tier_order():
    event = read(COMMITTED[0])[0]
    assert el.event_model_pairs(event) == [(event["models"][t], event["adapters"][t]) for t in ("strong", "floor") if t in event["models"]]
    assert el.tier_model(event, "strong") == event["models"]["strong"] and el.tier_model(event, "nonesuch") is None


def test_a_file_with_the_list_header_is_read_and_gives_its_pairs(tmp_path):
    source = COMMITTED[0]
    old = read(source)
    new = as_list_shape(old)
    assert isinstance(new[0]["models"], list)
    path = write(tmp_path / "skills" / source.parents[2].name / "evals" / "evidence" / source.name, new)
    assert el.evidence_file_problems(str(path)) == []
    assert el.event_model_pairs(new[0]) == el.event_model_pairs(old[0])  # the same pairs from either shape
    assert es.event_model_pairs is el.event_model_pairs
    assert el.tier_model(new[0], "strong") is None  # a tier belongs to the old shape only


def test_the_list_header_may_name_unknown_and_a_model_with_a_path_and_a_tag():
    event = read(COMMITTED[0])[0]
    new = {key: value for key, value in as_list_shape([event])[0].items() if key != "upstream"}
    one = {**new, "models": ["unknown", "a/model:1"], "adapters": {"unknown": "agents-dir", "a/model:1": "claude-code"},
           "adapter_sha256": {"agents-dir": H["a"], "claude-code": H["b"]}, "counts": {}, "grader": "unknown"}
    assert el.event_line_problems(one) == []
    assert el.event_model_pairs(one) == [("unknown", "agents-dir"), ("a/model:1", "claude-code")]
    run = {**read(COMMITTED[0])[1], "model": "a/model:1", "adapter": "claude-code"}
    one["cases"] = {str(run["case"]): run["case_sha256"]}
    for key in ("skill", "kind", "version", "content_sha256", "measurement_version", "measurement_sha256", "test"):
        one[key] = run[key]
    assert el.run_line_problems(run, one) == []
    assert el.run_line_problems({**run, "adapter": "agents-dir"}, one) == []  # an adapter of the event
    assert el.run_line_problems({**run, "adapter": "another"}, one) == ["adapter is not one of the event's adapters"]


@pytest.mark.parametrize("change, why", [
    ({"models": []}, "models must be"),
    ({"models": ["a-model", "a-model"], "adapters": {"a-model": "agents-dir"}}, "models must be"),
    ({"models": ["a model with spaces"], "adapters": {"a model with spaces": "agents-dir"}}, "models must be"),
    ({"models": ["a-model", 3], "adapters": {"a-model": "agents-dir"}}, "models must be"),
    ({"models": ["a-model", "b-model"], "adapters": {"a-model": "agents-dir"}}, "adapters must be {model id: an adapter's folder name}"),
    ({"models": ["a-model"], "adapters": {"a-model": "agents-dir", "b-model": "agents-dir"}}, "adapters must be {model id:"),
    ({"models": ["a-model"], "adapters": {"strong": "agents-dir"}}, "adapters must be {model id:"),
    ({"models": ["a-model"], "adapters": {"a-model": "../agents-dir"}}, "adapters must be {model id:"),
    ({"models": ["a-model"], "adapters": ["agents-dir"]}, "adapters must be {model id:"),
    ({"models": "a-model"}, "models must be"),
    ({"models": {"floor": "a-model"}}, "models must be"),
])
def test_a_malformed_header_is_refused_with_a_clear_problem(change, why):
    event = as_list_shape([read(COMMITTED[0])[0]])[0]
    base = {**event, "models": ["a-model"], "adapters": {"a-model": "agents-dir"}, "adapter_sha256": {"agents-dir": H["a"]},
            "counts": {}, "grader": "a-model"}
    line = {**base, **change}
    problems = el.event_line_problems(line)
    assert any(why in p for p in problems), problems
    assert el.event_model_pairs(line) == []  # a malformed header names no pair


def test_the_runs_of_an_event_are_checked_against_its_range_and_its_lines_only():
    event = read(COMMITTED[0])[0]
    assert el.event_line_problems({**event, "runs": 10}) == []
    assert el.event_line_problems({**event, "runs": 11}) == ["runs must be a whole number from 1 to 10"]
    assert es.EVENT_RANGES["runs"] == el.RUNS_RANGE  # the gate file's "runs" is held to the same range


# --- the module is the one source of what eval_status.py re-exports -------------------------------------------

@pytest.mark.parametrize("name", ["event_line_problems", "run_line_problems", "read_evidence_file", "evidence_file_problems",
                                  "evidence_files", "skill_names", "event_model_pairs", "tier_model", "EVENT_REQUIRED",
                                  "EVENT_OPTIONAL", "RUN_REQUIRED", "RUN_OPTIONAL", "COUNT_KEYS", "MODEL_RE", "NAME_RE",
                                  "TEST_ID_RE", "HEX64_RE", "_model", "_is", "_keys", "_date", "_count", "_number", "_case_id"])
def test_eval_status_re_exports_the_same_object(name):
    assert getattr(es, name) is getattr(el, name)


def test_the_module_holds_no_gate_or_band_logic():
    text = (REPO / "evals" / "evidence_lines.py").read_text()
    for name in ("load_gate", "gate_of", "skill_band", "known_models", "event_config", "GATE_REL", "pessimistic_score"):
        assert name not in text, name


def test_the_module_prints_its_help():
    import subprocess
    r = subprocess.run([sys.executable, str(REPO / "evals" / "evidence_lines.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "The two shapes of the model header" in r.stdout


def test_a_case_that_brings_the_status_script_into_its_folder_brings_the_module_it_loads():
    er = load("eval_run_evidence_lines_test", "evals/eval_run.py")
    pairs = er.workbench_files({"id": 1, "workbench_files": ["evals/eval_status.py"]})
    assert [rel for _, rel in pairs] == ["evals/eval_status.py", "evals/evidence_lines.py"]
    assert [rel for _, rel in er.workbench_files({"id": 1, "workbench_files": ["evals/evidence_lines.py", "evals/eval_status.py"]})] == [
        "evals/evidence_lines.py", "evals/eval_status.py"]  # listed already: not added twice
    assert er.workbench_files({"id": 1}) == []
