"""The kit of the second page contract's tests (PF-a2): a fictional HF-shaped component (`oh-test-pop`, written from the shape of a registry
`<template>` component with nothing copied from one), its planted variants, a small stand-in for the runtime and its shims (so that the offline tests
run the whole render with the host's Chromium and ffmpeg and no vendored file), the blocks folder with a test allowlist entry, and the helpers that
write the entry's hashes and its recorded determinism test.

The live legs (`test_engine_contract_live.py`) use the same component and variants against the image's real runtime: `component()` is the same text, and
only the vendor, shim and registry folders differ. Not a test file. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import renderer_kit as K
import _blocks
import _hf_host

NAME = "hf:oh-test-pop"
SHORT = "oh-test-pop"
COMPONENT_DIR = "registry/components/oh-test-pop"
FILE = "oh-test-pop.html"
COMMIT = "b" * 40
FPS = 30
FACE = (240, 300, 600, 480)                     # the kit's face box (renderer_kit.PIP_FACE_BOX): the card zone is above y = 282, the caption band below y = 798
FACE_CENTRE = (540, 540)
LINE_Y = 798                                    # face.y + face.h + the 18 px gap: where the caption band begins
POST = """# Post: a fictional pop (a test fixture)

- Owner: mkt-social-copy
- Status: draft
- Network: instagram
- Format: reel

```script
beat: 1
line: Hey, quick story about money.
on-screen: Money story
preset: keyword

beat: 2
line: Last year I tracked every expense for ninety days.
```

