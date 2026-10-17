"""Package P11 through the runtime: a pair that is reliable only because a community pool closed (quick tests from two forks, a
baseline in force) is still `community_only` (decision D36). The status script computes the pair from real evidence files written
in a temporary checkout, the facade's standing carries it, and the proof file and the choice of a model rank it, choose it for
`auto`, and hold its output for review: it is never proven, and the autonomy stays `supervised`. Offline: only the facade's
functions that need a container or the machine's image are stood in, as test_proof_routing.py does; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_proof_pooled_community.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import standin_tree as st

REPO = Path(__file__).resolve().parents[2]


def load_by_path(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lab = st.load("lab")
proof = st.load("proof")
routing = load_by_path("proof_routing_tests_for_pooled_community", "runtime/tests/test_proof_routing.py")
community = load_by_path("community_tests_for_pooled_runtime", "evals/tests/test_community_evidence.py")
bands = community.tb
facade, cfg, WEB, USAGE = routing.facade, routing.cfg, routing.WEB, routing.USAGE
IMAGE = "sha256:" + "e" * 64  # the image the community fixtures record


def quick(folder, who, run_id, date):
    repo_id = {"ana": 111, "bo": 222}[who]
    return community.community(folder, model="old-model", adapter="oh", repo_id=repo_id, run_id=run_id, kind="quick", per_case=1,
                                date=date, repository=f"{who}/openhora", run_number=run_id, extra_event={"runs": 1})


@pytest.fixture
def pooled(tmp_path, monkeypatch):
    """A checkout whose only evidence of old-model is a lab baseline and three community quick tests from two forks (the lines count in the order they were made: the first three of
    each case, one fork holding two thirds of them at most): the pool
    closes through community evidence alone. Returns the standing the facade builds from it, read before any stand-in."""
    root = tmp_path / "checkout"
    root.mkdir()
    community.git(root, "init", "-q", "-b", "main")
    folder = bands.skill(root)
    bands.versions(folder, ("1.0.0", "new"))
    bands.event(folder, "partial", "1.0.0", "2029-12-01", [(c, "without", 0.5, {"model": "old-model", "adapter": "oh"})
                                                           for c in (1, 2, 3) for _ in range(3)], strong="old-model")
    community.commit(root, "Owner <owner@mail.example>", "lab evidence")
    for n, who in enumerate(("ana", "bo", "ana"), 1):
        quick(folder, who, n, f"2030-01-0{n}")
    community.commit(root)
    module = lab.LAB.load_status()
    monkeypatch.setattr(lab.LAB, "load_status", lambda: module)
    monkeypatch.setattr(lab.load(), "ROOT", str(root))
    monkeypatch.setattr(module, "load_gate", lambda r: {**bands.CFG, "web_cases": {}})
    monkeypatch.setattr(module, "local_evidence_base", lambda: str(tmp_path / "no-local-evidence"))
    return lab.standing("core-demo")


def test_the_status_script_computes_the_pooled_pair_as_community_only(pooled):
    figures = pooled["community"]["old-model"]
    assert (figures["source"], figures["band"], figures["community_only"]) == ("community", "reliable", True)
    assert pooled["models"].get("old-model") is None  # the lab has no line of the model's with the skill: nothing in its column
    assert figures["images"] == [IMAGE]


def test_the_proof_ranks_the_pooled_pair_and_never_releases_it(pooled, facade, cfg, monkeypatch):
    facade["standing"] = {**pooled, "community": {"old-model": {**pooled["community"]["old-model"], "usage_mean": USAGE}}}
    facade["digest"] = IMAGE
    monkeypatch.setattr(lab, "models", lambda: ["old-model"])
    monkeypatch.setattr(lab, "names_of", lambda model: [model])
    monkeypatch.setattr(lab, "reference", lambda model=None: {"model": "old-model", "adapter": "oh", "route": "invented"})
    facade["table"] = routing.table(**{"old-model": (1.0, 2.0)})
    entry = proof.row(cfg, "core-demo")
    pair, = entry["pairs"]
    assert (pair["model"], pair["band"], pair["source"]) == ("old-model", "reliable", "community")
    auto = proof.route(cfg, "core-demo", WEB, model="auto")
    assert (auto["model"], auto["mode"], auto["source"]) == ("old-model", "auto", "community")  # it counts for ranking
    assert (auto["proven"], auto["autonomy"]) == (False, "supervised")  # and never for release: its output is reviewed
    assert any("reliable only through community evidence" in reason for reason in auto["reasons"])
    named = proof.route(cfg, "core-demo", WEB, model="old-model")
    assert (named["proven"], named["autonomy"]) == (False, "supervised")
