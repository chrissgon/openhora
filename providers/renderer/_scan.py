"""The `scan` verb, inside the common image (package P9-a1): the text and the QR codes in the pictures and clips of a media set, read after `asset-sheet --mode full`
normalised them and before the person approves them. A warning tool: it never refuses a picture, a clip or an approval, it reports what it saw (the host's `verb_scan`
rebuilds the answer from a closed schema; P9-a2 shows it).

No browser, no network, no recording. The only programs are the image's pinned ffmpeg, Tesseract and OpenCV's QR detector (a wheel, with numpy). Standard library at import;
`cv2` and `numpy` are imported inside the functions that use them, so a host test imports this module without them and replaces the four readers (`decode_frames`,
`make_qr_reader`, `thumbnail`, `read_text`) with fakes.

What it reads, and how (every figure is a validity bound of the spec's section 3, none limits what a person may pick):
  - Decoding. ffmpeg decodes each input to raw 8-bit grey frames on a pipe (one thread, the `file` protocol only, the container's demuxer forced, the first video stream
    alone, scaled to the size the host says). OpenCV and Tesseract never parse a file of the outside world: they get pixels (OpenCV) or a PGM this code writes (Tesseract).
  - QR codes: every frame of every clip and every picture, `cv2.QRCodeDetector().detectAndDecodeMulti`. A code found and not decoded is `qr_unreadable`.
  - Text: Tesseract (LSTM engine, sparse text) on every picture, and on a clip on a choice of frames that cannot skip a caption of 12 frames (`select_text_frames`): frame 0, the
    last frame, one in every GRID_STEP (30), and every frame whose 64x36 grey thumbnail has CELLS_MIN or more cells that differ by CELL_DIFF or more from the last read frame's (a
    caption appearing on a still picture moves the mean difference by only about 1.3 of 255, and about 100 cells by 8 or more; a still one's noise is 0 cells). When more than
    OCR_FRAMES_MAX frames qualify, the choice is OCR_FRAMES_MAX frames evenly spaced over the whole clip, a step of 6.1 frames at most for the longest clip (601 frames), so a text
    that shows for 12 frames is read at least once, a moving background or not.
  - Cleaning, before anything is written: printable characters only, no control, bidi or zero-width character, whitespace collapsed, a line cut to LINE_MAX characters, at most
    TEXT_LINES_MAX lines and TEXT_CHARS_MAX characters per asset. A QR payload that is a web link gives its host only.
  - One worker per asset (a thread: the heavy work is a subprocess or OpenCV, which let go of the interpreter), at most the container's cpus, each Tesseract call on one thread.
  - A budget of SCAN_BUDGET_S seconds, after which no new work starts and what is not finished is `partial`.
The answer: {"ok", "lang", "versions": {tesseract, opencv, tessdata}, "assets": [{slot, file, kind, frames, frames_qr, frames_text, frames_changed, partial, codes, text: {lines,
chars, cut}, qr: [{kind, host, scheme, text, first_frame, frames}]}]}. `frames_changed` is the number of clip frames that qualified for a text read (before the cap); `scan_partial` is set only when frames that were chosen were not read
(the budget ended), never for a choice that is a designed sampling. Text read from a picture is external content: it is only ever data.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import os
import re
import shutil
import subprocess
import time
import urllib.parse

import _media
from _text import Refusal
from _vocab import SLOT_ID

MAX_ASSETS = 6                    # = runtime/media_stock.py MAX_FULL (a test compares)
MAX_SIDE = 3840                   # = _asset_sheet.MAX_OUT_SIDE: a normalised file's side
TEXT_LINES_MAX, TEXT_CHARS_MAX, LINE_MAX = 8, 600, 160
QR_MAX, QR_TEXT_MAX, PAYLOAD_MAX = 4, 120, 2048
OCR_FRAMES_MAX = 100              # at most this many text reads per clip: 601 frames at this cap are sampled every 6.1 frames, so a 12-frame text is read at least once
GRID_STEP = 30                    # a clip is read for text at least every this many frames (a slow fade or a low-contrast caption moves no cell by CELL_DIFF at once)
CELL_DIFF, CELLS_MIN = 8, 16      # of 2304 cells (64x36), at least CELLS_MIN differ from the last read frame's by CELL_DIFF or more (of 255): live figures of a caption box on a still clip, 99 cells
                                  # against 0 for the compression noise; the mean absolute difference of the same frames is 1.3, which is why it is not the measure
THUMB = (64, 36)                  # width, height
CONF_MIN = 60                     # Tesseract's word confidence (0-100) under which a word is mostly noise
SCAN_BUDGET_S = 480               # the inner run stops starting new work here; the container's deadline is 600
TEXT_FOUND_MIN = 3                # letters or digits kept on an asset for `text_found`
FFMPEG_TIMEOUT = 600
TESSERACT_TIMEOUT = 120
DEFAULT_LANG = "eng+por+spa"
LANG = re.compile(r"[a-z]{3}(\+[a-z]{3}){0,3}")
SCAN_CODES = ("text_found", "qr_link", "qr_action", "qr_text", "qr_unreadable", "scan_partial")
ASSET_NAME = re.compile(r"asset-[0-9a-f]{12}\.(png|mp4)")
KIND_OF = {"png": "image", "mp4": "clip"}
ACTION_SCHEMES = ("tel", "mailto", "sms", "geo", "WIFI")      # closed list; the scheme word is written as here
# The characters `_docker.SAFE_TEXT` refuses on the host (a test compares), removed here before anything is written.
UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]")
HOST = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?){1,8}")      # = runtime/deliver_document.py HOST (a test compares)
TESSERACT_FALLBACK = "/usr/bin/tesseract"


def fail(code: str, field: str):
    raise Refusal(code, str(field)[:80])


# ---------------------------------------------------------------- cleaning

def clean_line(text: str) -> str:
    """`text` reduced to printable characters: the characters `UNSAFE` names are removed, a space-like character becomes a space, any other unprintable one is removed,
    whitespace is collapsed, and the line is cut to LINE_MAX characters."""
    kept = []
    for ch in UNSAFE.sub("", text or ""):
        if ch.isprintable():
            kept.append(ch)
        elif ch.isspace():
            kept.append(" ")
    return " ".join("".join(kept).split())[:LINE_MAX]


def dedupe(lines: list) -> list:
    """The cleaned `lines`, empty ones dropped and a repeated one kept once, in order."""
    seen, kept = set(), []
    for line in lines:
        line = clean_line(line)
        if line and line not in seen:
            seen.add(line)
            kept.append(line)
    return kept


def cut_text(lines: list) -> dict:
    """{lines, chars, cut}: the cleaned `lines` (empty ones dropped, a repeated one kept once) cut to TEXT_LINES_MAX lines and TEXT_CHARS_MAX characters; `chars` is the count
    before the cut and `cut` says whether one happened."""
    kept = dedupe(lines)
    chars = sum(len(line) for line in kept)
    out, used = [], 0
    for line in kept[:TEXT_LINES_MAX]:
        room = TEXT_CHARS_MAX - used
        if room <= 0:
            break
        out.append(line[:room])
        used += len(out[-1])
    return {"lines": out, "chars": chars, "cut": len(out) < len(kept) or used < chars}


def alnum_count(lines: list) -> int:
    return sum(1 for line in lines for ch in line if ch.isalnum())


# ---------------------------------------------------------------- QR payloads

def host_of(payload: str):
    """The lower case, IDNA-encoded host of an http(s) payload when it has the form the host's `HOST` pattern allows; None otherwise."""
    try:
        name = urllib.parse.urlsplit(payload.strip()).hostname
        if not name:
            return None
        host = name.lower().encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        return None
    return host if HOST.fullmatch(host) else None


