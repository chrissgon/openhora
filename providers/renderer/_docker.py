"""The renderer's container: the image, its build, and one run of it. Standard library only; the docker command-line client is
the one outside tool. The pattern is the transcriber's (providers/transcriber/): a provider-owned definition built by a verb the
person starts, an image run by its recorded id, and every limit of the container in code with a test that names it.

The container (tests/test_renderer_docker.py names each limit): no network, a read-only root file system, every capability
dropped and no new privileges, a non-root user, a limit on processes, memory (swap included) and CPUs, no environment variable of
the host, the recording and a staged job folder mounted read-only, one folder mounted read-write for the output, memory-backed
/tmp and /scratch with no exec, an image that is never pulled at run time, and a timeout after which the client is killed and
the container removed by name (also when this process is stopped). The daemon must be local.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from _browser import NotConfigured
from _text import Refusal

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGE_REPOSITORY = "openhora-renderer"
LABEL_DEFINITION = "org.openhora.definition"
LABEL_RUN, LABEL_DEADLINE = "org.openhora.renderer", "org.openhora.renderer.deadline"
STATE_ENV = "OPENHORA_STATE_DIR"
STATE_FOLDER, BUILD_RECORD, WORK_FOLDER, JOB_PREFIX = "renderer", "image.json", "work", ".job-"

# What the image's definition covers: its text, every module and data file the container runs, the templates, the fonts.
DEFINITION_FILES = ("Dockerfile", ".dockerignore", "renderer-presets.json", "browser-pin.json", "edl.schema.json")
DEFINITION_GLOBS = (("", ".py"), ("templates", ""), ("assets/fonts", ""))     # (folder, suffix filter) under HERE
HOST_ONLY = ("_docker.py", "_browser.py")      # underscore modules that only the host side uses: not in the image

# The limits of one container.
PIDS_LIMIT = 512
TMP_SIZE_MB = 256
DEFAULT_SCRATCH_MB, DEFAULT_MEMORY_MB, DEFAULT_CPUS = 2048, 6144, 4
MIN_MEMORY_MB, MAX_MEMORY_MB, MAX_SCRATCH_MB = 1024, 32768, 8192
MOUNT_RECORDING, MOUNT_JOB, MOUNT_OUT, MOUNT_SCRATCH = "/in/recording", "/job", "/out", "/scratch"
BUILD_TIMEOUT, PROBE_TIMEOUT, STOP_GRACE = 3600, 60, 120
MAX_TIMEOUT = 2400                       # seconds, the longest a container may run (the render limit is 1800)
MAX_OUT_BYTES = 450 * 1024 * 1024        # everything the container may leave in /out
MAX_OUT_ENTRIES = 8
MAX_RESULT_BYTES = 4 * 1024 * 1024
STDERR_TAIL = 300
DOCKER_CLIENT_ENV = ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME",
                     "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")


def say(text):
    print(text, file=sys.stderr)


def tail(text, limit=STDERR_TAIL):
    return " ".join((text or "").split())[-limit:]


# ---------------------------------------------------------------- the definition

def definition_files(folder=HERE) -> list:
    """The files the image is built from, as sorted paths relative to the folder."""
    found = set(n for n in DEFINITION_FILES if os.path.isfile(os.path.join(folder, n)))
    for sub, suffix in DEFINITION_GLOBS:
        base = os.path.join(folder, sub) if sub else folder
        for root, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", "container")] if not sub else dirs
            if not sub and root != base:
                dirs[:] = []
            for n in names:
                if not suffix or n.endswith(suffix):
                    if not sub and (not n.startswith("_") or n in HOST_ONLY):
                        continue          # the host side (ffmpeg.py and its two modules) is not in the image
                    found.add(os.path.relpath(os.path.join(root, n), folder))
    return sorted(found)


def definition_hash(folder=HERE) -> str:
    h = hashlib.sha256()
    for name in definition_files(folder):
        with open(os.path.join(folder, name), "rb") as f:
            h.update(name.encode() + b"\0" + f.read() + b"\0")
    return h.hexdigest()


def image_tag(folder=HERE) -> str:
    return "%s:%s" % (IMAGE_REPOSITORY, definition_hash(folder)[:12])


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


# ---------------------------------------------------------------- docker

def docker_environment(env=None) -> dict:
    env = os.environ if env is None else env
    return {k: env[k] for k in DOCKER_CLIENT_ENV if env.get(k)}


def docker_binary() -> str:
    found = shutil.which("docker")
    if not found:
        raise NotConfigured("docker_missing", "docker")
    return found


def docker(args, timeout=PROBE_TIMEOUT):
    try:
        return subprocess.run([docker_binary(), *args], capture_output=True, text=True, errors="replace", timeout=timeout,
                              env=docker_environment(), check=False)
    except subprocess.TimeoutExpired:
        raise Refusal("docker_timeout", args[0]) from None
    except OSError:
        raise NotConfigured("docker_unusable", "docker") from None


def require_local_daemon() -> None:
    """A recording, a transcript and a render must not cross a network: the daemon is a unix socket on this machine."""
    host = os.environ.get("DOCKER_HOST")
    if not host:
        done = docker(["context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
        host = done.stdout.strip() if done.returncode == 0 else ""
        if not host:
            raise NotConfigured("docker_daemon_unknown", "docker")
    if not host.startswith("unix://"):
        raise NotConfigured("docker_daemon_not_local", "docker")


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

BAD_PATH = re.compile(r"[:\x00-\x1f\x7f]")


def mount_path(path: str, what: str) -> str:
    """An absolute path for a bind mount: ':' separates the fields of -v, and a control character has no place in a path
    that goes to a command line. Refused (usage) otherwise."""
    if not isinstance(path, str) or not os.path.isabs(path) or BAD_PATH.search(path):
        raise Refusal("bad_mount_path", what)
    return path


def container_argv(name: str, image_id: str, inner_args: list, *, job_dir: str, out_dir: str, recording=None, memory_mb: int, cpus: int,
                   scratch_mb: int, deadline: int, platform=None) -> list:
    """The exact `docker run` command (a list; the first word is `docker`). Every limit of the container is here."""
    platform = sys.platform if platform is None else platform
    argv = ["docker", "run", "--rm", "--init", "--pull", "never", "--name", name,
            "--label", "%s=1" % LABEL_RUN, "--label", "%s=%d" % (LABEL_DEADLINE, deadline),
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(PIDS_LIMIT), "--memory", "%dm" % memory_mb, "--memory-swap", "%dm" % memory_mb, "--cpus", str(cpus),
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=%dm" % TMP_SIZE_MB,
            "--tmpfs", "%s:rw,noexec,nosuid,nodev,size=%dm,mode=1777" % (MOUNT_SCRATCH, scratch_mb)]
    if platform.startswith("linux"):       # a bind mount keeps numeric owners there; elsewhere the runtime maps them
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    if recording:
        argv += ["-v", "%s:%s:ro" % (mount_path(recording, "recording"), MOUNT_RECORDING)]
    argv += ["-v", "%s:%s:ro" % (mount_path(job_dir, "job folder"), MOUNT_JOB), "-v", "%s:%s:rw" % (mount_path(out_dir, "output folder"), MOUNT_OUT),
             image_id, *inner_args]
    return argv


def remove_container(name: str) -> None:
    try:
        docker(["rm", "-f", name], timeout=60)
    except Refusal:
        pass


class Stopped(Exception):
    pass


def run_container(argv: list, name: str, timeout: float):
    """Run the container: (returncode, stderr). The container is removed by name when the timeout passes, when this process is
    stopped and when anything else goes wrong; on a normal end `--rm` has already removed it."""
    def stop(signum, frame):
        raise Stopped()

    previous = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous.append((sig, signal.signal(sig, stop)))
        except ValueError:
            pass
    proc, finished = None, False
    try:
        try:
            proc = subprocess.Popen([docker_binary()] + argv[1:], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True, errors="replace", env=docker_environment(), start_new_session=True)
        except OSError:
            raise NotConfigured("docker_unusable", "docker") from None
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise Refusal("time_limit", "container") from None
        finished = True
        return proc.returncode, stderr or ""
    except Stopped:
        raise Refusal("stopped", "container") from None
    finally:
        for sig, _ in previous:
            signal.signal(sig, signal.SIG_IGN)
        if not finished:
            if proc is not None and proc.poll() is None:      # the client first: it must not outlive the container
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()
            remove_container(name)
        for sig, handler in previous:
            signal.signal(sig, handler)


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


def check_out_folder(folder: str) -> None:
    """What the container left in /out: a few regular files, none a link or a device, together within MAX_OUT_BYTES. The mount
    is writable, so the host looks before it reads anything."""
    total, count = 0, 0
    for entry in os.scandir(folder):
        found = entry.stat(follow_symlinks=False)
        count += 1
        if not stat.S_ISREG(found.st_mode):
            raise Refusal("container_left_non_regular_file", "output")
        total += found.st_size
    if count > MAX_OUT_ENTRIES or total > MAX_OUT_BYTES:
        raise Refusal("container_left_too_much", "output")


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
        if expect_sha256 and h.hexdigest() != expect_sha256:
            raise Refusal("container_file_differs", os.path.basename(src)[:40])
        os.chmod(tmp, mode)
        if exclusive:
            try:
                os.link(tmp, dest)
            except FileExistsError:
                existing = hashlib.sha256()
                with open(dest, "rb") as fh:
                    for block in iter(lambda: fh.read(1 << 20), b""):
                        existing.update(block)
                if existing.hexdigest() != h.hexdigest():
                    raise Refusal("name_collision", "output") from None
                return "replayed"
            return "written"
        os.replace(tmp, dest)
        return "written"
    finally:
        os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- leftovers of a run that was killed

def reap_containers(now=None) -> list:
    now = time.time() if now is None else now
    done = docker(["ps", "-a", "--filter", "label=%s=1" % LABEL_RUN, "--format", '{{.ID}} {{.Label "%s"}}' % LABEL_DEADLINE])
    if done.returncode != 0:
        raise Refusal("docker_ps_failed", "docker")
    removed = []
    for line in done.stdout.splitlines():
        parts = line.split()
        if not parts or not re.fullmatch(r"[0-9a-f]{6,64}", parts[0]):
            continue
        deadline = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if deadline < now and docker(["rm", "-f", parts[0]], timeout=60).returncode == 0:
            removed.append(parts[0])
    return removed


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
