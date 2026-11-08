#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Renderer provider (class renderer:video), the second engine: HyperFrames (decision VD1 of `docs/decisions/2026-11-07-v0-short-video-hyperframes.md`).

It renders the base page (the cuts and the zoom of the edit list) in the HyperFrames image and leaves every other stage to the common
image (the ffmpeg engine's), with the common modules, so that the two engines' outputs pass the same checks. The class default stays
`ffmpeg` (providers/resolve.py `CLASS_DEFAULTS`): a caller that names no implementation never gets this engine.

A render runs five containers, each with no network (providers/_container.py):

  page     common image  `hf-page`: writes index.html and vars.json into the run folder's project/ (with `--base-only`: numbers only, the
                         cuts and the zoom; without it: the captions and the beats too, from the staged blocks, and every text in vars.json)
  proxy    common image  `proxy`: a 1080x1920 H.264 proxy of the recording, at the edit list's fps, into project/media/
  hf       HyperFrames   `hf_render.py`: `hyperframes render` of the project into a ProRes HQ intermediate (4 workers, no frame cache)
  encode   common image  `encode`: the final H.264 from the intermediate with the same output options and fixed threads as the ffmpeg
                         engine, so the same intermediate gives the same bytes whatever the cores
  verify   common image  a fresh container checks the candidate against the platform's spec (`_host.finish_render`)

The frames, the proxy and the intermediate live in a disk work folder, `<work>/hf-<id>/`, checked for free space before the first
container and removed when the render ends. Without `--base-only` a render draws the captions and the beats with the blocks that have a runtime this
engine runs (`blocks/engines/hyperframes.json`: `gsap` pages inlined, `renderat` pages in iframes), stages and hashes the blocks as `ffmpeg.py`
does, and refuses `engine_unknown` while that file does not exist. The gates on what is drawn (the face box, the line at 1560, the pixels) are
package V3b-2's: until they are built, a render that draws is refused (`gates_not_built`) unless the blocks folder is the test folder of test mode.

Verbs (every verb prints one JSON object on stdout; diagnostics on stderr, the first line of a refusal is `refused: <closed code> <field>`):

  --check                  docker answering and local, both images built from their definitions and recorded, the tools in both
                           starting. Exit 3 names what is missing and the command that fixes it.
  build (--dry-run | --confirmed) [--arch arm64|amd64]
                           build the HyperFrames image (the common image is built by `ffmpeg.py build`). The one step that uses the
                           network, at the person's word; --confirmed writes the build record that --check and render read.
  reap                     remove containers and run folders a killed render left behind.
  render --edl EDL --beats BEATS --in VIDEO --out DIR --platform-file F --vocabulary V [--base-only] [--work-dir DIR] [--cpuset 0-3]
         [--time-limit S] [--dry-run] [--memory-mb N] [--cpus N] [--scratch-mb N] [--timeout S]
        Writes DIR/render-<sha12>.mp4 (mode 0400, never rewritten). --work-dir names an existing folder of this user's (not a link) that
        holds the run folder; the default is the renderer's own work folder. --dry-run prints the four stage commands.
  compat --survey DIR --out FILE [--timeout S] [--dry-run]
        The compatibility run of tier A: checks the survey folder (regular files only, at most 2000 files, 20 MB, 256 KiB each), mounts it
        read-only in the HyperFrames image with no network, runs `hf_compat.py` (the planted escapes first, then the verdict of each registry
        component) and writes its report to FILE (a new file, mode 0600). Writes nothing else.
  analyse, base, align, check, cover, still, verify
        the common verbs, served by the same code as `ffmpeg.py` (providers/renderer/_host.py).

Limits, in code (the constants below): memory 6144 MB by default and at least 4096 for the drawing container, 1024 processes, 4 workers.

exit codes: 0 ok, 1 refused or failed, 2 usage error, 3 not configured (docker, an image, its build record).
Standard library only; no network except `build --confirmed`.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

sys.path.insert(0, os.path.dirname(HERE))      # providers/: _container.py lives there (as _docker.py puts it on the path)

import _assets  # noqa: E402
import _blocks  # noqa: E402
import _container as box  # noqa: E402
import _docker as D  # noqa: E402
import _media  # noqa: E402
import _output  # noqa: E402
from _host import (COMMON_HANDLERS, MAX_SMALL_FILE, Job, Usage, add_common_parsers, add_limits, emit, finish_render, stage_blocks, CRASH_CODES)  # noqa: E402
from _text import Refusal  # noqa: E402
from _vocab import load_data  # noqa: E402

NotConfigured = D.NotConfigured


