#!/usr/bin/env python3
"""Render a short vertical video: cut by kept ranges, draw overlay frames with headless Chromium, composite.

Prototype of the plan's `renderer:video` render (P5). Pipeline, each step timed:
  edl      transcript + script -> output-timeline edit list (edl.py; code, no model)
  cut      ffmpeg trim/concat of the source by the kept ranges
  frames   HTML presets drawn frame by frame (renderAt(t, data)) by headless Chromium over the pipe,
           transparent PNGs on the OUTPUT timeline, `--jobs` pages at the same time
  compose  one ffmpeg command built as a list: layouts (pip), the two frame sequences, H.264 + AAC,
           1080x1920, faststart, bt709 tagged
"""
import argparse
import json
import os
import shutil
import struct
import sys
import threading
import time
import zlib

import cdp
import edl as E
import lint
import media
import presets as P

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(HERE, "templates")
DEFAULT_COLORS = {"bg": "#0B0F14", "text": "#FFFFFF", "muted": "#A8B0BC", "accent": "#FFC93C",
                  "chip_fill": "#1B1F2A", "chip_text": "#FFE08A", "chip_border": "#FFC93C"}
DEFAULT_FONTS = {
    "display": {"weight": 800, "fallback": '-apple-system, "Helvetica Neue", Arial, sans-serif'},
    "text": {"weight": 500, "fallback": '-apple-system, "Helvetica Neue", Arial, sans-serif'},
    "mono": {"weight": 500, "fallback": 'Menlo, ui-monospace, monospace'},
}
FONT_MAGIC = {b"wOF2": ("woff2", "font/woff2"), b"wOFF": ("woff", "font/woff"),
              b"\x00\x01\x00\x00": ("ttf", "font/ttf"), b"OTTO": ("otf", "font/otf"), b"true": ("ttf", "font/ttf")}


TAGS = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"


class RenderError(RuntimeError):
    pass


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- inputs

def load_theme(contract, color_flags, font_flags):
    """Colour tokens (#RRGGBB only) and fonts (allow-listed formats, checked by their bytes)."""
    colors = dict(DEFAULT_COLORS)
    given = {}
    for item in color_flags or []:
        name, _, value = item.partition("=")
        given[name] = value
    colors.update(P.validate_theme_colors(contract, given))
    fonts = {role: dict(spec) for role, spec in DEFAULT_FONTS.items()}
    serve = {}
    for item in font_flags or []:
        role, _, rest = item.partition("=")
        path, _, weight = rest.partition(":")
        if role not in contract["font_roles"]:
            raise RenderError("font role not allowed: %s" % role)
        w = int(weight) if weight else fonts[role]["weight"]
        if w not in range(100, 1000, 100):
            raise RenderError("font weight must be 100..900 in steps of 100")
        with open(path, "rb") as fh:
            data = fh.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024 or data[:4] not in FONT_MAGIC:
            raise RenderError("font file refused (type by bytes, 5 MiB limit): %s" % role)
        ext, mime = FONT_MAGIC[data[:4]]
        url_path = "/fonts/%s.%s" % (role, ext)
        serve[url_path] = (data, mime)
        fonts[role].update({"weight": w, "url": cdp.ORIGIN + url_path, "file": os.path.basename(path)})
    return colors, fonts, serve


def load_assets(contract, asset_flags):
    """PNG assets by slot id; type and dimensions checked from the header bytes."""
    serve, names = {}, {}
    for item in asset_flags or []:
        slot, _, path = item.partition("=")
        if not P.SLOT_ID.match(slot):
            raise RenderError("bad slot id")
        with open(path, "rb") as fh:
            data = fh.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise RenderError("asset must be a PNG (checked by bytes): %s" % slot)
        w, h = struct.unpack(">II", data[16:24])
        lim = contract["limits"]["assets_max_side"]
        if w > lim or h > lim or w < 1 or h < 1:
            raise RenderError("asset dimensions out of bounds: %s" % slot)
        serve["/assets/%s.png" % slot] = (data, "image/png")
        names[slot] = path
    return serve, names


