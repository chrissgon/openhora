"""The base page of the HyperFrames engine: the cuts and the zoom, nothing else. `write_page` writes it and keeps its bytes; the
functions it is made of (`build_parts`, `render_page`, `write_files`) are what `_hf_compose.py` reuses to add the layers above the video.

The common image writes this page (the drawing image holds no Python of the edit list), from the same checked edit list the ffmpeg
engine cuts. It is one `index.html` and one `vars.json` in an empty folder: one `<video>` per kept range, all of the same proxy
(`media/proxy.mp4`, which keeps the recording's timeline, so a time of the edit list is the same time in the proxy), a GSAP timeline
that zooms the ranges about the face as the ffmpeg engine does, and a volume lane at each cut that fades as the ffmpeg engine fades.
The page holds numbers only: no font family, no text node, no word of the edit list, so no word of a transcript can reach the
drawing image. The same edit list writes the same bytes. Standard library only; imports only common modules.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import _media
from _text import Refusal
from _vocab import load_data

COLOR = re.compile(r"#[0-9a-fA-F]{6}")
PROXY_SRC = "media/proxy.mp4"
LAYERS = ["cuts", "zoom"]

PAGE = """<!doctype html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=%(w)d, height=%(h)d">
<script src="gsap.min.js"></script>
<style>
html, body { margin: 0; background: %(bg)s; }
#root { position: relative; width: 100%%; height: 100%%; overflow: hidden; background: %(bg)s; }
.zw { position: absolute; inset: 0; overflow: hidden; z-index: 0; transform-origin: %(origin)s; }
.zw video { position: absolute; inset: 0; width: 100%%; height: 100%%; object-fit: cover; }
%(css)s</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="%(w)d" data-height="%(h)d" data-duration="%(dur)s" data-fps="%(fps)d">
%(clips)s%(layers)s
</div>
<script>
window.__timelines = window.__timelines || {};
var V = Object.assign(%(defaults)s,
  (window.__hyperframes && window.__hyperframes.getVariables ? window.__hyperframes.getVariables() : window.__hfVariables) || {});
