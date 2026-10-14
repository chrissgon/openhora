"""The media pipeline operation and its code task (package P4b of the short-video plan), through the real operations layer, the
real store and the real renderer logic (`base`, `align`, `check` of providers/renderer/_inner.py), with stand-in providers for the
containers (runtime/tests/pipeline_kit.py): a recording takes every step up to its render and its cover, the pipeline stops at the
caption review before anything is rendered, every step's failure is resumable at that step, and no model is ever called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_pipeline.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import types

import pytest

import pipeline_kit as kit
import standin_tree as st
from media_fixtures import png, webp

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
media = st.load("media")
pipeline = st.load("pipeline")
captions = st.load("captions")
project_config = st.load("project_config")

SPOKEN = {x["text"].strip(".,:?").lower() for x in kit.build_transcript()[0]["words"] if len(x["text"].strip(".,:?")) >= 4}   # the speaker's words


def make_world(tmp_path, monkeypatch, *, post=kit.POST, transcript=None, settings=True):
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    project, data = str(built["project"]), str(built["data"])
    made, silences = transcript or kit.build_transcript()
    kit.stand_in_providers(tree, made, silences)
    file = os.path.join(project, *kit.POST_PATH.split("/"))
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "w", encoding="utf-8") as f:
        f.write(post)
    config = os.path.join(project, "docs", "workbench", "runtime.json")
    doc = json.load(open(config))
    if settings:
        doc["media"] = {"model": "small", "language": "pt"}
    json.dump(doc, open(config, "w"))
    ops.accept_config(project, project_config.load(project)["sha256"])
    record = kit.make_recording(data, media)
    return types.SimpleNamespace(tree=tree, project=project, data=data, rid=record["id"], adapter=built["adapter"], tmp=tmp_path,
                                 folder=media.folder_of(data, record["id"]))


@pytest.fixture
def w(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """The same world with a post whose beat 7 is a cutaway: it has one asset slot, `beat7`."""
    return make_world(tmp_path, monkeypatch, post=kit.POST_SLOT)


def finish_review(w):
    """captions-done with the revision the person's view carries now."""
    return ops.captions_done(w.project, w.rid, ops.captions_read(w.project, w.rid)["revision"])


def start(w, **kw):
    return ops.media_pipeline(w.project, w.rid, **({"post": kit.POST_PATH} | kw))


def state(w):
    with open(os.path.join(w.folder, "pipeline.json"), encoding="utf-8") as f:
        return json.load(f)


def edit(w, edits, revision=None):
    shown = ops.captions_read(w.project, w.rid)
    return ops.captions_edit(w.project, w.rid, shown["revision"] if revision is None else revision, json.dumps(edits))


def code_task(w):
    return ops.task(w.project, media.load(w.data, w.rid)["tasks"]["code"])["task"]


def word_index(w, text, nth=0):
    words = ops.captions_read(w.project, w.rid)["words"]
    return [x["index"] for x in words if x["text"] == text][nth]


def beat_args(call):
    return {call[i]: call[i + 1] for i in range(1, len(call) - 1) if call[i].startswith("--")}


def renders(w):
    return sorted(n for n in os.listdir(w.folder) if media.RENDER.fullmatch(n))


RENDERER_ORDER = ["analyse", "base", "align", "base", "align", "check", "render", "cover"]


# --- the steps, in order, and the stop at the review ----------------------------------------------------------------------------------


def test_a_recording_runs_the_steps_in_order_and_stops_at_the_caption_review_before_any_render(w):
    out = start(w)
    assert out["ok"] is True and out["stopped"] == "review" and out["platform"] == "instagram"
    assert out["steps"] == {"transcribe": "done", "analyse": "done", "retakes": "done", "align-proposal": "done", "review": "waiting",
                            "remap": "pending", "base": "pending", "align": "pending", "check": "pending", "render": "pending",
                            "cover": "pending", "approval": "pending"}
    assert kit.verbs(w.tree, "transcriber") == ["transcribe"] and kit.verbs(w.tree, "renderer") == ["analyse", "base", "align"]
    assert not renders(w) and not [n for n in os.listdir(w.folder) if n.startswith("cover") or n == "render.json"] and not os.path.exists(os.path.join(w.folder, "edl.json"))
    pending = ops.pending(w.project)["pending"]
    assert [(p["kind"], p["title"], p["task_id"]) for p in pending] == [("question", "Check the captions", out["task"])]
    # a second call while it waits starts nothing and opens no second decision
    again = start(w)
    assert again["stopped"] == "review" and again["pending"] == out["pending"]
    assert kit.verbs(w.tree, "renderer") == ["analyse", "base", "align"] and len(ops.pending(w.project)["pending"]) == 1


def test_the_transcriber_is_asked_for_dtw_timestamps_with_the_projects_model_and_language_and_the_mode_is_recorded(w):
    start(w)
    call = kit.calls(w.tree, "transcriber")[0]
    args = beat_args(call)
    assert args["--timestamps"] == "dtw" and args["--model"] == "small" and args["--language"] == "pt" and args["--max-seconds"] == "300"
    assert args["--in"] == os.path.join(w.folder, "raw.mov") and args["--out"] == os.path.join(w.folder, "transcript.json")
    done = state(w)["steps"]["transcribe"]["result"]
    assert done["timestamps"] == "dtw" and done["model"] == "small" and done["language"] == "pt"
    assert json.load(open(os.path.join(w.folder, "transcript.json")))["facts"]["timestamps"] == "dtw"


def test_the_code_task_has_a_parent_request_a_key_and_no_skill_and_no_text_of_the_transcript_reaches_the_store(w):
    out = start(w)
    task = code_task(w)
    assert task["id"] == out["task"] and task["parent_id"] == out["request"] and task["skill"] is None
    assert task["key"] == f"media:{w.rid}" and task["state"] == "waiting" and task["agent"] is None
    assert media.load(w.data, w.rid)["tasks"]["code"] == task["id"]
    request = next(r for r in ops.status(w.project)["requests"] if r["id"] == out["request"])
    assert request["state"] == "planned" and [t["id"] for t in request["tasks"]] == [task["id"]]
    item = ops.pending(w.project, out["pending"])
    texts = " ".join([item["title"], item["body"], json.dumps(item["payload"]), str(task.get("note"))])
    assert w.rid in texts and "retake" in texts
    assert not set(re.findall(r"\w+", texts.lower())) & SPOKEN, "no word of the speaker is in a decision, a note or a payload"
    assert "85 words" in texts and "1 retake proposals" in texts


def test_the_answer_runs_the_rest_in_order_and_stops_with_the_task_waiting_for_the_approval_of_the_rendered_file(w):
    start(w)
    done = finish_review(w)
    assert done["ok"] is True and done["stopped"] == "approval"
    assert done["steps"]["approval"] == "waiting" and all(v == "done" for k, v in done["steps"].items() if k != "approval")
    assert kit.verbs(w.tree, "renderer") == RENDERER_ORDER and kit.verbs(w.tree, "transcriber") == ["transcribe"], "the earlier steps are not run again"
    result = state(w)["steps"]
    name = result["render"]["result"]["name"]
    path = os.path.join(w.folder, name)
    assert media.RENDER.fullmatch(name) and stat.S_IMODE(os.stat(path).st_mode) == 0o400
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == result["render"]["result"]["sha256"] and name == f"render-{result['render']['result']['sha256'][:12]}.mp4"
    sha = result["render"]["result"]["sha256"]
    cover = result["cover"]["result"]
    assert cover["name"] == f"cover-{sha[:12]}.png" and cover["offset_ms"] == 0 and os.path.isfile(os.path.join(w.folder, cover["name"]))
    assert hashlib.sha256(open(os.path.join(w.folder, cover["name"]), "rb").read()).hexdigest() == cover["sha256"]
    # the renderer's result as the page reads it (runtime/video.py): sha256, bytes, output facts, cover offset and hash
    kept = json.load(open(os.path.join(w.folder, "render.json")))
    assert kept["sha256"] == sha and kept["bytes"] == os.path.getsize(path) and kept["output"]["width"] == 1080 and kept["name"] == name
    assert kept["cover"] == {"offset_ms": 0, "sha256": cover["sha256"], "name": cover["name"]} and stat.S_IMODE(os.stat(os.path.join(w.folder, "render.json")).st_mode) == 0o600
    pending = ops.pending(w.project)["pending"]
    assert [(p["kind"], p["title"]) for p in pending] == [("question", "Approve the rendered video")]
    item = ops.pending(w.project, pending[0]["id"])
    mp = item["payload"]["media_pipeline"]
    assert mp["step"] == "approval" and mp["render"]["sha256"] == result["render"]["result"]["sha256"] and mp["cover"]["name"] == cover["name"]
    assert code_task(w)["state"] == "waiting"
    review = ops.task(w.project, code_task(w)["id"])["pending"]
    assert [p["status"] for p in review] == ["resolved", "open"] and review[0]["answer"] == "The captions were checked."


