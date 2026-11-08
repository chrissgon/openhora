#!/usr/bin/env python3
"""Tier A of the HyperFrames registry (package V3b-3): the admission lint and the wrapper of one registry component.

A component of the registry is somebody else's page: a composition with its own style, markup and script. This module decides whether one may
be drawn at all (`lint`) and, when it may, turns it into a part of OUR one root composition (`wrap`). Neither step runs a browser: both read the
component's text. The compatibility run (`hf_compat.py`) runs `lint` over a list of planted escapes and refuses to go on when one is admitted; the
drawing image's inner entry (`hf_render.py`) runs `lint` again on every instance and then `wrap`, so a file that changed after the admission
cannot be drawn.

`lint(html)` returns the closed codes of everything the component does that a block of ours may not do (an empty list admits it). The rules are
text rules and deliberately broad: a token inside a comment refuses the component too, because stripping comments with a pattern is how a lint
is walked around. `wrap(html, inst, files_sha, variables)` returns the text that replaces the instance's placeholder in `index.html`:

  * the instance element, clipped to its band (`contain: paint; overflow: clip`), holding the component's markup with every id prefixed
    `hf-inst-N-` and no composition timing attribute;
  * the component's style, inside `@scope (#hf-inst-N)`, with `html` and `body` rules dropped and `:root` read as `:scope`;
  * one script that registers a function, which the root script calls with the page's `main` timeline, its variables and GSAP. The function
    runs each of the component's scripts in strict mode with `window`, `document` and `gsap` as parameters: `window` is a Proxy over a frozen
    object exposing only `__timelines` (a local object), `getComputedStyle`, `innerWidth`/`innerHeight`, `document` and a `__hyperframes`
    whose `getVariables` returns the instance's own variables; its `set`, `defineProperty`, `deleteProperty` and `setPrototypeOf` traps throw
    `Error("hf-escape")`; `document` exposes `querySelector`, `querySelectorAll`, `getElementById` and `createElement`, bound to the instance
    (a short list of tags only); the network, the timers, the clock and the storage are shadowed by objects that throw the same error. The
    timelines the component registered are nested into `main` at the instance's start, and the instance is shown from its start to its end.

CLI (for the person who wants to look at a file): `hf_wrap.py --lint FILE` prints the codes as JSON. Standard library only; stdlib is all the
HyperFrames image has beside its Python.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys

MAX_BYTES = 256 * 1024
ESCAPE_MESSAGE = "hf-escape"
PREFIX = "hf-inst-%d-"
BAND_WIDTH, BAND_HEIGHT_MAX = 1080, 1920                  # the frame of the engine (the band's height is the instance's own)

ALLOWED_FAMILIES = {"inter", "jetbrains mono"}
GENERIC_FAMILIES = {"sans-serif", "serif", "monospace", "system-ui", "ui-monospace", "inherit", "initial", "unset"}
VARIABLE_TYPES = {"string": "text", "color": "color", "number": "number"}
VARIABLE_ID = re.compile(r"[^\x00-\x1f\x7f\"'<>\\]{1,64}")
SCRIPT_TYPES = ("", "text/javascript", "application/javascript")
SAFE_TAGS = ("div", "span", "p", "b", "i", "em", "strong", "small", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section")
TIMING_ATTRIBUTES = ("data-composition-id", "data-start", "data-width", "data-height", "data-track-index", "data-composition-src",
                     "data-composition-variables", "data-duration")

# The one script tag a registry component carries that is not its own: GSAP from a CDN, at an exact path. It is removed (the page has its
# own GSAP); a script tag with any other `src` is a refusal (`network`).
CDN_GSAP = re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"']https://(?:cdn\.jsdelivr\.net/npm/gsap@[0-9][0-9.]*/dist/gsap(?:\.min)?\.js|"
                      r"cdnjs\.cloudflare\.com/ajax/libs/gsap/[0-9][0-9.]*/gsap(?:\.min)?\.js)[\"'][^>]*>\s*</script>", re.I)

# The only form `window.__timelines` may be written in: the registry's own idiom and an assignment to one key of it.
TIMELINES_IDIOM = re.compile(r"window\s*\.\s*__timelines\s*=\s*window\s*\.\s*__timelines\s*\|\|\s*\{\s*\}")
TIMELINES_KEY = re.compile(r"window\s*\.\s*__timelines\s*\[[^\]\n]{1,80}\]\s*=(?!=)")

_ASSIGN = r"(?:[-+*/%&|^]|\*\*|<<|>>>?|&&|\|\||\?\?)?=(?!=)|\+\+|--"
_URL_SCHEME = r"(?:[a-z][a-z0-9+.\-]*:|//)"
# (code, pattern, flags): the closed codes, one list. JS tokens are case sensitive, HTML tokens are not.
RULES = [
    ("writes_window", r"\b(?:window|globalThis|self)\s*\.\s*[A-Za-z_$][\w$]*\s*(?:" + _ASSIGN + r")", 0),
    ("writes_window", r"\b(?:window|globalThis|self)\s*\[", 0),
    ("writes_window", r"\b(?:getPrototypeOf|setPrototypeOf|defineProperty|defineProperties|__defineGetter__|__defineSetter__)\b|__proto__|\bReflect\b", 0),
    ("top_layer", r"\bshowModal\b|\bpopover\b|\bshowPopover\b|\bshowPicker\b|\brequestFullscreen\b|<\s*dialog\b", 0),
    ("escapes_scope", r"\bownerDocument\b|\bparentNode\b|\bparentElement\b|\.\s*closest\s*\(|\bgetRootNode\b|\boffsetParent\b|\bcontentDocument\b|"
                      r"\bdocumentElement\b|\bdocument\s*\.\s*(?:body|head|scrollingElement)\b|\bcomposedPath\b", 0),
    ("network", r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|Worker|SharedWorker|importScripts)\b|\bsendBeacon\b|\bimport\s*\(", 0),
    ("network", r"<\s*link\b|@import", re.I),
    ("network", r"\burl\s*\(\s*[\"']?\s*" + _URL_SCHEME, re.I),
    ("network", r"\b(?:src|href|xlink:href|srcset|poster|action|formaction)\s*=\s*[\"']?\s*" + _URL_SCHEME, re.I),
    ("network", r"<\s*script\b[^>]*\bsrc\s*=", re.I),
    ("network", r"\.\s*(?:src|href|srcset|action)\s*=(?!=)|setAttribute\s*\(\s*[\"'](?:src|href|srcset|action)\b", 0),
    ("dynamic_code", r"\beval\b|\bFunction\s*\(|\bnew\s+Function\b|\.\s*constructor\b|\[\s*[\"'`]constructor|\bAsyncFunction\b|\bGeneratorFunction\b", 0),
    ("dynamic_code", r"\b(?:setTimeout|setInterval)\s*\(\s*[\"'`]", 0),
    ("dynamic_code", r"\bdocument\s*\.\s*write(?:ln)?\b|\binnerHTML\b|\bouterHTML\b|\binsertAdjacentHTML\b|\bsrcdoc\b|\bcreateContextualFragment\b|\bDOMParser\b", 0),
    ("dynamic_code", r"<[^>]*\son[a-z]{3,}\s*=|javascript\s*:|setAttribute\s*\(\s*[\"']on|createElement\s*\(\s*[\"'`](?:script|link|style|base|meta)\b", re.I),
    ("nondeterministic", r"Math\s*\.\s*random|\bDate\s*\.\s*now|\bnew\s+Date\b|\bDate\s*\(|\bperformance\b|\bgetRandomValues\b|\bcrypto\b", 0),
    ("timers", r"\b(?:setTimeout|setInterval|setImmediate|requestAnimationFrame|cancelAnimationFrame|requestIdleCallback|queueMicrotask)\b", 0),
    ("media", r"<\s*(?:img|video|audio|canvas|iframe|object|embed|picture|source|track)\b|background-image", re.I),
    ("media", r"\bnew\s+(?:Image|Audio|OffscreenCanvas|Option)\b|\bgetContext\b|\bOffscreenCanvas\b|createElement\s*\(\s*[\"'`](?:canvas|img|video|audio|iframe|object|embed)\b", 0),
    ("storage", r"\b(?:localStorage|sessionStorage|indexedDB|cookieStore|caches)\b|document\s*\.\s*cookie", 0),
    ("frames", r"(?<![\w$.])(?:top|parent|frames)\s*[.\[]|\bopener\b|\bwindow\s*\.\s*(?:top|parent|frames)\b|\bcontentWindow\b|\bpostMessage\b|\bBroadcastChannel\b", 0),
    ("fonts", r"@font-face", re.I),
]
_COMPILED = [(code, re.compile(pattern, flags)) for code, pattern, flags in RULES]
CODES = ("writes_window", "top_layer", "escapes_scope", "network", "dynamic_code", "nondeterministic", "timers", "media", "storage", "frames",
         "fonts", "variables_untyped", "too_large")


class WrapRefusal(Exception):
    """`wrap` was given a component the lint refuses, or one it cannot read (`code` is a closed word)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- reading a component

