"""Tests of runtime/proof.py: the proof file (one pair for each model), its two checks, and the choice of the model a run goes
to (a model the person names, or `auto`); and of the operation and the shell command that show it. Offline: the facade's
functions (lab.standing, lab.proof_inputs, lab.image, lab.measurement_problem, lab.models and the rest of the model table)
are replaced by stand-ins and the price table is a table of invented prices; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_proof_routing.py
"""
from __future__ import annotations

import ast
import datetime
import json
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
proof = st.load("proof")
prices = st.load("prices")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")
costs = st.load("costs")

IMAGE = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
WEB = {"web": True}
NO_WEB = {"web": False}
USAGE = {"input": 1000.0, "output": 200.0, "cache_read": 0.0, "cache_write": 0.0}
ADAPTERS = {"cheap": "cheap-adapter", "dear": "dear-adapter", "free": "free-adapter"}


def figures(band="reliable", score=0.8, source="lab", usage=USAGE, web=True):
    return {"band": band, "cause": None if band == "reliable" else "a cause", "score": score, "mean": 0.9, "runs": 12,
            "web_measured": web, "usage_mean": usage, "source": source}


def standing(models=None, web_cases=(1,), images=(IMAGE,), local=None):
    """The standing of a skill: "dear" and "cheap" have evidence, "free" has none."""
    found = models if models is not None else {"cheap": figures(), "dear": figures(score=0.9)}
    return {"skill": "demo", "version": "1.0.0", "lab_models": list(ADAPTERS), "adapters": dict(ADAPTERS), "models": found,
            "local": local or {}, "web_cases": list(web_cases), "evidence_images": list(images)}


def table(**by_model):
    """A price table of invented prices: cheap costs 1/10 of dear."""
    base = {"cache_read_usd_per_mtok": 0.1, "cache_write_usd_per_mtok": 1.0, "source": "https://prices.example/models", "accessed": "2026-10-01"}
    given = {"cheap": (1.0, 2.0), "dear": (10.0, 20.0), **by_model}
    return {"models": {m: {**base, "input_usd_per_mtok": p[0], "output_usd_per_mtok": p[1]} for m, p in given.items() if p is not None}}


@pytest.fixture
def facade(monkeypatch):
    """The facade's functions and the price table, replaced. Returns the knobs a test turns and the count of standing calls."""
    knobs = {"standing": standing(), "inputs": "inputs-1", "measurement": None, "digest": IMAGE, "calls": 0,
             "source": "local", "published": [], "setup": None, "table": table()}

    def fake_standing(skill):
        knobs["calls"] += 1
        return knobs["standing"]

    monkeypatch.setattr(lab, "standing", fake_standing)
    monkeypatch.setattr(lab, "proof_inputs", lambda skill: knobs["inputs"])
    monkeypatch.setattr(lab, "measurement_problem", lambda: knobs["measurement"])
    monkeypatch.setattr(lab, "image", lambda: {"name": "img", "digest": knobs["digest"], "platform": "linux/arm64",
                                               "source": knobs["source"], "setup": knobs["setup"]})
    monkeypatch.setattr(lab, "published_digests", lambda: list(knobs["published"]))
    monkeypatch.setattr(lab, "models", lambda: list(ADAPTERS))
    monkeypatch.setattr(lab, "names_of", lambda model: [model])
    monkeypatch.setattr(lab, "reference", lambda model=None: {"model": model or "cheap", "adapter": ADAPTERS.get(model or "cheap"),
                                                              "route": "invented" if model != "free" else "other"})
    monkeypatch.setattr(prices, "load", lambda path=None: knobs["table"])
    return knobs


@pytest.fixture
def cfg(tmp_path):
    return {"data_dir": str(tmp_path / "data"), "default_model": None}


# --- a model the person names -------------------------------------------------------------------------------------------


def test_a_named_model_runs_there_and_its_band_informs_the_person_without_gating_the_choice(facade, cfg):
    r = proof.route(cfg, "demo", WEB, model="dear", named_by="request")
    assert (r["model"], r["adapter"], r["mode"], r["proven"], r["autonomy"], r["named_by"]) == ("dear", "dear-adapter", "named", True, "proven", "request")
    assert r["checks"] == {"measurement": None, "image": None} and r["bands"] == {"cheap": "reliable", "dear": "reliable", "free": "needs a test"}
    unproven = proof.route(cfg, "demo", WEB, model="free", named_by="request")  # no evidence: it runs all the same, supervised
    assert (unproven["model"], unproven["mode"], unproven["proven"], unproven["autonomy"]) == ("free", "named", False, "supervised")
    assert "the band on free is needs a test: it is unproven and runs supervised" in unproven["reasons"]


