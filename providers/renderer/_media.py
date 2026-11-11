"""ffprobe and ffmpeg: facts, silence detection, the argv of the render, and the platform's video spec.

Every command is an argv list (there is no shell). Every ffprobe and ffmpeg input of the recording gets
`-f mov -protocol_whitelist file`; an asset is read with the forced demuxer and decoder of its type. A command runs in its
own session and its process group is killed past the time limit. The one ffmpeg command of the render (compose_argv)
has no path inside its filter graph. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import struct
import subprocess

from _text import Refusal

RECORDING_IN = ["-f", "mov", "-enable_drefs", "0", "-protocol_whitelist", "file"]   # no external data reference, no protocol but file
TAGS = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
VIDEO_CODECS = ("h264", "hevc")
AUDIO_CODECS = ("aac", "alac", "mp3", "pcm_s16le", "pcm_s24le")
PRORES_CODECS = ("prores",)             # the one video codec the encode stage accepts: the HyperFrames engine's intermediate
PROXY_CRF = 14                          # S2's proxy: x264 CRF 14 kept the picture the render needs at 361 MB for 192.66 s
PROXY_MAX_BYTES = 2 * 1024 ** 3         # S2: 361 MB for 192.66 s; 300 s at that rate is about 560 MB; the cap leaves room for busier content
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
# Data streams (an iPhone .mov carries three: metadata and timecode tracks) are ignored: counted for nothing and never
# mapped, so never read. Only the first video and the first audio stream are mapped.


class ToolError(Refusal):
    """A tool failed. `tail` (the last lines of its stderr) is for the operator's terminal only, never for a record."""

    def __init__(self, code: str, field: str = "", tail: str = ""):
        super().__init__(code, field)
        self.tail = tail


