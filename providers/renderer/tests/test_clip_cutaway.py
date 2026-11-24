"""A clip under an `oh:cutaway` entry on the ffmpeg engine (package V9b-5a): the compose draws the clip (cover, or the glass layout) under the beat layer, over the
speaker, on the entry's frames only; the page draws the label chip and nothing else; an image cutaway does not move. Every clip is made here by the host's ffmpeg
from generated frames (`clip_kit.py`; a moving gradient carrying its own frame number); the page is drawn by the host's headless browser. Tests are skipped
without ffmpeg, or without the browser. No docker, no network. Names are fictional."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import renderer_kit as K
import clip_kit as C
import _asset_sheet as A
import _assets
import _cdp
import _frames
import _layout
import _media
import _render
from _text import Refusal
from _vocab import load_data


@pytest.fixture(autouse=True)
def no_zoom_spacing(monkeypatch):
    """The plans and edit lists here have ranges of a few frames to 3.5 s and test the zoom's mechanics by the rule before V9g's spacing
    (`_media.ZOOM_SPACING_SECONDS`, at 0 every second range is zoomed); `test_zoom_spacing.py` tests the spacing itself."""
    monkeypatch.setattr(_media, "ZOOM_SPACING_SECONDS", 0.0)


needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason="ffmpeg, ffprobe and a headless Chromium are needed")
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
DATA = load_data()
LOOKS = DATA["presets"]["cutaway"]["looks"]


def code_of(call, *args, **kwargs) -> tuple:
    with pytest.raises(Refusal) as caught:
        call(*args, **kwargs)
    return caught.value.code, caught.value.field


# ---------------------------------------------------------------- the compose graph

def plan_with(clips, total=120, **more):
    plan = {"src": "/in/recording", "fps": 30, "size": [1080, 1920], "has_audio": False, "src_matrix": "bt709", "kept": [[0, total]], "layers": ["beat", "caption"],
            "frames_dir": "frames", "pips": [], "out_frames": total, "max_bytes": 300000000, "out_name": "out.mp4",
            "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}, "face": {"cx": 540, "cy": 500, "w": 600, "h": 400},
            "anchor": (540.0, 400.0), "fade": 0.015}
    plan.update(more)
    if clips is not None:
        plan["clips"] = clips
    return plan


COVER = {"asset": "assets/beat3.mp4", "start_frame": 20, "end_frame": 80, "mode": "cover"}
BOX = _media.glass_box(1920, 1080)
GLASS = {"asset": "assets/beat3.mp4", "start_frame": 20, "end_frame": 80, "mode": "glass", "box": BOX, "radius": LOOKS["glass_radius_px"], "blur": LOOKS["glass_blur_px"],
         "tint": "3A9E5C", "tint_alpha": LOOKS["glass_tint_alpha"]}


def graph_of(argv) -> str:
    return argv[argv.index("-filter_complex") + 1]


@pytest.mark.parametrize("name, clip", [("compose-clip-cover", COVER), ("compose-clip-glass", GLASS)])
def test_a_clip_cutaway_gives_exactly_this_argv(name, clip):
    argv = _media.compose_argv("/usr/bin/ffmpeg", plan_with([clip]))
    path = os.path.join(GOLDEN, name + ".json")
    if os.environ.get("UPDATE_GOLDEN") == "1":
        with open(path, "w") as fh:
            json.dump(argv, fh, indent=1)
            fh.write("\n")
    assert argv == json.load(open(path))


def test_the_cover_graph_has_no_path_no_enable_and_a_stream_the_length_of_the_output():
    argv = _media.compose_argv("ffmpeg", plan_with([COVER]))
    graph = graph_of(argv)
    for needle in ("assets/", ".mp4", "beat3", "/in/recording", "frames/", "enable="):
        assert needle not in graph, needle
    i = argv.index("assets/beat3.mp4")
    assert argv[i - 13:i] == ["-f", "mov", "-enable_drefs", "0", "-protocol_whitelist", "file", "-max_pixels", "33177600", "-codec_whitelist", "h264", "-c:v", "h264", "-i"]
    assert "[3:v:0]fps=30:start_time=0,tpad=stop=-1:stop_mode=clone,trim=end_frame=60,setpts=N/(30*TB),scale=1080:1920:force_original_aspect_ratio=increase:" in graph
    assert "[lay0]tpad=start=20:start_mode=clone:stop=-1:stop_mode=clone,trim=end_frame=120,setpts=N/(30*TB),format=gbrp[ca0]" in graph      # the stream is the whole output
    assert "if(between(N,20,79),255,0)" in graph and "trim=end_frame=120,setpts=N/(30*TB),scale=1080:1920:flags=lanczos+accurate_rnd+bitexact[cm0]" in graph
    assert "[ca0][cm0]alphamerge[cc0]" in graph and "overlay=0:0:format=gbrp[oc0]" in graph
    assert "gblur" not in graph and "split" not in graph.split("[cv]")[1]                                                                     # cover draws no blur and no copy
    scales = re.findall(r"scale=[^,;\[]*", graph)
    assert scales and all("flags=lanczos+accurate_rnd+bitexact" in x for x in scales), scales                                              # every scale is bit-exact


def test_the_glass_graph_is_the_pages_look_from_the_same_values():
    graph = graph_of(_media.compose_argv("ffmpeg", plan_with([GLASS])))
    for needle in ("assets/", ".mp4", "beat3", "enable="):
        assert needle not in graph, needle
    assert "scale=1272:2112:force_original_aspect_ratio=increase:" in graph and "gblur=sigma=48:steps=3,crop=1080:1920[gb0]" in graph          # 1080 + 4 x 48 and 1920 + 4 x 48
    assert "color=c=0x3A9E5C73:s=1080x1920" in graph                                                                                          # the tint, alpha 0.45 as 115 of 255
    assert "[gb0][gt0]overlay=0:0:format=gbrp[gl0]" in graph
    assert "gblur=sigma=24:steps=3" in graph and "*0.45" in graph and "geq=lum='clip((24-hypot(" in graph                                       # the shadow: 0.45, a blur of half 48, the radius 24
    assert "abs(Y+0.5-%g)" % (BOX["y"] + 12 + BOX["h"] / 2.0) in graph                                                                        # offset 12 down
    assert "scale=%d:%d:" % (BOX["w"], BOX["h"]) in graph and "overlay=%d:%d:format=gbrp[lay0]" % (BOX["x"], BOX["y"]) in graph               # the clip whole, in its box
    assert "if(between(N,20,79),255,0)" in graph and "trim=end_frame=120" in graph and "split=2[gs0][gf0]" in graph
    scales = re.findall(r"scale=[^,;\[]*", graph)
    assert all("flags=lanczos+accurate_rnd+bitexact" in x for x in scales), scales
    bare = graph_of(_media.compose_argv("ffmpeg", plan_with([dict(GLASS, tint=None)])))
    assert "[gt0]" not in bare                                                                                   # the builder draws no tint for a row that has none: the planner always gives one (clip_rows)


def test_the_look_values_of_the_page_are_the_ones_this_port_copies():
    page = (K.BLOCKS / "oh" / "cutaway" / "renderat.html").read_text(encoding="utf-8")
    assert "SAFE = 65, MAX_FG_H = 1700" in page and (_media.GLASS_SAFE, _media.GLASS_MAX_FG_H) == (65, 1700)
    assert "shadowColor = 'rgba(0, 0, 0, 0.45)'" in page and "shadowBlur = 48" in page and "shadowOffsetY = 12" in page
    assert (_media.SHADOW_ALPHA, _media.SHADOW_BLUR, _media.SHADOW_DY) == (0.45, 48, 12) and "FRAME_W + 4 * blur" in page
    assert _media.glass_box(1200, 675) == {"x": 65, "y": 693, "w": 950, "h": 534}
    assert _media.glass_box(1000, 1500)["h"] <= 1700 and _media.glass_box(2000, 100)["w"] == 950 and _media.js_round(2.5) == 3 and _media.js_round(0.5) == 1


def test_an_image_cutaway_is_composed_exactly_as_before_the_clip_path_existed():
    """The image cutaway is drawn by the page: the plan of a render with no clip has no `clips` key, and the argv of a plan with none (the key absent, or empty)
    is the argv this file has always given, byte for byte."""
    plain = json.load(open(os.path.join(GOLDEN, "compose-plain.json")))
    import test_renderer_media as M
    assert _media.compose_argv("/usr/bin/ffmpeg", M.plain_plan()) == plain
    assert _media.compose_argv("/usr/bin/ffmpeg", dict(M.plain_plan(), clips=[])) == plain
    assert _media.compose_argv("/usr/bin/ffmpeg", dict(M.pip_plan(), clips=[])) == json.load(open(os.path.join(GOLDEN, "compose-pip.json")))
    assert "clips" not in M.plain_plan() and "gblur" not in " ".join(plain)


def test_a_clip_is_over_the_speaker_and_under_the_beat_and_the_caption_layers():
    graph = graph_of(_media.compose_argv("ffmpeg", plan_with([COVER])))
    assert graph.index("[base]") < graph.index("overlay=0:0:format=gbrp[oc0]") < graph.index("[l_beat]") < graph.index("[c_beat]") < graph.index("[c_caption]")
    assert "[oc0][l_beat]overlay=0:0:format=gbrp[c_beat]" in graph
    pip = dict(asset="assets/s.png", kind="png", start_frame=5, end_frame=30, x=65, y=718, w=950, h=534, radius=24)
    both = graph_of(_media.compose_argv("ffmpeg", plan_with([COVER], pips=[pip])))
    assert both.index("overlay=65:718:format=gbrp[ob0]") < both.index("overlay=0:0:format=gbrp[oc0]")                                           # a card, then a clip, then the layers
    assert "overlay=0:0:format=gbrp[oc0]" in graph_of(_media.compose_argv("ffmpeg", plan_with([COVER], layers=[])))


# ---------------------------------------------------------------- the compose, run

def recording(tmp: Path, seconds=6, colour="0x203040") -> str:
    path = tmp / "rec.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "color=c=%s:s=1080x1920:r=30:d=%s" % (colour, seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path))
    return str(path)


def compose(tmp: Path, clips, out="out.mp4", total=120, **more):
    """Run the compose of a plan whose recording is a flat colour and whose clips are in `tmp`; returns the output path."""
    plan = plan_with(clips, total, layers=[], src=recording(tmp), **more)
    argv = _media.compose_argv(K.FFMPEG, plan)
    argv[argv.index("-i") + 1] = plan["src"]
    for k, a in enumerate(argv):
        if a == "assets/beat3.mp4":
            argv[k] = str(tmp / "clip.mp4")
    argv[-1] = str(tmp / out)
    done = subprocess.run(argv, cwd=tmp, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-800:]
    return tmp / out


def normalised(tmp: Path, w: int, h: int, frames: int, fps: int = 30, name="clip.mp4") -> str:
    raw = C.counter_clip(tmp / ("raw-" + name), w, h, frames, fps=fps)
    a, = A.asset_sheet(items={"s:1": raw}, mode="full", out_dir=str(tmp / ("sheet-" + name)), ffmpeg=K.FFMPEG, ffprobe=K.FFPROBE, fps=fps)["assets"]
    Path(tmp / name).write_bytes((tmp / ("sheet-" + name) / a["file"]).read_bytes())
    return str(tmp / name)


@needs_ffmpeg
@pytest.mark.parametrize("frames, start, end", [(60, 20, 80), (60, 20, 50), (30, 20, 80)])
def test_a_clip_plays_from_the_first_frame_of_the_entry_and_its_last_frame_is_held_to_its_end(tmp_path, frames, start, end):
    normalised(tmp_path, 1080, 1920, frames)
    out = compose(tmp_path, [dict(COVER, start_frame=start, end_frame=end)])
    assert C.frames_of(out) == 120
    shown = {f: C.frame_number(out, f) for f in (start - 1, start, start + 1, start + 9, end - 2, end - 1, end, end + 1)}
    assert shown[start] == 0 and shown[start + 1] == 1 and shown[start + 9] == 9                                        # from the first frame, frame for frame
    assert shown[end - 1] == min(frames - 1, end - 1 - start) and shown[end - 2] == min(frames - 1, end - 2 - start)      # the last frame of the clip is held, or the entry ends first
    assert shown[start - 1] not in range(0, frames) or shown[start - 1] == C.frame_number(out, 5)                         # before the entry: the recording, which has no counter
    assert shown[end] == shown[end + 1] == C.frame_number(out, 100)


@needs_ffmpeg
def test_the_clip_is_transparent_outside_the_entry_so_the_speaker_is_untouched(tmp_path):
    normalised(tmp_path, 1920, 1080, 40)
    with_clip = compose(tmp_path, [dict(GLASS, start_frame=30, end_frame=60)], out="with.mp4")
    without = compose(tmp_path, [], out="without.mp4")
    for f in (0, 29, 60, 61, 119):                                                       # every frame but the entry's: the same pixels as the render with no clip
        for x, y in ((10, 10), (540, 960), (1070, 1910), (200, 1200)):
            assert C.rgb_at(with_clip, f, x, y) == C.rgb_at(without, f, x, y), (f, x, y)
    assert C.rgb_at(with_clip, 45, 540, 960) != C.rgb_at(without, 45, 540, 960)
    assert C.frames_of(with_clip) == C.frames_of(without) == 120


@needs_ffmpeg
def test_a_clip_of_another_frame_rate_is_conformed_to_the_output_rate(tmp_path):
    normalised(tmp_path, 1080, 1920, 48, fps=24)                                          # two seconds at 24
    out = compose(tmp_path, [dict(COVER, start_frame=10, end_frame=100)])
    seen = [C.frame_number(out, f) for f in range(10, 100)]
    assert seen[0] == 0 and seen == sorted(seen) and seen[-1] == 47                      # in order, from its first frame to its last, which is held
    assert abs(C.frame_number(out, 40) - 24) <= 1                                         # one second in: the 25th frame of a 24 fps clip
    assert len(set(seen)) == 48


@needs_ffmpeg
def test_cover_fills_the_frame_and_glass_draws_the_clip_whole_in_its_box_over_a_blurred_copy(tmp_path):
    normalised(tmp_path, 1920, 1080, 40)
    out = compose(tmp_path, [dict(GLASS, start_frame=20, end_frame=60)], out="glass.mp4")
    scale = BOX["w"] / 1920.0
    assert [C.frame_number(out, f, BOX["x"], BOX["y"], scale) for f in (20, 21, 40, 59)] == [0, 1, 20, 39]          # the whole clip, in its box, frame for frame
    recording_pixel = C.rgb_at(out, 5, 540, 960)
    for x, y in ((10, 10), (1070, 10), (10, 1910), (1070, 1910), (540, 100), (540, 1800), (30, 960)):
        assert C.rgb_at(out, 40, x, y) != recording_pixel                                                        # the glass covers the whole frame
    inside = C.rgb_at(out, 40, BOX["x"] + BOX["w"] // 2, BOX["y"] + BOX["h"] // 2)
    below, far = C.rgb_at(out, 40, 540, BOX["y"] + BOX["h"] + 8), C.rgb_at(out, 40, 540, BOX["y"] + BOX["h"] + 160)
    assert sum(below) < sum(far)                                                                                 # the shadow darkens just under the box
    corner = C.rgb_at(out, 40, BOX["x"] + 1, BOX["y"] + 1)
    assert corner != C.rgb_at(out, 40, BOX["x"] + 40, BOX["y"] + 40) and inside != corner                         # the rounded corner shows what is under the box
    covered = compose(tmp_path, [dict(COVER, start_frame=20, end_frame=60)], out="cover.mp4")                  # the landscape clip cropped to fill the frame
    assert C.frame_number(covered, 30, 0, 0, 1080 / 1080.0) in range(0, 40) and C.rgb_at(covered, 30, 540, 960) != recording_pixel


def composed_frames(tmp: Path, clips, total=45) -> str:
    """The sha256 of the composed frames of a plan, taken from the filter graph's own output (raw yuv420p), before the final encode."""
    import hashlib
    plan = plan_with(clips, total, layers=[], src=recording(tmp))
    argv = _media.compose_argv(K.FFMPEG, plan)
    argv[argv.index("-i") + 1] = plan["src"]
    for k, a in enumerate(argv):
        if a == "assets/beat3.mp4":
            argv[k] = str(tmp / "clip.mp4")
    argv = argv[:argv.index("[vout]") + 1] + ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-frames:v", str(total), "-"]
    done = subprocess.run(argv, cwd=tmp, capture_output=True, timeout=600)
    assert done.returncode == 0, done.stderr[-800:]
    return hashlib.sha256(done.stdout).hexdigest()


