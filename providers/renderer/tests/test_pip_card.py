"""The pip as an image card over the speaker (V9e): the speaker stays full frame, the asset sits whole in a rounded card below the face,
the captions take the band the card leaves, and a pip with no room is dropped with its reason. Every picture is generated here (flat zlib
PNGs, a clip made by the host's ffmpeg); no real image or recording is used."""
from __future__ import annotations

import copy
import json
import os
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

import renderer_kit as K
import _cdp
import _docker
import _frames
import _layout
import _lint
import _media
import _render
from _vocab import load_data

DATA = load_data()
needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason="ffmpeg, ffprobe and a headless Chromium are needed")
needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
Z = DATA["zones"]
GAP = Z["gap"]


def flat_png(w, h, rgb=(200, 40, 40)):
    raw = (b"\x00" + bytes(rgb) * w) * h

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


UPPER_FACE = {"x": 240, "y": 300, "w": 600, "h": 400}


def test_the_values_are_in_the_presets_file():
    assert DATA["pip"] == {"card_max_height": 640, "card_min_height": 240}
    assert DATA["presets"]["pip"]["looks"] == {"radius_px": 24, "shadow": "0 14px 40px rgba(0,0,0,0.55)"}


def test_a_landscape_card_is_centred_inside_the_safe_width_and_starts_below_the_face():
    card = _layout.pip_card(DATA, UPPER_FACE, "top", 1200, 675)
    assert card["y"] == UPPER_FACE["y"] + UPPER_FACE["h"] + GAP
    assert 65 <= card["x"] and card["x"] + card["w"] <= 1015 and card["x"] + card["w"] // 2 == pytest.approx(540, abs=1)
    assert abs(card["w"] / card["h"] - 1200 / 675) < 0.01 and abs(card["h"] - card["w"] * 675 / 1200) <= 1


def test_a_card_at_the_bottom_ends_at_the_caption_line():
    card = _layout.pip_card(DATA, UPPER_FACE, "bottom", 1200, 675)
    assert card["y"] + card["h"] == Z["caption_bottom"]
    assert card["y"] >= UPPER_FACE["y"] + UPPER_FACE["h"] + GAP


def test_a_vertical_image_is_capped_in_height_and_its_width_follows_the_aspect():
    card = _layout.pip_card(DATA, {"x": 240, "y": 200, "w": 600, "h": 300}, "top", 600, 1000)
    assert card["h"] == 640 and abs(card["w"] - 384) <= 1 and card["x"] == (1080 - card["w"]) // 2


LOW_FACE = {"x": 240, "y": 628, "w": 600, "h": 560}          # the face box's bottom is at 1188, as on a real close-up


def test_the_card_takes_the_whole_room_down_to_the_caption_line_and_a_face_too_low_leaves_none():
    card = _layout.pip_card(DATA, LOW_FACE, "top", 1200, 675)
    assert card["y"] == 1188 + GAP and card["h"] == Z["caption_bottom"] - (1188 + GAP) and abs(card["w"] / card["h"] - 1200 / 675) < 0.01
    assert card["h"] > 300 and card["x"] >= 65          # drawn, not dropped
    assert _layout.pip_card(DATA, {"x": 240, "y": 800, "w": 600, "h": 540}, "top", 1200, 675) is None           # 1560 - 1358 = 202 px, under card_min_height
    assert _layout.pip_card(DATA, {"x": 240, "y": 800, "w": 600, "h": 540}, "top", 1200, 675, strict=False)["h"] == 202


def timeline_of(face, position="top", chunk_face=None, start=30, end=90):
    return {"beats": [{"id": "b1", "preset": "pip", "params": {"asset": "s1", "position": position}, "start_frame": start, "end_frame": end, "face": face}],
            "captions": [{"start_frame": 0, "end_frame": 20, "face": chunk_face or face}, {"start_frame": 40, "end_frame": 60, "face": chunk_face or face}],
            "dropped": []}


ASSETS = {"s1": {"kind": "png", "width": 1200, "height": 675}}


def test_a_caption_during_a_pip_gets_the_lower_part_of_the_card_and_one_outside_it_keeps_its_own():
    for position in ("top", "bottom"):
        tl = timeline_of(UPPER_FACE, position)
        assert _layout.pip_cards(DATA, tl, ASSETS) == []
        card = tl["beats"][0]["card"]
        assert "band" not in tl["captions"][0]
        assert tl["captions"][1]["band"] == [card["y"] + card["h"] - Z["caption_min_height"], card["y"] + card["h"]]
        assert _layout.entry_zones(DATA, tl["captions"][1])["caption"] == tl["captions"][1]["band"]
        assert tl["captions"][1]["band"][0] >= card["y"] and tl["captions"][1]["band"][0] > UPPER_FACE["y"] + UPPER_FACE["h"]


