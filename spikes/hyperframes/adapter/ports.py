"""Turns HyperFrames registry components (Apache-2.0, fetched at a pinned commit and hash-checked at image build) into compositions for a
1080x1920 reel with the words and zones of one of our edit lists.

Nothing of HyperFrames is stored in this repository: each port starts from the component's text and applies a list of exact
replacements, every one asserted to match the expected number of times. When a component changes upstream the assertion fails, which is
the point: the cost of adopting a component is the number of replacements below, and a changed component is noticed, not silently drawn.

Three kinds of component are used (this is what the spike found):
  * caption identities (older style): a full document with the sample transcript written into it and a 1920x1080 layout. Ported by text
    patches: geometry, font, words, groups, vertical position per group, and a font-load wait (the component measures text on a canvas
    when its script runs, and a font that is not loaded yet measures as the fallback).
  * overlays that ship as sub-compositions with variables (spring-pop, count-up, testimonial-card): used as they are, with the words given
    as per-instance variables, the theme given as CSS custom properties, the CDN script tag removed (the page already carries GSAP).
  * overlays that ship as a snippet to paste (line-by-line-slide): the markup and CSS are copied, the timeline recipe in its trailing
    comment is written out for our items.
"""
from __future__ import annotations

import json
import re

PATCH_LOG: list = []


def sub(text: str, old, new: str, count: int = 1, flags: int = 0, label: str = "") -> str:
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
    return out


def rx(pattern: str, flags: int = 0):
    return re.compile(pattern, flags)


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def split_component(text: str):
    """(style, markup, script) of an older-style caption component: one <style> in the head, the markup between <body> and the first
    <script>, and the one inline script."""
    style = text[text.index("<style>") + 7:text.index("</style>")]
    body = text[text.index("<body>") + 6:]
    markup = body[:body.index("<script>")]
    script = body[body.index("<script>") + 8:body.rindex("</script>")]
    return style, markup, script


def template(style: str, markup: str, script: str) -> str:
    return ("<!doctype html>\n<html>\n<head><meta charset=\"UTF-8\"></head>\n<body>\n<template>\n<style>%s</style>\n%s\n<script>%s</script>\n</template>\n"
            "</body>\n</html>\n" % (style, markup.strip(), script))


def font_wait(script: str, font: str, iife: bool) -> str:
    """Build after the font is loaded: the component measures text on a canvas when its script runs."""
    load = 'document.fonts.load(%s).then(function () {' % js(font)
    if iife:
        script = sub(script, "(function () {", load, 1, label="wait for the font")
        return sub(script, rx(r"\}\)\(\);\s*$"), "});", 1, label="close the wait")
    return load + script + "\n});"


def root_attrs(markup: str, duration: float) -> str:
    markup = sub(markup, 'data-width="1920"', 'data-width="1080"', 1, label="root width")
    markup = sub(markup, 'data-height="1080"', 'data-height="1920"', 1, label="root height")
    return sub(markup, 'data-duration="8"', 'data-duration="%.3f"' % duration, 1, label="root duration")


# ---------------------------------------------------------------- captions