def test_nothing_after_the_render_is_built_here_no_payload_no_dry_run_no_effect(w):
    start(w)
    finish_review(w)
    assert not os.path.exists(os.path.join(w.folder, "payload"))
    assert not [p for p in ops.pending(w.project)["pending"] if p["kind"] == "effect"]
    assert kit.verbs(w.tree, "renderer")[-2:] == ["render", "cover"]


# --- every step fails on a stand-in and the task resumes at that step ---------------------------------------------------------


FAILING = [("transcribe", "transcriber", "transcribe", 0, False), ("analyse", "renderer", "analyse", 0, False),
           ("retakes", "renderer", "base", 0, False), ("align-proposal", "renderer", "align", 0, False),
           ("base", "renderer", "base", 1, True), ("align", "renderer", "align", 1, True), ("check", "renderer", "check", 0, True),
           ("render", "renderer", "render", 0, True), ("cover", "renderer", "cover", 0, True)]
ORDER = pipeline.STEPS


@pytest.mark.parametrize("step,role,verb,skip,after_review", FAILING)
def test_each_step_fails_on_a_stand_in_and_the_task_resumes_at_that_step_with_the_earlier_results_not_repeated(w, step, role, verb, skip, after_review):
    kit.fail(w.tree, role, verb, skip=skip, stderr="refused: browser_failed x\n  reason: the secret text of a tool's log")
    first = start(w)
    if after_review:
        assert first["stopped"] == "review"
        first = finish_review(w)
    assert first["ok"] is False and first["failed"] == step and first["code"] == "browser_failed"
    before = {r: kit.verbs(w.tree, r) for r in ("transcriber", "renderer")}
    saved = state(w)
    assert saved["failure"]["step"] == step and saved["steps"][step]["status"] == "failed"
    for earlier in ORDER[:ORDER.index(step)]:
        if earlier not in ("review",):
            assert saved["steps"][earlier]["status"] == "done", earlier
    task = code_task(w)
    assert task["state"] == "failed" and task["note"].startswith(f"{step}: browser_failed") and "secret text" not in task["note"]
    assert "secret text" not in json.dumps(saved)
    with pytest.raises(ops.OpsError, match="media pipeline task.*media-pipeline --recording " + w.rid):
        ops.retry(w.project, task["id"])
    assert code_task(w)["state"] == "failed", "a retry of the store does not make it ready: no model run can pick it up"
    kit.heal(w.tree, role)
    resumed = ops.media_pipeline(w.project, w.rid)
    after = {r: kit.verbs(w.tree, r) for r in ("transcriber", "renderer")}
    new = {r: after[r][len(before[r]):] for r in after}
    assert resumed["ok"] is True and resumed["steps"][step] == "done"
    wanted = {"transcribe": ([ "transcribe"], ["analyse", "base", "align"]), "analyse": ([], ["analyse", "base", "align"]),
              "retakes": ([], ["base", "align"]), "align-proposal": ([], ["align"]), "base": ([], ["base", "align", "check", "render", "cover"]),
              "align": ([], ["align", "check", "render", "cover"]), "check": ([], ["check", "render", "cover"]), "render": ([], ["render", "cover"]),
              "cover": ([], ["cover"])}[step]
    assert (new["transcriber"], new["renderer"]) == wanted, "what runs again is the failed step and the ones after it, never an earlier one"
    assert resumed["stopped"] == ("review" if not after_review else "approval")


def test_a_credential_in_the_transcript_stops_the_remap_and_the_person_fixes_it_in_the_review(tmp_path, monkeypatch):
    secret = "AKIA" + "ABCDEFGHIJKLMNOP"   # built here so that no fake key sits in the source
    transcript, silences = kit.build_transcript()
    transcript["words"][5]["text"] = secret
    w = make_world(tmp_path, monkeypatch, transcript=(transcript, silences))
    start(w)
    with pytest.raises(ops.OpsError, match="credential_in_transcript"):
        edit(w, [{"op": "delete", "index": 40}])
    out = finish_review(w)
    assert out["ok"] is False and out["failed"] == "remap" and out["code"] == "credential_in_transcript"
    assert secret not in json.dumps(state(w)) and secret not in str(code_task(w))
    assert not os.path.exists(os.path.join(w.folder, "edl.json"))


def test_a_failure_note_carries_a_closed_code_never_the_text_a_tool_printed(w):
    kit.fail(w.tree, "renderer", "analyse", stderr="Traceback (most recent call last): oi gente tá bom? sk-" + "a" * 40, exit=1)
    out = start(w)
    assert out["ok"] is False and out["code"] == "failed" and out["failed"] == "analyse"
    text = json.dumps([state(w), code_task(w), ops.status(w.project)])
    assert "Traceback" not in text and "oi gente" not in text and "sk-aaaa" not in text


# --- a provider that is not set up: the refusal names the command, and the pipeline never runs it ---------------------------------


@pytest.mark.parametrize("role,verb,stderr,code,command", [
    ("renderer", "analyse", "refused: image_not_built renderer\n  run: python3 providers/renderer/ffmpeg.py build --confirmed", "image_not_built",
     "providers/renderer/standin.py build --confirmed"),
    ("renderer", "analyse", "refused: image_stale renderer", "image_stale", "providers/renderer/standin.py build --confirmed"),
    ("renderer", "analyse", "refused: pin_incomplete browser", "pin_incomplete", "providers/renderer/standin.py pin-browser --confirmed"),
    ("renderer", "analyse", "refused: docker_missing docker", "docker_missing", "install Docker"),
    ("transcriber", "transcribe", "the image openhora-transcriber:abc123 is not built: run `python3 providers/transcriber/whispercpp.py build --confirmed` "
     "(it downloads the base image)", "image_not_built", "providers/transcriber/standin.py build --confirmed"),
    ("transcriber", "transcribe", "model small is not at /models/ggml-small.bin (a regular file is expected); see providers/transcriber/README.md",
     "model_missing", "providers/transcriber/standin.py models"),
    ("transcriber", "transcribe", "docker is not installed or not on PATH (the transcriber runs whisper.cpp in a container)", "docker_missing",
     "install Docker"),
])
def test_a_missing_image_or_model_is_a_clear_refusal_with_the_command_to_run_and_nothing_is_built(w, role, verb, stderr, code, command):
    kit.fail(w.tree, role, verb, exit=3, stderr=stderr)
    out = start(w)
    assert out["ok"] is False and out["code"] == code and command in out["next"]
    assert out["next"].startswith("python3 ") == ("install Docker" not in command)
    task = code_task(w)
    assert task["state"] == "failed" and command in task["note"]
    for r in ("transcriber", "renderer"):
        assert not {"build", "models", "fetch-model", "pin-browser", "pin-templates", "reap"} & set(kit.verbs(w.tree, r)), "a setup verb is the person's command"
    kit.heal(w.tree, role)
    assert ops.media_pipeline(w.project, w.rid)["stopped"] == "review"


