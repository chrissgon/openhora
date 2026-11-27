#!/usr/bin/env python3
"""Check the file of explained text findings against the rules of the skill's self-check step.

Deterministic checks only: it never opens a link and never judges whether an explanation is right. It checks that
the file has the shape the skill promises, that the words are the closed ones, and, when it is given the lines the
task quoted, that every quote is one of them.

Usage:
  python3 check_explained.py --slot <name> [--slot ...] [--file <path>] [--task-file <path>]

  --slot <name>      a slot of the task that has lines (required, repeated); each must have a finding
  --file <path>      the file to check (default .workbench-local/video/scan-explained.json)
  --task-file <path> optional: a JSON file {"slots": {"<name>": ["<line>", ...]}} of the lines the task quoted. With it
                     every `quote` must be exactly one of the lines of its slot (grounding). The runtime passes it; a
                     run that has none checks the shape alone

What fails the check:
  - a file that is not a JSON object, a `schema_version` other than 1, `slots` or `open` that is not a list
  - a slot the task does not give, a slot twice, a slot given by --slot that the file lacks, a slot with no finding or with
    more than 12
  - a finding with a key other than source, quote, concern and explanation, or a missing one; a `source` other than
    `text` or `qr`; a `concern` outside the closed list; a quote or an explanation that is empty, not text, over its
    bound (quote 200 characters, explanation 240) or holds a control, bidirectional or zero-width character
  - an explanation that holds a web address (`://`)
  - an `open` item with a code other than `nothing_to_explain`
  - with --task-file, a quote that is not one of the slot's lines

Output: one JSON object on stdout with `ok`, `summary`, `errors` (a list of {"where", "field", "code"}; never the
refused text) and `counts`. Diagnostics of a usage error go to stderr. Exit codes: 0 no errors, 1 errors found,
2 usage error (nothing is checked).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_FILE = ".workbench-local/video/scan-explained.json"
SOURCES = ("text", "qr")
CONCERNS = ("licence_mark", "contact", "link", "brand", "claim", "language", "sensitive", "none", "unclear")
OPEN_CODES = ("nothing_to_explain",)
FINDING_KEYS = ("source", "quote", "concern", "explanation")
MAX_QUOTE = 200
MAX_EXPLANATION = 240
MAX_FINDINGS = 12
SLOT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
UNSAFE = re.compile("[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")


def text_problem(value, bound):
    """The code of the first rule the text breaks, or None. Never returns the text."""
    if not isinstance(value, str) or not value.strip():
        return "not_text"
    if len(value) > bound:
        return "too_long"
    if UNSAFE.search(value):
        return "bad_character"
    return None


def load_task(path):
    """{slot: [lines]} from the task file, or raises ValueError."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    slots = data.get("slots") if isinstance(data, dict) else None
    if not isinstance(slots, dict) or not all(isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v) for k, v in slots.items()):
        raise ValueError("the task file is not {\"slots\": {name: [lines]}}")
    return slots


def check(doc, slots, lines=None):
    """(errors, counts) of a parsed file; `slots` is the list of the task's slots, `lines` the optional {slot: [lines]}."""
    errors = []
    err = lambda where, field, code: errors.append({"where": where, "field": field, "code": code})  # noqa: E731
    counts = {"slots": 0, "findings": 0}
    if not isinstance(doc, dict):
        return [{"where": "file", "field": "", "code": "not_an_object"}], counts
    if doc.get("schema_version") != 1:
        err("file", "schema_version", "not_1")
    if set(doc) - {"schema_version", "slots", "open"}:
        err("file", "keys", "unknown_key")
    rows, opened = doc.get("slots"), doc.get("open")
    if not isinstance(rows, list):
        err("file", "slots", "not_a_list")
        rows = []
    if not isinstance(opened, list):
        err("file", "open", "not_a_list")
        opened = []
    seen = []
    for i, row in enumerate(rows):
        where = f"slots[{i}]"
        if not isinstance(row, dict) or set(row) != {"slot", "findings"}:
            err(where, "keys", "bad_keys")
            continue
        slot = row["slot"]
        if not (isinstance(slot, str) and SLOT_ID.fullmatch(slot)):
            err(where, "slot", "bad_slot")
        elif slot not in slots:
            err(where, "slot", "unknown_slot")
        elif slot in seen:
            err(where, "slot", "duplicate_slot")
        else:
            seen.append(slot)
        found = row["findings"]
        if not isinstance(found, list) or not found:
            err(where, "findings", "empty_or_not_a_list")
            continue
        if len(found) > MAX_FINDINGS:
            err(where, "findings", "too_many")
        for j, f in enumerate(found):
            at = f"{where}.findings[{j}]"
            counts["findings"] += 1
            if not isinstance(f, dict) or set(f) != set(FINDING_KEYS):
                err(at, "keys", "bad_keys")
                continue
            if f["source"] not in SOURCES:
                err(at, "source", "not_in_list")
            if f["concern"] not in CONCERNS:
                err(at, "concern", "not_in_list")
            for field, bound in (("quote", MAX_QUOTE), ("explanation", MAX_EXPLANATION)):
                problem = text_problem(f[field], bound)
                if problem:
                    err(at, field, problem)
            if isinstance(f["explanation"], str) and "://" in f["explanation"]:
                err(at, "explanation", "web_address")
            if lines is not None and isinstance(slot, str) and isinstance(f["quote"], str) and f["quote"] not in lines.get(slot, []):
                err(at, "quote", "not_a_line_of_the_task")
    counts["slots"] = len(seen)
    for name in slots:
        if name not in seen:
            err("file", name, "slot_missing")
    for i, item in enumerate(opened):
        if not (isinstance(item, dict) and set(item) == {"code"} and item["code"] in OPEN_CODES):
            err(f"open[{i}]", "code", "not_in_list")
    return errors, counts


def main(argv=None):
    p = argparse.ArgumentParser(description="Check the file of explained text findings.", add_help=True)
    p.add_argument("--slot", action="append", default=[], help="a slot of the task that has lines (repeated)")
    p.add_argument("--file", default=DEFAULT_FILE, help="the file to check")
    p.add_argument("--task-file", default=None, help="optional: {\"slots\": {name: [lines]}}, the lines the task quoted")
    args = p.parse_args(argv)
    for s in args.slot:
        if not SLOT_ID.fullmatch(s):
            print(f"error: {s!r} is not a slot name", file=sys.stderr)
            return 2
    if not args.slot:
        print("error: give at least one --slot", file=sys.stderr)
        return 2
    lines = None
    if args.task_file:
        try:
            lines = load_task(args.task_file)
        except (OSError, ValueError, RecursionError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    try:
        doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        doc = None
    errors, counts = check(doc, args.slot, lines)
    ok = not errors
    summary = (f"ok: {counts['findings']} findings in {counts['slots']} slots" if ok else f"{len(errors)} errors")
    json.dump({"ok": ok, "summary": summary, "errors": errors, "counts": counts}, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
