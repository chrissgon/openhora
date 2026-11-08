#!/usr/bin/env python3
"""The inner entry of the HyperFrames image (package V3a-2): it draws the page into a ProRes intermediate and, for a page that draws,
measures the boxes the page reports (package V3b-2).

Run inside the image, with no network, as

    python3 -I /opt/hf-run/hf_render.py --project /work/project --out /work/out --tmp /work/tmp --fps <n> --timeout <s> [--measure]

`--project` holds exactly `index.html`, `vars.json` and `media/proxy.mp4` (each a regular file within a cap), and, for a page that draws,
a folder `blocks/` of at most 16 pages (`blocks/<name>.html`, each at most 1 MiB), written by the common image and mounted read-write; this
script checks the folder, checks that the page and each block page name no font outside the allow-list (HyperFrames adds a bundled font for
any family a page names and does not declare), copies the three allow-listed font files into `fonts/` when a page uses them (each checked
against its sha256), copies GSAP's own file in, and runs `hyperframes render` once: a ProRes HQ `.mov`, four workers, no frame cache. With
`--measure` (the host gives it to every render that draws, and to no other) it then runs `node /opt/hf-run/hf_measure.mjs` once on the project:
the boxes of every frame as the page reports them, into `boxes.json`, which the encode stage's gate reads. The intermediate, the boxes, a log and
`result.json` go to `--out`. The host reads `result.json` as untrusted and hashes both files again. The only HyperFrames command this file
ever runs is `render`; the only other program is that one script. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
ALLOWED_FAMILIES = {"inter", "jetbrains mono", "oh inter", "oh mono"}      # the composed pages name the private families (V3b-4); the plain names stay allowed for the base page and other callers
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
INSTANCES_FILE = "instances.json"        # the tier-A rows the page stage wrote (V3b-3); optional
INSTANCES_MAX_BYTES = 256 * 1024
REGISTRY_ROOT = "/opt/hf-registry"       # the registry files baked into the image from registry.sha256
ESCAPE_MARKER = b"hf-escape"             # what the wrapper's guard says (and throws) when a tier-A component tries to leave its scope
INSTANCE_NAME = re.compile(r"hf:[a-z][a-z0-9-]{0,39}")
REGISTRY_REL = re.compile(r"[a-z0-9][a-z0-9._-]{0,60}(/[a-z0-9][a-z0-9._-]{0,60}){0,4}")
HEX64 = re.compile(r"[0-9a-f]{64}")
FONTS_SOURCE = "/opt/fonts"              # the image's fonts (hyperframes-image/fonts/SHA256SUMS); copied into the project as fonts/
FONT_FILES = {"inter-500.woff2": "f3779f1efccc4bdcdf9c0a02ab95bf6bd092ed09c48c08cedc725889edd1d19f",
              "inter-800.woff2": "a7d0a50f15d389cad679238466bdb5fc9787aa0715719064ce25abaff042820d",
              "jetbrains-mono-500.woff2": "cb182feeed4d798ff6961d3c79f7026279448fca0676438aaecb21f3fc39553a"}
GSAP_SOURCE = "/opt/hf/node_modules/gsap/dist/gsap.min.js"
HF_PACKAGE = "/opt/hf/node_modules/hyperframes/package.json"
MEASURE_SCRIPT = "/opt/hf-run/hf_measure.mjs"   # the measure step (V3b-2); it serves the project on the loopback and reads /opt/hf only
BOXES_MAX_BYTES = 64 * 1024 ** 2         # boxes.json's cap, the figure hf_measure.mjs refuses at (`boxes_too_large`) and the host checks again
MEASURE_MIN_SECONDS = 10                 # a render with less time than this left does not start the measure step
# What the measure script may refuse with (it writes the row into boxes.json and exits 1); anything else it leaves is `measure_failed`.
MEASURE_REFUSALS = ("boxes_too_many", "boxes_too_large", "font_not_allowed", "block_escaped", "measure_failed")
MEMORY_PEAK = "/sys/fs/cgroup/memory.peak"
WORKERS = "4"                            # S2 (check C2): `--workers auto` changes the bytes, so the count is fixed
# What the child process sees, copied from the image's own environment: nothing of the caller's.
ENV_FROM_IMAGE = ("PATH", "PRODUCER_HEADLESS_SHELL_PATH", "PUPPETEER_EXECUTABLE_PATH")
# The commands of the CLI that reach a network or an account, or change the install: never called (the second word of the argv is `render`).
NEVER_CALLED = ("cloud", "billing", "publish", "lambda", "tts", "transcribe", "skills", "upgrade", "update")


class Refuse(Exception):
    def __init__(self, code: str, field: str, problems=None):
        super().__init__("%s %s" % (code, field))
        self.code, self.field, self.problems = code, field, problems or []


def refuse(code: str, field: str, problems=None):
    raise Refuse(code, field, problems)


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
            if rel == INSTANCES_FILE:
                if (mode & 0o170000) != 0o100000 or os.lstat(path).st_size > INSTANCES_MAX_BYTES:
                    refuse("project_unexpected_file", rel)
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


def load_wrap():
    """hf_wrap.py, loaded by path from this file's folder (`python3 -I` puts nothing on the path)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hf_wrap.py")
    spec = importlib.util.spec_from_file_location("hf_wrap", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("hf_wrap", module)
    spec.loader.exec_module(module)
    return module


def read_instances(project: str):
    """The rows of `instances.json` as {int: row}, each row checked for its shape; None when the project has no such file."""
    path = os.path.join(project, INSTANCES_FILE)
    if not os.path.lexists(path):
        return None
    try:
        with open(path, "rb") as fh:
            doc = json.loads(fh.read(INSTANCES_MAX_BYTES).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        refuse("project_unexpected_file", INSTANCES_FILE)
    rows = {}
    if not isinstance(doc, dict) or not doc:
        refuse("project_unexpected_file", INSTANCES_FILE)
    for key, row in doc.items():
        files = row.get("files") if isinstance(row, dict) else None
        band = row.get("band") if isinstance(row, dict) else None
        if not re.fullmatch(r"[0-9]{1,3}", key) or set(row) != {"name", "files", "implementation", "start", "end", "band"} \
                or not isinstance(row["name"], str) or not INSTANCE_NAME.fullmatch(row["name"]) or not isinstance(files, dict) or not 1 <= len(files) <= 50 \
                or not all(isinstance(k, str) and REGISTRY_REL.fullmatch(k) and isinstance(v, str) and HEX64.fullmatch(v) for k, v in files.items()) \
                or row["implementation"] not in files or not all(isinstance(row[k], (int, float)) and not isinstance(row[k], bool) for k in ("start", "end")) \
                or not 0 <= row["start"] < row["end"] or not isinstance(band, list) or len(band) != 2 \
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0 for x in band):
            refuse("project_unexpected_file", INSTANCES_FILE)
        rows[int(key)] = row
    return rows


def inline_tier_a(project: str, page: str, registry_root: str = REGISTRY_ROOT) -> str:
    """The page with each tier-A placeholder replaced by the wrapped component. For every row: every file is read from the image's registry
    folder (`tier_a_file_missing`), its sha256 checked (`tier_a_hash`), the implementation linted again (`block_lint`) and wrapped, and the
    placeholder replaced (`block_lint` when the page has none, or more placeholders than rows). The result is written back to `index.html`."""
    rows = read_instances(project)
    if rows is None:
        return page
    wrap = load_wrap()
    if page.count('data-hf-tier-a="') != len(rows):
        refuse("block_lint", "instances")
    for n in sorted(rows):
        row = rows[n]
        folder = os.path.join(registry_root, "registry", "components", row["name"][3:])
        texts = {}
        for rel in sorted(row["files"]):
            path = os.path.join(folder, rel)
            try:
                if (os.lstat(path).st_mode & 0o170000) != 0o100000:
                    refuse("tier_a_file_missing", row["name"])
                with open(path, "rb") as fh:
                    raw = fh.read(INSTANCES_MAX_BYTES + 1024 ** 2)
            except OSError:
                refuse("tier_a_file_missing", row["name"])
            if hashlib.sha256(raw).hexdigest() != row["files"][rel]:
                refuse("tier_a_hash", row["name"])
            texts[rel] = raw
        html = texts[row["implementation"]].decode("utf-8", "replace")
        if wrap.lint(html):
            refuse("block_lint", row["name"])
        placeholder = re.compile(r'<div id="hf-inst-%d" class="hf-inst" data-hf-zone="card" data-hf-tier-a="%d"[^>]*></div>' % (n, n))
        if len(placeholder.findall(page)) != 1:
            refuse("block_lint", row["name"])
        inst = {"n": n, "zone": "card", "top": row["band"][0], "height": row["band"][1], "start": row["start"], "end": row["end"]}
        try:
            text = wrap.wrap(html, inst, row["files"], wrap.typed_variables(html))
        except (wrap.WrapRefusal, ValueError):
            refuse("block_lint", row["name"])
        page = placeholder.sub(lambda _m: text, page, count=1)
    with open(os.path.join(project, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    return page


def log_shows_escape(log_path: str) -> bool:
    try:
        with open(log_path, "rb") as fh:
            return ESCAPE_MARKER in fh.read(LOG_CAP + 64)
    except OSError:
        return False


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


def run_child(argv: list, cwd: str, env: dict, log_path: str, timeout: int, mode: str, timed_out: tuple, failed: tuple) -> None:
    """Run a program: no shell, its own process group, a timeout that kills the group (`timed_out` is the refusal's (code, field)). Its stdout
    and stderr are read in chunks on a thread into the log (`mode` "wb" starts it, "ab" goes on): the first LOG_CAP bytes are kept, the rest is
    read and dropped, so a chatty child can neither fill the disk nor block on a full pipe. A non-zero exit is the refusal `failed`."""
    with open(log_path, mode) as log:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=True)

        def pump():
            kept, tail, flagged = 0, b"", False
            while True:
                chunk = proc.stdout.read(CHUNK)
                if not chunk:
                    return
                seen = not flagged and ESCAPE_MARKER in tail + chunk
                tail = chunk[-(len(ESCAPE_MARKER) - 1):]
                if kept < LOG_CAP:
                    log.write(chunk[:LOG_CAP - kept])
                    kept += len(chunk)
                if seen:                                          # the guard's marker is kept even when it arrives past the cap (or is cut by it)
                    flagged = True
                    log.write(b"\n" + ESCAPE_MARKER + b"\n")

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
            refuse(*timed_out)
        reader.join(30)
    if code != 0:
        refuse(*failed)


def run_render(argv: list, project: str, env: dict, log_path: str, timeout: int) -> None:
    """Run HyperFrames (`render_argv`) in the project; its output is the first log."""
    run_child(argv, project, env, log_path, timeout, "wb", ("hf_timeout", "render"), ("hf_failed", "render"))


def measure_argv(project: str, boxes: str) -> list:
    argv = ["node", MEASURE_SCRIPT, project, boxes]
    assert argv[0] == "node" and argv[1] == MEASURE_SCRIPT, "the only program besides `hyperframes render` is the measure script"
    return argv


def measure_refusal(boxes: str) -> tuple:
    """(code, field, problems) of the row the measure script left in boxes.json when it exited non-zero: a code of MEASURE_REFUSALS and a short field,
    else `measure_failed`. The file is removed: a refused render leaves no boxes."""
    code, field, problems = "measure_failed", "measure", []
    try:
        with open(boxes, "rb") as fh:
            row = json.loads(fh.read(4096).decode("utf-8"))
        if isinstance(row, dict) and row.get("ok") is False and row.get("code") in MEASURE_REFUSALS \
                and isinstance(row.get("field"), str) and re.fullmatch(r"[A-Za-z0-9_.:\- ]{0,40}", row["field"]):
            code, field = row["code"], row["field"]
            for p in (row.get("problems") if isinstance(row.get("problems"), list) else [])[:10]:     # what the page reported: closed shapes only
                if isinstance(p, dict) and isinstance(p.get("code"), str) and re.fullmatch(r"[a-z_]{1,30}", p["code"]) \
                        and isinstance(p.get("field"), str) and re.fullmatch(r"[A-Za-z0-9_.:\- ]{0,80}", p["field"]):
                    problems.append({"code": p["code"], "field": p["field"]})
    except (OSError, ValueError):
        pass
    try:
        os.unlink(boxes)
    except OSError:
        pass
    return code, field, problems


def boxes_ready_ms(boxes: str):
    """The milliseconds the page took to become ready, which hf_measure.mjs writes last in boxes.json (`"ready_ms":N,"schema":1}`): read from the end of the
    file, never the whole of it. None when it is not there."""
    try:
        with open(boxes, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 64))
            tail = fh.read()
    except OSError:
        return None
    m = re.search(rb'"ready_ms":([0-9]{1,9}),"schema":1\}\s*$', tail)
    return int(m.group(1)) if m else None


def run_measure(project: str, out: str, env: dict, log_path: str, timeout: int) -> str:
    """The measure step: `node hf_measure.mjs <project> <out>/boxes.json`, its output appended to the log. A refusal of the script (its row
    in boxes.json, exit 1) is passed on; a timeout is `hf_timeout measure`; any other failure is `measure_failed`. Returns the boxes' sha256."""
    boxes = os.path.join(out, "boxes.json")
    try:
        run_child(measure_argv(project, boxes), project, env, log_path, timeout, "ab", ("hf_timeout", "measure"), ("measure_failed", "measure"))
    except Refuse as err:
        if err.code == "measure_failed":
            refuse(*measure_refusal(boxes))
        try:
            os.unlink(boxes)
        except OSError:
            pass
        raise
    if not os.path.isfile(boxes) or os.path.islink(boxes) or os.path.getsize(boxes) > BOXES_MAX_BYTES:
        refuse("measure_failed", "measure")
    return sha256_file(boxes)


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


def render(project: str, out: str, tmp: str, fps: int, timeout: int, measure: bool = False) -> dict:
    started = time.monotonic()
    page = check_project(project)
    tier_a = os.path.lexists(os.path.join(project, INSTANCES_FILE))
    page = inline_tier_a(project, page)
    check_fonts(page)
    pages = block_pages(project)
    for field, text in pages.items():
        check_fonts(text, field)
    if pages or "fonts/" in page:                          # a page that draws names the fonts by path; the base page names none
        copy_fonts(project)
    shutil.copyfile(GSAP_SOURCE, os.path.join(project, "gsap.min.js"))
    log = os.path.join(out, "hf.log")
    try:
        run_render(render_argv(out, fps), project, render_env(tmp), log, timeout)
    except Refuse as err:
        if tier_a and err.code == "hf_failed" and log_shows_escape(log):
            refuse("block_escaped", "render")
        raise
    if tier_a and log_shows_escape(log):                      # a component that caught the guard's error and went on still left the marker
        refuse("block_escaped", "render")
    target = os.path.join(out, "intermediate.mov")
    if not os.path.isfile(target) or os.path.islink(target):
        refuse("hf_no_output", "render")
    result = {"ok": True, "sha256": sha256_file(target), "bytes": os.path.getsize(target), "seconds": 0.0,
              "hyperframes": hyperframes_version(), "memory_peak_bytes": memory_peak()}
    if measure:
        measure_started = time.monotonic()
        left = timeout - (measure_started - started)
        if left < MEASURE_MIN_SECONDS:
            refuse("hf_timeout", "measure")
        result["boxes_sha256"] = run_measure(project, out, render_env(tmp), os.path.join(out, "hf.log"), int(left))
        result["measure_seconds"] = round(time.monotonic() - measure_started, 2)
        ready = boxes_ready_ms(os.path.join(out, "boxes.json"))
        if ready is not None:
            result["measure_ready_ms"] = ready
    result["seconds"] = round(time.monotonic() - started, 2)
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--tmp", required=True)
    p.add_argument("--fps", type=int, required=True)
    p.add_argument("--timeout", type=int, required=True)
    p.add_argument("--measure", action="store_true", help="also measure the boxes the page reports at every frame (a page that draws): boxes.json")
    args = p.parse_args(argv)
    try:
        write_result(args.out, render(args.project, args.out, args.tmp, args.fps, args.timeout, args.measure))
        return 0
    except Refuse as err:
        write_result(args.out, dict({"ok": False, "code": err.code, "field": err.field}, **({"problems": err.problems} if err.problems else {})))
        return 1


if __name__ == "__main__":
    sys.exit(main())
