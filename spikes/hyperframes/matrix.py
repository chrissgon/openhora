#!/usr/bin/env python3
"""S2 matrix: for one case, every caption block: the generator twice (same bytes?), three renders, four renders on limited cores, `verify` of every
render, the comparison with our render (C3), the boxes (C6) with a planted overlap, the fonts (C5). One JSON line per step goes to <results>/<case>.jsonl.
  python3 matrix.py --case synth [--captions highlight,pill,slam] [--skip-cpuset]
"""
import argparse, hashlib, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s2  # noqa: E402

VERIFY_IMAGE = os.environ.get("S2_VERIFY_IMAGE", "openhora-renderer:af62eab73099")


def sh(args, timeout=7200):
    t0 = time.time()
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True, timeout=timeout, cwd=HERE)
    last = [l for l in r.stdout.splitlines() if l.startswith("{")]
    try:
        out = json.loads(last[-1]) if last else {}
    except ValueError:
        out = {}
    out["_rc"] = r.returncode
    out["_seconds"] = round(time.time() - t0, 1)
    if r.returncode and r.stderr:
        out["_stderr"] = r.stderr[-400:]
    return out


def sha_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest() if os.path.exists(path) else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--case", required=True)
    p.add_argument("--captions", default="highlight,pill,slam")
    p.add_argument("--skip-cpuset", action="store_true")
    p.add_argument("--no-auto", action="store_true", help="leave out the two runs with --workers auto on limited cores")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--memory-mb", type=int); p.add_argument("--pids", type=int); p.add_argument("--scratch-mb", type=int)
    p.add_argument("--cpuset-captions", default="", help="comma list: only these blocks get the runs on limited cores (default: all)")
    p.add_argument("--timeout", type=int, default=3600)
    a = p.parse_args()
    results = os.path.join(os.environ.get("S2_RESULTS", os.path.join(s2.WORK, "results")))
    os.makedirs(results, exist_ok=True)
    log = open(os.path.join(results, a.case + ".jsonl"), "a")

    def rec(**kw):
        kw["t"] = time.strftime("%H:%M:%S")
        log.write(json.dumps(kw, ensure_ascii=False) + "\n"); log.flush()
        print(json.dumps({k: kw[k] for k in kw if k in ("step", "caption", "tag", "sha256", "returncode", "render_seconds", "cgroup_peak_mib", "ok", "psnr0", "hits", "same")}, ensure_ascii=False), flush=True)

    case_edl = os.path.join(s2.case_dir(a.case), "edl.json")
    for cap in a.captions.split(","):
        # generator: same bytes twice
        for tag in ("g1", "g2"):
            r = sh(["s2.py", "adapt", "--case", a.case, "--caption", cap, "--tag", tag])
        d1, d2 = s2.run_dir(a.case, cap, "g1"), s2.run_dir(a.case, cap, "g2")
        same = {f: sha_file(os.path.join(d1, "project", f)) == sha_file(os.path.join(d2, "project", f)) for f in ("index.html", "vars.json")}
        rec(step="generator_twice", caption=cap, same=all(same.values()), files=same, index_sha256=sha_file(os.path.join(d1, "project", "index.html")),
            vars_sha256=sha_file(os.path.join(d1, "project", "vars.json")))
        plans = [("r%d" % i, {}) for i in range(1, a.repeats + 1)]
        if not a.skip_cpuset and (not a.cpuset_captions or cap in a.cpuset_captions.split(",")):
            if not a.no_auto:
                plans += [("cs4", {"cpuset": "0-3", "cpus": 4, "workers": "auto"}), ("cs8", {"cpuset": "0-7", "cpus": 8, "workers": "auto"})]
            plans += [("cs4w4", {"cpuset": "0-3", "cpus": 4, "workers": "4"}), ("cs8w4", {"cpuset": "0-7", "cpus": 8, "workers": "4"})]
        for tag, opt in plans:
            sh(["s2.py", "adapt", "--case", a.case, "--caption", cap, "--tag", tag])
            args = ["s2.py", "render", "--case", a.case, "--caption", cap, "--tag", tag, "--timeout", str(a.timeout)]
            if "cpuset" in opt:
                args += ["--cpuset", opt["cpuset"], "--cpus", str(opt["cpus"])]
            if "workers" in opt:
                args += ["--workers", opt["workers"]]
            for flag, val in (("--memory-mb", a.memory_mb), ("--pids", a.pids), ("--scratch-mb", a.scratch_mb)):
                if val:
                    args += [flag, str(val)]
            r = sh(args, timeout=a.timeout + 600)
            rec(step="render", caption=cap, tag=tag, opts=opt, **{k: r.get(k) for k in ("sha256", "returncode", "render_seconds", "wall_seconds_total", "cgroup_peak_mib", "docker_stats_peak_mib", "bytes")})
            out = os.path.join(s2.run_dir(a.case, cap, tag), "out", "render.mp4")
            if r.get("sha256"):
                v = sh(["s2.py", "verify", "--video", out, "--edl", case_edl, "--verify-image", VERIFY_IMAGE])
                rec(step="verify", caption=cap, tag=tag, ok=(v.get("result") or {}).get("ok"), returncode=v.get("returncode"), output=(v.get("result") or {}).get("output"))
        # boxes (C6) with and without a planted overlap, fonts (C5), on the first plain render
        for mode in ("boxes", "fonts"):
            sh(["s2.py", "measure", "--case", a.case, "--caption", cap, "--tag", "r1", "--mode", mode])
        c6 = os.path.join(s2.run_dir(a.case, cap, "r1"), "out", "c6.json")
        sh_out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "adapter/c6.py"), "--renderer-src", os.path.join(s2.BRANCH, "providers/renderer"), "--edl", case_edl,
                                 "--beats", os.path.join(s2.case_dir(a.case), "beats.json"), "--boxes", os.path.join(s2.run_dir(a.case, cap, "r1"), "out", "boxes.json"),
                                 "--vocabulary", s2.VOCAB, "--out", c6], capture_output=True, text=True)
        c6d = json.load(open(c6)) if os.path.exists(c6) else {}
        rec(step="c6_plain", caption=cap, hits=c6d.get("hits"), frames_with_boxes=c6d.get("frames_with_drawn_boxes"), boxes_checked=c6d.get("boxes_checked"))
        fonts = os.path.join(s2.run_dir(a.case, cap, "r1"), "out", "fonts.json")
        fd = json.load(open(fonts)) if os.path.exists(fonts) else {}
        rec(step="c5_fonts", caption=cap, platform_fonts=fd.get("platform_fonts"), loaded=fd.get("loaded_font_faces"), pt_br=fd.get("pt_br_chars_on_screen"),
            coverage_ok={f: all(c.values()) for f, c in (fd.get("glyph_coverage") or {}).items()})
    log.close()


if __name__ == "__main__":
    main()
