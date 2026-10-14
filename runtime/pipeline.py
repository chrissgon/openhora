#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The media pipeline of a recording (package P4b of the short-video plan): the steps that take a recording that is in the
media store to a rendered video, with its cover, and stop with the task waiting for the person. No model is involved: every
step is a verb of a provider (`transcriber:speech`, `renderer:video`, both in a container), a function of runtime/captions.py
or a check. The steps, in order, each result recorded and each resumable:

  transcribe       transcriber:speech transcribe (`--timestamps dtw`, recorded)       -> transcript.json
  analyse          renderer analyse (ffprobe, silencedetect)                          -> analysis.json
  retakes          renderer base, no retake confirmed: the retakes found by rule,    -> proposal.edl.json
                   the words the renderer re-timed or left out (a proposal)
  align-proposal   renderer align on the transcript: each beat of the script with    -> proposal.beats.json
                   its matched words and score (a proposal); the asset slots are registered
  review           STOP: the decision "Check the captions" (runtime/captions.py). The person corrects words, confirms or
                   rejects each retake, anchors the beats, gives the face box; `captions-done` answers it
  remap            the edited transcript is made (or confirmed), hardened and scanned    -> transcript.edited.json
  base             renderer base on the edited transcript, the confirmed retakes cut     -> edl.json
  align            renderer align on it, the person's anchors over the match             -> beats.json
  check            renderer check (schema, bounds, hardening, credential shapes)
  render           renderer render, then the render is verified in a fresh container     -> render-<sha12>.mp4
  cover            renderer cover                                                        -> cover-<sha12>.png, render.json
  approval         STOP: the task waits for the approval of the rendered file (P7, P8)

Deferred to later packages, on purpose: the payload builder, the publisher's and the scheduler's dry runs, and the effect.

Rules that hold here, each with a test:

  - A step already done is not run again. A step that fails leaves the task `failed` and resumable at that step: the next
    call (`media-pipeline`, `retry`) starts there.
  - Every result is recorded in <data_dir>/media/<id>/pipeline.json as closed words and numbers: a code, a count, a hash, a
    name. The text of a transcript, a post or a tool's output is never in it, in a task's note or in a decision's body.
  - A provider's refusal is read for its closed code only (`refused: <code> <field>`); a provider that is not set up gives a
    code and the command the person runs to set it up. This module never builds an image, pulls one, fetches a model or
    pins a browser: those are the person's commands in a terminal.
  - Nothing here runs a model, and nothing leaves the machine.

The state file, the task and the decisions are moved by the callbacks of the Context, which runtime/ops_pipeline.py gives.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shlex
import stat
from typing import Callable

import captions as cap
import media

STEPS = ("transcribe", "analyse", "retakes", "align-proposal", "review", "remap", "base", "align", "check", "render", "cover",
         "approval")
STOPS = ("review", "approval")
STATE_FILE = "pipeline.json"
STATE_VERSION = 1
TRANSCRIPT, ANALYSIS = "transcript.json", "analysis.json"
EDITED, REVIEW = "transcript.edited.json", "review.json"
PROPOSAL_EDL, PROPOSAL_BEATS = "proposal.edl.json", "proposal.beats.json"
EDL, BEATS = "edl.json", "beats.json"
RENDER_RESULT = "render.json"             # the renderer's result for the recording, read by the page (runtime/video.py)
TIMESTAMPS = "dtw"                       # check C3: far fewer words misplaced into silences than the word mode
JSON_LIMIT = 5 * 1024 * 1024
POST_LIMIT = 2 * 1024 * 1024
# Seconds a provider verb may run before the call is given up; the providers have timeouts of their own inside.
TIMEOUTS = {"transcribe": 1800 + 120, "analyse": 900 + 60, "retakes": 300, "align-proposal": 300, "base": 300, "align": 300,
            "check": 300, "render": 2400 + 300, "cover": 300}
# The files a step makes, removed when the step is prepared again. remap, check and render make none that goes: the edited
# transcript holds the person's work, and a render is content-addressed and kept until retention.
STEP_FILES = {"transcribe": (TRANSCRIPT,), "analyse": (ANALYSIS,), "retakes": (PROPOSAL_EDL,), "align-proposal": (PROPOSAL_BEATS,),
              "base": (EDL,), "align": (BEATS,)}
