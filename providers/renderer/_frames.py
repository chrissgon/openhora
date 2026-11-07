"""Inputs served to the page, and the frame loop.

What the browser may load is decided here and nowhere else: the blocks' pages (each pinned by sha256 in blocks/pins.json and
linted for the determinism contract), the fonts (from the allow-list, checked by hash), and the person's image assets (checked by their
header bytes), all served from memory by the CDP driver under one synthetic origin. Nothing is navigated to file://, and
every other request fails the render. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time

import _blocks
import _cdp
import _layout
import _redact
from _assets import (FONT_ID, FONT_MAGIC, font_allowlist, fonts_dir, image_facts, load_assets, load_fonts, read_regular)  # noqa: F401  (moved: the callers and tests still find them here)
from _layout import caption_hit, face_hit  # noqa: F401
from _lint import lint
from _text import Refusal

ASSET_MIME = {"png": "image/png", "jpg": "image/jpeg"}
BLOCKS_DIR = _blocks.BLOCKS_DIR


# ---------------------------------------------------------------- templates

def template_pins(blocks_dir: str = BLOCKS_DIR) -> dict:
    """{path inside blocks/: sha256} of the pinned pages of the blocks."""
    return {rel: digest for rel, digest in _blocks.read_pins(blocks_dir)[1].items() if _blocks.IMPLEMENTATION.fullmatch(rel)}


def load_templates(names: list, blocks_dir: str = BLOCKS_DIR) -> tuple:
    """Serve the named pages (paths inside blocks/, "oh/keyword/renderat.html") from memory: only from the pinned files of the
    folder, each with the pinned hash, each clean under the determinism lint. Returns (serve table, sha256 by block name)."""
    pins = template_pins(blocks_dir)
    serve, hashes = {}, {}
    for name in sorted(set(names)):
        if name not in pins:
            raise Refusal("template_not_pinned", name.replace("/", ":")[:60])
        raw = read_regular(os.path.join(blocks_dir, name), 1 << 20, "template_unreadable", name.replace("/", ":")[:60])
        digest = hashlib.sha256(raw).hexdigest()
        if digest != pins[name]:
            raise Refusal("template_hash", name.replace("/", ":")[:60])
        try:
            broken = lint(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise Refusal("template_unreadable", name.replace("/", ":")[:60]) from None
        if broken:
            raise Refusal("template_lint", "%s:%s" % (name.replace("/", ":"), ",".join(broken)))
        serve["/t/" + name] = (raw, "text/html; charset=utf-8")
        hashes[_blocks.block_of(name)] = digest
    return serve, hashes


# ---------------------------------------------------------------- fonts

# ---------------------------------------------------------------- assets

# ---------------------------------------------------------------- the frame data of each page

def pip_geometry(data: dict, position: str) -> dict:
    f, size = data["frame"], data["pip"]["size"]
    x = (f["width"] - size) // 2
    y = f["safe"]["top"] if position == "top" else f["safe"]["bottom"] - size
    return {"x": x, "y": y, "size": size}


def caption_data(data: dict, edl: dict, chunk: dict, by_index: dict, fps: int) -> dict:
    f = data["frame"]
    origin = chunk["start_frame"] / fps
    words = [by_index[i] for i in sorted(by_index) if chunk["word_from"] <= i <= chunk["word_to"]]
    return {"duration": (chunk["end_frame"] - chunk["start_frame"]) / fps, "anchor": edl["captions"]["position"],
            "words": [{"text": w["text"], "start": round(w["start"] - origin, 4), "end": round(w["end"] - origin, 4)} for w in words],
            "zones": _layout.zones(data, chunk["face"]), "margin": data["zones"]["caption_margin"]}


def beat_data(data: dict, entry: dict, fps: int, edl: dict) -> dict:
    out = {"params": entry["params"], "look": data["presets"][entry["preset"]]["looks"], "zones": _layout.zones(data, entry["face"]),
           "duration": (entry["end_frame"] - entry["start_frame"]) / fps}
    if entry["preset"] == "pip":
        out["geom"] = pip_geometry(data, entry["params"].get("position", "top"))
    return out


REASON_LINES = 4
REASON_MAX = 200


def browser_reason(exc, log_path) -> str:
    """Why the browser did not start, in one short line: the kind of error and the first lines of what the browser wrote to its own
    log. Each line is redacted (credential formats, hidden characters), control characters become spaces, the whole is cut to
    REASON_MAX characters. The browser reads no transcript word, so its log carries none."""
    lines = []
    try:
        with open(log_path, "rb") as fh:
            raw = fh.read(4096)
        for line in raw.decode("utf-8", "replace").splitlines():
            line = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", line).strip()
            if line:
                lines.append(_redact.redact(line, limit=120))
            if len(lines) >= REASON_LINES:
                break
    except OSError:
        pass
    text = type(exc).__name__ + (": " + " | ".join(lines) if lines else "")
    text = re.sub(r"[^\x20-\x7e]", "?", text)
    return text[:REASON_MAX]


def frame_jobs(timeline: dict, out_frames: int) -> tuple:
    """Frame jobs on the OUTPUT timeline: ({track: entries}, [(frame, track, entry index)]). A frame belongs to one entry."""
    tracks = {"caption": timeline["captions"], "beat": timeline["beats"]}
    owner = {t: {} for t in tracks}
    for track, entries in tracks.items():
        for k, e in enumerate(entries):
            for f in range(max(0, e["start_frame"]), min(out_frames, e["end_frame"])):
                owner[track][f] = k
    jobs = sorted((f, track, k) for track in tracks for f, k in owner[track].items())
    return tracks, jobs


# ---------------------------------------------------------------- the frame loop

BACKDROP_JS = r"""
window.__backdrop = (geom, fill, bubble) => {
  // the storyboard's stand-ins under the pip's ring: the asset's slot as a flat full-frame colour and the speaker's bubble as a disc
  let a = document.getElementById('__pipfill'), b = document.getElementById('__pipbubble');
  if (!a) {
    a = document.createElement('div'); a.id = '__pipfill';
    b = document.createElement('div'); b.id = '__pipbubble';
    document.body.insertBefore(b, document.body.firstChild);
    document.body.insertBefore(a, document.body.firstChild);
  }
  a.style.cssText = 'position:absolute;left:0;top:0;width:1080px;height:1920px;background:' + fill;
  b.style.cssText = 'position:absolute;border-radius:50%;left:' + geom.x + 'px;top:' + geom.y + 'px;width:' + geom.size + 'px;height:' + geom.size + 'px;background:' + bubble;
  return true;
};
"""


def draw_frames(*, data, edl, timeline, serve, theme_fonts_urls, assets, browser, jobs_n, frames_dir, workdir, time_limit,
                templates, png_blank, only=None, backdrop=None, check_all=False):
    """Draw every frame of both tracks with `jobs_n` pages at the same time, into `frames_dir`.

    `only` (the storyboard's one use): a set of (track, frame) pairs; just those frames of the jobs are drawn and nothing else is
    written (no blank frame, no filler). `backdrop` (the same): {color, slot_fill}, the opaque colour the page is drawn over, so the
    PNG is a picture to look at; a pip beat also gets its asset slot and the speaker's bubble as flat stand-ins. With both left out the
    loop is the render's, unchanged.

    A page is opened once per block per worker, with the theme's colours and fonts set through CSSOM and every font
    and image awaited before frame 0. A frame whose DOM did not change since the previous frame of the same entry is
    a hard link of it. The sandbox is on; a browser that does not start is a render failure, with no second attempt.
    Returns (layers, facts)."""
    fps = edl["fps"]
    w, h = edl["size"]
    by_index = {x["index"]: x for x in edl["words"]}
    tracks, jobs = frame_jobs(timeline, edl["out_frames"])
    if only is not None and not check_all:
        jobs = [j for j in jobs if (j[1], j[0]) in only]
    os.makedirs(frames_dir, exist_ok=True)
    blank = os.path.join(frames_dir, "blank.png")
    if only is None:
        with open(blank, "wb") as fh:
            fh.write(png_blank(w, h))
    stats = {"rendered": 0, "reused": 0}
    lock = threading.Lock()
    errors = []
    colors = edl["theme"]["colors"]
    if not jobs:
        return set(), {"browser": None, "browser_sandbox": None, "frames_rendered": 0, "frames_reused": 0, "frame_jobs": 0, "layers": []}
    chrome = _cdp.Chrome(browser, serve, os.path.join(workdir, "chrome"), time_limit=time_limit)
    try:
        info = chrome.start()
    except (_cdp.CDPError, OSError) as exc:
        chrome.close()
        err = Refusal("browser_failed", "browser")
        err.reason = browser_reason(exc, chrome.log_path)
        raise err from None
    try:
        facts = {"browser": info.get("product") or chrome.send("Browser.getVersion").get("product"), "browser_pid": chrome.proc.pid,
                 "browser_sandbox": chrome.sandbox}

        def setup_cfg(preset, key):
            images = {}
            if data["presets"].get(preset, {}).get("page_images"):
                for e in timeline["beats"]:
                    if e["preset"] == preset and e.get("block", e["preset"]) == key:
                        for name, value in e["params"].items():
                            if value in assets:
                                images[value] = _cdp.ORIGIN + "/assets/%s.%s" % (value, assets[value]["kind"])
            return {"colors": colors, "fonts": theme_fonts_urls, "images": images}

        def worker(chunk):
            pages, last = {}, {}
            try:
                for f, track, k in chunk:
                    entry = tracks[track][k]
                    preset = "caption" if track == "caption" else entry["preset"]
                    key = "caption" if track == "caption" else entry.get("block", preset)
                    template = templates[key]
                    if key not in pages:
                        page = chrome.new_page(w, h)
                        page.open("/t/" + template, setup_cfg(preset, key))
                        if backdrop:
                            page.set_backdrop(backdrop["color"])
                            page.evaluate(BACKDROP_JS)
                        pages[key] = page
                    page = pages[key]
                    payload = caption_data(data, edl, entry, by_index, fps) if track == "caption" else beat_data(data, entry, fps, edl)
                    result = page.frame((f - entry["start_frame"]) / fps, payload)
                    sig = result["html"]
                    hit = face_hit(result["boxes"], entry["face"])
                    if hit:
                        raise Refusal("overlay_hits_face", hit)
                    band = _layout.zones(data, entry["face"])
                    for box in result["boxes"]:
                        if box["zone"] == "caption" and box["w"] > 0 and box["h"] > 0 and caption_hit(box, band):
                            raise Refusal("caption_below_line", "frame %d bottom %g" % (f, box["y"] + box["h"]))
                    if only is not None and (track, f) not in only:
                        continue                                           # checked, not drawn
                    if backdrop and preset == "pip":
                        page.evaluate("window.__backdrop(%s, %s, %s)" % (json.dumps(payload["geom"]), json.dumps(backdrop["slot_fill"]), json.dumps(backdrop["color"])))
                    dest = os.path.join(frames_dir, "%s_%06d.png" % ("cap" if track == "caption" else "beat", f))
                    prev = last.get(key)
                    if prev and prev[0] == k and prev[1] == sig:
                        os.link(prev[2], dest)
                        with lock:
                            stats["reused"] += 1
                    else:
                        png = page.screenshot()
                        with open(dest, "wb") as fh:
                            fh.write(png)
                        last[key] = (k, sig, dest)
                        with lock:
                            stats["rendered"] += 1
            except Exception as exc:     # collected, raised once every worker has stopped
                errors.append(exc)

        per = max(1, -(-len(jobs) // jobs_n))
        threads = [threading.Thread(target=worker, args=(jobs[i:i + per],)) for i in range(0, len(jobs), per)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        if errors:
            for e in errors:
                if isinstance(e, Refusal):
                    raise e
            blocked = any(isinstance(e, _cdp.RenderBlocked) for e in errors)
            err = Refusal("blocked_request" if blocked else "frame_failed", "frames")
            err.detail = str(errors[0])[:300]
            raise err
        time.sleep(0.2)                  # a refusal the browser logs arrives a moment after the frame that caused it
        if chrome.blocked or chrome.page_errors:
            raise Refusal("blocked_request", "frames")
    finally:
        chrome.close()
    present = {t: set() for t in tracks}
    for f, track, _ in jobs:
        present[track].add(f)
    for track, prefix in (("caption", "cap"), ("beat", "beat")):
        if present[track] and only is None:
            for f in range(edl["out_frames"]):
                if f not in present[track]:
                    os.link(blank, os.path.join(frames_dir, "%s_%06d.png" % (prefix, f)))
    layers = {t for t in tracks if present[t]}
    facts.update({"frames_rendered": stats["rendered"], "frames_reused": stats["reused"], "frame_jobs": len(jobs), "layers": sorted(layers)})
    return layers, facts
