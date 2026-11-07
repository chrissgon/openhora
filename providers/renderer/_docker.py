"""The renderer's container: the image, its build, and one run of it. Standard library only; the docker command-line client is
the one outside tool. The docker client, the run command, the run and the reaping are providers/_container.py's (the box, shared
with the converter, the exporter, the script runner and the transcriber); this file keeps its own names for them, as wrappers that
raise the renderer's refusals. The image's definition is _image.py's. A provider-owned definition built by a verb the person
starts, an image run by its recorded id, and every limit of the container in code with a test that names it.

The container (tests/test_renderer_docker.py names each limit): no network, a read-only root file system, every capability
dropped and no new privileges, a non-root user, a limit on processes, memory (swap included) and CPUs, no environment variable of
the host, the recording and a staged job folder mounted read-only, one folder mounted read-write for the output, memory-backed
/tmp and /scratch with no exec, an image that is never pulled at run time, and a timeout after which the client is killed and
the container removed by name (also when this process is stopped). The daemon must be local.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import _container as box  # noqa: E402  (the shared container box: providers/_container.py)

from _browser import NotConfigured  # noqa: E402
from _image import IMAGE_REPOSITORY, definition_files, definition_hash, image_tag  # noqa: E402,F401  (the image's definition is _image.py's)
from _text import Refusal  # noqa: E402

LABEL_DEFINITION = box.LABEL_DEFINITION
LABEL_RUN, LABEL_DEADLINE = "org.openhora.renderer", "org.openhora.renderer.deadline"
STATE_ENV = "OPENHORA_STATE_DIR"
STATE_FOLDER, BUILD_RECORD, WORK_FOLDER, JOB_PREFIX = "renderer", "image.json", "work", ".job-"

# What the image's definition covers is _image.py's: the files image-manifest.json lists, and only those.
HOST_ONLY = ("_docker.py", "_browser.py", "_image.py", "_host.py")      # underscore modules that only the host side uses: not in the image

# The limits of one container.
PIDS_LIMIT = 512
TMP_SIZE_MB = 256
DEFAULT_SCRATCH_MB, DEFAULT_MEMORY_MB, DEFAULT_CPUS = 2048, 6144, 8     # the CPU quota is what a render waits for: 8 against 4 took the compose of a 4K recording from 49 s to 21 s
MIN_MEMORY_MB, MAX_MEMORY_MB, MAX_SCRATCH_MB = 3072, 32768, 8192
MEMORY_MARGIN_MB = 2048                  # what the browser and ffmpeg need beside the memory-backed scratch: scratch <= memory - this
MAX_STDERR = box.STDERR_CAP              # the most of a container's stderr the host keeps (its last bytes); the rest is read and thrown away
MOUNT_RECORDING, MOUNT_JOB, MOUNT_OUT, MOUNT_SCRATCH = "/in/recording", "/job", "/out", "/scratch"
BUILD_TIMEOUT, PROBE_TIMEOUT, STOP_GRACE = 3600, 60, 120
MAX_TIMEOUT = 2400                       # seconds, the longest a container may run (the render limit is 1800)
MAX_OUT_BYTES = 450 * 1024 * 1024        # everything the container may leave in /out
MAX_OUT_ENTRIES = 8
STORYBOARD_OUT_ENTRIES = 16               # result.json, sheet.png and a still for each of the vocabulary's 12 beats
MAX_RESULT_BYTES = 4 * 1024 * 1024
STDERR_TAIL = 300
DOCKER_CLIENT_ENV = box.DOCKER_CLIENT_ENV

def say(text):
    print(text, file=sys.stderr)


def tail(text, limit=STDERR_TAIL):
    return " ".join((text or "").split())[-limit:]


# ---------------------------------------------------------------- state folders

def state_dir() -> str:
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def own_dir() -> str:
    return os.path.join(state_dir(), STATE_FOLDER)


def private_dir(path: str, what: str) -> str:
    """Make `path` (0700) when missing and check it: a real directory, this user's, closed to the group and others (a folder
    of this user that is open to others is closed with chmod, with a note)."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise NotConfigured("folder_unusable", "%s (%s)" % (what, e.strerror or e.__class__.__name__))
    if not stat.S_ISDIR(found.st_mode) or found.st_uid != os.getuid():
        raise NotConfigured("folder_unusable", what)
    if found.st_mode & 0o077:
        try:
            os.chmod(path, 0o700)
        except OSError:
            raise NotConfigured("folder_unusable", what) from None
        say("note: the %s %s was mode %04o; it is now 0700" % (what, path, stat.S_IMODE(found.st_mode)))
    return path


