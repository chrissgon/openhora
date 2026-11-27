#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `media` (package V1b1-4): a recording in the media store becomes a short video the person approves. The order is VD10's:

  take            reads the post (its `- Network:` line gives the platform, which must have a video entry, and it must hold a script) and binds the recording
                  to this task
  transcribe      the transcriber's `transcribe` verb on the recording (dtw timestamps)
  analyse         the renderer's `analyse` verb
  still           a side step: one frame of the recording for the review's face box, while the review is not passed
  retakes         the renderer's `base` on the transcript: the retakes found by rule, a proposal
  align-proposal  the renderer's `align` on the transcript: each beat of the script with its matched words, a proposal
  review          STOP: "Check the captions". The person edits the captions (runtime/ops_media_edit.py), then continues
  remap           the edited transcript is made (or confirmed), hardened and scanned for credentials
  base            the renderer's `base` on the edited transcript, the confirmed retakes cut, the project's theme from its identity
  align           the renderer's `align` on it, the person's anchors over the match, then the person's added animations appended (VD15)
  check           the renderer's `check` (schema, bounds, hardening, credential shapes)
  render          the renderer's `render`: the file `render-<sha12>.mp4`, verified in a fresh container by the renderer itself
  cover           the renderer's `cover`
  verify          the renderer's `verify` on the stored file against the platform's spec
  preview         a side step: the renderer's `preview` of a render larger than a messaging card carries (at most 15 MiB, V3d)
  document        the delivery document (runtime/deliver_document.py) for the exact render, written through the effect-files service
  deliver         the gate (runtime/steps.py, Gate): it opens an `effect` decision whose hash is the hash of the document; approving it marks that
                  render downloadable (runtime/effect_deliver.py, limit L67). Nothing is published. Its redo is `remap`: an answered delivery (the
                  captions were edited, or the render changed) renders again and asks again.
                  The document's preview is the render itself when it is at most 15 MiB, else the side step's copy, else none; a
                  preview is what lets a messaging app show and approve the delivery (decision 14).

Limit L30, in the structure of this file: it imports no module that calls a provider. The engine (`transcriber:speech` and `renderer:video`, a closed
list of verbs) and the store of recordings are asked of `ctx.services` (`media_engine`, `media_store`; runtime/ops_step_seams.py). Every file name
it gives the engine comes from the store (`store.path`), never built from a data folder here. A result recorded in the task's state is closed words,
numbers and hashes: a transcript, a post or a tool's output is never in it, in a note or in a decision's body.

Arguments (checked when the task is planned): {"media": "<16 hex recording id>", "post": "docs/marketing/content/<name>.md"}. The platform is not an
argument: `take` reads it from the post. The kind is not unattended: the review and the gate are the person's, so it starts when the person starts it,
and it writes no file of the project (its footprint is empty). An asset slot (a picture placed in the video) is a keyword, none, or `stock` (V9b-3a): a picture (or, since V9b-5c, a clip)
from the media set the person chose and approved (runtime/ops_media_stock.py, the folder `stock/` of the recording, read here by `store.read` and `store.path`
alone). The engine is given a picture only when it is in the approved set with the set's current hash, its file hashes to the set's sha256 again, and its licence is in the
accepted tuple or it has its own approval for this task, this sha256 and a source the project still uses (limit L76); anything else stops the step.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import captions  # noqa: E402
import deliver_document  # noqa: E402
import publish_document  # noqa: E402
import steps  # noqa: E402
import theme  # noqa: E402
import workcopy  # noqa: E402

KEYS = ("media", "post")
GATE_STEP = "deliver"
ORDER = ("take", "transcribe", "analyse", "still", "retakes", "align-proposal", "review", "remap", "base", "align", "check",
         "render", "cover", "verify", "preview", "document", GATE_STEP)
DEFAULT_TRANSCRIBER_MODEL = "small"      # the model a project that names none transcribes with: a name pinned in providers/transcriber/models.json (the maintainer's word is pending)
DEFAULT_LANGUAGE = "pt"                  # whisper's code for pt-BR; the project's `media.language` when set (OPEN-8)
ID = re.compile(r"[0-9a-f]{16}")         # = media.ID
NETWORK_LINE = re.compile(r"^- Network:\s*([a-z0-9][a-z0-9-]{0,31})\s*$", re.M | re.I)
SCRIPT_BLOCK = re.compile(r"^```script[ \t]*$", re.M)
SHA256 = re.compile(r"[0-9a-f]{64}")
RENDER_NAME = re.compile(r"render-[0-9a-f]{12}\.mp4")
STILL_NAME = re.compile(r"still-[0-9a-f]{12}\.png")
PREVIEW_NAME = re.compile(r"preview-[0-9a-f]{12}\.mp4")
# The patterns the store removes by (media.STILL, media.RENDER, media.COVER, media.PREVIEW), as the strings it compiles.
STILL_PATTERN, RENDER_PATTERN, COVER_PATTERN = r"still-[0-9a-f]{12}\.png", r"render-[0-9a-f]{12}\.mp4", r"cover-[0-9a-f]{12}\.png"
PREVIEW_PATTERN = r"preview-[0-9a-f]{12}\.mp4"
STOCK_SET, STOCK_APPROVED = "stock/set.json", "stock/approved.json"
STOCK_ASSET = "stock/asset-{sha12}.{ext}"      # `.mp4` for a clip, `.png` for a picture
CLIP_TIMING = {"cutaway": {"tail": 0.2, "min_duration": 1.5, "max_duration": None}}      # = providers/renderer/renderer-presets.json presets.cutaway (a test compares)
CLIP_SECONDS_MAX = 10.0      # = providers/renderer/_media.py CLIP_MAX_SECONDS (a test compares)
CLIP_SPARE_FRAMES = 2      # frames a cutaway ends before its clip does, so the engine holds a frame or meets clip_too_short
CLIP_SHORT_NEXT = "start a new video from this recording and pick a clip at least as long as the first word of its beat"
STOCK_KEYS = ("slot", "show", "search", "source", "item", "kind", "licence", "licence_url", "terms_read_on", "author", "title", "page", "licence_claim", "sha256",
              "width", "height", "seconds", "unverified")      # = runtime/media_stock.py ASSET_KEYS (a test compares)
