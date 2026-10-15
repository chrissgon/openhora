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
    if "gate" in event:  # the list header carries a gate for each model: the single gate was the strong tier's
        event["gate"] = {event["models"]["strong"]: event["gate"]}
    event["models"] = list(event["models"].values())
    return [event] + lines[1:]


def retired(gate, runs):
    """The gate file after a later change: another number of runs, and every model it listed replaced by others
    (a valid gate file: the configured models are among the listed ones)."""
    out = copy.deepcopy(gate)
    out.update(runs=runs, strong_model="next-strong", floor_model="next-floor", grader="next-grader",
               models={"next-strong": [], "next-floor": [], "next-grader": []})
    out["baseline_runs"] = min(out.get("baseline_runs", runs), runs)
    out.pop("lab_models", None)  # it names models of the list that is being replaced
    return out


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
    later = retired(gate, 5 if event["runs"] != 5 else 4)
    (root / "evals" / "eval-gate.json").write_text(json.dumps(later))
    assert es.gate_problems(str(root)) == [] and not (named & set(es.known_models(es.load_gate(str(root)))))
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


def test_a_run_line_names_a_model_of_its_event_line_and_unknown_only_when_the_header_names_it(tmp_path):
    lines = read(COMMITTED[0])
    run = lines[1]
    assert el.run_line_problems(run, lines[0]) == []
    assert el.run_line_problems({**run, "model": "unknown"}, lines[0]) == ["model is not one of the event's models"]
    assert el.run_line_problems({**run, "model": "some/well-formed-model"}, lines[0]) == ["model is not one of the event's models"]
    # The extra allowlist is the old, stricter reading; the validator never passes one.
    assert el.run_line_problems(run, None, {"another-model"}) == ["model must be a well-formed model id in the gate file's model list, or \"unknown\""]


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
           "adapter_sha256": {"agents-dir": H["a"], "claude-code": H["b"]}, "counts": {}, "grader": "unknown",
           "gate": {"a/model:1": next(iter(new["gate"].values()))}}
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

@pytest.mark.parametrize("name", ["event_line_problems", "run_line_problems", "read_evidence_file",
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


# --- a new file is read strictly (against the base), an old one by its own event line --------------------------

import os
import subprocess

GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
       "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "GIT_CONFIG_GLOBAL": os.devnull,
       "GIT_CONFIG_SYSTEM": os.devnull}


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=GIT, check=True).stdout.strip()


def committed_tree(tmp_path):
    """A git tree whose base commit holds one committed evidence file and the gate file; returns (root, old path, gate)."""
    source = COMMITTED[0]
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    root, old = tree(tmp_path, source, gate)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root, old, gate


def forged_copy(old, name, **event_changes):
    lines = read(old)
    lines[0].update(event_changes)
    lines[0]["test"] = lines[1]["test"] = name[4:-6]
    for line in lines[2:]:
        line["test"] = lines[0]["test"]
    return lines


def test_a_new_file_is_read_strictly_and_the_same_file_at_the_base_is_not(tmp_path, monkeypatch):
    root, old, gate = committed_tree(tmp_path)
    monkeypatch.setenv("WB_BASE_REF", git(root, "rev-parse", "HEAD"))
    gate_file = root / "evals" / "eval-gate.json"
    new_name = "lab-20300102T030405Z-0a1b2c3d.jsonl"
    problems_of = lambda: es.evidence_problems(str(root))[0]
    rel = lambda path: str(path.relative_to(root))
    # A forged event: runs 10 where the gate file configures 7. A new file is refused; the committed one is not.
    gate_file.write_text(json.dumps({**gate, "runs": 7, "baseline_runs": min(gate.get("baseline_runs", 7), 7)}))
    forged = write(old.parent / new_name, forged_copy(old, new_name, runs=10))
    found = problems_of()
    assert rel(old) not in found and any("runs is 10, and the configured number is 7" in p for p in found[rel(forged)])
    assert es.main(["evidence"], root=str(root)) == 1
    # A well-formed model name the gate file does not list: refused in a new file.
    forged = write(old.parent / new_name, forged_copy(old, new_name, grader="a-private-model-name"))
    assert any("grader must be a well-formed model id in the gate file's model list" in p for p in problems_of()[rel(forged)])
    # The gate file as a later change leaves it: another number of runs, every model replaced. The file committed
    # at the base stays valid; the new one is refused.
    gate_file.write_text(json.dumps(retired(gate, 7)))
    forged = write(old.parent / new_name, forged_copy(old, new_name))
    found = problems_of()
    assert rel(old) not in found and any(p.startswith("line 1: models must be") for p in found[rel(forged)])
    # Once the file is committed it is the base's, and is judged by its own event line.
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "second")
    monkeypatch.setenv("WB_BASE_REF", git(root, "rev-parse", "HEAD"))
    assert problems_of() == {}


