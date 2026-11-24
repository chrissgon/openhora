"""The split layout (V9f): the halves, the speaker's crop, the caption band and the bar, the dropped split, the compose command, the block and its page.
V9g: a top or bottom split has a feathered seam and its caption is a chip on the seam. Every picture and recording is generated here; nothing real is used."""
from __future__ import annotations

import copy
import json
import struct
import subprocess
import zlib

import pytest

import renderer_kit as K
import _blocks
import _cdp
import _frames
import _layout
import _media
import _payload
import _render
from _lint import lint
from _text import Refusal
from _vocab import check_params, load_data, load_vocabulary

needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FACE = {"x": 240, "y": 620, "w": 600, "h": 560}
THEME_BG = "#0B0F14"
COLORS = {"bg": THEME_BG, "text": "#FFFFFF", "muted": "#A8B0BC", "accent": "#FFC93C", "chip_fill": "#1B1F2A", "chip_text": "#FFE08A", "chip_border": "#FFC93C"}
PAGE = K.BLOCKS / "oh" / "split" / "renderat.html"
Z = DATA["zones"]


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except Refusal as exc:
        return exc
    raise AssertionError("not refused")


def png(width, height, pixel) -> bytes:
    rows = [b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height)]

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def decode(data):
    """A screenshot PNG (8 bit, RGB or RGBA) as (width, height, rows of bytes, bytes per pixel)."""
    pos, idat, width = 8, b"", 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype in (2, 6)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    bpp = 4 if ctype == 6 else 3
    raw, stride, rows, prev = zlib.decompress(idat), width * bpp, [], bytearray(width * bpp)
    for y in range(height):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, rows, bpp


def at(shot, x, y):
    _, _, rows, bpp = shot
    return tuple(rows[y][x * bpp:x * bpp + 3])


def alpha(shot, x, y):
    _, _, rows, bpp = shot
    assert bpp == 4
    return rows[y][x * 4 + 3]


def pixel(video, frame, x, y):
    raw = subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", str(video), "-vf", "select=eq(n\\,%d),format=rgb24,crop=1:1:%d:%d" % (frame, x, y),
                          "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return tuple(raw[:3])


HALVES = {"top": ({"x": 0, "y": 0, "w": 1080, "h": 960}, {"x": 0, "y": 960, "w": 1080, "h": 960}),
          "bottom": ({"x": 0, "y": 960, "w": 1080, "h": 960}, {"x": 0, "y": 0, "w": 1080, "h": 960}),
          "left": ({"x": 0, "y": 0, "w": 540, "h": 1920}, {"x": 540, "y": 0, "w": 540, "h": 1920}),
          "right": ({"x": 540, "y": 0, "w": 540, "h": 1920}, {"x": 0, "y": 0, "w": 540, "h": 1920})}
SIDES = ("top", "bottom", "left", "right")


def test_the_values_are_in_the_presets_file():
    assert {k: v for k, v in DATA["split"].items() if k != "note"} == {"bar_height": 180, "label_inset": 24, "feather_px": 100, "seam_band_height": 150}
    assert DATA["presets"]["split"] == {"anchor": "window", "min_duration": 1.5, "max_duration": None, "tail": 0.2, "settled": 0.5, "page_images": True, "looks": {}}


@pytest.mark.parametrize("side", SIDES)
def test_the_halves_of_each_side_tile_the_frame(side):
    g = _layout.split_geometry(DATA, FACE, side)
    asset, speaker = HALVES[side]
    assert g["asset"] == asset and g["speaker"] == speaker
    assert asset["w"] * asset["h"] + speaker["w"] * speaker["h"] == 1080 * 1920
    apart = (asset["x"] + asset["w"] <= speaker["x"] or speaker["x"] + speaker["w"] <= asset["x"]
             or asset["y"] + asset["h"] <= speaker["y"] or speaker["y"] + speaker["h"] <= asset["y"])
    assert apart