def test_a_project_with_no_media_settings_stops_at_the_first_step_and_says_which(tmp_path, monkeypatch):
    w = make_world(tmp_path, monkeypatch, settings=False)
    out = start(w)
    assert out["ok"] is False and out["failed"] == "transcribe" and out["code"] == "not_configured" and out["field"] == "media.model"
    assert "accept-config" in out["next"] and kit.verbs(w.tree, "transcriber") == []


def test_the_media_settings_of_the_configuration_are_closed(tmp_path):
    for bad in ({"model": "../x"}, {"model": 3}, {"language": "Portuguese"}, {"colour": "red"}, "small", ["small"]):
        with pytest.raises(project_config.ConfigError):
            project_config._media(bad)
    assert project_config._media(None) == {} and project_config._media({"model": "large-v3-turbo", "language": "auto"}) == {"model": "large-v3-turbo", "language": "auto"}


# --- no model, ever -----------------------------------------------------------------------------------------------------------------


def test_no_model_run_is_ever_started_for_the_code_task(w):
    start(w)
    task = code_task(w)["id"]
    assert ops.run_next(w.project)["ran"] is None
    finish_review(w)
    assert ops.run_next(w.project)["ran"] is None
    ops.dispatch(w.project, wait=True)
    assert not (w.adapter / "calls.txt").exists() and ops.task(w.project, task)["runs"] == []
    kit.fail(w.tree, "renderer", "cover", times=1)
    ops.prepare_again(w.project, w.rid, "cover")
    assert code_task(w)["state"] == "failed"
    claimed = ops_core.context(w.project)
    assert claimed["store"].task_claim(claimed["conn"], task) == {"task": None, "reason": "not-ready"}
    assert not (w.adapter / "calls.txt").exists()


def test_a_decision_of_the_pipeline_is_not_answered_released_rejected_or_approved_as_a_task_decision(w):
    out = start(w)
    for call in (lambda: ops.answer(w.project, out["pending"], "yes, go on"), lambda: ops.release(w.project, out["pending"]),
                 lambda: ops.reject(w.project, out["pending"]), lambda: ops.approve(w.project, out["pending"])):
        with pytest.raises(ops.OpsError):
            call()
    assert ops.pending(w.project, out["pending"])["status"] == "open" and code_task(w)["state"] == "waiting"


def test_the_cancel_of_the_request_stops_the_pipeline_without_a_failure(w):
    out = start(w)
    ops.cancel(w.project, out["request"])
    assert code_task(w)["state"] == "cancelled"
    result = ops.media_pipeline(w.project, w.rid)
    assert result["ok"] is False and result["code"] == "cancelled"
    assert kit.verbs(w.tree, "renderer") == ["analyse", "base", "align"]


# --- the caption review ---------------------------------------------------------------------------------------------------------------


def test_the_review_shows_chunks_retimed_words_retakes_and_beats_with_their_range_and_score(ws):
    start(ws)
    shown = ops.captions_read(ws.project, ws.rid)
    assert shown["editable"] is True and shown["language"] == "pt" and shown["steps"]["review"] == "waiting" and shown["revision"] == 0
    assert [x["text"] for x in shown["words"][:4]] == ["Oi", "gente,", "tá", "bom?"]
    assert shown["words"][0]["timing_adjusted"] and shown["words"][1]["timing_adjusted"] and not shown["words"][2]["timing_adjusted"]
    assert shown["counts"]["timing_adjusted"] == 2 and shown["chunks"][0]["words"] == [0, 1, 2]
    [retake] = shown["retakes"]
    assert retake["id"] == "retake-1" and retake["confirmed"] is False and retake["word_to"] + 1 == retake["keep_from"]
    texts = " ".join(x["text"] for x in shown["words"][retake["word_from"]:retake["word_to"] + 1])
    assert texts.startswith("Depois faz")
    rows = {b["beat"]: b for b in shown["beats"]}
    assert set(rows) == {3, 4, 5, 6, 7} and all(r["matched"] and not r["below_threshold"] for r in rows.values())
    assert shown["threshold"] == 0.6 and rows[4]["word_from"] > retake["word_to"], "a retake: the later take wins"
    assert shown["slots"][0]["slot"] == "beat7" and shown["slots"][0]["file"] is None


def test_a_beat_below_the_threshold_is_flagged_gets_no_overlay_and_an_anchor_overrides_the_match(tmp_path, monkeypatch):
    post = kit.POST.replace("line: Esse hábito me poupou trezentos e quarenta reais num mês só.", "line: Isso rendeu um bom troco no fim do ano inteiro.")  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    w = make_world(tmp_path, monkeypatch, post=post)
    start(w)
    shown = ops.captions_read(w.project, w.rid)
    row = next(b for b in shown["beats"] if b["beat"] == 5)
    assert row["below_threshold"] is True and row["matched"] is False and shown["counts"]["below_threshold"] == 1
    # without an anchor the beat gets no overlay and is reported on the task
    finish_review(w)
    beats = json.load(open(os.path.join(w.folder, "beats.json")))
    assert 5 in beats["unmatched"] and not [o for o in beats["overlays"] if o["beat"] == 5]
    assert state(w)["steps"]["align"]["result"]["unmatched"] == [5]
    # with an anchor the person's range stands in the match, and survives the run again
    ops.prepare_again(w.project, w.rid, "review")
    first, last = word_index(w, "hábito"), word_index(w, "só.")
    ops.captions_edit(w.project, w.rid, 0, json.dumps([{"op": "anchor", "beat": 5, "word_from": first, "word_to": last}]))
    shown = ops.captions_read(w.project, w.rid)
    row = next(b for b in shown["beats"] if b["beat"] == 5)
    assert row["anchored"] is True and row["score"] == 1.0 and row["below_threshold"] is False and (row["word_from"], row["word_to"]) == (first, last)
    done = finish_review(w)
    assert done["ok"] is True
    beats = json.load(open(os.path.join(w.folder, "beats.json")))
    [overlay] = [o for o in beats["overlays"] if o["beat"] == 5]
    assert (overlay["word_from"], overlay["word_to"]) == (first, last) and overlay["score"] == 1.0
    final = [c for c in kit.calls(w.tree, "renderer") if c[0] == "align"][-1]
    assert [final[i + 1] for i, v in enumerate(final) if v == "--anchor"] == [f"5={first}-{last}"]
    assert state(w)["steps"]["align"]["result"]["anchored"] == [5] and 5 not in state(w)["steps"]["align"]["result"]["unmatched"]


def test_an_anchor_survives_an_edit_that_changes_the_word_numbers_before_it(tmp_path, monkeypatch):
    post = kit.POST.replace("line: Esse hábito me poupou trezentos e quarenta reais num mês só.", "line: Isso rendeu um bom troco no fim do ano inteiro.")  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    w = make_world(tmp_path, monkeypatch, post=post)
    start(w)
    first, last = word_index(w, "hábito"), word_index(w, "só.")
    edit(w, [{"op": "anchor", "beat": 5, "word_from": first, "word_to": last}])
    edit(w, [{"op": "delete", "index": word_index(w, "gasto")}, {"op": "edit", "index": word_index(w, "gente", 0), "text": "a gente"}])
    assert word_index(w, "hábito") == first, "one word less before it, one word more: the numbers moved and came back"
    finish_review(w)
    beats = json.load(open(os.path.join(w.folder, "beats.json")))
    [overlay] = [o for o in beats["overlays"] if o["beat"] == 5]
    edl_words = {x["index"]: x["text"] for x in json.load(open(os.path.join(w.folder, "edl.json")))["words"]}
    assert edl_words[overlay["word_from"]] == "hábito" and edl_words[overlay["word_to"]] == "só."


