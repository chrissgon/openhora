"""Offline tests of the held-out set that is not the gate's split (evals/interpreter_status.py, `partition_events`, `heldout_report`): an event of split test whose corpus_sha256
is the hash of another summary than test-split.json is reported apart and never feeds a band, a cause or the go computation. The checkouts are small folders written from the
test's own literal data (interpreter_fixtures.py); the blind set is a fictional dozen of ids and a made-up summary file. No model is called."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import interpreter_fixtures as fx

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ist = load("interpreter_status_heldout_test", "evals/interpreter_status.py")
T1, T2, T3, T4 = fx.TEST_IDS[:4]
BLIND_N = 12
BLIND_SPLIT = "fictional-blind-split.json"


def cells(plan=None):
    out = {("pt-BR", 60000 + n): "correct" for n in range(1, BLIND_N + 1)}
    out.update(plan or {})
    return out


def write_blind_split(root, name=BLIND_SPLIT):
    body = json.dumps({"v": 1, "file": "fictional-blind.jsonl", "sha256": "1" * 64, "items": BLIND_N, "counts": {"lang": {"pt-BR": BLIND_N}}}, indent=1, sort_keys=True) + "\n"
    path = Path(root) / "evals/interpreter" / name
    path.write_text(body, encoding="utf-8")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def gate_checkout(root):
    """A checkout whose gate split has one complete event of each route (the cheap one reliable) and one of the current pipeline."""
    hs = fx.checkout(root)
    fx.write_file(root, fx.event(T1, hs), fx.lines_of(T1, fx.corpus(100), cost=0.001))
    fx.write_file(root, fx.event(T2, hs, route="fx-ref", model="example/strong-1"), fx.lines_of(T2, fx.corpus(100), cost=0.009))
    fx.write_file(root, fx.current_event(T3, hs), fx.lines_of(T3, fx.corpus(100, {("en", n): "missed" for n in range(1, 11)}), cost=None))
    return hs


def blind_events(root, hs, plan=None, arm="bprime", test=T4, route="fx-cheap", model="example/cheap-1"):
    """A (disastrous by default) event of the blind set: every item but the first wrong_effect_unconfirmed, its corpus_sha256 the hash of its own summary."""
    corpus = write_blind_split(root)
    bad = {("pt-BR", 60000 + n): "wrong_effect_unconfirmed" for n in range(2, BLIND_N + 1)} if plan is None else plan
    make = fx.current_event if arm == "current" else fx.event
    extra = {} if arm == "current" else {"route": route, "model": model}
    fx.write_file(root, make(test, hs, corpus_sha256=corpus, items=BLIND_N, **extra), fx.lines_of(test, cells(bad), cost=None if arm == "current" else 0.001))
    return corpus


def snapshot(root):
    result = ist.status(str(root))
    return {"rows": result["rows"], "go": result["go"], "accounts": result["accounts"]}


def test_a_held_out_event_of_another_set_changes_no_band_and_not_go(tmp_path):
    hs = gate_checkout(tmp_path)
    before = snapshot(tmp_path)
    assert {r["band"] for r in before["rows"] if r["route"] == "fx-cheap"} == {"reliable"}, "the control: the gate's own events make the cheap route reliable"
    for route, model in (("fx-cheap", "example/cheap-1"), ("fx-ref", "example/strong-1")):
        blind_events(tmp_path, hs, route=route, model=model, test=T4 if route == "fx-cheap" else fx.TEST_IDS[4])
    blind_events(tmp_path, hs, arm="current", test=fx.TEST_IDS[5])
    assert snapshot(tmp_path) == before


def test_the_held_out_event_is_reported_apart_with_its_counts_and_named_by_its_summary(tmp_path):
    hs = gate_checkout(tmp_path)
    corpus = blind_events(tmp_path, hs)
    held = ist.status(str(tmp_path))["heldout"]
    assert len(held) == 1
    (entry,) = held
    assert entry["test"] == T4 and entry["route"] == "fx-cheap" and entry["arm"] == "bprime" and entry["set"] == BLIND_SPLIT and entry["corpus_sha256"] == corpus
    assert entry["items"] == BLIND_N and entry["runs"] == 2 and entry["measures"]["counts"] == {"correct": 1, "wrong_effect_unconfirmed": BLIND_N - 1}
    assert set(entry["by_language"]) == {"pt-BR"} and entry["by_language"]["pt-BR"]["n"] == BLIND_N
    assert "not the gate" in entry["note"]
    text = "\n".join(ist.table(ist.status(str(tmp_path))))
    assert f"held-out set {BLIND_SPLIT} | fx-cheap | bprime | 12 items, 2 runs" in text and "wrong_effect_unconfirmed 11" in text


def test_a_set_whose_summary_is_not_committed_is_not_reported_apart_and_still_feeds_nothing(tmp_path):
    hs = gate_checkout(tmp_path)
    before = snapshot(tmp_path)
    blind_events(tmp_path, hs)
    (tmp_path / "evals/interpreter" / BLIND_SPLIT).unlink()
    result = ist.status(str(tmp_path))
    assert result["heldout"] == [] and snapshot(tmp_path) == before, "an unknown corpus hash is read as the gate's own: the hash filter keeps it out of every set"


def test_an_edited_gate_split_file_keeps_its_old_events_with_the_gate(tmp_path):
    gate_checkout(tmp_path)
    path = tmp_path / "evals/interpreter/test-split.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = ist.status(str(tmp_path))
    assert result["heldout"] == [] and {r["cause"] for r in result["rows"] if r["route"] == "fx-cheap"} == {"changed since the newest test run: corpus_sha256"}


def test_the_gates_own_events_and_dev_events_are_never_reported_as_held_out(tmp_path):
    hs = gate_checkout(tmp_path)
    fx.write_file(tmp_path, fx.event(T4, hs, split="dev", items=BLIND_N, corpus_sha256=fx.H["a"]), fx.lines_of(T4, cells(), split="dev"))
    assert ist.status(str(tmp_path))["heldout"] == []


def test_a_held_out_event_does_not_rewrite_the_cause_of_a_route_with_no_gate_run(tmp_path):
    hs = fx.checkout(tmp_path)
    blind_events(tmp_path, hs)
    result = ist.status(str(tmp_path))
    assert {r["cause"] for r in result["rows"] if r["route"] == "fx-cheap"} == {"no test run of this route"}
    assert len(result["heldout"]) == 1


def test_vacuity_without_the_partition_the_held_out_event_reaches_the_cause(tmp_path, monkeypatch):
    hs = fx.checkout(tmp_path)
    blind_events(tmp_path, hs)
    monkeypatch.setattr(ist, "partition_events", lambda events, inputs, root=None: (events, []))
    result = ist.status(str(tmp_path))
    causes = {r["cause"] for r in result["rows"] if r["route"] == "fx-cheap"}
    assert causes == {"changed since the newest test run: corpus_sha256"} and result["heldout"] == [], "so the test above can fail when the partition is gone"
