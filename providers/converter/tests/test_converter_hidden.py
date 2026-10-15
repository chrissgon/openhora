"""Tests of the hidden-text flag of the converter (package P8, finding S9): the part of providers/converter/_inner.py that finds, in an
HTML page and in a PDF, text a person cannot see and a model reads. The HTML detection is the standard library's parser and runs
here whatever this machine has; the PDF detection reads the XML of poppler's pdftohtml, so its logic is tested on that XML (taken
from a real run of the image) and the run of the tool itself is skipped where this machine lacks it and exercised by the container
test (test_converter_docker.py). Fictional fixtures (providers/converter/tests/fixtures).

Run: uv run --with pytest==9.1.1 pytest providers/converter/tests/test_converter_hidden.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
INNER = HERE.parent / "_inner.py"


@pytest.fixture(scope="module")
def inner():
    spec = importlib.util.spec_from_file_location("converter_inner_hidden_under_test", INNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def page(body: str, head: str = "") -> str:
    return f"<!DOCTYPE html><html><head><title>t</title>{head}</head><body>{body}</body></html>"


# One snippet for each kind the detection names: the text is hidden for exactly that reason.
KINDS = {
    "display_none": '<p style="display:none">words</p>',
    "visibility_hidden": '<span style="visibility:hidden">words</span>',
    "hidden_attribute": "<div hidden>words</div>",
    "zero_size": '<p style="font-size:0">words</p>',
    "tiny_text": '<p style="font-size:1px">words</p>',
    "off_page": '<p style="position:absolute;left:-9999px">words</p>',
    "transparent": '<p style="opacity:0">words</p>',
    "white_on_white": '<p style="color:#fff">words</p>',
    "color_matched": '<div style="background:#336699"><span style="color:#336699">words</span></div>',
}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_each_kind_of_hidden_text_an_html_page_can_carry_is_found_once_and_named(inner, kind):
    found = inner.hidden_in_html(page(KINDS[kind]))
    assert found["examined"] is True and found["count"] == 1 and found["kinds"] == {kind: 1}
    assert len(found["hints"]) == 1 and found["hints"][0].startswith(kind) and "words" not in json.dumps(found), "no content is echoed"


@pytest.mark.parametrize("snippet,kind", [
    ('<div style="width:1px;height:1px;overflow:hidden">words</div>', "zero_size"),
    ('<div style="max-height:0;overflow:hidden">words</div>', "zero_size"),
    ('<p style="text-indent:-9999px">words</p>', "off_page"),
    ('<p style="position:fixed;top:-2000px">words</p>', "off_page"),
    ('<p style="color:rgba(255,255,255,1)">words</p>', "white_on_white"),
    ('<p style="color:white">words</p>', "white_on_white"),
    ('<font color="#fefefe">words</font>', "white_on_white"),
    ('<p style="color:rgba(0,0,0,0)">words</p>', "transparent"),
    ('<p style="color:transparent">words</p>', "transparent"),
    ('<table><tr><td bgcolor="#aa0000"><span style="color:#aa0000">words</span></td></tr></table>', "color_matched"),
    ('<p style="font-size:0.5pt">words</p>', "tiny_text"),
    ('<p style="visibility:collapse">words</p>', "visibility_hidden"),
])
def test_the_other_ways_to_write_the_same_hiding_are_found_too(inner, snippet, kind):
    found = inner.hidden_in_html(page(snippet))
    assert found["count"] == 1 and kind in found["kinds"], found


def test_a_style_block_hides_text_through_a_class_an_id_or_a_tag_and_a_style_attribute_wins_over_it(inner):
    head = "<style>.gone{display:none} #ghost{color:#fefefe} aside{visibility:hidden} .shown{display:none}</style>"
    body = ('<div class="gone">one</div><p id="ghost">two</p><aside>three</aside>'
            '<p class="shown" style="display:block">four, visible: the style attribute wins</p>')
    found = inner.hidden_in_html(page(body, head))
    assert found["count"] == 3 and found["kinds"] == {"display_none": 1, "visibility_hidden": 1, "white_on_white": 1}


def test_a_hidden_block_is_counted_once_however_much_text_it_holds_and_a_visible_child_of_a_hidden_colour_is_not_flagged(inner):
    body = ('<div style="display:none"><p>a</p><p>b</p><ul><li>c</li><li>d</li></ul></div>'
            '<div style="color:#fff"><p>flagged</p><p style="color:#000">visible again</p></div>')
    found = inner.hidden_in_html(page(body))
    assert found["count"] == 2 and found["kinds"] == {"display_none": 1, "white_on_white": 1}


def test_visible_text_is_never_flagged_whatever_it_looks_like(inner):
    body = ('<h1>Title</h1><p>Plain.</p><p style="color:#333333;font-size:12px">Dark grey.</p>'
            '<div style="background:#000;color:#fff"><b>Light on dark</b></div>'
            '<p style="font-size:2px;color:#000">two pixels, shown as it is: not under the limit</p>'
            '<p style="position:absolute;left:-10px">a little out of its box</p>'
            '<p style="opacity:0.5">half</p><p style="width:1px">no overflow clip: not hidden</p>'
            '<div style="background:url(x.png);color:#fff">on a picture: nothing is said</div>')
    found = inner.hidden_in_html(page(body))
    assert found == {"examined": True, "count": 0, "kinds": {}, "hints": []}


def test_what_a_converter_never_reads_is_not_flagged(inner):
    head = "<style>@media print { .p { display:none } }</style>"
    body = ('<p class="p">only a print rule hides this</p><script>var a = "script words"; </script><noscript>nojs words</noscript>'
            '<template><p style="display:none">template words</p></template><!-- comment words -->')
    found = inner.hidden_in_html(page(body, head + "<style>.q{display:none}</style>"))
    assert found["count"] == 0


def test_the_fixture_page_holds_fifteen_hidden_pieces_and_the_hints_name_a_kind_and_an_element_but_never_a_word(inner):
    html = (FIXTURES / "hidden.html").read_text(encoding="utf-8")
    found = inner.hidden_in_html(html)
    assert found["count"] == 15
    assert found["kinds"] == {"display_none": 2, "visibility_hidden": 1, "hidden_attribute": 1, "zero_size": 2, "tiny_text": 1,
                              "off_page": 2, "transparent": 1, "white_on_white": 3, "color_matched": 2}
    assert len(found["hints"]) == inner.HIDDEN_HINTS_MAX
    assert found["hints"][0] == "display_none in div element 11"
    dumped = json.dumps(found)
    for word in ("One", "Seven", "Twelve", "market", "paragraph", "block"):
        assert word not in dumped


def test_a_page_with_an_unclosed_head_and_unclosed_paragraphs_is_still_read(inner):
    html = ('<html><head><title>t</title><body><p style="display:none">one<p>two, visible<p style="color:#fff">three</body></html>')
    found = inner.hidden_in_html(html)
    assert found["count"] == 2 and found["kinds"] == {"display_none": 1, "white_on_white": 1}


def test_a_page_nested_far_deeper_than_the_walk_looks_does_not_fail(inner):
    found = inner.hidden_in_html("<div>" * 5000 + '<p style="display:none">words</p>' + "</div>" * 5000)
    assert found["examined"] is True and found["count"] == 1


def test_a_page_with_enormous_tag_names_keeps_its_hints_short_and_its_info_whole_so_the_host_can_read_it(inner):
    tag = "a" * 6000
    body = "".join(f'<{tag}{n} style="display:none">planted words {n}</{tag}{n}>' for n in range(5))
    found = inner.hidden_in_html(page(body))
    assert found["count"] == 5 and found["kinds"] == {"display_none": 5}
    assert len(found["hints"]) == 5 and all(len(h) <= inner.HINT_MAX and h.startswith("display_none in a") for h in found["hints"]), found["hints"]
    info = inner.bounded_info({"converter": "document", "kind": "html", "tool_versions": {}, "notes": [], "hidden_text": found})
    assert len(info) <= inner.INFO_CAP and json.loads(info)["hidden_text"]["count"] == 5
    assert "planted" not in info.decode("utf-8")


def test_the_hint_of_an_element_keeps_only_a_clean_short_tag_and_the_first_kinds(inner):
    owner = {"tag": "x<script>alert(1)</script>" + "y" * 100, "kinds": set(inner.HIDDEN_KINDS)}
    hint = inner.hint_of(owner, 12345678)
    assert len(hint) <= inner.HINT_MAX and "<" not in hint and ">" not in hint and "(" not in hint
    assert hint.startswith("display_none+visibility_hidden+hidden_attribute in xscriptalert")
    assert inner.hint_of({"tag": "<>", "kinds": {"off_page"}}, 3) == "off_page in x element 3"


def test_the_account_of_a_conversion_never_exceeds_its_cap_and_is_never_cut_in_the_middle(inner):
    found = {"examined": True, "count": 9, "kinds": {"display_none": 9}, "hints": ["display_none in p element %d" % n for n in range(10)]}
    info = inner.bounded_info({"converter": "document", "kind": "html", "tool_versions": {"pandoc": "p" * 100},
                               "notes": ["n" * 500 for _ in range(60)], "hidden_text": found})
    parsed = json.loads(info)
    assert len(info) <= inner.INFO_CAP and parsed["notes"] == [] and parsed["hidden_text"]["count"] == 9 and parsed["hidden_text"]["kinds"] == {"display_none": 9}
    with pytest.raises(inner.Failed):
        inner.bounded_info({"converter": "x" * (inner.INFO_CAP + 10)})


def test_a_title_or_a_head_that_is_never_closed_does_not_hide_the_page_from_the_scan(inner):
    for opening in ("<html><head><title>Unclosed title", "<html><head>", "<title>Unclosed"):
        found = inner.hidden_in_html(opening + '<p style="display:none">words</p><p>visible</p>')
        assert found["count"] == 1 and found["kinds"] == {"display_none": 1}, opening
    clean = inner.hidden_in_html('<title>Hidden-looking title</title><p style="color:#000">visible</p>')
    assert clean["count"] == 0, "text of a title is not read, and not flagged either"
    assert inner.hidden_in_html('<noscript><p style="display:none">words</p></noscript><p style="display:none">other</p>')["count"] == 1


# --- a PDF -------------------------------------------------------------------------------------------------------------------------

# pdftohtml -xml -zoom 1 on providers/converter/tests/fixtures/hidden.pdf, as the container's poppler printed it.
SHOWN = """<?xml version="1.0" encoding="UTF-8"?>
<pdf2xml producer="poppler" version="22.12.0">
<page number="1" position="absolute" top="0" left="0" height="792" width="612">
	<fontspec id="0" size="14" family="Helvetica" color="#000000"/>
	<fontspec id="1" size="14" family="Helvetica" color="#ffffff"/>
	<fontspec id="2" size="1" family="Helvetica" color="#000000"/>
	<fontspec id="3" size="14" family="Helvetica" color="#7f7f7f"/>
