#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The evidence lines of the interpreter experiment (package IX-2c): the hashes an event states, the test id, and the builders of the event, item and aggregate lines in
the closed forms of IX-E (evals/evidence_lines.py: IX_EVENT_KEYS, IX_ITEM_KEYS, IX_AGGREGATE_KEYS). The layer map keeps runtime/ from importing evals/, so the forms are
repeated here and a test (runtime/tests/test_interpreter_measure_evidence.py) loads the validator by path and refuses any line this module builds that it would refuse.

Every value of a line is a closed word, a pattern, a hash, an id, a number or a bool. There is no free-text field: a line, a span, a frame, a model's answer or an exception
message never enters a builder. A file is written once, whole, with an exclusive create: an existing file is never overwritten.

  hashes(route, root=ROOT)             the hash fields of an event (a route is a row of runtime/interpreter_routes.json, or None for the current pipeline)
  corpus_sha256(split, corpus_path)    for a test or a local corpus the sha256 of the BYTES of evals/interpreter/test-split.json (the status script's reading, and never a
                                       hash of private content); for dev the sha256 of the corpus file's bytes
  harness_sha256(root)                 the sha256 of the canonical {path: sha256 of its bytes} of the four modules of the measurement and the two data files the scorer reads
  new_test_id(), utc_date()            `YYYYMMDDTHHMMSSZ-<8 hex>` (secrets.token_hex(4)) and the UTC date
  event_line, item_line, aggregate_line, cost_usd, write_exclusive

Python 3.9, standard library only. `python3 runtime/interpreter_evidence.py --help` prints this text.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import interpreter  # noqa: E402  (the same folder: the protocol, the prompt and the served catalog whose hashes an event states)
import interpreter_route  # noqa: E402  (the same folder: the hash of a route)
import prices  # noqa: E402  (the same folder: the one price table)

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "evals", "interpreter")
EVIDENCE_DIR = os.path.join(DATA, "evidence")
SPLIT_FILE = os.path.join(DATA, "test-split.json")
HARNESS_FILES = ("runtime/interpreter_measure.py", "runtime/interpreter_pipeline.py", "runtime/interpreter_score.py", "runtime/interpreter_evidence.py",
                 "evals/interpreter/taxonomy.json", "evals/interpreter/thresholds.json")
USAGE_KEYS = ("input", "output", "cache_read", "cache_write")
LANGS = ("pt-BR", "en", "es", "fr", "de", "it", "ja", "mixed")          # evals/evidence_lines.py IX_LANGS


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_obj(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def sha_file(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def harness_sha256(root: str = ROOT) -> str:
    """The version of the measurement code and of the data its scorer reads (recorded, never a condition of the current set)."""
    return sha_obj({rel: sha_file(os.path.join(root, *rel.split("/"))) for rel in HARNESS_FILES})


def corpus_sha256(split: str, corpus_path: str, split_file: str = SPLIT_FILE) -> str:
    """The `corpus_sha256` of an event: the test-split file's bytes for the test split and for local lines (the split the local counts are read beside), the corpus file's
    own bytes for dev."""
    if split in ("test", "local"):
        return sha_file(split_file)
    return sha_file(corpus_path)


def hashes(route=None, root: str = ROOT) -> dict:
    """The hash fields of an event. For the current pipeline (route None) the route and prompt hashes are null: no prompt and no route are used."""
    out = {"model": None, "route": None, "route_sha256": None, "prompt_sha256": None,
           "protocol": interpreter.PROTOCOL["protocol"], "protocol_sha256": sha_obj(_json(interpreter.PROTOCOL_FILE)),
           "catalog_sha256": interpreter.SERVED_SHA256,
           "taxonomy_sha256": sha_obj(_json(os.path.join(root, "evals", "interpreter", "taxonomy.json"))),
           "thresholds_sha256": sha_obj(_json(os.path.join(root, "evals", "interpreter", "thresholds.json"))),
           "harness_sha256": harness_sha256(root)}
    if route is not None:
        out.update(model=route["model"], route=route["id"], route_sha256=interpreter_route.route_sha256(route), prompt_sha256=interpreter.prompt_sha256())
    return out


def new_test_id(now=None) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now)) + "-" + secrets.token_hex(4)


def utc_date(now=None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


# --- the lines --------------------------------------------------------------------------------------------------------------------------------------------

def event_line(*, arm: str, split: str, test: str, date: str, route, runs: int, items: int, sequential: bool, billing: str, corpus: str, root: str = ROOT) -> dict:
    """The first line of an evidence file. `items` is the number of items of the corpus FILE (a sample event states the file's, not the sample's)."""
    line = {"record": "event", "kind": "interpreter", "test": test, "date": date, "arm": arm, "split": split}
    line.update(hashes(route if arm == "bprime" else None, root))
    line.update(corpus_sha256=corpus, runs=runs, items=items, sequential=sequential, billing=billing)
    return {key: line[key] for key in sorted(line)}


def cost_usd(usage, route, table):
    """Dollars for one call at the route's model price (runtime/prices.json), or None: a run that is not metered, a call that reported no token count, or a kind of token that
    has no price (an unpriced cache read is unknown, never zero)."""
    if route is None or not isinstance(usage, dict) or (usage.get("input") is None and usage.get("output") is None):
        return None
    return prices.expected_cost(usage, prices.price_of(table, [route["model"]]))


def item_line(test: str, item: dict, run: int, outcome: dict, category: str, route=None, table=None) -> dict:
    """The line of one run of one item. `route` is None for the current pipeline (unmetered: no cost, no upstream)."""
    call = outcome.get("call")
    usage = call.get("usage") if call else None
    clean = {key: usage.get(key) for key in USAGE_KEYS} if isinstance(usage, dict) else None
    latency = call.get("latency_ms") if call else None
    return {"record": "item", "test": test, "item": item["id"], "run": run, "lang": item["lang"], "hard": bool(item["hard"]), "gold": item["gold"]["outcome"],
            "category": category, "observed": outcome["observed"], "parse": outcome["parse"], "error": outcome["error"], "time_source": outcome["time_source"],
            "latency_ms": latency if isinstance(latency, int) and not isinstance(latency, bool) and latency >= 0 else None, "usage": clean,
            "cost_usd": cost_usd(clean, route, table) if route is not None else None,
            "upstream": route["pin"] if route is not None and call and call.get("upstream") else None}


def aggregate_line(test: str, lang: str, categories, parse_invalid: int) -> dict:
    """The line of one language of local lines: the categories of the worst run of each item, counted; no id, no line."""
    counts = {}
    for name in categories:
        counts[name] = counts.get(name, 0) + 1
    return {"record": "aggregate", "test": test, "lang": lang, "n": sum(counts.values()), "counts": dict(sorted(counts.items())), "parse_invalid": parse_invalid}


def dumps(line: dict) -> str:
    return json.dumps(line, ensure_ascii=True, sort_keys=True, separators=(",", ":"))          # ASCII: a lone surrogate in a model's answer cannot fail to encode


def write_exclusive(path: str, lines) -> None:
    """Write the lines (dicts) to `path`, one canonical JSON object each, with an exclusive create: a file that exists is never overwritten (FileExistsError)."""
    body = "".join(dumps(line) + "\n" for line in lines)
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(body)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
