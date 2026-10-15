#!/usr/bin/env python3
"""The program that runs INSIDE the converter's container (providers/converter/Dockerfile copies it to /opt/converter): it
converts one document to text with adopted open tools and prints the result on its standard output as frames. It is not
imported by the host except in the tests, and it never runs on the host in production.

What it uses, all of it adopted and none of it written here: poppler's `pdftotext` for a PDF, pandoc for a Word document and
an HTML page, openpyxl for a spreadsheet, python-pptx for a presentation (a small function here writes its slides as Markdown), and the
standard library for CSV and plain text. Each tool reads the one input file;
the container has no network, a read-only root file system, no capability, and a memory-backed /scratch, and the host copies
back only what this program prints.

  python3 -I _inner.py --type <pdf|docx|xlsx|pptx|ooxml|html|csv|text> --input <file> [--work <folder>]

The frames (standard output only, nothing else is ever printed there):

  OHF1\\n
  FILE <name> <size>\\n<size bytes>          one per output: converted.md or converted.csv, and info.json
  END\\n

The host (providers/converter/container.py) parses them with fixed rules: the names, the sizes and the count are checked
there, not trusted from here. A conversion that fails prints nothing on standard output, a reason on standard error and exits
with a code that is not 0.

The converted text is cut at CAP + 1 bytes, so that the host sees it is over the cap and refuses the file; the host's cap is the
one that counts. Standard library, plus openpyxl for a spreadsheet and python-pptx for a presentation (both in the image's virtual environment).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile

CAP = 1024 * 1024                 # providers/converter/container.py CONVERTED_CAP and runtime/sources.py CONVERTED_CAP
INFO_CAP = 16 * 1024
TOOL_SECONDS = 120
ZIP_ENTRIES_MAX = 5000
ZIP_BYTES_MAX = 300 * 1024 * 1024     # the sum of the uncompressed sizes a package may declare: a zip bomb is refused before any tool reads it
PPTX_BYTES_MAX = 150 * 1024 * 1024     # a presentation: python-pptx keeps every part in memory (the container has 1024 MiB), so its caps are lower
PPTX_XML_MAX = 24 * 1024 * 1024        # and the XML a library parses into a tree costs tens of times its size: a named error for most oversized decks
MEDIA_SUFFIXES = (".png", ".jpg", ".jpeg", ".jpe", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf", ".wdp", ".jxr", ".webp", ".heic",
                  ".mp3", ".mp4", ".m4a", ".m4v", ".wav", ".wma", ".wmv", ".avi", ".mov", ".mpg", ".mpeg", ".ogg",
                  ".xlsx", ".docx", ".pptx")   # what is not XML by its name; a part with any other name is counted as XML, whatever its name says
TEXT_CAP = 8 * 1024 * 1024            # what a tool's text is read up to before it is cut
CSV_DELIMITERS = ",;\t|"
SCRIPTLIKE = re.compile(r"(?is)<(script|style|noscript|template)\b.*?</\1\s*>")
PAGE_BREAK = "\f"
HIDDEN = ("0", "false")                  # the two spellings of a false xsd:boolean (a slide's show attribute)
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


def check_package(path: str, bytes_max: int = 0, xml_max: int = 0) -> list:
    """The names in an Office package, refusing a zip bomb (too many entries, or a declared size that is too large; `xml_max`, when
    given, also caps the declared size of every part that is not a known kind of media or an embedded package: a part is judged by what it
    could be, not by its name, because a part saved as slide2.bin can be typed XML by an Override of [Content_Types].xml)."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > ZIP_ENTRIES_MAX:
                raise Failed(f"the package holds {len(infos)} entries")
            if sum(i.file_size for i in infos) > (bytes_max or ZIP_BYTES_MAX):
                raise Failed("the package declares too much data")
            if xml_max and sum(i.file_size for i in infos if not i.filename.lower().endswith(MEDIA_SUFFIXES)) > xml_max:
                raise Failed("the package declares too much XML")
            return [i.filename for i in infos]
    except zipfile.BadZipFile:
        raise Failed("the file is not a valid Office package") from None


def ooxml_kind(path: str) -> str:
    """docx, xlsx or pptx, from the names of the package's main parts (read in the container, never on the host). The main part decides:
    a presentation with a chart holds an embedded workbook, a document may hold a spreadsheet, so no type string is searched."""
    names = set(check_package(path))
    if "[Content_Types].xml" not in names:
        raise Failed("the package has no [Content_Types].xml")
    for main, kind in (("word/document.xml", "docx"), ("ppt/presentation.xml", "pptx"), ("xl/workbook.xml", "xlsx")):
        if main in names:
            return kind
    raise Failed("the package is not a Word document, a spreadsheet or a presentation")


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
    # openpyxl refuses a file whose name does not end in .xlsx (the input is mounted as /in/input); the link has a name of its own for each
    # conversion, so that a folder shared by two conversions never hands the second the first's file
    named = os.path.join(work, f"book-{secrets.token_hex(6)}.xlsx")
    os.makedirs(work, mode=0o700, exist_ok=True)
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