def port_highlight(src: str, ctx: dict) -> str:
    """caption-highlight: a box sweeps behind the spoken word, all words of the group stay visible (the nearest to our Sweep)."""
    style, markup, script = split_component(src)
    style = sub(style, rx(r"html,\s*body\s*\{[^}]*\}"), "", 1, label="drop html/body rule (it would restyle the host page)")
    style = sub(style, rx(r"width: 1920px;\s*height: 1080px;"), "width: 1080px; height: 1920px;", 1, label="frame size")
    style = sub(style, "bottom: 140px;", "top: 0;", 1, label="position by group (set per group)")
    style = sub(style, "align-items: flex-end;", "align-items: flex-start;", 1, label="group aligns to its top")
    style = sub(style, "padding: 0 100px;", "padding: 0 60px;", 1, label="side margin")
    style = sub(style, 'font-family: "Montserrat", sans-serif;', 'font-family: "Inter", sans-serif;', 1, label="allow-listed font")
    style = sub(style, "background: linear-gradient(135deg, #ff1745 0%, #df1238 100%);", "background: %s;" % ctx["colors"]["accent"], 1, label="accent colour")
    style = sub(style, "box-shadow: 0 12px 30px rgba(229, 20, 58, 0.32);", "box-shadow: 0 8px 22px rgba(0, 0, 0, 0.35);", 1, label="shadow colour")
    markup = root_attrs(markup, ctx["duration"])
    script = sub(script, rx(r"var WORDS = \[.*?\n        \];", re.S), "var WORDS = %s;\n        var TOPS = %s;" % (js(ctx["words"]), js(ctx["tops"])), 1, label="our words and their zones")
    script = sub(script, rx(r"var RAW_GROUPS = \[.*?\n        \];", re.S), "var RAW_GROUPS = %s;" % js(ctx["chunks"]), 1, label="our caption chunks")
    script = sub(script, ": 8.0;", ": %.3f;" % ctx["duration"], 1, label="end of the last group")
    script = sub(script, 'fitFontSize(groupText, 80, "800", "Montserrat", 1620)', 'fitFontSize(groupText, 84, "800", "Inter", 940)', 1, label="size and measuring font")
    script = sub(script, 'grp.id = "hl-grp-" + gi;', 'grp.id = "hl-grp-" + gi;\n          grp.style.top = TOPS[gi] + "px";', 1, label="top of each group")
    script = font_wait(script, "800 84px Inter", True)
    return template(style, markup, script)


def port_emoji_pop(src: str, ctx: dict) -> str:
    """caption-emoji-pop: stroked uppercase words, a horizontal squeeze entrance (the nearest to our Pulse; it has no spoken-word colour)."""
    style, markup, script = split_component(src)
    style = sub(style, rx(r"html,\s*body\s*\{[^}]*\}"), "", 1, label="drop html/body rule (it would restyle the host page)")
    style = sub(style, rx(r"width: 1920px;\s*height: 1080px;"), "width: 1080px; height: 1920px;", 1, label="frame size")
    style = sub(style, rx(r"\.safe-zone\s*\{[^}]*\}"), ".safe-zone { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; }", 1, label="stage covers the frame")
    style = sub(style, rx(r"\.caption-group\s*\{[^}]*\}"),
                ".caption-group { position: absolute; left: 60px; top: 0; width: 960px; height: 280px; display: flex; align-items: center; "
                "justify-content: center; opacity: 0; transform-origin: 50% 50%; will-change: transform; backface-visibility: hidden; }", 1,
                label="group box (960 wide, top set per group)")
    style = sub(style, "max-width: 1400px;", "max-width: 960px;", 1, label="line width")
    style = sub(style, 'font-family: "Gabarito", Arial, sans-serif;', 'font-family: "Inter", Arial, sans-serif;', 1, label="allow-listed font")
    style = sub(style, "font-weight: 900;", "font-weight: 800;", 1, label="weight we have")
    markup = root_attrs(markup, ctx["duration"])
    script = sub(script, "var DURATION = 8;", "var DURATION = %.3f;" % ctx["duration"], 1, label="duration")
    script = sub(script, "var SAFE_ZONE_WIDTH = 1400;", "var SAFE_ZONE_WIDTH = 960;", 1, label="line width")
    script = sub(script, "var CAPTION_FONT_SIZE = 72;", "var CAPTION_FONT_SIZE = 112;", 1, label="type size for a portrait frame")
    script = sub(script, 'var ACCENT_COLORS = ["#FF76FF", "#FF0002", "#B2F7FF"];', "var ACCENT_COLORS = [%s];" % js(ctx["colors"]["accent"]), 1, label="our accent")
    script = sub(script, 'var KEYWORDS = new Set(["hyperframes", "html", "professional", "code", "cinema"]);', "var KEYWORDS = new Set([]);", 1,
                 label="no English keyword list")
    script = sub(script, rx(r"var WORD_EMOJI = \{.*?\n      \};", re.S), "var WORD_EMOJI = {};", 1, label="no emoji (no colour-emoji font in the allow-list)")
    script = sub(script, rx(r"var TRANSCRIPT = \[.*?\n      \];", re.S), "var TRANSCRIPT = %s;\n      var TOPS = %s;" % (js(ctx["words"]), js(ctx["tops"])), 1,
                 label="our words and their zones")
    script = sub(script, "if (rand > 0.55) {", "if (false) {", 1, label="no random colour on words")
    script = sub(script, 'measureContext.font = "900 " + fontSize + "px Gabarito";', 'measureContext.font = "800 " + fontSize + "px Inter";', 1,
                 label="measuring font")
    script = sub(script, rx(r'CAPTION_FONT_SIZE,\s*"900",\s*"Gabarito",'), 'CAPTION_FONT_SIZE,\n            "800",\n            "Inter",', 1, label="fit font")
    script = sub(script, "var GROUPS = makeGroups(WORDS);",
                 "var CHUNKS = %s;\n      var GROUPS = CHUNKS.map(function (p, gi) { return makeGroup(WORDS.slice(p[0], p[1] + 1), gi); });" % js(ctx["chunks"]), 1,
                 label="our caption chunks instead of its own grouping")
    script = sub(script, 'groupEl.className = "caption-group";', 'groupEl.className = "caption-group";\n          groupEl.style.top = TOPS[groupIndex] + "px";', 1,
                 label="top of each group")
    script = font_wait(script, "800 112px Inter", False)
    return template(style, markup, script)


