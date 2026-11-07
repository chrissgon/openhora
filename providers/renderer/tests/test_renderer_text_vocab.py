"""Text hardening and the typed parameters: the renderer's hard limits on what a text or a parameter may hold.

Run: uv run --with pytest pytest providers/renderer/tests
"""
from __future__ import annotations

import sys
import unicodedata

import pytest

import renderer_kit as K  # noqa: F401  (puts the provider folder on the import path)
from _text import Refusal, clean_text, is_clean
from _vocab import check_color, check_params, load_data, load_vocabulary

VOCAB = load_vocabulary(str(K.VOCABULARY))


def refused(fn, *a, **k):
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


INJECTIONS = ["{\\pos(0,0)}x", "a\\Nb", "x;y", "it's", "%{eval:1}", "a\nb", "a\rb", "a\u2028b", "a\u202eb", "a\u200bb", "a\x00b", "a\tb"]


@pytest.mark.parametrize("text", INJECTIONS)
def test_every_injection_shape_comes_out_refused_or_is_plain_text(text):
    """A newline, a bidirectional override, a zero-width space, U+2028 and a tab are refused; the rest (a brace, a
    backslash, a semicolon, a quote, a percent) are plain text that the templates draw with textContent and that never
    reaches a filter graph or a subtitle file."""
    categories = {unicodedata.category(c) for c in text}
    if categories & {"Cc", "Cf", "Zl", "Zp"}:
        assert refused(clean_text, text, 40, "label").code == "forbidden_character"
    else:
        assert clean_text(text, 40, "label") == text


def test_text_is_nfc_bounded_and_the_refusal_never_echoes_it():
    assert clean_text("é", 5, "x") == "é"
    assert is_clean("é") and not is_clean("é")
    assert refused(clean_text, "x" * 41, 40, "x").code == "text_too_long"
    assert refused(clean_text, "   ", 40, "x").code == "empty_text"
    assert refused(clean_text, 5, 40, "x").code == "not_text"
    err = refused(clean_text, "secret-word\u202e", 40, "label")
    assert "secret" not in str(err) and err.field == "label"


def test_colours_are_a_palette_token_or_rrggbb():
    palette = VOCAB["palette"]
    assert check_color("accent", palette, "c") == "accent"
    assert check_color("#07b6f0", palette, "c") == "#07B6F0"
    for bad in ("red", "#FFF", "#GGGGGG", "rgba(0,0,0,1)", "var(--x)", "url(x)", "#12345678", 5, "accent; background:url(x)", "#07B6F0\n"):
        assert refused(check_color, bad, palette, "c").code == "bad_color", bad


def test_params_follow_the_vocabulary_and_nothing_else():
    assert check_params(VOCAB, "keyword", {"text": "Name it", "icon": "coin", "color": "#112233"}) == {"text": "Name it", "icon": "coin", "color": "#112233"}
    assert refused(check_params, VOCAB, "keyword", {"text": "x", "html": "<b>"}).code == "undeclared_param"
    assert refused(check_params, VOCAB, "keyword", {}).code == "missing_param"
    assert refused(check_params, VOCAB, "keyword", {"text": "x" * 25}).code == "text_too_long"
    assert refused(check_params, VOCAB, "keyword", {"text": "x", "icon": "skull"}).code == "bad_icon"
    assert refused(check_params, VOCAB, "keyword", {"text": "x", "start": 3}).code == "undeclared_param"   # a time is never a parameter
    assert refused(check_params, VOCAB, "explode", {}).code == "unknown_preset"
    assert refused(check_params, VOCAB, "keyword", "text").code == "params_not_object"


def test_items_figures_choices_and_slots():
    assert check_params(VOCAB, "list", {"items": "A | B | C"})["items"] == "A | B | C"
    assert refused(check_params, VOCAB, "list", {"items": "1 | 2 | 3 | 4 | 5"}).code == "too_many_items"
    assert refused(check_params, VOCAB, "list", {"items": "A |  | C"}).code == "empty_text"
    assert refused(check_params, VOCAB, "list", {"items": "A | " + "x" * 31}).code == "text_too_long"
    assert check_params(VOCAB, "number", {"value": "1.234,5", "label": "x"})["value"] == "1.234,5"
    for bad in ("-1", "1e5", "12 3", "abc"):
        assert refused(check_params, VOCAB, "number", {"value": bad, "label": "x"}).code == "bad_pattern", bad
    assert refused(check_params, VOCAB, "pip", {"asset": "beat7", "position": "left"}).code == "bad_choice"
    assert check_params(VOCAB, "pip", {"asset": "beat7", "position": "bottom"})["asset"] == "beat7"
    for bad in ("../../etc/passwd", "https://x.example/a.png", "a b", "", "Beat7", "x" * 40):
        assert refused(check_params, VOCAB, "cutaway", {"asset": bad}).code == "bad_slot", bad
    assert refused(check_params, VOCAB, "quote", {"text": "ok", "author": "x\u2029"}).code == "forbidden_character"


def test_the_renderers_data_covers_the_vocabulary_and_no_other_preset():
    data = load_data()
    assert set(data["presets"]) == set(VOCAB["presets"])
    assert set(data["theme"]["colors"]) == set(VOCAB["palette"])
    assert data["frame"]["width"] == 1080 and data["frame"]["height"] == 1920