def classify_payload(payload: str) -> dict:
    """{kind, host, scheme, text} of one decoded QR payload: `link` (http or https; only its host is kept, null when it cannot be read as a site name), `action` (a scheme of
    ACTION_SCHEMES, only the scheme is kept) or `text` (its first QR_TEXT_MAX cleaned characters)."""
    payload = payload[:PAYLOAD_MAX]
    lower = payload.lower()
    if lower.startswith(("http://", "https://")):
        return {"kind": "link", "host": host_of(payload), "scheme": None, "text": None}
    for scheme in ACTION_SCHEMES:
        if lower.startswith(scheme.lower() + ":"):
            return {"kind": "action", "host": None, "scheme": scheme, "text": None}
    return {"kind": "text", "host": None, "scheme": None, "text": clean_line(payload)[:QR_TEXT_MAX]}


class QrSet:
    """The distinct QR payloads of one asset: where each first showed and on how many frames; at most QR_MAX are kept, `unreadable` counts a code found and not decoded."""

    def __init__(self):
        self.items = {}
        self.unreadable = False

    def add(self, frame: int, payloads) -> None:
        for payload in payloads:
            if not payload:
                self.unreadable = True
                continue
            key = classify_payload(payload)
            ident = (key["kind"], key["host"], key["scheme"], key["text"])
            if ident in self.items:
                if self.items[ident]["last"] != frame:
                    self.items[ident]["frames"] += 1
                    self.items[ident]["last"] = frame
            elif len(self.items) < QR_MAX:
                self.items[ident] = dict(key, first_frame=frame, frames=1, last=frame)

    def rows(self) -> list:
        return [{k: v for k, v in row.items() if k != "last"} for row in self.items.values()]


