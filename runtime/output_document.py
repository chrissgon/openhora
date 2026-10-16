#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of an output to the documents platform, and nothing that writes (package NOTION-OUT): what the step kinds `output-page`
and `output-table` build and the effect kind `write` approves, for the three operations that make something new on the platform. The
fourth operation of the same effect word, `update_page` (package P8), has its own document in runtime/write_document.py.

  create_page   a new page under a parent page the step names: a title and the Markdown of a project file
  create_table  a new table (a database with one data source) under a parent page: a title, its columns with their types and every row
  append_rows   rows added to an existing table the task read: its columns with their types and every row

The effect document has exactly these keys, and the hash the person approves is the hash of its canonical text (runtime/effects.py
`write`), so a different operation, parent or table, title, column, type, cell, base, note or key is another hash and an earlier
approval covers nothing of it:

  effect            "write" (the word of the side-effect vocabulary)
  operation         "create_page" | "create_table" | "append_rows"
  task              the step task that prepared it
  store             the first 12 hex characters of the sha256 of the project's store path: task numbers start again in every project, and
                    the provider's ledger is one file for the person, so a task's rows are found again only under its own project's name
  cycle             the cycle of the task that prepared it (it advances when a decision was answered because the table had changed)
  provider          the name the project's documents object carries; the write is refused if the configuration names another now
  target            {"id": the parent page (create_*) or the table's data source (append_rows), "path": the project file the content came
                    from: docs/<path>.md for a page, docs/<path>.csv or .xlsx for rows}
  target_name       the name the platform gave the parent page or the table when the task read it (or null): shown next to the id
  title             the new page's or table's title; null for append_rows
  base              what the task read of the target: {"schema_sha256", "row_count", "version", "rows_done"}; for append_rows the
                    table's columns hashed, its row count, the time of its newest edit, and how many of these rows the platform already
                    holds from an EARLIER approval of the same task (the ledger of the provider finds them by the task's scope);
                    for a new page or table, four nulls
  content           a page's Markdown (text), or a table's {"columns": [{"name", "type"}], "rows": [[...]]}
  content_sha256    the sha256 of the content: the UTF-8 text, or the table's canonical JSON (runtime/table_data.py canonical)
  bytes             the size of those bytes
  idempotency_key   derived from the task, the operation, the target, the title, the content's hash and the base: the same document
                    always carries the same key, so the platform's ledger writes it once, whatever pending decision it reaches
  notes             how each column's type was settled, one phrase for each (given, inferred, ambiguous); [] for a page
  remarks           what is true of the table as a whole and the person should read: the sheet of the workbook that was read, formulas
                    with no stored value, select options the platform will add to the person's table; [] for a page

The credential scan of runtime/workcopy.py runs on the content, and the caps are the ones of docs/architecture/platform/outputs.md:
a page's Markdown at most CONTENT_MAX bytes, a table at most ROWS_MAX rows, COLUMNS_MAX columns, CELL_MAX characters a cell and
TABLE_BYTES_MAX bytes (runtime/table_data.py).

It holds no function that calls a provider or executes an effect: that is runtime/effect_write.py, reached from the operation
`approve` only. The step kinds import this module and not that one, so a step kind has no function in reach that could write (limit
L30; limit L31 for the approval).

Standard library only, plus the credential scan of runtime/workcopy.py and the error class of runtime/effects.py. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import operations  # noqa: E402  (the command line the preview shows)
import table_data  # noqa: E402
import workcopy  # noqa: E402
from write_document import CONTENT_MAX, PROVIDER, SHA256, TARGET_ID, WORD, sha  # noqa: E402

OPERATIONS = ("create_page", "create_table", "append_rows")
KEYS = ("effect", "operation", "task", "store", "cycle", "provider", "target", "target_name", "title", "base", "content", "content_sha256", "bytes",
        "idempotency_key", "notes", "remarks")
PATHS = {"create_page": re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\.md"),
         "create_table": re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\.(csv|xlsx)"),
         "append_rows": re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\.(csv|xlsx)")}
TITLE_MAX = 200
NOTE_MAX = 200
PREVIEW_ROWS = 20       # the rows the preview shows whole (the first ones; the last three follow); the hash covers every row
PREVIEW_CELL = 60       # characters of a cell in the preview
NO_BASE = {"schema_sha256": None, "row_count": None, "version": None, "rows_done": None}
NAME_MAX = 200
REMARKS_MAX = table_data.REMARKS_MAX


def _usage(reason: str):
    return effects.EffectError("usage", reason)


def key_of(doc: dict) -> str:
    """The idempotency key of a document: derived from the pieces that make it what it is."""
    parts = [doc["store"], str(doc["task"]), str(doc["cycle"]), doc["operation"], doc["target"]["id"], doc["title"] or "", doc["content_sha256"],
             str(doc["base"]["schema_sha256"]), str(doc["base"]["row_count"]), str(doc["base"]["version"]), str(doc["base"]["rows_done"])]
    return "o-" + sha("\n".join(parts))[:40]


def content_bytes(operation: str, content) -> bytes:
    """The bytes the content's hash and size cover."""
    if operation == "create_page":
        return content.encode("utf-8") if isinstance(content, str) else b""
    return table_data.canonical(content) if isinstance(content, dict) else b""


STORE = re.compile(r"[0-9a-f]{12}")


def store_id(store_db: str) -> str:
    """The name of a project's store inside a key and a scope (as the key of a write-back builds it)."""
    return sha(store_db)[:12]


def scope_of(store: str, task_id: int) -> str:
    """The scope under which the provider's ledger finds again the rows an earlier attempt of the same task of the same project wrote
    (`--scope`)."""
    return f"s{store}-task-{task_id}"


def clean_name(value):
    """A name the platform gave, as one line of at most NAME_MAX characters without control characters, or None."""
    if not isinstance(value, str):
        return None
    text = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())[:NAME_MAX]
    return text or None


def document(*, operation: str, task_id: int, store: str, provider: str, target_id: str, path: str, title, content, base=None, notes=(),
             cycle: int = 0, target_name=None, remarks=()) -> dict:
    """The effect document, checked. EffectError usage when a piece is not in its form, a cap is over, the content is empty or
    holds what looks like a credential."""
    data = content_bytes(operation, content)
    doc = {"effect": WORD, "operation": operation, "task": task_id, "store": store, "cycle": cycle, "provider": provider,
           "target": {"id": target_id, "path": path}, "target_name": clean_name(target_name), "title": title,
           "base": dict(base or NO_BASE), "content": content, "content_sha256": sha(data), "bytes": len(data), "idempotency_key": "",
           "notes": list(notes), "remarks": list(remarks)}
    doc["idempotency_key"] = key_of(doc) if isinstance(doc["base"], dict) and set(doc["base"]) == set(NO_BASE) else ""
    check(doc)
    return doc


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the write."""
    if not isinstance(doc, dict) or set(doc) != set(KEYS) or doc["effect"] != WORD or doc["operation"] not in OPERATIONS:
        raise _usage("the effect document of an output has exactly its keys and one of its operations")
    operation, target, base, content, title = doc["operation"], doc["target"], doc["base"], doc["content"], doc["title"]
    if not isinstance(doc["task"], int) or isinstance(doc["task"], bool) or doc["task"] < 1:
        raise _usage("task is a task id")
    if not isinstance(doc["store"], str) or not STORE.fullmatch(doc["store"]):
        raise _usage("store is the name of the project's store")
    if not isinstance(doc["cycle"], int) or isinstance(doc["cycle"], bool) or not 0 <= doc["cycle"] < 1_000_000:
        raise _usage("cycle is a number")
    if doc["target_name"] is not None and (not isinstance(doc["target_name"], str) or doc["target_name"] != clean_name(doc["target_name"])):
        raise _usage("the target's name is one line of at most %d characters" % NAME_MAX)
    if not isinstance(doc["provider"], str) or not PROVIDER.fullmatch(doc["provider"]):
        raise _usage("provider is the name of an implementation")
    if not isinstance(target, dict) or set(target) != {"id", "path"} or not isinstance(target["id"], str) \
            or not TARGET_ID.fullmatch(target["id"]) or not isinstance(target["path"], str) \
            or not PATHS[operation].fullmatch(target["path"]) or ".." in target["path"].split("/") or target["path"].endswith(".comments.md"):
        raise _usage("the target is an identifier and a project-relative path of the kind of file the operation reads")
    if operation == "append_rows":
        if title is not None:
            raise _usage("rows added to a table have no title")
    elif not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX or re.search(r"[\x00-\x1f\x7f]", title):
        raise _usage(f"the title is one line of 1 to {TITLE_MAX} characters")
    if not isinstance(base, dict) or set(base) != set(NO_BASE):
        raise _usage("base is the schema hash, the row count and the version the task read")
    if operation == "append_rows":
        if not isinstance(base["schema_sha256"], str) or not SHA256.fullmatch(base["schema_sha256"]) \
                or not isinstance(base["row_count"], int) or isinstance(base["row_count"], bool) \
                or not 0 <= base["row_count"] <= table_data.TABLE_ROWS_MAX or not (base["version"] is None or isinstance(base["version"], str)) \
                or not isinstance(base["rows_done"], int) or isinstance(base["rows_done"], bool) or base["rows_done"] < 0:
            raise _usage("the base of rows added to a table is the hash of its columns, its row count, the time of its newest edit and the "
                         "rows an earlier approval already wrote")
        if isinstance(content, dict) and isinstance(content.get("rows"), list) and base["rows_done"] > len(content["rows"]):
            raise _usage("more rows are said to be there already than the document has")
    elif base != NO_BASE:
        raise _usage("a new page or table has no base")
    if operation == "create_page":
        if not isinstance(content, str) or not content.strip() or "\x00" in content:
            raise _usage("the content is non-empty text without a NUL character")
        if len(content.encode("utf-8")) > CONTENT_MAX:
            raise _usage(f"the content is over the {CONTENT_MAX} bytes one page takes: split it")
    else:
        try:
            table_data.check_table(content)
        except table_data.TableError as e:
            raise _usage(f"the table is not in its form ({e.hint})") from None
        if not content["rows"]:
            raise _usage("a table operation has at least one row")
    data = content_bytes(operation, content)
    if len(data) > (CONTENT_MAX if operation == "create_page" else table_data.TABLE_BYTES_MAX):
        raise _usage(f"the content is {len(data)} bytes, over what one operation takes: split it")
    if doc["content_sha256"] != sha(data) or doc["bytes"] != len(data):
        raise _usage("the content is not the one whose hash the document states")
    notes = doc["notes"]
    if not isinstance(notes, list) or len(notes) > table_data.COLUMNS_MAX or any(not isinstance(n, str) or len(n) > NOTE_MAX for n in notes) \
            or (operation == "create_page" and notes) or (operation != "create_page" and len(notes) != len(content["columns"])):
        raise _usage("notes: one phrase for each column of a table, none for a page")
    remarks = doc["remarks"]
    if not isinstance(remarks, list) or len(remarks) > REMARKS_MAX or any(not isinstance(r, str) or not r or len(r) > table_data.REMARK_MAX
                                                                          or re.search(r"[\x00-\x1f\x7f]", r) for r in remarks) \
            or (operation == "create_page" and remarks):
        raise _usage("remarks: up to %d lines about a table as a whole, none for a page" % REMARKS_MAX)
    if doc["idempotency_key"] != key_of(doc):
        raise _usage("the idempotency key is not the one this document derives")
    why = workcopy.scan(data)
    if why:
        raise _usage(f"the content {why}: it is not written anywhere")
    return doc


def title_of(doc: dict) -> str:
    """The title of the pending decision."""
    if doc["operation"] == "create_page":
        return f"Create page: {doc['title']}"[:200]
    if doc["operation"] == "create_table":
        return f"Create table: {doc['title']}"[:200]
    return f"Add {len(doc['content']['rows'])} rows to table {doc['target']['id']}"[:200]


def describe(doc: dict) -> str:
    """What is approved, in one line."""
    if doc["operation"] == "create_page":
        return f"create the page {doc['title']!r} under the page {doc['target']['id']} ({doc['bytes']} bytes)"
    rows, columns = len(doc["content"]["rows"]), len(doc["content"]["columns"])
    if doc["operation"] == "create_table":
        return f"create the table {doc['title']!r} of {rows} rows and {columns} columns under the page {doc['target']['id']}"
    return f"add {rows} rows of {columns} columns to the table {doc['target']['id']}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the content or the title."""
    out = {"operation": doc["operation"], "target": doc["target"]["id"], "path": doc["target"]["path"], "bytes": doc["bytes"],
           "content_sha256": doc["content_sha256"]}
    if doc["operation"] != "create_page":
        out.update(rows=len(doc["content"]["rows"]), columns=len(doc["content"]["columns"]))
    return out


def _cell(value, limit=PREVIEW_CELL) -> str:
    text = "" if value is None else ("true" if value is True else "false" if value is False else str(value))
    text = " / ".join(text.split("\n")).replace("|", "\\|")
    return text if limit is None or len(text) <= limit else text[:limit - 3] + "..."


def _table_lines(doc: dict) -> list:
    columns, rows = doc["content"]["columns"], doc["content"]["rows"]
    lines = ["| Column | Type | How the type was settled |", "|---|---|---|"]
    lines += [f"| {_cell(c['name'], None)} | {c['type']} | {_cell(n, None)} |" for c, n in zip(columns, doc["notes"])]
    shown = rows if len(rows) <= PREVIEW_ROWS + 3 else rows[:PREVIEW_ROWS] + [None] + rows[-3:]
    lines += ["", f"The rows ({len(rows)} in all; the first {min(len(rows), PREVIEW_ROWS)}"
              + (", then the last 3" if len(rows) > PREVIEW_ROWS + 3 else "") + "; a long cell is cut here and written whole):", "",
              "| " + " | ".join(_cell(c["name"], None) for c in columns) + " |", "|" + "---|" * len(columns)]
    for row in shown:
        lines.append("| ... |" + " |" * (len(columns) - 1) if row is None else "| " + " | ".join(_cell(v) for v in row) + " |")
    return lines


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving: where it goes, what it makes, what the hash covers, the command that approves, and the
    content (a page whole; a table's columns with their types, its row count and its first and last rows). A decision's body holds
    1 MiB; a page is at most CONTENT_MAX, and a table's preview a few thousand characters."""
    target, operation = doc["target"], doc["operation"]
    say = {"create_page": "Code makes a new page of your platform after your approval, and nothing else.",
           "create_table": "Code makes a new table (a database with one data source) of your platform after your approval, fills it with "
                           "these rows, and nothing else.",
           "append_rows": "Code adds these rows to a table of your platform after your approval, and nothing else. No row is changed or "
                          "removed, and no column is added."}[operation]
    lines = [say, ""]
    named = f" named {doc['target_name']!r}" if doc["target_name"] else ""
    if operation == "append_rows":
        rows, done = len(doc["content"]["rows"]), doc["base"]["rows_done"]
        lines += [f"Table: the data source {target['id']}{named} (provider {doc['provider']}); the rows come from {target['path']}",
                  f"When it was read the table had {doc['base']['row_count']} rows, columns with hash {doc['base']['schema_sha256']}"
                  + (f" and its newest edit was {doc['base']['version']}" if doc["base"]["version"] else ""),
                  "If its columns, its row count or its newest edit are not those when you approve, nothing is written and you are "
                  "asked again about the table as it is then. The columns of the rows must be columns of the table, with the types below."]
        if done:
            lines += ["", f"{done} of these {rows} rows are ALREADY in the table: an earlier approval of this task wrote them, and the "
                          "task started over because the table changed meanwhile. They are not sent again; approving writes the other "
                          f"{rows - done}" + (" (none: approving only records that they are all there)." if rows == done else ".")
                  + " The count comes from the platform's own listing of the table: a row the provider's ledger says was written and the "
                    "table no longer lists is not counted."]
    else:
        lines += [f"Parent: the page {target['id']}{named} (provider {doc['provider']}); the content comes from {target['path']}",
                  f"Title: {doc['title']}"]
    lines += ["", f"Content: {doc['bytes']} bytes, sha256 {doc['content_sha256']}", "",
              f"Hash of this effect (it covers the operation, the parent or table, the title, every column, type and cell, and the key): {digest}",
              "Approve exactly this: " + operations.command_line("approve", "<project>", pending_id="<this pending decision's id>",
                                                                 sha256=digest),
              "Or answer with what to change, or reject it: nothing is written until you approve.", ""]
    if operation == "create_page":
        lines += ["----- the content, exactly as it will be written -----", doc["content"].rstrip("\n"), "----- end of the content -----"]
    else:
        if doc["remarks"]:
            lines += ["Read before approving:"] + [f"- {r}" for r in doc["remarks"]] + [""]
        lines += ["----- the table, as it will be written -----"] + _table_lines(doc) + ["----- end of the table -----"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
