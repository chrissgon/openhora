"""The keyword slab (video P2c): `oh:keyword-slab`, a first-contract block that draws one short keyword on a solid slab of colour. The page is a pure
renderAt(t, data), passes the determinism lint, keeps its slab inside the card band, breaks a phrase into at most two lines when that gives a larger type,
and leaves the ffmpeg engine's keyword default as it was (`hf:spring-pop`). Every text here is invented; drawing tests skip without the kit's Chromium."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import renderer_kit as K
import _blocks
import _cdp
import _frames
import _layout
import _lint
from _vocab import load_data

DATA = load_data()
BLOCKS = Path(K.BLOCKS)
SLAB = BLOCKS / "oh" / "keyword-slab"
REL = "oh/keyword-slab/renderat.html"
needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
FACE = {"x": 240, "y": 700, "w": 600, "h": 480}
NBSP = " "


def block() -> dict:
    return json.loads((SLAB / "block.json").read_text(encoding="utf-8"))


def test_the_page_passes_the_determinism_lint_and_names_its_preset_and_parameters():
    html = (SLAB / "renderat.html").read_text(encoding="utf-8")
    assert _lint.lint(html) == []
    assert 'name="pv-preset" content="keyword"' in html and 'name="pv-params" content="text,color"' in html and "dataset.zone = 'card'" in html
    assert "window.renderAt" in html


def test_check_block_accepts_the_block_and_it_is_the_keyword_without_the_icon():
    doc = block()
    _blocks.check_block(doc, "oh/keyword-slab/block.json", "oh", "keyword-slab", _blocks.read_pins()[1])
    assert (doc["name"], doc["kind"], doc["preset"], doc["band"], doc["may_cross_face"], doc["natural_duration"]) == ("oh:keyword-slab", "overlay", "keyword", "card", False, 1.0)
    assert doc["license"] == ["MIT"] and doc["source"] == "openhora" and doc["implementations"] == {"renderat": "renderat.html"}
    assert doc["params"] == {"text": {"type": "text", "max": 24, "required": True}, "color": {"type": "color"}}
    texts = [s["text"] for s in doc["samples"]]
    assert len(texts) == 3 and any(len(t) <= 4 for t in texts) and any(any(ord(c) > 127 for c in t) for t in texts)


def test_the_block_is_pinned_and_listed_for_the_ffmpeg_engine():
    cat = _blocks.load_catalogue()
    row = cat["blocks"]["oh:keyword-slab"]
    assert row["implementations"] == {"renderat": "renderat.html"}
    assert row["preset"] == "keyword" and "ffmpeg" in _blocks.engines_of(cat, row)
    assert _blocks.resolve(cat, "ffmpeg", "keyword", "oh:keyword-slab", "beats.b1")["name"] == "oh:keyword-slab"
    pins = _blocks.read_pins()[1]
    assert {"oh/keyword-slab/block.json", "oh/keyword-slab/renderat.html"} <= set(pins)


def test_the_ffmpeg_engines_keyword_default_is_still_the_port():
    engine = json.loads((BLOCKS / "engines" / "ffmpeg.json").read_text(encoding="utf-8"))
    assert engine["presets"]["keyword"] == "hf:spring-pop"


# ---------------------------------------------------------------- drawing

def draw(tmp_path, texts_and_times, color=None):
    """For each (text, t): (state signature, boxes, screenshot bytes, the lines of the text, the font size in px)."""
    serve, _ = _frames.load_templates([REL])
    zones = _layout.zones(DATA, FACE)
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path)) as ch:
        pg = ch.new_page(1080, 1920)
        pg.open("/t/" + REL, {"colors": DATA["theme"]["colors"], "fonts": {}, "images": {}})
        for text, t in texts_and_times:
            params = {"text": text} if color is None else {"text": text, "color": color}
            r = pg.frame(t, {"params": params, "zones": zones, "duration": 1.4})
            lines = pg.evaluate("document.getElementById('txt').textContent")
            size = pg.evaluate("parseFloat(document.getElementById('card').style.fontSize)")
            out.append((r["html"], r["boxes"], pg.screenshot(), lines, size))
    return out, zones


@needs_browser
def test_at_each_sample_and_at_24_characters_the_slab_stays_inside_the_card_band(tmp_path):
    texts = [s["text"] for s in block()["samples"]] + ["x" * 24, "Name every dollar today"]
    drawn, zones = draw(tmp_path, [(text, 0.8) for text in texts])
    top, bottom = zones["card"]
    for (_, boxes, _, _, _), text in zip(drawn, texts):
        assert len(boxes) == 1 and boxes[0]["zone"] == "card", text
        b = boxes[0]
        assert top <= b["y"] and b["y"] + b["h"] <= bottom and 0 <= b["x"] and b["x"] + b["w"] <= 1080, (text, b, zones)


@needs_browser
def test_the_same_time_drawn_twice_gives_the_same_picture_and_the_entry_moves(tmp_path):
    drawn, _ = draw(tmp_path, [("Name every dollar", 0.8), ("Name every dollar", 0.0), ("Name every dollar", 0.8), ("Name every dollar", 0.8)])
    assert drawn[0][2] == drawn[2][2] == drawn[3][2]          # pure in (t, data): the frames in between change nothing
    assert drawn[0][0] == drawn[2][0]
    assert drawn[1][2] != drawn[0][2] or drawn[1][0] != drawn[0][0]      # t = 0 and t after the entry differ


@needs_browser
def test_a_24_character_phrase_with_spaces_is_on_two_lines_with_a_type_at_least_as_large_as_the_one_line_fit(tmp_path):
    phrase = "Name every dollar today"
    assert len(phrase) <= 24 and " " in phrase
    drawn, _ = draw(tmp_path, [(phrase, 0.8), (phrase.replace(" ", NBSP), 0.8)])
    (_, _, _, two_text, two_size), (_, _, _, one_text, one_size) = drawn
    assert "\n" in two_text and two_text.count("\n") == 1 and two_text.replace("\n", " ") == phrase
    assert "\n" not in one_text
    assert two_size >= one_size
    left, right = two_text.split("\n")
    assert abs(len(left) - len(right)) <= 3                  # the split is at the space nearest the middle


@needs_browser
def test_one_word_stays_one_line_and_a_short_phrase_stays_on_one_line_when_two_would_not_be_larger(tmp_path):
    drawn, _ = draw(tmp_path, [("Promo\u00e7\u00e3o", 0.8), ("Go on", 0.8)])
    assert "\n" not in drawn[0][3]
    assert "\n" not in drawn[1][3]          # the one line wins a tie: at the largest start size both layouts are limited by the band, not by the width


@needs_browser
def test_a_colour_parameter_is_read_and_a_missing_one_takes_the_accent(tmp_path):
    drawn, _ = draw(tmp_path, [("Go", 0.8), ("Go", 0.8)], color=None)
    assert drawn[0][2] == drawn[1][2]
    other, _ = draw(tmp_path, [("Go", 0.8)], color="#2255ff")
    assert other[0][2] != drawn[0][2]
