"""Tests of how providers/_email_text.py decides that text is hidden from a reader (shared by the Gmail and Outlook readers and the e-mail
channel): an element a reader cannot see is not message text, and an element only a layout trick touches is. The rule is on the inline style
and the hidden attribute only: a style sheet, a class, a colour and a comment are not read.

Run: uv run --with pytest==9.1.1 pytest providers/mailbox/tests/test_email_text_hidden.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "_email_text.py"
_spec = importlib.util.spec_from_file_location("email_text_for_the_hidden_tests", PATH)
et = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = et
_spec.loader.exec_module(et)


def text(html):
    return et.html_to_text(html)[0]


HIDES = [
    'style="display:none"', 'style="DISPLAY : NONE !important"', 'style="visibility:hidden"', 'style="mso-hide:all"', 'style="color:red;mso-hide: all;"',
    'style="opacity:0"', 'style="opacity: 0.0"', 'style="max-height:0;overflow:hidden"', 'style="overflow:hidden;max-height:0px"',
    'style="max-width:0;overflow-x:hidden"', 'style="width:0;overflow:hidden"', 'style="height:0px;overflow:hidden"', 'style="font-size:0"',
    'style="font-size: 0px !important"', 'style="font-size:0pt"', 'style="font-size:0.0em"', 'style="font-size:13px;font-size:0"', 'hidden']


@pytest.mark.parametrize("hide", HIDES)
def test_text_hidden_from_a_reader_is_dropped_whatever_follows_it(hide):
    assert text(f"<p>seen</p><div {hide}>UNSEEN</div><p>after</p>") == "seen\nafter"


@pytest.mark.parametrize("hide", [h for h in HIDES if "font-size" not in h])
def test_what_hides_a_box_hides_what_is_in_it_whatever_a_child_sets(hide):
    assert text(f'<p>seen</p><div {hide}><span style="font-size:13px"><b>UNSEEN</b></span></div><p>after</p>') == "seen\nafter"


@pytest.mark.parametrize("shown", [
    'style="width:0"', 'style="height:0"', 'style="width:0px;height:0"', 'style="max-width:0"', 'style="max-height:0"', 'style="overflow:hidden"',
    'style="max-height:100px;overflow:hidden"', 'style="min-width:0"', 'style="line-height:0"', 'style="width:50%"', 'style="font-size:0.8em"',
    'style="font-size:12px"', 'style="font-size:0;font-size:13px"', 'style="opacity:0.5"', 'style="opacity:1"', 'style="color:#ffffff"',
    'style="position:absolute;left:-9999px"', 'class="x"'])
def test_a_style_that_only_looks_like_hiding_leaves_the_text(shown):
    assert text(f"<p>a</p><div {shown}>SHOWN</div><p>b</p>") == "a\nSHOWN\nb"


def test_template_wrappers_of_font_size_zero_show_the_text_that_sets_its_own_size():
    assert text('<td style="font-size:0px;padding:10px 25px"><div style="font-size:13px">Your order has shipped</div></td>') == "Your order has shipped"
    assert text('<div style="font-size:0px;display:inline-block;width:100%"><p style="font-size:14px">Column text</p></div>') == "Column text"
    assert text('<div style="width:0">VISIBLE</div>') == "VISIBLE"


def test_inside_a_font_size_zero_wrapper_only_an_element_with_an_absolute_size_is_seen():
    html = ('<div style="font-size:0">own text<span>inherits</span><i style="font-size:1em">relative em</i><i style="font-size:100%">relative percent</i>'
            '<i style="font-size:smaller">relative keyword</i><i style="font-size:inherit">inherit</i>'
            '<p style="font-size:14px">px<span>child of px</span></p><u style="font-size:1rem">rem</u><s style="font-size:large">large</s></div>after')
    assert text(html) == "pxchild of px\nremlarge\nafter"


def test_the_size_stack_survives_unclosed_and_stray_tags():
    assert text('<div style="font-size:0"><p>unclosed hidden<p style="font-size:12px">second shown</div>back to normal') == "second shown\nback to normal"
    assert text('</span></div><p>stray end tags</p>') == "stray end tags"
    assert text('<div style="font-size:0"><br/><img src="x.png" alt="x"><span style="font-size:11px">kept</span></div>') == "kept"


def test_a_link_in_text_of_size_zero_is_not_a_link_and_one_with_a_size_of_its_own_is():
    html = ('<div style="font-size:0"><a href="https://hid.example/a">HIDDEN LINK</a><a style="font-size:12px" href="https://shown.example/b">shown</a></div>'
            '<span style="display:none"><a href="https://gone.example/c">gone</a></span><a href="https://plain.example/d">plain</a>')
    assert et.html_to_text(html)[1] == [{"href": "https://shown.example/b", "text": "shown"}, {"href": "https://plain.example/d", "text": "plain"}]


def test_what_is_not_read_is_not_removed():
    assert text('<style>.x{display:none}</style><p>ok</p><div class="x">CLASSED</div><!-- a comment --><font color="#fff">white</font>') == "ok\nCLASSED\nwhite"


def test_the_two_helpers_are_pure_functions_of_the_style():
    assert et.style_hides("display:none") and et.style_hides("height:0;overflow:hidden") and not et.style_hides("height:0") and not et.style_hides("font-size:0")
    assert et.font_zero("font-size:0", False) and not et.font_zero("font-size:13px", True) and et.font_zero("color:red", True)
    assert et.font_zero("font-size:1em", True) and not et.font_zero("font-size:1em", False) and not et.font_zero("font-size:0;font-size:13px", False)


# --- the open elements are kept the way a browser keeps them where it matters to what is shown --------------------------------------


@pytest.mark.parametrize("hide", ['style="font-size:0"', 'style="display:none"', 'style="visibility:hidden"', 'style="opacity:0"', 'hidden'])
@pytest.mark.parametrize("block", ["p", "div", "li", "td", "table", "h2", "blockquote"])
def test_an_end_tag_that_a_browser_ignores_does_not_let_hidden_text_out(hide, block):
    """</span> with a <block> opened inside the span is ignored by a browser: the text after it is still inside the hidden span."""
    assert text(f"<p>seen</p><span {hide}><{block}>a</span>INJECT</{block}></span>after") == "seen\nafter"


def test_stray_and_surplus_end_tags_close_nothing():
    assert text('<div style="font-size:0"></span></b></p>HIDDEN</div>vis') == "vis"
    assert text('<div style="display:none"></span></b></p>HIDDEN</div>vis') == "vis"
    assert text('<div style="font-size:0"><div>a</div></div>vis') == "vis"
    assert text('<span style="display:none">a</div>HIDDEN</span>vis') == "vis", "an end tag with nothing of its name open closes nothing"


def test_what_a_browser_ends_by_itself_is_ended():
    assert text('<p style="font-size:0">x<p>/approve 12') == "/approve 12"
    assert text('<p style="font-size:0">A<p>B') == "B"
    assert text('<ul><li style="font-size:0">A<li>B</ul>') == "B"
    assert text('<p style="font-size:0">A<div>B</div>') == "B"
    assert text('<table><tr><td style="font-size:0">A<td>B<tr><td>C</table>') == "B\nC"
    assert text('<table><tr style="font-size:0"><td>A<tr><td>B</table>') == "B"
    assert text('<dl><dt style="display:none">A<dd>B<dt>C</dl>') == "BC"
    assert text('<p style="display:none">A<p>B') == "B", "a hidden paragraph ends at the next one"
    assert text('<ul><li style="font-size:0">A<ul><li>nested hidden</ul><li>B</ul>') == "B", "a nested list's li does not end the outer li"


def test_the_size_of_an_element_is_read_from_the_font_shorthand_the_font_tag_and_calc():
    wrap = '<div style="font-size:0">{}</div>'
    assert text(wrap.format('<span style="font:14px Arial">A</span>')) == "A"
    assert text(wrap.format('<span style="font: italic bold 12px/1.5 Arial">A</span>')) == "A"
    assert text(wrap.format('<span style="font:large serif">A</span>')) == "A"
    assert text(wrap.format('<span style="font:0/0 Arial">A</span>')) == ""
    assert text(wrap.format('<span style="font:inherit">A</span>')) == ""
    assert text(wrap.format('<span style="font:1.2em Arial">A</span>')) == "", "relative to a parent of size zero"
    assert text(wrap.format('<font size="3">A</font><font size=2 style="font-size:0">B</font>')) == "A"
    assert text(wrap.format('<span style="font-size:calc(10px + 2px)">A</span><span style="font-size:min(12px, 1em)">B</span>')) == "AB"
    assert text('<span style="font:0 Arial">A</span>B') == "B"
    assert text('<span style="font-size:13px;font:0/0 Arial">A</span>B') == "B", "the last declaration decides"


def test_visibility_visible_in_a_hidden_parent_stays_hidden_the_safe_direction():
    assert text('<div style="visibility:hidden"><span style="visibility:visible">BROWSER SHOWS</span></div>vis') == "vis"


def test_a_stack_past_its_depth_cap_reads_nothing_more():
    cap = et.HTMLText.DEPTH_CAP
    assert "HIDDEN" not in text("<div>" * (cap + 50) + '<span style="display:none">HIDDEN</span>after')
    assert text("<div>" * (cap + 50) + "plain") == "", "past the cap nothing that follows can be told from what an element there hides"
    assert text("<div>" * (cap - 10) + "plain") == "plain", "just under the cap, the body is read"


@pytest.mark.parametrize("opened", [-1, 0, 1, 2])
def test_a_hidden_element_at_the_edge_of_the_cap_hides_what_follows_it(opened):
    """A hidden element that is the last the stack takes, with one more open element after it, then the end tags that follow."""
    cap = et.HTMLText.DEPTH_CAP
    body = "<span>" * (cap - 1 + opened) + '<span style="display:none">' + "<span>a</span>INJECT"
    assert "INJECT" not in text(body)
    assert "INJECT" not in text("<b>" * (cap - 1 + opened) + '<b style="display:none">' + "<b>a</b>INJECT")
    assert "INJECT" not in text("<div>" * (cap - 1 + opened) + '<div style="font-size:0">' + "<span>a</span>INJECT")


def test_a_stray_end_tag_of_another_skipped_element_does_not_end_the_skip():
    assert text("<template></title>INJECT</template>after") == "after"
    assert text("<style></template>INJECT</style>after") == "after"
    assert text("<template><title></template>INJECT") == "", "the innermost open skip is the title, and its content is raw text up to its own end tag"
    assert text("<title><template></title>INJECT") == "INJECT", "a template inside a title is raw text: the title ends at its end tag"
    assert text("<noscript>a<template>b</template>INJECT</noscript>after") == "after"
    assert text("<script>a</style>INJECT</script>after") == "after"


@pytest.mark.parametrize("barrier", ["td", "th", "caption", "button", "object", "marquee", "applet", "select", "table"])
@pytest.mark.parametrize("hide", ['style="display:none"', 'style="font-size:0"'])
def test_no_end_tag_closes_past_an_open_cell_table_or_control(barrier, hide):
    assert text(f"<p>seen</p><span {hide}><{barrier}>a</span>INJECT</{barrier}></span>after") == "seen\nafter"
    assert text(f"<p>seen</p><div {hide}><{barrier}>a</div>INJECT</{barrier}></div>after") == "seen\nafter"


def test_a_tables_own_end_tags_close_past_a_cell():
    assert text('<table><tr><td style="font-size:0">a</table>vis') == "vis"
    assert text('<table><tr style="font-size:0"><td>a</tr>b</table>vis') == "b\nvis", "b sits in the table, outside the row that ended"
    assert text('<table><tr><td style="display:none">a</td>b</tr>c</table>vis') == "b\nc\nvis"


@pytest.mark.parametrize("raw", ["textarea", "title", "xmp", "iframe", "noembed", "noframes"])
def test_raw_text_elements_are_not_text_and_their_markup_is_not_read(raw):
    assert text(f'x<{raw}><b style="font-size:13px">T</b><p>INNER</p></{raw}>y') == "xy"
    assert text(f'x<{raw}><span style="display:none"></{raw}>y') == "xy", "the end tag ends it though markup came before it"


def test_svg_desc_title_and_metadata_are_not_text():
    assert text("<svg><desc>D</desc><title>S</title><metadata>M</metadata><text>shown</text></svg>y") == "showny"


def test_calc_min_max_clamp_are_zero_only_when_every_length_in_them_is_zero():
    wrap = '<div style="font-size:0">{}</div>'
    for zero in ("calc(0px + 0px)", "calc(0)", "min(0, 0px)", "max(0px, 0em)", "clamp(0, 0, 0px)"):
        assert text(wrap.format(f'<span style="font-size:{zero}">Z</span>')) == "", zero
    for sized in ("calc(1px + 0px)", "min(0, 12px)", "max(0px, 1rem)", "clamp(0, 1vw, 0px)", "calc(10px + 2px)"):
        assert text(wrap.format(f'<span style="font-size:{sized}">V</span>')) == "V", sized
    assert text('<span style="font-size:calc(0px)">Z</span>after') == "after"


@pytest.mark.parametrize("shape", ["stray", "far", "blocked", "deep", "zero", "prepost", "bigstyle"])
def test_the_cost_is_linear_in_the_size_of_the_body(shape):
    import time
    n = 50000
    html = {"stray": "<span>" * n + "</b>" * n, "far": "<b>" + "<span>" * n + "</b>" * n, "blocked": "<b><div>" + "<span>" * n + "</b>" * n,
            "deep": "<div>" * n + "x" + "</div>" * n, "zero": '<div style="font-size:0">' * n + "x", "prepost": "<span>" * n + "</span>" * n,
            "bigstyle": '<div style="' + "font-size:0;" * n + '">x</div>'}[shape]
    started = time.monotonic()
    et.html_to_text(html)
    assert time.monotonic() - started < 2, shape