@needs_ffmpeg
def test_the_same_plan_gives_the_same_composed_frames_every_time(tmp_path):
    """The graph is deterministic: the frames it hands the encoder are the same each time. (The final mp4's bytes are the encoder's: on the host's ffmpeg 9.0.2 four slice
    threads of x264 gave different bytes for the same raw input on moving content, which is the live leg's question for the image's x264; the plain compose is the same.)"""
    normalised(tmp_path, 1920, 1080, 24)
    for clip in (dict(COVER, start_frame=10, end_frame=30), dict(GLASS, start_frame=10, end_frame=30)):
        runs = {composed_frames(tmp_path, [clip]) for _ in range(3)}
        assert len(runs) == 1, clip["mode"]


# ---------------------------------------------------------------- the page

OLD_PAGE = Path(__file__).resolve().parent / "golden" / "cutaway-renderat-v9b2.html"
PAGE_NOW = K.BLOCKS / "oh" / "cutaway" / "renderat.html"
COLORS = DATA["theme"]["colors"]


def png(width, height, pixel) -> bytes:
    import struct
    import zlib
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def pictures():
    return {"wide": png(1200, 675, lambda x, y: (200 - x // 10, 60 + y // 8, 120 + (x + y) % 40)),
            "tall": png(600, 1000, lambda x, y: (200, 40, 40) if x < 300 else (40, 60, 200)),
            "square": png(700, 670, lambda x, y: (30, 160, 90) if y < 300 else (240, 200, 40))}


def draw_with(tmp_path, template_bytes, name, steps):
    """Open one page (`template_bytes`) on the three pictures and draw `steps`, a list of (picture, params, extra payload keys, time): the PNG bytes of each frame and its boxes."""
    serve, _ = _frames.load_templates(["oh/cutaway/renderat.html"])
    serve["/t/oh/cutaway/%s.html" % name] = (template_bytes, "text/html; charset=utf-8")
    pics = pictures()
    images = {}
    for key, raw in pics.items():
        serve["/assets/%s.png" % key] = (raw, "image/png")
        images[key] = _cdp.ORIGIN + "/assets/%s.png" % key
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / name), time_limit=240) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/oh/cutaway/%s.html" % name, {"colors": COLORS, "fonts": {}, "images": images})
        for picture, params, extra, t in steps:
            payload = dict({"params": dict({"asset": picture}, **params), "look": LOOKS, "zones": {}, "duration": 2.0}, **extra)
            result = page.frame(t, payload)
            out.append((page.screenshot(), result["boxes"]))
    return out


