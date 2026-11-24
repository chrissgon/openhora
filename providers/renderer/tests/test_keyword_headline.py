"""The keyword's headline looks (V9g): a video picks `headline` (the theme's display font) or `headline-serif` (a look font) in its edit list's
`looks`; the keyword is then the spoken words in large stacked uppercase type under the face, in the accent colour, entering on its word with no
lead and no animation, and the caption is taken off its frames. The pill stays the default. Offline, on synthetic documents; the page tests use the
host's headless browser (skipped without it). Every name is fictional."""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zlib

import pytest

import renderer_kit as K
import _assets
import _cdp
import _edl
import _frames
import _hf_compose
import _layout
import _payload
import _render
from _text import Refusal
from _vocab import load_data, load_vocabulary

needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FPS = 30
COLORS = {"bg": "#0B0F14", "text": "#FFFFFF", "muted": "#A8B0BC", "accent": "#FFC93C", "chip_fill": "#1B1F2A", "chip_text": "#FFE08A", "chip_border": "#FFC93C"}
FACE = {"x": 240, "y": 300, "w": 600, "h": 560}


def refused(fn, *a, **k) -> Refusal:
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


def synthetic_edl(looks=None) -> dict:
    """28 words, one every half second (word i from 0.5 i + 0.1 to 0.5 i + 0.4 s), one kept range; captions of four words."""
    words = [{"index": i, "text": "word%d" % i, "start": round(0.5 * i + 0.1, 3), "end": round(0.5 * i + 0.4, 3)} for i in range(28)]
    words[9]["text"] = "habits"
    edl = {"schema_version": 2, "fps": FPS, "size": [1080, 1920], "kept": [[0, 450]], "out_frames": 450, "words": words,
           "captions": {"position": "bottom", "chunks": [[i, i + 3] for i in range(0, 28, 4)]}, "theme": {"colors": dict(COLORS), "fonts": {}},
           "face_box": dict(FACE), "source": {"has_audio": True}, "zoom": {"mode": "none", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}}
    if looks:
        edl["looks"] = dict(looks)
    return edl


def keyword_beats() -> dict:
    kw = {"id": "b1", "beat": 1, "preset": "keyword", "params": {"text": "Habits win"}, "word_from": 8, "word_to": 11, "score": 1.0}
    return {"schema_version": 1, "threshold": 0.6, "overlays": [kw], "layouts": [], "slots": [], "report": [], "unmatched": [], "fallbacks": []}


# ---------------------------------------------------------------- the data and the edit list

def test_the_pill_is_the_default_and_the_two_headlines_are_named_variants():
    assert DATA["presets"]["keyword"]["looks"] == {}
    variants = DATA["presets"]["keyword"]["variants"]
    assert set(variants) == {"headline", "headline-serif"}
    for name, v in variants.items():
        assert v["style"] == "headline" and v["replaces_caption"] is True and v["lead_seconds"] == 0, name
        assert 2 <= v["max_lines"] <= 4 and 0.8 <= v["width_share"] <= 0.92 and v["last_line_scale"] >= 1, name
    assert "font" not in variants["headline"]
    assert variants["headline-serif"]["font"] == "playfair-display-900" and variants["headline-serif"]["font_weight"] == 900
    assert "serif" in variants["headline-serif"]["font_fallback"]
    assert VOCAB["presets"]["keyword"]["params"]["text"]["max"] == 24          # the vocabulary is unchanged


def test_look_of_lays_the_variant_over_the_presets_looks():
    assert _payload.look_of(DATA, synthetic_edl(), "keyword") == {}
    look = _payload.look_of(DATA, synthetic_edl({"keyword": "headline-serif"}), "keyword")
    assert look["variant"] == "headline-serif" and look["font"] == "playfair-display-900" and look["style"] == "headline"
    assert _payload.look_of(DATA, synthetic_edl({"keyword": "headline"}), "cutaway") == DATA["presets"]["cutaway"]["looks"]


