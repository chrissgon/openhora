"""Offline tests of the gate read model by model (P2c): the gate takes the newest full test whose header lists the model,
and its X.Y, its pending cases, its pool, its Y count and its stored gate follow that selection, so that a full test of
one model changes nothing of another's. No model is called: evidence is written here, with the helpers of test_bands.py.

Run: uv run --with pytest pytest evals/tests/test_model_gate.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("bands_helpers_for_model_gate", Path(__file__).with_name("test_bands.py"))
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)
es, skill, versions, event = tb.es, tb.skill, tb.versions, tb.event
CFG = {**tb.CFG, "models": {**tb.CFG["models"], "z-model": []}}
PASS = {"passed": True, "with": 0.9, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05}


@pytest.fixture
def root(tmp_path):
    return tmp_path


def listing(path, models, gate=None, complete_models=None):
    """Rewrite the header of the evidence file at `path` into the list shape: the models, an adapter for each, and, when
    given, the gate keyed by model id and the models the event is complete for (None leaves either out)."""
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    head = lines[0]
    head["models"], head["adapters"] = list(models), {m: "h" for m in models}
    head["adapter_sha256"] = {"h": tb.H["b"]}
    head.pop("gate", None)
    if gate is not None:
        head["gate"] = gate
    if complete_models is not None:
        head["complete_models"] = list(complete_models)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def lines_of(model_runs=3, with_score=0.9, base_score=0.5, baseline=True, cases=(1, 2, 3)):
    found = [(c, "with", with_score, None) for c in cases for _ in range(model_runs)]
    return found + ([(c, "without", base_score, None) for c in cases for _ in range(model_runs)] if baseline else [])


def full_on(folder, model, version, date, gate=PASS, **kw):
    """A full test that lists one model only (the list header), with that model's lines."""
    path = event(folder, "full", version, date, lines_of(**kw), strong=model, gate=gate)
    return listing(path, [model], {model: gate} if gate else None)


def row(root, folder, cfg=CFG):
    return es.skill_band(str(root), str(folder), cfg)


def test_a_full_test_on_another_model_moves_neither_the_x_y_nor_the_gate_of_a_model(root):
    folder = skill(root, version="1.0.0")
    tb.full(folder, version="1.0.0", date="2030-01-01")  # s-model (and f-model in the header), version 1.0
    before = row(root, folder)
    assert (before["gate"]["version"], before["gate"]["passed"]) == ("1.0", True)
    skill(root, version="1.1.0")  # a later change of the skill: 1.1
    full_on(folder, "z-model", "1.1.0", "2030-02-01", with_score=0.6)  # z-model fails its gate at 1.1
    after = row(root, folder)
    # s-model's gate still reads s-model's own newest full test, at 1.0: z-model's test of 1.1 is not among its tests.
    assert after["gate"]["version"] == "1.0" and after["gate"]["test"] == before["gate"]["test"]
    assert (after["gate"]["with"], after["gate"]["baseline"]) == (pytest.approx(0.9), pytest.approx(0.5))
    assert after["last_full_test"] == before["last_full_test"]
    z = after["models"]["z-model"]
    assert z["gate"]["version"] == "1.1" and z["gate"]["test"] != before["gate"]["test"]
    assert z["gate"]["computed"] and z["gate"]["passed"] is False and z["gate"]["with"] == pytest.approx(0.6)
    assert (z["band"], z["kind"]) == ("needs a test", "gate failed")
    assert after["models"]["s-model"]["gate"] == before["gate"]  # the reference model's own row is the skill's own