def test_the_speaker_crop_is_centred_on_the_face_and_kept_inside_the_frame():
    expected = {"top": ({"x": 0, "y": 420, "w": 1080, "h": 960}, {"x": 240, "y": 1160, "w": 600, "h": 560}),
                "bottom": ({"x": 0, "y": 420, "w": 1080, "h": 960}, {"x": 240, "y": 200, "w": 600, "h": 560}),
                "left": ({"x": 270, "y": 0, "w": 540, "h": 1920}, {"x": 540, "y": 620, "w": 540, "h": 560}),
                "right": ({"x": 270, "y": 0, "w": 540, "h": 1920}, {"x": 0, "y": 620, "w": 540, "h": 560})}
    for side, (crop, moved) in expected.items():
        g = _layout.split_geometry(DATA, FACE, side)
        assert g["crop"] == crop and g["moved_face"] == moved, side
        assert (g["crop"]["w"], g["crop"]["h"]) == (g["speaker"]["w"], g["speaker"]["h"])          # never scaled
        s, m = g["speaker"], g["moved_face"]
        assert s["x"] <= m["x"] and m["x"] + m["w"] <= s["x"] + s["w"] and s["y"] <= m["y"] and m["y"] + m["h"] <= s["y"] + s["h"]
    assert _layout.split_geometry(DATA, {"x": 240, "y": 40, "w": 600, "h": 400}, "bottom")["crop"]["y"] == 0
    assert _layout.split_geometry(DATA, {"x": 900, "y": 620, "w": 160, "h": 300}, "right")["crop"]["x"] == 540


BANDS = {"bottom": ([885, 1035], None), "top": ([885, 1035], None), "left": ([1198, 1378], [1198, 1378]), "right": ([1198, 1378], [1198, 1378])}
MOVED = {"top": {"x": 240, "y": 1160, "w": 600, "h": 560}, "bottom": {"x": 240, "y": 200, "w": 600, "h": 560}}


@pytest.mark.parametrize("side", SIDES)
def test_the_caption_band_straddles_the_seam_or_keeps_clear_of_both_faces(side):
    g = _layout.split_geometry(DATA, FACE, side)
    band, bar = BANDS[side]
    assert g["band"] == band and g["bar"] == bar
    lo, hi = g["band"]
    assert hi - lo >= Z["caption_min_height"] and hi <= Z["caption_bottom"] and lo >= DATA["frame"]["safe"]["top"]
    gap = Z["gap"]
    m = g["moved_face"]
    assert hi <= m["y"] - gap or lo >= m["y"] + m["h"] + gap
    if side in ("top", "bottom"):
        # V9g: a chip on the seam; the face where it was is under the picture, so only the moved face is kept clear
        assert lo < 960 < hi and hi - lo == DATA["split"]["seam_band_height"] and (lo + hi) // 2 == 960
        assert g["bar"] is None and g["seam"] is True and g["feather"] == DATA["split"]["feather_px"]
    else:
        assert hi <= FACE["y"] - gap or lo >= FACE["y"] + FACE["h"] + gap
        assert g["bar"] == g["band"] and g["band"][1] - g["band"][0] <= 180 and g["seam"] is False and g["feather"] == 0


def test_the_label_sits_in_the_picture_half_away_from_the_seam():
    # V9g: top and bottom put it in the corner away from the seam (and its caption chip): the safe top for top, the caption line for bottom
    for side, want in {"bottom": {"x": 65, "max_w": 950, "top": None, "bottom": 360}, "top": {"x": 65, "max_w": 950, "top": 285, "bottom": None},
                       "left": {"x": 65, "max_w": 451, "top": 285, "bottom": None}, "right": {"x": 564, "max_w": 451, "top": 285, "bottom": None}}.items():
        assert _layout.split_geometry(DATA, FACE, side)["label"] == want, side


def split_timeline(face=FACE, side="bottom", chunk_face=None):
    return {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": side}, "start_frame": 30, "end_frame": 90, "face": dict(face)}],
            "captions": [{"start_frame": 0, "end_frame": 20, "face": dict(chunk_face or face)}, {"start_frame": 40, "end_frame": 60, "face": dict(chunk_face or face)}],
            "dropped": []}