def _load_hf_compat():
    """hyperframes-image/hf_compat.py, loaded by path, for `check_report` (it loads `hf_wrap.py` itself)."""
    path = os.path.join(HERE, "hyperframes-image", "hf_compat.py")
    spec = importlib.util.spec_from_file_location("hf_compat", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("hf_compat", module)
    spec.loader.exec_module(module)
    return module


def _load_hf_image():
    """hyperframes-image/hf_image.py, loaded by path: a folder with a dash in its name is not a package, and the image's definition
    stays that file's (IMAGE_REPOSITORY, definition_hash, image_tag, build_command, build_image, selfcheck)."""
    path = os.path.join(HERE, "hyperframes-image", "hf_image.py")
    spec = importlib.util.spec_from_file_location("hf_image", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("hf_image", module)
    spec.loader.exec_module(module)
    return module


hf_image = _load_hf_image()
hf_compat = _load_hf_compat()

ENGINE = "hyperframes"
LAYERS = ["cuts", "zoom"]
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3

# The limits of the drawing container, and where each figure comes from.
HF_LABEL = "org.openhora.renderer-hyperframes"          # the run label of the HF stage, reaped by `reap`
HF_RECORD = "hyperframes-image.json"                    # the build record, in D.own_dir()
HF_MEMORY_MB_DEFAULT = 6144                             # S2: peak 5924.5 MiB at 6144 on the real input
HF_MEMORY_MB_MIN = 4096                                 # S2: the lowest limit at which the proxied render passed
HF_PIDS = 1024                                          # S2: 512 failed with ffmpeg_transient
HF_WORKERS = 4                                          # S2, check C2: `--workers auto` changes the bytes; hf_render.py fixes it
HF_SCRATCH_MB = 256                                     # /scratch is memory; the frames go to the disk folder instead
HF_TMP_MB = 512                                         # S2's /tmp
HF_SHM_MB = None                                        # OPEN-5: S2 rendered without --shm-size
# Apple's ProRes 422 HQ target for 1920x1080 at 29.97 fps is 220 Mb/s (about 27.5 MB/s; 1080x1920 has the same pixels). Not measured
# here: S2's synthetic content gave 13.9 MB/s; the real recording's rate is what the decision file of V3a-2 records.
PRORES_BYTES_PER_SECOND = 28 * 1024 ** 2
INTERMEDIATE_SLACK = 64 * 1024 ** 2                     # container and index overhead of the .mov
FREE_SPACE_MARGIN = 1024 ** 3                           # margin for the filesystem
RUN_PREFIX = "hf-"                                      # the run folder's prefix
RUN_FOLDER = re.compile(r"hf-[0-9a-f]{12}")
MIN_STAGE_SECONDS = 30                                  # a stage that would get less than this refuses as render_timeout
STAGES = ("page", "proxy", "hf", "encode")
HF_SCHEMA = D.dct(ok=D.B, sha256=D.S, bytes=D.I, seconds=D.N, hyperframes=D.S, memory_peak_bytes=D.opt(D.I))
HF_REFUSAL = D.dct(ok=D.B, code=D.COD, field=D.FLD)
HF_OUT_NAMES = ("intermediate.mov", "result.json", "hf.log")
GATES_BUILT = False                                     # V3b-2 builds the face-box, 1560 and pixel gates and removes this line and its check
COMPOSED_FIELDS = ("blocks", "blocks_sha256", "captions_drawn", "beats_drawn", "runtimes", "fonts_used")   # what the page stage adds to a render that draws
RESULT_MAX_BYTES = 64 * 1024

BUILD_HINT = "python3 providers/renderer/hyperframes.py build --confirmed"
HINTS = {
    "docker_missing": "install Docker and start it (the renderer runs in a container)",
    "docker_not_answering": "start the Docker daemon",
    "docker_daemon_not_local": "use a local Docker daemon: a recording must not cross a network",
    "image_not_built": "run: " + D.BUILD_COMMAND,
    "image_stale": "the common image is older than the files in providers/renderer/: run: " + D.BUILD_COMMAND,
    "image_not_recorded": "the tag does not point at the image `build` recorded: `docker image rm` it and run: " + D.BUILD_COMMAND,
    "hf_image_not_built": "run: " + BUILD_HINT,
    "hf_image_stale": "the HyperFrames image is older than its definition: run: " + BUILD_HINT,
    "hf_image_not_recorded": "the tag does not point at the image `build` recorded: `docker image rm` it and run: " + BUILD_HINT,
    "edl_schema_outdated": "the edit list is version 1 (no zoom.anchor_y): make it again with `base`, which writes version 2",
}


def say(text: str) -> None:
    print(text, file=sys.stderr)


# ---------------------------------------------------------------- the HyperFrames image

def read_record():
    try:
        with open(os.path.join(D.own_dir(), HF_RECORD), encoding="utf-8") as f:
            record = json.load(f)
        return record if isinstance(record, dict) else None
    except (OSError, ValueError):
        return None


def check_hf_image() -> dict:
    """The HyperFrames image this folder's definition describes, ready to run: it exists, carries the definition's hash and is the one
    `build` recorded (a tag can be pointed at another image; the id cannot). NotConfigured otherwise, with the build command as the hint."""
    try:
        tag, wanted = hf_image.image_tag(), hf_image.definition_hash()
    except hf_image.ProviderError:
        raise Refusal("hf_definition_unreadable", "hyperframes-image") from None
    image = D.inspect_image(tag)
    if image is None:
        raise NotConfigured("hf_image_not_built", tag)
    if image["labels"].get(D.LABEL_DEFINITION) != wanted:
        raise NotConfigured("hf_image_stale", tag)
    record = read_record()
    if record is None or record.get("image_id") != image["id"]:
        raise NotConfigured("hf_image_not_recorded", tag)
    return {"tag": tag, "id": image["id"], "definition": wanted, "arch": image["arch"]}


def verb_check(args) -> dict:
    server = D.require_docker()
    common = D.check_image()
    hf = check_hf_image()
    out = {"ok": True, "docker_server": server, "image": common, "hf_image": hf, "daemon": D.daemon_facts()}
    out["hf_selfcheck"] = hf_image.selfcheck(hf["id"])
    with Job(args, 120, "selfcheck") as job:
        out["selfcheck"] = job.run(["selfcheck"], "selfcheck")
    out["ok"] = bool(out["hf_selfcheck"]["ok"])
    return out


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verb_build(args) -> dict:
    if bool(args.confirmed) == bool(args.dry_run):
        raise Usage("build takes --dry-run (the exact command) or --confirmed (it downloads a base image, packages, a browser, ffmpeg and npm packages "
                    "and writes a local image): a person starts it, never a run.")
    try:
        if args.dry_run:
            arch = args.arch or hf_image.ARCHES.get(platform.machine().lower())
            if arch not in hf_image.PINNED_ARCHES:
                raise Usage("--arch is arm64 or amd64")
            return {"ok": True, "dry_run": True, "command": hf_image.build_command(arch), "tag": hf_image.image_tag(), "arch": arch}
        D.require_docker()
        arch = hf_image.daemon_arch()
        if args.arch and args.arch != arch:
            raise Usage("a build is for the docker daemon's own architecture (%s): leave --arch out" % arch)
        say("building %s; this downloads the base image, packages, the browser, ffmpeg and the npm packages, and takes a while" % hf_image.image_tag())
        built = hf_image.build_image(arch)
    except hf_image.ProviderError as err:
        say("error: %s" % err)
        if err.code == EXIT_USAGE:
            raise Usage(str(err)) from None
        if err.code == EXIT_NOT_CONFIGURED:
            raise NotConfigured("hf_build_not_possible", "build") from None
        raise Refusal("hf_build_failed", "build") from None
    D.private_dir(D.own_dir(), "renderer folder")
    record = {"image_id": built["image_id"], "tag": built["tag"], "definition": built["definition"], "arch": built["arch"], "built_at": utc_now()}
    path = os.path.join(D.own_dir(), HF_RECORD)
    D.write_private_json(path, record)
    return dict(record, ok=True, dry_run=False, record=path)


# ---------------------------------------------------------------- leftovers

def reap_hf_folders(root: str, now=None) -> int:
    """Remove the run folders a killed render left under `root`: direct children named hf-<12 hex>, real folders (never a link), older
    than the longest a container may run plus ten minutes. Nothing else is touched."""
    now = time.time() if now is None else now
    removed = 0
    for entry in list(os.scandir(root)):
        try:
            if RUN_FOLDER.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False) \
                    and entry.stat(follow_symlinks=False).st_mtime < now - (D.MAX_TIMEOUT + 600):
                shutil.rmtree(entry.path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def verb_reap(args) -> dict:
    """Containers of both labels and the run folders of the renderer's own work folder. A `--work-dir` of the media step is that step's: its
    retention purges it, and this verb never reaches into it."""
    D.require_docker()
    try:
        hf_containers = box.reap(HF_LABEL)
    except box.ContainerError as err:
        raise D.refusal_of(err) from None
    return {"ok": True, "containers_removed": D.reap_containers(), "hf_containers_removed": hf_containers, "folders_removed": D.reap_folders(),
            "hf_folders_removed": reap_hf_folders(D.work_root())}


# ---------------------------------------------------------------- render

def work_folder(path):
    """The folder the run folder goes in: the renderer's own work folder, or `--work-dir`: absolute, an existing folder, no link in its
    path, owned by this user."""
    if path is None:
        return D.work_root()
    try:
        found = os.lstat(path)
        ok = os.path.isabs(path) and stat.S_ISDIR(found.st_mode) and os.path.realpath(path) == path and found.st_uid == os.getuid()
    except OSError:
        ok = False
    if not ok:
        raise Refusal("bad_work_dir", "work-dir")
    return path


def intermediate_cap(out_seconds: float) -> int:
    return int(PRORES_BYTES_PER_SECOND * out_seconds) + INTERMEDIATE_SLACK


def space_needed(out_seconds: float) -> int:
    return _media.PROXY_MAX_BYTES + intermediate_cap(out_seconds) + D.MAX_OUT_BYTES + FREE_SPACE_MARGIN


def left_for(deadline: float, stage: str) -> int:
    """Seconds this stage may take: what is left of the render's time limit; a stage that would get fewer than MIN_STAGE_SECONDS is refused."""
    left = deadline - time.monotonic()
    if left < MIN_STAGE_SECONDS:
        raise Refusal("render_timeout", stage)
    return int(left)


def check_memory(args) -> int:
    """The drawing container's memory: under HF_MEMORY_MB_MIN or over the box's maximum is refused (it needs no docker to say so)."""
    if args.memory_mb < HF_MEMORY_MB_MIN:
        raise Refusal("memory_too_small", "memory-mb")
    if args.memory_mb > D.MAX_MEMORY_MB:
        raise Refusal("memory_too_large", "memory-mb")
    return args.memory_mb


def hf_limits(args) -> tuple:
    """(memory MB, cpus) of the drawing container; the cpus are never more than the daemon has."""
    return check_memory(args), max(1, min(args.cpus, D.daemon_facts()["cpus"]))


def hf_command(args, image: dict, run_dir: str, fps: int, t: int):
    """(container name, the exact `docker run` command) of the drawing stage. Three read-write mounts, no recording, no network."""
    name = "openhora-hyperframes-%s" % uuid.uuid4().hex[:12]
    memory, cpus = hf_limits(args)
    mounts = [(os.path.join(run_dir, "project"), "/work/project", "rw"), (os.path.join(run_dir, "out"), "/work/out", "rw"),
              (os.path.join(run_dir, "tmp"), "/work/tmp", "rw")]
    inner = ["python3", "-I", "/opt/hf-run/hf_render.py", "--project", "/work/project", "--out", "/work/out", "--tmp", "/work/tmp",
             "--fps", str(fps), "--timeout", str(max(1, t - 30))]
    try:
        return name, box.argv(name, image["id"], inner, label=HF_LABEL, deadline=int(time.time()) + t + 60, mounts=mounts, memory_mb=memory, cpus=cpus,
                              scratch_mb=HF_SCRATCH_MB, pids_limit=HF_PIDS, tmp_mb=HF_TMP_MB, cpuset=getattr(args, "cpuset", None), shm_mb=HF_SHM_MB)
    except box.ContainerError as err:
        raise D.refusal_of(err) from None


def read_hf_result(out_dir: str, rc: int) -> dict:
    """What the drawing container wrote, as untrusted: only regular files of the three names; result.json rebuilt from its closed schema.
    A refusal row is raised again here as the same Refusal."""
    for entry in os.scandir(out_dir):
        found = entry.stat(follow_symlinks=False)
        if entry.name not in HF_OUT_NAMES or not stat.S_ISREG(found.st_mode):
            raise Refusal("container_left_non_regular_file", "output")
    try:
        raw = _assets.read_regular(os.path.join(out_dir, "result.json"), RESULT_MAX_BYTES, "container_wrote_no_file", "result.json")
        doc = json.loads(raw.decode("utf-8"))
        assert isinstance(doc, dict)
    except (Refusal, ValueError, AssertionError, UnicodeDecodeError, RecursionError):
        raise Refusal(CRASH_CODES.get(rc, "container_failed"), "container") from None
    if rc != 0 or doc.get("ok") is not True:
        row = D.sanitise(doc, HF_REFUSAL, "hf")
        raise Refusal(row.get("code", "container_failed"), row.get("field", ""))
    result = D.sanitise(doc, HF_SCHEMA, "hf")
    if not re.fullmatch(r"[0-9a-f]{64}", result.get("sha256", "")) or not isinstance(result.get("bytes"), int) or "hyperframes" not in result:
        raise Refusal("container_result_invalid", "hf")
    return result


def run_hf_stage(args, run_dir: str, fps: int, t: int, cap: int, dry: bool):
    image = check_hf_image()
    name, command = hf_command(args, image, run_dir, fps, t)
    if dry:
        return image, command, None
    try:
        done = box.run(command, name, t)
    except box.ContainerError as err:
        raise D.refusal_of(err) from None
    out_dir = os.path.join(run_dir, "out")
    result = read_hf_result(out_dir, done.returncode)
    target = os.path.join(out_dir, "intermediate.mov")
    try:
        found = os.lstat(target)
    except OSError:
        raise Refusal("container_wrote_no_file", "intermediate") from None
    if not stat.S_ISREG(found.st_mode):
        raise Refusal("container_file_not_regular", "intermediate")
    if found.st_size > cap:
        raise Refusal("intermediate_too_large", "intermediate")
    if found.st_size != result["bytes"] or _media.sha256_file(target) != result["sha256"]:
        raise Refusal("intermediate_differs", "intermediate")
    return image, command, result


def read_documents(args, data: dict) -> tuple:
    """(out seconds, fps, the platform's byte cap, the time limit) from the edit list and the platform file, as the ffmpeg engine reads them."""
    try:
        edl_doc = json.loads(_assets.read_regular(args.edl, data["limits"]["json_max_bytes"], "input_unreadable", "edl").decode("utf-8"))
        out_frames, fps = edl_doc["out_frames"], edl_doc["fps"]
        platform_doc = json.loads(_assets.read_regular(args.platform_file, MAX_SMALL_FILE, "input_unreadable", "platform").decode("utf-8"))
        out_seconds = out_frames / float(fps)
        limit = _output.time_limit_for(data, out_seconds, args.time_limit)
        byte_cap = min(D.MAX_OUT_BYTES, _media.byte_limit(platform_doc))
    except (Refusal, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError):
        raise Refusal("edl_unreadable", "edl") from None
    return out_seconds, fps, byte_cap, limit


def check_may_draw() -> None:
    """A render that draws needs the engine's own file in the blocks folder (`blocks/engines/hyperframes.json`): refused before any container
    runs while there is none (`engine_unknown`). And it needs the gates on what is drawn: while GATES_BUILT is False (package V3b-2 builds them)
    only a test blocks folder (test mode) may draw, so that nothing drawn reaches a recording unchecked. The folder is the committed one, or the
    test folder in test mode only."""
    if ENGINE not in _blocks.load_catalogue(_blocks.blocks_dir())["engines"]:
        raise Refusal("engine_unknown", ENGINE)
    if not GATES_BUILT and _blocks.blocks_dir() == _blocks.BLOCKS_DIR:
        raise Refusal("gates_not_built", "render")


def verb_render(args) -> dict:
    if not args.base_only:
        check_may_draw()
    if args.cpuset is not None:
        try:
            box.check_cpuset(args.cpuset)
        except box.ContainerError:
            raise Refusal("bad_cpuset", "cpuset") from None
    out_dir = os.path.abspath(os.path.dirname(args.out) if args.out.endswith(".mp4") else args.out)
    data = load_data()
    out_seconds, fps, byte_cap, limit = read_documents(args, data)
    deadline = time.monotonic() + limit
    check_memory(args)
    work = work_folder(args.work_dir)
    run_dir = os.path.join(work, "%s%s" % (RUN_PREFIX, uuid.uuid4().hex[:12]))
    seconds, commands = {}, {}
    try:
        try:
            box.check_free_space(work, space_needed(out_seconds), "work-dir")
        except box.ContainerError:
            raise Refusal("no_space", "work-dir") from None
        check_hf_image()                                  # before the first container: a missing image is found before a proxy is made
        os.mkdir(run_dir, 0o700)
        project, media, hf_out, tmp = (os.path.join(run_dir, name) for name in ("project", "project/media", "out", "tmp"))
        for folder in (project, hf_out, tmp):
            os.mkdir(folder, 0o700)                          # project/media is made after the page stage: the page's folder must be empty
        cap = intermediate_cap(out_seconds)
        dry = bool(args.dry_run)

        # Stage 1, the page, in the common image.
        started = time.monotonic()
        page = {}
        with Job(args, left_for(deadline, "page"), "hf-page") as job:
            job.add_mount(project, "/work/project", "rw")
            inner = ["hf-page", "--edl", job.stage("edl.json", args.edl), "--beats", job.stage("beats.json", args.beats),
                     "--vocabulary", job.stage("vocabulary.json", args.vocabulary), "--platform-file", job.stage("platform.json", args.platform_file),
                     "--out", "/work/project"]
            blocks_args = ["--base-only"] if args.base_only else stage_blocks(job, _blocks.blocks_dir())
            inner += blocks_args
            if dry:
                commands["page"] = job.argv(inner)[2]
            else:
                page = job.run(inner, "hf-page")
                if not args.base_only and page.get("blocks_sha256") != blocks_args[-1]:
                    raise Refusal("blocks_changed", "blocks")
        seconds["page"] = round(time.monotonic() - started, 2)
        os.mkdir(media, 0o700)

        # Stage 2, the proxy, in the common image.
        started = time.monotonic()
        proxy_sha256 = "0" * 64
        with Job(args, left_for(deadline, "proxy"), "proxy") as job:
            job.add_mount(media, "/work/media", "rw")
            inner = ["proxy", "--edl", job.stage("edl.json", args.edl), "--in", job.mount_recording(args.input), "--out", "/work/media/proxy.mp4"]
            if dry:
                commands["proxy"] = job.argv(inner)[2]
            else:
                proxied = job.run(inner, "proxy")
                path = os.path.join(media, "proxy.mp4")
                try:
                    found = os.lstat(path)
                except OSError:
                    raise Refusal("container_wrote_no_file", "proxy") from None
                if not stat.S_ISREG(found.st_mode):
                    raise Refusal("container_file_not_regular", "proxy")
                if found.st_size > _media.PROXY_MAX_BYTES:
                    raise Refusal("container_file_too_large", "proxy")
                if _media.sha256_file(path) != proxied["sha256"]:
                    raise Refusal("container_file_differs", "proxy")
                proxy_sha256 = proxied["sha256"]
        seconds["proxy"] = round(time.monotonic() - started, 2)

        # Stage 3, the drawing, in the HyperFrames image.
        started = time.monotonic()
        t = max(MIN_STAGE_SECONDS, min(D.MAX_TIMEOUT, args.timeout if args.timeout else left_for(deadline, "hf")))
        image, command, drawn = run_hf_stage(args, run_dir, fps, t, cap, dry)
        seconds["hf"] = round(time.monotonic() - started, 2)
        if dry:
            commands["hf"] = command

        # Stage 4, the final encode, in the common image, and the verification in a fresh one.
        started = time.monotonic()
        with Job(args, left_for(deadline, "encode"), "encode") as job:
            job.add_mount(hf_out, "/work/hf", "ro")
            inner = ["encode", "--in", "/work/hf/intermediate.mov", "--sha256", drawn["sha256"] if drawn else "0" * 64,
                     "--edl", job.stage("edl.json", args.edl), "--platform-file", job.stage("platform.json", args.platform_file), "--out", D.MOUNT_OUT]
            if dry:
                commands["encode"] = job.argv(inner)[2]
                return {"ok": True, "dry_run": True, "engine": ENGINE, "commands": commands, "image": job.image, "hf_image": image,
                        "time_limit_seconds": limit, "out_dir": out_dir, "limits": hf_limit_facts(args, cap, out_seconds)}
            result = job.run(inner, "encode")
            result = finish_render(args, job, result, out_dir=out_dir, byte_cap=byte_cap, out_seconds=out_seconds)
        seconds["encode"] = round(time.monotonic() - started, 2)
        result.update(engine=ENGINE, layers=list(LAYERS), stage_seconds=seconds, proxy_sha256=proxy_sha256, intermediate_sha256=drawn["sha256"],
                      intermediate_bytes=drawn["bytes"], memory_peak_bytes=drawn.get("memory_peak_bytes"), hyperframes=drawn["hyperframes"],
                      hf_image={"id": image["id"], "tag": image["tag"]})
        if not args.base_only:
            if any(key not in page for key in COMPOSED_FIELDS + ("layers",)):
                raise Refusal("container_result_invalid", "hf-page")
            result.update(layers=list(page["layers"]), **{key: page[key] for key in COMPOSED_FIELDS})
        return result
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)       # the proxy and the intermediate never outlive the render (OPEN-6)


# ---------------------------------------------------------------- compat (tier A)

COMPAT_MEMORY_MB = 2048
COMPAT_CPUS = 2
COMPAT_TIMEOUT_DEFAULT = 600
COMPAT_OUT_NAMES = hf_compat.OUT_NAMES
SURVEY_MAX_FILES = hf_compat.MAX_FILES
SURVEY_MAX_BYTES = hf_compat.MAX_TOTAL_BYTES
SURVEY_FILE_CAP = hf_compat.MAX_FILE_BYTES
SURVEY_DOC_CAP = 8 * 1024 * 1024


def check_survey(path: str) -> int:
    """The survey folder: absolute, a real folder (no link), holding `survey.json` and regular files only, at most SURVEY_MAX_FILES files
    and SURVEY_MAX_BYTES bytes, each file within its cap. Returns the file count. `bad_survey` otherwise."""
    try:
        found = os.lstat(path)
        ok = os.path.isabs(path) and stat.S_ISDIR(found.st_mode) and os.path.realpath(path) == path
    except OSError:
        ok = False
    if not ok:
        raise Refusal("bad_survey", "survey")
    count = total = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            full = os.path.join(base, name)
            mode = os.lstat(full).st_mode
            if stat.S_ISDIR(mode):
                continue
            size = os.lstat(full).st_size
            cap = SURVEY_DOC_CAP if full == os.path.join(path, "survey.json") else SURVEY_FILE_CAP
            count += 1
            total += size
            if not stat.S_ISREG(mode) or size > cap or count > SURVEY_MAX_FILES or total > SURVEY_MAX_BYTES:
                raise Refusal("bad_survey", os.path.relpath(full, path)[:80])
    if not os.path.isfile(os.path.join(path, "survey.json")):
        raise Refusal("bad_survey", "survey.json")
    return count


def overlay_presets(catalogue: dict) -> dict:
    """{preset: {parameter: {type, required}}} of our own overlay blocks, for the preset rule of `hf_compat.py`."""
    out = {}
    for name, block in sorted(catalogue["blocks"].items()):
        if name.startswith("oh:") and block["kind"] == "overlay" and block["preset"] and block["band"] == "card":
            out[block["preset"]] = {pname: {"type": spec["type"] if isinstance(spec["type"], str) else "slot", "required": bool(spec.get("required"))}
                                    for pname, spec in sorted(block["params"].items())}
    return out


def compat_command(args, image: dict, run_dir: str, t: int):
    name = "openhora-hyperframes-%s" % uuid.uuid4().hex[:12]
    memory, cpus = args.memory_mb, max(1, min(COMPAT_CPUS, D.daemon_facts()["cpus"]))
    if memory < 1024 or memory > D.MAX_MEMORY_MB:
        raise Refusal("memory_too_small" if memory < 1024 else "memory_too_large", "memory-mb")
    mounts = [(args.survey, "/work/survey", "ro"), (os.path.join(run_dir, "out"), "/work/out", "rw"), (os.path.join(run_dir, "in"), "/work/in", "ro")]
    inner = ["python3", "-I", "/opt/hf-run/hf_compat.py", "--survey", "/work/survey", "--out", "/work/out", "--presets", "/work/in/presets.json"]
    try:
        return name, box.argv(name, image["id"], inner, label=HF_LABEL, deadline=int(time.time()) + t + 60, mounts=mounts, memory_mb=memory, cpus=cpus,
                              scratch_mb=HF_SCRATCH_MB, pids_limit=HF_PIDS, tmp_mb=HF_TMP_MB)
    except box.ContainerError as err:
        raise D.refusal_of(err) from None


def read_compat_result(out_dir: str, rc: int) -> dict:
    """The report the compat container wrote, as untrusted: regular files of the two names only, `result.json` through its closed schema, the
    report through `hf_compat.check_report`."""
    for entry in os.scandir(out_dir):
        if entry.name not in COMPAT_OUT_NAMES or not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
            raise Refusal("container_left_non_regular_file", "output")
    try:
        doc = json.loads(_assets.read_regular(os.path.join(out_dir, hf_compat.RESULT_NAME), RESULT_MAX_BYTES, "container_wrote_no_file", "result.json").decode("utf-8"))
        assert isinstance(doc, dict)
    except (Refusal, ValueError, AssertionError, UnicodeDecodeError, RecursionError):
        raise Refusal(CRASH_CODES.get(rc, "container_failed"), "container") from None
    if rc != 0 or doc.get("ok") is not True:
        row = D.sanitise(doc, HF_REFUSAL, "compat")
        raise Refusal(row.get("code", "container_failed"), row.get("field", ""))
    try:
        raw = _assets.read_regular(os.path.join(out_dir, hf_compat.REPORT_NAME), SURVEY_DOC_CAP, "container_wrote_no_file", "compat-report.json")
        return hf_compat.check_report(json.loads(raw.decode("utf-8")))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise Refusal("container_result_invalid", "compat") from None


def verb_compat(args) -> dict:
    args.survey = os.path.abspath(args.survey) if args.survey else args.survey
    count = check_survey(args.survey)
    out = os.path.abspath(args.out)
    if not os.path.isdir(os.path.dirname(out)) or os.path.lexists(out):
        raise Refusal("bad_out", "out")
    t = max(MIN_STAGE_SECONDS, min(D.MAX_TIMEOUT, args.timeout or COMPAT_TIMEOUT_DEFAULT))
    presets = overlay_presets(_blocks.load_catalogue(_blocks.blocks_dir()))
    work = work_folder(None)
    run_dir = os.path.join(work, "%s%s" % (RUN_PREFIX, uuid.uuid4().hex[:12]))
    try:
        image = check_hf_image()
        os.mkdir(run_dir, 0o700)
        for folder in ("out", "in"):
            os.mkdir(os.path.join(run_dir, folder), 0o700)
        D.write_private_json(os.path.join(run_dir, "in", "presets.json"), presets)
        name, command = compat_command(args, image, run_dir, t)
        if args.dry_run:
            return {"ok": True, "dry_run": True, "command": command, "hf_image": image, "survey_files": count}
        try:
            done = box.run(command, name, t)
        except box.ContainerError as err:
            raise D.refusal_of(err) from None
        report = read_compat_result(os.path.join(run_dir, "out"), done.returncode)
        D.write_private_json(out, report)
        admitted = sum(1 for c in report["components"] if c["verdict"] == "admit-candidate")
        return {"ok": True, "report": out, "planted": report["planted"], "components": len(report["components"]), "admit_candidates": admitted,
                "hf_image": {"id": image["id"], "tag": image["tag"]}}
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def hf_limit_facts(args, cap: int, out_seconds: float) -> dict:
    memory, cpus = hf_limits(args)
    return {"memory_mb": memory, "cpus": cpus, "cpuset": args.cpuset, "pids": HF_PIDS, "workers": HF_WORKERS, "scratch_mb": HF_SCRATCH_MB, "tmp_mb": HF_TMP_MB,
            "shm_mb": HF_SHM_MB, "intermediate_cap_bytes": cap, "free_space_needed_bytes": space_needed(out_seconds)}


# ---------------------------------------------------------------- command line

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb")
    sp = sub.add_parser("build", help="build the HyperFrames image (--dry-run prints the command; --confirmed builds it and writes the record)")
    sp.add_argument("--confirmed", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--arch", choices=("arm64", "amd64"))
    sp = sub.add_parser("compat", help="the compatibility run of tier A: the planted escapes and the verdict of each registry component of a survey folder")
    sp.add_argument("--survey", required=True, help="the survey folder: survey.json and <component>/<file> (absolute, no link)")
    sp.add_argument("--out", required=True, help="the report to write (a new file)")
    sp.add_argument("--timeout", type=int, help="seconds before the container is removed (default %d)" % COMPAT_TIMEOUT_DEFAULT)
    sp.add_argument("--memory-mb", type=int, default=COMPAT_MEMORY_MB)
    sp.add_argument("--dry-run", action="store_true")
    sub.add_parser("reap", help="remove containers and run folders a killed render left behind")
    add_common_parsers(sub)
    sp = sub.add_parser("render", help="render with HyperFrames (the cuts and the zoom, plus the captions and the beats unless --base-only) and encode it "
                                       "in the common image")
    add_limits(sp)
    sp.set_defaults(memory_mb=HF_MEMORY_MB_DEFAULT)
    sp.add_argument("--edl", required=True)
    sp.add_argument("--beats", required=True)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--platform-file", required=True)
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--base-only", action="store_true", help="the cuts and the zoom only, no captions and no beats")
    sp.add_argument("--work-dir", help="an existing absolute folder of this user's (not a link) that holds the run folder; default: the renderer's work folder")
    sp.add_argument("--cpuset", help="pin the containers to these cores, for example 0-3")
    sp.add_argument("--time-limit", type=int)
    sp.add_argument("--dry-run", action="store_true")
    return p


VERBS = {"build": verb_build, "reap": verb_reap, "render": verb_render, "compat": verb_compat, **COMMON_HANDLERS}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "--check":
            if len(argv) != 1:
                raise Usage("--check takes no other flag")
            ns = argparse.Namespace(memory_mb=D.DEFAULT_MEMORY_MB, cpus=D.DEFAULT_CPUS, scratch_mb=D.DEFAULT_SCRATCH_MB, timeout=None, cpuset=None)
            result = verb_check(ns)
        else:
            args = parser().parse_args(argv)
            if args.verb is None:
                parser().print_help(sys.stderr)
                return EXIT_USAGE
            result = VERBS[args.verb](args)
        emit(result)
        return EXIT_OK if result.get("ok", True) else EXIT_FAILED
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
            failure["reason"] = err.reason
        emit(failure)
        return EXIT_NOT_CONFIGURED if isinstance(err, NotConfigured) else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