def strip_cdn(text: str) -> str:
    """The component without its CDN copy of GSAP (the page carries its own). Nothing else is removed."""
    return CDN_GSAP.sub("", text)


def declared_variables(text: str):
    """The variables the component declares in its own `data-composition-variables` attribute, as [{"id", "type", ...}], or None when it
    declares none. Raises ValueError when the attribute is not a list of objects."""
    found = re.search(r"data-composition-variables\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", text)
    if not found:
        return None
    try:
        rows = json.loads(htmllib.unescape(found.group(1) if found.group(1) is not None else found.group(2)))
    except ValueError:
        raise ValueError("variables") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("variables")
    return rows


def snake_case(name: str) -> str:
    """camelCase -> snake_case (`accentColor` -> `accent_color`)."""
    return re.sub(r"(?<=[a-z0-9])([A-Z])", lambda m: "_" + m.group(1).lower(), name).lower()


def typed_variables(text: str) -> list:
    """[{"id", "name", "type"}] of the declared variables, `type` one of the block parameter types (`text`, `color`, `number`) and `name` the
    snake_case parameter name (whether that name is a valid parameter name is the compatibility run's check, `param_name`). ValueError when a
    variable has no type of those, no valid or a repeated id, or the declaration is unreadable. A component with no declaration has no variables ([])."""
    rows = declared_variables(text)
    out, seen = [], set()
    for row in rows or []:
        vid, kind = row.get("id"), row.get("type")
        if not isinstance(vid, str) or not VARIABLE_ID.fullmatch(vid) or kind not in VARIABLE_TYPES or vid in seen:
            raise ValueError("variables")
        seen.add(vid)
        out.append({"id": vid, "name": snake_case(vid), "type": VARIABLE_TYPES[kind], "declared": row})
    return out


