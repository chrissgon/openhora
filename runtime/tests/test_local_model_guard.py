"""The runtime and a local model (backlog N14): the runtime never runs one, and `auto` never ranks one.

A model on the person's own machine (evals/local_models.py) is for lab tests: it has no price in runtime/prices.json, no evidence in the
repository and no key proxy. The lab facade refuses a run on a `local/` id with one stated sentence, before anything is resolved or
started; and `auto` ranks only models with a price, so a local model whose own evidence is `reliable` is not chosen, and a named
one is refused as a model the gate file does not list. Offline: the facade's functions are stand-ins, as in test_proof_routing.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_local_model_guard.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
proof = st.load("proof")
prices = st.load("prices")

_spec = importlib.util.spec_from_file_location("proof_routing_tests_for_local_model", Path(__file__).with_name("test_proof_routing.py"))
routing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(routing)
facade, cfg = routing.facade, routing.cfg  # the fixtures of the proof tests
figures, standing, table, WEB, ADAPTERS = routing.figures, routing.standing, routing.table, routing.WEB, routing.ADAPTERS

LOCAL = "local/example-coder@047bf46455a5"


@pytest.mark.parametrize("model", [LOCAL, "local/example-coder", "local/anything-at-all"])
def test_the_lab_facade_refuses_a_run_on_a_local_model_before_it_resolves_or_starts_anything(tmp_path, model, monkeypatch):
    def nothing(*args, **kwargs):
        raise AssertionError("the facade went past the guard")
    monkeypatch.setattr(lab, "reference", nothing)
    monkeypatch.setattr(lab, "_platform_names", nothing)
    with pytest.raises(lab.LabError) as e:
        lab.run_skill("demo", "Say hello.", [], str(tmp_path / "dest"), model=model)
    assert e.value.kind == "config" and e.value.reason == "a local model is for lab tests only; the runtime does not run one"
    assert not (tmp_path / "dest").exists()


def test_a_model_that_merely_contains_the_word_is_not_refused_by_the_guard(tmp_path, monkeypatch):
    seen = []

    def reference(model=None):
        seen.append(model)
        raise lab.LabError("config", "stop here")
    monkeypatch.setattr(lab, "reference", reference)
    with pytest.raises(lab.LabError, match="stop here"):
        lab.run_skill("demo", "p", [], str(tmp_path / "dest"), model="vendor/local/model")
    assert seen == ["vendor/local/model"]


def test_auto_never_picks_a_local_model_whose_own_evidence_is_reliable(facade, cfg):
    facade["standing"] = standing({"cheap": figures(score=0.7), "dear": figures(score=0.9)}, local={LOCAL: figures(score=1.0, source="local")})
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert r["model"] == "cheap" and r["mode"] == "auto" and LOCAL not in r["bands"]
    with pytest.raises(ValueError, match="not a model of the gate file"):
        proof.route(cfg, "demo", WEB, model=LOCAL)


def test_even_listed_among_the_models_a_local_model_has_no_price_so_auto_leaves_it_out(facade, cfg, monkeypatch):
    models = [*ADAPTERS, LOCAL]
    facade["standing"] = {**standing({"cheap": figures(score=0.5), "dear": figures(score=0.6), LOCAL: figures(score=1.0, source="local")}),
                          "adapters": {**ADAPTERS, LOCAL: "agents-dir"}, "lab_models": list(ADAPTERS)}
    monkeypatch.setattr(lab, "models", lambda: models)
    monkeypatch.setattr(lab, "reference", lambda model=None: {"model": model or "cheap", "adapter": ADAPTERS.get(model or "cheap", "agents-dir"),
                                                              "route": None})
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert r["model"] == "cheap" and f"{LOCAL} is reliable for this skill but no price is known for it: it is not a candidate" in r["reasons"]
    assert LOCAL not in [c["model"] for c in r["candidates"]]


def test_the_price_table_names_no_local_model():
    assert not [m for m in prices.load()["models"] if m.startswith("local/")]
