#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The container image the HyperFrames engine of renderer:video draws in (package V3a-image): its definition, its tag, its build and the
checks of a built image. It is not a provider and resolves to no class (it sits in a subfolder, which providers/resolve.py never lists):
the engine's provider, providers/renderer/hyperframes.py (package V3a), loads this file by path for IMAGE_REPOSITORY, definition_hash(),
image_tag() and image_id(), and so does the image family of scripts/doctor.py once a later package adds it.

The definition is the list of files in manifest.json and nothing else (review finding F11). The tag is
openhora-hyperframes:<the first 12 characters of the sha256 of those files, by name and content>, so a change to the ffmpeg engine, to a
block or to any file outside that list never changes this image, and a change to a listed file always does. The build context is the same
list less the files docker reads itself (.dockerignore admits only those); providers/renderer/tests/test_hf_image.py keeps the three in step.
What the image holds and how each piece is pinned: the Dockerfile and pins.json. What it installs, under which licence: NOTICE.md.

The network is used only by `build --confirmed`, a step the person starts. Every check of `selfcheck` runs the image through
providers/_container.py argv: no network, a read-only root, every capability dropped, no new privileges.

Usage:
  python3 providers/renderer/hyperframes-image/hf_image.py --help
  python3 providers/renderer/hyperframes-image/hf_image.py --check
  python3 providers/renderer/hyperframes-image/hf_image.py build (--dry-run [--arch arm64|amd64] | --confirmed)
  python3 providers/renderer/hyperframes-image/hf_image.py selfcheck [--jobs <n>]

  --check     exit 0 when docker is usable here, its daemon is local and the image of the current definition exists (prints
              {"ok", "image", "tag", "definition"}); 3 when it is not (the reason on stderr)
  build       docker build of the definition for the docker daemon's architecture, tagged openhora-hyperframes:<12 characters of the
              definition's hash and labelled with the hash; the pins of that architecture come from pins.json, and the build refuses
              (exit 3) while one of them has no sha256. --dry-run prints {"dry_run", "would": {"command", "tag", "arch"}} and runs
              nothing; it takes --arch (default: this machine's architecture)
  selfcheck   five checks of the built image, each in a container of its own, at most --jobs at a time (default 5): telemetry is
              disabled, `hyperframes --version` is the pinned version, no font file is in the image but the three of /opt/fonts
              (the ones inside HyperFrames' own node_modules are counted, not failed), those three have the sha256 of fonts/SHA256SUMS,
              and the only network interface is the loopback one. Prints {"ok", "image", "checks": [{"check", "ok", "detail"}]};
              exit 0 when every check passes, 1 otherwise

Exit codes: 0 ok, 1 failed, 2 usage, 3 not configured (no docker, a remote daemon, no image, an architecture or a sha256 not pinned).
Standard library only; the docker command-line client is the one outside tool. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import _container as box  # noqa: E402  (providers/_container.py: the one home of the container's lifecycle and limits)

IMAGE_REPOSITORY = "openhora-hyperframes"
LABEL_DEFINITION = "org.openhora.definition"
LABEL_RUN = "org.openhora.hyperframes-check"
MANIFEST, PINS, FONT_SUMS = "manifest.json", "pins.json", "fonts/SHA256SUMS"
ARCHES = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}
PINNED_ARCHES = ("arm64", "amd64")
SHA256 = re.compile(r"[0-9a-f]{64}")
FONT_DIR = "/opt/fonts"
FONT_FILES = ("inter-500.woff2", "inter-800.woff2", "jetbrains-mono-500.woff2")
FONT_PATTERNS = ("*.ttf", "*.ttc", "*.otf", "*.otc", "*.woff", "*.woff2", "*.pfa", "*.pfb", "*.pcf", "*.pcf.gz", "*.bdf")
NODE_MODULES = "/opt/hf/node_modules/"
BUILD_TIMEOUT = 3600
CHECK_TIMEOUT = 120
CHECK_MEMORY_MB, CHECK_CPUS, CHECK_SCRATCH_MB, CHECK_PIDS = 1024, 2, 16, 256
STDOUT_CAP = 1024 * 1024
DEFAULT_JOBS = 5
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAILED):
        super().__init__(message)
        self.code = code


# --- the definition and its pins ------------------------------------------------------------------------------------------------


def manifest_files(folder: str = HERE) -> list:
    """The files of the definition, as manifest.json lists them, sorted. ProviderError when the list is not a list of plain relative
    paths inside the folder, does not list manifest.json itself, or names a file twice."""
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise ProviderError("manifest.json cannot be read") from None
    files = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(files, list) or not all(isinstance(name, str) and name for name in files):
        raise ProviderError("manifest.json has no list of files")
    for name in files:
        if name.startswith("/") or "\\" in name or any(part in ("", ".", "..") for part in name.split("/")):
            raise ProviderError("manifest.json names a path that is not a plain path inside its folder: %r" % name[:60])
    if MANIFEST not in files or len(set(files)) != len(files):
        raise ProviderError("manifest.json must list itself, and no file twice")
    return sorted(files)