def test_a_pip_with_no_room_is_dropped_with_its_reason_and_its_id_stays_in_the_list_of_ids():
    tl = timeline_of({"x": 240, "y": 800, "w": 600, "h": 540})
    assert _layout.pip_cards(DATA, tl, ASSETS) == [{"id": "b1", "reason": "pip_no_room"}]
    assert tl["beats"] == [] and tl["dropped"] == ["b1"] and not any("band" in c for c in tl["captions"])
    low = timeline_of(LOW_FACE)
    assert _layout.pip_cards(DATA, low, ASSETS) == [] and low["beats"][0]["card"]["h"] > 300 and low["dropped"] == []


# ---------------------------------------------------------------- the command

def plan_with(pips, clip=False):
    plan = {"src": "/in/recording", "fps": 30, "size": [1080, 1920], "has_audio": False, "src_matrix": "auto", "kept": [[0, 120]],
            "layers": ["caption"], "frames_dir": "frames", "pips": pips, "out_frames": 120, "max_bytes": 300000000, "out_name": "out.mp4",
            "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}, "face": {"cx": 540, "cy": 500, "w": 600, "h": 400},
            "anchor": (540.0, 400.0), "fade": 0.015}
    return plan


ROW = {"asset": "assets/s1.png", "kind": "png", "start_frame": 30, "end_frame": 90, "x": 65, "y": 718, "w": 950, "h": 534, "radius": 24}


def test_the_card_is_the_asset_scaled_to_its_box_with_rounded_corners_over_the_speaker_who_stays_full_frame():
    argv = _media.compose_argv("ffmpeg", plan_with([ROW]))
    graph = argv[argv.index("-filter_complex") + 1]
    assert "scale=950:534:flags=" in graph and "alphamerge" in graph and "overlay=65:718:format=gbrp:enable='between(n,30,89)'" in graph
    assert "split" not in graph and "crop=" not in graph.split("[cv]")[1]          # no speaker bubble: the base picture is the cut recording itself
    lav = argv[argv.index("lavfi") + 2]
    assert lav.startswith("color=c=black:s=950x534:") and "geq=lum=" in lav
    assert "png_pipe" in argv


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["png", "clip"])
def test_an_image_and_a_clip_are_composed_in_the_same_box(tmp_path, kind):
    src = tmp_path / "rec.mp4"
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x203040:s=1080x1920:r=30:d=4", "-pix_fmt", "yuv420p", str(src)], check=True)
    if kind == "png":
        asset = tmp_path / "a.png"
        asset.write_bytes(flat_png(1200, 675, (250, 20, 20)))
    else:
        asset = tmp_path / "a.mp4"
        subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0xFA1414:s=320x180:r=30:d=4", "-pix_fmt", "yuv420p", str(asset)], check=True)
    row = dict(ROW, asset=str(asset), kind=kind)
    plan = plan_with([row])
    plan.update(src=str(src), layers=[], size=[1080, 1920])
    argv = _media.compose_argv(K.FFMPEG, plan)
    argv[argv.index("-i") + 1] = str(src)
    out = tmp_path / "out.mp4"
    argv[-1] = str(out)
    done = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-600:]
    inside, outside = (pixel(out, 60, 65 + 475, 718 + 267), pixel(out, 60, 20, 20))
    assert inside[0] > 150 and inside[1] < 80          # the card's colour, red
    assert outside[0] < 80 and outside[2] > 40         # the speaker's picture around it
    assert pixel(out, 10, 65 + 475, 718 + 267)[0] < 80        # before the beat: no card
    corner = pixel(out, 60, 66, 719)
    assert corner[0] < 80                                      # the rounded corner shows the picture under it


def pixel(video, frame, x, y):
    raw = subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", str(video), "-vf", "select=eq(n\\,%d),format=rgb24,crop=1:1:%d:%d" % (frame, x, y),
                          "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return tuple(raw[:3])


# ---------------------------------------------------------------- the page

def test_the_page_is_clean_asks_for_its_looks_and_reports_a_card_box_for_the_face_check():
    html = Path(K.BLOCKS, "oh", "pip", "renderat.html").read_text()
    assert _lint.lint(html) == []
    assert 'data-zone="card"' in html and "radius_px,shadow" in html and "ring" not in html and "opacity" not in html and "transform" not in html
    assert json.loads(Path(K.BLOCKS, "oh", "pip", "block.json").read_text())["may_cross_face"] is False


