#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The approval of an effect that a step task opened (package P8): the third path an external effect takes, beside a skill's gate and a
standing approval (runtime/effects.py, "for the step path"). A step kind with a gate (runtime/steps.py, Gate) stops at an `effect`
decision whose hash is the hash of an effect document; `approve --sha256` reaches this module through ops.py, which has already checked
that the call came from the terminal or the page (EFFECT_CHANNELS) and that the typed hash is the decision's.

  approve(ctx, item, sha256, call)   in order, under the request's effect lock:
      1. the decision is an `effect` of a step task of a kind this checkout has, whose gate names the effect word the document names;
      2. the effect file is read only if its bytes have the approved hash (effects.read_document); a document edited since the preview,
         or aimed at another target, has another hash and stops here;
      3. the documents configuration allows writing (its bounds have not expired), and names the provider the document names;
      4. the approval row is recorded (scope action, bound to the decision and the hash), then, holding the write lock, the effect
         module's `execute` runs: it reads the target again, stops if the target's text is not the one the task read, and otherwise
         writes once;
      5. only after it wrote is the decision resolved `approved` and the task `done` (store.effect_done, all or nothing).
  A write that is refused leaves the decision open and nothing written. A write call that fails leaves it open with the outcome unknown (the
  page may hold the content; approving again reads it first and records it as replayed if it does). One case answers the decision: a target edited since it was read
  (`stale`) answers the decision with the reason, nothing is written, and the task is ready again to start over from the step that
  reads (runtime/steps.py, Gate.redo), so that the person is asked about the page as it is now. The approval row of that attempt is
  revoked by the store when the decision is answered.

It is a sibling of runtime/ops.py, which calls it from `_approve_effect`. The names every module of the layer shares are read as
`core.<name>`.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import documents  # noqa: E402
import effects  # noqa: E402
import ops_core as core  # noqa: E402
import ops_waits  # noqa: E402
import project_config  # noqa: E402
import steps  # noqa: E402

EFFECTS_DIR = "step-effects"          # <data_dir>/step-effects/<task id>/<cycle>/effect.json: written by the kind, read here by its hash
STALE_ANSWER = ("Nothing was written by this attempt: the document is not the one the task read (it was edited, or an earlier attempt of "
                "this write did not finish: read the page). The task starts over from the step that reads it; start it again to be asked "
                "about the document as it is now.")
UNKNOWN_NEXT = ("the outcome is unknown: read the page. The effect stays open, and approving it again with the same hash reads the page "
                "first and records the write if the content is there")


def effect_dir(cfg: dict, task_id: int, cycle: int) -> str:
    return os.path.join(cfg["data_dir"], EFFECTS_DIR, str(task_id), str(cycle))


def make_effect_dir(cfg: dict, task_id: int, cycle: int) -> str:
    """The folder of a cycle's effect document, made with mode 0700 at every level it creates (os.makedirs would give the parents the
    umask's mode). Returns its path."""
    path = ""
    for part in (EFFECTS_DIR, str(task_id), str(cycle)):
        path = os.path.join(path, part)
        full = os.path.join(cfg["data_dir"], path)
        os.makedirs(full, mode=0o700, exist_ok=True)
        os.chmod(full, 0o700)
    return effect_dir(cfg, task_id, cycle)


def step_effect_of(ctx: dict, item: dict):
    """(task row, the kind, its gate) when the decision is the effect of a step task's gate, else None. Never taken from the payload
    alone: the task must be a step task of a kind this checkout has, with a gate at the step the payload names."""
    store = ctx["store"]
    named = (item.get("payload") or {}).get("step")
    if not isinstance(named, dict):
        return None
    task = core._stored(ctx, store.task_get, item["task_id"])
    if not store.is_step_task(task) or task.get("step_kind") != named.get("kind"):
        return None
    try:
        kind = steps.kind_of(task["step_kind"])
    except steps.StepFailure:
        return None
    gate = kind.gates.get(named.get("step"))
    return (task, kind, gate) if gate is not None else None


def approve(ctx: dict, item: dict, sha256: str, found, call=None) -> dict:
    """Execute the effect of a step task's gate with the person's approval of `sha256`. `found` is step_effect_of's answer. `call(verb,
    args)` is the seam a test replaces: by default the project's documents provider (runtime/documents.py call). Returns {"done": the
    store's answer, "approval": the approval row, "doc": the document, "result": what the effect module returned}. core.OpsError on any
    refusal, with nothing written."""
    store, cfg, pending_id = ctx["store"], ctx["cfg"], item["id"]
    task, kind, gate = found
    payload = item.get("payload") or {}
    try:
        module = effects.module_for(gate.word)
    except effects.EffectError as e:
        raise core.OpsError(f"the effect of pending decision {pending_id} cannot be approved: {e.reason}", 1) from None
    if getattr(module, "STEP", False) is not True:
        raise core.OpsError(f"the effect kind {gate.word!r} is not one a step task opens", 1)
    path = os.path.join(effect_dir(cfg, task["id"], int(payload.get("cycle", 0))), effects.EFFECT_FILE)
    try:
        doc = effects.read_document(path, sha256)
        module.check(doc)
    except effects.EffectError as e:
        raise core.OpsError(f"nothing was written: {e.reason}; the effect stays open", 1) from None
    except ValueError:
        raise core.OpsError(f"the effect document of pending decision {pending_id} cannot be read", 1) from None
    if doc.get("effect") != gate.word or doc.get("task") != task["id"]:
        raise core.OpsError("nothing was written: the effect document is not the one this decision opened", 1)
    if not documents.enabled(cfg):
        raise core.OpsError("the project has no documents platform configured: nothing was written", 3)
    if cfg["documents"].get("provider") != doc.get("provider"):
        raise core.OpsError("nothing was written: the project's documents provider is not the one the effect was prepared for", 1)
    expired = project_config.bounds_problem(cfg, key=documents.KEY)
    if expired:
        raise core.OpsError(f"nothing was written: {expired}", 1)

    def default_call(verb, args):
        try:
            return documents.call(cfg, ctx["root"], verb, args)
        except documents.DocumentsError as e:
            raise effects.EffectError("not-configured" if e.kind == "not configured" else "provider", f"{verb}: {e.detail}") from None

    approval = core._stored(ctx, store.approval_add, scope="action", what=" ".join(module.describe(doc).split())[:1000], by="user",
                            payload_sha256=sha256, pending_id=pending_id)
    key = f"wb-{hashlib.sha256(cfg['store_db'].encode('utf-8')).hexdigest()[:12]}-p{pending_id}"
    with core._write_lock(cfg):
        try:
            result = module.execute(doc, approval, call or default_call, key, cfg["data_dir"])
        except effects.EffectError as e:
            if e.kind == "stale":
                ops_waits.settled(ctx, core._stored(ctx, store.pending_resolve, pending_id, resolution="answered", by="code",
                                                    answer=STALE_ANSWER))
                raise core.OpsError(f"{e.reason}. {STALE_ANSWER}", 1) from None
            if e.kind == "unknown":
                raise core.OpsError(f"{e.reason}; {UNKNOWN_NEXT}", 1) from None
            raise core.OpsError(f"nothing was written: {e.reason}; the effect stays open, and approving it again with the same hash "
                                f"tries again", 3 if e.kind == "not-configured" else 1) from None
        done = core._stored(ctx, store.effect_done, pending_id, approval["id"], by="user", result=result)
    return {"done": done, "approval": approval, "doc": doc, "result": result}
