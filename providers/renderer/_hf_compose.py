"""The composed page of the HyperFrames engine: the base page (cuts and zoom, `_hf_page`) plus the captions and the beats, as ONE root
composition with ONE GSAP timeline registered as `window.__timelines["main"]`.

The common image writes it, from the same checked edit list and beats the ffmpeg engine draws, and the HyperFrames image only renders it.
Two runtimes draw a block on this engine, chosen per block (our `gsap` first, else `renderat`):

  gsap      the block's `gsap.html` (`_gsap_lint.py` is its contract) is inlined once per timeline entry: its markup in an instance element
            clipped to the entry's band (`contain: paint; overflow: clip`), its style inside `@scope (#hf-inst-N)`, its `build(root, tl, data,
            ctx)` run once into a child timeline that the root timeline places at the entry's start;
  renderat  the block's `renderat.html` (an `oh:` page, the page the ffmpeg engine draws) is served from `blocks/<ns>-<name>.html` into one
            full-frame iframe per block, with the colours and fonts set as the ffmpeg engine's driver sets them and the same guard on timers
            and the network; one tween of a getter/setter object on the root timeline calls the page's `renderAt` at every seek.

A tier-A block (an overlay admitted from the registry, `hyperframes-image/hf_compat.py`) is a third case: the page holds only its placeholder
element and one row of `instances.json` (the block's files with their sha256, its start and end in seconds, its band); the drawing image reads
the component's files from its own registry folder, checks each hash, lints and wraps it (`hyperframes-image/hf_wrap.py`) and replaces the
placeholder. Its parameters are `inst[N]` in `vars.json`, under their snake_case names.

Text never reaches `index.html`: every word is in `vars.json` (`inst[N]` for a gsap instance, `ra[key][i]` for a renderat entry), cleaned as
`check_beats` cleans it. `index.html` holds structure and numbers only. Fonts are the three allow-listed files (`fonts/<file>`, copied into
the project by the HyperFrames image); a page never names another family and never the theme's `system_fallback`. The same inputs write the
same bytes: sorted keys, no clock, no random. Standard library only; imports only common modules.
"""
from __future__ import annotations

import hashlib
import os

import _assets
import _blocks
import _edl
import _gsap_lint
import _hf_page
import _layout
import _payload
from _hf_page import COLOR, dumps, num
from _text import Refusal, is_clean

ENGINE = "hyperframes"
RUNTIME_ORDER = ("gsap", "renderat")                    # the engine's runtimes in this order: our own page first
MAX_VARS_BYTES = 256 * 1024                             # the same figures as hyperframes-image/hf_render.py, which the image holds
MAX_PAGE_BYTES = 2 * 1024 ** 2
MAX_BLOCK_PAGE_BYTES = 1 << 20
MAX_BLOCK_PAGES = 16
MAX_INSTANCES_BYTES = 256 * 1024                        # instances.json, the tier-A rows (the same figure as hf_render.py)
ZONE_ORDER = ("card", "caption")                        # the layers above the video, bottom first (the frame band is not drawn on this engine)

# The three allow-listed fonts (assets/fonts/allowlist.json; a test keeps the two equal): id -> (family, weight, file).
FONT_FILES = {"inter-500": ("Inter", 500, "inter-500.woff2"), "inter-800": ("Inter", 800, "inter-800.woff2"),
              "jetbrains-mono-500": ("JetBrains Mono", 500, "jetbrains-mono-500.woff2")}
DEFAULT_FONT = {"display": "inter-800", "text": "inter-500", "mono": "jetbrains-mono-500"}      # what `default` means here (the image has no system font)
STACKS = {"Inter": '"Inter", sans-serif', "JetBrains Mono": '"JetBrains Mono", monospace'}

# The guard of the renderat pages: the timers, the clocks, the random source and the network throw, as in `_cdp.FREEZE_JS`.
GUARD_JS = """(function () {
  var boom = function (n) { return function () { throw new Error(n + ' is forbidden in a template'); }; };
  Date.now = boom('Date.now');
  window.Date = function () { throw new Error('Date is forbidden in a template'); };
  performance.now = boom('performance.now');
  Math.random = boom('Math.random');
  window.setTimeout = boom('setTimeout');
  window.setInterval = boom('setInterval');
  window.requestAnimationFrame = boom('requestAnimationFrame');
  window.fetch = boom('fetch');
  window.XMLHttpRequest = function () { throw new Error('XMLHttpRequest is forbidden'); };
  window.WebSocket = function () { throw new Error('WebSocket is forbidden'); };
  window.Worker = function () { throw new Error('Worker is forbidden'); };
})();"""