def test_a_retake_is_cut_only_when_confirmed_and_an_undo_restores_it(w):
    start(w)
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": True}])
    assert ops.captions_read(w.project, w.rid)["retakes"][0]["confirmed"] is True
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": False}])
    assert ops.captions_read(w.project, w.rid)["retakes"][0]["confirmed"] is False
    finish_review(w)
    kept = json.load(open(os.path.join(w.folder, "edl.json")))
    assert not any(p["confirmed"] for p in kept["proposals"]) and kept["proposals"][0]["kind"] == "repeat"
    assert all("--confirm" not in c for c in kit.calls(w.tree, "renderer") if c[0] == "base")
    shorter = state(w)["steps"]["base"]["result"]["out_seconds"]
    ops.prepare_again(w.project, w.rid, "review")
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": True}])
    finish_review(w)
    confirmed = json.load(open(os.path.join(w.folder, "edl.json")))
    assert [p["confirmed"] for p in confirmed["proposals"]] == [True]
    base_calls = [c for c in kit.calls(w.tree, "renderer") if c[0] == "base"][-2:]
    assert "--confirm" not in base_calls[0] and beat_args(base_calls[1])["--confirm"] == "retake-1"
    assert state(w)["steps"]["base"]["result"]["retakes_confirmed"] == 1 and state(w)["steps"]["base"]["result"]["out_seconds"] < shorter


def test_a_confirmed_retake_follows_the_words_when_the_numbers_before_it_change(w):
    start(w)
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": True}])
    edit(w, [{"op": "delete", "index": word_index(w, "gasto")}, {"op": "delete", "index": word_index(w, "Ano")}])
    out = finish_review(w)
    assert out["ok"] is True
    [proposal] = json.load(open(os.path.join(w.folder, "edl.json")))["proposals"]
    assert proposal["confirmed"] is True
    assert state(w)["steps"]["base"]["result"]["retakes_confirmed"] == 1


def test_a_retake_an_edit_took_away_stops_the_base_list_and_the_person_confirms_it_again(w):
    start(w)
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": True}])
    first = ops.captions_read(w.project, w.rid)["retakes"][0]["word_from"]
    words = ops.captions_read(w.project, w.rid)["words"]
    edit(w, [{"op": "edit", "index": first + 2, "text": "duas"}, {"op": "edit", "index": first + 3, "text": "ideias"}])
    out = finish_review(w)
    assert out["ok"] is False and out["failed"] == "base" and out["code"] == "retake_lost" and "prepare-again --step review" in out["next"]
    assert not any(c for c in kit.calls(w.tree, "renderer") if c[0] == "render")
    assert code_task(w)["state"] == "failed"
    ops.prepare_again(w.project, w.rid, "review")
    assert ops.captions_read(w.project, w.rid)["steps"]["review"] == "waiting"


def test_words_are_remapped_into_the_edit_list_and_captions_stay_as_spoken(w):
    start(w)
    edit(w, [{"op": "edit", "index": word_index(w, "pra"), "text": "pra"}, {"op": "edit", "index": word_index(w, "gente", 0), "text": "a gente"},  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
             {"op": "delete", "index": word_index(w, "uma")}])
    shown = ops.captions_read(w.project, w.rid)
    gente = word_index(w, "gente", 0)
    assert shown["words"][gente - 1]["estimated"] and shown["words"][gente]["estimated"] and shown["counts"]["edited"] == 2
    finish_review(w)
    edited = json.load(open(os.path.join(w.folder, "transcript.edited.json")))
    edl = json.load(open(os.path.join(w.folder, "edl.json")))
    texts = [x["text"] for x in edl["words"]]
    assert "pra" in texts and "tá" in texts and "uma" not in texts and edited["facts"]["revision"] == 1  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    assert "para" not in texts and "está" not in texts  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    assert all(x["index"] == i for i, x in enumerate(edited["words"]))
    assert state(w)["steps"]["remap"]["result"]["edited"] == 2 and state(w)["steps"]["remap"]["result"]["estimated"] >= 2


def test_an_edit_that_carries_a_time_a_stale_revision_or_a_forbidden_character_changes_nothing(w):
    start(w)
    before = open(os.path.join(w.folder, "review.json")).read() if os.path.exists(os.path.join(w.folder, "review.json")) else None
    bad = [([{"op": "edit", "index": 3, "text": "oi", "start": 1.0}], "time_not_accepted"),
           ([{"op": "edit", "index": 3, "text": "oi", "end": 1.0}], "time_not_accepted"),
           ([{"op": "edit", "index": 3, "text": "um" + chr(0x200B) + "dois"}], "forbidden_character"),
           ([{"op": "edit", "index": 3, "text": "um" + chr(0x202E) + "dois"}], "forbidden_character")]
    for edits, code in bad:
        with pytest.raises(ops.OpsError, match=code):
            ops.captions_edit(w.project, w.rid, 0, json.dumps(edits))
    with pytest.raises(ops.OpsError, match="stale_revision"):
        ops.captions_edit(w.project, w.rid, 4, json.dumps([{"op": "delete", "index": 3}]))
    with pytest.raises(ops.OpsError, match="not valid JSON"):
        ops.captions_edit(w.project, w.rid, 0, "not json")
    assert not os.path.exists(os.path.join(w.folder, "transcript.edited.json"))
    assert (open(os.path.join(w.folder, "review.json")).read() if os.path.exists(os.path.join(w.folder, "review.json")) else None) == before
    assert ops.captions_read(w.project, w.rid)["revision"] == 0


def test_the_review_files_are_outside_the_project_the_documents_and_every_run_and_private(w):
    start(w)
    edit(w, [{"op": "delete", "index": 3}])
    finish_review(w)
    for name in ("transcript.json", "transcript.edited.json", "review.json", "pipeline.json", "proposal.edl.json", "edl.json", "beats.json"):
        path = os.path.join(w.folder, name)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600, name
        assert os.path.realpath(path).startswith(os.path.realpath(w.data) + os.sep) and not os.path.realpath(path).startswith(os.path.realpath(w.project) + os.sep)
    for base, _, names in os.walk(w.project):
        assert not {"transcript.json", "transcript.edited.json", "review.json", "pipeline.json", "edl.json", "beats.json"} & set(names), base
    assert not (w.tree / "docs").exists()


def test_the_captions_cannot_be_edited_before_or_after_the_review_and_cannot_be_read_before_they_exist(w):
    with pytest.raises(ops.OpsError, match="has not started"):
        ops.captions_read(w.project, w.rid)
    kit.fail(w.tree, "renderer", "align", times=1)
    start(w)
    with pytest.raises(ops.OpsError, match="is at align-proposal"):
        ops.captions_read(w.project, w.rid)
    kit.heal(w.tree, "renderer")
    ops.media_pipeline(w.project, w.rid)
    finish_review(w)
    with pytest.raises(ops.OpsError, match="not open for edits"):
        ops.captions_edit(w.project, w.rid, 1, json.dumps([{"op": "delete", "index": 3}]))
    with pytest.raises(ops.OpsError, match="not waiting for an answer"):
        finish_review(w)
    assert ops.captions_read(w.project, w.rid)["editable"] is False


def test_the_face_box_and_the_cover_offset_reach_the_renderer(w):
    start(w)
    edit(w, [{"op": "face_box", "x": 240, "y": 620, "w": 600, "h": 560}, {"op": "cover", "offset_ms": 1500}])
    finish_review(w)
    last_base = [c for c in kit.calls(w.tree, "renderer") if c[0] == "base"][-1]
    assert beat_args(last_base)["--face-box"] == "240,620,600,560" and state(w)["steps"]["base"]["result"]["face_box"] == "set"
    assert beat_args([c for c in kit.calls(w.tree, "renderer") if c[0] == "cover"][0])["--offset-ms"] == "1500"
    first_base = [c for c in kit.calls(w.tree, "renderer") if c[0] == "base"][0]
    assert "--face-box" not in first_base