def run(argv, timeout: float, cwd=None):
    """Run argv with no shell and no stdin, in its own session; kill the group past `timeout`. Returns (stdout, stderr)."""
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, cwd=cwd,
                                start_new_session=True)
    except OSError:
        raise ToolError("tool_not_runnable", os.path.basename(str(argv[0]))) from None
    try:
        out, err = proc.communicate(timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.communicate()
        raise ToolError("time_limit", os.path.basename(str(argv[0]))) from None
    if proc.returncode != 0:
        tail = " | ".join(err.decode("utf-8", "replace").strip().splitlines()[-6:])
        raise ToolError("tool_failed", os.path.basename(str(argv[0])), tail)
    return out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tool_version(path: str) -> str:
    try:
        out, _ = run([path, "-version"], 20)
    except Refusal:
        return "unknown"
    return out.splitlines()[0] if out else "unknown"


def has_filter(ffmpeg: str, name: str) -> bool:
    try:
        out, _ = run([ffmpeg, "-hide_banner", "-filters"], 30)
    except Refusal:
        return False
    return re.search(r"^\s*\S+\s+%s\s" % re.escape(name), out, re.M) is not None


def _fps(text) -> float:
    try:
        num, den = str(text).split("/")
        return float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(ffprobe: str, path: str, timeout: float = 60, *, video_codecs=VIDEO_CODECS, audio_codecs=AUDIO_CODECS) -> dict:
    """Facts of a recording. Refuses more than one video stream, more than one audio stream, a stream of any other
    kind than data (data streams are ignored), HDR, and codecs outside the whitelist (`video_codecs` and `audio_codecs`, today's lists by default). Sizes are the displayed ones (rotation applied)."""
    out, _ = run([ffprobe, "-v", "error", *RECORDING_IN, "-show_streams", "-show_format", "-of", "json", path], timeout)
    try:
        info = json.loads(out)
        streams = info["streams"]
        video = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        other = [s for s in streams if s.get("codec_type") not in ("video", "audio")]
    except (ValueError, KeyError, TypeError):
        raise ToolError("probe_unreadable") from None
    if len(video) != 1:
        raise Refusal("video_streams", "input")
    if len(audio) > 1:
        raise Refusal("audio_streams", "input")
    if any(s.get("codec_type") != "data" for s in other):
        raise Refusal("other_streams", "input")
    v = video[0]
    if v.get("disposition", {}).get("attached_pic"):
        raise Refusal("video_streams", "input")
    if v.get("codec_name") not in video_codecs:
        raise Refusal("video_codec", "input")
    if audio and audio[0].get("codec_name") not in audio_codecs:
        raise Refusal("audio_codec", "input")
    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(round(float(sd["rotation"]))) % 360
    if not rotation and (v.get("tags") or {}).get("rotate"):
        try:
            rotation = int(float(v["tags"]["rotate"])) % 360
        except ValueError:
            rotation = 0
    w, h = int(v["width"]), int(v["height"])
    if rotation in (90, 270):
        w, h = h, w
    transfer, space = v.get("color_transfer"), v.get("color_space")
    if transfer in HDR_TRANSFERS or (space or "").startswith("bt2020"):
        raise Refusal("hdr_input", "input")
    try:
        duration = float(info["format"]["duration"])
        size = int(info["format"]["size"])
    except (KeyError, ValueError):
        raise ToolError("probe_unreadable") from None
    def start(stream):
        try:
            value = float(stream.get("start_time", 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        return round(value, 4) if math.isfinite(value) else 0.0

    return {"video_start": start(v), "audio_start": start(audio[0]) if audio else 0.0, "width": w, "height": h, "rotation": rotation, "fps": round(_fps(v.get("avg_frame_rate")) or _fps(v.get("r_frame_rate")), 3),
            "duration": round(duration, 3), "has_audio": bool(audio), "codec": v["codec_name"], "pix_fmt": v.get("pix_fmt"),
            "color_space": space, "color_transfer": transfer, "color_primaries": v.get("color_primaries"),
            "color_range": v.get("color_range"), "bytes": size, "audio_codec": audio[0]["codec_name"] if audio else None}


def silencedetect(ffmpeg: str, path: str, duration: float, noise_db: float = -35, min_seconds: float = 0.3,
                  timeout: float = 600) -> list:
    """Silence intervals [{start, end}] of the recording's audio; an interval still open at the end closes there."""
    _, err = run([ffmpeg, "-hide_banner", "-nostats", *RECORDING_IN, "-i", path, "-vn", "-af",
                  "silencedetect=noise=%gdB:d=%g" % (noise_db, min_seconds), "-f", "null", "-"], timeout)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", err)]
    return [{"start": round(max(0.0, s), 3), "end": round(ends[k] if k < len(ends) else duration, 3)}
            for k, s in enumerate(starts)]


# ---------------------------------------------------------------- the output file

def top_level_boxes(path: str, limit: int = 64) -> list:
    """The type of each top-level box of an MP4 file, in order (the first `limit`)."""
    kinds = []
    with open(path, "rb") as fh:
        size_total = os.fstat(fh.fileno()).st_size
        pos = 0
        while pos + 8 <= size_total and len(kinds) < limit:
            fh.seek(pos)
            head = fh.read(16)
            size, kind = struct.unpack(">I4s", head[:8])
            header = 8
            if size == 1 and len(head) >= 16:
                size, header = struct.unpack(">Q", head[8:16])[0], 16
            elif size == 0:
                size = size_total - pos
            kinds.append(kind.decode("latin-1"))
            if size < header:
                break
            pos += size
    return kinds


def faststart(path: str) -> bool:
    kinds = top_level_boxes(path)
    return "moov" in kinds and ("mdat" not in kinds or kinds.index("moov") < kinds.index("mdat"))


def _ratio(text):
    a, _, b = str(text).partition(":")
    return float(a) / float(b)


def check_output(ffprobe: str, path: str, platform: dict, timeout: float = 60) -> dict:
    """ffprobe the render against the platform file's `video` block. Returns {facts, failures}; each failure is a
    closed code. Nothing is raised for a failed spec: the caller refuses the render."""
    spec = platform.get("video") or {}
    out, _ = run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path], timeout)
    info = json.loads(out)
    video = [s for s in info["streams"] if s["codec_type"] == "video"]
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    failures = []
    if len(video) != 1 or len(audio) > 1 or len(video) + len(audio) != len(info["streams"]):
        failures.append("streams")
        return {"facts": {}, "failures": failures}
    v = video[0]
    codec = {"hevc": "h265"}.get(v["codec_name"], v["codec_name"])
    width, height = int(v["width"]), int(v["height"])
    fps = _fps(v.get("avg_frame_rate"))
    duration = float(info["format"]["duration"])
    size = int(info["format"]["size"])
    facts = {"container": info["format"]["format_name"], "codec": codec, "profile": v.get("profile"), "pix_fmt": v.get("pix_fmt"),
             "width": width, "height": height, "fps": round(fps, 3), "duration": round(duration, 3), "bytes": size,
             "audio_codec": audio[0]["codec_name"] if audio else None, "faststart": faststart(path),
             "color": [v.get("color_space"), v.get("color_primaries"), v.get("color_transfer"), v.get("color_range")],
             "frames": v.get("nb_frames")}
    if "mp4" not in facts["container"] and "mov" not in facts["container"]:
        failures.append("container")
    if spec.get("codecs") and codec not in spec["codecs"]:
        failures.append("codec")
    if audio and spec.get("audio_codecs") and audio[0]["codec_name"] not in spec["audio_codecs"]:
        failures.append("audio_codec")
    if spec.get("fps_min") is not None and fps < spec["fps_min"] - 0.01:
        failures.append("fps_min")
    if spec.get("fps_max") is not None and fps > spec["fps_max"] + 0.01:
        failures.append("fps_max")
    if spec.get("max_width") and width > spec["max_width"]:
        failures.append("max_width")
    for key, value in (("min_side", min(width, height)), ("max_side", max(width, height))):
        if spec.get(key) is not None and ((key == "min_side" and value < spec[key]) or (key == "max_side" and value > spec[key])):
            failures.append(key)
    if spec.get("min_seconds") is not None and duration < spec["min_seconds"]:
        failures.append("min_seconds")
    if spec.get("max_seconds") is not None and duration > spec["max_seconds"]:
        failures.append("max_seconds")
    limit = min([x for x in (spec.get("max_bytes"), (platform.get("media") or {}).get("max_bytes")) if x] or [0])
    if limit and size > limit:
        failures.append("max_bytes")
    aspect = spec.get("aspect") or {}
    try:
        if aspect.get("min") and width / height < _ratio(aspect["min"]) - 1e-9:
            failures.append("aspect_min")
        if aspect.get("max") and width / height > _ratio(aspect["max"]) + 1e-9:
            failures.append("aspect_max")
    except (ValueError, ZeroDivisionError):
        failures.append("aspect_spec")
    if spec.get("faststart") and not facts["faststart"]:
        failures.append("faststart")
    return {"facts": facts, "failures": failures}


def byte_limit(platform: dict) -> int:
    """The `-fs` limit: the smaller of the platform file's two byte limits."""
    values = [x for x in ((platform.get("video") or {}).get("max_bytes"), (platform.get("media") or {}).get("max_bytes")) if x]
    return min(values) if values else 300_000_000


# ---------------------------------------------------------------- the render's one ffmpeg command

def asset_input(kind: str, path: str) -> list:
    """An image asset, read with the forced demuxer and decoder of its type."""
    demuxer, decoder = {"png": ("png_pipe", "png"), "jpg": ("jpeg_pipe", "mjpeg")}[kind]
    return ["-f", demuxer, "-c:v", decoder, "-protocol_whitelist", "file", "-i", path]


def _even(x: float) -> int:
    n = int(math.ceil(x))
    return n + (n % 2)


PUSH_MIN_SECONDS = 5.0     # only a range this long gets the slow push-in
SWS = "lanczos+accurate_rnd+bitexact"     # every scale: the same arithmetic whatever SIMD the CPU has (bitexact), no threads-dependent rounding
THREADS = 4                                # the decoders and filter graphs of the compose, the proxy and the contact sheet (with swscale's slices); no encoder reads it
ENCODE_INPUT_THREADS = 1                   # the encode's decoder and filter graph: one thread, so no worker can race another at the end of the stream (CI: 7 of 8 encodes matched, the tail frame of one differed)
ENCODE_THREADS = 1                         # the preview's x264 threads: one (its argv is pinned on one thread, decoder and filter graph too)
X264_THREADS = 4                           # x264's threads in the compose, the proxy and the final encode: four SLICE threads (sliced-threads=1), not frame threads: frame threads differed on amd64 CI (2026-11-08 final encode, 1 of 8, mid-stream; 2026-11-09 compose, frame 0), because a frame thread reads state another frame thread is still writing; the slices of one frame are encoded in parallel with no such state (one thread was the first fix and cost about 2x on the proxy)
X264_PARAMS = "threads=%d:lookahead_threads=1:sliced-threads=1" % X264_THREADS
PREVIEW_X264_PARAMS = "threads=%d:lookahead_threads=1:sliced-threads=0" % ENCODE_THREADS
BASE = 2                   # the picture is cut at twice the output size, so a zoom never upscales (and a slow zoom does not jitter)


def anchor_point(face: dict, anchor_y: float) -> tuple:
    """The fixed point of a zoom, in output pixels: the face's horizontal centre, `anchor_y` of the box's height from its top."""
    return face["x"] + face["w"] / 2.0, face["y"] + anchor_y * face["h"]


def zoom_levels(zoom: dict, k: int, frames: int, fps: int) -> tuple:
    """(zoom at the first frame, zoom at the last frame) of kept range number k: `alternate` draws every second range at `factor`;
    a range of PUSH_MIN_SECONDS or more also pushes in by `push_in` over its length."""
    z0 = zoom["factor"] if zoom["mode"] == "alternate" and k % 2 == 1 else 1.0
    z1 = z0 * (1.0 + zoom["push_in"]) if zoom["push_in"] > 0 and frames / float(fps) >= PUSH_MIN_SECONDS else z0
    return z0, z1


def zoomed_box(face: dict, z0: float, z1: float, anchor: tuple, w: int, h: int) -> dict:
    """Where the face box {x, y, w, h} lands in the output frame while a range is zoomed from z0 to z1 about the fixed point
    `anchor`: the picture grows about that point, so every point p lands at anchor + (p - anchor) * z. The bounding box of the box at
    the start and at the end of the range, outward to whole pixels, inside the frame."""
    ax, ay = anchor
    boxes = [(ax + (face["x"] - ax) * z, ay + (face["y"] - ay) * z, ax + (face["x"] + face["w"] - ax) * z, ay + (face["y"] + face["h"] - ay) * z)
             for z in {z0, z1}]
    left, top = max(0, int(math.floor(min(b[0] for b in boxes)))), max(0, int(math.floor(min(b[1] for b in boxes))))
    right, bottom = min(w, int(math.ceil(max(b[2] for b in boxes)))), min(h, int(math.ceil(max(b[3] for b in boxes))))
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def punch_expression(punches, base_z: str, frame: str = "on") -> str:
    """The zoom as a function of the range's frame index `on`: `base_z` outside the punches, a punch's level inside it. `punches` is [(a, b, level)]
    in the range's own frame index, b excluded (so the last frame is b - 1), earliest first and never overlapping. No punch gives `base_z` itself.
    `frame` is the expression that is the 0-based frame index in the filter that reads it (`on` in zoompan; `on-1` in perspective: see `zoom_filter_linear`)."""
    out = base_z
    for a, b, level in reversed(list(punches or [])):
        out = "if(between(%s,%d,%d),%.5f,%s)" % (frame, a, b - 1, level, out)
    return out


def zoom_filter(z0: float, z1: float, frames: int, anchor: tuple, w: int, h: int, fps, base: int = BASE, punches=()) -> str:
    """The filter from the picture cut at `base` (BASE by default) times the output size to the output for one kept range: a plain scale
    at 100%, else a zoompan about the fixed point `anchor` (output pixels): the point stays where it is while the picture grows about it.
    The pixel check of the HyperFrames engine gives `base` 1: it zooms the 1080x1920 proxy, not a picture cut at twice the size.
    `punches` ([(a, b, level)], see `punch_expression`) steps the zoom to a constant level on those frames and back; with none, the text is what it
    always was."""
    if not punches and abs(z0 - 1.0) < 1e-6 and abs(z1 - 1.0) < 1e-6:
        return "scale=%d:%d:flags=%s" % (w, h, SWS)
    ax, ay = anchor[0] * base, anchor[1] * base
    z = "%.5f" % z0 if abs(z1 - z0) < 1e-6 else "%.5f+%.6f*on" % (z0, (z1 - z0) / max(1, frames - 1))
    z = punch_expression(punches, z)
    return "zoompan=z='%s':x='%.2f*(1-1/zoom)':y='%.2f*(1-1/zoom)':d=1:s=%dx%d:fps=%s" % (z, ax, ay, w, h, fps)


def zoom_filter_linear(z0: float, z1: float, frames: int, anchor: tuple, w: int, h: int, punches=()) -> str:
    """The same zoom as `zoom_filter` about the same fixed point, sampled bilinearly at exact fractional positions: `perspective` with linear
    interpolation maps the window of the picture (its size divided by the zoom, its corner at the anchor's fixed point) onto the whole frame, per frame
    (`on` counts the range's frames). It is what a browser does to a scaled video layer, which is why the pixel check's reference uses it; the ffmpeg
    engine's own render keeps `zoom_filter`. Both zooms are the same arithmetic about the same point. `punches` as in `zoom_filter`."""
    if not punches and abs(z0 - 1.0) < 1e-6 and abs(z1 - 1.0) < 1e-6:
        return "scale=%d:%d:flags=%s" % (w, h, SWS)
    ax, ay = anchor
    z = "%.5f" % z0 if abs(z1 - z0) < 1e-6 else "(%.5f+%.6f*on)" % (z0, (z1 - z0) / max(1, frames - 1))
    if punches:
        # perspective counts `on` from 1 (frame i reads on = i + 1; vf_perspective adds one), zoompan from 0: a punch row is in 0-based frames, so it
        # reads `on-1` here, or the reference would switch one frame before the page and the encoder (found live 2026-11-10: psnr 20.9 at frames 51 and 66)
        z = "(%s)" % punch_expression(punches, z, "on-1")
    x0, y0 = "%.2f*(1-1/%s)" % (ax, z), "%.2f*(1-1/%s)" % (ay, z)
    wz, hz = "%d/%s" % (w, z), "%d/%s" % (h, z)
    return ("perspective=x0='%s':y0='%s':x1='%s+%s':y1='%s':x2='%s':y2='%s+%s':x3='%s+%s':y3='%s+%s':interpolation=linear:eval=frame:sense=source"
            % (x0, y0, x0, wz, y0, x0, y0, hz, x0, wz, y0, hz))


def bubble_crop(face: dict, w: int, h: int) -> tuple:
    """(side, x, y) of the square of the frame that the speaker's round bubble shows: the face box with some air."""
    side = min(w, h, _even(max(face["w"], face["h"]) * 1.2))
    x = int(min(max(face["cx"] - side / 2, 0), w - side))
    y = int(min(max(face["cy"] - side / 2, 0), h - side))
    return side, x, y


def framing_filter(w: int, h: int, src_matrix: str) -> str:
    """How the render frames a source into the output: scaled up to cover twice the output size (BASE), the centre cropped to it,
    read through the source's colour matrix and written as bt709 limited range. The render's graph and the still frame use this one
    text, so a pixel of the still is the pixel of the render's unzoomed picture."""
    return ("scale=%d:%d:force_original_aspect_ratio=increase:in_color_matrix=%s:out_color_matrix=bt709:out_range=tv:flags=%s,"
            "crop=%d:%d,setsar=1" % (w * BASE, h * BASE, src_matrix, SWS, w * BASE, h * BASE))


MONO_MATRIX = "rr=.2126:rg=.7152:rb=.0722:gr=.2126:gg=.7152:gb=.0722:br=.2126:bg=.7152:bb=.0722"     # the CSS `grayscale(1)` matrix: one formula in both engines
TO_RGB = "scale=in_range=tv:in_color_matrix=bt709:out_range=pc:flags=%s,format=gbrp" % SWS            # colorchannelmixer reads RGB: the picture goes through
FROM_RGB = "scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=%s,format=yuv420p" % SWS    # explicit bt709 conversions, as the compose's own RGB stage


def yuv_limited_bt709(color: str) -> tuple:
    """(Y, U, V) of an `#rrggbb` colour as bt709 limited-range 8-bit values: the colour the pictures of the render are written in."""
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 16 + 219 * y, 128 + 224 * (b - y) / 1.8556, 128 + 224 * (r - y) / 1.5748


def blend_filter(color: str, alpha: float, enable: str) -> str:
    """One colour laid over the whole picture at `alpha` on the frames `enable` names, as the exact blend in each plane of yuv420p: every plane goes to
    plane * (1 - alpha) + colour's plane * alpha. A colour is an affine function of RGB, so this is the browser's RGB alpha blend. `drawbox` is not used: on
    yuv420p it takes the chroma of a saturated picture towards grey about twice as far as the blend asks (measured on SMPTE bars, 2026-11-11: at alpha .35 a
    bar's U moved from 147 to 130 where the blend gives 141), which the face check read as a changed face."""
    yy, uu, vv = yuv_limited_bt709(color)
    return ("lutyuv=y='val*(1-%.3f)+%.2f*%.3f':u='val*(1-%.3f)+%.2f*%.3f':v='val*(1-%.3f)+%.2f*%.3f':enable='%s'"
            % (alpha, yy, alpha, alpha, uu, alpha, alpha, vv, alpha, enable))


def grade_filters(grades: list) -> list:
    """The filters of the grades of one kept range, in the range's own frame index `n` (a to b, b excluded), as a list of strings (empty for none):
    a flash or a dip is one blend (`blend_filter`) of white or black per frame of its ramp, a tint one blend of the accent colour over its span, mono
    the CSS grayscale matrix over its span (`colorchannelmixer`, between two bt709 conversions, FIRST, and only in a range that has a mono row: the page's
    mono is a filter on the video below the `#fx` colour layer, so a tint or a flash over a grey frame stays coloured). Only the frames of a grade are
    touched (the conversions around mono run on every frame of that range)."""
    out, mono = [], []
    for g in grades:
        if g["kind"] in ("flash", "dip"):
            color = "#FFFFFF" if g["kind"] == "flash" else "#000000"
            for i, alpha in enumerate(g["alphas"]):
                out.append(blend_filter(color, alpha, "eq(n,%d)" % (g["a"] + i)))
        elif g["kind"] == "tint":
            out.append(blend_filter(g["color"], g["alpha"], "between(n,%d,%d)" % (g["a"], g["b"] - 1)))
        elif g["kind"] == "mono":
            mono.append("colorchannelmixer=%s:enable='between(n,%d,%d)'" % (MONO_MATRIX, g["a"], g["b"] - 1))
    return ([TO_RGB] + mono + [FROM_RGB] if mono else []) + out


def base_graph(plan: dict, *, source: str = "[0:v:0]", prepare=None, base: int = BASE, audio: bool = True, zoom_linear: bool = False, first_index: int = 0) -> list:
    """The filter strings of the cut and zoomed picture, with no layer and no pip: the source cut into the kept ranges, each zoomed about
    the face as the plan says, joined by `concat` into `[cv]` (and, when the plan has audio and `audio` is true, `[aout]`). The render
    (`compose_argv`) and the pixel check of the HyperFrames engine (`_hf_gate`) build the picture from this one function, so the
    reference the check compares with is the base the ffmpeg engine draws. `plan` holds fps, size [w, h], kept, zoom, anchor, fade and
    has_audio, and src_matrix unless `prepare` is given. `source` is the label of the video input; `prepare` the filters from it to `[sv]`
    (by default the recording's framing at `base` times the output size); `base` the factor the picture is cut at, which `zoom_filter`
    needs to know. `zoom_linear` zooms with `zoom_filter_linear` (bilinear, exact positions, on a picture at the output size, so `base` is 1) instead of
    `zoom_filter`: the reference of the pixel check zooms the 1080x1920 proxy this way, as a browser zooms a video layer."""
    fps, (w, h) = plan["fps"], plan["size"]
    kept, has_audio = plan["kept"], plan["has_audio"] and audio
    n = len(kept)
    if prepare is None:
        prepare = "fps=%s:start_time=0,%s,format=yuv420p" % (fps, framing_filter(w, h, plan["src_matrix"]))
    g = ["%s%s[sv]" % (source, prepare)]
    if n > 1:
        g.append("[sv]split=%d%s" % (n, "".join("[s%d]" % k for k in range(n))))
        src_v = ["[s%d]" % k for k in range(n)]
    else:
        src_v = ["[sv]"]
    cat_in = []
    zoom, fade = plan["zoom"], plan["fade"]
    effects = plan.get("effects") or {}
    for k, (a, b) in enumerate(kept):
        z0, z1 = zoom_levels(zoom, first_index + k, b - a, fps)       # first_index: the number of the first kept range when a plan holds a part of the list
        fx = effects.get(first_index + k) or {}                      # the punches and grades of this range (`_edl.range_effects`), in its own frame index
        punches = fx.get("punches") or ()
        zf = (zoom_filter_linear(z0, z1, b - a, plan["anchor"], w, h, punches) if zoom_linear
              else zoom_filter(z0, z1, b - a, plan["anchor"], w, h, fps, base, punches))
        grades = "".join("%s," % f for f in grade_filters(fx.get("grades") or []))
        if grades:      # a grade comes after the zoom, before the format the range is joined in
            g.append("%strim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS,%s,setsar=1,%sformat=yuv420p[v%d]" % (src_v[k], a, b, zf, grades, k))
        else:
            g.append("%strim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS,%s,setsar=1,format=yuv420p[v%d]" % (src_v[k], a, b, zf, k))
        cat_in.append("[v%d]" % k)
        if has_audio:
            # a few milliseconds of fade at each end of a range, so that a cut never clicks; the length stays, so sound and
            # picture stay in step
            d = min(fade, (b - a) / fps / 2)
            g.append("[0:a:0]aresample=async=1:first_pts=0,atrim=start=%.6f:end=%.6f,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=%.4f,afade=t=out:st=%.6f:d=%.4f[a%d]"
                     % (a / fps, b / fps, d, (b - a) / fps - d, d, k))
            cat_in.append("[a%d]" % k)
    g.append("%sconcat=n=%d:v=1:a=%d[cv]%s" % ("".join(cat_in), n, 1 if has_audio else 0, "[ca]" if has_audio else ""))
    if has_audio:
        g.append("[ca]aformat=sample_rates=48000:channel_layouts=stereo[aout]")
    return g


def compose_argv(ffmpeg: str, plan: dict) -> list:
    """The whole render as one ffmpeg command, built as a list. `plan` holds:

      src, has_audio, fps, size [w, h], src_matrix ("bt709" or "auto"), kept [[from_frame, to_frame], ...] on the
      source frame grid at `fps`, layers (a subset of ["beat", "caption"]), frames_dir (relative to the working folder),
      pips [{asset, kind, start_frame, end_frame, x, y, w, h, radius}], out_frames, max_bytes, out_name (relative).

    The picture, from the bottom: the cut recording (the speaker, full frame, as without a pip); for each pip layout the asset (an image,
    or a clip when `kind` is "clip") scaled to its card box and masked to a rounded rectangle, over the speaker on the beat's frames; the
    beat frames; the captions. Everything is composed in RGB (gbrp), the recording read as bt709 limited
    range and written back as bt709, tagged with setparams. No path is inside the filter graph.
    """
    fps, (w, h) = plan["fps"], plan["size"]
    has_audio = plan["has_audio"]
    inputs = ["-threads", str(THREADS), *RECORDING_IN, "-i", plan["src"]]    # the decoder's threads: speed only, a decoder is exact whatever the count
    idx, nxt = {}, 1
    for layer, prefix in (("beat", "beat"), ("caption", "cap")):
        if layer in plan["layers"]:
            inputs += ["-f", "image2", "-c:v", "png", "-protocol_whitelist", "file", "-framerate", str(fps),
                       "-i", "%s/%s_%%06d.png" % (plan["frames_dir"], prefix)]
            idx[layer] = nxt
            nxt += 1
    pips = plan["pips"]
    pip_in = []
    mask_in = []
    for p in pips:
        if p["kind"] == "clip":      # a clip is read as its own container says, from a file only
            inputs += ["-protocol_whitelist", "file", "-i", p["asset"]]
        else:
            inputs += asset_input(p["kind"], p["asset"])
        pip_in.append(nxt)
        nxt += 1
        r, lo, hi = p["radius"], p["start_frame"], p["end_frame"] - 1
        # the card's corners: a rounded rectangle the size of the box, one pixel of soft edge, as a gray mask; it is nothing outside the beat's
        # frames (`N` is the frame's number from 0, on this source's own regular clock), so the mask runs the whole length of the output
        inputs += ["-f", "lavfi", "-i", ("color=c=black:s=%dx%d:r=%s,geq=lum='if(between(N,%d,%d),clip((%d-hypot(max(abs(X+0.5-W/2)-(W/2-%d),0),max(abs(Y+0.5-H/2)-(H/2-%d),0)))*255,0,255),0)'"
                                          ":cb=128:cr=128,format=gray") % (p["w"], p["h"], fps, lo, hi, r, r, r)]
        mask_in.append(nxt)
        nxt += 1

    g = base_graph(plan)

    if not idx and not pips:
        g.append("[cv]%s[vout]" % TAGS)
    else:
        g.append("[cv]scale=in_range=tv:in_color_matrix=bt709:out_range=pc:flags=%s,format=gbrp[base]" % SWS)
        cur = "base"
        for i, p in enumerate(pips):
            # The card is a stream the whole length of the output, like the beat and caption frames, and the overlay pairs it with the base by
            # timestamp exactly as it pairs them: transparent (the mask is 0) before and after the beat, the card on frames start_frame..end_frame-1.
            # An `enable` expression on `n` or a float `t` is evaluated by the overlay's own bookkeeping, which can sit a frame off; a sparse stream
            # that exists only during the beat is dropped a frame early when the base's timestamps jitter. This one has no edge to be off by.
            total, first = plan["out_frames"], p["start_frame"]
            if p["kind"] == "clip":      # a clip plays from the beat's first frame (its first frame is held before, its last after)
                g.append("[%d:v]fps=%s,tpad=start=%d:start_mode=clone:stop=-1:stop_mode=clone,trim=end_frame=%d,setpts=N/(%s*TB),scale=%d:%d:flags=%s,format=gbrp[ca%d]"
                         % (pip_in[i], fps, first, total, fps, p["w"], p["h"], SWS, i))
            else:
                g.append("[%d:v]scale=%d:%d:flags=%s,format=gbrp,loop=loop=-1:size=1:start=0,fps=%s,trim=end_frame=%d,setpts=N/(%s*TB)[ca%d]"
                         % (pip_in[i], p["w"], p["h"], SWS, fps, total, fps, i))
            g.append("[%d:v]format=gray,trim=end_frame=%d,setpts=N/(%s*TB)[cm%d]" % (mask_in[i], total, fps, i))
            g.append("[ca%d][cm%d]alphamerge[card%d]" % (i, i, i))
            g.append("[%s][card%d]overlay=%d:%d:format=gbrp[ob%d]" % (cur, i, p["x"], p["y"], i))
            cur = "ob%d" % i
        for layer in ("beat", "caption"):
            if layer in idx:
                g.append("[%d:v]format=gbrap[l_%s]" % (idx[layer], layer))
                g.append("[%s][l_%s]overlay=0:0:format=gbrp[c_%s]" % (cur, layer, layer))
                cur = "c_%s" % layer
        g.append("[%s]scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=%s,format=yuv420p,%s[vout]" % (cur, SWS, TAGS))

    argv = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", str(THREADS), "-filter_complex_threads", str(THREADS),
            *inputs, "-filter_complex", ";".join(g), "-map", "[vout]"]
    if has_audio:
        argv += ["-map", "[aout]"]
    argv += output_options(plan)
    return argv + [plan["out_name"]]


