"""Tests of web_measured (package P1 of the delegation platform plan): the proof turns the web on for a skill that
requires it only on a model whose current set holds a with-skill lab line of a web case, and the flag is stored on each
pair of the proof file, not on the entry. Offline: the status script's functions are replaced by stand-ins for
lab.standing, and the facade's four functions for proof; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_proof_web_measured.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
proof = st.load("proof")

IMAGE = "sha256:" + "a" * 64
WEB = {"web": True}
REASON = "the skill requires the web and was measured without it: it runs without it"
FIGURES = {"band": "reliable", "cause": None, "score": 0.9, "mean": 0.97, "runs": 12}


def line(case, model, variant="with"):
    return {"case": case, "model": model, "variant": variant}


@pytest.fixture
def status(monkeypatch):
    """The status script's four functions lab.standing reads, replaced; returns the knobs a test turns. The pools
    are what lab_view returns: per model, the current set and the inherited lines."""
    module = lab.LAB.load_status()
    monkeypatch.setattr(lab.LAB, "load_status", lambda: module)  # the facade loads the script afresh on every call
    knobs = {"web_cases": {"demo": [1, 3]}, "pools": {}, "views": []}

    monkeypatch.setattr(module, "load_gate", lambda root: {
        "strong_model": "ref-model", "strong_harness": "ref-adapter", "floor_model": "floor-model",
        "floor_harness": "floor-adapter", "measurement_floor": 1, "web_cases": knobs["web_cases"]})
    monkeypatch.setattr(module, "skill_evidence", lambda skill_dir: [])
    monkeypatch.setattr(module, "all_status", lambda root, only=None: {"skills": [
        {"version": "1.0.0", "models": {m: dict(FIGURES) for m in ("ref-model", "floor-model")}}]})

    def lab_view(root, skill_dir, cfg, events=None):
        knobs["views"].append((skill_dir, cfg, events))
        return {"version": "1.0.0", "reference": "ref-model", "pools": knobs["pools"]}

    monkeypatch.setattr(module, "lab_view", lab_view)
    return knobs


def web(found):
    return {model: figures["web_measured"] for model, figures in found["models"].items()}


def test_a_case_listed_as_a_web_case_with_no_evidence_does_not_turn_the_web_on(status):
    found = lab.standing("demo")
    assert found["web_cases"] == [1, 3]  # kept, for information
    assert web(found) == {"ref-model": False, "floor-model": False}
    status["pools"] = {"ref-model": {"current": [], "inherited": [line(1, "ref-model")]}}  # inherited lines do not count
    assert web(lab.standing("demo")) == {"ref-model": False, "floor-model": False}


def test_a_web_case_with_evidence_on_one_model_turns_the_web_on_for_that_model_only(status):
    status["pools"] = {"floor-model": {"current": [line(3, "floor-model")], "inherited": []},
                       "ref-model": {"current": [line(2, "ref-model")], "inherited": []}}  # case 2 is not a web case
    assert web(lab.standing("demo")) == {"ref-model": False, "floor-model": True}
    status["pools"] = {"ref-model": {"current": [line("1", "ref-model")], "inherited": []}}  # case ids compare as text
    assert web(lab.standing("demo")) == {"ref-model": True, "floor-model": False}


def test_the_current_set_is_the_status_scripts_own_for_the_skill_and_its_gate(status):
    lab.standing("demo")
    (skill_dir, cfg, events), = status["views"]
    assert Path(skill_dir).name == "demo" and cfg["strong_model"] == "ref-model" and events == []


def test_a_skill_with_no_web_case_in_the_gate_file_is_not_measured_with_the_web(status):
    status["web_cases"] = {}
    status["pools"] = {"ref-model": {"current": [line(1, "ref-model")], "inherited": []}}
    found = lab.standing("demo")
    assert found["web_cases"] == [] and web(found) == {"ref-model": False, "floor-model": False}


def test_the_standing_of_a_real_skill_carries_a_flag_for_every_model():
    found = lab.standing("biz-market-analysis")
    assert found["models"] and all(isinstance(m["web_measured"], bool) for m in found["models"].values())


def proof_standing(web_models):
    models = {name: dict(FIGURES, web_measured=name in web_models) for name in ("ref-model", "floor-model")}
    return {"skill": "demo", "version": "1.0.0", "models": models,
            "tiers": {"strong": {"model": "ref-model", "adapter": "ref-adapter"},
                      "floor": {"model": "floor-model", "adapter": "floor-adapter"}},
            "web_cases": [1], "evidence_images": [IMAGE]}  # a listed case, whatever the evidence says


@pytest.fixture
def facade(monkeypatch):
    knobs = {"standing": proof_standing(()), "inputs": "inputs-1", "calls": 0}

    def fake_standing(skill):
        knobs["calls"] += 1
        return knobs["standing"]

    monkeypatch.setattr(lab, "standing", fake_standing)
    monkeypatch.setattr(lab, "proof_inputs", lambda skill: knobs["inputs"])
    monkeypatch.setattr(lab, "measurement_problem", lambda: None)
    monkeypatch.setattr(lab, "image", lambda: {"name": "img", "digest": IMAGE, "platform": "linux/arm64"})
    return knobs


@pytest.fixture
def cfg(tmp_path):
    return {"data_dir": str(tmp_path / "data")}


def test_a_listed_case_with_no_evidence_runs_the_skill_without_the_web_on_either_model(facade, cfg):
    for floor_key in (False, True):
        r = proof.route(cfg, "demo", WEB, floor_key=floor_key)
        assert r["web"] is False and REASON in r["reasons"]


def test_the_web_follows_the_model_the_run_goes_to(facade, cfg):
    facade["standing"] = proof_standing(("floor-model",))
    floor = proof.route(cfg, "demo", WEB, floor_key=True)
    assert (floor["tier"], floor["web"]) == ("floor", True) and REASON not in floor["reasons"]
    strong = proof.route(cfg, "demo", WEB, floor_key=False)  # no key for the floor model: the reference model, unmeasured
    assert (strong["tier"], strong["web"]) == ("strong", False) and REASON in strong["reasons"]
    forced = proof.route(cfg, "demo", WEB, force="strong", floor_key=True)
    assert (forced["tier"], forced["web"]) == ("strong", False)
    facade["standing"], facade["inputs"] = proof_standing(("ref-model",)), "inputs-2"
    assert proof.route(cfg, "demo", WEB, floor_key=True)["web"] is False  # floor chosen, measured on the other model only
    assert proof.route(cfg, "demo", WEB, force="strong")["web"] is True
    assert proof.route(cfg, "demo", {"web": False}, force="strong")["web"] is False  # a skill that does not require it


def test_the_flag_is_stored_on_each_pair_and_not_on_the_entry(facade, cfg):
    facade["standing"] = proof_standing(("floor-model",))
    entry = proof.row(cfg, "demo")
    assert "web_measured" not in entry
    assert {pair["tier"]: pair["web_measured"] for pair in entry["pairs"]} == {"strong": False, "floor": True}


def test_a_model_with_no_standing_is_not_measured_with_the_web(facade, cfg):
    facade["standing"] = proof_standing(())
    del facade["standing"]["models"]["floor-model"]
    assert [pair["web_measured"] for pair in proof.row(cfg, "demo")["pairs"]] == [False, False]


def test_a_proof_file_of_version_1_is_recomputed(facade, cfg):
    facade["standing"] = proof_standing(("floor-model",))
    old = {"version": 1, "skills": {"demo": {
        "inputs_sha256": "inputs-1", "skill_version": "1.0.0", "web_measured": True, "evidence_images": [IMAGE],
        "pairs": [{"tier": "strong", "model": "ref-model", "adapter": "ref-adapter", "band": "reliable", "cause": None,
                   "score": 0.9, "mean": 0.97, "runs": 12},
                  {"tier": "floor", "model": "floor-model", "adapter": "floor-adapter", "band": "reliable", "cause": None,
                   "score": 0.9, "mean": 0.97, "runs": 12}]}}}  # same inputs hash: only the version tells it apart
    path = Path(cfg["data_dir"]) / "proof.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(old), encoding="utf-8")
    entry = proof.row(cfg, "demo")
    assert facade["calls"] == 1 and "web_measured" not in entry
    assert [pair["web_measured"] for pair in entry["pairs"]] == [False, True]
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2 == proof.VERSION