# Preparing a step again from here or before starts the review over: the words it was made on are new.
REVIEW_FILES_RESET_UP_TO = "align-proposal"
THRESHOLD_NOTE = "a beat is flagged below the renderer's threshold"
CODE = re.compile(r"[a-z][a-z0-9_]{1,40}")
REFUSED = re.compile(r"refused: ([a-z][a-z0-9_]{1,40})(?: ([A-Za-z0-9_.\[\]-]{1,40}))?")
FIELD = re.compile(r"[A-Za-z0-9_.\[\]-]{0,40}")
NETWORK_LINE = re.compile(r"^- Network:\s*([a-z0-9][a-z0-9-]{0,31})\s*$", re.M | re.I)


class StepFailure(Exception):
    """A step that stopped: a closed `code`, the `field` it names (never text), the `provider` word and what to do next
    (`next`: a command the person runs, or one fixed sentence)."""

    def __init__(self, code: str, field: str = "", provider: str = "", next: str = ""):
        super().__init__(f"{code} {field}".strip())
        self.code, self.field, self.provider, self.next = code, field, provider, next


class Cancelled(Exception):
    """The request of the task was cancelled: the pipeline stops without a word of failure."""


@dataclasses.dataclass
class Context:
    """What the pipeline is given. `call(cls, verb, args, timeout)` runs a provider's verb and returns its one JSON object,
    or raises StepFailure; `move(state, note, pending, resolve)` moves the code task (the store's code_task_move) and returns
    {"pending_id"}; `alive()` raises Cancelled; `scan(text)` lists the labels of what looks like a credential."""

    data_dir: str
    project: str
    root: str
    rid: str
    platform: str
    post: str
    settings: dict
    call: Callable
    move: Callable
    scan: Callable
    alive: Callable
    checker: str
    now: Callable
    task_id: int = 0
    request_id: int = 0

    def path(self, name: str) -> str:
        return os.path.join(media.folder_of(self.data_dir, self.rid), name)

    def reference(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)


# --- files ---------------------------------------------------------------------------------------------------------------


def read_json(path: str, label: str, limit: int = JSON_LIMIT):
    """A JSON file of the media folder: a regular file, never a link, at most `limit` bytes. StepFailure otherwise."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise StepFailure("file_missing", label) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise StepFailure("file_unreadable", label)
        with os.fdopen(fd, "rb", closefd=False) as f:
            return json.loads(f.read(limit + 1).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise StepFailure("file_unreadable", label) from None
    finally:
        os.close(fd)


def write_json(path: str, value) -> None:
    """Write a JSON file for its owner only (0600), through a temporary name opened with O_EXCL|O_NOFOLLOW."""
    temporary = f"{path}.{os.getpid()}.tmp"
    try:
        os.unlink(temporary)
    except OSError:
        pass
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(temporary, path)


def remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        raise StepFailure("file_unreadable", os.path.basename(path)[:40]) from None


def exists(path: str) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


# --- the state ------------------------------------------------------------------------------------------------------------


def new_state(rid: str, platform: str, post: str, task_id: int, request_id: int) -> dict:
    return {"version": STATE_VERSION, "recording": rid, "platform": platform, "post": post, "task": task_id, "request": request_id,
            "steps": {}, "failure": None, "decisions": {}}


def load_state(data_dir: str, rid: str):
    """The pipeline's state, or None when it never started. StepFailure when the file is there and cannot be read."""
    path = os.path.join(media.folder_of(data_dir, rid), STATE_FILE)
    if not exists(path):
        return None
    doc = read_json(path, STATE_FILE)
    if not isinstance(doc, dict) or doc.get("version") != STATE_VERSION or doc.get("recording") != rid or not isinstance(doc.get("steps"), dict):
        raise StepFailure("file_unreadable", STATE_FILE)
    return doc


def save_state(ctx: Context, state: dict) -> None:
    write_json(ctx.path(STATE_FILE), state)


def step_status(state: dict, name: str) -> str:
    return (state["steps"].get(name) or {}).get("status", "pending")


def summary(state: dict) -> dict:
    """Every step and its status, in order: what a shell shows of the pipeline."""
    return {name: step_status(state, name) for name in STEPS}


def next_step(state: dict):
    """The first step that is not done, or None."""
    for name in STEPS:
        if step_status(state, name) != "done":
            return name
    return None


# --- what a provider's refusal means ------------------------------------------------------------------------------------------