# The drive of the renderat pages: `RA` is {key: [[first frame, last frame + 1], ...]} (numbers), the texts are V.ra[key][i].
DRIVE_JS = """var RF = {};
document.querySelectorAll("iframe.hf-ra").forEach(function (el) { RF[el.getAttribute("data-hf-key")] = el; });
function drive(k, t) {
  var f = Math.round(t * V.fps), list = RA[k], el = RF[k], idx = -1;
  for (var i = 0; i < list.length; i++) { if (f >= list[i][0] && f < list[i][1]) { idx = i; break; } }
  if (idx < 0) { el.style.visibility = "hidden"; return; }
  var win = el.contentWindow;
  if (!win || typeof win.__frame !== "function") return;
  el.style.visibility = "visible";
  win.__frame((f - list[idx][0]) / V.fps, V.ra[k][idx]);
}"""


def px(x) -> str:
    """A pixel figure as the shortest text that reads back exactly."""
    return str(int(x)) if x == int(x) else repr(float(x))


def fail(code: str, field: str):
    raise Refusal(code, field[:80])


# ---------------------------------------------------------------- fonts and colours

def map_fonts(edl: dict) -> dict:
    """{role: (family, weight, file)} for the edit list's theme fonts on this engine. An allow-list id maps to its file, and its weight must be
    the file's; `default` maps to DEFAULT_FONT (OPEN-2); any other id, or another weight, is `font_not_on_engine`."""
    used = {}
    for role, spec in sorted(edl["theme"]["fonts"].items()):
        field = "edl.theme.fonts.%s" % role
        font_id = DEFAULT_FONT.get(role) if spec["id"] == "default" else spec["id"]
        if font_id not in FONT_FILES or FONT_FILES[font_id][1] != spec["weight"]:
            fail("font_not_on_engine", field)
        used[role] = FONT_FILES[font_id]
    return used


def font_face_css(fonts: dict, prefix: str) -> str:
    seen, rows = set(), []
    for family, weight, file in sorted(fonts.values()):
        if file not in seen:
            seen.add(file)
            rows.append('@font-face{font-family:"%s";font-weight:%d;font-display:block;src:url("%s%s") format("woff2");}' % (family, weight, prefix, file))
    return "\n".join(rows)


def theme_pairs(edl: dict, fonts: dict) -> list:
    """[(custom property, value)] of the theme: the colour tokens, the weights and the font stacks of the roles. Colours are checked as hex."""
    pairs = []
    for token, value in sorted(edl["theme"]["colors"].items()):
        if not isinstance(value, str) or not COLOR.fullmatch(value):
            fail("bad_color", "edl.theme.colors.%s" % token)
        pairs.append(("--c-%s" % token, value))
    for role, (family, weight, _) in sorted(fonts.items()):
        pairs.append(("--weight-%s" % role, str(weight)))
        pairs.append(("--font-%s" % role, STACKS[family]))
    return pairs


# ---------------------------------------------------------------- the blocks of the timeline

def runtime_of(catalogue: dict, block: dict) -> str:
    """The runtime that draws `block` on this engine: the first of RUNTIME_ORDER the engine runs and the block implements."""
    runs = set(catalogue["engines"][ENGINE]["runtimes"])
    for runtime in RUNTIME_ORDER:
        if runtime in runs and runtime in block["implementations"]:
            return runtime
    fail("block_not_on_engine", block["name"])


def impl_path(block: dict, runtime: str) -> str:
    """The implementation's path inside blocks/ ("oh/keyword/renderat.html")."""
    ns, short = block["name"].split(":")
    return "%s/%s/%s" % (ns, short, block["implementations"][runtime])


def tier_a_digest(block: dict) -> str:
    """The pin of a tier-A block in the render's `blocks` map: the sha256 of its files' sha256 lines (`<sha256>  <file>`, sorted by file)."""
    return hashlib.sha256("".join("%s  %s\n" % (block["files"][k], k) for k in sorted(block["files"])).encode("utf-8")).hexdigest()


def block_pin(catalogue: dict, block: dict, runtime: str) -> str:
    if block.get("tier") == "A":
        return tier_a_digest(block)
    return catalogue["files"][impl_path(block, runtime)]


