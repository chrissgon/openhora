"""A picture beat wins over a text overlay it overlaps (V9b-3e). One beat track still; but a layout with an asset slot keeps its own range against every text beat
(an overlay, or a layout with no slot), and the text beat yields: it ends where the picture starts, starts where the picture ends, or is dropped as `under_picture`.
Picture against picture and text against text keep the earlier rule.

Offline: the documents are the kit's fictional post, the pictures are made in the test, the recording check is stood in for. No ffmpeg, no browser, no docker."""
from __future__ import annotations

import copy
import json

import pytest

import renderer_kit as K
import _blocks
import _edl
import _hf_compose as C
import _render
from test_dropped_beat_picture import NOT_A_PNG, a_png, layout, live_shape, with_slots

# the kit's post: overlays b3 (words 14-21), b4 (22-31), b5 (32-42), b6 (43-52)


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("picwins")
    data, edl, beats, vocab = K.hf_documents(folder)
    return data, edl, beats, vocab, folder


def resolve(docs, rows, overlays=None):
    data, edl, beats, vocab, _ = docs
    beats = copy.deepcopy(beats)
    if overlays is not None:
        beats["overlays"] = overlays
    beats = with_slots(beats, rows)
    return _edl.resolve_timeline(edl, beats, vocab, data), beats


def by_id(timeline):
    return {e["id"]: e for e in timeline["beats"]}


def test_the_live_shape_draws_a3_on_its_own_range_and_b4_starts_at_its_end(docs, tmp_path, monkeypatch):
    data, edl, beats, vocab = live_shape(docs)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    rows = by_id(timeline)
    # b1 and b2 are left with fewer frames than their preset's minimum once a1 and a2 take their words: dropped (the minimum, below), not kept as a flash
    assert timeline["dropped"] == ["b1", "b2"] and timeline["dropped_reasons"] == [{"id": "b1", "reason": "under_picture"}, {"id": "b2", "reason": "under_picture"}]
    assert rows["b4"]["start_frame"] == rows["a3"]["end_frame"] and rows["b4"].get("clipped") and not rows["a3"].get("clipped")
    (tmp_path / "edl.json").write_text(json.dumps(edl))
    (tmp_path / "beats.json").write_text(json.dumps(beats))
    monkeypatch.setattr(_render, "check_recording", lambda *a, **k: {})
    files = {}
    for slot, raw in (("a1", a_png()), ("a2", a_png((200, 30, 30))), ("a3", a_png((30, 200, 30)))):
        (tmp_path / (slot + ".png")).write_bytes(raw)
        files[slot] = str(tmp_path / (slot + ".png"))
    for lay, slot in zip(beats["layouts"], ("a1", "a2", "a3")):          # the slots of the live shape are named after the layouts
        lay["params"]["asset"] = slot
    for row, slot in zip(beats["slots"], ("a1", "a2", "a3")):
        row["slot"] = slot
    (tmp_path / "beats.json").write_text(json.dumps(beats))
    result = _render.render(edl_path=str(tmp_path / "edl.json"), beats_path=str(tmp_path / "beats.json"), src="unused.mp4", out=str(tmp_path / "out"),
                            platform_path=str(K.INSTAGRAM), vocabulary_path=str(K.VOCABULARY), asset_files=files, asset_sha256s={}, ffmpeg="ffmpeg", ffprobe="ffprobe",
                            browser={"path": "chrome"}, dry_run=True)
    assert "assets_dropped" not in result and result["beats_dropped"] == ["b1", "b2"]
    assert {"a1", "a2", "a3"} <= {b["id"] for b in result["beats_drawn"]}


def test_a_text_beat_that_starts_before_a_picture_ends_where_the_picture_starts(docs):
    timeline, _ = resolve(docs, [layout("a1", 7, "s1", 29, 31)])
    rows = by_id(timeline)
    assert rows["a1"]["start_frame"] > rows["b4"]["start_frame"]
    assert timeline["dropped"] == []
    assert rows["b4"]["end_frame"] == rows["a1"]["start_frame"] and rows["b4"].get("clipped")


def test_a_text_beat_wholly_inside_a_picture_is_dropped_with_its_reason(docs):
    timeline, _ = resolve(docs, [layout("a1", 7, "s1", 20, 40)])
    assert "b4" in timeline["dropped"] and "b4" not in by_id(timeline) and "a1" in by_id(timeline)
    assert {"id": "b4", "reason": "under_picture"} in timeline["dropped_reasons"]
    assert not by_id(timeline)["a1"].get("clipped")


def test_a_text_beat_that_starts_inside_a_picture_starts_where_it_ends(docs):
    timeline, _ = resolve(docs, [layout("a1", 7, "s1", 22, 24)])
    rows = by_id(timeline)
    assert timeline["dropped"] == [] and rows["b4"]["start_frame"] == rows["a1"]["end_frame"] and rows["b4"]["clipped"] is True


def test_a_text_beat_that_spans_a_picture_keeps_the_longer_side(docs):
    after, _ = resolve(docs, [layout("a1", 7, "s1", 23, 24)])             # a short part before the picture, a long one after
    rows = by_id(after)
    assert rows["b4"]["start_frame"] == rows["a1"]["end_frame"] and after["dropped"] == []
    before, _ = resolve(docs, [layout("a1", 7, "s1", 29, 31)])            # a long part before, a short one after
    rows = by_id(before)
    assert rows["b4"]["end_frame"] == rows["a1"]["start_frame"] and before["dropped"] == []


