#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of the media pipeline (runtime/pipeline.py) and of the caption review (runtime/captions.py): `media-pipeline`,
`captions-read`, `captions-edit`, `captions-done` and `prepare-again`. A sibling of runtime/ops.py, which exposes each of them
under its name; no shell imports this file. The names every module of the layer shares are read as `core.<name>`.

  media_pipeline(project, recording, post, platform, request)   take a recording that is in the media store through the
                                   steps up to its rendered video and its cover, and stop with the task waiting. A code task
                                   (a task of a request with no skill, key `media:<recording id>`) carries it and the
                                   decisions. A step already done is not run again; a failed one is run again from there.
                                   The first call links the post file to the platform when `post` is given. A start that
                                   cannot work is refused before any task, state or link is made (the platform has no data file
                                   under shared/references/platforms/, the post file is not a regular file under docs/ or has no
                                   ```script block), so the recording is still one that has not started. A job: it takes
                                   minutes. No model is called. media-list also names these platforms (`platforms`).
  captions_read(project, recording)   the caption review the page shows: the transcript as caption chunks, the retakes
                                   proposed, the words whose timing was adjusted, each beat with its matched words and
                                   score, the words left out. The person's own words leave here, so it answers the
                                   terminal and the loopback page only (the table: no `mcp`, no `messaging`).
  captions_edit(project, recording, revision, edits)   the person's changes to words (edit, split, merge, delete), their
                                   answers on the retakes, anchors, dropped overlays, an empty slot's choice, the face box and
                                   the cover's offset, all re-mapped by code (runtime/captions.py). No time can be given.
  captions_done(project, recording, revision)   the person says the captions are right: the decision is answered, with no
                                   text in it, and the pipeline goes on from the re-map. A job.
  prepare_again(project, recording, step)   start over from a named step (the person's, from a Reject option or a changed
                                   post file). A job.

The images of the transcriber and of the renderer are built by the person's terminal commands, never by an operation: a
provider that says it is not set up stops the step with the command to run. Nothing here builds, pulls, fetches or pins.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import json
import os
import stat
import sys

import ops_core as core
import captions as cap
import isolated
import media
import pipeline
import workcopy

PROVIDERS = {"transcriber": "transcriber:speech", "renderer": "renderer:video"}
CHECKER = ("mkt-social-copy", "check_script.py")     # the skill that writes the script block checks it with its own script
TASK_KEY = "media:{}"                  # the key P7's video card is mounted on


def _refusal(error) -> "core.OpsError":
    if isinstance(error, media.MediaError):
        out = core.OpsError(str(error), 2 if error.kind in ("usage", "length") else 1)
        out.kind = error.kind
        return out
    if isinstance(error, cap.CaptionError):
        return core.OpsError(f"refused: {error.code}" + (f" {error.field}" if error.field else ""), 1)
    return core.OpsError(f"{error.code}" + (f" {error.field}" if error.field else "") + (f" -- {error.next}" if error.next else ""), 1)


def _resolver():
    return core._load("workbench_provider_resolve", os.path.join(core.ROOT, "providers", "resolve.py"))


ENV_KEEP = ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "OPENHORA_STATE_DIR",
            "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH",
            "TRANSCRIBER_SPEECH_PROVIDER", "TRANSCRIBER_PROVIDER", "RENDERER_VIDEO_PROVIDER", "RENDERER_PROVIDER")


def _provider_env() -> dict:
    """The whole environment a provider's process gets: what finds a program, a home, a docker daemon and the state folder, and the
    choice of the implementation of a class. Nothing else of the runtime's environment (a key, a token) reaches a container's client."""
    return {k: os.environ[k] for k in ENV_KEEP if k in os.environ}


def _caller(root: str):
    """The pipeline's one way to run a provider's verb: providers/resolve.py's call, its refusal read as a closed code. The
    command a refusal names is the script's path from the checkout, so that a job's result (read by the page) holds no absolute path."""
    resolve = _resolver()

    def call(cls: str, verb: str, args: list, timeout: int) -> dict:
        word = cls.split(":")[0]
        env = _provider_env()
        try:
            return resolve.call(cls, verb, args, root=root, timeout=timeout, env=env)
        except resolve.ProviderCallError as e:
            try:
                script = resolve.resolve(cls, root=root, env=env)["path"]
                script = os.path.relpath(script, root) if os.path.realpath(script).startswith(os.path.realpath(root) + os.sep) else script
            except Exception:   # the class does not resolve: there is no script to name
                script = ""
            raise pipeline.failure_from(word, e.kind, e.stderr_tail or e.reason, script) from None
    return call


def _data_dir(ctx: dict) -> str:
    return ctx["cfg"]["data_dir"]


def _rid(value) -> str:
    try:
        return media.check_id(value)
    except media.MediaError as e:
        raise _refusal(e) from None


def _record(ctx: dict, rid: str) -> dict:
    try:
        return media.load(_data_dir(ctx), rid)
    except media.MediaError as e:
        raise _refusal(e) from None


@contextlib.contextmanager
def _held(ctx: dict, task_id: int):
    """The task's lock, held while a pipeline step runs: the proof that the task is alive (runtime/ops_runs.py recovers a
    `running` task whose lock nobody holds). Not core._task_lock: that one writes the process group for `stop-runs --all` to
    signal, and the process here may be the local service."""
    fd = core._try_lock(ctx["cfg"], f"task-{task_id}.lock")
    if fd is None:
        raise core.OpsError(f"task {task_id} is already being run by another process", 1)
    try:
        yield
    finally:
        os.close(fd)


def _make_context(ctx: dict, rid: str, state: dict) -> pipeline.Context:
    cfg, store, task_id = ctx["cfg"], ctx["store"], state["task"]

    def move(word, note, pending, resolve):
        try:
            return store.code_task_move(ctx["conn"], task_id, state=word, note=note, pending=pending, resolve=resolve,
                                        by="user" if resolve else "code")
        except store.StoreError as e:
            if _stored_state(ctx, task_id) == "cancelled":
                raise pipeline.Cancelled() from None
            raise core.OpsError(str(e), e.code) from None

    def alive():
        if _stored_state(ctx, task_id) == "cancelled":
            raise pipeline.Cancelled()

    try:
        checker = isolated.skill_script(core.ROOT, *CHECKER)
    except ValueError:
        checker = ""
    return pipeline.Context(data_dir=_data_dir(ctx), project=cfg["project"], root=core.ROOT, rid=rid, platform=state["platform"],
                            post=state["post"], settings=cfg.get("media") or {}, call=_caller(core.ROOT), move=move,
                            scan=workcopy.credential_findings, alive=alive, checker=checker, now=media.stamp,
                            task_id=task_id, request_id=state["request"])


def _stored_state(ctx: dict, task_id: int):
    try:
        return ctx["store"].task_get(ctx["conn"], task_id)["state"]
    except ctx["store"].StoreError:
        return None


def _load_state(ctx: dict, rid: str):
    try:
        return pipeline.load_state(_data_dir(ctx), rid)
    except pipeline.StepFailure as e:
        raise _refusal(e) from None


def known_platforms() -> list:
    """The platforms this checkout has a data file for (shared/references/platforms/<platform>.json): the only networks a pipeline can be started for."""
    folder = os.path.join(core.ROOT, "shared", "references", "platforms")
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and media.PLATFORM.fullmatch(n[:-5]))


def _check_start(ctx: dict, platform: str, post: str) -> None:
    """What a start must hold before any task or state is made, so that a refused start leaves the recording as it was: the platform has a data file,
    and the post file is a regular file of the project (not a link) that has a ```script block."""
    known = known_platforms()
    if platform not in known:
        raise core.OpsError(f"{platform} is not a platform with a data file here ({', '.join(known) or 'none'}): name one of them with --network", 2)
    try:
        fd = os.open(pipeline.post_file(ctx["cfg"]["project"], post), os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, pipeline.StepFailure):
        raise core.OpsError("the post file cannot be read: it is a regular Markdown file under docs/ of the project", 2) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise core.OpsError("the post file cannot be read: it is a regular Markdown file under docs/ of the project", 2)
        with os.fdopen(fd, "rb", closefd=False) as f:
            text = f.read(pipeline.POST_LIMIT).decode("utf-8", "replace")
    finally:
        os.close(fd)
    if not pipeline.has_script(text):
        raise core.OpsError("the post file has no ```script block: a short video needs the script of its beats", 2)


def _platform_of(ctx: dict, record: dict, platform, post) -> tuple:
    """(platform, post path) for a pipeline that starts now: the post file the person names (linked to the recording here),
    or the one the recording has. The platform is the one given, else the one the post file's `- Network:` line names, else
    the recording's only one. Never a guess: a recording with several posts and no platform is a question."""
    data = _data_dir(ctx)
    if post is not None:
        if not isinstance(post, str) or not media.POST_PATH.fullmatch(post) or ".." in post.split("/") or "//" in post:
            raise core.OpsError("a post file is a Markdown file under docs/ of the project", 2)
        if platform is None:
            platform = _network_of(ctx["cfg"]["project"], post)
            if platform is None:
                raise core.OpsError("name the network with --network: the post file has no `- Network:` line to say it", 2)
        _check_start(ctx, platform, post)
        try:
            record = media.link_posts(data, record["id"], {platform: post})
        except media.MediaError as e:
            raise _refusal(e) from None
    posts = record.get("posts") or {}
    if platform is None:
        if len(posts) == 1:
            platform = next(iter(posts))
        else:
            raise core.OpsError("the recording has " + ("no post file" if not posts else "several post files")
                                + ": name the network with --network and the post file with --post", 2)
    if platform not in posts:
        raise core.OpsError(f"the recording has no post file for {platform}: give it with --post", 2)
    if post is None:
        _check_start(ctx, platform, posts[platform])      # a post file the recording had was checked when it was linked by a start; a link made elsewhere is not
    return platform, posts[platform]


def _network_of(project: str, post: str):
    """The platform a post file's `- Network:` line names; None when there is none or the file cannot be read (a link is not read)."""
    try:
        fd = os.open(pipeline.post_file(project, post), os.O_RDONLY | os.O_NOFOLLOW)
    except (OSError, pipeline.StepFailure):
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            return pipeline.network_of(f.read(pipeline.POST_LIMIT).decode("utf-8", "replace"))
    finally:
        os.close(fd)


def _new_task(ctx: dict, rid: str, request) -> dict:
    """The code task of a recording, made once: when the record already names one that is a code task of this recording it is the
    task (whoever asked first made it). A `request` must be a planned one: a done request is not reopened for a recording."""
    store = ctx["store"]
    known = (_record(ctx, rid).get("tasks") or {}).get("code")
    if known:
        try:
            found = store.task_get(ctx["conn"], known)
        except store.StoreError:
            found = None
        if found and found.get("key") == TASK_KEY.format(rid) and store.is_code_task(found):
            return {"task": found["id"], "request": found["parent_id"]}
    if request is not None:
        try:
            wanted = store.task_get(ctx["conn"], request)
        except store.StoreError as e:
            raise core.OpsError(str(e), e.code) from None
        if wanted["parent_id"] is not None or wanted["state"] != "planned":
            raise core.OpsError(f"request {request} is {wanted['state']}: a recording joins a planned request, never reopens a done one", 1)
    try:
        made = store.code_task_add(ctx["conn"], key=TASK_KEY.format(rid), title=f"Edit the recording {rid[:8]}",
                                   text=f"Take recording {rid} through the media pipeline up to its rendered video. No model runs.",
                                   request_id=request)
    except store.StoreError as e:
        raise core.OpsError(str(e), e.code) from None
    try:
        media.bind_tasks(_data_dir(ctx), rid, {"code": made["task"]})
    except media.MediaError as e:
        raise _refusal(e) from None
    return made


def _ensure_state(ctx: dict, rid: str, record: dict, network, post, request) -> dict:
    """The pipeline's state, made when the recording has none: under the recording's lock, so that two requests for one recording
    (a double click, two tabs) make one code task and one state file, and the second finds the first's."""
    with pipeline.recording_lock(_data_dir(ctx), rid):
        state = _load_state(ctx, rid)
        if state is not None:
            if network not in (None, state["platform"]) or post not in (None, state["post"]):
                raise core.OpsError(f"the pipeline of recording {rid} was started for {state['platform']} with {state['post']}: change the post "
                                    "file's text and use prepare-again, or start another recording", 1)
            return state
        platform, path = _platform_of(ctx, record, network, post)
        made = _new_task(ctx, rid, request)
        state = pipeline.new_state(rid, platform, path, made["task"], made["request"])
        pipeline.save_state(_make_context(ctx, rid, state), state)
        return state


def _locked_state(ctx: dict, rid: str) -> dict:
    """The state as the file holds it now, read inside the task's lock: what was read before the lock may be old."""
    state = _load_state(ctx, rid)
    if state is None:
        raise core.OpsError(f"the pipeline of recording {rid} has not started: media-pipeline starts it", 1)
    return state


def media_pipeline(project: str, recording: str, post: str | None = None, network: str | None = None, request: int | None = None) -> dict:
    """Take the recording through the steps up to the render and its cover, in this process, and stop at the caption
    review or, at the end, with the task waiting for the approval of the rendered file. See the module text. A second call while
    the first runs is refused (the task's lock); a call after it finds the state the first left. While it runs the code task
    is `running`, which counts against the project's `max_running` for the model tasks; the pipeline itself is started on
    request and is not admitted by the slots."""
    ctx = core.context(project)
    rid = _rid(recording)
    record = _record(ctx, rid)
    if not record.get("raw"):
        raise core.OpsError(f"recording {rid} has no file yet: take it in with media-in first", 1)
    state = _ensure_state(ctx, rid, record, network, post, request)
    with _held(ctx, state["task"]):
        state = _locked_state(ctx, rid)
        if not _cancelled(ctx, state):
            _consume_resume(ctx, rid, state)
        return _run(ctx, rid, state)


def _cancelled(ctx: dict, state: dict) -> bool:
    return _stored_state(ctx, state["task"]) == "cancelled"


def _refuse_cancelled(ctx: dict, state: dict) -> None:
    if _cancelled(ctx, state):
        raise core.OpsError(f"request {state['request']} was cancelled: the pipeline of this recording stopped with it", 1)


def _resume_marker(ctx: dict, rid: str, state: dict):
    """The page's send-back (runtime/ops_video.py) leaves `resume = {"step": "review", "reason": "sent_back", "platform", "at"}` in
    the recording's record. This is that marker when it is this pipeline's (its platform, the review), else None: a marker for
    another platform or another step is left alone."""
    marker = _record(ctx, rid).get("resume")
    if isinstance(marker, dict) and marker.get("step") == "review" and marker.get("reason") == "sent_back" \
            and marker.get("platform") in (None, state["platform"]):
        return marker
    return None


def _clear_resume(ctx: dict, rid: str, state: dict, marker: dict) -> None:
    """The marker is consumed: the decision will say the video was sent back (the comment is shown by `captions-read`, never put
    in a decision), and the record no longer asks. Only the marker that was read is removed: a send-back made since stays."""
    state["sent_back_at"] = marker.get("at")
    pipeline.save_state(_make_context(ctx, rid, state), state)

    def pop(record):
        if record.get("resume") == marker:
            record.pop("resume", None)
    try:
        media.update(_data_dir(ctx), rid, pop)
    except media.MediaError as e:
        raise _refusal(e) from None


def _consume_resume(ctx: dict, rid: str, state: dict) -> bool:
    """Open the review again as the person left it (no model, no provider run) when the page sent the video back, and clear the
    marker. Called with the task's lock held and the state read under it. Before the review was reached there is nothing to
    reopen: the pipeline gets there by itself. Returns whether a marker was consumed."""
    marker = _resume_marker(ctx, rid, state)
    if marker is None:
        return False
    if all(pipeline.step_status(state, n) == "done" for n in pipeline.STEPS[:4]):
        try:
            pipeline.prepare_again(_make_context(ctx, rid, state), state, "review")
        except pipeline.StepFailure as e:
            raise _refusal(e) from None
    _clear_resume(ctx, rid, state, marker)
    return True


def _run(ctx: dict, rid: str, state: dict) -> dict:
    """Run the pipeline from where the state says. The caller holds the task's lock."""
    pc = _make_context(ctx, rid, state)
    if _cancelled(ctx, state):
        return {"recording": rid, "task": state["task"], "request": state["request"], "platform": state["platform"], "ok": False, "failed": None,
                "code": "cancelled", "field": "", "next": "", "steps": pipeline.summary(state)}
    try:
        outcome = pipeline.run(pc, state)
    except pipeline.StepFailure as e:   # a failure of the state file itself: nothing to record it in
        raise _refusal(e) from None
    return {"recording": rid, "task": state["task"], "request": state["request"], "platform": state["platform"], **outcome}


# --- the caption review ----------------------------------------------------------------------------------------------------------------


def _documents(pc: pipeline.Context, need_review: bool = False) -> dict:
    """The files the review reads: transcript.json, the edited transcript (the transcript itself, edited by nobody yet), the
    review state, and the proposal edit list and beats."""
    try:
        edited_path = pc.path(pipeline.EDITED)
        edited = cap.check_edited(pipeline.read_json(edited_path, pipeline.EDITED)) if pipeline.exists(edited_path) else \
            cap.start_edited(pipeline.read_json(pc.path(pipeline.TRANSCRIPT), pipeline.TRANSCRIPT))
        review = pipeline.load_review(pc)
        return {"edited": edited, "review": review, "edl": pipeline.read_json(pc.path(pipeline.PROPOSAL_EDL), pipeline.PROPOSAL_EDL),
                "beats": pipeline.read_json(pc.path(pipeline.PROPOSAL_BEATS), pipeline.PROPOSAL_BEATS)}
    except (pipeline.StepFailure, cap.CaptionError) as e:
        raise _refusal(e) from None


def _assets(pc: pipeline.Context, record: dict, beats: dict) -> dict:
    out = {}
    for s in beats.get("slots") or []:
        held = (record.get("slots") or {}).get(media.slot_id(pc.rid, s["slot"]))
        asset = held.get("asset") if isinstance(held, dict) else None
        out[s["slot"]] = None if not asset else {"name": asset.get("name"), "type": asset.get("type"), "sha256": asset.get("sha256"),
                                                 "stale": bool(asset.get("stale"))}
    return out


def _review_ready(state) -> None:
    if state is None or any(pipeline.step_status(state, n) != "done" for n in pipeline.STEPS[:4]):
        where = "has not started" if state is None else f"is at {pipeline.next_step(state)}"
        raise core.OpsError(f"the captions are not ready: the pipeline {where}", 1)


def _sent_back(record: dict, state: dict):
    """What the page's send-back kept for this platform: the person's comment, when, and the render it was about; None otherwise."""
    back = record.get("sent_back")
    if isinstance(back, dict) and back.get("platform") in (None, state["platform"]):
        return {"comment": back.get("comment"), "at": back.get("at"), "render_sha256": back.get("render_sha256")}
    return None


def captions_read(project: str, recording: str) -> dict:
    """The caption review of a recording as the page shows it (runtime/captions.py, `view`), with where the pipeline stands."""
    ctx = core.context(project)
    rid = _rid(recording)
    state = _load_state(ctx, rid)
    _review_ready(state)
    pc = _make_context(ctx, rid, state)
    docs = _documents(pc)
    try:
        docs["review"] = cap.reconcile(docs["edited"], docs["review"])
    except cap.CaptionError as e:
        raise _refusal(e) from None
    record = _record(ctx, rid)
    shown = cap.view(docs["edited"], docs["review"], docs["edl"], docs["beats"], _assets(pc, record, docs["beats"]))
    return {"recording": rid, "platform": state["platform"], "task": state["task"], "steps": pipeline.summary(state),
            "still": pipeline.still_of(state), "editable": pipeline.step_status(state, "review") == "waiting", "language": docs["edited"].get("language"),
            "failure": state.get("failure"), "sent_back": _sent_back(_record(ctx, rid), state), **shown}


def _json_edits(text) -> list:
    try:
        value = json.loads(text)
    except (TypeError, ValueError, RecursionError):
        raise core.OpsError("edits is not valid JSON: a list of edit objects", 2) from None
    if not isinstance(value, list):
        raise core.OpsError("edits is a list of edit objects", 2)
    return value


def captions_edit(project: str, recording: str, revision: int, text: str) -> dict:
    """Apply the person's edits to the words of a recording and their decisions on the review, re-mapped by code onto word
    indices (runtime/captions.py). `revision` is the one the view carried; `text` is the JSON list of the closed edit objects.
    Refused unless the pipeline waits at the review. Writes the edited transcript and then the review state, outside the project,
    under the task's lock; if a crash cuts the two writes apart the transcript is one revision ahead, and the next read takes its
    revision (captions.reconcile): the person's words are never the thing lost. Returns the review as `captions_read` does."""
    ctx = core.context(project)
    rid = _rid(recording)
    state = _load_state(ctx, rid)
    _review_ready(state)
    items = _json_edits(text)
    with _held(ctx, state["task"]):
        state = _locked_state(ctx, rid)
        _refuse_cancelled(ctx, state)
        if pipeline.step_status(state, "review") != "waiting":
            raise core.OpsError("the captions are not open for edits: the pipeline is not waiting at the review "
                                "(prepare-again --step review opens them again)", 1)
        pc = _make_context(ctx, rid, state)
        docs = _documents(pc)
        try:
            docs["review"] = cap.reconcile(docs["edited"], docs["review"])
            edited, review, counts = cap.apply_edits(
                docs["edited"], docs["review"], items, revision=revision, proposals=cap.retake_ranges(docs["edl"]),
                beats={r["beat"] for r in docs["beats"].get("report") or [] if r.get("preset")},
                slots={s["slot"] for s in docs["beats"].get("slots") or []}, limits=_limits())
        except cap.CaptionError as e:
            raise _refusal(e) from None
        if pc.scan(" ".join(w["text"] for w in edited["words"])):
            raise core.OpsError("refused: credential_in_transcript edits", 1)
        try:
            pipeline.write_json(pc.path(pipeline.EDITED), edited)
            pipeline.write_json(pc.path(pipeline.REVIEW), review)
        except OSError as e:
            raise core.OpsError(f"the review could not be written: {e.strerror}", 1) from None
        shown = cap.view(edited, review, docs["edl"], docs["beats"], _assets(pc, _record(ctx, rid), docs["beats"]))
    return {"recording": rid, "applied": counts, "editable": True, **shown}


def _limits() -> dict:
    """The renderer's own limits on a word (providers/renderer/renderer-presets.json), so that the review refuses what the
    renderer would, before any step runs; the defaults of runtime/captions.py when the file cannot be read."""
    try:
        with open(os.path.join(core.ROOT, "providers", "renderer", "renderer-presets.json"), encoding="utf-8") as f:
            found = json.load(f)["limits"]
        return {"word_chars_max": int(found["word_chars_max"]), "words_max": int(found["words_max"])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _unanswered_slots(pc: pipeline.Context, record: dict, beats: dict, review: dict) -> list:
    assets = _assets(pc, record, beats)
    return [s for s, a in assets.items() if (a is None or a["stale"]) and s not in review["empty_slots"]]


def captions_done(project: str, recording: str, revision: int) -> dict:
    """The person says the captions are right. `revision` is the review's revision the view they looked at carried, required: an
    answer to captions that have since changed is refused. The decision is answered (by the person; the answer holds no text) and
    the pipeline goes on from the re-map: base list, alignment with the person's anchors, check, render, cover. Refused while an
    asset slot has neither a file nor a choice."""
    ctx = core.context(project)
    rid = _rid(recording)
    state = _load_state(ctx, rid)
    _review_ready(state)
    with _held(ctx, state["task"]):
        state = _locked_state(ctx, rid)
        _refuse_cancelled(ctx, state)
        if pipeline.step_status(state, "review") != "waiting":
            raise core.OpsError("the captions are not waiting for an answer: the pipeline is not at the review", 1)
        pc = _make_context(ctx, rid, state)
        docs = _documents(pc)
        try:
            docs["review"] = cap.reconcile(docs["edited"], docs["review"])
        except cap.CaptionError as e:
            raise _refusal(e) from None
        if revision != docs["review"]["revision"]:
            raise core.OpsError("refused: stale_revision revision", 1)
        empty = _unanswered_slots(pc, _record(ctx, rid), docs["beats"], docs["review"])
        if empty:
            raise core.OpsError("refused: slot_needs_a_choice " + empty[0] + ": give each asset slot a file (media-in --slot) or a choice "
                                "(keyword or none) before you say done", 1)
        pending_id = state["decisions"].get("review")
        if not isinstance(pending_id, int):
            raise core.OpsError("the decision \"Check the captions\" is not open: prepare-again --step review opens it again", 1)
        pipeline.answer_review(pc, state, pending_id)
        return _run(ctx, rid, state)


def prepare_again(project: str, recording: str, step: str) -> dict:
    """Start the pipeline of a recording over from a named step and run it. From `review` the captions open again as the
    person left them; from `align-proposal` or before, the words are new and the review starts over. Refused while the
    pipeline runs. The person starts it: a Reject option of the page, or a changed post file."""
    ctx = core.context(project)
    rid = _rid(recording)
    state = _load_state(ctx, rid)
    if state is None:
        raise core.OpsError(f"the pipeline of recording {rid} has not started: media-pipeline starts it", 1)
    with _held(ctx, state["task"]):
        state = _locked_state(ctx, rid)
        _refuse_cancelled(ctx, state)
        pc = _make_context(ctx, rid, state)
        if step in pipeline.SIDE_STEPS:
            return _remake_side_step(ctx, rid, state, pc, step)
        marker = _resume_marker(ctx, rid, state)
        if marker is not None and pipeline.ORDER.index(step) > pipeline.ORDER.index("review"):
            step = "review"      # a video sent back from the page reopens the captions, whatever later step was asked
        try:
            reset = pipeline.prepare_again(pc, state, step)
        except pipeline.StepFailure as e:
            raise _refusal(e) from None
        if marker is not None:
            _clear_resume(ctx, rid, state, marker)
        return {**_run(ctx, rid, state), **reset}


def _remake_side_step(ctx: dict, rid: str, state: dict, pc: pipeline.Context, step: str) -> dict:
    """`prepare-again --step still`: the still alone. It touches nothing else: the page's send-back marker is not consumed (a
    main step's prepare-again or the next media-pipeline does that), the pipeline's `failure` stays, no main step runs again
    (a failed one is not relaunched), the decision and the task are not moved. Refused while the review is answered or the
    recording is not analysed, before anything is changed, and the earlier still is kept when the remake is skipped."""
    if not pipeline.side_step_due(state):
        raise core.OpsError("the still is the picture behind the face box of the caption review, which is already answered or not reached: "
                            "open the captions again (prepare-again --step review) and it is made there", 1)
    try:
        done = pipeline.remake_side_step(pc, state, step)
    except pipeline.Cancelled:
        return {"recording": rid, "task": state["task"], "request": state["request"], "platform": state["platform"], "ok": False, "failed": None,
                "code": "cancelled", "field": "", "next": "", "steps": pipeline.summary(state)}
    except pipeline.StepFailure as e:
        raise _refusal(e) from None
    waiting = pipeline.next_step(state)
    out = {"recording": rid, "task": state["task"], "request": state["request"], "platform": state["platform"], "ok": True,
           "steps": pipeline.summary(state), "still": pipeline.still_of(state), "reset": done["reset"], "still_status": done["status"]}
    if done["code"]:
        out["still_code"] = done["code"]
    if waiting in pipeline.STOPS and pipeline.step_status(state, waiting) == "waiting" and state["decisions"].get(waiting):
        out.update(stopped=waiting, pending=state["decisions"][waiting])
    return out


def run_active(ctx: dict, task_id: int) -> bool:
    """Whether a process is running the task's pipeline now: its lock is held (a closed or dead process releases it, so a held lock is the proof). A shared probe: it
    never takes the lock from a runner, and it does not make a lock file that is not there."""
    cfg = ctx["cfg"]
    name = f"task-{task_id}.lock"
    if not os.path.exists(os.path.join(core._locks_dir(cfg), name)):
        return False
    fd = core._try_lock(cfg, name, shared=True)
    if fd is None:
        return True
    os.close(fd)
    return False


def pipeline_summary(data_dir: str, rid: str, ctx: dict | None = None):
    """What `media-list` shows of a recording's pipeline: its steps, where it stands, the last failure and, when a context is given, whether a process is running
    it now (`active`: a step left pending with no failure and nobody running it is a pipeline that stopped, for instance a cancelled request or a killed service);
    None before it started or when its file cannot be read."""
    try:
        state = pipeline.load_state(data_dir, rid)
    except pipeline.StepFailure:
        return None
    if state is None:
        return None
    shown = {"task": state["task"], "request": state["request"], "platform": state["platform"], "steps": pipeline.summary(state),
             "next": pipeline.next_step(state), "failure": state.get("failure"), "still": pipeline.still_of(state)}
    if ctx is not None:
        shown["active"] = run_active(ctx, state["task"])
    return shown


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
