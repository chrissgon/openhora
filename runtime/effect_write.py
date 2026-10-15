#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of writing a document back to the platform that holds the project's documents (package P8, decision D17,
direction 2): the text a step task prepared replaces, whole, a document that lives on the platform (a Notion page today), after the
person approved the exact content.

It is registered under the side-effect word `write` (runtime/effects.py KINDS; contracts/environment.md) and is the third path an
effect takes, after the gate path (a skill's confirmation gate, a change set committed) and the policy path (a standing approval):
the STEP path. A step task of the kind `write-back` (runtime/step_write_back.py) reads the target, writes this module's document
and opens an `effect` decision whose hash is the document's; nothing in the engine or in the kind writes to the platform. The
write happens in one place, `execute`, which runtime/ops_step_effects.py calls from the operation `approve` and nowhere else, with
the approval the person gave. What a kind module of this path exposes:

    PROVIDER_CLASS, GATE, POLICY, STEP   the class of provider; False and False (no skill's gate names `write`, and no standing
                                         approval covers it); True
    document(...)                        the effect document: what is approved, whole, and the hash of its canonical text
    check(doc)                           the document is in its form (EffectError usage)
    title(doc), body(doc, digest), describe(doc)   what the person reads and the state file's row
    verify(doc, current)                 the target was not edited since it was read (EffectError stale)
    execute(doc, approval, call, key, work_dir)    the write: refuses unless the approval is of this document's hash

The document. `effect` ("write"), `task` (the step task that prepared it), `provider` (the name the project's documents object
carries: the write is refused if the configuration names another now), `target` ({"id": the document's identifier on the platform,
"path": the project-relative Markdown path the provider titles it by}), `base` ({"text_sha256": the sha256 of the text the target
held when the task read it, "version": the platform's opaque version then}), `content` (the Markdown to write, the exact text),
`content_sha256` and `bytes`. The target's id is inside the document and so inside the hash the person approves (finding S9): a
document aimed at another target has another hash, and the approval of the first covers nothing of the second.

Not edited since it was read. The platform's version is rounded and may not move for a small edit (documents.py N1), so the guard is
the text: just before the write the target is read again, and its text must have the sha256 the task recorded. A text that differs
is `stale` and nothing is written, with two exceptions the same read tells apart. If the text is exactly what this write would leave
(the provider's dry run prints the sha256 of its own round trip of the content, `expected_sha256`), an earlier attempt of this
approval landed and its answer was lost: nothing is written again and the write is recorded as replayed. And if the write call itself
fails, nobody knows whether the page was replaced (a lost answer; a replace that appended the new blocks and failed before deleting the
old): the effect says `unknown`, stays open, and approving again reads the page first. A `stale` effect is answered with the reason
and the step task starts over from the step that reads, so the person is asked again about the page as it is now; a page left half
written by a failed replace matches neither text and comes back this way, with the message saying that it may be an earlier attempt.
A target that cannot be read is a provider failure: nothing is written. Between the read and the write is the platform's own gap; the
write replaces the whole document and merges nothing (the documents contract), so the gap is as wide as a call and is said here.

Which platform. Nothing here names one: the provider is the class `integration:documents` the project's configuration chose, and
`read` and `write` are two verbs of its contract (providers/CONTRACT.md). A provider that cannot write answers exit 2 and the effect
fails with nothing written (the Google Drive provider is sources-only today).

Usage (a library): python3 runtime/effect_write.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402

PROVIDER_CLASS = "integration:documents"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a write-back: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
from write_document import (CONTENT_MAX, DOC_PATH, KEYS, PROVIDER, SHA256, TARGET_ID, WORD, body, check, describe, document,  # noqa: E402,F401
                            sha, summary, title)  # the pure half, re-exported: the names of an effect kind of the step path


def verify(doc: dict, current: dict, expected=None) -> str:
    """Where the target stands against the document, from what the provider's `read` printed just now (`current`): "unchanged" when
    its Markdown has the sha256 the task recorded (go on and write), "written" when it is exactly what this write leaves (the sha256
    of the provider's own round trip of this content, `expected()`: an earlier attempt of this approval landed and its answer was lost,
    so there is nothing to write), else EffectError stale (an edit, or an earlier attempt that did not finish; the message says both).
    EffectError provider when the answer holds no text."""
    text = current.get("markdown") if isinstance(current, dict) else None
    if not isinstance(text, str):
        raise effects.EffectError("provider", "the provider's read printed no text for the target")
    now = sha(text)
    if now == doc["base"]["text_sha256"]:
        return "unchanged"
    if expected is not None and now == expected():
        return "written"
    raise effects.EffectError("stale", "the document is not the one the task read, and not the one this write would leave: it was edited, "
                                       "or an earlier attempt of this write did not finish")


def execute(doc: dict, approval: dict, call, key: str, work_dir=None) -> dict:
    """The write, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope
    action, status pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation).
    Then the document is checked again and the target is read and compared (verify): its text as the task read it, the write is made;
    its text as this write would leave it (a replay: the answer of an earlier attempt was lost, or the provider replaced the page and
    then failed to say so), nothing is written and the write is recorded as replayed; anything else is stale and nothing is written.
    The provider's `write` is called with --confirmed on a private file holding the exact content; if that call fails the outcome is
    unknown (EffectError unknown): the page may or may not hold the content, and approving again reads it first. `call(verb, args)` is
    the seam: the provider's one JSON object, or EffectError. Returns {"written": True, "id", "version", "bytes", "content_sha256",
    "replayed"}."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is written")
    check(doc)
    target = doc["target"]
    folder = tempfile.mkdtemp(prefix="openhora-write-back-", dir=work_dir)
    try:
        path = os.path.join(folder, "content.md")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(doc["content"].encode("utf-8"))
        args = ["--id", target["id"], "--path", target["path"], "--markdown-file", path, "--idempotency-key", key]

        def expected():
            would = call("write", args + ["--dry-run"])
            sha_found = (would.get("would") or {}).get("expected_sha256") if isinstance(would, dict) else None
            if not isinstance(sha_found, str) or not SHA256.fullmatch(sha_found):
                raise effects.EffectError("provider", "the provider's dry run printed no expected hash for this content")
            return sha_found

        current = call("read", ["--id", target["id"]])
        if verify(doc, current, expected) == "written":
            return {"written": True, "id": target["id"], "version": current.get("version") if isinstance(current.get("version"), str) else None,
                    "bytes": doc["bytes"], "content_sha256": doc["content_sha256"], "replayed": True}
        try:
            written = call("write", args + ["--confirmed"])
        except effects.EffectError as e:
            raise effects.EffectError("unknown", f"the write call failed ({e.reason}): the document may or may not hold the content now") from None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(written, dict) or not isinstance(written.get("id"), str):
        raise effects.EffectError("unknown", "the provider's write printed no document id: the document may or may not hold the content now")
    return {"written": True, "id": written["id"], "version": written.get("version") if isinstance(written.get("version"), str) else None,
            "bytes": doc["bytes"], "content_sha256": doc["content_sha256"], "replayed": False}


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
