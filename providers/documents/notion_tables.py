"""The pure half of the tables of the Notion documents provider (package NOTION-OUT): the table a task made, as the file
`--table-file` holds it, checked; the schema and the cell values the service takes for it; and the comparison of a row the
service holds with a row of the file. No network, no credential, no file but the one it is given: providers/documents/notion.py
loads it by path, next to notion_blocks.py, and does every call.

The table file is one JSON object with exactly two keys:

  {"columns": [{"name": "<text>", "type": "title|rich_text|number|date|select|checkbox|url"}, ...],
   "rows": [[<one value per column>], ...]}

A value is: for title, a non-empty text; for rich_text, select and url, a text or null; for number, a number or null (never a
boolean); for date, an ISO 8601 date or date-time text or null; for checkbox, true or false. Exactly one column is a title.

The caps are the provider's own, checked again here although the runtime checks them before it asks for an approval (a file
that did not come from the runtime meets the same walls): at most ROWS_MAX rows and COLUMNS_MAX columns, a text of at most
CELL_MAX UTF-16 code units (one text object of the service, whose limit is 2,000 "characters", counted here in the larger unit), a name of at most NAME_MAX characters, a select
value of at most SELECT_MAX characters with no comma, at most OPTIONS_MAX different options in a select column, and the whole file
at most BYTES_MAX bytes. runtime/table_data.py holds the same numbers; a test holds them equal.

Standard library only. Python 3.10 or newer, like notion.py.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta

ROWS_MAX = 500
COLUMNS_MAX = 30
CELL_MAX = 2000
NAME_MAX = 100
SELECT_MAX = 100
OPTIONS_MAX = 100
BYTES_MAX = 1024 * 1024
TYPES = ("title", "rich_text", "number", "date", "select", "checkbox", "url")
URL_RE = re.compile(r"https?://[^\s/$.?#][^\s]*")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2}))?")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TableError(ValueError):
    """The table file is not in its form; the message names the column or the row, never a cell's text."""


