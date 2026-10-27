#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The catalog the interpreter is served (package IX-C0): what a line of a person's own words may be turned into, as data.

Pure and deterministic: it reads the registry (runtime/registry.py: the `natural` records of runtime/operations.py, package CB-0) and the classification of the gated operations in
runtime/gated_ops.json, and writes nothing but the snapshot runtime/interpreter_catalog.json when asked to. No model runs here.

  generate(version=None, gated=None)
               the snapshot: {"v": <version>, "ops": [row...], "refused": [row...]}. `version` is the catalog version (default `operations.LINE_CATALOG`, 1 today): the rows and the
               slots served are those whose `since` is at most it; version 1 words each row with its `what` (byte for byte the catalog the newest enabling entry pins), version 2 with its `about`
                 ops      the operations of class R, N, W and E, then `ask`, then the gated operations of kind `operational`, each list in the registry's `order` (the order of the
                          catalog the model reads);
                          a row is {"op", "class", "what", "slots": {slot: kind}} (the class of `ask` is "work")
                 refused  the five operations of class D and the gated operations of kind `widening`, as {"op", "class", "what"}: a model may name them so that the code
                          refuses with the right sentence, and the code never executes one whatever the model returns
               The gated operations of kind `internal` and the work operations `say`, `request` and `route` are in neither list.
  sha256(obj)  the hash of the canonical JSON of an object (sorted keys, no spaces, UTF-8)
  TIME_SLOTS   the (operation, slot) pairs whose value is a time

  python3 runtime/interpreter_catalog.py --write   write runtime/interpreter_catalog.json
  python3 runtime/interpreter_catalog.py --check   exit 1 when the file's hash differs from generate()'s
  python3 runtime/interpreter_catalog.py --hash    print the hash of the file
  python3 runtime/interpreter_catalog.py --version 2 --print   print the catalog of version 2 and its hash; it writes nothing (CB-9 and the reviewers use it)

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

import operations  # noqa: E402  (LINE_CATALOG, the default version)
import registry  # noqa: E402  (the one reader of the rows)

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


def _words(rec: dict, version: int) -> str:
    """The text a row is served with: its `what` at version 1, its `about` from version 2."""
    return rec["what"] if version <= 1 else rec["about"]


def _row(rec: dict, version: int) -> dict:
    return {"op": rec["op"], "class": rec["class"], "what": _words(rec, version), "slots": {slot: spec["kind"] for slot, spec in rec["slots"].items()}}


def _refused(rec: dict, version: int) -> dict:
    return {"op": rec["op"], "class": rec["class"], "what": _words(rec, version)}


def generate(version: int = None, gated: list = None) -> dict:
    """The snapshot of catalog `version` (default `operations.LINE_CATALOG`). `gated` (rows of the gated-operations file) is read from the file when not given."""
    wanted = operations.LINE_CATALOG if version is None else version
    rows = gated_rows() if gated is None else gated
    kind = {r["op"]: r["kind"] for r in rows}
    records = registry.rows(wanted)
    ops = [rec for rec in records if rec["class"] in SERVED_CLASSES]
    ops += [rec for rec in records if rec["op"] == "ask"]
    ops += [rec for rec in records if rec["class"] == "G" and kind.get(rec["op"]) == "operational"]
    refused = [rec for rec in records if rec["class"] == "D"]
    refused += [rec for rec in records if rec["class"] == "G" and kind.get(rec["op"]) == "widening"]
    return {"v": wanted, "ops": [_row(rec, wanted) for rec in ops], "refused": [_refused(rec, wanted) for rec in refused]}


def text(snapshot: dict) -> str:
    """The file's text: indent 1, sorted keys, no ASCII escapes, one newline at the end."""
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def served(path: Path = CATALOG_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The catalog the interpreter is served: generate it, write it, check the served file against it.")
    parser.add_argument("--version", type=int, choices=(1, 2), default=None, help="with --print: the catalog version to print (default: operations.LINE_CATALOG)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write runtime/interpreter_catalog.json from generate()")
    mode.add_argument("--check", action="store_true", help="exit 1 when the served file's hash differs from generate()'s")
    mode.add_argument("--hash", action="store_true", help="print the hash of the served file")
    mode.add_argument("--print", action="store_true", help="print the catalog of --version and, on stderr, its hash; it writes nothing")
    args = parser.parse_args(argv)
    if args.print:
        snapshot = generate(args.version)
        sys.stdout.write(text(snapshot))
        print(sha256(snapshot), file=sys.stderr)
        return 0
    if args.version is not None:
        parser.error("--version goes with --print: --write and --check always use the default version")
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
