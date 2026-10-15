#!/usr/bin/env python3
"""The program that runs INSIDE the converter's container (providers/converter/Dockerfile copies it to /opt/converter): it
converts one document to text with adopted open tools and prints the result on its standard output as frames. It is not
imported by the host except in the tests, and it never runs on the host in production.

What it uses, all of it adopted and none of it written here: poppler's `pdftotext` for a PDF, pandoc for a Word document and
an HTML page, openpyxl for a spreadsheet, and the standard library for CSV and plain text. Each tool reads the one input file;
the container has no network, a read-only root file system, no capability, and a memory-backed /scratch, and the host copies
back only what this program prints.

  python3 -I _inner.py --type <pdf|docx|xlsx|ooxml|html|csv|text> --input <file> [--work <folder>]

The frames (standard output only, nothing else is ever printed there):

  OHF1\\n
  FILE <name> <size>\\n<size bytes>          one per output: converted.md or converted.csv, and info.json
  END\\n

The host (providers/converter/container.py) parses them with fixed rules: the names, the sizes and the count are checked
there, not trusted from here. A conversion that fails prints nothing on standard output, a reason on standard error and exits
with a code that is not 0.

The converted text is cut at CAP + 1 bytes, so that the host sees it is over the cap and refuses the file; the host's cap is the
one that counts. Standard library, plus openpyxl for a spreadsheet.
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
import zipfile

CAP = 1024 * 1024                 # providers/converter/container.py CONVERTED_CAP and runtime/sources.py CONVERTED_CAP
INFO_CAP = 16 * 1024
TOOL_SECONDS = 120
ZIP_ENTRIES_MAX = 5000
ZIP_BYTES_MAX = 300 * 1024 * 1024     # the sum of the uncompressed sizes a package may declare: a zip bomb is refused before any tool reads it
TEXT_CAP = 8 * 1024 * 1024            # what a tool's text is read up to before it is cut
CSV_DELIMITERS = ",;\t|"
SCRIPTLIKE = re.compile(r"(?is)<(script|style|noscript|template)\b.*?</\1\s*>")
PAGE_BREAK = "\f"
# The tools are found on this PATH. In the container nothing sets CONVERTER_TOOL_PATH (no environment variable of the host passes), so
# it is always the default; a test on a machine that keeps pandoc elsewhere sets it.
ENV = {"PATH": os.environ.get("CONVERTER_TOOL_PATH") or "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8",
       "LC_ALL": "C.UTF-8"}


class Failed(Exception):
    """A conversion that cannot be made; the message goes to standard error."""


def run_tool(argv, timeout=TOOL_SECONDS):
    """One adopted tool, started with a short environment and no input; its standard output is returned as bytes (cut at
    TEXT_CAP), its failure raised as Failed with the tail of its standard error."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, env=ENV, check=False)
    except FileNotFoundError:
        raise Failed(f"{argv[0]} is not in the image") from None
    except subprocess.TimeoutExpired:
        raise Failed(f"{argv[0]} ran over {timeout} s") from None
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [f"exit {done.returncode}"]
        raise Failed(f"{os.path.basename(argv[0])} failed: {tail[0][:300]}")
    return done.stdout[:TEXT_CAP]


