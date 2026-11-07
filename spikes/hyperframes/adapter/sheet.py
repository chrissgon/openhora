"""A contact sheet for check C10: one row per video, one column per time. Host side (standard library plus ffmpeg); the row order is the order of --video.
  python3 sheet.py --out sheet.png --times 0.8,3.1,7.0 --cell-w 270 --video highlight=a.mp4 --video pill=b.mp4 --video ours=c.mp4
"""
import argparse, os, subprocess, sys, tempfile

p = argparse.ArgumentParser()
p.add_argument("--out", required=True); p.add_argument("--times", required=True); p.add_argument("--cell-w", type=int, default=270)
p.add_argument("--video", action="append", required=True, metavar="LABEL=PATH")
a = p.parse_args()
times = [float(t) for t in a.times.split(",")]
rows = [v.split("=", 1) for v in a.video]
with tempfile.TemporaryDirectory() as tmp:
    row_files = []
    for r, (label, path) in enumerate(rows):
        cells = []
        for c, t in enumerate(times):
            f = os.path.join(tmp, "c%d_%d.png" % (r, c))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % t, "-i", path, "-frames:v", "1", "-vf", "scale=%d:-2" % a.cell_w, f], check=True)
            cells.append(f)
        rf = os.path.join(tmp, "row%d.png" % r)
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for f in cells:
            cmd += ["-i", f]
        cmd += ["-filter_complex", "hstack=inputs=%d" % len(cells), rf]
        subprocess.run(cmd, check=True)
        row_files.append(rf)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for f in row_files:
        cmd += ["-i", f]
    cmd += ["-filter_complex", "vstack=inputs=%d" % len(row_files), a.out]
    subprocess.run(cmd, check=True)
print("rows (top to bottom):", ", ".join(l for l, _ in rows), "| times:", a.times)
