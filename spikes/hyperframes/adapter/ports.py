"""Turns HyperFrames registry components (Apache-2.0, fetched at a pinned commit and hash-checked at image build) into inline parts of one
1080x1920 composition. Nothing of HyperFrames is stored in this repository: each port starts from the component's text and applies exact
replacements, every one asserted to match the expected number of times. When a component changes upstream the assertion fails, which is
the point: the cost of adopting a component is the number of replacements below, and a changed component is noticed, not silently drawn.

S2 differences from S1 (HyperFrames 0.9.19):
  * No word of the transcript is ever written into the page. A port replaces the sample data (the `WORDS` array and so on) by a read of
    `window.__hfV`, the object `hyperframes render --variables-file` supplies (read through `window.__hyperframes.getVariables()`). The blocks
    already put text on screen with `textContent`; nothing here changes that.
  * The blocks are inlined in the one root composition instead of mounted as sub-compositions, because `--variables` reaches only the top level:
    a sub-composition's `getVariables()` returns its own defaults and the host's `data-variable-values` (an attribute, i.e. markup).
  * One shared GSAP timeline (`window.__hfMain`) instead of one timeline per component, so the whole drawing is one timeline the renderer seeks.
  * Every component ships with CDN tags (Google Fonts, jsDelivr GSAP); they are removed here (the page carries a vendored GSAP and our own fonts).

Each port returns {"css": ..., "markup": ..., "script": ...}; `PATCH_LOG` counts the replacements (the figure the report calls "changes").
"""
from __future__ import annotations

import json
import re

PATCH_LOG: list = []
PATCHES_BY_BLOCK: dict = {}


def sub(text: str, old, new: str, count: int = 1, block: str = "", label: str = "") -> str:
    """Replace `old` (a plain string or a compiled regex) by `new` exactly `count` times, else raise: the component changed upstream."""
    if isinstance(old, str):
        found = text.count(old)
        if found != count:
            raise AssertionError("patch %r: expected %d match(es), found %d" % (label or old[:50], count, found))
        out = text.replace(old, new)
    else:
        found = len(old.findall(text))
        if found != count:
            raise AssertionError("patch %r: expected %d match(es), found %d" % (label or old.pattern[:50], count, found))
        out = old.sub(lambda m: new, text)
    PATCH_LOG.append(label or (old if isinstance(old, str) else old.pattern)[:60])
    PATCHES_BY_BLOCK[block] = PATCHES_BY_BLOCK.get(block, 0) + 1
    return out


def sub_expand(text: str, pattern, repl: str, count: int, block: str, label: str) -> str:
    """A regex replacement with group references (`\\1`), asserted to match exactly `count` times; each match counts as one change."""
    out, n = pattern.subn(repl, text)
    if n != count:
        raise AssertionError("patch %r: expected %d match(es), found %d" % (label, count, n))
    PATCH_LOG.extend([label] * n)
    PATCHES_BY_BLOCK[block] = PATCHES_BY_BLOCK.get(block, 0) + n
    return out


def rx(pattern: str, flags: int = 0):
    return re.compile(pattern, flags)


def split_standalone(text: str):
    """(style, markup, script) of a standalone caption component: one <style> in the head, the markup between <body> and the first <script>,
    and the one inline script."""
    style = text[text.index("<style>") + 7:text.index("</style>")]
    body = text[text.index("<body>") + 6:]
    markup = body[:body.index("<script>")]
    script = body[body.index("<script>") + 8:body.rindex("</script>")]
    return style, markup, script


def split_template(text: str):
    """(style, markup, script) of a component wrapped in <template>: the <style> and the <script> of the root, and the markup between them."""
    inner = text[text.index("<template>") + 10:text.rindex("</template>")]
    style = inner[inner.index("<style>") + 7:inner.index("</style>")]
    after = inner[inner.index("</style>") + 8:]
    markup = after[:after.index("<script")]
    script = after[after.index("<script>") + 8:after.rindex("</script>")]
    return style, markup, script


def iife_to_wait(script: str, block: str) -> str:
    """Build after the fonts are loaded: the components measure text on a canvas when their script runs, and a font that is not loaded yet
    measures as the fallback."""
    script = sub(script, "(function () {", "window.__hfFonts.then(function () {", 1, block, "wait for the fonts")
    return sub(script, rx(r"\}\)\(\);\s*$"), "});", 1, block, "close the wait")