def _families(css: str):
    for found in re.finditer(r"font-family\s*:\s*([^;}]*)", css, re.I):
        yield found.group(1)
    for found in re.finditer(r"(?<![\w-])font\s*:\s*([^;}]*)", css, re.I):
        after = re.search(r"\d(?:px|em|rem|pt|%|cqw|cqh|vw|vh)(?:/[^\s,]+)?\s+(.*)", found.group(1), re.I)
        if after:
            yield after.group(1)


def fonts_ok(text: str) -> bool:
    """Every family a CSS declaration names is one of ours, a generic keyword or a `var(...)`; a canvas-style `12px Name` font string in a
    script is checked as `hf_render.check_fonts` checks it."""
    for value in _families(text):
        for token in re.split(r",", re.sub(r"var\([^)]*\)", "", value)):
            name = token.strip().strip("\"'").strip().lower()
            if name and name not in ALLOWED_FAMILIES and name not in GENERIC_FAMILIES and not name.startswith("!"):
                return False
    for found in re.finditer(r"\b\d+px\s+(?:\\?[\"'])?([A-Za-z][A-Za-z ]*?)(?:\\?[\"'])?[\"';,)]", text):
        name = found.group(1).strip().lower()
        if name and name not in ALLOWED_FAMILIES and name not in GENERIC_FAMILIES:
            return False
    return True


def lint(html: str) -> list:
    """The closed codes of what the component does that it may not, in the order of CODES; [] admits it."""
    if not isinstance(html, str):
        return ["too_large"]
    found = set()
    if len(html.encode("utf-8")) > MAX_BYTES:
        found.add("too_large")
    text = strip_cdn(html)
    scan = TIMELINES_KEY.sub("", TIMELINES_IDIOM.sub("", text))              # the two ways `window.__timelines` may be written are not assignments to window
    for code, rx in _COMPILED:
        if code in found:
            continue
        if rx.search(scan):
            found.add(code)
    if not fonts_ok(text):
        found.add("fonts")
    try:
        declared = typed_variables(text)
    except ValueError:
        found.add("variables_untyped")
        declared = []
    if re.search(r"\bgetVariables\b|__hfVariables|__hfV\b", text) and declared_variables_present(text) is False:
        found.add("variables_untyped")
    return [code for code in CODES if code in found]