def output_options(plan: dict, threads: int = X264_THREADS, *, shortest: bool = True, x264_params: str = X264_PARAMS) -> list:
    """The output side of the final H.264 encode, shared by both engines (the ffmpeg engine's compose and the HyperFrames engine's
    encode stage): AAC when the plan has audio, then x264 on four slice threads (X264_THREADS, X264_PARAMS: sliced threads, not frame threads), every
    scale bit-exact (`-sws_flags`), the bitexact flags, no metadata and chapters, the rate, the frame count and the byte cap.
    x264's output depends on its thread count and the automatic count follows the cores the machine shows, so the same render would
    otherwise differ in bytes from one CPU limit or machine to another. What this function does NOT pin is the input side: the
    decoder's threads, the filter graph's (`-filter_threads`, `-filter_complex_threads`, and with them swscale's slices) belong to
    the command that calls it (compose_argv and encode_argv each pin them). `shortest` writes `-shortest` (compose's way of ending
    the streams); the encode stage passes False and ends both streams exactly instead. `plan` holds fps, out_frames, max_bytes and,
    optionally, has_audio (true by default). The output name is not included."""
    argv = []
    if plan.get("has_audio", True):
        argv += ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    argv += ["-sws_flags", SWS, "-c:v", "libx264", "-threads", str(threads)]
    if x264_params:
        argv += ["-x264-params", x264_params]
    argv += ["-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
             "-r", str(plan["fps"]), "-fps_mode", "cfr", "-frames:v", str(plan["out_frames"])]
    if shortest:
        argv += ["-shortest"]
    argv += ["-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
             "-fs", str(plan["max_bytes"]), "-movflags", "+faststart"]
    return argv


