"""The render: check, draw the overlay frames, compose with ffmpeg, check the file against the platform, address it.

  1. the edit list, the beats and the platform file are read and checked, and the recording is probed and matched to the
     edit list by its sha256;
  2. the pinned blocks (staged per job), the allow-listed fonts and the person's image assets are loaded and served from memory; a clip
     (V9b-5a, a normalised MP4 from `asset-sheet`, told from a picture by its first bytes) is checked and probed, never served to a page;
  3. the HTML presets are drawn frame by frame on the output timeline by the pinned browser over the DevTools pipe (a clip cutaway's page draws
     only its label);
  4. one ffmpeg command cuts the recording and composes everything (a clip cutaway included, under the beat layer): H.264 + AAC, 1080x1920,
     faststart, bt709 tagged, capped by `-fs`;
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

import _advice
import _alpha_gate
import _assets
import _blocks
import _cdp
import _edl
import _frames
import _hf_host
import _layout
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


def scratch_estimate(job_count: int, limits: dict, max_bytes: int) -> int:
    """The scratch a render needs before its first frame: one PNG per frame job at `frame_bytes_estimate`, the work files, and the output at most `max_bytes`.
    A frame the page draws again (same page state) is a hard link and costs nothing, and the blank frames are links too, so this counts the most a render can store.
    The figure is measured (PF-b1): the distinct PNGs of a 1080x1920 transparent layer of the offline fixture are 50 kB on average and 73 kB at most, so 120000 keeps a
    margin over the largest; the earlier 250000 refused a 300 s post (7493 frame jobs, about 2.24 GB against the 2048 MiB default scratch) that renders in 906 s."""
    return job_count * limits["frame_bytes_estimate"] + 64 * 1024 * 1024 + max_bytes


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
    _layout.pip_cards(data, timeline, assets)      # a pip with no room is taken out of the timeline here, before any frame is drawn
    _layout.split_layouts(data, timeline)      # after the pips (pip_cards resets every caption's band); a split with no caption room is taken out here
    pips = []
    for e in timeline["beats"]:
        if e["preset"] == "pip":
            slot = e["params"]["asset"]
            card = _frames.pip_geometry(data, e)
            pips.append({"asset": "assets/%s.%s" % (slot, assets[slot]["kind"]), "kind": assets[slot]["kind"],
                         "start_frame": e["start_frame"], "end_frame": e["end_frame"], "x": card["x"], "y": card["y"], "w": card["w"], "h": card["h"],
                         "radius": data["presets"]["pip"]["looks"]["radius_px"]})
    layers = []
    if timeline["beats"]:
        layers.append("beat")
    if timeline["captions"]:
        layers.append("caption")
    face = edl["face_box"]
    plan = {"zoom": edl["zoom"], "face": {"cx": face["x"] + face["w"] // 2, "cy": face["y"] + face["h"] // 2, "w": face["w"], "h": face["h"]},
            "anchor": _media.anchor_point(face, edl["zoom"]["anchor_y"]),
            "fade": data["zoom"]["audio_fade_seconds"], "src": src, "fps": edl["fps"], "size": edl["size"], "has_audio": edl["source"]["has_audio"], "src_matrix": edl["source"]["color_matrix"],
            "kept": edl["kept"], "layers": layers, "frames_dir": frames_rel, "pips": pips,
            "splits": _layout.split_rows(timeline),
            "out_frames": edl["out_frames"], "max_bytes": _media.byte_limit(platform), "out_name": "out.mp4"}
    clips = clip_rows(data, timeline, assets, edl["theme"]["colors"])
    if clips:
        plan["clips"] = clips                        # only a render that draws a clip cutaway has the key: any other plan is what it always was
    effects = _edl.range_effects(edl, timeline)      # the punches and grades, by kept range (V9a-3): the plan of a render with none has no such key
    if effects:
        plan["effects"] = effects
    drawn = [t for t in timeline.get("transitions") or [] if t["kind"] in _edl.FFMPEG_TRANSITIONS]
    if drawn:       # the ffmpeg transitions (P1a), each with its kind's numbers: the plan of a render with none has no such key
        plan["transitions"] = [dict(t, params=data["transitions"]["kinds"][t["kind"]]) for t in drawn]
    if timeline.get("echoes") and plan["has_audio"]:
        plan["echoes"] = timeline["echoes"]          # an aside's echo, on the joined sound: the plan of a render with none has no such key
    return plan


def admit_blocks(catalogue, timeline, data, edl, font_serve, vendor, hf_registry, browser_path) -> dict:
    """`_hf_host.prepare` with the image's folders (or the test folders `_inner.py` was given): what the second contract needs from this render's beats,
    refused before any frame is drawn. `browser_path` None (a dry run) leaves the browser's version, and so the runtime's hash, out."""
    version = _cdp.browser_version(browser_path) if browser_path else None
    return _hf_host.prepare(catalogue=catalogue, engine=ENGINE, timeline=timeline, data=data, edl=edl, font_serve=font_serve,
                            vendor=vendor or os.path.join(_here(), "vendor"), registry=hf_registry or os.path.join(_here(), "hf-registry"),
                            shims=os.path.join(_hf_host.runtime_dir(_here()), "shims"), browser_version=version)


def _here() -> str:
    return os.path.dirname(os.path.abspath(__file__))


CAPTION_DRAWN_MIN_FRAMES = 6      # a caption chunk shorter than this may draw nothing: the old engine's own floor (PF-b retired it; git history)


def admitted_ranges(data, timeline, admitted, out_frames) -> list:
    """The runs of output frames each admitted entry owns, each with the line of its own entry: [{start, end, line_y, prefix, id, require_drawn}]. A beat's line is the top of the caption band, so a card that reaches the captions is advice
    (`drawn_below_line`), and so is a range that draws nothing (`block_not_drawn`). Nothing is refused for touching the face (2026-11-24);
    a caption chunk's line is the bottom of its own caption band (the pip's or the split's included), so rows from there down must be clear, and a chunk of
    CAPTION_DRAWN_MIN_FRAMES frames or more should draw at least one pixel (advice otherwise)."""
    _, jobs = _frames.frame_jobs(timeline, out_frames)
    wanted = {"caption": set(admitted["pages"].get("caption", {})),
              "beat": {k for key, pages in admitted["pages"].items() if key != "caption" for k in pages}}
    owned = {}
    for f, track, k in jobs:
        if k in wanted[track]:
            owned.setdefault((track, k), []).append(f)
    rows = []
    for track, k in sorted(owned, key=lambda tk: (tk[0] != "beat", tk[1])):
        entry = timeline["captions" if track == "caption" else "beats"][k]
        caption = track == "caption"
        line_y = _layout.entry_zones(data, entry)["caption"][1 if caption else 0]
        run = owned[(track, k)]
        start = prev = run[0]
        for f in run[1:] + [None]:
            if f is None or f != prev + 1:
                rows.append({"start": start, "end": prev + 1, "line_y": line_y, "prefix": "cap" if caption else "beat", "id": "c%d" % k if caption else entry["id"],
                             "require_drawn": (prev + 1 - start) >= CAPTION_DRAWN_MIN_FRAMES if caption else True})
                start = f
            prev = f
    return rows


def check_admitted_layer(data, edl, timeline, admitted, frames_dir, ffmpeg) -> list:
    """The exact gates on every frame an admitted page drew. Returns the advice rows (`[]` for none)."""
    w, h = edl["size"]
    rows = admitted_ranges(data, timeline, admitted, edl["out_frames"])
    found = []
    for prefix in ("beat", "cap"):
        mine = [r for r in rows if r["prefix"] == prefix]
        if mine:
            found = _advice.merge(found, _alpha_gate.check_layer(frames_dir, mine, w, h, ffmpeg, prefix))
    return found


def load_clips(files: dict, sha256s: dict, limits: dict, ffmpeg: str, ffprobe: str) -> dict:
    """{slot: {kind: "clip", data, sha256, container, width, height, seconds, fps, tint}} of the clips of a render (`files` is `_assets.split_clips`'s). Each is
    read as the form `asset-sheet` writes (`_assets.read_clip`: an MP4, its sha256 matched when one is given) and probed against the same checks as that
    output (`_media.probe_clip`, output mode: H.264, yuv420p, constant frame rate, within the caps, no audio and no other stream, ten seconds at most);
    `tint` is the predominant colour of its first frame (`_media.predominant`) or None."""
    out = {}
    for slot, (path, _demuxer) in sorted(files.items()):
        clip = _assets.read_clip(slot, path, sha256s, limits)
        facts = _media.probe_clip(ffprobe, path, "mov", slot, output=True)
        try:
            tint = _media.predominant(_media.first_frame_rgb(ffmpeg, path, "mov"))
        except _media.ToolError:
            raise Refusal("asset_corrupt", slot) from None
        clip.update(width=facts["width"], height=facts["height"], seconds=facts["seconds"], fps=facts["fps"], tint=tint)
        out[slot] = clip
    return out


def settle_clips(vocab: dict, data: dict, timeline: dict, assets: dict) -> None:
    """Check where each clip is used, and mark the entries that draw one (`entry["params_kind"] = {"asset": "clip"}`, which the page is told). Only an `oh:cutaway`
    draws a clip: any other block with a clip slot (`oh:screenshot`, `oh:pip`, a keyword card) is `asset_type` naming the slot; a cutaway whose look is a slide or a zoom
    (the beat's own, from a transition row, else the theme's) is `clip_transition`: the page draws no motion for a clip, and ffmpeg draws the other kinds. Run after the blocks are resolved (`entry["block"]` is set)."""
    for e in timeline["beats"]:
        for name in _slot_names(vocab, e):
            slot = e["params"][name]
            if assets[slot]["kind"] != "clip":
                continue
            if e["block"] != "oh:cutaway" or name != "asset":
                raise Refusal("asset_type", slot)
            if (e.get("transition") or data["presets"][e["preset"]]["looks"].get("transition")) in _edl.PAGE_TRANSITIONS:      # the beat's own look, else the theme's
                raise Refusal("clip_transition", slot)
            e["params_kind"] = {name: "clip"}
            e["clip_size"] = {"w": assets[slot]["width"], "h": assets[slot]["height"]}      # the page reports the box the compose draws


def clip_rows(data: dict, timeline: dict, assets: dict, colors=None) -> list:
    """The compose plan's `clips` rows (`_media.clip_filters`), one per clip cutaway of the timeline. The look is the page's: a clip whose ratio is at or under
    `glass_ratio_max` with `fit: cover` fills the frame (cover); any other is drawn whole over a blurred, tinted copy of itself (glass). The tint is the clip's
    predominant colour, else the theme's background colour (`colors`, the edit list's theme; the preset file's own when left out), as the page does."""
    rows = []
    for e in timeline["beats"]:
        if (e.get("params_kind") or {}).get("asset") != "clip":
            continue
        slot = e["params"]["asset"]
        a = assets[slot]
        looks = data["presets"][e["preset"]]["looks"]
        ratio = a["width"] / float(a["height"])
        ratio_max = float(looks.get("glass_ratio_max", 0.8))
        glass = ratio > 0 and not ((e["params"].get("fit") or "cover") == "cover" and ratio <= ratio_max) and looks.get("glass_blur_px") is not None
        row = {"asset": "assets/%s.%s" % (slot, _media.CLIP_EXT), "start_frame": e["start_frame"], "end_frame": e["end_frame"], "mode": "glass" if glass else "cover"}
        if glass:
            row.update(box=_media.glass_box(a["width"], a["height"]), radius=int(looks["glass_radius_px"]), blur=float(looks["glass_blur_px"]),
                       tint=a.get("tint") or (colors or data["theme"]["colors"])["bg"].lstrip("#").upper(), tint_alpha=float(looks["glass_tint_alpha"]))
        rows.append(row)
    return rows


def render(*, edl_path, beats_path, src, out, platform_path, vocabulary_path, asset_files, asset_sha256s, ffmpeg, ffprobe, browser,
           jobs=3, dry_run=False, time_limit=None, cover_out=None, cover_offset_ms=None, blocks_dir=None, blocks_sha256=None, fonts_directory=None,
           scratch=None, vendor=None, hf_registry=None, log=lambda m: None) -> dict:
    started = time.time()
    data, edl, beats, platform, vocab, allow = load_documents(edl_path, beats_path, platform_path, vocabulary_path, fonts_directory)
    docs = check_documents(data, edl, beats, platform, vocab, allow)
    limits = data["limits"]
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    advice = []                                          # what this render does past a default, reported and never refused (video P0b); the gates add theirs below

    # the recording is the one the edit list was made from
    facts = check_recording(ffprobe, src, edl, limits)

    # assets: every slot a beat uses has a file, and every file is used
    # (a slot used only by beats the timeline dropped is not loaded and not drawn: it is `assets_dropped`, V9b-3d)
    used, dropped_only = _edl.classify_slots(beats, timeline, vocab, asset_files)
    missing = sorted(used - set(asset_files))
    if missing:
        raise Refusal("asset_missing", missing[0])
    extra = sorted(set(asset_files) - used - dropped_only)
    if extra:
        raise Refusal("asset_unused", extra[0])
    picture_files, clip_files = _assets.split_clips({s: asset_files[s] for s in sorted(used)})
    assets = _frames.load_assets(picture_files, asset_sha256s, limits)
    assets.update(load_clips(clip_files, asset_sha256s, limits, ffmpeg, ffprobe))

    catalogue = _blocks.load_catalogue(blocks_dir or _blocks.BLOCKS_DIR, blocks_sha256)
    block_advice = []
    templates, names = _blocks.templates_for(catalogue, ENGINE, timeline, vocab, with_caption=bool(timeline["captions"]), advice=block_advice,
                                          caption_block=edl["captions"].get("block"))
    settle_clips(vocab, data, timeline, assets)
    tpl_serve, tpl_hashes = _frames.load_templates(names, catalogue["dir"]) if names else ({}, {})
    font_serve, fonts_used = _frames.load_fonts(edl["theme"]["fonts"], allow, limits["font_max_bytes"], fonts_directory)
    # the pips and splits settled now, so that the caption pieces and the bands the second contract's pages are built for are the ones the frames are drawn with
    # (`compose_plan` settles them again: the arithmetic is the same and changes nothing)
    _layout.pip_cards(data, timeline, assets, advice=advice)
    _layout.split_layouts(data, timeline, advice=advice)
    # the entries whose block runs on the second contract: their files read, edited, linted and proven before any frame is drawn
    admitted = admit_blocks(catalogue, timeline, data, edl, font_serve, vendor, hf_registry, None if dry_run else browser["path"])
    asset_serve = {"/assets/%s.%s" % (s, a["kind"]): (a["data"], _frames.ASSET_MIME[a["kind"]]) for s, a in assets.items() if a["kind"] != "clip"}
    serve = {}
    serve.update(tpl_serve)
    serve.update(font_serve)
    serve.update(asset_serve)
    serve.update(admitted["serve"])

    out_seconds = edl["out_frames"] / edl["fps"]
    limit = time_limit_for(data, out_seconds, time_limit)
    plan = compose_plan(data, edl, timeline, assets, platform, os.path.abspath(src))
    argv = _media.compose_argv(ffmpeg, plan)
    outdir = os.path.abspath(os.path.dirname(out) if out.endswith(".mp4") else out)
    _, jobs_list = _frames.frame_jobs(timeline, edl["out_frames"])
    estimate = scratch_estimate(len(jobs_list), limits, plan["max_bytes"])
    advice = _advice.merge(advice, docs.get("advice"), timeline.get("advice"), block_advice)
    summary = {"ok": True, "dry_run": bool(dry_run), "out_dir": outdir, "out_seconds": round(out_seconds, 3), "out_frames": edl["out_frames"],
               "frame_jobs": len(jobs_list), "jobs": jobs, "time_limit_seconds": limit, "layers": plan["layers"],
               "beats_drawn": [{"id": e["id"], "preset": e["preset"], "block": e["block"], "start_frame": e["start_frame"], "end_frame": e["end_frame"]} for e in timeline["beats"]],
               "beats_dropped": timeline["dropped"], **({"assets_dropped": sorted(dropped_only)} if dropped_only else {}), **({"beats_dropped_reasons": timeline["dropped_reasons"]} if timeline.get("dropped_reasons") else {}), "effects_dropped": timeline["effects_dropped"], **_transition_summary(timeline), "unmatched_beats": beats["unmatched"], "mentions": docs["mentions"],
               "fonts": fonts_used, "blocks": {**tpl_hashes, **{n: p["served_sha256"] for n, p in admitted["proofs"].items()}}, "blocks_sha256": catalogue["sha256"],
               "ffmpeg_argv": argv, "estimated_bytes": estimate, **({"hf_proofs": admitted["proofs"]} if admitted["proofs"] else {})}
    if advice:
        summary["advice"] = advice
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
            fd = os.open(os.path.join(work, "assets", "%s.%s" % (slot, _media.CLIP_EXT if a["kind"] == "clip" else a["kind"])), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(a["data"])
        font_urls = font_urls_of(data, edl, font_serve)
        frames_dir = os.path.join(work, "frames")
        layers, ffacts = _frames.draw_frames(
            data=data, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls=font_urls, assets=assets, browser=browser["path"],
            jobs_n=max(1, min(jobs, 8)), frames_dir=frames_dir, workdir=work, time_limit=max(5, int(deadline - time.time())),
            templates=templates, png_blank=blank_png, admitted=admitted if admitted["pages"] else None)
        timings["frames"] = round(time.time() - t0, 2)
        advice = _advice.merge(advice, ffacts.get("advice"))
        if admitted["pages"]:                      # the exact gates on every frame an admitted page drew, before anything is composed
            t0 = time.time()
            advice = _advice.merge(advice, check_admitted_layer(data, edl, timeline, admitted, frames_dir, ffmpeg))
            timings["gates"] = round(time.time() - t0, 2)
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
    if advice:       # only a render that went past a default has the key: any other answer is what it always was
        summary["advice"] = advice
    return summary


def _transition_summary(timeline: dict) -> dict:
    """`transitions_drawn` for the render's answer: only a render with a transition has the key (any other answer is what it always was)."""
    if not timeline.get("transitions"):
        return {}
    return {"transitions_drawn": [{"id": t["id"], "kind": t["kind"], "start_frame": t["start_frame"], "end_frame": t["end_frame"]} for t in timeline["transitions"]]}


def _slot_names(vocab, entry):
    from _vocab import slot_params
    return [n for n in slot_params(vocab, entry["preset"]) if n in entry["params"]]
