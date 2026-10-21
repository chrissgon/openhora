"""The completeness test of the interpreter (package IX-C1, decision D10): nothing a channel policy can grant is reachable only by a command.

The rule, checked by `coverage_problems` against the test's OWN literal lists (the decisions, the widening and the internal gated operations, the work
operations that are not served) and the raw files of the corpus, never against the code under test:

  1. every operation that some group of `operations.GROUPS` grants is in the served catalog's `ops`, except
       - the five decisions (class D) and the sixteen widening gated operations, which are in `refused` and never in `ops`;
       - the ten internal gated operations and `say`, `request`, `route`, which are in neither list;
  2. every operation in the catalog's `ops` has at least 3 items in the dev corpus (`dev.jsonl` and `dev-relabelled.jsonl`, by the gold operation) and
     at least 2 in the test split (the per-operation counts of `test-split.json`; the held-out file itself is never read here).

An operation added to a policy group without a catalog row, or to the catalog without corpus items, fails. Each assertion has a vacuity case: the same
checker, run on a copy with one planted fault, must report it.

Offline, no model, no network. Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_coverage.py
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import standin_tree as st

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
EVALS = REPO / "evals" / "interpreter"
operations = st.load("operations")

MIN_DEV = 3
MIN_TEST = 2

# The operations a policy group grants and the catalog does not serve as a line to turn into an operation, by the test's own literals.
DECISIONS = ["approve", "reject", "release", "answer", "go-ahead"]
WIDENING = ["give-consent", "set-mode", "set-model", "config", "accept-config", "routine-approve", "source-add", "source-import", "source-drive",
            "source-onedrive", "source-mail", "source-calendar", "approve-policy", "standing", "execute-under-policy", "deps"]
INTERNAL = ["contained-run", "poll", "handler", "pin", "service-check", "route-queued", "attachment-hold", "conversation", "version", "artifact-raw"]
NOT_SERVED = ["say", "request", "route"]
REFUSED = DECISIONS + WIDENING
EXEMPT = INTERNAL + NOT_SERVED
# A few operations a reading of `operations.GROUPS` must hold, so that a reader that returned nothing could not pass.
KNOWN_GRANTED = ["status", "mail-send", "cancel", "approve", "say", "remind", "version", "stop-task", "source-refresh"]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def granted_ops() -> list:
    """Every operation some group of the channel policy can grant, read from the module that owns the groups."""
    return sorted({op for row in operations.GROUPS.values() for op in row["operations"]})


def dev_counts() -> dict:
    """The gold operation of every dev item (`dev.jsonl` and `dev-relabelled.jsonl`), counted from the raw lines."""
    counts: dict = {}
    seen = set()
    for name in ("dev.jsonl", "dev-relabelled.jsonl"):
        for line in (EVALS / name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            op = (item.get("gold") or {}).get("op")
            if op:
                counts[op] = counts.get(op, 0) + 1
    return counts


def split_counts() -> dict:
    """The per-operation counts of the test split's summary; the held-out lines are never read."""
    return load(EVALS / "test-split.json")["counts"]["op"]


# --- the checker (each assertion has a vacuity case below) ----------------------------------------------------------------------------------------

def coverage_problems(catalog: dict, granted: list, dev: dict, test: dict) -> list:
    """Everything that breaks the coverage rule, by the test's own literal lists."""
    out = []
    ops = [row["op"] for row in catalog["ops"]]
    refused = [row["op"] for row in catalog["refused"]]
    for op in granted:
        if op in EXEMPT:
            if op in ops or op in refused:
                out.append("%s: not served, yet in the catalog" % op)
        elif op in REFUSED:
            if op not in refused:
                out.append("%s: granted, a decision or a widening act, not in refused" % op)
            if op in ops:
                out.append("%s: a decision or a widening act in ops" % op)
        elif op not in ops:
            out.append("%s: granted by a policy group, not in the catalog" % op)
    for op in refused:
        if op not in REFUSED:
            out.append("%s: in refused, neither a decision nor a widening act" % op)
    for op in ops:
        if dev.get(op, 0) < MIN_DEV:
            out.append("%s: %d dev items, at least %d needed" % (op, dev.get(op, 0), MIN_DEV))
        if test.get(op, 0) < MIN_TEST:
            out.append("%s: %d test items, at least %d needed" % (op, test.get(op, 0), MIN_TEST))
    return out


def served() -> dict:
    return load(RUNTIME / "interpreter_catalog.json")