def test_a_split_with_no_room_for_captions_is_dropped_with_its_reason():
    low = {"x": 240, "y": 300, "w": 600, "h": 1200}          # left: the face and the moved face block every row from 282 to 1518
    tl = split_timeline(low, side="left")
    row = {"id": "b1", "reason": "split_no_room"}
    assert _layout.split_layouts(DATA, tl) == [row]
    assert tl["beats"] == [] and tl["dropped"] == ["b1"] and tl["dropped_reasons"] == [row] and not any("band" in c for c in tl["captions"])
    kept = split_timeline(low, side="left")
    assert _layout.split_layouts(DATA, kept, drop=False) == []
    assert len(kept["beats"]) == 1 and kept["beats"][0]["split"]["band"] is None and kept["dropped"] == []


def test_a_caption_during_a_split_takes_its_band_and_the_moved_face():
    tl = split_timeline(side="top")
    assert _layout.split_layouts(DATA, tl) == []
    assert "band" not in tl["captions"][0] and tl["captions"][0]["face"] == FACE and "seam" not in tl["captions"][0]
    c = tl["captions"][1]
    assert c["band"] == [885, 1035] and _layout.entry_zones(DATA, c)["caption"] == [885, 1035]
    assert c["face"] == MOVED["top"] and c["seam"] is True
    side = split_timeline(side="left")
    _layout.split_layouts(DATA, side)
    moved = side["beats"][0]["split"]["moved_face"]
    assert side["captions"][1]["face"] == _layout._union([FACE, moved]) and "seam" not in side["captions"][1]     # left: the union, as in V9f


def test_a_chunk_that_runs_past_a_top_split_takes_its_band_only_on_the_split_frames():
    # review probe P1: before the fix the whole chunk 80-120 took [285, 602] and lay over the next beat's card on frames 90-119
    tl = {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": "top"}, "start_frame": 30, "end_frame": 90, "face": dict(FACE)},
                    {"id": "b2", "preset": "keyword", "params": {"text": "Habits"}, "start_frame": 90, "end_frame": 150, "face": dict(FACE)}],
          "captions": [{"word_from": 3, "word_to": 5, "start_frame": 80, "end_frame": 120, "face": dict(FACE)}], "dropped": []}
    assert _layout.split_layouts(DATA, tl) == []
    a, b = tl["captions"]
    assert (a["start_frame"], a["end_frame"], b["start_frame"], b["end_frame"]) == (80, 90, 90, 120)
    assert a["band"] == [885, 1035] and a["face"] == MOVED["top"] and a["seam"] is True
    assert "band" not in b and b["face"] == FACE and "seam" not in b
    assert _layout.entry_zones(DATA, b)["caption"] == [1198, 1560]
    card_bottom = _layout.zones(DATA, FACE)["card"][1]
    assert _layout.entry_zones(DATA, b)["caption"][0] > card_bottom
    assert a["word_from"] == b["word_from"] == 3 and a["word_to"] == b["word_to"] == 5


def test_two_splits_back_to_back_give_each_piece_of_a_shared_chunk_its_own_band():
    # review probe P2: before the fix the chunk took the bottom split's band and a face union y 200-1720, and the render failed overlay_hits_face
    tl = {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": "top"}, "start_frame": 30, "end_frame": 90, "face": dict(FACE)},
                    {"id": "b2", "preset": "split", "params": {"asset": "s2", "side": "bottom"}, "start_frame": 90, "end_frame": 150, "face": dict(FACE)}],
          "captions": [{"word_from": 3, "word_to": 5, "start_frame": 80, "end_frame": 100, "face": dict(FACE)}], "dropped": []}
    assert _layout.split_layouts(DATA, tl) == []
    a, b = tl["captions"]
    assert (a["start_frame"], a["end_frame"], a["band"]) == (80, 90, [885, 1035])
    assert (b["start_frame"], b["end_frame"], b["band"]) == (90, 100, [885, 1035])
    assert a["face"] == MOVED["top"] and b["face"] == MOVED["bottom"]
    for piece in (a, b):
        lo, hi = piece["band"]
        f = piece["face"]
        assert hi <= f["y"] or lo >= f["y"] + f["h"]          # the caption band never meets the face the caption is checked against


