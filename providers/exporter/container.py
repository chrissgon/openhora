#!/usr/bin/env python3
"""The exporter of documents (class exporter:document): the converter's twin for the other direction (package P8). The converter
(providers/converter/container.py) turns a file into text; this turns a task's text into a file, CSV, XLSX, DOCX or PDF, by adopted
open tools run in a container on this machine, with no model and no network. A class the runtime uses and no skill may require, like
the converter and the messenger: on purpose it is not in contracts/environment.md, and in providers/resolve.py it is a role (`ROLES`)
and not a listed class (`LISTED`). runtime/step_export.py is its one caller, through the resolver; the person runs it by hand to
build the image and to check it. One implementation, this file.

What the container holds (providers/exporter/Dockerfile): pandoc and openpyxl from a dated snapshot of the Debian archive, on a base
image pinned by digest, WeasyPrint and what it needs from requirements.lock (wheels only, installed by hash), the DejaVu fonts, and
providers/exporter/_render.py, the program that drives them and that holds the formula guard of finding S9 (its text says what the
guard does). The tools are adopted, none is rewritten (principle 14). Why WeasyPrint for the PDF and not the short-video renderer's
headless browser: that browser belongs to an image built for video frames, on another branch; a document needs HTML and CSS printed
on pages, which is what WeasyPrint does, in Python, with no JavaScript engine to run on text that came from a task. Why not the
Debian package of WeasyPrint: it depends on python3-cffi, which pulls a compiler, the Python headers and a numerical stack (an image
of 1.27 GB against 506 MB). The image is built here by a verb the person starts (`build --confirmed`), named by the hash of its
definition, and never pulled when a render runs.

How a render runs (the limits are providers/_container.py's: no network, a read-only root, every capability dropped, no new
privileges, a limit on processes, memory and CPUs, and a memory-backed /tmp and /scratch with no exec):

  - the input is a file this module writes into a private folder (0700, created exclusively, 0600) and mounts read-only at /in/input;
    nothing else of the host is visible, and no environment variable passes;
  - the program works in /scratch and prints its result on its standard output as frames; the host reads at most STDOUT_CAP bytes
    of it, and a container that writes more is killed and removed;
  - the host parses the frames with fixed rules (parse_frames): the names are output.<format> and info.json, the sizes are capped, a
    name twice is refused. Nothing a container leaves as a folder, a link or a pipe can come back, because nothing is copied from
    its file system but this stream. The caller reads the out folder back with its own checks (runtime/step_export.py).

Usage:
  python3 providers/exporter/container.py --help
  python3 providers/exporter/container.py --check
  python3 providers/exporter/container.py build (--dry-run | --confirmed)
  python3 providers/exporter/container.py render --format <csv|xlsx|docx|pdf> --input <file> --out-dir <folder> [--timeout <seconds>]

  --check     exit 0 when docker is usable on this machine, its daemon is local and the image of the current definition exists;
              3 when it is not (the reason on stderr: build it with `build --confirmed`); 1 for another failure
  build       docker build of the definition into the tag openhora-render:<12 characters of the definition's hash>; the base image
              is pulled by the build, as a person's explicit step; --dry-run prints the command
  render      the folder must exist, be this user's and mode 0700, and be empty; it gets output.<format> and prints
              {"renderer", "format", "output", "bytes", "image", "counts", "tool_versions"}

Exit codes: 0 ok, 1 failed (the render, the container, the docker client), 2 usage, 3 not configured (no docker, a remote daemon, no
image). Standard library only; the docker command-line client is the one outside tool.
"""
from __future__ import annotations

import hashlib
import json
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
import _container as box  # noqa: E402  (providers/_container.py: the one home of the container's lifecycle and limits)