def test_the_check_takes_a_known_look_and_refuses_any_other():
    _edl.check_looks(DATA, {"keyword": "headline"})
    _edl.check_looks(DATA, {})
    for bad, field in (({"keyword": "neon"}, "looks.keyword"), ({"cutaway": "headline"}, "looks.cutaway"), ({"keyword": 3}, "looks.keyword"),
                       (["keyword"], "looks"), ({"../x": "headline"}, "looks.?")):
        err = refused(_edl.check_looks, DATA, bad)
        assert (err.code, err.field) == ("bad_look", field), bad


def test_base_writes_looks_only_when_given_and_the_check_reads_them():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    allow = _frames.font_allowlist()
    plain, _ = _edl.build_base(doc, analysis, DATA, allow)
    assert "looks" not in plain
    _edl.check_edl(plain, DATA, VOCAB, allow)
    picked, _ = _edl.build_base(doc, analysis, DATA, allow, looks={"keyword": "headline-serif"})
    assert picked["looks"] == {"keyword": "headline-serif"}
    _edl.check_edl(picked, DATA, VOCAB, allow)
    assert refused(_edl.build_base, doc, analysis, DATA, allow, looks={"keyword": "neon"}).code == "bad_look"
    picked["looks"] = {"keyword": "neon"}
    assert refused(_edl.check_edl, picked, DATA, VOCAB, allow).code == "bad_look"


# ---------------------------------------------------------------- the timeline

def test_a_headline_enters_on_its_word_and_takes_the_caption_off_its_frames():
    pill = _edl.resolve_timeline(synthetic_edl(), keyword_beats(), VOCAB, DATA)
    head = _edl.resolve_timeline(synthetic_edl({"keyword": "headline"}), keyword_beats(), VOCAB, DATA)
    word = int(round(4.6 * FPS))                                  # "habits", word 9, at 4.6 s
    assert pill["beats"][0]["start_frame"] == int(round((4.6 - 0.05) * FPS))     # the pill's 0.05 s lead for its pop
    b = head["beats"][0]
    assert b["start_frame"] == word
    covered = [c for c in head["captions"] if c["start_frame"] < b["end_frame"] and b["start_frame"] < c["end_frame"]]
    assert covered == []                                          # no caption on the headline's frames
    assert any(c["end_frame"] == b["start_frame"] for c in head["captions"])      # the chunk it interrupts runs up to it
    assert any(c["start_frame"] == b["end_frame"] for c in head["captions"])      # and the next one picks up after it
    assert sum(c["end_frame"] - c["start_frame"] for c in head["captions"]) == \
        sum(c["end_frame"] - c["start_frame"] for c in pill["captions"]) - (b["end_frame"] - b["start_frame"])


def test_caption_gaps_cuts_a_chunk_at_each_span_edge_and_drops_the_pieces_inside():
    chunks = [{"word_from": 0, "word_to": 3, "start_frame": 0, "end_frame": 40, "face": dict(FACE)},
              {"word_from": 4, "word_to": 7, "start_frame": 40, "end_frame": 80, "face": dict(FACE), "band": [1300, 1420]}]
    out = _layout.caption_gaps(chunks, [(30, 50)])
    assert [(c["word_from"], c["start_frame"], c["end_frame"], c.get("band")) for c in out] == [(0, 0, 30, None), (4, 50, 80, [1300, 1420])]
    assert _layout.caption_gaps(chunks, [(100, 120)])[0] is chunks[0]
    assert _layout.caption_gaps(chunks, [(0, 80)]) == []


# ---------------------------------------------------------------- the look font

def fonts_dir(tmp_path, with_row=True, tamper=False):
    folder = tmp_path / "fonts"
    shutil.copytree(_assets.fonts_dir(), folder)
    stand_in = (folder / "inter-800.woff2").read_bytes()          # a stand-in file for the serif: the test checks the wiring, not the face
    (folder / "stand-in.woff2").write_bytes(stand_in + (b"x" if tamper else b""))
    doc = json.loads((folder / "allowlist.json").read_text())
    if with_row:
        doc["look_fonts"] = [{"id": "playfair-display-900", "file": "stand-in.woff2", "sha256": hashlib.sha256(stand_in).hexdigest(), "weight": 900,
                              "family": "Stand In", "licence": "OFL-1.1", "licence_file": "Inter-OFL.txt", "source": "a test stand-in"}]
    (folder / "allowlist.json").write_text(json.dumps(doc))
    return str(folder)


