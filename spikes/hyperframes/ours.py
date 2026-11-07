#!/usr/bin/env python3
"""Renders an input with OUR ffmpeg renderer (providers/renderer of origin/feature/short-video, extracted under .work/branch-src), for the comparison of
S2 (checks C3 and C7): wall time and peak memory, as `docker stats` reports for its container. Usage: ours.py CASE_DIR OUT_DIR"""
import json, os, subprocess, sys, threading, time

case, out = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(here, ".work/branch-src")
rec = [os.path.join(case, n) for n in sorted(os.listdir(case)) if n.startswith("recording.") or n.startswith("raw.")][0]
os.makedirs(out, exist_ok=True)
peak = [0.0]
stop = threading.Event()

def sample():
    while not stop.is_set():
        o = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"], capture_output=True, text=True).stdout
        for line in o.splitlines():
            n, _, rest = line.partition(" ")
            if n.startswith("openhora-renderer-"):
                head = rest.split("/")[0].strip()
                try:
                    peak[0] = max(peak[0], float(head[:-3]) * (1024 if head.endswith("GiB") else 1))
                except ValueError:
                    pass
        stop.wait(0.5)

t = threading.Thread(target=sample, daemon=True); t.start()
t0 = time.time()
r = subprocess.run([sys.executable, "-I", os.path.join(src, "providers/renderer/ffmpeg.py"), "render", "--edl", os.path.join(case, "edl.json"), "--beats", os.path.join(case, "beats.json"),
                    "--in", rec, "--out", out, "--platform-file", os.path.join(src, "shared/references/platforms/instagram.json"),
                    "--vocabulary", os.path.join(src, "shared/references/video-presets.json")], capture_output=True, text=True)
wall = time.time() - t0
stop.set(); t.join(3)
res = {"returncode": r.returncode, "wall_seconds": round(wall, 2), "docker_stats_peak_mib": round(peak[0], 1), "stdout": r.stdout[-1500:], "stderr": r.stderr[-800:]}
open(os.path.join(out, "ours.json"), "w").write(json.dumps(res, indent=1))
print(json.dumps(res))