TRANSCRIBER_TEXTS = (   # (words of the provider's own refusal, the closed code): the transcriber's messages are plain sentences
    ("docker is not installed", "docker_missing"), ("docker could not be started", "docker_missing"),
    ("not answering", "docker_not_answering"), ("not local", "docker_daemon_not_local"),
    ("is not built", "image_not_built"), ("not built from", "image_not_built"), ("`build` recorded", "image_not_built"),
    ("names no cpu flags", "image_not_built"), ("no pinned sha256", "model_missing"), ("is not at", "model_missing"),
    ("open to other users", "folder_unusable"), ("not owned by", "folder_unusable"), ("not a real directory", "folder_unusable"),
    ("differs", "model_mismatch"),
)
DOCKER_NEXT = "install Docker and start it; the pipeline never starts or installs it"


def next_for(code: str, script: str) -> str:
    """The fixed instruction for a code that means something is not set up: the command the person runs in a terminal, on the
    provider's own script (`script`, the path providers/resolve.py gave). The page never runs it (a build downloads, and
    downloads are the person's word)."""
    if code in ("docker_missing", "docker_not_answering", "docker_daemon_not_local", "docker_unusable"):
        return DOCKER_NEXT
    if not script:
        return ""
    quoted = shlex.quote(script)
    if code in ("image_not_built", "image_stale", "image_not_recorded"):
        return f"python3 {quoted} build --confirmed"
    if code in ("model_missing", "model_mismatch"):
        return f"python3 {quoted} models"
    if code == "pin_incomplete":
        return f"python3 {quoted} pin-browser --confirmed"
    return ""


def failure_from(provider: str, kind: str, tail: str, script: str) -> StepFailure:
    """A provider call that did not give one JSON object, as a StepFailure. `kind` is providers/resolve.py's
    (usage, not-configured, failed, timeout) and `tail` the end of the provider's stderr. Only a closed code leaves this
    function: the one after `refused:` (renderer), or a word picked by the transcriber's own sentences; never the text."""
    found = REFUSED.search(tail or "")
    code, field = (found.group(1), found.group(2) or "") if found else ("", "")
    if kind == "timeout":
        code = "timeout"
    elif not code and provider == "transcriber":
        lowered = (tail or "").lower()
        code = next((c for words, c in TRANSCRIBER_TEXTS if words in lowered), "")
    if not code:
        code = {"usage": "usage", "not-configured": "not_configured"}.get(kind, "failed")
    return StepFailure(code, field, provider, next_for(code, script))


def note_of(step: str, failure: StepFailure) -> str:
    text = f"{step}: {failure.code}" + (f" {failure.field}" if failure.field else "")
    return text + (f" -- {failure.next}" if failure.next else "")


# --- the steps ---------------------------------------------------------------------------------------------------------------


def _setting(ctx: Context, name: str) -> str:
    value = (ctx.settings or {}).get(name)
    if not value:
        raise StepFailure("not_configured", f"media.{name}", "runtime",
                          "set media.model and media.language in docs/workbench/runtime.json, then accept-config in the terminal")
    return value


def _raw(ctx: Context) -> str:
    record = media.load(ctx.data_dir, ctx.rid)
    raw = record.get("raw") or {}
    name = raw.get("file")
    if not isinstance(name, str) or not re.fullmatch(r"raw\.[a-z0-9]{2,4}", name) or not exists(ctx.path(name)):
        raise StepFailure("no_recording", "raw")
    return ctx.path(name)


def post_file(project: str, post: str) -> str:
    """The path of a post file of the project: a Markdown file under docs/ (media.POST_PATH), a regular file that is not a link,
    whose folders do not lead out of the project, at most POST_LIMIT bytes. StepFailure (post_unreadable) otherwise."""
    if not isinstance(post, str) or not media.POST_PATH.fullmatch(post) or ".." in post.split("/") or "//" in post:
        raise StepFailure("post_unreadable", "post")
    path = os.path.join(project, *post.split("/"))
    try:
        info = os.lstat(path)
        inside = os.path.realpath(os.path.dirname(path)).startswith(os.path.realpath(project) + os.sep)
    except OSError:
        raise StepFailure("post_unreadable", "post") from None
    if not stat.S_ISREG(info.st_mode) or info.st_size > POST_LIMIT or not inside:
        raise StepFailure("post_unreadable", "post")
    return path


def _post(ctx: Context) -> str:
    return post_file(ctx.project, ctx.post)


