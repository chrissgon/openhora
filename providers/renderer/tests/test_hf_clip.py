"""A clip under the cutaway on the HyperFrames engine (package V9b-5b, Design B): `_hf_compose.write_page` with `clip_assets` writes the clip as top-level
`<video>` elements, written the way the proxy's are, inside wrapping divs that carry the cover or the glass look, as the first layers of the page, and tells
the page to draw the label chip only. The tests here are offline and need no browser and no ffmpeg: the clip's facts (size, seconds, fps, tint) are passed in
directly, as `_inner.py`'s `hf-page` verb passes what its probe read. A real clip through the verb is a test of its own, skipped without ffmpeg. Names are
fictional."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

import renderer_kit as K
import clip_kit as CK
import _blocks
import _edl
import _hf_compose as C
import _media
import _render
from _text import Refusal
from _vocab import load_data

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
DATA = load_data()
SLOT = "beat7"
needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
COVER = {"width": 1080, "height": 1920, "seconds": 10.0, "fps": 30, "tint": None}
GLASS = {"width": 1920, "height": 1080, "seconds": 10.0, "fps": 30, "tint": "3A9E5C"}
LAYER = re.compile(r'(<div id="hf-clip-0".*?)\n(?=<div id="hf-inst|<iframe)', re.S)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def clip_section(index: str) -> str:
    """The clip layers of a page and its `CL` line, the text the golden files hold."""
    return LAYER.search(index).group(1) + "\n" + re.search(r"^var CL = .*$", index, re.M).group(0) + "\n"


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("clip-docs")
    data, edl, beats, vocab = K.hf_documents(folder)
    beats["layouts"] = [row for row in json.loads((folder / "beats.json").read_text())["layouts"] if row["preset"] == "cutaway"]
    assert [row["id"] for row in beats["layouts"]] == ["b7"]
    return data, edl, beats, vocab


@pytest.fixture(scope="module")
def catalogue():
    return _blocks.load_catalogue()


def compose(docs, catalogue, folder, assets, clips, mutate=None):
    data, edl, beats, vocab = copy.deepcopy(docs)
    if mutate:
        mutate(data, edl, beats)
    folder.mkdir(parents=True, exist_ok=True)
    return C.write_page(data, edl, beats, vocab, catalogue, str(folder), edl["fps"], assets, clips)


def refusal(docs, catalogue, folder, assets, clips, mutate=None) -> tuple:
    with pytest.raises(Refusal) as caught:
        compose(docs, catalogue, folder, assets, clips, mutate)
    return caught.value.code, caught.value.field


def three_cutaways(data, edl, beats):
    """b7 and b8 are short cutaways (one cover, one glass clip) and b9 a picture, so that one page holds all three."""
    beats["layouts"] = [
        {"id": "b7", "beat": 7, "preset": "cutaway", "params": {"label": "My dashboard", "fit": "cover", "asset": "beat7"}, "word_from": 53, "word_to": 55, "score": 1.0},
        {"id": "b8", "beat": 8, "preset": "cutaway", "params": {"label": "Weekly savings", "fit": "cover", "asset": "beat8"}, "word_from": 56, "word_to": 59, "score": 1.0},
        {"id": "b9", "beat": 9, "preset": "cutaway", "params": {"label": "Another view", "fit": "cover", "asset": "beat9"}, "word_from": 60, "word_to": 69, "score": 1.0}]


def entry_of(docs, beat="b7"):
    data, edl, beats, vocab = copy.deepcopy(docs)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    return next(e for e in timeline["beats"] if e["id"] == beat), edl


# ---------------------------------------------------------------- 4.1 a: the picture page does not move

def test_the_picture_cutaway_page_has_the_same_two_hashes_with_clip_assets_absent_and_empty(docs, catalogue, tmp_path):
    from test_cutaway_look import two_colours
    picture = two_colours(1200, 675)
    want = dict(line.split("  ")[::-1] for line in Path(GOLDEN, "hf-cutaway-picture.sha256").read_text().split("\n") if line)
    for name, extra in (("absent", ()), ("empty", ({},))):
        data, edl, beats, vocab = copy.deepcopy(docs)
        out = tmp_path / name
        out.mkdir()
        C.write_page(data, edl, beats, vocab, catalogue, str(out), edl["fps"], {SLOT: sha(picture)}, *extra)
        assert {n: sha((out / n).read_bytes()) for n in ("index.html", "vars.json")} == {n: h for n, h in want.items()}, name
        assert "hf-clip" not in (out / "index.html").read_text() and "clip_slots" not in (out / "vars.json").read_text()


# ---------------------------------------------------------------- 4.1 b: the layer's markup against the golden files

@pytest.mark.parametrize("name,facts", (("cover", COVER), ("glass", GLASS)))
def test_the_clip_layer_and_the_cl_line_are_the_golden_files(docs, catalogue, tmp_path, name, facts):
    out = tmp_path / name
    compose(docs, catalogue, out, {SLOT: "a" * 64}, {SLOT: facts})
    assert clip_section((out / "index.html").read_text()) == Path(GOLDEN, "hf-clip-%s.html" % name).read_text()


def test_the_cover_geometry_and_the_glass_numbers_are_the_ones_of_the_page(docs, catalogue, tmp_path):
    entry, edl = entry_of(docs)
    start, end = entry["start_frame"], entry["end_frame"]
    compose(docs, catalogue, tmp_path / "c", {SLOT: "a" * 64}, {SLOT: COVER})
    cover = (tmp_path / "c" / "index.html").read_text()
    assert ('<video id="hf-clip-0-v0" src="media/clip-beat7.mp4" muted playsinline data-has-audio="false" data-start="%s" data-duration="%s" data-media-start="0" '
            'data-track-index="%d" style="position:absolute; left:0px; top:0px; width:1080px; height:1920px; object-fit:fill"></video>'
            % (C.num(start / 30.0), C.num((end - start) / 30.0), len(edl["kept"]))) in cover
    looks = DATA["presets"]["cutaway"]["looks"]
    compose(docs, catalogue, tmp_path / "g", {SLOT: "a" * 64}, {SLOT: GLASS})
    glass = (tmp_path / "g" / "index.html").read_text()
    box = _media.glass_box(1920, 1080)
    blur = looks["glass_blur_px"]
    bs = max((1080 + 4 * blur) / 1920.0, (1920 + 4 * blur) / 1080.0)
    assert box["w"] == 950 and box["x"] == 65                                                                  # the page's own computation, `_media.glass_box`
    assert "filter:blur(%spx)" % C.px(blur) in glass
    assert "left:%spx; top:%spx; width:%spx; height:%spx; object-fit:fill" % (C.px((1080 - 1920 * bs) / 2), C.px((1920 - 1080 * bs) / 2), C.px(1920 * bs), C.px(1080 * bs)) in glass
    place = "left:%spx; top:%spx; width:%spx; height:%spx" % (box["x"], box["y"], box["w"], box["h"])
    assert "%s; border-radius:%dpx; background:#000000; box-shadow:0 12px 48px rgba(0,0,0,0.45)" % (place, looks["glass_radius_px"]) in glass
    assert "%s; overflow:hidden; border-radius:%dpx" % (place, looks["glass_radius_px"]) in glass
    assert "background:#3A9E5C; opacity:%s" % C.px(looks["glass_tint_alpha"]) in glass
    assert "left:0px; top:0px; width:%dpx; height:%dpx; object-fit:fill" % (box["w"], box["h"]) in glass


# ---------------------------------------------------------------- 4.1 c: where the layers are

def test_the_layers_come_before_every_iframe_start_hidden_and_use_tracks_after_the_proxy(docs, catalogue, tmp_path):
    out = tmp_path / "t"
    compose(docs, catalogue, out, {SLOT: "a" * 64}, {SLOT: GLASS}, mutate=None)
    index = (out / "index.html").read_text()
    entry, edl = entry_of(docs)
    assert index.index('id="hf-clip-0"') < index.index("<iframe")
    layer = re.search(r'<div id="hf-clip-0"[^>]*>', index).group(0)
    assert 'data-hf-zone="frame"' in layer and "visibility:hidden" in layer and 'class="hf-clip"' in layer
    tracks = [int(n) for n in re.findall(r'id="hf-clip-0-v\d" [^>]*data-track-index="(\d+)"', index)]
    assert tracks == [len(edl["kept"]), len(edl["kept"]) + 1]
    proxy = [int(n) for n in re.findall(r'<video id="v\d+" src="media/proxy.mp4"[^>]*data-track-index="(\d+)"', index)]
    assert proxy and max(proxy) < min(tracks)
    assert 'src="media/clip-beat7.mp4"' in index and ".hf-clip{position:absolute;display:block}" in index
    section = clip_section(index)
    for word in ("My dashboard", "label", "edl", "words"):
        assert word not in section


# ---------------------------------------------------------------- 4.1 d, e: what the page and vars hold

def test_the_payload_tells_the_page_it_is_a_clip_and_no_picture_script_is_written(docs, catalogue, tmp_path):
    out = tmp_path / "p"
    compose(docs, catalogue, out, {SLOT: "a" * 64}, {SLOT: GLASS})
    vars_ = json.loads((out / "vars.json").read_text())
    payload = vars_["ra"]["oh:cutaway"][0]
    assert payload["params_kind"] == {"asset": "clip"} and payload["clip_size"] == {"w": 1920, "h": 1080}
    page = (out / "blocks" / "oh-cutaway.html").read_text()
    assert "var slots" not in page and "window.__hfImageLoads = [];" not in page                              # a clip-only page has no picture script
    assert vars_["clip_slots"] == [SLOT] and vars_["assets"] == {SLOT: "a" * 64}


def test_a_picture_slot_beside_a_clip_keeps_its_picture_script_and_vars_list_every_slot_sorted(docs, catalogue, tmp_path):
    out = tmp_path / "m"
    assets = {"beat7": "a" * 64, "beat8": "b" * 64, "beat9": "c" * 64}
    compose(docs, catalogue, out, assets, {"beat8": GLASS, "beat7": COVER}, mutate=three_cutaways)
    vars_ = json.loads((out / "vars.json").read_text())
    assert vars_["clip_slots"] == ["beat7", "beat8"] and vars_["assets"] == assets
    page = (out / "blocks" / "oh-cutaway.html").read_text()
    assert 'var slots = ["beat9"]' in page                                                                  # window.__imgs lists the picture slots only
    kinds = [p.get("params_kind") for p in vars_["ra"]["oh:cutaway"]]
    assert kinds == [{"asset": "clip"}, {"asset": "clip"}, None]


# ---------------------------------------------------------------- 4.1 f: no tint

def test_a_glass_clip_with_no_tint_uses_the_themes_background(docs, catalogue, tmp_path):
    out = tmp_path / "n"
    compose(docs, catalogue, out, {SLOT: "a" * 64}, {SLOT: dict(GLASS, tint=None)})
    index = (out / "index.html").read_text()
    bg = docs[1]["theme"]["colors"]["bg"].lstrip("#").upper()
    assert "background:#%s; opacity:" % bg in index


# ---------------------------------------------------------------- 4.1 g: several clips and a picture

def test_two_clip_cutaways_and_a_picture_cutaway_in_one_project(docs, catalogue, tmp_path):
    out = tmp_path / "s"
    assets = {"beat7": "a" * 64, "beat8": "b" * 64, "beat9": "c" * 64}
    result = compose(docs, catalogue, out, assets, {"beat7": COVER, "beat8": GLASS}, mutate=three_cutaways)
    index = (out / "index.html").read_text()
    assert index.count('class="hf-clip"') == 2 and 'id="hf-clip-0"' in index and 'id="hf-clip-1"' in index
    kept = len(docs[1]["kept"])
    tracks = [int(n) for n in re.findall(r'data-track-index="(\d+)"', index) if int(n) >= kept]
    assert tracks == [kept, kept + 1, kept + 2] and len(set(tracks)) == 3
    # V9g: b7 starts on the cut at 683 (its word is 3 frames later) and b9 on the cut at 766, which ends b8 there (the cut snap of `_edl.snap_to_cuts`)
    assert re.search(r'var CL = \[\["hf-clip-0",683,715\],\["hf-clip-1",715,766\]\];', index)
    assert result["beats_drawn"] >= 3


def test_the_same_slot_twice_is_two_layers_of_one_file(docs, catalogue, tmp_path):
    def same_slot(data, edl, beats):
        three_cutaways(data, edl, beats)
        beats["layouts"][1]["params"]["asset"] = "beat7"
        beats["layouts"][2]["params"]["asset"] = "beat7"
    out = tmp_path / "same"
    compose(docs, catalogue, out, {"beat7": "a" * 64}, {"beat7": COVER}, mutate=same_slot)
    index = (out / "index.html").read_text()
    assert index.count('class="hf-clip"') == 3 and index.count('src="media/clip-beat7.mp4"') == 3


# ---------------------------------------------------------------- 4.1 h: the refusals

def test_a_clip_on_screenshot_a_slide_look_another_fps_a_long_entry_and_a_stray_slot_are_refused(docs, catalogue, tmp_path):
    def screenshot(data, edl, beats):
        beats["layouts"][0]["block"] = "oh:screenshot"

    def slide(data, edl, beats):
        data["presets"]["cutaway"]["looks"]["transition"] = "slide"

    entry, edl = entry_of(docs)
    frames = entry["end_frame"] - entry["start_frame"]
    assets = {SLOT: "a" * 64}
    assert refusal(docs, catalogue, tmp_path / "a", assets, {SLOT: COVER}, screenshot) == ("asset_type", SLOT)
    assert refusal(docs, catalogue, tmp_path / "b", assets, {SLOT: COVER}, slide) == ("clip_transition", SLOT)
    assert refusal(docs, catalogue, tmp_path / "c", assets, {SLOT: dict(COVER, fps=25)}) == ("asset_type", SLOT)
    assert refusal(docs, catalogue, tmp_path / "d", assets, {SLOT: dict(COVER, seconds=(frames - 1) / 30.0)}) == ("clip_too_short", SLOT)
    compose(docs, catalogue, tmp_path / "e", assets, {SLOT: dict(COVER, seconds=frames / 30.0)})                         # as long as the entry is enough
    assert refusal(docs, catalogue, tmp_path / "f", assets, {"stray": COVER})[0] == "asset_missing"
    assert refusal(docs, catalogue, tmp_path / "g", assets, {"stray": COVER}) == ("asset_missing", "stray")


def test_a_bad_tint_is_refused_naming_the_slot(docs, catalogue, tmp_path):
    assert refusal(docs, catalogue, tmp_path / "t", {SLOT: "a" * 64}, {SLOT: dict(GLASS, tint="red")}) == ("bad_color", SLOT)


# ---------------------------------------------------------------- hf-page with a real clip

def verb_args(tmp, docs, clip, *more):
    """The arguments of the inner `hf-page` verb for the kit's post with its one cutaway, written under `tmp`."""
    folder = Path(tmp)
    folder.mkdir(parents=True, exist_ok=True)
    data, edl, beats, vocab = copy.deepcopy(docs)
    K.write_json(folder / "edl.json", edl)
    K.write_json(folder / "beats.json", beats)
    return ["hf-page", "--edl", folder / "edl.json", "--beats", folder / "beats.json", "--vocabulary", K.VOCABULARY, "--platform-file", K.INSTAGRAM,
            "--out", folder / "out", *more]


