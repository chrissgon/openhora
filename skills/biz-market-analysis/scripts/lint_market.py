#!/usr/bin/env python3
"""Lint a market analysis for the mistakes models repeat: prices under Implications, price cells
that hold no price, and citations that are not source numbers.

Usage:
  python3 lint_market.py --file docs/business/market.md
         [--implications-heading "Implications for the next decisions"]
         [--alternatives-heading "Alternatives and competitors per offer"]
         [--price-column price] [--not-found-label "price not found"] [--sources-heading Sources]
         [--quote-free-headings "Method,Assumptions"]

Checks, each reported with the line number:
  implications_currency: a currency amount (a currency sign or code next to a number) in the
    implications section. Implications ask the next skill a question; they propose no price.
  price_cell: a cell of the price column, in any table under the alternatives heading, that holds
    no currency amount, does not start with 0 (free, doing nothing) and is not the not-found label.
  bad_citation: a bracketed citation outside the sources section that is not one source number
    ([3], [2b]) or one command label (M1): lists such as [2,3] or [8-13] and names such as [Acme] are
    reported; Markdown links [text](url), checkboxes and [...] in quotes are ignored.
  implications_not_question: a bullet under Implications with no question mark. Each bullet is
    the question the next skill must answer, not an answer.
  uncited_figure: a bullet or table row with a percentage or a currency amount and no source number,
    command label or assumption label, outside the sources section and the --free-headings.
  figure_not_in_quote: a bullet or table row, outside the sources section and the --quote-free-headings,
    that cites sources ([3], [2b]) and holds a percentage or a currency amount whose number is in none of
    the quotes of those sources (a quote is the text of the source entry from its first quote mark; 4,100,
    4.100 and 4 100 are the same number, so are 15 and 15,00). Skipped: a line with a command label,
    an assumption label, no source number, or a cited source with no entry or no quote.
Headings are matched by their text after "## " (the alternatives heading also matches "### "
subsections below it), case-insensitive; pass the translated text for an artifact not in English.
The price column is the first header cell that contains --price-column, case-insensitive.
Prints JSON to stdout; exit 1 when anything is reported, 2 on a bad argument or unreadable file.
"""
import argparse
import json
import re
import sys

CURRENCY = re.compile(
    r"(?:[€$£]|R\$|US\$|\b(?:EUR|USD|BRL|GBP)\b)\s?\d|\d[\d.,]*\s?(?:[€£]|\b(?:EUR|USD|BRL|GBP)\b)")
CITATION = re.compile(r"\[([^\]\n]+)\](?!\()")
GOOD_CITATION = re.compile(r"^(\d+[a-z]?|M\d+)$")
CUR_NUM = re.compile(
    r"(?:[€$£]|R\$|US\$|\b(?:EUR|USD|BRL|GBP)\b)\s?(\d[\d.,]*)|(\d[\d.,]*)\s?(?:[€£]|\b(?:EUR|USD|BRL|GBP)\b)")
