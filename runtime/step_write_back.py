#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `write-back`: write a project document over a document on the platform, as an external effect the person approves
(package P8, decision D17 direction 2). The kind prepares; it never writes. Two steps:

  prepare   reads the project file named by `content` (a Markdown file under docs/, a regular file, UTF-8, at most the effect's
            CONTENT_MAX, no credential in it), reads the target through the project's documents provider, records the sha256 of
            the text the target holds now, and writes the effect document (runtime/effect_write.py) to
            <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a 0700 folder. With `source` the page must still be the
            text of that source's newest version (the version the task read): a page edited since stops here (`target_changed`).
  write     the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the
            effect document and whose body shows the content whole, and the task waits. The person approves the hash in the
            terminal or on the page (any other channel is refused), and then runtime/ops_step_effects.py calls the effect module,
            which reads the target once more, writes if its text is the one recorded, and records. A target edited meanwhile
            answers the decision, writes nothing and sends the task back to `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will run):

  {"target": "<the document's identifier on the platform>", "content": "docs/<path>.md"[, "source": "<source id>"]}

The target is an identifier, not an address (a page's address holds its identifier; the provider says what it takes). The content is a
file of the project, never of the sources folder, and the path the provider titles the document by is that same relative path.

The kind is not `unattended`: a write-back starts when the person starts it (run-next, run-step) and ends at the person's approval.
It writes no file of the project (its footprint is empty). It has no `effectful` step: no executor of its own touches the platform.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import documents  # noqa: E402
import ops_core as core  # noqa: E402
import effect_write  # noqa: E402
import effects  # noqa: E402
import ops_step_effects  # noqa: E402
import project_config  # noqa: E402
import sources  # noqa: E402
import steps  # noqa: E402

KEYS = ("target", "content", "source")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def check(args) -> dict:
    """The arguments of a write-back, checked."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise steps.StepFailure("bad_args", "args")
    target, content = args.get("target"), args.get("content")
    if not isinstance(target, str) or not effect_write.TARGET_ID.fullmatch(target):
        raise steps.StepFailure("bad_args", "target", "", "give the document's identifier, not its address")
    if not isinstance(content, str) or not steps.REL_PATH.fullmatch(content) or not content.startswith("docs/") \
            or not content.endswith(".md") or ".." in content.split("/") or content.endswith(".comments.md"):
        raise steps.StepFailure("bad_args", "content", "", "give a Markdown file under docs/")
    out = {"target": target, "content": content}
    if args.get("source") is not None:
        try:
            out["source"] = sources.check_id(args["source"])
        except sources.SourcesError:
            raise steps.StepFailure("bad_args", "source") from None
    return out


def _config(ctx: steps.Context) -> dict:
    return ctx.services.get("config") or project_config.load(ctx.project)


def _read_content(ctx: steps.Context) -> str:
    """The text of the project file named by `content`: opened without following a link, a regular file, at most CONTENT_MAX bytes,
    UTF-8. StepFailure: content_missing, content_too_large, content_not_text."""
    root = os.path.realpath(ctx.project)
    path = os.path.join(root, *ctx.args["content"].split("/"))
    if ctx.protected(path):
        raise steps.StepFailure("protected_path", "content")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise steps.StepFailure("content_missing", "content", "", "write the file first, then start this task") from None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise steps.StepFailure("content_missing", "content")
    with os.fdopen(fd, "rb") as f:
        data = f.read(effect_write.CONTENT_MAX + 1)
    if len(data) > effect_write.CONTENT_MAX:
        raise steps.StepFailure("content_too_large", "content", "", "split the document: a write-back takes a part you can read whole")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise steps.StepFailure("content_not_text", "content") from None


def _call(ctx: steps.Context, cfg: dict):
    """The seam to the documents provider: ctx.services["documents"](verb, args) in a test, else runtime/documents.py."""
    seam = ctx.services.get("documents")
    if seam is not None:
        return seam

    def call(verb, args):
        try:
            return documents.call(cfg, os.path.dirname(HERE), verb, args)
        except documents.DocumentsError as e:
            raise steps.StepFailure("provider_failed" if e.kind != "not configured" else "not_configured", "target", "documents") from None
    return call


def _source_sha(ctx: steps.Context):
    """The sha256 of the converted text of a source's newest version (the version the task read), or None: from the store."""
    def look(source_id):
        found = core.context(ctx.project)
        try:
            latest = found["store"].source_latest(found["conn"], source_id)
        except found["store"].StoreError:
            return None
        return latest["converted_sha256"] if latest else None
    return look


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    cfg = _config(ctx)
    if not documents.enabled(cfg):
        raise steps.StepFailure("not_configured", "documents", "", "configure a documents platform in docs/workbench/runtime.json")
    expired = project_config.bounds_problem(cfg, key=documents.KEY)
    if expired:
        raise steps.StepFailure("bounds_expired", "documents", "", "change expires in docs/workbench/runtime.json and accept the new hash")
    content = _read_content(ctx)
    read = _call(ctx, cfg)("read", ["--id", args["target"]])
    text = read.get("markdown") if isinstance(read, dict) else None
    if not isinstance(text, str):
        raise steps.StepFailure("provider_failed", "target", "documents")
    base = effect_write.sha(text)
    if args.get("source"):
        pinned = (ctx.services.get("source_sha256") or _source_sha(ctx))(args["source"])
        if pinned is None:
            raise steps.StepFailure("source_missing", "source", "", "import the source first")
        if pinned != base:
            raise steps.StepFailure("target_changed", "target", "", "the document was edited after the source was read: import the "
                                    "source again, redo the work, and start a new write-back")
    try:
        doc = effect_write.document(task_id=ctx.task_id, provider=cfg["documents"]["provider"], target_id=args["target"],
                                    path=args["content"], content=content, base_text_sha256=base, base_version=read.get("version"))
    except effects.EffectError as e:
        raise steps.StepFailure("content_refused", "content", "", e.reason[:200]) from None
    cycle_folder = ops_step_effects.effect_dir(cfg, ctx.task_id, _cycle(state))
    os.makedirs(cycle_folder, mode=0o700, exist_ok=True)
    os.chmod(cycle_folder, 0o700)
    path, digest = effects.write(cycle_folder, doc)
    os.chmod(path, 0o600)
    return {"effect_sha256": digest, "content_sha256": doc["content_sha256"], "bytes": doc["bytes"], "base_sha256": base}


def _cycle(state: dict) -> int:
    return int(state.get("cycle", 0))


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its preview, its hash."""
    cfg = _config(ctx)
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = effects.read_document(os.path.join(ops_step_effects.effect_dir(cfg, ctx.task_id, _cycle(state)), effects.EFFECT_FILE), recorded)
    effect_write.check(doc)
    return {"title": effect_write.title(doc)[:200], "body": effect_write.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": effect_write.summary(doc)}}


KIND = steps.register(steps.Kind(
    name="write-back",
    order=("prepare", "write"),
    executors={"prepare": _prepare},
    gates={"write": steps.Gate(word=effect_write.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