def test_an_overlay_the_person_dropped_is_not_in_the_beats_the_renderer_checks_and_draws(w):
    start(w)
    edit(w, [{"op": "overlay", "beat": 4, "dropped": True}])
    finish_review(w)
    beats = json.load(open(os.path.join(w.folder, "beats.json")))
    assert 4 not in {o["beat"] for o in beats["overlays"]} and 3 in {o["beat"] for o in beats["overlays"]}
    assert state(w)["steps"]["align"]["result"]["dropped"] == [4] and state(w)["steps"]["check"]["status"] == "done"


# --- the asset slots ---------------------------------------------------------------------------------------------------------------------


def test_done_waits_for_a_file_or_a_choice_for_every_asset_slot(ws):
    start(ws)
    with pytest.raises(ops.OpsError, match="slot_needs_a_choice beat7"):
        finish_review(ws)
    assert ops.pending(ws.project)["pending"][0]["title"] == "Check the captions" and code_task(ws)["state"] == "waiting"
    edit(ws, [{"op": "slot", "slot": "beat7", "choice": "keyword"}])
    assert finish_review(ws)["ok"] is True
    final = [c for c in kit.calls(ws.tree, "renderer") if c[0] == "align"][-1]
    assert beat_args(final)["--empty-slot"] == "beat7=keyword"


def test_an_uploaded_file_is_bound_to_its_slot_by_id_and_handed_to_the_render_with_its_hash(ws, tmp_path):
    start(ws)
    picture = tmp_path / "painel.png"
    picture.write_bytes(png(30, 20))
    sid = media.slot_id(ws.rid, "beat7")
    uploaded = ops.media_in(ws.project, recording=ws.rid, slot=sid, file=str(picture))
    assert uploaded["kind"] == "asset" and not ops.captions_read(ws.project, ws.rid)["slots"][0]["choice"]
    assert ops.captions_read(ws.project, ws.rid)["slots"][0]["file"]["type"] == "png"
    finish_review(ws)
    render = [c for c in kit.calls(ws.tree, "renderer") if c[0] == "render"][0]
    found = [render[i + 1] for i, v in enumerate(render) if v == "--asset"]
    held = media.load(ws.data, ws.rid)["slots"][sid]["asset"]
    assert found == [f"beat7={os.path.join(ws.folder, 'assets', held['file'])}"]
    assert [render[i + 1] for i, v in enumerate(render) if v == "--asset-sha256"] == [f"beat7={uploaded['sha256']}"]
    assert "--empty-slot" not in [x for c in kit.calls(ws.tree, "renderer") if c[0] == "align" for x in c][-6:]


def test_an_asset_of_a_type_the_renderer_does_not_take_is_refused_naming_the_slot(ws, tmp_path):
    start(ws)
    picture = tmp_path / "painel.webp"
    picture.write_bytes(webp(30, 20))
    ops.media_in(ws.project, recording=ws.rid, slot=media.slot_id(ws.rid, "beat7"), file=str(picture))
    out = finish_review(ws)
    assert out["ok"] is False and out["failed"] == "render" and out["code"] == "asset_type" and out["field"] == "beat7"
    assert "PNG or a JPEG" in out["next"] and not any(c for c in kit.calls(ws.tree, "renderer") if c[0] == "render")


def test_a_slot_that_lost_its_file_after_the_review_stops_the_alignment_with_the_way_forward(ws, tmp_path):
    start(ws)
    picture = tmp_path / "painel.png"
    picture.write_bytes(png(30, 20))
    sid = media.slot_id(ws.rid, "beat7")
    ops.media_in(ws.project, recording=ws.rid, slot=sid, file=str(picture))
    kit.fail(ws.tree, "renderer", "base", times=1)
    finish_review(ws)
    media.update(ws.data, ws.rid, lambda r: r["slots"][sid].update(asset=None))
    kit.heal(ws.tree, "renderer")
    out = ops.media_pipeline(ws.project, ws.rid)
    assert out["ok"] is False and out["failed"] == "align" and out["code"] == "slot_empty" and out["field"] == "beat7"


# --- starting over -------------------------------------------------------------------------------------------------------------------------


def test_prepare_again_from_the_review_opens_the_captions_as_they_were_left_and_runs_no_model(w):
    start(w)
    edit(w, [{"op": "delete", "index": 3}, {"op": "overlay", "beat": 4, "dropped": True}])
    finish_review(w)
    first_pending = ops.pending(w.project)["pending"][0]["id"]
    n = len(kit.calls(w.tree, "renderer"))
    out = ops.prepare_again(w.project, w.rid, "review")
    assert out["stopped"] == "review" and out["reset"][0] == "review" and "approval" in out["reset"]
    assert kit.verbs(w.tree, "transcriber") == ["transcribe"] and len(kit.calls(w.tree, "renderer")) == n, "nothing is run again to open the captions"
    shown = ops.captions_read(w.project, w.rid)
    assert shown["revision"] == 1 and shown["editable"] and shown["counts"]["words"] == 84 and shown["beats"][1]["dropped"] is True
    titles = [p["title"] for p in ops.pending(w.project)["pending"]]
    assert titles == ["Check the captions"] and first_pending not in [p["id"] for p in ops.pending(w.project)["pending"]]
    edit(w, [{"op": "overlay", "beat": 4, "dropped": False}])
    done = finish_review(w)
    assert done["stopped"] == "approval"
    new = [c[0] for c in kit.calls(w.tree, "renderer")][n:]
    assert new == ["base", "align", "check", "render", "cover"], "from the re-map: no transcription, no analysis, no model"
    assert 4 in {o["beat"] for o in json.load(open(os.path.join(w.folder, "beats.json")))["overlays"]}
    assert len(renders(w)) == 2, "another edit list, another render: named by its bytes, the first one stays until retention"


def test_prepare_again_from_a_later_step_keeps_the_review_and_from_an_earlier_one_starts_it_over(w):
    start(w)
    edit(w, [{"op": "delete", "index": 3}])
    finish_review(w)
    out = ops.prepare_again(w.project, w.rid, "base")
    assert out["stopped"] == "approval" and out["reset"] == ["base", "align", "check", "render", "cover", "approval"]
    assert captions.check_review(json.load(open(os.path.join(w.folder, "review.json"))))["revision"] == 1
    out = ops.prepare_again(w.project, w.rid, "align-proposal")
    assert out["stopped"] == "review" and out["reset"][0] == "align-proposal"
    assert not os.path.exists(os.path.join(w.folder, "transcript.edited.json")) and not os.path.exists(os.path.join(w.folder, "review.json"))
    assert ops.captions_read(w.project, w.rid)["revision"] == 0 and kit.verbs(w.tree, "transcriber") == ["transcribe"]
    out = ops.prepare_again(w.project, w.rid, "transcribe")
    assert out["stopped"] == "review" and kit.verbs(w.tree, "transcriber") == ["transcribe", "transcribe"]
    with pytest.raises(ops.OpsError, match="unknown_step"):
        ops.prepare_again(w.project, w.rid, "approval")


def test_prepare_again_before_the_pipeline_started_and_for_an_unknown_recording_is_refused(w):
    with pytest.raises(ops.OpsError, match="has not started"):
        ops.prepare_again(w.project, w.rid, "base")
    with pytest.raises(ops.OpsError):
        ops.media_pipeline(w.project, "0" * 16)
    with pytest.raises(ops.OpsError):
        ops.media_pipeline(w.project, "../x")


# --- starting a pipeline ------------------------------------------------------------------------------------------------------------------


