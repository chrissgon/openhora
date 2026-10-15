#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The program that runs INSIDE the project-script container (providers/script/Dockerfile puts it at /opt/script/_inner.py).
Two modes, both started by providers/script/container.py and by nothing else.

  run --kind py|sh     run the approved script (mounted read-only at /in/script) as a child process, with an environment built here
                       from a short list of names, never the container's own; the child's standard output and error go to a file,
                       never to this process's standard output; when it ends, everything left in its session is killed; then the
                       outputs are read back from /scratch/out and printed on THIS process's standard output as frames, the one
                       stream the host reads:

                           OHF1\\n   FILE <name> <size>\\n<size bytes>   ...   END\\n

                       Only regular files named result.md, result.csv or result.txt (at most one) come back, each looked at with
                       lstat and opened with O_NOFOLLOW; anything else in the folder is counted as refused and not read. info.json
                       is this program's own account: the exit code, the signal, the milliseconds, the sizes, the refused names.
                       Nothing the script writes anywhere else leaves the container.
  build                read a lock file from standard input, check every line of it again, and install the wheels it names into
                       /deps with pip (--require-hashes --only-binary=:all: --no-deps), through the proxy the environment names.
                       Nothing is mounted; the host keeps the container's file system as an image layer.

The host reads the frames with fixed rules and caps (providers/script/container.py `parse_frames`); this program is not trusted
to be the only writer of that stream, and the host does not need it to be. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import signal
import stat
import subprocess
import sys
import time

SCRIPT = "/in/script"
WORK, OUT, LOG, HOME = "/scratch/work", "/scratch/out", "/scratch/script.log", "/scratch/home"
DEPS = "/deps"
RESULT_NAMES = ("result.md", "result.csv", "result.txt")
RESULT_CAP = 1024 * 1024 + 1            # one byte over the runtime's cap: the host sees "over the cap" and refuses
PASS = ("PATH", "HOME", "LANG", "TMPDIR", "PYTHONDONTWRITEBYTECODE", "OUTPUT_DIR", "SCRIPT_DESTINATIONS",
        "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")
FRAME_START, FRAME_END = b"OHF1\n", b"END\n"
SAFE_NAME = re.compile(r"[a-z0-9._-]{1,30}")
LOCK_MAX = 256 * 1024
REQUIREMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._!+-]*")
HASH_OPTION = re.compile(r"--hash=sha256:[0-9a-f]{64}")
INDEX_URL = "https://pypi.org/simple"


def child_environment(env=None) -> dict:
    """The environment of the script: only the names of PASS that the container was given, plus the ones this program sets. The
    container's other variables never reach the script, whatever the host put there."""
    env = os.environ if env is None else env
    out = {k: env[k] for k in PASS if env.get(k)}
    out.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    out["HOME"] = HOME
    out["LANG"] = out.get("LANG") or "C.UTF-8"
    out["PYTHONDONTWRITEBYTECODE"] = "1"
    out["OUTPUT_DIR"] = OUT
    if os.path.isdir(DEPS) and os.listdir(DEPS):
        out["PYTHONPATH"] = DEPS
    return out


def read_outputs(folder: str) -> tuple:
    """({name: bytes} of the result files, [refused names]) from the folder the script wrote to: a regular file with one link and a
    name from RESULT_NAMES comes back; every other entry is refused (its name is cut to safe characters). More than one result file
    is refused whole."""
    found, refused = {}, []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return {}, ["unreadable"]
    for name in names:
        if name not in RESULT_NAMES:
            refused.append(name if SAFE_NAME.fullmatch(name) else "other")
            continue
        path = os.path.join(folder, name)
        try:
            before = os.lstat(path)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                refused.append(name)
                continue
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            refused.append(name)
            continue
        try:
            after = os.fstat(fd)
            if not stat.S_ISREG(after.st_mode) or not os.path.samestat(before, after):
                refused.append(name)
                continue
            data = b""
            while len(data) < RESULT_CAP:
                piece = os.read(fd, min(65536, RESULT_CAP - len(data)))
                if not piece:
                    break
                data += piece
            found[name] = data
        finally:
            os.close(fd)
    if len(found) > 1:
        refused += sorted(found)
        found = {}
    return found, refused