def test_a_model_the_gate_file_does_not_list_is_refused(facade, cfg):
    with pytest.raises(ValueError):
        proof.route(cfg, "demo", WEB, model="invented-model")


def test_a_named_model_whose_key_is_missing_is_marked_so(facade, cfg):
    r = proof.route(cfg, "demo", WEB, model="dear", key_found=lambda model: model != "dear")
    assert r["key_missing"] is True and "no key was found for dear" in r["reasons"]
    assert proof.route(cfg, "demo", WEB, model="dear", key_found=lambda model: True)["key_missing"] is False


def test_a_pair_is_proven_by_the_persons_own_tests_too_and_not_by_community_evidence(facade, cfg):
    facade["standing"] = standing({"cheap": figures(), "dear": figures(source="local"), "free": figures(source="community")})
    assert proof.route(cfg, "demo", WEB, model="dear")["proven"] is True
    assert proof.route(cfg, "demo", WEB, model="free")["proven"] is False  # reliable only through community evidence: reviewed


def test_when_the_measurement_files_differ_nothing_is_proven(facade, cfg):
    facade["measurement"] = "the measurement fingerprint of this checkout differs"
    r = proof.route(cfg, "demo", WEB, model="dear")
    assert (r["model"], r["proven"], r["autonomy"]) == ("dear", False, "supervised")
    assert r["checks"]["measurement"] in r["reasons"]


@pytest.mark.parametrize("digest, reason", [
    (None, "the eval image is not on this machine"),
    (OTHER, "the image on this machine is not the one the evidence was measured in (evidence measured in a locally "
            "built image holds on the machine that built it only; the published image is the one every machine can have)"),
])
def test_when_the_image_is_not_the_evidences_nothing_is_proven(facade, cfg, digest, reason):
    facade["digest"] = digest
    r = proof.route(cfg, "demo", WEB, model="dear")
    assert (r["proven"], r["autonomy"], r["checks"]["image"]) == (False, "supervised", reason)
    assert reason in r["reasons"]


def test_a_skill_measured_without_the_web_runs_without_it_on_that_model(facade, cfg):
    facade["standing"] = standing({"cheap": figures(web=False), "dear": figures(web=True)})
    r = proof.route(cfg, "demo", WEB, model="cheap")
    assert r["web"] is False
    assert "the skill requires the web and was measured without it: it runs without it" in r["reasons"]
    assert proof.route(cfg, "demo", WEB, model="dear")["web"] is True  # the measurement is a pair's own
    assert proof.route(cfg, "demo", NO_WEB, model="dear")["web"] is False


# --- auto -----------------------------------------------------------------------------------------------------------------


def test_auto_picks_the_cheaper_of_the_reliable_pairs(facade, cfg):
    r = proof.route(cfg, "demo", WEB, model="auto", key_found=lambda model: True)
    assert (r["model"], r["adapter"], r["mode"], r["proven"], r["autonomy"]) == ("cheap", "cheap-adapter", "auto", True, "proven")
    assert [c["model"] for c in r["candidates"]] == ["cheap", "dear"] and r["candidates"][0]["expected_cost"] < r["candidates"][1]["expected_cost"]
    assert r["expected_cost"] == pytest.approx((1000 * 1.0 + 200 * 2.0) / 1e6)  # the mean usage times the price of each kind
    assert proof.route(cfg, "demo", WEB, model=None, default="auto")["model"] == "cheap"  # no model, a default of auto: the same


def test_a_tie_goes_to_the_higher_pessimistic_score(facade, cfg):
    facade["table"] = table(dear=(1.0, 2.0))  # as cheap as the other
    facade["standing"] = standing({"cheap": figures(score=0.7), "dear": figures(score=0.9)})
    assert proof.route(cfg, "demo", WEB, model="auto")["model"] == "dear"
    facade["standing"], facade["inputs"] = standing({"cheap": figures(score=0.95), "dear": figures(score=0.9)}), "inputs-2"
    assert proof.route(cfg, "demo", WEB, model="auto")["model"] == "cheap"


def test_a_pair_that_is_not_reliable_is_not_a_candidate_however_cheap(facade, cfg):
    facade["standing"] = standing({"cheap": figures(band="watch"), "dear": figures()})
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert (r["model"], r["mode"]) == ("dear", "auto") and [c["model"] for c in r["candidates"]] == ["dear"]