def test_the_first_call_links_the_post_file_and_names_the_network_from_its_network_line_or_asks(w):
    out = start(w)
    assert out["platform"] == "instagram" and media.load(w.data, w.rid)["posts"] == {"instagram": kit.POST_PATH}
    other = make_recording_in(w)
    with pytest.raises(ops.OpsError, match="no post file"):
        ops.media_pipeline(w.project, other)
    with pytest.raises(ops.OpsError, match="Markdown file under docs"):
        ops.media_pipeline(w.project, other, post="../etc/passwd")
    nofile = "docs/marketing/content/no-network.md"
    with open(os.path.join(w.project, *nofile.split("/")), "w") as f:
        f.write("# Post\n\n- Format: reel\n")
    with pytest.raises(ops.OpsError, match="name the network"):
        ops.media_pipeline(w.project, other, post=nofile)
    with pytest.raises(ops.OpsError, match="was started for instagram"):
        ops.media_pipeline(w.project, w.rid, network="tiktok")


def make_recording_in(w):
    return kit.make_recording(w.data, media)["id"]


def test_a_recording_without_a_file_cannot_start_and_a_post_that_is_a_link_is_not_read(w, tmp_path):
    empty = media.create(w.data)
    with pytest.raises(ops.OpsError, match="has no file yet"):
        ops.media_pipeline(w.project, empty["id"])
    target = tmp_path / "elsewhere.md"
    target.write_text(kit.POST)
    link = "docs/marketing/content/link.md"
    os.symlink(target, os.path.join(w.project, *link.split("/")))
    out = ops.media_pipeline(w.project, w.rid, post=link, network="instagram")
    assert out["ok"] is False and out["failed"] == "align-proposal" and out["code"] == "post_unreadable"


def test_a_post_the_checker_refuses_stops_the_alignment_with_the_checkers_closed_code(tmp_path, monkeypatch):
    post = kit.POST.replace("preset: keyword", "preset: confetti")
    w = make_world(tmp_path, monkeypatch, post=post)
    out = start(w)
    assert out["ok"] is False and out["failed"] == "align-proposal" and out["code"] == "script_refused"
    assert "confetti" not in json.dumps([state(w), code_task(w)])


def test_media_list_shows_where_the_pipeline_stands_and_the_last_failure(w):
    assert ops.media_list(w.project)["recordings"][0]["pipeline"] is None
    kit.fail(w.tree, "renderer", "analyse")
    start(w)
    shown = ops.media_list(w.project, w.rid)["recordings"][0]["pipeline"]
    assert shown["next"] == "analyse" and shown["failure"]["code"] == "browser_failed" and shown["steps"]["transcribe"] == "done"
    kit.heal(w.tree, "renderer")
    ops.media_pipeline(w.project, w.rid)
    assert ops.media_list(w.project, w.rid)["recordings"][0]["pipeline"]["next"] == "review"


def test_two_pipelines_of_one_recording_do_not_run_at_once(w):
    start(w)
    task = code_task(w)["id"]
    fd = ops_core._try_lock(ops_core._config_of(w.project), f"task-{task}.lock")
    try:
        with pytest.raises(ops.OpsError, match="already being run"):
            ops.media_pipeline(w.project, w.rid)
        with pytest.raises(ops.OpsError, match="already being run"):
            ops.captions_edit(w.project, w.rid, 0, json.dumps([{"op": "delete", "index": 3}]))
    finally:
        os.close(fd)


def test_a_pipeline_that_died_mid_step_is_resumed_from_its_file(w):
    start(w)
    saved = state(w)
    saved["steps"].pop("align-proposal")
    saved["steps"].pop("review")
    saved["decisions"] = {}
    open(os.path.join(w.folder, "pipeline.json"), "w").write(json.dumps(saved))
    ops.media_pipeline(w.project, w.rid)
    assert kit.verbs(w.tree, "renderer") == ["analyse", "base", "align", "align"], "only the step that had no result runs again"
    assert state(w)["steps"]["align-proposal"]["status"] == "done"


# --- the pipeline is code: no model, no network, nothing that builds ---------------------------------------------------------------------------------