def units(text: str) -> int:
    """The length of a text in UTF-16 code units. The service says "characters" for the 2,000 of one text object and does not say in
    which unit; counting code units is the larger count for a character outside the basic plane, so a text that fits is safe."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def valid_date(text: str) -> bool:
    """An ISO 8601 date (`2026-11-01`) or a date-time WITH its zone (`2026-11-01T09:30:00Z`, `...+02:00`): a date-time with no zone is
    refused, because the service reads it in a zone this provider does not know."""
    m = DATE_RE.fullmatch(text)
    if not m:
        return False
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (1 <= month <= 12 and 1 <= day <= days[month - 1] and year >= 1):
        return False
    if m.group(4) is not None and not (int(m.group(4)) <= 23 and int(m.group(5)) <= 59 and int(m.group(6) or 0) <= 59):
        return False
    zone = m.group(8)
    return not (zone and zone != "Z" and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59))


def instant(text):
    """What a date text names, to compare two of them: ("date", "YYYY-MM-DD") for a date, ("instant", the UTC datetime) for a date-time
    with its zone, whatever form the service writes it in (`.000`, `+00:00` for `Z`, another offset for the same moment). None when
    it is neither."""
    if not isinstance(text, str) or not valid_date(text):
        return None
    m = DATE_RE.fullmatch(text)
    if m.group(4) is None:
        return ("date", text)
    micro = int(((m.group(7) or ".0")[1:] + "000000")[:6])
    zone = m.group(8)
    offset = timedelta(0) if zone == "Z" else (1 if zone[0] == "+" else -1) * timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
    moment = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6) or 0), micro)
    try:
        return ("instant", moment - offset)
    except OverflowError:      # 0001-01-01T00:00+01:00 and 9999-12-31T23:59-01:00 name a moment before or after the range of a datetime
        return None


def check_value(kind: str, value, where: str) -> None:
    """A cell of the type, or TableError naming `where` (a column and a row, never the value)."""
    if kind == "checkbox":
        if not isinstance(value, bool):
            raise TableError(f"{where}: a checkbox is true or false")
    elif kind == "number":
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value != value
                                  or value in (float("inf"), float("-inf"))):
            raise TableError(f"{where}: a number is a finite number or null")
    elif kind in ("title", "rich_text", "select", "url", "date"):
        if value is None and kind != "title":
            return
        if not isinstance(value, str) or (kind == "title" and not value.strip()):
            raise TableError(f"{where}: " + ("a title is a non-empty text" if kind == "title" else f"a {kind} value is a text or null"))
        if units(value) > CELL_MAX or CONTROL.search(value):
            raise TableError(f"{where}: a text of at most {CELL_MAX} UTF-16 code units without control characters")
        if kind == "select" and (not value.strip() or len(value) > SELECT_MAX or "," in value):
            raise TableError(f"{where}: a select value is at most {SELECT_MAX} characters and has no comma")
        if kind == "url" and not URL_RE.fullmatch(value):
            raise TableError(f"{where}: a url starts with http:// or https:// and has no space")
        if kind == "date" and not valid_date(value):
            raise TableError(f"{where}: a date is YYYY-MM-DD or an ISO 8601 date-time with Z or an offset")
    else:
        raise TableError(f"{where}: the type {kind!r} is not one this provider makes")


def check(table) -> dict:
    """The table, or TableError. Caps, one title column, unique non-empty names, a value of each row's column in its type."""
    if not isinstance(table, dict) or set(table) != {"columns", "rows"}:
        raise TableError("the table file is an object with exactly columns and rows")
    columns, rows = table["columns"], table["rows"]
    if not isinstance(columns, list) or not 1 <= len(columns) <= COLUMNS_MAX:
        raise TableError(f"a table has from 1 to {COLUMNS_MAX} columns")
    if not isinstance(rows, list) or len(rows) > ROWS_MAX:
        raise TableError(f"a table operation has at most {ROWS_MAX} rows")
    names = set()
    for n, c in enumerate(columns, 1):
        if not isinstance(c, dict) or set(c) != {"name", "type"} or not isinstance(c["name"], str) or not c["name"].strip() \
                or len(c["name"]) > NAME_MAX or CONTROL.search(c["name"]) or c["type"] not in TYPES:
            raise TableError(f"column {n}: a name of at most {NAME_MAX} characters and one of the types {', '.join(TYPES)}")
        if c["name"] in names:
            raise TableError(f"column {n}: two columns have the same name")
        names.add(c["name"])
    if sum(1 for c in columns if c["type"] == "title") != 1:
        raise TableError("a table has exactly one title column")
    options = {}
    for r, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(columns):
            raise TableError(f"row {r}: one value for each of the {len(columns)} columns")
        for c, value in zip(columns, row):
            check_value(c["type"], value, f"row {r}, column {c['name']!r}")
            if c["type"] == "select" and value is not None:
                options.setdefault(c["name"], set()).add(value)
    for name, found in options.items():
        if len(found) > OPTIONS_MAX:
            raise TableError(f"column {name!r}: at most {OPTIONS_MAX} different select options")
    return table