STOCK_LICENCES = ("pexels-license", "pixabay-content-license", "cc0-1.0", "pdm-1.0", "cc-by-4.0", "cc-by-3.0", "cc-by-2.5", "cc-by-2.0")      # = media_stock.LICENCES_ACCEPTED (a test compares)
STOCK_UNVERIFIED = "unverified"      # = media_stock.UNVERIFIED
STOCK_NOT_APPROVED = "Approve the media set, or clear the picks, before you continue."      # = the English of the phrase VID_STOCK_NOT_APPROVED (a test compares)
PAGE_HOST = re.compile(r"https://([A-Za-z0-9.-]{1,253})(?:[/?#:].*)?", re.S)
POST_LIMIT = 2 * 1024 * 1024
COVER_LIMIT = 16 * 1024 * 1024
STILL_DEFAULT_MS = 1500
STILL_LONG_SILENCE = 2.0
STILL_BEFORE_SPEECH_MS = 300
STILL_EDGE_MS = 100
VOCABULARY = "shared/references/video-presets.json"
TRANSCRIPT, ANALYSIS, EDITED, REVIEW = "transcript.json", "analysis.json", "transcript.edited.json", "review.json"
PROPOSAL_EDL, PROPOSAL_BEATS, EDL, BEATS = "proposal.edl.json", "proposal.beats.json", "edl.json", "beats.json"
RENDER_JSON, VERIFY_JSON = "render.json", "verify.json"
TIMEOUTS = {"transcribe": 1800 + 120, "analyse": 900 + 60, "retakes": 300, "align-proposal": 300, "base": 300, "align": 300,
            "check": 300, "render": 2400 + 300, "cover": 300, "still": 300, "verify": 300, "preview": 1200}
SERVICE_CODES = {"not_configured": "not_configured", "engine_failed": "engine_failed", "refused": "engine_refused", "not_found": "recording_missing",
                 "stale": "recording_missing", "taken": "recording_taken", "delivered": "recording_delivered", "unreadable": "recording_unreadable"}
REVIEW_NEXT = "Edit the captions, then continue."
ENGINE_NEXT = {"not_configured": "set up the transcriber and the renderer this project uses (media.renderer in docs/workbench/runtime.json: auto means ffmpeg, the one renderer (the name hyperframes is read as ffmpeg); the README files give the commands, run by you), or name the other renderer there and accept the file, then start the task again"}


def check(args) -> dict:
    """The arguments of a media task, checked."""
    if not isinstance(args, dict) or set(args) != set(KEYS):
        raise steps.StepFailure("bad_args", "args", "", "give the recording and the post")
    rid, post = args.get("media"), args.get("post")
    if not isinstance(rid, str) or not ID.fullmatch(rid):
        raise steps.StepFailure("bad_args", "media", "", "give the recording's id: 16 lowercase hexadecimal characters")
    if not _is_post(post):
        raise steps.StepFailure("bad_args", "post", "", "give a post file docs/marketing/content/<name>.md, with a name of lowercase letters, digits, "
                                "dots and hyphens")
    return {"media": rid, "post": post}


def _is_post(post) -> bool:
    """The rule of the publishing path for a post's file (runtime/publish_document.py content_key): the one source, so the two never differ."""
    try:
        publish_document.content_key(post)
    except Exception:      # an EffectError of the document: the path is not a post's file
        return False
    return True


# --- the services ------------------------------------------------------------------------------------------------------------


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
    except Exception as e:      # the services raise errors that carry a `code`; anything else is an engine failure
        code = SERVICE_CODES.get(getattr(e, "code", ""), "engine_failed")
        raise steps.StepFailure(code, "media", "media", ENGINE_NEXT.get(code, "")) from None


def _handles(ctx: steps.Context):
    return _service(ctx, "media_store"), _service(ctx, "media_engine"), ctx.args["media"]


def _call(ctx: steps.Context, cls: str, verb: str, args: list) -> dict:
    _, engine, _ = _handles(ctx)
    done = _asked(engine.call, cls, verb, args, TIMEOUTS[verb if verb in TIMEOUTS else "check"])
    return done if isinstance(done, dict) else {}


def _json(store, rid: str, name: str, limit=None):
    """A work file as JSON; a file that is not JSON is `step_output_invalid`."""
    data = _asked(store.read, rid, name) if limit is None else _asked(store.read, rid, name, limit)
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise steps.StepFailure("step_output_invalid", name[:40]) from None


