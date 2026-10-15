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


# --- hidden text (package P8, finding S9) ----------------------------------------------------------------------------------------
#
# A page or a PDF can carry text a person cannot see and a model reads, and the conversion hands the model all of it. This section
# finds the kinds listed below in an HTML page and in a PDF and reports a count, the kinds and short location hints, never the
# text. The host (runtime/sources.py) checks the answer against the same closed list and records it in the version's manifest and
# in its catalog.
#
#   HTML  an element's own style attribute, the simple rules of its <style> blocks (a tag, a class, an id, or a tag with a class
#         or an id) and the attributes `hidden`, `bgcolor` and `<font color>`: display:none, visibility:hidden, the hidden
#         attribute, opacity 0, font-size 0 or under 2px, a box of 1px or less with overflow hidden or a clip, a position or a
#         text-indent 500px or more off the page, and a text colour that matches its background (white on the page's default white
#         included) with a contrast ratio under 1.1. A hidden ancestor hides everything under it and is counted once.
#   PDF   poppler's pdftohtml: a fill colour that matches the white page, a font size of 2pt or less, and text in the invisible
#         render mode (the pieces that appear only when pdftohtml is told to show hidden text). A scanned PDF with a recognised-text
#         layer is flagged on purpose: the person sees the picture and the model reads that layer.
#
# What it does not find, and says so (docs/architecture/platform/outputs.md): text under a picture or a drawn shape, a colour match
# against a background that a style sheet outside the page, a selector with a combinator, a pseudo-class or an attribute, or a rule
# inside @media sets, text drawn as paths or as an image, the alt or title text of a hidden element, text a script moves, and the
# hidden text of a Word document, a spreadsheet or a presentation. A PDF's off-page text is not extracted by pdftotext, so it is
# not read and is not flagged.

HIDDEN_KINDS = ("display_none", "visibility_hidden", "hidden_attribute", "zero_size", "tiny_text", "off_page", "transparent",
                "white_on_white", "color_matched", "invisible_text")
HIDDEN_HINTS_MAX = 10
HIDDEN_OWNERS_MAX = 2000
CONTRAST_MIN = 1.1
TINY_PX, TINY_PT = 2.0, 2
OFF_PAGE_PX = 500.0
CSS_CAP = 200000
IMPLIED_END = {"p": ("p",), "li": ("li",), "dt": ("dt", "dd"), "dd": ("dt", "dd"), "tr": ("tr",), "td": ("td", "th"),
               "th": ("td", "th"), "option": ("option",)}
VOID_TAGS = frozenset("area base br col embed hr img input link meta param source track wbr".split())
UNREAD_TAGS = frozenset(("script", "style", "noscript", "template", "title", "head"))
NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "snow": (255, 250, 250), "ivory": (255, 255, 240), "whitesmoke": (245, 245, 245),
    "ghostwhite": (248, 248, 255), "floralwhite": (255, 250, 240), "azure": (240, 255, 255), "mintcream": (245, 255, 250),
    "honeydew": (240, 255, 240), "aliceblue": (240, 248, 255), "seashell": (255, 245, 238), "gainsboro": (220, 220, 220),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211), "silver": (192, 192, 192), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169), "red": (255, 0, 0), "blue": (0, 0, 255),
    "green": (0, 128, 0), "yellow": (255, 255, 0), "navy": (0, 0, 128),
}
LENGTH = re.compile(r"(-?\d*\.?\d+)(px|pt|em|rem|%)?")
SIMPLE_SELECTOR = re.compile(r"([a-z][a-z0-9]*|\*)?(?:\.([a-z0-9_-]+))?(?:#([a-z0-9_-]+))?")
HEX_COLOR = re.compile(r"#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})")
FUNC_COLOR = re.compile(r"rgba?\(\s*([0-9.]+%?)\s*[, ]\s*([0-9.]+%?)\s*[, ]\s*([0-9.]+%?)\s*(?:[,/]\s*([0-9.]+%?)\s*)?\)")


def css_declarations(text: str) -> dict:
    """{property: value} from the text of a style attribute or of a rule's block: lower case, `!important` dropped, values cut at
    200 characters; a later declaration of a property wins."""
    out = {}
    for part in text[:4000].split(";"):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        name = name.strip().lower()
        if re.fullmatch(r"-?[a-z][a-z-]{0,40}", name):
            out[name] = re.sub(r"\s*!important\s*$", "", value.strip().lower())[:200]
    return out


