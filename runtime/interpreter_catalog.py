#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The catalog the interpreter is served (package IX-C0): what a line of a person's own words may be turned into, as data.

Pure and deterministic: it reads the tables of runtime/natural.py (`NATURAL`, `CLASSES`) and the classification of the gated operations in
runtime/gated_ops.json, and writes nothing but the snapshot runtime/interpreter_catalog.json when asked to. No model runs here.

  generate()   the snapshot: {"v": 1, "ops": [row...], "refused": [row...]}
                 ops      the operations of class R, N, W and E, then `ask`, then the gated operations of kind `operational`, each list in the order of `NATURAL`;
                          a row is {"op", "class", "what", "slots": {slot: kind}} (the class of `ask` is "work")
                 refused  the five operations of class D and the gated operations of kind `widening`, as {"op", "class", "what"}: a model may name them so that the code
                          refuses with the right sentence, and the code never executes one whatever the model returns
               The gated operations of kind `internal` and the work operations `say`, `request` and `route` are in neither list.
  sha256(obj)  the hash of the canonical JSON of an object (sorted keys, no spaces, UTF-8)
  TIME_SLOTS   the (operation, slot) pairs whose value is a time

  python3 runtime/interpreter_catalog.py --write   write runtime/interpreter_catalog.json
  python3 runtime/interpreter_catalog.py --check   exit 1 when the file's hash differs from generate()'s
  python3 runtime/interpreter_catalog.py --hash    print the hash of the file

Runs on Python 3.9: python3 runtime/interpreter_catalog.py --help
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import natural  # noqa: E402  (the one module this one reads)

GATED_FILE = HERE / "gated_ops.json"
CATALOG_FILE = HERE / "interpreter_catalog.json"
TIME_SLOTS = (("remind", "when"), ("event-create", "time"), ("event-change", "time"))
SERVED_CLASSES = ("R", "N", "W", "E")
KINDS = ("operational", "widening", "internal")


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def gated_rows(path: Path = GATED_FILE) -> list:
    """The rows of runtime/gated_ops.json: {"op", "kind", "group", "why"}, in `natural.CLASSES` order."""
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def _row(op: str) -> dict:
    entry = natural.NATURAL[op]
    cls = natural.CLASSES[op]
    return {"op": op, "class": cls, "what": entry["what"], "slots": {slot: kind for slot, (kind, _param) in entry["slots"].items()}}


def _refused(op: str) -> dict:
    return {"op": op, "class": natural.CLASSES[op], "what": natural.NATURAL[op]["what"]}


def generate(gated: list = None) -> dict:
    """The snapshot. `gated` (rows of the gated-operations file) is read from the file when not given."""
    rows = gated_rows() if gated is None else gated
    kind = {r["op"]: r["kind"] for r in rows}
    ops = [op for op in natural.NATURAL if natural.CLASSES[op] in SERVED_CLASSES]
    ops += ["ask"]
    ops += [op for op in natural.NATURAL if natural.CLASSES[op] == "G" and kind.get(op) == "operational"]
    refused = [op for op in natural.NATURAL if natural.CLASSES[op] == "D"]
    refused += [op for op in natural.NATURAL if natural.CLASSES[op] == "G" and kind.get(op) == "widening"]
    return {"v": 1, "ops": [_row(op) for op in ops], "refused": [_refused(op) for op in refused]}


def text(snapshot: dict) -> str:
    """The file's text: indent 1, sorted keys, no ASCII escapes, one newline at the end."""
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def served(path: Path = CATALOG_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The catalog the interpreter is served: generate it, write it, check the served file against it.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write runtime/interpreter_catalog.json from generate()")
    mode.add_argument("--check", action="store_true", help="exit 1 when the served file's hash differs from generate()'s")
    mode.add_argument("--hash", action="store_true", help="print the hash of the served file")
    args = parser.parse_args(argv)
    if args.write:
        CATALOG_FILE.write_text(text(generate()), encoding="utf-8")
        print(sha256(served()))
        return 0
    if args.hash:
        print(sha256(served()))
        return 0
    if not CATALOG_FILE.exists() or sha256(served()) != sha256(generate()):
        print("interpreter_catalog: the served file differs from generate(); run --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
