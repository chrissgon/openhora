"""The gates of the HyperFrames engine (`_hf_gate.py`, package V3b-2): the rules on the boxes the page reported, the pixel check of the face region
against the undrawn base, and the `encode` verb that runs both. The rules are arithmetic on synthetic boxes; the pixel check and the verb run the
host's ffmpeg on generated test patterns (skipped without it). No docker, no browser, no HyperFrames. Every input is synthetic."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import renderer_kit as K
import _docker as D
import _blocks
import _edl
import _hf_compose
import _hf_gate as G
import _layout
import _media
from _text import Refusal
from _vocab import load_data, load_vocabulary

needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
DATA = load_data()
FACE = {"x": 300, "y": 700, "w": 480, "h": 600}


def ffmpeg(*args):
    subprocess.run([K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True, timeout=600)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    return K.hf_documents(tmp_path_factory.mktemp("gate-docs"))


def boxes_doc(frames: int, per_frame=None, fonts=None) -> dict:
    rows = [[] for _ in range(frames)]
    for f, boxes in (per_frame or {}).items():
        rows[f] = boxes
    return {"schema": 1, "fps": 30, "frames": frames, "per_frame": rows, "fonts": fonts if fonts is not None else [{"custom": True, "family": "Inter"}]}


def write_boxes(folder: Path, doc: dict):
    path = folder / "boxes.json"
    raw = json.dumps(doc, sort_keys=True).encode()
    path.write_bytes(raw)
    return str(path), sha(raw)


def box(zone="caption", x=100.0, y=1400.0, w=300.0, h=60.0, key="hf-inst-0", glyph=False) -> dict:
    return {"glyph": glyph, "h": h, "key": key, "w": w, "x": x, "y": y, "zone": zone}


def timeline_of(docs):
    data, edl, beats, vocab = copy.deepcopy(docs)
    return data, edl, _edl.resolve_timeline(edl, beats, vocab, data), _edl.range_faces(edl, data)


def code_of(call, *args) -> tuple:
    with pytest.raises(Refusal) as caught:
        call(*args)
    return caught.value.code, caught.value.field


# ---------------------------------------------------------------- reading boxes.json

def test_a_boxes_file_with_its_hash_the_frames_and_the_two_fonts_is_read(tmp_path):
    path, digest = write_boxes(tmp_path, boxes_doc(10, fonts=[{"custom": True, "family": "Inter"}, {"custom": True, "family": "JetBrains Mono"}]))
    assert G.read_boxes(path, digest, 10)["frames"] == 10


def test_a_boxes_file_whose_hash_is_not_the_named_one_is_boxes_changed(tmp_path):
    path, digest = write_boxes(tmp_path, boxes_doc(5))
    assert code_of(G.read_boxes, path, "0" * 64, 5) == ("boxes_changed", "boxes")
    assert G.read_boxes(path, digest, 5)["frames"] == 5


@pytest.mark.parametrize("text", ["not json", "[]", '{"schema": 2, "frames": 1, "per_frame": [[]], "fonts": []}',
                                  '{"schema": 1, "frames": 1, "per_frame": "x", "fonts": []}', '{"schema": 1, "frames": true, "per_frame": [], "fonts": []}',
                                  '{"schema": 1, "frames": 1, "per_frame": [{}], "fonts": []}', '{"schema": 1, "frames": 1, "per_frame": [[1]], "fonts": []}',
                                  '{"schema": 1, "frames": 1, "per_frame": [[]], "fonts": [1]}'])
def test_a_boxes_file_that_is_not_the_shape_the_script_writes_is_boxes_unreadable(tmp_path, text):
    path = tmp_path / "boxes.json"
    path.write_text(text)
    assert code_of(G.read_boxes, str(path), sha(text.encode()), 1) == ("boxes_unreadable", "boxes")


@pytest.mark.parametrize("bad", [{"zone": 1}, {"key": "has space"}, {"key": ""}, {"glyph": "no"}, {"x": float("nan")}, {"w": -1}, {"y": True}, {"h": None}])
def test_a_box_with_a_bad_field_is_boxes_unreadable(tmp_path, bad):
    path = tmp_path / "boxes.json"
    path.write_text(json.dumps(boxes_doc(1, {0: [dict(box(), **bad)]})))
    assert code_of(G.read_boxes, str(path), sha(path.read_bytes()), 1) == ("boxes_unreadable", "boxes")


def test_a_boxes_file_missing_a_link_or_over_its_cap_is_boxes_unreadable(tmp_path, monkeypatch):
    assert code_of(G.read_boxes, str(tmp_path / "nowhere.json"), "0" * 64, 1) == ("boxes_unreadable", "boxes")
    path, digest = write_boxes(tmp_path, boxes_doc(1))
    link = tmp_path / "link.json"
    link.symlink_to(path)
    assert code_of(G.read_boxes, str(link), digest, 1) == ("boxes_unreadable", "boxes")
    monkeypatch.setattr(G, "BOXES_MAX_BYTES", 10)
    assert code_of(G.read_boxes, path, digest, 1) == ("boxes_unreadable", "boxes")


def test_boxes_for_another_number_of_frames_than_the_edit_lists_are_boxes_frames_differ(tmp_path):
    path, digest = write_boxes(tmp_path, boxes_doc(9))
    assert code_of(G.read_boxes, path, digest, 10) == ("boxes_frames_differ", "boxes")
    doc = boxes_doc(10)
    doc["per_frame"].pop()                                  # frames says 10, the list holds 9
    path, digest = write_boxes(tmp_path, doc)
    assert code_of(G.read_boxes, path, digest, 10) == ("boxes_frames_differ", "boxes")


def test_more_than_the_most_boxes_in_a_frame_is_boxes_too_many(tmp_path):
    path, digest = write_boxes(tmp_path, boxes_doc(1, {0: [box()] * (G.MAX_BOXES_PER_FRAME + 1)}))
    assert code_of(G.read_boxes, path, digest, 1) == ("boxes_too_many", "boxes")
    path, digest = write_boxes(tmp_path, boxes_doc(1, {0: [box()] * G.MAX_BOXES_PER_FRAME}))
    assert G.read_boxes(path, digest, 1)["frames"] == 1


@pytest.mark.parametrize("fonts", [[{"custom": True, "family": "Arial"}], [{"custom": False, "family": "Inter"}], [{"custom": True, "family": "Inter"}, {"custom": False, "family": "JetBrains Mono"}]])
def test_a_font_that_is_not_one_of_the_two_custom_files_is_font_not_allowed(tmp_path, fonts):
    path, digest = write_boxes(tmp_path, boxes_doc(1, fonts=fonts))
    assert code_of(G.read_boxes, path, digest, 1) == ("font_not_allowed", "drawn")


def test_the_two_allowed_families_are_the_font_allow_lists(tmp_path):
    allow = json.loads((K.RENDERER / "assets" / "fonts" / "allowlist.json").read_text())
    rows = allow["fonts"] if isinstance(allow, dict) and "fonts" in allow else allow
    families = {row["family"] for row in (rows.values() if isinstance(rows, dict) else rows)}
    assert families == set(G.ALLOWED_FAMILIES)


# ---------------------------------------------------------------- the face of each frame

def test_the_face_of_a_frame_is_the_entry_on_in_the_zone_else_the_ranges_face():
    a, b = {"x": 0, "y": 0, "w": 100, "h": 100}, {"x": 50, "y": 0, "w": 100, "h": 200}
    ranges = [(0, 10, a), (10, 20, b)]
    entry = {"start_frame": 5, "end_frame": 15, "face": {"x": 0, "y": 0, "w": 150, "h": 200}}
    other = {"start_frame": 12, "end_frame": 14, "face": {"x": 0, "y": 0, "w": 300, "h": 300}}
    faces = G.faces_by_frame({"captions": [entry], "beats": [other]}, ranges, 20)
    assert faces["caption"][4] is a and faces["caption"][16] is b
    assert faces["caption"][5] == faces["caption"][14] == entry["face"]
    assert faces["card"][5] is a and faces["card"][12] == other["face"] and faces["card"][14] is b
    both = G.faces_by_frame({"captions": [entry, dict(entry, start_frame=8, end_frame=9, face={"x": 500, "y": 0, "w": 10, "h": 10})], "beats": []}, ranges, 20)
    assert both["caption"][8] == {"x": 0, "y": 0, "w": 510, "h": 200} and both["caption"][9] == entry["face"]


def test_the_faces_of_the_real_timeline_cover_every_frame(docs):
    data, edl, timeline, faces_of_ranges = timeline_of(docs)
    faces = G.faces_by_frame(timeline, faces_of_ranges, edl["out_frames"])
    assert len(faces["caption"]) == len(faces["card"]) == edl["out_frames"]
    assert all(f["w"] > 0 and f["h"] > 0 for f in faces["caption"] + faces["card"])


# ---------------------------------------------------------------- the rules on the boxes

def check_without_the_glyph_rule(doc, timeline, ranges, data, **kwargs):
    """`check_boxes` with the caption-drawn rule out of reach (no entry is long enough to be judged): the tests that follow are about the other rules
    and draw no glyphs. The rule has its own tests, further down, with the real constant."""
    old = G.CAPTION_DRAWN_MIN_FRAMES
    G.CAPTION_DRAWN_MIN_FRAMES = 10 ** 9
    try:
        return G.check_boxes(doc, timeline, ranges, data, **kwargs)
    finally:
        G.CAPTION_DRAWN_MIN_FRAMES = old


def checked(docs, per_frame, frames=None):
    data, edl, timeline, ranges = timeline_of(docs)
    n = frames or edl["out_frames"]
    return check_without_the_glyph_rule(boxes_doc(n, per_frame), timeline, ranges, data)


def first_frame_without_an_entry(docs):
    data, edl, timeline, ranges = timeline_of(docs)
    busy = {f for e in timeline["captions"] + timeline["beats"] for f in range(e["start_frame"], e["end_frame"])}
    return next(f for f in range(edl["out_frames"]) if f not in busy), ranges, edl


def test_boxes_in_their_bands_pass_and_the_result_counts_them_and_gives_the_lowest_caption_bottom(docs):
    data, edl, timeline, ranges = timeline_of(docs)
    face = edl["face_box"]
    caption_top = face["y"] + face["h"] + data["zones"]["gap"] + 150      # well below any zoomed face: the band's lower half
    per = {3: [box("caption", y=caption_top, h=50.0, key="a"), box("card", y=data["zones"]["card_top"], h=40.0, key="b")],
           4: [box("caption", y=caption_top + 20, h=50.0, key="a", glyph=True)]}
    result = check_without_the_glyph_rule(boxes_doc(edl["out_frames"], per), timeline, ranges, data)
    assert result == {"frames": edl["out_frames"], "boxes": 3, "lowest_caption_bottom": round(caption_top + 70, 1)}
    assert check_without_the_glyph_rule(boxes_doc(edl["out_frames"]), timeline, ranges, data) == {"frames": edl["out_frames"], "boxes": 0, "lowest_caption_bottom": None}


def test_a_card_box_or_glyph_on_the_face_passes_nothing_is_refused_for_the_face(docs):
    """The maintainer's decision of 2026-11-24: an overlay may be drawn over the speaker's face (`overlay_hits_face` no longer exists)."""
    f, ranges, edl = first_frame_without_an_entry(docs)
    face = ranges[0][2]
    on_face = box("card", x=face["x"] + 10, y=face["y"] + 10, w=100.0, h=100.0, key="hf-inst-7")
    glyph = box("card", x=face["x"] + 20, y=face["y"] + 20, w=60.0, h=30.0, key="hf-inst-8", glyph=True)
    assert checked(docs, {f: [on_face, glyph]})["boxes"] == 2


def test_a_caption_box_or_glyph_on_the_face_passes_and_the_line_is_advice(docs):
    """The maintainer's decisions of 2026-11-24: a caption may cross the face; the 1560 line stays."""
    f, ranges, edl = first_frame_without_an_entry(docs)
    face = ranges[0][2]
    on_face = box("caption", x=face["x"] + 10, y=face["y"] + 10, w=100.0, h=100.0, key="hf-inst-7")
    glyph = box("caption", x=face["x"] + 20, y=face["y"] + 20, w=60.0, h=30.0, key="oh:caption", glyph=True)
    for hit in (on_face, glyph):
        checked_doc = checked(docs, {f: [hit]})
        assert checked_doc["boxes"] == 1
    low = checked(docs, {f: [box("caption", y=1540.0, h=40.0, glyph=True)]})
    assert [(r["code"], r["value"], r["default"]) for r in low["advice"]] == [("caption_below_line", 1580, 1560)]      # the line is advice, never a refusal (video P0b)


