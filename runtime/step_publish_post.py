#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `publish-post`: publish one drafted post now, as an external effect the person approves (package PUBLISH-EFFECT). The kind
prepares; it never publishes. Two steps, as in a write-back and an e-mail:

  prepare   reads the content file (a regular file under docs/marketing/content/, no link on the way, never the sources folder) and refuses a post
            whose `- Status:` line says blocked; asks the read-only publisher service for the provider the platform resolves to, for the
            provider's check (the token), and for the post as the publishing skill's own script (skills/mkt-publish/scripts/payload.py) builds it
            together with the provider's dry run of it; refuses a key the provider's ledger already holds (published by this path or by the skill's
            job, or left pending); checks that the image, when there is one, is a file of the project; and writes the effect document
            (runtime/publish_document.py) through the effect-files service to <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a
            0700 folder.
  publish   the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the effect document
            and whose body shows the platform, that it publishes now and not at the slot, the post and its first comment whole, the image by name,
            size and hash, and the provider's dry run; the task waits. The person approves the hash in the terminal or on the page (any other
            channel is refused, unless the project's policy grants it, and a post with an image is never whole on a messaging card), and then
            runtime/ops_step_effects.py calls the effect module (runtime/effect_publish.py), which builds the post again with the same script,
            compares it with the document (another text, comment or image is `stale`: nothing is published and the task starts over), and
            publishes once under the key the publishing skill uses.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will be asked about):

  {"post": "docs/marketing/content/<name>.md", "platform": "<platform>"}

The platform is the name the publisher's class takes (`publisher:<platform>`) and the platform's data file is named after (shared/references/platforms/
<platform>.json); it is lower-cased. Nothing here names a platform. One post per decision; the slot's time is shown, never waited for (scheduling
stays with the publishing skill).

Limit L30, in the structure of this file: it imports no module that calls a provider or runs a script. What it needs of the publisher and of the data
folder it asks of `ctx.services` (runtime/ops_step_seams.py), where `publisher` has a check and a dry run and no way to publish, and `effect_files`
writes and reads the effect document and does not execute it. The only code that publishes is runtime/effect_publish.py `execute`, which this
file cannot reach.

The kind is not `unattended`: a post goes out when the person starts it and ends at the person's approval. It writes no file of the project (its
footprint is empty).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import publish_document  # noqa: E402
import steps  # noqa: E402

KEYS = ("post", "platform")
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed", "refused": "refused", "payload_refused": "payload_refused",
                 "ledger_differs": "ledger_differs"}
LEDGER_NEXT = ("the publisher's ledger is named differently by your environment or by a scheduled job for this key than by this path: make them one "
               "file (providers/publisher/README.md), then start the task again")
GATE_STEP = "publish"
REFUSED_NEXT = ("the publishing skill's payload builder refused this post (a limit of the platform, a missing block or time, an image it does not take): "
                "run `skills/mkt-publish/scripts/payload.py build` by hand on the file to read why, fix the file, and start the task again")
TOKEN_NEXT = ("set up the publisher for this platform, or renew its token (the provider's auth.py, run by you; providers/publisher/README.md), then "
              "start the task again")


def check(args) -> dict:
    """The arguments of a publish-post, checked and normalised (the platform in lowercase)."""
    if not isinstance(args, dict) or set(args) != set(KEYS):
        raise steps.StepFailure("bad_args", "args", "", "give the post and the platform")
    post, platform = args.get("post"), args.get("platform")
    try:
        publish_document.content_key(post)
    except Exception:      # an EffectError of the document: the path is not a post's file
        raise steps.StepFailure("bad_args", "post", "", f"give a file {publish_document.CONTENT_DIR}<name>.md, with a name of lowercase letters, "
                                "digits, dots and hyphens") from None
    if not isinstance(platform, str) or not publish_document.PLATFORM.fullmatch(platform.strip().lower()):
        raise steps.StepFailure("bad_args", "platform", "", "give the platform's name: lowercase letters, digits and hyphens")
    return {"post": post, "platform": platform.strip().lower()}


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
        code = SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed")
        raise steps.StepFailure(code, "publisher", "publisher", REFUSED_NEXT if code == "payload_refused" else LEDGER_NEXT if code == "ledger_differs" else
                                TOKEN_NEXT if code == "not_configured" else "") from None


def _read(ctx: steps.Context, rel: str, limit: int, field: str, what: str) -> bytes:
    """A file of the project, read with steps.read_file (no link anywhere on the way, never the sources folder, a regular file). StepFailure:
    `<what>_missing`, `<what>_too_large`, protected_path, path_unsafe."""
    try:
        return steps.read_file(ctx, rel, limit)
    except steps.StepFailure as e:
        code = {"missing": f"{what}_missing", "too_large": f"{what}_too_large"}.get(e.code, e.code)
        raise steps.StepFailure(code, field, "", "write the file first, then start this task" if code.endswith("_missing") else "") from None


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    reader, files = _service(ctx, "publisher"), _service(ctx, "effect_files")
    platform, content = args["platform"], args["post"]
    raw = _read(ctx, content, publish_document.CONTENT_MAX, "post", "post")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise steps.StepFailure("post_not_text", "post") from None
    facts = publish_document.header_facts(text)
    if facts["blocked"]:
        raise steps.StepFailure("post_blocked", "post", "", "the drafting step marked this post blocked: fix the file, or leave it unpublished")
    provider = _asked(reader.provider, platform)
    ready = _asked(reader.check, platform)
    if not isinstance(ready, dict) or ready.get("ready") is not True:
        raise steps.StepFailure("not_configured", "publisher", "publisher", TOKEN_NEXT)
    expires = ready.get("token_expires_at")
    shown = _asked(reader.preview, content, platform)
    recorded = shown.get("recorded")
    if recorded == "published":
        raise steps.StepFailure("already_published", "post", "publisher", "this key is published already, by this path or by the publishing skill: "
                                "there is nothing to approve")
    if recorded == "pending":
        raise steps.StepFailure("outcome_unknown", "post", "publisher", "an earlier attempt under this key left its outcome unknown: look at the "
                                "profile, then settle the key with the provider's resolve verb (providers/publisher/README.md)")
    post = shown["post"]
    image = post["image"]
    if image is not None:     # the image is a file of the project that the person can look at: read again here, with the engine's reader
        data = _read(ctx, image["source"], publish_document.IMAGE_MAX, "image", "image")
        if publish_document.sha(data) != image["sha256"]:
            raise steps.StepFailure("image_changed", "post", "", "the image changed while the post was prepared: start the task again")
    try:
        doc = publish_document.document(task_id=ctx.task_id, provider=provider, platform=platform, content=content, slot=post["at"], text=post["text"],
                                        comment=post["comment"], image=image, checks=facts["checks"],
                                        token_expires_at=expires if isinstance(expires, str) and expires else None, ledger=shown["ledger"],
                                        dry_run=shown["dry_run"])
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "post", "", str(getattr(e, "reason", ""))[:200]) from None
    if doc["idempotency_key"] != post["key"]:
        raise steps.StepFailure("payload_refused", "post", "publisher", REFUSED_NEXT)
    written = _asked(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)
    return {"effect_sha256": written, "characters": len(doc["text"]), "first_comment": doc["comment"] is not None, "image": image is not None}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its preview, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    publish_document.check(doc)
    return {"title": publish_document.title(doc)[:200], "body": publish_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": publish_document.summary(doc)}}


KIND = steps.register(steps.Kind(
    name="publish-post",
    order=("prepare", GATE_STEP),
    executors={"prepare": _prepare},
    gates={GATE_STEP: steps.Gate(word=publish_document.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