def test_a_chunk_that_covers_a_short_split_is_cut_in_three():
    tl = {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": "left"}, "start_frame": 30, "end_frame": 60, "face": dict(FACE)}],
          "captions": [{"word_from": 0, "word_to": 2, "start_frame": 20, "end_frame": 70, "face": dict(FACE)}], "dropped": []}
    _layout.split_layouts(DATA, tl)
    assert [(c["start_frame"], c["end_frame"], c.get("band")) for c in tl["captions"]] == [(20, 30, None), (30, 60, [1198, 1378]), (60, 70, None)]


def test_a_pip_band_stays_on_the_pieces_outside_the_split():
    tl = {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": "top"}, "start_frame": 30, "end_frame": 90, "face": dict(FACE)}],
          "captions": [{"word_from": 0, "word_to": 2, "start_frame": 80, "end_frame": 100, "face": dict(FACE), "band": [1300, 1420]}], "dropped": []}
    _layout.split_layouts(DATA, tl)
    a, b = tl["captions"]
    assert a["band"] == [885, 1035] and b["band"] == [1300, 1420]


def test_without_a_split_the_captions_are_left_as_they_were():
    first = {"word_from": 0, "word_to": 2, "start_frame": 80, "end_frame": 120, "face": dict(FACE), "band": [1300, 1420]}
    tl = {"beats": [{"id": "b2", "preset": "keyword", "params": {"text": "Habits"}, "start_frame": 90, "end_frame": 150, "face": dict(FACE)}],
          "captions": [first], "dropped": []}
    before = copy.deepcopy(tl["captions"])
    assert _layout.split_layouts(DATA, tl) == []
    assert tl["captions"][0] is first and tl["captions"] == before


def test_a_dropped_split_cuts_no_chunk():
    low = {"x": 240, "y": 300, "w": 600, "h": 1200}
    tl = {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": "left"}, "start_frame": 30, "end_frame": 90, "face": dict(low)}],
          "captions": [{"word_from": 0, "word_to": 2, "start_frame": 20, "end_frame": 40, "face": dict(low)}], "dropped": []}
    _layout.split_layouts(DATA, tl)
    assert tl["beats"] == [] and len(tl["captions"]) == 1 and tl["captions"][0]["start_frame"] == 20 and tl["captions"][0]["end_frame"] == 40


HIGH_FACE = {"x": 220, "y": 320, "w": 380, "h": 540}      # a face in the upper half of the frame (the shape that dropped every `top` split in V9f)


def test_a_top_split_over_a_face_in_the_upper_half_is_kept_with_a_seam_band():
    g = _layout.split_geometry(DATA, HIGH_FACE, "top")
    assert g["band"] == [885, 1035] and g["moved_face"] == {"x": 220, "y": 1170, "w": 380, "h": 540}
    tl = split_timeline(HIGH_FACE, side="top")
    assert _layout.split_layouts(DATA, tl) == [] and tl["dropped"] == [] and len(tl["beats"]) == 1
    piece = tl["captions"][1]
    assert piece["band"] == [885, 1035] and piece["seam"] is True and piece["face"] == g["moved_face"]
    lo, hi = piece["band"]
    assert hi + Z["gap"] <= piece["face"]["y"]
    assert _layout.split_geometry(DATA, HIGH_FACE, "bottom")["band"] == [885, 1035]


def test_a_seam_band_that_would_meet_the_moved_face_moves_into_the_picture_half():
    big = {"x": 140, "y": 200, "w": 800, "h": 1300}           # the crop puts the face on the seam: the chip goes up into the picture
    g = _layout.split_geometry(DATA, big, "top")
    assert g["moved_face"]["y"] == 960 and g["band"] == [960 - Z["gap"] - 150, 960 - Z["gap"]]
    g = _layout.split_geometry(DATA, big, "bottom")
    assert g["moved_face"]["y"] + g["moved_face"]["h"] == 960 and g["band"] == [960 + Z["gap"], 960 + Z["gap"] + 150]