def test_a_box_that_only_touches_the_faces_edge_is_not_a_hit(docs):
    f, ranges, edl = first_frame_without_an_entry(docs)
    face = ranges[0][2]
    beside = box("card", x=face["x"] + face["w"], y=face["y"], w=50.0, h=50.0)
    assert checked(docs, {f: [beside]})["boxes"] == 1


@pytest.mark.parametrize("zone", ["cutaway", ""])
def test_a_box_of_a_zone_that_does_not_exist_is_box_zone_unknown(docs, zone):
    assert code_of(checked, docs, {2: [box(zone, y=10.0, h=10.0, key="x")]}) == ("box_zone_unknown", "frame 2 x")


def test_a_box_of_the_frame_band_passes_everywhere_a_layout_may_cover_the_face(docs):
    assert checked(docs, {2: [box("frame", y=10.0, h=10.0, key="x")]})["boxes"] == 1


def test_a_glyph_below_the_line_at_1560_is_caption_below_line_advice_and_one_at_the_line_is_not(docs):
    data = docs[0]
    line = data["zones"]["caption_bottom"]
    assert line == 1560
    low = box("caption", y=1530.0, h=40.0, glyph=True)                # bottom 1570
    got = checked(docs, {9: [low]})
    assert [(r["code"], r["value"], r["default"]) for r in got["advice"]] == [("caption_below_line", 1570, 1560)]
    at_line = checked(docs, {9: [box("caption", y=1520.0, h=40.0, glyph=True)]})
    assert at_line["lowest_caption_bottom"] == 1560.0 and "advice" not in at_line
    assert checked(docs, {9: [box("caption", y=1520.0, h=40.1)]})["advice"][0]["code"] == "caption_below_line"


def test_a_caption_element_below_the_line_is_advice_and_a_card_below_it_is_not_this_gates_business(docs):
    assert [(r["code"], r["value"]) for r in checked(docs, {1: [box("caption", y=1540.0, h=30.0)]})["advice"]] == [("caption_below_line", 1570)]
    assert checked(docs, {1: [box("card", y=1700.0, h=30.0)]})["boxes"] == 1


def test_a_box_with_no_area_is_neither_a_hit_nor_below_the_line(docs):
    f, ranges, edl = first_frame_without_an_entry(docs)
    face = ranges[0][2]
    assert checked(docs, {f: [box("caption", x=face["x"] + 5, y=1700.0, w=0.0, h=10.0), box("card", x=face["x"] + 5, y=face["y"] + 5, w=10.0, h=0.0)]})["boxes"] == 2


def test_the_ffmpeg_engines_own_arithmetic_is_what_decides(docs):
    data = docs[0]
    face = FACE
    assert _layout.zones(data, face)["caption"][1] == 1560
    assert _layout.caption_hit(box("caption", y=1551.0, h=10.0), _layout.zones(data, face))


def test_the_worst_caption_bottom_over_the_frames_is_the_advice_value(docs):
    data, edl, timeline, ranges = timeline_of(docs)
    faces = G.faces_by_frame(timeline, ranges, edl["out_frames"])["card"]
    late = edl["out_frames"] - 1
    face = faces[late]
    on_face = box("card", x=face["x"] + 5, y=face["y"] + 5, w=50.0, h=50.0, key="late")
    low = box("caption", y=1540.0, h=40.0, key="early")
    assert checked(docs, {1: [low], late: [on_face]})["advice"][0]["value"] == 1580
    worse = box("caption", y=1560.0, h=40.0, key="worse")
    got = checked(docs, {1: [low], late: [on_face, worse]})["advice"]
    assert [(r["code"], r["value"], r["count"]) for r in got] == [("caption_below_line", 1600, 2)]        # the worst bottom over the frames, and the card on the face is no refusal


# ---------------------------------------------------------------- a caption with words draws glyphs (C12, V3c)

def glyph_in(entry, key="oh:caption", **kwargs):
    """A caption glyph box of area inside the entry's caption band, at the frame `frame` (default: the entry's first)."""
    return box("caption", y=kwargs.pop("y", 1450.0), key=key, glyph=kwargs.pop("glyph", True), **kwargs)


def glyph_check(docs, drawn, minimum=None):
    """check_boxes on the real timeline of the kit with `drawn[k]` = (frame offset in entry k, box) for the entries that draw something."""
    data, edl, timeline, ranges = timeline_of(docs)
    per = {}
    for k, (offset, b) in drawn.items():
        e = timeline["captions"][k]
        per.setdefault(e["start_frame"] + offset, []).append(b)
    return G.check_boxes(boxes_doc(edl["out_frames"], per), timeline, ranges, data), timeline


