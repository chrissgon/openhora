"""Offline tests of the gate file's keys "baseline_runs" and "baseline_margin" in evals/eval_status.py: their
defaults, their ranges, and the committed gate file. No model is called."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "evals" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


es = load("eval_status")


def test_baseline_runs_defaults_to_runs_and_the_margin_to_none():
    assert es.event_config({})["baseline_runs"] == 3
    assert es.event_config({"runs": 2})["baseline_runs"] == 2
    assert es.event_config({"baseline_runs": 1})["baseline_runs"] == 1
    assert es.event_config({})["baseline_margin"] is None
    assert es.event_config({"baseline_margin": 0.2})["baseline_margin"] == 0.2


def test_baseline_runs_is_a_whole_number_from_1_to_runs():
    assert es.event_problems({"baseline_runs": 1}) == []
    assert es.event_problems({"baseline_runs": 0}) != []
    assert es.event_problems({"baseline_runs": True}) != []
    assert es.event_problems({"runs": 2, "baseline_runs": 3}) == ["baseline_runs must not be above runs"]


def test_baseline_margin_is_a_number_from_0_to_1():
    assert es.event_problems({"baseline_margin": 0.2}) == []
    for bad in (-0.1, 1.5, True, "0.2"):
        assert es.event_problems({"baseline_margin": bad}) == ["baseline_margin must be a number from 0 to 1"]



# --- package P2b: the model list names what a model needs, so that a model is a line in it ----------------------

import copy
import json
import shutil

import pytest

GATE = json.loads((REPO / "evals" / "eval-gate.json").read_text(encoding="utf-8"))


def tree_with_gate(tmp_path, cfg):
    """A tree with the files the measurement fingerprint covers (copied) and a gate file; returns its root."""
    for rel in es.FINGERPRINT_FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, tmp_path / rel)
    shutil.copytree(REPO / "evals" / "container", tmp_path / "evals" / "container", ignore=shutil.ignore_patterns("__pycache__"))
    for adapter in (REPO / "adapters").iterdir():
        if (adapter / "run-prompt.sh").is_file():
            (tmp_path / "adapters" / adapter.name).mkdir(parents=True)
            for name in ("run-prompt.sh", "eval.json"):
                shutil.copy(adapter / name, tmp_path / "adapters" / adapter.name / name)
    (tmp_path / "evals" / "eval-gate.json").write_text(json.dumps(cfg))
    return tmp_path


def entry(**changes):
    return {**GATE["models"]["openrouter/deepseek/deepseek-v4.1-flash"], "aliases": [], **changes}


def test_the_committed_gate_file_lists_the_lab_models_in_the_object_shape_with_a_route_each():
    assert es.gate_problems() == []
    assert GATE["lab_models"] == ["claude-sonnet-5-5", "openrouter/deepseek/deepseek-v4.1-flash"]
    for model, found in GATE["models"].items():
        assert set(found) - set(es.MODEL_ENTRY_OPTIONAL) == set(es.MODEL_ENTRY_KEYS) and found["upstream_models"] and found["run_token_budget"] >= 3 * 1_600_052
        assert (REPO / "evals" / "container" / "keyproxy" / f"route-{found['route']}.json").is_file(), model
    assert es.known_models(GATE) == {"claude-sonnet-5-5": [],
                                     "openrouter/deepseek/deepseek-v4.1-flash": ["deepseek/deepseek-v4.1-flash", "deepseek-v4.1-flash"]}
    assert es.model_entry(GATE, "deepseek-v4.1-flash")["id"] == "openrouter/deepseek/deepseek-v4.1-flash"
    assert es.model_entry(GATE, "nobody") is None and es.model_entry({}, "x") is None and es.model_entry(GATE, None) is None


def test_adding_a_model_to_the_list_and_to_a_route_leaves_the_measurement_fingerprint_unchanged(tmp_path):
    root = tree_with_gate(tmp_path, GATE)
    before = es.measurement_fingerprint(str(root))
    with_model = copy.deepcopy(GATE)
    with_model["models"]["openrouter/vendor/a-new-model"] = entry(aliases=["a-new-model"], upstream_models=["vendor/a-new-model"],
                                                                  provider_pin="another-provider")
    with_model["lab_models"].append("openrouter/vendor/a-new-model")
    (root / "evals" / "eval-gate.json").write_text(json.dumps(with_model))
    assert es.gate_problems(str(root)) == []
    assert es.measurement_fingerprint(str(root)) == before  # the gate file is outside the fingerprint
    assert "openrouter/vendor/a-new-model" in es.known_models(es.load_gate(str(root)))
    # and the executor serves it at once: its route, its pin and the names its runner sends come from that entry
    spec = importlib.util.spec_from_file_location("executor_gate", REPO / "evals" / "executor.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    found = ex.model_entry("a-new-model", str(root / "evals" / "eval-gate.json"))
    assert found["route"] == "openrouter" and found["provider_pin"] == "another-provider" and found["upstream_models"] == ["vendor/a-new-model"]


def test_a_model_may_still_be_a_list_of_aliases_unless_it_is_a_lab_model_or_the_grader(tmp_path):
    cfg = copy.deepcopy(GATE)
    cfg["models"]["vendor/other"] = ["other"]  # known to the evidence, run by nobody: the list form is enough
    assert es.gate_problems(str(tree_with_gate(tmp_path / "a", cfg))) == []
    assert es.known_models(cfg)["vendor/other"] == ["other"] and es.model_entry(cfg, "other") is None
    cfg["models"]["claude-sonnet-5-5"] = []  # a lab model and the grader need their entry's adapter and key
    problems = es.gate_problems(str(tree_with_gate(tmp_path / "b", cfg)))
    assert any("'claude-sonnet-5-5' as a list of aliases" in p for p in problems), problems


@pytest.mark.parametrize("change, why", [
    ({"route": 3}, "wrong type for 'route'"), ({"upstream_models": []}, "upstream_models must list"),
    ({"upstream_models": ["a", "a"]}, "upstream_models must list"), ({"upstream_models": [5]}, "upstream_models must list"),
    ({"provider_pin": "-x"}, "provider_pin must name"), ({"provider_pin": 5}, "wrong type for 'provider_pin'"),
    ({"price_source": "http://insecure.example/price"}, "price_source must be an https URL"),
    ({"run_token_budget": 0}, "run_token_budget must be a positive"), ({"run_token_budget": True}, "wrong type for 'run_token_budget'"),
    ({"pass_env": ["not a name"]}, "pass_env must list variable names"), ({"adapter": "../x"}, "adapter must be"),
    ({"pass_env": ["OPENROUTER_API_KEY", "OP_SERVICE_ACCOUNT_TOKEN"]}, "pass_env names OP_SERVICE_ACCOUNT_TOKEN, a token variable"),
    ({"web_pass_env": ["OP_SESSION_demo"]}, "web_pass_env names OP_SESSION_demo, a token variable"),
    ({"web_pass_env": ["GITHUB_TOKEN"]}, "web_pass_env names GITHUB_TOKEN, a token variable"),
    ({"route": None}, "holds no key"), ({"extra": 1}, "unknown key 'extra'"),
])
def test_an_entry_outside_its_form_is_a_gate_file_problem(tmp_path, change, why):
    cfg = copy.deepcopy(GATE)
    cfg["models"]["openrouter/deepseek/deepseek-v4.1-flash"] = {**entry(aliases=["deepseek/deepseek-v4.1-flash", "deepseek-v4.1-flash"]), **change}
    problems = es.gate_problems(str(tree_with_gate(tmp_path, cfg)))
    assert any(why in p for p in problems), problems


def test_an_entry_that_lacks_a_key_is_named(tmp_path):
    cfg = copy.deepcopy(GATE)
    del cfg["models"]["claude-sonnet-5-5"]["run_token_budget"]
    assert any("lacks the key 'run_token_budget'" in p for p in es.gate_problems(str(tree_with_gate(tmp_path, cfg))))


REMOVED = ("strong_model", "strong_harness", "floor_model", "floor_harness", "strong_pass_env", "floor_pass_env",
           "strong_tolerance", "strong_web_pass_env")


def test_the_tiers_leave_the_gate_file_and_the_new_shape_is_accepted(tmp_path):
    assert not [k for k in GATE if k.startswith(("strong_", "floor_"))]
    assert GATE["tolerance"] == 0.05 and set(GATE["web_jobs"]) <= set(GATE["models"]) and GATE["lab_models"]
    assert es.gate_problems(str(tree_with_gate(tmp_path / "ok", copy.deepcopy(GATE)))) == []
    for i, key in enumerate(REMOVED):
        cfg = {**copy.deepcopy(GATE), key: "x" if key.endswith(("model", "harness")) else []}
        assert f"unknown field {key!r}" in es.gate_problems(str(tree_with_gate(tmp_path / f"r{i}", cfg))), key


@pytest.mark.parametrize("key", ["lab_models", "tolerance", "models", "grader"])
def test_a_required_key_that_is_missing_is_named(tmp_path, key):
    cfg = copy.deepcopy(GATE)
    del cfg[key]
    assert f"missing field {key!r}" in es.gate_problems(str(tree_with_gate(tmp_path, cfg)))


def test_web_jobs_is_per_model_and_an_entry_may_carry_a_web_key(tmp_path):
    cfg = copy.deepcopy(GATE)
    cfg["web_jobs"] = {"claude-sonnet-5-5": 3}
    cfg["models"]["claude-sonnet-5-5"]["web_pass_env"] = ["CLAUDE_CODE_WEB_API_KEY"]
    assert es.gate_problems(str(tree_with_gate(tmp_path / "a", cfg))) == []
    assert es.event_config(cfg)["web_jobs"] == {"claude-sonnet-5-5": 3}
    cfg["web_jobs"] = {"nobody": 1}
    assert any("web_jobs names a model" in p for p in es.gate_problems(str(tree_with_gate(tmp_path / "b", cfg))))
    cfg["web_jobs"] = {"claude-sonnet-5-5": 0}
    assert any("web_jobs must map a model id" in p for p in es.gate_problems(str(tree_with_gate(tmp_path / "c", cfg))))
    cfg["web_jobs"], cfg["models"]["claude-sonnet-5-5"]["web_pass_env"] = {}, ["not a name"]
    assert any("web_pass_env must list variable names" in p for p in es.gate_problems(str(tree_with_gate(tmp_path / "d", cfg))))


def test_lab_models_names_known_models_only(tmp_path):
    cfg = copy.deepcopy(GATE)
    cfg["lab_models"] = ["claude-sonnet-5-5", "not-a-listed-model"]
    assert any("lab_models names a model" in p for p in es.gate_problems(str(tree_with_gate(tmp_path / "a", cfg))))
    for i, bad in enumerate(([], "claude-sonnet-5-5", ["claude-sonnet-5-5", "claude-sonnet-5-5"])):
        cfg["lab_models"] = bad
        assert any("lab_models" in p for p in es.gate_problems(str(tree_with_gate(tmp_path / f"b{i}", cfg))))


def test_a_model_must_name_a_route_that_has_a_file_and_pass_the_routes_key(tmp_path):
    cfg = copy.deepcopy(GATE)
    cfg["models"]["openrouter/deepseek/deepseek-v4.1-flash"]["route"] = "nonesuch"
    problems = es.gate_problems(str(tree_with_gate(tmp_path / "a", cfg)))
    assert any("names the route 'nonesuch', which has no readable route-nonesuch.json" in p for p in problems), problems
    cfg = copy.deepcopy(GATE)
    cfg["models"]["openrouter/deepseek/deepseek-v4.1-flash"]["pass_env"] = ["SOMETHING_ELSE"]
    problems = es.gate_problems(str(tree_with_gate(tmp_path / "b", cfg)))
    assert any("whose key is OPENROUTER_API_KEY, and does not pass it in pass_env" in p for p in problems), problems
