#!/usr/bin/env python3
"""Lint a business-model or pricing artifact for the mistakes models repeat.

Usage:
  python3 lint_model.py --file docs/business/business-model.md --kind model
  python3 lint_model.py --file docs/business/pricing.md --kind pricing
  common: [--status-words hypothesis,validated,limited] [--sources-heading Sources]
          [--free-headings Method,Assumptions,Unknowns]
          [--hypothetical "would you,will you,if we,if you had,would it,interested in"]
  headings (translate them for an artifact not in English): [--free-heading "What stays free"]
          [--revenue-heading "Revenue model"] [--costs-heading Costs] [--economics-heading "Unit economics"]
          [--path-heading "Path to the goal"] [--assumptions-heading Assumptions] [--method-heading Method]
          [--anchors-heading Anchors] [--proposed-heading "Proposed price"] [--test-heading "Price test"]
  labels: [--price-column price] [--source-column source] [--per-words "per,/"]
          [--not-found-label "price not found"] [--origin-words "user,state file,assumed,unknown"]
          [--decision-label Decision] [--ready-label Ready] [--decided-word decided] [--no-word no]
          [--validated-label "validated if"] [--rejected-label "rejected if"] [--assumed-label "Assumption:"]

Checks, each reported with the line number:
  status: no "Status:" line containing one of --status-words (both kinds).
  missing_section: a required "## heading" is absent. Kind model: What stays free, Revenue model, Costs,
    Unit economics, Path to the goal, Assumptions, Sources, Method. Kind pricing: Anchors, Proposed price,
    Price test, Assumptions, Sources.
  cost_without_origin: a row of the Costs table whose last column is empty, "-", or holds no source
    number, command label (M1), or one of --origin-words (kind model).
  unit_economics_not_scripted: the Unit economics section has no Markdown table, or no M<n> label
    (kind model).
  anchor_cell: a row of the Anchors table whose price cell has neither a currency mark with a digit and a
    --per-words unit, nor the --not-found-label (kind pricing).
  anchor_without_source: an Anchors row with an empty source cell (kind pricing).
  decision: no "Decision:" line; or one with neither OPEN-<n> nor the --decided-word; or an OPEN-<n>
    decision with no "Ready:" line or one that is not "no" (kind pricing).
  hypothetical_question: a line of the Price test section that asks a hypothetical buying question
    (kind pricing).
  missing_criteria: the Price test section has no "validated if" line or no "rejected if" line
    (kind pricing).
  bad_citation: a bracketed citation that is not one source number ([3], [2b]) or command label (M1).
  uncited_figure: a bullet or table row with a percentage or a currency amount and no source number,
    command label or assumption label, outside the sources section, the Costs table (it has its own
    check), the Price test section of a pricing file (its figures are criteria the user sets) and
    --free-headings.
Headings are matched by their text after "## ", case-insensitive. Prints JSON to stdout; exit 1 when
anything is reported, 2 on a bad argument or unreadable file.
"""
import argparse
import json
import re
import sys

CURRENCY = re.compile(
    r"(?:[€$£]|R\$|US\$|\b(?:EUR|USD|BRL|GBP)\b)\s?\d|\d[\d.,]*\s?(?:[€£]|\b(?:EUR|USD|BRL|GBP)\b)")
ANY_CODE = re.compile(r"\b[A-Z]{3}\b\s?\d|\d[\d.,]*\s?\b[A-Z]{3}\b")
FIGURE = re.compile(r"\d+(?:[.,]\d+)?\s?%|" + CURRENCY.pattern)
CITATION = re.compile(r"\[([^\]\n]+)\](?!\()")
GOOD_CITATION = re.compile(r"^(\d+[a-z]?|M\d+)$")
CITED = re.compile(r"\[(\d+[a-z]?|M\d+)\]|\bM\d+\b|assumption:|\bassumed\b", re.I)
ORIGIN_NUMBER = re.compile(r"(?:^|[\s,;(\[])(?:\d+[a-z]?|M\d+)(?=$|[\s,;)\]])")
OPEN_MARK = re.compile(r"OPEN-\d+", re.I)


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(cells):
    return set("".join(cells)) <= set("-: ")


