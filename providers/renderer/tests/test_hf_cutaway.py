"""The cutaway on the HyperFrames engine (package V9b-2): a frame-band entry in the composed page, drawn with the page the ffmpeg engine draws
(`oh:cutaway` and `oh:screenshot`), with the hard cut and the glass layout its looks give. Two kinds of test:

  the compose  `_hf_compose.write_page` on the kit's fictional post with a cutaway beat: the files, the iframe, the pictures' names and hashes in
               `vars.json`, the refusals. Offline, no browser.
  the page     the composed project served from memory to the host's headless browser (skipped without it), with a few lines of the test's own standing
               in for GSAP's timeline (GSAP is in the HyperFrames image only; the page's own drive is what runs). The four checks of the V9d look,
               through this compose: the cut, the glass layout, the cover fill, the same bytes twice.

Every picture is a flat-colour PNG made with zlib. Names are fictional.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

import renderer_kit as K
import _blocks
import _cdp
import _edl
import _frames
import _hf_compose as C
from _text import Refusal
from _vocab import load_data
from test_cutaway_look import at, decode, png, two_colours

needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
DATA = load_data()
SLOT = "beat7"                                     # the slot the kit's script gives its cutaway beat (beat 7)
GLASS_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; frame-src 'self'; "
             "media-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'")
THEME_BG = tuple(int(DATA["theme"]["colors"]["bg"][i:i + 2], 16) for i in (1, 3, 5))
# GSAP's own file is in the HyperFrames image only. These lines stand in for the part of its timeline the composed page uses on a seek: the tweens of the
# page's own objects (`fromTo(object, {at: 0}, {at: end, duration}, start)`), which call the page's drive; zooms and visibility sets are not needed here.
GSAP_SHIM = """window.gsap = { timeline: function () {
  var tweens = [];
  var tl = { set: function () { return tl; }, add: function () { return tl; },
    fromTo: function (target, from, to, start) { if (typeof target !== 'string') tweens.push({ t: target, from: from, to: to, start: start }); return tl; },
    seek: function (time) { tweens.forEach(function (w) {
      var p = Math.max(0, Math.min(1, (time - w.start) / w.to.duration));
      w.t.at(w.from.at + (w.to.at - w.from.at) * p); }); } };
  return tl; } };"""


def sha(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    """(data, edl, beats, vocab) of the kit's post with its one cutaway (beat 7, slot `beat7`) and no pip."""
    folder = tmp_path_factory.mktemp("cutaway-docs")
    data, edl, beats, vocab = K.hf_documents(folder)
    beats["layouts"] = [row for row in json.loads((folder / "beats.json").read_text())["layouts"] if row["preset"] == "cutaway"]
    assert [row["id"] for row in beats["layouts"]] == ["b7"]
    return data, edl, beats, vocab


@pytest.fixture(scope="module")
def catalogue():
    return _blocks.load_catalogue()


def compose(docs, catalogue, folder, assets, mutate=None, **over):
    data, edl, beats, vocab = copy.deepcopy(docs)
    if mutate:
        mutate(beats)
    folder.mkdir(parents=True, exist_ok=True)
    return C.write_page(data, edl, beats, vocab, catalogue, str(folder), edl["fps"], assets)


def refusal(docs, catalogue, folder, assets, mutate=None) -> tuple:
    with pytest.raises(Refusal) as caught:
        compose(docs, catalogue, folder, assets, mutate)
    return caught.value.code, caught.value.field


def entry_of(docs, catalogue):
    data, edl, beats, vocab = copy.deepcopy(docs)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    return next(e for e in timeline["beats"] if e["id"] == "b7"), edl["fps"]


# ---------------------------------------------------------------- the compose

def test_the_committed_hyperframes_engine_draws_the_cutaway_and_no_pip(catalogue):
    engine = catalogue["engines"]["hyperframes"]
    assert engine["presets"]["cutaway"] == "oh:cutaway" and "pip" not in engine["presets"]
    assert "draws the cutaway" in engine["note"] and "no pip" in engine["note"]
    assert _blocks.resolve(catalogue, "hyperframes", "cutaway", None, "beats.b7")["name"] == "oh:cutaway"
    with pytest.raises(Refusal) as caught:
        _blocks.resolve(catalogue, "hyperframes", "pip", None, "beats.b8")
    assert caught.value.code == "preset_not_on_engine"