def cover_file(sha256: str) -> str:
    return f"cover-{sha256[:12]}.png"


def _remove_outputs(ctx: Context, name: str, state: dict) -> None:
    for file in STEP_FILES.get(name, ()):
        remove(ctx.path(file))
    if name == "render":
        remove(ctx.path(RENDER_RESULT))
    if name == "cover":
        made = (state["steps"].get("cover") or {}).get("result") or {}
        if isinstance(made.get("name"), str) and re.fullmatch(r"cover-[0-9a-f]{12}\.png", made["name"]):
            remove(ctx.path(made["name"]))


def _transcribe(ctx: Context, state: dict) -> dict:
    raw = _raw(ctx)
    model, language = _setting(ctx, "model"), _setting(ctx, "language")
    out = ctx.path(TRANSCRIPT)
    done = ctx.call("transcriber:speech", "transcribe",
                    ["--in", raw, "--model", model, "--language", language, "--timestamps", TIMESTAMPS, "--out", out,
                     "--max-seconds", str(media.MAX_SECONDS)], TIMEOUTS["transcribe"])
    doc = read_json(out, TRANSCRIPT)
    facts = doc.get("facts") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or not isinstance(doc.get("words"), list) or not doc["words"] or not isinstance(facts, dict):
        raise StepFailure("transcript_invalid", "transcript")
    return {"words": len(doc["words"]), "segments": len(doc.get("segments") or []), "duration": doc.get("duration"),
            "language": doc.get("language"), "model": model, "timestamps": facts.get("timestamps", TIMESTAMPS),
            "wall_seconds": done.get("wall_seconds")}


def _analyse(ctx: Context, state: dict) -> dict:
    raw = _raw(ctx)
    done = ctx.call("renderer:video", "analyse", ["--in", raw, "--out", ctx.path(ANALYSIS)], TIMEOUTS["analyse"])
    record = media.load(ctx.data_dir, ctx.rid)
    if done.get("sha256") != (record.get("raw") or {}).get("sha256"):
        raise StepFailure("recording_changed", "raw")
    return {"duration": done.get("duration"), "silences": done.get("silences"), "has_audio": done.get("has_audio"),
            "sha256": done.get("sha256")}


def _face_args(review) -> list:
    box = (review or {}).get("face_box")
    args = []
    if box:
        args += ["--face-box", "{x},{y},{w},{h}".format(**box)]
    return args


def _normalisation_counts(edl: dict) -> dict:
    norm = edl.get("normalisation") or {}
    return {"retimed": len(norm.get("retimed_words") or []), "unplaced": len(norm.get("unplaced_words") or []),
            "dropped_segments": len(norm.get("dropped_segments") or []), "estimated": norm.get("estimated_words"),
            "clamped": norm.get("clamped_starts")}


def _retakes(ctx: Context, state: dict) -> dict:
    done = ctx.call("renderer:video", "base", ["--transcript", ctx.path(TRANSCRIPT), "--analysis", ctx.path(ANALYSIS), "--out", ctx.path(PROPOSAL_EDL)],
                    TIMEOUTS["retakes"])
    edl = read_json(ctx.path(PROPOSAL_EDL), PROPOSAL_EDL)
    proposals = edl.get("proposals") or []
    return {"proposals": [{"id": p["id"], "kind": p["kind"], "seconds": p["seconds"]} for p in proposals],
            "kept_ranges": done.get("kept_ranges"), "out_seconds": done.get("out_seconds"), **_normalisation_counts(edl)}


def _beat_args(ctx: Context, transcript: str, out: str) -> list:
    args = ["--post", _post(ctx), "--transcript", transcript, "--checker", ctx.checker,
            "--vocabulary", ctx.reference("shared", "references", "video-presets.json"), "--out", out]
    return args


def _align_proposal(ctx: Context, state: dict) -> dict:
    done = ctx.call("renderer:video", "align", _beat_args(ctx, ctx.path(TRANSCRIPT), ctx.path(PROPOSAL_BEATS)), TIMEOUTS["align-proposal"])
    beats = read_json(ctx.path(PROPOSAL_BEATS), PROPOSAL_BEATS)
    try:
        media.register_slots(ctx.data_dir, ctx.rid, [{"key": s["slot"], "description": s["description"]} for s in beats.get("slots") or []])
    except media.MediaError:
        raise StepFailure("slots_frozen", "slots") from None
    return {"beats": done.get("beats"), "overlays": done.get("overlays"), "layouts": done.get("layouts"), "unmatched": done.get("unmatched") or [],
            "slots": [s["slot"] for s in beats.get("slots") or []], "scores": done.get("scores") or {}}