CLASS = "exporter:document"
IMAGE_REPOSITORY = "openhora-render"
LABEL_DEFINITION = "org.openhora.definition"
LABEL_RUN = "org.openhora.render"
DEFINITION_DIR = HERE
DEFINITION_FILES = ("Dockerfile", ".dockerignore", "_render.py", "requirements.lock")
FORMATS = ("csv", "xlsx", "docx", "pdf")
INPUT_CAP = 1024 * 1024                  # the program's own CAP_INPUT
OUTPUT_CAP = 8 * 1024 * 1024             # the program's own CAP_OUTPUT
INFO_CAP = 16 * 1024
STDOUT_CAP = OUTPUT_CAP + INFO_CAP + 4096
MEMORY_MB, CPUS, SCRATCH_MB, PIDS = 1024, 2, 256, 128
DEFAULT_TIMEOUT, MAX_TIMEOUT = 120, 600
BUILD_TIMEOUT = 3600
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
FRAME_START, FRAME_END = b"OHF1\n", b"END\n"
FRAME_HEAD = re.compile(rb"FILE ([a-z.]{1,20}) ([0-9]{1,9})\n")


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAILED):
        super().__init__(message)
        self.code = code


# --- the definition and the image -----------------------------------------------------------------------------------------------


def definition_hash(folder: str = DEFINITION_DIR) -> str:
    """The sha256 of the files the image is built from, by name and content, in a fixed order."""
    digest = hashlib.sha256()
    for name in sorted(DEFINITION_FILES):
        with open(os.path.join(folder, name), "rb") as f:
            digest.update(name.encode() + b"\0" + f.read() + b"\0")
    return digest.hexdigest()


def image_tag(folder: str = DEFINITION_DIR) -> str:
    return f"{IMAGE_REPOSITORY}:{definition_hash(folder)[:12]}"


def image_id(tag: str) -> str:
    """The id of the image of this definition, or ProviderError (3) when it has not been built here."""
    try:
        done = box.docker(["image", "inspect", "--format", "{{.Id}}", tag])
    except box.ContainerError as e:
        raise ProviderError(f"docker cannot be used here ({e.code})", EXIT_NOT_CONFIGURED) from None
    found = done.stdout.strip()
    if done.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", found):
        raise ProviderError(f"the renderer image {tag} is not built on this machine: run "
                            "`python3 providers/exporter/container.py build --confirmed` (once; it needs the network)",
                            EXIT_NOT_CONFIGURED)
    return found


def local_daemon() -> None:
    try:
        box.require_local_daemon()
    except box.ContainerError as e:
        raise ProviderError(f"the docker daemon is not usable as a local one ({e.code})", EXIT_NOT_CONFIGURED) from None


# --- the frames ---------------------------------------------------------------------------------------------------------------------


def parse_frames(data: bytes, fmt: str) -> dict:
    """{"output": bytes, "info": dict} from what a container printed, or ProviderError. The rules: the stream starts with FRAME_START
    and ends with FRAME_END and nothing follows it; each record is `FILE <name> <size>\\n` and exactly <size> bytes; the names are
    output.<fmt> and info.json, each once and nothing else; the output is at most OUTPUT_CAP bytes and not empty, info.json at most
    INFO_CAP. Anything else is the container's fault and nothing is kept."""
    if fmt not in FORMATS:
        raise ProviderError(f"the format is one of {', '.join(FORMATS)}", EXIT_USAGE)
    if not data.startswith(FRAME_START):
        raise ProviderError("the container's output is not a render (no start marker)")
    at, found = len(FRAME_START), {}
    while True:
        if data.startswith(FRAME_END, at):
            if at + len(FRAME_END) != len(data):
                raise ProviderError("the container wrote after the end marker")
            break
        head = FRAME_HEAD.match(data, at)
        if head is None:
            raise ProviderError("the container's output is cut or malformed")
        name, size = head.group(1).decode("ascii"), int(head.group(2))
        if name not in (f"output.{fmt}", "info.json") or name in found:
            raise ProviderError(f"the container wrote an output that is not taken: {name!r}")
        if size > (INFO_CAP if name == "info.json" else OUTPUT_CAP):
            raise ProviderError(f"the container's output {name} is {size} bytes, over its cap")
        start = head.end()
        if start + size > len(data):
            raise ProviderError("the container's output is cut short")
        found[name] = data[start:start + size]
        at = start + size
    output = found.get(f"output.{fmt}")
    if not output:
        raise ProviderError("the container wrote no output")
    try:
        about = json.loads(found.get("info.json", b"{}").decode("utf-8"))
    except ValueError:
        about = {}
    return {"output": output, "info": about if isinstance(about, dict) else {}}