# ---------------------------------------------------------------- which frames of a clip are read for text

def changed_cells(a, b) -> int:
    """How many cells of two thumbnails (lists of 0-255 values of the same length) differ by CELL_DIFF or more."""
    return sum(1 for x, y in zip(a, b) if abs(x - y) >= CELL_DIFF)


def select_text_frames(thumbs: list) -> tuple:
    """(indices to read, how many qualified): frame 0, the last frame, every GRID_STEP-th frame, and every frame with CELLS_MIN or more cells that differ by CELL_DIFF or more from
    the last chosen frame's thumbnail. When more than OCR_FRAMES_MAX qualify (a moving picture: nearly every frame does), the choice is OCR_FRAMES_MAX frames evenly spaced over
    the whole clip, first and last included: a step of at most 6.1 frames for the longest clip, so a text of 12 frames is read at least once."""
    n = len(thumbs)
    if not n:
        return [], 0
    chosen, last = set(), thumbs[0]
    for i in range(n):
        if i in (0, n - 1) or i % GRID_STEP == 0 or changed_cells(thumbs[i], last) >= CELLS_MIN:
            chosen.add(i)
            last = thumbs[i]
    ordered = sorted(chosen)
    if len(ordered) <= OCR_FRAMES_MAX:
        return ordered, len(ordered)
    step = (n - 1) / float(OCR_FRAMES_MAX - 1)
    return sorted({int(round(k * step)) for k in range(OCR_FRAMES_MAX)}), len(ordered)


# ---------------------------------------------------------------- the readers (seams: a host test replaces them)

def decode_argv(ffmpeg: str, path: str, kind: str, w: int, h: int) -> list:
    """ffmpeg's command that writes the raw 8-bit grey frames of `path` (a picture or a normalised clip) at w x h to stdout: one thread, only the `file` protocol, the
    container's demuxer forced, the first video stream alone."""
    one = str(_media.ENCODE_INPUT_THREADS)
    base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", one, "-filter_threads", one, "-filter_complex_threads", one]
    source = _media.asset_input("png", path) if kind == "image" else _media.clip_input("mov", "h264") + ["-i", path]
    return base + source + ["-map", "0:v:0", "-an", "-sn", "-dn", "-vf", "scale=%d:%d:flags=%s,format=gray" % (w, h, _media.SWS), "-f", "rawvideo", "-pix_fmt", "gray", "-"]


