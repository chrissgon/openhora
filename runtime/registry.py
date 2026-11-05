#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The registry: what a line in the person's own words may do with each operation, read from one place (PLAN-BRAIN section 4.2, package CB-0).

The registry is the rows of `operations.OPERATIONS`: each row carries a pure literal `natural` (its class, the catalog version it is served from, its place in the catalog, its
texts, its slots with a kind, a parameter and a version, its privacy class and its cost class; `runtime/operations.py` describes the record above its `OPERATIONS`). There is no second
table. `natural.CLASSES` and `natural.NATURAL` are views of those records, and this module is the one reader for the layers above them (the catalog the interpreter is served, the
confirmation of a read, the page and the reviewers).

  rows(version=None)       the records served at a catalog version (default `operations.LINE_CATALOG`): the rows whose `since` is at most the version, in their `order`, each as
                           {"op", "class", "since", "order", "what", "about", "privacy", "cost", "slots": {slot: {"kind", "param", "since"}}} with only the slots whose `since` is at most
                           the version; a copy, so that the caller cannot change the literal
  row(op)                  the whole record of one operation whatever its version, or None for a name that is not an operation
  privacy(op), cost(op), about(op), what(op)
                           one field of the record, or None for a name that is not an operation
  origins(op, slot)        the origins an argument of that slot may have, a tuple of words of `turn_gate.ORIGINS`. For a class E row it is `turn_gate.ALLOWED[param]`: the gate is the one
                           home of the allowed origins (a hard limit has one home in code) and the registry only reads it; a slot whose parameter is not an argument of the card (`target`, `day`:
                           the words that find an item, read by code from the line) is `line-span`; a parameter the gate does not declare raises ValueError, so a new slot cannot go
                           unchecked. For another class, by kind: int and ints are `line-number` or `listed`, span and word `line-span`, when `time-engine`. KeyError for an unknown operation or slot.
  always(version=None)     the reads (class R, and the `work` operation a line may name, `natural.LINE_WORK`) served at that version that always ask "Posso?" on a messaging app: those whose
                           cost is `model` or whose privacy is `off-host`, in catalog order. `plan_confirm.ALWAYS` is this value.
  data                     `registry_data` (S41-9), unchanged: the private words and the search stop words

Pure and deterministic; standard library only, and the modules of this folder it names. `turn_gate` is imported inside `origins`, never at import, so the import order has no cycle
(`turn_gate` imports `natural`). Runs on Python 3.9: python3 runtime/registry.py --help
"""
from __future__ import annotations

import argparse
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural  # noqa: E402  (the views and LINE_WORK)
import operations  # noqa: E402  (the rows)
import registry_data as data  # noqa: E402,F401  (re-exported: the data the registry owns)

FINDER_PARAMS = ("target", "day")      # the slots that name an item of the person's calendar or mailbox by its words; read by code, never an argument of the card (B''-lite)


def _version(version) -> int:
    return operations.LINE_CATALOG if version is None else version


def _record(row: dict, version=None) -> dict:
    rec = copy.deepcopy(row["natural"])
    rec["op"] = row["name"]
    if version is not None:
        rec["slots"] = {slot: spec for slot, spec in rec["slots"].items() if spec["since"] <= version}
    return rec


def rows(version=None) -> list:
    """The records served at catalog `version` (default `operations.LINE_CATALOG`), in their `order`."""
    wanted = _version(version)
    found = [_record(row, wanted) for row in operations.OPERATIONS if row["natural"]["since"] <= wanted]
    return sorted(found, key=lambda rec: rec["order"])


def row(op: str):
    """The whole record of `op`, or None."""
    for given in operations.OPERATIONS:
        if given["name"] == op:
            return _record(given)
    return None


def _field(op: str, key: str):
    rec = row(op)
    return None if rec is None else rec[key]


def privacy(op: str):
    return _field(op, "privacy")


def cost(op: str):
    return _field(op, "cost")


def about(op: str):
    return _field(op, "about")


def what(op: str):
    return _field(op, "what")


def origins(op: str, slot: str) -> tuple:
    """The origins an argument of `slot` of `op` may have (see the module's text)."""
    rec = row(op)
    if rec is None:
        raise KeyError(op)
    spec = rec["slots"][slot]
    kind, param = spec["kind"], spec["param"]
    if rec["class"] == "E":
        if param in FINDER_PARAMS:
            return ("line-span",)
        import turn_gate      # inside the function: turn_gate imports natural, which imports operations, so the registry stays above both
        if param not in turn_gate.ALLOWED:
            raise ValueError(f"the gate declares no origin for {param!r} ({op}, slot {slot})")
        return tuple(turn_gate.ALLOWED[param])
    if kind in ("int", "ints"):
        return ("line-number", "listed")
    if kind == "when":
        return ("time-engine",)
    return ("line-span",)


def always(version=None) -> tuple:
    """The served reads that always ask before they run on a messaging app (see the module's text)."""
    return tuple(rec["op"] for rec in rows(version)
                 if (rec["class"] == "R" or rec["op"] in natural.LINE_WORK) and (rec["cost"] == "model" or rec["privacy"] == "off-host"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The registry: the `natural` records of runtime/operations.py. With --list, one line per served row: "
                                                 "operation, class, since, privacy, cost and the slots.")
    parser.add_argument("--list", action="store_true", help="print one line per row served at --version")
    parser.add_argument("--version", type=int, default=None, help="the catalog version (default: operations.LINE_CATALOG)")
    args = parser.parse_args(argv)
    if not args.list:
        parser.print_help()
        return 0
    for rec in rows(args.version):
        slots = ",".join(f"{slot}:{spec['kind']}" for slot, spec in rec["slots"].items()) or "-"
        print(f"{rec['op']}\t{rec['class']}\tsince={rec['since']}\t{rec['privacy']}\t{rec['cost']}\t{slots}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
