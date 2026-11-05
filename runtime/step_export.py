#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kinds that make a file: `export-csv`, `export-xlsx`, `export-docx` and `export-pdf` (package P8, decision D17 direction 1).

A task's result, a Markdown or a CSV file of the project, becomes a CSV file, a workbook, a Word document or a PDF, made by code with
no model: the text is rendered by the adopted tools of the renderer's container (providers/exporter/container.py: the standard library's
csv, openpyxl, pandoc and WeasyPrint, no network, a read-only root), and the bytes that come back are written with the engine's own
`write_file` (runtime/steps.py: inside the footprint only, never the sources folder, no link followed, a temporary name renamed over
its place; the input is read with its `read_file`). One module holds the four kinds, a row of FORMATS each: another format is a row, not a step.

One step, `render`. Arguments (checked when the task is planned, so the plan's hash covers exactly what will run):

  {"input": "docs/<path>.csv|md", "name": "<a plain name>"[, "replace": true]}     the output is docs/outputs/<name>.<csv|xlsx|docx|pdf>

  An output that is already there is not replaced unless the arguments say `"replace": true` (the plan shows its arguments, so a plan
  that replaces a file says so): the task fails `output_exists` and names the way out.

  csv, xlsx   read a .csv; docx, pdf read a .md. A cell of a CSV or a workbook whose text starts with = + - @, a tab, a carriage return
              or a line feed (after any leading spaces) is written as text, never as a formula (finding S9: providers/exporter/_render.py holds
              the rule and its text says it). A Markdown picture, raw fragment or unsafe link is
              cleaned before a writer reads it.
  input       a file of the project under docs/, a regular file read without following a link, at most 1 MiB, UTF-8, with no
              credential in it (runtime/workcopy.py scan): a file that fails is not rendered.

Where the file goes, and why. The default and only place is docs/outputs/ of the project, through `write_file`, which refuses the
sources folder. The sources folder holds what people gave the project, as immutable versions made by the import (runtime/sources.py);
an output written there would be read by a later task as something a person provided, and the engine does not write there on
purpose (limits L23 and L26). A person who wants an output as a source imports it (`source-import`). The file is a file of the project
like any other: a rerun with `replace` replaces it, and the project's version control keeps the earlier ones.

The kinds are not `unattended`: a rerun replaces a file, and a routine that would do so on its own waits for the review rules of
a routine (decision D24) to say when. The footprint is the one output path, so the admission rule keeps two tasks from writing the
same file at once.

The result recorded is closed words and numbers: the output path, its size and sha256, the input's sha256, the tools' versions.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import steps  # noqa: E402
import workcopy  # noqa: E402

OUTPUT_DIR = "docs/outputs"
INPUT_MAX = 1024 * 1024                        # the renderer's own cap (providers/exporter/container.py INPUT_CAP)
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,59}")
FORMATS = {                                    # format -> (extension, the input's suffix, the words the person reads)
    "csv": ("csv", ".csv", "a CSV file"),
    "xlsx": ("xlsx", ".csv", "a workbook"),
    "docx": ("docx", ".md", "a Word document"),
    "pdf": ("pdf", ".md", "a PDF"),
}


def _check(fmt: str):
    suffix = FORMATS[fmt][1]

    def check(args) -> dict:
        if not isinstance(args, dict) or not {"input", "name"} <= set(args) <= {"input", "name", "replace"}:
            raise steps.StepFailure("bad_args", "args")
        source, name = args["input"], args["name"]
        if "replace" in args and not isinstance(args["replace"], bool):
            raise steps.StepFailure("bad_args", "replace")
        if not isinstance(source, str) or not steps.REL_PATH.fullmatch(source) or not source.startswith("docs/") \
                or ".." in source.split("/") or not source.endswith(suffix):
            raise steps.StepFailure("bad_args", "input", "", f"give a {suffix} file under docs/")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise steps.StepFailure("bad_args", "name", "", "a name is lowercase letters, digits and hyphens")
        return {"input": source, "name": name, **({"replace": True} if args.get("replace") else {})}
    return check