def every_caption_drawn(docs, skip=(), **kwargs):
    data, edl, timeline, ranges = timeline_of(docs)
    return {k: (0, glyph_in(e, **kwargs)) for k, e in enumerate(timeline["captions"]) if k not in skip}


def test_the_constant_is_six_frames_and_the_kits_captions_are_judged(docs):
    data, edl, timeline, ranges = timeline_of(docs)
    assert G.CAPTION_DRAWN_MIN_FRAMES == 6
    assert timeline["captions"] and all(e["end_frame"] - e["start_frame"] >= 6 for e in timeline["captions"])


def test_every_caption_entry_with_a_glyph_box_of_area_passes(docs):
    result, timeline = glyph_check(docs, every_caption_drawn(docs))
    assert result["boxes"] == len(timeline["captions"]) and result["lowest_caption_bottom"] is not None


def test_a_caption_entry_with_only_zero_area_or_non_glyph_boxes_is_caption_not_drawn_advice_that_names_the_entry(docs):
    data, edl, timeline, ranges = timeline_of(docs)
    k = 1
    e = timeline["captions"][k]
    span = e["end_frame"] - e["start_frame"]
    assert span >= 6
    for bad in (glyph_in(e, w=0.0), glyph_in(e, h=0.0), glyph_in(e, glyph=False), box("card", y=300.0, h=40.0, glyph=True)):
        drawn = every_caption_drawn(docs, skip=(k,))
        drawn[k] = (2, bad)
        result, _ = glyph_check(docs, drawn)
        assert result["advice"] == [{"code": "caption_not_drawn", "value": span, "default": 0, "count": 1, "ids": ["c%d" % k]}]


def test_a_glyph_box_of_area_in_one_frame_of_the_span_is_enough_and_one_outside_it_is_not(docs):
    data, edl, timeline, ranges = timeline_of(docs)
    k = 2
    e = timeline["captions"][k]
    last = e["end_frame"] - e["start_frame"] - 1
    drawn = every_caption_drawn(docs, skip=(k,))
    drawn[k] = (last, glyph_in(e))
    glyph_check(docs, drawn)
    drawn[k] = (last + 1, glyph_in(e))                       # the next frame: another entry's, or none
    result, _ = glyph_check(docs, drawn)
    assert "c%d" % k in next(r for r in result["advice"] if r["code"] == "caption_not_drawn")["ids"]


def test_every_entry_that_draws_nothing_is_named_in_the_advice_in_order(docs):
    drawn = every_caption_drawn(docs, skip=(1, 3))
    result, _ = glyph_check(docs, drawn)
    row = next(r for r in result["advice"] if r["code"] == "caption_not_drawn")
    assert row["ids"] == ["c1", "c3"] and row["count"] == 2


def test_an_entry_of_five_frames_is_not_judged_and_one_of_six_is():
    face = {"x": 300, "y": 700, "w": 480, "h": 600}
    ranges = [(0, 40, face)]
    def timeline(span):
        return {"captions": [{"start_frame": 10, "end_frame": 10 + span, "face": face}], "beats": []}
    doc = boxes_doc(40)
    assert G.check_boxes(doc, timeline(5), ranges, DATA) == {"frames": 40, "boxes": 0, "lowest_caption_bottom": None}
    assert G.check_boxes(doc, timeline(6), ranges, DATA)["advice"] == [{"code": "caption_not_drawn", "value": 6, "default": 0, "count": 1, "ids": ["c0"]}]
    doc = boxes_doc(40, {12: [box("caption", y=1450.0, glyph=True)]})
    assert G.check_boxes(doc, timeline(6), ranges, DATA)["boxes"] == 1


def test_a_caption_with_no_entries_judges_nothing_and_pixel_group_is_gone():
    face = {"x": 300, "y": 700, "w": 480, "h": 600}
    assert G.check_boxes(boxes_doc(10), {"captions": [], "beats": []}, [(0, 10, face)], DATA)["boxes"] == 0
    assert not hasattr(G, "PIXEL_GROUP")


# ---------------------------------------------------------------- the pixel check: its command

def small_edl(kept=((0, 20), (30, 60)), zoom=None, fps=30):
    out = sum(b - a for a, b in kept)
    return {"fps": fps, "out_frames": out, "kept": [list(k) for k in kept], "face_box": dict(FACE),
            "zoom": zoom or {"mode": "none", "factor": 1.0, "push_in": 0.0, "anchor_y": 0.25}}


def ranges_of(edl):
    return _edl.range_faces(edl, DATA)


def test_the_pixel_command_pins_every_thread_ends_every_stream_and_never_uses_shortest():
    edl = small_edl()
    argv = G.pixel_argv("ffmpeg", "/in/hf.mov", "/in/proxy.mp4", edl, DATA, ranges_of(edl))
    assert "-shortest" not in argv
    assert argv[argv.index("-filter_threads") + 1] == "1" and argv[argv.index("-filter_complex_threads") + 1] == "1"
    inputs = [i for i, w in enumerate(argv) if w == "-i"]
    assert len(inputs) == 2 and all(argv[i - 4] == "-threads" and argv[i - 3] == "1" and argv[i - 2] == "-t" for i in inputs)
    assert argv[inputs[0] - 1] == "%.6f" % (edl["out_frames"] / 30.0) and argv[inputs[1] - 1] == "%.6f" % (60 / 30.0)
    assert argv[argv.index("-frames:v") + 1] == str(edl["out_frames"]) and argv[argv.index("-sws_flags") + 1] == _media.SWS
    assert argv.count("-map") == 1 and argv[-3:] == ["-f", "null", "-"]
    graph = argv[argv.index("-filter_complex") + 1]
    assert graph.count("psnr=") == 2 and "stats_file=psnr-0.log" in graph and "stats_file=psnr-1.log" in graph and graph.count("nullsink") == 1
    assert argv[argv.index("-map") + 1] == "[p1]" and "[p0]nullsink" in graph          # the last range's comparison is the one output: it ends last
    assert "/in/" not in graph and "[1:v:0]fps=30:start_time=0,format=yuv420p[sv]" in graph and "concat=n=2:v=1:a=0[cv]" in graph


def test_the_pixel_check_is_one_command_per_range_with_no_split_each_input_seeked_and_bounded_and_the_frames_exact():
    edl = small_edl(kept=((0, 20), (30, 60), (90, 100)))
    faces = ranges_of(edl)
    for k, (first, last, _box) in enumerate(faces):
        argv = G.pixel_argv_range("ffmpeg", "/in/hf.mov", "/in/proxy.mp4", edl, DATA, faces, k)
        graph = argv[argv.index("-filter_complex") + 1]
        a, b = edl["kept"][k]
        assert "split" not in graph and "nullsink" not in graph and "-shortest" not in argv
        assert graph.count("psnr=") == 1 and "stats_file=psnr-%d.log" % k in graph and "concat=n=1:v=1:a=0[cv]" in graph
        assert argv[argv.index("-filter_threads") + 1] == "1" and argv[argv.index("-filter_complex_threads") + 1] == "1"
        inputs = [i for i, w in enumerate(argv) if w == "-i"]
        assert len(inputs) == 2 and argv[inputs[0] + 1] == "/in/hf.mov" and argv[inputs[1] + 1] == "/in/proxy.mp4"
        for i, (start, length) in zip(inputs, ((first, last - first), (a, b - a))):                  # -ss and -t come before -i, so each input is seeked and bounded
            assert argv[i - 6:i - 4] == ["-threads", "1"] and argv[i - 4] == "-ss" and argv[i - 3] == "%.6f" % (start / 30.0)
            assert argv[i - 2] == "-t" and argv[i - 1] == "%.6f" % (length / 30.0)
        assert argv[argv.index("-frames:v") + 1] == str(last - first) and argv[argv.index("-map") + 1] == "[p]" and argv[-3:] == ["-f", "null", "-"]
        assert "trim=start_frame=0:end_frame=%d" % (last - first) in graph and "[1:v:0]fps=30:start_time=0,format=yuv420p[sv]" in graph


def test_the_pixel_check_runs_the_runner_once_per_range_and_reads_one_stats_file_per_range(tmp_path):
    edl = small_edl(kept=((0, 20), (30, 60), (90, 100)))
    calls = []

    def fake_run(argv, timeout, cwd=None):
        graph = argv[argv.index("-filter_complex") + 1]
        k = int(graph.split("stats_file=psnr-")[1].split(".log")[0])
        calls.append(k)
        n = edl["kept"][k][1] - edl["kept"][k][0]
        (Path(cwd) / ("psnr-%d.log" % k)).write_text("".join("n:%d mse_avg:1 psnr_avg:%s psnr_y:1\n" % (i + 1, 40 + k) for i in range(n)))
        return "", ""

    assert G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), run=fake_run) == {"pixel_min_psnr_db": 40.0, "pixel_ranges": 3}
    assert calls == [0, 1, 2]                                    # in order, one after another: the memory of a check is that of one range, whatever their number