def read_block_file(catalogue: dict, block: dict, runtime: str) -> tuple:
    """(path inside blocks/, its text) of the implementation, read again from the staged folder and checked against the pinned hash."""
    rel = impl_path(block, runtime)
    pinned = catalogue["files"].get(rel)
    if pinned is None:
        fail("template_not_pinned", _blocks.field_of(rel))
    raw = _assets.read_regular(os.path.join(catalogue["dir"], rel), _blocks.MAX_FILE, "template_unreadable", _blocks.field_of(rel))
    if hashlib.sha256(raw).hexdigest() != pinned:
        fail("block_hash", _blocks.field_of(rel))
    try:
        return rel, raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("template_unreadable", _blocks.field_of(rel))


def draw_plan(data: dict, edl: dict, beats: dict, vocab: dict, catalogue: dict, fps: int) -> list:
    """The entries the engine draws, in layer order (the cards, then the captions), each {zone, key, block, runtime, band, start, end, payload,
    field}; every block resolved on this engine, its tier and band checked, its parameters and texts checked."""
    if ENGINE not in catalogue["engines"]:
        fail("engine_unknown", ENGINE)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    by_index = {w["index"]: w for w in edl["words"]}
    plan = []
    if timeline["captions"]:
        block = _blocks.resolve(catalogue, ENGINE, "caption", None, "edl.captions")
        if block.get("tier") == "A":
            fail("caption_tier_b_only", "edl.captions")                         # tier A admits overlays only (OPEN-7)
        for k, chunk in enumerate(timeline["captions"]):
            for w in (by_index[i] for i in range(chunk["word_from"], chunk["word_to"] + 1) if i in by_index):
                if not is_clean(w["text"]):
                    fail("text_not_clean", "edl.words")
            plan.append({"zone": "caption", "key": "caption", "block": block, "field": "edl.captions[%d]" % k, "entry": chunk,
                         "payload": _payload.caption_data(data, edl, chunk, by_index, fps)})
    for e in timeline["beats"]:
        field = "beats.%s" % e["id"]
        block = _blocks.resolve(catalogue, ENGINE, e["preset"], e.get("block"), field)
        if block["band"] != "card":
            fail("preset_not_on_engine", field)
        clean = _blocks.check_params(block, e["params"], vocab, field + ".params")
        if clean != e["params"]:
            fail("text_not_clean", field + ".params")
        e["block"] = block["name"]
        tier_a = block.get("tier") == "A"
        # A tier-A instance gets only the parameters its block declares (snake_case names, as `check_params` just checked them); the page gets
        # them as `inst[N]`, and the drawing image's wrapper hands them to the component as its own variables.
        payload = dict(clean) if tier_a else _payload.beat_data(data, e, fps, edl)
        plan.append({"zone": "card", "key": block["name"], "block": block, "field": field, "entry": e, "payload": payload, "tier_a": tier_a})
    plan.sort(key=lambda p: ZONE_ORDER.index(p["zone"]))                         # stable: the timeline order inside a layer
    for p in plan:
        top, bottom = _layout.zones(data, p["entry"]["face"])[p["zone"]]
        if bottom - top <= 0:
            fail("band_too_small", p["field"])
        p["band"] = (top, bottom - top)
        p["start"], p["end"] = p["entry"]["start_frame"], p["entry"]["end_frame"]
        p["runtime"] = runtime_of(catalogue, p["block"])
    return plan


# ---------------------------------------------------------------- the page

def gsap_scripts(plan: list, catalogue: dict) -> tuple:
    """({block name: parts of its gsap.html}, {block name: function suffix}) for the blocks the plan draws with gsap, each file linted once."""
    parts, suffix = {}, {}
    for p in plan:
        name = p["block"]["name"]
        if p["runtime"] == "gsap" and not p.get("tier_a") and name not in parts:
            rel, text = read_block_file(catalogue, p["block"], "gsap")
            _gsap_lint.check(text, name)
            parts[name] = _gsap_lint.parse(text, name)
            suffix[name] = len(suffix)
    return parts, suffix