IMAGE_STEPS = [("wide", {"label": "Aster Lane"}, {}, 0.0), ("wide", {}, {}, 1.0), ("tall", {"fit": "cover"}, {}, 0.5), ("tall", {"fit": "contain", "label": "Bram Hollow"}, {}, 1.9),
               ("square", {}, {}, 0.0)]


@needs_browser
def test_an_image_cutaway_page_draws_the_same_frame_bytes_as_the_page_before_this_package(tmp_path):
    """The approved look of V9b-2 does not move: the page of that package is kept in `golden/` and drawn beside the present one, on the same pictures and times."""
    before = draw_with(tmp_path, OLD_PAGE.read_bytes(), "old", IMAGE_STEPS)
    after = draw_with(tmp_path, PAGE_NOW.read_bytes(), "new", IMAGE_STEPS)
    assert len(before) == len(after) == len(IMAGE_STEPS)
    for k, ((shot_a, boxes_a), (shot_b, boxes_b)) in enumerate(zip(before, after)):
        assert shot_a == shot_b and boxes_a == boxes_b, k


@needs_browser
def test_a_clip_cutaway_page_draws_only_the_label_chip_on_a_transparent_stage(tmp_path):
    import test_cutaway_look as L
    steps = [("wide", {"label": "Aster Lane"}, {"params_kind": {"asset": "clip"}}, t) for t in (0.0, 1.0, 1.9)]
    frames = draw_with(tmp_path, PAGE_NOW.read_bytes(), "clip", steps)
    for shot, boxes in frames:
        decoded = L.decode(shot)
        _, _, rows, bpp = decoded
        assert bpp == 4
        alpha = [row[3::4] for row in rows]
        opaque = [(x, y) for y, row in enumerate(alpha) for x in range(0, 1080, 6) if row[x]]
        assert opaque, "the chip is drawn"
        assert all(65 <= x < 65 + 520 and 320 <= y < 320 + 120 for x, y in opaque), "nothing but the chip is opaque"       # the chip's corner of the frame
        assert all(alpha[y][x] == 0 for y, x in ((960, 540), (100, 100), (1800, 900), (960, 1000)))                          # no picture, no background
        assert boxes == []                                                                                                   # the gate sees what it sees on an image cutaway: no box
    none = draw_with(tmp_path, PAGE_NOW.read_bytes(), "clip-none", [("wide", {}, {"params_kind": {"asset": "clip"}}, 0.5)])
    assert not any(any(row[3::4]) for row in L.decode(none[0][0])[2][2:])                                                    # no label: a frame with nothing on it
    image = draw_with(tmp_path, PAGE_NOW.read_bytes(), "image-gate", [("wide", {"label": "Aster Lane"}, {}, 1.0)])
    assert image[0][1] == frames[0][1] == []                                                                                 # the same boxes as an image cutaway: the face gate judges alike


