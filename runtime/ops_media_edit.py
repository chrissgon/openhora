#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The caption edit of a new video, and the way back from the delivery approval (package V1b1-4; the command and the route that call it are V1b2's).

`edit(ctx, task_id, revision, edits)` applies the person's closed edits (runtime/captions.py) to the words of a recording whose task is a step task of the
kind `media` (runtime/step_media.py), in one of two places:

  review   the task waits at the caption review: the edit writes `transcript.edited.json` and then `review.json`, and answers nothing
  gate     the task waits at the delivery approval: the edit does the same and answers the open delivery decision `answered` by code, under the decision's
           lock (a concurrent approval of the same decision waits, or this edit waits for it). The task is then `ready` with no open decision (the store's rule for an answered decision); the kind is not unattended, so when the person
           starts it again the engine finds the answered decision, prepares `remap` again (the gate's redo) and renders again, which gives a new hash
           and a new approval: the old approval can never pass the new gate.

`view(ctx, task_id)` reads the same files and writes nothing: the caption review as the person reads it (words, chunks, proposed retakes, beats, and the revision an edit must name).

A pick of a picture for a slot (`slot_asset`) is one of the candidates the media set found for it (runtime/ops_media_stock.py); a pick that changes voids the approval of the media set, so a picture
that was not approved is never drawn. An edit that changes nothing is refused before anything is written or answered. The files it writes are the person's work: the engine's cleanup never
removes them. An added animation's parameters are checked by the renderer's own checker (`block-params`, through runtime/media_animation.py and
`MediaEngine`), a process on this computer; nothing here reaches the network.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import captions  # noqa: E402
import media_animation  # noqa: E402
import media_stock  # noqa: E402
import ops_core as core  # noqa: E402
import ops_step_effects  # noqa: E402
import ops_step_seams  # noqa: E402
import ops_waits  # noqa: E402
import step_media  # noqa: E402
import steps  # noqa: E402
import workcopy  # noqa: E402

KIND = step_media.KIND.name
BACK_ANSWER = "The captions were changed; the video will be rendered again and shown for a new approval."
WAITING_ONLY = "the captions can be edited only while the video waits at the caption review or at the delivery approval"
TRANSCRIPT, EDITED, REVIEW = "transcript.json", "transcript.edited.json", "review.json"
PROPOSAL_EDL, PROPOSAL_BEATS = "proposal.edl.json", "proposal.beats.json"
PRESETS = ("providers", "renderer", "renderer-presets.json")


def _json(store, rid: str, name: str, default=None):
    try:
        return json.loads(store.read(rid, name).decode("utf-8"))
    except ops_step_seams.StepServiceError as e:
        if e.code == "not_found" and default is not None:
            return default
        raise core.OpsError(f"the file {name} cannot be read ({e.code})", 1) from None
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise core.OpsError(f"the file {name} cannot be read", 1) from None


def _limits(root: str) -> dict:
    """The renderer's own limits on a word, so the review refuses what the renderer would; the defaults of runtime/captions.py when the file cannot be read."""
    try:
        with open(os.path.join(root, *PRESETS), encoding="utf-8") as f:
            found = json.load(f)["limits"]
        return {"word_chars_max": int(found["word_chars_max"]), "words_max": int(found["words_max"])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _candidates(data_dir: str, rid: str) -> dict:
    """{slot: {pick}} of the candidates the media set found, or {} when there is none (every pick is then refused)."""
    try:
        found = media_stock.read_doc(data_dir, rid, media_stock.SET)
    except media_stock.StockError:
        return {}
    rows = found.get("slots") if isinstance(found, dict) else None
    return {r["slot"]: {c["pick"] for c in r.get("candidates") or [] if isinstance(c, dict) and isinstance(c.get("pick"), str)}
            for r in rows or [] if isinstance(r, dict) and isinstance(r.get("slot"), str)}


def _assets(data_dir: str, rid: str, review: dict) -> dict:
    """{slot: {"name", "type", "sha256"}} of the pictures the set fetched for the review's picks (the file facts the view shows), {} when there is none."""
    try:
        found = media_stock.read_doc(data_dir, rid, media_stock.SET)
    except media_stock.StockError:
        return {}
    rows = found.get("assets") if isinstance(found, dict) and found.get("phase") == "fetched" else None
    return {a["slot"]: {"name": "asset-%s.png" % a["sha256"][:12], "type": "png", "sha256": a["sha256"]} for a in rows or []
            if isinstance(a, dict) and isinstance(a.get("slot"), str) and isinstance(a.get("sha256"), str) and review["slot_assets"].get(a["slot"]) == "%s:%s" % (a.get("source"), a.get("item"))}


def _content(edited: dict, review: dict) -> str:
    """The two documents without the revision counters an edit always raises, to tell whether an edit changed anything."""
    one, two = copy.deepcopy(edited), copy.deepcopy(review)
    two.pop("revision", None)
    if isinstance(one.get("facts"), dict):
        one["facts"].pop("revision", None)
    return json.dumps([one, two], sort_keys=True)


STOCK_REPAIR = ("media_not_approved", "asset_changed", "asset_not_approved")      # a Continue that the media set stopped (V9b-3a): the person approves the set or clears the picks, then starts the video again


def stock_repair(task: dict, state: dict) -> bool:
    """Whether the task failed because a pick of the media set is not approved (or a picture changed): the review is passed, the video is stopped before it renders, and the
    person may still choose, approve or clear the pictures. The same words as the review's own edit: `review`."""
    failure = state.get("failure")
    return task["state"] == "failed" and isinstance(failure, dict) and failure.get("code") in STOCK_REPAIR


def _where(ctx: dict, task: dict, state: dict):
    """(mode, the open delivery decision or None): `review` or `gate`, or a refusal when the task waits at neither (a task the media set stopped counts as at the review)."""
    if stock_repair(task, state):
        return "review", None
    if task["state"] != "waiting":
        raise core.OpsError(WAITING_ONLY, 1)
    if steps.step_status(state, "review") == "waiting":
        return "review", None
    if steps.step_status(state, step_media.GATE_STEP) == "waiting":
        want = {"kind": KIND, "step": step_media.GATE_STEP}
        cycle = state.get("cycle", 0)
        open_items = [p for p in core._stored(ctx, ctx["store"].pending_list, "open", task["id"])
                      if (p.get("payload") or {}).get("step") == want and (p.get("payload") or {}).get("cycle", 0) == cycle]
        if open_items:
            return "gate", max(open_items, key=lambda p: p["id"])
    raise core.OpsError(WAITING_ONLY, 1)


def edit(ctx: dict, task_id: int, revision: int, edits: list, *, actor=None) -> dict:
    """Apply `edits` (the closed objects of runtime/captions.py, in the numbering of the revision the person read) to the captions of the video of `task_id`.
    Returns {"task", "mode", "applied": counts, "answered": the decision's id or None}. core.OpsError for every refusal, with nothing written."""
    store, cfg = ctx["store"], ctx["cfg"]
    task = core._stored(ctx, store.task_get, task_id)
    if not store.is_step_task(task) or task.get("step_kind") != KIND:
        raise core.OpsError("this task is not a new video", 1)
    try:
        state = steps.state_of(steps.kind_of(KIND), task.get("step_state"))
    except steps.StepFailure:
        raise core.OpsError("the state of this task cannot be read", 1) from None
    mode, item = _where(ctx, task, state)
    with contextlib.ExitStack() as held:
        if mode == "gate":
            held.enter_context(ops_step_effects.resolution_guard(ctx, item))
        media_store = ops_step_seams.MediaStore(ctx)
        rid = (task.get("step_args") or {}).get("media")
        if not isinstance(rid, str):
            raise core.OpsError("this task names no recording", 1)
        transcript = _json(media_store, rid, TRANSCRIPT)
        try:
            read_edited = captions.check_edited(_json(media_store, rid, EDITED, default=captions.start_edited(transcript)))
            read_review = captions.reconcile(read_edited, captions.check_review(_json(media_store, rid, REVIEW, default=captions.new_review())))
            proposal_edl, proposal_beats = _json(media_store, rid, PROPOSAL_EDL), _json(media_store, rid, PROPOSAL_BEATS)
            edited, review, counts = captions.apply_edits(
                read_edited, read_review, edits, revision=revision, proposals=captions.retake_ranges(proposal_edl),
                beats={r["beat"] for r in proposal_beats.get("report") or [] if r.get("preset")},
                slots={s["slot"] for s in proposal_beats.get("slots") or []}, limits=_limits(media_store.root()),
                animate=media_animation.checker(ctx), stock=_candidates(cfg["data_dir"], rid))
        except captions.CaptionError as e:
            raise core.OpsError(f"refused: {e.code} {e.field}".strip(), 1) from None
        if _content(edited, review) == _content(read_edited, read_review):
            raise core.OpsError("nothing changed: the captions are as they were", 1)
        if workcopy.scan(" ".join(w["text"] for w in edited["words"]).encode("utf-8")):
            raise core.OpsError("refused: credential_in_transcript edits", 1)
        try:
            media_store.write(rid, EDITED, (json.dumps(edited, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            media_store.write(rid, REVIEW, (json.dumps(review, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        except ops_step_seams.StepServiceError as e:
            raise core.OpsError(f"the review could not be written ({e.code})", 1) from None
        if review["slot_assets"] != read_review["slot_assets"]:      # a pick that changed is not the one that was approved
            try:
                media_stock.void_approval(cfg["data_dir"], rid)
            except media_stock.StockError:
                pass
        answered = None
        if mode == "gate":
            with core._write_lock(cfg, wait=None):
                ops_waits.settled(ctx, core._stored(ctx, store.pending_resolve, item["id"], resolution="answered", by="code", answer=BACK_ANSWER))
            answered = item["id"]
    return {"task": task_id, "mode": mode, "applied": counts, "answered": answered}


NOT_READY = "the captions are not ready: the video has not reached the caption review yet"


def _still_name(state: dict):
    """The name of the still the engine made for the face box, or None when none was made."""
    name = ((state["steps"].get("still") or {}).get("result") or {}).get("name")
    return name if isinstance(name, str) and step_media.STILL_NAME.fullmatch(name) else None


def view(ctx: dict, task_id: int) -> dict:
    """The caption review of the video of `task_id` as the page and the terminal read it (`captions-read`). Returns {"task", "media",
    "mode": "review" or "gate" (where an edit would go) or None (no edit is taken now), "still": the still's name or None,
    "view": runtime/captions.py view(...)}. core.OpsError for a task that is not a new video, or one whose proposal is not made yet.
    It writes nothing and takes no lock."""
    task = core._stored(ctx, ctx["store"].task_get, task_id)
    if not ctx["store"].is_step_task(task) or task.get("step_kind") != KIND:
        raise core.OpsError("this task is not a new video", 1)
    try:
        state = steps.state_of(steps.kind_of(KIND), task.get("step_state"))
    except steps.StepFailure:
        raise core.OpsError("the state of this task cannot be read", 1) from None
    rid = (task.get("step_args") or {}).get("media")
    if not isinstance(rid, str):
        raise core.OpsError("this task names no recording", 1)
    if steps.step_status(state, "align-proposal") != "done":
        raise core.OpsError(NOT_READY, 1)
    media_store = ops_step_seams.MediaStore(ctx)
    transcript = _json(media_store, rid, TRANSCRIPT)
    try:
        read_edited = captions.check_edited(_json(media_store, rid, EDITED, default=captions.start_edited(transcript)))
        read_review = captions.reconcile(read_edited, captions.check_review(_json(media_store, rid, REVIEW, default=captions.new_review())))
        proposal_edl, proposal_beats = _json(media_store, rid, PROPOSAL_EDL), _json(media_store, rid, PROPOSAL_BEATS)
        shown = captions.view(read_edited, read_review, proposal_edl, proposal_beats, _assets(ctx["cfg"]["data_dir"], rid, read_review))
    except captions.CaptionError as e:
        raise core.OpsError(f"refused: {e.code} {e.field}".strip(), 1) from None
    try:
        mode = _where(ctx, task, state)[0]
    except core.OpsError:
        mode = None
    return {"task": task_id, "media": rid, "mode": mode, "still": _still_name(state), "view": shown}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