@needs_ffmpeg
def test_hf_page_with_a_real_clip_writes_the_page_and_refuses_audio_and_a_picture(docs, catalogue, tmp_path):
    clip = CK.counter_clip(tmp_path / "clip.mp4", 1080, 1920, 90, 30, codec_args=("-c:v", "libx264", "-g", "30", "-bf", "0", "-colorspace", "bt709", "-color_primaries",
                                                                                 "bt709", "-color_trc", "bt709", "-movflags", "+faststart"))
    digest = sha(Path(clip).read_bytes())
    blocks = ("--blocks", K.BLOCKS, "--blocks-sha256", catalogue["sha256"])
    rc, out, err = K.run_verb(*verb_args(tmp_path / "ok", docs, clip, *blocks, "--asset", "beat7=" + clip, "--asset-sha256", "beat7=" + digest))
    assert rc == 0, err
    assert out["ok"] is True and "clip_slots" in (tmp_path / "ok" / "out" / "vars.json").read_text()
    assert 'class="hf-clip"' in (tmp_path / "ok" / "out" / "index.html").read_text() and "clip_slots" not in out                  # the answer gains no key
    audio = tmp_path / "audio.mp4"
    CK.ffmpeg("-f", "lavfi", "-i", CK.counter_source(1080, 1920, 90), "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
              "-shortest", str(audio))
    rc, out, err = K.run_verb(*verb_args(tmp_path / "au", docs, clip, *blocks, "--asset", "beat7=%s" % audio, "--asset-sha256", "beat7=" + sha(audio.read_bytes())))
    assert rc == 1 and "asset_type" in err
    rc, out, err = K.run_verb(*verb_args(tmp_path / "wrong", docs, clip, *blocks, "--asset", "beat7=" + clip, "--asset-sha256", "beat7=" + "0" * 64))
    assert rc == 1 and "asset_hash" in err
    from test_cutaway_look import two_colours
    picture = tmp_path / "p.png"
    picture.write_bytes(two_colours(64, 64))
    rc, out, err = K.run_verb(*verb_args(tmp_path / "pic", docs, clip, *blocks, "--asset", "beat7=%s" % picture, "--asset-sha256", "beat7=" + sha(picture.read_bytes())))
    assert rc == 1 and "asset_type" in err


def test_asset_with_base_only_is_a_usage_error(docs, tmp_path):
    rc, out, err = K.run_verb(*verb_args(tmp_path / "b", docs, None, "--base-only", "--asset", "beat7=/x/clip.mp4"))
    assert rc == 2 and "only with the blocks" in err
    rc, out, err = K.run_verb(*verb_args(tmp_path / "c", docs, None, "--base-only", "--asset-sha256", "beat7=" + "0" * 64))
    assert rc == 2


@needs_ffmpeg
def test_the_live_leg_reads_the_clip_frame_number_of_every_frame_with_one_call(tmp_path):
    import test_engine_contract_live as live
    clip = CK.counter_clip(tmp_path / "c.mp4", 1080, 1920, 60, 30, codec_args=("-c:v", "libx264", "-g", "30", "-bf", "0"))
    assert live.counter_numbers(clip, 7, 30) == list(range(7, 37))