@needs_browser
def test_a_page_that_drew_a_clip_draws_a_picture_after_it_as_a_fresh_page_does(tmp_path):
    mixed = draw_with(tmp_path, PAGE_NOW.read_bytes(), "mixed", [("wide", {"label": "Aster Lane"}, {"params_kind": {"asset": "clip"}}, 0.5), ("tall", {"fit": "cover"}, {}, 0.5),
                                                              ("wide", {}, {"params_kind": {"asset": "clip"}}, 0.5), ("wide", {"label": "Aster Lane"}, {}, 0.0)])
    fresh = draw_with(tmp_path, PAGE_NOW.read_bytes(), "fresh", [("tall", {"fit": "cover"}, {}, 0.5), ("wide", {"label": "Aster Lane"}, {}, 0.0)])
    assert mixed[1][0] == fresh[0][0] and mixed[3][0] == fresh[1][0]


# ---------------------------------------------------------------- where a clip may be used, and what is refused

def timeline_with(block, slot="beat3", preset="cutaway", transition_ok=True):
    return {"beats": [{"id": "b3", "preset": preset, "block": block, "params": {"asset": slot, "label": "x"}, "start_frame": 20, "end_frame": 60, "face": {"x": 240, "y": 300, "w": 600, "h": 400}}],
            "captions": [], "dropped": []}