def work_root() -> str:
    state = private_dir(state_dir(), "state folder")
    return private_dir(os.path.join(private_dir(os.path.join(state, STATE_FOLDER), "renderer folder"), WORK_FOLDER), "work folder")


# ---------------------------------------------------------------- docker (the box's, behind this provider's own refusals)

def refusal_of(error, args=None):
    """The provider's own refusal for a ContainerError of the box: the kinds and codes this provider always gave."""
    code = error.code
    if code == "docker_timeout":
        return Refusal("docker_timeout", (args[0] if args else error.what)[:40])
    if code in ("docker_missing", "docker_unusable", "docker_daemon_unknown", "docker_daemon_not_local"):
        return NotConfigured(code, "docker")
    if code in ("bad_mount_path", "bad_mount"):
        return Refusal("bad_mount_path", error.what)
    if code in ("time_limit", "stopped"):
        return Refusal(code, "container")
    return Refusal(code if CODE.fullmatch(code) else "docker_failed", "docker")


def docker_environment(env=None) -> dict:
    return box.docker_environment(env)


def docker_binary() -> str:
    try:
        return box.docker_binary()
    except box.ContainerError as e:
        raise refusal_of(e) from None


def docker(args, timeout=PROBE_TIMEOUT):
    try:
        return box.docker(args, timeout)
    except box.ContainerError as e:
        raise refusal_of(e, args) from None


def require_local_daemon() -> None:
    """A recording, a transcript and a render must not cross a network: the daemon is a unix socket on this machine."""
    try:
        box.require_local_daemon()
    except box.ContainerError as e:
        raise refusal_of(e) from None


def require_docker() -> str:
    done = docker(["version", "--format", "{{.Server.Version}}"])
    if done.returncode != 0:
        raise NotConfigured("docker_not_answering", "docker")
    require_local_daemon()
    return done.stdout.strip()


def daemon_facts() -> dict:
    """{cpus, architecture} of the daemon (`docker info`): a container cannot be given more CPUs than it has, and the browser
    archive is the one for its architecture."""
    done = docker(["info", "--format", "{{.NCPU}} {{.Architecture}}"])
    parts = done.stdout.split()
    if done.returncode != 0 or len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) < 1:
        raise Refusal("docker_info_failed", "docker")
    return {"cpus": int(parts[0]), "architecture": parts[1]}


def inspect_image(reference: str):
    done = docker(["image", "inspect", reference])
    if done.returncode != 0:
        return None
    try:
        found = json.loads(done.stdout)[0]
        return {"id": found["Id"], "labels": (found.get("Config") or {}).get("Labels") or {}, "arch": found.get("Architecture")}
    except (ValueError, KeyError, IndexError, TypeError):
        raise Refusal("docker_image_unreadable", "docker") from None


def read_record():
    try:
        with open(os.path.join(own_dir(), BUILD_RECORD), encoding="utf-8") as f:
            record = json.load(f)
        return record if isinstance(record, dict) else None
    except (OSError, ValueError):
        return None


BUILD_COMMAND = "python3 providers/renderer/ffmpeg.py build --confirmed"


def check_image() -> dict:
    """The image this folder's definition describes, ready to run: it exists, carries this definition's hash and is the one
    `build` recorded (a tag can be pointed at another image; the id cannot). Raises NotConfigured."""
    tag, wanted = image_tag(), definition_hash()
    image = inspect_image(tag)
    if image is None:
        raise NotConfigured("image_not_built", tag)
    if image["labels"].get(LABEL_DEFINITION) != wanted:
        raise NotConfigured("image_stale", tag)
    record = read_record()
    if record is None or record.get("image_id") != image["id"]:
        raise NotConfigured("image_not_recorded", tag)
    return {"tag": tag, "id": image["id"], "definition": wanted, "arch": image["arch"],
            "chrome_version": image["labels"].get("org.openhora.chrome.version"),
            "debian_snapshot": image["labels"].get("org.openhora.debian-snapshot")}


