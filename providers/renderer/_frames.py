"""Inputs served to the page, and the frame loop.

What the browser may load is decided here and nowhere else: the templates (each pinned by sha256 and linted for the
determinism contract), the fonts (from the allow-list, checked by hash), and the person's image assets (checked by their
header bytes), all served from memory by the CDP driver under one synthetic origin. Nothing is navigated to file://, and
every other request fails the render. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import threading
import time

import _cdp
import _redact
from _lint import lint
from _text import Refusal
from _vocab import HERE, SLOT_ID, read_json

FONT_MAGIC = {b"wOF2": ("woff2", "font/woff2"), b"wOFF": ("woff", "font/woff"), b"\x00\x01\x00\x00": ("ttf", "font/ttf"),
              b"OTTO": ("otf", "font/otf"), b"true": ("ttf", "font/ttf")}
FONT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,47}")
ASSET_MIME = {"png": "image/png", "jpg": "image/jpeg"}
TEMPLATES_DIR = os.path.join(HERE, "templates")


def read_regular(path: str, max_bytes: int, code: str, field: str) -> bytes:
    """A regular file's bytes, opened with O_NOFOLLOW (a symlink is refused) and read through that descriptor."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        raise Refusal(code, field) from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            raise Refusal(code, field)
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(max_bytes + 1)
    finally:
        os.close(fd)
    if len(data) > max_bytes:
        raise Refusal(code, field)
    return data


# ---------------------------------------------------------------- templates

def template_pins(templates_dir: str = TEMPLATES_DIR) -> dict:
    return read_json(os.path.join(templates_dir, "pins.json"))["templates"]


def write_pins(templates_dir: str = TEMPLATES_DIR) -> dict:
    """Maintainer tool: hash every template of the folder into pins.json."""
    pins = {}
    for name in sorted(os.listdir(templates_dir)):
        if name.endswith(".html"):
            pins[name] = hashlib.sha256(read_regular(os.path.join(templates_dir, name), 1 << 20, "template_unreadable", name)).hexdigest()
    with open(os.path.join(templates_dir, "pins.json"), "w", encoding="utf-8") as fh:
        json.dump({"note": "sha256 of each template. A template whose hash differs is refused. Rewritten by `ffmpeg.py pin-templates --confirmed` after a reviewed change.",
                   "templates": pins}, fh, indent=1)
        fh.write("\n")
    return pins


def load_templates(names: list, templates_dir: str = TEMPLATES_DIR) -> tuple:
    """Serve the named templates (file names) from memory: only from the allow-listed folder, each with the pinned
    hash, each clean under the determinism lint. Returns (serve table, hash by name)."""
    pins = template_pins(templates_dir)
    serve, hashes = {}, {}
    for name in sorted(set(names)):
        if os.path.basename(name) != name or name not in pins:
            raise Refusal("template_not_pinned", name)
        raw = read_regular(os.path.join(templates_dir, name), 1 << 20, "template_unreadable", name)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != pins[name]:
            raise Refusal("template_hash", name)
        try:
            broken = lint(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise Refusal("template_unreadable", name) from None
        if broken:
            raise Refusal("template_lint", "%s:%s" % (name, ",".join(broken)))
        serve["/t/" + name] = (raw, "text/html; charset=utf-8")
        hashes[name] = digest[:12]
    return serve, hashes


# ---------------------------------------------------------------- fonts

def fonts_dir() -> str:
    """The allow-listed font folder. Another folder is honoured only in test mode (RENDERER_TEST=1)."""
    if os.environ.get("RENDERER_TEST") == "1" and os.environ.get("RENDERER_ASSETS_DIR"):
        return os.path.join(os.environ["RENDERER_ASSETS_DIR"], "fonts")
    return os.path.join(HERE, "assets", "fonts")


def font_allowlist(directory=None) -> dict:
    """{id: row} of the allow-list file: each row has id, file (a plain name), sha256, weight, licence and source."""
    directory = directory or fonts_dir()
    doc = read_json(os.path.join(directory, "allowlist.json"))
    rows = {}
    try:
        for row in doc["fonts"]:
            if not FONT_ID.fullmatch(row["id"]) or os.path.basename(row["file"]) != row["file"] or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) \
                    or not row.get("licence") or not row.get("source") or row["id"] == "default":
                raise Refusal("bad_font_allowlist", "allowlist.json")
            rows[row["id"]] = row
    except (KeyError, TypeError):
        raise Refusal("bad_font_allowlist", "allowlist.json") from None
    return rows


def load_fonts(theme_fonts: dict, allowlist: dict, max_bytes: int, directory=None) -> tuple:
    """Serve the fonts the theme names, each re-checked against its allow-listed sha256. Returns (serve, used) where
    used maps a role to the file name or to `system default`."""
    directory = directory or fonts_dir()
    serve, used = {}, {}
    for role, f in theme_fonts.items():
        if f["id"] == "default":
            used[role] = "system default"
            continue
        row = allowlist.get(f["id"])
        if row is None:
            raise Refusal("font_not_allowed", role)
        data = read_regular(os.path.join(directory, row["file"]), max_bytes, "font_unreadable", role)
        if hashlib.sha256(data).hexdigest() != row["sha256"] or data[:4] not in FONT_MAGIC:
            raise Refusal("font_hash", role)
        ext, mime = FONT_MAGIC[data[:4]]
        serve["/fonts/%s.%s" % (role, ext)] = (data, mime)
        used[role] = row["id"]
    return serve, used


