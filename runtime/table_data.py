#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The table a task made, read and checked as code (package NOTION-OUT): a CSV file or the first sheet of a workbook becomes the
table an output step approves and a platform receives, `{"columns": [{"name", "type"}], "rows": [[value, ...]]}`, with the type of
each column given or inferred by a rule, and every cap enforced. Pure: no network, no provider, no project file but the bytes it is
handed; runtime/step_output.py reads the file with the engine's own `read_file` and passes the bytes here.

The rule that infers a column's type (nothing is guessed silently: an ambiguous column is text, and the preview says why):

  title      the column named in `columns` as a title; with none named, the first column. Exactly one column is the title.
  checkbox   every cell is `true` or `false` (any case) and no cell is empty. (A column with a gap is not a checkbox: an empty
             cell would have to become `false`, which is a guess. Name the type in `columns` to say that it may.)
  number     every non-empty cell is a plain number: an optional minus sign, digits with no leading zero (`0` and `0.5` are
             fine, `007` is not), an optional decimal part, at most 15 digits in all. No thousands separator, no exponent, no
             percent sign: a zip code, a phone number or `1,200` is text.
  date       every non-empty cell is an ISO 8601 date (`2026-11-01`) or a date-time WITH its zone (`2026-11-01T09:30:00Z`,
             `2026-11-01T09:30+02:00`), and a real calendar day. A date-time with no zone is not a date: the platform would read it in a
             zone of its own, so the column is text, the note says why, and a column named as a date stops the step.
  url        every non-empty cell starts with http:// or https:// and has no space.
  rich_text  everything else, and a column with no cell at all. When some cells fit a type above and others do not, the column is
             text and the note says "ambiguous".
  select     never inferred (a value that repeats is not always a choice): only a `columns` entry makes a select. Its options are
             the values that occur, at most 100, each of at most 100 characters and with no comma.

A type given in `columns` is checked against every cell: a cell that does not fit stops the step (`cell_not_type`), it is never
turned into something else. For rows added to an existing table (`schema`), the table's types decide: a column of the file must be a
column of the table, in a type this module writes, and the table's title column must be among the file's columns.

An empty cell is nothing (`null`), except in a checkbox column that was named, where it is `false`. Every cell is stripped of the
spaces and line breaks around it. A formula guard is not needed here: a cell is sent as the text of a property, which a platform
never evaluates (finding S9 is about files a spreadsheet program opens; runtime/step_export.py holds it).

The caps, and why: ROWS_MAX rows (one call a row, 2.8 calls a second, so a run of 500 takes about three minutes and fits the
provider's time limit), COLUMNS_MAX columns, CELL_MAX UTF-16 code units a cell (the platform's limit for one text object, "2,000 characters" in its
reference, counted in the larger unit; nothing is split), NAME_MAX a column's name, SELECT_MAX and OPTIONS_MAX for a select, TABLE_BYTES_MAX for the table as the effect document
holds it, CSV_MAX and XLSX_MAX for the file. providers/documents/notion_tables.py holds the same numbers; a test holds them equal.

A workbook is read with the standard library's zipfile and ElementTree and nothing else: the first sheet that is not hidden (the
table's remarks name it), shared and inline strings, numbers, booleans, and dates by their cell format; the cached value of a formula
(the formula is not read; a formula with no cached value is empty, and a remark counts them); a part with a DOCTYPE or an entity
declaration (found in the bytes, and a part with a NUL byte, which is how UTF-16 would hide one, is refused too), more than 200 parts,
a part over 16 MiB, or a ratio of expansion over 200 is refused (`xlsx_unsafe`); a file that is not a workbook, is damaged, is
encrypted or uses a compression zipfile does not read is `xlsx_unreadable`; a cell with a value beyond column 30 is `too_many_columns`
(how far to the right a cell with no value says it is does not matter, and no list is built from it).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import zipfile
import zlib
from datetime import datetime, timedelta
from xml.etree import ElementTree

