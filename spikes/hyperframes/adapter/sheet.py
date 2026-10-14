"""A sheet of stills: one row per video, one column per time (seconds). Needs ffmpeg and the DejaVu font (both are in the spike image).

  python3 sheet.py --out sheet.png --times 0.3,0.8,15 --cell-w 270 --video ours=/a.mp4 --video hyperframes=/b.mp4
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--times", required=True)
    p.add_argument("--cell-w", type=int, default=270)
    p.add_argument("--video", action="append", required=True, metavar="LABEL=PATH")
    args = p.parse_args()
    times = [float(t) for t in args.times.split(",")]
    rows = [v.split("=", 1) for v in args.video]
    with tempfile.TemporaryDirectory() as tmp:
        row_files = []
        for r, (label, path) in enumerate(rows):
            cells = []
            for c, t in enumerate(times):
                cell = os.path.join(tmp, "c%d_%d.png" % (r, c))
                vf = "scale=%d:-2,drawtext=fontfile=%s:text='%s %.1fs':x=6:y=6:fontsize=16:fontcolor=white:box=1:boxcolor=black@0.6" % (args.cell_w, FONT, label, t)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t, "-i", path, "-frames:v", "1", "-vf", vf, cell], check=True)
                cells.append(cell)
            row = os.path.join(tmp, "row%d.png" % r)
            cmd = ["ffmpeg", "-y", "-v", "error"]
            for cell in cells:
                cmd += ["-i", cell]
            cmd += ["-filter_complex", "hstack=inputs=%d" % len(cells), row]
            subprocess.run(cmd, check=True)
            row_files.append(row)
        if len(row_files) == 1:
            shutil.copyfile(row_files[0], args.out)
            return 0
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for row in row_files:
            cmd += ["-i", row]
        cmd += ["-filter_complex", "vstack=inputs=%d" % len(row_files), args.out]
        subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
