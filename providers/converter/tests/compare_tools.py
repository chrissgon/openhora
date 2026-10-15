#!/usr/bin/env python3
"""The comparison that chose the converter's tool per format (docs/decisions.md, "MarkItDown measured against the converter's tools and not adopted").
It runs INSIDE the converter image (it needs both the adopted tools and MarkItDown), on the committed fixtures, and prints a Markdown
table on standard output. It is a measuring tool, not a test: nothing imports it and no test depends on it.

  docker run --rm --network none --read-only --tmpfs /scratch:rw,size=256m,mode=1777 --user 65534:65534 \\
      -v <repo>/providers/converter/tests:/cmp:ro <image> /opt/venv/bin/python -I /cmp/compare_tools.py [--runs 3] [--dump <folder>]

COMPARE_INNER_DIR and COMPARE_SCRATCH name where _inner.py is and a writable folder, for a run outside a container (the times are then
the machine's). The image must hold MarkItDown with the extras of the formats compared (docx, pdf, xlsx, pptx), which the production image does not (it
holds the presentation's only): build one from a scratch copy of providers/converter with `markitdown[docx,pdf,xlsx,pptx]==0.1.8` added
to requirements.in and the lock remade. The production program does not use MarkItDown (decisions.md); this script registers, one at a time, the MarkItDown converter
of each format it compares, and runs the program's own function as "current" (for a presentation, python-pptx).

For each fixture and each tool that can convert it, it measures, by script and not by eye:
  phrases sentences of the document that must come out whole (not cut by a column or a line) and in order
  noise   `(cid:n)` codes and replacement characters in the output   pages  `[page n]` lines (the PDF tool's page marks)
  lost    the words of the document (a list written below, from what the fixture was made to hold) that the output does not hold
  forbid  text that must never come out (a script's body, a hidden sheet) and did
  head    Markdown headings in the output (`#` lines)         tbl  rows of a Markdown table (`|` lines, the separator not counted)
  list    list items (`-`, `*`, `+`, `1.`, a bullet)           size  bytes of the converted text
  ms      the median wall time of a fresh process that imports the tool and converts the file (runs times)

Each conversion runs in its own process (`python -I -c`), so the time includes what the tool must load, as a real conversion does.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PY = sys.executable
REVIEW = ("Harbor Cafe Quarterly Review The group opened two new cafés this quarter and the loyalty programme grew faster than "
          "planned. Highlights Opening day sales beat the forecast Staff turnover fell to 8 percent Supplier costs stayed flat "
          "Site Revenue Visits Dock Street 48200 9100 Mill Lane 39750 7400")
STEPS = "Next steps Hire a regional trainer Open the third cafe in spring Review the loyalty rewards"
# name: (kind, words that must come out, text that must not, headings, table rows, list items, phrases that must come out whole and in
# this order). The counts are what the document holds; a tool is not asked for what the format cannot say (a PDF has no headings).
SPECS = {
    "brief.pdf": ("pdf", "Clinics want shorter forms. Prices vary by region.", [], 0, 0, 0, []),
    "review.pdf": ("pdf", REVIEW + " " + STEPS + " Sites", [], 0, 3, 6, []),
    "columns.pdf": ("pdf", "Opening and closing guide", [], 0, 0, 0, [
        "The left column opens the guide for new staff.", "who unlocks the doors, and where the cash float is counted",
        "The right column covers closing time.", "how the day's takings are sealed and signed by two people",
        "A second page repeats the contacts", "printed on the back of the staff card."]),
    "notes.docx": ("docx", "Interview notes The first clinic asked for shorter forms Prices apple 1.2 pear 3.1", [], 2, 0, 2, []),
    "review.docx": ("docx", REVIEW + " " + STEPS + " Sites", [], 4, 3, 6, []),
    "rich.docx": ("docx", "Supplier handbook Orders go to Quay Beans Ltd before noon. Delivery rules Use the side door Ring twice "
                          "after nine Sign the delivery note Item Unit Beans kilo Milk litre", ["hidden docx text"], 2, 3, 3,
                  ["Orders go to Quay Beans Ltd before noon."]),
    "page.html": ("html", "Fruit market Apples sell best in autumn. fruit price apple 1.2", ["hidden script text", "alert"], 1, 2, 0, []),
    "review.html": ("html", REVIEW + " " + STEPS + " Sites the loyalty page", ["hidden script text", "alert"], 4, 3, 6, []),
    "rich.html": ("html", "Kitchen guide Rinse the beans & dry them. Use mode=fast only for small batches. Prepare Wash Dry Roast "
                          "Taste before you serve. step 1 step 2 full guide",
                  ["hidden script text", "comment text", "noscript text", "template text", "color:blue"], 1, 0, 4,
                  ["Rinse the beans & dry them.", "Taste before you serve."]),
    "answers.xlsx": ("xlsx", "clinic forms per day North clinic 12 South clinic 30", [], 0, 0, 0, []),
    "survey.xlsx": ("xlsx", "item price qty apple 1.2 10 pear 3.1 4 total item cost apple 0.5 pear 1.5",
                    ["hidden sheet text", "Internal", "NaN"], 0, 0, 0, []),
    "review.xlsx": ("xlsx", "Site Revenue Visits Dock Street 48200 9100 Mill Lane 39750 7400 Total 87950 16500 Highlights "
                            "Opening day sales beat the forecast Staff turnover fell to 8 percent Supplier costs stayed flat", [], 0, 0, 0, []),
    "rich.pptx": ("pptx", "Opening checklist Unlock the doors Disarm the alarm Count the cash float Call the manager if the float is short "
                          "Suppliers Name Terms Quay Beans net 30 invoice by mail A slide with no title", ["Draft pricing"], 3, 2, 3, []),
    "review.pptx": ("pptx", "Harbor Cafe Quarterly Review Fictional deck for the converter's tests Highlights Opening day sales beat "
                            "the forecast Staff turnover fell to 8 percent Supplier costs stayed flat Sites Site Revenue Visits Dock "
                            "Street 48200 9100 Mill Lane 39750 7400 Speaker note: thank the Dock Street team.", [], 3, 3, 3, []),
}
CHILD = r"""
import json, sys, time
import os
sys.path.insert(0, os.environ.get("COMPARE_INNER_DIR", "/opt/converter"))
kind, path, tool = sys.argv[1:4]
start = time.perf_counter()
import _inner
if tool == "markitdown":
    # every candidate converter, one registered at a time (the production program does not use MarkItDown); local stream API,
    # built-ins and plugins off
    import markitdown
    from markitdown import MarkItDown, StreamInfo, converters
    wanted = {"docx": "DocxConverter", "pptx": "PptxConverter", "xlsx": "XlsxConverter", "pdf": "PdfConverter", "html": "HtmlConverter"}[kind]
    reader = MarkItDown(enable_builtins=False, enable_plugins=False)
    reader.register_converter(getattr(converters, wanted)())
    with open(path, "rb") as stream:
        text = reader.convert_stream(stream, stream_info=StreamInfo(extension="." + kind)).markdown
