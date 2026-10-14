"""The `still` step of the media pipeline (runtime/pipeline.py), the picture of the first seconds of a recording for the face-box picker of
"Check the captions": where it sits in the order, how its time is chosen, that it is recorded as closed words and exposed by `captions-read`
and `media-list`, that its failure never fails the pipeline or disturbs an open review, that a recording already past `analyse` gets it on its
next call without any other step running again, and that it can be prepared again alone. The providers are the stand-ins of pipeline_kit.py
(its `still` makes a 1x1 PNG); the renderer's own verb is tested in providers/renderer/tests/test_renderer_still.py. Fictional fixtures only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_still.py
"""
from __future__ import annotations

import json
import os
import re
import stat

import pytest

import pipeline_kit as kit
import standin_tree as st
from test_media_pipeline import code_task, finish_review, make_world, start, state

ops = st.load("ops")
media = st.load("media")
pipeline = st.load("pipeline")


@pytest.fixture
def w(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def stills(w):
    return sorted(n for n in os.listdir(w.folder) if pipeline.STILL_FILE.fullmatch(n))


def renderer_new(w, before):
    return kit.verbs(w.tree, "renderer")[before:]


def make_late(w):
    """The pipeline as a build without this step left it: stopped at the review, no `still` among its steps and no file."""
    saved = state(w)
    for name in stills(w):
        os.chmod(os.path.join(w.folder, name), 0o600)
        os.unlink(os.path.join(w.folder, name))
    saved["steps"].pop("still")
    with open(os.path.join(w.folder, "pipeline.json"), "w", encoding="utf-8") as f:
        json.dump(saved, f)


# --- where it sits, what it records ----------------------------------------------------------------------------------------------------------


def test_the_still_runs_right_after_analyse_and_before_the_retakes_and_is_not_one_of_the_steps_the_page_lists(w):
    out = start(w)
    assert out["stopped"] == "review" and kit.verbs(w.tree, "renderer") == ["analyse", "still", "base", "align"]
    assert "still" not in out["steps"] and list(out["steps"]) == list(pipeline.STEPS)
    assert pipeline.ORDER.index("still") == pipeline.ORDER.index("analyse") + 1 and "still" in pipeline.SIDE_STEPS
    assert pipeline.next_step(state(w)) == "review" and "still" not in ops.captions_read(w.project, w.rid)["steps"]


def test_the_result_is_recorded_as_closed_words_and_numbers_and_the_file_is_in_the_recordings_folder(w):
    start(w)
    done = state(w)["steps"]["still"]
    assert done["status"] == "done" and set(done["result"]) == {"name", "sha256", "at_ms", "width", "height", "bytes"}
    assert re.fullmatch(r"still-[0-9a-f]{12}\.png", done["result"]["name"]) and re.fullmatch(r"[0-9a-f]{64}", done["result"]["sha256"])
    assert done["result"]["name"] == f"still-{done['result']['sha256'][:12]}.png"
    assert all(type(done["result"][k]) is int for k in ("at_ms", "width", "height", "bytes")) and done["result"]["at_ms"] == 1500
    assert stills(w) == [done["result"]["name"]] and stat.S_IMODE(os.stat(os.path.join(w.folder, done["result"]["name"])).st_mode) == 0o400
    call = [c for c in kit.calls(w.tree, "renderer") if c[0] == "still"][0]
    flags = {call[i]: call[i + 1] for i in range(1, len(call), 2)}
    assert flags == {"--in": os.path.join(w.folder, "raw.mov"), "--at-ms": "1500", "--out": w.folder + os.sep}
    assert "transcript" not in json.dumps(done).lower() and w.folder not in json.dumps(state(w))


def test_captions_read_and_media_list_expose_the_still_with_its_hash_name_and_time_and_nothing_else(w):
    assert ops.media_list(w.project, w.rid)["recordings"][0]["pipeline"] is None
    start(w)
    made = state(w)["steps"]["still"]["result"]
    wanted = {"sha256": made["sha256"], "name": made["name"], "at_ms": 1500}
    assert ops.captions_read(w.project, w.rid)["still"] == wanted
    assert ops.media_list(w.project, w.rid)["recordings"][0]["pipeline"]["still"] == wanted
    assert ops.media_list(w.project)["recordings"][0]["pipeline"]["still"] == wanted
    found = ops.media_still(w.project, w.rid, wanted["sha256"])                       # the page can read it through the route's operation
    try:
        assert found["file"].read(8) == b"\x89PNG\r\n\x1a\n" and found["name"] == wanted["name"]
    finally:
        found["opened"].close()


# --- the time of the frame ------------------------------------------------------------------------------------------------------------------------


def analysis(duration, silences):
    return {"facts": {"duration": duration}, "silences": silences}


@pytest.mark.parametrize("doc, wanted", [
    (analysis(30.0, [{"start": 0.0, "end": 1.2}, {"start": 5.0, "end": 6.0}]), 1500),                  # a short leading silence: about 1.5 s
    (analysis(30.0, []), 1500),
    (analysis(30.0, None), 1500),                                                                       # a recording with no audio
    (analysis(30.0, [{"start": 0.0, "end": 3.0}]), 2700),                                               # a long one: just before the first speech
    (analysis(30.0, [{"start": 0.0, "end": 2.0}]), 1700),                                               # the threshold is 2 s
    (analysis(30.0, [{"start": 0.05, "end": 2.05}]), 1750),                                             # a start within 0.1 s of zero opens the recording
    (analysis(30.0, [{"start": 0.0, "end": 1.99}]), 1500),
    (analysis(30.0, [{"start": 4.0, "end": 9.0}]), 1500),                                               # a silence that is not at the start does not move it
    (analysis(1.0, [{"start": 0.0, "end": 0.4}]), 900),                                                 # clamped to the recording, 0.1 s from its end
    (analysis(0.05, []), 0),
    (analysis(30.0, [{"start": 0.0, "end": 30.0}]), 1500),                                              # silence to the end: nothing to be before
    (analysis(2.5, [{"start": 0.0, "end": 2.4}]), 2100),                                                # long silence, and the clamp of the end
])
def test_the_time_is_about_a_second_and_a_half_clamped_to_the_recording_and_before_the_first_speech_after_a_long_leading_silence(doc, wanted):
    assert pipeline.still_offset(doc) == wanted


@pytest.mark.parametrize("doc", [analysis("30", []), analysis(0, []), analysis(30.0, [{"start": "0", "end": 3}]), {"silences": []},
                                 analysis(30.0, [{"end": 3.0}]), analysis(float("inf"), [])])
def test_an_analysis_of_the_wrong_shape_is_refused_not_guessed_at(doc):
    with pytest.raises((ValueError, KeyError, TypeError)):
        pipeline.still_offset(doc)


def test_a_long_leading_silence_in_the_recording_moves_the_frame_to_just_before_the_first_speech(tmp_path, monkeypatch):
    made, silences = kit.build_transcript()
    silences = [{"start": 0.0, "end": 3.4}] + [s for s in silences if s["start"] >= 3.4]
    w = make_world(tmp_path, monkeypatch, transcript=(made, silences))
    start(w)
    assert state(w)["steps"]["still"]["result"]["at_ms"] == 3100 and ops.captions_read(w.project, w.rid)["still"]["at_ms"] == 3100


# --- a still that cannot be made never fails the pipeline ----------------------------------------------------------------------------------------


def test_a_failed_still_is_recorded_as_skipped_with_a_closed_code_and_the_pipeline_goes_on_to_the_review(w):
    kit.fail(w.tree, "renderer", "still", stderr="refused: image_stale renderer\n  Traceback: oi gente tá bom? sk-" + "a" * 40, exit=3)
    out = start(w)
    assert out["ok"] is True and out["stopped"] == "review" and code_task(w)["state"] == "waiting"
    step = state(w)["steps"]["still"]
    assert step["status"] == "skipped" and step["result"] == {"code": "image_stale", "field": "renderer"} and state(w)["failure"] is None
    assert "sk-" not in json.dumps(state(w)) and "Traceback" not in json.dumps([state(w), code_task(w)])
    assert ops.captions_read(w.project, w.rid)["still"] is None and ops.media_list(w.project, w.rid)["recordings"][0]["pipeline"]["still"] is None
    assert kit.verbs(w.tree, "renderer") == ["analyse", "still", "base", "align"], "the steps after it ran"


def test_a_skipped_still_is_tried_again_by_the_next_call_and_nothing_else_runs_again(w):
    kit.fail(w.tree, "renderer", "still", stderr="refused: docker_missing docker", exit=3)
    start(w)
    before = {r: len(kit.verbs(w.tree, r)) for r in ("transcriber", "renderer")}
    pending = ops.pending(w.project)["pending"]
    assert len(pending) == 1
    kit.heal(w.tree, "renderer")
    out = ops.media_pipeline(w.project, w.rid)
    assert out["ok"] is True and out["stopped"] == "review"
    assert kit.verbs(w.tree, "renderer")[before["renderer"]:] == ["still"] and kit.verbs(w.tree, "transcriber")[before["transcriber"]:] == []
    assert state(w)["steps"]["still"]["status"] == "done" and len(stills(w)) == 1
    assert ops.pending(w.project)["pending"] == pending and code_task(w)["state"] == "waiting", "the open review was not touched"


@pytest.mark.parametrize("result", [{"name": "../../etc/passwd", "sha256": "a" * 64, "at_ms": 1500, "width": 1080, "height": 1920, "bytes": 9},
                                    {"name": "still-aaaaaaaaaaaa.png", "sha256": "b" * 64, "at_ms": 1500, "width": 1080, "height": 1920, "bytes": 9},
                                    {"name": "still-aaaaaaaaaaaa.png", "sha256": "a" * 64, "at_ms": "soon", "width": 1080, "height": 1920, "bytes": 9},
                                    {"name": "still-aaaaaaaaaaaa.png", "sha256": "a" * 64, "at_ms": 1500, "width": 1080, "height": 1920, "bytes": 9}])
def test_an_answer_of_the_renderer_that_is_not_a_still_in_the_folder_is_skipped_as_a_malformed_answer(w, result):
    kit.fail(w.tree, "renderer", "still", exit=0, stdout=json.dumps({"ok": True, **result}))          # a name that is not the hash's, a hash, a time, a file that is not there
    out = start(w)
    assert out["ok"] is True and state(w)["steps"]["still"] == {"status": "skipped", "at": state(w)["steps"]["still"]["at"],
                                                                "result": {"code": "provider_output_invalid", "field": "still"}}
    assert stills(w) == []


def test_a_recording_that_is_not_there_fails_the_main_steps_as_before_and_the_still_is_not_among_them(w):
    os.unlink(os.path.join(w.folder, "raw.mov"))
    out = start(w)
    assert out["ok"] is False and out["failed"] in ("transcribe", "analyse") and "still" not in out["steps"]


# --- a recording already past `analyse` ------------------------------------------------------------------------------------------------------------


def test_a_pipeline_already_at_its_review_gets_the_still_on_its_next_media_pipeline_without_a_step_run_again(w):
    start(w)
    make_late(w)
    before = {r: len(kit.verbs(w.tree, r)) for r in ("transcriber", "renderer")}
    pending = ops.pending(w.project)["pending"]
    out = ops.media_pipeline(w.project, w.rid)
    assert out["ok"] is True and out["stopped"] == "review" and out["pending"] == pending[0]["id"]
    assert kit.verbs(w.tree, "renderer")[before["renderer"]:] == ["still"] and kit.verbs(w.tree, "transcriber")[before["transcriber"]:] == []
    assert state(w)["steps"]["still"]["status"] == "done" and ops.captions_read(w.project, w.rid)["still"]["at_ms"] == 1500
    assert ops.pending(w.project)["pending"] == pending and code_task(w)["state"] == "waiting"
    ops.media_pipeline(w.project, w.rid)
    assert kit.verbs(w.tree, "renderer")[before["renderer"]:] == ["still"], "and only once"


def test_the_person_can_edit_the_captions_and_say_done_with_the_late_still_in_place(w):
    start(w)
    make_late(w)
    ops.media_pipeline(w.project, w.rid)
    out = finish_review(w)
    assert out["ok"] is True and out["stopped"] == "approval" and "still" not in out["steps"]
    assert state(w)["steps"]["still"]["status"] == "done"


def test_a_late_still_that_fails_leaves_the_review_open_and_the_task_waiting(w):
    start(w)
    make_late(w)
    kit.fail(w.tree, "renderer", "still", stderr="refused: image_not_built renderer", exit=3)
    pending = ops.pending(w.project)["pending"]
    out = ops.media_pipeline(w.project, w.rid)
    assert out["ok"] is True and out["stopped"] == "review" and code_task(w)["state"] == "waiting" and state(w)["failure"] is None
    assert state(w)["steps"]["still"]["result"]["code"] == "image_not_built" and ops.pending(w.project)["pending"] == pending


def test_prepare_again_from_the_review_gives_a_late_still_and_runs_no_other_step_before_it(w):
    start(w)
    make_late(w)
    before = {r: len(kit.verbs(w.tree, r)) for r in ("transcriber", "renderer")}
    out = ops.prepare_again(w.project, w.rid, "review")
    assert out["ok"] is True and out["stopped"] == "review" and out["reset"] == ["review"]
    assert kit.verbs(w.tree, "renderer")[before["renderer"]:] == ["still"] and kit.verbs(w.tree, "transcriber")[before["transcriber"]:] == []
    assert ops.captions_read(w.project, w.rid)["still"] is not None


def test_the_still_is_not_made_once_the_review_is_answered(w):
    start(w)
    finish_review(w)
    make_late(w)
    before = len(kit.verbs(w.tree, "renderer"))
    out = ops.media_pipeline(w.project, w.rid)
    assert out["stopped"] == "approval" and kit.verbs(w.tree, "renderer")[before:] == [] and "still" not in state(w)["steps"]
    assert ops.captions_read(w.project, w.rid)["still"] is None


def test_a_skipped_still_is_not_tried_again_by_captions_done(w):
    kit.fail(w.tree, "renderer", "still", stderr="refused: docker_missing docker", exit=3, times=5)
    start(w)
    finish_review(w)
    assert kit.verbs(w.tree, "renderer").count("still") == 1


# --- preparing it again ----------------------------------------------------------------------------------------------------------------------------


def test_prepare_again_at_the_still_remakes_that_step_alone_and_keeps_the_review_and_every_other_step(w):
    start(w)
    first = state(w)["steps"]["still"]["result"]
    pending = ops.pending(w.project)["pending"]
    before = {r: len(kit.verbs(w.tree, r)) for r in ("transcriber", "renderer")}
    out = ops.prepare_again(w.project, w.rid, "still")
    assert out["ok"] is True and out["stopped"] == "review" and out["reset"] == ["still"]
    assert kit.verbs(w.tree, "renderer")[before["renderer"]:] == ["still"] and kit.verbs(w.tree, "transcriber")[before["transcriber"]:] == []
    assert state(w)["steps"]["still"]["result"] == first and stills(w) == [first["name"]]            # the same time, the same bytes, the same name
    assert ops.pending(w.project)["pending"] == pending and out["steps"]["review"] == "waiting" and out["steps"]["align-proposal"] == "done"


def test_prepare_again_at_analyse_or_before_removes_the_still_and_makes_it_again_and_after_the_retakes_keeps_it(w):
    start(w)
    first = state(w)["steps"]["still"]["result"]["name"]
    ops.prepare_again(w.project, w.rid, "retakes")
    assert state(w)["steps"]["still"]["status"] == "done" and kit.verbs(w.tree, "renderer").count("still") == 1 and stills(w) == [first]
    ops.prepare_again(w.project, w.rid, "analyse")
    assert kit.verbs(w.tree, "renderer").count("still") == 2 and state(w)["steps"]["still"]["status"] == "done" and stills(w) == [first]
    # a different time (another analysis) is another file, and the old one is removed with its step
    path = w.tree / "providers" / "renderer" / "analysis-source.json"
    doc = json.loads(path.read_text())
    doc["silences"] = [{"start": 0.0, "end": 3.4}] + doc["silences"][1:]
    path.write_text(json.dumps(doc))
    ops.prepare_again(w.project, w.rid, "transcribe")
    assert state(w)["steps"]["still"]["result"]["at_ms"] == 3100 and len(stills(w)) == 1 and stills(w) != [first]


def test_the_step_is_in_the_choices_of_prepare_again_and_a_raw_purge_takes_the_still_with_the_recording(w):
    row = [r for r in st.load("operations").OPERATIONS if r["name"] == "prepare-again"][0]
    assert "still" in [a for a in row["args"] if a["name"] == "step"][0]["choices"]
    start(w)
    assert len(stills(w)) == 1
    media._purge_raw(w.data, w.rid, w.folder, media.now_utc())
    assert stills(w) == [], "the still is a picture of the raw recording: it goes with it, unlike the renders and covers"


# --- the still's prepare-again touches nothing else (review of #381) -------------------------------------------------------------------------------


def snapshot(w):
    """What a side step's prepare-again must leave alone: the state without the still's entry, the record's marker, the task, the decisions."""
    saved = state(w)
    saved["steps"].pop("still", None)
    return {"state": saved, "resume": media.load(w.data, w.rid).get("resume"), "task": code_task(w)["state"],
            "pending": ops.pending(w.project)["pending"]}


def test_prepare_again_at_the_still_after_a_send_back_is_refused_and_keeps_the_marker_the_review_and_the_still(w):
    from test_media_pipeline import send_back
    start(w)
    finish_review(w)
    made = state(w)["steps"]["still"]
    send_back(w)
    before, calls = snapshot(w), len(kit.calls(w.tree, "renderer"))
    with pytest.raises(ops.OpsError, match="already answered"):
        ops.prepare_again(w.project, w.rid, "still")
    assert snapshot(w) == before and state(w)["steps"]["still"] == made and stills(w) == [made["result"]["name"]]
    assert len(kit.calls(w.tree, "renderer")) == calls, "no provider ran"
    assert media.load(w.data, w.rid)["resume"]["step"] == "review", "the send-back is still there to be consumed"
    out = ops.media_pipeline(w.project, w.rid)                        # and the next ordinary call reopens the review as before
    assert out["stopped"] == "review" and "resume" not in media.load(w.data, w.rid)


def test_prepare_again_at_the_still_does_not_relaunch_a_failed_main_step_or_clear_the_failure(w):
    kit.fail(w.tree, "renderer", "render", times=1)
    start(w)
    finish_review(w)
    failed = state(w)
    assert failed["failure"]["step"] == "render" and code_task(w)["state"] == "failed"
    calls = len(kit.calls(w.tree, "renderer"))
    kit.heal(w.tree, "renderer")
    with pytest.raises(ops.OpsError, match="already answered"):
        ops.prepare_again(w.project, w.rid, "still")                  # the review is answered: refused, nothing relaunched
    assert state(w) == failed and code_task(w)["state"] == "failed" and len(kit.calls(w.tree, "renderer")) == calls


def test_a_failed_step_before_the_review_is_not_relaunched_by_the_stills_prepare_again(w):
    kit.fail(w.tree, "renderer", "align", times=1)                     # align-proposal fails; the still was made before it
    out = start(w)
    assert out["failed"] == "align-proposal"
    failure, calls = state(w)["failure"], len(kit.calls(w.tree, "renderer"))
    kit.heal(w.tree, "renderer")
    done = ops.prepare_again(w.project, w.rid, "still")
    assert done["ok"] is True and done["reset"] == ["still"] and "stopped" not in done
    assert [c[0] for c in kit.calls(w.tree, "renderer")[calls:]] == ["still"], "only the still ran: the failed step is not relaunched"
    assert state(w)["failure"] == failure and state(w)["steps"]["align-proposal"]["status"] == "failed" and code_task(w)["state"] == "failed"


def test_a_remake_that_is_skipped_keeps_the_earlier_still_and_its_file(w):
    start(w)
    made = state(w)["steps"]["still"]
    kit.fail(w.tree, "renderer", "still", stderr="refused: docker_missing docker", exit=3)
    done = ops.prepare_again(w.project, w.rid, "still")
    assert done["ok"] is True and done["still_code"] == "docker_missing" and done["still_status"] == "done" and done["reset"] == ["still"]
    assert state(w)["steps"]["still"] == made and stills(w) == [made["result"]["name"]] and done["still"]["name"] == made["result"]["name"]


def test_a_remake_at_another_time_removes_the_old_file_only_after_the_new_one_is_made(w):
    start(w)
    first = state(w)["steps"]["still"]["result"]["name"]
    path = w.tree / "providers" / "renderer" / "analysis-source.json"
    doc = json.loads(path.read_text())
    doc["silences"] = [{"start": 0.0, "end": 3.4}] + doc["silences"][1:]
    path.write_text(json.dumps(doc))
    os.unlink(os.path.join(w.folder, "analysis.json"))
    with open(os.path.join(w.folder, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f)
    done = ops.prepare_again(w.project, w.rid, "still")
    now = state(w)["steps"]["still"]["result"]
    assert done["still_status"] == "done" and now["at_ms"] == 3100 and stills(w) == [now["name"]] and now["name"] != first


def test_the_remake_is_refused_before_the_recording_is_analysed(w):
    kit.fail(w.tree, "renderer", "analyse", times=1)
    start(w)
    assert state(w)["steps"].get("still") is None
    with pytest.raises(ops.OpsError, match="already answered or not reached"):
        ops.prepare_again(w.project, w.rid, "still")