def test_the_page_geometry_carries_the_feather_and_the_caption_payload_the_seam():
    for side, feather in (("top", 100), ("bottom", 100), ("left", 0), ("right", 0)):
        assert _payload.split_geometry_of({"split": _layout.split_geometry(DATA, FACE, side)})["feather"] == feather, side
    edl = {"captions": {"position": "bottom"}}
    by_index = {3: {"index": 3, "text": "every", "start": 2.70, "end": 2.90}}
    piece = {"word_from": 3, "word_to": 3, "start_frame": 90, "end_frame": 120, "face": dict(FACE), "band": [885, 1035], "seam": True}
    out = _payload.caption_data(DATA, edl, piece, by_index, 30)
    assert out["seam"] is True and out["zones"]["caption"] == [885, 1035]
    assert "seam" not in _payload.caption_data(DATA, edl, dict(piece, seam=False), by_index, 30)


def test_a_piece_keeps_the_word_times_of_its_chunk():
    # caption_data (unchanged) takes the piece's first frame as its origin: a word said before the piece starts has a negative start
    edl = {"captions": {"position": "bottom"}}
    by_index = {3: {"index": 3, "text": "every", "start": 2.70, "end": 2.90}, 4: {"index": 4, "text": "euro", "start": 3.10, "end": 3.40}}
    piece = {"word_from": 3, "word_to": 4, "start_frame": 90, "end_frame": 120, "face": dict(FACE)}
    out = _payload.caption_data(DATA, edl, piece, by_index, 30)
    assert out["words"] == [{"text": "every", "start": -0.3, "end": -0.1}, {"text": "euro", "start": 0.1, "end": 0.4}]
    assert out["duration"] == 1.0


def test_split_rows_are_what_the_compose_plan_needs():
    tl = split_timeline(side="top")
    _layout.split_layouts(DATA, tl)
    assert _layout.split_rows(tl) == [{"start_frame": 30, "end_frame": 90, "crop": {"x": 0, "y": 420, "w": 1080, "h": 960}, "at": {"x": 0, "y": 960}}]


def test_the_render_plan_carries_the_splits(monkeypatch):
    monkeypatch.setattr(_render._edl, "range_effects", lambda edl, tl: {})
    edl = {"face_box": FACE, "zoom": {"mode": "none", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}, "fps": 30, "size": [1080, 1920],
           "source": {"has_audio": False, "color_matrix": "bt709"}, "kept": [[0, 120]], "out_frames": 120, "theme": {"colors": COLORS}}
    tl = split_timeline()
    tl.update(punches=[], grades=[])
    plan = _render.compose_plan(DATA, edl, tl, {"s1": {"kind": "png", "width": 1200, "height": 675}}, {}, "/in/rec")
    assert plan["splits"] == [{"start_frame": 30, "end_frame": 90, "crop": {"x": 0, "y": 420, "w": 1080, "h": 960}, "at": {"x": 0, "y": 0}}]
    assert plan["pips"] == []


SPLIT_ROW = {"start_frame": 30, "end_frame": 90, "crop": {"x": 0, "y": 420, "w": 1080, "h": 960}, "at": {"x": 0, "y": 0}}
PIP_ROW = {"asset": "assets/s1.png", "kind": "png", "start_frame": 30, "end_frame": 90, "x": 65, "y": 718, "w": 950, "h": 534, "radius": 24}


def plan_with(pips, splits=None):
    plan = {"src": "/in/recording", "fps": 30, "size": [1080, 1920], "has_audio": False, "src_matrix": "auto", "kept": [[0, 120]],
            "layers": ["caption"], "frames_dir": "frames", "pips": pips, "out_frames": 120, "max_bytes": 300000000, "out_name": "out.mp4",
            "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}, "face": {"cx": 540, "cy": 500, "w": 600, "h": 400},
            "anchor": (540.0, 400.0), "fade": 0.015}
    if splits is not None:
        plan["splits"] = splits
    return plan


def graph_of(argv):
    return argv[argv.index("-filter_complex") + 1]