def proxy_argv(ffmpeg: str, src: str, src_matrix: str, out: str, *, fps: int, has_audio: bool) -> list:
    """The proxy of a recording for the HyperFrames engine: 1080x1920 at the edit list's fps, x264 (four slice threads) CRF PROXY_CRF with fixed threads
    and bit-exact scaling, the audio as the final encode writes it. The whole timeline is kept (no cut), so a time of the edit list is
    the same time in the proxy. At most PROXY_MAX_BYTES."""
    # framing_filter cuts at BASE times the output size (for the zoom); the proxy is the plain scale down to the output, as an unzoomed range is
    vf = "fps=%s:start_time=0,%s,format=yuv420p,scale=1080:1920:flags=%s,%s" % (fps, framing_filter(1080, 1920, src_matrix), SWS, TAGS)
    argv = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", str(THREADS), "-filter_threads", str(THREADS),
            *RECORDING_IN, "-i", src, "-map", "0:v:0", "-vf", vf, "-sws_flags", SWS,
            "-c:v", "libx264", "-threads", str(X264_THREADS), "-x264-params", X264_PARAMS,
            "-preset", "medium", "-crf", str(PROXY_CRF), "-pix_fmt", "yuv420p"]
    if has_audio:
        argv += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    else:
        argv += ["-an"]
    argv += ["-fs", str(PROXY_MAX_BYTES), "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-map_metadata", "-1", out]
    return argv