PCT_NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")
SRC_REF = re.compile(r"\[(\d+[a-z]?)\]")
SRC_ENTRY = re.compile(r"^\s*\[(\d+[a-z]?)\]")
NUM_TOKEN = re.compile(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d(?:[\d.,]*\d)?")
SKIP_QUOTE = re.compile(r"\[M\d+\]|\bM\d+\b|\(assumed\)", re.I)
FIGURE = re.compile(r"\d+(?:[.,]\d+)?\s?%|" + CURRENCY.pattern)
CITED = re.compile(r"\[(\d+[a-z]?|M\d+)\]|\bM\d+\b|assumption:|\(assumed\)|\bassumed\b", re.I)


def num_key(tok):
    tok = tok.strip().rstrip(".,")
    tok = re.sub(r"[.,]0{1,2}$", "", tok)
    return re.sub(r"\D", "", tok)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--implications-heading", default="Implications for the next decisions")
    ap.add_argument("--alternatives-heading", default="Alternatives and competitors per offer")
    ap.add_argument("--price-column", default="price")
    ap.add_argument("--not-found-label", default="price not found")
    ap.add_argument("--sources-heading", default="Sources")
    ap.add_argument("--free-headings", default="Method,Assumptions,Unknowns,Contradictions",
                    help="comma-separated sections exempt from uncited_figure (translate for other languages)")
    ap.add_argument("--assumed-label", default="Assumption:",
                    help="label that marks an assumption in the artifact's language")
    ap.add_argument("--quote-free-headings", default="Method,Assumptions",
                    help="comma-separated sections exempt from figure_not_in_quote (translate for other languages)")
    args = ap.parse_args()
    try:
        with open(args.file, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        print(f"lint_market.py: cannot read {args.file}: {exc}", file=sys.stderr)
        sys.exit(2)
    impl, alts, srcs = (h.strip().lower() for h in
                        (args.implications_heading, args.alternatives_heading, args.sources_heading))
    free = {h.strip().lower() for h in args.free_headings.split(",") if h.strip()} | {srcs}
    qfree = {h.strip().lower() for h in args.quote_free_headings.split(",") if h.strip()} | {srcs}
    quotes, sec = {}, ""
    for line in lines:
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            sec = m.group(1).strip().lower()
        elif sec == srcs and SRC_ENTRY.match(line):
            q = re.search(r"[\"\u201c](.*)$", line)
            quotes[SRC_ENTRY.match(line).group(1)] = (
                {num_key(t) for t in NUM_TOKEN.findall(q.group(1))} if q else None)
    assumed = args.assumed_label.strip().lower()
    findings, section, price_col = [], "", None
    seen = {impl: False, alts: False}
    for n, line in enumerate(lines, 1):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            section, price_col = m.group(1).strip().lower(), None
            if section in seen:
                seen[section] = True
            continue
        if re.match(r"^###\s", line):
            price_col = None
        if section == impl and CURRENCY.search(line):
            findings.append({"line": n, "check": "implications_currency", "text": line.strip()[:160]})
        if section == impl and line.lstrip().startswith(("-", "*")) and "?" not in line:
            findings.append({"line": n, "check": "implications_not_question", "text": line.strip()[:160]})
        if (section not in free and section and line.lstrip().startswith(("-", "*", "|"))
                and FIGURE.search(line) and not CITED.search(line) and assumed not in line.lower()):
            findings.append({"line": n, "check": "uncited_figure", "text": line.strip()[:160]})
        if (section and section not in qfree and line.lstrip().startswith(("-", "*", "|"))
                and not SKIP_QUOTE.search(line) and assumed not in line.lower()):
            refs = SRC_REF.findall(line)
            if refs and all(quotes.get(r) for r in refs):
                pool = set().union(*(quotes[r] for r in refs))
                figs = [a or b for a, b in CUR_NUM.findall(line)] + PCT_NUM.findall(line)
                miss = [f.strip().rstrip(".,") for f in figs if num_key(f).strip("0") and num_key(f) not in pool]
                if miss:
                    findings.append({"line": n, "check": "figure_not_in_quote",
                                     "text": f"{', '.join(miss)} not in the quote of {', '.join(sorted(set(refs)))}: "
                                             f"{line.strip()[:120]}"})
        if section == alts and line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if price_col is None:
                hits = [i for i, c in enumerate(cells) if args.price_column.lower() in c.lower()]
                price_col = hits[0] if hits else -1
            elif price_col >= 0 and not set("".join(cells)) <= set("-: ") and price_col < len(cells):
                cell = cells[price_col]
                if not (CURRENCY.search(cell) or re.match(r"0([.,]0+)?(\s|$|\()", cell)
                        or args.not_found_label.lower() in cell.lower()):
                    findings.append({"line": n, "check": "price_cell", "text": cell[:160]})
        if section != srcs:
            for tok in CITATION.findall(line):
                if tok.strip().lower() in ("", "x", "...", "\u2026") or GOOD_CITATION.match(tok.strip()):
                    continue
                hint = " (write one reference per bracket: [2][3])" if re.fullmatch(r"[\d\s,;\u2013-]+[a-z]?", tok) else ""
                findings.append({"line": n, "check": "bad_citation", "text": f"[{tok}]"[:160] + hint})
    missing = [h for h, found in seen.items() if not found]
    report = {"file": args.file, "missing_headings": missing, "findings": findings,
              "ok": not findings and not missing}
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