def test_a_full_test_on_another_model_resets_no_y_count(root):
    folder = skill(root, version="1.0.3")
    versions(folder, ("1.0.0", "new"), ("1.0.1", "y"), ("1.0.2", "y"), ("1.0.3", "y"))
    tb.full(folder, version="1.0.0", date="2030-01-01")  # s-model: 3 Y changes since its newest full test
    first = row(root, folder)
    assert (first["band"], first["kind"]) == ("watch", "y changes") and "3 Y changes" in first["cause"]
    full_on(folder, "z-model", "1.0.3", "2030-02-01")  # z-model: a full test at the newest version
    second = row(root, folder)
    assert (second["band"], second["kind"], second["cause"]) == (first["band"], first["kind"], first["cause"])
    z = second["models"]["z-model"]
    assert (z["band"], z["kind"]) == ("reliable", None)  # no Y change since z-model's own full test
    assert second["models"]["s-model"]["kind"] == "y changes"
    # And the other way: a full test of the reference model resets its count and leaves z-model's alone.
    versions(folder, ("1.0.0", "new"), ("1.0.1", "y"), ("1.0.2", "y"), ("1.0.3", "y"), ("1.0.4", "y"), ("1.0.5", "y"), ("1.0.6", "y"))
    skill(root, version="1.0.6")
    full_on(folder, "s-model", "1.0.6", "2030-03-01")
    third = row(root, folder)
    assert (third["band"], third["kind"]) == ("reliable", None)
    assert third["models"]["z-model"]["kind"] == "y changes" and "3 Y changes" in third["models"]["z-model"]["cause"]


@pytest.mark.parametrize("says", [True, False])
def test_a_full_test_that_lists_a_model_it_ran_only_in_part_moves_nothing_of_that_model(root, says):
    folder = skill(root, version="1.0.3")
    versions(folder, ("1.0.0", "new"), ("1.0.1", "y"), ("1.0.2", "y"), ("1.0.3", "y"))
    tb.full(folder, version="1.0.0", date="2030-01-01")  # s-model: a complete full test, then 3 Y changes
    before = row(root, folder)
    assert (before["band"], before["kind"]) == ("watch", "y changes")
    # A z-led full test at the newest version that lists s-model, of which s-model ran 1 of 3 runs per case.
    part = [(c, "with", 0.9, {"model": "s-model", "adapter": "h"}) for c in (1, 2, 3)]
    path = event(folder, "full", "1.0.3", "2030-02-01", lines_of(model_runs=3) + part, strong="z-model", gate=PASS)
    listing(path, ["z-model", "s-model"], {"z-model": PASS}, ["z-model"] if says else None)  # without the key: the lead's
    after = row(root, folder)
    assert after["gate"] == before["gate"] and after["last_full_test"] == before["last_full_test"]
    assert (after["band"], after["kind"], after["cause"]) == (before["band"], before["kind"], before["cause"])  # Y count: 3
    assert after["models"]["s-model"]["gate"] == before["gate"]
    z = after["models"]["z-model"]
    assert z["gate"]["test"] != before["gate"]["test"] and (z["band"], z["kind"]) == ("reliable", None)
    # Once s-model has run it whole, the test is one of its own: its newest full test, its count of Y changes.
    whole = [(c, "with", 0.9, {"model": "s-model", "adapter": "h"}) for c in (1, 2, 3) for _ in range(3)]
    path = event(folder, "full", "1.0.3", "2030-03-01", lines_of(model_runs=3) + whole, strong="z-model", gate=PASS)
    listing(path, ["z-model", "s-model"], {"z-model": PASS}, ["z-model", "s-model"])
    final = row(root, folder)
    assert final["gate"]["test"] != before["gate"]["test"] and (final["band"], final["kind"]) == ("reliable", None)


def test_an_abandoned_full_test_keeps_the_lines_of_its_lead_model_and_no_other_model_s(root):
    folder = skill(root, version="1.0.0")
    part = [(c, "with", 0.9, {"model": "s-model", "adapter": "h"}) for c in (1, 2, 3)]
    path = event(folder, "full", "1.0.0", "2030-01-01", lines_of() + part, strong="z-model", complete=False)
    listing(path, ["z-model", "s-model"], None, [])
    cfg = CFG
    z = es.gate_of(str(folder), es.as_subject(cfg, "z-model"))
    assert z["test"] is not None and z["version"] == "1.0"  # the lead's lines stay in the gate of the version
    s = es.gate_of(str(folder), es.as_subject(cfg, "s-model"))
    assert s["test"] is None and "no full test" in s["cause"]