def wrap_wait(script: str, block: str) -> str:
    """The same for a component whose script is not wrapped in a function (its variables are globals): wrap it."""
    PATCH_LOG.append("wrap in the font wait")
    PATCHES_BY_BLOCK[block] = PATCHES_BY_BLOCK.get(block, 0) + 1
    return "window.__hfFonts.then(function () {" + script + "\n});"


# ---------------------------------------------------------------- captions

def port_highlight(src: str) -> dict:
    """caption-highlight: a box sweeps behind the spoken word, all words of the group stay visible."""
    b = "caption-highlight"
    style, markup, script = split_standalone(src)
    style = sub(style, rx(r"html,\s*body\s*\{[^}]*\}"), "", 1, b, "drop html/body rule (it would restyle the host page)")
    style = sub(style, rx(r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*\}"), "#captions *, #captions *::before, #captions *::after { box-sizing: border-box; }", 1, b, "scope the universal box-sizing rule to the block's own container (the host page has none; dropping it changes the width of padded boxes)")
    style = sub(style, rx(r"width: 1920px;\s*height: 1080px;"), "width: 1080px; height: 1920px;", 1, b, "frame size")
    style = sub(style, "bottom: 140px;", "top: 0;", 1, b, "position by group (set per group)")
    style = sub(style, "align-items: flex-end;", "align-items: flex-start;", 1, b, "group aligns to its top")
    style = sub(style, "padding: 0 100px;", "padding: 0 60px;", 1, b, "side margin")
    style = sub(style, 'font-family: "Montserrat", sans-serif;', 'font-family: "Inter", sans-serif;', 1, b, "allow-listed font")
    style = sub(style, "background: linear-gradient(135deg, #ff1745 0%, #df1238 100%);", "background: var(--hf-accent);", 1, b, "accent colour from the edit list")
    style = sub(style, "box-shadow: 0 12px 30px rgba(229, 20, 58, 0.32);", "box-shadow: 0 8px 22px rgba(0, 0, 0, 0.35);", 1, b, "shadow colour")
    markup = sub(markup, rx(r'<div\s+id="highlight"[^>]*>'), '<div id="highlight">', 1, b, "no composition attributes (it is part of the root)")
    script = sub(script, "window.__timelines = window.__timelines || {};", "", 1, b, "no own timeline registry")
    script = sub(script, rx(r"var WORDS = \[.*?\n        \];", re.S), "var WORDS = window.__hfV.words;\n        var TOPS = window.__hfV.tops;", 1, b, "words and zones come from the variables")
    script = sub(script, rx(r"var RAW_GROUPS = \[.*?\n        \];", re.S), "var RAW_GROUPS = window.__hfV.chunks;", 1, b, "caption chunks come from the variables")
    script = sub(script, 'fitFontSize(groupText, 80, "800", "Montserrat", 1620)', 'fitFontSize(groupText, 84, "800", "Inter", 940)', 1, b, "size and measuring font")
    script = sub(script, 'grp.id = "hl-grp-" + gi;', 'grp.id = "hl-grp-" + gi;\n          grp.style.top = TOPS[gi] + "px";', 1, b, "top of each group")
    script = sub(script, "var tl = gsap.timeline({ paused: true });", "var tl = window.__hfMain;", 1, b, "draw on the shared timeline")
    script = sub(script, 'tl.seek(0);\n        window.__timelines["caption-highlight"] = tl;', "", 1, b, "no own seek or registration")
    script = iife_to_wait(script, b)
    return {"css": style, "markup": markup, "script": script}


def port_pill_karaoke(src: str) -> dict:
    """caption-pill-karaoke: a rounded pill holds the group, the spoken word darkens."""
    b = "caption-pill-karaoke"
    style, markup, script = split_standalone(src)
    style = sub(style, rx(r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*\}"), "#captions *, #captions *::before, #captions *::after { box-sizing: border-box; }", 1, b, "scope the universal box-sizing rule to the block's own container (the host page has none; dropping it changes the width of padded boxes)")
    style = sub(style, rx(r"html,\s*body\s*\{[^}]*\}"), "", 1, b, "drop html/body rule (it would restyle the host page)")
    style = sub(style, rx(r"width: 1920px;\s*height: 1080px;"), "width: 1080px; height: 1920px;", 1, b, "frame size")
    style = sub(style, rx(r"\.safe-zone\s*\{[^}]*\}"), ".safe-zone { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; }", 1, b, "stage covers the frame")
    style = sub(style, rx(r"\.caption-group\s*\{[^}]*\}"),
                ".caption-group { position: absolute; left: 60px; top: 0; width: 960px; height: 220px; display: flex; align-items: center; "
                "justify-content: center; opacity: 0; }", 1, b, "group box (960 wide, top set per group)")
    style = sub(style, "max-width: 1600px;", "max-width: 960px;", 1, b, "pill width")
    style = sub(style, 'font-family: "Poppins", Arial, sans-serif;', 'font-family: "Inter";', 1, b, "allow-listed font (and no Arial: the compiler would add a font for any named family)")
    style = sub(style, "font-weight: 700;", "font-weight: 800;", 1, b, "weight we have")
    script = sub(script, "var DURATION = 8;", "var DURATION = window.__hfV.duration;", 1, b, "duration from the variables")
    script = sub(script, "var SAFE_ZONE_WIDTH = 1400;", "var SAFE_ZONE_WIDTH = 960;", 1, b, "line width")
    script = sub(script, "var PILL_MAX_WIDTH = 1400;", "var PILL_MAX_WIDTH = 960;", 1, b, "pill width")
    script = sub(script, 'var FONT_FAMILY = "Poppins";', 'var FONT_FAMILY = "Inter";', 1, b, "measuring font")
    script = sub(script, 'var FONT_WEIGHT = "700";', 'var FONT_WEIGHT = "800";', 1, b, "measuring weight")
    script = sub(script, rx(r"var TRANSCRIPT = \[.*?\n      \];", re.S), "var TRANSCRIPT = window.__hfV.words;\n      var TOPS = window.__hfV.tops;", 1, b,
                 "words and zones come from the variables")
    script = sub(script, "var GROUPS = makeGroups(WORDS);",
                 "var GROUPS = window.__hfV.chunks.map(function (p) { var ws = WORDS.slice(p[0], p[1] + 1); "
                 "return { words: ws, start: ws[0].start, end: ws[ws.length - 1].end }; });", 1, b, "our caption chunks instead of its own grouping")
    script = sub(script, 'groupEl.className = "caption-group";', 'groupEl.className = "caption-group";\n          groupEl.style.top = TOPS[groupIndex] + "px";', 1, b,
                 "top of each group")
    script = sub(script, "window.__timelines = window.__timelines || {};\n      var tl = gsap.timeline({ paused: true });", "var tl = window.__hfMain;", 1, b,
                 "draw on the shared timeline")
    script = sub(script, 'window.__timelines["caption-pill-karaoke"] = tl;', "", 1, b, "no own registration")
    script = wrap_wait(script, b)
    markup = sub(markup, rx(r'<div\s+id="pill-karaoke"[^>]*>'), '<div id="pill-karaoke">', 1, b, "no composition attributes (it is part of the root)")
    return {"css": style, "markup": markup, "script": script}


def port_kinetic_slam(src: str) -> dict:
    """caption-kinetic-slam: one big word at a time, alternating entrances."""
    b = "caption-kinetic-slam"
    style, markup, script = split_standalone(src)
    style = sub(style, rx(r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*\}"), "#captions *, #captions *::before, #captions *::after { box-sizing: border-box; }", 1, b, "scope the universal box-sizing rule to the block's own container (the host page has none; dropping it changes the width of padded boxes)")
    style = sub(style, rx(r"html,\s*body\s*\{[^}]*\}"), "", 1, b, "drop html/body rule (it would restyle the host page)")
    style = sub(style, rx(r"width: 1920px;\s*height: 1080px;"), "width: 1080px; height: 1920px;", 1, b, "frame size")
    style = sub(style, 'font-family: "Anton", sans-serif;', 'font-family: "Inter", sans-serif;', 1, b, "allow-listed font (Anton is not on the list)")
    style = sub(style, "font-weight: 400;", "font-weight: 800;", 1, b, "weight we have")
    style = sub(style, "top: 50%;", "top: 0;", 1, b, "position by word (set per word)")
    markup = sub(markup, rx(r'<div\s+id="kinetic-slam"[^>]*>'), '<div id="kinetic-slam">', 1, b, "no composition attributes (it is part of the root)")
    script = sub(script, "window.__timelines = window.__timelines || {};", "", 1, b, "no own timeline registry")
    script = sub(script, rx(r"var WORDS = \[.*?\n        \];", re.S), "var WORDS = window.__hfV.words;\n        var TOPS = window.__hfV.word_tops;", 1, b,
                 "words and zones come from the variables")
    script = sub(script, rx(r"var KEYWORDS = new Set\(\[[^\]]*\]\);[^\n]*"), "var KEYWORDS = new Set([]);", 1, b, "no sample keyword list")
    script = sub(script, "220, \"400\", \"'Anton', sans-serif\", 1720", "190, \"800\", \"Inter\", 960", 1, b, "size and measuring font")
    script = sub(script, 'el.id = "kt-w-" + wi;', 'el.id = "kt-w-" + wi;\n          el.style.top = TOPS[wi] + "px";', 1, b, "top of each word")
    script = sub(script, '_fitCtx.font = fontWeight + " " + size + "px " + fontFamily;', '_fitCtx.font = fontWeight + " " + size + "px " + fontFamily;\n            _fitCtx.letterSpacing = size * 0.04 + "px";', 1, b,
                 "measure with the CSS letter-spacing (0.04em), which the component's fit ignores: a long word was 26 px wider than the frame")
    script = sub(script, "var tl = gsap.timeline({ paused: true });", "var tl = window.__hfMain;", 1, b, "draw on the shared timeline")
    script = sub(script, 'tl.seek(0);\n        window.__timelines["caption-kinetic-slam"] = tl;', "", 1, b, "no own seek or registration")
    script = iife_to_wait(script, b)
    return {"css": style, "markup": markup, "script": script}


CAPTIONS = {
    "highlight": ("caption-highlight", port_highlight, "hl-word"),
    "pill": ("caption-pill-karaoke", port_pill_karaoke, "caption-word"),
    "slam": ("caption-kinetic-slam", port_kinetic_slam, "kt-word"),
}

# the extent, in pixels, of the box each block places per chunk: its top is computed from the caption band
GROUP_BOX = {"highlight": 120, "pill": 220, "slam": 0}


# ---------------------------------------------------------------- cards (sub-compositions, inlined as functions that build one instance)

def port_count_up(src: str) -> dict:
    """number card: a figure counts up and lands with one pulse."""
    b = "count-up"
    style, markup, script = split_template(src)
    style = sub(style, rx(r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*\}"), ".card *, .card *::before, .card *::after { box-sizing: border-box; }", 1, b, "scope the universal box-sizing rule to the block's own container (the host page has none)")
    style = sub(style, "#root {", ".cu-root {", 1, b, "the root is a class (there is one instance per card)")
    script = sub(script, '            var root = document.getElementById("root");\n', "", 1, b, "the host is a parameter")
    script = sub(script, rx(r"var vars =\s*window\.__hyperframes && window\.__hyperframes\.getVariables\s*\?\s*window\.__hyperframes\.getVariables\(\)\s*:\s*\{\};"),
                 "", 1, b, "the values are a parameter")
    script = sub(script, 'var duration = Math.max(0.001, parseFloat(root.dataset.duration || "3"));', "var duration = Math.max(0.001, DURATION);", 1, b,
                 "the beat's duration is a parameter")
    script = sub(script, 'toLocaleString("en-US")', 'toLocaleString("pt-BR")', 1, b, "thousands separator of the audience")
    script = sub(script, "var tl = gsap.timeline({ paused: true });", "var tl = window.__hfChild();", 1, b, "a child of the shared timeline")
    script = sub(script, 'tl.seek(0);\n            window.__timelines = window.__timelines || {};\n            window.__timelines["count-up"] = tl;', "return tl;", 1, b,
                 "return the timeline instead of registering it")
    script = sub(script, "(function () {", "function __hfCountUp(root, vars, DURATION) {", 1, b, "a function, one call per card")
    script = sub(script, rx(r"\}\)\(\);\s*$"), "}", 1, b, "close the function")
    markup = sub(markup, rx(r'<div\s+id="count-up-clip"\s+class="cu-clip clip"[^>]*>'), '<div class="cu-clip">', 1, b, "no timing attributes (it is part of the root)")
    return {"css": style, "markup": markup, "script": script}


def port_testimonial(src: str) -> dict:
    """quote card: a card with the sentence and who said it."""
    b = "testimonial-card"
    style, markup, script = split_template(src)
    style = sub(style, rx(r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*\}"), ".card *, .card *::before, .card *::after { box-sizing: border-box; }", 1, b, "scope the universal box-sizing rule to the block's own container (the host page has none)")
    style = sub(style, "#root {", ".tc-root {", 1, b, "the root is a class (there is one instance per card)")
    style = sub(style, 'var(--font-mono, ui-monospace, "SF Mono", Menlo, Consolas, monospace)', "var(--font-mono, monospace)", 1, b,
                "no named system monospace fonts (the compiler adds a bundled font for each named family it does not find declared)")
    style = sub_expand(style, rx(r"min\(([\d.]+)cqw, ([\d.]+)cqh\)"), r"\1cqw", 14, b,
                       "size by the width of the host (the card band of a portrait frame is wide and short; the component sizes by its smaller side)")
    script = sub(script, '            var root = document.getElementById("root");\n', "", 1, b, "the host is a parameter")
    script = sub(script, rx(r"var vars =\s*window\.__hyperframes && window\.__hyperframes\.getVariables\s*\?\s*window\.__hyperframes\.getVariables\(\)\s*:\s*\{\};"),
                 "", 1, b, "the values are a parameter")
    script = sub(script, "var durationValue = Number(root.dataset.duration);", "var durationValue = Number(DURATION);", 1, b, "the beat's duration is a parameter")
    script = sub(script, "var tl = gsap.timeline({ paused: true });", "var tl = window.__hfChild();", 1, b, "a child of the shared timeline")
    script = sub(script, 'tl.seek(0);\n\n            window.__timelines = window.__timelines || {};\n            window.__timelines[compositionId] = tl;', "return tl;", 1, b,
                 "return the timeline instead of registering it")
    script = sub(script, "(function () {", "function __hfTestimonial(root, vars, DURATION) {", 1, b, "a function, one call per card")
    script = sub(script, rx(r"\}\)\(\);\s*$"), "}", 1, b, "close the function")
    markup = sub(markup, rx(r'<div\s+id="testimonial-card-clip"\s+class="tc-clip clip"[^>]*>'), '<div class="tc-clip">', 1, b, "no timing attributes (it is part of the root)")
    style += "\n.tc-root .tc-rating { display: none; }"            # our quote has no star rating (not a patch of the component: an addition)
    return {"css": style, "markup": markup, "script": script}


def port_spring_pop(src: str) -> dict:
    """keyword card: a badge pops in, overshoots once and settles."""
    b = "spring-pop"
    style, markup, script = split_template(src)
    style = sub(style, rx(r"\*,\s*\*::before,\s*\*::after\s*\{[^}]*\}"), ".card *, .card *::before, .card *::after { box-sizing: border-box; }", 1, b, "scope the universal box-sizing rule to the block's own container (the host page has none)")
    style = sub(style, "#root {", ".sp-root {", 1, b, "the root is a class (there is one instance per card)")
    style = sub(style, "font-size: clamp(14px, 9cqmin, 54px);", "font-size: var(--sp-font, 54px);", 1, b,
                "type size set by the adapter from the text length (the component sizes it from the card height)")
    script = sub(script, '            var root = document.getElementById("root");\n', "", 1, b, "the host is a parameter")
    script = sub(script, rx(r"var vars =\s*window\.__hyperframes && window\.__hyperframes\.getVariables\s*\?\s*window\.__hyperframes\.getVariables\(\)\s*:\s*\{\};"),
                 "", 1, b, "the values are a parameter")
    script = sub(script, 'var duration = Math.max(0.001, parseFloat(root.dataset.duration || "2"));', "var duration = Math.max(0.001, DURATION);", 1, b,
                 "the beat's duration is a parameter")
    script = sub(script, "var tl = gsap.timeline({ paused: true });", "var tl = window.__hfChild();", 1, b, "a child of the shared timeline")
    script = sub(script, rx(r"tl\.seek\(0\);\s*window\.__timelines = window\.__timelines \|\| \{\};\s*window\.__timelines\[\"spring-pop\"\] = tl;"), "return tl;", 1, b,
                 "return the timeline instead of registering it")
    script = sub(script, "(function () {", "function __hfSpringPop(root, vars, DURATION) {", 1, b, "a function, one call per card")
    script = sub(script, rx(r"\}\)\(\);\s*$"), "}", 1, b, "close the function")
    markup = sub(markup, rx(r'<div\s+id="spring-pop-clip"\s+class="sp-clip clip"[^>]*>'), '<div class="sp-clip">', 1, b, "no timing attributes (it is part of the root)")
    return {"css": style, "markup": markup, "script": script}


CARDS = {"number": ("count-up", port_count_up), "quote": ("testimonial-card", port_testimonial), "keyword": ("spring-pop", port_spring_pop)}
