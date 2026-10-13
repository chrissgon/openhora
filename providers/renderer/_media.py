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


def probe(ffprobe: str, path: str, timeout: float = 60) -> dict:
    """Facts of a recording. Refuses more than one video stream, more than one audio stream, a stream of any other
    kind than data (data streams are ignored), HDR, and codecs outside the whitelist. Sizes are the displayed ones (rotation applied)."""
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
    if v.get("codec_name") not in VIDEO_CODECS:
        raise Refusal("video_codec", "input")
    if audio and audio[0].get("codec_name") not in AUDIO_CODECS:
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


def zoomed_box(face: dict, z0: float, push: float, w: int, h: int) -> dict:
    """Where the face box {x, y, w, h} lands in the output frame when a kept range is drawn at zoom `z0`, and with a slow push-in
    of `push` (the zoom then ends at z0 + push): the bounding box of the box at the start and at the end of the range, outward
    to whole pixels. It mirrors zoom_chain: a static zoom is scale then a crop centred on the face and clamped to the frame; a
    push-in is zoompan with the same centre, clamped the same way."""
    cx, cy = face["x"] + face["w"] / 2.0, face["y"] + face["h"] / 2.0
    boxes = []
    for z in ((z0, z0 + push) if push > 0 else (z0,)):
        if push > 0:
            x0 = min(max(int(cx) - w / z / 2, 0), w - w / z)
            y0 = min(max(int(cy) - h / z / 2, 0), h - h / z)
            sx = sy = z
        elif z <= 1.0:
            x0 = y0 = 0
            sx = sy = 1.0
        else:
            sw, sh = _even(w * z), _even(h * z)
            x0 = int(min(max(int(cx) * sw / w - w / 2, 0), sw - w)) / (sw / w)
            y0 = int(min(max(int(cy) * sh / h - h / 2, 0), sh - h)) / (sh / h)
            sx, sy = sw / w, sh / h
        boxes.append(((face["x"] - x0) * sx, (face["y"] - y0) * sy, (face["x"] + face["w"] - x0) * sx, (face["y"] + face["h"] - y0) * sy))
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
    left, top = max(0, int(math.floor(left))), max(0, int(math.floor(top)))
    right, bottom = min(w, int(math.ceil(right))), min(h, int(math.ceil(bottom)))
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def zoom_chain(zoom: dict, face: dict, k: int, frames: int, fps: int, w: int, h: int) -> str:
    """The filters that zoom kept range number k, as a string that starts with a comma (or is empty). `alternate` draws
    every second range at `factor` centred on the face box (scale, then a static crop: no jitter); `push_in` is a slow
    extra zoom over the range (zoompan, per frame). Both stay inside the frame."""
    z0 = zoom["factor"] if zoom["mode"] == "alternate" and k % 2 == 1 else 1.0
    push = zoom["push_in"]
    cx, cy = face["cx"], face["cy"]
    if push > 0:
        return (",zoompan=z='%.4f+%.4f*on/%d':x='min(max(%d-iw/zoom/2,0),iw-iw/zoom)':y='min(max(%d-ih/zoom/2,0),ih-ih/zoom)':d=1:s=%dx%d:fps=%s"
                % (z0, push, max(1, frames), cx, cy, w, h, fps))
    if z0 <= 1.0:
        return ""
    sw, sh = _even(w * z0), _even(h * z0)
    x = int(min(max(cx * sw / w - w / 2, 0), sw - w))
    y = int(min(max(cy * sh / h - h / 2, 0), sh - h))
    return ",scale=%d:%d,crop=%d:%d:%d:%d,setsar=1" % (sw, sh, w, h, x, y)


def bubble_crop(face: dict, w: int, h: int) -> tuple:
    """(side, x, y) of the square of the frame that the speaker's round bubble shows: the face box with some air."""
    side = min(w, h, _even(max(face["w"], face["h"]) * 1.2))
    x = int(min(max(face["cx"] - side / 2, 0), w - side))
    y = int(min(max(face["cy"] - side / 2, 0), h - side))
    return side, x, y


