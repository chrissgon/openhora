"""ffprobe / ffmpeg helpers. Every argv is a list: there is no shell anywhere.

Every input of the recording gets `-f mov -protocol_whitelist file` (plan, hard limits).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
RECORDING_IN = ["-f", "mov", "-protocol_whitelist", "file"]


class MediaError(RuntimeError):
    pass


def run(argv, timeout=1800):
    """Run a command, return stdout and stderr; raise MediaError with the tail of stderr on failure."""
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise MediaError("%s failed (%d): %s" % (os.path.basename(argv[0]), p.returncode, " | ".join(tail)))
    return p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def probe(path):
    """Facts of a recording. Refuses anything other than one video stream and at most one audio stream."""
    out, _ = run([FFPROBE, "-v", "error", *RECORDING_IN, "-show_streams", "-show_format", "-of", "json", path])
    info = json.loads(out)
    v = [s for s in info["streams"] if s["codec_type"] == "video"]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if len(v) != 1 or len(a) > 1 or len(v) + len(a) != len(info["streams"]):
        raise MediaError("recording must have one video stream and at most one audio stream")
    num, den = v[0]["avg_frame_rate"].split("/")
    return {"width": v[0]["width"], "height": v[0]["height"], "fps": float(num) / float(den),
            "duration": float(info["format"]["duration"]), "has_audio": bool(a), "codec": v[0]["codec_name"],
            "pix_fmt": v[0].get("pix_fmt"), "bytes": int(info["format"]["size"])}


def silencedetect(path, noise_db=-35, min_dur=0.3):
    """Silence intervals [{start, end}] of the recording's audio."""
    _, err = run([FFMPEG, "-hide_banner", "-nostats", *RECORDING_IN, "-i", path, "-vn",
                  "-af", "silencedetect=noise=%ddB:d=%s" % (noise_db, min_dur), "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", err)]
    out = []
    for k, s in enumerate(starts):
        e = ends[k] if k < len(ends) else None
        out.append({"start": max(0.0, s), "end": e})
    return out


def close_open_silences(silences, duration):
    for s in silences:
        if s["end"] is None:
            s["end"] = duration
    return silences


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def probe_output(path):
    out, _ = run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path])
    info = json.loads(out)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    return {"codec": v["codec_name"], "profile": v.get("profile"), "size": "%dx%d" % (v["width"], v["height"]),
            "pix_fmt": v["pix_fmt"], "fps": v["avg_frame_rate"], "color": [v.get("color_space"), v.get("color_primaries"),
            v.get("color_transfer"), v.get("color_range")], "audio": a[0]["codec_name"] if a else None,
            "duration": float(info["format"]["duration"]), "bytes": int(info["format"]["size"]),
            "nb_frames": v.get("nb_frames")}