def test_the_modules_of_the_pipeline_never_name_a_setup_verb_a_model_or_the_configuration_file():
    import ast
    for name in ("pipeline", "captions", "ops_pipeline"):
        source = (st.RUNTIME / f"{name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}
        assert not {"build", "fetch-model", "pin-browser", "pin-templates", "reap", "models"} & strings, name
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not {"lab", "run_skill", "task_run_start", "project_config"} & names, name   # no model, no run row, no way to write the configuration
    assert "import lab" not in (st.RUNTIME / "pipeline.py").read_text() and "import lab" not in (st.RUNTIME / "ops_pipeline.py").read_text()


def test_every_reader_of_tasks_copes_with_a_task_that_has_no_skill_in_every_state_it_takes(w):
    def readers():
        for read in (ops.status, ops.progress, ops.pending, ops.agents, ops.costs, ops.artifacts, ops.flows, ops.version, ops.conversation,
                     ops.poll):
            read(w.project)
        ops.task(w.project, code_task(w)["id"])
        ops.task(w.project, code_task(w)["parent_id"])
        ops.dispatch(w.project, wait=True)
        ops.run_next(w.project)
        ops.media_list(w.project)
    start(w)                                  # waiting at the review
    readers()
    finish_review(w)       # waiting for the approval
    readers()
    kit.fail(w.tree, "renderer", "cover")
    ops.prepare_again(w.project, w.rid, "cover")   # failed
    readers()
    ops.cancel(w.project, code_task(w)["parent_id"])   # cancelled
    readers()
    assert not (w.adapter / "calls.txt").exists()
    status = ops.status(w.project)
    [request] = status["requests"]
    assert [t["skill"] for t in request["tasks"]] == [None] and request["tasks"][0]["holds_slot"] is False


def test_a_post_file_in_a_folder_that_leads_out_of_the_project_is_not_read(w, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_text(kit.POST)
    os.symlink(outside, os.path.join(w.project, "docs", "marketing", "out"))
    out = ops.media_pipeline(w.project, w.rid, post="docs/marketing/out/x.md", network="instagram")
    assert out["ok"] is False and out["failed"] == "align-proposal" and out["code"] == "post_unreadable"
    assert not any(c for c in kit.calls(w.tree, "renderer") if c[0] == "align")


def test_a_word_the_renderer_could_not_place_is_listed_marked_and_left_out_of_the_captions(tmp_path, monkeypatch):
    w = make_world(tmp_path, monkeypatch, transcript=kit.build_transcript(unplace_last=True))
    start(w)
    shown = ops.captions_read(w.project, w.rid)
    last = shown["counts"]["words"] - 1
    assert shown["counts"]["unplaced"] == 1 and [u["word"] for u in shown["unplaced"]] == [last]
    assert shown["words"][last]["left_out"] == "unplaced" and shown["words"][last]["chunk"] is None
    assert last not in [i for c in shown["chunks"] for i in c["words"]]
    assert state(w)["steps"]["retakes"]["result"]["unplaced"] == 1
    finish_review(w)
    assert last not in {x["index"] for x in json.load(open(os.path.join(w.folder, "edl.json")))["words"]}


# --- the page's send-back (package P7): the pipeline reads its marker, reopens the review and clears it ---------------------------------------


def send_back(w, comment="trim the opening", platform="instagram"):
    """What runtime/ops_video.py's send-back leaves in the record: the comment and the marker the pipeline reads."""
    at = media.stamp()
    sha = state(w)["steps"]["render"]["result"]["sha256"]
    media.update(w.data, w.rid, lambda r: r.update(sent_back={"platform": platform, "comment": comment, "at": at, "render_sha256": sha},
                                                   resume={"step": "review", "reason": "sent_back", "platform": platform, "at": at}))


def test_a_video_sent_back_reopens_the_review_with_the_comment_shown_and_the_marker_cleared(w):
    start(w)
    finish_review(w)
    first = state(w)["steps"]["render"]["result"]["sha256"]
    send_back(w)
    before = len(kit.calls(w.tree, "renderer"))
    out = ops.media_pipeline(w.project, w.rid)
    assert out["stopped"] == "review" and out["steps"]["review"] == "waiting" and out["steps"]["render"] == "pending"
    assert len(kit.calls(w.tree, "renderer")) == before, "nothing is run to open the captions again"
    assert "resume" not in media.load(w.data, w.rid), "the marker is consumed"
    shown = ops.captions_read(w.project, w.rid)
    assert shown["editable"] and shown["sent_back"]["comment"] == "trim the opening" and shown["sent_back"]["render_sha256"] == first
    [item] = [ops.pending(w.project, p["id"]) for p in ops.pending(w.project)["pending"]]
    assert "sent back" in item["body"] and "trim the opening" not in item["body"] + json.dumps(item["payload"]), "the comment is not copied into a decision"
    edit(w, [{"op": "delete", "index": word_index(w, "gasto")}])
    again = finish_review(w)
    second = state(w)["steps"]["render"]["result"]["sha256"]
    assert again["stopped"] == "approval" and second != first, "another edit list, another render: the old approval goes stale by itself"
    record = media.load(w.data, w.rid)
    assert "approvals" not in record and "resume" not in record, "the pipeline writes no approval"
    assert "sent back" not in ops.pending(w.project, ops.pending(w.project)["pending"][0]["id"])["body"]
    assert json.load(open(os.path.join(w.folder, "render.json")))["sha256"] == second


def test_a_marker_for_another_platform_or_step_is_left_alone_and_prepare_again_obeys_a_marker(w):
    start(w)
    finish_review(w)
    send_back(w, platform="tiktok")
    assert ops.media_pipeline(w.project, w.rid)["stopped"] == "approval" and media.load(w.data, w.rid)["resume"]["platform"] == "tiktok"
    media.update(w.data, w.rid, lambda r: r.update(resume={"step": "render", "reason": "sent_back"}))
    assert ops.media_pipeline(w.project, w.rid)["stopped"] == "approval" and "resume" in media.load(w.data, w.rid)
    send_back(w)
    out = ops.prepare_again(w.project, w.rid, "cover")        # a later step was asked: the person's send-back wins
    assert out["stopped"] == "review" and out["reset"][0] == "review" and "resume" not in media.load(w.data, w.rid)


def test_the_page_reads_what_the_pipeline_wrote_the_render_its_facts_and_the_cover(w):
    video = st.load("video")
    start(w)
    finish_review(w)
    result = state(w)["steps"]
    sha = result["render"]["result"]["sha256"]
    read = video.read_result(w.data, w.rid)
    assert read["sha256"] == sha and read["bytes"] == result["render"]["result"]["bytes"] and (read["width"], read["height"]) == (1080, 1920)
    assert read["duration"] == result["render"]["result"]["seconds"] and read["cover"] == {"offset_ms": 0, "sha256": result["cover"]["result"]["sha256"]}
    opened = video.open_render(w.data, w.rid, sha)
    opened.close()
    cover = video.open_cover(w.data, w.rid, sha, read["cover"]["sha256"])
    assert cover.name == result["cover"]["result"]["name"]
    cover.close()
    card = ops.video_card(w.project, w.rid)
    assert card["render"]["sha256"] == sha and not card["approval"] and card["cover"], "the card of P7 finds the render and the cover the pipeline kept"


def test_a_send_back_through_the_pages_own_operations_holds_the_post_until_the_pipeline_clears_it(w):
    start(w)
    finish_review(w)
    card = ops.video_card(w.project, w.rid)
    first = card["render"]["sha256"]
    ops.video_approve(w.project, w.rid, first, card["caption"]["sha256"], channel="page")
    ops.video_send_back(w.project, w.rid, "trim the opening")
    assert media.load(w.data, w.rid)["resume"]["step"] == "review"
    with pytest.raises(ops.OpsError, match="sent back|sent_back"):
        ops.video_approve(w.project, w.rid, first, card["caption"]["sha256"], channel="page")
    out = ops.media_pipeline(w.project, w.rid)                       # the pipeline reads the marker, reopens the review, clears it
    assert out["stopped"] == "review" and "resume" not in media.load(w.data, w.rid)
    edit(w, [{"op": "delete", "index": word_index(w, "gasto")}])
    finish_review(w)
    again = ops.video_card(w.project, w.rid)
    assert again["render"]["sha256"] != first and not again["approval"]
    ops.video_approve(w.project, w.rid, again["render"]["sha256"], again["caption"]["sha256"], channel="page")
    assert media.load(w.data, w.rid)["approvals"]["instagram"]["video_sha256"] == again["render"]["sha256"]


# --- review round: one pipeline per recording, however many ask ---------------------------------------------------------------------------


def codes_of(w):
    ctx = ops_core.context(w.project)
    return [t for t in ctx["store"].tasks_list(ctx["conn"]) if t.get("key") == f"media:{w.rid}"]


def test_two_requests_at_once_for_a_fresh_recording_make_one_task_and_one_state(tmp_path, monkeypatch):
    import threading
    for round_ in range(int(os.environ.get("PIPELINE_LOOPS", "6"))):
        w = make_world(tmp_path / f"r{round_}", monkeypatch)
        results, barrier = [], threading.Barrier(2)

        def ask():
            barrier.wait()
            try:
                results.append(ops.media_pipeline(w.project, w.rid, post=kit.POST_PATH))
            except ops.OpsError as e:
                results.append(e)
        threads = [threading.Thread(target=ask) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        tasks = codes_of(w)
        assert len(tasks) == 1, [str(r) for r in results]
        assert media.load(w.data, w.rid)["tasks"]["code"] == tasks[0]["id"] == state(w)["task"]
        assert any(isinstance(r, dict) and r["stopped"] == "review" for r in results) and all(isinstance(r, dict) or "already being run" in str(r) for r in results)
        assert kit.verbs(w.tree, "transcriber") == ["transcribe"], "the second request did not run the steps again"
        assert not [n for n in os.listdir(w.folder) if n.endswith(".tmp") or n.startswith(".tmp-")]


def test_the_state_file_is_written_through_a_temporary_file_of_its_own(w):
    import threading
    path = os.path.join(w.folder, "probe.json")
    errors = []

    def write(n):
        try:
            for i in range(200):
                pipeline.write_json(path, {"n": n, "i": i})
        except BaseException as e:   # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and json.load(open(path))["i"] == 199 and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [n for n in os.listdir(w.folder) if n.startswith(".tmp-")] == []


def test_the_code_task_is_made_once_even_when_the_state_is_made_again(w):
    start(w)
    os.unlink(os.path.join(w.folder, "pipeline.json"))     # the state file is lost; the record still names the task
    again = ops.media_pipeline(w.project, w.rid, post=kit.POST_PATH)
    assert len(codes_of(w)) == 1 and again["task"] == media.load(w.data, w.rid)["tasks"]["code"]


def test_a_done_request_is_not_reopened_for_a_recording_and_a_planned_one_is_joined(w):
    ctx = ops_core.context(w.project)
    store = ctx["store"]
    finished = store.request_add(ctx["conn"], title="old", text="x", flow="demo", tasks=[{"key": "k", "skill": "demo-asks", "title": "t", "text": "x"}])["request"]
    ctx["conn"].execute("UPDATE tasks SET state = 'done' WHERE id = ?", (finished,))
    with pytest.raises(ops.OpsError, match="never reopens a done one"):
        start(w, request=finished)
    assert media.load(w.data, w.rid)["tasks"] == {}
    open_one = store.request_add(ctx["conn"], title="idea", text="x", flow="demo", tasks=[{"key": "k", "skill": "demo-asks", "title": "t", "text": "x"}])["request"]
    assert start(w, request=open_one)["request"] == open_one


# --- review round: a send-back is consumed inside the lock, and only the marker that was read ------------------------------------------------------


def test_the_send_back_is_consumed_with_the_tasks_lock_held_and_the_state_read_under_it(w, monkeypatch):
    start(w)
    finish_review(w)
    send_back(w)
    seen = []
    real = pipeline.prepare_again

    def watching(ctx, st, step):
        seen.append(ops_core._try_lock(ops_core._config_of(w.project), f"task-{st['task']}.lock"))   # None: another holder, this process's own lock
        return real(ctx, st, step)
    monkeypatch.setattr(pipeline, "prepare_again", watching)
    assert ops.media_pipeline(w.project, w.rid)["stopped"] == "review"
    assert seen == [None], "prepare_again ran while the task's lock was held"


def test_a_second_send_back_made_while_the_first_is_consumed_is_not_lost(w):
    start(w)
    finish_review(w)
    send_back(w, comment="first")
    ctx = ops_core.context(w.project)
    state_now = pipeline.load_state(w.data, w.rid)
    ops_pipeline = st.load("ops_pipeline")
    first = ops_pipeline._resume_marker(ctx, w.rid, state_now)
    media.update(w.data, w.rid, lambda r: r.update(resume={**first, "at": "2099-01-01T00:00:00Z"}, sent_back={"platform": "instagram", "comment": "second",
                                                                                                      "at": "2099-01-01T00:00:00Z", "render_sha256": None}))
    ops_pipeline._clear_resume(ctx, w.rid, state_now, first)
    assert media.load(w.data, w.rid)["resume"]["at"] == "2099-01-01T00:00:00Z", "only the marker that was read is cleared"
    ops_pipeline._clear_resume(ctx, w.rid, state_now, media.load(w.data, w.rid)["resume"])
    assert "resume" not in media.load(w.data, w.rid)


# --- review round: a provider's malformed answer is a failure, never a task left running ------------------------------------------------------------


def test_a_malformed_provider_result_fails_the_step_with_a_closed_code_and_the_task_moves(w):
    start(w)
    kit.fail(w.tree, "renderer", "check", stdout='{"ok": true, "mentions": 5, "overlays": {}}')
    out = finish_review(w)
    assert out["ok"] is False and out["failed"] == "check" and out["code"] == "provider_output_invalid" and out["field"] == "check"
    assert code_task(w)["state"] == "failed" and code_task(w)["note"].startswith("check: provider_output_invalid")
    kit.heal(w.tree, "renderer")
    assert ops.media_pipeline(w.project, w.rid)["stopped"] == "approval"


def test_a_failure_still_moves_the_task_when_the_recordings_folder_is_gone(w):
    start(w)
    kit.fail(w.tree, "renderer", "check", stdout='{"ok": true, "mentions": 5}', rmtree=w.folder)
    out = finish_review(w)
    assert out["ok"] is False and out["code"] == "provider_output_invalid"
    assert not os.path.exists(w.folder) and out["task"] and ops.task(w.project, out["task"])["task"]["state"] == "failed"


# --- review round: edits that would fail later are refused when they are made ---------------------------------------------------------------------


def test_a_merge_too_long_or_a_word_with_a_space_is_refused_at_edit_time_before_done(w):
    start(w)
    long_pair = next(i for i, x in enumerate(ops.captions_read(w.project, w.rid)["words"][:-1]) if x["text"] == "primeira")
    edit(w, [{"op": "edit", "index": long_pair, "text": "x" * 30}, {"op": "edit", "index": long_pair + 1, "text": "y" * 20}])   # words within the bound of 40
    with pytest.raises(ops.OpsError, match="text_too_long"):
        edit(w, [{"op": "merge", "from": long_pair, "to": long_pair + 1}])
    with pytest.raises(ops.OpsError, match="space_in_word"):
        edit(w, [{"op": "merge", "from": 1, "to": 2, "text": "dois mundos"}])
    with pytest.raises(ops.OpsError, match="space_in_word"):
        edit(w, [{"op": "split", "index": 1, "parts": ["a b", "c"]}])
    assert ops.captions_read(w.project, w.rid)["counts"]["edited"] == 2
    assert finish_review(w)["ok"] is True


def test_the_two_review_files_are_one_revision_apart_after_a_crash_and_the_persons_words_stay(w):
    start(w)
    edit(w, [{"op": "delete", "index": 3}])
    edited = json.load(open(os.path.join(w.folder, "transcript.edited.json")))
    edited["words"][0]["text"] = "Olá"
    edited["facts"]["revision"] += 1                       # the transcript was written, the review file was not
    pipeline.write_json(os.path.join(w.folder, "transcript.edited.json"), edited)
    shown = ops.captions_read(w.project, w.rid)
    assert shown["words"][0]["text"] == "Olá" and shown["revision"] == 2
    ops.captions_edit(w.project, w.rid, 2, json.dumps([{"op": "delete", "index": 5}]))
    assert finish_review(w)["ok"] is True
    edited["facts"]["revision"] += 5                       # a disagreement that is not a cut-short write is refused
    pipeline.write_json(os.path.join(w.folder, "transcript.edited.json"), edited)
    with pytest.raises(ops.OpsError, match="review_disagrees"):
        ops.captions_read(w.project, w.rid)


def test_a_retake_an_edit_took_away_opens_unconfirmed_again(w):
    start(w)
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": True}])
    first = ops.captions_read(w.project, w.rid)["retakes"][0]["word_from"]
    edit(w, [{"op": "edit", "index": first + 2, "text": "duas"}, {"op": "edit", "index": first + 3, "text": "ideias"}])
    assert finish_review(w)["code"] == "retake_lost"
    ops.prepare_again(w.project, w.rid, "review")
    shown = ops.captions_read(w.project, w.rid)
    assert shown["retakes"][0]["confirmed"] is False and shown["editable"]
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": True}])
    assert ops.captions_read(w.project, w.rid)["retakes"][0]["confirmed"] is True


# --- review round: the small ones ------------------------------------------------------------------------------------------------------------


def test_a_deeply_nested_edit_list_is_a_usage_error_and_captions_done_needs_the_revision(w):
    start(w)
    with pytest.raises(ops.OpsError, match="not valid JSON") as caught:
        ops.captions_edit(w.project, w.rid, 0, "[" * 200000)
    assert caught.value.code == 2
    assert [a for a in operations_row("captions-done")["args"] if a["name"] == "revision"][0]["required"] is True
    with pytest.raises(ops.OpsError, match="stale_revision"):
        ops.captions_done(w.project, w.rid, 7)
    assert code_task(w)["state"] == "waiting"


def operations_row(name):
    return st.load("operations").by_name(name)


def test_the_answer_to_the_review_is_the_persons_not_the_codes(w):
    start(w)
    finish_review(w)
    answered = [p for p in ops.task(w.project, code_task(w)["id"])["pending"] if p["status"] == "resolved"]
    assert [(p["title"], p["resolved_by"]) for p in answered] == [("Check the captions", "user")]


def test_a_failure_names_the_command_from_the_checkout_and_the_environment_of_a_provider_is_minimal(w, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "not-a-real-secret")
    kit.fail(w.tree, "renderer", "analyse", exit=3, stderr="refused: image_not_built renderer")
    out = start(w)
    assert out["next"] == "python3 providers/renderer/standin.py build --confirmed" and str(w.tree) not in json.dumps(out)
    kit.heal(w.tree, "renderer")
    ops.media_pipeline(w.project, w.rid)
    for role in ("transcriber", "renderer"):
        for names in kit.envs(w.tree, role):
            assert "SECRET_TOKEN" not in names and "PATH" in names, role