def renderat_page(text: str, name: str, pairs: list, fonts: dict) -> str:
    """The block's `renderat.html` with, right after its charset line (else after `<head>`), the guard, the theme's custom properties set inline on the root element (an inline
    value beats the page's own `:root` rule) and the page's `@font-face` rules, and the `__frame` the root timeline calls."""
    charset = '<meta charset="utf-8">'
    anchor = charset if text.count(charset) == 1 else "<head>"                   # the charset stays in the first 1024 bytes of the page
    if text.count("<head>") != 1 or text.count(anchor) != 1:
        fail("block_lint", "%s head" % name)
    sets = "\n".join("  rs.setProperty(%s, %s);" % (dumps(k), dumps(v)) for k, v in pairs)
    loads = "\n".join("  document.fonts.load(%s);" % dumps("%d 20px \"%s\"" % (weight, family)) for family, weight, _ in sorted(set(fonts.values())))
    setup = ("(function () {\n  var rs = document.documentElement.style;\n%s\n  if (document.fonts && document.fonts.load) {\n%s\n  }\n"
             "  window.__frame = function (t, data) { window.renderAt(t, data); };\n})();" % (sets, loads))
    insert = "\n<style>\n%s\n</style>\n<script>\n%s\n%s\n</script>" % (font_face_css(fonts, "../fonts/"), GUARD_JS, setup)
    return text.replace(anchor, anchor + insert, 1)