# ---------------------------------------------------------------- assets

def image_facts(data: bytes):
    """('png'|'jpg', width, height) from the header bytes, or None when the bytes are neither. An animated PNG is None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        pos = 8
        while pos + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[pos:pos + 8])
            if kind == b"acTL":
                return None
            if kind == b"IDAT":
                break
            pos += 12 + length
        return "png", w, h
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpg", w, h
            i += 2 + length
    return None


def load_assets(items: dict, sha256s: dict, limits: dict) -> dict:
    """Image assets by slot id: {slot: {kind, width, height, data, sha256}}. Type by the header bytes (PNG or JPEG, never
    animated), dimensions bounded, size bounded, the hash checked against the one recorded at intake when given."""
    out = {}
    for slot, path in items.items():
        if not SLOT_ID.fullmatch(slot):
            raise Refusal("bad_slot", slot[:32])
        data = read_regular(path, limits["asset_max_bytes"], "asset_unreadable", slot)
        facts = image_facts(data)
        if facts is None:
            raise Refusal("asset_type", slot)
        kind, w, h = facts
        if not (1 <= w <= limits["asset_max_side"] and 1 <= h <= limits["asset_max_side"]) or w * h > limits["asset_max_pixels"]:
            raise Refusal("asset_dimensions", slot)
        digest = hashlib.sha256(data).hexdigest()
        if sha256s.get(slot) and sha256s[slot] != digest:
            raise Refusal("asset_hash", slot)
        out[slot] = {"kind": kind, "width": w, "height": h, "data": data, "sha256": digest}
    return out


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
            "zones": _edl_zones(data, chunk["face"]), "margin": data["zones"]["caption_margin"]}


def _edl_zones(data: dict, face: dict) -> dict:
    """The two bands the face box leaves, for the face box as it is while this card or caption is on screen (zoom included)."""
    z = data["zones"]
    return {"card": [z["card_top"], face["y"] - z["gap"]], "caption": [face["y"] + face["h"] + z["gap"], z["caption_bottom"]]}


def beat_data(data: dict, entry: dict, fps: int, edl: dict) -> dict:
    out = {"params": entry["params"], "look": data["presets"][entry["preset"]]["looks"], "zones": _edl_zones(data, entry["face"]),
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


def face_hit(boxes: list, face: dict):
    """The zone (`card` or `caption`) of the first drawn box that touches the face box, else None. Layout presets
    (cutaway, pip) are not in a zone: they replace the picture, they do not sit over the face."""
    for b in boxes:
        if b["zone"] in ("card", "caption") and b["w"] > 0 and b["h"] > 0 \
                and b["x"] < face["x"] + face["w"] - 0.5 and b["x"] + b["w"] > face["x"] + 0.5 \
                and b["y"] < face["y"] + face["h"] - 0.5 and b["y"] + b["h"] > face["y"] + 0.5:
            return b["zone"]
    return None


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

    A page is opened once per preset per worker, with the theme's colours and fonts set through CSSOM and every font
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

        def setup_cfg(preset):
            images = {}
            if data["presets"].get(preset, {}).get("page_images"):
                for e in timeline["beats"]:
                    if e["preset"] == preset:
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
                    template = templates[preset]
                    if preset not in pages:
                        page = chrome.new_page(w, h)
                        page.open("/t/" + template, setup_cfg(preset))
                        if backdrop:
                            page.set_backdrop(backdrop["color"])
                            page.evaluate(BACKDROP_JS)
                        pages[preset] = page
                    page = pages[preset]
                    payload = caption_data(data, edl, entry, by_index, fps) if track == "caption" else beat_data(data, entry, fps, edl)
                    result = page.frame((f - entry["start_frame"]) / fps, payload)
                    sig = result["html"]
                    hit = face_hit(result["boxes"], entry["face"])
                    if hit:
                        raise Refusal("overlay_hits_face", hit)
                    if only is not None and (track, f) not in only:
                        continue                                           # checked, not drawn
                    if backdrop and preset == "pip":
                        page.evaluate("window.__backdrop(%s, %s, %s)" % (json.dumps(payload["geom"]), json.dumps(backdrop["slot_fill"]), json.dumps(backdrop["color"])))
                    dest = os.path.join(frames_dir, "%s_%06d.png" % ("cap" if track == "caption" else "beat", f))
                    prev = last.get(preset)
                    if prev and prev[0] == k and prev[1] == sig:
                        os.link(prev[2], dest)
                        with lock:
                            stats["reused"] += 1
                    else:
                        png = page.screenshot()
                        with open(dest, "wb") as fh:
                            fh.write(png)
                        last[preset] = (k, sig, dest)
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
