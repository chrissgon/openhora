#!/usr/bin/env python3
"""Summarises <results>/<case>.jsonl of matrix.py: per caption block, the sha256 of every render (one value per group?), verify results, C5/C6 facts."""
import json, sys, collections
rows = [json.loads(l) for l in open(sys.argv[1])]
by = collections.defaultdict(list)
for r in rows:
    by[r["caption"]].append(r)
for cap, rs in by.items():
    print("==", cap)
    renders = [r for r in rs if r["step"] == "render"]
    plain = [r for r in renders if r["tag"] in ("r1", "r2", "r3")]
    print(" plain renders:", {r["tag"]: (r["sha256"] or "FAIL")[:12] for r in plain}, "-> one sha:", len({r["sha256"] for r in plain}) == 1)
    print(" cores:", {r["tag"]: (r["sha256"] or "FAIL")[:12] for r in renders if r["tag"].startswith("cs")})
    print(" all renders one sha:", len({r["sha256"] for r in renders}) == 1, "| exit codes", sorted({r["returncode"] for r in renders}))
    print(" verify ok:", [(r["tag"], r["ok"]) for r in rs if r["step"] == "verify"])
    print(" render_seconds:", {r["tag"]: r["render_seconds"] for r in renders}, "| peak MiB (cgroup):", {r["tag"]: r["cgroup_peak_mib"] for r in renders if r["tag"] == "r1"})
    for r in rs:
        if r["step"] in ("c6_plain", "c5_fonts", "generator_twice"):
            print(" ", r["step"], {k: v for k, v in r.items() if k not in ("step", "caption", "t")})
