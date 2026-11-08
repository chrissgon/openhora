"""The contract of our own `gsap.html` (a tier-B port, or a second implementation of an `oh:` block): one fragment, not a document.

    <!-- <block name>: <one line>. [Adapted from ... See providers/renderer/hyperframes-image/NOTICE.md.] -->
    <template data-hf-block="<ns>:<short>">
      <style>/* selectors only under :scope */</style>
      <div class="root">...markup, no text content: text comes from data...</div>
      <script data-hf-build>
        function build(root, tl, data, ctx) { /* adds tweens to tl (local time 0 = entry start); reads only root and data */ }
      </script>
    </template>

The HyperFrames page stage (`_hf_compose.py`) inlines the fragment once per entry: the markup in an instance element, the style inside
`@scope (#hf-inst-N)`, the script once per block. `check(text, name)` is the one gate: it raises `Refusal("block_lint", "<name> <rule>")`
for the first rule the fragment breaks. `parse` returns the three parts of a fragment that passed. Pure text work: no browser, nothing
of the host. Standard library only.
"""
from __future__ import annotations

import re

from _text import Refusal

MAX_BYTES = 64 * 1024
BUILD_SIGNATURE = "function build(root, tl, data, ctx)"
FONT_VALUES = {"var(--font-display)", "var(--font-text)", "var(--font-mono)", "sans-serif", "serif", "monospace", "system-ui", "ui-monospace",
               "inherit", "initial", "unset"}

# The tokens no fragment may hold, as (rule, pattern). HTML tokens are matched without regard to case.
_HTML = [
    ("html_element", r"<\s*(html|body|head|link|iframe|img|video|audio|object|embed)\b"),
    ("external_src", r"\b(src|href|srcset|poster|action|formaction)\s*="),
    ("css_url", r"\burl\s*\(|@import|@font-face"),
    ("html_comment", r"<!--"),
]
_JS = [
    ("network", r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|Worker|SharedWorker|importScripts)\b|\bsendBeacon\b"),
    ("dynamic_code", r"\bimport\s*\(|\beval\b|\bFunction\s*\("),
    ("timers", r"\b(setTimeout|setInterval|setImmediate|requestAnimationFrame|cancelAnimationFrame|requestIdleCallback)\b"),
    ("clock_random", r"Math\s*\.\s*random|\bDate\s*\.\s*now|\bnew\s+Date\b|\bperformance\b"),
    ("storage", r"\b(localStorage|sessionStorage|indexedDB)\b|document\s*\.\s*cookie"),
    ("page_reach", r"\bnavigator\b|\bglobalThis\b|\bwindow\b|(?<![\w$.])(self|top|parent)\s*\.|\bopener\b|(?<![\w$.])document\s*\.|\.\s*ownerDocument\b"
                   r"|\.\s*parentNode\b|\.\s*parentElement\b|\.\s*closest\s*\(|\.\s*getRootNode\b"),
    ("overlay_api", r"\bshowModal\b|\bpopover\b|\brequestFullscreen\b"),
    ("timeline_registry", r"__timelines"),
]
_RULES = [(name, re.compile(rx, re.I)) for name, rx in _HTML] + [(name, re.compile(rx)) for name, rx in _JS]
_FRAGMENT = re.compile(r"\s*(?:<!--(?:(?!-->).)*-->\s*)?<template data-hf-block=\"([^\"]*)\">(.*)</template>\s*", re.S)
_COMMENT_MAX = 1000
_STYLE = re.compile(r"<style>(.*?)</style>", re.S | re.I)
_SCRIPT = re.compile(r"<script data-hf-build>(.*?)</script>", re.S | re.I)


def _fail(name: str, rule: str):
    raise Refusal("block_lint", ("%s %s" % (name, rule))[:80])


def _depth_ok(css: str) -> bool:
    depth = 0
    for ch in css:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _fonts_ok(css: str) -> bool:
    for found in re.finditer(r"font-family\s*:\s*([^;}]*)", css, re.I):
        for token in found.group(1).split(","):
            if token.strip().lower() not in FONT_VALUES:
                return False
    return True


def parse(text: str, name: str) -> dict:
    """The parts of a fragment: {markup, style, script}. Raises `block_lint` when the shape is wrong; it does not look at the tokens
    (`check` does)."""
    found = _FRAGMENT.fullmatch(text)
    if not found:
        _fail(name, "shape")
    if found.group(1) != name:
        _fail(name, "name")
    lowered = text.lower()
    if lowered.count("<template") != 1 or lowered.count("</template>") != 1:
        _fail(name, "template_count")
    body = found.group(2)
    styles, scripts = _STYLE.findall(body), _SCRIPT.findall(body)
    if len(styles) != 1 or len(scripts) != 1 or body.lower().count("<style") != 1 or body.lower().count("<script") != 1 \
            or body.lower().count("</style>") != 1 or body.lower().count("</script>") != 1:
        _fail(name, "parts")
    markup = _SCRIPT.sub("", _STYLE.sub("", body))
    return {"markup": markup.strip("\n"), "style": styles[0].strip("\n"), "script": scripts[0].strip("\n")}


def check(text: str, name: str = "block") -> None:
    """None when the fragment keeps the contract, else `Refusal("block_lint", "<name> <rule>")`."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        _fail(name, "size")
    parts = parse(text, name)
    comment = re.match(r"\s*<!--(.*?)-->", text, re.S)
    if comment and len(comment.group(1)) > _COMMENT_MAX:
        _fail(name, "comment_size")
    inside = text[comment.end():] if comment else text                    # the leading comment is inert text: it may say anything
    for rule, rx in _RULES:
        if rx.search(inside):
            _fail(name, rule)
    if len(re.findall(r"function\s+build\b", parts["script"])) != 1 or BUILD_SIGNATURE not in parts["script"] \
            or len(re.findall(r"^[ \t]*function build\(", parts["script"], re.M)) != 1:
        _fail(name, "build_function")
    if not _depth_ok(parts["style"]):
        _fail(name, "style_braces")
    if re.search(r"@scope|:root|\bhtml\b|\bbody\b", parts["style"], re.I):
        _fail(name, "style_scope")
    if not _fonts_ok(parts["style"]) or not _fonts_ok(parts["markup"]):
        _fail(name, "font_family")
    if re.sub(r"<[^>]*>", "", parts["markup"]).strip():
        _fail(name, "markup_text")
