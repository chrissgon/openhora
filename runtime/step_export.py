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
its place). One module holds the four kinds, a row of FORMATS each: another format is a row, not a step.

One step, `render`. Arguments (checked when the task is planned, so the plan's hash covers exactly what will run):

  {"input": "docs/<path>.csv|md", "name": "<a plain name>"}        the output is docs/outputs/<name>.<csv|xlsx|docx|pdf>

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
like any other: a rerun replaces it, and the project's version control keeps the earlier ones.

The kinds are not `unattended`: a rerun replaces a file, and a routine that would do so on its own waits for the review rules of
a routine (decision D24) to say when. The footprint is the one output path, so the admission rule keeps two tasks from writing the
same file at once.

The result recorded is closed words and numbers: the output path, its size and sha256, the input's sha256, the tools' versions.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import shutil
import os
import re
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import project_config  # noqa: E402
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
        if not isinstance(args, dict) or set(args) != {"input", "name"}:
            raise steps.StepFailure("bad_args", "args")
        source, name = args["input"], args["name"]
        if not isinstance(source, str) or not steps.REL_PATH.fullmatch(source) or not source.startswith("docs/") \
                or ".." in source.split("/") or not source.endswith(suffix):
            raise steps.StepFailure("bad_args", "input", "", f"give a {suffix} file under docs/")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise steps.StepFailure("bad_args", "name", "", "a name is lowercase letters, digits and hyphens")
        return {"input": source, "name": name}
    return check


def output_path(fmt: str, args: dict) -> str:
    return f"{OUTPUT_DIR}/{args['name']}.{FORMATS[fmt][0]}"


def _read_input(ctx: steps.Context) -> bytes:
    """The bytes of the input file: opened without following a link, a regular file, at most INPUT_MAX, outside the sources folder,
    and free of credentials. StepFailure: input_missing, input_too_large, protected_path, input_refused."""
    root = os.path.realpath(ctx.project)
    path = os.path.join(root, *ctx.args["input"].split("/"))
    if ctx.protected(path) or ctx.protected(os.path.realpath(path)):
        raise steps.StepFailure("protected_path", "input")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise steps.StepFailure("input_missing", "input", "", "write the file first, then start this task") from None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise steps.StepFailure("input_missing", "input")
    with os.fdopen(fd, "rb") as f:
        data = f.read(INPUT_MAX + 1)
    if len(data) > INPUT_MAX:
        raise steps.StepFailure("input_too_large", "input", "", "split the input: a render takes at most 1 MiB")
    if workcopy.scan(data):
        raise steps.StepFailure("input_refused", "input", "", "the input holds what looks like a credential: take it out first")
    return data


EXPORTER_CLASS = "exporter:document"
EXPORTER_TIMEOUT = 300
OUTPUT_MAX = 8 * 1024 * 1024        # the exporter's own cap (providers/exporter/container.py OUTPUT_CAP)


def _read_output(folder: str, name: str) -> bytes:
    """The one file the exporter left in the private out folder: a regular file with one link, opened without following a link, at most
    OUTPUT_MAX bytes, and nothing else in the folder. StepFailure render_failed otherwise."""
    path = os.path.join(folder, name)
    try:
        info = os.lstat(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise steps.StepFailure("render_failed", "renderer", "exporter") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > OUTPUT_MAX or sorted(os.listdir(folder)) != [name]:
            raise steps.StepFailure("render_failed", "renderer", "exporter")
        return f.read(OUTPUT_MAX + 1)


def _renderer(ctx: steps.Context):
    """The render function: ctx.services["render"](format, data) in a test, else the provider of the class exporter:document, called
    through providers/resolve.py with the minimum environment (the host side: providers/exporter/container.py). The input goes into
    a private file, the output comes back as one file in a private folder, and both are removed."""
    seam = ctx.services.get("render")
    if seam is not None:
        return seam
    root = os.path.dirname(HERE)

    def render(fmt, data):
        resolver = project_config.resolver(root)
        folder = tempfile.mkdtemp(prefix="openhora-export-")
        try:
            source, out = os.path.join(folder, "input"), os.path.join(folder, "out")
            os.mkdir(out, 0o700)
            fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            try:
                done = resolver.call(EXPORTER_CLASS, "render", ["--format", fmt, "--input", source, "--out-dir", out], root=root,
                                     timeout=EXPORTER_TIMEOUT, env=resolver.provider_environment(EXPORTER_CLASS, None, ()))
            except resolver.ProviderCallError as e:
                if e.kind == "not-configured":
                    raise steps.StepFailure("not_configured", "renderer", "exporter",
                                            "build the renderer's image: python3 providers/exporter/container.py build --confirmed") from None
                raise steps.StepFailure("render_failed", "renderer", "exporter") from None
            tools = done.get("tool_versions") if isinstance(done, dict) and isinstance(done.get("tool_versions"), dict) else {}
            return {"output": _read_output(out, f"output.{fmt}"), "tool_versions": tools}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    return render


def _executor(fmt: str):
    def render(ctx: steps.Context, state: dict) -> dict:
        data = _read_input(ctx)
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
