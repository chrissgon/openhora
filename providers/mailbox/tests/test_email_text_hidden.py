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