def load_templates(contract):
    """Every template is linted, then served from memory. Returns (serve table, sha256 by preset)."""
    import hashlib
    serve, hashes = {}, {}
    for name, spec in contract["presets"].items():
        with open(os.path.join(TEMPLATE_DIR, spec["template"]), "rb") as fh:
            raw = fh.read()
        broken = lint.lint(raw.decode("utf-8"))
        if broken:
            raise RenderError("template %s breaks the determinism contract: %s" % (name, ", ".join(broken)))
        serve["/t/" + spec["template"]] = (raw, "text/html; charset=utf-8")
        hashes[name] = hashlib.sha256(raw).hexdigest()[:12]
    return serve, hashes


# ---------------------------------------------------------------- geometry and frame data

def pip_geometry(contract, position):
    f, size = contract["frame"], contract["pip"]["size"]
    x = f["safe"]["left"] if position.endswith("left") else f["width"] - f["safe"]["right"] - size
    y = f["safe"]["top"] if position.startswith("top") else f["safe"]["bottom"] - size
    return {"x": x, "y": y, "size": size}


def caption_data(contract, chunk, fps):
    f = contract["frame"]
    origin = chunk["start_frame"] / fps
    bottom_px = f["height"] - f["safe"]["bottom"]
    if chunk["lift"]:
        bottom_px = f["height"] - (f["safe"]["bottom"] - contract["pip"]["size"] - 30)
    data = {"params": chunk["params"], "duration": (chunk["end_frame"] - chunk["start_frame"]) / fps,
            "words": [{"text": w["text"], "start": round(w["start"] - origin, 4), "end": round(w["end"] - origin, 4)}
                      for w in chunk["words"]],
            "bottom_px": bottom_px, "anchor": chunk["params"]["position"], "center_px": f["height"] // 2}
    return data


def beat_data(contract, entry, fps):
    data = {"params": entry["params"], "duration": (entry["end_frame"] - entry["start_frame"]) / fps}
    if entry["preset"] == "pip":
        data["geom"] = pip_geometry(contract, entry["params"]["position"])
    return data


def build_jobs(contract, edl):
    """Frame jobs on the OUTPUT timeline: [(frame, track, entry_index)], later entry wins on overlap."""
    tracks = {"caption": edl["captions"], "beat": sorted(edl["overlays"] + edl["layouts"], key=lambda e: e["start_frame"])}
    n = edl["out_frames"]
    owner = {t: {} for t in tracks}
    for track, entries in tracks.items():
        for k, e in enumerate(entries):
            for f in range(max(0, e["start_frame"]), min(n, e["end_frame"])):
                owner[track][f] = k
    jobs = [(f, track, k) for track in tracks for f, k in owner[track].items()]
    jobs.sort()
    return tracks, jobs


def blank_png(w, h):
    raw = (b"\x00" + b"\x00" * (w * 4)) * h
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- ffmpeg argv (pure; tested)

def cut_argv(source, kept, fps, size, has_audio, out):
    w, h = size
    vparts, aparts, labels = [], [], []
    for k, (s, e) in enumerate(kept):
        vparts.append("[0:v]trim=start=%.6f:end=%.6f,setpts=PTS-STARTPTS[v%d]" % (s, e, k))
        labels.append("[v%d]" % k)
        if has_audio:
            aparts.append("[0:a]atrim=start=%.6f:end=%.6f,asetpts=PTS-STARTPTS[a%d]" % (s, e, k))
            labels.append("[a%d]" % k)
    n = len(kept)
    cat = "".join(labels) + "concat=n=%d:v=1:a=%d[cv]%s" % (n, 1 if has_audio else 0, "[ca]" if has_audio else "")
    post = ("[cv]fps=%s,scale=%d:%d:force_original_aspect_ratio=increase:in_color_matrix=bt709:out_color_matrix=bt709,"
            "crop=%d:%d,format=yuv420p,%s[vout]" % (fps, w, h, w, h, TAGS))
    graph = ";".join(vparts + aparts + [cat, post])
    if has_audio:
        graph += ";[ca]aformat=sample_rates=48000:channel_layouts=stereo[aout]"
    argv = [media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *media.RECORDING_IN, "-i", source,
            "-filter_complex", graph, "-map", "[vout]"]
    if has_audio:
        argv += ["-map", "[aout]", "-c:a", "pcm_s16le"]
    argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", out]
    return argv


def compose_argv(contract, edl, cut_path, frames_dir, mask_path, asset_paths, has_audio, layers, out,
                 max_bytes=300_000_000):
    """One ffmpeg command, built as a list. `layers` is the set of tracks that have frames.

    Order of the picture, bottom to top: the cut video; for each pip layout the asset (full frame) and the
    speaker in a circular bubble; the beat frames (overlays, cutaway, the pip ring and label); the captions.
    Colours: everything is composed in RGB (gbrp), the video read as bt709 tv range and written back as bt709.
    """
    fps, (w, h) = edl["fps"], edl["size"]
    total = edl["out_duration"]
    inputs = ["-i", cut_path]
    idx = {"cut": 0}
    n = 1
    for track in ("beat", "caption"):
        if track in layers:
            prefix = {"beat": "beat", "caption": "cap"}[track]
            inputs += ["-framerate", str(fps), "-i", os.path.join(frames_dir, prefix + "_%06d.png")]
            idx[track] = n
            n += 1
    pips = [l for l in edl["layouts"] if l["preset"] == "pip"]
    pip_in = []
    for l in pips:
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", "%.3f" % total, "-i", asset_paths[l["asset"]]]
        pip_in.append(n)
        n += 1
    mask_in = None
    if pips:
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", "%.3f" % total, "-i", mask_path]
        mask_in = n
        n += 1

    g = ["[0:v]scale=in_range=tv:in_color_matrix=bt709:out_range=pc,format=gbrp[base]"]
    cur = "base"
    size = contract["pip"]["size"]
    if pips:
        k = len(pips)
        g.append("[base]split=%d[main]%s" % (k + 1, "".join("[spk%d]" % i for i in range(k))))
        cur = "main"
        g.append("[%d:v]format=gray,scale=%d:%d,split=%d%s" % (mask_in, size, size, k, "".join("[m%d]" % i for i in range(k))))
        for i, l in enumerate(pips):
            s, e = l["start_frame"] / fps, l["end_frame"] / fps
            en = "enable='between(t,%.4f,%.4f)'" % (s, e)
            geom = pip_geometry(contract, l["params"]["position"])
            g.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,format=gbrp[as%d]" % (pip_in[i], w, h, w, h, i))
            g.append("[%s][as%d]overlay=0:0:format=gbrp:%s[oa%d]" % (cur, i, en, i))
            g.append("[spk%d]crop=%d:%d:0:%d,scale=%d:%d,format=gbrp[sq%d]" % (i, w, w, (h - w) // 2, size, size, i))
            g.append("[sq%d][m%d]alphamerge[bub%d]" % (i, i, i))
            g.append("[oa%d][bub%d]overlay=%d:%d:format=gbrp:%s[ob%d]" % (i, i, geom["x"], geom["y"], en, i))
            cur = "ob%d" % i
    for track in ("beat", "caption"):
        if track in idx:
            g.append("[%d:v]format=gbrap[l_%s]" % (idx[track], track))
            g.append("[%s][l_%s]overlay=0:0:format=gbrp[c_%s]" % (cur, track, track))
            cur = "c_%s" % track
    g.append("[%s]scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p,%s[vout]" % (cur, TAGS))
    argv = [media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(g), "-map", "[vout]"]
    if has_audio:
        argv += ["-map", "0:a", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    argv += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
             "-r", str(fps), "-fps_mode", "cfr", "-frames:v", str(edl["out_frames"]), "-shortest", "-fs", str(max_bytes),
             "-movflags", "+faststart", out]
    return argv


# ---------------------------------------------------------------- frame loop

def render_frames(contract, edl, serve, setup_colors, setup_fonts, browser, jobs_n, frames_dir, workdir,
                  fast_png, dedupe, time_limit):
    w, h = edl["size"]
    fps = edl["fps"]
    tracks, jobs = build_jobs(contract, edl)
    os.makedirs(frames_dir, exist_ok=True)
    blank = os.path.join(frames_dir, "blank.png")
    with open(blank, "wb") as fh:
        fh.write(blank_png(w, h))

    used = {}
    for track, entries in tracks.items():
        for e in entries:
            used.setdefault(e["preset"] if track == "beat" else "caption", e)
    stats = {"rendered": 0, "reused": 0}
    lock = threading.Lock()
    errors = []

    with cdp.Chrome(browser, serve, os.path.join(workdir, "chrome"), headless_flag="--headless",
                    time_limit=time_limit) as chrome:
        info = chrome.send("Browser.getVersion")
        facts = {"browser": info.get("product"), "browser_pid": chrome.proc.pid}
        log("browser: %s (pid %d), %d frame jobs, jobs=%d" % (info.get("product"), chrome.proc.pid, len(jobs), jobs_n))

        def setup_cfg(preset):
            spec = contract["presets"][preset]
            images = {}
            if spec.get("page_images"):
                for e in edl["layouts"] + edl["overlays"]:
                    if e["preset"] == preset:
                        images[e["asset"]] = cdp.ORIGIN + "/assets/%s.png" % e["asset"]
            return {"colors": setup_colors, "fonts": {r: {k: v for k, v in f.items() if k in ("url", "weight", "fallback")}
                                                      for r, f in setup_fonts.items()}, "images": images}

        def worker(chunk):
            pages, last = {}, {}
            try:
                for f, track, k in chunk:
                    entry = tracks[track][k]
                    preset = "caption" if track == "caption" else entry["preset"]
                    spec = contract["presets"][preset]
                    if preset not in pages:
                        pg = chrome.new_page(w, h)
                        pg.open("/t/" + spec["template"], setup_cfg(preset))
                        pages[preset] = pg
                    pg = pages[preset]
                    data = caption_data(contract, entry, fps) if track == "caption" else beat_data(contract, entry, fps)
                    t = (f - entry["start_frame"]) / fps
                    sig = pg.frame(t, data)
                    dest = os.path.join(frames_dir, "%s_%06d.png" % ("cap" if track == "caption" else "beat", f))
                    prev = last.get(preset)
                    if dedupe and prev and prev[0] == k and prev[1] == sig:
                        os.link(prev[2], dest)
                        with lock:
                            stats["reused"] += 1
                    else:
                        png = pg.screenshot(fast_png)
                        with open(dest, "wb") as fh:
                            fh.write(png)
                        last[preset] = (k, sig, dest)
                        with lock:
                            stats["rendered"] += 1
            except Exception as exc:  # collected, then raised once all workers stopped
                errors.append(exc)

        per = max(1, -(-len(jobs) // jobs_n))
        chunks = [jobs[i:i + per] for i in range(0, len(jobs), per)]
        threads = [threading.Thread(target=worker, args=(c,)) for c in chunks]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        if errors:
            raise RenderError("frame loop failed: %s" % errors[0])
        if chrome.blocked:
            raise RenderError("a page asked for a resource that is not served from memory: %s" % chrome.blocked[:3])
        pid = chrome.proc.pid
    # fill the frames where a track has nothing to draw with the shared transparent frame
    present = {t: set() for t in tracks}
    for f, track, k in jobs:
        present[track].add(f)
    for track, prefix in (("caption", "cap"), ("beat", "beat")):
        if not present[track]:
            continue
        for f in range(edl["out_frames"]):
            if f not in present[track]:
                os.link(blank, os.path.join(frames_dir, "%s_%06d.png" % (prefix, f)))
    layers = {t for t in tracks if present[t]}
    facts.update({"frames_rendered": stats["rendered"], "frames_reused": stats["reused"], "frame_jobs": len(jobs),
                  "layers": sorted(layers)})
    return layers, facts


# ---------------------------------------------------------------- main

def faststart_ok(path):
    """moov atom before mdat."""
    with open(path, "rb") as fh:
        head = fh.read(1 << 20)
    m, d = head.find(b"moov"), head.find(b"mdat")
    return m != -1 and (d == -1 or m < d)


def render(args):
    t_all = time.time()
    contract = P.load_contract(args.presets)
    out_dir = os.path.abspath(args.workdir)
    os.makedirs(out_dir, exist_ok=True)
    timings = {}

    # inputs ------------------------------------------------------------
    facts_in = media.probe(args.source)
    log("source: %dx%d %.2ffps %.2fs audio=%s" % (facts_in["width"], facts_in["height"], facts_in["fps"],
                                                  facts_in["duration"], facts_in["has_audio"]))
    colors, fonts, font_serve = load_theme(contract, args.color, args.font)
    asset_serve, asset_files = load_assets(contract, args.asset)
    tpl_serve, tpl_hashes = load_templates(contract)
    serve = {}
    serve.update(tpl_serve)
    serve.update(font_serve)
    serve.update(asset_serve)

    silences = None
    t0 = time.time()
    if args.silences:
        silences = [(s["start"], s["end"]) for s in E.load_json(args.silences)]
    elif args.silence_detect:
        sil = media.close_open_silences(media.silencedetect(args.source), facts_in["duration"])
        silences = [(s["start"], s["end"]) for s in sil]
        log("silencedetect: %d intervals" % len(silences))
    timings["analyse"] = time.time() - t0

    # edit list ---------------------------------------------------------
    t0 = time.time()
    transcript = E.load_json(args.transcript)
    edl = E.build_edl(transcript, E.load_json(args.script), contract, silences, args.gap, args.margin, args.threshold)
    for slot in {e["asset"] for e in edl["layouts"] + edl["overlays"] if "asset" in e}:
        if slot not in asset_files:
            raise RenderError("slot has no uploaded file: %s" % slot)
    edl_path = os.path.join(out_dir, "edl.json")
    with open(edl_path, "w", encoding="utf-8") as fh:
        json.dump(edl, fh, indent=1)
    timings["edl"] = time.time() - t0
    print(E.format_report(edl), file=sys.stderr)
    log("edl: source %.2fs -> output %.2fs (%d frames), %d kept ranges" % (edl["source_duration"], edl["out_duration"],
                                                                       edl["out_frames"], len(edl["kept"])))
    if edl["out_duration"] > args.max_seconds:
        raise RenderError("output longer than the limit")

    # cut ---------------------------------------------------------------
    t0 = time.time()
    cut_path = os.path.join(out_dir, "cut.mov")
    kept = [(r["src_start"], r["src_end"]) for r in edl["kept"]]
    media.run(cut_argv(args.source, kept, edl["fps"], edl["size"], facts_in["has_audio"], cut_path))
    timings["cut"] = time.time() - t0
    log("cut: %.2fs" % timings["cut"])

    # frames ------------------------------------------------------------
    t0 = time.time()
    frames_dir = os.path.join(out_dir, "frames")
    if os.path.isdir(frames_dir):
        shutil.rmtree(frames_dir)
    browser = cdp.find_browser(args.browser)
    layers, ffacts = render_frames(contract, edl, serve, colors, fonts, browser, args.jobs, frames_dir, out_dir,
                                   args.fast_png, not args.no_dedupe, args.time_limit)
    timings["frames"] = time.time() - t0
    log("frames: %.2fs" % timings["frames"])

    # compose -----------------------------------------------------------
    t0 = time.time()
    mask_path = os.path.join(out_dir, "mask.png")
    size = contract["pip"]["size"]
    media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=%dx%d" % (size, size),
               "-vf", "geq=lum='clip((W/2-hypot(X-W/2+0.5,Y-H/2+0.5))*255,0,255)':cb=128:cr=128,format=gray",
               "-frames:v", "1", mask_path])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    part = args.out + ".part.mp4"
    media.run(compose_argv(contract, edl, cut_path, frames_dir, mask_path, asset_files, facts_in["has_audio"],
                           layers, part, args.max_bytes))
    os.replace(part, args.out)
    timings["compose"] = time.time() - t0
    log("compose: %.2fs" % timings["compose"])

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)
    out_facts = media.probe_output(args.out)
    total = time.time() - t_all
    n_rendered = ffacts["frames_rendered"]
    summary = {
        "out": args.out, "sha256": media.sha256_file(args.out), "bytes": out_facts["bytes"],
        "faststart": faststart_ok(args.out), "output": out_facts,
        "frames_total": edl["out_frames"], "frames_rendered": n_rendered, "frames_reused": ffacts["frames_reused"],
        "frame_jobs": ffacts["frame_jobs"], "jobs": args.jobs, "browser": ffacts["browser"],
        "seconds": {k: round(v, 2) for k, v in timings.items()},
        "seconds_total": round(total, 2),
        "seconds_per_rendered_frame": round(timings["frames"] / max(1, n_rendered), 4),
        "seconds_per_frame_job": round(timings["frames"] / max(1, ffacts["frame_jobs"]), 4),
        "templates": tpl_hashes, "fonts": {r: f.get("file", "system default") for r, f in fonts.items()},
        "colors": colors,
    }
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render a short vertical video from a recording, a transcript and a script.")
    ap.add_argument("--source", required=True, help="the recording (MP4/MOV)")
    ap.add_argument("--transcript", required=True, help="transcript.json: words with start/end and segment")
    ap.add_argument("--script", required=True, help="script.json: beats with spoken line, preset, params")
    ap.add_argument("--out", required=True, help="output MP4")
    ap.add_argument("--workdir", required=True, help="scratch folder for the edit list, the cut and the frames")
    ap.add_argument("--presets", default=P.DEFAULT_CONTRACT)
    ap.add_argument("--browser", help="Chromium / headless shell executable (default: search the Playwright cache, then Chrome)")
    ap.add_argument("--jobs", type=int, default=2, help="pages rendering frame ranges at the same time (default 2)")
    ap.add_argument("--color", action="append", metavar="TOKEN=#RRGGBB", help="theme colour token (repeatable)")
    ap.add_argument("--font", action="append", metavar="ROLE=FILE[:WEIGHT]", help="font file for display, text or mono (repeatable)")
    ap.add_argument("--asset", action="append", metavar="SLOT=FILE.png", help="PNG for an asset slot (repeatable)")
    ap.add_argument("--silences", help="JSON list of {start,end}; cuts are confirmed by it")
    ap.add_argument("--silence-detect", action="store_true", help="run ffmpeg silencedetect on the source to confirm cuts")
    ap.add_argument("--gap", type=float, default=0.5)
    ap.add_argument("--margin", type=float, default=0.15)
    ap.add_argument("--threshold", type=float, default=E.DEFAULT_THRESHOLD)
    ap.add_argument("--fast-png", action="store_true", help="captureScreenshot optimizeForSpeed (bigger frames)")
    ap.add_argument("--no-dedupe", action="store_true", help="screenshot every frame even if the DOM did not change")
    ap.add_argument("--keep-frames", action="store_true")
    ap.add_argument("--max-seconds", type=float, default=90.0, help="longest output accepted")
    ap.add_argument("--max-bytes", type=int, default=300_000_000)
    ap.add_argument("--time-limit", type=int, default=1800, help="browser process group is killed past this (s)")
    args = ap.parse_args(argv)
    try:
        summary = render(args)
    except (RenderError, E.EdlError, P.ParamError, media.MediaError, cdp.CDPError, cdp.RenderBlocked) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
