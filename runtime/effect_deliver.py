#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of a video's delivery (package V1b1-3): approving the document of runtime/deliver_document.py marks that exact rendered file downloadable, once. Nothing is
published, nothing is sent, and no provider is called: the effect is the media store's own mark (runtime/media.py `mark_delivered`), the one writer of a delivery (limit L67).

It is registered under the side-effect word `deliver` (runtime/effects.py KINDS; contracts/environment.md) and is the STEP path of an effect, like the task list's
(runtime/effect_tasks.py): a step task of the kind `media` writes the delivery document and opens an `effect` decision whose hash is the document's. The mark is made in one place,
`execute`, which runtime/ops_step_effects.py calls from the operation `approve` and nowhere else. What this kind exposes, besides the names of runtime/deliver_document.py (`check`,
`title`, `body`, `describe`, `summary`, `on_cards`):

    GATE, POLICY, STEP   False and False (no skill's gate names `deliver`, and no standing approval covers it: a delivery is approved by the hash of its exact document); True
    PROVIDER_CLASS       "" (no provider: a str, as runtime/tests/test_effects.py asks of every kind)
    NOTHING_DONE         "nothing was delivered": how a refusal of the approval starts
    preflight(cfg, doc, root)   the render is still kept ((exit code, sentence) or None); it does not hash, `execute` does
    caller(cfg, root)    None
    idempotency_key(doc, default)   the default: a delivery is idempotent by its record (a second mark of the same render changes nothing)
    APPROVAL_GROUP       the policy group that lets a messaging app approve this kind (`approve-effect-deliver`; decision 14)

Execution (`execute`). The document was read by the approved hash before this runs, so a changed document never reaches it. The render's file is hashed again under the recording's
lock: a render whose bytes changed after the document named it is `stale` (the decision is answered by code, and the task goes back to the step that renders), and a recording that
another render was delivered for is a `deviation`.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deliver_document  # noqa: E402
import effects  # noqa: E402
import media  # noqa: E402
from deliver_document import WORD, title, body, describe, summary, on_cards  # noqa: E402,F401  (the pure half, re-exported)

STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a delivery: every one is approved by the hash of its exact document
PROVIDER_CLASS = ""      # no provider: the effect is the store's own mark (runtime/media.py mark_delivered); a str, as test_effects asks
APPROVAL_GROUP = "approve-effect-deliver"      # the group a project's policy grants to let a messaging app approve a delivery (decision 14)
NOTHING_DONE = "nothing was delivered"      # the words ops_step_effects.py starts a refusal with
GONE = "nothing was delivered: the render is no longer kept (the retention removed it); start the task again"
STALE_ANSWER = "The render changed after it was shown; it will be rendered again and shown for a new approval."


def check(doc) -> dict:
    """The document, or an EffectError of kind deviation: a delivery document that is not well formed is never approved."""
    try:
        return deliver_document.check(doc)
    except ValueError:
        raise effects.EffectError("deviation", "the delivery document is not well formed") from None


def preflight(cfg: dict, doc: dict, root: str):
    """(exit code, sentence) when the render the document names is no longer kept, else None. It does not hash the file: `execute` does."""
    try:
        media.path_of(cfg["data_dir"], doc["recording"], doc["video"]["name"])
    except media.MediaError:
        return 1, GONE
    return None


def caller(cfg: dict, root: str):
    """No provider is called."""
    return None


def idempotency_key(doc: dict, default: str) -> str:
    return default


def execute(doc: dict, approval: dict, call, key: str, work_dir: str, project=None) -> dict:
    """Mark the render delivered through the store, after the store hashes it again. `stale` when the file changed (with the answer a person reads), `deviation` when another
    render of this recording was delivered already."""
    video = doc["video"]
    try:
        media.mark_delivered(work_dir, doc["recording"], sha256=video["sha256"], task_id=doc["task"], pending_id=approval.get("pending_id"), now=time.time())
    except media.MediaError as e:
        if e.code == "stale":
            err = effects.EffectError("stale", "the render changed after it was shown")
            err.answer = STALE_ANSWER
            raise err from None
        if e.code == "delivered":
            raise effects.EffectError("deviation", "another render of this recording was delivered already") from None
        raise effects.EffectError("provider", "the delivery could not be recorded") from None
    return {"delivered": video["sha256"], "recording": doc["recording"]}