def decode_frames(ffmpeg: str, path: str, kind: str, w: int, h: int):
    """A generator of the grey frames (bytes, w*h each) of `path`; an incomplete last frame is dropped. A decoder that fails, or starts and cannot run, is a closed refusal."""
    size = w * h
    try:
        proc = subprocess.Popen(decode_argv(ffmpeg, path, kind, w, h), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        fail("tool_not_runnable", "ffmpeg")
    ended = False
    try:
        while True:
            frame = proc.stdout.read(size)
            if len(frame) < size:
                ended = True
                break
            yield frame
    finally:
        proc.stdout.close()
        if not ended:
            try:
                proc.kill()
            except OSError:
                pass
        proc.wait()
    if proc.returncode != 0:
        fail("tool_failed", "ffmpeg")


def make_qr_reader():
    """A function (frame bytes, w, h) -> the payloads found in the frame, "" for a code found and not decoded. One reader per worker: the detector is not thread safe."""
    import cv2
    import numpy
    detector = cv2.QRCodeDetector()

    def read(frame: bytes, w: int, h: int) -> list:
        image = numpy.frombuffer(frame, dtype=numpy.uint8).reshape(h, w)
        try:
            found, texts, points, _ = detector.detectAndDecodeMulti(image)
        except cv2.error:
            return []
        if not found:
            return []
        texts = [t for t in (texts or ())]
        return texts if texts else [""]
    return read


def thumbnail(frame: bytes, w: int, h: int) -> list:
    """The 64x36 grey thumbnail of a frame, as a flat list of 0-255 values (area averaging)."""
    import cv2
    import numpy
    image = numpy.frombuffer(frame, dtype=numpy.uint8).reshape(h, w)
    return cv2.resize(image, THUMB, interpolation=cv2.INTER_AREA).flatten().tolist()


def tesseract_path() -> str:
    return shutil.which("tesseract") or TESSERACT_FALLBACK


def tesseract_env() -> dict:
    return {"OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1", "LANG": "C.UTF-8"}


def tesseract_run(args: list, data: bytes = b"") -> str:
    """Run Tesseract with no shell, on one thread, `data` on its stdin; its stdout. A failure or a timeout is a closed refusal."""
    try:
        done = subprocess.run([tesseract_path()] + args, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=tesseract_env(), timeout=TESSERACT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        fail("tool_failed", "tesseract")
    if done.returncode != 0:
        fail("tool_failed", "tesseract")
    return done.stdout.decode("utf-8", "replace")


def parse_tsv(text: str) -> list:
    """The lines of Tesseract's `tsv` answer, in reading order: the words of a (block, paragraph, line) with a confidence of CONF_MIN or more and at least two letters or
    digits, joined by a space."""
    lines, order = {}, []
    for row in text.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if conf < CONF_MIN or sum(1 for ch in word if ch.isalnum()) < 2:
            continue
        key = (cols[2], cols[3], cols[4])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
    return [" ".join(lines[key]) for key in order]


def read_text(frame: bytes, w: int, h: int, lang: str) -> list:
    """The lines of text Tesseract reads in one grey frame: the LSTM engine, sparse text (page segmentation mode 11), the frame given as a PGM on stdin."""
    pgm = b"P5\n%d %d\n255\n" % (w, h) + frame
    return parse_tsv(tesseract_run(["stdin", "stdout", "--oem", "1", "--psm", "11", "-l", lang, "tsv"], pgm))


# ---------------------------------------------------------------- one asset

def scan_asset(ffmpeg: str, spec: dict, lang: str, deadline: float) -> dict:
    """The answer row of one asset: every frame for QR codes (and a thumbnail of each, for a clip), then the frames chosen for text. `spec` is {slot, file, path, kind, w, h}."""
    path, kind, w, h = spec["path"], spec["kind"], spec["w"], spec["h"]
    read_qr, qrs, thumbs, frames, partial = make_qr_reader(), QrSet(), [], 0, False
    with contextlib.closing(decode_frames(ffmpeg, path, kind, w, h)) as source:
        for frame in source:
            if time.monotonic() > deadline:
                partial = True
                break
            qrs.add(frames, read_qr(frame, w, h))
            if kind == "clip":
                thumbs.append(thumbnail(frame, w, h))
            frames += 1
    if frames == 0 and not partial:
        fail("asset_unreadable", spec["slot"])
    frames_qr = frames
    wanted, qualified = ([0], 1) if kind == "image" else select_text_frames(thumbs)
    lines, read = [], 0
    if partial:                                      # the budget ended in the QR pass: no text is read, and the row says so
        wanted = []
    if wanted:
        last = wanted[-1]
        with contextlib.closing(decode_frames(ffmpeg, path, kind, w, h)) as source:
            for index, frame in enumerate(source):
                if index > last:
                    break
                if index not in wanted:
                    continue
                if time.monotonic() > deadline:
                    partial = True
                    break
                lines += read_text(frame, w, h, lang)
                read += 1
    text = cut_text(lines)
    codes = set()
    if alnum_count(dedupe(lines)) >= TEXT_FOUND_MIN:
        codes.add("text_found")
    for row in qrs.rows():
        codes.add({"link": "qr_link", "action": "qr_action", "text": "qr_text"}[row["kind"]])
    if qrs.unreadable:
        codes.add("qr_unreadable")
    if partial:                                      # frames were chosen and not read: the budget ended
        codes.add("scan_partial")
    return {"slot": spec["slot"], "file": spec["file"], "kind": kind, "frames": frames, "frames_qr": frames_qr, "frames_text": read, "frames_changed": qualified if frames else 0,
            "partial": partial, "codes": sorted(codes), "text": text, "qr": qrs.rows()}


# ---------------------------------------------------------------- the verb

def parse_assets(assets: list, sizes: list) -> list:
    """[{slot, file, path, kind, w, h}] from `--asset SLOT=FILE` and `--size SLOT=WxH`: a slot id each once, a file named `asset-<sha12>.png` or `.mp4`, a size of 1 to MAX_SIDE a side."""
    if not assets:
        fail("no_assets", "asset")
    if len(assets) > MAX_ASSETS:
        fail("too_many_assets", "asset")
    wanted = {}
    for item in sizes or []:
        slot, sep, dims = item.partition("=")
        m = re.fullmatch(r"([0-9]{1,5})x([0-9]{1,5})", dims)
        if not sep or not m or slot in wanted or not 1 <= int(m.group(1)) <= MAX_SIDE or not 1 <= int(m.group(2)) <= MAX_SIDE:
            fail("bad_size", slot[:32])
        wanted[slot] = (int(m.group(1)), int(m.group(2)))
    out, seen = [], set()
    for item in assets:
        slot, sep, path = item.partition("=")
        name = os.path.basename(path)
        if not sep or not SLOT_ID.fullmatch(slot) or slot in seen:
            fail("bad_slot", slot[:32])
        if not ASSET_NAME.fullmatch(name) or slot not in wanted:
            fail("bad_asset", slot[:32])
        seen.add(slot)
        out.append({"slot": slot, "file": name, "path": path, "kind": KIND_OF[name.rsplit(".", 1)[1]], "w": wanted[slot][0], "h": wanted[slot][1]})
    if set(wanted) != seen:
        fail("bad_size", "size")
    return out


def tool_versions(lang: str) -> dict:
    """{tesseract, opencv, tessdata}: the Tesseract program's version, OpenCV's and the sorted languages whose data Tesseract has; a language of `lang` it lacks, or no
    OpenCV, is `not_ready`."""
    version = tesseract_run(["--version"]).splitlines()
    langs = sorted(x.strip() for x in tesseract_run(["--list-langs"]).splitlines()[1:] if x.strip())
    if not version or any(code not in langs for code in lang.split("+")):
        raise_not_ready("scan:tessdata")
    try:
        import cv2
    except ImportError:
        raise_not_ready("scan:opencv")
    return {"tesseract": version[0].split()[-1][:40], "opencv": str(cv2.__version__)[:40], "tessdata": langs[:16]}


def raise_not_ready(field: str):
    """Something the image should hold is missing: the refusal `not_ready`, which `_inner.verb_scan` turns into its `NotConfigured` (exit 3)."""
    raise Refusal("not_ready", field)


def scan(*, assets: list, sizes: list, lang: str, ffmpeg: str) -> dict:
    """Scan every asset (one worker each, at most the container's cpus) and return the answer described in the module's text."""
    if not LANG.fullmatch(lang or ""):
        fail("bad_lang", "lang")
    specs = parse_assets(assets, sizes)
    deadline = time.monotonic() + SCAN_BUDGET_S
    versions = tool_versions(lang)
    workers = max(1, min(len(specs), len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(lambda spec: scan_asset(ffmpeg, spec, lang, deadline), specs))
    return {"ok": True, "lang": lang, "versions": versions, "assets": rows}