def test_a_cutaway_beat_is_one_frame_zone_iframe_with_its_picture_named_in_the_page_and_hashed_in_vars(docs, catalogue, tmp_path):
    picture = two_colours(1200, 675)
    out = tmp_path / "p"
    result = compose(docs, catalogue, out, {SLOT: sha(picture)})
    index = (out / "index.html").read_text()
    entry, fps = entry_of(docs, catalogue)
    assert 'data-hf-zone="frame" data-hf-key="oh:cutaway" src="blocks/oh-cutaway.html"' in index
    assert '[data-hf-zone="frame"]{z-index:0}' in index and '[data-hf-zone="card"]{z-index:1}' in index
    assert "var RA = " in index and "[%d,%d]" % (entry["start_frame"], entry["end_frame"]) in index
    vars_ = json.loads((out / "vars.json").read_text())
    assert vars_["assets"] == {SLOT: sha(picture)}
    assert len(vars_["ra"]["oh:cutaway"]) == 1 and vars_["ra"]["oh:cutaway"][0]["params"]["asset"] == SLOT
    assert vars_["ra"]["oh:cutaway"][0]["look"] == DATA["presets"]["cutaway"]["looks"]        # the look comes with the payload, as on the ffmpeg engine
    page = (out / "blocks" / "oh-cutaway.html").read_text()
    assert 'var slots = ["beat7"]' in page and "../assets/" in page and "window.__hfImageLoads.push(im.decode())" in page
    assert "window.__hfFaceLoads = (window.__hfFaceLoads || []).concat(window.__hfImageLoads)" in page
    assert result["layers"] == ["cuts", "zoom", "captions", "beats"] and result["beats_drawn"] == 5 and result["runtimes"]["oh:cutaway"] == "renderat"
    assert result["blocks"]["oh:cutaway"] == catalogue["files"]["oh/cutaway/renderat.html"]
    assert set(p.name for p in out.iterdir()) == {"index.html", "vars.json", "blocks"}                        # the pictures are put in by the host, not written here


def test_the_frame_layer_is_listed_before_the_cards_and_the_captions_by_the_plan(docs, catalogue):
    data, edl, beats, vocab = copy.deepcopy(docs)
    plan = C.draw_plan(data, edl, beats, vocab, catalogue, edl["fps"], {SLOT: "a" * 64})
    zones = [p["zone"] for p in plan]
    assert C.ZONE_ORDER == ("frame", "card", "caption") and zones == sorted(zones, key=C.ZONE_ORDER.index) and zones[0] == "frame"
    frame = plan[0]
    assert frame["slot"] == SLOT and frame["band"] == (0, data["frame"]["height"]) and frame["runtime"] == "renderat"


def test_a_render_with_no_frame_entry_has_no_assets_key_no_frame_layer_and_no_picture_script(docs, catalogue, tmp_path):
    out = tmp_path / "plain"
    result = compose(docs, catalogue, out, None, mutate=lambda b: b.update(layouts=[]))
    assert "assets" not in json.loads((out / "vars.json").read_text())
    index = (out / "index.html").read_text()
    assert 'data-hf-zone="frame"' not in index and "frame\"]{z-index" not in index
    assert not (out / "blocks" / "oh-cutaway.html").exists()
    assert result["beats_drawn"] == 4 and "oh:cutaway" not in result["runtimes"]
    again = tmp_path / "plain2"
    compose(docs, catalogue, again, {}, mutate=lambda b: b.update(layouts=[]))
    assert (out / "index.html").read_bytes() == (again / "index.html").read_bytes() and (out / "vars.json").read_bytes() == (again / "vars.json").read_bytes()


def test_the_same_inputs_write_the_same_bytes(docs, catalogue, tmp_path):
    for name in ("a", "b"):
        compose(docs, catalogue, tmp_path / name, {SLOT: "c" * 64})
    for rel in ("index.html", "vars.json", "blocks/oh-cutaway.html"):
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


def test_a_slot_without_a_picture_and_a_picture_without_a_slot_are_refused(docs, catalogue, tmp_path):
    assert refusal(docs, catalogue, tmp_path / "a", {}) == ("asset_missing", SLOT)
    assert refusal(docs, catalogue, tmp_path / "b", None) == ("asset_missing", SLOT)
    assert refusal(docs, catalogue, tmp_path / "c", {SLOT: "d" * 64, "extra": "e" * 64}) == ("asset_unused", "extra")
    assert refusal(docs, catalogue, tmp_path / "d", {"extra": "e" * 64}, mutate=lambda b: b.update(layouts=[])) == ("asset_unused", "extra")