```post
A pop. What would you track first?
```
"""

CDN = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'

TEMPLATE = """<!doctype html>
<html lang="en" data-composition-variables='[{ "id": "text", "type": "string", "role": "content", "label": "Label", "default": "New" }]'>
  <head><meta charset="UTF-8" /><title>Test Pop</title></head>
  <body>
    <template>
      <div id="root" data-composition-id="oh-test-pop" data-duration="2" data-fps="30">
        <style>
          #root { position: absolute; inset: 0; overflow: hidden; color: var(--fg, #ffffff); font-family: var(--font-body, Inter, system-ui, sans-serif); pointer-events: none; }
          .badge { position: absolute; left: 50%%; top: 50%%; transform: translate(-50%%, -50%%); padding: 10px 22px; border-radius: 12px; background: var(--brand, #cc99aa); font-size: 48px; opacity: 0; %(badge_css)s }
          .mark { position: fixed; opacity: 0; %(mark_css)s }
        </style>
        <div class="badge" id="badge"></div>
        <div class="mark" id="mark"></div>
        %(cdn)s
        <script>
          (function () {
            var vars = window.__hyperframes.getVariables();
            var badge = document.getElementById("badge");
            var mark = document.getElementById("mark");
            badge.textContent = vars.text == null ? "New" : String(vars.text);
            var tl = gsap.timeline({ paused: true });
            tl.fromTo(badge, { opacity: 0 }, { opacity: %(badge_opacity)s, duration: 0.4 }, 0);
            %(script)s
            tl.seek(0);
            window.__timelines = window.__timelines || {};
            window.__timelines["oh-test-pop"] = tl;
          })();
        </script>
      </div>
    </template>
  </body>
</html>
"""

# each variant: what it adds to the clean component. `k` is the first frame of the entry's range the planted pixels appear on.
VARIANTS = {
    "clean": {},
    # the clean control as an admission measures it: the badge is its own compositor layer for the whole page (as a real component's `will-change` makes it), so that what
    # is drawn does not depend on the frames drawn before it. Without it (`clean`) Chrome rasterises the frames after a fade differently from the same frames sought first.
    "stable": {"badge_css": "will-change: opacity;"},
    # a 1-pixel mark with alpha 1/255 at the face box's centre on frames 5, 6 and 7 of the entry: the exact face gate refuses it, frame k = 5
    "face_dot": {"mark_css": "left: 540px; top: 540px; width: 1px; height: 1px; background: rgba(255,255,255,0.004);",
                 "script": 'tl.set(mark, { opacity: 1 }, 5 / 30); tl.set(mark, { opacity: 0 }, 8 / 30);'},
    # the same two planted pixels at the DEFAULT face box (240,620,600,560 at 1080x1920: the box an admission measures at) and below its caption line (1198)
    "face_dot_default": {"mark_css": "left: 540px; top: 900px; width: 1px; height: 1px; background: rgba(255,255,255,0.004);",
                         "script": 'tl.set(mark, { opacity: 1 }, 5 / 30); tl.set(mark, { opacity: 0 }, 8 / 30);'},
    "below_default_line": {"mark_css": "left: 300px; top: 1250px; width: 60px; height: 60px; background: #ffffff;", "script": 'tl.set(mark, { opacity: 1 }, 4 / 30);'},
    # a box that starts below the line the captions begin at
    "below_line": {"mark_css": "left: 300px; top: 830px; width: 60px; height: 60px; background: #ffffff;",
                   "script": 'tl.set(mark, { opacity: 1 }, 4 / 30);'},
    # the page draws nothing at all
    "nothing": {"badge_opacity": "0"},
    # a request whose name is built at run time: the text lint does not see it, the page policy does
    "computed_fetch": {"script": 'window["fe" + "tch"]("/x");'},
    # a face the page adds itself (the lint refuses the name)
    "fontface": {"script": 'new FontFace("pv-x", "url(/fonts/display.ttf)");'},
    # a family the page asks for that is not one the host declared
    "system_font": {"badge_css": "font-family: Georgia, serif !important;"},
    # a full-frame opaque layer: with the 1-pixel corner cut it is RGBA and the face gate refuses it
    "opaque": {"mark_css": "left: 0; top: 0; width: 1080px; height: 1920px; background: #101820;", "script": 'tl.set(mark, { opacity: 1 }, 3 / 30);'},
    # the same, and the page removes the corner cut: Chrome then writes an RGB frame
    "opaque_no_clip": {"mark_css": "left: 0; top: 0; width: 1080px; height: 1920px; background: #101820;",
                       "script": 'tl.set(mark, { opacity: 1 }, 3 / 30); tl.call(function () { document.documentElement.style.clipPath = "none"; }, [], 3 / 30);'},
    # the badge sits where a random number puts it: nothing in the page's own clock or the shims is involved, so the frames differ from run to run
    "math_random": {"script": 'badge.style.left = (30 + Math.random() * 40) + "%";'},
    # a text the lint refuses by its category
    "lint_storage": {"script": 'window.localStorage.setItem("a", "b");'},
}


def component(variant: str = "clean") -> str:
    v = VARIANTS[variant]
    return TEMPLATE % {"badge_css": v.get("badge_css", ""), "mark_css": v.get("mark_css", ""), "badge_opacity": v.get("badge_opacity", "1"),
                       "script": v.get("script", ""), "cdn": CDN}


# ---------------------------------------------------------------- a stand-in for the runtime and its shims

FAKE_GSAP = """(function () {
  function setv(el, v) { if ("opacity" in v) el.style.opacity = String(v.opacity); }
  function make() {
    var tweens = [];
    var tl = {
      fromTo: function (el, from, to, pos) { tweens.push({ el: el, from: from, to: to, pos: pos || 0, dur: to.duration || 0 }); return tl; },
      set: function (el, vals, pos) { tweens.push({ el: el, to: vals, pos: pos || 0, dur: 0, set: true }); return tl; },
      call: function (fn, args, pos) { tweens.push({ fn: fn, pos: pos || 0, call: true, done: false }); return tl; },
      seek: function (t) { return tl.time(t); },
      time: function (t) {
        tweens.slice().sort(function (a, b) { return a.pos - b.pos; }).forEach(function (x) {
          if (x.call) { if (t >= x.pos) x.fn(); return; }
          if (x.set) { if (t >= x.pos) setv(x.el, x.to); return; }
          var p = x.dur > 0 ? Math.min(1, Math.max(0, (t - x.pos) / x.dur)) : (t >= x.pos ? 1 : 0);
          p = Math.round(p * 1e6) / 1e6;      // a tween that has reached its end is exactly at it, whatever float the frame's time came as
          var v = {};
          for (var k in x.to) { if (k === "duration" || k === "ease") continue; v[k] = x.from[k] + (x.to[k] - x.from[k]) * p; }
          setv(x.el, t >= x.pos ? v : x.from);
        });
        return tl;
      }
    };
    return tl;
  }
  window.gsap = { timeline: make, set: function (el, v) { setv(el, v); } };
})();
"""

FAKE_RUNTIME = """(function () {
  window.__player = { renderSeek: function (t) { var tl = window.__timelines && window.__timelines["oh-test-pop"]; if (tl) tl.time(t); }, getDuration: function () { return 2; } };
  window.__hyperframes = { getVariables: function () { var h = document.getElementById("oh-host"); try { return JSON.parse(h.getAttribute("data-variable-values")); } catch (e) { return {}; } } };
  function mount() {
    var host = document.getElementById("oh-host");
    var tpl = document.querySelector("template#" + host.getAttribute("data-composition-id") + "-template");
    host.appendChild(tpl.content.cloneNode(true));
    var scripts = Array.prototype.slice.call(host.querySelectorAll("script"));
    function next() {
      var s = scripts.shift();
      if (!s) { window.__renderReady = true; return; }
      var n = document.createElement("script");
      var src = s.getAttribute("src");
      if (src) { n.src = src; n.onload = next; n.onerror = next; } else { n.textContent = s.textContent; }
      s.parentNode.replaceChild(n, s);
      if (!src) next();
    }
    next();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();
"""

FAKE_SHIMS = {
    "early_stub.js": "window.__early = 1;\n",
    "capture_mode_shim.js": "window.__capture = 1;\n",
    "virtual_time_shim.js": "window.__HF_VIRTUAL_TIME__ = { originalRequestAnimationFrame: window.requestAnimationFrame.bind(window) };\n",
    "render_mode.js": "window.__fps = __OH_FPS__;\n",
    "bridge.js": ("(function () { var hf = {}; Object.defineProperty(hf, 'duration', { get: function () { return window.__renderReady ? window.__player.getDuration() : 0; } });"
                  " hf.seek = function (t) { window.__player.renderSeek(t); }; window.__hf = hf; })();\n"),
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_runtime(tmp) -> dict:
    """{runtime_dir, vendor, registry_root}: a folder of pins and shims (`hf-runtime/`), a vendor folder and an empty registry folder, all checked by the
    same code the image's are, with a stand-in for the runtime and GSAP. The shims are the stand-in's own five."""
    tmp = Path(tmp)
    base = tmp / "hf-runtime"
    (base / "shims").mkdir(parents=True)
    vendor = tmp / "vendor"
    vendor.mkdir()
    files = {"gsap.min.js": FAKE_GSAP.encode(), "hyperframe.runtime.iife.js": FAKE_RUNTIME.encode(), "hyperframe.manifest.json": b'{"fake": true}\n'}
    for name, raw in files.items():
        (vendor / name).write_bytes(raw)
    (base / "npm-pins.json").write_text(json.dumps({"schema_version": 1, "packages": [
        {"name": "gsap", "version": "0", "url": "u", "integrity": "i", "files": {"package/dist/gsap.min.js": _sha(files["gsap.min.js"])}},
        {"name": "hyperframes", "version": "0", "url": "u", "integrity": "i", "files": {"package/dist/hyperframe.runtime.iife.js": _sha(files["hyperframe.runtime.iife.js"]),
                                                                                       "package/dist/hyperframe.manifest.json": _sha(files["hyperframe.manifest.json"])}}]}))
    rows = []
    for name, text in FAKE_SHIMS.items():
        (base / "shims" / name).write_text(text)
        rows.append("%s  %s" % (_sha(text.encode()), name))
    (base / "shims" / "SHA256SUMS").write_text("\n".join(rows) + "\n")
    registry = tmp / "registry"
    registry.mkdir()
    return {"runtime_dir": str(base), "vendor": str(vendor), "registry": str(registry)}


# ---------------------------------------------------------------- the entry

THEME_VARS = {"--fg": "text", "--font-body": "font:text"}


def write_component(registry, html: str) -> dict:
    """The component's file in the registry folder; {name: sha256}."""
    folder = Path(registry) / COMPONENT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_text(html, encoding="utf-8")
    return {FILE: _sha(html.encode())}


def entry(files: dict, served: str, runtime_sha256: str, **over) -> dict:
    """The allowlist entry of the fictional component, with a recorded determinism test at the given hashes."""
    e = {"name": NAME, "kind": "overlay", "preset": "keyword", "band": "card", "may_cross_face": False, "license": ["Apache-2.0"], "source": "hyperframes-registry",
         "use_when": "a fictional pop for one short phrase, used by the tests only",
         "params": {"text": {"type": "text", "max": 24, "required": True}, "color": {"type": "color"}},
         "samples": [{"text": "Name every dollar"}], "natural_duration": 2.0, "implementations": {"hf": FILE},
         "tier": "A", "commit": COMMIT, "notice": "Apache-2.0; a fictional component written for the tests", "files": dict(files),
         "component": COMPONENT_DIR, "edits": ["E1", "E2:Inter"], "font_map": {"Inter": "oh-text"}, "served_sha256": served,
         "bind": {"text": "var:text", "color": "css:--brand"}, "fixed": {}, "theme_vars": dict(THEME_VARS),
         "determinism": {"served_sha256": served, "runtime_sha256": runtime_sha256, "samples": 3, "frames": 180, "runs": 4, "blocked": 0,
                         "date": "2026-11-24", "image": "openhora-renderer:test", "seconds": 1.5}}
    e.update(over)
    return e


def served_of(files_text: dict) -> str:
    """The served digest the entry pins: the edits applied to the file texts."""
    edited = _hf_host.apply_edits({n: t.encode() for n, t in files_text.items()}, ["E1", "E2:Inter"], {"Inter": "oh-text"})
    return _hf_host.served_digest(edited)


def blocks_folder(tmp, hf_entry, name="blocks") -> str:
    """A copy of the committed blocks with `hf_entry` as the one allowlist entry, the ffmpeg engine drawing the keyword preset with it, pinned again."""
    folder = Path(tmp) / name
    shutil.copytree(K.BLOCKS, folder)
    allow = json.loads((folder / "hf" / "allowlist.json").read_text())
    allow.update(registry_commit=COMMIT, blocks=[hf_entry])
    (folder / "hf" / "allowlist.json").write_text(json.dumps(allow, indent=1))
    eng = json.loads((folder / "engines" / "ffmpeg.json").read_text())
    eng["presets"]["keyword"] = hf_entry["name"]
    (folder / "engines" / "ffmpeg.json").write_text(json.dumps(eng, indent=1))
    _blocks.write_pins(str(folder))
    return str(folder)
