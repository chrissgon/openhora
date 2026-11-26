"""Tests of a clip in the cutaway (package V9b-5c): `step_media.fit_clip_entries` ends a cutaway with its clip, a seeded sweep proves the engine meets the fitted answer
(ffmpeg's last-frame hold, through the renderer's own timeline and clip rows), the constants the runtime copies from the renderer
equal their sources, and the media step hands a clip to the render by its `.mp4` name, refuses a clip made at another rate and a file swapped under its name. The engine is the fake
of media_kit; the clips are planted bytes; nothing is called, and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_media_clips.py
"""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import flag, media, open_items, ops, ops_core, run_task, step_media, steps, task_row, work_file, world  # noqa: F401
from media_stock_kit import LIBRARY, SLOT_SOURCE, media_stock, ops_media_stock, pick, review_of, to_found
from test_step_media_assets import COMPLETE_BEATS, go_on, stock_dir

REPO = st.REPO
PRESETS = json.loads((REPO / "providers" / "renderer" / "renderer-presets.json").read_text(encoding="utf-8"))
LAYER = {"id": "b7", "beat": 7, "preset": "cutaway", "params": {"label": "My dashboard", "fit": "cover", "asset": "beat7"}, "word_from": 0, "word_to": 9, "score": 1.0}


def synthetic_edl(fps=30, count=20, step=0.5, length=0.4):
    """An edit list with the fields `fit_clip_entries` reads: `fps` and words with output `start` and `end`, half a second apart."""
    return {"fps": fps, "words": [{"index": i, "start": i * step, "end": i * step + length} for i in range(count)]}


def beats_with(*entries, bucket="layouts"):
    return {"overlays": [], "layouts": [], bucket: [copy.deepcopy(e) for e in entries]}


# --- fit_clip_entries -----------------------------------------------------------------------------------------------------------------------------


def test_a_clip_longer_than_its_beat_leaves_the_beats_byte_identical():
    beats, edl = beats_with(LAYER), synthetic_edl()
    before = json.dumps(beats, sort_keys=True)
    assert step_media.fit_clip_entries(beats, edl, {"beat7": 10.0}) == [] and json.dumps(beats, sort_keys=True) == before
    assert step_media.fit_clip_entries(beats, edl, {"beat7": 12.0}) == [] and json.dumps(beats, sort_keys=True) == before      # a clip is kept at ten seconds at most, and 10 s is enough here


def test_a_clip_shorter_than_its_beat_lowers_word_to_to_the_last_word_that_fits_with_two_frames_to_spare():
    beats, edl = beats_with(LAYER), synthetic_edl()
    assert step_media.fit_clip_entries(beats, edl, {"beat7": 4.0}) == ["beat7"]
    assert beats["layouts"][0]["word_to"] == 6      # room = (120 - 2) / 30 = 3.93 s; word 6 ends at 3.4 and its beat is 3.6 s, word 7's is 4.1 s
    assert beats["layouts"][0]["word_from"] == 0 and beats["layouts"][0]["params"] == LAYER["params"]


def test_a_beat_whose_first_word_does_not_fit_is_refused_naming_the_slot():
    beats, edl = beats_with(LAYER), synthetic_edl()
    with pytest.raises(steps.StepFailure) as refused:
        step_media.fit_clip_entries(beats, edl, {"beat7": 1.5})      # the cutaway lasts 1.5 s at least, and the clip less two frames is 1.43 s
    assert refused.value.code == "clip_too_short" and refused.value.field == "beat7" and refused.value.next == step_media.CLIP_SHORT_NEXT


def test_a_preset_outside_the_timing_table_is_asset_type_and_an_entry_without_a_clip_slot_is_untouched():
    beats = beats_with(dict(LAYER, preset="screenshot"))
    with pytest.raises(steps.StepFailure) as refused:
        step_media.fit_clip_entries(beats, synthetic_edl(), {"beat7": 4.0})
    assert refused.value.code == "asset_type" and refused.value.field == "beat7"
    other = dict(LAYER, id="b8", params={"label": "x", "fit": "cover", "asset": "beat8"})
    beats = beats_with(LAYER, other)
    assert step_media.fit_clip_entries(beats, synthetic_edl(), {"beat7": 4.0}) == ["beat7"] and beats["layouts"][1] == other


def test_the_same_slot_in_two_entries_fits_both():
    beats = {"overlays": [copy.deepcopy(dict(LAYER, id="o1"))], "layouts": [copy.deepcopy(LAYER)]}
    assert step_media.fit_clip_entries(beats, synthetic_edl(), {"beat7": 4.0}) == ["beat7", "beat7"]
    assert beats["layouts"][0]["word_to"] == 6 and beats["overlays"][0]["word_to"] == 6


# --- both engines, the same answer ----------------------------------------------------------------------------------------------------------------