def forbid_network() -> None:
    """A second wall behind the container's missing network: in this process nothing can open a connection or resolve a name, so a
    converter library that tried (a URL converter, an update check) fails here before it fails there."""
    import socket

    def refuse(*args, **kwargs):
        raise OSError("the converter makes no network connection")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse


def table_rows(table) -> list:
    """The rows of a presentation's table as lists of cell text (a line break in a cell becomes a space, a pipe is escaped)."""
    rows = []
    for row in table.rows:
        rows.append([" ".join(c.text_frame.text.split()).replace("|", "\\|") if c.text_frame is not None else "" for c in row.cells])
    return rows


def markdown_table(rows: list) -> list:
    width = max((len(r) for r in rows), default=0)
    if not width:
        return []
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines


def shape_blocks(shapes, title, out: list) -> None:
    """The text of the shapes of a slide in the order they are stored: a text frame as paragraphs (a placeholder of the body as list
    items, indented by level), a table as a Markdown table, a group by its members. The title shape is the heading; pictures, charts
    and other objects hold no text that is read."""
    for shape in shapes:
        if getattr(shape, "shape_type", None) == 6 and hasattr(shape, "shapes"):    # a group of shapes
            shape_blocks(shape.shapes, title, out)
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            out.append("\n".join(markdown_table(table_rows(shape.table))))
            continue
        if (title is not None and shape.shape_id == title.shape_id) or not getattr(shape, "has_text_frame", False) or not shape.has_text_frame:
            continue
        body = shape.is_placeholder and shape.placeholder_format.type is not None and int(shape.placeholder_format.type) in (2, 7)
        lines = []
        for paragraph in shape.text_frame.paragraphs:
            text = " ".join(paragraph.text.split())
            if text:
                lines.append(("  " * paragraph.level + "- " + text) if body else text)
        if lines:
            out.append("\n".join(lines))


def convert_pptx(path: str, work: str):
    """A presentation as Markdown with python-pptx: one section per slide, headed by the slide's title (`# Slide n` when it has none),
    then its text frames, tables and, under `### Notes`, its speaker notes. A hidden slide is not read and the manifest says so.
    Nothing is fetched: python-pptx reads the one package, the process cannot open a connection (forbid_network), and a failure of the
    library is a conversion error that names the exception class and nothing else."""
    forbid_network()
    check_package(path, PPTX_BYTES_MAX, PPTX_XML_MAX)
    try:
        import pptx
        deck = pptx.Presentation(path)
        parts, notes = [], []
        for number, slide in enumerate(deck.slides, 1):
            if slide._element.get("show") in HIDDEN:    # xsd:boolean: 0 and false
                notes.append(f"the hidden slide {number} was not read")
                continue
            title = slide.shapes.title
            heading = " ".join(title.text_frame.text.split()) if title is not None and title.has_text_frame else ""
            blocks = ["# " + (heading or f"Slide {number}")]
            shape_blocks(slide.shapes, title, blocks)
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                spoken = slide.notes_slide.notes_text_frame.text.strip()
                if spoken:
                    blocks.append("### Notes\n\n" + spoken)
            parts.append("\n\n".join(blocks))
            if sum(len(p) for p in parts) > CAP:
                notes.append(f"the presentation was cut after slide {number}")
                break
        text = "\n\n".join(parts).replace("\x00", "")
        version = getattr(pptx, "__version__", None)
    except Failed:
        raise
    except Exception as e:  # the library raises its own errors and its dependencies': one closed message, the class name only
        raise Failed(f"python-pptx could not convert the pptx file: {type(e).__name__}") from None
    return "converted.md", text.strip() + "\n", {"python-pptx": version}, notes


def convert(kind: str, path: str, work: str):
    if kind == "ooxml":
        kind = ooxml_kind(path)
    table = {"pdf": convert_pdf, "docx": convert_docx, "xlsx": convert_xlsx, "html": convert_html, "csv": convert_csv,
             "text": convert_text, "pptx": convert_pptx}
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
    if not args.input.startswith("/"):    # a path in the container; an address (http://, file:, data:) is never an input
        print("error: the input is a file path, never an address", file=sys.stderr)
        return 3
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
