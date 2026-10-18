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

  {"source": "<source id>", "file": "<a name>", "sha256": "<its hash>"}       import the file of that name from the task's file drop
  {"source": "<source id>", "url": "<a Notion page's address or id>"}         import that page
  {"source": "<source id>"}                                                   refresh: a Notion source reads its page again; a file
                                                                              source checks the newest version against its hashes
                                                                              a Drive source asks Drive for the file's version and reads
                                                                              it only when it moved (P7)
                                                                              a mail or calendar source (RT-1) reads its window again: a new
                                                                              version only when the listing changed or the day did; this is how a
                                                                              routine keeps a snapshot younger than the 26 hours limit L52 allows
                                                                              an unattended task. The arguments hold no query, box, window or
                                                                              calendar: those are fixed by the source's origin, which only the
                                                                              person sets (limit L51)

A file is never read from an arbitrary path: the task reads the plain name it is given from its own file drop,
`.workbench-local/drop/<task id>/` (runtime/drop.py: a regular file, no link, no credential in it, put there by the person with
`hand-over --task <id> --file <path>`), and only when its sha256 is the one the plan carries. A file that changed since the plan was
approved stops the task (`file_changed`): the person looks at it and plans again, and no other bytes are imported.

The kind is `unattended`: a routine or a round may start it without the person (a refresh is a routine's target, decision D12). The
person's brake still stops it (`set-mode --agent runtime --mode stopped`).

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
import hashlib  # noqa: E402
import drop  # noqa: E402
import ops_core as core  # noqa: E402  (read as core.<name>)
import ops_sources  # noqa: E402
import sources  # noqa: E402
import steps  # noqa: E402

KEYS = ("source", "file", "url", "sha256")
SHA256 = re.compile(r"[0-9a-f]{64}")
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
    if (args.get("file") is None) != (args.get("sha256") is None):
        raise steps.StepFailure("bad_args", "sha256")        # a file comes with the hash of the bytes the plan approved
    if args.get("file") is not None:
        file = args["file"]
        if not isinstance(file, str) or not drop.NAME.fullmatch(file):
            raise steps.StepFailure("bad_args", "file")
        if not isinstance(args["sha256"], str) or not SHA256.fullmatch(args["sha256"]):
            raise steps.StepFailure("bad_args", "sha256")
        out["file"], out["sha256"] = file, args["sha256"]
    if args.get("url") is not None:
        url = args["url"]
        if not isinstance(url, str) or not url.strip() or CONTROL.search(url) or len(url) > 1024:
            raise steps.StepFailure("bad_args", "url")
        out["url"] = url.strip()
    return out


HAND = "hand the file over: hand-over --task <id> --file <path>"


def _dropped(ctx: steps.Context) -> bytes:
    """The bytes of the file the plan names, read once from this task's drop and checked against the plan's hash: the same bytes are
    then imported, so a file swapped after the check changes nothing. The drop folder is opened from the project's root one part at a
    time with O_NOFOLLOW (drop.open_folder), so a link at `.workbench-local`, `drop` or `<task id>` is refused; the file is looked at
    through the folder's descriptor before it is opened, so that a pipe, a device or a link is refused without being opened (opening a
    FIFO waits for a writer), opened with O_NOFOLLOW | O_NONBLOCK and looked at again through the descriptor (the same file), and at
    most drop.MAX_BYTES are read (drop.read_file). StepFailure: file_missing (not there, not a regular file, a link anywhere on the
    way), file_too_large, file_changed (another hash)."""
    missing = steps.StepFailure("file_missing", "file", "", HAND)
    try:
        dirfd = drop.open_folder(ctx.project, ctx.task_id)
    except (OSError, drop.DropError):
        raise missing from None
    try:
        data = drop.read_file(dirfd, ctx.args["file"], drop.MAX_BYTES)
    except (OSError, drop.DropError):
        raise missing from None
    finally:
        os.close(dirfd)
    if len(data) > drop.MAX_BYTES:
        raise steps.StepFailure("file_too_large", "file")
    if hashlib.sha256(data).hexdigest() != ctx.args["sha256"]:
        raise steps.StepFailure("file_changed", "file", "", "the file is not the one the plan approved: plan the ingest again")
    return data


def _ingest(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    try:
        if args.get("file") is not None or args.get("url") is not None:
            if args.get("file") is not None:
                done = ops_sources.import_bytes(ctx.project, args["source"], args["file"], _dropped(ctx))
            else:
                done = ops_sources.source_import(ctx.project, args["source"], url=args.get("url"))
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
    unattended=True,
    brings_source=True,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