def renderer_world(fps):
    """(data, vocab, catalogue, edl) of the renderer's own code for one frame rate: the base edit list of its kit's transcript. No process, no container."""
    folder = str(REPO / "providers" / "renderer")
    for one in (folder, folder + "/tests"):
        if one not in sys.path:
            sys.path.insert(0, one)
    import _blocks, _edl, _vocab  # noqa: E401
    import renderer_kit as K
    data, vocab = _vocab.load_data(), _vocab.load_vocabulary(str(K.VOCABULARY))
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, data, {}, fps=fps)
    return data, vocab, _blocks.load_catalogue(), edl


def test_a_seeded_sweep_fits_every_clip_without_a_refusal_or_a_held_frame():
    worlds = {fps: renderer_world(fps) for fps in (24, 25, 30, 50, 60)}
    import _edl, _render  # noqa: E401  (on the path since renderer_world)
    rng, fitted, refused = random.Random(20261122), 0, 0
    for case in range(360):
        fps = (24, 25, 30, 50, 60)[case % 5]
        data, vocab, catalogue, edl = worlds[fps]
        words = [w["index"] for w in edl["words"]]
        first = rng.choice(words[:-2])
        last = rng.choice(words[words.index(first):words.index(first) + rng.choice((1, 3, 8, 20, 60))])
        seconds = round(rng.uniform(1.5 + 3.0 / fps, 12.0), 3)
        clip = min(seconds, 10.0)
        frames = int(round(clip * fps))
        beats = {"overlays": [], "layouts": [dict(LAYER, word_from=first, word_to=last)]}
        facts = {"width": 1080, "height": 1920, "seconds": clip, "fps": fps, "tint": None}
        timeline = _edl.resolve_timeline(edl, beats, vocab, data)
        [entry] = timeline["beats"]
        try:
            step_media.fit_clip_entries(beats, edl, {"beat7": clip})
        except steps.StepFailure as e:      # a first word alone longer than the clip: counted, never skipped silently
            assert e.code == "clip_too_short"
            refused += 1
            continue
        fitted += 1
        timeline = _edl.resolve_timeline(edl, beats, vocab, data)
        [entry] = timeline["beats"]
        assert entry["end_frame"] - entry["start_frame"] <= frames - 1, (case, fps, seconds)      # no held frame on ffmpeg
        entry["block"] = "oh:cutaway"
        kinds = {"beat7": dict(facts, kind="clip")}
        _render.settle_clips(vocab, data, timeline, kinds)
        [row] = _render.clip_rows(data, timeline, kinds, edl["theme"]["colors"])
        assert row["end_frame"] - row["start_frame"] <= frames - 1
    assert fitted + refused == 360 and fitted >= 300      # most cases were fitted


def test_the_beats_the_runtime_wrote_pass_the_renderers_own_check():
    from test_step_media_assets import renderer_checker
    check, _ = renderer_checker()
    data, vocab, catalogue, edl = renderer_world(30)
    beats = dict(COMPLETE_BEATS, layouts=[dict(LAYER, word_from=3, word_to=40)], slots=[{"slot": "beat7", "beat": 7, "param": "asset", "type": "image", "description": "a mountain lake"}])
    assert step_media.fit_clip_entries(beats, edl, {"beat7": 3.0}) == ["beat7"]
    assert check(beats)["mentions"] == []


# --- the constants the runtime copies -------------------------------------------------------------------------------------------------------------


def test_the_constants_the_runtime_copies_equal_their_sources():
    cutaway = PRESETS["presets"]["cutaway"]
    assert step_media.CLIP_TIMING["cutaway"] == {"tail": cutaway["tail"], "min_duration": cutaway["min_duration"], "max_duration": cutaway["max_duration"]}
    assert cutaway["anchor"] == "window" and cutaway["looks"]["transition"] == "cut"
    assert media_stock.KIND_BYTES["clip"] == PRESETS["limits"]["asset_max_bytes"] == 67108864
    folder = str(REPO / "providers" / "renderer")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import _media
    assert media_stock.CLIP_SECONDS_MAX == step_media.CLIP_SECONDS_MAX == _media.CLIP_MAX_SECONDS
    assert ops_media_stock.CLIP_MIN_DURATION == step_media.CLIP_TIMING["cutaway"]["min_duration"]
    source = (REPO / "providers" / "renderer" / "_render.py").read_text(encoding="utf-8")
    assert 'e["block"] != "oh:cutaway" or name != "asset"' in source
    animation = st.load("media_animation")
    assert (animation.CLIP_BLOCK, animation.CLIP_PARAM) == ("oh:cutaway", "asset")


# --- the step, through the media kit --------------------------------------------------------------------------------------------------------------