def test_without_a_base_every_file_is_judged_by_its_own_event_line(tmp_path, monkeypatch):
    source = COMMITTED[0]
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    root, path = tree(tmp_path, source, retired(gate, 7))  # not a git tree
    assert es.comparison_base(str(root)) is None
    assert es.evidence_problems(str(root)) == ({}, 1)


def test_the_strict_reading_of_one_file_is_asked_for_by_the_caller(tmp_path):
    source = COMMITTED[0]
    event = read(source)[0]
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    gate["runs"] = event["runs"] + 1 if event["runs"] < 10 else event["runs"] - 1
    root, path = tree(tmp_path, source, gate)
    assert es.evidence_file_problems(str(path), str(root)) == []
    problems = es.evidence_file_problems(str(path), str(root), strict=True)
    assert problems and "the configured number is" in problems[0]
    (root / "evals" / "eval-gate.json").write_text(json.dumps(retired(gate, event["runs"])))
    assert any(p.startswith("line 1: models must be") for p in es.evidence_file_problems(str(path), str(root), strict=True))


def test_a_run_count_is_by_case_model_adapter_and_variant():
    event = {"runs": 2}
    line = lambda adapter, variant: {"case": 1, "model": "m", "adapter": adapter, "variant": variant}
    assert el.run_count_problems(event, [line("a", "with")] * 2 + [line("b", "with")] * 2 + [line("a", "without")] * 2) == []
    problems = el.run_count_problems(event, [line("a", "with")] * 3)
    assert problems == ["case 1 has 3 lines with the skill on m (a), more than the event's \"runs\", 2"]


# --- committed evidence is never edited; a wrong base is an error, a missing one a note ------------------------

def test_a_committed_file_edited_in_place_is_refused_and_an_unchanged_one_is_not(tmp_path, monkeypatch, capsys):
    root, old, gate = committed_tree(tmp_path)
    monkeypatch.setenv("WB_BASE_REF", git(root, "rev-parse", "HEAD"))
    rel = str(old.relative_to(root))
    (root / "evals" / "eval-gate.json").write_text(json.dumps(retired(gate, 7)))
    assert es.evidence_problems(str(root)) == ({}, 1)  # unchanged, and the gate dropped its models
    lines = read(old)
    lines[0]["models"]["floor"] = "a-private-model-name"
    lines[1]["model"] = "a-private-model-name"
    write(old, lines)  # a well-formed edit that the lenient reading alone would accept
    found = es.evidence_problems(str(root))[0]
    assert len(found[rel]) == 1 and "committed evidence is never edited" in found[rel][0]
    assert es.main(["evidence"], root=str(root)) == 1 and "committed evidence is never edited" in capsys.readouterr().err
    assert es.main(["evidence", "--file", str(old)], root=str(root)) == 1
    git(root, "checkout", "--", rel)  # restored: the base's bytes again
    assert es.evidence_problems(str(root)) == ({}, 1)
    assert es.main(["evidence", "--file", str(old)], root=str(root)) == 0


