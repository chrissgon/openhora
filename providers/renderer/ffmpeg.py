#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Renderer provider (class renderer:video): cut a recording, draw HTML presets over it, compose a vertical video, in a container.

A class the runtime uses and no skill requires (providers/CONTRACT.md, decision D11 of the short-video plan). The one implementation:
ffmpeg for the cut and the composition and a pinned headless Chrome for the overlay frames, drawn from HTML templates frame by
frame. No model is involved: the edit list is built by code from a transcript, and the beats come from the post file's script block.

Everything that reads a recording, a transcript or a post runs INSIDE a container (decision D22), built from this folder's
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
       [--face-box X,Y,W,H] [--zoom alternate|none] [--zoom-factor 1.1] [--push-in 0.02] [--zoom-anchor-y 0.25] [--confirm RETAKE-ID]...
       [--color TOKEN=#RRGGBB]... [--font ROLE=ID[:WEIGHT]]...
        The code-generated base edit list. Silence is the cut signal (the words only protect speech) and no range is kept shorter
        than 0.4 s; captions come in chunks of one to three words; every second range is drawn zoomed on the face box. Retakes found
        by rule are written into the list as proposals, none applied: only the ones named with --confirm are cut.
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
  cover --in MP4 --offset-ms N --out PNG
        One frame of a render.
  pin-templates --confirmed
        Maintainer tool: rewrite templates/pins.json after a reviewed template change.

Container limits, for analyse, base, align, check, render and cover: --memory-mb (default 6144, at least 3072), --cpus (default 8,
never more than the daemon has), --scratch-mb (default 2048, memory-backed, and at most the memory less 2048: a larger one is refused,
never an out-of-memory kill), --timeout (seconds).

`render` checks its own result in a second, fresh container of the same image (the render mounted read-only, no network): ffprobe
facts against the platform's spec, the colour tags, the length and the sha256. The file is given its name only after that passes.

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
import shutil
import stat
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _browser  # noqa: E402
import _docker as D  # noqa: E402
import _frames  # noqa: E402
import _media  # noqa: E402
import _render  # noqa: E402
from _browser import NotConfigured  # noqa: E402
from _text import Refusal  # noqa: E402
from _vocab import SLOT_ID, load_data  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
MAX_RECORDING_BYTES = 1 << 30
MAX_SMALL_FILE = 5 * 1024 * 1024
COVER_MAX_BYTES = 16 * 1024 * 1024
CRASH_CODES = {125: "docker_run_failed", 126: "docker_run_failed", 127: "docker_run_failed", 137: "container_killed", 143: "container_killed"}
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


class Usage(Exception):
    pass


def emit(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


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


# ---------------------------------------------------------------- one job: stage, run, collect

class Job:
    """A private folder `.job-<id>` under the work folder: `in/` is mounted read-only at /job, `out/` read-write at /out. The
    inputs are copied in through safe reads with size caps; nothing of the person's folders is mounted but the recording."""

    def __init__(self, args, timeout: float, verb: str):
        self.args, self.timeout, self.verb = args, timeout, verb
        self.recording = None
        self.staged = {}

    def __enter__(self):
        D.require_docker()
        self.image = D.check_image()
        self.facts = D.daemon_facts()
        try:
            D.reap_containers()
            D.reap_folders()
        except Refusal:
            pass
        self.root = os.path.join(D.work_root(), "%s%s" % (D.JOB_PREFIX, uuid.uuid4().hex[:12]))
        os.mkdir(self.root, 0o700)
        self.in_dir, self.out_dir = os.path.join(self.root, "in"), os.path.join(self.root, "out")
        os.mkdir(self.in_dir, 0o700)
        os.mkdir(self.out_dir, 0o700)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)

    def stage(self, name: str, path: str, limit: int = MAX_SMALL_FILE) -> str:
        """Copy a file into the job's read-only folder; returns its path inside the container."""
        if name in self.staged or not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,80}", name) or ".." in name:
            raise Refusal("bad_staged_name", name[:40])
        data = _frames.read_regular(path, limit, "input_unreadable", os.path.basename(name)[:40])
        target = os.path.join(self.in_dir, name)
        os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        self.staged[name] = target
        return "%s/%s" % (D.MOUNT_JOB, name)

    def mount_recording(self, path: str) -> str:
        """The recording is mounted read-only where it is: a real file (not a link), under the size cap."""
        try:
            found = os.lstat(path)
        except OSError:
            raise Refusal("input_unreadable", "recording") from None
        if not stat.S_ISREG(found.st_mode) or found.st_size > MAX_RECORDING_BYTES:
            raise Refusal("input_unreadable", "recording")
        self.recording = os.path.abspath(path)
        D.mount_path(self.recording, "recording")
        return D.MOUNT_RECORDING

    def limits(self):
        a = self.args
        cpus = max(1, min(a.cpus, self.facts["cpus"]))
        memory = max(D.MIN_MEMORY_MB, min(D.MAX_MEMORY_MB, a.memory_mb))
        scratch = max(64, min(D.MAX_SCRATCH_MB, a.scratch_mb))
        if scratch > memory - D.MEMORY_MARGIN_MB:       # a memory-backed scratch counts against the memory limit: refuse, never an OOM kill
            raise Refusal("scratch_exceeds_memory", "scratch-mb")
        timeout = max(30, min(D.MAX_TIMEOUT, a.timeout if a.timeout else self.timeout))
        return cpus, memory, scratch, int(timeout)

    def argv(self, inner_args: list):
        cpus, memory, scratch, timeout = self.limits()
        name = "openhora-renderer-%s" % uuid.uuid4().hex[:12]
        deadline = int(time.time()) + timeout + D.STOP_GRACE
        return name, timeout, D.container_argv(name, self.image["id"], ["--result", D.MOUNT_OUT + "/result.json"] + inner_args,
                                              job_dir=self.in_dir, out_dir=self.out_dir, recording=self.recording, memory_mb=memory,
                                              cpus=cpus, scratch_mb=scratch, deadline=deadline)

    def run(self, inner_args: list, schema: str) -> dict:
        """Run the container and return the verb's result object, rebuilt from the closed schema `schema` (what the container wrote to
        /out/result.json, validated: only understood fields survive). A refusal inside becomes the same Refusal here; a container
        that died without a result is a closed failure. Nothing the container wrote to its stderr is printed."""
        if shutil.disk_usage(self.root).free < D.MAX_OUT_BYTES + 64 * 1024 * 1024:
            raise Refusal("no_space", "output")
        name, timeout, argv = self.argv(inner_args)
        rc, _stderr = D.run_container(argv, name, timeout + D.STOP_GRACE)
        D.check_out_folder(self.out_dir)
        try:
            raw = D.read_regular(os.path.join(self.out_dir, "result.json"), D.MAX_RESULT_BYTES, "result.json")
            result = json.loads(raw.decode("utf-8"))
            assert isinstance(result, dict)
        except (Refusal, ValueError, AssertionError, UnicodeDecodeError, RecursionError):
            raise Refusal(CRASH_CODES.get(rc, "container_failed"), "container") from None
        if rc == 0 and result.get("ok", True) is not False:
            return D.sanitise(result, D.RESULT_SCHEMAS[schema], schema)
        code, field = str(result.get("code", "")), str(result.get("field", ""))
        err_cls = NotConfigured if rc == 3 else Refusal
        err = err_cls(code if D.CODE.fullmatch(code) else "container_failed", field if D.FIELD.fullmatch(field) else "")
        try:
            err.problems = D.sanitise(result.get("problems") or [], D.PROBLEMS, "problems")
        except Refusal:
            err.problems = []
        try:
            err.reason = D.sanitise(result.get("reason") or "", D.S, "reason")
        except Refusal:
            err.reason = ""
        raise err

    def collect(self, name: str, dest: str, *, max_bytes: int, mode: int = 0o600, expect_sha256=None, exclusive=False) -> str:
        return D.copy_out(os.path.join(self.out_dir, name), dest, max_bytes=max_bytes, mode=mode, expect_sha256=expect_sha256, exclusive=exclusive)