def _remap(ctx: Context, state: dict) -> dict:
    """The edited transcript the later steps read: the person's, or the transcript itself when nothing was edited. Hardened
    again word by word and scanned for credentials, because it is the text a renderer draws and the file may be handed on."""
    path = ctx.path(EDITED)
    if exists(path):
        edited = cap.check_edited(read_json(path, EDITED))
    else:
        edited = cap.start_edited(read_json(ctx.path(TRANSCRIPT), TRANSCRIPT))
    for word in edited["words"]:
        try:
            cap.harden_word(word["text"], "word")
        except cap.CaptionError as e:
            raise StepFailure(e.code, "transcript.edited") from None
    if ctx.scan(" ".join(w["text"] for w in edited["words"])):
        raise StepFailure("credential_in_transcript", "transcript.edited")
    write_json(path, edited)
    return {"words": len(edited["words"]), "edited": sum(1 for w in edited["words"] if w.get("edited")),
            "estimated": sum(1 for w in edited["words"] if w.get("estimated")), "revision": (edited.get("facts") or {}).get("revision", 0)}


def load_review(ctx: Context) -> dict:
    path = ctx.path(REVIEW)
    if not exists(path):
        return cap.new_review()
    try:
        return cap.check_review(read_json(path, REVIEW))
    except cap.CaptionError as e:
        raise StepFailure(e.code, e.field) from None


def _base(ctx: Context, state: dict) -> dict:
    edited = cap.check_edited(read_json(ctx.path(EDITED), EDITED))
    review = load_review(ctx)
    args = ["--transcript", ctx.path(EDITED), "--analysis", ctx.path(ANALYSIS), "--out", ctx.path(EDL)] + _face_args(review)
    done = ctx.call("renderer:video", "base", args, TIMEOUTS["base"])
    confirm, lost = [], 0
    if review["confirmed_retakes"]:
        edl = read_json(ctx.path(EDL), EDL)
        confirm, lost = cap.confirmed_ids(review, edited, edl.get("proposals") or [])
        if lost:
            raise StepFailure("retake_lost", "retakes", "", "open the caption review again (prepare-again --step review) and confirm the retake again")
        if confirm:
            done = ctx.call("renderer:video", "base", args + [x for i in confirm for x in ("--confirm", i)], TIMEOUTS["base"])
    edl = read_json(ctx.path(EDL), EDL)
    return {"kept_ranges": done.get("kept_ranges"), "out_seconds": done.get("out_seconds"), "retakes_confirmed": len(confirm),
            "retakes_proposed": len(edl.get("proposals") or []), "face_box": "set" if review["face_box"] else "default",
            **_normalisation_counts(edl)}


def _asset_for(ctx: Context, record: dict, slot: str):
    """The uploaded file of a renderer slot id ('beat7'): {"path", "sha256", "type"} or None when there is none to use."""
    held = (record.get("slots") or {}).get(media.slot_id(ctx.rid, slot))
    asset = held.get("asset") if isinstance(held, dict) else None
    if not asset or asset.get("stale"):
        return None
    return {"path": os.path.join(ctx.path(media.ASSETS), asset["file"]), "sha256": asset["sha256"], "type": asset.get("type")}