def css_rules(css: str) -> list:
    """The simple rules of the style blocks, [(rank, tag, class, id, declarations)] in the order a cascade applies them (an id over
    a class over a tag, later over earlier). Rules inside an at-rule (@media, @supports) and selectors with a combinator, a
    pseudo-class or an attribute are left out."""
    css = re.sub(r"/\*.*?\*/", "", css[:CSS_CAP], flags=re.S)
    css = re.sub(r"@[a-z-]+[^{};]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    rules = []
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        declarations = css_declarations(block.group(2))
        for selector in block.group(1).split(","):
            found = SIMPLE_SELECTOR.fullmatch(selector.strip().lower())
            if found and selector.strip():
                tag, klass, ident = found.groups()
                rank = (3 if ident else 0) + (2 if klass else 0) + (1 if tag and tag != "*" else 0)
                rules.append((rank, None if tag == "*" else tag, klass, ident, declarations))
    return sorted(rules, key=lambda r: r[0])


def css_length(value, em: float = 16.0):
    """A CSS length in pixels, or None when it is not a plain one (`auto`, a calc, a viewport unit, a percentage)."""
    found = LENGTH.fullmatch((value or "").strip())
    if not found:
        return None
    number, unit = float(found.group(1)), found.group(2)
    if unit in (None, "px"):
        return number
    if unit == "pt":
        return number * 4.0 / 3.0
    if unit in ("em", "rem"):
        return number * em
    return None


def css_color(value):
    """(r, g, b, alpha) of a colour written as a name, #rgb, #rgba, #rrggbb, #rrggbbaa, rgb() or rgba(); None for anything else
    (inherit, currentcolor, hsl, a variable)."""
    text = (value or "").strip().lower()
    if text == "transparent":
        return (0, 0, 0, 0.0)
    if text in NAMED_COLORS:
        return NAMED_COLORS[text] + (1.0,)
    hexed = HEX_COLOR.fullmatch(text)
    if hexed:
        digits = hexed.group(1)
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        alpha = int(digits[6:8], 16) / 255.0 if len(digits) == 8 else 1.0
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), alpha)
    func = FUNC_COLOR.fullmatch(text)
    if func:
        def channel(part):
            return min(255, max(0, round(float(part[:-1]) * 2.55 if part.endswith("%") else float(part))))
        alpha = 1.0
        if func.group(4):
            alpha = float(func.group(4)[:-1]) / 100.0 if func.group(4).endswith("%") else float(func.group(4))
        return (channel(func.group(1)), channel(func.group(2)), channel(func.group(3)), alpha)
    return None