def compose_argv(ffmpeg: str, plan: dict) -> list:
    """The whole render as one ffmpeg command, built as a list. `plan` holds:

      src, has_audio, fps, size [w, h], src_matrix ("bt709" or "auto"), kept [[from_frame, to_frame], ...] on the
      source frame grid at `fps`, layers (a subset of ["beat", "caption"]), frames_dir (relative to the working folder),
      pips [{asset, kind, start_frame, end_frame, x, y}], pip_size, out_frames, max_bytes, out_name (relative).

    The picture, from the bottom: the cut recording; for each pip layout the asset (full frame) and the speaker in a
    round bubble; the beat frames; the captions. Everything is composed in RGB (gbrp), the recording read as bt709 limited
    range and written back as bt709, tagged with setparams. No path is inside the filter graph.
    """
    fps, (w, h) = plan["fps"], plan["size"]
    kept, has_audio = plan["kept"], plan["has_audio"]
    n = len(kept)
    inputs = [*RECORDING_IN, "-i", plan["src"]]
    idx, nxt = {}, 1
    for layer, prefix in (("beat", "beat"), ("caption", "cap")):
        if layer in plan["layers"]:
            inputs += ["-f", "image2", "-c:v", "png", "-protocol_whitelist", "file", "-framerate", str(fps),
                       "-i", "%s/%s_%%06d.png" % (plan["frames_dir"], prefix)]
            idx[layer] = nxt
            nxt += 1
    pips = plan["pips"]
    pip_in = []
    for p in pips:
        inputs += asset_input(p["kind"], p["asset"])
        pip_in.append(nxt)
        nxt += 1
    mask_in = None
    if pips:
        s = plan["pip_size"]
        inputs += ["-f", "lavfi", "-i", "color=c=black:s=%dx%d:r=%s,geq=lum='clip((W/2-hypot(X-W/2+0.5,Y-H/2+0.5))*255,0,255)':cb=128:cr=128,format=gray" % (s, s, fps)]
        mask_in = nxt
        nxt += 1

    g = ["[0:v:0]fps=%s:start_time=0,scale=%d:%d:force_original_aspect_ratio=increase:in_color_matrix=%s:out_color_matrix=bt709:out_range=tv,"
         "crop=%d:%d,setsar=1,format=yuv420p[sv]" % (fps, w, h, plan["src_matrix"], w, h)]
    vlabels = []
    if n > 1:
        g.append("[sv]split=%d%s" % (n, "".join("[s%d]" % k for k in range(n))))
        src_v = ["[s%d]" % k for k in range(n)]
    else:
        src_v = ["[sv]"]
    cat_in = []
    zoom, face, fade = plan["zoom"], plan["face"], plan["fade"]
    for k, (a, b) in enumerate(kept):
        g.append("%strim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS%s[v%d]" % (src_v[k], a, b, zoom_chain(zoom, face, k, b - a, fps, w, h), k))
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

    if not idx and not pips:
        g.append("[cv]%s[vout]" % TAGS)
    else:
        g.append("[cv]scale=in_range=tv:in_color_matrix=bt709:out_range=pc,format=gbrp[base]")
        cur = "base"
        size = plan["pip_size"]
        if pips:
            k = len(pips)
            g.append("[base]split=%d%s" % (k + 1, "".join("[main]" if i == 0 else "[spk%d]" % (i - 1) for i in range(k + 1))))
            cur = "main"
            g.append("[%d:v]format=gray,scale=%d:%d,split=%d%s" % (mask_in, size, size, k, "".join("[m%d]" % i for i in range(k))))
            for i, p in enumerate(pips):
                en = "enable='between(t,%.4f,%.4f)'" % (p["start_frame"] / fps, p["end_frame"] / fps)
                g.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,format=gbrp[as%d]" % (pip_in[i], w, h, w, h, i))
                g.append("[%s][as%d]overlay=0:0:format=gbrp:%s[oa%d]" % (cur, i, en, i))
                bubble = bubble_crop(face, w, h)
                g.append("[spk%d]crop=%d:%d:%d:%d,scale=%d:%d,format=gbrp[sq%d]" % (i, bubble[0], bubble[0], bubble[1], bubble[2], size, size, i))
                g.append("[sq%d][m%d]alphamerge[bub%d]" % (i, i, i))
                g.append("[oa%d][bub%d]overlay=%d:%d:format=gbrp:%s[ob%d]" % (i, i, p["x"], p["y"], en, i))
                cur = "ob%d" % i
        for layer in ("beat", "caption"):
            if layer in idx:
                g.append("[%d:v]format=gbrap[l_%s]" % (idx[layer], layer))
                g.append("[%s][l_%s]overlay=0:0:format=gbrp[c_%s]" % (cur, layer, layer))
                cur = "c_%s" % layer
        g.append("[%s]scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p,%s[vout]" % (cur, TAGS))

    argv = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", *inputs, "-filter_complex", ";".join(g), "-map", "[vout]"]
    if has_audio:
        argv += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    argv += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
             "-r", str(fps), "-fps_mode", "cfr", "-frames:v", str(plan["out_frames"]), "-shortest",
             "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
             "-fs", str(plan["max_bytes"]), "-movflags", "+faststart", plan["out_name"]]
    return argv


def cover_argv(ffmpeg: str, src: str, offset_seconds: float, out_name: str) -> list:
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", "%.3f" % offset_seconds, *RECORDING_IN,
            "-i", src, "-frames:v", "1", "-f", "image2", "-c:v", "png", out_name]