def test_the_speaker_half_is_a_masked_crop_laid_over_the_picture():
    argv = _media.compose_argv("ffmpeg", plan_with([], [SPLIT_ROW]))
    graph = graph_of(argv)
    for part in ("[base]split=2[sb0][sk0]", "crop=1080:960:0:420", "[sc0][sm0]alphamerge[sp0]", "overlay=0:0:format=gbrp[os0]", "trim=end_frame=120"):
        assert part in graph, part
    assert "enable=" not in graph
    lav = [a for a in argv if a.startswith("color=c=black:s=1080x960:")]
    assert lav and "if(between(N,30,89),255,0)" in lav[0]


def test_a_plan_without_splits_gives_the_argv_it_always_gave():
    plain = _media.compose_argv("ffmpeg", plan_with([]))
    assert plain == _media.compose_argv("ffmpeg", plan_with([], []))
    assert plain == _media.compose_argv("ffmpeg", plan_with([], None))
    assert "split=2[sb" not in graph_of(plain)
    pipped = _media.compose_argv("ffmpeg", plan_with([PIP_ROW]))
    assert pipped == _media.compose_argv("ffmpeg", plan_with([PIP_ROW], []))
    assert "split=2[sb" not in graph_of(pipped)


def test_the_block_declares_the_presets_kind_band_and_parameters():
    cat = _blocks.load_catalogue(str(K.BLOCKS))
    block = cat["blocks"]["oh:split"]
    assert block["kind"] == "layout" and block["band"] == "frame" and block["may_cross_face"] is True
    assert block["params"] == VOCAB["presets"]["split"]["params"]
    assert "ffmpeg" in _blocks.engines_of(cat, block)
    assert cat["engines"]["ffmpeg"]["presets"]["split"] == "oh:split"
    assert "split" not in cat["engines"]["hyperframes"]["presets"]


def test_the_hyperframes_engine_refuses_a_split():
    cat = _blocks.load_catalogue(str(K.BLOCKS))
    assert refused(_blocks.resolve, cat, "hyperframes", "split", None, "beats.b1").code == "preset_not_on_engine"
    assert _blocks.resolve(cat, "ffmpeg", "split", None, "beats.b1")["name"] == "oh:split"


def test_the_renderer_side_checker_takes_a_split_and_refuses_what_the_vocabulary_refuses():
    assert check_params(VOCAB, "split", {"asset": "beat7", "side": "left"})["asset"] == "beat7"
    assert refused(check_params, VOCAB, "split", {"asset": "beat7", "side": "middle"}).code == "bad_choice"
    for bad in ("../../etc/passwd", "https://x.example/a.png", "a b", "", "Beat7", "x" * 40):
        assert refused(check_params, VOCAB, "split", {"asset": bad}).code == "bad_slot", bad
    assert refused(check_params, VOCAB, "split", {"asset": "beat7", "label": "x" * 41}).code == "text_too_long"


def test_the_page_is_clean_and_reads_only_its_parameters():
    html = PAGE.read_text(encoding="utf-8")
    assert lint(html) == []
    assert '<meta name="pv-preset" content="split">' in html and '<meta name="pv-params" content="asset,side,fit,label">' in html
    assert '<meta name="pv-looks" content="">' in html
    assert "data-zone" not in html and "maskImage" in html


# ---------------------------------------------------------------- the page, in the host's browser

def draw(tmp_path, image, side, params=None, times=(0.5,)):
    template = K.template_of("split")
    serve, _ = _frames.load_templates([template])
    serve["/assets/pic.png"] = (image, "image/png")
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "chrome"), time_limit=120) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/" + template, {"colors": COLORS, "fonts": {}, "images": {"pic": _cdp.ORIGIN + "/assets/pic.png"}})
        geom = _payload.split_geometry_of({"split": _layout.split_geometry(DATA, FACE, side)})
        payload = {"params": {"asset": "pic", "side": side, **(params or {})}, "look": {}, "zones": {}, "duration": 2.0, "geom": geom}
        for t in times:
            page.frame(t, payload)
            state = page.evaluate("JSON.stringify({box: window.__box, bar: getComputedStyle(document.getElementById('bar')).display, "
                                  "chip: (function(){var c=document.getElementById('chip'); if(!c) return null; var r=c.getBoundingClientRect();"
                                  "return {left: r.left, top: r.top, right: r.right, bottom: r.bottom};})()})")
            out.append((json.loads(state), page.screenshot()))
    return out