def test_a_reliable_pair_without_a_key_a_price_or_a_measured_usage_is_left_out_with_the_reason(facade, cfg):
    facade["table"] = table(cheap=None)  # no price for the cheaper one
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert r["model"] == "dear" and "cheap is reliable for this skill but no price is known for it: it is not a candidate" in r["reasons"]
    facade["table"], facade["inputs"] = table(), "inputs-2"
    facade["standing"] = standing({"cheap": figures(usage=None), "dear": figures()})
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert r["model"] == "dear"
    assert "cheap is reliable for this skill but its runs measured no usage, so there is no expected cost: it is not a candidate" in r["reasons"]
    facade["standing"], facade["inputs"] = standing(), "inputs-3"
    r = proof.route(cfg, "demo", WEB, model="auto", key_found=lambda model: model == "dear")
    assert r["model"] == "dear" and "cheap is reliable for this skill but no key was found for it: it is not a candidate" in r["reasons"]


def test_a_price_that_lacks_a_kind_the_runs_used_leaves_the_pair_out(facade, cfg):
    facade["table"] = table()
    del facade["table"]["models"]["cheap"]["cache_read_usd_per_mtok"]
    facade["standing"] = standing({"cheap": figures(usage={**USAGE, "cache_read": 500.0}), "dear": figures()})
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert r["model"] == "dear" and "its price lacks a kind its runs used" in " ".join(r["reasons"])


def test_when_none_qualifies_auto_falls_back_to_the_project_default_supervised_with_the_reason(facade, cfg):
    facade["standing"] = standing({"cheap": figures(band="needs a test"), "dear": figures(band="watch")})
    r = proof.route({**cfg, "default_model": "dear"}, "demo", WEB, model="auto", default="dear")
    assert (r["model"], r["mode"], r["proven"], r["autonomy"]) == ("dear", "fallback", False, "supervised")
    assert any("no model qualifies for auto" in reason and "dear runs, supervised" in reason for reason in r["reasons"])
    # no default model of the project: the first lab model
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert (r["model"], r["mode"], r["autonomy"]) == ("cheap", "fallback", "supervised")


def test_when_the_proof_does_not_hold_here_auto_has_no_candidate_and_falls_back(facade, cfg):
    facade["digest"] = OTHER
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert (r["mode"], r["proven"], r["autonomy"]) == ("fallback", False, "supervised")


def test_a_pair_reliable_only_through_community_evidence_is_chosen_and_held_for_review(facade, cfg):
    facade["standing"] = standing({"cheap": figures(source="community"), "dear": figures(source="lab")})
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert (r["model"], r["mode"], r["source"]) == ("cheap", "auto", "community")  # it counts for ranking
    assert (r["proven"], r["autonomy"]) == (False, "supervised")  # and never for release
    assert any("reliable only through community evidence" in reason for reason in r["reasons"])


def test_the_community_column_ranks_a_pair_the_lab_has_not_proven_and_never_releases_it(facade, cfg):
    """P10 through the proof file: the lab's reliable figures win, then the person's own, then the community's; a pair that
    rests on the community column alone is reliable, ranked, chosen by auto, and its output is held for review."""
    community = figures(source="community", score=0.95) | {"community_only": True}
    facade["standing"] = standing({"cheap": figures(band="needs a test"), "dear": figures(score=0.9)}, local=None)
    facade["standing"]["community"] = {"cheap": community, "dear": figures(source="community")}
    entry = proof.row(cfg, "demo")
    by_model = {p["model"]: p for p in entry["pairs"]}
    assert (by_model["cheap"]["band"], by_model["cheap"]["source"]) == ("reliable", "community"), "the community column fills a pair the lab leaves unproven"
    assert by_model["dear"]["source"] == "lab", "the lab's reliable figures win over the community's"
    route = proof.route(cfg, "demo", WEB)
    assert (route["model"], route["mode"], route["source"], route["proven"], route["autonomy"]) == ("cheap", "auto", "community", False, "supervised")
    assert any("reliable only through community evidence" in r for r in route["reasons"])
    named = proof.route(cfg, "demo", WEB, model="cheap")
    assert (named["proven"], named["autonomy"]) == (False, "supervised"), "named by the person, the pair is still not released"