def luminance(rgb) -> float:
    def part(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * part(rgb[0]) + 0.7152 * part(rgb[1]) + 0.0722 * part(rgb[2])


def contrast(a, b) -> float:
    """The WCAG contrast ratio of two colours: 1.0 (the same) to 21.0."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def color_reason(color, background):
    """The kind of hidden text a text colour on a background is, or None. `color` is None for the default (black); `background` is
    None for the page's default white, or "unknown" for one that cannot be worked out (a picture, a gradient): then nothing is said."""
    if background == "unknown":
        return None
    if color is not None and color[3] <= 0.05:
        return "transparent"
    ink = color[:3] if color is not None else (0, 0, 0)
    paper = background[:3] if background is not None and background[3] > 0.05 else (255, 255, 255)
    if contrast(ink, paper) >= CONTRAST_MIN:
        return None
    return "white_on_white" if background is None else "color_matched"


class HiddenScan:
    """What an HTML page hides: feed(html), then result(). A small walk over html.parser's events that keeps, for each open element,
    the reasons its text is hidden (those of the elements around it and its own) and the colour, size and background it resolves
    to; text found under an element that has a reason is counted once, for the outermost element that has one."""

    def __init__(self, rules):
        import html.parser

        outer = self

        class Parser(html.parser.HTMLParser):
            def handle_starttag(self, tag, attrs):
                outer.start(tag, attrs)

            def handle_startendtag(self, tag, attrs):
                outer.start(tag, attrs)
                outer.end(tag)

            def handle_endtag(self, tag):
                outer.end(tag)

            def handle_data(self, data):
                outer.data(data)

        self.rules = rules
        self.parser = Parser(convert_charrefs=True)
        self.stack = []
        self.number = 0
        self.unread = 0
        self.owners = {}

    def feed(self, html: str) -> None:
        self.parser.feed(html)
        self.parser.close()

    def own_style(self, tag, attrs) -> dict:
        classes = set((attrs.get("class") or "").lower().split())
        ident = (attrs.get("id") or "").lower()
        found = {}
        for _rank, rtag, rclass, rid, declarations in self.rules:
            if (rtag is None or rtag == tag) and (rclass is None or rclass in classes) and (rid is None or rid == ident):
                found.update(declarations)
        found.update(css_declarations(attrs.get("style") or ""))
        return found

    def start(self, tag, pairs) -> None:
        self.number += 1
        if tag == "body":
            self.unread = 0                       # a head that was never closed ends here
        if tag in UNREAD_TAGS:
            self.unread += 1
        if tag in VOID_TAGS:
            return
        if self.stack and self.stack[-1]["tag"] in IMPLIED_END.get(tag, ()):
            self.stack.pop()                      # <p>a<p>b: the first paragraph ended where the second began
        attrs = {k.lower(): (v or "") for k, v in pairs[:60] if isinstance(k, str)}
        style = self.own_style(tag, attrs)
        root = {"hide": frozenset(), "color": None, "font": None, "background": None, "visibility": False}
        parent = self.stack[-1] if self.stack else root
        hide = set(parent["hide"])
        if "hidden" in attrs:
            hide.add("hidden_attribute")
        if (style.get("display") or "").split(" ")[0] == "none":
            hide.add("display_none")
        visibility = parent["visibility"]
        if style.get("visibility") in ("hidden", "collapse"):
            visibility = True
        elif style.get("visibility") == "visible":
            visibility = False
        try:
            if "opacity" in style and float(style["opacity"]) <= 0.01:
                hide.add("transparent")
        except ValueError:
            pass
        small = [css_length(style.get(p)) for p in ("width", "height", "max-width", "max-height") if p in style]
        clipped = style.get("overflow") in ("hidden", "clip") or "clip" in style or "clip-path" in style
        if clipped and any(v is not None and v <= 1.0 for v in small):
            hide.add("zero_size")
        edges = [css_length(style.get(p)) for p in ("left", "right", "top", "bottom") if p in style]
        indent = css_length(style.get("text-indent"))
        if (style.get("position") in ("absolute", "fixed") and any(v is not None and v <= -OFF_PAGE_PX for v in edges)) \
                or (indent is not None and indent <= -OFF_PAGE_PX):
            hide.add("off_page")
        font = parent["font"]
        if "font-size" in style:
            size = style["font-size"]
            if size.endswith("%"):
                try:
                    font = (font if font is not None else 16.0) * float(size[:-1]) / 100.0
                except ValueError:
                    pass
            else:
                length = css_length(size, em=font if font is not None else 16.0)
                font = length if length is not None else font
        color = parent["color"]
        wanted = style.get("color") or (attrs.get("color") if tag == "font" else None)
        if wanted:
            color = css_color(wanted) or color
        background = parent["background"]
        painted = style.get("background-color") or style.get("background") or attrs.get("bgcolor")
        if painted:
            first = painted.split(" ")[0]
            parsed = None if ("url(" in painted or "gradient" in painted) else (css_color(painted) or css_color(first))
            background = parsed if parsed is not None else "unknown"
        reasons = set(hide)
        if visibility:
            reasons.add("visibility_hidden")
        if font is not None and font < TINY_PX:
            reasons.add("zero_size" if font <= 0 else "tiny_text")
        reason = color_reason(color, background) if (color is not None or background not in (None, "unknown")) else None
        if reason:
            reasons.add(reason)
        self.stack.append({"tag": tag, "n": self.number, "hide": frozenset(hide), "color": color, "font": font,
                           "background": background, "visibility": visibility, "reasons": frozenset(reasons)})

    def end(self, tag) -> None:
        if tag in UNREAD_TAGS and self.unread:
            self.unread -= 1
        for depth in range(len(self.stack) - 1, max(-1, len(self.stack) - 40), -1):
            if self.stack[depth]["tag"] == tag:
                del self.stack[depth:]
                return

    def data(self, text) -> None:
        if self.unread or not text.strip() or not self.stack or not self.stack[-1]["reasons"]:
            return
        owner = next(e for e in self.stack if e["reasons"])
        if owner["n"] not in self.owners and len(self.owners) >= HIDDEN_OWNERS_MAX:
            return
        found = self.owners.setdefault(owner["n"], {"tag": owner["tag"], "kinds": set()})
        found["kinds"] |= self.stack[-1]["reasons"]

    def result(self) -> dict:
        kinds = {}
        for owner in self.owners.values():
            for kind in owner["kinds"]:
                kinds[kind] = kinds.get(kind, 0) + 1
        hints = [f"{'+'.join(k for k in HIDDEN_KINDS if k in owner['kinds'])} in {owner['tag']} element {n}"
                 for n, owner in sorted(self.owners.items())[:HIDDEN_HINTS_MAX]]
        return {"examined": True, "count": len(self.owners), "kinds": {k: kinds[k] for k in HIDDEN_KINDS if k in kinds}, "hints": hints}


def hidden_in_html(html: str) -> dict:
    """The hidden-text record of an HTML page: {"examined": True, "count", "kinds": {kind: n}, "hints": [...]}."""
    html = html[:TEXT_CAP]
    scan = HiddenScan(css_rules("\n".join(re.findall(r"(?is)<style\b[^>]*>(.*?)</style\s*>", html))))
    scan.feed(html)
    return scan.result()


PDF_PAGE = re.compile(r'<page number="(\d+)"[^>]*? height="(\d+)" width="(\d+)"')
PDF_FONT = re.compile(r'<fontspec id="(\d+)" size="(-?\d+)" family="[^"]*" color="(#[0-9a-fA-F]{6})"')
PDF_TEXT = re.compile(r'<text top="(-?\d+)" left="(-?\d+)" width="(-?\d+)" height="(-?\d+)" font="(\d+)">(.*?)</text>')


def pdf_texts(xml: str) -> list:
    """[(page, top, left, text, size in pt, colour)] of the pieces of text in pdftohtml's XML that lie on their page. A piece off
    the page is not read by pdftotext, so it is left out."""
    fonts, out = {}, []
    page = height = width = 0
    for line in xml.splitlines():
        found = PDF_PAGE.search(line)
        if found:
            page, height, width = int(found.group(1)), int(found.group(2)), int(found.group(3))
            continue
        found = PDF_FONT.search(line)
        if found:
            fonts[found.group(1)] = (int(found.group(2)), found.group(3).lower())
            continue
        found = PDF_TEXT.search(line)
        if found and found.group(5) in fonts:
            top, left, w, h = (int(found.group(i)) for i in (1, 2, 3, 4))
            text = re.sub(r"<[^>]*>", "", found.group(6)).strip()
            if text and not (left + w <= 0 or left >= width or top + h <= 0 or top >= height):
                out.append((page, top, left, text, fonts[found.group(5)][0], fonts[found.group(5)][1]))
    return out


def hidden_in_pdf(shown_xml: str, all_xml: str) -> dict:
    """The hidden-text record of a PDF from two runs of pdftohtml -xml: `shown_xml` as it comes and `all_xml` with -hidden. A piece
    of text is flagged when its fill colour matches the white page or its font is 2pt or less; a piece that only the second run
    has is in the invisible render mode."""
    visible = pdf_texts(shown_xml)
    flagged = []                                  # [(page, {kinds})], one for each piece
    for page, _top, _left, _text, size, color in visible:
        reasons = set()
        if size <= TINY_PT:
            reasons.add("zero_size" if size <= 0 else "tiny_text")
        if contrast((int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)), (255, 255, 255)) < CONTRAST_MIN:
            reasons.add("white_on_white")
        if reasons:
            flagged.append((page, reasons))
    seen = {}
    for page, top, left, text, _size, _color in visible:
        seen[(page, top, left, text)] = seen.get((page, top, left, text), 0) + 1
    for page, top, left, text, _size, _color in pdf_texts(all_xml):
        if seen.get((page, top, left, text), 0) > 0:
            seen[(page, top, left, text)] -= 1
        else:
            flagged.append((page, {"invisible_text"}))
    kinds, pages = {}, {}
    for page, reasons in flagged:
        for kind in reasons:
            kinds[kind] = kinds.get(kind, 0) + 1
            pages[(page, kind)] = pages.get((page, kind), 0) + 1
    hints = [f"{kind} on page {page} count {n}" for (page, kind), n in sorted(pages.items(), key=lambda i: (i[0][0], HIDDEN_KINDS.index(i[0][1])))]
    return {"examined": True, "count": len(flagged), "kinds": {k: kinds[k] for k in HIDDEN_KINDS if k in kinds},
            "hints": hints[:HIDDEN_HINTS_MAX]}


def hidden_text(kind: str, path: str):
    """The hidden-text record of a converted file: for an HTML page and a PDF the record; for any other kind None (not examined). A
    check that cannot be made is {"examined": False, "why": "tool_failed"}: the conversion is not failed for it, and the host says so."""
    try:
        if kind == "html":
            with open(path, "rb") as f:
                return hidden_in_html(utf8(f.read(TEXT_CAP)))
        if kind == "pdf":
            base = ["pdftohtml", "-xml", "-zoom", "1", "-i", "-stdout", "-enc", "UTF-8"]
            shown = utf8(run_tool(base + [path]))
            everything = utf8(run_tool(base[:2] + ["-hidden"] + base[2:] + [path]))
            return hidden_in_pdf(shown, everything)
    except (Failed, OSError, RecursionError):
        return {"examined": False, "why": "tool_failed"}
    return None


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
    info = json.dumps({"converter": "document", "kind": kind, "tool_versions": tools, "notes": notes,
                       "hidden_text": hidden_text(kind, args.input)}, sort_keys=True).encode("utf-8")
    sys.stdout.buffer.write(frames([(name, data), ("info.json", info[:INFO_CAP])]))
    sys.stdout.buffer.flush()
    shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