def declared_variables_present(text: str) -> bool:
    try:
        return declared_variables(text) is not None
    except ValueError:
        return True                                                           # present and unreadable: `typed_variables` already refused it


# ---------------------------------------------------------------- parsing and rewriting

_TAG = re.compile(r"<([A-Za-z][A-Za-z0-9-]*)((?:\s+[^\s>=/]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?)*)\s*(/?)>")
_ATTR = re.compile(r"([^\s=/>]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+))?")
_STYLE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)
_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def parse_component(text: str) -> dict:
    """{styles: [css], scripts: [js], markup: html}: the component read as a `<template>` wrapper or as a whole document. Inline scripts
    of a type other than JavaScript are dropped; a script with a `src` was refused by the lint."""
    text = strip_cdn(text)
    styles = [m.group(1).strip("\n") for m in _STYLE.finditer(text)]
    scripts = []
    for m in _SCRIPT.finditer(text):
        kind = re.search(r"\btype\s*=\s*[\"']?([^\"'\s>]*)", m.group(1), re.I)
        if (kind.group(1).lower() if kind else "") in SCRIPT_TYPES:
            scripts.append(m.group(2).strip("\n"))
    body = _COMMENT.sub("", _SCRIPT.sub("", _STYLE.sub("", text)))
    template = re.search(r"<template\b[^>]*>(.*)</template>", body, re.S | re.I)
    if template:
        body = template.group(1)
    else:
        inner = re.search(r"<body\b[^>]*>(.*)</body>", body, re.S | re.I)
        body = inner.group(1) if inner else re.sub(r"<!doctype[^>]*>|</?html\b[^>]*>|<head\b[^>]*>.*?</head>", "", body, flags=re.S | re.I)
    return {"styles": styles, "scripts": scripts, "markup": body.strip("\n")}


def ids_of(markup: str) -> list:
    out = []
    for tag in _TAG.finditer(markup):
        for attr in _ATTR.finditer(tag.group(2)):
            if attr.group(1).lower() == "id" and attr.group(2):
                value = attr.group(2).strip("\"'")
                if value and value not in out:
                    out.append(value)
    return out


def num(x: float) -> str:
    return repr(float(x))


