#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kinds `output-page` and `output-table`: a task's result becomes a new page, a new table, or rows added to a table on the
platform that holds the project's documents, as an external effect the person approves (package NOTION-OUT, an extension of P8's
write-back). I chose two new kinds and not an extension of `write-back`: that kind replaces the text of a page, and its arguments, its
checks and its preview are about that; a page made, a table made and rows added each have arguments of their own, and a kind per shape
keeps each closed. Provider-neutral names: the effect word is `write`, and what the platform is lives in the provider.

The kinds prepare; they never write. Two steps, as in a write-back:

  prepare    reads the project file named by the arguments (a Markdown file under docs/; a .csv or the first sheet of a .xlsx under
             docs/), checks it (runtime/table_data.py: the type of each column, the caps, one title column), reads the target through
             the read-only documents service (the parent page exists and is not in the trash; for rows added, the table's columns, its
             row count and its newest edit), and writes the effect document (runtime/output_document.py) through the effect-files service
             to <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a 0700 folder.
  approval   the gate (runtime/steps.py, Gate): no executor. It opens an `effect` decision whose hash is the hash of the effect document
             and whose body shows the operation, the parent or table, the title, the columns with their types and how each was settled,
             the row count and the first and last rows, or the page whole; the task waits. The person approves the hash in the terminal
             or on the page (any other channel is refused), and runtime/ops_step_effects.py calls the effect module, which reads the
             target again, writes, and records. A table or page changed meanwhile answers the decision, writes nothing and sends the task
             back to `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will run):

  output-page    {"parent": "<page id>", "title": "<one line>", "content": "docs/<path>.md"}
  output-table   a new table:   {"parent": "<page id>", "title": "<one line>", "rows": "docs/<path>.csv|.xlsx"[, "columns": {...}]}
                 rows added:    {"table": "<data source id>", "rows": "docs/<path>.csv|.xlsx"[, "columns": {...}]}
                 `columns` maps a column's name to title, rich_text, number, date, select, checkbox or url; the columns it leaves out are
                 typed by the rule in runtime/table_data.py (an ambiguous column is rich_text and the preview says so). Exactly one column
                 is the title. For rows added the table's own types decide and `columns` may only repeat them.

The parent and the table are identifiers, not addresses (the provider says what it takes). The files are files of the project, never of
the sources folder. The kinds are not `unattended` (a routine that would write to the platform on its own waits for the review rules of
a routine, decision D24) and write no file of the project (their footprint is empty).

Limit L30, in the structure of this file: it imports no module that calls a provider. What it needs of the platform and of the data
folder it asks of `ctx.services` (runtime/ops_step_seams.py), where `documents` has `read`, `stat` and `table_read` and no way to write,
and `effect_files` writes and reads the effect document and does not execute it. The only code that writes to the platform is
runtime/effect_write.py `execute`, which this file cannot reach.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import output_document  # noqa: E402
import steps  # noqa: E402
import table_data  # noqa: E402
import write_document  # noqa: E402

PAGE_KEYS = ("parent", "title", "content")
TABLE_KEYS = ("parent", "table", "title", "rows", "columns")
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed"}
GATE_STEP = "approval"


def _path(value, suffixes) -> bool:
    return isinstance(value, str) and bool(steps.REL_PATH.fullmatch(value)) and value.startswith("docs/") \
        and value.endswith(suffixes) and ".." not in value.split("/") and not value.endswith(".comments.md")


def _title(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > output_document.TITLE_MAX or re.search(r"[\x00-\x1f\x7f]", value):
        raise steps.StepFailure("bad_args", "title", "", f"give a title of one line, at most {output_document.TITLE_MAX} characters")
    return value.strip()


def _id(value, field: str) -> str:
    if not isinstance(value, str) or not write_document.TARGET_ID.fullmatch(value):
        raise steps.StepFailure("bad_args", field, "", "give the identifier, not the address")
    return value


def check_page(args) -> dict:
    """The arguments of an output-page, checked."""
    if not isinstance(args, dict) or set(args) != set(PAGE_KEYS):
        raise steps.StepFailure("bad_args", "args")
    if not _path(args["content"], (".md",)):
        raise steps.StepFailure("bad_args", "content", "", "give a Markdown file under docs/")
    return {"parent": _id(args["parent"], "parent"), "title": _title(args["title"]), "content": args["content"]}


def check_table(args) -> dict:
    """The arguments of an output-table, checked: a new table (parent and title) or rows added (table), and the rows file."""
    if not isinstance(args, dict) or not {"rows"} <= set(args) <= set(TABLE_KEYS) or ("parent" in args) == ("table" in args):
        raise steps.StepFailure("bad_args", "args", "", "give a parent and a title for a new table, or a table for rows added")
    if not _path(args["rows"], (".csv", ".xlsx")):
        raise steps.StepFailure("bad_args", "rows", "", "give a .csv or .xlsx file under docs/")
    out = {"rows": args["rows"]}
    if "parent" in args:
        if "title" not in args:
            raise steps.StepFailure("bad_args", "title", "", "a new table needs a title")
        out.update(parent=_id(args["parent"], "parent"), title=_title(args["title"]))
    else:
        if "title" in args:
            raise steps.StepFailure("bad_args", "title", "", "rows added to a table have no title")
        out["table"] = _id(args["table"], "table")
    if "columns" in args:
        given = args["columns"]
        if not isinstance(given, dict) or not 1 <= len(given) <= table_data.COLUMNS_MAX or any(
                not isinstance(k, str) or not k or len(k) > table_data.NAME_MAX or v not in table_data.TYPES for k, v in given.items()):
            raise steps.StepFailure("bad_args", "columns", "", "map a column's name to " + ", ".join(table_data.TYPES))
        out["columns"] = dict(given)
    return out


def _store(ctx: steps.Context) -> str:
    """The name of the project's store for the document (the services' configuration holds its path)."""
    cfg = ctx.services.get("config")
    if not isinstance(cfg, dict) or not isinstance(cfg.get("store_db"), str):
        raise steps.StepFailure("not_configured", "config")
    return output_document.store_id(cfg["store_db"])


def _service(ctx: steps.Context, name: str):
    found = ctx.services.get(name)
    if found is None:
        raise steps.StepFailure("not_configured", name)
    return found


def _asked(call, field: str, *args):
    """A service call whose failure is a closed code of the step."""
    try:
        return call(*args)
    except steps.StepFailure:
        raise
    except Exception as e:      # the services raise errors that carry a `code`; anything else is a provider failure
        raise steps.StepFailure(SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed"), field, "documents") from None


def _ready(ctx: steps.Context):
    """(reader, files) when a documents platform is configured and its bounds have not expired, else the step's closed failure."""
    reader, files = _service(ctx, "documents"), _service(ctx, "effect_files")
    if not reader.enabled():
        raise steps.StepFailure("not_configured", "documents", "", "configure a documents platform in docs/workbench/runtime.json")
    if reader.problem():
        raise steps.StepFailure("bounds_expired", "documents", "", "change expires in docs/workbench/runtime.json and accept the new hash")
    return reader, files


def _read(ctx: steps.Context, field: str, rel: str, limit: int) -> bytes:
    """A file of the project, read with steps.read_file (no link on the way, never the sources folder, a regular file, at most `limit`)."""
    try:
        return steps.read_file(ctx, rel, limit)
    except steps.StepFailure as e:
        code = {"missing": f"{field}_missing", "too_large": f"{field}_too_large"}.get(e.code, e.code)
        raise steps.StepFailure(code, field, "", "write the file first, then start this task" if code == f"{field}_missing" else
                                "split the file: an output takes a part you can read whole" if code == f"{field}_too_large" else "") from None


def _parent_ok(ctx: steps.Context, reader, parent: str):
    """The parent page exists, the integration reaches it and it is not in the trash; returns its name (or None) for the preview."""
    seen = _asked(reader.stat, "parent", parent)
    if not isinstance(seen, dict) or seen.get("archived") is not False:
        raise steps.StepFailure("parent_unreachable", "parent", "documents", "the parent page is in the trash or cannot be read")
    return seen.get("title") if isinstance(seen.get("title"), str) else None


def _document(ctx: steps.Context, **fields) -> dict:
    try:
        return output_document.document(task_id=ctx.task_id, store=_store(ctx), **fields)
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "content", "", str(getattr(e, "reason", ""))[:200]) from None


def _prepare_page(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    reader, files = _ready(ctx)
    raw = _read(ctx, "content", args["content"], write_document.CONTENT_MAX)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise steps.StepFailure("content_not_text", "content") from None
    name = _parent_ok(ctx, reader, args["parent"])
    doc = _document(ctx, operation="create_page", provider=reader.provider(), target_id=args["parent"], path=args["content"],
                    title=args["title"], content=content, cycle=int(state.get("cycle", 0)), target_name=name)
    digest = _asked(files.write, "target", ctx.task_id, int(state.get("cycle", 0)), doc)
    return {"effect_sha256": digest, "content_sha256": doc["content_sha256"], "bytes": doc["bytes"]}


def _prepare_table(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    reader, files = _ready(ctx)
    suffix = ".xlsx" if args["rows"].endswith(".xlsx") else ".csv"
    raw = _read(ctx, "rows", args["rows"], table_data.XLSX_MAX if suffix == ".xlsx" else table_data.CSV_MAX)
    adding, cycle = "table" in args, int(state.get("cycle", 0))
    try:
        header, rows, extras = table_data.parse(raw, suffix)
        if adding:
            read = _asked(reader.table_read, "table", args["table"])
            base = _base_of(read)
            options = read.get("select_options") if isinstance(read.get("select_options"), dict) else {}
            table = table_data.build(header, rows, args.get("columns"), schema=read["schema"], options=options, extras=extras)
            name = read.get("name") if isinstance(read.get("name"), str) else None
            base["rows_done"] = _rows_done(ctx, reader, args["table"], table)
        else:
            name = _parent_ok(ctx, reader, args["parent"])
            base, table = None, table_data.build(header, rows, args.get("columns"), extras=extras)
    except table_data.TableError as e:
        raise steps.StepFailure(e.code, e.field, "", e.hint) from None
    doc = _document(ctx, operation="append_rows" if adding else "create_table", provider=reader.provider(),
                    target_id=args["table"] if adding else args["parent"], path=args["rows"], title=None if adding else args["title"],
                    content={"columns": table["columns"], "rows": table["rows"]}, base=base, notes=table["notes"], cycle=cycle,
                    target_name=name, remarks=table["remarks"])
    digest = _asked(files.write, "target", ctx.task_id, int(state.get("cycle", 0)), doc)
    return {"effect_sha256": digest, "content_sha256": doc["content_sha256"], "bytes": doc["bytes"], "rows": len(table["rows"]),
            "columns": len(table["columns"])}


def _rows_done(ctx: steps.Context, reader, table_id: str, table: dict) -> int:
    """How many of these rows an EARLIER approval of this task already wrote into the table (the provider's ledger knows them by the
    task's scope), so that the preview says so and they are not sent again. 0 for a task that has written nothing."""
    content = {"columns": table["columns"], "rows": table["rows"]}
    found = _asked(reader.rows_state, "table", table_id, output_document.scope_of(_store(ctx), ctx.task_id), table_data.canonical(content))
    done = found.get("rows_done") if isinstance(found, dict) else None
    if not isinstance(done, int) or isinstance(done, bool) or not 0 <= done <= len(table["rows"]):
        raise steps.StepFailure("provider_failed", "table", "documents")
    return done


def _base_of(read) -> dict:
    """What the task read of a table (the provider's table-read), as the effect document's base; StepFailure provider_failed when the
    answer is not in its form, table_too_large for a table longer than the provider counts."""
    ok = isinstance(read, dict) and isinstance(read.get("schema"), list) and isinstance(read.get("schema_sha256"), str) \
        and isinstance(read.get("row_count"), int) and not isinstance(read.get("row_count"), bool) \
        and (read.get("last_edited") is None or isinstance(read.get("last_edited"), str))
    if not ok:
        raise steps.StepFailure("provider_failed", "table", "documents")
    if read["row_count"] > table_data.TABLE_ROWS_MAX:
        raise steps.StepFailure("table_too_large", "table", "", f"rows are not added to a table of more than {table_data.TABLE_ROWS_MAX} rows")
    return {"schema_sha256": read["schema_sha256"], "row_count": read["row_count"], "version": read.get("last_edited"), "rows_done": 0}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its preview, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    output_document.check(doc)
    return {"title": output_document.title_of(doc)[:200], "body": output_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": output_document.summary(doc)}}


def _kind(name: str, prepare, check) -> steps.Kind:
    return steps.Kind(name=name, order=("prepare", GATE_STEP), executors={"prepare": prepare},
                      gates={GATE_STEP: steps.Gate(word=output_document.WORD, open=_open, redo="prepare")},
                      footprint=lambda args: (), check=check, unattended=False)


PAGE = _kind("output-page", _prepare_page, check_page)
TABLE = _kind("output-table", _prepare_table, check_table)
for _kind_made in (PAGE, TABLE):
    if _kind_made.name not in steps.REGISTRY:
        steps.register(_kind_made)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
