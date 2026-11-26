"""The look of the cutaway (V9d): a hard cut, and a glass layout for a picture that is not vertical; the `oh:screenshot` card (moved here from test_hf_cutaway.py, PF-b2). The pictures are flat-colour PNGs
the test writes with zlib; the page is drawn by the host's headless browser (skipped without it)."""
from __future__ import annotations

import json
import re
import struct
import zlib

import pytest

import renderer_kit as K
import _blocks
import _cdp
import _frames
from _lint import lint
from _vocab import load_data

needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
TEMPLATE = "oh/cutaway/renderat.html"
PAGE = K.BLOCKS / "oh" / "cutaway" / "renderat.html"
DATA = load_data()
LOOKS = DATA["presets"]["cutaway"]["looks"]
THEME_BG = "#0B0F14"
THEME_RGB = tuple(int(THEME_BG[i:i + 2], 16) for i in (1, 3, 5))
COLORS = {"bg": THEME_BG, "text": "#FFFFFF", "muted": "#A8B0BC", "accent": "#FFC93C", "chip_fill": "#1B1F2A", "chip_text": "#FFE08A", "chip_border": "#FFC93C"}


def png(width, height, pixel) -> bytes:
    """A RGB PNG; `pixel(x, y)` gives (r, g, b)."""
    rows = []
    for y in range(height):
        rows.append(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


def two_colours(width, height, left=(200, 40, 40), right=(40, 60, 200)):
    return png(width, height, lambda x, y: left if x < width // 2 else right)


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


def draw(tmp_path, image, params=None, look=None, times=(0.5,), duration=2.0, shots=True):
    """Open the page on a served image and draw it at each time. Returns a list of (box, state, screenshot or None) per time."""
    serve, _ = _frames.load_templates([TEMPLATE])
    serve["/assets/pic.png"] = (image, "image/png")
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "chrome"), time_limit=120) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/" + TEMPLATE, {"colors": COLORS, "fonts": {}, "images": {"pic": _cdp.ORIGIN + "/assets/pic.png"}})
        payload = {"params": {"asset": "pic", **(params or {})}, "look": {**LOOKS, **(look or {})}, "zones": {}, "duration": duration}
        for t in times:
            page.frame(t, payload)
            state = page.evaluate("JSON.stringify({box: window.__box, img: (function(){var e=document.querySelector('#stage > *');"
                                  "return {tag: e.tagName, opacity: e.style.opacity, transform: e.style.transform};})(), "
                                  "chip: (document.getElementById('chip')||{style:{}}).style.opacity || null})")
            out.append((json.loads(state), page.screenshot() if shots else None))
        predominant = page.evaluate("window.__predominant(window.__imgs.pic)")
    return out, predominant


def test_the_preset_holds_the_cut_and_the_glass_values():
    assert LOOKS["transition"] == "cut"
    assert (LOOKS["glass_ratio_max"], LOOKS["glass_blur_px"], LOOKS["glass_tint_alpha"], LOOKS["glass_radius_px"]) == (0.8, 48, 0.45, 24)
    assert 40 <= LOOKS["glass_blur_px"] <= 60 and 0.4 <= LOOKS["glass_tint_alpha"] <= 0.5


def test_the_page_is_inside_the_determinism_lint():
    assert lint(PAGE.read_text(encoding="utf-8")) == []


@needs_browser
def test_a_landscape_picture_is_centred_inside_the_safe_margins_over_a_glass_background(tmp_path):
    (state, shot), = draw(tmp_path, two_colours(1200, 675))[0]
    box = state["box"]
    assert 65 <= box["x"] and box["x"] + box["w"] <= 1015 and box["w"] == 950
    assert abs((box["x"] + box["w"] / 2) - 540) <= 1 and abs((box["y"] + box["h"] / 2) - 960) <= 1
    shot = decode(shot)
    bg = tuple(int(THEME_BG[i:i + 2], 16) for i in (1, 3, 5))
    for x, y in ((10, 10), (1070, 10), (10, 1900), (1070, 1900), (540, 100), (540, 1800), (30, 960)):
        assert at(shot, x, y) != bg
    left, right = at(shot, 200, 960), at(shot, 900, 960)           # the picture itself, whole, unblurred
    assert left[0] > 150 and left[2] < 90 and right[2] > 150 and right[0] < 90