var main = gsap.timeline({ paused: true });
main.set({}, {}, V.duration);
(V.zooms || []).forEach(function (zm) {
  main.fromTo("#zw" + zm[0], { scale: zm[3] }, { scale: zm[4], duration: zm[2], ease: "none" }, zm[1]);
});
%(tail)swindow.__timelines["main"] = main;
</script>
</body>
</html>
"""


def num(x: float) -> str:
    """A float as the shortest text that reads back exactly (the source frame times are k/fps)."""
    return repr(float(x))


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def check_target(out_dir: str, background: str) -> None:
    """The background is `#rrggbb` and the folder exists and is empty, else a refusal."""
    if not isinstance(background, str) or not COLOR.fullmatch(background):
        raise Refusal("bad_color", "background")
    if not os.path.isdir(out_dir) or os.listdir(out_dir):
        raise Refusal("page_dir_not_empty", "out")


FX_CSS = "#fx { position: absolute; inset: 0; z-index: 0; opacity: 0; pointer-events: none; background-color: #000000; }\n"
FX_LAYER = '\n<div id="fx"></div>'
# The punches and the grades of V9a-3, drawn from the frame index (`n = Math.round(t * fps)`) of rows the edit list's timeline made (`_edl.range_effects`):
# the same rows `_media.base_graph` draws and the face check's reference holds. A punched range has no GSAP zoom tween: one drive tween over the range
# sets its scale from the same piecewise rule as the zoom filter (the range's own level, a constant level on each punch). The grades are one `#fx` layer
# above the video wrappers and below every overlay (flash, dip, tint: its colour and opacity per frame) and, for mono, `filter: grayscale(1)` on the
# range's wrapper on its frames (the CSS matrix the ffmpeg engine's `colorchannelmixer` copies). Every style is set from the frame index: no clock.
FX_JS = """var PZ = V.punched || [];
PZ.forEach(function (pz) {
  var el = document.getElementById("zw" + pz[0]);
  var PD = {at: function (v) {
    if (v === undefined) return this._t || 0;
    this._t = v;
    var n = Math.min(pz[5] - 1, Math.round(v * V.fps));
    var z = pz[3] + (pz[4] - pz[3]) * n / Math.max(1, pz[5] - 1);
    pz[6].forEach(function (r) { if (n >= r[0] && n < r[1]) z = r[2]; });
    el.style.transform = "scale(" + z.toFixed(5) + ")";
  }};
  main.fromTo(PD, {at: 0}, {at: pz[2], duration: pz[2], ease: "none", immediateRender: true}, pz[1]);
});
var GR = V.grades || [];
if (GR.length) {
  var fxEl = document.getElementById("fx");
  var GD = {at: function (v) {
    if (v === undefined) return this._t || 0;
    this._t = v;
    var n = Math.round(v * V.fps), op = 0, col = "#000000", mono = {};
    GR.forEach(function (g) {
      if (n < g[1] || n >= g[2]) return;
      if (g[0] === "mono") { mono[g[5]] = true; return; }
      col = g[0] === "flash" ? "#ffffff" : (g[0] === "dip" ? "#000000" : g[4]);
      op = g[0] === "tint" ? g[6] : g[3][n - g[1]];
    });
    fxEl.style.backgroundColor = col;
    fxEl.style.opacity = String(op);
    GR.forEach(function (g) { if (g[0] === "mono") document.getElementById("zw" + g[5]).style.filter = mono[g[5]] ? "grayscale(1)" : "none"; });
  }};
  main.fromTo(GD, {at: 0}, {at: V.duration, duration: V.duration, ease: "none", immediateRender: true}, 0);
}
"""


def build_parts(edl: dict, *, fps: int, effects=None) -> dict:
    """What the cuts and the zoom are made of: the markup of the kept ranges (one zoom wrapper and one `<video>` each), the zooms, the
    numbers the page keeps as defaults, and the length. The same edit list gives the same parts. `effects` (the table of `_edl.range_effects`)
    adds the punches and the grades: a punched range leaves `zooms` for `punched`, and `grades` lists every grade; with none, the parts are what they
    always were (no new key, no new text)."""
    data = load_data()
    effects = effects or {}
    anchor = _media.anchor_point(edl["face_box"], edl["zoom"]["anchor_y"])
    has_audio = bool(edl["source"]["has_audio"])
    out_seconds = edl["out_frames"] / float(fps)
    clips, zooms, punched, grades, pos = [], [], [], [], 0
    for k, (a, b) in enumerate(edl["kept"]):
        z0, z1 = _media.zoom_levels(edl["zoom"], k, b - a, fps)
        start, dur = pos / float(fps), (b - a) / float(fps)
        fade = min(data["zoom"]["audio_fade_seconds"], dur / 2)
        lanes = {"version": 1, "lanes": [{"target": "volume", "points": [
            {"t": 0, "v": 0}, {"t": round(fade, 4), "v": 1}, {"t": round(dur - fade, 4), "v": 1}, {"t": round(dur, 4), "v": 0}]}]}
        clips.append('<div class="zw" id="zw%d"><video id="v%d" src="%s" playsinline data-has-audio="%s" data-start="%s" data-duration="%s" '
                     'data-media-start="%s" data-track-index="%d" data-automation=\'%s\'></video></div>'
                     % (k, k, PROXY_SRC, "true" if has_audio else "false", num(start), num(dur), num(a / float(fps)), k, dumps(lanes)))
        fx = effects.get(k) or {}
        if fx.get("punches"):
            punched.append([k, start, dur, z0, z1, b - a, [list(row) for row in fx["punches"]]])
        elif abs(z0 - 1.0) > 1e-9 or abs(z1 - 1.0) > 1e-9:
            zooms.append([k, start, dur, z0, z1])
        for g in fx.get("grades") or []:
            grades.append([g["kind"], pos + g["a"], pos + g["b"], g["alphas"], g["color"], k, g["alpha"]])
        pos += b - a
    parts = {"clips": clips, "zooms": zooms, "anchor": anchor, "out_seconds": out_seconds, "vars": {"duration": out_seconds, "fps": fps, "zooms": zooms}}
    if punched or grades:
        parts["fx_tail"] = FX_JS
        if punched:
            parts["vars"]["punched"] = punched
        if grades:
            parts["vars"]["grades"] = grades
            parts["fx_css"], parts["fx_layer"] = FX_CSS, FX_LAYER
    return parts


def render_page(parts: dict, *, width: int, height: int, fps: int, background: str, css: str = "", layers: str = "", tail: str = "") -> str:
    """The page's text. `css` goes at the end of the page's style, `layers` after the kept ranges inside the root composition, `tail` in the
    script after the zooms and before the timeline is registered; all three empty is the base page, byte for byte."""
    return PAGE % {"w": width, "h": height, "dur": num(parts["out_seconds"]), "fps": fps, "bg": background, "clips": "\n".join(parts["clips"]),
                   "origin": "%.2fpx %.2fpx" % parts["anchor"], "defaults": dumps(parts["vars"]), "css": parts.get("fx_css", "") + css,
                   "layers": parts.get("fx_layer", "") + layers, "tail": parts.get("fx_tail", "") + tail}


def write_files(out_dir: str, files: dict) -> None:
    """Write {name: bytes} into `out_dir`, each file new (O_EXCL, no link followed) and mode 0600. A name with a folder in it (`blocks/x.html`)
    makes the folder, mode 0700, once."""
    for name in files:
        folder = os.path.dirname(os.path.join(out_dir, name))
        if not os.path.isdir(folder):
            os.mkdir(folder, 0o700)
    for name, raw in files.items():
        fd = os.open(os.path.join(out_dir, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)


def write_page(edl: dict, out_dir: str, *, width: int, height: int, fps: int, background: str) -> dict:
    """Write `index.html` and `vars.json` into `out_dir`, an existing empty folder (`page_dir_not_empty` otherwise), for the edit list's
    kept ranges. Returns {page_sha256, vars_sha256, clips, zooms, duration, fps, layers}. `background` is `#rrggbb`."""
    check_target(out_dir, background)
    parts = build_parts(edl, fps=fps)
    page = render_page(parts, width=width, height=height, fps=fps, background=background)
    files = {"index.html": page.encode("utf-8"), "vars.json": (dumps(parts["vars"]) + "\n").encode("utf-8")}
    write_files(out_dir, files)
    return {"page_sha256": hashlib.sha256(files["index.html"]).hexdigest(), "vars_sha256": hashlib.sha256(files["vars.json"]).hexdigest(),
            "clips": len(parts["clips"]), "zooms": len(parts["zooms"]), "duration": round(parts["out_seconds"], 3), "fps": fps, "layers": list(LAYERS)}