def test_a_bad_slot_a_bad_hash_and_too_many_pictures_are_refused(docs, catalogue, tmp_path):
    assert refusal(docs, catalogue, tmp_path / "a", {"Bad Slot": "a" * 64})[0] == "bad_slot"
    assert refusal(docs, catalogue, tmp_path / "b", {SLOT: "xyz"}) == ("asset_hash", SLOT)
    assert refusal(docs, catalogue, tmp_path / "c", {SLOT: "A" * 64}) == ("asset_hash", SLOT)
    assert refusal(docs, catalogue, tmp_path / "d", {"s%d" % n: "a" * 64 for n in range(C.MAX_ASSETS + 1)}) == ("too_many_assets", "assets")
    assert C.MAX_ASSETS == 12


def test_a_pip_beat_still_fails_on_this_engine(docs, catalogue, tmp_path):
    data, edl, beats, vocab = copy.deepcopy(docs)
    raw = {"id": "b8", "beat": 8, "preset": "pip", "params": {"label": "Weekly savings", "position": "top", "asset": "beat8"}, "word_from": 60, "word_to": 69, "score": 1.0}
    assert refusal(docs, catalogue, tmp_path / "a", {SLOT: "a" * 64, "beat8": "b" * 64}, mutate=lambda b: b["layouts"].append(raw))[0] == "preset_not_on_engine"


def test_a_screenshot_block_named_by_the_beat_is_drawn_in_the_same_frame_zone(docs, catalogue, tmp_path):
    def name_it(beats):
        beats["layouts"][0]["block"] = "oh:screenshot"
    out = tmp_path / "s"
    result = compose(docs, catalogue, out, {SLOT: "a" * 64}, mutate=name_it)
    assert result["runtimes"]["oh:screenshot"] == "renderat" and "oh:cutaway" not in result["runtimes"]
    assert 'data-hf-zone="frame" data-hf-key="oh:screenshot" src="blocks/oh-screenshot.html"' in (out / "index.html").read_text()
    assert 'var slots = ["beat7"]' in (out / "blocks" / "oh-screenshot.html").read_text()


def test_only_an_oh_layout_with_one_picture_parameter_and_a_renderat_page_is_a_frame_block(catalogue):
    cutaway = catalogue["blocks"]["oh:cutaway"]
    assert C.is_frame_block(cutaway) and C.asset_param(cutaway) == "asset" and C.is_frame_block(catalogue["blocks"]["oh:screenshot"])
    assert not C.is_frame_block(catalogue["blocks"]["oh:keyword"]) and C.asset_param(catalogue["blocks"]["oh:keyword"]) is None
    assert not C.is_frame_block(dict(cutaway, name="hf:cutaway")) and not C.is_frame_block(dict(cutaway, implementations={"gsap": "gsap.html"}))
    two = dict(cutaway, params=dict(cutaway["params"], second={"type": "image"}))
    assert C.asset_param(two) is None and not C.is_frame_block(two)
    assert not C.is_frame_block(dict(cutaway, kind="overlay"))


# ---------------------------------------------------------------- the page, in the host's browser

def project_files(folder: Path, picture_by_slot: dict) -> dict:
    """The served table of a composed project: the page with a stand-in timeline and its variables, the block pages, the pictures and the fonts."""
    index = (folder / "index.html").read_text()
    assert index.count('<script src="gsap.min.js"></script>') == 1 and index.count("<head>") == 1
    index = index.replace('<script src="gsap.min.js"></script>', "<script>%s</script>" % GSAP_SHIM)
    # HyperFrames' runtime gives the root composition the frame's size; here the page's html and body get it, so that the root (100 percent of them) is not empty
    index = index.replace("<head>", "<head><style>html, body { width: 1080px; height: 1920px; }</style><script>window.__hfVariables = %s;</script>"
                          % (folder / "vars.json").read_text().strip(), 1)
    serve = {"/index.html": (index.encode("utf-8"), "text/html; charset=utf-8")}
    for page in sorted((folder / "blocks").glob("*.html")):
        serve["/blocks/" + page.name] = (page.read_bytes(), "text/html; charset=utf-8")
    for slot, raw in picture_by_slot.items():
        serve["/assets/%s.png" % slot] = (raw, "image/png")
    for font in sorted((K.RENDERER / "assets" / "fonts").glob("*.woff2")):
        serve["/fonts/" + font.name] = (font.read_bytes(), "font/woff2")
    return serve