def _align(ctx: Context, state: dict) -> dict:
    edited = cap.check_edited(read_json(ctx.path(EDITED), EDITED))
    review = load_review(ctx)
    edl = read_json(ctx.path(EDL), EDL)
    proposal = read_json(ctx.path(PROPOSAL_BEATS), PROPOSAL_BEATS)
    live = {w["index"] for w in edl.get("words") or []}
    anchors, lost = cap.anchors_current(review, edited, live)
    if lost:
        raise StepFailure("anchor_lost", f"beat{lost[0]}", "", "open the caption review again (prepare-again --step review) and anchor the beat again")
    record = media.load(ctx.data_dir, ctx.rid)
    args = _beat_args(ctx, ctx.path(EDITED), ctx.path(BEATS)) + ["--edl", ctx.path(EDL)]
    empty = []
    for s in proposal.get("slots") or []:
        if _asset_for(ctx, record, s["slot"]) is None:
            choice = review["empty_slots"].get(s["slot"])
            if choice is None:
                empty.append(s["slot"])
            else:
                args += ["--empty-slot", f"{s['slot']}={choice}"]
    if empty:
        raise StepFailure("slot_empty", empty[0], "", "give the slot a file (media-in --slot) or choose keyword or none for it in the caption review")
    for beat, (first, last) in sorted(anchors.items()):
        args += ["--anchor", f"{beat}={first}-{last}"]
    done = ctx.call("renderer:video", "align", args, TIMEOUTS["align"])
    beats = read_json(ctx.path(BEATS), BEATS)
    dropped = set(review["dropped_beats"])
    if dropped:
        beats["overlays"] = [e for e in beats.get("overlays") or [] if e.get("beat") not in dropped]
        beats["layouts"] = [e for e in beats.get("layouts") or [] if e.get("beat") not in dropped]
        write_json(ctx.path(BEATS), beats)
    return {"beats": done.get("beats"), "overlays": len(beats.get("overlays") or []), "layouts": len(beats.get("layouts") or []),
            "unmatched": [b for b in done.get("unmatched") or [] if b not in dropped], "anchored": sorted(anchors), "dropped": sorted(dropped),
            "scores": done.get("scores") or {}, "reordered": done.get("reordered") or []}


def _platform_file(ctx: Context) -> str:
    return ctx.reference("shared", "references", "platforms", f"{ctx.platform}.json")


def _check(ctx: Context, state: dict) -> dict:
    done = ctx.call("renderer:video", "check", ["--edl", ctx.path(EDL), "--beats", ctx.path(BEATS),
                                                 "--vocabulary", ctx.reference("shared", "references", "video-presets.json"),
                                                 "--platform-file", _platform_file(ctx)], TIMEOUTS["check"])
    return {"out_seconds": done.get("out_seconds"), "words": done.get("words"), "overlays": done.get("overlays"),
            "layouts": done.get("layouts"), "mentions": len(done.get("mentions") or [])}


def _render(ctx: Context, state: dict) -> dict:
    if media.renders_kept(ctx.data_dir) >= media.MAX_RENDERS:
        raise StepFailure("render_cap", "renders", "", "free some space: media-purge removes what the retention allows")
    record = media.load(ctx.data_dir, ctx.rid)
    beats = read_json(ctx.path(BEATS), BEATS)
    args = ["--edl", ctx.path(EDL), "--beats", ctx.path(BEATS), "--in", _raw(ctx), "--out", ctx.path(""), "--platform-file", _platform_file(ctx),
            "--vocabulary", ctx.reference("shared", "references", "video-presets.json")]
    used = {p for e in (beats.get("overlays") or []) + (beats.get("layouts") or []) for p in e.get("params", {}).values() if isinstance(p, str)}
    for s in beats.get("slots") or []:
        if s["slot"] not in used:
            continue
        asset = _asset_for(ctx, record, s["slot"])
        if asset is None:
            continue
        if asset["type"] not in ("png", "jpeg"):
            raise StepFailure("asset_type", s["slot"], "", "the renderer takes a PNG or a JPEG for a slot; export the image as one of them")
        args += ["--asset", f"{s['slot']}={asset['path']}", "--asset-sha256", f"{s['slot']}={asset['sha256']}"]
    done = ctx.call("renderer:video", "render", args, TIMEOUTS["render"])
    name = os.path.basename(str(done.get("path") or ""))
    if not media.RENDER.fullmatch(name) or not exists(ctx.path(name)):
        raise StepFailure("render_missing", "render")
    if done.get("verified") is not True or done.get("sha256", "")[:12] != name[7:19]:
        raise StepFailure("render_not_verified", "render")
    fonts = done.get("fonts") if isinstance(done.get("fonts"), dict) else {}
    facts = done.get("output") if isinstance(done.get("output"), dict) else {}
    output = {str(k)[:40]: v for k, v in list(facts.items())[:24]
              if isinstance(v, (int, float, str)) and not isinstance(v, bool) and (not isinstance(v, str) or re.fullmatch(r"[A-Za-z0-9._:+ /-]{0,40}", v))}
    result = {"name": name, "sha256": done["sha256"], "bytes": done.get("bytes"), "seconds": done.get("seconds"), "output": output,
              "replayed": bool(done.get("replayed")),
              "unmatched_beats": done.get("unmatched_beats") or [], "fonts": {str(k): str(v)[:40] for k, v in list(fonts.items())[:8]},
              "browser_sandbox": done.get("browser_sandbox"), "image": (done.get("image") or {}).get("id")}
    write_render_result(ctx, result, None)
    return result


