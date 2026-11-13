#!/usr/bin/env python3
"""Lint a go-to-market artifact for the mistakes models repeat, and print its hours per week.

Usage:
  python3 lint_gtm.py --file docs/business/gtm.md
         [--status-words hypothesis,limited] [--hours-label "Hours per week"]
         [--plan-heading "First four weeks"] [--week-column Week] [--hours-column Hours]
         [--measurement-heading Measurement] [--continue-label "continue if"] [--stop-label "stop if"]
         [--rules-heading "Channel rules"] [--source-column Source] [--not-researched-label "not researched yet"]
         [--readiness-heading "Launch readiness"] [--done-column Done] [--done-words yes,no,unknown]
         [--sources-heading Sources] [--free-headings Method,Assumptions,Unknowns]
         [--required-headings "Motion,Channels,Channel rules,Launch readiness,First four weeks,Measurement,Left out,Assumptions,Sources,Method"]
         [--assumed-label "Assumption:"]

Checks, each reported with the line number:
  status: no "Status:" line containing one of --status-words.
  missing_section: a heading of --required-headings is not a "## " heading of the file.
  no_capacity: no number after "<--hours-label>:" in the header (the lines before the first "## " heading).
  bad_hours: a row of the plan table whose hours cell is not a number, or whose week cell is empty.
  hours_over_capacity: the hours of one week, summed over its rows, exceed the capacity.
  rules_cell: a row of the channel rules table whose source cell is empty and that does not hold
    the not-researched label.
  measurement_rule: a row of the measurement table with an empty "continue if" or "stop if" cell.
  readiness_done: a row of the readiness table whose done cell is not one of --done-words.
  bad_citation: a bracketed citation that is not one source number ([3], [2b]) or command label (M1).
  uncited_figure: a bullet or table row with a percentage or a currency amount and no source number,
    command label or assumption label, outside the sources section and --free-headings.
Headings and column labels are matched case-insensitively; pass translated texts for an artifact not in
English. The report always carries "hours_per_week" (week to summed hours) and "capacity", also when ok.
Prints JSON to stdout; exit 1 when anything is reported, 2 on a bad argument or unreadable file.
"""
import argparse
import json
import re
import sys

CURRENCY = re.compile(
    r"(?:[€$£]|R\$|US\$|\b(?:EUR|USD|BRL|GBP)\b)\s?\d|\d[\d.,]*\s?(?:[€£]|\b(?:EUR|USD|BRL|GBP)\b)")
FIGURE = re.compile(r"\d+(?:[.,]\d+)?\s?%|" + CURRENCY.pattern)
CITATION = re.compile(r"\[([^\]\n]+)\](?!\()")
GOOD_CITATION = re.compile(r"^(\d+[a-z]?|M\d+)$")
CITED = re.compile(r"\[(\d+[a-z]?|M\d+)\]|\bM\d+\b|assumption:|\bassumed\b", re.I)
DEFAULT_REQUIRED = ("Motion,Channels,Channel rules,Launch readiness,First four weeks,Measurement,"
                    "Left out,Assumptions,Sources,Method")


def low(text):
    return text.strip().lower()