<text top="62" left="72" width="125" height="13" font="0">Visible heading text.</text>
<text top="82" left="72" width="138" height="13" font="1">WHITE injected words</text>
<text top="111" left="72" width="9" height="1" font="2">TINY injected words</text>
<text top="142" left="-899" width="131" height="13" font="0">OFFPAGE left words</text>
<text top="142" left="5000" width="139" height="13" font="0">OFFPAGE right words</text>
<text top="177" left="72" width="131" height="13" font="3">GRAY on gray words</text>
<text top="222" left="72" width="121" height="13" font="0"><b>Another</b> visible line.</text>
</page>
</pdf2xml>
"""
HIDDEN_TOO = SHOWN.replace('<text top="142" left="-899"', '<text top="122" left="72" width="191" height="13" font="0">INVISIBLE render mode words</text>\n'
                           '<text top="142" left="-899"')


def test_a_pdf_with_white_text_a_tiny_font_and_invisible_text_is_flagged_and_off_page_text_is_not(inner):
    found = inner.hidden_in_pdf(SHOWN, HIDDEN_TOO)
    assert found["examined"] is True and found["count"] == 3
    assert found["kinds"] == {"tiny_text": 1, "white_on_white": 1, "invisible_text": 1}
    assert found["hints"] == ["tiny_text on page 1 count 1", "white_on_white on page 1 count 1", "invisible_text on page 1 count 1"]
    assert "words" not in json.dumps(found), "no content is echoed"


def test_a_pdf_with_nothing_hidden_is_examined_and_clean_and_a_gray_on_gray_match_is_not_seen(inner):
    clean = SHOWN.replace('font="1">WHITE injected words', 'font="0">WHITE injected words').replace('font="2">TINY', 'font="0">TINY')
    assert inner.hidden_in_pdf(clean, clean) == {"examined": True, "count": 0, "kinds": {}, "hints": []}


def test_a_piece_both_tiny_and_white_counts_once_with_both_kinds_and_the_pages_are_told_apart(inner):
    xml = ('<page number="1" position="absolute" top="0" left="0" height="792" width="612">\n'
           '<fontspec id="0" size="1" family="X" color="#fdfdfd"/>\n<fontspec id="1" size="14" family="X" color="#ffffff"/>\n'
           '<text top="82" left="72" width="9" height="1" font="0">both words</text>\n</page>\n'
           '<page number="2" position="absolute" top="0" left="0" height="792" width="612">\n'
           '<text top="82" left="72" width="138" height="13" font="1">second page words</text>\n</page>\n')
    found = inner.hidden_in_pdf(xml, xml)
    assert found["count"] == 2 and found["kinds"] == {"tiny_text": 1, "white_on_white": 2}
    assert found["hints"] == ["tiny_text on page 1 count 1", "white_on_white on page 1 count 1", "white_on_white on page 2 count 1"]


def test_the_hint_list_is_cut_at_its_limit(inner):
    pages = "".join(f'<page number="{n}" position="absolute" top="0" left="0" height="792" width="612">\n'
                    f'<fontspec id="{n}" size="14" family="X" color="#ffffff"/>\n'
                    f'<text top="82" left="72" width="138" height="13" font="{n}">w{n}</text>\n</page>\n' for n in range(1, 30))
    found = inner.hidden_in_pdf(pages, pages)
    assert found["count"] == 29 and len(found["hints"]) == inner.HIDDEN_HINTS_MAX


def test_the_info_a_conversion_prints_carries_the_record_for_html_and_pdf_only(inner, tmp_path):
    other = tmp_path / "t.txt"
    other.write_text("plain words\n", encoding="utf-8")
    assert inner.hidden_text("text", str(other)) is None, "a kind that is not examined says so with null, not with a clean record"
    assert inner.hidden_text("csv", str(other)) is None and inner.hidden_text("docx", str(other)) is None
    found = inner.hidden_text("html", str(FIXTURES / "hidden.html"))
    assert found["count"] == 15


def test_a_pdf_whose_tool_fails_is_not_failed_but_says_it_could_not_be_checked(inner, tmp_path, monkeypatch):
    def refuse(argv, timeout=0):
        raise inner.Failed("pdftohtml is not in the image")
    monkeypatch.setattr(inner, "run_tool", refuse)
    broken = tmp_path / "x.pdf"
    broken.write_bytes(b"%PDF-1.4\n")
    assert inner.hidden_text("pdf", str(broken)) == {"examined": False, "why": "tool_failed"}


@pytest.mark.skipif(shutil.which("pdftohtml") is None or shutil.which("pdftotext") is None,
                    reason="poppler's pdftohtml is not on this machine (the container test runs it)")
def test_the_real_pdftohtml_finds_the_three_hidden_pieces_of_the_fixture(inner, monkeypatch):
    monkeypatch.setitem(inner.ENV, "PATH", os.path.dirname(shutil.which("pdftohtml")) + os.pathsep + "/usr/bin:/bin")
    found = inner.hidden_text("pdf", str(FIXTURES / "hidden.pdf"))
    assert found["count"] == 3 and set(found["kinds"]) == {"tiny_text", "white_on_white", "invisible_text"}