def test_a_base_ref_that_does_not_resolve_is_an_error_and_not_a_lenient_reading(tmp_path, tmp_path_factory, monkeypatch):
    root, old, gate = committed_tree(tmp_path)
    monkeypatch.setenv("WB_BASE_REF", "no-such-ref")
    found, checked = es.evidence_problems(str(root))
    assert checked == 1 and list(found) == ["WB_BASE_REF"] and "names no commit of this checkout" in found["WB_BASE_REF"][0]
    assert es.main(["evidence"], root=str(root)) == 1
    # Outside a git checkout the variable is not read: there is no base to name.
    plain, _ = tree(tmp_path_factory.mktemp("plain"), COMMITTED[0], gate)
    assert es.evidence_problems(str(plain)) == ({}, 1)


def test_without_a_base_in_a_git_checkout_the_reading_is_lenient_and_a_note_is_printed(tmp_path, monkeypatch, capsys):
    source = COMMITTED[0]
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    root, old = tree(tmp_path, source, gate)
    git(root, "init", "-q", "-b", "feature")  # no main, master or origin: no default branch to compare with
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    monkeypatch.delenv("WB_BASE_REF", raising=False)
    (root / "evals" / "eval-gate.json").write_text(json.dumps(retired(gate, 7)))
    assert es.evidence_problems(str(root)) == ({}, 1)
    assert "no comparison base" in capsys.readouterr().err


def test_the_blob_id_of_a_working_file_is_the_one_git_gives_and_survives_a_crlf_checkout(tmp_path, monkeypatch):
    root, old, gate = committed_tree(tmp_path)
    rel = str(old.relative_to(root))
    committed = git(root, "rev-parse", "HEAD:" + rel)
    import hashlib
    raw = hashlib.sha1(b"blob %d\0" % len(old.read_bytes()) + old.read_bytes()).hexdigest()
    assert es.blob_id(str(old), str(root)) == committed == raw  # a plain file: git and the raw bytes agree
    assert es.blob_id(str(old)) == raw and es.blob_id(str(tmp_path / "nonesuch")) is None
    # A checkout that converts line endings (core.autocrlf=true) holds CRLF where the blob holds LF: not an edit.
    git(root, "config", "core.autocrlf", "true")
    old.write_bytes(old.read_bytes().replace(b"\n", b"\r\n"))
    assert es.blob_id(str(old), str(root)) == committed
    assert es.blob_id(str(old)) != committed  # the raw bytes alone would call it an edit
    monkeypatch.setenv("WB_BASE_REF", git(root, "rev-parse", "HEAD"))
    standing, error, note = es.evidence_standing(str(root))
    assert error is None and standing(rel) == "same"
    assert es.evidence_problems(str(root)) == ({}, 1)


# --- package P2b: where the image came from, and an upstream for every model that ran through a key proxy ---------

def test_image_source_is_an_optional_key_of_the_event_line_and_upstream_may_name_several_models():
    event = read(COMMITTED[0])[0]
    assert "image_source" in el.EVENT_OPTIONAL and "image_source" not in event  # every committed file predates it
    for source in ("published", "local"):
        assert el.event_line_problems({**event, "image_source": source}) == []
    for bad in ("pulled", "", None, 3):
        assert el.event_line_problems({**event, "image_source": bad})[0].startswith("image_source must be")
    upstream = {model: "a-provider" for model in event["models"].values()}
    assert el.event_line_problems({**event, "upstream": upstream}) == []  # one for each model that ran through a proxy, not the floor only


# --- package P2c: the gate of an event line, keyed by model, and the usage of a run -----------------------------

GATE_OF_ONE = {"passed": True, "with": 0.9, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05}


def full_event():
    """A committed full test with a gate, in the old shape (a single gate) and in the list shape (a gate for each model)."""
    old = next(read(p)[0] for p in COMMITTED if "gate" in read(p)[0])
    return old, as_list_shape([old])[0]


def test_an_old_events_single_gate_and_a_list_events_keyed_gate_are_both_read():
    old, new = full_event()
    assert el.event_line_problems(old) == [] and el.event_line_problems(new) == []
    strong = old["models"]["strong"]
    assert el.event_gates(old) == {strong: old["gate"]} and el.event_gates(new) == {strong: old["gate"]}
    assert el.event_gates({k: v for k, v in old.items() if k != "gate"}) == {} and el.event_gates("nothing") == {}
    assert es.event_gates is el.event_gates