def write_render_result(ctx: Context, render: dict, cover) -> None:
    """render.json, the renderer's result for the recording as the page reads it (runtime/video.py): `sha256`, `bytes`, `output`
    (the ffprobe facts of the file), `name`, and, once the cover is cut, `cover` ({"offset_ms", "sha256", "name"}). Closed words
    and numbers only; written again when the cover is."""
    doc = {k: render.get(k) for k in ("sha256", "bytes", "output", "name", "seconds", "replayed", "unmatched_beats", "fonts", "browser_sandbox", "image")}
    doc["verified"] = True
    if cover:
        doc["cover"] = {k: cover[k] for k in ("offset_ms", "sha256", "name")}
    write_json(ctx.path(RENDER_RESULT), doc)


def _cover(ctx: Context, state: dict) -> dict:
    render = state["steps"]["render"]["result"]
    offset = load_review(ctx)["cover_offset_ms"]
    name = cover_file(render["sha256"])
    ctx.call("renderer:video", "cover", ["--in", ctx.path(render["name"]), "--offset-ms", str(offset), "--out", ctx.path(name)], TIMEOUTS["cover"])
    if not exists(ctx.path(name)):
        raise StepFailure("cover_missing", "cover")
    with open(ctx.path(name), "rb") as f:
        digest = hashlib.sha256(f.read(16 * 1024 * 1024 + 1)).hexdigest()
    result = {"name": name, "offset_ms": offset, "sha256": digest}
    write_render_result(ctx, render, result)
    return result


EXECUTORS = {"transcribe": _transcribe, "analyse": _analyse, "retakes": _retakes, "align-proposal": _align_proposal, "remap": _remap,
             "base": _base, "align": _align, "check": _check, "render": _render, "cover": _cover}


# --- the decisions -----------------------------------------------------------------------------------------------------------------


def review_decision(ctx: Context, state: dict) -> dict:
    """The decision "Check the captions": a fixed text with the recording id and counts, never a word of the transcript."""
    edl = read_json(ctx.path(PROPOSAL_EDL), PROPOSAL_EDL)
    beats = read_json(ctx.path(PROPOSAL_BEATS), PROPOSAL_BEATS)
    counts = _normalisation_counts(edl)
    below = sum(1 for r in beats.get("report") or [] if r.get("preset") and not r.get("matched") and "fallback" not in r)
    body = (f"Recording {ctx.rid}: the captions are ready to check, before anything is rendered. {state['steps']['transcribe']['result']['words']} words, "
            f"{len(edl.get('proposals') or [])} retake proposals, {below} beats below the match threshold, {counts['retimed']} words with timing "
            f"adjusted, {counts['unplaced']} words left out. Open the caption review: correct the words, confirm or undo each retake, anchor the "
            "beats that did not match, then say done.")
    if state.get("sent_back_at"):
        body += " The video was sent back with a comment: the caption review shows it."
    return {"kind": "question", "title": "Check the captions", "body": body,
            "payload": {"media_pipeline": {"recording": ctx.rid, "step": "review", "counts": {"retakes": len(edl.get("proposals") or []),
                                                                                              "below_threshold": below, **counts}}}}


def approval_decision(ctx: Context, state: dict) -> dict:
    render = state["steps"]["render"]["result"]
    body = (f"Recording {ctx.rid}: the video is rendered ({render.get('seconds')} s, {render.get('bytes')} bytes, sha256 {render['sha256']}). "
            "Nothing is approved, scheduled or published yet: the page shows the video and takes the approval of exactly this file.")
    return {"kind": "question", "title": "Approve the rendered video", "body": body,
            "payload": {"media_pipeline": {"recording": ctx.rid, "step": "approval", "platform": ctx.platform,
                                           "render": {k: render.get(k) for k in ("name", "sha256", "bytes", "seconds")},
                                           "cover": state["steps"]["cover"]["result"]}}}


# --- running -----------------------------------------------------------------------------------------------------------------------