def clip_engine(engine, count=20, length=0.4):
    """The fake renderer for a clip video: the proposal and the final beats hold one cutaway layout that asks for `beat7` (words 0 to 9), the edit lists carry the frame rate and the words'
    times (`count` words half a second apart), as the real renderer's do."""
    original = engine._base

    def base(a):
        done = original(a)
        out = flag(a, "--out")
        doc = json.loads(Path(out).read_text())
        doc["fps"] = 30
        if not out.endswith("proposal.edl.json"):
            doc.update(words=[{"index": i, "start": i * 0.5, "end": i * 0.5 + length} for i in range(count)], out_frames=int(count * 15 + 30))
        Path(out).write_text(json.dumps(doc))
        return done

    def align(a):
        out = flag(a, "--out")
        layer = dict(LAYER)
        if out.endswith("proposal.beats.json"):
            Path(out).write_text(json.dumps({"report": [{"beat": 7, "preset": "cutaway", "matched": True}], "slots": [dict(SLOT_SOURCE, slot="beat7")], "overlays": [], "layouts": [layer]}))
        else:
            Path(out).write_text(json.dumps(dict(COMPLETE_BEATS, layouts=[layer])))
        return {"ok": True, "beats": 1, "overlays": 0, "layouts": 1, "unmatched": []}
    engine._base, engine._align = base, align


def clip_video(world, monkeypatch, seconds=4.0, approve=True, length=0.4):
    """A video with a clip found, picked, fetched and approved (the fake library `fakelib`, the fake renderer's `clip_seconds` set), waiting at the review."""
    clip_engine(world["engine"], length=length)
    found = to_found(world, monkeypatch, {"beat7": ("market stall", "clip")}, stock=["fakelib"], extra={"fakelib": LIBRARY})
    found["sheets"].clip_seconds = seconds
    done = ops.video_media_find(world["path"], found["task"], confirm=True)
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    answer = ops.video_media_fetch_picks(world["path"], found["task"])
    shown = ops.video_media_approve(world["path"], found["task"])
    if approve:
        ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    return dict(found, shown=shown, answer=answer)


def beats_of(world):
    return json.loads(work_file(world, "beats.json").read_text())


def test_an_approved_clip_is_handed_to_the_renderer_by_its_mp4_name_and_hash_and_the_beat_is_shortened(world, monkeypatch):
    video = clip_video(world, monkeypatch, seconds=4.0)
    assert go_on(world, video["task"])["stopped"] == "deliver"
    [asset] = video["shown"]["set"]["assets"]
    assert asset["kind"] == "clip" and asset["seconds"] == 4.0
    args = world["engine"].of("render")[-1]["args"]
    path = stock_dir(world) / ("asset-%s.mp4" % asset["sha256"][:12])
    assert path.is_file() and flag(args, "--asset") == "beat7=" + str(path) and flag(args, "--asset-sha256") == "beat7=" + asset["sha256"]
    assert beats_of(world)["layouts"][0]["word_to"] == 6
    result = task_row(world, video["task"])["step_state"]["steps"]["align"]["result"]
    assert result["clips"] == 1 and result["clips_shortened"] == 1 and result["pictures"] == 1


def test_a_clip_longer_than_its_beat_changes_no_beat_and_a_picture_video_returns_the_keys_it_always_did(world, monkeypatch):
    video = clip_video(world, monkeypatch, seconds=10.0)
    assert go_on(world, video["task"])["stopped"] == "deliver"
    assert beats_of(world)["layouts"][0]["word_to"] == 9
    result = task_row(world, video["task"])["step_state"]["steps"]["align"]["result"]
    assert result["clips"] == 1 and result["clips_shortened"] == 0


def test_a_picture_video_adds_no_clip_keys_to_the_align_result(world, monkeypatch):
    from test_step_media_assets import approved_video
    video = approved_video(world, monkeypatch)
    assert go_on(world, video["task"])["stopped"] == "deliver"
    result = task_row(world, video["task"])["step_state"]["steps"]["align"]["result"]
    assert "clips" not in result and "clips_shortened" not in result and result["pictures"] == 1


def test_a_clip_made_at_another_rate_than_the_edit_lists_is_refused_before_the_renderer_draws_it(world, monkeypatch):
    video = clip_video(world, monkeypatch)
    doc = json.loads((stock_dir(world) / "set.json").read_text())
    assert doc["clip_fps"] == 30
    media_stock.write_doc(world["data"], world["rid"], "set.json", dict(doc, clip_fps=24))      # outside the hashed set document: the approval still holds
    out = go_on(world, video["task"])
    assert out["ok"] is False and out["code"] == "clip_fps_changed" and not world["engine"].of("render")


def test_an_mp4_swapped_under_its_name_fails_before_the_renderer_is_asked(world, monkeypatch):
    video = clip_video(world, monkeypatch)
    [asset] = video["shown"]["set"]["assets"]
    path = stock_dir(world) / ("asset-%s.mp4" % asset["sha256"][:12])
    path.chmod(0o600)
    path.write_bytes(b"\x00\x00\x00\x18ftypisom swapped")
    out = go_on(world, video["task"])
    assert out["ok"] is False and out["code"] == "asset_changed" and not world["engine"].of("render")


def test_a_beat_whose_first_word_is_longer_than_the_clip_fails_the_align_step_naming_the_slot(world, monkeypatch):
    video = clip_video(world, monkeypatch, seconds=2.0, length=2.2)      # long enough to be fetched (1.6 s), too short for a first word that lasts 2.2 s
    out = go_on(world, video["task"])
    assert out["ok"] is False and out["code"] == "clip_too_short" and not world["engine"].of("render")
