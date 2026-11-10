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
and it writes no file of the project (its footprint is empty). Asset slots (a picture placed in the video) are not in this package: every empty slot
is a keyword or none.

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
ENGINE_NEXT = {"not_configured": "set up the transcriber and the renderer this project uses (media.renderer in docs/workbench/runtime.json: auto means hyperframes unless RENDERER_PROVIDER names another; the README files give the commands, run by you), or name the other renderer there and accept the file, then start the task again"}


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
    out = _asked(store.path, rid, EDL, False)
    args = ["--transcript", _asked(store.path, rid, EDITED), "--analysis", _asked(store.path, rid, ANALYSIS), "--out", out, "--retakes", "propose"] + _face_args(review) + flags
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
            **_counts(edl)}


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
    args = _beat_args(ctx, _asked(store.path, rid, EDITED), _asked(store.path, rid, BEATS, False)) + ["--edl", _asked(store.path, rid, EDL)]
    for slot in proposal.get("slots") or []:      # no asset slots in this package: an empty slot is the person's choice, else none
        args += ["--empty-slot", f"{slot['slot']}={review['empty_slots'].get(slot['slot'], 'none')}"]
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
            added.append({"id": a["id"], "beat": captions.ANIMATION_BEAT_BASE + int(a["id"][1:]), "preset": a["preset"], "params": a["params"],
                          "block": a["block"], "word_from": a["word_from"], "word_to": a["word_to"], "score": 1.0})
    if dropped or placed:
        _asked(store.write, rid, BEATS, _dump(beats))
    return {"beats": _num(done.get("beats")), "overlays": len(beats.get("overlays") or []), "layouts": len(beats.get("layouts") or []),
            "unmatched": len([b for b in done.get("unmatched") or [] if b not in dropped]), "anchored": len(anchors), "dropped": len(dropped),
            "animations": len(placed)}


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


def _render(ctx: steps.Context, state: dict) -> dict:
    store, _, rid = _handles(ctx)
    done = _call(ctx, "renderer:video", "render", ["--edl", _asked(store.path, rid, EDL), "--beats", _asked(store.path, rid, BEATS),
                                                   "--in", _asked(store.raw, rid), "--out", _asked(store.folder, rid),
                                                   "--platform-file", _asked(store.platform_path, _platform(state)),
                                                   "--vocabulary", _asked(store.reference, VOCABULARY)])
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
    blocks_sha = done.get("blocks_sha256")
    record = {"name": name, "sha256": digest, "size": size, "duration_ms": max(1, int(round(seconds * 1000))), "blocks": _blocks_of(done),
              "blocks_sha256": blocks_sha if isinstance(blocks_sha, str) and SHA256.fullmatch(blocks_sha) else None}
    _asked(store.write, rid, RENDER_JSON, _dump(record))
    return {"sha256": digest, "size": size}


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
    doc = deliver_document.build(task=ctx.task_id, recording=rid, platform=_platform(state), post=ctx.args["post"],
                                 video={k: render[k] for k in ("name", "sha256", "size", "duration_ms")}, cover=held,
                                 verify_platform=verify["platform"], blocks=render.get("blocks") or [], preview=preview)
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