def check_out_dir(path: str) -> None:
    """The folder the output goes to: a real folder (not a link), this user's, mode 0700, empty."""
    try:
        info = os.lstat(path)
    except OSError:
        raise ProviderError(f"--out-dir {path} does not exist", EXIT_USAGE) from None
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, "getuid") and info.st_uid != os.getuid()) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProviderError("--out-dir must be a real folder of this user with mode 0700", EXIT_USAGE)
    if os.listdir(path):
        raise ProviderError("--out-dir must be empty", EXIT_USAGE)


# --- the render ---------------------------------------------------------------------------------------------------------------------


def command_for(name: str, image: str, input_path: str, fmt: str, timeout: int) -> list:
    """The exact `docker run` command of one render (every limit is _container.argv's)."""
    return box.argv(name, image, ["python3", "-I", "/opt/render/_render.py", "--format", fmt, "--input", "/in/input"],
                    label=LABEL_RUN, deadline=int(time.time()) + timeout + 60, mounts=[(input_path, "/in/input", "ro")],
                    memory_mb=MEMORY_MB, cpus=CPUS, scratch_mb=SCRATCH_MB, pids_limit=PIDS)


def _private_input(data: bytes) -> tuple:
    """(folder, path) of a private copy of the input: a folder made 0700 and a file in it created exclusively, 0600."""
    folder = tempfile.mkdtemp(prefix="openhora-render-")
    fd = os.open(os.path.join(folder, "input"), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return folder, os.path.join(folder, "input")


def render(fmt: str, data: bytes, timeout: int = DEFAULT_TIMEOUT, run=None, image=None) -> dict:
    """One render: {"renderer", "format", "output": bytes, "bytes", "image", "counts", "tool_versions"}. `run(command, name, timeout,
    stdout_cap=)` and `image` are the seams a test replaces; by default providers/_container.py's run and the image of this
    definition. ProviderError: 2 for a bad format, input or timeout, 3 when docker or the image is not usable, 1 when the container
    fails or prints what is not a render."""
    if fmt not in FORMATS:
        raise ProviderError(f"the format is one of {', '.join(FORMATS)}", EXIT_USAGE)
    if not isinstance(data, (bytes, bytearray)) or not data.strip():
        raise ProviderError("the input is empty", EXIT_USAGE)
    if len(data) > INPUT_CAP:
        raise ProviderError(f"the input is {len(data)} bytes, over the {INPUT_CAP} a render takes", EXIT_USAGE)
    if not 1 <= timeout <= MAX_TIMEOUT:
        raise ProviderError(f"--timeout is from 1 to {MAX_TIMEOUT} seconds", EXIT_USAGE)
    if image is None:
        local_daemon()
        image = image_id(image_tag())
    folder, path = _private_input(bytes(data))
    try:
        name = f"openhora-render-{uuid.uuid4().hex[:16]}"
        command = command_for(name, image, path, fmt, timeout)
        try:
            done = (run or box.run)(command, name, timeout, stdout_cap=STDOUT_CAP)
        except box.ContainerError as e:
            raise ProviderError(f"the render did not finish ({e.code})") from None
        if done.returncode != 0:
            tail = " ".join((done.stderr or "").split())[-300:]
            raise ProviderError(f"the render failed: {tail or 'exit ' + str(done.returncode)}")
        parsed = parse_frames(done.stdout, fmt)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    about = parsed["info"]
    return {"renderer": "document", "format": fmt, "output": parsed["output"], "bytes": len(parsed["output"]), "image": image,
            "counts": about.get("counts") if isinstance(about.get("counts"), dict) else {},
            "tool_versions": about.get("tool_versions") if isinstance(about.get("tool_versions"), dict) else {}}


# --- the verbs ----------------------------------------------------------------------------------------------------------------------


def cmd_check(args: dict) -> int:
    local_daemon()
    tag = image_tag()
    print(json.dumps({"ok": True, "image": image_id(tag), "tag": tag, "definition": definition_hash()}))
    return EXIT_OK


def cmd_build(args: dict) -> int:
    if bool(args.get("--dry-run")) == bool(args.get("--confirmed")):
        raise ProviderError("give --dry-run to see the build, or --confirmed to make it", EXIT_USAGE)
    digest = definition_hash()
    command = ["docker", "build", "--label", f"{LABEL_DEFINITION}={digest}", "--build-arg", f"DEFINITION_HASH={digest}",
               "-t", image_tag(), DEFINITION_DIR]
    if args.get("--dry-run"):
        print(json.dumps({"dry_run": True, "would": {"command": command, "tag": image_tag()}}))
        return EXIT_OK
    local_daemon()
    try:
        done = subprocess.run([box.docker_binary()] + command[1:], env=box.docker_environment(), timeout=BUILD_TIMEOUT, check=False,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (box.ContainerError, OSError, subprocess.SubprocessError) as e:
        raise ProviderError(f"the build did not run ({type(e).__name__})") from None
    if done.returncode != 0:
        tail = " ".join(done.stderr.decode("utf-8", "replace").split())[-400:]
        raise ProviderError(f"the build failed: {tail}")
    print(json.dumps({"built": True, "tag": image_tag(), "image": image_id(image_tag())}))
    return EXIT_OK


def cmd_render(args: dict) -> int:
    for flag in ("--format", "--input", "--out-dir"):
        if not args.get(flag):
            raise ProviderError(f"{flag} is required", EXIT_USAGE)
    try:
        timeout = int(args.get("--timeout") or DEFAULT_TIMEOUT)
    except ValueError:
        raise ProviderError("--timeout is a whole number of seconds", EXIT_USAGE) from None
    path = args["--input"]
    if not os.path.isabs(path):
        raise ProviderError("--input is an absolute path", EXIT_USAGE)
    try:
        info = os.lstat(path)
    except OSError:
        raise ProviderError(f"--input {path} does not exist", EXIT_USAGE) from None
    if not stat.S_ISREG(info.st_mode) or info.st_size > INPUT_CAP:
        raise ProviderError(f"--input must be a regular file of at most {INPUT_CAP} bytes", EXIT_USAGE)
    check_out_dir(args["--out-dir"])
    with open(path, "rb") as f:
        data = f.read(INPUT_CAP + 1)
    made = render(args["--format"], data, timeout)
    fd = os.open(args["--out-dir"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        mark = os.open(f"output.{made['format']}", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(mark, "wb") as f:
            f.write(made["output"])
    finally:
        os.close(fd)
    print(json.dumps({**{k: v for k, v in made.items() if k != "output"}, "output": f"output.{made['format']}"}))
    return EXIT_OK


VERBS = {"build": cmd_build, "render": cmd_render}
VALUE_FLAGS = ("--format", "--input", "--out-dir", "--timeout")
SWITCHES = ("--dry-run", "--confirmed", "--check")


def parse_args(argv: list) -> tuple:
    verb, args, i = None, {}, 0
    while i < len(argv):
        word = argv[i]
        if word in VALUE_FLAGS:
            if i + 1 >= len(argv):
                raise ProviderError(f"{word} needs a value", EXIT_USAGE)
            args[word] = argv[i + 1]
            i += 2
        elif word in SWITCHES:
            args[word] = True
            i += 1
        elif verb is None and word in VERBS:
            verb = word
            i += 1
        else:
            raise ProviderError(f"unknown argument {word[:60]!r}; see --help", EXIT_USAGE)
    return verb, args


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return EXIT_OK if argv else EXIT_USAGE
    try:
        verb, args = parse_args(argv)
        if args.get("--check"):
            if verb is not None:
                raise ProviderError("--check takes no verb", EXIT_USAGE)
            return cmd_check(args)
        if verb is None:
            raise ProviderError("give a verb or --check; see --help", EXIT_USAGE)
        return VERBS[verb](args)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    except box.ContainerError as e:
        print(f"error: the container helper refused ({e.code})", file=sys.stderr)
        return EXIT_NOT_CONFIGURED if e.code in ("docker_missing", "docker_unusable") else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
