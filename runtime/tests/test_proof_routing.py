"""Tests of runtime/proof.py: the proof file, its two checks, and the choice of the model a run goes to; and of
the operation and the shell command that show it. Offline: the facade's four functions (lab.standing,
lab.proof_inputs, lab.image, lab.measurement_problem) are replaced by stand-ins; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_proof_routing.py
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
proof = st.load("proof")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")

IMAGE = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
WEB = {"web": True}
NO_WEB = {"web": False}


def standing(floor_band="reliable", web_cases=(1,), images=(IMAGE,)):
    models = {"ref-model": {"band": "reliable", "cause": None, "score": 0.9, "mean": 0.97, "runs": 12}}
    if floor_band is not None:
        models["floor-model"] = {"band": floor_band, "cause": None if floor_band == "reliable" else "a cause",
                                 "score": 0.8, "mean": 0.9, "runs": 12}
    return {"skill": "demo", "version": "1.0.0", "models": models,
            "tiers": {"strong": {"model": "ref-model", "adapter": "ref-adapter"},
                      "floor": {"model": "floor-model", "adapter": "floor-adapter"}},
            "web_cases": list(web_cases), "evidence_images": list(images)}


@pytest.fixture
def facade(monkeypatch):
    """The facade's four functions, replaced. Returns the knobs a test turns and the count of standing calls."""
    knobs = {"standing": standing(), "inputs": "inputs-1", "measurement": None, "digest": IMAGE, "calls": 0}

    def fake_standing(skill):
        knobs["calls"] += 1
        return knobs["standing"]

    monkeypatch.setattr(lab, "standing", fake_standing)
    monkeypatch.setattr(lab, "proof_inputs", lambda skill: knobs["inputs"])
    monkeypatch.setattr(lab, "measurement_problem", lambda: knobs["measurement"])
    monkeypatch.setattr(lab, "image", lambda: {"name": "img", "digest": knobs["digest"], "platform": "linux/arm64"})
    return knobs


@pytest.fixture
def cfg(tmp_path):
    return {"data_dir": str(tmp_path / "data")}


def test_a_skill_reliable_on_the_floor_model_runs_there_when_both_checks_pass_and_the_runtime_has_its_key(facade, cfg):
    r = proof.route(cfg, "demo", WEB, floor_key=True)
    assert (r["tier"], r["model"], r["adapter"], r["proven"], r["autonomy"]) == ("floor", "floor-model", "floor-adapter", True, True)
    assert r["checks"] == {"measurement": None, "image": None} and r["bands"] == {"strong": "reliable", "floor": "reliable"}


@pytest.mark.parametrize("band", ["watch", "needs a test", None])
def test_a_skill_that_is_not_reliable_on_the_floor_model_runs_on_the_reference_model(facade, cfg, band):
    facade["standing"] = standing(floor_band=band)
    r = proof.route(cfg, "demo", WEB, floor_key=True)
    expected = band or "needs a test"
    assert (r["tier"], r["model"], r["adapter"], r["proven"]) == ("strong", "ref-model", "ref-adapter", True)
    assert r["bands"]["floor"] == expected and f"the band on the floor model is {expected}" in r["reasons"]


def test_when_the_measurement_files_differ_the_skill_runs_on_the_reference_model_and_without_autonomy(facade, cfg):
    facade["measurement"] = "the measurement fingerprint of this checkout differs"
    r = proof.route(cfg, "demo", WEB, floor_key=True)
    assert (r["tier"], r["proven"], r["autonomy"]) == ("strong", False, False)
    assert r["checks"]["measurement"] in r["reasons"]


@pytest.mark.parametrize("digest, reason", [
    (None, "the eval image is not on this machine"),
    (OTHER, "the image on this machine is not the one the evidence was measured in"),
])
def test_when_the_image_is_not_the_evidences_the_skill_runs_on_the_reference_model_and_without_autonomy(facade, cfg, digest, reason):
    facade["digest"] = digest
    r = proof.route(cfg, "demo", WEB, floor_key=True)
    assert (r["tier"], r["proven"], r["autonomy"], r["checks"]["image"]) == ("strong", False, False, reason)
    assert reason in r["reasons"]


def test_a_skill_measured_without_the_web_runs_without_it(facade, cfg):
    facade["standing"] = standing(web_cases=())
    r = proof.route(cfg, "demo", WEB)
    assert r["web"] is False
    assert "the skill requires the web and was measured without it: it runs without it" in r["reasons"]
    facade["standing"], facade["inputs"] = standing(), "inputs-2"
    assert proof.route(cfg, "demo", WEB)["web"] is True and proof.route(cfg, "demo", NO_WEB)["web"] is False


def test_the_person_can_ask_for_the_reference_model_and_never_for_the_floor_model(facade, cfg, tmp_path, capsys):
    r = proof.route(cfg, "demo", WEB, force="strong", floor_key=True)
    assert (r["tier"], r["model"]) == ("strong", "ref-model") and "the person asked for the reference model" in r["reasons"]
    with pytest.raises(ValueError):
        proof.route(cfg, "demo", WEB, force="floor", floor_key=True)
    assert cli.main(["run-next", "--project", str(tmp_path), "--tier", "floor"]) == 2
    with pytest.raises(ops.OpsError) as refused:
        ops.run_next(str(tmp_path), "floor")
    assert refused.value.code == 2


def test_the_proof_file_is_rebuilt_when_the_evidence_or_the_gate_file_changed(facade, cfg):
    first = proof.row(cfg, "demo")
    assert proof.row(cfg, "demo") == first and facade["calls"] == 1
    saved = json.loads((Path(cfg["data_dir"]) / "proof.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1 and saved["skills"]["demo"]["inputs_sha256"] == "inputs-1"
    facade["inputs"] = "inputs-2"
    proof.row(cfg, "demo")
    assert facade["calls"] == 2
    # The two checks are never cached: they run on every route.
    facade["digest"] = OTHER
    assert proof.route(cfg, "demo", WEB, floor_key=True)["tier"] == "strong" and facade["calls"] == 2


def test_the_run_row_and_the_pending_decision_carry_the_routing(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    path = str(built["project"])
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    out = ops.run_next(path)
    assert (out["routing"]["tier"], out["routing"]["model"], out["routing"]["adapter"]) == ("strong", "m", "h")
    ctx = ops_core.context(path)
    row = ctx["store"].task_runs_list(ctx["conn"], out["ran"])[0]
    assert (row["model"], row["adapter"], row["web"]) == ("m", "h", 0)
    assert ops.pending(path, out["pending_id"])["payload"]["routing"] == out["routing"]
    shown = ops.proof(path, "demo-asks")["skills"]["demo-asks"]
    assert (shown["tier"], shown["proven"], shown["checks"]) == ("strong", True, {"measurement": None, "image": None})


def test_no_operation_of_ops_has_the_name_of_a_module_it_imports():
    tree = ast.parse((Path(ops.__file__)).read_text(encoding="utf-8"))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.asname or alias.name for alias in node.names)  # the name the module is bound to
    operations = {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")}
    assert "proof" in operations and not operations & imported, operations & imported