@pytest.mark.parametrize("change", [
    {"gate": GATE_OF_ONE},  # a single gate under a list header
    {"gate": {}},
    {"gate": {"a-model": {"passed": "yes"}}},
    {"gate": {"b-model": GATE_OF_ONE}},  # a model the event does not list
    {"gate": {"a-model": GATE_OF_ONE, "unknown": GATE_OF_ONE}},
    {"gate": ["a-model"]},
])
def test_a_malformed_keyed_gate_is_refused(change):
    _, new = full_event()
    line = {**{k: v for k, v in new.items() if k != "upstream"}, "models": ["a-model"], "adapters": {"a-model": "agents-dir"},
            "adapter_sha256": {"agents-dir": H["a"]}, "counts": {}, "grader": "a-model", "gate": {"a-model": GATE_OF_ONE}}
    assert el.event_line_problems(line) == []
    problems = el.event_line_problems({**line, **change})
    assert any(p.startswith("gate must be {model id") for p in problems), problems


def test_a_keyed_gate_belongs_to_a_list_header_and_a_single_gate_to_the_old_one():
    old, new = full_event()
    keyed = {old["models"]["strong"]: old["gate"]}
    assert any(p.startswith("gate must be {\"passed\"") for p in el.event_line_problems({**old, "gate": keyed}))
    assert el.event_gates({**old, "gate": keyed}) == {}  # neither form: no one's gate is read from it


def test_a_keyed_gate_may_carry_a_gate_for_each_model_and_the_baseline_expired_note():
    _, new = full_event()
    models = list(new["models"])
    gates = {m: {**GATE_OF_ONE, **({"note": "baseline expired"} if i else {})} for i, m in enumerate(models)}
    assert el.event_line_problems({**new, "gate": gates}) == []
    assert el.event_line_problems({**new, "gate": {models[0]: {**GATE_OF_ONE, "note": "something else"}}})
    assert any("gate belongs to a full test only" in p for p in el.event_line_problems({**new, "kind": "partial", "gate": gates}))
    assert any("gate is written by a complete full test only" in p for p in el.event_line_problems({**new, "complete": False, "gate": gates}))
    assert "a complete full test carries its gate" in el.event_line_problems({k: v for k, v in new.items() if k != "gate"})


USAGE = {"input": 120, "output": 40, "cache_read": 3000, "cache_write": 0}


def test_a_run_line_with_or_without_usage_is_valid_and_a_malformed_usage_is_refused():
    run = next(line for line in read(COMMITTED[0])[1:] if "usage" not in line)
    assert "usage" in el.RUN_OPTIONAL and el.USAGE_KEYS == ("input", "output", "cache_read", "cache_write")
    assert es.USAGE_KEYS is el.USAGE_KEYS
    assert el.run_line_problems(run) == [] and el.run_line_problems({**run, "usage": USAGE}) == []
    assert el.run_line_problems({**run, "usage": {k: 0 for k in USAGE}}) == []
    for bad in ({**USAGE, "input": -1}, {**USAGE, "output": 1.5}, {**USAGE, "input": True}, {**USAGE, "cache_read": "3"},
                {k: v for k, v in USAGE.items() if k != "cache_write"}, {**USAGE, "total": 3160}, [1, 2, 3, 4], None, 3160):
        problems = el.run_line_problems({**run, "usage": bad})
        assert problems and problems[0].startswith("usage must be {"), bad


