#!/usr/bin/env python3
"""The inner entry of the HyperFrames image (package V3a-2): it draws the base page into a ProRes intermediate and nothing else.

Run inside the image, with no network, as

    python3 -I /opt/hf-run/hf_render.py --project /work/project --out /work/out --tmp /work/tmp --fps <n> --timeout <s>

`--project` holds exactly `index.html`, `vars.json` and `media/proxy.mp4` (each a regular file within a cap), and, for a page that draws,
a folder `blocks/` of at most 16 pages (`blocks/<name>.html`, each at most 1 MiB), written by the common image and mounted read-write; this
script checks the folder, checks that the page and each block page name no font outside the allow-list (HyperFrames adds a bundled font for
any family a page names and does not declare), copies the three allow-listed font files into `fonts/` when a page uses them (each checked
against its sha256), copies GSAP's own file in, and runs `hyperframes render` once: a ProRes HQ `.mov`, four workers, no frame cache. The intermediate, a log and `result.json` go to `--out`. The host reads `result.json` as
untrusted and hashes the intermediate again. The only HyperFrames command this file ever runs is `render`. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

# The families a page may name: the lower-cased families of providers/renderer/assets/fonts/allowlist.json (a test keeps the two equal).
ALLOWED_FAMILIES = {"inter", "jetbrains mono"}
GENERIC_FAMILIES = {"sans-serif", "serif", "monospace", "system-ui", "ui-monospace", "inherit", "initial", "unset"}

INDEX_MAX_BYTES = 2 * 1024 ** 2          # the page's cap
VARS_MAX_BYTES = 256 * 1024              # the variables' cap
PROXY_MAX_BYTES = 2 * 1024 ** 3          # the proxy's cap (the same figure as _media.PROXY_MAX_BYTES, which this image does not carry)
LOG_CAP = 1024 ** 2                      # the most of HyperFrames' own output that is kept
CHUNK = 64 * 1024
PROJECT_FILES = {"index.html": INDEX_MAX_BYTES, "vars.json": VARS_MAX_BYTES, "media/proxy.mp4": PROXY_MAX_BYTES}
BLOCK_PAGE = re.compile(r"blocks/[a-z0-9-]{1,80}\.html")
BLOCK_PAGE_MAX_BYTES = 1024 ** 2         # one block page's cap
BLOCK_PAGES_MAX = 16                     # the most block pages a project holds
FONTS_SOURCE = "/opt/fonts"              # the image's fonts (hyperframes-image/fonts/SHA256SUMS); copied into the project as fonts/
FONT_FILES = {"inter-500.woff2": "f3779f1efccc4bdcdf9c0a02ab95bf6bd092ed09c48c08cedc725889edd1d19f",
              "inter-800.woff2": "a7d0a50f15d389cad679238466bdb5fc9787aa0715719064ce25abaff042820d",
              "jetbrains-mono-500.woff2": "cb182feeed4d798ff6961d3c79f7026279448fca0676438aaecb21f3fc39553a"}
GSAP_SOURCE = "/opt/hf/node_modules/gsap/dist/gsap.min.js"
HF_PACKAGE = "/opt/hf/node_modules/hyperframes/package.json"
MEMORY_PEAK = "/sys/fs/cgroup/memory.peak"
WORKERS = "4"                            # S2 (check C2): `--workers auto` changes the bytes, so the count is fixed
# What the child process sees, copied from the image's own environment: nothing of the caller's.
ENV_FROM_IMAGE = ("PATH", "PRODUCER_HEADLESS_SHELL_PATH", "PUPPETEER_EXECUTABLE_PATH")
# The commands of the CLI that reach a network or an account, or change the install: never called (the second word of the argv is `render`).
NEVER_CALLED = ("cloud", "billing", "publish", "lambda", "tts", "transcribe", "skills", "upgrade", "update")


class Refuse(Exception):
    def __init__(self, code: str, field: str):
        super().__init__("%s %s" % (code, field))
        self.code, self.field = code, field


def refuse(code: str, field: str):
    raise Refuse(code, field)


def check_fonts(html: str, field: str = "index.html") -> None:
    """Every font family the page names (in CSS, in @font-face and in the canvas font strings of a script) is one of ours or a generic
    keyword. HyperFrames' compiler adds a bundled font for any other NAMED family it does not find declared, so a page that names one
    is refused before any render (`font_not_allowed`). The base page names none."""
    problems = []
    for m in re.finditer(r"font-family\s*:\s*([^;}]+)", html):
        for tok in re.findall(r"\"([^\"]+)\"|'([^']+)'|([A-Za-z][A-Za-z0-9 -]*)", re.sub(r"var\(--[a-z-]+\)|var\(--[a-z-]+,|\)", "", m.group(1))):
            name = next(t for t in tok if t).strip().lower()
            if name and name not in ALLOWED_FAMILIES and name not in GENERIC_FAMILIES and not name.startswith("var"):
                problems.append(name)
    for m in re.finditer(r"\b\d+px\s+(?:\\?[\"'])?([A-Za-z][A-Za-z ]*?)(?:\\?[\"'])?[\"';,)]", html):
        name = m.group(1).strip().lower()
        if name and name not in ALLOWED_FAMILIES and name not in GENERIC_FAMILIES:
            problems.append(name)
    if problems:
        refuse("font_not_allowed", field)


def check_project(project: str) -> str:
    """The folder holds exactly the three files, each a regular file (never a link) within its cap, and at most BLOCK_PAGES_MAX block pages
    in a `blocks` folder (`blocks/<name>.html`, each a regular file within BLOCK_PAGE_MAX_BYTES), and nothing else. Returns the page's text."""
    found, pages = set(), 0
    for base, dirs, files in os.walk(project, followlinks=False):
        for name in dirs + files:
            path = os.path.join(base, name)
            rel = os.path.relpath(path, project)
            try:
                mode = os.lstat(path).st_mode
            except OSError:
                refuse("project_unexpected_file", rel[:80])
            if os.path.isdir(path) and not os.path.islink(path):
                if rel not in ("media", "blocks"):
                    refuse("project_unexpected_file", rel[:80])
                continue
            if BLOCK_PAGE.fullmatch(rel):
                pages += 1
                if pages > BLOCK_PAGES_MAX or (mode & 0o170000) != 0o100000 or os.lstat(path).st_size > BLOCK_PAGE_MAX_BYTES:
                    refuse("project_unexpected_file", rel[:80])
                continue
            if rel not in PROJECT_FILES or (mode & 0o170000) != 0o100000:
                refuse("project_unexpected_file", rel[:80])
            found.add(rel)
    for rel, cap in PROJECT_FILES.items():
        path = os.path.join(project, rel)
        if rel not in found:
            refuse("project_unexpected_file", rel)
        if os.lstat(path).st_size > cap:
            refuse("project_unexpected_file", rel)
    with open(os.path.join(project, "index.html"), "rb") as fh:
        return fh.read(INDEX_MAX_BYTES).decode("utf-8", "replace")


