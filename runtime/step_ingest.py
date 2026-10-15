#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `ingest`: bring one version of a source into the project, as a task (package P5, the engine's second consumer).

One step, `ingest`, over the operations of runtime/ops_sources.py, which are runtime/sources.py `import_version` and `recheck`: the
file or the Notion page is read, converted to text in a container with no network, scanned for credentials and kept as a new
immutable version in the sources folder. The task writes nothing in the project: its footprint is empty, so it never waits for a task
that writes a file and no task waits for it. Nothing it runs is written into the sources folder except through `import_version`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will run):

  {"source": "<source id>", "file": "<absolute path of a file of yours>"}      import that file as a new version
  {"source": "<source id>", "url": "<a Notion page's address or id>"}         import that page
  {"source": "<source id>"}                                                   refresh: a Notion source reads its page again; a file
                                                                              source checks the newest version against its hashes

The result recorded is closed words and numbers: the source id, the version, whether a version was made. A refusal is recorded as the
closed code of the exit of the operation (`usage`, `folder`, `refused`), never its sentence: the person sees the sentence by running the
same import in the terminal (`source-import`), which the note says.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ops_core as core  # noqa: E402  (read as core.<name>)
import ops_sources  # noqa: E402
import sources  # noqa: E402
import steps  # noqa: E402

KEYS = ("source", "file", "url")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
NEXT = "run the same import with source-import in the terminal to read the reason"
CODES = {2: "usage", 3: "folder"}       # the exit code of an operation's refusal (ops_sources.CODES) as a closed word


def check(args) -> dict:
    """The arguments of an ingest, checked: a source id, and at most one of an absolute file path and a Notion address."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise steps.StepFailure("bad_args", "args")
    try:
        source = sources.check_id(args.get("source"))
    except sources.SourcesError:
        raise steps.StepFailure("bad_args", "source") from None
    out = {"source": source}
    if args.get("file") is not None and args.get("url") is not None:
        raise steps.StepFailure("bad_args", "file")
    if args.get("file") is not None:
        file = args["file"]
        if not isinstance(file, str) or not os.path.isabs(file) or CONTROL.search(file) or len(file) > 1024:
            raise steps.StepFailure("bad_args", "file")
        out["file"] = file
    if args.get("url") is not None:
        url = args["url"]
        if not isinstance(url, str) or not url.strip() or CONTROL.search(url) or len(url) > 1024:
            raise steps.StepFailure("bad_args", "url")
        out["url"] = url.strip()
    return out


def _ingest(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    try:
        if args.get("file") is not None or args.get("url") is not None:
            done = ops_sources.source_import(ctx.project, args["source"], file=args.get("file"), url=args.get("url"))
        else:
            done = ops_sources.source_refresh(ctx.project, args["source"])
    except core.OpsError as e:
        raise steps.StepFailure(CODES.get(e.code, "refused"), "source", "sources", NEXT) from None
    made = bool(done.get("imported") or done.get("refreshed"))
    return {"source": args["source"], "version": done.get("version") if isinstance(done.get("version"), int) else None,
            "made": made, "unchanged": bool(done.get("unchanged")) or not made}


KIND = steps.register(steps.Kind(
    name="ingest",
    order=("ingest",),
    executors={"ingest": _ingest},
    footprint=lambda args: (),
    check=check,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
