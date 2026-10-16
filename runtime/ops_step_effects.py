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
      4. the approval row is recorded (scope action, bound to the decision and the hash), then the effect
         module's `execute` runs: it reads the target again, stops if the target is not the one the task read, and otherwise writes
         once. A write-back (one call) runs holding the project's write lock. An output (a page, a table: minutes) runs under the lock of
         the decision instead (a reject or an answer of the decision is refused while it is held), so that the project's other
         writers are not made to wait; it takes the write lock ONLY for the record at the end;
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

import contextlib
import datetime
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import documents  # noqa: E402
import effects  # noqa: E402
import ops_cancel  # noqa: E402  (the name of the lock of a decision's write, shared with the cancel)
import ops_core as core  # noqa: E402
import ops_waits  # noqa: E402
import project_config  # noqa: E402
import steps  # noqa: E402

OUTPUT_VERBS = ("page-create", "table-create", "rows-append", "table-read", "rows-state")      # the provider verbs of the outputs (runtime/effect_write.py)
OUTPUT_RETENTION_DAYS = 90            # the provider keeps a done key this long (providers/documents/notion.py RETENTION_DAYS); a decision older is refused
OUTPUT_TIMEOUT = 900                  # seconds: 500 rows at 2.8 calls a second take about 3 minutes; 429 waits and the table's listing add to it
EFFECTS_DIR = "step-effects"          # <data_dir>/step-effects/<task id>/<cycle>/effect.json: written by the kind, read here by its hash
STALE_ANSWER = ("Nothing was written by this attempt: the document or table is not the one the task read (it was edited, or an earlier "
                "attempt of this write did not finish: read the page or the table). The task starts over from the step that reads it; "
                "start it again to be asked about it as it is now.")
UNKNOWN_NEXT = ("the outcome is unknown: read the page or the table. The effect stays open, and approving it again with the same hash "
                "reads what is there first and writes only what is missing, recording the write as replayed if everything is there")


def stale_answer(rows_written: int) -> str:
    """What a stale answer says. When an earlier attempt of the same task wrote rows (`rows_written`), it does not say that nothing was
    written: it says how many rows are in the table, that they stay, and that the new preview counts them."""
    if not rows_written:
        return STALE_ANSWER
    return (f"This attempt wrote nothing more, but an earlier attempt of this task already wrote {rows_written} row(s) into the table and "
            "they stay there. The table is not the one the task read (it changed, or an earlier attempt of this write did not finish). "
            "The task starts over from the step that reads the table; start it again: the new preview says how many rows are already "
            "there, and approving it sends only the others.")


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
        try:     # a table of 500 rows is written one call a row, kept to the platform's rate: a long verb gets its own time limit
            return documents.call(cfg, ctx["root"], verb, args, timeout=OUTPUT_TIMEOUT if verb in OUTPUT_VERBS else documents.TIMEOUT)
        except documents.DocumentsError as e:
            raise effects.EffectError("not-configured" if e.kind == "not configured" else "provider", f"{verb}: {e.detail}") from None

    # A write of one page takes a call; an output (a table of 500 rows) takes minutes, so it is not made holding the project's write lock,
    # which every sync, every return of a run and every other writer waits for. What keeps a second writer out is the lock of this
    # decision (taken first, before anything is recorded: two approvals of one decision never write together, and a reject or an
    # answer of the decision waits for it too), the effect lock of the request that ops._approve_effect already holds, the provider's
    # lock of the key, and its ledger (every call of the write is recorded before it is made). The write lock is taken ONLY for the
    # record at the end (the stale answer, or effect_done): the reads above, the approval row and the remote write take none.
    long = bool(getattr(module, "is_long", lambda d: False)(doc))
    if long:
        old = decision_age_days(item)
        if old is not None and old > OUTPUT_RETENTION_DAYS:
            raise core.OpsError(f"nothing was written: this decision is {old} days old, and the provider's ledger forgets a key after "
                                f"{OUTPUT_RETENTION_DAYS} days, so approving it could write twice. Reject it and start the task again", 1)
    key = f"wb-{hashlib.sha256(cfg['store_db'].encode('utf-8')).hexdigest()[:12]}-p{pending_id}"
    with (_decision_lock(cfg, pending_id, APPROVE_BUSY) if long else contextlib.nullcontext()):
        approval = core._stored(ctx, store.approval_add, scope="action", what=" ".join(module.describe(doc).split())[:1000], by="user",
                                payload_sha256=sha256, pending_id=pending_id)
        with (contextlib.nullcontext() if long else core._write_lock(cfg)):
            try:
                result = module.execute(doc, approval, call or default_call, key, cfg["data_dir"])
            except effects.EffectError as e:
                if e.kind == "stale":
                    answer = stale_answer(getattr(e, "rows_written", 0))
                    with core._write_lock(cfg, wait=None):
                        ops_waits.settled(ctx, core._stored(ctx, store.pending_resolve, pending_id, resolution="answered", by="code",
                                                            answer=answer))
                    raise core.OpsError(f"{e.reason}. {answer}", 1) from None
                if e.kind == "unknown":
                    raise core.OpsError(f"{e.reason}; {UNKNOWN_NEXT}", 1) from None
                raise core.OpsError(f"nothing was written: {e.reason}; the effect stays open, and approving it again with the same hash "
                                    f"tries again", 3 if e.kind == "not-configured" else 1) from None
            # The record of a write that landed must not fail because another writer held the project's files for the usual wait
            # (core.WRITE_LOCK_WAIT): it waits for as long as it takes. Every holder is bounded (a provider call has its timeout).
            with core._write_lock(cfg, wait=None):
                done = core._stored(ctx, store.effect_done, pending_id, approval["id"], by="user", result=result)
    return {"done": done, "approval": approval, "doc": doc, "result": result}


APPROVE_BUSY = "is being cancelled with its request or written by another approval; wait for that to end, then approve it again if it is still open"
RESOLVE_BUSY = "is being written; wait for the write to finish, then reject or answer it"


@contextlib.contextmanager
def _decision_lock(cfg: dict, pending_id: int, busy: str = APPROVE_BUSY):
    """The lock of one decision's write (output-<pending id>.lock), taken without waiting: two approvals of the same decision never write
    together, and a reject or an answer of it is refused while one runs (`busy` is the sentence). The file is removed as the last act
    while the lock is held (ops_core._try_lock depends on that order), so none is left behind; a decision still open gets a new one at
    its next approval. Released when the write ends or its process dies."""
    fd = core._try_lock(cfg, ops_cancel.lock_name(pending_id))
    if fd is None:
        raise core.OpsError(f"pending decision {pending_id} {busy}", 1)
    try:
        yield
    finally:
        ops_cancel.release(cfg, pending_id, fd)


@contextlib.contextmanager
def resolution_guard(ctx: dict, item: dict):
    """Held around the rejection or the answer of an `effect` decision a step task opened: while a write of that decision runs it is
    refused ("being written"), because its record would otherwise fail after the page or the table was made, with the decision
    already cancelled. Nothing for any other decision."""
    if item.get("kind") != "effect" or step_effect_of(ctx, item) is None:
        yield
        return
    with _decision_lock(ctx["cfg"], item["id"], RESOLVE_BUSY):
        yield


def decision_age_days(item: dict):
    """How many whole days old a pending decision is, or None when its time cannot be read."""
    try:
        made = datetime.datetime.fromisoformat(str(item.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if made.tzinfo is None:
        made = made.replace(tzinfo=datetime.timezone.utc)
    return max(0, (datetime.datetime.now(datetime.timezone.utc) - made).days)