def test_the_pixel_check_gives_the_reference_the_punches_and_the_grades_of_the_timeline_and_crops_the_union_of_the_faces(tmp_path):
    edl = small_edl(kept=((0, 20), (30, 60), (90, 100)))
    faces = ranges_of(edl)
    anchor = _media.anchor_point(edl["face_box"], edl["zoom"]["anchor_y"])
    punched = _media.zoomed_box(edl["face_box"], 1.2, 1.2, anchor, 1080, 1920)
    timeline = {"captions": [], "beats": [],
                "punches": [{"id": "p1", "start_frame": 25, "end_frame": 40, "range": 1, "zoom": 1.2, "face": punched}],
                "grades": [{"id": "e1", "kind": "flash", "start_frame": 3, "end_frame": 5, "range": 0, "alphas": [0.8, 0.4]}]}
    seen = {}

    def fake_run(argv, timeout, cwd=None):
        graph = argv[argv.index("-filter_complex") + 1]
        k = int(graph.split("stats_file=psnr-")[1].split(".log")[0])
        seen[k] = (graph, [w for w in argv if w.startswith("crop") or "crop=" in w])
        n = edl["kept"][k][1] - edl["kept"][k][0]
        (Path(cwd) / ("psnr-%d.log" % k)).write_text("".join("n:%d mse_avg:1 psnr_avg:40 psnr_y:1\n" % (i + 1) for i in range(n)))
        return "", ""

    assert G.pixel_check("ffmpeg", "a", "b", edl, DATA, faces, str(tmp_path), run=fake_run, timeline=timeline)["pixel_ranges"] == 3
    assert "lutyuv=y='val*(1-0.800)+235.00*0.800'" in seen[0][0] and "enable='eq(n,3)'" in seen[0][0] and "between(on" not in seen[0][0]
    assert "1/(if(between(on-1,5,19),1.20000," in seen[1][0]            # in the range's own frame index: output frames 25 to 39 of a range that starts at 20
    plain = G.punched_faces(faces, {"punches": []})
    wide = G.punched_faces(faces, timeline)
    assert plain is faces and wide[1][2]["h"] >= faces[1][2]["h"] and wide[1][2]["w"] >= faces[1][2]["w"] and wide[0][2] == faces[0][2] and wide[2][2] == faces[2][2]
    assert wide[1][2] == _edl.union([faces[1][2], punched])


def test_a_range_made_alone_keeps_the_zoom_level_of_its_number_in_the_list():
    zoom = {"mode": "alternate", "factor": 1.15, "push_in": 0.0, "anchor_y": 0.25}
    edl = small_edl(kept=((0, 20), (30, 60), (90, 100)), zoom=zoom)
    whole = G.reference_graph(edl, DATA, "[1:v:0]")
    ax, ay = _media.anchor_point(edl["face_box"], 0.25)
    zoomed = "perspective=x0='%.2f*(1-1/1.15000)'" % ax
    assert zoomed in ";".join(whole) and sum(zoomed in line for line in whole) == 1                  # only range 1 of the whole list is zoomed
    assert not any(zoomed in line for line in G.reference_graph(edl, DATA, "[1:v:0]", only=0))
    assert any(zoomed in line for line in G.reference_graph(edl, DATA, "[1:v:0]", only=1))
    assert not any(zoomed in line for line in G.reference_graph(edl, DATA, "[1:v:0]", only=2))
    alone = G.reference_graph(edl, DATA, "[1:v:0]", only=1)
    assert "trim=start_frame=0:end_frame=30" in ";".join(alone) and "concat=n=1:v=1:a=0[cv]" in alone[-1]


def test_base_graph_with_the_default_first_index_is_the_graph_it_was_and_first_index_moves_only_the_zoom_numbers():
    plan = {"fps": 30, "size": [1080, 1920], "src_matrix": "bt709", "kept": [[0, 10], [20, 40]], "has_audio": False, "fade": 0.01, "anchor": (540.0, 850.0),
            "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.0, "anchor_y": 0.25}}
    assert _media.base_graph(plan) == _media.base_graph(plan, first_index=0)
    shifted = _media.base_graph(plan, first_index=1)
    plain = _media.base_graph(plan)
    assert shifted != plain and [s for s in shifted if "trim=" not in s] == [s for s in plain if "trim=" not in s]
    alone = _media.base_graph(dict(plan, kept=[[20, 40]]), first_index=1)
    assert alone[1] == plain[3].replace("[s1]", "[sv]").replace("[v1]", "[v0]")                  # range 1 made alone is range 1 of the list


def test_the_reference_is_the_proxy_cut_and_zoomed_by_the_one_base_graph_with_each_zoom_sampled_bilinearly_at_exact_positions():
    edl = small_edl(zoom={"mode": "alternate", "factor": 1.15, "push_in": 0.0, "anchor_y": 0.25})
    graph = ";".join(G.reference_graph(edl, DATA, "[1:v:0]"))
    ax, ay = _media.anchor_point(edl["face_box"], 0.25)
    assert "perspective=x0='%.2f*(1-1/1.15000)':y0='%.2f*(1-1/1.15000)'" % (ax, ay) in graph and "interpolation=linear:eval=frame:sense=source" in graph
    assert "zoompan" not in graph and graph.count("perspective=") == 1 and "scale=1080:1920:flags=%s" % _media.SWS in graph     # the unzoomed range is the proxy as it is
    pushed = _media.zoom_filter_linear(1.0, 1.02, 120, (540.0, 850.0), 1080, 1920)
    assert "(1.00000+0.000168*on)" in pushed and _media.zoom_filter_linear(1.0, 1.0, 120, (540.0, 850.0), 1080, 1920).startswith("scale=1080:1920")


def test_the_base_graph_is_what_compose_argv_builds_its_picture_from():
    plan = {"src": "in.mp4", "has_audio": True, "fps": 30, "size": [1080, 1920], "src_matrix": "bt709", "kept": [[0, 10], [20, 40]], "layers": [], "pips": [],
            "out_frames": 30, "max_bytes": 10 ** 8, "out_name": "o.mp4", "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.0, "anchor_y": 0.25},
            "face": dict(FACE, cx=540, cy=1000), "fade": 0.01, "anchor": (540.0, 850.0)}
    argv = _media.compose_argv("ffmpeg", plan)
    graph = argv[argv.index("-filter_complex") + 1]
    assert graph.startswith(";".join(_media.base_graph(plan)))


@pytest.mark.parametrize("box_, expect", [({"x": 301, "y": 701, "w": 480, "h": 600}, (480, 600, 300, 700)), ({"x": -5, "y": -5, "w": 100, "h": 100}, (94, 94, 0, 0)),
                                           ({"x": 1000, "y": 1800, "w": 200, "h": 300}, (80, 120, 1000, 1800))])
def test_the_face_region_is_cropped_on_even_coordinates_inside_the_frame(box_, expect):
    assert G.crop_box(box_, 1080, 1920) == expect


def test_a_face_region_under_two_pixels_is_refused():
    assert code_of(G.crop_box, {"x": 0, "y": 0, "w": 1, "h": 100}, 1080, 1920)[0] == "face_box_leaves_no_room"


def test_the_stats_of_a_range_are_read_with_inf_capped_and_one_figure_per_frame(tmp_path):
    path = tmp_path / "psnr-0.log"
    path.write_text("n:1 mse_avg:0.00 mse_y:0.00 mse_u:0.00 mse_v:0.00 psnr_avg:inf psnr_y:inf psnr_u:inf psnr_v:inf\n"
                    "n:2 mse_avg:1.50 mse_y:1.00 mse_u:2.00 mse_v:2.00 psnr_avg:46.37 psnr_y:48.13 psnr_u:44.2 psnr_v:44.2\n")
    assert G.read_stats(str(path), 2) == [G.PSNR_CAP, 46.37]
    assert code_of(G.read_stats, str(path), 3)[0] == "pixel_check_failed"
    path.write_text("n:1 something else\n")
    assert code_of(G.read_stats, str(path), 1)[0] == "pixel_check_failed"
    assert code_of(G.read_stats, str(tmp_path / "missing.log"), 1)[0] == "pixel_check_failed"


def test_the_judgement_gives_the_figure_and_the_range_as_advice_and_the_minimum_is_over_all(tmp_path):
    edl = small_edl()

    def fake_run(argv, timeout, cwd=None):
        (Path(cwd) / "psnr-0.log").write_text("".join("n:%d mse_avg:1 mse_y:1 mse_u:1 mse_v:1 psnr_avg:%s psnr_y:1 psnr_u:1 psnr_v:1\n" % (i + 1, v)
                                                      for i, v in enumerate(["45.0"] * 20)))
        (Path(cwd) / "psnr-1.log").write_text("".join("n:%d mse_avg:1 mse_y:1 mse_u:1 mse_v:1 psnr_avg:%s psnr_y:1 psnr_u:1 psnr_v:1\n" % (i + 1, v)
                                                      for i, v in enumerate(["50.0"] * 5 + ["31.2"] + ["50.0"] * 24)))
        return "", ""

    assert G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), run=fake_run) == {"pixel_min_psnr_db": 31.2, "pixel_ranges": 2}
    assert G.PIXEL_MIN_PSNR_DB == 30.0

    def under(argv, timeout, cwd=None):
        fake_run(argv, timeout, cwd)
        (Path(cwd) / "psnr-1.log").write_text("".join("n:%d mse_avg:1 mse_y:1 mse_u:1 mse_v:1 psnr_avg:%s psnr_y:1 psnr_u:1 psnr_v:1\n" % (i + 1, v)
                                                      for i, v in enumerate(["50.0"] * 7 + ["29.94"] + ["50.0"] * 22)))

    got = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), under)
    assert got == {"pixel_min_psnr_db": 29.94, "pixel_ranges": 2, "advice": [{"code": "face_pixels_changed", "value": 29.94, "default": 30, "count": 1, "ids": ["r1"]}]}


