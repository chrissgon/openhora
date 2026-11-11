"""The render: check, draw the overlay frames, compose with ffmpeg, check the file against the platform, address it.

  1. the edit list, the beats and the platform file are read and checked, and the recording is probed and matched to the
     edit list by its sha256;
  2. the pinned blocks (staged per job), the allow-listed fonts and the person's image assets are loaded and served from memory;
  3. the HTML presets are drawn frame by frame on the output timeline by the pinned browser over the DevTools pipe;
  4. one ffmpeg command cuts the recording and composes everything: H.264 + AAC, 1080x1920, faststart, bt709 tagged,
     capped by `-fs`;
  5. ffprobe checks the file against the platform's video spec; it is written as render-<sha12>.mp4, O_EXCL, mode 0400.

A render that goes past its time limit is stopped (the browser's process group and ffmpeg's are killed). Standard library.
"""
from __future__ import annotations

import math
import os
import shutil
import stat
import struct
import tempfile
import time
import zlib

import _blocks
import _edl
import _frames
import _media
from _output import (check_documents, check_recording, make_cover, make_still, png_size, read_platform, time_limit_for,  # noqa: F401  (moved: the render and its callers still find them here)
                     write_once)
from _text import Refusal
from _vocab import load_data, load_vocabulary, read_json

ENGINE = "ffmpeg"


def blank_png(w: int, h: int) -> bytes:
    raw = (b"\x00" + b"\x00" * (w * 4)) * h

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def load_documents(edl_path, beats_path, platform_path, vocabulary_path, fonts_directory=None):
    data = load_data()
    limits = data["limits"]
    edl = read_json(edl_path, limits["json_max_bytes"])
    beats = read_json(beats_path, limits["json_max_bytes"])
    platform = read_platform(platform_path)
    vocab = load_vocabulary(vocabulary_path)
    allow = _frames.font_allowlist(fonts_directory)
    return data, edl, beats, platform, vocab, allow


def font_urls_of(data, edl, font_serve) -> dict:
    """The theme's fonts as the page's setup wants them: {role: {weight, fallback[, url]}}."""
    urls = {}
    for role, f in edl["theme"]["fonts"].items():
        entry = {"weight": f["weight"], "fallback": data["theme"]["system_fallback"][role]}
        for path in font_serve:
            if path.startswith("/fonts/%s." % role):
                entry["url"] = "https://render.invalid" + path
        urls[role] = entry
    return urls