def block_pages(project: str) -> dict:
    """{field: text} of the block pages of a project `check_project` accepted (the field is `blocks:<name>.html`, which holds no slash)."""
    folder = os.path.join(project, "blocks")
    pages = {}
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            with open(os.path.join(folder, name), "rb") as fh:
                pages["blocks:" + name] = fh.read(BLOCK_PAGE_MAX_BYTES).decode("utf-8", "replace")
    return pages


def copy_fonts(project: str) -> None:
    """Copy the three allow-listed font files from the image into `<project>/fonts/`, each checked against its sha256 first (`font_hash`).
    Called after the project was checked: the check refuses a `fonts` folder it did not expect, so this one is made here."""
    os.mkdir(os.path.join(project, "fonts"), 0o700)
    for name, digest in sorted(FONT_FILES.items()):
        source = os.path.join(FONTS_SOURCE, name)
        try:
            with open(source, "rb") as fh:
                raw = fh.read()
        except OSError:
            refuse("font_hash", name)
        if hashlib.sha256(raw).hexdigest() != digest:
            refuse("font_hash", name)
        with open(os.path.join(project, "fonts", name), "wb") as out:
            out.write(raw)


def render_argv(out: str, fps: int) -> list:
    argv = ["hyperframes", "render", "--output", os.path.join(out, "intermediate.mov"), "--format", "mov", "--prores-profile", "hq",
            "--variables-file", "vars.json", "--workers", WORKERS, "--frames-cache-dir", "off", "--fps", str(fps), "--quiet"]
    assert argv[1] == "render" and not set(NEVER_CALLED) & set(argv), "only `hyperframes render` is ever run"
    return argv