@needs_browser
def test_the_first_and_the_last_frame_of_the_beat_show_the_same_full_card(tmp_path):
    serve, _ = _frames.load_templates([K.template_of("pip")])
    card = _layout.pip_card(DATA, UPPER_FACE, "top", 1200, 675)
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path)) as ch:
        pg = ch.new_page(1080, 1920)
        pg.open("/t/" + K.template_of("pip"), {"colors": DATA["theme"]["colors"], "fonts": {}, "images": {}})
        look = DATA["presets"]["pip"]["looks"]
        seen = []
        for t in (0.0, 1.0, 2.0):
            data = {"params": {"asset": "s1", "position": "top", "label": "Fictional chart"}, "look": look, "zones": _layout.zones(DATA, UPPER_FACE), "duration": 2.0, "geom": card}
            r = pg.frame(t, data)
            seen.append(r["html"])
            assert r["boxes"] == [dict(zone="card", x=card["x"], y=card["y"], w=card["w"], h=card["h"])]
            assert _frames.face_hit(r["boxes"], UPPER_FACE) is None
            assert _frames.face_hit(r["boxes"], {"x": 240, "y": card["y"] - 100, "w": 600, "h": 200}) == "card"      # a card on the face is found
        assert seen[0] == seen[1] == seen[2]            # a hard cut: nothing moves, fades or slides
        assert "opacity" not in seen[0]


# ---------------------------------------------------------------- whole renders (a generated recording, generated pictures)

CARD_RGB = (255, 0, 255)


def with_asset(files, tmp, w, h):
    path = Path(tmp) / "card.png"
    path.write_bytes(flat_png(w, h, CARD_RGB))
    return dict(files, asset=path)


def edit_json(path, change):
    doc = json.loads(Path(path).read_text())
    change(doc)
    Path(path).write_text(json.dumps(doc))


def render_it(files, out, jobs="2", slots=(3, 4)):
    rc, result, err = K.run_verb(*K.render_args(files, out, "--jobs", jobs, slots=slots))
    assert rc == 0, err
    return result


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """One recording through analyse, base and align with a face high in the frame, and its pip set to the top; rendered with the pip,
    with the pip's beat taken out, and again with the pip with other worker counts."""
    tmp = tmp_path_factory.mktemp("pipcard")
    files = K.pipeline(tmp, K.build_transcript(K.SHORT_SENTENCES), K.SHORT_POST)
    files = with_asset(files, tmp, 1200, 675)
    edit_json(files["beats"], lambda b: [e["params"].update(position="top") for e in b["layouts"] if e["preset"] == "pip"])
    out = {"pip": render_it(files, tmp / "pip", "2"), "again": render_it(files, tmp / "again", "1")}
    own = dict(files, beats=tmp / "nopip-beats.json")
    Path(own["beats"]).write_text(Path(files["beats"]).read_text())
    edit_json(own["beats"], lambda b: b.update(layouts=[e for e in b["layouts"] if e["preset"] != "pip"]))
    out["nopip"] = render_it(own, tmp / "nopip", slots=(3,))
    data, edl, beats, platform, vocab, allow = _render.load_documents(files["edl"], files["beats"], K.INSTAGRAM, K.VOCABULARY)
    timeline = _render._edl.resolve_timeline(edl, beats, vocab, data)
    assets = _frames.load_assets({"beat4": str(files["asset"])}, {}, data["limits"])
    _layout.pip_cards(data, timeline, assets)
    pip = [e for e in timeline["beats"] if e["preset"] == "pip"][0]
    return {"files": files, "tmp": tmp, "out": out, "pip": pip, "timeline": timeline, "edl": edl, "data": data}


def frame_png(video, frame, path):
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-i", str(video), "-vf", "select=eq(n\\,%d)" % frame, "-frames:v", "1", str(path)], check=True)


def region_bytes(video, frame, crop):
    return subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", str(video), "-vf", "select=eq(n\\,%d),format=rgb24,crop=%s" % (frame, crop), "-frames:v", "1",
                           "-f", "rawvideo", "-"], capture_output=True, check=True).stdout


def mean_difference(a, b):
    assert len(a) == len(b) > 0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def is_card_pixel(p):
    return abs(p[0] - CARD_RGB[0]) < 40 and p[1] < 60 and abs(p[2] - CARD_RGB[2]) < 40