def port_kinetic_slam(src: str, ctx: dict) -> str:
    """caption-kinetic-slam: one big word at a time, alternating entrances (the nearest to our Block)."""
    style, markup, script = split_component(src)
    style = sub(style, rx(r"html,\s*body\s*\{[^}]*\}"), "", 1, label="drop html/body rule (it would restyle the host page)")
    style = sub(style, rx(r"width: 1920px;\s*height: 1080px;"), "width: 1080px; height: 1920px;", 1, label="frame size")
    style = sub(style, 'font-family: "Anton", sans-serif;', 'font-family: "Inter", sans-serif;', 1, label="allow-listed font (Anton is not on the list)")
    style = sub(style, "font-weight: 400;", "font-weight: 800;", 1, label="weight we have")
    style = sub(style, "top: 50%;", "top: 0;", 1, label="position by word (set per word)")
    markup = root_attrs(markup, ctx["duration"])
    script = sub(script, rx(r"var WORDS = \[.*?\n        \];", re.S), "var WORDS = %s;\n        var TOPS = %s;" % (js(ctx["words"]), js(ctx["word_tops"])), 1,
                 label="our words and their zones")
    script = sub(script, "var KEYWORDS = new Set([8, 12, 15, 24, 27]); // HyperFrames, HTML, professional, code, cinema.", "var KEYWORDS = new Set([]);", 1,
                 label="no sample keyword list")
    script = sub(script, "220, \"400\", \"'Anton', sans-serif\", 1720", "190, \"800\", \"Inter\", 960", 1, label="size and measuring font")
    script = sub(script, 'el.id = "kt-w-" + wi;', 'el.id = "kt-w-" + wi;\n          el.style.top = TOPS[wi] + "px";', 1, label="top of each word")
    script = font_wait(script, "800 190px Inter", True)
    return template(style, markup, script)


CAPTIONS = {
    "sweep": ("caption-highlight", port_highlight),
    "pulse": ("caption-emoji-pop", port_emoji_pop),
    "block": ("caption-kinetic-slam", port_kinetic_slam),
}


# ---------------------------------------------------------------- overlays

CDN_GSAP = rx(r'\s*<script src="https://cdn\.jsdelivr\.net/npm/gsap@3\.14\.2/dist/gsap\.min\.js"></script>')


def port_spring_pop(src: str) -> str:
    """keyword: a badge pops in, overshoots once and settles."""
    out = sub(src, CDN_GSAP, "", 1, label="drop the CDN script (the page carries GSAP)")
    return sub(out, "font-size: clamp(14px, 9cqmin, 54px);", "font-size: var(--sp-font, 54px);", 1, label="type size set by the adapter from the text length (the component sizes it from the card height)")


