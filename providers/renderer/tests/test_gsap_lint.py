"""The contract of our own `gsap.html` (`_gsap_lint.py`): one passing fictional fragment, and one failing fragment per rule. Pure text: no
browser, no docker, no ffmpeg. Every fragment is invented."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

import renderer_kit as K
import _gsap_lint as L
from _text import Refusal

NAME = "hf:demo-pop"
GOOD = K.POP_GSAP


def refused(text, name=NAME) -> str:
    with pytest.raises(Refusal) as caught:
        L.check(text, name)
    assert caught.value.code == "block_lint"
    return caught.value.field


def with_script(extra: str) -> str:
    return GOOD.replace("root.querySelector(\".label\").textContent", extra + "\n      root.querySelector(\".label\").textContent", 1)


def test_the_fictional_fragment_passes_and_its_parts_are_found():
    L.check(GOOD, NAME)
    parts = L.parse(GOOD, NAME)
    assert parts["markup"].strip() == '<div class="card"><span class="label"></span></div>'
    assert parts["style"].lstrip().startswith(":scope") and "function build(root, tl, data, ctx)" in parts["script"]
    assert "<template" not in parts["markup"] and "<style" not in parts["markup"] and "<script" not in parts["markup"]


def test_the_leading_comment_is_inert_and_may_name_anything():
    comment = "<!-- hf:demo-pop: adapted from a fictional component, commit " + "a" * 40 + ", Apache-2.0; href= url( window fetch. -->\n"
    L.check(comment + GOOD.split("-->\n", 1)[1], NAME)


# (rule, a fragment that breaks it, the field the refusal names)
BREAKS = [
    ("shape", "<div></div>"),
    ("shape", GOOD + "<p>after</p>"),
    ("shape", GOOD.replace('<template data-hf-block="hf:demo-pop">', '<template data-hf-block="hf:demo-pop" id="x">')),
    ("name", GOOD.replace('data-hf-block="hf:demo-pop"', 'data-hf-block="hf:other"')),
    ("template_count", GOOD.replace("</template>\n", "</template>\n<template data-hf-block=\"hf:demo-pop\"></template>\n")),
    ("parts", GOOD.replace("  <style>", "  <style>.a{color:red}</style><style>", 1)),
    ("parts", GOOD.replace("<script data-hf-build>", "<script>var a = 1;</script><script data-hf-build>", 1)),
    ("parts", GOOD.replace("<style>", "<p>").replace("</style>", "</p>")),
    ("build_function", GOOD.replace("function build(root, tl, data, ctx)", "function build(root, tl, data)")),
    ("build_function", GOOD.replace("function build(root, tl, data, ctx)", "function render(root, tl, data, ctx)")),
    ("build_function", GOOD.replace("    function build(root, tl, data, ctx) {", "    function build(root, tl, data, ctx) { }\n    function build(root, tl, data, ctx) {")),
    ("html_element", GOOD.replace('<div class="card">', '<img class="card">')),
    ("html_element", GOOD.replace('<div class="card">', '<iframe class="card">')),
    ("html_element", GOOD.replace('<div class="card">', '<VIDEO class="card">')),
    ("html_element", GOOD.replace('<div class="card">', '<link class="card">')),
    ("html_element", GOOD.replace('<div class="card">', '<body class="card">')),
    ("external_src", GOOD.replace('<div class="card">', '<div src="x.png" class="card">')),
    ("external_src", GOOD.replace('<div class="card">', '<div HREF = "x" class="card">')),
    ("css_url", GOOD.replace("color: var(--c-text);", "background: url(x.png);")),
    ("css_url", GOOD.replace("  <style>", "  <style>\n    @import 'x.css';", 1)),
    ("css_url", GOOD.replace("  <style>", "  <style>\n    @font-face { font-family: X; }", 1)),
    ("html_comment", GOOD.replace('<div class="card">', '<!-- x --><div class="card">')),
    ("network", with_script("fetch('x');")),
    ("network", with_script("new XMLHttpRequest();")),
    ("network", with_script("new WebSocket('x');")),
    ("network", with_script("new EventSource('x');")),
    ("network", with_script("new Worker('x');")),
    ("dynamic_code", with_script("import('x');")),
    ("dynamic_code", with_script("ev" + "al('1');")),
    ("dynamic_code", with_script("Function('1')();")),
    ("timers", with_script("setTimeout(function () {}, 1);")),
    ("timers", with_script("setInterval(function () {}, 1);")),
    ("timers", with_script("requestAnimationFrame(function () {});")),
    ("clock_random", with_script("var r = Math.random();")),
    ("clock_random", with_script("var r = Date.now();")),
    ("clock_random", with_script("var r = new Date();")),
    ("clock_random", with_script("var r = performance.now();")),
    ("storage", with_script("localStorage.x = 1;")),
    ("storage", with_script("sessionStorage.x = 1;")),
    ("storage", with_script("indexedDB.open('x');")),
    ("storage", with_script("var c = document.cookie;")),
    ("page_reach", with_script("var n = navigator.userAgent;")),
    ("page_reach", with_script("var g = globalThis;")),
    ("page_reach", with_script("var w = window;")),
    ("page_reach", with_script("var s = self.name;")),
    ("page_reach", with_script("var s = top.name;")),
    ("page_reach", with_script("var s = parent.name;")),
    ("page_reach", with_script("var s = opener;")),
    ("page_reach", with_script("var s = document.body;")),
    ("page_reach", with_script("var s = root.ownerDocument;")),
    ("page_reach", with_script("var s = root.parentNode;")),
    ("page_reach", with_script("var s = root.parentElement;")),
    ("page_reach", with_script("var s = root.closest('div');")),
    ("page_reach", with_script("var s = root.getRootNode();")),
    ("overlay_api", with_script("root.showModal();")),
    ("overlay_api", with_script("root.popover = 'auto';")),
    ("overlay_api", with_script("root.requestFullscreen();")),
    ("timeline_registry", with_script("var t = __timelines;")),
    ("font_family", GOOD.replace("font-family: var(--font-display);", "font-family: Papyrus, serif;")),
    ("font_family", GOOD.replace("font-family: var(--font-display);", "font-family: var(--font-display), Inter;")),
    ("font_family", GOOD.replace('<div class="card">', '<div style="font-family: Menlo" class="card">')),
    ("markup_text", GOOD.replace('<span class="label"></span>', '<span class="label">Name every dollar</span>')),
    ("style_braces", GOOD.replace(":scope { display: block; }", ":scope { display: block; } } body { color: red; ")),
    ("style_scope", GOOD.replace(":scope { display: block; }", ":root { display: block; }")),
    ("style_scope", GOOD.replace(":scope { display: block; }", "body { display: block; }")),
    ("style_scope", GOOD.replace(":scope { display: block; }", "@scope (.x) { :scope { display: block; } }")),
]


@pytest.mark.parametrize("rule,text", BREAKS, ids=["%s-%d" % (rule, k) for k, (rule, _) in enumerate(BREAKS)])
def test_a_fragment_that_breaks_a_rule_is_refused_naming_that_rule(rule, text):
    assert refused(text) == "%s %s" % (NAME, rule)


def test_a_fragment_over_64_kib_is_refused_and_the_comment_is_capped():
    assert refused(GOOD.replace("<style>", "<style>\n/* " + "x" * L.MAX_BYTES + " */", 1)) == NAME + " size"
    assert refused("<!-- " + "x" * 1001 + " -->\n" + GOOD.split("-->\n", 1)[1]) == NAME + " comment_size"


def test_a_font_the_fragment_names_is_one_of_the_three_variables_or_a_generic_keyword():
    for value in ("var(--font-text)", "var(--font-mono)", "sans-serif", "monospace", "inherit", "var(--font-display), sans-serif"):
        L.check(GOOD.replace("font-family: var(--font-display);", "font-family: %s;" % value), NAME)


def test_a_literal_colour_is_allowed():
    L.check(GOOD.replace("color: var(--c-text);", "color: #ff00aa;"), NAME)


def test_a_rule_names_only_the_first_break_and_the_message_holds_no_fragment_text():
    field = refused(GOOD.replace('<span class="label"></span>', '<span class="label">SECRET WORDS</span>'))
    assert "SECRET" not in field and field.startswith(NAME)


def test_the_module_imports_on_its_own_with_no_other_path_than_its_own_folder(tmp_path):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/nonexistent")}
    done = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); import _gsap_lint" % str(K.RENDERER)], capture_output=True, text=True,
                          env=env, timeout=60, cwd=str(tmp_path))
    assert done.returncode == 0, done.stderr[-800:]