def write_page(data: dict, edl: dict, beats: dict, vocab: dict, catalogue: dict, out_dir: str, fps: int) -> dict:
    """Write `index.html`, `vars.json` and, for the renderat blocks, `blocks/<ns>-<name>.html` into `out_dir`, an existing empty folder.
    Returns {page_sha256, vars_sha256, clips, zooms, duration, fps, layers, blocks, blocks_sha256, captions_drawn, beats_drawn, runtimes,
    fonts_used}. Everything is checked before anything is written."""
    frame = data["frame"]
    background = data["theme"]["colors"]["bg"]
    _hf_page.check_target(out_dir, background)
    plan = draw_plan(data, edl, beats, vocab, catalogue, fps)
    fonts = map_fonts(edl)
    pairs = theme_pairs(edl, fonts)
    gsap_parts, suffix = gsap_scripts(plan, catalogue)
    parts = _hf_page.build_parts(edl, fps=fps)

    css = [font_face_css(fonts, "fonts/"), ":root{%s}" % ";".join("%s:%s" % pair for pair in pairs),
           ".hf-inst,.hf-ra{position:absolute;display:block}", '[data-hf-zone="card"]{z-index:1}', '[data-hf-zone="caption"]{z-index:2}']
    layers, tail, inst, ra, ra_frames, ra_keys = [], [], [], {}, {}, []
    tier_a_rows = {}
    for p in plan:
        name = p["block"]["name"]
        if p.get("tier_a"):
            n = len(inst)
            ident = "hf-inst-%d" % n
            top, height = p["band"]
            layers.append('<div id="%s" class="hf-inst" data-hf-zone="%s" data-hf-tier-a="%d" style="position:absolute; left:0; top:%spx; width:%dpx; '
                          'height:%spx; contain:paint; overflow:clip; visibility:hidden"></div>' % (ident, p["zone"], n, px(top), frame["width"], px(height)))
            start, end = p["start"] / float(fps), p["end"] / float(fps)
            tail.append("__hfTierA[%d](main, V, gsap);" % n)
            tier_a_rows[str(n)] = {"name": p["block"]["name"], "files": dict(sorted(p["block"]["files"].items())),
                                   "implementation": p["block"]["implementations"]["gsap"], "start": start, "end": end, "band": [top, height]}
            inst.append(p["payload"])
        elif p["runtime"] == "gsap":
            n = len(inst)
            ident = "hf-inst-%d" % n
            top, height = p["band"]
            layers.append('<div id="%s" class="hf-inst" data-hf-zone="%s" data-hf-block="%s" style="position:absolute; left:0; top:%spx; width:%dpx; '
                          'height:%spx; contain:paint; overflow:clip; visibility:hidden">\n%s\n</div>'
                          % (ident, p["zone"], name, px(top), frame["width"], px(height), gsap_parts[name]["markup"]))
            css.append("@scope (#%s) {\n%s\n}" % (ident, gsap_parts[name]["style"]))
            start, end = p["start"] / float(fps), p["end"] / float(fps)
            ctx = {"fps": fps, "duration": (p["end"] - p["start"]) / float(fps), "band": {"top": top, "height": height}}
            tail.append('const tl_%d = gsap.timeline(); build_%d(document.getElementById("%s"), tl_%d, V.inst[%d], %s);\n'
                        'main.add(tl_%d, %s);\nmain.set("#%s", {visibility:"visible"}, %s);\nmain.set("#%s", {visibility:"hidden"}, %s);'
                        % (n, suffix[name], ident, n, n, dumps(ctx), n, num(start), ident, num(start), ident, num(end)))
            inst.append(p["payload"])
        else:
            if p["key"] not in ra:
                ra[p["key"]], ra_frames[p["key"]] = [], []
                ra_keys.append((p["key"], p["zone"], p["block"]))
            ra[p["key"]].append(p["payload"])
            ra_frames[p["key"]].append([p["start"], p["end"]])
    ra_keys.sort(key=lambda row: (0 if row[0] == "caption" else 1, row[0]))                       # the caption first, then each block by name
    files = {}
    runtimes = {p["block"]["name"]: p["runtime"] for p in plan}
    pages = {}
    for key, zone, block in ra_keys:
        ns, short = block["name"].split(":")
        page_name = "blocks/%s-%s.html" % (ns, short)
        rel, text = read_block_file(catalogue, block, "renderat")
        files[page_name] = renderat_page(text, block["name"], pairs, fonts).encode("utf-8")
        if len(files[page_name]) > MAX_BLOCK_PAGE_BYTES:
            fail("page_too_large", block["name"])
        pages[key] = page_name
        layers.append('<iframe class="hf-ra" data-hf-zone="%s" data-hf-key="%s" src="%s" style="position:absolute; inset:0; width:%dpx; height:%dpx; '
                      'border:0; visibility:hidden" scrolling="no"></iframe>' % (zone, key, page_name, frame["width"], frame["height"]))
    if len(files) > MAX_BLOCK_PAGES:
        fail("page_too_large", "blocks")
    scripts = ["\n".join(g["script"].replace("function build(", "function build_%d(" % suffix[name], 1) for name, g in sorted(gsap_parts.items(),
               key=lambda kv: suffix[kv[0]]))] if gsap_parts else []
    if ra_keys:
        scripts.append("var RA = %s;\n%s" % (dumps(ra_frames), DRIVE_JS))
        for j, (key, zone, block) in enumerate(ra_keys):
            seconds = num(parts["out_seconds"])
            scripts.append('var D_%d = {at: function (v) { if (v === undefined) return this._t || 0; this._t = v; drive(%s, v); }};\n'
                           'main.fromTo(D_%d, {at: 0}, {at: %s, duration: %s, ease: "none", immediateRender: true}, 0);' % (j, dumps(key), j, seconds, seconds))
    scripts.extend(tail)

    full_vars = dict(parts["vars"], inst=inst, ra=ra)
    defaults = dict(parts["vars"], inst=[], ra={})
    page = _hf_page.render_page(dict(parts, vars=defaults), width=frame["width"], height=frame["height"], fps=fps, background=background,
                                css="\n".join(css) + "\n", layers=("\n" + "\n".join(layers)) if layers else "",
                                tail=("\n".join(scripts) + "\n") if scripts else "")
    files["index.html"] = page.encode("utf-8")
    if tier_a_rows:
        files["instances.json"] = (dumps(tier_a_rows) + "\n").encode("utf-8")
        if len(files["instances.json"]) > MAX_INSTANCES_BYTES:
            fail("page_too_large", "instances.json")
    files["vars.json"] = (dumps(full_vars) + "\n").encode("utf-8")
    if len(files["vars.json"]) > MAX_VARS_BYTES:
        fail("vars_too_large", "vars.json")
    if len(files["index.html"]) > MAX_PAGE_BYTES:
        fail("page_too_large", "index.html")
    _hf_page.write_files(out_dir, dict(sorted(files.items())))
    shown = [name for name in ("captions" if any(p["zone"] == "caption" for p in plan) else None, "beats" if any(p["zone"] == "card" for p in plan) else None) if name]
    return {"page_sha256": hashlib.sha256(files["index.html"]).hexdigest(), "vars_sha256": hashlib.sha256(files["vars.json"]).hexdigest(),
            "clips": len(parts["clips"]), "zooms": len(parts["zooms"]), "duration": round(parts["out_seconds"], 3), "fps": fps,
            "layers": ["cuts", "zoom"] + shown, "blocks": {name: block_pin(catalogue, catalogue["blocks"][name], rt) for name, rt in sorted(runtimes.items())},
            "blocks_sha256": catalogue["sha256"], "captions_drawn": sum(1 for p in plan if p["zone"] == "caption"),
            "beats_drawn": sum(1 for p in plan if p["zone"] == "card"), "runtimes": dict(sorted(runtimes.items())),
            "fonts_used": {role: file for role, (_, _, file) in sorted(fonts.items())}}