def encode_argv(ffmpeg: str, intermediate: str, out: str, plan: dict) -> list:
    """The final H.264 encode of the HyperFrames engine: the ProRes intermediate (video, and its audio when it has one) written with
    the same output options as the ffmpeg engine's render. Nothing automatic is left that can follow the machine: the decoder's
    threads and the filter graph's (with swscale's slices), both one, x264's threads (four slice threads: X264_THREADS, X264_PARAMS), its lookahead threads and sliced threads are all named, and
    both streams end exactly (`-frames:v` and `-t` from the frame count), with no `-shortest`, so the end of the streams is not a
    race between the muxer's inputs. `plan` carries fps, out_frames and max_bytes (and has_audio, true by default)."""
    n, one = X264_THREADS, ENCODE_INPUT_THREADS
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", str(one), "-filter_complex_threads", str(one),
            "-threads", str(one), "-i", intermediate, "-map", "0:v:0", "-map", "0:a:0?",
            *output_options(plan, n, shortest=False, x264_params=X264_PARAMS),
            "-t", "%.6f" % (plan["out_frames"] / float(plan["fps"])), out]


def preview_rate(duration: float, spec: dict, has_audio: bool):
    """The video rate (kbit/s) of a preview of a render `duration` seconds long, so that the whole file fits spec["max_bytes"] with
    spec["margin"] of room: the audio's share (spec["audio_kbps"], none without audio) is taken first and one second is added for the
    container and the rounding. At most spec["max_video_kbps"]; None when it would be under spec["min_video_kbps"] (too long to fit)."""
    seconds = float(duration) + 1.0
    audio = spec["audio_kbps"] * 1000 if has_audio else 0
    rate = int((spec["max_bytes"] * 8 * spec["margin"] - audio * seconds) / seconds / 1000)
    if rate < spec["min_video_kbps"]:
        return None
    return min(rate, spec["max_video_kbps"])