def version_of(argv, pick=0):
    try:
        done = subprocess.run(argv, capture_output=True, timeout=30, env=ENV, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (done.stdout + done.stderr).decode("utf-8", "replace").strip().splitlines()
    return text[pick].strip()[:120] if len(text) > pick else None


def utf8(data: bytes) -> str:
    """Text from bytes: UTF-8 (a BOM dropped), else Windows-1252 as a spreadsheet tool writes it; NUL characters out."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")
    return text.replace("\x00", "")


def check_package(path: str) -> list:
    """The names in an Office package, refusing a zip bomb (too many entries, or a declared size that is too large)."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > ZIP_ENTRIES_MAX:
                raise Failed(f"the package holds {len(infos)} entries")
            if sum(i.file_size for i in infos) > ZIP_BYTES_MAX:
                raise Failed("the package declares too much data")
            return [i.filename for i in infos]
    except zipfile.BadZipFile:
        raise Failed("the file is not a valid Office package") from None


def ooxml_kind(path: str) -> str:
    """docx or xlsx, from the package's [Content_Types].xml (read in the container, never on the host)."""
    names = check_package(path)
    if "[Content_Types].xml" not in names:
        raise Failed("the package has no [Content_Types].xml")
    with zipfile.ZipFile(path) as z:
        types = z.read("[Content_Types].xml")[:200000].decode("utf-8", "replace")
    if "wordprocessingml" in types:
        return "docx"
    if "spreadsheetml" in types:
        return "xlsx"
    raise Failed("the package is neither a Word document nor a spreadsheet")


def convert_pdf(path: str, work: str):
    raw = run_tool(["pdftotext", "-enc", "UTF-8", "-eol", "unix", path, "-"])
    text = utf8(raw)
    pages = text.split(PAGE_BREAK)
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    out = []
    for n, page in enumerate(pages, 1):
        out.append(f"[page {n}]\n\n{page.strip()}")
    notes = []
    if not any(p.strip() for p in pages):
        notes.append("no text layer: the PDF may be scans of pages (no OCR is made)")
    return "converted.md", "\n\n".join(out).strip() + "\n", {"pdftotext": version_of(["pdftotext", "-v"])}, notes


def convert_docx(path: str, work: str):
    check_package(path)
    raw = run_tool(["pandoc", "--sandbox", "-f", "docx", "-t", "gfm", "--wrap=none", path])
    return "converted.md", utf8(raw).strip() + "\n", {"pandoc": version_of(["pandoc", "--version"])}, []


def convert_html(path: str, work: str):
    with open(path, "rb") as f:
        html = utf8(f.read(TEXT_CAP))
    html = SCRIPTLIKE.sub("", html)
    cleaned = os.path.join(work, "page.html")
    with open(cleaned, "w", encoding="utf-8") as f:
        f.write(html)
    raw = run_tool(["pandoc", "--sandbox", "-f", "html", "-t", "gfm", "--wrap=none", cleaned])
    return "converted.md", utf8(raw).strip() + "\n", {"pandoc": version_of(["pandoc", "--version"])}, \
        ["script, style and template elements were dropped before conversion"]


def delimiter_of(text: str) -> str:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        return ","


def write_csv(rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    size = 0
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
        size = buffer.tell()
        if size > CAP:
            break
    return buffer.getvalue()


def convert_csv(path: str, work: str):
    with open(path, "rb") as f:
        text = utf8(f.read(TEXT_CAP))
    delimiter = delimiter_of(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    notes = [] if delimiter == "," else [f"the delimiter {delimiter!r} was changed to a comma"]
    return "converted.csv", write_csv(rows), {}, notes


def convert_text(path: str, work: str):
    with open(path, "rb") as f:
        text = utf8(f.read(TEXT_CAP))
    return "converted.md", text.strip() + "\n", {}, []


def cell(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value if isinstance(value, str) else str(value)


def convert_xlsx(path: str, work: str):
    check_package(path)
    try:
        import openpyxl
    except ImportError:
        raise Failed("openpyxl is not in the image") from None
    named = os.path.join(work, "book.xlsx")   # openpyxl refuses a file whose name does not end in .xlsx (the input is mounted as /in/input)
    os.makedirs(work, mode=0o700, exist_ok=True)
    if not os.path.lexists(named):
        os.symlink(path, named)
    try:
        book = openpyxl.load_workbook(named, read_only=True, data_only=True)
    except Exception as e:  # openpyxl raises its own and zipfile's errors for a file it cannot read
        raise Failed(f"the workbook cannot be read: {type(e).__name__}") from None
    notes, sheets = [], []
    for sheet in book.worksheets:
        if getattr(sheet, "sheet_state", "visible") != "visible":
            notes.append(f"the hidden sheet {sheet.title!r} was not read")
            continue
        rows, empty = [], 0
        for row in sheet.iter_rows(values_only=True):
            values = [cell(v) for v in row]
            if not any(str(v).strip() for v in values):
                empty += 1
                if empty > 1000:
                    break
                continue
            empty = 0
            rows.append(values)
            if len(rows) > 200000:
                notes.append(f"the sheet {sheet.title!r} was cut at 200000 rows")
                break
        width = max((max((i + 1 for i, v in enumerate(r) if str(v).strip()), default=0) for r in rows), default=0)
        sheets.append((sheet.title, [r[:width] for r in rows]))
    book.close()
    tools = {"openpyxl": getattr(openpyxl, "__version__", None)}
    if not sheets:
        raise Failed("the workbook holds no visible sheet with data")
    if len(sheets) == 1:
        return "converted.csv", write_csv(sheets[0][1]), tools, notes + [f"one sheet: {sheets[0][0]!r}"]
    parts = []
    for title, rows in sheets:
        parts.append(f"## Sheet: {title}\n\n```csv\n{write_csv(rows).rstrip()}\n```")
    return "converted.md", "\n\n".join(parts) + "\n", tools, notes


def convert(kind: str, path: str, work: str):
    if kind == "ooxml":
        kind = ooxml_kind(path)
    table = {"pdf": convert_pdf, "docx": convert_docx, "xlsx": convert_xlsx, "html": convert_html, "csv": convert_csv,
             "text": convert_text}
    if kind not in table:
        raise Failed(f"the type {kind!r} is not converted")
    name, text, tools, notes = table[kind](path, work)
    data = text.encode("utf-8")
    cut = len(data) > CAP
    return kind, name, data[:CAP + 1], {k: v for k, v in tools.items() if v}, notes + (["the text was cut at the cap"] if cut else [])


def frames(files) -> bytes:
    out = [b"OHF1\n"]
    for name, data in files:
        out.append(f"FILE {name} {len(data)}\n".encode("ascii") + data)
    out.append(b"END\n")
    return b"".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--work", default="/scratch/work")
    args = parser.parse_args(argv)
    os.makedirs(args.work, mode=0o700, exist_ok=True)
    try:
        kind, name, data, tools, notes = convert(args.type, args.input, args.work)
    except Failed as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"error: {type(e).__name__}: {e.strerror}", file=sys.stderr)
        return 1
    info = json.dumps({"converter": "document", "kind": kind, "tool_versions": tools, "notes": notes}, sort_keys=True).encode("utf-8")
    sys.stdout.buffer.write(frames([(name, data), ("info.json", info[:INFO_CAP])]))
    sys.stdout.buffer.flush()
    shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