else:
    import tempfile
    name, text, tools, notes = getattr(_inner, "convert_" + kind)(path, tempfile.mkdtemp(dir=os.environ.get("COMPARE_SCRATCH", "/scratch")))
print(json.dumps({"text": text, "seconds": time.perf_counter() - start}))
"""


def words(text: str) -> list:
    return re.findall(r"[\w'&=]+(?:\.\d+)?", text.lower().replace("’", "'").replace("\\", ""))


def flat(text: str) -> str:
    """The text with Markdown's marks, escapes and line breaks out, for finding a phrase whole."""
    return " ".join(re.sub(r"[*_`\\]", "", text.lower().replace("’", "'")).split())


def measure(text: str) -> dict:
    lines = text.splitlines()
    table = [ln for ln in lines if ln.lstrip().startswith("|") and not re.fullmatch(r"\s*\|[\s:|-]+\|\s*", ln)]
    items = [ln for ln in lines if re.match(r"\s*([-*+•]|\d+[.)])\s+\S", ln)]
    piped = [ln for ln in lines if ln.lstrip().startswith("|")]
    first = piped[0].strip("| \t") if piped else None
    return {"hdr": "-" if first is None else ("ok" if first.replace("|", "").strip().strip("-: ") else "empty"), "noise": text.count("(cid:") + text.count("\ufffd"), "pages": len(re.findall(r"^\[page \d+\]$", text, re.M)),
            "head": sum(1 for ln in lines if re.match(r"#{1,6} \S", ln)), "tbl": len(table), "list": len(items),
            "size": len(text.encode("utf-8"))}


def run_once(kind: str, path: str, tool: str):
    done = subprocess.run([PY, "-I", "-c", CHILD, kind, path, tool], capture_output=True, timeout=300, check=False)
    if done.returncode != 0:
        return None, (done.stderr.decode("utf-8", "replace").strip().splitlines() or ["failed"])[-1][:100]
    return json.loads(done.stdout.decode("utf-8")), None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", help="only the fixtures whose name ends with this (for example .pptx)")
    parser.add_argument("--dump", help="a folder to write each converted text to (for reading)")
    args = parser.parse_args()
    os.makedirs(os.environ.get("COMPARE_SCRATCH", "/scratch"), exist_ok=True)
    print("| fixture | tool | lost words | phrases whole | forbidden | headings | table rows | table header | list items | noise | page marks | bytes | ms |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, (kind, expected, forbid, heads, rows, items, phrases) in sorted(SPECS.items()):
        if args.only and not name.endswith(args.only):
            continue
        path = os.path.join(FIXTURES, name)
        for tool in ("current", "markitdown"):
            results, error = [], None
            for _ in range(args.runs):
                got, error = run_once(kind, path, tool)
                if got is None:
                    break
                results.append(got)
            label = "current" if tool == "current" else "markitdown"
            if not results:
                print(f"| {name} | {label} | failed: {error} | | | | | | | | | | |")
                continue
            text = results[0]["text"]
            if args.dump:
                with open(os.path.join(args.dump, f"{name}.{tool}.md"), "w", encoding="utf-8") as f:
                    f.write(text)
            have = set(words(text))
            lost = sorted({w for w in words(expected) if w not in have})
            bad = [f for f in forbid if f.lower() in text.lower()]
            whole = sum(1 for ph in phrases if flat(ph) in flat(text))
            m = measure(text)
            ms = int(statistics.median(r["seconds"] for r in results) * 1000)
            print(f"| {name} | {label} | {len(lost)}{' ' + str(lost[:4]) if lost else ''} | {whole}/{len(phrases)} | {bad or 0} | "
                  f"{m['head']}/{heads} | {m['tbl']}/{rows} | {m['hdr']} | {m['list']}/{items} | {m['noise']} | {m['pages']} | {m['size']} | {ms} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
