"""Adapter (S2): our renderer-neutral edit list and beats -> a HyperFrames project (a folder with index.html and vars.json).

Runs inside the spike image (Python 3 standard library). It reuses our own planning code, read-only, from a mounted copy of
providers/renderer: the document checks (`_edl.check_edl`, `check_beats`) and the timeline (`_edl.resolve_timeline`: caption windows,
beat windows, the face box each one must avoid, the zoom of each kept range). Only the drawing is HyperFrames'.

  python3 hf_adapter.py --renderer-src /renderer --edl edl.json --beats beats.json --vocabulary video-presets.json \
      --platform-file instagram.json --registry /opt/hf-registry --gsap /opt/hf/node_modules/gsap/dist/gsap.min.js \
      --out /work/project --caption highlight|pill|slam

What goes where (the rule of S2, spec step 4):
  * `vars.json` is the file `hyperframes render --variables-file` reads. It carries every piece of TEXT: the words, the caption chunks, the
    text of the cards, the colours. The page reads it with `window.__hyperframes.getVariables()` and puts text on screen with `textContent`.
  * `index.html` carries the structure and numbers only: one <video> per kept range (its start, duration and media offset are numbers formatted
    here), the registry blocks (their own code, patched to read the variables), the vendored GSAP and our three fonts. No word of the
    transcript is in it, and no word is ever concatenated into markup or script.
It also writes <out>/gsap.min.js, <out>/fonts/*.woff2, <out>/adapter-report.json. The recording is media/source.mov inside the project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ports  # noqa: E402

REGISTRY = "registry/components"
DEFAULT_FONT = {"display": "inter-800", "text": "inter-500", "mono": "jetbrains-mono-500"}


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def num(x: float) -> str:
    """A float as the shortest text that reads back exactly (the source frame times are k/30)."""
    return repr(float(x))


def hex_color(theme: dict, token: str) -> str:
    return theme["colors"].get(token, theme["colors"]["accent"]) if not token.startswith("#") else token


def card_numbers(raw: str) -> float:
    """'1.250' -> 1250 and '3,5' -> 3.5: the figure a card counts up to, read from the value text of the beat."""
    digits = raw.replace(".", "").replace(",", ".") if "," in raw else raw.replace(".", "") if raw.count(".") > 1 else raw
    return float(digits)


def build(args) -> dict:
    sys.path.insert(0, args.renderer_src)
    import _edl
    import _frames
    import _media
    import _vocab
    from _text import Refusal

    ports.PATCH_LOG.clear()
    ports.PATCHES_BY_BLOCK.clear()
    data = _vocab.load_data()
    vocab = _vocab.load_vocabulary(args.vocabulary)
    edl = _vocab.read_json(args.edl, data["limits"]["json_max_bytes"])
    beats = _vocab.read_json(args.beats, data["limits"]["json_max_bytes"])
    platform = _vocab.read_json(args.platform_file)
    allow = _frames.font_allowlist()
    try:
        _edl.check_edl(edl, data, vocab, allow, platform)
        _edl.check_beats(beats, edl, vocab)
    except Refusal as err:
        raise SystemExit("refused by our own checks: %s %s" % (err.code, err.field))
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)

    fps, size = edl["fps"], edl["size"]
    out_seconds = edl["out_frames"] / fps
    theme = edl["theme"]
    colors = dict(theme["colors"])
    z = data["zones"]
    report: dict = {"fps": fps, "out_frames": edl["out_frames"], "caption": args.caption, "skipped": []}

    out = args.out
    for sub_dir in ("fonts", "media"):
        os.makedirs(os.path.join(out, sub_dir), exist_ok=True)
    shutil.copyfile(args.gsap, os.path.join(out, "gsap.min.js"))
    font_faces, fonts_used = [], []
    for role, f in theme["fonts"].items():
        row = allow.get(DEFAULT_FONT[role] if f["id"] == "default" else f["id"])      # "default" means the system font: here, the allow-list's own default of the role
        if row is None or row["file"] in fonts_used:
            continue
        src = os.path.join(_frames.fonts_dir(), row["file"])
        raw = open(src, "rb").read()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise SystemExit("font %s differs from the allow-list" % f["id"])
        shutil.copyfile(src, os.path.join(out, "fonts", row["file"]))
        fonts_used.append(row["file"])
        font_faces.append('@font-face { font-family: "%s"; font-weight: %d; src: url("fonts/%s") format("woff2"); }' % (row["family"], row["weight"], row["file"]))

    # ---- cuts: one <video> per kept range, the same source, trimmed by data-media-start / data-duration. Numbers only.
    clips, zooms, pos = [], [], 0
    anchor = _media.anchor_point(edl["face_box"], edl["zoom"]["anchor_y"])
    for k, (a, b) in enumerate(edl["kept"]):
        z0, z1 = _media.zoom_levels(edl["zoom"], k, b - a, fps)
        start, dur = pos / fps, (b - a) / fps
        fade = min(data["zoom"]["audio_fade_seconds"], dur / 2)
        auto = {"version": 1, "lanes": [{"target": "volume", "points": [
            {"t": 0, "v": 0}, {"t": round(fade, 4), "v": 1}, {"t": round(dur - fade, 4), "v": 1}, {"t": round(dur, 4), "v": 0}]}]}
        clips.append('<div class="zw" id="zw%d"><video id="v%d" src="media/source.mov" playsinline data-has-audio="true" data-start="%s" '
                     'data-duration="%s" data-media-start="%s" data-track-index="%d" data-automation=\'%s\'></video></div>'
                     % (k, k, num(start), num(dur), num(a / fps), k % 2, json.dumps(auto, separators=(",", ":"))))
        if abs(z0 - 1) > 1e-9 or abs(z1 - 1) > 1e-9:
            zooms.append({"k": k, "start": start, "dur": dur, "z0": z0, "z1": z1})
        pos += b - a

    # ---- captions: the registry block, patched to read the variables; our chunk windows decide where each group sits
    words = edl["words"]
    at = {w["index"]: n for n, w in enumerate(words)}
    chunk_zone = {(c["word_from"], c["word_to"]): c for c in timeline["captions"]}
    chunks_pos, tops, word_tops = [], [], [0] * len(words)
    margin = z["caption_margin"]
    cap_id, cap_port, word_class = ports.CAPTIONS[args.caption]
    box_h = ports.GROUP_BOX[args.caption]
    for a_idx, b_idx in edl["captions"]["chunks"]:
        entry = chunk_zone.get((a_idx, b_idx))
        face = entry["face"] if entry else edl["face_box"]
        band = _edl.zones(data, face)["caption"]
        chunks_pos.append([at[a_idx], at[b_idx]])
        centre = (band[0] + band[1]) // 2
        tops.append(band[0] + margin if args.caption == "highlight" else centre - box_h // 2)
        for n in range(at[a_idx], at[b_idx] + 1):
            word_tops[n] = centre
    cap = cap_port(read_text(os.path.join(args.registry, REGISTRY, cap_id, cap_id + ".html")))
    n_caption_patches = len(ports.PATCH_LOG)

    # ---- cards: one function per kind of card, one call per beat (the function builds the card's markup into a host the page makes)
    card_defs, card_css, card_blocks, beat_vars = [], [], {}, []
    for e in timeline["beats"]:
        band = _edl.zones(data, e["face"])["card"]
        x, w_box = 65, size[0] - 130
        y, h_box = band[0], band[1] - band[0]
        start, dur = e["start_frame"] / fps, (e["end_frame"] - e["start_frame"]) / fps
        p = e["params"]
        if e["preset"] not in ports.CARDS:
            report["skipped"].append({"beat": e["id"], "what": "preset %s: not ported in S2 (only the number, quote and keyword cards are)" % e["preset"]})
            continue
        block, port_fn = ports.CARDS[e["preset"]]
        if block not in card_blocks:
            card_blocks[block] = port_fn(read_text(os.path.join(args.registry, REGISTRY, block, block + ".html")))
        if args.plant_overlap == e["id"]:     # the planted failure of check C6: draw this card on the face
            y, h_box = edl["face_box"]["y"] + 20, min(h_box, 300)
        col = hex_color(theme, p.get("color", "accent"))
        row = {"id": e["id"], "preset": e["preset"], "start": start, "dur": dur, "x": x, "y": y, "w": w_box, "h": h_box, "color": col,
               "word_from": e["word_from"], "word_to": e["word_to"]}
        if e["preset"] == "number":
            row.update({"end": card_numbers(p["value"]), "label": p["label"]})
        elif e["preset"] == "keyword":
            row.update({"text": p["text"], "font": int(min(110, h_box * 0.5, (w_box * 0.82 - 130) / (max(1, len(p["text"])) * 0.56)))})
        else:
            row.update({"quote": p["text"], "author": p.get("author", "")})
        beat_vars.append(row)
    n_card_patches = len(ports.PATCH_LOG) - n_caption_patches

    vars_doc = {
        "words": [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in words], "chunks": chunks_pos, "tops": tops, "word_tops": word_tops,
        "colors": colors, "duration": out_seconds, "fps": fps, "beats": beat_vars, "zooms": zooms,
        "face_box": edl["face_box"],
    }
    write_text(os.path.join(out, "vars.json"), json.dumps(vars_doc, ensure_ascii=False, indent=1) + "\n")

    css = ["/* ---- caption block: %s */" % cap_id, cap["css"]] + ["/* ---- card block: %s */\n%s" % (b, c["css"]) for b, c in card_blocks.items()]
    scripts = []
    for b, c in card_blocks.items():
        scripts.append(c["script"])
    markup_consts = "\n".join("var MARKUP_%s = %s;" % (b.upper().replace("-", "_"), json.dumps(c["markup"].strip())) for b, c in card_blocks.items())
    html = INDEX % {
        "faces": "\n".join(font_faces), "w": size[0], "h": size[1], "dur": num(out_seconds), "fps": fps, "clips": "\n".join(clips),
        "origin": "%.2fpx %.2fpx" % anchor, "bg": colors["bg"], "css": "\n".join(css), "caption_markup": cap["markup"].strip(),
        "caption_script": cap["script"], "card_scripts": "\n".join(scripts), "markup_consts": markup_consts,
        "cards": CARDS_JS, "fonts_js": json.dumps(["800 84px Inter", "500 40px Inter", "500 40px 'JetBrains Mono'"]),
    }
    bad = check_fonts(html)
    if bad:
        raise SystemExit("refused: the page names a font that is not in the allow-list: %s" % ", ".join(bad))
    write_text(os.path.join(out, "index.html"), html)
    report["patches"] = {"caption": n_caption_patches, "cards": n_card_patches, "by_block": dict(ports.PATCHES_BY_BLOCK)}
    report["patch_log"] = ports.PATCH_LOG
    report["zoomed_ranges"] = len(zooms)
    report["kept_ranges"] = len(edl["kept"])
    report["cards"] = [{"id": r["id"], "preset": r["preset"], "start_frame": round(r["start"] * fps), "box": [r["x"], r["y"], r["w"], r["h"]]} for r in beat_vars]
    report["caption_word_class"] = word_class
    write_text(os.path.join(out, "adapter-report.json"), json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return report


ALLOWED_FAMILIES = {"inter", "jetbrains mono"}
GENERIC_FAMILIES = {"sans-serif", "serif", "monospace", "system-ui", "ui-monospace", "inherit", "initial", "unset"}


def check_fonts(html: str) -> list:
    """The code guard of check C5: every font family the page names (in CSS, in @font-face and in the canvas font strings of the blocks' scripts) is
    one of ours or a generic keyword. HyperFrames' compiler adds a bundled font for any other NAMED family it does not find declared (it did for
    "SF Mono", "Menlo" and "Consolas" in the quote card, and it draws Inter from its own catalogue when no @font-face of ours exists), so a page that
    names one is refused here, before any render."""
    problems = []
    for m in re.finditer(r"font-family\s*:\s*([^;}]+)", html):
        for tok in re.findall(r"\"([^\"]+)\"|'([^']+)'|([A-Za-z][A-Za-z0-9 -]*)", re.sub(r"var\(--[a-z-]+\)|var\(--[a-z-]+,|\)", "", m.group(1))):
            name = next(t for t in tok if t).strip().lower()
            if name and name not in ALLOWED_FAMILIES and name not in GENERIC_FAMILIES and not name.startswith("var"):
                problems.append("css family %r" % name)
    for m in re.finditer(r"\b\d+px\s+(?:\\?[\"'])?([A-Za-z][A-Za-z ]*?)(?:\\?[\"'])?[\"';,)]", html):
        name = m.group(1).strip().lower()
        if name and name not in ALLOWED_FAMILIES and name not in GENERIC_FAMILIES:
            problems.append("script font %r" % name)
    return sorted(set(problems))


# The page. Everything between the % markers is code of this adapter or of a registry block; no transcript text is ever interpolated.
CARDS_JS = """
  (function () {
    var tokens = function (host, c) {
      var s = host.style;
      s.setProperty("--bg", "transparent"); s.setProperty("--fg", c.text); s.setProperty("--muted", c.muted); s.setProperty("--surface", c.chip_fill);
      s.setProperty("--border", c.accent); s.setProperty("--brand", c.accent); s.setProperty("--accent", c.accent); s.setProperty("--radius", "30px");
      s.setProperty("--font-display", "'Inter', sans-serif"); s.setProperty("--font-body", "'Inter', sans-serif"); s.setProperty("--font-mono", "'JetBrains Mono', monospace");
    };
    var layer = document.getElementById("cards");
    (V.beats || []).forEach(function (b) {
      var host = document.createElement("div");
      host.className = "card"; host.id = "card-" + b.id;
      host.style.left = b.x + "px"; host.style.top = b.y + "px"; host.style.width = b.w + "px"; host.style.height = b.h + "px";
      tokens(host, V.colors);
      host.style.setProperty("--border", b.color); host.style.setProperty("--brand", b.color);
      layer.appendChild(host);
      var inner = document.createElement("div");
      var child;
      if (b.preset === "number") {
        var hNum = Math.floor(b.h * 0.66);
        inner.className = "cu-root"; inner.style.height = hNum + "px";
        inner.innerHTML = MARKUP_COUNT_UP;
        host.appendChild(inner);
        var label = document.createElement("div");
        label.className = "card-label"; label.style.top = hNum + "px"; label.style.height = (b.h - hNum) + "px";
        label.textContent = b.label;
        host.appendChild(label);
        child = __hfCountUp(inner, { start: 0, end: b.end, prefix: "", suffix: "", accent: "green" }, b.dur);
      } else if (b.preset === "keyword") {
        inner.className = "sp-root"; inner.style.height = b.h + "px";
        inner.innerHTML = MARKUP_SPRING_POP;
        host.style.setProperty("--sp-font", b.font + "px");
        host.appendChild(inner);
        child = __hfSpringPop(inner, { text: b.text, overshoot: 1.7, fromScale: 0.9 }, b.dur);
      } else {
        inner.className = "tc-root"; inner.style.height = b.h + "px";
        inner.innerHTML = MARKUP_TESTIMONIAL_CARD;
        host.appendChild(inner);
        child = __hfTestimonial(inner, { quote: b.quote, author: b.author, handle: "", rating: 0 }, b.dur);
      }
      main.set(host, { visibility: "visible" }, b.start);
      main.add(child, b.start);
      main.set(host, { visibility: "hidden" }, b.start + b.dur);
    });
  })();