def output_path(fmt: str, args: dict) -> str:
    return f"{OUTPUT_DIR}/{args['name']}.{FORMATS[fmt][0]}"


def _read_input(ctx: steps.Context) -> bytes:
    """The bytes of the input file, read with steps.read_file (no link on the way, never the sources folder, a regular file, at most
    INPUT_MAX) and free of credentials. StepFailure: input_missing, input_too_large, protected_path, path_unsafe, input_refused."""
    try:
        data = steps.read_file(ctx, ctx.args["input"], INPUT_MAX)
    except steps.StepFailure as e:
        code = {"missing": "input_missing", "too_large": "input_too_large"}.get(e.code, e.code)
        raise steps.StepFailure(code, "input", "", "write the file first, then start this task" if code == "input_missing" else
                                "split the input: a render takes at most 1 MiB" if code == "input_too_large" else "") from None
    if workcopy.scan(data):
        raise steps.StepFailure("input_refused", "input", "", "the input holds what looks like a credential: take it out first")
    return data


def _renderer(ctx: steps.Context):
    """The render function of the engine's services (runtime/ops_step_seams.py: the exporter, class exporter:document, through the
    resolver) or a test's. A kind imports no module that calls a provider."""
    found = ctx.services.get("render")
    if found is None:
        raise steps.StepFailure("not_configured", "renderer", "exporter")

    def render(fmt, data):
        try:
            return found(fmt, data)
        except steps.StepFailure:
            raise
        except Exception as e:      # the service's errors carry a `code`
            if getattr(e, "code", "") == "not_configured":
                raise steps.StepFailure("not_configured", "renderer", "exporter",
                                        "build the renderer's image: python3 providers/exporter/container.py build --confirmed") from None
            raise steps.StepFailure("render_failed", "renderer", "exporter") from None
    return render


def _present(ctx: steps.Context, rel: str) -> str:
    """"absent", "file" (a regular file) or "link" (a link at the path or on the way, or anything the engine refuses to open): looked at
    with steps.read_file, which follows no link."""
    try:
        steps.read_file(ctx, rel, 0)
    except steps.StepFailure as e:
        if e.code == "protected_path":
            raise
        return "absent" if e.code == "missing" else "file" if e.code == "too_large" else "link"      # too_large: it has bytes
    except Exception:
        return "link"
    return "file"


def _executor(fmt: str):
    def render(ctx: steps.Context, state: dict) -> dict:
        data = _read_input(ctx)
        present = _present(ctx, output_path(fmt, ctx.args))
        if present == "link":
            raise steps.StepFailure("path_unsafe", "name", "", "a link is where the output goes: it is never followed or replaced")
        if present == "file" and not ctx.args.get("replace"):
            raise steps.StepFailure("output_exists", "name", "", "the file is already there: give another name, or add \"replace\": true "
                                    "to the arguments to replace it")
        made = _renderer(ctx)(fmt, data)
        output = made.get("output") if isinstance(made, dict) else None
        if not isinstance(output, (bytes, bytearray)) or not output:
            raise steps.StepFailure("render_failed", "renderer", "exporter")
        written = steps.write_file(ctx, output_path(fmt, ctx.args), bytes(output))
        tools = made.get("tool_versions") if isinstance(made.get("tool_versions"), dict) else {}
        return {"path": written["path"], "bytes": written["bytes"], "sha256": written["sha256"],
                "input_sha256": hashlib.sha256(data).hexdigest(),
                "tools": {str(k)[:40]: str(v)[:80] for k, v in sorted(tools.items())[:6]}}
    return render


def _kind(fmt: str) -> steps.Kind:
    return steps.Kind(name=f"export-{fmt}", order=("render",), executors={"render": _executor(fmt)},
                      footprint=lambda args, fmt=fmt: (output_path(fmt, args),), check=_check(fmt), unattended=False)


KINDS = {fmt: _kind(fmt) for fmt in FORMATS}
for _kind_of_format in KINDS.values():
    if _kind_of_format.name not in steps.REGISTRY:
        steps.register(_kind_of_format)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
