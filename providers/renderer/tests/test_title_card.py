"""The title card (video P4c): `oh:title-card`, a first-contract layout page that draws one keyword large on a full-screen card, over the speaker's own shot (blurred by the
compose, see test_backdrop_compose.py). Three styles (`a`, `b`, `c`: the maintainer's A, B and C of P4-6; c is the default), a backdrop of `blur` or `none` only (a solid colour was
removed on 2026-11-28). The page is a pure renderAt(t, data), passes the determinism lint, and keeps the keyword inside the safe side margins. Drawing tests skip without the
kit's Chromium. All texts are fictional."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import renderer_kit as K
import _blocks
import _cdp
import _edl
import _frames
from _lint import lint
from _vocab import load_data, load_vocabulary
from test_cutaway_look import COLORS, decode
from test_transitions_edl import beats_of, entry, synthetic_edl

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
LOOKS = DATA["presets"]["title_card"]["looks"]
BLOCKS = Path(K.BLOCKS)
PAGE = BLOCKS / "oh" / "title-card" / "renderat.html"
REL = "oh/title-card/renderat.html"
needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
SIDE = 65
DURATION = 2.0
FORTY = "Stop splitting every single purchase now"
ACCENTED = "Promo\u00e7\u00e3o s\u00f3 hoje, j\u00e1!"


def block() -> dict:
    return json.loads((PAGE.parent / "block.json").read_text(encoding="utf-8"))


def test_the_page_passes_the_determinism_lint_and_names_its_preset_parameters_and_looks():
    html = PAGE.read_text(encoding="utf-8")
    assert lint(html) == [] and "innerHTML" not in html and "window.renderAt" in html
    assert re.search(r'<meta name="pv-preset" content="([^"]*)">', html).group(1) == "title_card"
    assert set(re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1).split(",")) == {"text", "note", "style", "color", "backdrop"}
    assert set(re.search(r'<meta name="pv-looks" content="([^"]*)">', html).group(1).split(",")) == set(LOOKS)
    assert set(re.findall(r"\bP\.([a-z0-9_]+)", html)) == {"text", "note", "style", "color"}          # `backdrop` is the compose's: the page is always transparent
    assert set(re.findall(r"\bL\.([a-z0-9_]+)", html)) == set(LOOKS)
    assert set(re.findall(r"\bS\.([a-z0-9_]+)", html)) == set(LOOKS["styles"]["a"])
    assert "'solid'" not in html


def test_check_block_accepts_the_block_and_it_is_the_review_preset_as_a_frame_band_layout():
    doc = block()
    _blocks.check_block(doc, "oh/title-card/block.json", "oh", "title-card", _blocks.read_pins()[1])
    assert (doc["name"], doc["kind"], doc["preset"], doc["band"], doc["may_cross_face"]) == ("oh:title-card", "layout", "title_card", "frame", True)
    assert doc["license"] == ["MIT"] and doc["source"] == "openhora" and doc["implementations"] == {"renderat": "renderat.html"}
    assert doc["params"] == DATA["review_presets"]["title_card"]["params"] == VOCAB["presets"]["title_card"]["params"]
    assert VOCAB["presets"]["title_card"]["review_only"] is True and VOCAB["presets"]["title_card"]["main"] == "text"
    assert doc["params"]["text"] == {"type": "text", "max": 40, "required": True} and doc["params"]["note"] == {"type": "text", "max": 60}
    assert doc["params"]["style"] == {"type": "choice", "values": ["a", "b", "c"], "default": "c"}
    assert doc["params"]["backdrop"] == {"type": "choice", "values": ["blur", "none"], "default": "blur"}
    texts = [s["text"] for s in doc["samples"]]
    assert len(texts) >= 3 and len(min(texts, key=len).split()) == 1 and FORTY in texts and any(re.search(r"[^\x00-\x7f]", t) for t in texts)
    for sample in doc["samples"]:
        assert _blocks.check_params(doc, sample, VOCAB) == sample


def test_the_pages_defaults_equal_the_review_presets():
    html = PAGE.read_text(encoding="utf-8")
    params = DATA["review_presets"]["title_card"]["params"]
    assert re.search(r"P\.style === undefined \? '([a-z]+)'", html).group(1) == params["style"]["default"] == "c"
    assert params["backdrop"]["default"] == "blur"


def test_the_look_holds_the_picked_numbers_for_the_three_styles():
    common = {k: v for k, v in LOOKS.items() if k != "styles"}
    assert common == {"max_w": 930, "max_h": 1100, "start_size": 360, "enter_seconds": 0.28, "exit_seconds": 0.2, "rise_em": 0.18, "enter_scale": 0.08, "note_delay": 0.12}
    assert LOOKS["styles"] == {
        "a": {"caps": True, "fg": "accent", "note_style": "none", "note_color": "muted", "note_size": 0, "note_caps": False},
        "b": {"caps": False, "fg": "text", "note_style": "small", "note_color": "muted", "note_size": 54, "note_caps": False},
        "c": {"caps": True, "fg": "text", "note_style": "small", "note_color": "accent", "note_size": 50, "note_caps": True}}
    cfg = DATA["presets"]["title_card"]
    assert (cfg["anchor"], cfg["min_duration"], cfg["max_duration"], cfg["tail"], cfg["settled"], cfg["page_images"]) == ("window", 1.0, None, 0.3, 0.4, False)


def test_the_block_is_pinned_catalogued_and_mapped_by_the_ffmpeg_engine():
    cat = _blocks.load_catalogue()
    row = cat["blocks"]["oh:title-card"]
    assert row["preset"] == "title_card" and "ffmpeg" in _blocks.engines_of(cat, row)
    assert cat["engines"]["ffmpeg"]["presets"]["title_card"] == "oh:title-card"
    assert _blocks.resolve(cat, "ffmpeg", "title_card", None, "beats.a1")["name"] == "oh:title-card"
    assert {"oh/title-card/block.json", "oh/title-card/renderat.html"} <= set(_blocks.read_pins()[1])


def test_the_title_card_is_a_review_only_text_layout_a_script_cannot_name():
    shared = json.loads(K.VOCABULARY.read_text(encoding="utf-8"))
    assert "title_card" not in shared["presets"] and "title_card" in VOCAB["presets"]
    assert _edl.BACKDROPS == ("blur", "none")


def test_a_title_card_with_the_default_backdrop_blurs_its_frames_and_one_with_none_does_not():
    edl = synthetic_edl()
    tl = _edl.resolve_timeline(edl, beats_of(layouts=[entry("a1", "title_card", {"text": "Interest"}, 4, 9)]), VOCAB, DATA)
    (beat,) = tl["beats"]
    assert tl["blurs"] == [{"id": "a1", "start_frame": beat["start_frame"], "end_frame": beat["end_frame"]}]
    sharp = _edl.resolve_timeline(edl, beats_of(layouts=[entry("a1", "title_card", {"text": "Interest", "backdrop": "none"}, 4, 9)]), VOCAB, DATA)
    assert "blurs" not in sharp and len(sharp["beats"]) == 1


# ---------------------------------------------------------------- drawing

def draw(tmp_path, params, times=(1.2,), duration=DURATION):
    """Open the page and draw it at each time. Returns a list of (facts about the page, screenshot bytes) per time."""
    serve, _ = _frames.load_templates([REL])
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "chrome"), time_limit=120) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/" + REL, {"colors": COLORS, "fonts": {}, "images": {}})
        payload = {"params": params, "look": json.loads(json.dumps(LOOKS)), "zones": {}, "duration": duration}
        probe = ("(function () { const k = document.getElementById('kw'), n = document.getElementById('note'), a = k.getBoundingClientRect(), b = n.getBoundingClientRect();"
                 "return JSON.stringify({text: k.textContent, size: parseFloat(k.style.fontSize), color: k.style.color, caps: k.style.textTransform, opacity: k.style.opacity,"
                 "note: n.style.display === 'none' ? null : n.textContent, note_size: parseFloat(n.style.fontSize || '0'), note_color: n.style.color, note_caps: n.style.textTransform,"
                 "kw: [a.left, a.top, a.width, a.height], nb: [b.left, b.top, b.width, b.height]}); })()")
        for t in times:
            page.frame(t, payload)
            out.append((json.loads(page.evaluate(probe)), page.screenshot()))
    return out


def alpha(shot, x, y):
    _, _, rows, bpp = shot
    assert bpp == 4
    return rows[y][x * bpp + 3]


def count(shot, test):
    _, _, rows, bpp = shot
    return sum(1 for y in range(0, 1920, 8) for x in range(0, 1080, 8) if rows[y][x * bpp + 3] > 250 and test(*rows[y][x * bpp:x * bpp + 3]))


def whitish(r, g, b):
    return r > 235 and g > 235 and b > 235


def yellowish(r, g, b):          # the accent #FFC93C
    return r > 235 and 170 < g < 230 and b < 110


@needs_browser
def test_the_same_time_drawn_twice_gives_the_same_picture_and_the_entry_moves(tmp_path):
    shots = draw(tmp_path, {"text": "Interest", "note": "What nobody tells you"}, times=(1.2, 0.0, 1.2, 1.2))
    assert shots[0][1] == shots[2][1] == shots[3][1]          # pure in (t, data): the frames in between change nothing
    assert shots[1][1] != shots[0][1] and float(shots[1][0]["opacity"]) == 0.0


@needs_browser
@pytest.mark.parametrize("backdrop", ["blur", "none", None])
def test_every_corner_is_transparent_for_blur_none_and_the_default(tmp_path, backdrop):
    params = {"text": "Interest"} if backdrop is None else {"text": "Interest", "backdrop": backdrop}
    ((_, shot),) = draw(tmp_path, params)
    decoded = decode(shot)
    for x, y in ((3, 3), (1076, 3), (3, 1916), (1076, 1916)):
        assert alpha(decoded, x, y) == 0


@needs_browser
@pytest.mark.parametrize("text", ["Interest", FORTY, ACCENTED, "Go", "Name every dollar today before the month ends"])
@pytest.mark.parametrize("style", ["a", "b", "c"])
def test_the_keyword_stays_inside_the_safe_margins_and_the_looks_box_and_the_frame(tmp_path, text, style):
    ((facts, _),) = draw(tmp_path, {"text": text, "note": "A short line above it", "style": style})
    x, y, w, h = facts["kw"]
    assert SIDE <= x and x + w <= 1080 - SIDE and w <= LOOKS["max_w"] + 1 and h <= LOOKS["max_h"] + 1
    assert 0 <= y and y + h <= 1920 and facts["size"] <= LOOKS["start_size"]
    assert facts["text"].replace("\n", " ") == text
    if facts["note"] is not None:
        nx, ny, nw, nh = facts["nb"]
        assert SIDE <= nx and nx + nw <= 1080 - SIDE and ny + nh <= y + 1        # the note lies above the keyword, inside the margins


@needs_browser
def test_a_word_is_drawn_as_large_as_the_start_size_allows_and_a_phrase_on_two_lines_fills_its_box(tmp_path):
    ((word, _), (phrase, _)) = draw(tmp_path, {"text": "Rate"}) + draw(tmp_path / "b", {"text": "Pare de parcelar tudo"})
    assert "\n" not in word["text"] and word["size"] <= LOOKS["start_size"]
    assert phrase["text"].count("\n") == 1                                    # the larger type wins, so two lines
    one_line = draw(tmp_path / "c", {"text": "Pare de parcelar tudo"})[0][0]
    assert phrase["size"] >= 100 and phrase["kw"][3] <= LOOKS["max_h"] + 1 and one_line["kw"][2] <= LOOKS["max_w"] + 1
    assert phrase["text"].count("\n") == 1


@needs_browser
def test_a_tie_between_one_line_and_two_is_one_line(tmp_path):
    ((facts, _),) = draw(tmp_path, {"text": "A B"}, times=(1.2,))
    assert "\n" not in facts["text"]
    ((facts, _),) = draw(tmp_path / "b", {"text": "Aster"})
    assert "\n" not in facts["text"]


@needs_browser
def test_the_three_styles_set_capitals_colours_and_the_note_as_picked(tmp_path):
    params = {"text": "Interest", "note": "What nobody tells you"}
    a, b, c = (draw(tmp_path / s, dict(params, style=s))[0] for s in "abc")
    assert (a[0]["caps"], b[0]["caps"], c[0]["caps"]) == ("uppercase", "none", "uppercase")
    assert a[0]["note"] is None and b[0]["note"] == params["note"] and c[0]["note"] == params["note"]          # style a has no small line
    assert b[0]["note_size"] == 54 and c[0]["note_size"] == 50 and (b[0]["note_caps"], c[0]["note_caps"]) == ("none", "uppercase")
    assert count(decode(a[1]), yellowish) > 20 and count(decode(a[1]), whitish) == 0          # the keyword in the accent colour
    assert count(decode(b[1]), whitish) > 20 and count(decode(c[1]), whitish) > 20
    assert count(decode(c[1]), yellowish) > 5 and count(decode(b[1]), yellowish) == 0         # c: the note in the accent colour; b: the note in the muted one
    default = draw(tmp_path / "d", params)[0]
    assert default[1] == c[1]                                                                   # no `style` given: c


@needs_browser
def test_the_color_parameter_overrides_the_keyword_colour(tmp_path):
    ((facts, shot),) = draw(tmp_path, {"text": "Interest", "style": "b", "color": "#FF3B30"})
    assert facts["color"] in ("rgb(255, 59, 48)", "#ff3b30", "#FF3B30")


@needs_browser
def test_the_note_enters_later_than_the_keyword_and_both_fade_at_the_end(tmp_path):
    shots = draw(tmp_path, {"text": "Interest", "note": "What nobody tells you", "style": "c"}, times=(0.2, 1.0, 1.95, 2.0))
    note_opacity = [float(s[0]["opacity"]) for s in shots]
    assert note_opacity[0] > 0.8 and note_opacity[1] == 1.0                    # the keyword is in by 0.28 s
    assert note_opacity[2] < 0.5 and float(note_opacity[3]) == 0.0                    # fading over the last 0.2 s
    assert shots[0][0]["nb"][1] > shots[1][0]["nb"][1]                          # the note is still rising at 0.2 s (delayed 0.12 s)
