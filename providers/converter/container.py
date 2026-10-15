#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The converter of documents (class converter:document): PDF, Word, spreadsheet, presentation, HTML, CSV and plain text to text, by adopted open
tools run in a container on this machine, and nothing else. A class the runtime uses, not one a skill may require (like the
messenger): the runtime's sources module (runtime/sources.py) is its one caller, and it is on purpose not in
contracts/environment.md.

What the container holds (providers/converter/Dockerfile): poppler's pdftotext and pandoc from a dated snapshot of the Debian archive,
on a base image pinned by digest; openpyxl and Microsoft's MarkItDown (presentations only) in a virtual environment installed from
providers/converter/requirements.lock, every file checked against its sha256; and providers/converter/_inner.py, the program that
drives them. The tools are adopted, none is rewritten (principle 14). The image is built here by a verb the person starts (`build --confirmed`),
named by the hash of its definition, and never pulled when a conversion runs.

How a conversion runs (the limits are providers/_container.py's: no network, a read-only root, every capability dropped, no new
privileges, a limit on processes, memory and CPUs, and a memory-backed /tmp and /scratch with no exec):

  - the input is mounted read-only at /in/input; nothing else of the host is visible, and no environment variable passes;
  - the program works in /scratch, a memory-backed folder of a fixed size (SCRATCH_MB), and prints its result on its standard
    output as frames (_inner.py, the module text); the host reads at most STDOUT_CAP bytes of it, and a container that writes
    more is killed and removed;
  - the host parses the frames with fixed rules (parse_frames): the names are from OUTPUT_NAMES, the sizes and the count are
    capped, a name twice is refused; it writes each output into the out folder it was given, a new regular file at mode 0600
    created with O_EXCL and O_NOFOLLOW. Nothing a container leaves as a folder, a link or a pipe can come back, because nothing is
    copied from its file system but this stream. The caller reads the out folder back with its own checks (runtime/sources.py,
    collect_outputs, limit L24) and scans the converted text for credentials (limit L14's scan).

Usage:
  python3 providers/converter/container.py --help
  python3 providers/converter/container.py --check
  python3 providers/converter/container.py build (--dry-run | --confirmed)
  python3 providers/converter/container.py convert --input <file> --type <pdf|docx|xlsx|pptx|ooxml|html|csv|text> --out-dir <folder>
                                                    [--timeout <seconds>]

  --check     exit 0 when docker is usable on this machine, its daemon is local and the image of the current definition exists
              (prints the image and the tool versions it recorded); 3 when it is not (the reason on stderr: build it with
              `build --confirmed`); 1 for another failure
  build       docker build of the definition into the tag openhora-converter:<12 characters of the definition's hash>, labelled with
              the definition's hash; the base image is pulled by the build, as a person's explicit step; --dry-run prints the command
  convert     the folder must exist, be this user's and mode 0700, and be empty; it gets converted.md or converted.csv and info.json
              and prints {"converter", "kind", "outputs", "image"}

Exit codes: 0 ok, 1 failed (the conversion, the container, the docker client), 2 usage, 3 not configured (no docker, a remote
daemon, no image). Standard library only; the docker command-line client is the one outside tool.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import _container as box  # noqa: E402  (providers/_container.py: the one home of the container's lifecycle and limits)

CLASS = "converter:document"
PYTHON = "/opt/venv/bin/python"          # the image's virtual environment: MarkItDown and openpyxl are installed there, from the lock
IMAGE_REPOSITORY = "openhora-converter"
LABEL_DEFINITION = "org.openhora.definition"
LABEL_RUN = "org.openhora.converter"
DEFINITION_FILES = ("Dockerfile", ".dockerignore", "_inner.py", "requirements.lock")
SUBTYPES = ("pdf", "docx", "xlsx", "pptx", "ooxml", "html", "csv", "text")
OUTPUT_NAMES = ("converted.md", "converted.csv", "info.json")
OUTPUT_ENTRIES_MAX = 2                   # one converted text and its info
CONVERTED_CAP = 1024 * 1024 + 1          # one byte over runtime/sources.py CONVERTED_CAP: the caller sees "over the cap" and refuses
INFO_CAP = 16 * 1024
STDOUT_CAP = CONVERTED_CAP + INFO_CAP + 4096
INPUT_CAP = 25 * 1024 * 1024             # the intake's route limit (runtime/sources.py ORIGINAL_CAP)
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


def definition_hash(folder: str = HERE) -> str:
    """The sha256 of the files the image is built from, by name and content, in a fixed order."""
    digest = hashlib.sha256()
    for name in sorted(DEFINITION_FILES):
        with open(os.path.join(folder, name), "rb") as f:
            digest.update(name.encode() + b"\0" + f.read() + b"\0")
    return digest.hexdigest()


def image_tag(folder: str = HERE) -> str:
    return f"{IMAGE_REPOSITORY}:{definition_hash(folder)[:12]}"


def image_id(tag: str) -> str:
    """The id of the image of this definition, or ProviderError (3) when it has not been built here."""
    try:
        done = box.docker(["image", "inspect", "--format", "{{.Id}}", tag])
    except box.ContainerError as e:
        raise ProviderError(f"docker cannot be used here ({e.code})", EXIT_NOT_CONFIGURED) from None
    found = done.stdout.strip()
    if done.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", found):
        raise ProviderError(f"the converter image {tag} is not built on this machine: run "
                            "`python3 providers/converter/container.py build --confirmed` (once; it needs the network)",
                            EXIT_NOT_CONFIGURED)
    return found


def local_daemon() -> None:
    try:
        box.require_local_daemon()
    except box.ContainerError as e:
        raise ProviderError(f"the docker daemon is not usable as a local one ({e.code})", EXIT_NOT_CONFIGURED) from None


# --- the frames ---------------------------------------------------------------------------------------------------------------------


def parse_frames(data: bytes) -> dict:
    """The outputs a container printed, {name: bytes}, or ProviderError. The rules: the stream starts with FRAME_START and ends with
    FRAME_END and nothing follows it; each record is `FILE <name> <size>\\n` and exactly <size> bytes; a name is one of OUTPUT_NAMES
    and appears once; a converted text is at most CONVERTED_CAP bytes, info.json at most INFO_CAP; at most OUTPUT_ENTRIES_MAX records;
    exactly one of converted.md and converted.csv. Anything else is the container's fault and nothing is kept."""
    if not data.startswith(FRAME_START):
        raise ProviderError("the container's output is not a conversion (no start marker)")
    at, out = len(FRAME_START), {}
    while True:
        if data.startswith(FRAME_END, at):
            if at + len(FRAME_END) != len(data):
                raise ProviderError("the container wrote after the end marker")
            break
        head = FRAME_HEAD.match(data, at)
        if head is None:
            raise ProviderError("the container's output is cut or malformed")
        name, size = head.group(1).decode("ascii"), int(head.group(2))
        if name not in OUTPUT_NAMES or name in out or len(out) >= OUTPUT_ENTRIES_MAX:
            raise ProviderError(f"the container wrote an output that is not taken: {name!r}")
        if size > (INFO_CAP if name == "info.json" else CONVERTED_CAP):
            raise ProviderError(f"the container's output {name} is {size} bytes, over its cap")
        start = head.end()
        if start + size > len(data):
            raise ProviderError("the container's output is cut short")
        out[name] = data[start:start + size]
        at = start + size
    converted = [n for n in ("converted.md", "converted.csv") if n in out]
    if len(converted) != 1:
        raise ProviderError("the container wrote no converted text, or two")
    return out


def check_out_dir(path: str) -> None:
    """The folder the outputs go to: a real folder (not a link), this user's, mode 0700, empty."""
    try:
        info = os.lstat(path)
    except OSError:
        raise ProviderError(f"--out-dir {path} does not exist", EXIT_USAGE) from None
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, "getuid") and info.st_uid != os.getuid()) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ProviderError("--out-dir must be a real folder of this user with mode 0700", EXIT_USAGE)
    if os.listdir(path):
        raise ProviderError("--out-dir must be empty", EXIT_USAGE)