VOCAB = None


def vocab():
    global VOCAB
    if VOCAB is None:
        from _vocab import load_vocabulary
        VOCAB = load_vocabulary(K.VOCABULARY)
    return VOCAB


CLIP = {"kind": "clip", "width": 1920, "height": 1080, "seconds": 2.0, "fps": 30.0, "tint": "3A9E5C"}


def test_only_the_cutaway_block_draws_a_clip_and_the_entry_is_marked_for_the_page():
    tl = timeline_with("oh:cutaway")
    _render.settle_clips(vocab(), DATA, tl, {"beat3": CLIP})
    assert tl["beats"][0]["params_kind"] == {"asset": "clip"}
    image = timeline_with("oh:cutaway")
    _render.settle_clips(vocab(), DATA, image, {"beat3": {"kind": "png", "width": 10, "height": 10}})
    assert "params_kind" not in image["beats"][0]                                       # an image cutaway is left as it was
    for block, preset in (("oh:screenshot", "cutaway"), ("oh:pip", "pip")):
        tl = timeline_with(block, preset=preset)
        assert code_of(_render.settle_clips, vocab(), DATA, tl, {"beat3": CLIP}) == ("asset_type", "beat3"), block        # the slot is named


def test_a_theme_whose_cutaway_look_is_a_slide_or_a_zoom_cannot_use_a_clip_yet():
    for transition in ("slide", "zoom"):
        data = copy.deepcopy(DATA)
        data["presets"]["cutaway"]["looks"]["transition"] = transition
        assert code_of(_render.settle_clips, vocab(), data, timeline_with("oh:cutaway"), {"beat3": CLIP}) == ("clip_transition", "beat3"), transition
        image = timeline_with("oh:cutaway")
        _render.settle_clips(vocab(), data, image, {"beat3": {"kind": "png", "width": 10, "height": 10}})                  # a picture keeps both
    assert LOOKS["transition"] == "cut"


