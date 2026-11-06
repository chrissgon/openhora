#!/usr/bin/env python3
"""Check that a brand guide still matches the brand files it consolidates.

Usage:
  python3 check_guide.py --guide docs/brand/guidelines.md [--brand-dir docs/brand]

Reports, as JSON on stdout:
  missing_sources   brand files the guide cites ([file.md]) that do not exist in --brand-dir
  uncited_sources   brand files that exist (profile, name, strategy, identity, voice) but the guide
                    never cites
  stale_quotes      lines of the guide inside quotes ("...") of 12 or more characters that appear in
                    no brand file (a label or rule changed and the guide was not updated); pass
                    --ignore-quote for quotes that are the guide's own examples
  hex_not_in_identity  colour codes in the guide that identity.md does not contain
  absent_not_named  brand files that do not exist and whose skill the guide never names (a missing
                    name.md must be written as "not defined yet" with brand-name, not left out)
  unquoted_examples cells of the do-and-don't table (the table under the heading that contains
                    --examples-heading, default "Do and don't") that are not a quote in "..."
  untagged_lines    rule lines (a bullet, a numbered item or a table body row) between the first "## "
                    heading and the heading that contains --sources-heading (default "Sources"), outside
                    code fences, that do not end with [<name>.md] (a closing ".", ")" or " |" after the
                    tag is allowed); a line that names docs/workbench/state.md or a brand skill in
                    backticks (`brand-name`) is exempt
Exit 1 when anything is reported, 2 on a bad argument or unreadable file.
"""
import argparse
import json
import os
import re
import sys

KNOWN = ["profile.md", "name.md", "strategy.md", "identity.md", "voice.md"]
SKILL_OF = {f: "brand-" + f[:-3] for f in KNOWN}


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        print(f"check_guide.py: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def unquoted_cells(guide, heading):
    section, inside = [], False
    for line in guide.splitlines():
        if line.startswith("#"):
            inside = heading.lower() in line.lower()
            continue
        if inside and line.strip().startswith("|"):
            section.append(line)
    cells = []
    for row in section[2:]:  # skip the header row and the separator
        for cell in [c.strip() for c in row.strip().strip("|").split("|")]:
            if cell and not re.match(r'^["\u201c]', cell):
                cells.append(cell)
    return cells


TAG_END = re.compile(r"\[[\w-]+\.md\][.)]*\s*\|?\s*$")
ITEM = re.compile(r"^\s*(?:[-*]\s|\d+\.\s)")


def untagged_lines(guide, sources_heading):
    found, started, fenced, table_row = [], False, False, 0
    for line in guide.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("#"):
            table_row = 0
            if line.startswith("## "):
                if started and sources_heading.lower() in line.lower():
                    break
                started = True
            continue
        if not started:
            continue
        is_table = stripped.startswith("|")
        if is_table:
            table_row += 1
            if table_row <= 2:  # the header row and the separator
                continue
        else:
            table_row = 0
            if not ITEM.match(line):
                continue
        if TAG_END.search(stripped):
            continue
        if "docs/workbench/state.md" in line or re.search(r"`brand-[\w-]+`", line):
            continue
        found.append(stripped)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--guide", required=True)
    ap.add_argument("--brand-dir", default="docs/brand")
    ap.add_argument("--ignore-quote", action="append", default=[])
    ap.add_argument("--examples-heading", default="Do and don't")
    ap.add_argument("--sources-heading", default="Sources")
    args = ap.parse_args()
    guide = read(args.guide)
    cited = set(re.findall(r"\[([\w-]+\.md)\]", guide))
    existing = {f for f in KNOWN if os.path.isfile(os.path.join(args.brand_dir, f))}
    files = {f: read(os.path.join(args.brand_dir, f)) for f in existing}
    for f in cited - existing:
        p = os.path.join(args.brand_dir, f)
        if os.path.isfile(p):
            files[f] = read(p)
    corpus = "\n".join(files.values())
    norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
    ncorpus = norm(corpus)
    quotes = [q for q in re.findall(r"\"([^\"\n]{12,})\"", guide) if q not in args.ignore_quote]
    stale = [q for q in quotes if norm(q) not in ncorpus]
    identity = files.get("identity.md", "").upper()
    hexes = sorted({h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}\b", guide)})
    report = {
        "missing_sources": sorted(f for f in cited if not os.path.isfile(os.path.join(args.brand_dir, f))),
        "uncited_sources": sorted(existing - cited),
        "stale_quotes": stale,
        "hex_not_in_identity": [h for h in hexes if identity and h not in identity],
        "absent_not_named": sorted(f for f in KNOWN if f not in existing and SKILL_OF[f] not in guide),
        "unquoted_examples": unquoted_cells(guide, args.examples_heading),
        "untagged_lines": untagged_lines(guide, args.sources_heading),
    }
    report["ok"] = not any(report.values())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