def write_outputs(out_dir: str, outputs: dict) -> list:
    """Write each output into the folder as a new regular file: O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600. Returns the names."""
    fd = os.open(out_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in sorted(outputs):
            mark = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(mark, "wb") as f:
                f.write(outputs[name])
    finally:
        os.close(fd)
    return sorted(outputs)


# --- the verbs ----------------------------------------------------------------------------------------------------------------------


def command_for(name: str, image: str, input_path: str, kind: str, timeout: int) -> list:
    """The exact `docker run` command of one conversion (every limit is _container.argv's)."""
    return box.argv(name, image, [PYTHON, "-I", "/opt/converter/_inner.py", "--type", kind, "--input", "/in/input"],
                    label=LABEL_RUN, deadline=int(time.time()) + timeout + 60,
                    mounts=[(input_path, "/in/input", "ro")], memory_mb=MEMORY_MB, cpus=CPUS, scratch_mb=SCRATCH_MB,
                    pids_limit=PIDS)


def convert(input_path: str, kind: str, out_dir: str, timeout: int = DEFAULT_TIMEOUT, run=None, image=None) -> dict:
    """One conversion. `run(command, name, timeout, stdout_cap=)` and `image` are the seams a test replaces; by default
    providers/_container.py's run and the image of this definition."""
    if kind not in SUBTYPES:
        raise ProviderError(f"--type is one of {', '.join(SUBTYPES)}", EXIT_USAGE)
    if not isinstance(input_path, str) or not os.path.isabs(input_path):
        raise ProviderError("--input is an absolute path", EXIT_USAGE)
    try:
        info = os.lstat(input_path)
    except OSError:
        raise ProviderError(f"--input {input_path} does not exist", EXIT_USAGE) from None
    if not stat.S_ISREG(info.st_mode):
        raise ProviderError("--input must be a regular file (a link or a folder is never converted)", EXIT_USAGE)
    if info.st_size > INPUT_CAP:
        raise ProviderError(f"--input is {info.st_size} bytes, over the {INPUT_CAP} a conversion takes", EXIT_USAGE)
    check_out_dir(out_dir)
    if not 1 <= timeout <= MAX_TIMEOUT:
        raise ProviderError(f"--timeout is from 1 to {MAX_TIMEOUT} seconds", EXIT_USAGE)
    if image is None:
        local_daemon()
        image = image_id(image_tag())
    name = f"openhora-converter-{uuid.uuid4().hex[:16]}"
    command = command_for(name, image, input_path, kind, timeout)
    try:
        done = (run or box.run)(command, name, timeout, stdout_cap=STDOUT_CAP)
    except box.ContainerError as e:
        raise ProviderError(f"the conversion did not finish ({e.code})") from None
    if done.returncode != 0:
        tail = " ".join((done.stderr or "").split())[-300:]
        raise ProviderError(f"the conversion failed: {tail or 'exit ' + str(done.returncode)}")
    outputs = parse_frames(done.stdout)
    names = write_outputs(out_dir, outputs)
    try:
        about = json.loads(outputs.get("info.json", b"{}").decode("utf-8"))
    except ValueError:
        about = {}
    return {"converter": "document", "kind": about.get("kind", kind) if isinstance(about, dict) else kind,
            "outputs": names, "image": image, "tool_versions": (about.get("tool_versions") if isinstance(about, dict) else None) or {}}


def cmd_check(args: dict) -> int:
    local_daemon()
    tag = image_tag()
    found = image_id(tag)
    print(json.dumps({"ok": True, "image": found, "tag": tag, "definition": definition_hash()}))
    return EXIT_OK


def cmd_build(args: dict) -> int:
    if bool(args.get("--dry-run")) == bool(args.get("--confirmed")):
        raise ProviderError("give --dry-run to see the build, or --confirmed to make it", EXIT_USAGE)
    digest = definition_hash()
    command = ["docker", "build", "--label", f"{LABEL_DEFINITION}={digest}", "--build-arg", f"DEFINITION_HASH={digest}",
               "-t", image_tag(), HERE]
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


def cmd_convert(args: dict) -> int:
    for flag in ("--input", "--type", "--out-dir"):
        if not args.get(flag):
            raise ProviderError(f"{flag} is required", EXIT_USAGE)
    try:
        timeout = int(args.get("--timeout") or DEFAULT_TIMEOUT)
    except ValueError:
        raise ProviderError("--timeout is a whole number of seconds", EXIT_USAGE) from None
    print(json.dumps(convert(args["--input"], args["--type"], args["--out-dir"], timeout)))
    return EXIT_OK


VERBS = {"build": cmd_build, "convert": cmd_convert}
VALUE_FLAGS = ("--input", "--type", "--out-dir", "--timeout", "--config-file")
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