def load(path: str) -> dict:
    """The table file, read (at most BYTES_MAX bytes, UTF-8 JSON) and checked."""
    try:
        with open(path, "rb") as f:
            raw = f.read(BYTES_MAX + 1)
    except OSError:
        raise TableError(f"the table file {path} cannot be read") from None
    if len(raw) > BYTES_MAX:
        raise TableError(f"the table file is over {BYTES_MAX} bytes")
    try:
        return check(json.loads(raw.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, TableError):
            raise
        raise TableError("the table file is not UTF-8 JSON") from None


def text_objects(text: str) -> list:
    return [{"type": "text", "text": {"content": text}}] if text else []


def schema_properties(columns: list, rows: list) -> dict:
    """`initial_data_source.properties` of a new database: a property for each column, a select with the options its values name."""
    out = {}
    for n, c in enumerate(columns):
        kind = c["type"]
        if kind == "number":
            out[c["name"]] = {"type": "number", "number": {"format": "number"}}
        elif kind == "select":
            seen = []
            for row in rows:
                if row[n] is not None and row[n] not in seen:
                    seen.append(row[n])
            out[c["name"]] = {"type": "select", "select": {"options": [{"name": v} for v in seen]}}
        else:
            out[c["name"]] = {"type": kind, kind: {}}
    return out


def row_properties(columns: list, row: list) -> dict:
    """The `properties` of the page that is one row: the value of each column in the form the service takes."""
    out = {}
    for c, value in zip(columns, row):
        kind = c["type"]
        if kind in ("title", "rich_text"):
            out[c["name"]] = {kind: text_objects(value or "")}
        elif kind == "date":
            out[c["name"]] = {"date": {"start": value} if value else None}
        elif kind == "select":
            out[c["name"]] = {"select": {"name": value} if value else None}
        else:
            out[c["name"]] = {kind: value}
    return out


def plain(rich) -> str:
    return "".join((r.get("plain_text") if r.get("plain_text") is not None else (r.get("text") or {}).get("content", ""))
                   for r in rich or [] if isinstance(r, dict))


def cell_of(prop) -> object:
    """The plain value of a property of a page the service lists."""
    if not isinstance(prop, dict):
        return None
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in ("title", "rich_text"):
        return plain(value)
    if kind == "date":
        return (value or {}).get("start") if isinstance(value, dict) else None
    if kind == "select":
        return (value or {}).get("name") if isinstance(value, dict) else None
    return value


def row_matches(page: dict, columns: list, row: list) -> bool:
    """Whether a page of the table holds exactly this row's values in these columns (a column the page lacks does not match)."""
    props = page.get("properties") or {}
    for c, value in zip(columns, row):
        if c["name"] not in props:
            return False
        have = cell_of(props[c["name"]])
        if c["type"] in ("title", "rich_text"):
            if (have or "") != (value or ""):
                return False
        elif c["type"] == "date":
            if (have is None) != (value is None) or (value is not None and (instant(have) is None or instant(have) != instant(value))):
                return False
        elif have != value:
            return False
    return True


def schema_of(source: dict) -> list:
    """The columns of a data source as the service describes it: [{"name", "type"}, ...], sorted by name."""
    props = source.get("properties")
    if not isinstance(props, dict):
        raise TableError("the answer holds no properties")
    out = []
    for name, p in props.items():
        if not isinstance(p, dict) or not isinstance(p.get("type"), str):
            raise TableError("the answer holds a property with no type")
        out.append({"name": name, "type": p["type"]})
    return sorted(out, key=lambda c: c["name"])


def row_sha256(columns: list, row: list) -> str:
    """A row as the ledger knows it: the hash of its values with the names and types of the columns they are in."""
    body = {"c": [[c["name"], c["type"]] for c in columns], "r": row}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def select_options(source: dict) -> dict:
    """{column name: [option names]} of the select columns of a data source as the service describes it."""
    out = {}
    for name, p in (source.get("properties") or {}).items():
        if isinstance(p, dict) and p.get("type") == "select":
            out[name] = [o.get("name") for o in ((p.get("select") or {}).get("options") or []) if isinstance(o, dict) and o.get("name")]
    return out


def schema_sha256(schema: list) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def problem_with(columns: list, schema: list):
    """Why a table's columns cannot be added to a data source with this schema, or None: each column must exist by name, with the
    same type, in a type this provider writes, and the table's title column must be the data source's title property."""
    have = {c["name"]: c["type"] for c in schema}
    for c in columns:
        if c["name"] not in have:
            return f"the table has no column named {c['name']!r}"
        if have[c["name"]] != c["type"]:
            return f"the column {c['name']!r} is {have[c['name']]} in the table and {c['type']} in the rows"
    if sum(1 for c in schema if c["type"] == "title") != 1 or {c["name"] for c in columns if c["type"] == "title"} \
            != {c["name"] for c in schema if c["type"] == "title"}:
        return "the rows must fill the table's title column"
    return None
