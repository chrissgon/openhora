#!/usr/bin/env python3
"""S2 host driver: runs every step of the spike in a container built by `providers/_container.py` of origin/main (imported, not copied).

Every container has no network, a read-only root, every capability dropped, no new privileges, a limit on processes, memory (swap included)
and CPUs, memory-backed /tmp and /scratch, an image that is never pulled, and an id the host never reuses. This file adds only what the
helper has no argument for (`--cpuset-cpus`, for check C2) and a sampler of `docker stats` (check C7).

  python3 s2.py synth   --case synth                       # the fictional pt-BR case (code makes it, in the container)
  python3 s2.py adapt   --case C --caption B [--plant-overlap b1]
  python3 s2.py render  --case C --caption B --tag T [--cpuset 0-3] [--memory-mb 6144] [--workers 4]
  python3 s2.py verify  --video F --edl E                  # `verify` of providers/renderer in a fresh container of its image

Inputs live under spikes/hyperframes/.work/ (git-ignored): cases/<case>/ (edl.json, beats.json, recording.*), runs/<case>/<caption>/<tag>/.
The real recording is read in place and mounted read-only; nothing of it is copied into the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, ".work")
MAIN = os.path.join(WORK, "main")                      # a detached worktree of origin/main: providers/_container.py is imported from it
BRANCH = os.path.join(WORK, "branch-src")              # providers/renderer and shared/references of origin/feature/short-video, read-only
sys.path.insert(0, os.path.join(MAIN, "providers"))
import _container as C  # noqa: E402

IMAGE_TAG = os.environ.get("HF_IMAGE", "hf-s2:local")
LABEL = "org.openhora.spike-s2"
DEFAULTS = {"memory_mb": 6144, "cpus": 8, "scratch_mb": 2048, "pids": 512}      # the ffmpeg renderer's defaults (providers/renderer/_docker.py)
VOCAB = os.path.join(BRANCH, "shared/references/video-presets.json")
PLATFORM = os.path.join(BRANCH, "shared/references/platforms/instagram.json")


def image_id(tag: str) -> str:
    out = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"], capture_output=True, text=True, check=True).stdout.strip()
    return out


class Sampler(threading.Thread):
    """`docker stats --no-stream` once a second for one container: the peak memory it reports (MiB)."""

    def __init__(self, name: str):
        super().__init__(daemon=True)
        self.name_, self.peak, self.stop_ = name, 0.0, threading.Event()

    def run(self):
        while not self.stop_.is_set():
            out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.name_], capture_output=True, text=True).stdout.strip()
            head = out.split("/")[0].strip() if out else ""
            try:
                if head.endswith("GiB"):
                    self.peak = max(self.peak, float(head[:-3]) * 1024)
                elif head.endswith("MiB"):
                    self.peak = max(self.peak, float(head[:-3]))
            except ValueError:
                pass
            self.stop_.wait(0.5)


def run_job(tag: str, inner: list, mounts: list, *, name_prefix: str, timeout: int = 1800, memory_mb: int = None, cpus: int = None, scratch_mb: int = None,
            pids: int = None, tmp_mb: int = 512, cpuset: str = None, image: str = None, sample: bool = False, stdout_cap: int = None) -> dict:
    image = image or IMAGE_TAG
    name = "%s-%s" % (name_prefix, uuid.uuid4().hex[:10])
    argv = C.argv(name, image_id(image), inner, label=LABEL, deadline=int(time.time()) + timeout + 60, mounts=mounts,
                  memory_mb=memory_mb or DEFAULTS["memory_mb"], cpus=cpus or DEFAULTS["cpus"], scratch_mb=scratch_mb or DEFAULTS["scratch_mb"],
                  pids_limit=pids or DEFAULTS["pids"], tmp_mb=tmp_mb)
    if cpuset:       # the helper has no argument for it: inserted next to --cpus, nothing else of the command changes
        argv.insert(argv.index("--cpus") + 2, "--cpuset-cpus")
        argv.insert(argv.index("--cpuset-cpus") + 1, cpuset)
    C.require_local_daemon()
    sampler = Sampler(name) if sample else None
    if sampler:
        sampler.start()
    t0 = time.time()
    try:
        fin = C.run(argv, name, timeout, stdout_cap=stdout_cap)
        err = None
    except C.ContainerError as e:
        fin, err = None, str(e)
    wall = time.time() - t0
    if sampler:
        sampler.stop_.set()
        sampler.join(3)
    return {"returncode": None if fin is None else fin.returncode, "error": err, "stderr": "" if fin is None else fin.stderr[-4000:], "stdout": "" if fin is None else fin.stdout.decode("utf-8", "replace"), "wall_seconds": round(wall, 2),
            "docker_stats_peak_mib": None if not sampler else round(sampler.peak, 1), "argv": argv}


def ro(host: str, inside: str) -> tuple:
    return (os.path.abspath(host), inside, "ro")


def rw(host: str, inside: str) -> tuple:
    return (os.path.abspath(host), inside, "rw")


# The real recording: its media-store folder (read in place, mounted read-only) and a runs folder OUTSIDE this repository (principle 8).
REAL_MEDIA = os.environ.get("S2_REAL_MEDIA", "")
REAL_RUNS = os.environ.get("S2_REAL_RUNS", "")


def run_dir(case: str, caption: str, tag: str) -> str:
    base = REAL_RUNS if case == "real" else os.path.join(WORK, "runs")
    path = os.path.join(base, case, caption, tag)
    os.makedirs(os.path.join(path, "out"), exist_ok=True)
    return path


def case_dir(case: str) -> str:
    return REAL_MEDIA if case == "real" else os.path.join(WORK, "cases", case)


def case_recording(case: str) -> str:
    if case == "real" and os.environ.get("S2_REAL_RECORDING"):      # a normalised proxy of the recording, made by code (see the report)
        return os.environ["S2_REAL_RECORDING"]
    for n in sorted(os.listdir(case_dir(case))):
        if n.startswith("recording.") or (case == "real" and n.startswith("raw.")):
            return os.path.join(case_dir(case), n)
    raise SystemExit("no recording.* in the case folder")


def cmd_synth(a) -> int:
    out = case_dir(a.case)
    os.makedirs(out, exist_ok=True)
    res = run_job(a.tag, ["python3", "-I", "/adapter/make_synthetic.py", "--renderer-src", "/renderer", "--vocabulary", "/data/video-presets.json", "--out", "/case"],
                  [ro(os.path.join(BRANCH, "providers/renderer"), "/renderer"), ro(VOCAB, "/data/video-presets.json"), ro(os.path.join(HERE, "adapter"), "/adapter"),
                   rw(out, "/case")], name_prefix="s2-synth", timeout=300)
    print(json.dumps({k: res[k] for k in ("returncode", "error", "stderr", "wall_seconds")}))
    return res["returncode"] or 0


def cmd_adapt(a) -> int:
    rd = run_dir(a.case, a.caption, a.tag)
    proj = os.path.join(rd, "project")
    os.makedirs(os.path.join(proj, "media"), exist_ok=True)
    open(os.path.join(proj, "media", "source.mov"), "w").close()     # the mount point of the recording at render time
    inner = ["python3", "-I", "/adapter/hf_adapter.py", "--renderer-src", "/renderer", "--edl", "/case/edl.json", "--beats", "/case/beats.json", "--vocabulary",
             "/data/video-presets.json", "--platform-file", "/data/instagram.json", "--registry", "/opt/hf-registry", "--gsap", "/opt/hf/node_modules/gsap/dist/gsap.min.js",
             "--out", "/work/project", "--caption", a.caption]
    if a.plant_overlap:
        inner += ["--plant-overlap", a.plant_overlap]
    res = run_job(a.tag, inner, [ro(os.path.join(BRANCH, "providers/renderer"), "/renderer"), ro(VOCAB, "/data/video-presets.json"), ro(PLATFORM, "/data/instagram.json"),
                                 ro(os.path.join(HERE, "adapter"), "/adapter"), ro(case_dir(a.case), "/case"), rw(rd, "/work")], name_prefix="s2-adapt", timeout=300)
    print(json.dumps({k: res[k] for k in ("returncode", "error", "stderr", "wall_seconds")}))
    return res["returncode"] or 0


RENDER_SH = r"""
cd /work/project || exit 90
export TMPDIR="$TMPD"; mkdir -p "$TMPD"
t0=$(date +%s.%N)
hyperframes render --output "/work/out/$NAME.mp4" --variables-file /work/project/vars.json --workers "$WORKERS" --frames-cache-dir off --fps 30 --quiet $EXTRA > "/work/out/$NAME.log" 2>&1
rc=$?
t1=$(date +%s.%N)
peak=$(cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo null)
python3 -I -c "import json,sys; print(json.dumps({'exit': int(sys.argv[1]), 'wall_seconds': round(float(sys.argv[3])-float(sys.argv[2]), 2), 'memory_peak_bytes': None if sys.argv[4]=='null' else int(sys.argv[4])}))" "$rc" "$t0" "$t1" "$peak" > "/work/out/$NAME.stats"
exit $rc
"""


def cmd_render(a) -> int:
    rd = run_dir(a.case, a.caption, a.tag)
    rec = case_recording(a.case)
    name = "render"
    script = "NAME=%s WORKERS=%s EXTRA='%s' TMPD=%s\n%s" % (name, a.workers, a.extra or "", a.tmpdir, RENDER_SH)
    res = run_job(a.tag, ["sh", "-c", script], [rw(rd, "/work"), ro(rec, "/work/project/media/source.mov")], name_prefix="s2-render", timeout=a.timeout,   # security-scan: allow shell-string -- the script is the fixed RENDER_SH template plus flags of this driver, run inside the sealed container
                  memory_mb=a.memory_mb, cpus=a.cpus, cpuset=a.cpuset, sample=True, scratch_mb=a.scratch_mb, pids=a.pids)
    out = os.path.join(rd, "out", name + ".mp4")
    sha = hashlib.sha256(open(out, "rb").read()).hexdigest() if os.path.exists(out) else None
    stats = {}
    sp = os.path.join(rd, "out", name + ".stats")
    if os.path.exists(sp):
        stats = json.load(open(sp))
    record = {"returncode": res["returncode"], "error": res["error"], "sha256": sha, "wall_seconds_total": res["wall_seconds"], "docker_stats_peak_mib": res["docker_stats_peak_mib"],
              "cgroup_peak_mib": None if not stats.get("memory_peak_bytes") else round(stats["memory_peak_bytes"] / 1048576, 1), "render_seconds": stats.get("wall_seconds"),
              "memory_mb_limit": a.memory_mb or DEFAULTS["memory_mb"], "scratch_mb_limit": a.scratch_mb or DEFAULTS["scratch_mb"], "pids_limit": a.pids or DEFAULTS["pids"], "cpuset": a.cpuset, "workers": a.workers, "tmpdir": a.tmpdir, "bytes": os.path.getsize(out) if sha else None}
    with open(os.path.join(rd, "out", name + ".json"), "w") as fh:
        json.dump(record, fh, indent=1)
    print(json.dumps(record))
    return 0 if sha else 1


def cmd_measure(a) -> int:
    rd = run_dir(a.case, a.caption, a.tag)
    rec = case_recording(a.case)
    res = run_job(a.tag, ["node", "/adapter/measure.mjs", a.mode, "/work/project", "/work/out/%s.json" % a.mode],
                  [rw(rd, "/work"), ro(rec, "/work/project/media/source.mov"), ro(os.path.join(HERE, "adapter"), "/adapter")], name_prefix="s2-measure", timeout=900,
                  memory_mb=a.memory_mb or 4096)
    print(json.dumps({k: res[k] for k in ("returncode", "error", "stderr", "wall_seconds")}))
    return res["returncode"] or 0


def cmd_verify(a) -> int:
    renderer_img = a.verify_image
    edl = json.load(open(a.edl))
    sha = hashlib.sha256(open(a.video, "rb").read()).hexdigest()
    scratch = os.path.join(WORK, "verify-%s" % uuid.uuid4().hex[:8])
    os.makedirs(os.path.join(scratch, "in"))
    os.makedirs(os.path.join(scratch, "out"))
    with open(PLATFORM, "rb") as src, open(os.path.join(scratch, "in", "platform.json"), "wb") as dst:
        dst.write(src.read())
    inner = ["--result", "/out/result.json", "verify", "--in", "/recording", "--platform-file", "/job/platform.json", "--sha256", sha, "--expect-seconds",
             "%.3f" % (edl["out_frames"] / float(edl["fps"]))]
    res = run_job("verify", inner, [ro(a.video, "/recording"), ro(os.path.join(scratch, "in"), "/job"), rw(os.path.join(scratch, "out"), "/out")], name_prefix="s2-verify",
                  timeout=300, image=renderer_img, memory_mb=1024, cpus=2, scratch_mb=256)
    result = {}
    rp = os.path.join(scratch, "out", "result.json")
    if os.path.exists(rp):
        result = json.load(open(rp))
    print(json.dumps({"returncode": res["returncode"], "sha256": sha, "result": result}, ensure_ascii=False))
    return res["returncode"] or 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for n in ("synth", "adapt", "render"):
        s = sub.add_parser(n)
        s.add_argument("--case", required=True)
        s.add_argument("--tag", default="r1")
        if n != "synth":
            s.add_argument("--caption", required=True, choices=["highlight", "pill", "slam"])
        if n == "adapt":
            s.add_argument("--plant-overlap")
        if n == "render":
            s.add_argument("--cpuset")
            s.add_argument("--cpus", type=int)
            s.add_argument("--memory-mb", type=int)
            s.add_argument("--scratch-mb", type=int)
            s.add_argument("--pids", type=int, help="the pids limit of the container (default 512, the ffmpeg renderer's)")
            s.add_argument("--workers", default="4")
            s.add_argument("--tmpdir", default="/scratch", help="where HyperFrames puts its temporary frames: /scratch (memory-backed) or /work/tmp (the disk folder of the run)")
            s.add_argument("--timeout", type=int, default=3000)
            s.add_argument("--extra", default="")
    s = sub.add_parser("measure")
    s.add_argument("--case", required=True)
    s.add_argument("--tag", default="r1")
    s.add_argument("--caption", required=True, choices=["highlight", "pill", "slam"])
    s.add_argument("--mode", required=True, choices=["boxes", "fonts"])
    s.add_argument("--memory-mb", type=int)
    s = sub.add_parser("verify")
    s.add_argument("--video", required=True)
    s.add_argument("--edl", required=True)
    s.add_argument("--verify-image", required=True)
    a = p.parse_args()
    return {"synth": cmd_synth, "adapt": cmd_adapt, "render": cmd_render, "verify": cmd_verify, "measure": cmd_measure}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
