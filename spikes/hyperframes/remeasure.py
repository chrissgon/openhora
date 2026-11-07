#!/usr/bin/env python3
"""Measure again (boxes, fonts) on the r1 project of each block of a case, then C6 plain. After a change of adapter/measure.mjs. Usage: remeasure.py CASE [--memory-mb N]"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import s2
case = sys.argv[1]; mem = sys.argv[3] if len(sys.argv) > 3 else None
edl, beats = os.path.join(s2.case_dir(case), "edl.json"), os.path.join(s2.case_dir(case), "beats.json")
for cap in ("highlight", "pill", "slam"):
    for mode in ("boxes", "fonts"):
        subprocess.run([sys.executable, os.path.join(HERE, "s2.py"), "measure", "--case", case, "--caption", cap, "--tag", "r1", "--mode", mode] + (["--memory-mb", mem] if mem else []), capture_output=True)
    rd = s2.run_dir(case, cap, "r1")
    for glyph in (False, True):
        o = os.path.join(rd, "out", "c6%s.json" % ("-glyph" if glyph else ""))
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "adapter/c6.py"), "--renderer-src", os.path.join(s2.BRANCH, "providers/renderer"), "--edl", edl, "--beats", beats,
                            "--boxes", os.path.join(rd, "out", "boxes.json"), "--vocabulary", s2.VOCAB, "--out", o] + (["--glyph"] if glyph else []), capture_output=True, text=True)
        print(case, cap, "glyph" if glyph else "element", r.stdout.strip()[:200], flush=True)
