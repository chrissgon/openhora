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
from _payload import beat_data, caption_data, pip_geometry, split_geometry_of  # noqa: F401  (moved: the callers and tests still find them here)
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

# ---------------------------------------------------------------- the frame data of each page (moved to _payload.py)

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
  // the storyboard's stand-in under the pip's page: the asset's slot as a flat-colour card at the computed box
  let a = document.getElementById('__pipfill');
  if (!a) {
    a = document.createElement('div'); a.id = '__pipfill';
    document.body.insertBefore(a, document.body.firstChild);
  }
  a.style.cssText = 'position:absolute;border-radius:' + geom.radius + 'px;left:' + geom.x + 'px;top:' + geom.y + 'px;width:' + geom.w + 'px;height:' + geom.h + 'px;background:' + fill;
  return true;
};
"""


def admitted_call(fn, *args):
    """Run one call on an admitted page and map what it raises to the closed codes of the second contract: a font the host did not declare is
    `font_not_allowed` (the page's own check says so), a request or policy violation is `blocked_request` (raised as is), everything else the
    page does wrong (an exception, a timeout, a runtime that never became ready) is `block_failed`."""
    try:
        return fn(*args)
    except _cdp.RenderBlocked:
        raise
    except (_cdp.BlockFailed, _cdp.CDPError) as exc:
        if "font_not_allowed" in str(exc):
            raise Refusal("font_not_allowed", "frames") from None
        err = Refusal("block_failed", "frames")
        err.detail = str(exc)[:300]
        raise err from None


def draw_frames(*, data, edl, timeline, serve, theme_fonts_urls, assets, browser, jobs_n, frames_dir, workdir, time_limit,
                templates, png_blank, only=None, backdrop=None, check_all=False, admitted=None, reverse=False):
    """Draw every frame of both tracks with `jobs_n` pages at the same time, into `frames_dir`.

    `only` (the storyboard's one use): a set of (track, frame) pairs; just those frames of the jobs are drawn and nothing else is
    written (no blank frame, no filler). `backdrop` (the same): {color, slot_fill}, the opaque colour the page is drawn over, so the
    PNG is a picture to look at; a pip beat also gets its asset slot as a flat-colour card. A split beat gets its halves (`_layout.split_layouts`). With both left out the
    loop is the render's, unchanged.

    `admitted` (the second contract, `_hf_host.prepare`'s result, or None): the beats whose block runs on it are drawn from their own page, one per
    beat per worker, sought with the runtime's seek, every frame written (no link of a frame to the one before it) and no box reported: the render
    checks the pixels of those frames afterwards (`_alpha_gate`). The first contract's path is untouched.
    `reverse` (the admission test's one use): the jobs are taken last frame first.

    A page is opened once per block per worker, with the theme's colours and fonts set through CSSOM and every font
    and image awaited before frame 0. A frame whose DOM did not change since the previous frame of the same entry is
    a hard link of it. The sandbox is on; a browser that does not start is a render failure, with no second attempt.
    Returns (layers, facts)."""
    fps = edl["fps"]
    w, h = edl["size"]
    by_index = {x["index"]: x for x in edl["words"]}
    if any(e["preset"] == "pip" and "card" not in e for e in timeline["beats"]):      # the render settled them in `compose_plan`; the storyboard's call has not
        _layout.pip_cards(data, timeline, assets, drop=backdrop is None)
    if any(e["preset"] == "split" and "split" not in e for e in timeline["beats"]):   # as for the pips: settled in `compose_plan`, after them
        _layout.split_layouts(data, timeline, drop=backdrop is None)
    tracks, jobs = frame_jobs(timeline, edl["out_frames"])
    if only is not None and not check_all:
        jobs = [j for j in jobs if (j[1], j[0]) in only]
    if reverse:
        jobs = list(reversed(jobs))              # the admission test seeks the last frame first (with one page, so that the order is the whole order)
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
                            if value in assets and assets[value]["kind"] != "clip":      # a clip is drawn by the compose, never by the page (V9b-5a)
                                images[value] = _cdp.ORIGIN + "/assets/%s.%s" % (value, assets[value]["kind"])
            return {"colors": colors, "fonts": theme_fonts_urls, "images": images}

        def worker(chunk):
            pages, last = {}, {}
            try:
                for f, track, k in chunk:
                    entry = tracks[track][k]
                    preset = "caption" if track == "caption" else entry["preset"]
                    key = "caption" if track == "caption" else entry.get("block", preset)
                    if admitted and track != "caption" and key in admitted["pages"]:
                        pkey = (key, k)
                        if pkey not in pages:
                            page = chrome.new_page(w, h, contract="admitted")
                            admitted_call(page.open_admitted, admitted["pages"][key][k], admitted["ready"], admitted["fonts"])
                            pages[pkey] = page
                        if only is not None and (track, f) not in only:
                            continue                                       # a storyboard draws its rest frame only
                        png = admitted_call(pages[pkey].seek_admitted, (f - entry["start_frame"]) / fps)
                        with open(os.path.join(frames_dir, "beat_%06d.png" % f), "wb") as fh:
                            fh.write(png)
                        with lock:
                            stats["rendered"] += 1
                        continue
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
                    if track != "caption" and entry["preset"] == "split":
                        payload["geom"] = split_geometry_of(entry)
                    if track != "caption" and entry.get("params_kind"):
                        payload["params_kind"] = entry["params_kind"]
                        payload["clip_size"] = entry["clip_size"]      # {"asset": "clip"}: the page draws the label only; the compose draws the clip (V9b-5a)
                    result = page.frame((f - entry["start_frame"]) / fps, payload)
                    sig = result["html"]
                    hit = face_hit(result["boxes"], entry["face"])
                    if hit:
                        raise Refusal("overlay_hits_face", hit)
                    band = _layout.entry_zones(data, entry)
                    for box in result["boxes"]:
                        if box["zone"] == "caption" and box["w"] > 0 and box["h"] > 0 and caption_hit(box, band):
                            raise Refusal("caption_below_line", "frame %d bottom %g" % (f, box["y"] + box["h"]))
                    if only is not None and (track, f) not in only:
                        continue                                           # checked, not drawn
                    if backdrop and preset == "pip":
                        page.evaluate("window.__backdrop(%s, %s, %s)" % (json.dumps(dict(payload["geom"], radius=payload["look"]["radius_px"])), json.dumps(backdrop["slot_fill"]), json.dumps(backdrop["color"])))
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
            for e in errors:
                if isinstance(e, _cdp.BlockFailed):
                    err = Refusal("block_failed", "frames")
                    err.detail = str(e)[:300]
                    raise err
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