RED = (200, 30, 30)


@needs_browser
@pytest.mark.parametrize("side, painted, clear", [("bottom", (540, 1400), (540, 480)), ("top", (540, 480), (540, 1400)),
                                                   ("left", (270, 700), (810, 700)), ("right", (810, 700), (270, 700))])
def test_each_side_paints_the_picture_half_and_leaves_the_speaker_half_transparent(tmp_path, side, painted, clear):
    (state, shot), = draw(tmp_path, png(600, 1000, lambda x, y: RED), side)
    shot = decode(shot)
    r, g, _b = at(shot, *painted)
    assert r > 150 and g < 80
    assert alpha(shot, *painted) == 255 and alpha(shot, *clear) == 0
    assert state["box"] == HALVES[side][0]


@needs_browser
@pytest.mark.parametrize("side", SIDES)
def test_a_left_or_right_split_covers_the_caption_band_with_an_opaque_bar(tmp_path, side):
    (state, shot), = draw(tmp_path, png(600, 1000, lambda x, y: RED), side)
    shot = decode(shot)
    if side in ("left", "right"):
        for x in (270, 810):
            assert at(shot, x, 1300) == (11, 15, 20) and alpha(shot, x, 1300) == 255
        assert state["bar"] == "block"
    else:
        assert state["bar"] == "none"


@needs_browser
def test_contain_shows_the_whole_picture_with_bars_of_the_theme(tmp_path):
    (state, shot), = draw(tmp_path, png(1200, 675, lambda x, y: RED), "bottom", {"fit": "contain"})
    shot = decode(shot)
    assert at(shot, 540, 1000) == (11, 15, 20)
    r, g, _b = at(shot, 540, 1440)
    assert r > 150 and g < 80


@needs_browser
@pytest.mark.parametrize("label", ["Aster Lane", "x" * 40])
@pytest.mark.parametrize("side", SIDES)
def test_the_label_sits_in_the_picture_half_and_never_on_the_caption_band(tmp_path, side, label):
    (state, _shot), = draw(tmp_path, png(600, 1000, lambda x, y: RED), side, {"label": label})
    c, a = state["chip"], HALVES[side][0]
    assert c["left"] >= a["x"] and c["right"] <= a["x"] + a["w"] and c["top"] >= a["y"] and c["bottom"] <= a["y"] + a["h"]
    if side == "top":
        assert c["top"] == 285
    elif side == "bottom":
        assert c["bottom"] == 1560
    else:
        assert c["top"] == 285 and c["right"] <= (516 if side == "left" else 1015)
    lo, hi = BANDS[side][0]
    assert c["bottom"] <= lo or c["top"] >= hi


@needs_browser
@pytest.mark.parametrize("side", ("top", "bottom"))
def test_the_picture_fades_into_the_speaker_half_over_the_feather(tmp_path, side):
    (state, shot), = draw(tmp_path, png(600, 1000, lambda x, y: RED), side)
    shot = decode(shot)
    inside, step = (958, 1) if side == "top" else (961, -1)          # the picture's own rows at the seam: opaque
    assert alpha(shot, 540, inside) == 255
    a = [alpha(shot, 540, 960 + step * k) for k in (5, 50, 95)] if side == "top" else [alpha(shot, 540, 959 - k) for k in (5, 50, 95)]
    assert 255 > a[0] > a[1] > a[2] and 100 < a[1] < 160                 # linear: about half way at the feather's middle
    clear = 1070 if side == "top" else 849
    assert alpha(shot, 540, clear) == 0                                   # past the feather the speaker is untouched
    assert state["box"] == HALVES[side][0]


def draw_caption(tmp_path, chunk_payload):
    template = K.template_of("caption")
    serve, _ = _frames.load_templates([template])
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "chrome"), time_limit=120) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/" + template, {"colors": COLORS, "fonts": {}, "images": {}})
        result = page.frame(0.3, chunk_payload)
        return result, page.screenshot()