@needs_all
def test_the_card_is_below_the_face_centred_in_the_aspect_of_the_image_and_the_base_picture_around_it_is_the_one_without_a_pip(world):
    e, out = world["pip"], world["out"]["pip"]
    card, face = e["card"], e["face"]
    assert card["y"] == face["y"] + face["h"] + GAP and 65 <= card["x"] and card["x"] + card["w"] <= 1015
    assert abs(card["w"] / card["h"] - 1200 / 675) < 0.02 and abs((card["x"] + card["w"] / 2) - 540) <= 1
    video, f = out["path"], (e["start_frame"] + e["end_frame"]) // 2
    cx, cy = card["x"] + card["w"] // 2, card["y"] + card["h"] // 2
    assert is_card_pixel(pixel(video, f, cx, cy)) and is_card_pixel(pixel(video, f, card["x"] + 30, cy)) and is_card_pixel(pixel(video, f, card["x"] + card["w"] - 30, cy))
    assert not is_card_pixel(pixel(video, f, card["x"] - 6, cy)) and not is_card_pixel(pixel(video, f, card["x"] + card["w"] + 6, cy))
    assert not is_card_pixel(pixel(video, f, cx, card["y"] - 6))
    assert not is_card_pixel(pixel(video, f, card["x"] + 1, card["y"] + 1))          # the rounded corner
    above = "1080:%d:0:0" % (card["y"] - 100)
    # both are lossy encodes of different whole frames, so the regions agree to the encoder's noise, not byte for byte
    same = mean_difference(region_bytes(video, f, above), region_bytes(world["out"]["nopip"]["path"], f, above))
    assert same < 1.5, same                                                    # the speaker is the same picture as with no pip
    assert mean_difference(region_bytes(video, f, "1080:%d:0:%d" % (card["h"] - 40, card["y"] + 20)), region_bytes(world["out"]["nopip"]["path"], f, "1080:%d:0:%d" % (card["h"] - 40, card["y"] + 20))) > 20      # and the card's band is not