def frames(files: dict) -> bytes:
    out = bytearray(FRAME_START)
    for name in sorted(files):
        out += b"FILE %s %d\n" % (name.encode("ascii"), len(files[name])) + files[name]
    return bytes(out) + FRAME_END


def cmd_run(kind: str) -> int:
    if kind not in ("py", "sh"):
        print("error: --kind is py or sh", file=sys.stderr)
        return 2
    for folder in (WORK, OUT, HOME):
        os.makedirs(folder, exist_ok=True)
    command = [sys.executable, "-B", "-s", SCRIPT] if kind == "py" else ["/bin/bash", SCRIPT]
    started = time.monotonic()
    with open(LOG, "wb") as log:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, cwd=WORK,
                                 env=child_environment(), close_fds=True, start_new_session=True)
        code = child.wait()
    try:
        os.killpg(child.pid, signal.SIGKILL)       # whatever the script left running in its session
    except OSError:
        pass
    found, refused = read_outputs(OUT)
    info = {"exit": code if code >= 0 else None, "signal": -code if code < 0 else None,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "log_bytes": os.path.getsize(LOG) if os.path.exists(LOG) else 0, "refused": refused[:8],
            "results": sorted(found)}
    files = dict(found)
    files["info.json"] = (json.dumps(info, sort_keys=True) + "\n").encode("utf-8")
    sys.stdout.buffer.write(frames(files))
    sys.stdout.buffer.flush()
    return 0


def check_lock(text: str) -> list:
    """The requirements of a lock file, each as [`name==version`, `--hash=sha256:<hex>`, ...], or ValueError. The only lines: blank
    ones, whole-line comments, and `name==version` followed by one or more `--hash=sha256:<64 hex>` options, on the same line or
    on continuation lines (a trailing backslash). No other option (an index, a URL, a path, an editable install, another file) is
    ever accepted."""
    requirements, pending = [], []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            if pending:
                raise ValueError("a lock file ends a continued line with a blank or comment line")
            continue
        joined = line.endswith("\\")
        pending += (line[:-1] if joined else line).split()
        if not joined:
            if len(pending) < 2 or not REQUIREMENT.fullmatch(pending[0]) or not all(HASH_OPTION.fullmatch(p) for p in pending[1:]):
                raise ValueError("a lock line is `name==version` with --hash=sha256:<hex> options, nothing else")
            requirements.append(pending)
            pending = []
    if pending:
        raise ValueError("a lock file ends inside a continued line")
    if not requirements or len(requirements) > 200:
        raise ValueError("a lock file names from 1 to 200 requirements")
    return requirements


def cmd_build() -> int:
    data = sys.stdin.buffer.read(LOCK_MAX + 1)
    if len(data) > LOCK_MAX:
        print("error: the lock file is too large", file=sys.stderr)
        return 2
    try:
        requirements = check_lock(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    path = "/tmp/requirements.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(" ".join(r) for r in requirements) + "\n")
    index = os.environ.get("SCRIPT_INDEX_URL") or INDEX_URL
    command = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "--require-hashes",
               "--only-binary=:all:", "--no-deps", "--no-compile", "--target", DEPS, "--index-url", index, "-r", path]
    env = {k: v for k, v in os.environ.items() if k in PASS or k in ("PIP_CERT", "SSL_CERT_FILE")}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["HOME"] = "/tmp"
    return subprocess.call(command, stdin=subprocess.DEVNULL, env=env, close_fds=True)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:2] == ["run", "--kind"] and len(argv) == 3:
        return cmd_run(argv[2])
    if argv == ["build"]:
        return cmd_build()
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
