"""Adapter: our renderer-neutral edit list and beats -> a HyperFrames project (a folder with index.html and compositions/).

Runs inside the spike image (Python 3 standard library). It reuses our own planning code, read-only, from a mounted copy of
providers/renderer: the document checks (`_edl.check_edl`, `check_beats`) and the timeline (`_edl.resolve_timeline`: caption windows,
beat windows, the face box each one must avoid, the zoom of each kept range). Only the drawing is HyperFrames'.

  python3 hf_adapter.py --renderer-src /renderer --edl edl.json --beats beats.json --vocabulary video-presets.json \
      --platform-file instagram.json --registry /opt/hf-registry --gsap /opt/hf/node_modules/gsap/dist/gsap.min.js \
      --out /work/project --caption sweep|pulse|block

It writes <out>/index.html, <out>/compositions/*.html, <out>/gsap.min.js, <out>/fonts/*.woff2 and <out>/adapter-report.json. The recording is
referenced as media/source.mov inside the project: the caller mounts it there (read-only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ports  # noqa: E402

REGISTRY = "registry/components"


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


def css_color(theme: dict, token: str) -> str:
    return theme["colors"].get(token, theme["colors"]["accent"]) if not token.startswith("#") else token


def build(args) -> dict:
    sys.path.insert(0, args.renderer_src)
    import _edl
    import _frames
    import _vocab
    from _text import Refusal

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
    report: dict = {"fps": fps, "out_frames": edl["out_frames"], "caption": args.caption, "skipped": [], "hosts": []}

    # ---- the project folder
    out = args.out
    for sub_dir in ("compositions", "fonts", "media"):
        os.makedirs(os.path.join(out, sub_dir), exist_ok=True)
    shutil.copyfile(args.gsap, os.path.join(out, "gsap.min.js"))
    font_faces = []
    for role, f in theme["fonts"].items():
        row = allow.get(f["id"])
        if row is None:
            continue
        src = os.path.join(_frames.fonts_dir(), row["file"])
        raw = open(src, "rb").read()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise SystemExit("font %s differs from the allow-list" % f["id"])
        shutil.copyfile(src, os.path.join(out, "fonts", row["file"]))
        font_faces.append('@font-face { font-family: "%s"; font-weight: %d; src: url("fonts/%s") format("woff2"); }'
                          % (row["family"], row["weight"], row["file"]))

    # ---- cuts: one <video> per kept range, the same source, trimmed by data-media-start / data-duration
    clips, zooms, pos = [], [], 0
    anchor = None
    import _media
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
            zooms.append((k, start, dur, z0, z1))
        pos += b - a

    # ---- captions: one sub-composition over the whole length, built from the registry component
    words = edl["words"]
    at = {w["index"]: n for n, w in enumerate(words)}
    chunk_zone = {(c["word_from"], c["word_to"]): c for c in timeline["captions"]}
    chunks_pos, tops, word_tops = [], [], [0] * len(words)
    margin = z["caption_margin"]
    cap_id, cap_port = ports.CAPTIONS[args.caption]
    for a_idx, b_idx in edl["captions"]["chunks"]:
        entry = chunk_zone.get((a_idx, b_idx))
        face = entry["face"] if entry else edl["face_box"]
        band = _edl.zones(data, face)["caption"]
        chunks_pos.append([at[a_idx], at[b_idx]])
        if args.caption == "pulse":
            tops.append(band[0] + margin + 62 - 140)       # a 280 px group box whose text sits about 124 px high
        elif args.caption == "sweep":
            tops.append(band[0] + margin)
        else:
            tops.append((band[0] + band[1]) // 2)
        for n in range(at[a_idx], at[b_idx] + 1):
            word_tops[n] = (band[0] + band[1]) // 2
    ctx = {"words": [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in words], "chunks": chunks_pos, "duration": out_seconds,
           "colors": colors, "tops": tops, "word_tops": word_tops}
    cap_src = read_text(os.path.join(args.registry, REGISTRY, cap_id, cap_id + ".html"))
    write_text(os.path.join(out, "compositions", cap_id + ".html"), cap_port(cap_src, ctx))
    hosts = ['<div id="cap" data-composition-id="%s" data-composition-src="compositions/%s.html" data-start="0" data-duration="%s" '
             'data-track-index="20" data-width="%d" data-height="%d"></div>' % (cap_id, cap_id + "", num(out_seconds), size[0], size[1])]
    n_caption_patches = len(ports.PATCH_LOG)

    # ---- overlays: the registry's sub-compositions, with our words as per-instance variables
    tokens = ("--bg:transparent;--fg:%(text)s;--muted:%(muted)s;--surface:%(chip_fill)s;--border:%(accent)s;--brand:%(accent)s;--accent:%(accent)s;"
              "--radius:30px;--font-display:'Inter',sans-serif;--font-body:'Inter',sans-serif;--font-mono:'JetBrains Mono',monospace;" % colors)
    used_files = {}

    def comp_file(name: str, port) -> str:
        if name not in used_files:
            write_text(os.path.join(out, "compositions", name + ".html"), port(read_text(os.path.join(args.registry, REGISTRY, name, name + ".html"))))
            used_files[name] = True
        return name

    for e in timeline["beats"]:
        band = _edl.zones(data, e["face"])["card"]
        x, w_box = 65, size[0] - 130
        y, h_box = band[0], band[1] - band[0]
        start, dur = e["start_frame"] / fps, (e["end_frame"] - e["start_frame"]) / fps
        p = e["params"]
        col = css_color(theme, p.get("color", "accent"))
        style = "left:%dpx;top:%dpx;width:%dpx;height:%dpx;z-index:10;%s--border:%s;--brand:%s;" % (x, y, w_box, h_box, tokens, col, col)
        host_attrs = 'data-start="%s" data-duration="%s" data-track-index="10" data-width="%d" data-height="%d"' % (num(start), num(dur), w_box, h_box)
        if e["preset"] == "keyword":
            cid = comp_file("spring-pop", ports.port_spring_pop)
            var = json.dumps({"text": p["text"]}, ensure_ascii=False)
            fs = int(min(110, h_box * 0.5, (w_box * 0.82 - 130) / (max(1, len(p["text"])) * 0.56)))
            style += "--sp-font:%dpx;" % fs
            hosts.append("<div id=\"%s\" data-composition-id=\"%s\" data-composition-src=\"compositions/%s.html\" %s data-variable-values='%s' style=\"%s\"></div>"
                         % (e["id"], cid, cid, host_attrs, var.replace("'", "&#39;"), style))
            if p.get("icon"):
                report["skipped"].append({"beat": e["id"], "what": "icon %s: the component has a dot, not our icon set" % p["icon"]})
        elif e["preset"] == "list":
            items = [s.strip() for s in p["items"].split("|")]
            cid = "list-" + e["id"]
            write_text(os.path.join(out, "compositions", cid + ".html"), ports.make_list(cid, items, w_box, h_box, colors["text"], dur))
            hosts.append("<div id=\"%s\" data-composition-id=\"%s\" data-composition-src=\"compositions/%s.html\" %s style=\"%s\"></div>"
                         % (e["id"], cid, cid, host_attrs, style))
        elif e["preset"] == "number":
            cid = comp_file("count-up", ports.port_count_up)
            raw = p["value"]
            digits = raw.replace(".", "").replace(",", ".") if "," in raw else raw.replace(".", "") if raw.count(".") > 1 else raw
            var = json.dumps({"start": 0, "end": float(digits), "prefix": "", "suffix": "", "accent": "green"})
            h_num = int(h_box * 0.66)
            hosts.append("<div id=\"%s\" data-composition-id=\"%s\" data-composition-src=\"compositions/%s.html\" data-start=\"%s\" data-duration=\"%s\" "
                         "data-track-index=\"10\" data-width=\"%d\" data-height=\"%d\" data-variable-values='%s' style=\"%s\"></div>"
                         % (e["id"], cid, cid, num(start), num(dur), w_box, h_num, var, style.replace("height:%dpx" % h_box, "height:%dpx" % h_num)))
            lab = "label-" + e["id"]
            write_text(os.path.join(out, "compositions", lab + ".html"), ports.make_label(lab, p["label"], w_box, h_box - h_num, 40))
            hosts.append("<div id=\"%s-label\" data-composition-id=\"%s\" data-composition-src=\"compositions/%s.html\" data-start=\"%s\" data-duration=\"%s\" "
                         "data-track-index=\"11\" data-width=\"%d\" data-height=\"%d\" style=\"%s\"></div>"
                         % (e["id"], lab, lab, num(start), num(dur), w_box, h_box - h_num,
                            style.replace("top:%dpx" % y, "top:%dpx" % (y + h_num)).replace("height:%dpx" % h_box, "height:%dpx" % (h_box - h_num))))
        elif e["preset"] == "quote":
            cid = comp_file("testimonial-card", ports.port_testimonial)
            var = json.dumps({"quote": p["text"], "author": p.get("author", ""), "handle": "", "rating": 0}, ensure_ascii=False)
            hosts.append("<div id=\"%s\" data-composition-id=\"%s\" data-composition-src=\"compositions/%s.html\" %s data-variable-values='%s' style=\"%s\"></div>"
                         % (e["id"], cid, cid, host_attrs, var.replace("'", "&#39;"), style))
            report["skipped"].append({"beat": e["id"], "what": "the card's star rating and handle are hidden by CSS: our quote has neither"})
        else:
            report["skipped"].append({"beat": e["id"], "what": "preset %s (needs the person's asset): not built in the spike" % e["preset"]})
        report["hosts"].append({"id": e["id"], "preset": e["preset"], "start_frame": e["start_frame"], "end_frame": e["end_frame"]})

    zoom_js = "\n".join("tl.fromTo(\"#zw%d\", { scale: %.5f }, { scale: %.5f, duration: %s, ease: \"none\" }, %s);" % (k, z0, z1, num(dur), num(start))
                        for k, start, dur, z0, z1 in zooms)
    html = INDEX % {
        "faces": "\n".join(font_faces), "w": size[0], "h": size[1], "dur": num(out_seconds), "fps": fps, "clips": "\n".join(clips),
        "hosts": "\n".join(hosts), "origin": "%.2fpx %.2fpx" % anchor, "zoom": zoom_js, "bg": colors["bg"],
        "hide": "[data-composition-id=\"testimonial-card\"] .tc-rating { display: none; }"}
    write_text(os.path.join(out, "index.html"), html)
    report["patches"] = {"caption": n_caption_patches, "overlays": len(ports.PATCH_LOG) - n_caption_patches}
    report["patch_log"] = ports.PATCH_LOG
    report["zoomed_ranges"] = len(zooms)
    report["kept_ranges"] = len(edl["kept"])
    write_text(os.path.join(out, "adapter-report.json"), json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return report


INDEX = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=%(w)d, height=%(h)d">
<title>openhora spike</title>
<script src="gsap.min.js"></script>
<style>
%(faces)s
html, body { margin: 0; background: %(bg)s; }
#root { position: relative; width: 100%%; height: 100%%; overflow: hidden; background: %(bg)s; }
.zw { position: absolute; inset: 0; overflow: hidden; z-index: 0; transform-origin: %(origin)s; }
.zw video { position: absolute; inset: 0; width: 100%%; height: 100%%; object-fit: cover; }
#cap { z-index: 20; }
%(hide)s
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-width="%(w)d" data-height="%(h)d" data-duration="%(dur)s" data-fps="%(fps)d">
%(clips)s
%(hosts)s
</div>
<script>
const tl = gsap.timeline({ paused: true });
%(zoom)s
window.__timelines["main"] = tl;
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
    p.add_argument("--caption", choices=sorted(ports.CAPTIONS), default="sweep")
    args = p.parse_args(argv)
    report = build(args)
    json.dump({k: report[k] for k in ("caption", "patches", "kept_ranges", "zoomed_ranges", "skipped")}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
