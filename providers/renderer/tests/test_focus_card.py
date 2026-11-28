"""The picture card (video P4b): `oh:focus-card`, a first-contract layout page that shows a picture whole as a rounded card in the middle of the frame, with an optional
X or check stamp, over the speaker's own shot (blurred by the compose, see test_backdrop_compose.py). The page is a pure renderAt(t, data), passes the determinism lint and
keeps its card inside the side margins and the look's tallest height. Pictures are flat colours the tests write; drawing tests skip without the kit's Chromium."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import renderer_kit as K
import _blocks
import _cdp
import _frames
from _lint import lint
from _vocab import load_data, load_vocabulary
from test_cutaway_look import COLORS, THEME_RGB, at, decode, png

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
LOOKS = DATA["presets"]["focus_card"]["looks"]
BLOCKS = Path(K.BLOCKS)
PAGE = BLOCKS / "oh" / "focus-card" / "renderat.html"
REL = "oh/focus-card/renderat.html"
needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
GREY = (120, 120, 120)
SIDE = 65
DURATION = 3.0


def block() -> dict:
    return json.loads((PAGE.parent / "block.json").read_text(encoding="utf-8"))


def grey(w, h):
    return png(w, h, lambda x, y: GREY)


def test_the_page_passes_the_determinism_lint_and_names_its_preset_parameters_and_looks():
    html = PAGE.read_text(encoding="utf-8")
    assert lint(html) == [] and "innerHTML" not in html and "window.renderAt" in html
    assert re.search(r'<meta name="pv-preset" content="([^"]*)">', html).group(1) == "focus_card"
    assert set(re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1).split(",")) == {"asset", "label", "stamp", "backdrop"}
    assert "'solid'" not in html and "P.backdrop" not in html          # the page is always transparent; the compose owns `blur` and `none` (2026-11-28: no solid colour)
    assert set(re.search(r'<meta name="pv-looks" content="([^"]*)">', html).group(1).split(",")) == set(LOOKS)
    assert set(re.findall(r"\bP\.([a-z0-9_]+)", html)) == {"asset", "label", "stamp"}
    assert set(re.findall(r"\bL\.([a-z0-9_]+)", html)) == set(LOOKS)


def test_check_block_accepts_the_block_and_it_is_the_review_preset_as_a_frame_band_layout():
    doc = block()
    _blocks.check_block(doc, "oh/focus-card/block.json", "oh", "focus-card", _blocks.read_pins()[1])
    assert (doc["name"], doc["kind"], doc["preset"], doc["band"], doc["may_cross_face"], doc["natural_duration"]) == ("oh:focus-card", "layout", "focus_card", "frame", True, 1.5)
    assert doc["license"] == ["MIT"] and doc["source"] == "openhora" and doc["implementations"] == {"renderat": "renderat.html"}
    assert doc["params"] == DATA["review_presets"]["focus_card"]["params"] == VOCAB["presets"]["focus_card"]["params"]
    assert doc["params"]["asset"] == {"type": "image", "required": True}          # a clip is drawn only by oh:cutaway
    assert len(doc["samples"]) >= 3 and {s.get("stamp") for s in doc["samples"]} >= {"x", "check"} and any(s.get("backdrop") == "none" for s in doc["samples"]) and not any(s.get("backdrop") == "solid" for s in doc["samples"])
    for sample in doc["samples"]:
        assert _blocks.check_params(doc, sample, VOCAB) == sample


def test_the_pages_defaults_equal_the_review_presets():
    html = PAGE.read_text(encoding="utf-8")
    params = DATA["review_presets"]["focus_card"]["params"]
    assert params["backdrop"]["default"] == "blur" and params["backdrop"]["values"] == ["blur", "none"]          # the page does not read it
    assert re.search(r"P\.stamp === undefined \? '([a-z]+)'", html).group(1) == params["stamp"]["default"] == "none"


def test_the_look_holds_the_picked_numbers_and_the_stamp_colours():
    assert (LOOKS["width_frac"], LOOKS["radius_px"], LOOKS["max_height"], LOOKS["push"]) == (0.6, 28, 1300, 0.04)
    assert (LOOKS["enter_seconds"], LOOKS["enter_from"], LOOKS["exit_seconds"]) == (0.22, 0.06, 0.18)
    assert (LOOKS["stamp_delay"], LOOKS["stamp_seconds"], LOOKS["stamp_from"], LOOKS["stamp_size"], LOOKS["stamp_stroke"], LOOKS["stamp_tilt"]) == (0.55, 0.4, 1.8, 0.26, 64, -8)
    assert (LOOKS["stamp_x_color"], LOOKS["stamp_check_color"]) == ("#FF3B30", "#34C759")      # the maintainer's answer (P4-5): a red X and a green check


def test_the_block_is_pinned_catalogued_and_mapped_by_the_ffmpeg_engine():
    cat = _blocks.load_catalogue()
    row = cat["blocks"]["oh:focus-card"]
    assert row["preset"] == "focus_card" and "ffmpeg" in _blocks.engines_of(cat, row)
    assert cat["engines"]["ffmpeg"]["presets"]["focus_card"] == "oh:focus-card"
    assert _blocks.resolve(cat, "ffmpeg", "focus_card", None, "beats.a1")["name"] == "oh:focus-card"
    assert {"oh/focus-card/block.json", "oh/focus-card/renderat.html"} <= set(_blocks.read_pins()[1])


# ---------------------------------------------------------------- drawing

def draw(tmp_path, image, params=None, times=(1.2,), duration=DURATION):
    """Open the page on a served image and draw it at each time. Returns a list of (box, screenshot bytes) per time."""
    serve, _ = _frames.load_templates([REL])
    serve["/assets/pic.png"] = (image, "image/png")
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "chrome"), time_limit=120) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/" + REL, {"colors": COLORS, "fonts": {}, "images": {"pic": _cdp.ORIGIN + "/assets/pic.png"}})
        payload = {"params": {"asset": "pic", **(params or {})}, "look": dict(LOOKS), "zones": {}, "duration": duration}
        for t in times:
            page.frame(t, payload)
            out.append((json.loads(page.evaluate("JSON.stringify(window.__box)")), page.screenshot()))
    return out


def alpha(shot, x, y):
    _, _, rows, bpp = shot
    assert bpp == 4
    return rows[y][x * bpp + 3]


def count(shot, test, box):
    """How many pixels of a 6-pixel grid inside the box pass `test(r, g, b)`."""
    _, _, rows, bpp = shot
    return sum(1 for y in range(box["y"], box["y"] + box["h"], 6) for x in range(box["x"], box["x"] + box["w"], 6) if test(*rows[y][x * bpp:x * bpp + 3]))


def reddish(r, g, b):
    return r > 200 and g < 110 and b < 110


def greenish(r, g, b):
    return g > 170 and r < 110 and b < 150


@needs_browser
def test_the_same_time_drawn_twice_gives_the_same_picture_and_the_entry_moves(tmp_path):
    shots = draw(tmp_path, grey(800, 1000), {"stamp": "x", "label": "Aster Lane"}, times=(1.2, 0.0, 1.2, 1.2))
    assert shots[0][1] == shots[2][1] == shots[3][1]          # pure in (t, data): the frames in between change nothing
    assert shots[1][1] != shots[0][1]


@needs_browser
def test_a_corner_is_transparent_for_blur_and_none(tmp_path):
    for backdrop, expect in (("blur", False), ("none", False)):
        ((_, shot),) = draw(tmp_path, grey(800, 1000), {"backdrop": backdrop})
        decoded = decode(shot)
        for x, y in ((3, 3), (1076, 3), (3, 1916), (1076, 1916)):
            if expect:
                assert at(decoded, x, y) == THEME_RGB and alpha(decoded, x, y) == 255
            else:
                assert alpha(decoded, x, y) == 0
    ((_, shot),) = draw(tmp_path, grey(800, 1000))          # no `backdrop` given: the default is blur
    assert alpha(decode(shot), 3, 3) == 0


@needs_browser
@pytest.mark.parametrize("w,h,expect", [(800, 1000, (648, 810)), (1200, 800, (648, 432)), (64, 64, (128, 128)), (400, 3000, (None, 1300))])
def test_the_card_stays_inside_the_side_margins_and_the_looks_tallest_height_and_is_centred(tmp_path, w, h, expect):
    ((box, shot),) = draw(tmp_path, grey(w, h))
    assert SIDE <= box["x"] and box["x"] + box["w"] <= 1080 - SIDE and box["h"] <= LOOKS["max_height"]
    if expect[0] is not None:
        assert (box["w"], box["h"]) == expect
    else:
        assert box["h"] == 1300
    assert abs(box["x"] + box["w"] / 2 - 540) <= 1 and abs(box["y"] + box["h"] / 2 - 960) <= 1
    decoded = decode(shot)
    assert at(decoded, 540, 960) != THEME_RGB and alpha(decoded, 540, 960) == 255                 # the picture is there
    assert alpha(decoded, 3, 960) == 0 and alpha(decoded, 1076, 960) == 0                         # and the card's own shadow is all that is painted beside it


@needs_browser
def test_the_stamp_is_drawn_only_when_asked_in_the_picked_colours_and_only_after_its_time(tmp_path):
    none, x, check = (draw(tmp_path, grey(800, 1000), {"stamp": s}, times=(0.3, 1.2)) for s in ("none", "x", "check"))
    box = none[0][0]
    assert none[0][1] == x[0][1] == check[0][1]                  # before `stamp_delay` (0.55 s): the three are one picture
    assert x[1][1] != none[1][1] and check[1][1] != none[1][1] and x[1][1] != check[1][1]
    assert count(decode(none[1][1]), reddish, box) == 0 and count(decode(none[1][1]), greenish, box) == 0
    assert count(decode(x[1][1]), reddish, box) > 20 and count(decode(x[1][1]), greenish, box) == 0
    assert count(decode(check[1][1]), greenish, box) > 20 and count(decode(check[1][1]), reddish, box) == 0
    assert alpha(decode(x[1][1]), 3, 3) == 0                     # the stamp stays on the card: the rest of the page is still transparent


@needs_browser
def test_a_frame_before_and_after_the_stamp_time_differ_and_the_x_is_drawn_stroke_by_stroke(tmp_path):
    shots = draw(tmp_path, grey(800, 1000), {"stamp": "x"}, times=(0.5, 0.7, 0.8, 1.5))
    box = shots[0][0]
    reds = [count(decode(s), reddish, box) for _, s in shots]
    assert reds[0] == 0 and 0 < reds[1] < reds[3] and reds[1] <= reds[2] <= reds[3]          # the first stroke, then both


@needs_browser
def test_the_label_is_drawn_and_a_missing_label_draws_no_chip(tmp_path):
    ((_, with_label),) = draw(tmp_path, grey(800, 1000), {"label": "Aster Lane"})
    ((_, without),) = draw(tmp_path, grey(800, 1000))
    assert with_label != without