def planted(catalog: dict, **change) -> dict:
    return {**copy.deepcopy(catalog), **change}


# --- the real files -------------------------------------------------------------------------------------------------------------------------------

def test_the_policy_groups_are_read_and_hold_the_known_operations():
    granted = granted_ops()
    assert granted
    for op in KNOWN_GRANTED:
        assert op in granted, op
    assert set(NOT_SERVED) <= set(granted)


def test_every_operation_a_policy_can_grant_is_in_the_catalog_or_exempt():
    problems = [p for p in coverage_problems(served(), granted_ops(), dev_counts(), split_counts())
                if "dev items" not in p and "test items" not in p]
    assert problems == []


def test_every_catalog_operation_has_dev_and_test_items():
    problems = [p for p in coverage_problems(served(), granted_ops(), dev_counts(), split_counts())
                if "dev items" in p or "test items" in p]
    assert problems == []


# --- vacuity: the same checker, one planted fault each ---------------------------------------------------------------------------------------------

def test_vacuity_a_granted_operation_missing_from_the_catalog_fails():
    catalog = served()
    granted = granted_ops() + ["fake-new-op"]
    assert any(p.startswith("fake-new-op: granted by a policy group") for p in coverage_problems(catalog, granted, dev_counts(), split_counts()))
    dropped = planted(catalog, ops=[row for row in catalog["ops"] if row["op"] != "mail-send"])
    assert any(p.startswith("mail-send: granted by a policy group") for p in coverage_problems(dropped, granted_ops(), dev_counts(), split_counts()))


def test_vacuity_a_catalog_with_one_extra_operation_fails():
    catalog = served()
    extra = planted(catalog, ops=catalog["ops"] + [{"op": "fake-new-op", "class": "R", "what": "x", "slots": {}}])
    problems = coverage_problems(extra, granted_ops(), dev_counts(), split_counts())
    assert "fake-new-op: 0 dev items, at least 3 needed" in problems
    assert "fake-new-op: 0 test items, at least 2 needed" in problems


def test_vacuity_an_operation_with_two_dev_items_fails():
    dev = dict(dev_counts())
    dev["status"] = 2
    assert coverage_problems(served(), granted_ops(), dev, split_counts()) == ["status: 2 dev items, at least 3 needed"]
    dev["status"] = 3
    assert coverage_problems(served(), granted_ops(), dev, split_counts()) == []


def test_vacuity_an_operation_with_one_test_item_fails():
    test = dict(split_counts())
    test["status"] = 1
    assert coverage_problems(served(), granted_ops(), dev_counts(), test) == ["status: 1 test items, at least 2 needed"]
    test["status"] = 2
    assert coverage_problems(served(), granted_ops(), dev_counts(), test) == []


def test_vacuity_a_decision_a_widening_act_or_an_internal_operation_in_the_wrong_list_fails():
    catalog = served()
    row = {"op": "x", "class": "R", "what": "x", "slots": {}}
    for op in ("approve", "give-consent", "version"):
        in_ops = planted(catalog, ops=catalog["ops"] + [dict(row, op=op)])
        assert any(p.startswith(op + ":") for p in coverage_problems(in_ops, granted_ops(), dev_counts(), split_counts())), op
    lost = planted(catalog, refused=[r for r in catalog["refused"] if r["op"] != "approve"])
    assert "approve: granted, a decision or a widening act, not in refused" in coverage_problems(lost, granted_ops(), dev_counts(), split_counts())
    foreign = planted(catalog, refused=catalog["refused"] + [dict(row, op="status")])
    assert "status: in refused, neither a decision nor a widening act" in coverage_problems(foreign, granted_ops(), dev_counts(), split_counts())
    named = planted(catalog, refused=catalog["refused"] + [dict(row, op="say")])
    assert "say: not served, yet in the catalog" in coverage_problems(named, granted_ops(), dev_counts(), split_counts())


def test_vacuity_the_dev_reader_counts_both_files_and_each_item_once(tmp_path, monkeypatch):
    (tmp_path / "dev.jsonl").write_text('{"id":"a","gold":{"op":"status"}}\n{"id":"b","gold":{"outcome":"refuse"}}\n', encoding="utf-8")
    (tmp_path / "dev-relabelled.jsonl").write_text('{"id":"c","gold":{"op":"status"}}\n{"id":"a","gold":{"op":"status"}}\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "EVALS", tmp_path)
    assert dev_counts() == {"status": 2}