def test_the_serif_look_falls_back_when_its_font_is_not_listed_and_says_so():
    serve, used, roles = _assets.load_look_fonts(DATA, synthetic_edl({"keyword": "headline-serif"}), DATA["limits"]["font_max_bytes"])
    assert _assets.look_font_allowlist() == {} and serve == {}
    assert used == {"look-keyword": "system default"}
    assert roles == {"look-keyword": {"weight": 900, "fallback": DATA["presets"]["keyword"]["variants"]["headline-serif"]["font_fallback"]}}
    assert _assets.load_look_fonts(DATA, synthetic_edl({"keyword": "headline"}), 1 << 20) == ({}, {}, {})
    assert _assets.load_look_fonts(DATA, synthetic_edl(), 1 << 20) == ({}, {}, {})


def test_a_listed_look_font_is_served_by_hash_and_named_in_the_pages_fonts(tmp_path):
    folder = fonts_dir(tmp_path)
    edl = synthetic_edl({"keyword": "headline-serif"})
    serve, used, roles = _assets.load_look_fonts(DATA, edl, DATA["limits"]["font_max_bytes"], folder)
    assert list(serve) == ["/fonts/look-keyword.woff2"] and used == {"look-keyword": "playfair-display-900"}
    edl["theme"]["fonts"] = {}
    urls = _render.font_urls_of(DATA, edl, serve, roles)
    assert urls["look-keyword"]["url"].endswith("/fonts/look-keyword.woff2") and urls["look-keyword"]["weight"] == 900
    bad = fonts_dir(tmp_path / "t", tamper=True)
    assert refused(_assets.load_look_fonts, DATA, edl, DATA["limits"]["font_max_bytes"], bad).code == "font_hash"


def test_a_theme_role_can_never_name_a_look_font(tmp_path):
    folder = fonts_dir(tmp_path)
    assert "playfair-display-900" not in _assets.font_allowlist(folder)


def test_the_hyperframes_engine_refuses_an_edit_list_with_a_look(tmp_path):
    err = refused(_hf_compose.write_page, DATA, synthetic_edl({"keyword": "headline"}), keyword_beats(), VOCAB, {}, str(tmp_path), FPS)
    assert (err.code, err.field) == ("look_not_on_engine", "edl.looks.keyword")


# ---------------------------------------------------------------- the page, in the host's browser

def draw(tmp_path, look, text="Small habits win", times=(0.0,), fonts=None, serve_extra=None, color=None):
    template = K.template_of("keyword")
    serve, _ = _frames.load_templates([template])
    serve.update(serve_extra or {})
    payload = {"params": {"text": text, **({"color": color} if color else {})}, "look": look, "zones": _layout.zones(DATA, FACE), "duration": 1.5}
    out = []
    with _cdp.Chrome(K.BROWSER, serve, str(tmp_path / "chrome"), time_limit=120) as chrome:
        chrome.start()
        page = chrome.new_page(1080, 1920)
        page.open("/t/" + template, {"colors": COLORS, "fonts": fonts or {}, "images": {}})
        for t in times:
            result = page.frame(t, payload)
            lines = page.evaluate("JSON.stringify(Array.from(document.querySelectorAll('#stack > div')).map(function (d) { var r = d.getBoundingClientRect();"
                                  " return {text: d.textContent, w: r.width, h: r.height, size: parseFloat(getComputedStyle(d).fontSize),"
                                  " transform: getComputedStyle(d).textTransform, family: getComputedStyle(d).fontFamily}; }))")
            out.append((result, json.loads(lines), page.screenshot()))
    return out


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


HEADLINE = _payload.look_of(DATA, {"looks": {"keyword": "headline"}}, "keyword")
SERIF = _payload.look_of(DATA, {"looks": {"keyword": "headline-serif"}}, "keyword")


