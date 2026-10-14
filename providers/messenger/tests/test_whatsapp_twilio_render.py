"""Offline tests of the rendering in providers/messenger/whatsapp-twilio.py: it uses the renderer both official WhatsApp providers
share (whatsapp_meta.py), which must agree with the Go renderer of providers/messenger/whatsapp/render.go on the shared corpus
(tests/whatsapp_render_corpus.json), at the 4096-character limit of that corpus, and give the same text under the 1600 limit
of a Twilio message body wherever the text fits.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_twilio_render.py
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import pytest

from whatsapp_cloud_kit import wc
from whatsapp_twilio_kit import SCRIPT, wt

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "whatsapp_render_corpus.json"
LIMIT = 1600
NOTE = "\n" + wt.CUT_NOTE


def expand(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(expand(p) for p in value)
    unit, count = value["repeat"]
    return unit * count


CASES = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_shared_renderer_gives_the_go_renderers_output_on_the_corpus_at_the_clouds_limit(case):
    got = wt.render_whatsapp(expand(case["in"]), 4096)
    want = case["want"]
    if isinstance(want, str):
        assert got == want
    else:
        assert len(got) == want["runes"] and hashlib.sha256(got.encode("utf-8")).hexdigest() == want["sha256"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_twilio_renderer_gives_the_same_text_when_it_fits_in_1600_and_a_cut_one_otherwise(case):
    text = expand(case["in"])
    got = wt.render_whatsapp_twilio(text)
    full = wt.render_whatsapp(text, 4096)
    assert len(got) <= LIMIT
    if len(full) <= LIMIT:
        assert got == full
    else:
        assert got.endswith(NOTE) or got.endswith(wt.CUT_NOTE)
        assert wc.render_whatsapp_cloud(text) == full           # and the cloud provider renders the same text as before


def test_the_two_providers_and_the_module_are_one_renderer():
    for case in CASES:
        text = expand(case["in"])
        assert wt.render_whatsapp(text, 4096) == wc.render_whatsapp_cloud(text)
    assert wt.render_whatsapp is wc.render_whatsapp and wt.cut_rendered is wc.cut_rendered


def test_the_source_of_the_provider_and_the_shared_module_hold_no_invisible_or_non_ascii_character():
    for path in (SCRIPT, SCRIPT.with_name("whatsapp_meta.py")):
        assert path.read_text(encoding="utf-8").isascii(), path.name


def spans_of(text):
    return re.findall(r"`[^`\n]+`", text)


def test_the_cut_at_1600_never_falls_inside_a_code_span_or_a_fence():
    rng = random.Random(9)
    lines = ["word " * 30, "**bold** text", "text with `span of code` inside", "`/approve " + "a" * 70 + "`", "",
             "```\ncode **x**\nmore code\n```", "| a | b |\n| 1 | 2 |", "# Heading", "- item",
             "[l](https://example.com/" + "p" * 40 + ") link", "\U0001F600 emoji " * 10, "> quote"]
    for _ in range(300):
        text = "\n".join(rng.choice(lines) for _ in range(rng.randint(5, 200)))
        out = wt.render_whatsapp_twilio(text)
        assert len(out) <= LIMIT and "\x00" not in out
        if out.endswith(NOTE):
            body = out[:-len(NOTE)]
            assert body.count("```") % 2 == 0, "a cut fence is closed before the note"
            for span in spans_of(body):
                assert span.count("`") == 2


def test_a_text_within_the_limit_is_never_cut_and_the_limit_counts_the_rendered_text():
    assert wt.render_whatsapp_twilio("x" * LIMIT) == "x" * LIMIT
    assert wt.render_whatsapp_twilio("x" * (LIMIT + 1)).endswith(NOTE)


def test_the_effect_command_of_a_card_stays_byte_for_byte():
    command = "`python3 runtime/ops.py approve --path /srv/northwind-shop --id 12 --sha256 " + "ab" * 32 + "`"
    for text in (f"An effect waits.\n{command}", f"**Effect** ~~old~~ [link](https://example.com)\n{command}\n\n- bullet", command):
        assert command in wt.render_whatsapp_twilio(text)