def preview_argv(ffmpeg: str, src: str, out: str, spec: dict, *, video_kbps: int, has_audio: bool) -> list:
    """The preview of a finished render: scaled to spec["width"] x spec["height"] with the bit-exact scaler, x264 at CRF spec["crf"] capped
    by `video_kbps` (maxrate and a one-second buffer), AAC at spec["audio_kbps"] when the render has audio, the bt709 tags, no metadata, the
    index first (faststart). Pinned as the final encode is (encode_argv): the decoder, the filter graph and x264 on one thread each, so the
    bytes do not follow the machine. The render is read under the same input rules as a recording (RECORDING_IN)."""
    one = ENCODE_INPUT_THREADS
    rate = "%dk" % video_kbps
    vf = "scale=%d:%d:flags=%s,format=yuv420p,%s" % (spec["width"], spec["height"], SWS, TAGS)
    argv = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", str(one), "-filter_complex_threads", str(one),
            "-threads", str(one), *RECORDING_IN, "-i", src, "-map", "0:v:0"]
    if has_audio:
        argv += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "%dk" % spec["audio_kbps"], "-ar", "48000"]
    else:
        argv += ["-an"]
    argv += ["-sn", "-dn", "-vf", vf, "-sws_flags", SWS, "-c:v", "libx264", "-threads", str(ENCODE_THREADS),
             "-x264-params", PREVIEW_X264_PARAMS,
             "-preset", spec["preset"], "-crf", str(spec["crf"]), "-maxrate", rate, "-bufsize", rate, "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
             "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
             "-movflags", "+faststart", out]
    return argv


def cover_argv(ffmpeg: str, src: str, offset_seconds: float, out_name: str) -> list:
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", "%.3f" % offset_seconds, *RECORDING_IN,
            "-i", src, "-frames:v", "1", "-f", "image2", "-c:v", "png", out_name]


def still_argv(ffmpeg: str, src: str, at_seconds: float, size: tuple, src_matrix: str, out_name: str) -> list:
    """One frame of a recording at `at_seconds`, framed as the render frames it (framing_filter, then the plain scale of an unzoomed
    range down to the output size) and converted to RGB the way the render converts for its overlays, written as a PNG with no
    metadata. The same input rules as every read of a recording (RECORDING_IN)."""
    w, h = size
    graph = "%s,format=yuv420p,scale=%d:%d:flags=%s,scale=in_range=tv:in_color_matrix=bt709:out_range=pc:flags=%s,format=rgb24" % (
        framing_filter(w, h, src_matrix), w, h, SWS, SWS)
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", "%.3f" % at_seconds, *RECORDING_IN, "-i", src,
            "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", graph, "-frames:v", "1", "-map_metadata", "-1", "-fflags", "+bitexact",
            "-flags:v", "+bitexact", "-f", "image2", "-c:v", "png", out_name]