@needs_browser
def test_the_headline_stacks_the_words_large_in_the_caption_band_under_the_face(tmp_path):
    (result, lines, _shot), = draw(tmp_path, HEADLINE)
    band = _layout.zones(DATA, FACE)["caption"]
    boxes = [b for b in result["boxes"] if b["w"] > 0]
    assert len(boxes) == 1 and boxes[0]["zone"] == "caption"           # the stack is the one measured box, in the caption zone
    box = boxes[0]
    assert band[0] <= box["y"] and box["y"] + box["h"] <= band[1]
    assert box["w"] <= 1080 * HEADLINE["width_share"] + 0.5 and abs(box["x"] + box["w"] / 2 - 540) <= 1
    assert _layout.face_hit(result["boxes"], FACE) is None and not _layout.caption_hit(box, {"caption": band})
    assert 2 <= len(lines) <= 4 and " ".join(l["text"] for l in lines) == "Small habits win"
    assert all(l["transform"] == "uppercase" for l in lines)
    assert lines[0]["size"] >= 120                                     # very large type, far above the caption's own
    assert lines[-1]["size"] == pytest.approx(lines[0]["size"] * HEADLINE["last_line_scale"], rel=0.01)
    assert "card" not in {b["zone"] for b in result["boxes"] if b["w"] > 0}


@needs_browser
def test_the_headline_is_in_the_accent_colour_with_no_box_and_does_not_move(tmp_path):
    shots = draw(tmp_path, HEADLINE, times=(0.0, 0.7, 1.45))
    assert shots[0][2] == shots[1][2] == shots[2][2]                   # no pop, no fade: the same frame from the first to the last
    shot = decode(shots[0][2])
    _, _, rows, bpp = shot
    band = _layout.zones(DATA, FACE)["caption"]
    accent = 0
    for y in range(band[0], band[1], 6):
        for x in range(100, 980, 6):
            r, g, b = rows[y][x * bpp:x * bpp + 3]
            a = rows[y][x * bpp + 3] if bpp == 4 else 255
            if a == 255 and abs(r - 255) < 4 and abs(g - 201) < 4 and abs(b - 60) < 4:
                accent += 1
    assert accent > 200                                                # glyph pixels in #FFC93C
    assert rows[band[0] - 40][540 * bpp + 3] == 0 if bpp == 4 else True      # nothing drawn above the band: no card, no border


@needs_browser
def test_a_long_keyword_fits_the_width_and_a_single_word_is_one_line(tmp_path):
    (result, lines, _), = draw(tmp_path, HEADLINE, text="Automation made simple")
    assert 2 <= len(lines) <= 4 and max(l["w"] for l in lines) <= 1080 * HEADLINE["width_share"] + 0.5
    (result, lines, _), = draw(tmp_path / "one", HEADLINE, text="Focus")
    assert len(lines) == 1 and lines[0]["size"] <= HEADLINE["max_font_px"]


@needs_browser
def test_the_serif_headline_uses_its_look_font_and_its_fallback(tmp_path):
    fallback = {"look-keyword": {"weight": 900, "fallback": SERIF["font_fallback"]}}
    (_, lines, _), = draw(tmp_path, SERIF, fonts=fallback)
    assert "Playfair Display" in lines[0]["family"] and "serif" in lines[0]["family"]
    folder = fonts_dir(tmp_path)
    serve, _used, roles = _assets.load_look_fonts(DATA, synthetic_edl({"keyword": "headline-serif"}), DATA["limits"]["font_max_bytes"], folder)
    fonts = {role: dict(spec, url=_cdp.ORIGIN + "/fonts/look-keyword.woff2") for role, spec in roles.items()}
    (_, lines, _), = draw(tmp_path / "served", SERIF, fonts=fonts, serve_extra=serve)
    assert lines[0]["family"].startswith("pv-look-keyword")
    (_, lines, _), = draw(tmp_path / "inter", HEADLINE)
    assert not lines[0]["family"].startswith("pv-look-keyword")       # the Inter headline uses the theme's display font