def definition_hash(folder: str = HERE) -> str:
    """The sha256 of the files of manifest.json, by name and content, in sorted order."""
    digest = hashlib.sha256()
    for name in manifest_files(folder):
        try:
            with open(os.path.join(folder, name), "rb") as f:
                body = f.read()
        except OSError:
            raise ProviderError("a file of manifest.json is missing: %s" % name) from None
        digest.update(name.encode() + b"\0" + body + b"\0")
    return digest.hexdigest()


def image_tag(folder: str = HERE) -> str:
    return "%s:%s" % (IMAGE_REPOSITORY, definition_hash(folder)[:12])


def load_pins(folder: str = HERE) -> dict:
    try:
        with open(os.path.join(folder, PINS), encoding="utf-8") as f:
            pins = json.load(f)
    except (OSError, ValueError):
        raise ProviderError("pins.json cannot be read") from None
    if not isinstance(pins, dict):
        raise ProviderError("pins.json is not an object")
    return pins


def font_sums(folder: str = HERE) -> dict:
    """{file name: sha256} of fonts/SHA256SUMS, whose lines are `<sha256>  <file name>`."""
    sums = {}
    try:
        with open(os.path.join(folder, FONT_SUMS), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    digest, name = line.split(None, 1)
                    sums[name.strip()] = digest
    except (OSError, ValueError):
        raise ProviderError("fonts/SHA256SUMS cannot be read") from None
    return sums


def build_args(pins: dict, arch: str) -> list:
    """The --build-arg words of the architecture `arch`, from pins.json. ProviderError (3) when the architecture is not pinned or the
    browser or ffmpeg of it has no sha256 yet."""
    if arch not in PINNED_ARCHES:
        raise ProviderError("the architecture %r is not one this image pins (arm64, amd64)" % str(arch)[:20], EXIT_NOT_CONFIGURED)
    try:
        chrome = pins["browser"]["platforms"][arch]
        ffmpeg = pins["ffmpeg"]["platforms"][arch]
        for what, spec in (("browser", chrome), ("ffmpeg", ffmpeg)):
            if not SHA256.fullmatch(str(spec.get("sha256") or "")):
                raise ProviderError("pins.json has no sha256 of the %s for %s: record it first (README.md, 'Pinning the browser for amd64')"
                                    % (what, arch), EXIT_NOT_CONFIGURED)
        values = {
            "CHROME_VERSION": pins["browser"]["version"], "CHROME_URL": chrome["url"], "CHROME_SIZE": str(chrome["size"]),
            "CHROME_MD5": chrome["md5"], "CHROME_SHA256": chrome["sha256"], "CHROME_BINARY": chrome["binary"],
            "FFMPEG_URL": ffmpeg["url"], "FFMPEG_SHA256": ffmpeg["sha256"], "FFMPEG_VERSION": pins["ffmpeg"]["version"],
            "DEBIAN_SNAPSHOT": pins["debian_snapshot"],
            "HYPERFRAMES_VERSION": pins["npm"]["hyperframes"], "GSAP_VERSION": pins["npm"]["gsap"],
        }
    except (KeyError, TypeError, AttributeError):
        raise ProviderError("pins.json is missing a value for %s (README.md, 'pins.json')" % arch) from None
    out = []
    for key in sorted(values):
        out += ["--build-arg", "%s=%s" % (key, values[key])]
    return out


def build_command(arch: str, folder: str = HERE) -> list:
    """The exact `docker build` command for the architecture `arch` (a list; the first word is `docker`)."""
    digest = definition_hash(folder)
    return (["docker", "build", "--progress=plain", "--platform", "linux/" + arch,
             "--label", "%s=%s" % (LABEL_DEFINITION, digest), "--build-arg", "DEFINITION_HASH=" + digest]
            + build_args(load_pins(folder), arch)
            + ["-t", "%s:%s" % (IMAGE_REPOSITORY, digest[:12]), folder])


# --- docker ------------------------------------------------------------------------------------------------------------------------


def local_daemon() -> None:
    try:
        box.require_local_daemon()
    except box.ContainerError as e:
        raise ProviderError("the docker daemon is not usable as a local one (%s)" % e.code, EXIT_NOT_CONFIGURED) from None


def daemon_arch() -> str:
    """The docker daemon's architecture as this image names it (arm64, amd64), or ProviderError (3)."""
    try:
        done = box.docker(["info", "--format", "{{.Architecture}}"])
    except box.ContainerError as e:
        raise ProviderError("docker cannot be used here (%s)" % e.code, EXIT_NOT_CONFIGURED) from None
    arch = ARCHES.get(done.stdout.strip()) if done.returncode == 0 else None
    if arch is None:
        raise ProviderError("the docker daemon's architecture is not one this image pins (arm64, amd64)", EXIT_NOT_CONFIGURED)
    return arch


def image_id(tag: str) -> str:
    """The id of the image of this definition, or ProviderError (3) when it has not been built here."""
    try:
        done = box.docker(["image", "inspect", "--format", "{{.Id}}", tag])
    except box.ContainerError as e:
        raise ProviderError("docker cannot be used here (%s)" % e.code, EXIT_NOT_CONFIGURED) from None
    found = done.stdout.strip()
    if done.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", found):
        raise ProviderError("the HyperFrames image %s is not built on this machine: run "
                            "`python3 providers/renderer/hyperframes-image/hf_image.py build --confirmed` (once; it needs the network)"
                            % tag, EXIT_NOT_CONFIGURED)
    return found


# --- the checks of a built image -----------------------------------------------------------------------------------------------------


def find_args() -> list:
    """`find` over the image's root file system for every font file, by the patterns of FONT_PATTERNS."""
    words = ["find", "/", "-xdev", "-type", "f", "("]
    for i, pattern in enumerate(FONT_PATTERNS):
        words += (["-o"] if i else []) + ["-iname", pattern]
    return words + [")", "-print"]


# (check, the command run in the image, the exit codes that let its output be judged)
CHECKS = (
    ("telemetry", ["hyperframes", "telemetry", "status"], (0,)),
    ("version", ["hyperframes", "--version"], (0,)),
    ("font_files", find_args(), (0, 1)),          # 1: a folder the image's user may not read; the build's own check ran as root
    ("font_sha256", ["sha256sum"] + ["%s/%s" % (FONT_DIR, name) for name in FONT_FILES], (0,)),
    ("network", ["node", "-p", "Object.keys(require('os').networkInterfaces()).sort().join(',')"], (0,)),
)


def judge(check: str, text: str, pins: dict, sums: dict) -> tuple:
    """(ok, detail) of one check, from what its container printed."""
    if check == "telemetry":
        ok = "disabled" in text and "HYPERFRAMES_NO_TELEMETRY" in text
        return ok, ("disabled by HYPERFRAMES_NO_TELEMETRY" if ok else "not disabled: " + " ".join(text.split())[:200])
    if check == "version":
        want = pins["npm"]["hyperframes"]
        ok = re.search(r"(?<![0-9.])%s(?![0-9.])" % re.escape(want), text) is not None
        return ok, (want if ok else "not %s: %s" % (want, " ".join(text.split())[:200]))
    if check == "font_files":
        lines = sorted(line.strip() for line in text.splitlines() if line.strip())
        inside = [line for line in lines if line.startswith(NODE_MODULES)]
        outside = [line for line in lines if not line.startswith(NODE_MODULES)]
        want = sorted("%s/%s" % (FONT_DIR, name) for name in FONT_FILES)
        if outside == want:
            return True, "the three of %s; %d inside HyperFrames' node_modules" % (FONT_DIR, len(inside))
        return False, "font files that differ from the three: " + ", ".join(sorted(set(outside) ^ set(want)))[:300]
    if check == "font_sha256":
        got = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2:
                got[os.path.basename(parts[1])] = parts[0]
        wrong = [name for name in FONT_FILES if not sums.get(name) or got.get(name) != sums[name]]
        return (not wrong), ("as fonts/SHA256SUMS" if not wrong else "differs from fonts/SHA256SUMS: " + ", ".join(wrong))
    if check == "network":
        ok = text.strip() == "lo"
        return ok, ("loopback only" if ok else "interfaces: " + text.strip()[:100])
    raise ValueError(check)


def run_one(image: str, check: str, inner: list, ok_codes: tuple, run=None) -> tuple:
    """(stdout, stderr) of one check's container. ProviderError when it does not finish or exits with a code not in ok_codes."""
    name = "openhora-hyperframes-check-%s" % uuid.uuid4().hex[:16]
    command = box.argv(name, image, inner, label=LABEL_RUN, deadline=int(time.time()) + CHECK_TIMEOUT + 60, mounts=[],
                       memory_mb=CHECK_MEMORY_MB, cpus=CHECK_CPUS, scratch_mb=CHECK_SCRATCH_MB, pids_limit=CHECK_PIDS)
    try:
        done = (run or box.run)(command, name, CHECK_TIMEOUT, stdout_cap=STDOUT_CAP)
    except box.ContainerError as e:
        raise ProviderError("the check %s did not finish (%s)" % (check, e.code)) from None
    if done.returncode not in ok_codes:
        tail = " ".join((done.stderr or "").split())[-300:]
        raise ProviderError("the check %s exited %d: %s" % (check, done.returncode, tail))
    return done.stdout.decode("utf-8", "replace"), done.stderr or ""


def selfcheck(image: str, folder: str = HERE, run=None, jobs: int = DEFAULT_JOBS) -> dict:
    """Every check of CHECKS against the image `image`, at most `jobs` at a time: {"ok", "image", "checks": [{"check", "ok", "detail"}]}.
    `run(command, name, timeout, stdout_cap=)` is the seam a test replaces; by default providers/_container.py's run."""
    pins, sums = load_pins(folder), font_sums(folder)

    def one(row):
        check, inner, ok_codes = row
        try:
            out, err = run_one(image, check, inner, ok_codes, run)
        except ProviderError as e:
            return {"check": check, "ok": False, "detail": str(e)}
        text = out + "\n" + err if check in ("telemetry", "version") else out     # a CLI may print its answer on stderr
        ok, detail = judge(check, text, pins, sums)
        return {"check": check, "ok": bool(ok), "detail": detail}

    with ThreadPoolExecutor(max_workers=max(1, min(int(jobs), len(CHECKS)))) as pool:
        results = list(pool.map(one, CHECKS))
    return {"ok": all(r["ok"] for r in results), "image": image, "checks": results}


# --- the verbs ----------------------------------------------------------------------------------------------------------------------


def cmd_check(args: dict) -> int:
    local_daemon()
    tag = image_tag()
    found = image_id(tag)
    print(json.dumps({"ok": True, "image": found, "tag": tag, "definition": definition_hash()}))
    return EXIT_OK


def cmd_build(args: dict) -> int:
    if bool(args.get("--dry-run")) == bool(args.get("--confirmed")):
        raise ProviderError("give --dry-run to see the build, or --confirmed to make it", EXIT_USAGE)
    if args.get("--arch") and not args.get("--dry-run"):
        raise ProviderError("--arch goes with --dry-run only: a build is for the docker daemon's own architecture", EXIT_USAGE)
    if args.get("--dry-run"):
        arch = args.get("--arch") or ARCHES.get(platform.machine().lower())
        if arch not in PINNED_ARCHES:
            raise ProviderError("--arch is arm64 or amd64", EXIT_USAGE)
        print(json.dumps({"dry_run": True, "would": {"command": build_command(arch), "tag": image_tag(), "arch": arch}}))
        return EXIT_OK
    local_daemon()
    arch = daemon_arch()
    command = build_command(arch)
    try:
        done = subprocess.run([box.docker_binary()] + command[1:], env=box.docker_environment(), timeout=BUILD_TIMEOUT, check=False,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (box.ContainerError, OSError, subprocess.SubprocessError) as e:
        raise ProviderError("the build did not run (%s)" % type(e).__name__) from None
    if done.returncode != 0:
        tail = " ".join(done.stderr.decode("utf-8", "replace").split())[-2000:]
        raise ProviderError("the build failed: " + tail)
    print(json.dumps({"built": True, "arch": arch, "tag": image_tag(), "image": image_id(image_tag())}))
    return EXIT_OK


def cmd_selfcheck(args: dict) -> int:
    try:
        jobs = int(args.get("--jobs") or DEFAULT_JOBS)
    except ValueError:
        raise ProviderError("--jobs is a whole number", EXIT_USAGE) from None
    if jobs < 1:
        raise ProviderError("--jobs is at least 1", EXIT_USAGE)
    local_daemon()
    result = selfcheck(image_id(image_tag()), jobs=jobs)
    print(json.dumps(result))
    return EXIT_OK if result["ok"] else EXIT_FAILED


VERBS = {"build": cmd_build, "selfcheck": cmd_selfcheck}
VALUE_FLAGS = ("--arch", "--jobs")
SWITCHES = ("--dry-run", "--confirmed", "--check")


def parse_args(argv: list) -> tuple:
    verb, args, i = None, {}, 0
    while i < len(argv):
        word = argv[i]
        if word in VALUE_FLAGS:
            if i + 1 >= len(argv):
                raise ProviderError("%s needs a value" % word, EXIT_USAGE)
            args[word] = argv[i + 1]
            i += 2
        elif word in SWITCHES:
            args[word] = True
            i += 1
        elif verb is None and word in VERBS:
            verb = word
            i += 1
        else:
            raise ProviderError("unknown argument %r; see --help" % word[:60], EXIT_USAGE)
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
        print("error: %s" % e, file=sys.stderr)
        return e.code
    except box.ContainerError as e:
        print("error: the container helper refused (%s)" % e.code, file=sys.stderr)
        return EXIT_NOT_CONFIGURED if e.code in ("docker_missing", "docker_unusable") else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