def cells_of(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(cells):
    return set("".join(cells)) <= set("-: ")


def column(header, label):
    for i, c in enumerate(header):
        if low(label) in c.lower():
            return i
    return -1


def number(text):
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--status-words", default="hypothesis,limited")
    ap.add_argument("--hours-label", default="Hours per week")
    ap.add_argument("--plan-heading", default="First four weeks")
    ap.add_argument("--week-column", default="Week")
    ap.add_argument("--hours-column", default="Hours")
    ap.add_argument("--measurement-heading", default="Measurement")
    ap.add_argument("--continue-label", default="continue if")
    ap.add_argument("--stop-label", default="stop if")
    ap.add_argument("--rules-heading", default="Channel rules")
    ap.add_argument("--source-column", default="Source")
    ap.add_argument("--not-researched-label", default="not researched yet")
    ap.add_argument("--readiness-heading", default="Launch readiness")
    ap.add_argument("--done-column", default="Done")
    ap.add_argument("--done-words", default="yes,no,unknown")
    ap.add_argument("--sources-heading", default="Sources")
    ap.add_argument("--free-headings", default="Method,Assumptions,Unknowns")
    ap.add_argument("--required-headings", default=DEFAULT_REQUIRED)
    ap.add_argument("--assumed-label", default="Assumption:")
    args = ap.parse_args()
    try:
        with open(args.file, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        print(f"lint_gtm.py: cannot read {args.file}: {exc}", file=sys.stderr)
        sys.exit(2)
    plan, meas, rules, ready = (low(args.plan_heading), low(args.measurement_heading),
                                low(args.rules_heading), low(args.readiness_heading))
    srcs = low(args.sources_heading)
    free = {low(h) for h in args.free_headings.split(",") if h.strip()} | {srcs}
    required = [h.strip() for h in args.required_headings.split(",") if h.strip()]
    statuses = [low(w) for w in args.status_words.split(",") if w.strip()]
    done_words = [low(w) for w in args.done_words.split(",") if w.strip()]
    assumed, not_researched = low(args.assumed_label), low(args.not_researched_label)
    hours_re = re.compile(re.escape(low(args.hours_label)) + r"\s*:\s*\**\s*(\d+(?:[.,]\d+)?)")

    findings, headings = [], set()
    section, header, status_ok, capacity = "", None, False, None
    per_week = {}
    for n, line in enumerate(lines, 1):
        l = line.lower()
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            section, header = low(m.group(1)), None
            headings.add(section)
            continue
        if not section and capacity is None:
            hit = hours_re.search(l)
            if hit:
                capacity = number(hit.group(1))
        if re.search(r"status\s*:", l) and any(w in l for w in statuses):
            status_ok = True
        if line.lstrip().startswith("|"):
            cells = cells_of(line)
            if header is None:
                header = cells
            elif not is_separator(cells):
                if section == plan:
                    wi, hi = column(header, args.week_column), column(header, args.hours_column)
                    week = cells[wi] if 0 <= wi < len(cells) else ""
                    hours = number(cells[hi]) if 0 <= hi < len(cells) else None
                    if not week or hours is None or hours < 0:
                        findings.append({"line": n, "check": "bad_hours", "text": line.strip()[:160]})
                    else:
                        digits = re.search(r"\d+", week)
                        key = digits.group(0) if digits else week
                        per_week[key] = per_week.get(key, 0.0) + hours
                elif section == rules:
                    si = column(header, args.source_column)
                    cell = cells[si] if 0 <= si < len(cells) else ""
                    if cell in ("", "-", "—") and not_researched not in l:
                        findings.append({"line": n, "check": "rules_cell", "text": line.strip()[:160]})
                elif section == meas:
                    for label in (args.continue_label, args.stop_label):
                        ci = column(header, label)
                        cell = cells[ci] if 0 <= ci < len(cells) else ""
                        if cell in ("", "-", "—"):
                            findings.append({"line": n, "check": "measurement_rule",
                                             "text": f"{label}: {line.strip()[:140]}"})
                elif section == ready:
                    di = column(header, args.done_column)
                    cell = cells[di] if 0 <= di < len(cells) else ""
                    if low(cell) not in done_words:
                        findings.append({"line": n, "check": "readiness_done", "text": line.strip()[:160]})
        if section != srcs:
            for tok in CITATION.findall(line):
                if low(tok) in ("", "x", "...", "…") or GOOD_CITATION.match(tok.strip()):
                    continue
                findings.append({"line": n, "check": "bad_citation", "text": f"[{tok}]"[:160]})
        if (section not in free and section and line.lstrip().startswith(("-", "*", "|"))
                and FIGURE.search(line) and not CITED.search(line) and assumed not in l):
            findings.append({"line": n, "check": "uncited_figure", "text": line.strip()[:160]})
    if not status_ok:
        findings.append({"line": 0, "check": "status", "text": f"no Status line with one of {statuses}"})
    for h in required:
        if low(h) not in headings:
            findings.append({"line": 0, "check": "missing_section", "text": f"## {h}"})
    if capacity is None:
        findings.append({"line": 0, "check": "no_capacity",
                         "text": f"no number after '{args.hours_label}:' in the header"})
    hours_per_week = {k: round(v, 1) for k, v in per_week.items()}
    if capacity is not None:
        for week, total in sorted(hours_per_week.items()):
            if total > capacity:
                findings.append({"line": 0, "check": "hours_over_capacity",
                                 "text": f"week {week}: {total} hours of {capacity}"})
    report = {"file": args.file, "findings": findings, "hours_per_week": hours_per_week,
              "capacity": capacity, "ok": not findings}
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