def test_the_stored_gate_is_the_one_a_full_test_wrote_for_that_model(root):
    folder = skill(root)
    # No baseline lines in force anywhere: each model's gate stands as its own full test wrote it, "baseline expired".
    floor = [(c, "with", 0.9, {"model": "f-model", "adapter": "fh"}) for c in (1, 2, 3) for _ in range(3)]
    event(folder, "full", "1.0.0", "2030-01-01", lines_of(baseline=False) + floor, gate=PASS)  # the old header and gate: s-model's
    full_on(folder, "z-model", "1.0.0", "2030-01-02", gate={**PASS, "passed": False, "with": 0.6, "baseline": 0.7}, baseline=False)
    for model, passed, mean in (("s-model", True, 0.9), ("z-model", False, 0.6)):
        gate = es.gate_of(str(folder), es.as_subject(CFG, model))
        assert (gate["computed"], gate["passed"], gate["note"]) == (False, passed, "baseline expired"), model
        assert gate["with"] == pytest.approx(mean)
    # A model with no gate of its own (the old event's floor tier): nobody else's stands for it.
    other = es.gate_of(str(folder), es.as_subject(CFG, "f-model"))
    assert other["passed"] is None and other["note"] is None and "no baseline in force on f-model" in other["cause"]


def test_the_old_events_single_gate_is_the_strong_tier_models_and_no_other(root):
    folder = skill(root)
    event(folder, "full", "1.0.0", "2030-01-01", lines_of(baseline=False), gate=PASS)
    latest = es.skill_evidence(str(folder))[0][0]
    assert es.event_gates(latest) == {"s-model": PASS} and es.event_gate(latest, "s-model") == PASS
    assert es.event_gate(latest, "f-model") is None and es.event_gate(latest, None) == PASS
    keyed = {**latest, "models": ["a-model", "b-model"], "adapters": {"a-model": "h", "b-model": "h"},
             "gate": {"a-model": PASS, "b-model": {**PASS, "passed": False}}}
    assert es.event_gates(keyed) == keyed["gate"] and es.event_gate(keyed, "b-model")["passed"] is False


def test_the_tests_that_list_a_model_are_the_ones_its_gate_reads(root):
    folder = skill(root)
    full_on(folder, "z-model", "1.0.0", "2030-01-02")
    tb.full(folder, version="1.0.0", date="2030-01-03")
    events = es.skill_evidence(str(folder))
    assert [e["models"] for e, _ in es.model_events(events, "z-model")] == [["z-model"]]
    assert [e["test"] for e, _ in es.model_events(events, "s-model")] == [events[1][0]["test"]]
    assert es.model_events(events, None) == events and es.model_events(events, "nobody") == []
    assert [e["test"] for e, _ in es.model_events(events, "f-model")] == [events[1][0]["test"]]  # the old header lists its floor tier too


def test_the_gate_command_takes_a_model(root, capsys):
    (root / "evals").mkdir()
    (root / "evals" / "eval-gate.json").write_text(json.dumps({**CFG, "models": {**CFG["models"], "z-model": tb.ENTRY}}))
    folder = skill(root)
    full_on(folder, "z-model", "1.0.0", "2030-01-02")
    assert es.main(["gate", "--skill", "core-demo", "--model", "z-model"], root=str(root)) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    assert es.main(["gate", "--skill", "core-demo"], root=str(root)) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is None  # s-model has no full test here
    with pytest.raises(SystemExit):
        es.main(["status", "--skill", "core-demo", "--model", "z-model"], root=str(root))


