"""Advice rows in a delivery (video P0b; runtime/deliver_document.py `advice`, `ADVICE_WORDS`, `advice_sentence`; runtime/step_media.py `_advice`): the closed rows the renderer
returns reach the delivery document, its body and its card, the host says the sentence from a closed table, a wrong row is refused, and a delivery with no advice keeps the
document, the hash and the body it always had. Offline; every value is made up here.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_deliver_advice.py
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import steps, step_media  # noqa: F401

dd = st.load("deliver_document")
cap = st.load("captions")
phrases = st.load("phrases")
REPO = Path(__file__).resolve().parents[2]

VIDEO_SHA = hashlib.sha256(b"northwind render").hexdigest()
DIGEST = hashlib.sha256(b"the document").hexdigest()
POST = "docs/marketing/content/aster-lane-launch.md"
PT = {"language": "pt-BR"}
ROWS = [{"code": "caption_below_line", "value": 1580.5, "default": 1560, "count": 2, "ids": ["c1", "c3"]},
        {"code": "punch_short", "value": 0.3, "default": 0.4, "count": 1},
        {"code": "text_over_default", "value": 30, "default": 24, "count": 1, "ids": ["b2"]}]


def make(advice=()):
    video = {"name": f"render-{VIDEO_SHA[:12]}.mp4", "sha256": VIDEO_SHA, "size": 12_345_678, "duration_ms": 31_000}
    return dd.build(task=12, recording="0123456789abcdef", platform="instagram", post=POST, video=video, cover=None, verify_platform="instagram",
                    preview={"sha256": VIDEO_SHA, "size": 12_345_678, "from_sha256": VIDEO_SHA}, advice=advice)


def renderer_codes():
    text = (REPO / "providers" / "renderer" / "_advice.py").read_text(encoding="utf-8")
    block = text.split("CODES = {", 1)[1].split("}", 1)[0]
    return re.findall(r'"([a-z_]+)": \(', block)


def test_a_delivery_with_no_advice_has_the_document_the_body_and_the_card_it_always_had():
    doc = make()
    assert "advice" not in doc and "advice" not in dd.summary(doc) and make(advice=[]) == doc
    assert not any("ADVICE" in k for k, _ in dd.card_lines(doc, DIGEST)) and "Advice" not in dd.body(doc, DIGEST)
    assert make(advice=()) == doc


def test_the_rows_reach_the_document_the_body_the_card_and_the_summary():
    doc = make(ROWS)
    dd.check(doc)
    assert doc["advice"] == ROWS and dd.summary(doc)["advice"] == 3
    lines = dd.body(doc, DIGEST).splitlines()
    assert lines[-5:-2] == [dd.advice_sentence(r) for r in ROWS] and lines[-2].startswith("Delivery document sha256") and lines[-1] == dd.CLOSING
    assert "Advice: Captions reach 1580.5 px, below the usual line at 1560 px, where the app's buttons may cover them." in lines
    assert "Advice: A text has 30 characters, more than the 24 its animation was made for; it may be cut or shrink." in lines
    card = dd.card_lines(doc, DIGEST)
    assert phrases.card_valid(card) and phrases.card_text(card) == dd.body(doc, DIGEST)
    keys = [k for k, _ in card if "ADVICE" in k]
    assert keys == ["CARD_VIDEO_ADVICE_CAPTION_BELOW_LINE", "CARD_VIDEO_ADVICE_PUNCH_SHORT", "CARD_VIDEO_ADVICE_TEXT_OVER_DEFAULT"]
    assert all(isinstance(v, str) for _, fields in card for v in fields.values())


def test_in_portuguese_the_card_says_the_rows_in_words():
    text = phrases.card_text(dd.card_lines(make(ROWS), DIGEST), PT)
    assert "Conselho: as legendas chegam a 1580.5 px, abaixo da linha de costume em 1560 px" in text and "Advice" not in text
    assert "Conselho: um zoom de impacto dura 0.3 s, menos que os 0.4 s de costume." in text


def test_every_code_has_a_sentence_and_a_phrase_in_both_languages_and_the_english_phrase_is_the_body_line():
    assert sorted(dd.ADVICE_WORDS) == sorted(renderer_codes()) and len(dd.ADVICE_WORDS) == 16
    for code in dd.ADVICE_WORDS:
        row = {"code": code, "value": 7, "default": 3.5, "count": 2}
        key = dd.advice_key(row)
        assert phrases.text(key, None, value="7", default="3.5", count="2") == dd.advice_sentence(row)
        assert phrases.text(key, PT, value="7", default="3.5", count="2").startswith("Conselho: ")
        assert phrases.TABLE["pt-BR"][key] != phrases.TABLE[phrases.DEFAULT][key]
    part_en = json.loads((REPO / "runtime" / "phrases_parts" / "p0b.en.json").read_text(encoding="utf-8"))["table"]
    part_pt = json.loads((REPO / "runtime" / "phrases_parts" / "p0b.pt-BR.json").read_text(encoding="utf-8"))["table"]
    assert sorted(part_en) == sorted(part_pt) == sorted(dd.advice_key({"code": c}) for c in dd.ADVICE_WORDS)


def test_numbers_are_written_whole_or_with_one_decimal():
    assert dd.advice_number(30) == "30" and dd.advice_number(30.0) == "30" and dd.advice_number(0.3) == "0.3" and dd.advice_number(1580.55) in ("1580.5", "1580.6")


@pytest.mark.parametrize("rows", [[], "x", [{"code": "made_up", "value": 1, "default": 1, "count": 1}],
                                  [{"code": "punch_short", "value": 1, "default": 1}],
                                  [{"code": "punch_short", "value": 1, "default": 1, "count": 0}],
                                  [{"code": "punch_short", "value": True, "default": 1, "count": 1}],
                                  [{"code": "punch_short", "value": float("inf"), "default": 1, "count": 1}],
                                  [{"code": "punch_short", "value": 1, "default": 1, "count": 1, "extra": 1}],
                                  [{"code": "punch_short", "value": 1, "default": 1, "count": 1, "ids": ["B"]}],
                                  [{"code": "punch_short", "value": 1, "default": 1, "count": 1, "ids": ["b%d" % k for k in range(13)]}],
                                  [{"code": "punch_short", "value": 1, "default": 1, "count": 1}, {"code": "aside_repeated", "value": 2, "default": 1, "count": 1}],
                                  [{"code": "punch_short", "value": 1, "default": 1, "count": 1}] * 2])
def test_an_advice_that_is_not_closed_sorted_rows_of_the_closed_codes_is_refused(rows):
    doc = make()
    doc["advice"] = rows
    with pytest.raises(ValueError):
        dd.check(doc)


# ---------------------------------------------------------------- the step reads the renderer's rows

def test_the_step_takes_closed_rows_sorted_and_nothing_else():
    assert step_media._advice({}) == [] and step_media._advice({"advice": None}) == []
    assert step_media._advice({"advice": list(reversed(ROWS))}) == sorted(ROWS, key=lambda r: r["code"])
    assert step_media._advice({"advice": [{"code": "punch_short", "value": 0.3, "default": 0.4, "count": 1}]})[0].get("ids") is None
    assert tuple(step_media.ADVICE_CODES) == tuple(sorted(renderer_codes())) and set(step_media.ADVICE_CODES) == set(dd.ADVICE_WORDS)


@pytest.mark.parametrize("bad", ["x", {"a": 1}, [{"code": "made_up", "value": 1, "default": 1, "count": 1}], [dict(ROWS[0]), dict(ROWS[0])],
                                 [dict(ROWS[0], count=0)], [dict(ROWS[0], count=True)], [dict(ROWS[0], value="1")], [dict(ROWS[0], value=float("nan"))],
                                 [dict(ROWS[0], ids=["BAD"])], [dict(ROWS[0], ids="c1")], [dict(ROWS[0], extra=1)], ["x"],
                                 [dict(ROWS[0], code=c) for c in ("a" * k for k in range(1, 26))]])
def test_the_step_refuses_a_row_that_is_not_closed_as_provider_output_invalid(bad):
    with pytest.raises(steps.StepFailure) as caught:
        step_media._advice({"advice": bad})
    assert caught.value.code == "provider_output_invalid"


# ---------------------------------------------------------------- the ceilings of the review

def test_the_animation_ids_run_from_a1_to_a99():
    for ok in ("a1", "a9", "a10", "a99"):
        assert cap.ANIMATION_ID.fullmatch(ok)
    for bad in ("a0", "a01", "a100", "a", "b1"):
        assert not cap.ANIMATION_ID.fullmatch(bad)


def test_the_ceilings_are_the_renderers_and_the_usual_count_is_the_vocabulary_default():
    text = (REPO / "providers" / "renderer" / "_edl.py").read_text(encoding="utf-8")
    assert int(re.search(r"^BEATS_CEILING = (\d+)", text, re.M).group(1)) == cap.BEATS_CEILING == 99
    assert int(re.search(r"^PUNCHES_CEILING = (\d+)", text, re.M).group(1)) == 99
    assert cap.ANIMATIONS_MAX == 99 and dd.LEFT_OUT_MAX == cap.EFFECTS_MAX + 2 * cap.BEATS_CEILING
    vocabulary = json.loads((REPO / "shared" / "references" / "video-presets.json").read_text(encoding="utf-8"))
    assert cap.BEATS_MAX == vocabulary["limits"]["beats_max"] == 12
