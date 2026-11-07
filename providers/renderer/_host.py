#!/usr/bin/env python3
"""The host side both engines share: one job in a container (stage the inputs, run, collect the result as untrusted), the flags of the
limits, and the verbs that need no browser: analyse, base, align, check, cover, still and verify.

Not a provider (a file whose name starts with an underscore is not an implementation); `ffmpeg.py` imports it and keeps only the verbs
that draw (render, storyboard, pin-blocks, block-params), `build`, `pin-browser`, `reap` and `--check`. A second engine imports `add_common_parsers`
and `COMMON_HANDLERS` and gets the same verbs, run the same way, in a container of its own image. This file is not in the image
(`_docker.HOST_ONLY`). The verbs are the ones the branch had, moved without a change; `verify` is new as a host verb. Standard library
only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import time
import uuid

import _assets
import _blocks
import _docker as D
import _media
import _output
from _browser import NotConfigured
from _text import Refusal
from _vocab import load_data, load_vocabulary

MAX_RECORDING_BYTES = 1 << 30
MAX_SMALL_FILE = 5 * 1024 * 1024
COVER_MAX_BYTES = 16 * 1024 * 1024
STILL_MAX_BYTES = 8 * 1024 * 1024        # the largest still the host keeps (the service refuses to serve more): a 1080x1920 photograph is a few MiB
CRASH_CODES = {125: "docker_run_failed", 126: "docker_run_failed", 127: "docker_run_failed", 137: "container_killed", 143: "container_killed"}


class Usage(Exception):
    pass


def emit(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


# ---------------------------------------------------------------- one job: stage, run, collect

class Job:
    """A private folder `.job-<id>` under the work folder: `in/` is mounted read-only at /job, `out/` read-write at /out. The
    inputs are copied in through safe reads with size caps; nothing of the person's folders is mounted but the recording."""

    def __init__(self, args, timeout: float, verb: str):
        self.args, self.timeout, self.verb = args, timeout, verb
        self.recording = None
        self.staged = {}
        self.max_entries = D.MAX_OUT_ENTRIES

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
        data = _assets.read_regular(path, limit, "input_unreadable", os.path.basename(name)[:40])
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
        D.check_out_folder(self.out_dir, self.max_entries)
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


# ---------------------------------------------------------------- the common verbs

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


def verb_cover(args) -> dict:
    with Job(args, 120, "cover") as job:
        result = job.run(["cover", "--in", job.mount_recording(args.input), "--offset-ms", str(args.offset_ms), "--out", D.MOUNT_OUT + "/cover.png"], "cover")
        job.collect("cover.png", args.out, max_bytes=COVER_MAX_BYTES)
        return dict(result, path=os.path.abspath(args.out))


def verb_still(args) -> dict:
    """A frame of the recording, framed as the render frames it. The container writes `still.png`; the host hashes it on the way out,
    checks the PNG header and the frame size itself, and stores it as `still-<sha12>.png`, 0400, never rewritten."""
    if args.at_ms < 0:
        raise Usage("--at-ms is a number of milliseconds, zero or more")
    out_dir = os.path.abspath(args.out)
    with Job(args, 120, "still") as job:
        result = job.run(["still", "--in", job.mount_recording(args.input), "--at-ms", str(args.at_ms), "--out", D.MOUNT_OUT + "/still.png"], "still")
        digest = result.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Refusal("container_result_invalid", "still")
        candidate = os.path.join(job.root, "candidate.png")
        job.collect("still.png", candidate, max_bytes=STILL_MAX_BYTES, mode=0o400, expect_sha256=digest)
        frame = load_data()["frame"]
        if result.get("at_ms") != args.at_ms or result.get("bytes") != os.path.getsize(candidate):
            raise Refusal("container_result_invalid", "still")          # the container's own account must be the request and the file
        if _output.png_size(candidate) != (frame["width"], frame["height"]) or (result.get("width"), result.get("height")) != (frame["width"], frame["height"]):
            raise Refusal("container_result_invalid", "still")
        final = os.path.join(out_dir, "still-%s.png" % digest[:12])
        os.makedirs(out_dir, mode=0o700, exist_ok=True)
        outcome = D.copy_out(candidate, final, max_bytes=STILL_MAX_BYTES, mode=0o400, expect_sha256=digest, exclusive=True)
        return dict(result, path=final, name=os.path.basename(final), replayed=(outcome == "replayed"),
                    image={"id": job.image["id"], "tag": job.image["tag"]})


