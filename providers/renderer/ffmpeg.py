#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Renderer provider (class renderer:video): cut a recording, draw HTML presets over it, compose a vertical video, in a container.

A class the runtime uses and no skill requires (providers/CONTRACT.md, decision VD2 of `docs/decisions/2026-11-07-v0-short-video-hyperframes.md`). The one implementation:
ffmpeg for the cut and the composition and a pinned headless Chrome for the overlay frames, drawn from HTML templates frame by
frame. No model is involved: the edit list is built by code from a transcript, and the beats come from the post file's script block.

Everything that reads a recording, a transcript or a post runs INSIDE a container (decision VD4), built from this folder's
Dockerfile by `build --confirmed`, a command the person starts (it downloads a base image, Debian packages and the browser). This
file is the host side: it checks the flags, stages the inputs into a private job folder, builds the `docker run` command (a test
names every limit of it), runs it, and reads what the container wrote, as untrusted. The image is run by the id `build` recorded.

Verbs (every verb prints one JSON object on stdout; diagnostics on stderr, the first line of a refusal is
`refused: <closed code> <field>`; the text of an input is never echoed):

  --check                  docker answering and local, the image built from this folder's definition and unchanged, and the tools
                           in it starting (versions printed). Exit 3 names what is missing and the command that fixes it.
  build (--dry-run | --confirmed) [--platform linux-arm64|linux64]
                           build the image. The one step that uses the network, at the person's word. Refuses while the browser's
                           archive has no pinned sha256 (run pin-browser first).
  pin-browser (--dry-run | --confirmed) [--platform P]
                           the maintainer's one-time step: download the browser archive of the architecture, check its size and
                           md5 against the official bucket's published values, record its sha256 in browser-pin.json.
  reap                     remove containers and job folders a killed run left behind (every run does it at its start too).
  analyse --in VIDEO [--out F] [--noise-db -35] [--min-silence 0.25]
        ffprobe facts, the recording's sha256 and silencedetect intervals.
  base --transcript T --analysis A --out EDL [--fps 30] [--pad-head 0.10] [--pad-tail 0.14] [--long-cut 2] [--wordless-max 0.3] [--caption-position bottom|center]
       [--face-box X,Y,W,H] [--zoom alternate|none] [--zoom-factor 1.1] [--push-in 0.02] [--zoom-anchor-y 0.25] [--retakes auto|propose]
       [--confirm RETAKE-ID]... [--keep RETAKE-ID]...
       [--color TOKEN=#RRGGBB]... [--font ROLE=ID[:WEIGHT]]...
        The code-generated base edit list. Silence is the cut signal (the words only protect speech) and no range is kept shorter
        than 0.4 s; captions come in chunks of one to three words; every second range is drawn zoomed on the face box. Retakes found
        by rule are written into the list as proposals, each with a default (cut or keep) and a reason; with --retakes auto (the default) the
        ones whose default is cut are cut, except those named with --keep, and --confirm cuts one more; with --retakes propose only --confirm cuts.
  align --post FILE --transcript T --checker SCRIPT --vocabulary V --out BEATS [--threshold 0.6] [--empty-slot SLOT=keyword|none]...
        [--anchor BEAT=WORD_FROM-WORD_TO]... [--edl EDL]
        Runs the post-writing skill's own script checker (an isolated subprocess, inside the container) and refuses a post it does
        not pass; aligns each beat's spoken line to word indices; writes beats.json with scores and the unmatched beats.
  check --edl EDL --beats BEATS --vocabulary V [--platform-file F]
        Schema, bounds, text hardening, colours and fonts, credential shapes. Exit 1 and the closed code when refused.
  render --edl EDL --beats BEATS --in VIDEO --out DIR --platform-file F --vocabulary V [--asset SLOT=FILE]...
         [--asset-sha256 SLOT=HEX]... [--jobs 3] [--dry-run] [--time-limit S] [--cover-out PNG --cover-offset-ms N]
        Writes DIR/render-<sha12>.mp4 (mode 0400, never rewritten) and prints its sha256, bytes and seconds. `--out` may name a path
        ending in .mp4: its folder is used, the file name is always content-addressed. --dry-run prints the exact docker command.
  storyboard (--post FILE --checker SCRIPT | --beat FILE) --vocabulary V --out DIR [--face-box X,Y,W,H] [--color TOKEN=#RRGGBB]... [--font ROLE=ID[:WEIGHT]]...
        What a script's beats will look like, before any recording: DIR/beat-<n>.png (the beat's overlay at rest, over a flat neutral
        picture; a layout's asset is a flat colour) for each beat that has a preset, and DIR/sheet.png, a grid of them with no text. No
        recording and no transcript go in: the beats' lines become synthetic words at 2.5 words a second and the render's own checks
        (the checker, `check_edl`, `check_beats` with the credential scan) run before a frame is drawn; only those frames are drawn.
        `--beat` takes one beat as JSON ({preset, params, line}) and gives the same still as the post it came from.
  cover --in MP4 --offset-ms N --out PNG
        One frame of a render.
  still --in VIDEO --at-ms N --out DIR
        One PNG frame of a recording at N ms, framed exactly as the render frames the source into 1080x1920 (the same scale and crop, so
        a pixel of the still is a pixel of the render's unzoomed picture). Writes DIR/still-<sha12>.png (mode 0400, never rewritten) and
        prints its sha256, size and offset. The recording is read under the same rules as `analyse` and `render`.
  preview --in MP4 [--sha256 HEX] --out DIR
        A smaller copy of a finished render for a phone: 720x1280 H.264 at a rate capped from the render's length, AAC 96 kbit/s, at
        most 15 MiB (renderer-presets.json `preview`), as long as the render, its index first. Writes DIR/preview-<sha12>.mp4 (mode
        0400, never rewritten) and prints its sha256, the render's (`from_sha256`), bytes, size, duration and rates. One encoder
        thread: the same render gives the same bytes whatever the cores.
  pin-blocks --confirmed
        Maintainer tool: after a reviewed change of a block, rewrite blocks/pins.json and the generated blocks/catalogue.json.
  block-params --block NAME --params FILE --vocabulary V
        The renderer-side checker (VD15): one block's parameters (a JSON object) against its block.json or allowlist entry, on the
        host (it reads no recording, transcript or post). Prints the block, the engine and the parameter names, never their text.

Container limits, for analyse, base, align, check, render, cover and still: --memory-mb (default 6144, at least 3072), --cpus (default 8,
never more than the daemon has), --scratch-mb (default 2048, memory-backed, and at most the memory less 2048: a larger one is refused,
never an out-of-memory kill), --timeout (seconds).

`render` checks its own result in a second, fresh container of the same image (the render mounted read-only, no network): ffprobe
facts against the platform's spec, the colour tags, the length and the sha256. The file is given its name only after that passes. The blocks it draws are copied from blocks/ into the job's read-only folder, hashed there and
checked again inside; the result names them (`blocks`, `blocks_sha256`), and a beat that names a block this engine cannot draw is
refused as `block_not_on_engine`, naming the engine's own block.

The browser's own sandbox is off inside the image, where the container is the boundary (Dockerfile, "The browser's sandbox");
every render says `browser_sandbox`. Output choices: 1080x1920 at 30 fps whatever the input (a 4K 60 fps HEVC iPhone clip is scaled
down and its frame rate halved; a landscape clip is cropped to the centre), H.264 high profile with AAC, bt709 limited range,
metadata stripped.

exit codes: 0 ok, 1 refused or failed, 2 usage error, 3 not configured (docker, the image, the pin).
Standard library only; no network except `build --confirmed` and `pin-browser --confirmed`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil  # noqa: F401  (the tests reach the host's `shutil` through this module)
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _assets  # noqa: E402
import _blocks  # noqa: E402
import _browser  # noqa: E402
import _docker as D  # noqa: E402
import _frames  # noqa: E402
import _media  # noqa: E402
import _render  # noqa: E402
from _browser import NotConfigured  # noqa: E402
from _host import (COMMON_HANDLERS, COVER_MAX_BYTES, CRASH_CODES, MAX_RECORDING_BYTES, MAX_SMALL_FILE, STILL_MAX_BYTES, Job, Usage,  # noqa: E402,F401
                   add_common_parsers, add_limits, emit, finish_render, opt, stage_blocks, verb_align, verb_analyse, verb_base,
                   verb_check_documents, verb_cover, verb_still, verb_verify)
from _host import verb_block_params as host_block_params  # noqa: E402
from _text import Refusal  # noqa: E402
from _vocab import SLOT_ID, load_data  # noqa: E402

ENGINE = "ffmpeg"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
HINTS = {
    "docker_missing": "install Docker and start it (the renderer runs in a container)",
    "docker_not_answering": "start the Docker daemon",
    "docker_daemon_not_local": "use a local Docker daemon: a recording must not cross a network",
    "image_not_built": "run: " + D.BUILD_COMMAND,
    "image_stale": "the image is older than the files in providers/renderer/: run: " + D.BUILD_COMMAND,
    "image_not_recorded": "the tag does not point at the image `build` recorded: `docker image rm` it and run: " + D.BUILD_COMMAND,
    "edl_schema_outdated": "the edit list is version 1 (no zoom.anchor_y): make it again with `base`, which writes version 2",
    "pin_incomplete": "run once: python3 providers/renderer/ffmpeg.py pin-browser --confirmed (then commit browser-pin.json)",
}


def pairs(items, field: str) -> dict:
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key or not value or key in out:
            raise Usage("%s takes KEY=VALUE, once per key" % field)
        out[key] = value
    return out


def slot_key(key: str) -> str:
    """A beat number is read as the slot id `beat<N>` the alignment gives it."""
    return "beat%s" % key if key.isdigit() else key


# ---------------------------------------------------------------- the verbs

def verb_check(args) -> dict:
    server = D.require_docker()
    image = D.check_image()
    out = {"ok": True, "docker_server": server, "image": image, "daemon": D.daemon_facts()}
    with Job(args, 120, "selfcheck") as job:
        out["selfcheck"] = job.run(["selfcheck"], "selfcheck")
    out["browser_sandbox"] = "off: the container is the boundary" if out["selfcheck"].get("container") else "on"
    return out


def platform_of(args) -> str:
    if args.platform:
        return args.platform
    return _browser.platform_for(D.daemon_facts()["architecture"])


def verb_build(args) -> dict:
    if not args.confirmed and not args.dry_run:
        raise Usage("build downloads a base image, packages and the browser and writes a local image: it needs --confirmed (or --dry-run). A person starts it, never a run.")
    return D.build(_browser.load_pin(), platform_of(args), args.confirmed, args.dry_run)


def verb_pin_browser(args) -> dict:
    if not args.confirmed and not args.dry_run:
        raise Usage("pin-browser downloads the browser archive once: it needs --confirmed (or --dry-run).")
    return _browser.pin_browser(platform_of(args), test_mode=os.environ.get("RENDERER_TEST") == "1", dry_run=args.dry_run)


def verb_reap(args) -> dict:
    D.require_docker()
    return {"ok": True, "containers_removed": D.reap_containers(), "folders_removed": D.reap_folders()}


def verb_pin_blocks(args) -> dict:
    if not args.confirmed:
        raise Usage("pin-blocks needs --confirmed")
    files = _blocks.write_pins()
    return {"ok": True, "files": len(files), "blocks_sha256": _blocks.write_catalogue()}


def verb_block_params(args) -> dict:
    return host_block_params(args, ENGINE)


def verb_render(args) -> dict:
    asset_files = {slot_key(k): v for k, v in pairs(args.asset, "--asset").items()}
    asset_hashes = {slot_key(k): v for k, v in pairs(args.asset_sha256, "--asset-sha256").items()}
    if (args.cover_out is None) != (args.cover_offset_ms is None):
        raise Usage("--cover-out and --cover-offset-ms go together")
    out_dir = os.path.abspath(os.path.dirname(args.out) if args.out.endswith(".mp4") else args.out)
    data = load_data()
    try:
        edl_doc = json.loads(_assets.read_regular(args.edl, data["limits"]["json_max_bytes"], "input_unreadable", "edl").decode("utf-8"))
        out_frames, fps = edl_doc["out_frames"], edl_doc["fps"]
        platform = json.loads(_assets.read_regular(args.platform_file, MAX_SMALL_FILE, "input_unreadable", "platform").decode("utf-8"))
        limit = _render.time_limit_for(data, out_frames / float(fps), args.time_limit)
        byte_cap = min(D.MAX_OUT_BYTES, _media.byte_limit(platform))
    except (Refusal, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
        raise Refusal("edl_unreadable", "edl") from None
    with Job(args, limit + 60, "render") as job:
        inner = ["render", "--edl", job.stage("edl.json", args.edl), "--beats", job.stage("beats.json", args.beats),
                 "--in", job.mount_recording(args.input), "--out", D.MOUNT_OUT, "--scratch", D.MOUNT_SCRATCH,
                 "--platform-file", job.stage("platform.json", args.platform_file), "--vocabulary", job.stage("vocabulary.json", args.vocabulary),
                 "--jobs", str(max(1, min(args.jobs, 2 * max(1, job.limits()[0])))), "--time-limit", str(limit)]
        blocks_args = stage_blocks(job)
        inner += blocks_args
        for slot, path in sorted(asset_files.items()):
            if not SLOT_ID.fullmatch(slot):
                raise Refusal("bad_slot", slot[:32])
            inner += ["--asset", "%s=%s" % (slot, job.stage("assets/" + slot, path, data["limits"]["asset_max_bytes"]))]
        for slot, digest in sorted(asset_hashes.items()):
            inner += ["--asset-sha256", "%s=%s" % (slot, digest)]
        if args.cover_out:
            inner += ["--cover-out", D.MOUNT_OUT + "/cover.png", "--cover-offset-ms", str(args.cover_offset_ms)]
        if args.dry_run:
            name, timeout, argv = job.argv(inner)
            return {"ok": True, "dry_run": True, "command": argv, "image": job.image, "time_limit_seconds": limit, "out_dir": out_dir}
        result = job.run(inner, "render")
        if result.get("blocks_sha256") != blocks_args[-1]:
            raise Refusal("container_result_invalid", "blocks")
        result = finish_render(args, job, result, out_dir=out_dir, byte_cap=byte_cap, out_seconds=out_frames / float(fps))
        if args.cover_out:
            job.collect("cover.png", args.cover_out, max_bytes=COVER_MAX_BYTES)
            result["cover"] = dict(result.get("cover") or {}, path=os.path.abspath(args.cover_out))
        return result


STILL_NAME = re.compile(r"beat-[0-9]{1,2}\.png|sheet\.png")


STORYBOARD_MAX_PIXELS = 16 * 1000 * 1000      # a fixed ceiling on any one PNG the container names, whatever its header says


def storyboard_files(result: dict, data: dict) -> list:
    """[(file name, sha256, (width, height))] the container may hand over, from what it reported, trusting none of it: every key must be
    there (`container_result_invalid` otherwise), a still's name must be `beat-<its beat>.png` and its size the frame's, the sheet's size
    the grid the presets give for that many tiles (never its own declaration), and every size within a fixed ceiling."""
    bad = Refusal("container_result_invalid", "storyboard")
    beats, sheet = result.get("beats"), result.get("sheet")
    if not isinstance(beats, list) or not beats or not isinstance(sheet, dict):
        raise bad
    frame = (data["frame"]["width"], data["frame"]["height"])
    wanted, seen = [], set()
    for b in beats:
        number = b.get("beat") if isinstance(b, dict) else None
        name, digest = (b.get("file"), b.get("sha256")) if isinstance(b, dict) else (None, None)
        if not isinstance(number, int) or isinstance(number, bool) or number < 1 or number in seen or name != "beat-%d.png" % number \
                or not STILL_NAME.fullmatch(name) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise bad
        seen.add(number)
        wanted.append((name, digest, frame))
    cfg = data["storyboard"]["sheet"]
    cols = max(1, min(len(beats), cfg["columns"]))
    rows = -(-len(beats) // cols)
    size = (cols * (cfg["tile_width"] + cfg["gap"]), rows * (cfg["tile_height"] + cfg["gap"]))
    digest = sheet.get("sha256")
    if sheet.get("file") != "sheet.png" or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) \
            or (sheet.get("width"), sheet.get("height")) != size or sheet.get("tiles") != len(beats) or sheet.get("columns") != cols:
        raise bad
    wanted.append(("sheet.png", digest, size))
    if any(w * h > STORYBOARD_MAX_PIXELS for _, _, (w, h) in wanted):
        raise bad
    return wanted


def verb_storyboard(args) -> dict:
    """A still per beat and a contact sheet. The container gets no recording and no transcript (two mounts: the staged job folder
    read-only and the output folder); the host reads each PNG as untrusted: size-capped, hashed, its header checked, then named."""
    if bool(args.post) == bool(args.beat) or bool(args.post) != bool(args.checker):
        raise Usage("storyboard takes --post FILE with --checker SCRIPT, or --beat FILE, not both")
    with Job(args, 240, "storyboard") as job:
        job.max_entries = D.STORYBOARD_OUT_ENTRIES
        inner = ["storyboard", "--vocabulary", job.stage("vocabulary.json", args.vocabulary), "--out", D.MOUNT_OUT, "--scratch", D.MOUNT_SCRATCH,
                 "--jobs", str(max(1, min(args.jobs, 2 * max(1, job.limits()[0]))))]
        blocks_args = stage_blocks(job)
        inner += blocks_args
        if args.post:
            inner += ["--post", job.stage("post.md", args.post, 2 * 1024 * 1024), "--checker", job.stage("check_script.py", args.checker, 1024 * 1024)]
        else:
            inner += ["--beat", job.stage("beat.json", args.beat)]
        inner += opt("--face-box", args.face_box)
        for flag, values in (("--color", args.color), ("--font", args.font)):
            for v in values or []:
                inner += [flag, v]
        result = job.run(inner, "storyboard")
        if result.get("blocks_sha256") != blocks_args[-1]:
            raise Refusal("container_result_invalid", "blocks")
        out_dir = os.path.abspath(args.out)
        wanted = storyboard_files(result, load_data())
        candidates = os.path.join(job.root, "candidates")
        os.mkdir(candidates, 0o700)
        for name, digest, size in wanted:
            if not STILL_NAME.fullmatch(name) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise Refusal("container_result_invalid", "storyboard")
            job.collect(name, os.path.join(candidates, name), max_bytes=STILL_MAX_BYTES, expect_sha256=digest)
            facts = _frames.image_facts(_assets.read_regular(os.path.join(candidates, name), STILL_MAX_BYTES, "container_file_unreadable", name[:40]))
            if facts is None or facts[0] != "png" or (facts[1], facts[2]) != size:
                raise Refusal("container_file_not_png", name[:40])
        os.makedirs(out_dir, mode=0o700, exist_ok=True)
        replayed = True
        for name, digest, _ in wanted:
            outcome = D.copy_out(os.path.join(candidates, name), os.path.join(out_dir, name), max_bytes=STILL_MAX_BYTES, mode=0o400, expect_sha256=digest, exclusive=True)
            replayed = replayed and outcome == "replayed"
        return dict(result, out_dir=out_dir, replayed=replayed, image={"id": job.image["id"], "tag": job.image["tag"]})


# ---------------------------------------------------------------- command line

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb")
    sp = sub.add_parser("build")
    sp.add_argument("--confirmed", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--platform", choices=("linux-arm64", "linux64"))
    sp = sub.add_parser("pin-browser")
    sp.add_argument("--confirmed", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--platform", choices=("linux-arm64", "linux64"))
    sub.add_parser("reap")
    sp = sub.add_parser("pin-blocks")
    sp.add_argument("--confirmed", action="store_true")
    sp = sub.add_parser("block-params")
    sp.add_argument("--block", required=True, help="a block name, oh:<name> or hf:<name>")
    sp.add_argument("--params", required=True, help="a JSON file holding one object: the block's parameters")
    sp.add_argument("--vocabulary", required=True, help="shared/references/video-presets.json")
    add_common_parsers(sub)
    sp = sub.add_parser("render")
    add_limits(sp)
    sp.add_argument("--edl", required=True)
    sp.add_argument("--beats", required=True)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--platform-file", required=True)
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--asset", action="append", metavar="SLOT=FILE")
    sp.add_argument("--asset-sha256", action="append", metavar="SLOT=HEX")
    sp.add_argument("--jobs", type=int, default=3)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--time-limit", type=int)
    sp.add_argument("--cover-out")
    sp.add_argument("--cover-offset-ms", type=int)
    sp = sub.add_parser("storyboard")
    add_limits(sp)
    sp.add_argument("--post")
    sp.add_argument("--checker", help="the post-writing skill's script checker (check_script.py), with --post")
    sp.add_argument("--beat", help="one beat as JSON: {preset, params, line}")
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--out", required=True, help="the folder that gets beat-<n>.png and sheet.png")
    sp.add_argument("--jobs", type=int, default=3)
    sp.add_argument("--face-box", help="X,Y,W,H in frame pixels (1080x1920); the default face box otherwise")
    sp.add_argument("--color", action="append", metavar="TOKEN=#RRGGBB")
    sp.add_argument("--font", action="append", metavar="ROLE=ID[:WEIGHT]")
    return p


VERBS = {"build": verb_build, "pin-browser": verb_pin_browser, "reap": verb_reap, "pin-blocks": verb_pin_blocks,
         "block-params": verb_block_params, "render": verb_render, "storyboard": verb_storyboard, **COMMON_HANDLERS}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "--check":
            if len(argv) != 1:
                raise Usage("--check takes no other flag")
            ns = argparse.Namespace(memory_mb=D.DEFAULT_MEMORY_MB, cpus=D.DEFAULT_CPUS, scratch_mb=D.DEFAULT_SCRATCH_MB, timeout=None)
            result = verb_check(ns)
        else:
            args = parser().parse_args(argv)
            if args.verb is None:
                parser().print_help(sys.stderr)
                return EXIT_USAGE
            result = VERBS[args.verb](args)
        emit(result)
        return EXIT_OK
    except SystemExit as err:
        return EXIT_USAGE if err.code else EXIT_OK
    except Usage as err:
        print("usage: %s" % err, file=sys.stderr)
        return EXIT_USAGE
    except Refusal as err:
        print("refused: %s %s" % (err.code, err.field), file=sys.stderr)
        if err.code in HINTS:
            print("  " + HINTS[err.code], file=sys.stderr)
        for p in getattr(err, "problems", []):
            print("  beat %s %s %s" % (p.get("beat"), p.get("field"), p.get("code")), file=sys.stderr)
        if err.code == "bad_mount_path":
            return EXIT_USAGE
        failure = {"ok": False, "code": err.code, "field": err.field, "problems": getattr(err, "problems", [])}
        if getattr(err, "reason", ""):
            print("  reason: %s" % err.reason, file=sys.stderr)
            failure["reason"] = err.reason                  # already through the closed schema: one short plain line
        emit(failure)
        return EXIT_NOT_CONFIGURED if isinstance(err, NotConfigured) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