def render_env(tmp: str, source=None) -> dict:
    source = os.environ if source is None else source
    env = {key: source[key] for key in ENV_FROM_IMAGE if key in source}
    env.update({"HOME": "/work/tmp", "TMPDIR": tmp, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"})
    return env


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run_render(argv: list, project: str, env: dict, log_path: str, timeout: int) -> None:
    """Run HyperFrames: no shell, its own process group, a timeout that kills the group. Its stdout and stderr are read in chunks on a
    thread into the log: the first LOG_CAP bytes are kept, the rest is read and dropped, so a chatty child can neither fill the disk nor
    block on a full pipe."""
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(argv, cwd=project, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)

        def pump():
            kept = 0
            while True:
                chunk = proc.stdout.read(CHUNK)
                if not chunk:
                    return
                if kept < LOG_CAP:
                    log.write(chunk[:LOG_CAP - kept])
                    kept += len(chunk)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()
            reader.join(5)
            refuse("hf_timeout", "render")
        reader.join(30)
    if code != 0:
        refuse("hf_failed", "render")


def memory_peak():
    try:
        with open(MEMORY_PEAK, encoding="ascii") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def hyperframes_version() -> str:
    try:
        with open(HF_PACKAGE, encoding="utf-8") as fh:
            return str(json.load(fh)["version"])
    except (OSError, ValueError, KeyError):
        refuse("hf_version_unreadable", "render")


def write_result(out: str, doc: dict) -> None:
    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
        fh.write("\n")


def render(project: str, out: str, tmp: str, fps: int, timeout: int) -> dict:
    started = time.monotonic()
    page = check_project(project)
    check_fonts(page)
    pages = block_pages(project)
    for field, text in pages.items():
        check_fonts(text, field)
    if pages or "fonts/" in page:                          # a page that draws names the fonts by path; the base page names none
        copy_fonts(project)
    shutil.copyfile(GSAP_SOURCE, os.path.join(project, "gsap.min.js"))
    run_render(render_argv(out, fps), project, render_env(tmp), os.path.join(out, "hf.log"), timeout)
    target = os.path.join(out, "intermediate.mov")
    if not os.path.isfile(target) or os.path.islink(target):
        refuse("hf_no_output", "render")
    return {"ok": True, "sha256": sha256_file(target), "bytes": os.path.getsize(target), "seconds": round(time.monotonic() - started, 2),
            "hyperframes": hyperframes_version(), "memory_peak_bytes": memory_peak()}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--tmp", required=True)
    p.add_argument("--fps", type=int, required=True)
    p.add_argument("--timeout", type=int, required=True)
    args = p.parse_args(argv)
    try:
        write_result(args.out, render(args.project, args.out, args.tmp, args.fps, args.timeout))
        return 0
    except Refuse as err:
        write_result(args.out, {"ok": False, "code": err.code, "field": err.field})
        return 1


if __name__ == "__main__":
    sys.exit(main())