def verb_verify(args) -> dict:
    """Check a finished render, a file that is already stored, in a fresh container: its sha256 (given, or the file's own when not given),
    ffprobe's facts against the platform file's video spec, the colour tags, and the length when an edit list says what it should be. The
    same inner verb the render runs on its own candidate, started the same way, so an output can be verified without rendering it again."""
    expect = []
    if args.edl:
        data = load_data()
        try:
            doc = json.loads(_assets.read_regular(args.edl, data["limits"]["json_max_bytes"], "input_unreadable", "edl").decode("utf-8"))
            expect = ["--expect-seconds", "%.3f" % (doc["out_frames"] / float(doc["fps"]))]
        except (Refusal, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
            raise Refusal("edl_unreadable", "edl") from None
    digest = args.sha256 or _media.sha256_file(args.input)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise Usage("--sha256 takes 64 lowercase hex digits")
    with Job(args, 300, "verify") as job:
        return job.run(["verify", "--in", job.mount_recording(args.input), "--platform-file", job.stage("platform.json", args.platform_file),
                        "--sha256", digest] + expect, "verify")


COMMON_HANDLERS = {"analyse": verb_analyse, "base": verb_base, "align": verb_align, "check": verb_check_documents, "cover": verb_cover,
                   "still": verb_still, "verify": verb_verify}
COMMON_VERBS = tuple(COMMON_HANDLERS)


# ---------------------------------------------------------------- the blocks of a job

def stage_blocks(job, blocks_dir=None) -> list:
    """G9: copy blocks/pins.json and every file it pins into the job's read-only folder, then load the catalogue from that copy (every
    hash checked there, never on the live folder) and return the container's flags with the sha256 of the copied pins.json."""
    src = blocks_dir or _blocks.BLOCKS_DIR
    job.stage("blocks/pins.json", os.path.join(src, "pins.json"), _blocks.MAX_FILE)
    staged = os.path.join(job.in_dir, "blocks")
    files = _blocks.read_pins(staged)[1]
    for rel in sorted(files):
        job.stage("blocks/" + rel, os.path.join(src, rel), _blocks.MAX_FILE)
    digest = _blocks.load_catalogue(staged)["sha256"]
    return ["--blocks", D.MOUNT_JOB + "/blocks", "--blocks-sha256", digest]


def verb_block_params(args, engine: str) -> dict:
    """The renderer-side checker (decision VD15) on the host: one block's parameters against its block.json or allowlist entry. It reads
    no recording, transcript or post, so it starts no container. It prints the block, the engine and the parameter names, never their text;
    a value that the checker would clean is refused (text_not_clean), as check_beats refuses it."""
    vocab = load_vocabulary(args.vocabulary)
    try:
        params = json.loads(_assets.read_regular(args.params, 64 * 1024, "input_unreadable", "params").decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refusal("params_not_object", "params") from None
    catalogue = _blocks.load_catalogue()
    name = args.block
    if not _blocks.NAME.fullmatch(name or "") or name not in catalogue["blocks"]:
        raise Refusal("block_unknown", "block")
    block = catalogue["blocks"][name]
    if engine not in _blocks.engines_of(catalogue, block):
        raise Refusal("block_not_on_engine", catalogue["engines"][engine]["presets"].get(block["preset"] or "", ""))
    clean = _blocks.check_params(block, params, vocab, "params")
    if clean != params:
        raise Refusal("text_not_clean", "params")
    return {"ok": True, "block": name, "engine": engine, "params": sorted(clean)}


# ---------------------------------------------------------------- the flags of the common verbs

def add_common_parsers(sub) -> None:
    """Add the common verbs' subparsers to `sub` (the result of `add_subparsers`)."""
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
    sp = sub.add_parser("cover")
    add_limits(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--offset-ms", type=int, required=True)
    sp.add_argument("--out", required=True)
    sp = sub.add_parser("still")
    add_limits(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--at-ms", type=int, required=True)
    sp.add_argument("--out", required=True, help="the folder the still is written into")
    sp = sub.add_parser("verify")
    add_limits(sp)
    sp.add_argument("--in", dest="input", required=True, help="the stored render (an MP4)")
    sp.add_argument("--platform-file", required=True)
    sp.add_argument("--sha256", help="the sha256 the render reported; the file's own when left out")
    sp.add_argument("--edl", help="the edit list the render came from: its length is checked against the file's")