"""

INDEX = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=%(w)d, height=%(h)d">
<title>openhora spike S2</title>
<script src="gsap.min.js"></script>
<style>
%(faces)s
html, body { margin: 0; background: %(bg)s; }
#root { position: relative; width: 100%%; height: 100%%; overflow: hidden; background: %(bg)s; }
.zw { position: absolute; inset: 0; overflow: hidden; z-index: 0; transform-origin: %(origin)s; }
.zw video { position: absolute; inset: 0; width: 100%%; height: 100%%; object-fit: cover; }
#captions, #cards { position: absolute; inset: 0; pointer-events: none; }
#captions { z-index: 20; }
#cards { z-index: 10; }
.card { position: absolute; visibility: hidden; overflow: hidden; }
.card .cu-root, .card .tc-root, .card .sp-root { position: absolute; left: 0; top: 0; width: 100%%; }
.card-label { position: absolute; left: 0; width: 100%%; display: flex; align-items: center; justify-content: center; color: var(--fg);
  font-family: var(--font-body); font-weight: 500; font-size: 40px; text-align: center; }
%(css)s
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="%(w)d" data-height="%(h)d" data-duration="%(dur)s" data-fps="%(fps)d">
%(clips)s
<div id="cards"></div>
<div id="captions">
%(caption_markup)s
</div>
</div>
<script>
%(markup_consts)s
%(card_scripts)s
</script>
<script>
window.__timelines = window.__timelines || {};
var V = Object.assign({ words: [], chunks: [], tops: [], word_tops: [], beats: [], zooms: [], duration: 1, fps: 30,
  colors: { bg: "#000000", text: "#ffffff", muted: "#aaaaaa", accent: "#ffffff", chip_fill: "#000000" } },
  (window.__hyperframes && window.__hyperframes.getVariables ? window.__hyperframes.getVariables() : window.__hfVariables) || {});
window.__hfV = V;
var main = gsap.timeline({ paused: true });
main.set({}, {}, %(dur)s);
window.__hfMain = main;
window.__hfChild = function () { return gsap.timeline(); };
document.getElementById("captions").style.setProperty("--hf-accent", V.colors.accent);
window.__hfFonts = Promise.all(%(fonts_js)s.map(function (f) { return document.fonts.load(f); }));
(V.zooms || []).forEach(function (zm) {
  main.fromTo("#zw" + zm.k, { scale: zm.z0 }, { scale: zm.z1, duration: zm.dur, ease: "none" }, zm.start);
});
%(cards)s
</script>
<script>
%(caption_script)s
window.__hfFonts.then(function () { window.__timelines["main"] = main; });
</script>
</body>
</html>
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--renderer-src", required=True, help="a read-only copy of providers/renderer (its planning code is reused)")
    p.add_argument("--edl", required=True)
    p.add_argument("--beats", required=True)
    p.add_argument("--vocabulary", required=True)
    p.add_argument("--platform-file", required=True)
    p.add_argument("--registry", required=True, help="the fetched HyperFrames registry root (contains registry/components)")
    p.add_argument("--gsap", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--caption", choices=sorted(ports.CAPTIONS), default="highlight")
    p.add_argument("--plant-overlap", help="beat id: draw that card on top of the face box (the planted failure of check C6)")
    args = p.parse_args(argv)
    report = build(args)
    json.dump({k: report[k] for k in ("caption", "patches", "kept_ranges", "zoomed_ranges", "skipped")}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
