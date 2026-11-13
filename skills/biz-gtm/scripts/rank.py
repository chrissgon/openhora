#!/usr/bin/env python3
"""Rank options on scored criteria, refusing any score without a source.

Usage:
  python3 rank.py --input options.json
  python3 rank.py < options.json

Input JSON:
  {
    "criteria": [{"name": "demand", "weight": 1}, ...],        # weight optional, default 1
    "options": [
      {"name": "Websites",
       "scores": {"demand": {"score": 4, "sources": ["1", "3"]},
                  "urgency": {"score": 1, "sources": [], "note": "no evidence"}}}
    ]
  }

Every option must score every criterion with an integer from 1 to 5. A score above 1 needs at
least one source reference: a source number ("3", "2b") or a command label ("M1"), nothing else; a score of 1 with no source is reported as "1 (no evidence)".
--no-evidence-label sets the text shown for an unsupported score (default "no evidence").
Prints JSON to stdout: the ranked options with weighted totals, the gap between the top two,
and a Markdown table under "table". Diagnostics go to stderr.
Exit codes: 0 ok; 1 when the input is read and its content is refused (a score without a source,
a criterion not scored); 2 on a bad argument, or an input that cannot be read or is not JSON.
"""
import argparse
import json
import re
import sys

REF = re.compile(r"^(\d+[a-z]?|M\d+)$")


def fail(msg, code=1):
    print(f"rank.py: {msg}", file=sys.stderr)
    sys.exit(code)


def load(args):
    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            return json.load(fh)
    return json.load(sys.stdin)


def validate(data):
    crits = data.get("criteria")
    opts = data.get("options")
    if not isinstance(crits, list) or not crits:
        fail("'criteria' must be a non-empty list")
    if not isinstance(opts, list) or len(opts) < 2:
        fail("'options' must list at least two options")
    names = []
    for c in crits:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"]:
            fail("each criterion needs a 'name'")
        w = c.get("weight", 1)
        if not isinstance(w, (int, float)) or isinstance(w, bool) or w <= 0:
            fail(f"criterion '{c['name']}': weight must be a positive number")
        names.append(c["name"])
    if len(set(names)) != len(names):
        fail("criterion names must be unique")
    errors = []
    for o in opts:
        oname = o.get("name") if isinstance(o, dict) else None
        if not isinstance(oname, str) or not oname:
            fail("each option needs a 'name'")
        scores = o.get("scores")
        if not isinstance(scores, dict):
            fail(f"option '{oname}': 'scores' must be an object")
        for extra in set(scores) - set(names):
            errors.append(f"option '{oname}': unknown criterion '{extra}'")
        for n in names:
            s = scores.get(n)
            if not isinstance(s, dict):
                errors.append(f"option '{oname}': criterion '{n}' is not scored")
                continue
            val = s.get("score")
            if not isinstance(val, int) or isinstance(val, bool) or not 1 <= val <= 5:
                errors.append(f"option '{oname}', '{n}': score must be an integer from 1 to 5")
                continue
            srcs = s.get("sources", [])
            if not isinstance(srcs, list) or not all(isinstance(x, (str, int)) for x in srcs):
                errors.append(f"option '{oname}', '{n}': 'sources' must be a list of references")
            elif any(not REF.match(str(x)) for x in srcs):
                bad = [x for x in srcs if not REF.match(str(x))]
                errors.append(f"option '{oname}', '{n}': sources {bad} are not references; "
                              "use source numbers (\"3\", \"2b\") or command labels (\"M1\")")
            elif val > 1 and not srcs:
                errors.append(f"option '{oname}', '{n}': score {val} has no source; "
                              "use 1 with note 'no evidence' or cite a source")
    if errors:
        fail("invalid scores:\n  " + "\n  ".join(errors))
    return crits, opts


def cell(s, label):
    if not s.get("sources"):
        return f"{s['score']} ({label})"
    refs = "".join(f"[{x}]" for x in s["sources"])
    return f"{s['score']} {refs}"


def rank(crits, opts, label="no evidence"):
    rows = []
    for o in opts:
        total = sum(c.get("weight", 1) * o["scores"][c["name"]]["score"] for c in crits)
        unsupported = [c["name"] for c in crits if not o["scores"][c["name"]].get("sources")]
        rows.append({"name": o["name"], "total": round(total, 2), "unsupported": unsupported,
                     "cells": [cell(o["scores"][c["name"]], label) for c in crits]})
    rows.sort(key=lambda r: (-r["total"], r["name"]))
    header = ["Rank", "Option"] + [
        c["name"] if c.get("weight", 1) == 1 else f"{c['name']} (x{c['weight']})" for c in crits
    ] + ["Total"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for i, r in enumerate(rows, 1):
        lines.append("| " + " | ".join([str(i), r["name"]] + r["cells"] + [str(r["total"])]) + " |")
    gap = round(rows[0]["total"] - rows[1]["total"], 2)
    return {
        "ranked": [{"rank": i, "name": r["name"], "total": r["total"],
                    "unsupported_criteria": r["unsupported"]} for i, r in enumerate(rows, 1)],
        "max_total": round(sum(5 * c.get("weight", 1) for c in crits), 2),
        "gap_top_two": gap,
        "close_call": gap <= 2,
        "table": "\n".join(lines),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="options JSON file (default: stdin)")
    ap.add_argument("--no-evidence-label", default="no evidence",
                    help="text shown next to an unsupported score, in the artifact's language")
    args = ap.parse_args()
    try:
        data = load(args)
    except (OSError, ValueError) as exc:  # a missing file, a folder, bytes that are not UTF-8, text that is not JSON
        fail(f"cannot read input: {exc}", 2)
    if not isinstance(data, dict):
        fail("input must be a JSON object")
    crits, opts = validate(data)
    json.dump(rank(crits, opts, args.no_evidence_label), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