def test_evidence_from_the_persons_own_tests_ranks_and_releases(facade, cfg):
    facade["standing"] = standing({"cheap": figures(band="needs a test"), "dear": figures()},
                                  local={"cheap": figures(source="local")})
    entry = proof.row(cfg, "demo")
    assert {p["model"]: (p["band"], p["source"]) for p in entry["pairs"]}["cheap"] == ("reliable", "local")
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert (r["model"], r["proven"], r["source"]) == ("cheap", True, "local")


def test_auto_stays_inside_the_approved_providers_of_a_routine_and_lists_what_it_left_out(facade, cfg):
    r = proof.route(cfg, "demo", WEB, model="auto", approved={"other"})  # only the "free" model's provider: it has no evidence
    assert r["mode"] == "fallback" and r["outside_provider"] == ["cheap", "dear"]
    r = proof.route(cfg, "demo", WEB, model="auto", approved={"invented"})
    assert r["model"] == "cheap" and r["outside_provider"] == []


# --- the proof file -------------------------------------------------------------------------------------------------------


def test_the_proof_file_is_rebuilt_when_the_evidence_or_the_gate_file_changed(facade, cfg):
    first = proof.row(cfg, "demo")
    assert proof.row(cfg, "demo") == first and facade["calls"] == 1
    saved = json.loads((Path(cfg["data_dir"]) / "proof.json").read_text(encoding="utf-8"))
    assert saved["version"] == 3 and saved["skills"]["demo"]["inputs_sha256"] == "inputs-1"
    assert [p["model"] for p in first["pairs"]] == ["cheap", "dear", "free"]  # one pair for each model the gate file lists
    assert first["pairs"][2]["band"] == "needs a test" and first["pairs"][2]["runs"] == 0 and first["pairs"][2]["source"] is None
    assert first["pairs"][0]["usage_mean"] == USAGE and first["pairs"][0]["names"] == ["cheap"]
    facade["inputs"] = "inputs-2"
    proof.row(cfg, "demo")
    assert facade["calls"] == 2
    # The two checks are never cached: they run on every route.
    facade["digest"] = OTHER
    assert proof.route(cfg, "demo", WEB, model="auto")["mode"] == "fallback" and facade["calls"] == 2


def test_a_proof_file_of_the_earlier_form_is_read_as_empty(facade, cfg):
    path = Path(cfg["data_dir"]) / "proof.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 2, "skills": {"demo": {"inputs_sha256": "inputs-1", "pairs": [{"tier": "strong"}]}}}), encoding="utf-8")
    assert [p["model"] for p in proof.row(cfg, "demo")["pairs"]] == ["cheap", "dear", "free"] and facade["calls"] == 1


def test_a_pair_is_shown_with_the_price_its_date_and_the_expected_cost(facade, cfg):
    entry = proof.row(cfg, "demo")
    shown = proof.pair_view(entry["pairs"][0], facade["table"], today="2026-10-15", max_days=90)
    assert shown["price"]["input"] == 1.0 and shown["price"]["accessed"] == "2026-10-01" and shown["price"]["stale"] is False
    assert shown["expected_cost"] == pytest.approx((1000 * 1.0 + 200 * 2.0) / 1e6)
    old = proof.pair_view(entry["pairs"][0], facade["table"], today="2026-10-15", max_days=7)
    assert old["price"]["stale"] is True and old["price"]["age_days"] == 14
    none = proof.pair_view(entry["pairs"][2], facade["table"], today="2026-10-15")  # a model with no usage: no expected cost
    assert none["expected_cost"] is None and none["price"] is None


