"""Compares two renders of the same edit: do the cuts land on the same frames, does the sound stay in step.

  python3 compare.py --ours a.mp4 --other b.mp4 --edl edl.json --out result.json [--crop 0:330:1080:900]

Picture: per-frame PSNR of the two videos on a crop (default: the band where the speaker is, so the captions and cards, which differ by design,
do not count), for the other video shifted by -2..+2 frames. A render whose cuts land on the same frames has the best match at shift 0 in every
kept range. Sound: the offset (milliseconds) that best aligns the loudness envelopes of the two audio tracks, in windows along the video.
Standard library plus ffmpeg.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

STAT = re.compile(r"n:(\d+) .*psnr_avg:(\S+)")


def psnr_series(a: str, b: str, shift: int, crop: str, frames: int) -> list:
    """PSNR of a[n] against b[n + shift] for n in 0..frames-1-|shift|."""
    with tempfile.TemporaryDirectory() as tmp:
        stats = os.path.join(tmp, "stats.log")
        fa = "[0:v]crop=%s,format=yuv420p,setpts=PTS-STARTPTS%s[a]" % (crop, ",trim=start_frame=%d,setpts=PTS-STARTPTS" % -shift if shift < 0 else "")
        fb = "[1:v]crop=%s,format=yuv420p,setpts=PTS-STARTPTS%s[b]" % (crop, ",trim=start_frame=%d,setpts=PTS-STARTPTS" % shift if shift > 0 else "")
        graph = "%s;%s;[a][b]psnr=stats_file=%s" % (fa, fb, stats)
        subprocess.run(["ffmpeg", "-v", "error", "-i", a, "-i", b, "-lavfi", graph, "-f", "null", "-"], check=True)
        out = {}
        for line in open(stats, encoding="utf-8"):
            m = STAT.search(line)
            if m:
                v = m.group(2)
                out[int(m.group(1)) - 1] = 100.0 if v == "inf" else float(v)
    n = frames - abs(shift)
    return [out.get(i, 0.0) for i in range(n)]


def pcm_envelope(path: str, rate: int = 1000) -> list:
    """Mono loudness envelope, `rate` values per second, from 8 kHz PCM."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], check=True, capture_output=True).stdout
    step = 8000 // rate
    env = []
    for i in range(0, len(raw) - 2 * step, 2 * step):
        chunk = raw[i:i + 2 * step]
        env.append(sum(abs(int.from_bytes(chunk[j:j + 2], "little", signed=True)) for j in range(0, len(chunk), 2)) / step)
    return env


def best_lag(a: list, b: list, lo: int, hi: int, max_lag: int) -> int:
    """The lag (in samples of b relative to a) in [-max_lag, max_lag] that maximises the correlation of a[lo:hi] with b."""
    best, best_lag_ = None, 0
    ma = sum(a[lo:hi]) / max(1, hi - lo)
    for lag in range(-max_lag, max_lag + 1):
        s = 0.0
        for i in range(lo, hi, 4):
            j = i + lag
            if 0 <= j < len(b):
                s += (a[i] - ma) * b[j]
        if best is None or s > best:
            best, best_lag_ = s, lag
    return best_lag_


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ours", required=True)
    p.add_argument("--other", required=True)
    p.add_argument("--edl", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--crop", default="1080:900:0:330", help="w:h:x:y of the region compared")
    p.add_argument("--shifts", default="-2,-1,0,1,2")
    args = p.parse_args()
    edl = json.load(open(args.edl, encoding="utf-8"))
    frames = edl["out_frames"]
    starts, pos = [], 0
    for a, b in edl["kept"]:
        starts.append((pos, pos + b - a))
        pos += b - a
    shifts = [int(s) for s in args.shifts.split(",")]
    series = {s: psnr_series(args.ours, args.other, s, args.crop, frames) for s in shifts}
    result = {"frames": frames, "crop": args.crop, "mean_psnr_by_shift": {str(s): round(sum(v) / len(v), 3) for s, v in series.items()}}
    # per kept range: which shift matches best (the first and last 3 frames of a range are skipped: a cut's neighbours differ by design when a shift is applied)
    best_by_range, mismatches = [], []
    for k, (a, b) in enumerate(starts):
        lo, hi = a + 3, b - 3
        if hi - lo < 5:
            continue
        means = {}
        for s, v in series.items():
            idx = [i for i in range(lo, hi) if 0 <= i < len(v)]
            means[s] = sum(v[i] for i in idx) / max(1, len(idx))
        best = max(means, key=means.get)
        best_by_range.append(best)
        if best != 0:
            mismatches.append({"range": k, "best_shift": best, "psnr_by_shift": {str(s): round(m, 2) for s, m in means.items()}})
    result["ranges_compared"] = len(best_by_range)
    result["ranges_best_at_shift_0"] = sum(1 for s in best_by_range if s == 0)
    result["ranges_with_other_best_shift"] = mismatches
    # at the boundaries themselves: PSNR of the first frame of each range against the frames around it (shift 0)
    s0 = series[0]
    bound = [s0[a] for a, _ in starts[1:] if a < len(s0)]
    around = [s0[i] for a, _ in starts[1:] for i in (a - 4, a - 3, a + 3, a + 4) if 0 <= i < len(s0)]
    result["boundary_frame_mean_psnr"] = round(sum(bound) / max(1, len(bound)), 3)
    result["frames_around_boundaries_mean_psnr"] = round(sum(around) / max(1, len(around)), 3)
    result["lowest_boundary_psnr"] = round(min(bound), 3) if bound else None
    # sound
    ea, eb = pcm_envelope(args.ours), pcm_envelope(args.other)
    win = 8000
    lags = []
    for lo in range(0, min(len(ea), len(eb)) - win, win):
        lags.append(best_lag(ea, eb, lo, lo + win, 150))
    result["audio_lag_ms_per_8s_window"] = lags
    result["audio_seconds"] = {"ours": round(len(ea) / 1000.0, 3), "other": round(len(eb) / 1000.0, 3)}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
        fh.write("\n")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