ROWS_MAX = 500
COLUMNS_MAX = 30
CELL_MAX = 2000
NAME_MAX = 100
SELECT_MAX = 100
OPTIONS_MAX = 100
TABLE_BYTES_MAX = 1024 * 1024
CSV_MAX = 1024 * 1024
XLSX_MAX = 2 * 1024 * 1024
TABLE_ROWS_MAX = 2000     # the rows an existing table may hold for rows to be added (the provider counts them by listing)
TYPES = ("title", "rich_text", "number", "date", "select", "checkbox", "url")
NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")
URL = re.compile(r"https?://[^\s/$.?#][^\s]*")
DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2}))?")
NAIVE_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MEMBER_MAX = 16 * 1024 * 1024
MEMBERS_MAX = 200
RATIO_MAX = 200
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


class TableError(Exception):
    """A closed `code`, the `field` it names (never a cell's text), and a hint of positions (row and column numbers) or one fixed
    sentence."""

    def __init__(self, code: str, field: str = "", hint: str = ""):
        super().__init__(f"{code} {field} {hint}".strip())
        self.code, self.field, self.hint = code, field, hint


# --- the files -------------------------------------------------------------------------------------------------------------------------


def _clean(value) -> object:
    """A cell: its text without the space around it, None when nothing is left."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_csv(data: bytes) -> tuple:
    """(header, rows) of a CSV file: UTF-8 (a byte order mark is dropped), comma-separated, quoted by the usual rules, every row as long as the
    header, blank lines skipped. TableError: table_too_large, table_not_text, table_empty, table_ragged, columns_bad,
    too_many_columns, too_many_rows."""
    if len(data) > CSV_MAX:
        raise TableError("table_too_large", "rows", "the file is over 1 MiB")
    try:
        text = data.decode("utf-8-sig")
        lines = [[_clean(c) for c in row] for row in csv.reader(io.StringIO(text, newline=""), strict=True, skipinitialspace=True)]
    except (UnicodeDecodeError, csv.Error):
        raise TableError("table_not_text", "rows", "give a UTF-8 CSV file with commas between cells") from None
    return _shape([row for row in lines if any(c is not None for c in row)])


def _shape(lines: list, pad: bool = False) -> tuple:
    """(header, rows) from the non-blank lines: the first line names the columns. pad: a row that stops short has empty cells after it
    (a workbook does not store them); in a CSV file a short row is an error."""
    if not lines:
        raise TableError("table_empty", "rows", "the file has no header")
    head = list(lines[0])
    while head and head[-1] is None and all(len(r) < len(head) or r[len(head) - 1] is None for r in lines[1:]):
        head.pop()
    if not head or any(c is None for c in head):
        raise TableError("columns_bad", "columns", "every column needs a name")
    if len(head) > COLUMNS_MAX:
        raise TableError("too_many_columns", "columns", f"at most {COLUMNS_MAX}")
    names = [str(c) for c in head]
    for n, name in enumerate(names, 1):
        if len(name) > NAME_MAX or CONTROL.search(name) or "\n" in name:
            raise TableError("columns_bad", "columns", f"column {n}: a name is one line of at most {NAME_MAX} characters")
    if len(set(names)) != len(names):
        raise TableError("columns_bad", "columns", "two columns have the same name")
    rows = lines[1:]
    if not rows:
        raise TableError("table_empty", "rows", "the file has a header and no row")
    if len(rows) > ROWS_MAX:
        raise TableError("too_many_rows", "rows", f"at most {ROWS_MAX} rows a table operation: split the file")
    out = []
    for n, row in enumerate(rows, 1):
        extra = row[len(names):]
        if pad and len(row) < len(names):
            row = row + [None] * (len(names) - len(row))
        if len(row) < len(names) or any(c is not None for c in extra):
            raise TableError("table_ragged", "rows", f"row {n} does not have one cell for each of the {len(names)} columns")
        out.append(row[:len(names)])
    return names, out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_index(ref: str) -> int:
    """The zero-based column of a cell reference (`B3` is 1). A reference with no letters, or with more than three, is refused: the
    letters are the workbook's data and name how far to the right a cell is."""
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters or len(letters.group(0)) > 3:
        raise TableError("xlsx_unreadable", "rows", "a cell has no usable reference")
    n = 0
    for ch in letters.group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _si_text(element) -> str:
    out = []
    for child in element:
        name = _local(child.tag)
        if name == "t":
            out.append(child.text or "")
        elif name == "r":
            out.extend(t.text or "" for t in child if _local(t.tag) == "t")
    return "".join(out)


