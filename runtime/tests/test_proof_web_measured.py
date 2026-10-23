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


def write_cases(root, cases, top_allow_web=None):
    folder = Path(root) / "skills" / "demo" / "evals"
    folder.mkdir(parents=True, exist_ok=True)
    data = {"skill": "demo", "evals": cases}
    if top_allow_web is not None:
        data["allow_web"] = top_allow_web
    (folder / "evals.json").write_text(json.dumps(data), encoding="utf-8")


WEB_CASES = [{"id": 1, "allow_web": True}, {"id": 2}, {"id": 3, "allow_web": True}]


@pytest.fixture
def status(monkeypatch, tmp_path):
    """The status script's functions lab.standing reads, replaced, and a tree with a case file of the skill; returns
    the knobs a test turns. The pools are what lab_view returns: per model, the current set and the inherited lines.
    Cases 1 and 3 set allow_web, case 2 does not; the gate file lists 1 and 3."""
    module = lab.LAB.load_status()
    monkeypatch.setattr(lab.LAB, "load_status", lambda: module)  # the facade loads the script afresh on every call
    monkeypatch.setattr(lab.load(), "ROOT", str(tmp_path))  # the case file is read from here
    write_cases(tmp_path, WEB_CASES)
    knobs = {"web_cases": {"demo": [1, 3]}, "pools": {}, "views": [], "root": tmp_path}

    monkeypatch.setattr(module, "load_gate", lambda root: {
        "models": {"ref-model": {"aliases": [], "adapter": "ref-adapter", "pass_env": [], "route": None},
                   "floor-model": {"aliases": [], "adapter": "floor-adapter", "pass_env": [], "route": None}},
        "lab_models": ["ref-model", "floor-model"], "measurement_floor": 1, "web_cases": knobs["web_cases"]})
    monkeypatch.setattr(module, "local_evidence_base", lambda: str(tmp_path / "no-local-evidence"))
    monkeypatch.setattr(module, "skill_evidence", lambda skill_dir: [])
    monkeypatch.setattr(module, "all_status", lambda root, only=None, local_base=None: {"skills": [
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


def test_a_web_case_with_evidence_on_one_model_turns_the_web_on_for_that_model_only(status):
    status["pools"] = {"floor-model": {"current": [line(3, "floor-model")], "inherited": []},
                       "ref-model": {"current": [line(2, "ref-model")], "inherited": []}}  # case 2 is not a web case
    assert web(lab.standing("demo")) == {"ref-model": False, "floor-model": True}
    status["pools"] = {"ref-model": {"current": [line("1", "ref-model")], "inherited": []}}  # case ids compare as text
    assert web(lab.standing("demo")) == {"ref-model": True, "floor-model": False}


def test_a_web_case_whose_only_lines_are_inherited_still_turns_the_web_on(status):
    # After a Y change that does not rerun the case, or an execution epoch, the band can stay reliable on inherited
    # lines (they weigh above zero in the score): the flag follows the same lines.
    status["pools"] = {"ref-model": {"current": [line(2, "ref-model")], "inherited": [line(1, "ref-model")]},
                       "floor-model": {"current": [], "inherited": [line(3, "floor-model")]}}
    assert web(lab.standing("demo")) == {"ref-model": True, "floor-model": True}
    status["pools"] = {"ref-model": {"current": [], "inherited": []}, "floor-model": {"current": [line(2, "floor-model")]}}
    assert web(lab.standing("demo")) == {"ref-model": False, "floor-model": False}  # no line of a web case at all


def test_being_listed_is_only_the_permission_the_case_must_set_allow_web(status):
    status["pools"] = {"ref-model": {"current": [line(1, "ref-model")], "inherited": []},
                       "floor-model": {"current": [line(3, "floor-model")], "inherited": []}}
    write_cases(status["root"], [{"id": 1}, {"id": 3, "allow_web": True}])  # case 1 no longer sets it
    assert web(lab.standing("demo")) == {"ref-model": False, "floor-model": True}
    write_cases(status["root"], [{"id": 1}, {"id": 3}], top_allow_web=True)  # the top level applies to every case
    assert web(lab.standing("demo")) == {"ref-model": True, "floor-model": True}
    write_cases(status["root"], [{"id": 1, "allow_web": False}, {"id": 3}], top_allow_web=False)
    assert web(lab.standing("demo")) == {"ref-model": False, "floor-model": False}
    write_cases(status["root"], [{"id": 3, "allow_web": True}])  # the listed case 1 is gone from the file
    assert web(lab.standing("demo")) == {"ref-model": False, "floor-model": True}


def test_the_current_set_is_the_status_scripts_own_for_the_skill_and_its_gate(status):
    lab.standing("demo")
    (skill_dir, cfg, events), = status["views"]
    assert Path(skill_dir).name == "demo" and cfg["lab_models"] == ["ref-model", "floor-model"] and events == []


def test_a_skill_with_no_web_case_in_the_gate_file_is_not_measured_with_the_web(status):
    status["web_cases"] = {}
    status["pools"] = {"ref-model": {"current": [line(1, "ref-model")], "inherited": []}}
    found = lab.standing("demo")
    assert found["web_cases"] == [] and web(found) == {"ref-model": False, "floor-model": False}


def test_the_standing_of_a_real_skill_carries_a_flag_and_a_usage_for_every_model():
    found = lab.standing("biz-market-analysis")
    assert found["models"] and all(isinstance(m["web_measured"], bool) for m in found["models"].values())
    assert all("usage_mean" in m and m["source"] == "lab" for m in found["models"].values())
    assert set(found["adapters"]) == set(found["lab_models"])


def test_the_usage_mean_is_the_mean_of_the_lines_that_carry_a_usage_and_none_when_no_line_does(status):
    one = {"input": 100, "output": 20, "cache_read": 0, "cache_write": 10}
    two = {"input": 300, "output": 40, "cache_read": 10, "cache_write": 10}
    status["pools"] = {"ref-model": {"current": [dict(line(1, "ref-model"), usage=one), dict(line(2, "ref-model"), usage=two)],
                                     "inherited": [line(3, "ref-model")]},  # a line with no usage is left out of the mean
                       "floor-model": {"current": [line(3, "floor-model")], "inherited": []}}
    found = lab.standing("demo")["models"]
    assert found["ref-model"]["usage_mean"] == {"input": 200.0, "output": 30.0, "cache_read": 5.0, "cache_write": 10.0}
    assert found["floor-model"]["usage_mean"] is None


def test_the_standing_carries_the_persons_own_tests_apart_from_the_labs(status, monkeypatch):
    module = lab.LAB.load_status()
    own = {"band": "reliable", "cause": None, "score": 0.8, "mean": 0.9, "runs": 6}
    monkeypatch.setattr(module, "all_status", lambda root, only=None, local_base=None: {
        "skills": [{"version": "1.0.0", "models": {"ref-model": dict(FIGURES)}}],
        "local": {"folder": local_base, "skills": {"demo": {"floor-model": own, "unlisted-model": own}}}})
    monkeypatch.setattr(module, "local_skill_evidence", lambda skill, base=None: [])
    found = lab.standing("demo")
    assert set(found["models"]) == {"ref-model"} and set(found["local"]) == {"floor-model"}  # an unlisted model cannot run: left out
    assert found["local"]["floor-model"]["source"] == "local" and found["local"]["floor-model"]["band"] == "reliable"


def test_the_standing_carries_the_community_evidence_apart_and_marks_a_pair_reliable_only_through_it(status, monkeypatch):
    """P10: the status script's own "community" section is read through the facade, for the listed models only, with the source
    named and the flag community_only kept; the lines come from community_pool, never from the lab's."""
    module = lab.LAB.load_status()
    one = {"input": 100, "output": 20, "cache_read": 0, "cache_write": 0}
    shared = {"band": "reliable", "cause": None, "score": 0.8, "mean": 0.9, "runs": 6}
    monkeypatch.setattr(module, "all_status", lambda root, only=None, local_base=None: {
        "skills": [{"version": "1.0.0", "models": {"ref-model": dict(FIGURES)}}],
        "community": {"skills": {"demo": {"floor-model": dict(shared, community_only=True),
                                          "ref-model": dict(shared, community_only=False),
                                          "unlisted-model": dict(shared, community_only=True)}}}})
    monkeypatch.setattr(module, "evidence_authors", lambda root: {})
    monkeypatch.setattr(module, "community_pool", lambda root, skill_dir, authors: ({"floor-model": [({"test": "t"}, [])]}, {}))
    status["pools"] = {"floor-model": {"current": [dict(line(1, "floor-model"), usage=one)], "inherited": []}}
    found = lab.standing("demo")
    assert set(found["community"]) == {"floor-model", "ref-model"}, "an unlisted model cannot run: left out"
    floor = found["community"]["floor-model"]
    assert floor["source"] == "community" and floor["community_only"] is True and floor["band"] == "reliable"
    assert floor["usage_mean"] == {"input": 100.0, "output": 20.0, "cache_read": 0.0, "cache_write": 0.0}
    assert floor["web_measured"] is True, "a web case line of the community pool counts for its own column"
    assert found["community"]["ref-model"]["community_only"] is False
    assert found["models"]["ref-model"]["source"] == "lab" and "floor-model" not in found["models"], "never added to a lab figure"


def test_a_standing_without_community_evidence_has_an_empty_community_column(status):
    assert lab.standing("demo")["community"] == {}


def test_the_standing_keeps_the_evidence_images_for_each_model_and_source_the_local_events_included(status, monkeypatch):
    """Review of P3: the image a pair is released in is checked against the images of the events its own figures rest on."""
    module = lab.LAB.load_status()
    lab_image, local_image = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    other_image, below_floor = "sha256:" + "3" * 64, "sha256:" + "4" * 64

    def event(models, digest, version=5):
        return ({"measurement_version": version, "image_digest": digest, "models": models, "adapters": {m: "a" for m in models}}, [])

    monkeypatch.setattr(module, "skill_evidence", lambda skill_dir: [event(["ref-model"], lab_image), event(["ref-model", "floor-model"], other_image),
                                                                    event(["floor-model"], below_floor, version=0)])
    monkeypatch.setattr(module, "local_skill_evidence", lambda skill, base=None: [event(["floor-model"], local_image)])
    own = {"band": "reliable", "cause": None, "score": 0.8, "mean": 0.9, "runs": 6}
    monkeypatch.setattr(module, "all_status", lambda root, only=None, local_base=None: {
        "skills": [{"version": "1.0.0", "models": {"ref-model": dict(FIGURES), "floor-model": dict(FIGURES)}}],
        "local": {"folder": local_base, "skills": {"demo": {"floor-model": own}}}})
    found = lab.standing("demo")
    assert found["models"]["ref-model"]["images"] == sorted([lab_image, other_image])
    assert found["models"]["floor-model"]["images"] == [other_image], "an event below the measurement floor names no image, and another model's event is not this one's"
    assert found["local"]["floor-model"]["images"] == [local_image], "the person's own events are their own source"
    assert found["evidence_images"] == sorted([lab_image, other_image])


def proof_standing(web_models):
    models = {name: dict(FIGURES, web_measured=name in web_models, usage_mean=None, source="lab") for name in ("ref-model", "floor-model")}
    return {"skill": "demo", "version": "1.0.0", "lab_models": ["ref-model", "floor-model"],
            "adapters": {"ref-model": "ref-adapter", "floor-model": "floor-adapter"}, "models": models, "local": {},
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
    monkeypatch.setattr(lab, "models", lambda: ["ref-model", "floor-model"])
    monkeypatch.setattr(lab, "names_of", lambda model: [model])
    monkeypatch.setattr(lab, "reference", lambda model=None: {"model": model, "route": None})
    return knobs


@pytest.fixture
def cfg(tmp_path):
    return {"data_dir": str(tmp_path / "data")}


def test_a_listed_case_with_no_evidence_runs_the_skill_without_the_web_on_either_model(facade, cfg):
    for model in ("ref-model", "floor-model"):
        r = proof.route(cfg, "demo", WEB, model=model)
        assert r["web"] is False and REASON in r["reasons"]


def test_the_web_follows_the_model_the_run_goes_to(facade, cfg):
    facade["standing"] = proof_standing(("floor-model",))
    floor = proof.route(cfg, "demo", WEB, model="floor-model")
    assert (floor["model"], floor["web"]) == ("floor-model", True) and REASON not in floor["reasons"]
    other = proof.route(cfg, "demo", WEB, model="ref-model")  # the other model, unmeasured with the web
    assert (other["model"], other["web"]) == ("ref-model", False) and REASON in other["reasons"]
    facade["standing"], facade["inputs"] = proof_standing(("ref-model",)), "inputs-2"
    assert proof.route(cfg, "demo", WEB, model="floor-model")["web"] is False  # measured on the other model only
    assert proof.route(cfg, "demo", WEB, model="ref-model")["web"] is True
    assert proof.route(cfg, "demo", {"web": False}, model="ref-model")["web"] is False  # a skill that does not require it


def test_the_flag_is_stored_on_each_pair_and_not_on_the_entry(facade, cfg):
    facade["standing"] = proof_standing(("floor-model",))
    entry = proof.row(cfg, "demo")
    assert "web_measured" not in entry
    assert {pair["model"]: pair["web_measured"] for pair in entry["pairs"]} == {"ref-model": False, "floor-model": True}


def test_a_model_with_no_standing_is_not_measured_with_the_web(facade, cfg):
    facade["standing"] = proof_standing(())
    del facade["standing"]["models"]["floor-model"]
    assert [pair["web_measured"] for pair in proof.row(cfg, "demo")["pairs"]] == [False, False]


def test_a_proof_file_of_an_earlier_version_is_recomputed(facade, cfg):
    facade["standing"] = proof_standing(("floor-model",))
    old = {"version": 2, "skills": {"demo": {
        "inputs_sha256": "inputs-1", "skill_version": "1.0.0", "evidence_images": [IMAGE],
        "pairs": [{"tier": "strong", "model": "ref-model", "adapter": "ref-adapter", "band": "reliable", "cause": None,
                   "score": 0.9, "mean": 0.97, "runs": 12, "web_measured": True},
                  {"tier": "floor", "model": "floor-model", "adapter": "floor-adapter", "band": "reliable", "cause": None,
                   "score": 0.9, "mean": 0.97, "runs": 12, "web_measured": False}]}}}  # same inputs hash: only the version tells it apart
    path = Path(cfg["data_dir"]) / "proof.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(old), encoding="utf-8")
    entry = proof.row(cfg, "demo")
    assert facade["calls"] == 1 and "web_measured" not in entry
    assert [pair["web_measured"] for pair in entry["pairs"]] == [False, True]
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 5 == proof.VERSION