# ---------------------------------------------------------------- the pixel check on real pixels (host ffmpeg)

@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """A proxy (testsrc2, 1080x1920, 60 frames) and, for two edit lists, the clean intermediate: the proxy cut and zoomed by the one base graph."""
    folder = tmp_path_factory.mktemp("pixels")
    proxy = folder / "proxy.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", proxy)
    return folder, proxy


def clean_intermediate(folder, proxy, edl, name, extra_filter=""):
    out = folder / name
    graph = ";".join(G.reference_graph(edl, DATA, "[0:v:0]"))
    tail = "[cv]%sformat=yuv422p10le[o]" % (extra_filter + "," if extra_filter else "")
    ffmpeg("-i", proxy, "-filter_complex", graph + ";" + tail, "-map", "[o]", "-c:v", "prores_ks", "-profile:v", "3", "-frames:v", edl["out_frames"], out)
    return out


@needs_ffmpeg
@pytest.mark.parametrize("zoom", [{"mode": "none", "factor": 1.0, "push_in": 0.0, "anchor_y": 0.25}, {"mode": "alternate", "factor": 1.15, "push_in": 0.0, "anchor_y": 0.25}])
def test_the_undrawn_base_passes_and_the_figures_are_the_same_at_two_runs(clip, tmp_path, zoom):
    folder, proxy = clip
    edl = small_edl(zoom=zoom)
    mov = clean_intermediate(folder, proxy, edl, "clean-%s.mov" % zoom["mode"])
    results = []
    for run in ("one", "two"):
        work = tmp_path / run
        work.mkdir()
        results.append(G.pixel_check(K.FFMPEG, str(mov), str(proxy), edl, DATA, ranges_of(edl), str(work)))
        assert sorted(os.listdir(work)) == ["psnr-0.log", "psnr-1.log"]
    assert results[0] == results[1] and results[0]["pixel_ranges"] == 2 and results[0]["pixel_min_psnr_db"] >= 40.0


@needs_ffmpeg
def test_a_box_drawn_on_the_face_region_with_no_dom_box_is_advice_from_the_pixels(clip, tmp_path):
    folder, proxy = clip
    edl = small_edl()
    drawn = clean_intermediate(folder, proxy, edl, "drawn.mov", extra_filter="drawbox=x=400:y=900:w=120:h=120:color=red@1:t=fill:enable='gte(n,25)'")
    work = tmp_path / "w"
    work.mkdir()
    got = G.pixel_check(K.FFMPEG, str(drawn), str(proxy), edl, DATA, ranges_of(edl), str(work))
    row = got["advice"][0]
    assert row["code"] == "face_pixels_changed" and row["ids"] == ["r1"] and row["value"] < 27.0 and row["default"] == 30 and got["pixel_min_psnr_db"] == row["value"]


@needs_ffmpeg
def test_a_box_outside_the_face_region_is_not_what_the_pixel_check_looks_at(clip, tmp_path):
    folder, proxy = clip
    edl = small_edl()
    elsewhere = clean_intermediate(folder, proxy, edl, "elsewhere.mov", extra_filter="drawbox=x=0:y=0:w=200:h=200:color=red@1:t=fill")
    work = tmp_path / "w"
    work.mkdir()
    assert G.pixel_check(K.FFMPEG, str(elsewhere), str(proxy), edl, DATA, ranges_of(edl), str(work))["pixel_min_psnr_db"] >= 40.0


@needs_ffmpeg
def test_the_reference_of_a_pushed_in_range_stays_within_30_db_of_a_smooth_zoom_made_at_four_times_the_size(clip, tmp_path):
    """The renderer's zoom is smooth: the stand-in is the same zoom made at four times the size and brought down by area (the measured minimum is 34.5 dB;
    the first references, zoompan on the proxy and zoompan at twice the size, were at 26 and 30 against a bilinear stand-in)."""
    folder, proxy = clip
    edl = small_edl(kept=((0, 60),))
    z1 = 1.05                                                                  # a push-in is made by hand: the clip is under the five seconds that earn one
    ax, ay = _media.anchor_point(edl["face_box"], 0.25)
    ideal = folder / "ideal.mov"
    ffmpeg("-i", proxy, "-vf", "scale=4320:7680:flags=lanczos,zoompan=z='1+%s*on/59':x='%.2f*(1-1/zoom)':y='%.2f*(1-1/zoom)':d=1:s=4320x7680:fps=30,scale=1080:1920:flags=area,format=yuv422p10le" % (z1 - 1, ax * 4, ay * 4),
           "-c:v", "prores_ks", "-profile:v", "3", "-frames:v", 60, ideal)
    reference = folder / "reference.mov"
    graph = "[0:v:0]fps=30:start_time=0,format=yuv420p,%s,format=yuv422p10le" % _media.zoom_filter_linear(1.0, z1, 60, (ax, ay), 1080, 1920)
    ffmpeg("-i", proxy, "-vf", graph.split("]", 1)[1], "-c:v", "prores_ks", "-profile:v", "3", "-frames:v", 60, reference)
    done = subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", ideal, "-i", reference, "-lavfi", "[0:v]crop=480:600:300:700,format=yuv420p[a];[1:v]crop=480:600:300:700,format=yuv420p[b];[a][b]psnr=stats_file=%s" % (tmp_path / "s.log"), "-f", "null", "-"],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-300:]
    assert min(float(line.split("psnr_avg:")[1].split()[0]) for line in (tmp_path / "s.log").read_text().splitlines()) >= 30.0


def test_the_explanation_of_a_range_under_the_threshold_names_the_range_the_worst_frame_the_count_the_median_the_zoom_and_what_is_drawn(tmp_path):
    edl = small_edl(zoom={"mode": "alternate", "factor": 1.15, "push_in": 0.0, "anchor_y": 0.25})
    timeline = {"captions": [{"start_frame": 0, "end_frame": 20}], "beats": [{"start_frame": 5, "end_frame": 8, "preset": "keyword"}, {"start_frame": 6, "end_frame": 12, "preset": "quote"}]}

    def run(argv, timeout, cwd=None):
        (Path(cwd) / "psnr-0.log").write_text("".join("n:%d mse_avg:1 psnr_avg:%s psnr_y:1 \n" % (i + 1, v) for i, v in enumerate(["45.0"] * 6 + ["24.6", "29.0"] + ["45.0"] * 12)))
        (Path(cwd) / "psnr-1.log").write_text("".join("n:%d mse_avg:1 psnr_avg:45.0 psnr_y:1 \n" % (i + 1) for i in range(30)))
        return "", ""

    got = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), run, timeline)
    assert got["advice"] == [{"code": "face_pixels_changed", "value": 24.6, "default": 30, "count": 1, "ids": ["r0"]}]
    values = [45.0] * 6 + [24.6, 29.0] + [45.0] * 12
    problems = G.explain(0, edl, 0, 20, values, 6, timeline)
    rows = {p["code"]: p["field"] for p in problems if p["code"] != "entry"}
    assert rows == {"range_frames": "first 0 last 19", "worst_offset": "offset 6 of 20", "frames_under": "under 2 of 20", "under_at": "under_at 6-7", "median": "median 45.0",
                    "zoom": "zoom 1.0000 to 1.0000", "drawn_at_worst": "drawn caption keyword quote"}
    assert [p["field"] for p in problems if p["code"] == "entry"] == ["caption 0 to 20", "keyword 5 to 8", "quote 6 to 12"]
    assert all(p["beat"] is None and len(p["field"]) <= 80 and G.FIELD_OK.fullmatch(p["field"]) for p in problems)