def test_the_auto_estimate_a_runs_cost_and_the_proof_page_read_one_price_table(facade, cfg):
    """One table (D36): the number auto ranks by, the cost a run is recomputed to and the figure the proof page shows are
    the same arithmetic on the same entry; when the table changes, all three change, and a stale price is stale in each."""
    entry = proof.row(cfg, "demo")
    pair = entry["pairs"][0]  # "cheap": 1000 input and 200 output tokens a run, at 1.0 and 2.0 dollars per million
    expected = (1000 * 1.0 + 200 * 2.0) / 1e6
    route = proof.route(cfg, "demo", WEB)
    assert route["mode"] == "auto" and route["model"] == "cheap"
    assert route["expected_cost"] == pytest.approx(expected)
    assert costs.recompute(USAGE, prices.price_of(facade["table"], ["cheap"])) == pytest.approx(expected)
    assert proof.pair_view(pair, facade["table"], today="2026-10-15", max_days=90)["expected_cost"] == pytest.approx(expected)
    # The price changes in the one table: the three follow it, and no copy of the old price is left anywhere.
    facade["table"] = table(cheap=(3.0, 4.0))
    dearer = (1000 * 3.0 + 200 * 4.0) / 1e6
    assert proof.route(cfg, "demo", WEB)["expected_cost"] == pytest.approx(dearer)
    assert costs.recompute(USAGE, prices.price_of(facade["table"], ["cheap"])) == pytest.approx(dearer)
    assert proof.pair_view(pair, facade["table"], today="2026-10-15")["expected_cost"] == pytest.approx(dearer)
    # A price older than the project's limit is shown as stale on the page and in the costs.
    assert proof.pair_view(pair, facade["table"], today="2026-10-15", max_days=7)["price"]["stale"] is True
    run = {"started_at": "2026-10-14T10:00:00.000000Z", "model": "cheap", "adapter": "cheap-adapter", "cost_usd": None,
           "tokens": 1200, "run_dir": None, "agent": "business"}
    rows = costs.summary([run], facade["table"], today=datetime.date(2026, 10, 15), max_days=7)
    assert [r["price"]["stale"] for r in rows] == [True]


def test_the_run_row_and_the_pending_decision_carry_the_routing(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    path = str(built["project"])
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    out = ops.run_next(path)
    assert (out["routing"]["model"], out["routing"]["adapter"], out["routing"]["mode"]) == ("m", "h", "auto")
    assert (out["routing"]["autonomy"], out["routing"]["billing"]) == ("proven", "subscription")
    ctx = ops_core.context(path)
    row = ctx["store"].task_runs_list(ctx["conn"], out["ran"])[0]
    assert (row["model"], row["adapter"], row["web"], row["autonomy"]) == ("m", "h", 0, "proven")
    assert ops.pending(path, out["pending_id"])["payload"]["routing"] == out["routing"]
    shown = ops.proof(path, "demo-asks")["skills"]["demo-asks"]
    assert (shown["model"], shown["proven"], shown["checks"]) == ("m", True, {"measurement": None, "image": None})
    assert shown["recommended"] == "m" and [p["model"] for p in shown["pairs"]] == ["m", "fm"]
    assert shown["pairs"][0]["price"]["source"] == "https://prices.example/models"


def test_no_operation_of_ops_has_the_name_of_a_module_it_imports():
    tree = ast.parse((Path(ops.__file__)).read_text(encoding="utf-8"))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.asname or alias.name for alias in node.names)  # the name the module is bound to
    operations = {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")}
    assert "proof" in operations and not operations & imported, operations & imported


# --- the published image (P2d): identity is the repo digest, and local evidence is local-only (D21) --------------------

def test_a_published_image_that_is_not_pulled_names_the_command(facade, cfg):
    facade["digest"], facade["source"], facade["setup"] = None, "published", "python3 scripts/image_lock.py pull"
    found = proof.checks(proof.row(cfg, "demo"))
    assert found["image"] == "the published eval image is not on this machine: run python3 scripts/image_lock.py pull"


def test_the_image_holds_when_the_published_digest_here_is_the_one_the_evidence_recorded(facade, cfg):
    facade["digest"], facade["source"], facade["published"] = IMAGE, "published", [IMAGE]
    assert proof.checks(proof.row(cfg, "demo"))["image"] is None
    r = proof.route(cfg, "demo", WEB, model="auto")
    assert (r["model"], r["proven"], r["checks"]["image"]) == ("cheap", True, None)


def test_evidence_measured_in_a_published_image_is_not_called_local_when_the_machine_has_another(facade, cfg):
    """The machine has a local build; the evidence names a published image: the plain reason, no local-only note."""
    facade["digest"], facade["source"], facade["published"] = OTHER, "local", [IMAGE]
    assert proof.checks(proof.row(cfg, "demo"))["image"] == "the image on this machine is not the one the evidence was measured in"


def test_evidence_measured_in_a_local_image_holds_on_that_machine_and_says_so_elsewhere(facade, cfg):
    facade["digest"], facade["source"] = IMAGE, "local"
    assert proof.checks(proof.row(cfg, "demo"))["image"] is None  # the machine that built it
    facade["digest"] = OTHER  # another machine, or a rebuild
    reason = proof.checks(proof.row(cfg, "demo"))["image"]
    assert reason.startswith("the image on this machine is not the one the evidence was measured in")
    assert "locally built image holds on the machine that built it only" in reason