@needs_browser
def test_a_caption_piece_inside_a_top_split_is_a_chip_on_the_seam_clear_of_the_moved_face(tmp_path):
    tl = split_timeline(HIGH_FACE, side="top")
    tl["captions"][1].update(word_from=0, word_to=2)
    _layout.split_layouts(DATA, tl)
    piece = tl["captions"][1]
    by_index = {0: {"index": 0, "text": "Name", "start": 1.3, "end": 1.5}, 1: {"index": 1, "text": "every", "start": 1.5, "end": 1.7},
                2: {"index": 2, "text": "euro", "start": 1.7, "end": 1.9}}
    payload = _payload.caption_data(DATA, {"captions": {"position": "bottom"}}, piece, by_index, 30)
    result, shot = draw_caption(tmp_path, payload)
    boxes = [b for b in result["boxes"] if b["zone"] == "caption"]
    assert len(boxes) == 1                                                # the chip is the one measured box
    chip = boxes[0]
    assert chip["y"] < 960 < chip["y"] + chip["h"] and chip["y"] >= 885 and chip["y"] + chip["h"] <= 1035
    assert abs((chip["x"] + chip["w"] / 2) - 540) <= 1
    assert _layout.face_hit(result["boxes"], piece["face"]) is None and not _layout.caption_hit(chip, _layout.entry_zones(DATA, piece))
    shot = decode(shot)
    assert at(shot, int(chip["x"]) + 6, 960) == (255, 201, 60)           # the accent fill (#FFC93C)


@needs_browser
def test_the_same_page_and_picture_give_the_same_frame_bytes_twice(tmp_path):
    image = png(600, 1000, lambda x, y: RED if x < 300 else (40, 60, 200))
    a, = draw(tmp_path / "a", image, "left", {"label": "Aster Lane"})
    b, = draw(tmp_path / "b", image, "left", {"label": "Aster Lane"})
    assert a[1] == b[1] and a[0] == b[0]


# ---------------------------------------------------------------- the compose, with the host's ffmpeg

@needs_ffmpeg
def test_the_speaker_is_moved_into_its_half_on_the_beat_frames_only(tmp_path):
    src = tmp_path / "rec.mp4"
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=0x203040:s=1080x1920:r=30:d=4,drawbox=x=240:y=620:w=600:h=560:color=0xFA1414:t=fill", "-pix_fmt", "yuv420p", str(src)], check=True)
    plan = plan_with([], [SPLIT_ROW])
    plan.update(src=str(src), layers=[])
    argv = _media.compose_argv(K.FFMPEG, plan)
    argv[argv.index("-i") + 1] = str(src)
    out = tmp_path / "out.mp4"
    argv[-1] = str(out)
    done = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-600:]
    red = pixel(out, 60, 540, 400)
    assert red[0] > 150 and red[1] < 80                       # the moved face, rows 200-760
    assert pixel(out, 60, 540, 100)[0] < 80 and pixel(out, 60, 540, 1300)[0] < 80
    assert pixel(out, 10, 540, 400)[0] < 80 and pixel(out, 10, 540, 900)[0] > 150      # before the beat: the speaker where the recording has it
    assert pixel(out, 60, 540, 215)[0] > 150 and pixel(out, 60, 540, 185)[0] < 80      # not scaled: the box's top edge is at 200


@needs_ffmpeg
def test_the_speaker_is_moved_on_exactly_the_first_and_the_last_frame_of_the_beat(tmp_path):
    src = tmp_path / "rec.mp4"
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=0x203040:s=1080x1920:r=30:d=4,drawbox=x=240:y=620:w=600:h=560:color=0xFA1414:t=fill", "-pix_fmt", "yuv420p", str(src)], check=True)
    plan = plan_with([], [SPLIT_ROW])
    plan.update(src=str(src), layers=[])
    argv = _media.compose_argv(K.FFMPEG, plan)
    out = tmp_path / "out.mp4"
    argv[-1] = str(out)
    done = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-600:]
    # SPLIT_ROW covers frames 30..89 of one kept range; row 400 is the moved face only while the split is on
    assert pixel(out, 29, 540, 400)[0] < 80
    assert pixel(out, 30, 540, 400)[0] > 150
    assert pixel(out, 89, 540, 400)[0] > 150
    assert pixel(out, 90, 540, 400)[0] < 80