# ---------------------------------------------------------------- the encode verb with the gates

@pytest.fixture(scope="module")
def gated(tmp_path_factory, docs):
    """The fictional post's edit list and beats, a proxy long enough for its cuts, and the clean intermediate (the proxy cut and zoomed by the base
    graph, with a tone for the audio the edit list says it has)."""
    data, edl, beats, vocab = copy.deepcopy(docs)
    folder = tmp_path_factory.mktemp("gated")
    seconds = edl["source"]["duration"] + 1
    proxy = folder / "proxy.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=%d:duration=%s" % (edl["fps"], seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", proxy)
    graph = ";".join(G.reference_graph(edl, data, "[0:v:0]"))
    mov = folder / "hf.mov"
    ffmpeg("-i", proxy, "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000", "-filter_complex", graph + ";[cv]format=yuv422p10le[o]", "-map", "[o]", "-map", "1:a",
           "-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le", "-frames:v", edl["out_frames"], "-t", "%.6f" % (edl["out_frames"] / float(edl["fps"])), mov)
    K.write_json(folder / "edl.json", edl)
    K.write_json(folder / "beats.json", beats)
    return folder, proxy, mov, edl


def clean_doc(folder, edl) -> dict:
    """The boxes of a clean render: one caption glyph box of area, in the caption band, on the first frame of every caption entry (the rule of V3c
    refuses a caption that draws nothing), and nothing else."""
    beats = json.loads((folder / "beats.json").read_text())
    timeline = _edl.resolve_timeline(copy.deepcopy(edl), beats, load_vocabulary(str(K.VOCABULARY)), DATA)
    return boxes_doc(edl["out_frames"], {e["start_frame"]: [box("caption", y=1450.0, h=40.0, glyph=True, key="oh:caption")] for e in timeline["captions"]}), len(timeline["captions"])


def left_over(out: Path) -> list:
    """What a refused encode left in its output folder: nothing (the folder may not exist at all)."""
    return sorted(os.listdir(out)) if out.exists() else []


def encode_args(folder, proxy, mov, out, doc, *, boxes_sha=None, proxy_sha=None, drop=None):
    boxes_path, digest = write_boxes(folder, doc)
    flags = {"--boxes": boxes_path, "--boxes-sha256": boxes_sha or digest, "--beats": folder / "beats.json", "--vocabulary": K.VOCABULARY,
             "--proxy": proxy, "--proxy-sha256": proxy_sha or sha(Path(proxy).read_bytes())}
    for key in drop or ():
        del flags[key]
    argv = ["--in", mov, "--sha256", sha(Path(mov).read_bytes()), "--edl", folder / "edl.json", "--platform-file", K.INSTAGRAM, "--out", out]
    for key, value in flags.items():
        argv += [key, value]
    return argv


@needs_ffmpeg
def test_a_clean_composed_encode_writes_one_file_and_reports_the_gates(gated, tmp_path):
    folder, proxy, mov, edl = gated
    doc, captions = clean_doc(folder, edl)
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", doc))
    assert rc == 0, err
    clean = D.sanitise(out, D.RESULT_SCHEMAS["encode"], "encode")
    assert clean["gate_frames"] == edl["out_frames"] and clean["gate_boxes"] == captions and clean["lowest_caption_bottom"] == 1490.0
    assert clean["pixel_ranges"] == len(edl["kept"]) and clean["pixel_min_psnr_db"] >= 40.0 and clean["pixel_seconds"] >= 0
    assert sorted(os.listdir(tmp_path / "out")) == ["render-%s.mp4" % clean["sha256"][:12]]


@needs_ffmpeg
def test_the_encode_without_the_gates_flags_is_the_base_only_path_and_reports_none(gated, tmp_path):
    folder, proxy, mov, edl = gated
    rc, out, err = K.run_verb("encode", "--in", mov, "--sha256", sha(Path(mov).read_bytes()), "--edl", folder / "edl.json", "--platform-file", K.INSTAGRAM,
                              "--out", tmp_path / "out")
    assert rc == 0, err
    assert not {"gate_frames", "gate_boxes", "pixel_min_psnr_db", "pixel_ranges", "pixel_seconds", "lowest_caption_bottom"} & set(out)


@needs_ffmpeg
@pytest.mark.parametrize("drop", [["--boxes"], ["--boxes-sha256"], ["--beats"], ["--vocabulary"], ["--proxy"], ["--proxy-sha256"],
                                  ["--boxes", "--boxes-sha256", "--beats"]])
def test_some_of_the_gates_flags_without_the_others_is_a_usage_error_and_writes_nothing(gated, tmp_path, drop):
    folder, proxy, mov, edl = gated
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", boxes_doc(edl["out_frames"]), drop=drop))
    assert rc == 2 and "together" in err and not (tmp_path / "out").exists()


@needs_ffmpeg
def test_neither_a_box_on_the_face_nor_the_line_stops_the_encode_the_line_is_advice(gated, tmp_path):
    folder, proxy, mov, edl = gated
    data = load_data()
    face = _edl.range_faces(edl, data)[0][2]
    doc, _ = clean_doc(folder, edl)
    doc["per_frame"][0].append(box("card", x=face["x"] + 5, y=face["y"] + 5, w=80.0, h=80.0, key="hf-inst-1"))
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", doc))
    assert rc == 0, err
    low = boxes_doc(edl["out_frames"], {0: [box("caption", y=1540.0, h=40.0, key="hf-inst-1", glyph=True)]})
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out2", low))
    assert rc == 0, err
    assert ("caption_below_line", 1580) in [(r["code"], r["value"]) for r in out["advice"]] and out["lowest_caption_bottom"] == 1580.0      # the other captions draw no glyph: advice too


@needs_ffmpeg
def test_a_caption_below_1560_does_not_stop_the_encode_and_is_reported(gated, tmp_path):
    folder, proxy, mov, edl = gated
    doc = boxes_doc(edl["out_frames"], {3: [box("caption", y=1545.0, h=35.0, glyph=True, key="caption")]})
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", doc))
    assert rc == 0, err
    assert ("caption_below_line", 1580) in [(r["code"], r["value"]) for r in out["advice"]] and len(left_over(tmp_path / "out")) == 1


@needs_ffmpeg
@pytest.mark.parametrize("what, code", [("boxes_sha", "boxes_changed"), ("proxy_sha", "proxy_changed")])
def test_a_boxes_file_or_a_proxy_that_is_not_the_one_named_is_refused(gated, tmp_path, what, code):
    folder, proxy, mov, edl = gated
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", boxes_doc(edl["out_frames"]), **{what: "0" * 64}))
    assert rc == 1 and out["code"] == code and left_over(tmp_path / "out") == []


@needs_ffmpeg
def test_a_proxy_shorter_than_the_cuts_need_is_refused_before_anything_is_compared(gated, tmp_path):
    folder, proxy, mov, edl = gated
    short = folder / "short.mp4"
    ffmpeg("-i", proxy, "-t", "0.5", "-c", "copy", short)
    rc, out, err = K.run_verb("encode", *encode_args(folder, short, mov, tmp_path / "out", boxes_doc(edl["out_frames"])))
    assert rc == 1 and (out["code"], out["field"]) == ("proxy_truncated", "proxy") and left_over(tmp_path / "out") == []


@needs_ffmpeg
def test_boxes_for_another_length_than_the_edit_lists_stop_the_encode(gated, tmp_path):
    folder, proxy, mov, edl = gated
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", boxes_doc(edl["out_frames"] - 1)))
    assert rc == 1 and out["code"] == "boxes_frames_differ"


@needs_ffmpeg
def test_a_drawing_on_the_face_that_no_box_reports_is_advice_from_the_pixels_and_the_encode_writes_its_file(gated, tmp_path):
    folder, proxy, mov, edl = gated
    face = _edl.range_faces(edl, load_data())[0][2]
    drawn = folder / "drawn.mov"
    ffmpeg("-i", mov, "-vf", "drawbox=x=%d:y=%d:w=100:h=100:color=red@1:t=fill:enable='gte(n,0)'" % (face["x"] + 40, face["y"] + 40), "-c:v", "prores_ks", "-profile:v", "3",
           "-c:a", "copy", drawn)
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, drawn, tmp_path / "out", clean_doc(folder, edl)[0]))
    assert rc == 0, err
    assert out["advice"][0]["code"] == "face_pixels_changed" and out["advice"][0]["ids"][0] == "r0" and len(left_over(tmp_path / "out")) == 1