# ---------------------------------------------------------------- build

def build_argv(pin: dict, platform: str, folder=HERE) -> list:
    spec = pin["platforms"][platform]
    args = ["build", "--tag", image_tag(folder), "--build-arg", "DEFINITION_HASH=" + definition_hash(folder),
            "--build-arg", "CHROME_VERSION=" + pin["version"], "--build-arg", "CHROME_URL=" + spec["url"],
            "--build-arg", "CHROME_SIZE=%d" % spec["size"], "--build-arg", "CHROME_MD5=" + spec["md5"],
            "--build-arg", "CHROME_SHA256=" + str(spec.get("sha256") or ""), "--build-arg", "CHROME_BINARY=" + spec["binary"],
            "--file", os.path.join(folder, "Dockerfile"), folder]
    return args


def write_private_json(path: str, value) -> None:
    tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:8])
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def build(pin: dict, platform: str, confirmed: bool, dry_run: bool) -> dict:
    """Build the image from this folder's definition. The one step that uses the network, at the person's word: it pulls the
    pinned base image, installs packages from the pinned Debian snapshot and downloads the pinned browser archive, which the
    build checks against the pin's size, md5 and sha256."""
    from _browser import require_sha256, spec_for
    if dry_run:
        spec_for(pin, platform)
    else:
        require_sha256(pin, platform)
    argv = build_argv(pin, platform)
    plan = {"command": ["docker"] + argv, "image": image_tag(), "definition": definition_hash(), "platform": platform,
            "chrome_version": pin["version"], "files": definition_files(),
            "chrome_sha256_pinned": bool(pin["platforms"][platform].get("sha256"))}
    if dry_run:
        return dict(plan, dry_run=True)
    if not confirmed:
        raise Refusal("needs_confirmation", "build")
    require_docker()
    private_dir(own_dir(), "renderer folder")
    say("building %s (Chrome for Testing %s); this downloads the base image, packages and the browser, and takes a while" % (plan["image"], pin["version"]))
    try:
        done = subprocess.run([docker_binary(), *argv], timeout=BUILD_TIMEOUT, env=docker_environment(), check=False, stdout=2, stderr=2)
    except subprocess.TimeoutExpired:
        raise Refusal("build_timeout", "build") from None
    if done.returncode != 0:
        raise Refusal("build_failed", "build")
    image = inspect_image(plan["image"])
    if image is None or image["labels"].get(LABEL_DEFINITION) != plan["definition"]:
        raise Refusal("build_unverified", "build")
    write_private_json(os.path.join(own_dir(), BUILD_RECORD),
                       {"image_tag": plan["image"], "image_id": image["id"], "definition": plan["definition"], "platform": platform,
                        "chrome_version": pin["version"], "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return dict(plan, dry_run=False, ok=True, image_id=image["id"], record=os.path.join(own_dir(), BUILD_RECORD))


# ---------------------------------------------------------------- one run

def mount_path(path: str, what: str) -> str:
    """An absolute path for a bind mount: ':' separates the fields of -v, and a control character has no place in a path
    that goes to a command line. Refused (bad_mount_path) otherwise."""
    try:
        return box.mount_path(path, what)
    except box.ContainerError as e:
        raise refusal_of(e) from None


def container_argv(name: str, image_id: str, inner_args: list, *, job_dir: str, out_dir: str, recording=None, memory_mb: int, cpus: int,
                   scratch_mb: int, deadline: int, platform=None, extra_mounts=(), cpuset=None) -> list:
    """The exact `docker run` command (a list; the first word is `docker`), written by the box. Every limit of the container is
    there; this function names the renderer's mounts, label and sizes. `extra_mounts` are (host, inside, mode) entries appended after
    the four fixed mounts; an `inside` path at or under a fixed mount point is refused. `cpuset` pins the cores."""
    mounts = ([(recording, MOUNT_RECORDING, "ro")] if recording else []) + [(job_dir, MOUNT_JOB, "ro"), (out_dir, MOUNT_OUT, "rw")]
    for host, inside, mode in extra_mounts:
        for fixed in ("/in", MOUNT_JOB, MOUNT_OUT, MOUNT_SCRATCH):
            if inside == fixed or inside.startswith(fixed.rstrip("/") + "/"):
                raise Refusal("bad_mount", inside)
        mounts.append((host, inside, mode))
    try:
        return box.argv(name, image_id, inner_args, label=LABEL_RUN, deadline=deadline, mounts=mounts, memory_mb=memory_mb, cpus=cpus,
                        scratch_mb=scratch_mb, pids_limit=PIDS_LIMIT, tmp_mb=TMP_SIZE_MB, platform=platform, cpuset=cpuset)
    except box.ContainerError as e:
        raise refusal_of(e) from None


def remove_container(name: str) -> None:
    box.remove(name)


Stopped = box.Stopped      # this process was asked to stop (SIGTERM or SIGINT) while the container ran


def run_container(argv: list, name: str, timeout: float):
    """Run the container (the box's `run`): (returncode, stderr). The stderr is at most MAX_STDERR bytes, the last ones (the end of
    a log says why a run failed). The container is removed by name when the timeout passes, when this process is stopped and when
    anything else goes wrong; on a normal end `--rm` has already removed it."""
    try:
        done = box.run(argv, name, timeout)
    except box.ContainerError as e:
        raise refusal_of(e) from None
    return done.returncode, done.stderr


def read_regular(path: str, limit: int, what: str) -> bytes:
    """The bytes of a regular file the container wrote, at most `limit`: opened without following a link and without blocking
    (a FIFO would hang a plain open), refused unless fstat says it is a regular file within the limit."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise Refusal("container_wrote_no_file", what) from None
    except OSError:
        raise Refusal("container_file_unreadable", what) from None
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode):
            raise Refusal("container_file_not_regular", what)
        if found.st_size > limit:
            raise Refusal("container_file_too_large", what)
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(limit + 1)[:limit]
    finally:
        os.close(fd)


def check_out_folder(folder: str, max_entries: int = MAX_OUT_ENTRIES) -> None:
    """What the container left in /out: a few regular files, none a link or a device, together within MAX_OUT_BYTES. The mount
    is writable, so the host looks before it reads anything. `max_entries`: a verb that writes more files says how many."""
    total, count = 0, 0
    for entry in os.scandir(folder):
        found = entry.stat(follow_symlinks=False)
        count += 1
        if not stat.S_ISREG(found.st_mode):
            raise Refusal("container_left_non_regular_file", "output")
        total += found.st_size
    if count > max_entries or total > MAX_OUT_BYTES:
        raise Refusal("container_left_too_much", "output")


def _same_or_collision(dest: str, digest: str) -> str:
    existing = hashlib.sha256()
    try:
        fd = os.open(dest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise Refusal("name_collision", "output") from None
    with os.fdopen(fd, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            existing.update(block)
    if existing.hexdigest() != digest:
        raise Refusal("name_collision", "output")
    return "replayed"


def copy_out(src: str, dest: str, *, max_bytes: int, mode: int, expect_sha256=None, exclusive=False) -> str:
    """Copy a file the container wrote to its destination through a temporary name: opened without following links, size
    capped, hashed while copied (compared with `expect_sha256` when given). `exclusive`: the destination is created with
    O_EXCL and never rewritten, an existing file with the same bytes is a replay. Returns "written" or "replayed"."""
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise Refusal("container_file_unreadable", os.path.basename(src)[:40]) from None
    folder = os.path.dirname(os.path.abspath(dest))
    os.makedirs(folder, mode=0o700, exist_ok=True)
    tmp = os.path.join(folder, ".copy-%s.tmp" % uuid.uuid4().hex[:10])
    h, total = hashlib.sha256(), 0
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_size > max_bytes:
            raise Refusal("container_file_not_regular", os.path.basename(src)[:40])
        with os.fdopen(fd, "rb", closefd=False) as fin, open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as fout:
            for block in iter(lambda: fin.read(1 << 20), b""):
                total += len(block)
                if total > max_bytes:
                    raise Refusal("container_file_too_large", os.path.basename(src)[:40])
                h.update(block)
                fout.write(block)
            fout.flush()
            os.fsync(fout.fileno())              # the bytes are on disk before the name is made
        if expect_sha256 and h.hexdigest() != expect_sha256:
            raise Refusal("container_file_differs", os.path.basename(src)[:40])
        os.chmod(tmp, mode)
        if exclusive:
            try:
                os.link(tmp, dest)
            except FileExistsError:
                return _same_or_collision(dest, h.hexdigest())
            except OSError:                    # a file system without hard links: create the name exclusively and copy into it
                try:
                    out_fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                except FileExistsError:
                    return _same_or_collision(dest, h.hexdigest())
                try:
                    with os.fdopen(out_fd, "wb") as fout, open(tmp, "rb") as fin:
                        shutil.copyfileobj(fin, fout, 1 << 20)
                        fout.flush()
                        os.fsync(fout.fileno())
                    os.chmod(dest, mode)
                except BaseException:
                    os.unlink(dest)
                    raise
            return "written"
        os.replace(tmp, dest)
        return "written"
    finally:
        os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- leftovers of a run that was killed

def reap_containers(now=None) -> list:
    try:
        return box.reap(LABEL_RUN, now)
    except box.ContainerError as e:
        raise refusal_of(e) from None


def reap_folders(now=None) -> int:
    now = time.time() if now is None else now
    root, removed = work_root(), 0
    for entry in list(os.scandir(root)):
        try:
            if entry.name.startswith(JOB_PREFIX) and entry.is_dir(follow_symlinks=False) \
                    and entry.stat(follow_symlinks=False).st_mtime < now - (MAX_TIMEOUT + 600):
                shutil.rmtree(entry.path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


# ---------------------------------------------------------------- what the host prints of a container's result

CODE = re.compile(r"[a-z0-9_]{1,60}")
FIELD = re.compile(r"[A-Za-z0-9_.\[\]:\- ]{0,80}")
SAFE_TEXT = re.compile(r"[^\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]{0,200}")
S, I, N, B, FLD, COD = "str", "int", "num", "bool", "field", "code"


def opt(schema):
    return ("opt", schema)


def lst(schema, limit=2000):
    return ("list", schema, limit)


def dct(**keys):
    return ("dict", keys)


def mp(schema):
    return ("map", schema)


def sanitise(value, schema, where="result"):
    """`value` rebuilt from a closed schema: only the listed keys of an object survive, every leaf has the listed type (a string
    is short and holds no control character, a number is finite, an integer is an integer), a list is bounded. Anything else is
    refused with a closed code: the host prints what it has understood, never what the container wrote."""
    bad = Refusal("container_result_invalid", where[:40])
    if isinstance(schema, tuple):
        kind = schema[0]
        if kind == "opt":
            return None if value is None else sanitise(value, schema[1], where)
        if kind == "list":
            if not isinstance(value, list) or len(value) > schema[2]:
                raise bad
            return [sanitise(v, schema[1], where) for v in value]
        if kind == "dict":
            if not isinstance(value, dict):
                raise bad
            return {k: sanitise(value[k], sub, "%s.%s" % (where, k)) for k, sub in schema[1].items() if k in value}
        if kind == "map":
            if not isinstance(value, dict) or len(value) > 2000:
                raise bad
            return {sanitise(k, FLD, where): sanitise(v, schema[1], where) for k, v in value.items()}
        raise bad
    if schema == S:
        if not isinstance(value, str) or not SAFE_TEXT.fullmatch(value):
            raise bad
        return value
    if schema == FLD:
        if not isinstance(value, str) or not FIELD.fullmatch(value):
            raise bad
        return value
    if schema == COD:
        if not isinstance(value, str) or not CODE.fullmatch(value):
            raise bad
        return value
    if schema == I:
        if not isinstance(value, int) or isinstance(value, bool):
            raise bad
        return value
    if schema == N:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise bad
        return value
    if schema == B:
        if not isinstance(value, bool):
            raise bad
        return value
    raise bad


FACTS = dct(video_start=N, audio_start=N, width=I, height=I, rotation=I, fps=N, duration=N, has_audio=B, codec=S, pix_fmt=opt(S), color_space=opt(S),
            color_transfer=opt(S), color_primaries=opt(S), color_range=opt(S), bytes=I, audio_codec=opt(S), sha256=S)
OUTPUT = dct(container=S, codec=S, profile=opt(S), pix_fmt=opt(S), width=I, height=I, fps=N, duration=N, bytes=I, audio_codec=opt(S), faststart=B,
             color=lst(opt(S), 8), frames=opt(S))
PROBLEMS = lst(dct(beat=opt(I), field=FLD, code=COD), 50)
RESULT_SCHEMAS = {
    "selfcheck": dct(ok=B, ffmpeg=S, ffprobe=S, missing=lst(S, 50), python=S, browser=S, libass=B, container=B),
    "analyse": dct(ok=B, duration=N, sha256=S, silences=opt(I), has_audio=B),
    "analysis_doc": dct(ok=B, schema_version=I, facts=FACTS, silences=opt(lst(dct(start=N, end=N), 20000)), noise_db=N, min_silence=N),
    "base": dct(ok=B, fps=I, kept_ranges=I, out_seconds=N, source_seconds=N, words=I, caption_chunks=I,
                normalisation=dct(words=I, dropped_words=I, dropped_segments=lst(dct(segment=I, words=I, seconds=N), 500), zero_length_words=I,
                                  spread_runs=I, estimated_words=I, clamped_starts=I, retimed_words=lst(dct(index=I, **{"from": lst(N, 2), "to": lst(N, 2)}), 2000), unplaced_words=lst(dct(index=I, start=N, end=N), 2000)),
                font_fallbacks=lst(dct(role=S, asked=S, used=S, reason=S), 20), proposals=lst(dct(id=S, kind=S, seconds=N, confirmed=B), 100),
                face_box=dct(x=I, y=I, w=I, h=I), zoom=dct(mode=S, factor=N, push_in=N)),
    "align": dct(ok=B, beats=I, overlays=I, layouts=I, unmatched=lst(I, 100), slots=lst(S, 100), fallbacks=lst(dct(beat=I, **{"from": S, "to": S}), 100),
                 scores=mp(N), reordered=lst(I, 100)),
    "check": dct(ok=B, mentions=lst(S, 500), out_seconds=N, words=I, overlays=I, layouts=I),
    "cover": dct(ok=B, offset_ms=I, sha256=S),
    "still": dct(ok=B, at_ms=I, sha256=S, width=I, height=I, bytes=I),
    "verify": dct(ok=B, sha256=S, output=OUTPUT),
    "storyboard": dct(ok=B, beats=lst(dct(beat=I, preset=S, file=S, sha256=S, frame=I), 12), skipped=lst(I, 100), words=I, frame_jobs=I, frames_checked=I, jobs=I,
                      sheet=dct(file=S, sha256=S, tiles=I, columns=I, width=I, height=I), face_box=dct(x=I, y=I, w=I, h=I), fonts=mp(S), blocks=mp(S), blocks_sha256=S,
                      font_fallbacks=lst(dct(role=S, asked=S, used=S, reason=S), 20), mentions=lst(S, 500), browser=opt(S), browser_sandbox=opt(S)),
    "proxy": dct(ok=B, sha256=S, bytes=I, seconds=N, width=I, height=I, fps=I, has_audio=B),
    "encode": dct(ok=B, sha256=S, out_seconds=N, out_frames=I, intermediate_sha256=S),
    "hf-page": dct(ok=B, page_sha256=S, vars_sha256=S, clips=I, zooms=I, duration=N, fps=I, layers=lst(S, 4)),
    "render": dct(ok=B, dry_run=B, out_seconds=N, out_frames=I, frame_jobs=I, jobs=I, time_limit_seconds=I, layers=lst(S, 4),
                  beats_drawn=lst(dct(id=S, preset=S, block=opt(S), start_frame=I, end_frame=I), 100), beats_dropped=lst(S, 100), unmatched_beats=lst(I, 100),
                  mentions=lst(S, 500), fonts=mp(S), blocks=mp(S), blocks_sha256=S, estimated_bytes=I, sha256=S, bytes=I, output=OUTPUT, seconds=mp(N),
                  browser=opt(S), browser_sandbox=opt(S), frames_rendered=I, frames_reused=I, cover=opt(dct(offset_ms=I, sha256=S))),
}