def test_the_rows_of_the_plan_say_cover_for_a_tall_clip_and_glass_for_the_rest():
    def row(width, height, fit=None, looks=None):
        data = copy.deepcopy(DATA)
        data["presets"]["cutaway"]["looks"].update(looks or {})
        tl = timeline_with("oh:cutaway")
        tl["beats"][0]["params_kind"] = {"asset": "clip"}
        if fit:
            tl["beats"][0]["params"]["fit"] = fit
        rows = _render.clip_rows(data, tl, {"beat3": dict(CLIP, width=width, height=height)})
        assert len(rows) == 1 and rows[0]["asset"] == "assets/beat3.mp4" and (rows[0]["start_frame"], rows[0]["end_frame"]) == (20, 60)
        return rows[0]
    assert row(1080, 1920)["mode"] == "cover" and row(864, 1080)["mode"] == "cover"                 # 0.8 is the ratio: at or under it, the clip fills the frame
    assert row(1080, 1920, "contain")["mode"] == "glass" and row(1920, 1080)["mode"] == "glass" and row(865, 1080)["mode"] == "glass"
    g = row(1920, 1080)
    assert g["box"] == _media.glass_box(1920, 1080) and (g["radius"], g["blur"], g["tint"], g["tint_alpha"]) == (24, 48.0, "3A9E5C", 0.45)
    assert row(1920, 1080, looks={"glass_blur_px": None})["mode"] == "cover"                        # a theme with no glass look: the clip fills the frame
    assert row(1920, 1080, looks={"glass_ratio_max": 2.0})["mode"] == "cover"
    none = _render.clip_rows(DATA, timeline_with("oh:cutaway"), {"beat3": {"kind": "png", "width": 10, "height": 10}})
    assert none == []                                                                                # an image cutaway gives no clip row


@needs_ffmpeg
def test_a_clip_is_loaded_with_the_checks_of_the_normalised_form(tmp_path):
    good = normalised(tmp_path, 1920, 1080, 30)
    limits = DATA["limits"]

    def load(path, shas=None):
        files = {"beat3": (path, "mov")}
        return _render.load_clips(files, shas or {}, limits, K.FFMPEG, K.FFPROBE)["beat3"]
    clip = load(good)
    assert (clip["kind"], clip["width"], clip["height"], clip["fps"]) == ("clip", 1920, 1080, 30.0) and clip["seconds"] == pytest.approx(1.0, abs=0.1) and clip["tint"] is not None
    digest = clip["sha256"]
    assert load(good, {"beat3": digest})["sha256"] == digest
    assert code_of(load, good, {"beat3": "0" * 64}) == ("asset_hash", "beat3")                       # a clip whose sha256 differs
    audio = tmp_path / "audio.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "color=c=red:s=1280x720:r=30:d=1", "-f", "lavfi", "-i", "sine=f=300:d=1", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(audio))
    assert code_of(load, str(audio)) == ("asset_type", "beat3")                                      # a clip with audio at render
    raw = C.counter_clip(tmp_path / "raw.mp4", 1280, 720, 30)
    assert load(raw)["width"] == 1280                                                               # H.264, yuv420p, constant rate, no audio: the checks hold for a raw clip that already has the form
    vfr = tmp_path / "vfr.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60:d=2", "-vf", "select='gt(random(1),0.4)',setpts='N/(30*TB)+0.012*sin(N*1.7)/TB'", "-fps_mode", "vfr", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-video_track_timescale", "90000", str(vfr))
    assert code_of(load, str(vfr)) == ("asset_type", "beat3")                                        # not a constant rate
    long = C.flat_clip(tmp_path / "long.mp4", 1280, 720, 12)
    assert code_of(load, long) == ("asset_type", "beat3")                                            # not the first ten seconds
    webm = C.counter_clip(tmp_path / "w.webm", 1280, 720, 30, codec_args=("-c:v", "libvpx-vp9", "-b:v", "1M"))
    assert code_of(_assets.read_clip, "beat3", webm, {}, limits) == ("asset_type", "beat3")           # a render draws the one form asset-sheet writes: an MP4
    hevc = C.counter_clip(tmp_path / "h.mp4", 1280, 720, 30, codec_args=("-c:v", "libx265", "-tag:v", "hvc1"))
    assert code_of(load, hevc) == ("asset_type", "beat3")                                            # another codec than H.264
    big = dict(limits, asset_max_bytes=1000)
    assert code_of(_assets.read_clip, "beat3", good, {}, big) == ("asset_unreadable", "beat3")
    link = tmp_path / "link.mp4"
    link.symlink_to(good)
    assert code_of(_assets.read_clip, "beat3", str(link), {}, limits) == ("asset_unreadable", "beat3")