# --- the local evidence folder ------------------------------------------------------------------------

def test_the_local_evidence_folder_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "mine"))
    assert es.local_evidence_base() == str(tmp_path / "mine")
    monkeypatch.delenv("WB_LOCAL_EVIDENCE_DIR")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert es.local_evidence_base() == str(tmp_path / "data" / "openhora" / "evidence")
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert es.local_evidence_base() == str(tmp_path / "home" / ".local" / "share" / "openhora" / "evidence")


def test_a_local_folder_inside_the_checkout_is_refused(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "skills" / "demo" / "evals" / "evidence").mkdir(parents=True)
    root = str(checkout)
    assert es.local_base_problem(str(tmp_path / "outside"), root) is None
    assert "must be outside it" in es.local_base_problem(str(checkout / "evidence"), root)  # not made yet: its parent decides
    assert es.local_base_problem(root, root) is not None
    # Not by strings: another spelling of the checkout, a link into it, and a skill folder that is a link into it.
    assert es.local_base_problem(str(checkout / "skills" / ".." / "evidence"), root) is not None
    (tmp_path / "link").symlink_to(checkout / "skills")
    assert es.local_base_problem(str(tmp_path / "link"), root) is not None
    assert es.local_base_problem(str(tmp_path / "link" / "new" / "deeper"), root) is not None
    base = tmp_path / "mine"
    base.mkdir()
    assert es.local_base_problem(str(base), root, "demo") is None
    (base / "demo").symlink_to(checkout / "skills" / "demo" / "evals" / "evidence")
    assert es.local_base_problem(str(base), root) is None  # the base alone is outside
    assert "must be outside it" in es.local_base_problem(str(base), root, "demo")  # its skill folder is a link into the checkout


def test_the_checkout_spelled_in_another_case_is_still_the_checkout(tmp_path):
    checkout = tmp_path / "Checkout"
    checkout.mkdir()
    swapped = tmp_path / "cHECKOUT"
    if not swapped.exists():  # a case-sensitive filesystem has no such alias
        pytest.skip("this filesystem tells Checkout and cHECKOUT apart")
    assert es.local_base_problem(str(swapped / "evidence"), str(checkout)) is not None
    assert es.local_base_problem(str(swapped), str(checkout)) is not None


def test_the_status_shows_local_evidence_in_a_section_of_its_own(root, tmp_path_factory):
    local = tmp_path_factory.mktemp("mine")
    folder = skill(root)
    (root / "evals").mkdir()
    (root / "evals" / "eval-gate.json").write_text(json.dumps({**CFG, "models": {"s-model": [], "f-model": []}}))
    tb.full(folder, version="1.0.0", date="2030-01-01")
    alone = es.all_status(str(root), None, str(local))
    assert "local" not in alone and alone["skills"] == es.all_status(str(root))["skills"]
    # A person's own full test of a model the gate file does not list, in the local folder.
    mine = local / "core-demo"
    mine.mkdir()
    probe = tmp_path_factory.mktemp("probe") / "skills" / "core-demo"
    skill(probe.parents[1], version="1.0.0")
    path = full_on(probe, "own-model", "1.0.0", "2030-02-01")
    (mine / path.name).write_text(path.read_text())
    shown = es.all_status(str(root), None, str(local))
    section = shown["local"]
    assert section["folder"] == str(local) and list(section["skills"]) == ["core-demo"]
    figures = section["skills"]["core-demo"]["own-model"]
    assert figures["tests"] == 1 and figures["gate"]["passed"] is True and figures["gate"]["version"] == "1.0"
    assert figures["runs"] > 0 and set(es.LOCAL_ROW_KEYS) <= set(figures)
    # The repository's figures are what they were: the local test is in no row, no count and no model of theirs.
    assert shown["skills"] == alone["skills"] and "own-model" not in shown["skills"][0]["models"]
    assert shown["counts"] == alone["counts"]