def port_count_up(src: str) -> str:
    """number: a figure counts up and lands with one pulse."""
    out = sub(src, CDN_GSAP, "", 1, label="drop the CDN script (the page carries GSAP)")
    return sub(out, 'toLocaleString("en-US")', 'toLocaleString("pt-BR")', 1, label="thousands separator of the audience")


def port_testimonial(src: str) -> str:
    """quote: a card with the sentence and who said it."""
    return sub(src, CDN_GSAP, "", 1, label="drop the CDN script (the page carries GSAP)")


LIST_SNIPPET = """<template>
<style>
  #list-root { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; }
  .hf-catalog-line-by-line-slide { color: var(--hf-line-color); font-family: var(--font-display); font-weight: 800; letter-spacing: -0.02em;
    display: grid; justify-items: center; text-align: center; gap: var(--hf-line-gap, 10px); font-size: var(--hf-line-size); line-height: 1.05; overflow: hidden; }
  .hf-catalog-line-by-line-slide span { display: block; transform: translate(var(--hf-line-x, 0px), var(--hf-line-y, 0px));
    filter: blur(var(--hf-line-blur, 0px)); will-change: transform, filter, opacity; }
</style>
<div id="list-root" data-composition-id="%(id)s" data-width="%(w)d" data-height="%(h)d">
  <div class="hf-catalog-line-by-line-slide">%(spans)s</div>
</div>
<script>
  (function () {
    var host = document.querySelector('[data-composition-id=%(idq)s] .hf-catalog-line-by-line-slide');
    host.style.setProperty("--hf-line-size", %(size)s);
    host.style.setProperty("--hf-line-color", %(color)s);
    var tl = gsap.timeline({ paused: true });
    // the recipe from the component's trailing comment, one item every STEP seconds (ours reveal one after the other across the beat)
    %(steps)s
    window.__timelines[%(idj)s] = tl;
  })();
</script>
</template>
"""

TEXT_SNIPPET = """<template>
<style>
  #text-root { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; }
  .tx { color: var(--fg); font-family: var(--font-body); font-weight: 500; font-size: %(size)dpx; text-align: center; white-space: nowrap; }
</style>
<div id="text-root" data-composition-id="%(id)s" data-width="%(w)d" data-height="%(h)d"><div class="tx">%(text)s</div></div>
<script>
  (function () {
    var tl = gsap.timeline({ paused: true });
    tl.fromTo(".tx", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, 0.9);
    window.__timelines["%(id)s"] = tl;
  })();
</script>
</template>
"""


def html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def make_list(cid: str, items: list, w: int, h: int, color_css: str, duration: float) -> str:
    n = max(1, len(items))
    size = max(34, min(88, int(h / (n * 1.2))))
    step = max(0.35, min(1.2, (duration - 0.9) / n))
    spans = "".join("<span>%s</span>" % html_escape(t) for t in items)
    steps = "\n    ".join(
        "tl.fromTo(%s, { opacity: 0, '--hf-line-x': '-36px', '--hf-line-y': '18px', '--hf-line-blur': '6px' }, "
        "{ opacity: 1, '--hf-line-x': '0px', '--hf-line-y': '0px', '--hf-line-blur': '0px', duration: 0.34, ease: 'power3.out' }, %.3f);"
        % (js(".hf-catalog-line-by-line-slide span:nth-child(%d)" % (i + 1)), 0.1 + i * step) for i in range(n))
    return LIST_SNIPPET % {"id": cid, "idq": js(cid), "idj": js(cid), "w": w, "h": h, "spans": spans, "size": js("%dpx" % size), "color": js(color_css), "steps": steps}


def make_label(cid: str, text: str, w: int, h: int, size: int) -> str:
    return TEXT_SNIPPET % {"id": cid, "w": w, "h": h, "size": size, "text": html_escape(text)}