def rewrite_markup(markup: str, prefix: str, ids: list, duration: float) -> str:
    """The markup with every id prefixed, the references to those ids prefixed, no composition timing attribute, no `clip` class, and the
    root's `data-duration` set to the instance's own."""
    def tag(m):
        attrs, root = [], False
        parsed = [(a.group(1), a.group(2)) for a in _ATTR.finditer(m.group(2))]
        root = any(name.lower() == "data-composition-id" for name, _ in parsed)
        for name, value in parsed:
            low = name.lower()
            raw = value.strip("\"'") if value is not None else None
            if low == "data-duration" and root:
                attrs.append((low, num(duration)))
            elif low in TIMING_ATTRIBUTES:
                continue
            elif low == "id" and raw:
                attrs.append((low, prefix + raw))
            elif low == "class" and raw is not None:
                kept = [c for c in raw.split() if c != "clip"]
                if kept:
                    attrs.append((low, " ".join(kept)))
            elif raw is None:
                attrs.append((low, None))
            else:
                attrs.append((low, re.sub(r"(?<![\w-])#(%s)\b" % "|".join(re.escape(i) for i in ids), lambda mm: "#" + prefix + mm.group(1), raw) if ids else raw))
        body = "".join(" %s" % n if v is None else ' %s="%s"' % (n, v.replace('"', "&quot;")) for n, v in attrs)
        return "<%s%s%s>" % (m.group(1), body, " /" if m.group(3) else "")
    out = _TAG.sub(tag, markup)
    for ident in ids:
        out = out.replace("url(#%s)" % ident, "url(#%s%s)" % (prefix, ident))
    return out


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str):
    """The top-level (prelude, body) pairs of a stylesheet and any text after the last block ('' normally). Strings are skipped."""
    out, depth, start, i, quote = [], 0, 0, 0, None
    prelude = ""
    while i < len(css):
        ch = css[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            if depth == 0:
                prelude, start = css[start:i].strip(), i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append((prelude, css[start:i]))
                start = i + 1
            elif depth < 0:
                raise WrapRefusal("block_lint")
        elif ch == ";" and depth == 0:
            out.append((css[start:i].strip(), None))                          # a statement rule such as `@layer a;`
            start = i + 1
        i += 1
    if depth != 0:
        raise WrapRefusal("block_lint")
    return out


def _selectors(prelude: str) -> list:
    parts, depth, cur = [], 0, ""
    for ch in prelude:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def scope_css(css: str, prefix: str, ids: list) -> str:
    """The component's CSS for use inside `@scope (#hf-inst-N)`: rules on `html` and `body` dropped, `:root` read as `:scope`, ids prefixed.
    `@media` and `@supports` are entered; `@keyframes` are kept as they are."""
    out = []
    for prelude, body in _blocks(_strip_comments(css)):
        if body is None:
            continue
        low = prelude.lower()
        if low.startswith(("@media", "@supports", "@container", "@layer")):
            inner = scope_css(body, prefix, ids)
            if inner.strip():
                out.append("%s {\n%s\n}" % (prelude, inner))
        elif prelude.startswith("@"):
            out.append("%s {%s}" % (prelude, body))
        else:
            kept = []
            for selector in _selectors(prelude):
                if re.match(r"(?:html|body)(?![\w-])", selector, re.I):
                    continue
                selector = re.sub(r":root\b", ":scope", selector)
                if ids:
                    selector = re.sub(r"#(%s)(?![\w-])" % "|".join(re.escape(i) for i in ids), lambda m: "#" + prefix + m.group(1), selector)
                kept.append(selector)
            if kept:
                out.append("%s {%s}" % (", ".join(kept), body))
    return "\n".join(out)


# ---------------------------------------------------------------- the script

def js(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


DENIED = ("fetch", "XMLHttpRequest", "WebSocket", "EventSource", "Worker", "SharedWorker", "Image", "Audio", "Date", "performance", "setTimeout",
          "setInterval", "requestAnimationFrame", "cancelAnimationFrame", "localStorage", "sessionStorage", "indexedDB", "navigator", "location",
          "history", "open", "alert", "postMessage", "importScripts", "Function", "Reflect")
ALIASES = ("window", "self", "globalThis", "top", "parent", "frames")       # every name the page's global object goes by, all bound to the guarded window

REGISTER = """(window.__hfTierA = window.__hfTierA || {})[%(n)d] = function (main, V, gsap) {
  "use strict";
  var REAL = document, REAL_WIN = window, INST = REAL.getElementById(%(inst)s), PFX = %(pfx)s, IDS = %(ids)s, DECL = %(decl)s;
  var ESC = {hit: false};
  function hit() { ESC.hit = true; try { console.error(%(msg)s); } catch (e) {} throw new Error(%(msg)s); }
  var deny = new Proxy(function () {}, {get: hit, set: hit, apply: hit, construct: hit, has: hit, defineProperty: hit, deleteProperty: hit});
  function sel(s) { return String(s).replace(/#([A-Za-z][\\w-]*)/g, function (m, id) { return IDS.indexOf(id) < 0 ? m : "#" + PFX + id; }); }
  var SAFE = %(safe)s;
  var D = Object.freeze({
    querySelector: function (s) { return INST.querySelector(sel(s)); },
    querySelectorAll: function (s) { return INST.querySelectorAll(sel(s)); },
    getElementById: function (id) { return REAL.getElementById(PFX + id); },
    createElement: function (t) { t = String(t).toLowerCase(); if (SAFE.indexOf(t) < 0) hit(); return REAL.createElement(t); }
  });
  var timelines = {};
  var vars = Object.freeze({getVariables: function () {
    var src = (V.inst && V.inst[%(n)d]) || {}, out = {};
    DECL.forEach(function (d) { if (Object.prototype.hasOwnProperty.call(src, d.name)) out[d.id] = src[d.name]; });
    return out;
  }});
  var base = Object.assign(Object.create(null), {__timelines: timelines, getComputedStyle: REAL_WIN.getComputedStyle.bind(REAL_WIN),
    innerWidth: %(width)d, innerHeight: %(height)d, document: D, __hyperframes: vars});
  var guarded = new Proxy(Object.freeze(base), {
    set: function (t, k, v) { if (k === "__timelines" && v === timelines) return true; return hit(); },
    defineProperty: hit, deleteProperty: hit, setPrototypeOf: hit, preventExtensions: hit,
    get: function (t, k) { return typeof k === "string" && Object.prototype.hasOwnProperty.call(t, k) ? t[k] : undefined; },
    has: function (t, k) { return Object.prototype.hasOwnProperty.call(t, k); }
  });
%(scripts)s
  Object.keys(timelines).sort().forEach(function (k) { timelines[k].paused(false); main.add(timelines[k], %(start)s); });
  main.set(INST, {visibility: "visible"}, %(start)s);
  main.set(INST, {visibility: "hidden"}, %(end)s);
  if (ESC.hit) hit();
};"""

RUN_ONE = """  (function (%(params)s) {
    "use strict";
%(code)s
  }).call(undefined, %(args)s);"""


def build_script(parts: dict, n: int, ids: list, decl: list, start: float, end: float, band: dict) -> str:
    params = list(ALIASES) + ["document", "gsap"] + list(DENIED)
    args = ["guarded"] * len(ALIASES) + ["D", "gsap"] + ["deny"] * len(DENIED)
    runs = "\n".join(RUN_ONE % {"params": ", ".join(params), "args": ", ".join(args), "code": script} for script in parts["scripts"])
    return REGISTER % {"n": n, "inst": js("hf-inst-%d" % n), "pfx": js(PREFIX % n), "ids": js(ids), "decl": js([{"id": d["id"], "name": d["name"]} for d in decl]),
                       "msg": js(ESCAPE_MESSAGE), "safe": js(list(SAFE_TAGS)), "width": BAND_WIDTH, "height": BAND_HEIGHT_MAX, "scripts": runs,
                       "start": num(start), "end": num(end)}


# ---------------------------------------------------------------- wrap

def wrap(html: str, inst: dict, files_sha: dict, variables: list) -> str:
    """The text that replaces the placeholder of instance `inst["n"]`: its element (with the band `inst["top"]` and `inst["height"]` in pixels,
    `inst["zone"]`), its scoped style and its registering script. `files_sha` is {file: sha256} of the component's files (its digest goes in
    the element, so a changed file is a changed page); `variables` is `typed_variables(html)` (the names the shim returns). Raises
    `WrapRefusal` when the lint refuses the component. The same inputs give the same text."""
    if lint(html):
        raise WrapRefusal("block_lint")
    n = inst["n"]
    prefix = PREFIX % n
    parts = parse_component(html)
    ids = ids_of(parts["markup"])
    start, end = float(inst["start"]), float(inst["end"])
    markup = rewrite_markup(parts["markup"], prefix, ids, end - start)
    css = scope_css("\n".join(parts["styles"]), prefix, ids)
    digest = hashlib.sha256("".join("%s  %s\n" % (files_sha[k], k) for k in sorted(files_sha)).encode("utf-8")).hexdigest()[:12]
    top, height = inst["top"], inst["height"]
    element = ('<div id="hf-inst-%d" class="hf-inst" data-hf-zone="%s" data-hf-tier-a="%d" data-hf-files="%s" style="position:absolute; left:0; top:%spx; '
               'width:%dpx; height:%spx; contain:paint; overflow:clip; visibility:hidden">\n%s\n</div>'
               % (n, inst["zone"], n, digest, _px(top), BAND_WIDTH, _px(height), markup))
    style = "<style>\n@scope (#hf-inst-%d) {\n%s\n}\n</style>" % (n, css)
    script = "<script>\n%s\n</script>" % build_script(parts, n, ids, variables, start, end, {"top": top, "height": height})
    return "\n".join((element, style, script))


def _px(x) -> str:
    return str(int(x)) if x == int(x) else repr(float(x))


# ---------------------------------------------------------------- the command line

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lint", metavar="FILE", help="print the lint codes of FILE as a JSON list (an empty list admits it)")
    args = p.parse_args(argv)
    if not args.lint:
        p.print_help(sys.stderr)
        return 2
    with open(args.lint, encoding="utf-8", errors="replace") as fh:
        print(json.dumps(lint(fh.read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