def _dump(value) -> bytes:
    return (json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _exists(store, rid: str, name: str) -> bool:
    try:
        store.path(rid, name)
    except Exception as e:
        if getattr(e, "code", "") == "not_found":
            return False
        raise steps.StepFailure(SERVICE_CODES.get(getattr(e, "code", ""), "engine_failed"), "media") from None
    return True


def _read(ctx: steps.Context, rel: str, limit: int, field: str, what: str) -> bytes:
    """A file of the project, read with steps.read_file. StepFailure: `<what>_missing`, `<what>_too_large`, protected_path, path_unsafe."""
    try:
        return steps.read_file(ctx, rel, limit)
    except steps.StepFailure as e:
        code = {"missing": f"{what}_missing", "too_large": f"{what}_too_large"}.get(e.code, e.code)
        raise steps.StepFailure(code, field, "", "write the file first, then start this task" if code.endswith("_missing") else "") from None


def _num(value):
    """A number as the engine gave it, or None: never text, never a boolean."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# --- the pictures of the media set (V9b-3a) ----------------------------------------------------------------------------------


def stock_hash(found: dict) -> str:
    """The sha256 of the set document of a fetched set: the canonical JSON (keys sorted, no spaces) of {"version", "task", "assets" (the STOCK_KEYS of each, by slot),
    "credits"}. The same bytes as runtime/media_stock.py `set_hash(set_document(found))` (a test compares), which this module cannot import (limit L30)."""
    assets = [{k: a.get(k) for k in STOCK_KEYS} for a in sorted(found.get("assets") or [], key=lambda a: a["slot"])]
    doc = {"version": 1, "task": found.get("task"), "assets": assets, "credits": list(found.get("credits") or [])}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _optional_json(store, rid: str, name: str):
    """A work file as JSON, or None when it is not there."""
    try:
        return _json(store, rid, name)
    except steps.StepFailure:
        if not _exists(store, rid, name):
            return None
        raise


def _sources_now(ctx: steps.Context, approved: dict) -> list:
    """The sources the project uses now: `media.stock` when its configuration names it, else the ones the approval was given under (the default list is a property of the
    checkout, which only grows)."""
    found = (ctx.services.get("config") or {}).get("media")
    if not isinstance(found, dict):      # a project with no `media` object uses no stock source
        return []
    listed = found.get("stock")
    return list(listed) if isinstance(listed, list) else [n for n in approved.get("sources") or [] if isinstance(n, str)]


def _stock_assets(ctx: steps.Context, store, rid: str, review: dict, code: str) -> dict:
    """{slot: {"asset", "path"}} of the approved pictures and clips of the review's picks. With no pick it is {} and nothing is read. Otherwise every pick must be an asset of the
    set that was fetched for this task, the set's approval must hold its current hash, each file must hash to the set's sha256 again, and each licence must be in
    STOCK_LICENCES or be `unverified` with its own approval (this task, this sha256, a source the project still uses). Anything else is `StepFailure(code)`: `media_not_approved`
    before the step goes on (Continue), `asset_not_approved` when the engine would be given a picture."""
    picks = review.get("slot_assets") or {}
    if not picks:
        return {}
    found, approved = _optional_json(store, rid, STOCK_SET), _optional_json(store, rid, STOCK_APPROVED)
    refuse = lambda field: steps.StepFailure(code, field, "", STOCK_NOT_APPROVED)      # noqa: E731
    if not isinstance(found, dict) or not isinstance(approved, dict) or found.get("phase") != "fetched" or found.get("task") != ctx.task_id \
            or approved.get("task") != ctx.task_id or approved.get("hash") != stock_hash(found):
        raise refuse("stock")
    sources = _sources_now(ctx, approved)
    own = approved.get("unverified") if isinstance(approved.get("unverified"), dict) else {}
    out = {}
    for slot, pick in sorted(picks.items()):
        asset = next((a for a in found.get("assets") or [] if isinstance(a, dict) and a.get("slot") == slot), None)
        if asset is None or "%s:%s" % (asset.get("source"), asset.get("item")) != pick or not isinstance(asset.get("sha256"), str) or not SHA256.fullmatch(asset["sha256"]):
            raise refuse(slot)
        if asset.get("licence") == STOCK_UNVERIFIED:
            given = own.get(slot)
            if not (isinstance(given, dict) and given.get("sha256") == asset["sha256"] and given.get("task") == ctx.task_id) or asset.get("source") not in sources:
                raise refuse(slot)
        elif asset.get("licence") not in STOCK_LICENCES:
            raise refuse(slot)
        name = STOCK_ASSET.format(sha12=asset["sha256"][:12], ext="mp4" if asset.get("kind") == "clip" else "png")
        try:
            same = _asked(store.sha256, rid, name) == asset["sha256"]
        except steps.StepFailure:
            same = False
        if not same:
            raise steps.StepFailure("asset_changed", slot, "", "fetch the pictures again and approve the media set again")
        out[slot] = {"asset": asset, "path": _asked(store.path, rid, name)}
    return out


def _used_slots(beats: dict) -> set:
    """The slot ids the layouts of a beats.json hold in their parameters: what the renderer will ask a picture for."""
    return {v for e in beats.get("layouts") or [] if isinstance(e, dict) for v in (e.get("params") or {}).values() if isinstance(v, str)}


def _page_parts(page) -> tuple:
    """(host, sha256 of the page text) of an open-web asset's source page, or ("", "") when it holds no https address."""
    found = PAGE_HOST.fullmatch(page) if isinstance(page, str) else None
    return (found.group(1).lower(), hashlib.sha256(page.encode("utf-8")).hexdigest()) if found else ("", "")


# --- the steps ---------------------------------------------------------------------------------------------------------------


def has_script(text: str) -> bool:
    """Whether a post file has a ```script block, the beats of a short video (a text post has none)."""
    return bool(SCRIPT_BLOCK.search(text or ""))


def _post_text(ctx: steps.Context) -> str:
    raw = _read(ctx, ctx.args["post"], POST_LIMIT, "post", "post")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise steps.StepFailure("post_not_text", "post") from None


def _take(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    text = _post_text(ctx)
    found = NETWORK_LINE.search(text)
    if not found:
        raise steps.StepFailure("no_platform", "post", "", "add a `- Network: <platform>` line to the post's header, then start this task again")
    platform = found.group(1).lower()
    data = _asked(store.platform_file, platform)
    if not isinstance(data, dict) or "video" not in data:
        raise steps.StepFailure("platform_has_no_video", "post", "", "this platform has no video entry in its data file")
    if not has_script(text):
        raise steps.StepFailure("no_script", "post", "", "write the script first (the flow short-video), then record it")
    _asked(store.bind, rid, ctx.task_id)
    return {"platform": platform, "bound": True}


def _platform(state: dict) -> str:
    return state["steps"]["take"]["result"]["platform"]


def _transcribe(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    model = _asked(store.setting, "transcriber_model") or DEFAULT_TRANSCRIBER_MODEL
    language = _asked(store.setting, "language") or DEFAULT_LANGUAGE
    raw, out = _asked(store.raw, rid), _asked(store.path, rid, TRANSCRIPT, False)
    _call(ctx, "transcriber:speech", "transcribe", ["--in", raw, "--model", str(model), "--language", str(language), "--timestamps", "dtw",
                                                    "--out", out, "--max-seconds", "300"])
    doc = _json(store, rid, TRANSCRIPT)
    if not isinstance(doc, dict) or not isinstance(doc.get("words"), list) or not doc["words"]:
        raise steps.StepFailure("transcript_invalid", "transcript")
    return {"words": len(doc["words"])}


def _analyse(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    done = _call(ctx, "renderer:video", "analyse", ["--in", _asked(store.raw, rid), "--out", _asked(store.path, rid, ANALYSIS, False)])
    return {"duration": _num(done.get("duration")), "silences": _num(done.get("silences")), "has_audio": done.get("has_audio") is True}


def _still_due(state: dict) -> bool:
    return steps.step_status(state, "analyse") == "done" and steps.step_status(state, "review") != "done"


def still_offset(analysis: dict) -> int:
    """Where in the recording the still is taken, in milliseconds: about a second and a half in, but just before the first speech when the
    recording opens with a long silence, and always inside the recording. A field of the wrong shape is a ValueError."""
    duration = analysis["facts"]["duration"]
    if type(duration) not in (int, float) or not 0 < duration < 10 ** 6:
        raise ValueError("duration")
    at = STILL_DEFAULT_MS
    for silence in analysis.get("silences") or []:
        start, end = silence["start"], silence["end"]
        if type(start) not in (int, float) or type(end) not in (int, float):
            raise ValueError("silences")
        if start <= 0.1:
            if end - start >= STILL_LONG_SILENCE - 1e-6 and end < duration:
                at = int(end * 1000) - STILL_BEFORE_SPEECH_MS
            break
    return max(0, min(at, int(duration * 1000) - STILL_EDGE_MS))


def _still(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    at = still_offset(_json(store, rid, ANALYSIS))
    done = _call(ctx, "renderer:video", "still", ["--in", _asked(store.raw, rid), "--at-ms", str(at), "--out", _asked(store.folder, rid)])
    name = os.path.basename(str(done.get("name") or ""))
    if not STILL_NAME.fullmatch(name):
        raise steps.StepFailure("provider_output_invalid", "still")
    return {"name": name}


def _counts(edl: dict) -> dict:
    norm = edl.get("normalisation") or {}
    return {"retimed": len(norm.get("retimed_words") or []), "unplaced": len(norm.get("unplaced_words") or []),
            "dropped_segments": len(norm.get("dropped_segments") or [])}


def _retakes(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    done = _call(ctx, "renderer:video", "base", ["--transcript", _asked(store.path, rid, TRANSCRIPT), "--analysis", _asked(store.path, rid, ANALYSIS),
                                                  "--out", _asked(store.path, rid, PROPOSAL_EDL, False), "--retakes", "propose"])
    edl = _json(store, rid, PROPOSAL_EDL)
    return {"proposals": len(edl.get("proposals") or []), "cut_by_rule": sum(1 for p in edl.get("proposals") or [] if p.get("default") == "cut"),
            "kept_ranges": _num(done.get("kept_ranges")), "out_seconds": _num(done.get("out_seconds")),
            **_counts(edl)}


def _post_path(ctx: steps.Context) -> str:
    """The post's path for the renderer: read once more through the engine's own reader first, so a link put in place since `take` is refused."""
    _read(ctx, ctx.args["post"], POST_LIMIT, "post", "post")
    return os.path.join(os.path.realpath(ctx.project), *ctx.args["post"].split("/"))


def _beat_args(ctx: steps.Context, transcript: str, out: str) -> list:
    store, _, _ = _handles(ctx)
    flags = ["--post", _post_path(ctx), "--transcript", transcript, "--checker", _asked(store.checker), "--vocabulary", _asked(store.reference, VOCABULARY),
            "--out", out]
    return flags


def _align_proposal(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    done = _call(ctx, "renderer:video", "align", _beat_args(ctx, _asked(store.path, rid, TRANSCRIPT), _asked(store.path, rid, PROPOSAL_BEATS, False)))
    return {"beats": _num(done.get("beats")), "overlays": _num(done.get("overlays")), "layouts": _num(done.get("layouts")),
            "unmatched": len(done.get("unmatched") or [])}


def _below_threshold(beats: dict) -> int:
    return sum(1 for r in beats.get("report") or [] if r.get("preset") and not r.get("matched") and "fallback" not in r)


def _review_decision(ctx: steps.Context, state: dict) -> dict:
    """The question "Check the captions": fixed lines with counts, never a word of the transcript."""
    store, _, rid = _handles(ctx)
    beats = _json(store, rid, PROPOSAL_BEATS)
    still = (state["steps"].get("still") or {}).get("result") or {}
    cut = sum(1 for p in _json(store, rid, PROPOSAL_EDL).get("proposals") or [] if p.get("default") == "cut")
    lines = [f"{state['steps']['transcribe']['result']['words']} words were transcribed.",
             f"{_below_threshold(beats)} beats are below the match threshold.",
             "A still was made for the face box." if STILL_NAME.fullmatch(str(still.get("name") or "")) else "No still was made for the face box.",
             f"{cut} repeated take{'' if cut == 1 else 's'} will be cut by rule; open the captions to keep one.",
             REVIEW_NEXT]
    return {"title": "Check the captions", "body": "\n".join(lines)}


def _load_review(store, rid: str) -> dict:
    if not _exists(store, rid, REVIEW):
        return captions.new_review()
    return captions.check_review(_json(store, rid, REVIEW))


def _remap(ctx: steps.Context, state: dict) -> dict:
    """The edited transcript the later steps read: the person's, or the transcript itself when nothing was edited, hardened word by word and
    scanned for credentials. It removes nothing: the review and the edited transcript hold the person's work."""
    store, _, rid = _handles(ctx)
    _stock_assets(ctx, store, rid, _load_review(store, rid), "media_not_approved")      # Continue: a pick that is not approved (or a web picture with no approval of its own) stops here
    if _exists(store, rid, EDITED):
        edited = captions.check_edited(_json(store, rid, EDITED))
    else:
        edited = captions.start_edited(_json(store, rid, TRANSCRIPT))
    for word in edited["words"]:
        try:
            captions.harden_word(word["text"], "word")
        except captions.CaptionError as e:
            raise steps.StepFailure(e.code, "transcript.edited") from None
    if workcopy.scan(" ".join(w["text"] for w in edited["words"]).encode("utf-8")):
        raise steps.StepFailure("credential_in_transcript", "transcript.edited")
    _asked(store.write, rid, EDITED, _dump(edited))
    return {"words": len(edited["words"]), "edited": sum(1 for w in edited["words"] if w.get("edited")),
            "estimated": sum(1 for w in edited["words"] if w.get("estimated"))}


def _face_args(review: dict) -> list:
    box = (review or {}).get("face_box")
    found = ["--face-box", "{x},{y},{w},{h}".format(**box)] if box else []
    return found


def _choice_args(review: dict) -> list:
    """The flags of the video's own choices (P2a: the caption block and position, the camera's mode, factor and push-in), only those the review holds: no choice, no flag."""
    args = []
    for key, flag in (("block", "--caption-block"), ("position", "--caption-position")):
        if key in review["caption"]:
            args += [flag, review["caption"][key]]
    for key, flag in (("mode", "--zoom"), ("factor", "--zoom-factor"), ("push_in", "--push-in")):
        if key in review["zoom"]:
            args += [flag, str(review["zoom"][key])]
    return args


def _identity(ctx: steps.Context):
    """The text of the project's identity, or None when there is none (steps.read_file's `missing`)."""
    try:
        data = steps.read_file(ctx, "docs/brand/identity.md", theme.IDENTITY_LIMIT)
    except steps.StepFailure as e:
        if e.code == "missing":
            return None
        raise steps.StepFailure(e.code, "identity") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise steps.StepFailure("theme_unreadable", "identity") from None


def _base(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    edited = captions.check_edited(_json(store, rid, EDITED))
    review = _load_review(store, rid)
    flags, record = theme.theme_from_text(_identity(ctx), _asked(store.root), review["theme"] == "default")
    flags, record = theme.with_fonts(flags, record, review["fonts"], _asked(store.root))
    out = _asked(store.path, rid, EDL, False)
    args = ["--transcript", _asked(store.path, rid, EDITED), "--analysis", _asked(store.path, rid, ANALYSIS), "--out", out, "--retakes", "propose"] + _face_args(review) + _choice_args(review) + flags
    done = _call(ctx, "renderer:video", "base", args)
    confirm, by_rule, unmatched = [], 0, 0
    entries = captions.cut_entries(review, _json(store, rid, PROPOSAL_EDL))      # what the person saw as cut: theirs and the rule's
    if entries:
        confirm, lost = captions.confirmed_ids(dict(review, confirmed_retakes=entries), edited, _json(store, rid, EDL).get("proposals") or [])
        unmatched = sum(1 for r in lost if r.get("rule"))
        by_rule = sum(1 for r in entries if r.get("rule")) - unmatched
        lost = [r for r in lost if not r.get("rule")]      # a rule's own proposal that an edit made stale is counted and never cut; it stops nothing
        if lost:      # the retake the person confirmed is no longer there: it is shown unconfirmed when the captions open again
            edited["facts"] = dict(edited.get("facts") or {}, revision=review["revision"] + 1)
            _asked(store.write, rid, EDITED, _dump(edited))
            _asked(store.write, rid, REVIEW, _dump(captions.drop_confirmations(review, lost)))
            raise steps.StepFailure("retake_lost", "retakes", "", "open the caption review again and confirm the retake again")
        if confirm:
            done = _call(ctx, "renderer:video", "base", args + [x for i in confirm for x in ("--confirm", i)])
    edl = _json(store, rid, EDL)
    return {"kept_ranges": _num(done.get("kept_ranges")), "out_seconds": _num(done.get("out_seconds")), "retakes_confirmed": len(confirm), "retakes_by_rule": by_rule, "retakes_unmatched": unmatched,
            "face_box": "set" if review["face_box"] else "default", "theme": {"source": record.get("source"), "reason": record.get("reason")},
            **({"caption": dict(review["caption"])} if review["caption"] else {}), **({"zoom": dict(edl.get("zoom") or review["zoom"])} if review["zoom"] else {}),
            **({"fonts": dict(review["fonts"])} if review["fonts"] else {}), **_counts(edl)}


SLOT_FALLBACK = "a picture"      # the description when the person gave neither `show` nor search words that fit the renderer's limits (`slot_description_min`, `slot_description_max`, read from the vocabulary file)


def _slot_row(store, entry: dict, a: dict) -> dict:
    """The row of beats.json `slots` for an added layout or picture overlay drawn with its approved picture, made as the renderer's aligner makes its own
    (providers/renderer/_align.py build_beats): `slot` is the entry's id, `beat` its beat, `param` the picture parameter, `type` the preset's picture kinds read from the
    vocabulary file joined with `|`, `description` what the person said the picture shows (`show`), else the search words, else SLOT_FALLBACK, inside the vocabulary's limits."""
    where = _asked(store.reference, VOCABULARY)
    try:
        with open(where, "rb") as f:
            vocab = json.loads(f.read())
        spec = vocab["presets"][entry["preset"]]["params"][a["asset_param"]]
        kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        low, high = vocab["limits"]["slot_description_min"], vocab["limits"]["slot_description_max"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise steps.StepFailure("step_output_invalid", "vocabulary") from None
    kinds = [k for k in kinds if k in ("image", "clip")]
    words = next((w.strip() for w in a.get("words") or [] if isinstance(w, str) and low <= len(w.strip()) <= high), SLOT_FALLBACK)
    return {"slot": entry["id"], "beat": entry["beat"], "param": a["asset_param"], "type": "|".join(kinds), "description": words}


def _add_slot_row(store, beats: dict, entry: dict, a: dict) -> None:
    rows = beats.setdefault("slots", [])
    if not any(isinstance(r, dict) and r.get("slot") == entry["id"] for r in rows):
        rows.append(_slot_row(store, entry, a))


def fit_clip_entries(beats: dict, edl: dict, clips: dict) -> list:
    """Lower `word_to` of each entry of `beats` whose slot holds an approved clip, when its beat would outlast the clip, to the last word whose beat fits the clip with
    CLIP_SPARE_FRAMES frames to spare (V9b-5c). `clips` is `{slot: seconds}`. Edits `beats` in place and returns the slots shortened, in the order met. The beat's length is the
    renderer's (providers/renderer/_edl.py resolve_timeline): the last word's end plus `tail`, at least `min_duration`, at most `max_duration`; a later beat or the video's
    end can only shorten it. A preset outside CLIP_TIMING is `asset_type`; a beat whose first word alone does not fit is `clip_too_short`."""
    fps = edl["fps"]
    words = {w["index"]: w for w in edl["words"]}
    order = sorted(words)
    shortened = []
    for bucket in ("layouts", "overlays"):
        for e in beats.get(bucket) or []:
            slot = (e.get("params") or {}).get("asset")
            if slot not in clips:
                continue
            t = CLIP_TIMING.get(e["preset"])
            if t is None:
                raise steps.StepFailure("asset_type", slot)
            frames = int(round(min(clips[slot], CLIP_SECONDS_MAX) * fps))
            room = (frames - CLIP_SPARE_FRAMES) / fps
            start = words[e["word_from"]]["start"]

            def span(to, start=start, t=t):
                end = max(words[to]["end"] + t["tail"], start + t["min_duration"])
                if t["max_duration"]:
                    end = min(end, start + t["max_duration"])
                return end - start

            if span(e["word_to"]) <= room + 1e-9:
                continue
            fits = [i for i in order if e["word_from"] <= i <= e["word_to"] and span(i) <= room + 1e-9]
            if not fits:
                raise steps.StepFailure("clip_too_short", slot, "", CLIP_SHORT_NEXT)
            e["word_to"] = max(fits)
            shortened.append(slot)
    return shortened


def _align(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    edited = captions.check_edited(_json(store, rid, EDITED))
    review = _load_review(store, rid)
    edl, proposal = _json(store, rid, EDL), _json(store, rid, PROPOSAL_BEATS)
    live = {w["index"] for w in edl.get("words") or []}
    anchors, lost = captions.anchors_current(review, edited, live)
    if lost:
        raise steps.StepFailure("anchor_lost", f"beat{lost[0]}", "", "open the caption review again and anchor the beat again")
    placed, gone = captions.animations_current(review, edited, live)
    if gone:
        raise steps.StepFailure("animation_lost", gone[0], "", "open the caption review again and place the animation again, or remove it")
    effects, vanished = captions.effects_current(review, edited, live)
    if vanished:
        raise steps.StepFailure("effect_lost", vanished[0], "", "open the caption review again and place the effect again, or remove it")
    stock = _stock_assets(ctx, store, rid, review, "media_not_approved")
    args = _beat_args(ctx, _asked(store.path, rid, EDITED), _asked(store.path, rid, BEATS, False)) + ["--edl", _asked(store.path, rid, EDL)]
    for slot in proposal.get("slots") or []:      # a slot with an approved picture is left to the renderer; an empty one is the person's choice (`stock` with no pick reads as none), else none
        if slot["slot"] in stock:
            continue
        choice = review["empty_slots"].get(slot["slot"], "none")
        args += ["--empty-slot", f"{slot['slot']}={'none' if choice == 'stock' else choice}"]
    for beat, (first, last) in sorted(anchors.items()):
        args += ["--anchor", f"{beat}={first}-{last}"]
    done = _call(ctx, "renderer:video", "align", args)
    beats = _json(store, rid, BEATS)
    dropped = set(review["dropped_beats"])
    if dropped:
        beats["overlays"] = [e for e in beats.get("overlays") or [] if e.get("beat") not in dropped]
        beats["layouts"] = [e for e in beats.get("layouts") or [] if e.get("beat") not in dropped]
    if placed:
        added = beats.setdefault("overlays", [])
        for a in placed:
            entry = {"id": a["id"], "beat": captions.ANIMATION_BEAT_BASE + int(a["id"][1:]), "preset": a["preset"], "params": a["params"],
                     "block": a["block"], "word_from": a["word_from"], "word_to": a["word_to"], "score": 1.0}
            if a.get("asset_param"):      # an added layout: drawn only with its approved picture (its slot is its id), else not at all
                if a["id"] not in stock:
                    continue
                entry["params"] = dict(a["params"], **{a["asset_param"]: a["id"]})
                _add_slot_row(store, beats, entry, a)
                beats.setdefault("overlays" if a.get("pic_kind") == "overlay" else "layouts", []).append(entry)
                continue
            added.append(entry)
    skipped = set(review["dropped_punches"])      # the script's punches the person dropped stay dropped, whatever the alignment finds
    kept_punches = [p for p in beats.get("punches") or [] if p.get("beat") not in skipped]
    changed = len(kept_punches) != len(beats.get("punches") or [])
    if changed:
        if kept_punches:
            beats["punches"] = kept_punches
        else:
            beats.pop("punches", None)
    if effects:
        beats["effects"] = effects
    transitions, adrift = captions.transitions_current(review, edited, live, beats)      # after the drops and the added animations: a beat anchor names an entry that is left
    if adrift:
        raise steps.StepFailure("transition_lost", adrift[0], "", "open the caption review again and place the transition again, or remove it")
    if transitions:
        beats["transitions"] = transitions
    clips = {s: a["asset"]["seconds"] if isinstance(a["asset"].get("seconds"), (int, float)) and not isinstance(a["asset"]["seconds"], bool) else 0
             for s, a in stock.items() if a["asset"].get("kind") == "clip"}
    trimmed = []
    if clips:      # a cutaway ends with its clip (V9b-5c): the set was made at the edit list's rate, and no beat may outlast its clip
        if (_optional_json(store, rid, STOCK_SET) or {}).get("clip_fps") != edl["fps"]:
            raise steps.StepFailure("clip_fps_changed", sorted(clips)[0], "", "fetch the picks again and approve the media set again")
        trimmed = fit_clip_entries(beats, edl, clips)
    if dropped or placed or changed or effects or transitions or trimmed:
        _asked(store.write, rid, BEATS, _dump(beats))
    found = {"beats": _num(done.get("beats")), "overlays": len(beats.get("overlays") or []), "layouts": len(beats.get("layouts") or []),
             "unmatched": len([b for b in done.get("unmatched") or [] if b not in dropped]), "anchored": len(anchors), "dropped": len(dropped),
             "animations": len(placed), "punches": len(beats.get("punches") or []), "effects": len(effects)}
    if transitions:
        found["transitions"] = len(transitions)      # only a video with a transition adds the key
    if stock:
        found["pictures"] = len(stock)      # the approved pictures; only a video that has some adds the key
    if clips:
        found["clips"], found["clips_shortened"] = len(clips), len(trimmed)      # only a video that draws a clip adds the keys
    return found


def _check(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    done = _call(ctx, "renderer:video", "check", ["--edl", _asked(store.path, rid, EDL), "--beats", _asked(store.path, rid, BEATS),
                                                   "--vocabulary", _asked(store.reference, VOCABULARY),
                                                   "--platform-file", _asked(store.platform_path, _platform(state))])
    return {"ok": True, "out_seconds": _num(done.get("out_seconds"))}


def _blocks_of(done: dict) -> list:
    """The blocks the renderer drew, as the delivery document holds them: a list of {id, sha256} sorted by id, at most BLOCKS_MAX."""
    found = done.get("blocks")
    if not isinstance(found, dict) or len(found) > deliver_document.BLOCKS_MAX:
        raise steps.StepFailure("provider_output_invalid", "blocks")
    out = []
    for key in sorted(found):
        if not isinstance(key, str) or not deliver_document.BLOCK_ID.fullmatch(key) or not isinstance(found[key], str) or not SHA256.fullmatch(found[key]):
            raise steps.StepFailure("provider_output_invalid", "blocks")
        out.append({"id": key, "sha256": found[key]})
    return out


def _drawn_pictures(ctx: steps.Context, store, rid: str, code: str) -> dict:
    """{slot: {"asset", "path"}} of the approved pictures the beats of this video draw (the layouts' slots): the approval is checked here again, `asset_not_approved` for a
    picture the set's current approval does not cover."""
    review = _load_review(store, rid)
    approved = _stock_assets(ctx, store, rid, review, code)
    if not approved:
        return {}
    used = _used_slots(_json(store, rid, BEATS))
    return {slot: found for slot, found in approved.items() if slot in used}


def _render(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    pictures = _drawn_pictures(ctx, store, rid, "asset_not_approved")
    flags = ["--edl", _asked(store.path, rid, EDL), "--beats", _asked(store.path, rid, BEATS),
             "--in", _asked(store.raw, rid), "--out", _asked(store.folder, rid),
             "--platform-file", _asked(store.platform_path, _platform(state)),
             "--vocabulary", _asked(store.reference, VOCABULARY)]
    for slot, found in sorted(pictures.items()):      # only an approved picture a beat draws is handed over, with the sha256 the set recorded (the engine checks it at intake)
        flags += ["--asset", f"{slot}={found['path']}", "--asset-sha256", f"{slot}={found['asset']['sha256']}"]
    done = _call(ctx, "renderer:video", "render", flags)
    name, digest = os.path.basename(str(done.get("path") or "")), done.get("sha256")
    if not RENDER_NAME.fullmatch(name) or not isinstance(digest, str) or not SHA256.fullmatch(digest) or name[7:19] != digest[:12]:
        raise steps.StepFailure("render_missing", "render")
    if done.get("verified") is not True:
        raise steps.StepFailure("render_not_verified", "render")
    _asked(store.path, rid, name)      # the file is in the recording's folder
    output = done.get("output") if isinstance(done.get("output"), dict) else {}
    seconds = _num(output.get("duration")) or _num(done.get("out_seconds"))
    size = done.get("bytes")
    if type(size) is not int or size < 1 or seconds is None or seconds <= 0:
        raise steps.StepFailure("provider_output_invalid", "render")
    left_out_pictures = _assets_dropped(done, pictures)      # a picture whose beat the timeline dropped was not drawn: not in the record, not in the delivery (V9b-3d)
    handed = dict(pictures)      # every picture handed over, drawn or not: a dropped beat's kind is read from it
    pictures = {slot: found for slot, found in pictures.items() if slot not in left_out_pictures}
    blocks_sha = done.get("blocks_sha256")
    record = {"name": name, "sha256": digest, "size": size, "duration_ms": max(1, int(round(seconds * 1000))), "blocks": _blocks_of(done),
              "blocks_sha256": blocks_sha if isinstance(blocks_sha, str) and SHA256.fullmatch(blocks_sha) else None}
    if pictures:      # what this render drew, kept with it: the delivery's assets and credits come from here, never from a set changed since
        found = _optional_json(store, rid, STOCK_SET) or {}
        credit_of = found.get("credit_of") if isinstance(found.get("credit_of"), dict) else {}
        drawn = []
        for slot, got in sorted(pictures.items()):
            a = got["asset"]
            row = {"slot": slot, "sha256": a["sha256"], "source": a["source"], "item": a["item"], "licence": a["licence"]}
            if a["licence"] == STOCK_UNVERIFIED:
                row["page_host"], row["page_sha256"] = _page_parts(a.get("page"))
            if isinstance(credit_of.get(slot), str) and credit_of[slot]:
                row["credit"] = credit_of[slot]
            drawn.append(row)
        record["assets"] = drawn
    effects = _effects_dropped(done)
    left_out = _left_out(done, _json(store, rid, BEATS), handed, effects)      # V9b-3f: what the render left out, in one list for the delivery and the person
    if left_out:
        record["left_out"] = left_out
    advice = _advice(done)      # video P0b: where the edit went past a default, as closed rows; the render is not refused and the host says the sentence
    if advice:
        record["advice"] = advice
    _asked(store.write, rid, RENDER_JSON, _dump(record))
    result = {"sha256": digest, "size": size}
    if pictures:
        result["pictures"] = len(pictures)
    if left_out_pictures:      # the person is told as for `effects_dropped` (the step result; nothing else shows either): the render is not refused
        result["pictures_dropped"] = left_out_pictures
    if effects:      # an effect the renderer did not draw (too short, capped, overlapping): the person is told, the render is not refused
        result["effects_dropped"] = effects
    if left_out:
        result["left_out"] = left_out
    if advice:
        result["advice"] = advice
    return result


def _left_out(done: dict, beats: dict, handed: dict, effects: list) -> list:
    """What the render left out of the video (V9b-3f), rows {id, kind, reason} sorted by id: a beat of its `beats_dropped_reasons` (an id of the beats.json and a reason of the
    closed list; anything else, or an id twice, is `provider_output_invalid` on `render`), `kind` `picture` for a layout whose parameters name a picture this call handed over
    and `text` for any other beat, and an effect of `effects_dropped` with its reason, kind `effect`."""
    rows = done.get("beats_dropped_reasons")
    found = []
    if rows is not None:
        if not isinstance(rows, list):
            raise steps.StepFailure("provider_output_invalid", "render")
        layouts = {e["id"]: e for e in beats.get("layouts") or [] if isinstance(e, dict) and isinstance(e.get("id"), str)}
        known = set(layouts) | {e["id"] for e in beats.get("overlays") or [] if isinstance(e, dict) and isinstance(e.get("id"), str)}
        seen = set()
        for row in rows:
            if not (isinstance(row, dict) and set(row) == {"id", "reason"} and isinstance(row["id"], str) and row["id"] in known and row["id"] not in seen
                    and row["reason"] in BEAT_LEFT_OUT_REASONS):
                raise steps.StepFailure("provider_output_invalid", "render")
            seen.add(row["id"])
            params = (layouts[row["id"]].get("params") or {}) if row["id"] in layouts else {}
            picture = any(isinstance(v, str) and v in handed for v in params.values())
            found.append({"id": row["id"], "kind": "picture" if picture else "text", "reason": row["reason"]})
    found += [{"id": r["id"], "kind": "effect", "reason": r["reason"]} for r in effects]
    return sorted(found, key=lambda r: (r["id"], r["kind"]))[:deliver_document.LEFT_OUT_MAX]


def _assets_dropped(done: dict, handed: dict) -> list:
    """The render's `assets_dropped`: the slots, of those this call handed over, whose picture the engine did not draw (its beat was left out of the timeline), sorted. A value that is
    not a list of strings, a slot that was not handed over or one named twice is `provider_output_invalid` on `render`; no field is none."""
    rows = done.get("assets_dropped")
    if rows is None:
        return []
    if not isinstance(rows, list) or any(not isinstance(slot, str) or slot not in handed for slot in rows) or len(set(rows)) != len(rows):
        raise steps.StepFailure("provider_output_invalid", "render")
    return sorted(rows)


ADVICE_CODES = ("aside_repeated", "aside_with_punch", "beat_shorter_than_default", "beats_over_default", "block_not_drawn", "caption_below_line", "caption_not_drawn",
                "caption_room_small", "card_room_small", "drawn_below_line", "face_pixels_changed", "pip_card_over_face", "punch_short", "punches_over_default",
                "split_band_over_face", "text_over_default")      # = providers/renderer/_advice.py CODES (a test compares)


def _advice(done: dict) -> list:
    """The render's `advice` as closed rows {code, value, default, count[, ids]}, sorted by code: a code of ADVICE_CODES, once; value and default finite numbers; count an integer of 1 or more;
    at most 12 ids of the closed id pattern; at most 24 rows. Anything else is `provider_output_invalid` on `render` (the host never echoes what a container wrote)."""
    rows = done.get("advice")
    if rows is None:
        return []
    bad = steps.StepFailure("provider_output_invalid", "render")
    if not isinstance(rows, list) or len(rows) > deliver_document.ADVICE_MAX:
        raise bad
    found, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not {"code", "value", "default", "count"} <= set(row) or set(row) - {"code", "value", "default", "count", "ids"}:
            raise bad
        if row["code"] not in ADVICE_CODES or row["code"] in seen:
            raise bad
        seen.add(row["code"])
        if any(_num(row[k]) is None or row[k] - row[k] != 0 for k in ("value", "default")) or type(row["count"]) is not int or row["count"] < 1:
            raise bad
        ids = row.get("ids", [])
        if not isinstance(ids, list) or len(ids) > deliver_document.ADVICE_IDS_MAX or not all(isinstance(i, str) and deliver_document.LEFT_OUT_ID.fullmatch(i) for i in ids):
            raise bad
        clean = {"code": row["code"], "value": row["value"], "default": row["default"], "count": row["count"]}
        if ids:
            clean["ids"] = list(ids)
        found.append(clean)
    return sorted(found, key=lambda r: r["code"])


EFFECT_ID_OUT = re.compile(r"[pet][0-9]{1,2}")
EFFECT_REASONS = ("punch_short", "punch_capped", "grade_short", "grade_overlap", "transition_overlap", "transition_beat_dropped")
BEAT_LEFT_OUT_REASONS = ("overlap", "under_picture", "pip_no_room", "split_no_room")      # the renderer's closed list for a beat it left out (V9b-3f)


def _effects_dropped(done: dict) -> list:
    """The render's `effects_dropped` as closed rows {id, reason} (an id of the shape `p3`, `e2` or `t4`, a reason of the renderer's closed list); anything else is left out."""
    rows = done.get("effects_dropped")
    found = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("id"), str) and EFFECT_ID_OUT.fullmatch(row["id"]) and row.get("reason") in EFFECT_REASONS:
            found.append({"id": row["id"], "reason": row["reason"]})
    return found


def _cover(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    render = _json(store, rid, RENDER_JSON)
    offset = _load_review(store, rid)["cover_offset_ms"]
    temporary = f"cover-{render['sha256'][:12]}.png"      # the engine writes here; the store then names the file by its own hash (the document's rule)
    _call(ctx, "renderer:video", "cover", ["--in", _asked(store.path, rid, render["name"]), "--offset-ms", str(offset),
                                           "--out", _asked(store.path, rid, temporary, False)])
    name = _asked(store.settle_cover, rid, temporary)
    data = _asked(store.read, rid, name, COVER_LIMIT)
    if not data:
        raise steps.StepFailure("cover_missing", "cover")
    return {"name": name, "size": len(data)}


def _verify(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    render, platform = _json(store, rid, RENDER_JSON), _platform(state)
    done = _call(ctx, "renderer:video", "verify", ["--in", _asked(store.path, rid, render["name"]), "--platform-file", _asked(store.platform_path, platform),
                                                   "--sha256", render["sha256"], "--edl", _asked(store.path, rid, EDL)])
    if done.get("ok") is not True:
        raise steps.StepFailure("verify_failed", "render")
    _asked(store.write, rid, VERIFY_JSON, _dump({"passed": True, "platform": platform}))
    return {"passed": True}


def _preview_due(state: dict) -> bool:
    """The preview is made after the render is verified and before the document is written, only for a render larger than a messaging card
    carries (deliver_document.PREVIEW_MAX_BYTES), and not again after it was skipped in this cycle (a redo prepares it again)."""
    if steps.step_status(state, "verify") != "done" or steps.step_status(state, "document") == "done" or steps.step_status(state, "preview") == "skipped":
        return False
    size = ((state["steps"].get("render") or {}).get("result") or {}).get("size")
    return type(size) is int and size > deliver_document.PREVIEW_MAX_BYTES


def _preview(ctx: steps.Context, state: dict) -> dict:
    """A side step: the renderer's `preview` of the verified render, re-read from the store and hashed here. A failure is `skipped` and the
    document then has no preview (the delivery is approved in the terminal or on the page)."""
    store, _, rid = _handles(ctx)
    render = _json(store, rid, RENDER_JSON)
    flags = ["--in", _asked(store.path, rid, render["name"]), "--sha256", render["sha256"], "--out", _asked(store.folder, rid)]
    done = _call(ctx, "renderer:video", "preview", flags)
    name, digest, size = os.path.basename(str(done.get("name") or "")), done.get("sha256"), done.get("bytes")
    if not PREVIEW_NAME.fullmatch(name) or not isinstance(digest, str) or not SHA256.fullmatch(digest) or name[8:20] != digest[:12]:
        raise steps.StepFailure("provider_output_invalid", "preview")
    if done.get("from_sha256") != render["sha256"] or type(size) is not int or size < 1:
        raise steps.StepFailure("provider_output_invalid", "preview")
    if size > deliver_document.PREVIEW_MAX_BYTES:
        raise steps.StepFailure("preview_too_large", "preview")
    data = _asked(store.read, rid, name, deliver_document.PREVIEW_MAX_BYTES)
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise steps.StepFailure("preview_differs", "preview")
    return {"name": name, "sha256": digest, "size": size, "from_sha256": render["sha256"]}


def _document(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    files = _service(ctx, "effect_files")
    render, verify = _json(store, rid, RENDER_JSON), _json(store, rid, VERIFY_JSON)
    cover = (state["steps"].get("cover") or {}).get("result") or {}
    held = {"name": cover["name"], "sha256": _asked(store.sha256, rid, cover["name"]), "size": cover["size"]} if cover.get("name") else None
    # The preview a messaging card carries (decision 14): the renderer's copy when the side step made one from this render, else the render
    # itself when it is small enough, else none (the delivery is then approved in the terminal or on the page).
    made = state["steps"].get("preview") or {}
    copy = made.get("result") if made.get("status") == "done" else None
    if isinstance(copy, dict) and copy.get("from_sha256") == render["sha256"]:
        preview = {"sha256": copy["sha256"], "size": copy["size"], "from_sha256": render["sha256"]}
    elif render["size"] <= deliver_document.PREVIEW_MAX_BYTES:
        preview = {"sha256": render["sha256"], "size": render["size"], "from_sha256": render["sha256"]}
    else:
        preview = None
    assets, web, credits = [], [], []
    for row in render.get("assets") or []:      # the pictures this render drew, as the render recorded them (a set changed since cannot reach the delivery)
        assets.append({k: row[k] for k in ("slot", "sha256", "source", "item", "licence")})
        if row["licence"] == STOCK_UNVERIFIED:
            web.append({"slot": row["slot"], "sha256": row["sha256"], "page_host": row.get("page_host", ""), "page_sha256": row.get("page_sha256", "")})
        if isinstance(row.get("credit"), str):
            credits.append(row["credit"])
    doc = deliver_document.build(task=ctx.task_id, recording=rid, platform=_platform(state), post=ctx.args["post"],
                                 video={k: render[k] for k in ("name", "sha256", "size", "duration_ms")}, cover=held,
                                 verify_platform=verify["platform"], blocks=render.get("blocks") or [], preview=preview,
                                 assets=assets, web=web, left_out=render.get("left_out") or [], advice=render.get("advice") or [],
                                 credits={"count": len(credits), "sha256": hashlib.sha256(json.dumps(credits, ensure_ascii=False).encode("utf-8")).hexdigest()} if credits else None)      # S4: the text stays out
    return {"effect_sha256": _asked(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the document read back by the hash `document` recorded, its preview and its hash."""
    recorded = state["steps"]["document"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    deliver_document.check(doc)
    return {"title": deliver_document.title(doc)[:200], "body": deliver_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": deliver_document.summary(doc), "card": deliver_document.card_lines(doc, recorded)}}


# --- what a step prepared again removes ---------------------------------------------------------------------------------------


def _cleaner(*names):
    def clean(ctx: steps.Context, state: dict) -> None:
        store, _, rid = _handles(ctx)
        _asked(store.remove, rid, list(names))
    return clean


CLEANUP = {"transcribe": (TRANSCRIPT,), "analyse": (ANALYSIS,), "still": (STILL_PATTERN,), "retakes": (PROPOSAL_EDL,),
           "align-proposal": (PROPOSAL_BEATS, EDITED, REVIEW),      # new words start the review over
           "base": (EDL,), "align": (BEATS,), "render": (RENDER_PATTERN, RENDER_JSON), "cover": (COVER_PATTERN,), "verify": (VERIFY_JSON,),
           "preview": (PREVIEW_PATTERN,)}

EXECUTORS = {"take": _take, "transcribe": _transcribe, "analyse": _analyse, "still": _still, "retakes": _retakes, "align-proposal": _align_proposal,
             "remap": _remap, "base": _base, "align": _align, "check": _check, "render": _render, "cover": _cover, "verify": _verify,
             "preview": _preview, "document": _document}

KIND = steps.register(steps.Kind(
    name="media",
    order=ORDER,
    executors=EXECUTORS,
    stops=("review",),
    decisions={"review": _review_decision},
    side_steps={"still": _still_due, "preview": _preview_due},
    cleanup={name: _cleaner(*names) for name, names in CLEANUP.items()},
    gates={GATE_STEP: steps.Gate(word=deliver_document.WORD, open=_open, redo="remap")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
    errors=(captions.CaptionError, theme.ThemeError),
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