@needs_all
def test_the_caption_is_drawn_over_the_lower_part_of_the_card_and_never_above_it(world):
    e, out = world["pip"], world["out"]["pip"]
    card = e["card"]
    least = Z["caption_min_height"]
    caps = [c for c in world["timeline"]["captions"] if "band" in c]
    assert caps, "a caption overlaps the pip"
    seen = 0
    for c in caps:
        a, b = max(c["start_frame"], e["start_frame"]), min(c["end_frame"], e["end_frame"])
        for f in {a, (a + b) // 2, b - 1}:
            rows = card_rows(out["path"], f, card)
            band_top = card["h"] - least
            above = [r for r in range(4, band_top) if any(not is_card_pixel(px) for px in rows[r][card["w"] // 2:-40])]      # the right half: the label chip sits at the left corner; the first rows are the card's edge, blurred by the codec
            assert above == [], (f, above[:3])                       # no caption pixel above the card's lower band
            seen += sum(1 for r in range(band_top, card["h"]) if any(not is_card_pixel(px) for px in rows[r][40:-40]))
    assert seen > 0                                                 # the words are there, over the card's lower part


def card_rows(video, frame, card):
    raw = subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", str(video), "-vf",
                          "select=eq(n\\,%d),format=rgb24,crop=%d:%d:%d:%d" % (frame, card["w"], card["h"], card["x"], card["y"]), "-frames:v", "1", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    return [px[r * card["w"]:(r + 1) * card["w"]] for r in range(card["h"])]


@needs_all
def test_the_first_and_the_last_frame_of_the_beat_carry_the_card_at_full_strength(world):
    e, out = world["pip"], world["out"]["pip"]
    card = e["card"]
    cx, cy = card["x"] + card["w"] // 2, card["y"] + card["h"] // 2
    for f in (e["start_frame"], e["end_frame"] - 1):
        p = pixel(out["path"], f, cx, cy)
        assert p[0] > 235 and p[1] < 25 and p[2] > 235, (f, p)
    assert not is_card_pixel(pixel(out["path"], e["start_frame"] - 1, cx, cy))
    if e["end_frame"] + 1 < world["edl"]["out_frames"]:
        assert not is_card_pixel(pixel(out["path"], e["end_frame"] + 1, cx, cy))


@needs_all
def test_the_same_inputs_give_the_same_bytes_whatever_the_worker_count(world):
    assert world["out"]["pip"]["sha256"] == world["out"]["again"]["sha256"] != world["out"]["nopip"]["sha256"]


@needs_all
def test_a_pip_with_no_room_is_reported_with_its_reason_and_the_render_still_succeeds(world, tmp_path):
    files = world["files"]
    low = dict(files, edl=tmp_path / "low-edl.json")
    Path(low["edl"]).write_text(Path(files["edl"]).read_text())
    edit_json(low["edl"], lambda d: d.update(face_box={"x": 240, "y": 800, "w": 600, "h": 560}))
    result = render_it(low, tmp_path / "low")
    assert result["beats_dropped"] == ["b4"] and result["beats_dropped_reasons"] == [{"id": "b4", "reason": "pip_no_room"}]
    assert all(b["preset"] != "pip" for b in result["beats_drawn"])
    clean = _docker.sanitise(result, _docker.RESULT_SCHEMAS["render"], "render")
    assert clean["beats_dropped_reasons"] == [{"id": "b4", "reason": "pip_no_room"}]
    assert "beats_dropped_reasons" not in world["out"]["pip"]          # a render with no dropped pip writes the result it always wrote


def test_the_card_stays_below_the_face_as_a_punch_grows_it():
    punch_face = {"x": 200, "y": 280, "w": 680, "h": 520}
    edl = {"fps": 30, "face_box": UPPER_FACE, "kept": [[0, 300]], "zoom": {"mode": "none", "factor": 1.0, "push_in": 0.0, "anchor_y": 0.25}, "out_frames": 300}
    face = _edl_span(edl, [{"start_frame": 40, "end_frame": 80, "face": punch_face}])
    card = _layout.pip_card(DATA, face, "top", 1200, 675)
    assert face["y"] + face["h"] >= punch_face["y"] + punch_face["h"] and card["y"] == face["y"] + face["h"] + GAP
    assert not (card["x"] < face["x"] + face["w"] and card["x"] + card["w"] > face["x"] and card["y"] < face["y"] + face["h"] and card["y"] + card["h"] > face["y"])


def _edl_span(edl, punches):
    import _edl
    return _edl.span_face(edl, DATA, 30, 90, punches)


# ---------------------------------------------------------------- the beat's frames are exact, whatever the source's timestamps

def card_pattern(video):
    """'1' for each output frame whose pixel at the card's centre is the card's colour, '0' otherwise."""
    raw = subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", str(video), "-vf", "format=rgb24,crop=1:1:540:985", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    return "".join("1" if (raw[i] > 150 and raw[i + 1] < 80) else "0" for i in range(0, len(raw), 3))


def make_irregular_source(path):
    """A 1080x1920 clip whose frames come at irregular times (a phone's variable frame rate): about 30 frames a second, jittered."""
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=60:d=5", "-vf",
                    "select='not(mod(n,2))+gt(random(1),0.8)',setpts='N/(30*TB)+0.012*sin(N*1.7)/TB'", "-fps_mode", "vfr", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast", "-video_track_timescale", "90000", str(path)], check=True)


@needs_ffmpeg
@pytest.mark.parametrize("kept, start, end", [([[0, 100]], 6, 64), ([[20, 120]], 6, 64), ([[0, 3], [10, 100]], 6, 64), ([[0, 100]], 12, 66), ([[0, 100]], 30, 90)])
def test_the_card_is_on_exactly_from_the_first_frame_of_the_beat_to_its_last_whatever_the_source_timestamps(tmp_path, kept, start, end):
    """A float `t` compared with `start/fps` fell on the wrong side of the boundary (for 6/30 the product of a frame number and 1/30 is
    just under 0.2): the card was missing on its first frame. It is enabled by frame number now, which is the output frame's own index."""
    src = tmp_path / "vfr.mp4"
    make_irregular_source(src)
    asset = tmp_path / "a.png"
    asset.write_bytes(flat_png(1200, 675, CARD_RGB))
    total = sum(b - a for a, b in kept)
    plan = plan_with([dict(ROW, asset=str(asset), start_frame=start, end_frame=end)])
    plan.update(src=str(src), layers=[], kept=kept, out_frames=total)
    argv = _media.compose_argv(K.FFMPEG, plan)
    out = tmp_path / "out.mp4"
    argv[-1] = str(out)
    done = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-600:]
    pattern = card_pattern(out)
    assert len(pattern) == total
    assert [pattern[f] for f in (start - 1, start, start + 1, end - 1, end)] == ["0", "1", "1", "1", "0"], pattern
    assert pattern == "0" * start + "1" * (end - start) + "0" * (total - end)
