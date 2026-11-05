#!/usr/bin/env python3
"""The program that runs INSIDE the renderer's container (providers/exporter/Dockerfile copies it to /opt/render): it
makes one file, CSV, XLSX, DOCX or PDF, from one text, a CSV for the first two and Markdown for the others, with adopted open tools
and no model, and prints it on its standard output as frames. The host never imports it except in the tests, and it never runs on
the host in production.

What it uses, all of it adopted: the standard library's csv for a CSV file, openpyxl for a workbook, pandoc for a Word document and
for the HTML that WeasyPrint prints as a PDF. The only code of its own is the guard of S9 below, the cleaning of the document before
a writer reads it, and the few lines that join the tools.

  python3 -I _render.py --format <csv|xlsx|docx|pdf> --input <file> [--work <folder>]

The frames (standard output only, nothing else is ever printed there):

  OHF1\\n
  FILE <name> <size>\\n<size bytes>          output.<csv|xlsx|docx|pdf>, then info.json
  END\\n

The host (providers/exporter/container.py) parses them with fixed rules. A render that fails prints nothing on standard output, a
reason on standard error and exits with a code that is not 0.

The formula guard (finding S9). A spreadsheet runs a cell as a formula when its text starts with a character of FORMULA_STARTS, and
a formula can read other cells, call a program or send data out. So a cell whose text starts with one of them, after any leading
spaces, no-break spaces, zero-width characters and byte order marks, is written as text:
  - in a CSV file, with a single quote in front of it (the usual guidance: the quote is part of the cell's text, as the file has no
    cell types), and in front of every segment of a cell that follows a `;`, a bar or a tab inside it, because a spreadsheet in a
    locale that separates cells with `;` (pt-BR, de, fr) splits there; every cell is quoted;
  - in a workbook, as a text cell (a string, never a formula), with the quote-prefix style that keeps Excel from turning it into a
    formula when the person edits it. Its text is not changed.
A cell that starts with none of them is written as it is, except that in a workbook a plain unsigned number (digits and one decimal
point, no leading zero) is stored as a number. A signed number such as -5 is text on purpose: the guard does not tell it from -5+cmd.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys

CAP_INPUT = 1024 * 1024
CAP_OUTPUT = 8 * 1024 * 1024
INFO_CAP = 16 * 1024
TOOL_SECONDS = 120
ROWS_MAX, COLUMNS_MAX, CELL_MAX = 200000, 1000, 32767     # a workbook's own limits are 1,048,576 rows, 16,384 columns, 32,767 characters
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")   # = + - @ TAB CR LF and the fullwidth = + - @
SKIPPED = " \u00a0\u3000\u200b\u200c\u200d\u2060\ufeff"        # a space, a no-break space, an ideographic space, zero-width characters, a byte order mark
NUMBER = re.compile(r"(0|[1-9][0-9]{0,14})(\.[0-9]{1,6})?")     # no sign, no leading zero (an identifier), at most 15 digits (a double keeps them)
LIB = "/opt/render/lib"      # WeasyPrint and what it needs, installed from requirements.lock (see the Dockerfile)
ENV = {"PATH": os.environ.get("RENDER_TOOL_PATH") or "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
STYLE = """
@page { size: A4; margin: 22mm 20mm }
body { font-family: "DejaVu Serif", serif; font-size: 10.5pt; line-height: 1.45; color: #111 }
h1, h2, h3, h4 { font-family: "DejaVu Sans", sans-serif; line-height: 1.2; margin: 1.2em 0 0.4em }
h1 { font-size: 20pt } h2 { font-size: 15pt } h3 { font-size: 12.5pt }
table { border-collapse: collapse; margin: 0.8em 0; width: 100% }
th, td { border: 0.5pt solid #777; padding: 3pt 5pt; text-align: left; vertical-align: top }
th { background: #eee; font-family: "DejaVu Sans", sans-serif }
pre, code { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt }
pre { background: #f4f4f4; padding: 6pt; white-space: pre-wrap; word-wrap: break-word }
blockquote { border-left: 2pt solid #999; margin-left: 0; padding-left: 10pt; color: #333 }
"""


class Failed(Exception):
    """A render that cannot be made; the message goes to standard error."""


def guarded(text: str) -> bool:
    """Whether a cell's text would be run as a formula: its first character, after the skipped ones, is in FORMULA_STARTS."""
    stripped = text.lstrip(SKIPPED)
    return bool(stripped) and stripped[0] in FORMULA_STARTS


CELL_SPLIT = re.compile(r"([;|\t])")


def csv_cell(value) -> str:
    """The text of a cell as a CSV file holds it. A spreadsheet in a locale that writes `;` between cells (pt-BR, de, fr) or that is
    handed a bar- or tab-separated file splits a cell at that character, so every segment of the cell is guarded on its own: a single
    quote goes in front of each one that would run as a formula (`x;=1+1` is written `x;'=1+1`)."""
    text = "" if value is None else str(value)
    parts = CELL_SPLIT.split(text)          # segments at the even places, the separators between them at the odd ones
    parts = [("'" + part if i >= 2 and i % 2 == 0 and guarded(part) else part) for i, part in enumerate(parts)]
    return ("'" if guarded(text) else "") + "".join(parts)


def utf8(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Failed("the input is not UTF-8 text") from None
    return text.replace("\x00", "")


def read_rows(text: str) -> list:
    """The rows of a CSV text: the delimiter is the commonest of a comma, a semicolon, a tab and a bar on the first line (a comma on a
    tie). At most ROWS_MAX rows and COLUMNS_MAX columns, a cell at most CELL_MAX characters: a table over a limit is refused, never cut."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t|", key=lambda d: (first.count(d), d == ","))
    rows = []
    for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
        if len(rows) >= ROWS_MAX:
            raise Failed(f"the table has more than {ROWS_MAX} rows")
        if len(row) > COLUMNS_MAX:
            raise Failed(f"a row has more than {COLUMNS_MAX} columns")
        if any(len(cell) > CELL_MAX for cell in row):
            raise Failed(f"a cell has more than {CELL_MAX} characters")
        rows.append(row)
    if not any(any(cell.strip() for cell in row) for row in rows):
        raise Failed("the table is empty")
    return rows


def render_csv(text: str, work: str):
    rows = read_rows(text)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_ALL)    # every cell quoted, and with CR LF as the row end a lone CR or LF is inside the quotes
    for row in rows:
        writer.writerow([csv_cell(cell) for cell in row])
    return "csv", ("\ufeff" + buffer.getvalue()).encode("utf-8"), {"rows": len(rows)}, {}


def render_xlsx(text: str, work: str):
    rows = read_rows(text)
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        raise Failed("openpyxl is not in the image") from None
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Data"
    for r, row in enumerate(rows, 1):
        for c, value in enumerate(row, 1):
            cell = sheet.cell(row=r, column=c)
            if guarded(value):
                cell.value = value
                cell.data_type = "s"             # text, never a formula
                cell.quotePrefix = True          # and Excel keeps it text when the person edits it
            elif NUMBER.fullmatch(value.strip()):
                cell.value = float(value) if "." in value else int(value)
            else:
                cell.value = value
                cell.data_type = "s"             # a text that merely looks like an error code or a reference is text too
            if r == 1:
                cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    os.makedirs(work, mode=0o700, exist_ok=True)
    target = os.path.join(work, "book.xlsx")
    book.save(target)
    with open(target, "rb") as f:
        data = f.read(CAP_OUTPUT + 1)
    return "xlsx", data, {"rows": len(rows)}, {"openpyxl": getattr(openpyxl, "__version__", None)}


def run_tool(argv, timeout=TOOL_SECONDS):
    """One adopted tool, started with a short environment and no input; its standard output is returned, its failure is Failed."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, env=ENV, check=False)
    except FileNotFoundError:
        raise Failed(f"{argv[0]} is not in the image") from None
    except subprocess.TimeoutExpired:
        raise Failed(f"{argv[0]} ran over {timeout} s") from None
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [f"exit {done.returncode}"]
        raise Failed(f"{os.path.basename(argv[0])} failed: {tail[0][:300]}")
    return done.stdout


def version_of(argv):
    try:
        done = subprocess.run(argv, capture_output=True, timeout=30, env=ENV, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (done.stdout + done.stderr).decode("utf-8", "replace").strip().splitlines()
    return text[0].strip()[:120] if text else None


# Markdown is read as GitHub-flavoured Markdown without raw HTML and without a metadata block, and the document that comes out of the
# reader is cleaned before any writer sees it: a picture becomes its alt text (a writer would otherwise read the file or the address
# the picture names and put it in the output), a raw fragment is dropped, and a link keeps its address only when that is http, https or
# mailto (a file:, smb: or javascript: address in a document is how a file or a login is leaked). Pandoc runs twice: the reader with
# --sandbox (no file but the input is read), then the writer on the cleaned document.
MARKDOWN = "gfm-raw_html-yaml_metadata_block"
LINK_SCHEMES = ("http://", "https://", "mailto:", "#")


def clean_one(node) -> list:
    """What a node of the document becomes, as a list of nodes: a picture its alt text, a raw fragment nothing, a link with an
    address that is not allowed its text, anything else itself with its children cleaned."""
    if not isinstance(node, dict):
        return [node]
    kind, content = node.get("t"), node.get("c")
    if kind == "Image":
        return clean(content[1])
    if kind in ("RawInline", "RawBlock"):
        return []
    if kind == "Link":
        inner = clean(content[1])
        address = content[2][0] if isinstance(content[2], list) and content[2] else ""
        if not isinstance(address, str) or not address.lower().startswith(LINK_SCHEMES):
            return inner
        return [{"t": "Link", "c": [content[0], inner, [address, ""]]}]
    return [{key: clean(value) for key, value in node.items()}]


def clean(node):
    """The document with every picture, raw fragment and unsafe link cleaned, at any depth."""
    if isinstance(node, list):
        out = []
        for item in node:
            out.extend(clean_one(item) if isinstance(item, dict) else [clean(item)])
        return out
    if isinstance(node, dict):
        return clean_one(node)[0] if clean_one(node) else {}
    return node


def markdown_document(text: str, work: str) -> str:
    """The cleaned document, as a JSON file the writers read: its path."""
    os.makedirs(work, mode=0o700, exist_ok=True)
    source = os.path.join(work, "input.md")
    with open(source, "w", encoding="utf-8") as f:
        f.write(text)
    raw = run_tool(["pandoc", "--sandbox", "-f", MARKDOWN, "-t", "json", source])
    try:
        tree = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise Failed("pandoc's document could not be read") from None
    tree["blocks"] = clean(tree.get("blocks", []))
    tree["meta"] = {}
    target = os.path.join(work, "clean.json")
    with open(target, "w", encoding="utf-8") as f:
        json.dump(tree, f)
    return target


def render_docx(text: str, work: str):
    document = markdown_document(text, work)
    target = os.path.join(work, "book.docx")
    run_tool(["pandoc", "-f", "json", "-t", "docx", "-o", target, document])
    with open(target, "rb") as f:
        data = f.read(CAP_OUTPUT + 1)
    return "docx", data, {}, {"pandoc": version_of(["pandoc", "--version"])}


def refuse_fetch(url, *args, **kwargs):
    """WeasyPrint's url_fetcher: nothing is ever fetched, from a file or the network (the container has no network either)."""
    raise ValueError("nothing is fetched while a PDF is made")


def render_pdf(text: str, work: str):
    document = markdown_document(text, work)
    fragment = run_tool(["pandoc", "-f", "json", "-t", "html5", "--wrap=none", document]).decode("utf-8", "replace")
    page = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Document</title><style>' + STYLE
            + "</style></head><body>" + fragment + "</body></html>")
    if os.path.isdir(LIB) and LIB not in sys.path:
        sys.path.insert(0, LIB)
    try:
        import weasyprint
    except ImportError:
        raise Failed("weasyprint is not in the image") from None
    try:
        data = weasyprint.HTML(string=page, url_fetcher=refuse_fetch).write_pdf()
    except Exception as e:     # WeasyPrint raises its own and fontconfig's errors
        raise Failed(f"weasyprint could not make the PDF: {type(e).__name__}") from None
    return "pdf", data, {}, {"pandoc": version_of(["pandoc", "--version"]), "weasyprint": getattr(weasyprint, "__version__", None)}


FORMATS = {"csv": render_csv, "xlsx": render_xlsx, "docx": render_docx, "pdf": render_pdf}


def render(fmt: str, data: bytes, work: str):
    """(format, output bytes, counts, tool versions). Failed on an input over the cap, not UTF-8, empty, or a tool that fails."""
    if fmt not in FORMATS:
        raise Failed(f"the format {fmt!r} is not made")
    if len(data) > CAP_INPUT:
        raise Failed(f"the input is over {CAP_INPUT} bytes")
    text = utf8(data)
    if not text.strip():
        raise Failed("the input is empty")
    name, out, counts, tools = FORMATS[fmt](text, work)
    if len(out) > CAP_OUTPUT:
        raise Failed(f"the output is over {CAP_OUTPUT} bytes")
    return name, out, counts, {k: v for k, v in tools.items() if v}


def frames(files) -> bytes:
    out = [b"OHF1\n"]
    for name, data in files:
        out.append(f"FILE {name} {len(data)}\n".encode("ascii") + data)
    out.append(b"END\n")
    return b"".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--work", default="/scratch/work")
    args = parser.parse_args(argv)
    try:
        with open(args.input, "rb") as f:
            data = f.read(CAP_INPUT + 1)
        fmt, out, counts, tools = render(args.format, data, args.work)
    except Failed as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"error: {type(e).__name__}: {e.strerror}", file=sys.stderr)
        return 1
    info = json.dumps({"renderer": "document", "format": fmt, "counts": counts, "tool_versions": tools}, sort_keys=True).encode("utf-8")
    sys.stdout.buffer.write(frames([(f"output.{fmt}", out), ("info.json", info[:INFO_CAP])]))
    sys.stdout.buffer.flush()
    shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