# ---------------------------------------------------------------- the planted blocks of the live tests (never committed)

@pytest.mark.parametrize("which, name", [("demo-cover", "hf:demo-cover"), ("demo-low", "hf:demo-low")])
def test_the_planted_blocks_of_the_live_tests_are_valid_blocks_that_the_composer_draws_with_gsap(docs, tmp_path, which, name):
    folder = K.planted_blocks(tmp_path, which)
    catalogue = _blocks.load_catalogue(str(folder))
    data, edl, beats, vocab = copy.deepcopy(docs)
    out = tmp_path / "page"
    out.mkdir()
    result = _hf_compose.write_page(data, edl, beats, vocab, catalogue, str(out), edl["fps"])
    assert result["runtimes"][name] == "gsap" and name in result["blocks"]
    page = (out / "index.html").read_text()
    assert 'data-hf-block="%s"' % name in page and 'data-hf-zone="%s"' % ("caption" if which == "demo-low" else "card") in page


# ---------------------------------------------------------------- the schema and the module

def test_the_encode_result_schema_carries_the_gate_figures_as_optional_fields():
    keys = D.RESULT_SCHEMAS["encode"][1]
    assert {"gate_frames", "gate_boxes", "lowest_caption_bottom", "pixel_min_psnr_db", "pixel_ranges", "pixel_seconds"} <= set(keys)
    base = D.sanitise({"ok": True, "sha256": "a" * 64, "out_seconds": 1.0, "out_frames": 30, "intermediate_sha256": "b" * 64}, D.RESULT_SCHEMAS["encode"], "encode")
    assert set(base) == {"ok", "sha256", "out_seconds", "out_frames", "intermediate_sha256"}


def test_no_environment_variable_and_no_flag_turns_the_gates_off():
    source = (K.RENDERER / "_hf_gate.py").read_text()
    inner = (K.RENDERER / "_inner.py").read_text()
    assert "os.environ" not in source and "getenv" not in source and "os.environ" not in inner.split("def encode_gate")[1].split("def verb_hf_page")[0]
    gate_flags = [w for w in ("--boxes", "--boxes-sha256", "--beats", "--vocabulary", "--proxy", "--proxy-sha256") if '"%s"' % w in inner]
    assert len(gate_flags) == 6 and "--no-gate" not in inner and "--skip" not in inner


# ---------------------------------------------------------------- decision 6: the face gate, loosened only inside the cut (package V9b-2)

CUT_FIRST, CUT_END = 30, 61                      # a cutaway entry on frames 30 to 60 (the end is exclusive)


@pytest.fixture(scope="module")
def cut_catalogue():
    return _blocks.load_catalogue()


def with_cutaway(docs, block=None, start=CUT_FIRST, end=CUT_END):
    """(data, edl, timeline, ranges) of the kit's post with one more beat entry: a cutaway on frames `start` to `end - 1`, drawn by `block` (the engine's
    default for the preset when None)."""
    data, edl, timeline, ranges = timeline_of(docs)
    entry = {"id": "bcut", "preset": "cutaway", "kind": "layout", "start_frame": start, "end_frame": end, "face": dict(ranges[0][2]),
             "params": {"asset": "slot-1", "fit": "cover"}}
    if block:
        entry["block"] = block
    timeline["beats"] = timeline["beats"] + [entry]
    return data, edl, timeline, ranges


def frame_box(**kwargs):
    return box("frame", **dict({"x": 0.0, "y": 0.0, "w": 1080.0, "h": 1920.0, "key": "oh:cutaway"}, **kwargs))


def checked_with(docs, cut_catalogue, per_frame, block=None, catalogue=None, **kwargs):
    data, edl, timeline, ranges = with_cutaway(docs, block, **kwargs)
    return check_without_the_glyph_rule(boxes_doc(edl["out_frames"], per_frame), timeline, ranges, data)


def test_a_frame_box_inside_a_cutaway_entry_passes_whether_or_not_it_covers_the_face(docs, cut_catalogue):
    face = timeline_of(docs)[3][0][2]
    on_face = frame_box(x=face["x"] + 10, y=face["y"] + 10, w=200.0, h=200.0)
    for frame in (CUT_FIRST, 45, CUT_END - 1):
        assert checked_with(docs, cut_catalogue, {frame: [frame_box(), on_face]})["boxes"] == 2, frame


def test_a_frame_box_one_frame_before_and_one_frame_after_the_entry_passes_too_the_box_check_has_no_span(docs, cut_catalogue):
    for frame in (CUT_FIRST - 1, CUT_END):
        assert checked_with(docs, cut_catalogue, {frame: [frame_box()]})["boxes"] == 1


def test_a_block_that_may_not_cross_the_face_opens_no_span_for_the_pixel_check_and_its_frame_box_still_passes(docs, cut_catalogue):
    closed = copy.deepcopy(cut_catalogue)
    closed["blocks"]["oh:cutaway"]["may_cross_face"] = False
    assert G.crossing_spans(with_cutaway(docs)[2], closed) == []
    assert checked_with(docs, cut_catalogue, {40: [frame_box()]}, catalogue=closed)["boxes"] == 1


def test_only_an_entry_of_the_frame_band_with_may_cross_face_opens_a_span(docs, cut_catalogue):
    data, edl, timeline, ranges = with_cutaway(docs)
    assert G.crossing_spans(timeline, cut_catalogue) == [(CUT_FIRST, CUT_END)]                  # the kit's four cards add none
    screenshot = with_cutaway(docs, block="oh:screenshot")[2]
    assert G.crossing_spans(screenshot, cut_catalogue) == [(CUT_FIRST, CUT_END)]
    card_band = copy.deepcopy(cut_catalogue)
    card_band["blocks"]["oh:cutaway"].update(band="card", may_cross_face=False)
    assert G.crossing_spans(timeline, card_band) == []
    assert G.inside([(30, 61)], 30) and G.inside([(30, 61)], 60) and not G.inside([(30, 61)], 29) and not G.inside([(30, 61)], 61) and not G.inside([], 0)


def test_a_caption_or_card_box_on_the_face_during_a_cutaway_passes_and_a_caption_below_1560_is_advice(docs, cut_catalogue):
    face = timeline_of(docs)[3][0][2]
    on_face = box("caption", x=face["x"] + 10, y=face["y"] + 10, w=100.0, h=100.0, key="oh:caption", glyph=True)
    assert checked_with(docs, cut_catalogue, {40: [on_face]})["boxes"] == 1
    assert checked_with(docs, cut_catalogue, {40: [box("caption", y=1540.0, h=40.0, glyph=True)]})["advice"][0]["value"] == 1580
    assert checked_with(docs, cut_catalogue, {45: [frame_box(), box("caption", y=1540.0, h=40.0)]})["advice"][0]["code"] == "caption_below_line"
    low_card = box("card", x=face["x"] + 10, y=face["y"] + 10, w=100.0, h=100.0)                # a card on the face too
    assert checked_with(docs, cut_catalogue, {40: [low_card]})["boxes"] == 1


def test_a_render_with_no_frame_entry_gives_the_same_gate_result_with_or_without_the_new_input(docs, cut_catalogue):
    data, edl, timeline, ranges = timeline_of(docs)
    assert G.crossing_spans(timeline, cut_catalogue) == []
    f = first_frame_without_an_entry(docs)[0]
    per = {f: [box("caption", y=1450.0, h=50.0, glyph=True)], 3: [box("card", y=data["zones"]["card_top"], h=40.0)]}
    old = check_without_the_glyph_rule(boxes_doc(edl["out_frames"], per), timeline, ranges, data)
    assert check_without_the_glyph_rule(boxes_doc(edl["out_frames"], per), timeline, ranges, data) == old


def stats_run(edl, values):
    """A `run` seam for `pixel_check`: each range's stats file has 40 dB everywhere but at the frames of `values` ({output frame: dB})."""
    def run(argv, timeout, cwd=None):
        k = int(argv[argv.index("-filter_complex") + 1].split("stats_file=psnr-")[1].split(".log")[0])
        a, b = edl["kept"][k]
        first = sum(y - x for x, y in edl["kept"][:k])
        (Path(cwd) / ("psnr-%d.log" % k)).write_text("".join("n:%d mse_avg:1 psnr_avg:%s psnr_y:1\n" % (i + 1, values.get(first + i, 40.0)) for i in range(b - a)))
        return "", ""
    return run