def test_a_text_beat_over_two_pictures_keeps_the_longer_end_part(docs):
    timeline, _ = resolve(docs, [layout("a1", 7, "s1", 22, 23), layout("a2", 8, "s2", 25, 26)])
    rows = by_id(timeline)
    assert timeline["dropped"] == [] and rows["b4"]["start_frame"] == rows["a2"]["end_frame"]


def test_two_picture_beats_that_start_together_keep_the_old_rule_and_the_shorter_slot_is_dropped(docs, tmp_path, monkeypatch):
    rows = [layout("a1", 7, "s1", 22, 24), layout("a2", 8, "s2", 22, 27)]
    timeline, beats = resolve(docs, rows)
    assert timeline["dropped"] == ["a1"] and "a2" in by_id(timeline) and timeline["dropped_reasons"] == [{"id": "a1", "reason": "overlap"}]
    used, dropped_only = _edl.classify_slots(beats, timeline, docs[3], {"s1": 1, "s2": 2})
    assert dropped_only == {"s1"} and used == {"s2"}


def test_two_text_beats_keep_the_old_rule(docs):
    data, edl, beats, vocab, _ = docs
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    assert timeline["dropped"] == [] and "dropped_reasons" not in timeline
    doubled = copy.deepcopy(beats)
    doubled["overlays"] = [dict(doubled["overlays"][1], id="b4a", word_to=24)] + doubled["overlays"]      # b4a starts with b4 and is the shorter
    timeline = _edl.resolve_timeline(edl, doubled, vocab, data)
    assert timeline["dropped"] == ["b4a"] and timeline["dropped_reasons"] == [{"id": "b4a", "reason": "overlap"}]


def test_a_layout_with_no_slot_in_its_params_is_a_text_beat(docs):
    data, edl, beats, vocab, _ = docs
    plain = {"id": "a9", "beat": 9, "preset": "cutaway", "params": {"label": "A line"}, "word_from": 22, "word_to": 24, "score": 1.0}      # no `asset` given: not a picture
    only = copy.deepcopy(beats)
    only["layouts"] = [plain]
    timeline = _edl.resolve_timeline(edl, only, vocab, data)
    assert timeline["dropped"] == ["a9"] and timeline["dropped_reasons"] == [{"id": "a9", "reason": "overlap"}]          # the shorter of two text beats loses, as before
    assert by_id(timeline)["b4"]["start_frame"] == _edl.resolve_timeline(edl, beats, vocab, data)["beats"][1]["start_frame"]


def test_hf_the_live_shape_composes_with_a3_drawn(docs, tmp_path):
    data, edl, beats, vocab = live_shape(docs)
    folder = tmp_path / "page"
    folder.mkdir()
    result = C.write_page(data, edl, beats, vocab, _blocks.load_catalogue(), str(folder), edl["fps"], {"s1": "a" * 64, "s2": "b" * 64, "s3": "c" * 64})
    assert "assets_dropped" not in result and result["beats_drawn"] == 5            # a1, a2, a3, b3 and b4: b1 and b2 are under pictures
    assert (folder / "blocks" / "oh-cutaway.html").exists()


def least(docs, preset):
    data, edl = docs[0], docs[1]
    return max(1, int(round(data["presets"][preset]["min_duration"] * edl["fps"])))


def test_a_text_beat_left_with_fewer_frames_than_its_minimum_is_dropped_and_one_left_with_exactly_that_is_kept(docs):
    data, edl, beats, vocab, _ = docs
    fps = edl["fps"]
    data = copy.deepcopy(data)
    only = [o for o in beats["overlays"] if o["id"] == "b4"]              # b4 alone: nothing else clips it, so what the picture leaves is what the pass measures
    beats2 = with_slots(copy.deepcopy(beats), [layout("a1", 7, "s1", 22, 24)])
    beats2["overlays"] = only
    data["presets"]["list"]["min_duration"] = 0.01                         # b4 is 4 seconds long by its words: this only lets the pass show what a picture leaves of it
    b4 = by_id(_edl.resolve_timeline(edl, beats2, docs[3], data))["b4"]
    left = b4["end_frame"] - b4["start_frame"]
    data["presets"]["list"]["min_duration"] = (left - 0.4) / fps          # exactly `left` frames are enough
    assert "b4" in by_id(_edl.resolve_timeline(edl, beats2, docs[3], data))
    data["presets"]["list"]["min_duration"] = (left + 0.6) / fps          # one frame fewer than the minimum
    timeline = _edl.resolve_timeline(edl, beats2, docs[3], data)
    assert "b4" not in by_id(timeline) and timeline["dropped_reasons"] == [{"id": "b4", "reason": "under_picture"}]


def test_the_live_shape_keeps_no_text_beat_shorter_than_its_minimum(docs):
    data, edl, beats, vocab = live_shape(docs)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    for row in timeline["beats"]:
        if row["id"].startswith("b"):
            assert row["end_frame"] - row["start_frame"] >= least(docs, row["preset"]), row["id"]