def test_a_clip_is_told_from_a_picture_by_its_first_bytes_and_the_pictures_are_unchanged(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40)
    (tmp_path / "b.webm").write_bytes(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x84webm" + b"\x00" * 40)
    (tmp_path / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    (tmp_path / "d.bin").write_bytes(b"not a clip")
    pictures, clips = _assets.split_clips({s: str(tmp_path / n) for s, n in (("a", "a.mp4"), ("b", "b.webm"), ("c", "c.png"), ("d", "d.bin"), ("e", "missing"))})
    assert sorted(clips) == ["a", "b"] and clips["a"][1] == "mov" and clips["b"][1] == "matroska" and sorted(pictures) == ["c", "d", "e"]
    assert _assets.head_bytes(str(tmp_path / "missing")) == b""
    (tmp_path / "l").symlink_to(tmp_path / "a.mp4")
    assert _assets.head_bytes(str(tmp_path / "l")) == b""
    assert _frames.ASSET_MIME == {"png": "image/png", "jpg": "image/jpeg"}                         # a clip is never served to a page


# ---------------------------------------------------------------- whole renders (a generated recording, generated clips)

def edit_json(path, change):
    doc = json.loads(Path(path).read_text())
    change(doc)
    Path(path).write_text(json.dumps(doc))


def render_it(files, out, *more, slots=()):
    args = K.render_args(files, out, *more, slots=slots)
    return K.run_verb(*args)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """One recording through analyse, base and align (its beat 3 a cutaway, its beat 4 a pip), a cover clip and a glass clip made by `asset-sheet`, and the renders:
    the cover clip on the cutaway, the glass clip, and the pip's picture throughout."""
    tmp = tmp_path_factory.mktemp("clipcut")
    files = K.pipeline(tmp, K.build_transcript(K.SHORT_SENTENCES), K.SHORT_POST)
    out = {}
    for name, (w, h, frames) in (("tall", (1080, 1920, 90)), ("wide", (1920, 1080, 90))):
        raw = C.counter_clip(tmp / (name + "-raw.mp4"), w, h, frames)
        a, = A.asset_sheet(items={"s:1": raw}, mode="full", out_dir=str(tmp / (name + "-sheet")), ffmpeg=K.FFMPEG, ffprobe=K.FFPROBE)["assets"]
        out[name] = tmp / (name + "-sheet") / a["file"]
    return {"files": files, "tmp": tmp, "clips": out}


def render_with(world, name, clip, *more):
    files = world["files"]
    out = world["tmp"] / name
    args = K.render_args(files, out, "--asset", "beat3=%s" % world["clips"][clip], "--asset", "beat4=%s" % files["asset"], *more, slots=())
    rc, result, err = K.run_verb(*args)
    return rc, result, err


@needs_all
def test_a_render_draws_the_cover_clip_frame_for_frame_with_the_label_over_it(world):
    rc, result, err = render_with(world, "cover", "tall", "--jobs", "2")
    assert rc == 0, err
    entry = [b for b in result["beats_drawn"] if b["preset"] == "cutaway"][0]
    lo, hi = entry["start_frame"], entry["end_frame"]
    video = result["path"]
    assert [C.frame_number(video, f) for f in (lo, lo + 1, lo + 30)] == [0, 1, 30]
    assert C.frame_number(video, hi - 1) == min(89, hi - 1 - lo) and C.frame_number(video, hi) != C.frame_number(video, hi - 1)
    chip = C.rgb_at(video, lo + 5, 80, 340)
    assert chip != C.rgb_at(video, lo - 3, 80, 340) and max(chip) < 80                           # the label chip is over the clip, from the first frame (a hard cut)


@needs_all
def test_a_render_draws_the_glass_clip_whole_over_a_blurred_copy(world):
    rc, result, err = render_with(world, "glass", "wide", "--jobs", "2")
    assert rc == 0, err
    entry = [b for b in result["beats_drawn"] if b["preset"] == "cutaway"][0]
    lo = entry["start_frame"]
    box = _media.glass_box(1920, 1080)
    assert [C.frame_number(result["path"], lo + k, box["x"], box["y"], box["w"] / 1920.0) for k in (0, 1, 20)] == [0, 1, 20]
    assert C.rgb_at(result["path"], lo + 20, 10, 10) != C.rgb_at(result["path"], lo - 3, 10, 10)


@needs_all
def test_the_render_checks_a_clip_before_a_frame_is_drawn(world):
    files, tmp = world["files"], world["tmp"]
    clip = world["clips"]["tall"]
    # a clip on the pip, and on the screenshot block
    rc, out, err = K.run_verb(*K.render_args(files, tmp / "r1", "--asset", "beat3=%s" % files["asset"], "--asset", "beat4=%s" % clip, "--dry-run", slots=()))
    assert rc == 1 and err.startswith("refused: asset_type beat4"), err
    shot = dict(files, beats=tmp / "screenshot-beats.json")
    Path(shot["beats"]).write_text(Path(files["beats"]).read_text())
    edit_json(shot["beats"], lambda b: [e.update(block="oh:screenshot") for e in b["layouts"] if e["preset"] == "cutaway"])
    rc, out, err = K.run_verb(*K.render_args(shot, tmp / "r2", "--asset", "beat3=%s" % clip, "--asset", "beat4=%s" % files["asset"], "--dry-run", slots=()))
    assert rc == 1 and err.startswith("refused: asset_type beat3"), err
    rc, out, err = K.run_verb(*K.render_args(files, tmp / "r3", "--asset", "beat3=%s" % clip, "--asset", "beat3=%s" % clip, "--dry-run", slots=()))
    assert rc != 0
    rc, out, err = K.run_verb(*K.render_args(files, tmp / "r4", "--asset", "beat3=%s" % clip, "--asset", "beat4=%s" % files["asset"], "--asset-sha256", "beat3=%s" % ("0" * 64), "--dry-run", slots=()))
    assert rc == 1 and err.startswith("refused: asset_hash beat3"), err
    rc, out, err = K.run_verb(*K.render_args(files, tmp / "r5", "--asset", "beat3=%s" % clip, "--asset", "beat4=%s" % files["asset"], "--dry-run", slots=()))
    assert rc == 0, err                                                                              # the same clip on the cutaway is accepted, and the plan has its row
    assert any(a == "assets/beat3.mp4" for a in out["ffmpeg_argv"]) and "gblur" not in " ".join(out["ffmpeg_argv"])
    assert not (tmp / "r5").exists() or not any((tmp / "r5").iterdir())                              # a dry run draws nothing
    assert Path(clip).stat().st_mode & 0o777 == 0o400 and C.frames_of(clip) == 90


@needs_all
def test_a_render_with_pictures_only_has_no_clip_in_its_plan(world):
    files, tmp = world["files"], world["tmp"]
    rc, out, err = K.run_verb(*K.render_args(files, tmp / "r6", "--asset", "beat3=%s" % files["asset"], "--asset", "beat4=%s" % files["asset"], "--dry-run", slots=()))
    assert rc == 0, err
    argv = out["ffmpeg_argv"]
    assert "gblur" not in " ".join(argv) and not any(a.endswith(".mp4") for a in argv if a.startswith("assets/")) and "h264" not in argv[:argv.index("-filter_complex")]
    data, edl, beats, platform, vocab_, allow = _render.load_documents(files["edl"], files["beats"], K.INSTAGRAM, K.VOCABULARY)
    timeline = _render._edl.resolve_timeline(edl, beats, vocab_, data)
    assets = _frames.load_assets({"beat3": str(files["asset"]), "beat4": str(files["asset"])}, {}, data["limits"])
    templates, names = __import__("_blocks").templates_for(__import__("_blocks").load_catalogue(), "ffmpeg", timeline, vocab_, with_caption=True)
    _layout.pip_cards(data, timeline, assets)
    plan = _render.compose_plan(data, edl, timeline, assets, platform, "/in/rec")
    assert "clips" not in plan


def test_a_glass_clip_with_no_predominant_colour_is_tinted_with_the_themes_background_as_the_page_does():
    page = (K.BLOCKS / "oh" / "cutaway" / "renderat.html").read_text(encoding="utf-8")
    assert "predominant(img) || getComputedStyle(document.documentElement).getPropertyValue('--c-bg').trim()" in page          # the page's fallback: the theme's `bg`
    tl = timeline_with("oh:cutaway")
    tl["beats"][0]["params_kind"] = {"asset": "clip"}
    plain = {"beat3": dict(CLIP, tint=None)}
    row, = _render.clip_rows(DATA, tl, plain)
    assert row["mode"] == "glass" and row["tint"] == DATA["theme"]["colors"]["bg"].lstrip("#").upper()
    themed, = _render.clip_rows(DATA, tl, plain, {"bg": "#10203a"})                       # the edit list's own theme
    assert themed["tint"] == "10203A"
    assert "color=c=0x10203A73" in graph_of(_media.compose_argv("ffmpeg", plan_with([themed])))
    own, = _render.clip_rows(DATA, tl, {"beat3": dict(CLIP, tint="3A9E5C")}, {"bg": "#10203a"})
    assert own["tint"] == "3A9E5C"                                                        # a predominant colour wins


@needs_browser
def test_the_page_reports_the_glass_box_of_a_clip_as_it_does_for_an_image(tmp_path):
    steps = [("wide", {}, {"params_kind": {"asset": "clip"}, "clip_size": {"w": 1920, "h": 1080}}, 0.5), ("wide", {}, {"params_kind": {"asset": "clip"}, "clip_size": {"w": 1080, "h": 1920}}, 0.5),
             ("wide", {"fit": "contain"}, {"params_kind": {"asset": "clip"}, "clip_size": {"w": 1080, "h": 1920}}, 0.5), ("wide", {}, {}, 0.5)]
    serve, _ = _frames.load_templates(["oh/cutaway/renderat.html"])
    serve["/assets/wide.png"] = (pictures()["wide"], "image/png")
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "c"), time_limit=240) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/oh/cutaway/renderat.html", {"colors": COLORS, "fonts": {}, "images": {"wide": _cdp.ORIGIN + "/assets/wide.png"}})
        boxes = []
        for picture, params, extra, t in steps:
            page.frame(t, dict({"params": dict({"asset": picture}, **params), "look": LOOKS, "zones": {}, "duration": 2.0}, **extra))
            boxes.append(json.loads(page.evaluate("JSON.stringify(window.__box)")))
    assert boxes[0] == _media.glass_box(1920, 1080) and boxes[1] == {"x": 0, "y": 0, "w": 1080, "h": 1920} and boxes[2] == _media.glass_box(1080, 1920)
    assert boxes[3] == _media.glass_box(1200, 675)                                        # an image: the box of its own picture


@needs_ffmpeg
def test_a_rotated_clip_and_a_clip_with_a_side_over_3840_are_refused_at_render(tmp_path):
    good = normalised(tmp_path, 1280, 720, 20)
    rotated = tmp_path / "rotated.mp4"
    C.ffmpeg("-display_rotation", "90", "-i", good, "-c", "copy", str(rotated))
    limits = DATA["limits"]
    assert code_of(_render.load_clips, {"beat3": (str(rotated), "mov")}, {}, limits, K.FFMPEG, K.FFPROBE) == ("asset_type", "beat3")
    wide = tmp_path / "wide.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "color=c=0x2060C0:s=3842x64:r=30:d=0.5", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(wide))
    assert code_of(_render.load_clips, {"beat3": (str(wide), "mov")}, {}, limits, K.FFMPEG, K.FFPROBE) == ("asset_type", "beat3")