def add_limits(sp):
    sp.add_argument("--memory-mb", type=int, default=D.DEFAULT_MEMORY_MB)
    sp.add_argument("--cpus", type=int, default=D.DEFAULT_CPUS)
    sp.add_argument("--scratch-mb", type=int, default=D.DEFAULT_SCRATCH_MB)
    sp.add_argument("--timeout", type=int, help="seconds before the container is removed")


def opt(flag, value):
    return [] if value is None else [flag, str(value)]


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


def verb_pin_templates(args) -> dict:
    if not args.confirmed:
        raise Usage("pin-templates needs --confirmed")
    return {"ok": True, "pins": _frames.write_pins()}


def verb_analyse(args) -> dict:
    with Job(args, 900, "analyse") as job:
        rec = job.mount_recording(args.input)
        result = job.run(["analyse", "--in", rec, "--out", D.MOUNT_OUT + "/analysis.json", "--noise-db", str(args.noise_db),
                          "--min-silence", str(args.min_silence)], "analyse")
        if args.out:
            job.collect("analysis.json", args.out, max_bytes=D.MAX_RESULT_BYTES)
            return dict(result, out=os.path.abspath(args.out))
        try:
            doc = json.loads(D.read_regular(os.path.join(job.out_dir, "analysis.json"), D.MAX_RESULT_BYTES, "analysis.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise Refusal("container_result_invalid", "analysis.json") from None
        return dict(D.sanitise(doc, D.RESULT_SCHEMAS["analysis_doc"], "analysis"), ok=True)


def verb_base(args) -> dict:
    with Job(args, 120, "base") as job:
        inner = ["base", "--transcript", job.stage("transcript.json", args.transcript), "--analysis", job.stage("analysis.json", args.analysis),
                 "--out", D.MOUNT_OUT + "/edl.json", "--caption-position", args.caption_position]
        inner += opt("--push-in", args.push_in) + opt("--zoom-anchor-y", args.zoom_anchor_y)
        inner += opt("--fps", args.fps) + opt("--gap", args.gap) + opt("--pad-head", args.pad_head) + opt("--pad-tail", args.pad_tail) + opt("--face-box", args.face_box)
        inner += opt("--long-cut", args.long_cut) + opt("--wordless-max", args.wordless_max)
        inner += opt("--zoom", args.zoom) + opt("--zoom-factor", args.zoom_factor)
        for flag, values in (("--confirm", args.confirm), ("--color", args.color), ("--font", args.font)):
            for v in values or []:
                inner += [flag, v]
        result = job.run(inner, "base")
        job.collect("edl.json", args.out, max_bytes=D.MAX_RESULT_BYTES)
        return dict(result, out=os.path.abspath(args.out))


def verb_align(args) -> dict:
    with Job(args, 120, "align") as job:
        inner = ["align", "--post", job.stage("post.md", args.post, 2 * 1024 * 1024), "--transcript", job.stage("transcript.json", args.transcript),
                 "--checker", job.stage("check_script.py", args.checker, 1024 * 1024), "--vocabulary", job.stage("vocabulary.json", args.vocabulary),
                 "--out", D.MOUNT_OUT + "/beats.json", "--threshold", str(args.threshold)]
        if args.edl:
            inner += ["--edl", job.stage("edl.json", args.edl)]
        for flag, values in (("--empty-slot", args.empty_slot), ("--anchor", args.anchor)):
            for v in values or []:
                inner += [flag, v]
        result = job.run(inner, "align")
        job.collect("beats.json", args.out, max_bytes=D.MAX_RESULT_BYTES)
        return dict(result, out=os.path.abspath(args.out))


def verb_check_documents(args) -> dict:
    with Job(args, 120, "check") as job:
        inner = ["check", "--edl", job.stage("edl.json", args.edl), "--beats", job.stage("beats.json", args.beats),
                 "--vocabulary", job.stage("vocabulary.json", args.vocabulary)]
        if args.platform_file:
            inner += ["--platform-file", job.stage("platform.json", args.platform_file)]
        return job.run(inner, "check")


def verb_render(args) -> dict:
    asset_files = {slot_key(k): v for k, v in pairs(args.asset, "--asset").items()}
    asset_hashes = {slot_key(k): v for k, v in pairs(args.asset_sha256, "--asset-sha256").items()}
    if (args.cover_out is None) != (args.cover_offset_ms is None):
        raise Usage("--cover-out and --cover-offset-ms go together")
    out_dir = os.path.abspath(os.path.dirname(args.out) if args.out.endswith(".mp4") else args.out)
    data = load_data()
    try:
        edl_doc = json.loads(_frames.read_regular(args.edl, data["limits"]["json_max_bytes"], "input_unreadable", "edl").decode("utf-8"))
        out_frames, fps = edl_doc["out_frames"], edl_doc["fps"]
        platform = json.loads(_frames.read_regular(args.platform_file, MAX_SMALL_FILE, "input_unreadable", "platform").decode("utf-8"))
        limit = _render.time_limit_for(data, out_frames / float(fps), args.time_limit)
        byte_cap = min(D.MAX_OUT_BYTES, _media.byte_limit(platform))
    except (Refusal, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
        raise Refusal("edl_unreadable", "edl") from None
    with Job(args, limit + 60, "render") as job:
        inner = ["render", "--edl", job.stage("edl.json", args.edl), "--beats", job.stage("beats.json", args.beats),
                 "--in", job.mount_recording(args.input), "--out", D.MOUNT_OUT, "--scratch", D.MOUNT_SCRATCH,
                 "--platform-file", job.stage("platform.json", args.platform_file), "--vocabulary", job.stage("vocabulary.json", args.vocabulary),
                 "--jobs", str(max(1, min(args.jobs, 2 * max(1, job.limits()[0])))), "--time-limit", str(limit)]
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
        digest = result.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Refusal("container_result_invalid", "render")
        name = "render-%s.mp4" % digest[:12]
        # The candidate leaves the container that made it only into a private file, hashed on the way, and is checked in a
        # fresh container before it is given its name: a render that fails its own platform's spec is never stored.
        candidate = os.path.join(job.root, "candidate.mp4")
        job.collect(name, candidate, max_bytes=byte_cap, mode=0o400, expect_sha256=digest)
        with Job(args, 300, "verify") as checker:
            verdict = checker.run(["verify", "--in", checker.mount_recording(candidate), "--platform-file", checker.stage("platform.json", args.platform_file),
                                   "--sha256", digest, "--expect-seconds", "%.3f" % (out_frames / float(fps))], "verify")
        final = os.path.join(out_dir, name)
        os.makedirs(out_dir, mode=0o700, exist_ok=True)
        outcome = D.copy_out(candidate, final, max_bytes=byte_cap, mode=0o400, expect_sha256=digest, exclusive=True)
        result.update(path=final, bytes=verdict["output"]["bytes"], output=verdict["output"], replayed=(outcome == "replayed"), verified=True,
                      image={"id": job.image["id"], "tag": job.image["tag"]})
        if args.cover_out:
            job.collect("cover.png", args.cover_out, max_bytes=COVER_MAX_BYTES)
            result["cover"] = dict(result.get("cover") or {}, path=os.path.abspath(args.cover_out))
        return result


def verb_cover(args) -> dict:
    with Job(args, 120, "cover") as job:
        result = job.run(["cover", "--in", job.mount_recording(args.input), "--offset-ms", str(args.offset_ms), "--out", D.MOUNT_OUT + "/cover.png"], "cover")
        job.collect("cover.png", args.out, max_bytes=COVER_MAX_BYTES)
        return dict(result, path=os.path.abspath(args.out))


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
    sp = sub.add_parser("pin-templates")
    sp.add_argument("--confirmed", action="store_true")
    cuts = load_data()["cuts"]
    sp = sub.add_parser("analyse")
    add_limits(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--out")
    sp.add_argument("--noise-db", type=float, default=cuts["noise_db"])
    sp.add_argument("--min-silence", type=float, default=cuts["min_silence"])
    sp = sub.add_parser("base")
    add_limits(sp)
    sp.add_argument("--transcript", required=True)
    sp.add_argument("--analysis", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--fps", type=int)
    sp.add_argument("--gap", type=float, help="no audio: cut word gaps longer than this (seconds)")
    sp.add_argument("--pad-head", type=float, help="seconds of speech kept before the first word after a silence (default 0.10)")
    sp.add_argument("--pad-tail", type=float, help="seconds of speech kept after the last word before a silence (default 0.14)")
    sp.add_argument("--long-cut", type=float, help="a cut this long (seconds) also takes the wordless sound at its edges (default 2)")
    sp.add_argument("--wordless-max", type=float, help="seconds of sound with no word that a long cut does not leave at an edge (default 0.3)")
    sp.add_argument("--caption-position", default="bottom")
    sp.add_argument("--face-box", help="X,Y,W,H in frame pixels (1080x1920): where the speaker's face is; given once per recording")
    sp.add_argument("--zoom", choices=("alternate", "none"))
    sp.add_argument("--zoom-factor", type=float)
    sp.add_argument("--push-in", type=float, help="slow extra zoom over each range of 5 s or more, as a fraction up to 0.03 (default 0.02, 0 for none)")
    sp.add_argument("--zoom-anchor-y", type=float, help="the zoom's fixed point: this fraction of the face box's height down from its top (default 0.25)")
    sp.add_argument("--confirm", action="append", metavar="RETAKE-ID", help="cut this proposed retake (repeatable)")
    sp.add_argument("--color", action="append", metavar="TOKEN=#RRGGBB")
    sp.add_argument("--font", action="append", metavar="ROLE=ID[:WEIGHT]")
    sp = sub.add_parser("align")
    add_limits(sp)
    sp.add_argument("--post", required=True)
    sp.add_argument("--transcript", required=True)
    sp.add_argument("--checker", required=True, help="the post-writing skill's script checker (check_script.py)")
    sp.add_argument("--vocabulary", required=True, help="shared/references/video-presets.json")
    sp.add_argument("--out", required=True)
    sp.add_argument("--threshold", type=float, default=0.6)
    sp.add_argument("--empty-slot", action="append", metavar="SLOT=keyword|none")
    sp.add_argument("--anchor", action="append", metavar="BEAT=WORD_FROM-WORD_TO")
    sp.add_argument("--edl", help="the edit list whose confirmed retakes are left out of the alignment")
    sp = sub.add_parser("check")
    add_limits(sp)
    sp.add_argument("--edl", required=True)
    sp.add_argument("--beats", required=True)
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--platform-file")
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
    sp = sub.add_parser("cover")
    add_limits(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--offset-ms", type=int, required=True)
    sp.add_argument("--out", required=True)
    return p


VERBS = {"build": verb_build, "pin-browser": verb_pin_browser, "reap": verb_reap, "pin-templates": verb_pin_templates,
         "analyse": verb_analyse, "base": verb_base, "align": verb_align, "check": verb_check_documents, "render": verb_render,
         "cover": verb_cover}


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