@needs_browser
def test_a_vertical_picture_with_cover_fills_the_frame_edge_to_edge(tmp_path):
    (state, shot), = draw(tmp_path, two_colours(600, 1000), {"fit": "cover"})[0]
    assert state["img"]["tag"] == "IMG" and state["box"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}
    shot = decode(shot)
    for x, y in ((2, 2), (1077, 2), (2, 1917), (1077, 1917)):
        p = at(shot, x, y)
        assert p[0] > 150 or p[2] > 150                                     # the picture's colours, never the theme background


@needs_browser
def test_a_square_ish_picture_gets_the_glass_layout(tmp_path):
    (state, _), = draw(tmp_path, two_colours(700, 670), shots=False)[0]
    assert state["img"]["tag"] == "CANVAS" and state["box"]["w"] == 950 and state["box"]["h"] == round(670 * 950 / 700)


@needs_browser
def test_a_vertical_picture_with_contain_gets_the_glass_layout(tmp_path):
    (state, _), = draw(tmp_path, two_colours(600, 1000), {"fit": "contain"}, shots=False)[0]
    assert state["img"]["tag"] == "CANVAS" and state["box"]["x"] >= 65 and state["box"]["x"] + state["box"]["w"] <= 1015
    assert state["box"]["y"] + state["box"]["h"] <= 1920


@needs_browser
def test_the_cut_shows_the_picture_at_full_opacity_with_no_offset_on_the_first_and_last_frame(tmp_path):
    frames, _ = draw(tmp_path, two_colours(1200, 675), {"label": "Aster Lane"}, times=(0.0, 1.0, 2.0 - 1 / 30), shots=False)
    for state, _ in frames:
        assert float(state["img"]["opacity"]) == 1.0 and state["img"]["transform"] == "translateX(0px) scale(1)"
        assert float(state["chip"]) == 1.0                                  # the label chip is there at once, with no fade


@needs_browser
def test_the_slide_stays_a_value_a_theme_may_pick(tmp_path):
    frames, _ = draw(tmp_path, two_colours(600, 1000), {"fit": "cover"}, look={"transition": "slide"}, times=(0.0, 1.0), shots=False)
    assert frames[0][0]["img"]["transform"] == "translateX(1080px) scale(1)" and frames[1][0]["img"]["transform"] == "translateX(0px) scale(1)"