def test_complete_models_is_a_list_of_models_of_the_header_and_an_old_event_reads_its_lead_s_completion():
    old, new = full_event()
    lead, other = new["models"][0], new["models"][1]
    assert "complete_models" in el.EVENT_OPTIONAL and es.event_complete_models is el.event_complete_models
    assert el.event_line_problems({**new, "complete_models": [lead, other]}) == []
    assert el.event_line_problems({**new, "complete_models": [lead]}) == []
    assert any(p.startswith("complete_models must be") for p in el.event_line_problems({**new, "complete_models": [lead, "a-model"]}))
    assert any(p.startswith("complete_models must be") for p in el.event_line_problems({**new, "complete_models": [lead, lead]}))
    assert any(p.startswith("complete_models must be") for p in el.event_line_problems({**new, "complete_models": lead}))
    assert any(p.startswith("complete_models must be") for p in el.event_line_problems({**old, "complete_models": [lead]}))  # a list header only
    assert any("complete for its lead model" in p for p in el.event_line_problems({**new, "complete_models": [other]}))
    assert el.event_line_problems({**new, "complete": False, "complete_models": [other], "gate": {other: GATE_OF_ONE}}) == [
        "gate is written by a complete full test only: an event closed as abandoned evaluates no gate"]
    assert any(p.startswith("gate must be {model id") for p in el.event_line_problems(
        {**new, "complete_models": [lead], "gate": {other: GATE_OF_ONE}}))  # a gate only for a model the event is complete for
    # What a line without the key says: its lead model's "complete", nothing for another.
    assert el.event_complete_models(old) == [old["models"]["strong"]] and el.event_complete_models(new) == [lead]
    assert el.event_complete_models({**old, "complete": False}) == [] and el.event_complete_models("x") == []
    assert el.event_complete_models({**new, "complete_models": [other]}) == [other]
    assert el.lead_model(old) == old["models"]["strong"] and el.lead_model(new) == lead and el.lead_model({}) is None


def test_a_new_file_must_be_of_the_lab_models_through_their_configured_adapters(tmp_path, monkeypatch):
    root, old, gate = committed_tree(tmp_path)
    monkeypatch.setenv("WB_BASE_REF", git(root, "rev-parse", "HEAD"))
    gate_file = root / "evals" / "eval-gate.json"
    new_name = "lab-20300102T030405Z-0a1b2c3d.jsonl"
    rel = lambda path: str(path.relative_to(root))
    problems_of = lambda: es.evidence_problems(str(root))[0]
    event = read(old)[0]
    strong, floor = event["models"]["strong"], event["models"]["floor"]
    # The file as it is: the lab models through their configured adapters. New, and valid.
    forged = write(old.parent / new_name, forged_copy(old, new_name))
    assert rel(forged) not in problems_of()
    # A model of the gate file's list that is not a lab model: its evidence stays local.
    gate_file.write_text(json.dumps({**gate, "lab_models": [strong]}))
    found = problems_of()
    assert rel(old) not in found  # the committed file is judged by its own event line
    assert any(f"{floor} is not one of the gate file's lab models" in p for p in found[rel(forged)])
    # A lab model through another adapter than its entry's.
    gate_file.write_text(json.dumps(gate))
    swapped = forged_copy(old, new_name, adapters={"strong": event["adapters"]["floor"], "floor": event["adapters"]["strong"]})
    write(old.parent / new_name, swapped)
    found = problems_of()
    assert any(f"{strong} ran through the adapter" in p and "evidence in the repository is of the configured pair" in p
               for p in found[rel(forged)])
    # Without lab_models the configured strong and floor models are the lab models.
    without = {k: v for k, v in gate.items() if k != "lab_models"}
    gate_file.write_text(json.dumps(without))
    write(old.parent / new_name, forged_copy(old, new_name))
    assert rel(forged) not in problems_of()
    assert es.lab_pairs(without) == es.lab_pairs(gate) and set(es.lab_pairs(gate)) == {strong, floor}


def test_an_old_evidence_file_stays_valid_against_a_changed_gate_file_and_a_line_may_carry_usage(tmp_path):
    source = COMMITTED[0]
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text())
    root, old = tree(tmp_path, source, retired(gate, 7))  # the gate file no longer lists the models the file names
    assert es.evidence_file_problems(str(old), str(root)) == [] and es.evidence_problems(str(root)) == ({}, 1)
    lines = read(old)
    lines[1] = {**lines[1], "usage": USAGE}  # one run line with usage, among lines without
    write(old, lines)
    assert es.evidence_file_problems(str(old), str(root)) == []
