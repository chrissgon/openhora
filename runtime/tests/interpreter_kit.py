"""Helpers of the tests of the interpreter's protocol and validator (package IX-2a). Not a test file.

The served catalog (package IX-C, `runtime/interpreter_catalog.py`) is built here by the rule of its text, from `natural.NATURAL` and `natural.CLASSES`, with the test's own
literal lists of the operations that are not in the model's vocabulary, so that a test of the validator never reads the generator it is checked against.
"""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import standin_tree as st

natural = st.load("natural")
operations = st.load("operations")

# The test's own literal lists (the oracle reads these, never the code under test).
D_OPS = ["approve", "reject", "release", "answer", "go-ahead"]
WIDENING = ["give-consent", "set-mode", "set-model", "config", "accept-config", "routine-approve", "source-add", "source-import", "source-drive", "source-onedrive",
            "source-mail", "source-calendar", "approve-policy", "standing", "execute-under-policy", "deps"]
OPERATIONAL = ["routine-resume", "instructions-set", "instructions-add", "source-refresh", "source-describe", "flow-save", "stage-file", "sync", "hand-over", "dispatch",
               "verdict", "run-next", "run-task", "run-step", "proof", "revoke-policy", "stop-runs"]
INTERNAL = ["contained-run", "poll", "handler", "pin", "service-check", "route-queued", "attachment-hold", "conversation", "version", "artifact-raw"]
WORK_NOT_ASK = ["say", "request", "route"]

ZONE = "America/Sao_Paulo"


def now_at(wall: str = "2026-10-20 09:00", zone: str = ZONE) -> datetime.datetime:
    return datetime.datetime.strptime(wall, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(zone))


NOW = now_at()


def _words(op: str) -> str:
    """The text a row is served with: its `what` at catalog version 1, its `about` from version 2 (CB-9; the record of the row is the operations table's `natural` key)."""
    record = next(row["natural"] for row in operations.OPERATIONS if row["name"] == op)
    return record["what"] if operations.LINE_CATALOG <= 1 else record["about"]


def _row(op: str, cls: str) -> dict:
    return {"op": op, "class": cls, "what": _words(op), "slots": {slot: kind for slot, (kind, _param) in natural.NATURAL[op]["slots"].items()}}


def build_catalog() -> dict:
    ops = [_row(op, natural.CLASSES[op]) for op in natural.NATURAL if natural.CLASSES.get(op) in ("R", "N", "W", "E")]
    ops.append(_row("ask", "work"))
    ops += [_row(op, "G") for op in natural.NATURAL if op in OPERATIONAL]
    refused = [{"op": op, "class": "D", "what": _words(op)} for op in natural.NATURAL if op in D_OPS]
    refused += [{"op": op, "class": "G", "what": _words(op)} for op in natural.NATURAL if op in WIDENING]
    return {"v": operations.LINE_CATALOG, "ops": ops, "refused": refused}      # the version of the served catalog (3 since MAIL-SUMMARY-FLIP)


CATALOG = build_catalog()
ALL_OPS = frozenset(row["op"] for row in CATALOG["ops"])


def item(id="i1", kind="write-draft", need="slot", op="mail-send", slot="to", age_s=20, **more) -> dict:
    return {"id": id, "kind": kind, "need": need, "op": op, "slot": slot, "age_s": age_s, **more}
