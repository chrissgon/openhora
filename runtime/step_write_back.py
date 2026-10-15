#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `write-back`: write a project document over a document on the platform, as an external effect the person approves
(package P8, decision D17 direction 2). The kind prepares; it never writes. Two steps:

  prepare   reads the project file named by `content` (a Markdown file under docs/, a regular file, UTF-8, at most the effect's
            CONTENT_MAX, no credential in it), reads the target through the read-only documents service, records the sha256 of the
            text the target holds now, and writes the effect document (runtime/write_document.py) through the effect-files service to
            <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a 0700 folder. With `source` the source must be the target's
            own page (`source_not_target` otherwise) and the page must still be the text of that source's newest version, the version
            the task read: a page edited since stops here (`target_changed`).
  write     the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the
            effect document and whose body shows the content whole, and the task waits. The person approves the hash in the
            terminal or on the page (any other channel is refused), and then runtime/ops_step_effects.py calls the effect module,
            which reads the target once more, writes if its text is the one recorded, and records. A target edited meanwhile
            answers the decision, writes nothing and sends the task back to `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will run):

  {"target": "<the document's identifier on the platform>", "content": "docs/<path>.md"[, "source": "<source id>"]}

The target is an identifier, not an address (a page's address holds its identifier; the provider says what it takes). The content is a
file of the project, never of the sources folder, and the path the provider titles the document by is that same relative path.

Limit L30, in the structure of this file. It imports no module that calls a provider: what it needs of the platform and of the data
folder it asks of `ctx.services` (runtime/ops_step_seams.py), where `documents` has `read` and `stat` and no way to write, and
`effect_files` writes and reads the effect document and does not execute it. It reads the project's files with `steps.read_file`. The
only code that writes to the platform is runtime/effect_write.py `execute`, which this file cannot reach.

The kind is not `unattended`: a write-back starts when the person starts it (run-next, run-step) and ends at the person's approval.
It writes no file of the project (its footprint is empty).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import steps  # noqa: E402
import write_document  # noqa: E402

KEYS = ("target", "content", "source")
SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")      # runtime/sources.py SOURCE_ID: a test holds them equal
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed"}


def check(args) -> dict:
    """The arguments of a write-back, checked."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise steps.StepFailure("bad_args", "args")
    target, content = args.get("target"), args.get("content")
    if not isinstance(target, str) or not write_document.TARGET_ID.fullmatch(target):
        raise steps.StepFailure("bad_args", "target", "", "give the document's identifier, not its address")
    if not isinstance(content, str) or not steps.REL_PATH.fullmatch(content) or not content.startswith("docs/") \
            or not content.endswith(".md") or ".." in content.split("/") or content.endswith(".comments.md"):
        raise steps.StepFailure("bad_args", "content", "", "give a Markdown file under docs/")
    out = {"target": target, "content": content}
    if args.get("source") is not None:
        if not isinstance(args["source"], str) or not SOURCE_ID.fullmatch(args["source"]):
            raise steps.StepFailure("bad_args", "source")
        out["source"] = args["source"]
    return out


def _service(ctx: steps.Context, name: str):
    found = ctx.services.get(name)
    if found is None:
        raise steps.StepFailure("not_configured", name)
    return found


def _asked(call, *args):
    """A service call whose failure is a closed code of the step."""
    try:
        return call(*args)
    except steps.StepFailure:
        raise
    except Exception as e:      # the services raise errors that carry a `code`; anything else is a provider failure
        raise steps.StepFailure(SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed"), "target", "documents") from None


def _read_content(ctx: steps.Context) -> str:
    """The text of the project file named by `content`, read with steps.read_file (no link anywhere on the way, never the sources
    folder, a regular file, at most CONTENT_MAX bytes), UTF-8. StepFailure: content_missing, content_too_large, content_not_text,
    protected_path, path_unsafe."""
    try:
        data = steps.read_file(ctx, ctx.args["content"], write_document.CONTENT_MAX)
    except steps.StepFailure as e:
        code = {"missing": "content_missing", "too_large": "content_too_large"}.get(e.code, e.code)
        raise steps.StepFailure(code, "content", "", "write the file first, then start this task" if code == "content_missing" else
                                "split the document: a write-back takes a part you can read whole" if code == "content_too_large" else "") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise steps.StepFailure("content_not_text", "content") from None


def _same_page(page, target) -> bool:
    """Whether the page a source is bound to is the target: both identifiers, dashes and case aside, exactly equal."""
    flat = lambda text: str(text).replace("-", "").lower()
    return isinstance(page, str) and bool(page) and flat(page) == flat(target)


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    reader, files = _service(ctx, "documents"), _service(ctx, "effect_files")
    if not reader.enabled():
        raise steps.StepFailure("not_configured", "documents", "", "configure a documents platform in docs/workbench/runtime.json")
    if reader.problem():
        raise steps.StepFailure("bounds_expired", "documents", "", "change expires in docs/workbench/runtime.json and accept the new hash")
    content = _read_content(ctx)
    read = _asked(reader.read, args["target"])
    text = read.get("markdown") if isinstance(read, dict) else None
    if not isinstance(text, str):
        raise steps.StepFailure("provider_failed", "target", "documents")
    base = write_document.sha(text)
    if args.get("source"):
        pinned = _asked(_service(ctx, "source_pin"), args["source"])
        if pinned is None:
            raise steps.StepFailure("source_missing", "source", "", "import the source first")
        if not _same_page(pinned.get("page"), args["target"]):
            raise steps.StepFailure("source_not_target", "source", "", "the source is not the page this write-back targets")
        if pinned["sha256"] != base:
            raise steps.StepFailure("target_changed", "target", "", "the document was edited after the source was read: import the "
                                    "source again, redo the work, and start a new write-back")
    try:
        doc = write_document.document(task_id=ctx.task_id, provider=reader.provider(), target_id=args["target"], path=args["content"],
                                      content=content, base_text_sha256=base, base_version=read.get("version"))
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "content", "", str(getattr(e, "reason", ""))[:200]) from None
    digest = _asked(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)
    return {"effect_sha256": digest, "content_sha256": doc["content_sha256"], "bytes": doc["bytes"], "base_sha256": base}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its preview, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    write_document.check(doc)
    return {"title": write_document.title(doc)[:200], "body": write_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": write_document.summary(doc)}}


KIND = steps.register(steps.Kind(
    name="write-back",
    order=("prepare", "write"),
    executors={"prepare": _prepare},
    gates={"write": steps.Gate(word=write_document.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
