#!/usr/bin/env python3
"""After matrix.py: C3 (picture and sound against our render), C6 with a planted overlap, C8 (layout fit) for one case. Writes <results>/<case>-finish.json.
  python3 finish.py --case synth --ours F.mp4 --crop 1080:500:0:560
"""
import argparse, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import s2  # noqa

p = argparse.ArgumentParser()
p.add_argument("--case", required=True); p.add_argument("--ours", required=True); p.add_argument("--crop", required=True)
p.add_argument("--captions", default="highlight,pill,slam"); p.add_argument("--plant-caption", default="highlight")
p.add_argument("--memory-mb", type=int); p.add_argument("--pids", type=int); p.add_argument("--scratch-mb", type=int)
a = p.parse_args()
edl, beats = os.path.join(s2.case_dir(a.case), "edl.json"), os.path.join(s2.case_dir(a.case), "beats.json")
out = {}
def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)
for cap in a.captions.split(","):
    rd = s2.run_dir(a.case, cap, "r1")
    cmp_path = os.path.join(rd, "out", "compare.json")
    run([sys.executable, os.path.join(HERE, "adapter/compare.py"), "--ours", a.ours, "--other", os.path.join(rd, "out", "render.mp4"), "--edl", edl, "--crop", a.crop, "--out", cmp_path])
    c = json.load(open(cmp_path))
    c8p = os.path.join(rd, "out", "c8.json")
    run([sys.executable, "-I", os.path.join(HERE, "adapter/c8.py"), "--renderer-src", os.path.join(s2.BRANCH, "providers/renderer"), "--edl", edl, "--beats", beats,
         "--boxes", os.path.join(rd, "out", "boxes.json"), "--vocabulary", s2.VOCAB, "--out", c8p])
    c8 = json.load(open(c8p))
    out[cap] = {"c3": {"mean_psnr_by_shift": c["mean_psnr_by_shift"], "ranges_compared": c["ranges_compared"], "ranges_best_at_shift_0": c["ranges_best_at_shift_0"],
                       "lowest_boundary_psnr": c["lowest_boundary_psnr"], "audio_lag_ms_per_8s_window": c["audio_lag_ms_per_8s_window"], "audio_seconds": c["audio_seconds"]}, "c8": c8}
    print(cap, json.dumps(out[cap]["c3"])[:300], flush=True)
# planted overlap: the first keyword (or number, or quote) card of the beats
ov = json.load(open(beats))["overlays"]
target = next(o["id"] for o in ov if o["preset"] in ("keyword", "number", "quote"))
cap = a.plant_caption
subprocess.run([sys.executable, os.path.join(HERE, "s2.py"), "adapt", "--case", a.case, "--caption", cap, "--tag", "plant", "--plant-overlap", target], capture_output=True)
subprocess.run([sys.executable, os.path.join(HERE, "s2.py"), "measure", "--case", a.case, "--caption", cap, "--tag", "plant", "--mode", "boxes"] + (["--memory-mb", str(a.memory_mb)] if a.memory_mb else []), capture_output=True)
rd = s2.run_dir(a.case, cap, "plant")
c6p = os.path.join(rd, "out", "c6.json")
run([sys.executable, "-I", os.path.join(HERE, "adapter/c6.py"), "--renderer-src", os.path.join(s2.BRANCH, "providers/renderer"), "--edl", edl, "--beats", beats,
     "--boxes", os.path.join(rd, "out", "boxes.json"), "--vocabulary", s2.VOCAB, "--out", c6p])
c6 = json.load(open(c6p))
out["planted"] = {"beat": target, "hits": c6["hits"], "hit_frames": len(c6["hit_frames"]), "first": c6["first_hits"][:1]}
print("planted", json.dumps(out["planted"]))
res = os.environ.get("S2_RESULTS", os.path.join(s2.WORK, "results"))
json.dump(out, open(os.path.join(res, a.case + "-finish.json"), "w"), indent=1)
