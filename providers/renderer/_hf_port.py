"""The page of one of our own ports under the second contract (PF-a4): a tier-B `gsap.html` fragment drawn by the ffmpeg engine's host.

This module is the successor of the retired `_hf_compose`'s `gsap` path (plan PF-a: "`_hf_compose`'s successor inlines the fragment and gives it `build(root, tl, data,
ctx)`"). The old engine inlines every fragment into one composed page; here each caption chunk and each beat gets its own `/h/` page, built with the same
head as a registry component's (`_hf_host.build_page`: the three early shims, the vendored GSAP, the runtime, the theme's faces) and held to the same
guards: the page policy, the exact alpha gates on every frame, the font check, the hash pin and a recorded determinism test. What it keeps from the first
contract and an admitted registry block does not have: the fragment lint (`_gsap_lint.check`: no clocks, timers, random, network, `window` or `document`)
and the band clip (`contain: paint; overflow: clip` at the entry's band, as the retired `_hf_compose` puts on the instance element).

The fragment is mounted through a local `<template>`: the host root names the composition, the runtime mounts the template, runs the fragment's own `build`
script into a paused GSAP timeline registered as `window.__timelines["oh-port"]`, and is sought as for any admitted block. The payload and the context are
what the old engine hands the same `build` (`_payload.caption_data` and `_payload.beat_data`; ctx `{fps, duration, band: {top, height}}`).

A change to the shape of the page changes `PORT_HOST_VERSION`, which is part of the served digest: every recorded determinism test of a port then expires.
Standard library and the renderer's own modules only.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re

import _assets
import _blocks
import _gsap_lint
import _hf_host
import _hf_lint
import _layout
import _payload
from _text import Refusal, is_clean

COLOR = re.compile(r"#[0-9a-fA-F]{6}")
PORT_HOST_VERSION = "3"
COMPOSITION = "oh-port"
INSTANCE = "oh-inst"
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}")
ROLE = re.compile(r"[a-z][a-z0-9_]{0,31}")


def num(x: float) -> str:
    """A float as the shortest text that reads back exactly (the source frame times are k/fps)."""
    return repr(float(x))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_fragment(catalogue: dict, block: dict) -> dict:
    """The port's `gsap.html` from the staged blocks folder, read again and checked against its pin (`block_hash` on any difference, as
    the retired `_hf_compose.read_block_file` does), then both lints: `_hf_lint.check` (the second contract's escape lint) and `_gsap_lint.check` (the first contract's
    fragment lint). Returns {raw (bytes), parts ({markup, style, script})}."""
    ns, short = block["name"].split(":")
    rel = "%s/%s/%s" % (ns, short, block["implementations"]["gsap"])
    pinned = catalogue["files"].get(rel)
    if pinned is None:
        raise Refusal("template_not_pinned", _blocks.field_of(rel))
    raw = _assets.read_regular(os.path.join(catalogue["dir"], rel), _blocks.MAX_FILE, "template_unreadable", _blocks.field_of(rel))
    if _sha256(raw) != pinned:
        raise Refusal("block_hash", _blocks.field_of(rel))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal("template_unreadable", _blocks.field_of(rel)) from None
    _hf_lint.check({"gsap.html": raw})
    _gsap_lint.check(text, block["name"])
    return {"raw": raw, "parts": _gsap_lint.parse(text, block["name"])}


def served_digest(raw: bytes) -> str:
    """The digest a port's determinism record pins: the fragment's bytes and the version of the page shape this module builds."""
    return _hf_host.served_digest({"gsap.html": raw, "port-host": PORT_HOST_VERSION.encode("ascii")})


def theme_css(edl: dict, stacks: dict) -> str:
    """The `:root` block of the theme, with the names the old engine sets (the retired `_hf_compose.theme_pairs`): `--c-<token>` for each colour (`bad_color` when a
    value is not `#rrggbb`), `--weight-<role>` and `--font-<role>` (the host's declared family with the system fallback, or the fallback alone for a
    role on the system default: `stacks` is `_hf_host.prepare`'s font stacks)."""
    pairs = []
    for token, value in sorted(edl["theme"]["colors"].items()):
        if not isinstance(token, str) or not TOKEN.fullmatch(token) or not isinstance(value, str) or not COLOR.fullmatch(value):
            raise Refusal("bad_color", ("edl.theme.colors.%s" % token)[:80])
        pairs.append(("--c-%s" % token, value))
    for role, spec in sorted(edl["theme"]["fonts"].items()):
        if not ROLE.fullmatch(role) or role not in stacks:
            raise Refusal("font_not_on_engine", ("edl.theme.fonts.%s" % role)[:80])
        pairs.append(("--weight-%s" % role, str(int(spec["weight"]))))
        pairs.append(("--font-%s" % role, stacks[role]))
    return ":root{%s}" % ";".join("%s:%s" % pair for pair in pairs)


def ctx_for(data: dict, entry: dict, zone: str, fps: int) -> dict:
    """The context the port's `build` is given: {fps, duration (the entry's own, in seconds), band {top, height}}. The band is the entry's own (a caption
    chunk can carry a pip or a split band), `band_too_small` when it has no height."""
    top, bottom = _layout.entry_zones(data, entry)[zone]
    if bottom - top <= 0:
        raise Refusal("band_too_small", "band")
    return {"fps": fps, "duration": (entry["end_frame"] - entry["start_frame"]) / float(fps), "band": {"top": top, "height": bottom - top}}


def payload_for(track: str, data: dict, edl: dict, entry: dict, by_index: dict, fps: int) -> dict:
    """The payload of one entry, exactly what the old engine hands the same `build`. The texts are checked as it checks them: every caption word of the chunk
    and every string parameter must be clean (`text_not_clean`)."""
    if track == "caption":
        for i in range(entry["word_from"], entry["word_to"] + 1):
            if i in by_index and not is_clean(by_index[i]["text"]):
                raise Refusal("text_not_clean", "edl.words")
        return _payload.caption_data(data, edl, entry, by_index, fps)
    for name, value in entry["params"].items():
        if isinstance(value, str) and not is_clean(value):
            raise Refusal("text_not_clean", ("beats.%s.params.%s" % (entry.get("id", "?"), name))[:80])
    return _payload.beat_data(data, entry, fps, edl)


def _json(obj) -> str:
    """JSON for a script: ASCII only, sorted keys, and `<`, `>` and `&` written as escapes, so that no text can close the script or open a comment."""
    text = json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _px(value) -> str:
    return str(int(value)) if value == int(value) else repr(float(value))


def build_port_page(*, block: dict, parts: dict, runtime: dict, faces: list, css: str, payload: dict, ctx: dict, zone: str, prefix: str, index: int,
                    duration: float, fps: int, width: int, height: int) -> bytes:
    """The page of one entry at `/h/<prefix><index>/index.html` (`prefix` c for a caption chunk, b for a beat). The head is `_hf_host.build_page`'s. The
    theme, `.hf-inst` and the fragment's CSS inside `@scope (#oh-inst)` are in the page's own `<style>` (as the retired `_hf_compose` puts them), never inside the
    template: the runtime rewrites every selector of a style it finds in a mounted composition under `[data-composition-id="oh-port"]`, which cannot match
    inside `@scope (#oh-inst)` (the composition root is outside the scope root), and `:root` becomes the composition root (PF-a4d). The component is one
    `<template>` holding the port's markup in an instance element clipped to the band, and the port's own build script followed by the call that runs it
    into a paused timeline; the host root names it and the runtime mounts it from the local template. The composition root
    sets the theme's text font: the page's font check walks every element that holds text, the fragment's own `<style>` and `<script>` included, and they
    inherit from it (a family the browser would resolve to its own default is `font_not_allowed`)."""
    top, band_h = ctx["band"]["top"], ctx["band"]["height"]
    d = num(duration)
    font_css = "".join("@font-face{font-family:%s;src:url(%s) format('%s');font-weight:%s;font-style:normal}" % (f["family"], f["path"], f["format"], f["weight"])
                       for f in faces)
    inst = ('<div id="%s" class="hf-inst" data-hf-zone="%s" data-hf-block="%s" style="position:absolute; left:0; top:%spx; width:%dpx; height:%spx; '
            'contain:paint; overflow:clip">\n%s\n</div>' % (INSTANCE, zone, html.escape(block["name"], quote=True), _px(top), width, _px(band_h), parts["markup"]))
    script = ("%s\nvar OH_DATA = %s;\nvar OH_CTX = %s;\n"
              "(function () { var tl = gsap.timeline({paused: true}); build(document.getElementById(\"%s\"), tl, OH_DATA, OH_CTX); tl.set({}, {}, %s); "
              "window.__timelines = window.__timelines || {}; window.__timelines[\"%s\"] = tl; })();"
              % (parts["script"], _json(payload), _json(ctx), INSTANCE, d, COMPOSITION))
    component = ('<div data-composition-id="%s" data-duration="%s" data-fps="%d" style="position:absolute;inset:0;font-family:var(--font-text)">\n%s\n<script>%s</script>\n</div>'
                 % (COMPOSITION, d, fps, inst, script))
    port_css = "%s\n.hf-inst{position:absolute;display:block}\n@scope (#%s) {\n%s\n}\n" % (css, INSTANCE, parts["style"])
    page = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n%s\n"
        "<script src=\"/h/vendor/gsap.min.js\"></script>\n%s\n"
        "<style>%s%shtml,body{margin:0;padding:0;background:transparent}body{position:relative;width:%dpx;height:%dpx;overflow:hidden}</style>\n</head>\n<body>\n"
        "<template id=\"%s-template\">%s</template>\n"
        "<div id=\"oh-host\" data-composition-id=\"%s\" data-composition-src=\"/h/%s%d/%s.html\" data-start=\"0\" data-duration=\"%s\" "
        "style=\"position:absolute;left:0;top:0;width:%dpx;height:%dpx\"></div>\n"
        "<script>window.__timelines = window.__timelines || {}; window.__timelines[\"oh-host\"] = gsap.timeline({paused: true});</script>\n%s\n</body>\n</html>\n"
    ) % (_hf_host._tags(runtime["shims"][:3], "early"), _hf_host._tags([runtime["runtime"]], "runtime"), font_css, port_css, width, height, COMPOSITION, component,
         COMPOSITION, prefix, index, COMPOSITION, d, width, height, _hf_host._tags(runtime["shims"][3:], "late"))
    return page.encode("utf-8")


def page_for(*, block: dict, fragment: dict, runtime: dict, faces: list, stacks: dict, data: dict, edl: dict, entry: dict, track: str,
             index: int, by_index: dict) -> bytes:
    """The page of one caption chunk (`track` "caption") or one beat (`track` "beat") of a port: the payload and the ctx of the old engine, the theme, the
    entry's own band and duration. `_hf_host.prepare` calls it once per entry."""
    zone = "caption" if track == "caption" else "card"
    fps = edl["fps"]
    payload = payload_for(track, data, edl, entry, by_index, fps)
    ctx = ctx_for(data, entry, zone, fps)
    frame = data["frame"]
    return build_port_page(block=block, parts=fragment["parts"], runtime=runtime, faces=faces, css=theme_css(edl, stacks), payload=payload, ctx=ctx, zone=zone,
                           prefix="c" if track == "caption" else "b", index=index, duration=ctx["duration"], fps=fps, width=frame["width"], height=frame["height"])