def test_the_pixel_check_skips_exactly_the_frames_inside_the_entry(tmp_path):
    edl = small_edl(kept=((0, 100),))
    inside_cut = {f: 12.0 for f in range(CUT_FIRST, CUT_END)}                                     # the picture covers the face: 12 dB on every frame of the entry
    spans = [(CUT_FIRST, CUT_END)]
    assert G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), stats_run(edl, inside_cut))["advice"][0]["code"] == "face_pixels_changed"
    result = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), stats_run(edl, inside_cut), crossing=spans)
    assert result == {"pixel_min_psnr_db": 40.0, "pixel_ranges": 1}
    for frame in (CUT_FIRST - 1, CUT_END):                                                         # one frame before and one after the entry are judged as ever
        values = {**inside_cut, frame: 20.0}
        got = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), stats_run(edl, values), crossing=spans)
        assert got["advice"] == [{"code": "face_pixels_changed", "value": 20, "default": 30, "count": 1, "ids": ["r0"]}]


def test_with_an_entry_of_frames_30_to_60_face_changes_at_frames_29_and_61_are_still_judged_and_reported(tmp_path):
    edl = small_edl(kept=((0, 100),))
    spans = [(30, 61)]
    for frame in (29, 61):
        run = stats_run(edl, {**{f: 12.0 for f in range(30, 61)}, frame: 28.0})
        got = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), run, crossing=spans)
        assert got["advice"] == [{"code": "face_pixels_changed", "value": 28, "default": 30, "count": 1, "ids": ["r0"]}]
    ok = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), stats_run(edl, {f: 12.0 for f in range(30, 61)}), crossing=spans)
    assert ok["pixel_min_psnr_db"] == 40.0


def test_an_entry_that_covers_a_whole_range_leaves_nothing_to_judge_and_the_figure_is_the_cap(tmp_path):
    edl = small_edl(kept=((0, 20), (30, 60)))
    values = {f: 5.0 for f in range(0, 20)}
    ok = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), stats_run(edl, values), crossing=[(0, 20)])
    assert ok == {"pixel_min_psnr_db": 40.0, "pixel_ranges": 2}
    everything = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), stats_run(edl, {f: 5.0 for f in range(50)}), crossing=[(0, 50)])
    assert everything == {"pixel_min_psnr_db": G.PSNR_CAP, "pixel_ranges": 2}


def test_a_render_with_no_frame_entry_has_the_same_pixel_result_with_or_without_the_new_input(tmp_path):
    edl = small_edl()
    run = stats_run(edl, {7: 31.2})
    plain = G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), run)
    assert plain == {"pixel_min_psnr_db": 31.2, "pixel_ranges": 2}
    assert G.pixel_check("ffmpeg", "a", "b", edl, DATA, ranges_of(edl), str(tmp_path), run, crossing=()) == plain


def test_the_gate_module_says_where_the_loosening_is_and_zones_hold_the_frame_band():
    assert G.ZONES == ("frame", "card", "caption") and G.ENGINE == "hyperframes"
    assert "decision 6" in G.__doc__ and "crossing_spans" in G.__doc__


# ---------------------------------------------------------------- the encode verb with a cutaway: the loosening end to end (package V9b-2)

CUTAWAY_ROW = {"id": "bcut", "beat": 7, "preset": "cutaway", "params": {"label": "My dashboard", "fit": "cover", "asset": "beat7"}, "word_from": 53, "word_to": 59, "score": 1.0}


@pytest.fixture(scope="module")
def gated_cutaway(tmp_path_factory, gated, docs):
    """The kit's post with a cutaway beat, and an intermediate whose every pixel is black on the frames of that entry (the picture covers the face), the
    rest being the clean render. Returns (folder, proxy, mov, edl, entry)."""
    _, proxy, _, edl = gated
    data, _, beats, vocab = copy.deepcopy(docs)
    beats["layouts"] = [dict(CUTAWAY_ROW)]
    entry = next(e for e in _edl.resolve_timeline(copy.deepcopy(edl), beats, vocab, data)["beats"] if e["id"] == "bcut")
    folder = tmp_path_factory.mktemp("gated-cutaway")
    K.write_json(folder / "edl.json", edl)
    K.write_json(folder / "beats.json", beats)
    cover = "drawbox=x=0:y=0:w=1080:h=1920:color=black:t=fill:enable='between(n,%d,%d)'" % (entry["start_frame"], entry["end_frame"] - 1)
    graph = ";".join(G.reference_graph(edl, data, "[0:v:0]"))
    mov = folder / "hf.mov"
    ffmpeg("-i", proxy, "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000", "-filter_complex", graph + ";[cv]" + cover + ",format=yuv422p10le[o]", "-map", "[o]", "-map", "1:a",
           "-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le", "-frames:v", edl["out_frames"], "-t", "%.6f" % (edl["out_frames"] / float(edl["fps"])), mov)
    return folder, proxy, mov, edl, entry


def cutaway_doc(folder, edl, entry, chip=True):
    doc, _ = clean_doc(folder, edl)
    if chip:
        doc["per_frame"][entry["start_frame"] + 2].append(box("frame", x=65.0, y=320.0, w=300.0, h=60.0, key="oh:cutaway", glyph=True))
    return doc


BLOCK_FLAGS = ["--blocks", str(K.BLOCKS), "--blocks-sha256", K.BLOCKS_SHA256]


@needs_ffmpeg
def test_with_the_blocks_a_picture_over_the_face_in_exactly_the_cutaways_frames_passes_both_gates(gated_cutaway, tmp_path):
    folder, proxy, mov, edl, entry = gated_cutaway
    doc = cutaway_doc(folder, edl, entry)
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", doc), *BLOCK_FLAGS)
    assert rc == 0, err
    clean = D.sanitise(out, D.RESULT_SCHEMAS["encode"], "encode")
    assert clean["pixel_min_psnr_db"] >= 40.0 and clean["gate_boxes"] == clean_doc(folder, edl)[1] + 1                 # the captions' glyph boxes and the chip
    assert sorted(os.listdir(tmp_path / "out")) == ["render-%s.mp4" % clean["sha256"][:12]]


@needs_ffmpeg
def test_without_the_blocks_the_same_render_reports_the_face_pixels_the_gate_is_then_stricter_never_looser(gated_cutaway, tmp_path):
    folder, proxy, mov, edl, entry = gated_cutaway
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", cutaway_doc(folder, edl, entry)))
    assert rc == 0 and out["advice"][0]["code"] == "face_pixels_changed"         # the box check has no face rule; the pixel check is the old engine's, and it reports
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out2", cutaway_doc(folder, edl, entry, chip=False)))
    assert rc == 0 and out["advice"][0]["code"] == "face_pixels_changed"


@needs_ffmpeg
def test_a_frame_box_one_frame_outside_the_entry_passes_the_box_check_with_the_blocks(gated_cutaway, tmp_path):
    folder, proxy, mov, edl, entry = gated_cutaway
    doc = cutaway_doc(folder, edl, entry, chip=False)
    doc["per_frame"][entry["end_frame"]].append(box("frame", x=65.0, y=320.0, w=300.0, h=60.0, key="oh:cutaway", glyph=True))
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", doc), *BLOCK_FLAGS)
    assert rc == 0, err


@needs_ffmpeg
def test_the_blocks_flags_are_together_and_only_with_the_gates_flags(gated, tmp_path):
    folder, proxy, mov, edl = gated
    doc = boxes_doc(edl["out_frames"])
    for extra in (["--blocks", str(K.BLOCKS)], ["--blocks-sha256", K.BLOCKS_SHA256]):
        rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out", doc), *extra)
        assert rc == 2 and "--blocks" in err and not (tmp_path / "out").exists()
    rc, out, err = K.run_verb("encode", "--in", mov, "--sha256", sha(Path(mov).read_bytes()), "--edl", folder / "edl.json", "--platform-file", K.INSTAGRAM,
                              "--out", tmp_path / "base", *BLOCK_FLAGS)
    assert rc == 2 and "only with the flags of the gate" in err and not (tmp_path / "base").exists()
    rc, out, err = K.run_verb("encode", *encode_args(folder, proxy, mov, tmp_path / "out3", doc), "--blocks", str(K.BLOCKS), "--blocks-sha256", "0" * 64)
    assert rc == 1 and out["code"] == "blocks_changed" and not (tmp_path / "out3").exists()