@needs_browser
def test_the_same_page_and_picture_give_the_same_frame_bytes_twice(tmp_path):
    image = png(1200, 675, lambda x, y: (200 - x // 10, 60 + y // 8, 120 + (x + y) % 40))
    a, pa = draw(tmp_path / "a", image, times=(0.0, 1.0))
    b, pb = draw(tmp_path / "b", image, times=(0.0, 1.0))
    assert [s for _, s in a] == [s for _, s in b] and pa == pb


@needs_browser
def test_the_predominant_colour_of_a_mostly_flat_picture_is_that_colour(tmp_path):
    flat = png(1200, 675, lambda x, y: (30, 160, 90) if x < 1000 else (240, 240, 240))
    _, colour = draw(tmp_path, flat, shots=False)
    r, g, b = (int(v) for v in colour[4:-1].split(","))
    assert abs(r - 30) <= 16 and abs(g - 160) <= 16 and abs(b - 90) <= 16


@needs_browser
def test_a_picture_with_nothing_but_white_has_no_predominant_colour(tmp_path):
    _, colour = draw(tmp_path, png(1200, 675, lambda x, y: (255, 255, 255)), shots=False)
    assert colour is None


@pytest.fixture(scope="module")
def catalogue():
    return _blocks.load_catalogue()


# ---------------------------------------------------------------- oh:screenshot (moved from test_hf_cutaway.py, PF-b2)

def draw_screenshot(tmp_path, image, params=None, times=(0.0,), duration=2.0):
    template = "oh/screenshot/renderat.html"
    serve, _ = _frames.load_templates([template])
    serve["/assets/pic.png"] = (image, "image/png")
    colors = {"bg": "#0B0F14", "text": "#FFFFFF", "muted": "#A8B0BC", "accent": "#FFC93C", "chip_fill": "#1B1F2A", "chip_text": "#FFE08A", "chip_border": "#FFC93C"}
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "chrome"), time_limit=120) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/" + template, {"colors": colors, "fonts": {}, "images": {"pic": _cdp.ORIGIN + "/assets/pic.png"}})
        payload = {"params": {"asset": "pic", **(params or {})}, "look": DATA["presets"]["cutaway"]["looks"], "zones": {}, "duration": duration}
        for t in times:
            page.frame(t, payload)
            state = page.evaluate("JSON.stringify({box: window.__box, card: document.getElementById('card').style.transform, chip: !!document.getElementById('chip')})")
            out.append((json.loads(state), decode(page.screenshot())))
    return out


@needs_browser
def test_a_landscape_picture_is_a_card_in_the_middle_over_the_themes_background_with_a_slow_push_in(tmp_path):
    (a, shot_a), (b, _) = draw_screenshot(tmp_path, two_colours(1200, 675), times=(0.0, 2.0 - 1 / 30))
    assert a["box"]["w"] == 950 and abs(a["box"]["h"] - 534) <= 1 and a["box"]["x"] == 65 and abs((a["box"]["y"] + a["box"]["h"] / 2) - 960) <= 1
    assert at(shot_a, 10, 10) == THEME_RGB and at(shot_a, 1070, 1900) == THEME_RGB                      # a backdrop in the theme's colour, not a glass layout
    assert at(shot_a, 200, 960)[0] > 150 and at(shot_a, 900, 960)[2] > 150
    assert a["card"] == "scale(1)" and float(re.match(r"scale\(([0-9.]+)\)", b["card"]).group(1)) > 1.03 and not a["chip"]


@needs_browser
def test_a_vertical_or_small_picture_is_shown_whole_never_cropped_and_never_more_than_twice_its_size(tmp_path):
    (tall, _), = draw_screenshot(tmp_path / "t", two_colours(600, 3000))
    assert tall["box"]["h"] == 1700 and tall["box"]["w"] == 340 and tall["box"]["h"] / tall["box"]["w"] == pytest.approx(3000 / 600, rel=0.01)
    (small, _), = draw_screenshot(tmp_path / "s", two_colours(100, 60))
    assert small["box"]["w"] == 200 and small["box"]["h"] == 120


@needs_browser
def test_the_label_chip_is_there_from_the_first_frame_in_a_hard_cut(tmp_path):
    (state, _), = draw_screenshot(tmp_path, two_colours(1200, 675), {"label": "Aster Lane"})
    assert state["chip"] is True


# ---------------------------------------------------------------- the block itself

def test_the_screenshot_block_is_a_cutaway_layout_with_the_cutaways_parameters(catalogue):
    shot, cut = catalogue["blocks"]["oh:screenshot"], catalogue["blocks"]["oh:cutaway"]
    assert (shot["kind"], shot["preset"], shot["band"], shot["may_cross_face"], shot["license"], shot["source"]) == ("layout", "cutaway", "frame", True, ["MIT"], "openhora")
    assert shot["params"] == cut["params"] and len(shot["samples"]) == 1 and shot["natural_duration"] == 1.5
    assert shot["use_when"] == "a document, a page or a screen is shown whole, framed, while the line is spoken"
    assert set(shot["implementations"]) == {"renderat"} and "ffmpeg" in _blocks.engines_of(catalogue, shot)