def compose_plan(data, edl, timeline, assets, platform, src, frames_rel="frames") -> dict:
    pips = []
    for e in timeline["beats"]:
        if e["preset"] == "pip":
            slot = e["params"]["asset"]
            geom = _frames.pip_geometry(data, e["params"].get("position", "top"))
            pips.append({"asset": "assets/%s.%s" % (slot, assets[slot]["kind"]), "kind": assets[slot]["kind"],
                         "start_frame": e["start_frame"], "end_frame": e["end_frame"], "x": geom["x"], "y": geom["y"]})
    layers = []
    if timeline["beats"]:
        layers.append("beat")
    if timeline["captions"]:
        layers.append("caption")
    face = edl["face_box"]
    plan = {"zoom": edl["zoom"], "face": {"cx": face["x"] + face["w"] // 2, "cy": face["y"] + face["h"] // 2, "w": face["w"], "h": face["h"]},
            "anchor": _media.anchor_point(face, edl["zoom"]["anchor_y"]),
            "fade": data["zoom"]["audio_fade_seconds"], "src": src, "fps": edl["fps"], "size": edl["size"], "has_audio": edl["source"]["has_audio"], "src_matrix": edl["source"]["color_matrix"],
            "kept": edl["kept"], "layers": layers, "frames_dir": frames_rel, "pips": pips, "pip_size": data["pip"]["size"],
            "out_frames": edl["out_frames"], "max_bytes": _media.byte_limit(platform), "out_name": "out.mp4"}
    effects = _edl.range_effects(edl, timeline)      # the punches and grades, by kept range (V9a-3): the plan of a render with none has no such key
    if effects:
        plan["effects"] = effects
    return plan


def render(*, edl_path, beats_path, src, out, platform_path, vocabulary_path, asset_files, asset_sha256s, ffmpeg, ffprobe, browser,
           jobs=3, dry_run=False, time_limit=None, cover_out=None, cover_offset_ms=None, blocks_dir=None, blocks_sha256=None, fonts_directory=None,
           scratch=None, log=lambda m: None) -> dict:
    started = time.time()
    data, edl, beats, platform, vocab, allow = load_documents(edl_path, beats_path, platform_path, vocabulary_path, fonts_directory)
    docs = check_documents(data, edl, beats, platform, vocab, allow)
    limits = data["limits"]
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)

    # the recording is the one the edit list was made from
    facts = check_recording(ffprobe, src, edl, limits)

    # assets: every slot a beat uses has a file, and every file is used
    used = set()
    for e in timeline["beats"]:
        for name in _slot_names(vocab, e):
            used.add(e["params"][name])
    missing = sorted(used - set(asset_files))
    if missing:
        raise Refusal("asset_missing", missing[0])
    extra = sorted(set(asset_files) - used)
    if extra:
        raise Refusal("asset_unused", extra[0])
    assets = _frames.load_assets({s: asset_files[s] for s in sorted(used)}, asset_sha256s, limits)

    catalogue = _blocks.load_catalogue(blocks_dir or _blocks.BLOCKS_DIR, blocks_sha256)
    templates, names = _blocks.templates_for(catalogue, ENGINE, timeline, vocab, with_caption=bool(timeline["captions"]))
    tpl_serve, tpl_hashes = _frames.load_templates(names, catalogue["dir"]) if names else ({}, {})
    font_serve, fonts_used = _frames.load_fonts(edl["theme"]["fonts"], allow, limits["font_max_bytes"], fonts_directory)
    asset_serve = {"/assets/%s.%s" % (s, a["kind"]): (a["data"], _frames.ASSET_MIME[a["kind"]]) for s, a in assets.items()}
    serve = {}
    serve.update(tpl_serve)
    serve.update(font_serve)
    serve.update(asset_serve)

    out_seconds = edl["out_frames"] / edl["fps"]
    limit = time_limit_for(data, out_seconds, time_limit)
    plan = compose_plan(data, edl, timeline, assets, platform, os.path.abspath(src))
    argv = _media.compose_argv(ffmpeg, plan)
    outdir = os.path.abspath(os.path.dirname(out) if out.endswith(".mp4") else out)
    _, jobs_list = _frames.frame_jobs(timeline, edl["out_frames"])
    estimate = len(jobs_list) * limits["frame_bytes_estimate"] + 64 * 1024 * 1024 + plan["max_bytes"]
    summary = {"ok": True, "dry_run": bool(dry_run), "out_dir": outdir, "out_seconds": round(out_seconds, 3), "out_frames": edl["out_frames"],
               "frame_jobs": len(jobs_list), "jobs": jobs, "time_limit_seconds": limit, "layers": plan["layers"],
               "beats_drawn": [{"id": e["id"], "preset": e["preset"], "block": e["block"], "start_frame": e["start_frame"], "end_frame": e["end_frame"]} for e in timeline["beats"]],
               "beats_dropped": timeline["dropped"], "unmatched_beats": beats["unmatched"], "mentions": docs["mentions"],
               "fonts": fonts_used, "blocks": tpl_hashes, "blocks_sha256": catalogue["sha256"], "ffmpeg_argv": argv, "estimated_bytes": estimate}
    if dry_run:
        return summary
    os.makedirs(outdir, mode=0o700, exist_ok=True)
    if shutil.disk_usage(scratch if scratch else outdir).free < estimate:
        raise Refusal("no_space", "output")
    scratch = os.path.abspath(scratch) if scratch else outdir        # the frames and the work files go here (memory-backed in the container)
    work = tempfile.mkdtemp(prefix=".render-", dir=scratch)
    os.chmod(work, 0o700)
    deadline = started + limit
    timings = {}
    try:
        t0 = time.time()
        os.mkdir(os.path.join(work, "assets"), 0o700)
        for slot, a in assets.items():
            fd = os.open(os.path.join(work, "assets", "%s.%s" % (slot, a["kind"])), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(a["data"])
        font_urls = font_urls_of(data, edl, font_serve)
        frames_dir = os.path.join(work, "frames")
        layers, ffacts = _frames.draw_frames(
            data=data, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls=font_urls, assets=assets, browser=browser["path"],
            jobs_n=max(1, min(jobs, 8)), frames_dir=frames_dir, workdir=work, time_limit=max(5, int(deadline - time.time())),
            templates=templates, png_blank=blank_png)
        timings["frames"] = round(time.time() - t0, 2)
        t0 = time.time()
        _media.run(argv, deadline - time.time(), cwd=work)
        timings["compose"] = round(time.time() - t0, 2)
        part = os.path.join(work, "out.mp4")
        verdict = _media.check_output(ffprobe, part, platform)
        if verdict["failures"]:
            raise Refusal("platform_spec", ",".join(verdict["failures"]))
        digest = _media.sha256_file(part)
        final = os.path.join(outdir, "render-%s.mp4" % digest[:12])
        replayed = write_once(part, final, digest)
        cover = None
        if cover_out is not None:
            cover = make_cover(ffmpeg, final, cover_out, cover_offset_ms or 0, verdict["facts"]["duration"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    timings["total"] = round(time.time() - started, 2)
    summary.update({"dry_run": False, "path": final, "sha256": digest, "bytes": verdict["facts"]["bytes"], "replayed": replayed,
                    "output": verdict["facts"], "seconds": timings, "browser": ffacts.get("browser"), "browser_sandbox": ffacts.get("browser_sandbox"),
                    "frames_rendered": ffacts["frames_rendered"], "frames_reused": ffacts["frames_reused"], "cover": cover})
    summary.pop("ffmpeg_argv")
    return summary


def _slot_names(vocab, entry):
    from _vocab import slot_params
    return [n for n in slot_params(vocab, entry["preset"]) if n in entry["params"]]
