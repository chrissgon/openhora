"""Offline tests of render_whatsapp_cloud in providers/messenger/whatsapp-cloud.py: it must agree with the Go renderer of
providers/messenger/whatsapp/render.go on a shared corpus (tests/whatsapp_render_corpus.json, which the Go test reads too),
keep the effect command of a card byte for byte, and never cut inside a code span or a fence.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_cloud_render.py
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import pytest

from whatsapp_cloud_kit import wc

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "whatsapp_render_corpus.json"
GO_TEST = HERE.parent / "whatsapp" / "render_test.go"
LIMIT = 4096
NOTE = "\n" + wc.CUT_NOTE


def expand(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(expand(p) for p in value)
    unit, count = value["repeat"]
    return unit * count


CASES = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_python_renderer_gives_the_go_renderers_output_on_the_shared_corpus(case):
    got = wc.render_whatsapp_cloud(expand(case["in"]))
    want = case["want"]
    if isinstance(want, str):
        assert got == want
    else:
        assert len(got) == want["runes"] and hashlib.sha256(got.encode("utf-8")).hexdigest() == want["sha256"]


def test_the_corpus_is_shared_with_the_go_test_and_holds_the_cases_where_the_two_languages_could_differ():
    assert "whatsapp_render_corpus.json" in GO_TEST.read_text(encoding="utf-8")
    names = {c["name"] for c in CASES}
    assert len(CASES) >= 80
    assert {"nbsp after stars", "nbsp before stars", "vertical tab in bold", "separator controls not trimmed", "nel trimmed",
            "ideographic space table", "crlf", "nul removed", "fence cut", "cut lines", "span in long line"} <= names
    for case in CASES:                                   # the file is ASCII: no invisible character can hide in it
        assert CORPUS.read_text(encoding="ascii")


def test_the_regular_expressions_are_ascii_and_spell_out_the_whitespace_go_knows():
    for pattern in (wc.HEADING, wc.LINK, wc.BOLD, wc.STRIKE):
        assert pattern.flags & re.ASCII
    assert "\\s" not in wc.LINK.pattern and "\\s" not in wc.BOLD.pattern and "\\s" not in wc.STRIKE.pattern
    assert "\x0b" not in "\t\n\f\r " and wc.go_strip("\x1c|\x1c") == "\x1c|\x1c" and wc.go_strip("\xa0|\xa0") == "|"


def test_the_source_holds_no_invisible_character_or_any_non_ascii_character():
    source = (HERE.parent / "whatsapp-cloud.py").read_text(encoding="utf-8")
    assert source.isascii()


def test_a_no_break_space_after_the_stars_is_text_so_the_mark_converts_as_in_go():
    assert wc.render_whatsapp_cloud("**" + chr(0xA0) + "x**") == "*" + chr(0xA0) + "x*"
    assert wc.render_whatsapp_cloud("** x**") == "** x**"


def test_the_effect_command_of_a_card_stays_byte_for_byte():
    command = "`python3 runtime/ops.py approve --path /srv/northwind-shop --id 12 --sha256 " + "ab" * 32 + "`"
    for text in (f"An effect waits.\n{command}", f"**Effect** ~~old~~ [link](https://example.com)\n{command}\n\n- bullet", command):
        assert command in wc.render_whatsapp_cloud(text)
    tricky = "`a **b** ~~c~~ [d](e) # f | g |`"
    assert wc.render_whatsapp_cloud("x " + tricky + " **y**") == "x " + tricky + " *y*"


def spans_of(text):
    return re.findall(r"`[^`\n]+`", text)


def test_the_cut_never_falls_inside_a_code_span_or_a_fence_and_stays_within_the_limit():
    rng = random.Random(8)
    lines = ["word " * 30, "**bold** text", "text with `span of code` inside", "`/approve " + "a" * 70 + "`", "",
             "```\ncode **x**\nmore code\n```", "| a | b |\n| 1 | 2 |", "# Heading", "- item",
             "[l](https://example.com/" + "p" * 40 + ") link", "\U0001F600 emoji " * 10, "> quote"]
    for _ in range(300):
        text = "\n".join(rng.choice(lines) for _ in range(rng.randint(5, 400)))
        out = wc.render_whatsapp_cloud(text)
        assert len(out) <= LIMIT
        if out.endswith(NOTE):
            body = out[:-len(NOTE)]
            assert body.count("```") % 2 == 0, "a cut fence is closed before the note"
            assert out.count("`") == 0 or all(span in body for span in spans_of(body))
            for span in spans_of(body):
                assert span.count("`") == 2
        assert "\x00" not in out


def test_a_text_within_the_limit_is_never_cut_and_the_limit_counts_the_rendered_text():
    assert wc.render_whatsapp_cloud("x" * LIMIT) == "x" * LIMIT
    assert wc.render_whatsapp_cloud("x" * (LIMIT + 1)).endswith(NOTE)
    longer = "[a](https://example.com/aaaaaaaaaa) " * 200       # rendering makes it longer than the raw text
    assert len(longer) > LIMIT - 1000 and len(wc.render_whatsapp_cloud(longer)) <= LIMIT


def test_a_line_that_is_the_whole_text_and_longer_than_the_limit_is_cut_before_a_span_it_would_split():
    span = "`" + "s" * 80 + "`"
    out = wc.render_whatsapp_cloud("y" * (LIMIT - 60) + " " + span + " tail")
    assert span not in out and "`" not in out and out.endswith(NOTE) and len(out) <= LIMIT


def test_the_zero_width_space_in_a_table_cell_fence_is_a_real_character_written_as_a_number():
    out = wc.render_whatsapp_cloud("| a |\n| ```x``` |")
    assert "``" + chr(0x200B) + "`x``" + chr(0x200B) + "`" in out