def _is_date_format(code: str) -> bool:
    stripped = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code)
    return bool(re.search(r"[ymdhs]", stripped, re.I))


def _serial_text(serial: float, base1904: bool):
    """A date serial as ISO text (a date, or a date-time when it has a time of day); None when it is not a date."""
    if serial < 1 and not base1904:
        return None
    start = datetime(1904, 1, 1) if base1904 else datetime(1899, 12, 30)
    try:
        moment = start + timedelta(seconds=round(serial * 86400))
    except OverflowError:
        return None
    return moment.strftime("%Y-%m-%d") if moment.hour == moment.minute == moment.second == 0 else moment.strftime("%Y-%m-%dT%H:%M:%S")


ZIP_FAULTS = (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError, OSError, ValueError)


def parse_xlsx(data: bytes) -> tuple:
    """(header, rows, extras) of the first VISIBLE sheet of a workbook; extras = {"sheet": its name, "hidden": the names of the hidden
    sheets before it, "no_value": {column index: cells that hold a formula and no stored value}}. TableError: table_too_large,
    xlsx_unreadable (not a workbook, damaged, encrypted, a compression this does not read, a part that is not XML), xlsx_unsafe
    (an entity or a DOCTYPE, in any encoding: a part with a NUL byte is refused, so UTF-16 cannot hide one; too many parts, a part over
    16 MiB, a ratio of expansion over 200), too_many_columns (a cell with a value beyond column 30), and the codes of parse_csv for the
    table inside."""
    if len(data) > XLSX_MAX:
        raise TableError("table_too_large", "rows", "the file is over 2 MiB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except ZIP_FAULTS:
        raise TableError("xlsx_unreadable", "rows", "the file is not a workbook") from None
    if len(infos) > MEMBERS_MAX or any(i.file_size > MEMBER_MAX or (i.file_size > 1024 and i.file_size > RATIO_MAX * max(i.compress_size, 1))
                                      for i in infos):
        raise TableError("xlsx_unsafe", "rows", "the workbook is not shaped like one a program makes")

    def member(name: str):
        try:
            info = archive.getinfo(name.lstrip("/"))
        except KeyError:
            return None
        try:
            with archive.open(info) as f:
                raw = f.read(MEMBER_MAX + 1)
        except ZIP_FAULTS:
            raise TableError("xlsx_unreadable", "rows", "a part of the workbook is damaged, encrypted or compressed in a way this "
                                                        "does not read") from None
        if len(raw) > MEMBER_MAX or b"\x00" in raw or re.search(rb"<!(DOCTYPE|ENTITY)", raw, re.I):
            raise TableError("xlsx_unsafe", "rows", "the workbook declares entities, is not plain UTF-8 or ASCII XML, or is too large")
        return raw

    def tree(name: str):
        raw = member(name)
        if raw is None:
            return None
        try:
            return ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            raise TableError("xlsx_unreadable", "rows", "a part of the workbook is not XML") from None

    book = tree("xl/workbook.xml")
    if book is None:
        raise TableError("xlsx_unreadable", "rows", "the file has no workbook part")
    base1904 = any(_local(e.tag) == "workbookPr" and e.get("date1904") in ("1", "true") for e in book)
    sheets = [e for e in book.iter() if _local(e.tag) == "sheet"]
    visible = [e for e in sheets if e.get("state") not in ("hidden", "veryHidden")]
    if not visible:
        raise TableError("xlsx_unreadable", "rows", "the workbook has no visible sheet")
    first = visible[0]
    hidden = [str(e.get("name") or "")[:40] for e in sheets[:sheets.index(first)] if e.get("state") in ("hidden", "veryHidden")]
    sheet_path = "xl/worksheets/sheet1.xml"
    rels = tree("xl/_rels/workbook.xml.rels")
    if rels is not None:
        rid = next((v for k, v in first.attrib.items() if _local(k) == "id"), None)
        target = next((e.get("Target") for e in rels if e.get("Id") == rid), None)
        if target:
            sheet_path = target.lstrip("/") if target.startswith("/") else "xl/" + target
    shared = []
    strings = tree("xl/sharedStrings.xml")
    if strings is not None:
        shared = [_si_text(si) for si in strings if _local(si.tag) == "si"]
    formats = []
    styles = tree("xl/styles.xml")
    if styles is not None:
        custom = {int(e.get("numFmtId")): e.get("formatCode") or "" for e in styles.iter() if _local(e.tag) == "numFmt"
                  and (e.get("numFmtId") or "").isdigit()}
        cell_xfs = next((e for e in styles if _local(e.tag) == "cellXfs"), None)
        for xf in (cell_xfs if cell_xfs is not None else []):
            fid = int(xf.get("numFmtId") or 0) if (xf.get("numFmtId") or "0").isdigit() else 0
            formats.append(fid in BUILTIN_DATE_FORMATS or (fid in custom and _is_date_format(custom[fid])))
    raw = member(sheet_path)
    if raw is None:
        raise TableError("xlsx_unreadable", "rows", "the first sheet is not in the file")
    lines, no_value = [], {}
    try:
        for _, element in ElementTree.iterparse(io.BytesIO(raw)):
            if _local(element.tag) != "row":
                continue
            cells = {}
            for c in element:
                if _local(c.tag) != "c":
                    continue
                kind, style = c.get("t") or "n", c.get("s")
                value = next((v for v in c if _local(v.tag) == "v"), None)
                text = value.text if value is not None else None
                if kind == "inlineStr":
                    inline = next((i for i in c if _local(i.tag) == "is"), None)
                    text = _si_text(inline) if inline is not None else None
                elif kind == "s":
                    try:
                        index = int(text) if text is not None else None
                        if index is not None and not 0 <= index < len(shared):
                            raise IndexError
                        text = shared[index] if index is not None else None
                    except (ValueError, IndexError):
                        raise TableError("xlsx_unreadable", "rows", "a cell names a string that is not there") from None
                elif kind == "b":
                    text = {"1": "true", "0": "false"}.get(text or "", text)
                elif kind == "e":
                    raise TableError("xlsx_unreadable", "rows", "a cell holds an error value")
                elif kind == "n" and text is not None and style is not None and style.isdigit() and int(style) < len(formats) \
                        and formats[int(style)]:
                    try:
                        text = _serial_text(float(text), base1904) or text
                    except ValueError:
                        pass
                has_formula = any(_local(f.tag) == "f" for f in c)
                cleaned = _clean(text)
                if cleaned is None and not (has_formula and value is None):
                    continue         # a cell with nothing in it is no cell: how far to the right it says it is does not matter
                column = _column_index(c.get("r") or "")
                if column >= COLUMNS_MAX:
                    raise TableError("too_many_columns", "columns", f"a cell is beyond column {COLUMNS_MAX}")
                cells[column] = cleaned
                if cleaned is None:
                    no_value[column] = no_value.get(column, 0) + 1
            element.clear()
            if any(v is not None for v in cells.values()):
                lines.append([cells.get(i) for i in range(max(cells) + 1)])
                if len(lines) > ROWS_MAX + 1:
                    raise TableError("too_many_rows", "rows", f"at most {ROWS_MAX} rows a table operation: split the file")
    except ElementTree.ParseError:
        raise TableError("xlsx_unreadable", "rows", "the sheet is not XML") from None
    header, rows = _shape(lines, pad=True)
    return header, rows, {"sheet": str(first.get("name") or "")[:60], "hidden": hidden, "no_value": no_value}


def parse(data: bytes, suffix: str) -> tuple:
    """(header, rows, extras) of the bytes of a `.csv` or `.xlsx` file (extras is {} for a CSV file)."""
    if suffix == ".xlsx":
        return parse_xlsx(data)
    header, rows = parse_csv(data)
    return header, rows, {}


# --- the types -----------------------------------------------------------------------------------------------------------------------


def units(text: str) -> int:
    """The length of a text in UTF-16 code units. The platform's reference says "characters" for the 2,000 of one text object and does
    not say in which unit; the code unit is the larger count for a character outside the basic plane, so a text that fits is safe."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def valid_date(text: str) -> bool:
    """An ISO 8601 date (`2026-11-01`) or a date-time WITH its zone (`2026-11-01T09:30:00Z`, `...+02:00`). A date-time with no zone is not
    one: the platform would read it in a zone this module does not know."""
    m = DATE.fullmatch(text)
    if not m:
        return False
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (1 <= month <= 12 and 1 <= day <= days[month - 1] and year >= 1):
        return False
    if m.group(4) is not None and not (int(m.group(4)) <= 23 and int(m.group(5)) <= 59 and int(m.group(6) or 0) <= 59):
        return False
    zone = m.group(7)
    return not (zone and zone != "Z" and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59))


def is_number(text: str) -> bool:
    return bool(NUMBER.fullmatch(text)) and len(re.sub(r"[^0-9]", "", text)) <= 15


def fits(kind: str, text: str) -> bool:
    if kind == "number":
        return is_number(text)
    if kind == "date":
        return valid_date(text)
    if kind == "url":
        return bool(URL.fullmatch(text)) and units(text) <= CELL_MAX
    if kind == "checkbox":
        return text.lower() in ("true", "false")
    if kind == "select":
        return len(text) <= SELECT_MAX and "," not in text
    return kind in ("title", "rich_text")


def infer(values: list) -> tuple:
    """(type, how) of a column from its cells (strings or None): the rule in this module's text. `how` is a fixed phrase."""
    present = [v for v in values if v is not None]
    if not present:
        return "rich_text", "text: the column has no value"
    if len(present) == len(values) and all(fits("checkbox", v) for v in present):
        return "checkbox", "inferred: every cell is true or false"
    for kind, phrase in (("number", "a plain number"), ("date", "an ISO date"), ("url", "a web address")):
        if all(fits(kind, v) for v in present):
            return kind, f"inferred: every filled cell is {phrase}"
    if len(present) < len(values) and all(fits("checkbox", v) for v in present):
        return "rich_text", "text, ambiguous: true and false with empty cells (name the type to make a checkbox)"
    if any(NAIVE_DATETIME.fullmatch(v) for v in present):
        return "rich_text", ("text, ambiguous: a date-time with no Z or offset is not sent as a date (the platform would read it in a zone "
                             "of its own); write the offset, such as +00:00")
    near = [k for k in ("number", "date", "url") if any(fits(k, v) for v in present)]
    return "rich_text", (f"text, ambiguous: some cells look like {near[0]} and some do not" if near else "text: no other type fits")


def convert(kind: str, text, row: int, column: int):
    """The canonical value of a cell for the type; TableError cell_not_type / cell_too_long / title_empty with positions only."""
    where = f"row {row}, column {column}"
    if text is not None and units(text) > CELL_MAX:
        raise TableError("cell_too_long", "rows", f"{where}: at most {CELL_MAX} UTF-16 code units")
    if text is not None and CONTROL.search(text):
        raise TableError("cell_not_type", "rows", f"{where}: a control character")
    if kind == "title":
        if text is None:
            raise TableError("title_empty", "rows", f"{where}: every row needs a title")
        return text
    if kind == "checkbox":
        if text is None:
            return False
        if not fits("checkbox", text):
            raise TableError("cell_not_type", "rows", f"{where}: a checkbox is true or false")
        return text.lower() == "true"
    if text is None:
        return None
    if not fits(kind, text):
        more = " with Z or an offset" if kind == "date" and NAIVE_DATETIME.fullmatch(text) else ""
        raise TableError("cell_not_type", "rows", f"{where}: not a {kind.replace('_', ' ')}{more}")
    if kind == "number":
        return float(text) if "." in text else int(text)
    return text


REMARKS_MAX = 10
REMARK_MAX = 200


def _one_line(text, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def build(header: list, rows: list, declared=None, schema=None, options=None, extras=None) -> dict:
    """The table: {"columns": [{"name", "type"}], "rows": [[...]], "notes": [one phrase for each column], "remarks": [fixed sentences
    about the table as a whole]}.

    declared  {name: type} the step's `columns` argument, or None;
    schema    [{"name", "type"}] of the table the rows are added to, or None. With a schema the table's types decide (the declared
              types must agree with them); without, a declared type is used and the rest are inferred;
    options   {column name: [the select options the table has]} of that table: a value that is not one of them is a NEW option the
              platform adds to the person's table, and a remark says so;
    extras    what parse_xlsx found besides the cells (the sheet read, hidden sheets skipped, formulas with no stored value).
    TableError: columns_bad, column_unknown, column_not_in_table, column_type_differs, column_type_unsupported, title_missing,
    title_count, cell_not_type, cell_too_long, title_empty, too_many_options, table_too_large."""
    declared = declared or {}
    for name, kind in declared.items():
        if name not in header:
            raise TableError("column_unknown", "columns", "`columns` names a column the file does not have")
        if kind not in TYPES:
            raise TableError("columns_bad", "columns", "a type is one of " + ", ".join(TYPES))
    types, notes = [], []
    if schema is not None:
        have = {c["name"]: c["type"] for c in schema}
        for n, name in enumerate(header, 1):
            if name not in have:
                raise TableError("column_not_in_table", "columns", f"column {n} is not a column of the table")
            if have[name] not in TYPES:
                raise TableError("column_type_unsupported", "columns", f"column {n}: the table's type is not one this writes")
            if name in declared and declared[name] != have[name]:
                raise TableError("column_type_differs", "columns", f"column {n}: the type given is not the table's")
            types.append(have[name])
            notes.append("the table's")
        titles = [c["name"] for c in schema if c["type"] == "title"]
        if len(titles) != 1 or titles[0] not in header:
            raise TableError("title_missing", "columns", "the file must have the table's title column")
    else:
        titled = [n for n, name in enumerate(header) if declared.get(name) == "title"]
        if len(titled) > 1:
            raise TableError("title_count", "columns", "exactly one column is the title")
        title_at = titled[0] if titled else 0
        for n, name in enumerate(header):
            column = [row[n] for row in rows]
            if n == title_at:
                types.append("title")
                notes.append("given: the title" if titled else "inferred: the first column is the title")
            elif name in declared:
                if declared[name] == "title":
                    raise TableError("title_count", "columns", "exactly one column is the title")
                types.append(declared[name])
                notes.append("given" + ("; an empty cell is unchecked" if declared[name] == "checkbox" and None in column else ""))
            else:
                kind, how = infer(column)
                types.append(kind)
                notes.append(how)
    out_rows = []
    for r, row in enumerate(rows, 1):
        out_rows.append([convert(types[n], row[n], r, n + 1) for n in range(len(header))])
    for n, kind in enumerate(types):
        if kind == "select" and len({row[n] for row in out_rows if row[n] is not None}) > OPTIONS_MAX:
            raise TableError("too_many_options", "columns", f"column {n + 1}: at most {OPTIONS_MAX} different options")
    remarks = []
    extras = extras or {}
    if extras.get("sheet") is not None:
        remarks.append(f"read from the sheet {_one_line(extras['sheet'], 60)!r}, the first sheet that is not hidden"
                       + (f"; {len(extras['hidden'])} hidden sheet(s) before it were skipped" if extras.get("hidden") else ""))
    for index, count in sorted((extras.get("no_value") or {}).items()):
        if index < len(header):
            remarks.append(f"{count} cell(s) of the column {_one_line(header[index], 40)!r} hold a formula with no stored value (the "
                           "workbook was saved without calculating it); they are empty here")
    for n, kind in enumerate(types):
        if kind == "select" and schema is not None and options is not None:
            fresh = sorted({row[n] for row in out_rows if row[n] is not None} - set(options.get(header[n]) or []))
            if fresh:
                shown = ", ".join(_one_line(v, 30) for v in fresh[:5]) + (f" and {len(fresh) - 5} more" if len(fresh) > 5 else "")
                remarks.append(f"the column {_one_line(header[n], 40)!r} gets {len(fresh)} NEW option(s) in the table: {shown}")
    if len(remarks) > REMARKS_MAX:
        remarks = remarks[:REMARKS_MAX - 1] + [f"and {len(remarks) - REMARKS_MAX + 1} more remarks"]
    table = {"columns": [{"name": name, "type": kind} for name, kind in zip(header, types)], "rows": out_rows, "notes": notes,
             "remarks": [_one_line(r, REMARK_MAX) for r in remarks]}
    if len(canonical({"columns": table["columns"], "rows": table["rows"]})) > TABLE_BYTES_MAX:
        raise TableError("table_too_large", "rows", "the table is over 1 MiB as the approval holds it")
    return table


def check_table(content) -> dict:
    """A table as the effect document holds it (`columns` and `rows`, already in their canonical values) is in its form and inside the
    caps. TableError table_bad with a position. The same rules as the provider's own check (providers/documents/notion_tables.py)."""
    if not isinstance(content, dict) or set(content) != {"columns", "rows"}:
        raise TableError("table_bad", "rows", "a table is columns and rows")
    columns, rows = content["columns"], content["rows"]
    if not isinstance(columns, list) or not 1 <= len(columns) <= COLUMNS_MAX or not isinstance(rows, list) or len(rows) > ROWS_MAX:
        raise TableError("table_bad", "rows", f"from 1 to {COLUMNS_MAX} columns and at most {ROWS_MAX} rows")
    names = set()
    for n, c in enumerate(columns, 1):
        if not isinstance(c, dict) or set(c) != {"name", "type"} or not isinstance(c["name"], str) or not c["name"].strip() \
                or len(c["name"]) > NAME_MAX or CONTROL.search(c["name"]) or c["type"] not in TYPES or c["name"] in names:
            raise TableError("table_bad", "columns", f"column {n}")
        names.add(c["name"])
    if sum(1 for c in columns if c["type"] == "title") != 1:
        raise TableError("table_bad", "columns", "exactly one title column")
    options = {}
    for r, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(columns):
            raise TableError("table_bad", "rows", f"row {r}")
        for n, (c, v) in enumerate(zip(columns, row), 1):
            kind = c["type"]
            ok = isinstance(v, bool) if kind == "checkbox" else (v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)
                                                                                and v == v and abs(v) != float("inf"))) \
                if kind == "number" else (isinstance(v, str) and bool(v.strip()) if kind == "title" else v is None or isinstance(v, str))
            if ok and isinstance(v, str):
                ok = units(v) <= CELL_MAX and not CONTROL.search(v) and (kind not in ("date", "url", "select") or fits(kind, v))
            if not ok:
                raise TableError("table_bad", "rows", f"row {r}, column {n}")
            if kind == "select" and v is not None:
                options.setdefault(c["name"], set()).add(v)
    if any(len(found) > OPTIONS_MAX for found in options.values()):
        raise TableError("table_bad", "columns", "too many select options")
    return content


def canonical(content: dict) -> bytes:
    """The bytes the hash of a table covers: its columns and rows as JSON with sorted keys, no spaces, UTF-8."""
    return json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