class Run:
    """One browser on one composed project: `seek(frame)` and a screenshot of that frame."""

    def __init__(self, tmp: Path, serve: dict, monkeypatch):
        monkeypatch.setattr(_cdp, "CSP", GLASS_CSP)
        self.chrome = _cdp.Chrome(K.BROWSER, serve, str(tmp / "chrome"), time_limit=180)
        self.chrome.start()
        self.page = self.chrome.new_page(1080, 1920)
        self.page.c.send("Page.navigate", {"url": _cdp.ORIGIN + "/index.html"}, self.page.sid)
        for _ in range(500):
            if self.page.evaluate("document.readyState") == "complete":
                break
            import time
            time.sleep(0.02)
        else:
            raise AssertionError("the composed page did not load")
        # every picture decoded before frame 0, as the drawing image waits for it
        self.page.evaluate("Promise.all(Array.prototype.map.call(document.querySelectorAll('iframe.hf-ra'), function (f) { return Promise.all(f.contentWindow.__hfImageLoads || []); }))",
                           await_promise=True)

    def seek(self, frame: int, fps: int = 30):
        self.page.evaluate("window.__timelines.main.seek(%r)" % (frame / float(fps)))

    def shot(self):
        return decode(self.page.screenshot())

    def state(self):
        """What the cutaway iframe shows: whether it is visible, its box, the layer's opacity and transform, the chip's opacity."""
        return json.loads(self.page.evaluate(
            "JSON.stringify((function(){var f=document.querySelector('iframe[data-hf-zone=frame]'),d=f.contentDocument,e=d.querySelector('#stage > *');"
            "return {visible: f.style.visibility, box: f.contentWindow.__box || null, tag: e ? e.tagName : null, opacity: e ? e.style.opacity : null,"
            "transform: e ? e.style.transform : null, chip: (d.getElementById('chip') || {style: {}}).style.opacity || null};})())"))

    def close(self):
        self.chrome.close()


@pytest.fixture
def served(docs, catalogue, tmp_path, monkeypatch):
    runs = []

    def make(picture: bytes, params=None, block=None, name="run"):
        def edit(beats):
            beats["layouts"][0]["params"].update(params or {})
            if block:
                beats["layouts"][0]["block"] = block
        folder = tmp_path / name
        compose(docs, catalogue, folder, {SLOT: sha(picture)}, mutate=edit)
        run = Run(tmp_path / (name + "-browser"), project_files(folder, {SLOT: picture}), monkeypatch)
        runs.append(run)
        return run
    yield make
    for run in runs:
        run.close()