def words(text):
    return [w.strip().lower() for w in text.split(",") if w.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--kind", choices=["model", "pricing"], required=True)
    ap.add_argument("--status-words", default="hypothesis,validated,limited")
    ap.add_argument("--sources-heading", default="Sources")
    ap.add_argument("--free-headings", default="Method,Assumptions,Unknowns")
    ap.add_argument("--hypothetical", default="would you,will you,if we,if you had,would it,interested in")
    ap.add_argument("--free-heading", default="What stays free")
    ap.add_argument("--revenue-heading", default="Revenue model")
    ap.add_argument("--costs-heading", default="Costs")
    ap.add_argument("--economics-heading", default="Unit economics")
    ap.add_argument("--path-heading", default="Path to the goal")
    ap.add_argument("--assumptions-heading", default="Assumptions")
    ap.add_argument("--method-heading", default="Method")
    ap.add_argument("--anchors-heading", default="Anchors")
    ap.add_argument("--proposed-heading", default="Proposed price")
    ap.add_argument("--test-heading", default="Price test")
    ap.add_argument("--price-column", default="price")
    ap.add_argument("--source-column", default="source")
    ap.add_argument("--per-words", default="per,/")
    ap.add_argument("--not-found-label", default="price not found")
    ap.add_argument("--origin-words", default="user,state file,assumed,unknown")
    ap.add_argument("--decision-label", default="Decision")
    ap.add_argument("--ready-label", default="Ready")
    ap.add_argument("--decided-word", default="decided")
    ap.add_argument("--no-word", default="no")
    ap.add_argument("--validated-label", default="validated if")
    ap.add_argument("--rejected-label", default="rejected if")
    ap.add_argument("--assumed-label", default="Assumption:")
    args = ap.parse_args()
    try:
        with open(args.file, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        print(f"lint_model.py: cannot read {args.file}: {exc}", file=sys.stderr)
        sys.exit(2)
    low = lambda t: t.strip().lower()
    h = {k: low(getattr(args, k + "_heading")) for k in
         ("free", "revenue", "costs", "economics", "path", "assumptions", "method", "anchors", "proposed",
          "test", "sources")}
    if args.kind == "model":
        required = [("free", args.free_heading), ("revenue", args.revenue_heading), ("costs", args.costs_heading),
                    ("economics", args.economics_heading), ("path", args.path_heading),
                    ("assumptions", args.assumptions_heading), ("sources", args.sources_heading),
                    ("method", args.method_heading)]
    else:
        required = [("anchors", args.anchors_heading), ("proposed", args.proposed_heading),
                    ("test", args.test_heading), ("assumptions", args.assumptions_heading),
                    ("sources", args.sources_heading)]
    free = {low(x) for x in args.free_headings.split(",") if x.strip()} | {h["sources"]}
    if args.kind == "pricing":
        free.add(h["test"])
    else:
        free.add(h["costs"])
    hypos = words(args.hypothetical)
    statuses = words(args.status_words)
    origin_words = words(args.origin_words)
    per_words = words(args.per_words)
    not_found = low(args.not_found_label)
    assumed = low(args.assumed_label)
    decision_label, ready_label = low(args.decision_label), low(args.ready_label)
    findings, sections_seen = [], set()
    section, header, price_col, source_col = "", None, None, None
    status_ok, has_ok, has_no = False, False, False
    decision_line, decision_text, ready_value = 0, None, None
    in_economics_table, economics_label, economics_line = False, False, 0
    for n, line in enumerate(lines, 1):
        l = low(line)
        if re.search(r"status\s*:", l) and any(w in l for w in statuses):
            status_ok = True
        stripped = re.sub(r"^[-*]\s*", "", l)
        if stripped.startswith(decision_label + ":") or stripped.startswith(decision_label + " :"):
            if decision_text is None:
                decision_line, decision_text = n, line.strip()
        if stripped.startswith(ready_label + ":") or stripped.startswith(ready_label + " :"):
            if ready_value is None:
                ready_value = stripped.split(":", 1)[1].strip().split()[0] if stripped.split(":", 1)[1].strip() else ""
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            section, header, price_col, source_col = low(m.group(1)), None, None, None
            sections_seen.add(section)
            if section == h["economics"]:
                economics_line = n
            continue
        if args.kind == "pricing" and section == h["test"]:
            has_ok = has_ok or low(args.validated_label) in l
            has_no = has_no or low(args.rejected_label) in l
            if any(w in l for w in hypos):
                findings.append({"line": n, "check": "hypothetical_question", "text": line.strip()[:160]})
        if args.kind == "model" and section == h["economics"]:
            if line.lstrip().startswith("|"):
                in_economics_table = True
            if re.search(r"\bM\d+\b", line):
                economics_label = True
        if line.lstrip().startswith("|") and section:
            cells = split_row(line)
            if is_separator(cells):
                pass
            elif header is None:
                header = cells
                if section == h["anchors"] and args.kind == "pricing":
                    hp = [i for i, c in enumerate(cells) if low(args.price_column) in c.lower()]
                    hs = [i for i, c in enumerate(cells) if low(args.source_column) in c.lower()]
                    price_col = hp[0] if hp else None
                    source_col = hs[0] if hs else None
            else:
                if args.kind == "model" and section == h["costs"]:
                    origin = cells[-1] if cells else ""
                    ok = bool(origin) and origin not in ("-", "—") and (
                        ORIGIN_NUMBER.search(origin) or CITED.search(origin)
                        or any(w in origin.lower() for w in origin_words))
                    if not ok:
                        findings.append({"line": n, "check": "cost_without_origin", "text": line.strip()[:160]})
                if args.kind == "pricing" and section == h["anchors"]:
                    if price_col is not None and price_col < len(cells):
                        cell = cells[price_col].lower()
                        good = not_found in cell or (
                            (CURRENCY.search(cells[price_col]) or ANY_CODE.search(cells[price_col]))
                            and any(w in cell for w in per_words))
                        if not good:
                            findings.append({"line": n, "check": "anchor_cell", "text": line.strip()[:160]})
                    if source_col is not None and source_col < len(cells) and cells[source_col] in ("", "-", "—"):
                        findings.append({"line": n, "check": "anchor_without_source", "text": line.strip()[:160]})
        if section != h["sources"]:
            for tok in CITATION.findall(line):
                if low(tok) in ("", "x", "...", "…") or GOOD_CITATION.match(tok.strip()):
                    continue
                findings.append({"line": n, "check": "bad_citation", "text": f"[{tok}]"[:160]})
        if (section not in free and section and line.lstrip().startswith(("-", "*", "|"))
                and FIGURE.search(line) and not CITED.search(line) and assumed not in l):
            findings.append({"line": n, "check": "uncited_figure", "text": line.strip()[:160]})
    if not status_ok:
        findings.append({"line": 0, "check": "status", "text": f"no Status line with one of {statuses}"})
    for key, text in required:
        if h[key] not in sections_seen:
            findings.append({"line": 0, "check": "missing_section", "text": f"## {text}"})
    if args.kind == "model" and h["economics"] in sections_seen and not (in_economics_table and economics_label):
        findings.append({"line": economics_line, "check": "unit_economics_not_scripted",
                         "text": "the section needs the table printed by unit_economics.py and its M<n> label"})
    if args.kind == "pricing":
        if h["test"] in sections_seen and not (has_ok and has_no):
            findings.append({"line": 0, "check": "missing_criteria",
                             "text": f"'## {args.test_heading}' with '{args.validated_label}' and "
                                     f"'{args.rejected_label}' lines"})
        if decision_text is None:
            findings.append({"line": 0, "check": "decision", "text": f"no '{args.decision_label}:' line"})
        else:
            is_open = bool(OPEN_MARK.search(decision_text))
            if not is_open and low(args.decided_word) not in low(decision_text):
                findings.append({"line": decision_line, "check": "decision",
                                 "text": f"'{args.decision_label}:' has neither OPEN-<n> nor '{args.decided_word}'"})
            elif is_open and low(ready_value or "") != low(args.no_word):
                findings.append({"line": decision_line, "check": "decision",
                                 "text": f"an open decision needs '{args.ready_label}: {args.no_word}'"})
    report = {"file": args.file, "kind": args.kind, "findings": findings, "ok": not findings}
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