def _stop_at(ctx: Context, state: dict, name: str, build: Callable) -> dict:
    if step_status(state, name) == "waiting" and state["decisions"].get(name):
        return {"ok": True, "stopped": name, "pending": state["decisions"][name]}
    moved = ctx.move("waiting", None, build(ctx, state), None)
    state["steps"][name] = {"status": "waiting", "at": ctx.now(), "result": {}}
    state["decisions"][name] = moved["pending_id"]
    state["failure"] = None
    save_state(ctx, state)
    return {"ok": True, "stopped": name, "pending": moved["pending_id"]}


def failure_record(name: str, failure: StepFailure, at: str) -> dict:
    return {"step": name, "code": failure.code, "field": failure.field if FIELD.fullmatch(failure.field) else "", "provider": failure.provider,
            "next": failure.next, "at": at}


def run(ctx: Context, state: dict) -> dict:
    """Run the steps from the first that is not done, until the review, the approval or a failure. The code task is
    `running` while this runs. Returns {"ok", "stopped" or "failed"/"code"..., "steps"}; never raises for a step."""
    waiting = next_step(state)
    if waiting in STOPS and step_status(state, waiting) == "waiting" and state["decisions"].get(waiting):
        # already stopped there with its decision open: nothing moves, nothing is opened a second time
        return {"ok": True, "stopped": waiting, "pending": state["decisions"][waiting], "steps": summary(state)}
    result, name = {"ok": True}, None
    try:
        ctx.move("running", None, None, None)
        for name in STEPS:
            if step_status(state, name) == "done":
                continue
            ctx.alive()
            if name == "review":
                result = _stop_at(ctx, state, name, review_decision)
                break
            if name == "approval":
                result = _stop_at(ctx, state, name, approval_decision)
                break
            try:
                outcome = EXECUTORS[name](ctx, state)
            except (cap.CaptionError, media.MediaError) as e:
                raise StepFailure(getattr(e, "code", "failed"), getattr(e, "field", "")) from None
            except OSError:   # a full disk, a folder that cannot be written: a closed word, never the system's message
                raise StepFailure("io_error", "") from None
            state["steps"][name] = {"status": "done", "at": ctx.now(), "result": outcome}
            state["failure"] = None
            save_state(ctx, state)
    except StepFailure as failure:
        name = name or "transcribe"
        state["steps"][name] = {"status": "failed", "at": ctx.now(), "result": {}}
        state["failure"] = failure_record(name, failure, ctx.now())
        save_state(ctx, state)
        ctx.move("failed", note_of(name, failure), None, None)
        return {"ok": False, "failed": name, "code": failure.code, "field": state["failure"]["field"], "next": failure.next,
                "steps": summary(state)}
    except Cancelled:
        return {"ok": False, "failed": None, "code": "cancelled", "field": "", "next": "", "steps": summary(state)}
    return {**result, "steps": summary(state)}


def answer_review(ctx: Context, state: dict, pending_id: int) -> None:
    """The person said done: the decision is resolved (an answer with no text) and the review step is done."""
    state["steps"]["review"] = {"status": "done", "at": ctx.now(), "result": {}}
    state["decisions"].pop("review", None)
    state.pop("sent_back_at", None)
    save_state(ctx, state)
    ctx.move("running", None, None, {"id": pending_id, "answer": "The captions were checked."})


def prepare_again(ctx: Context, state: dict, step: str) -> dict:
    """Start the pipeline over from `step`: that step and every later one become pending and the files they made are removed.
    From the review or before, the person's decision on a step is kept, so the captions open again as they were left;
    from `align-proposal` or before, the words are new, and the review starts over. A render stays (it is named by its
    bytes); retention removes it. Returns the steps that were reset."""
    if step not in STEPS or step == "approval":
        raise StepFailure("unknown_step", "step")
    start = STEPS.index(step)
    reset = [n for n in STEPS[start:] if n in state["steps"]]
    for name in STEPS[start:]:
        _remove_outputs(ctx, name, state)
        state["steps"].pop(name, None)
        state["decisions"].pop(name, None)
    if start <= STEPS.index(REVIEW_FILES_RESET_UP_TO):
        remove(ctx.path(EDITED))
        remove(ctx.path(REVIEW))
    state["failure"] = None
    save_state(ctx, state)
    return {"reset": reset}


def network_of(text: str):
    """The platform the post file names on its `- Network:` line, or None."""
    found = NETWORK_LINE.search(text or "")
    return found.group(1).lower() if found else None