@needs_browser
def test_the_first_and_last_frames_of_a_cutaway_show_the_picture_at_full_opacity_with_no_offset_and_the_frames_around_it_do_not(served, docs, catalogue):
    run = served(two_colours(1200, 675), {"label": "Aster Lane"})
    entry, fps = entry_of(docs, catalogue)
    first, last = entry["start_frame"], entry["end_frame"] - 1
    for frame in (first, (first + last) // 2, last):
        run.seek(frame)
        state = run.state()
        assert state["visible"] == "visible" and float(state["opacity"]) == 1.0 and state["transform"] == "translateX(0px) scale(1)" and float(state["chip"]) == 1.0
    for frame in (first - 1, last + 1):
        run.seek(frame)
        assert run.state()["visible"] == "hidden"
    run.seek(first - 1)
    assert at(run.shot(), 540, 960) != (200, 40, 40)                       # not the picture's colour: the cut is not there yet


@needs_browser
def test_a_landscape_picture_is_drawn_in_the_glass_layout_inside_the_safe_margins_with_no_theme_background_outside_it(served, docs, catalogue):
    run = served(two_colours(1200, 675))
    entry, fps = entry_of(docs, catalogue)
    run.seek(entry["start_frame"])
    state = run.state()
    box = state["box"]
    assert state["tag"] == "CANVAS" and 65 <= box["x"] and box["x"] + box["w"] <= 1015 and abs((box["x"] + box["w"] / 2) - 540) <= 1
    shot = run.shot()
    for x, y in ((10, 10), (1070, 10), (10, 1900), (1070, 1900), (540, 100), (540, 1800), (30, 960)):
        assert at(shot, x, y) != THEME_BG, (x, y)                        # the blurred picture, not the backdrop
    left, right = at(shot, 200, 960), at(shot, 900, 960)
    assert left[0] > 150 and left[2] < 90 and right[2] > 150 and right[0] < 90


@needs_browser
def test_a_vertical_picture_with_cover_fills_the_frame_edge_to_edge(served, docs, catalogue):
    run = served(two_colours(600, 1000), {"fit": "cover"})
    entry, fps = entry_of(docs, catalogue)
    run.seek(entry["start_frame"] + 3)
    state = run.state()
    assert state["tag"] == "IMG" and state["box"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}
    shot = run.shot()
    for x, y in ((2, 2), (1077, 2), (2, 1917), (1077, 1917)):
        p = at(shot, x, y)
        assert p[0] > 150 or p[2] > 150


@needs_browser
def test_the_same_project_rendered_twice_gives_the_same_frame_bytes(docs, catalogue, tmp_path, monkeypatch):
    picture = png(1200, 675, lambda x, y: (200 - x // 10, 60 + y // 8, 120 + (x + y) % 40))
    entry, fps = entry_of(docs, catalogue)
    shots = []
    for name in ("one", "two"):
        folder = tmp_path / name
        compose(docs, catalogue, folder, {SLOT: sha(picture)})
        run = Run(tmp_path / (name + "-browser"), project_files(folder, {SLOT: picture}), monkeypatch)
        try:
            rows = []
            for frame in (entry["start_frame"], (entry["start_frame"] + entry["end_frame"]) // 2, entry["end_frame"] - 1):
                run.seek(frame)
                rows.append(run.page.screenshot())
            shots.append(rows)
        finally:
            run.close()
    assert shots[0] == shots[1]


@needs_browser
def test_the_picture_is_decoded_before_frame_zero(served, docs, catalogue):
    run = served(two_colours(1200, 675))
    facts = run.page.evaluate("JSON.stringify((function(){var w=document.querySelector('iframe[data-hf-zone=frame]').contentWindow;"
                              "return {loads: w.__hfImageLoads.length, size: [w.__imgs.beat7.naturalWidth, w.__imgs.beat7.naturalHeight], complete: w.__imgs.beat7.complete};})())")
    assert json.loads(facts) == {"loads": 1, "size": [1200, 675], "complete": True}


@needs_browser
def test_a_screenshot_block_draws_the_picture_whole_as_a_card_with_a_push_in_on_the_hyperframes_page(served, docs, catalogue):
    run = served(two_colours(1200, 675), {"label": "The page on screen"}, block="oh:screenshot")
    entry, fps = entry_of(docs, catalogue)
    first, last = entry["start_frame"], entry["end_frame"] - 1
    run.seek(first)
    state = run.state()
    box = state["box"]
    assert box["w"] == 950 and abs(box["h"] - 534) <= 1 and box["x"] == 65
    shot = run.shot()
    assert at(shot, 10, 10) == THEME_BG and at(shot, 200, 960)[0] > 150 and at(shot, 900, 960)[2] > 150
    first_scale = run.page.evaluate("document.querySelector('iframe[data-hf-zone=frame]').contentDocument.getElementById('card').style.transform")
    run.seek(last)
    last_scale = run.page.evaluate("document.querySelector('iframe[data-hf-zone=frame]').contentDocument.getElementById('card').style.transform")
    assert first_scale == "scale(1)" and float(re.match(r"scale\(([0-9.]+)\)", last_scale).group(1)) > 1.03


def test_the_limits_of_the_three_places_that_hold_them_are_equal():
    import importlib.util
    import hyperframes
    spec = importlib.util.spec_from_file_location("hf_render_for_cutaway", K.RENDERER / "hyperframes-image" / "hf_render.py")
    image = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(image)
    assert C.MAX_ASSETS == hyperframes.ASSETS_MAX == image.ASSETS_MAX == 12
    assert image.ASSET_MAX_BYTES == DATA["limits"]["asset_max_bytes"]
    assert C.IMAGE_PREFIX == "../assets/" and image.ASSET_FILE.fullmatch("assets/beat7.png") and image.PNG_MAGIC == b"\x89PNG\r\n\x1a\n"
