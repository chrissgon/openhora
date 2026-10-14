"""A fictional test case for the spike, made inside the container: a test-pattern video with spoken-looking bursts of tone, a transcript with
invented words, the analysis and the base edit list written by OUR renderer code (read-only copy), and beats that use the four overlays.

  python3 make_synthetic.py --renderer-src /renderer --vocabulary video-presets.json --out /work/synth

Writes <out>/recording.mp4, transcript.json, analysis.json, edl.json, beats.json. No real person, recording or text is used.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

SENTENCES = [
    (0.4, 2.3, "Every project starts with one small step"),
    (3.2, 5.4, "Within ten days fifty people tried it"),
    (6.4, 8.9, "The question is simple: what changes tomorrow?"),
    (9.9, 12.9, "First understand, then build, then measure"),
    (13.9, 16.6, "Aurora said: haste fools the eye"),
]
DURATION = 18.0


def words_of(sentences):
    words, segs = [], []
    for si, (a, b, text) in enumerate(sentences):
        toks = text.split()
        weights = [max(2, len(t)) for t in toks]
        total, t = float(sum(weights)), a
        first = len(words)
        for tok, wgt in zip(toks, weights):
            span = (b - a) * wgt / total
            words.append({"index": len(words), "text": tok, "start": round(t, 3), "end": round(t + span, 3), "segment": si, "probability": 0.99})
            t += span
        segs.append({"index": si, "start": a, "end": b, "text": text, "first_word": first, "last_word": len(words) - 1})
    return words, segs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--renderer-src", required=True)
    p.add_argument("--vocabulary", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out = args.out
    os.makedirs(out, exist_ok=True)
    words, segs = words_of(SENTENCES)
    with open(os.path.join(out, "transcript.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "language": "en", "duration": DURATION, "words": words, "segments": segs, "facts": {}}, fh, ensure_ascii=False, indent=1)
    # picture: a colourful test pattern (so a wrong frame is visible); sound: a tone that is on while a sentence is spoken
    gate = "+".join("between(t\\,%.3f\\,%.3f)" % (a - 0.05, b + 0.05) for a, b, _ in SENTENCES)
    expr = "0.3*sin(2*PI*220*t)*(%s)" % gate
    rec = os.path.join(out, "recording.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=%s" % DURATION,
                    "-f", "lavfi", "-i", "aevalsrc=%s:s=48000:d=%s" % (expr, DURATION), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", rec], check=True)
    inner = os.path.join(args.renderer_src, "_inner.py")
    run = lambda *a: subprocess.run([sys.executable, "-I", inner, *a], check=True, stdout=subprocess.DEVNULL)   # noqa: E731
    run("analyse", "--in", rec, "--out", os.path.join(out, "analysis.json"))
    run("base", "--transcript", os.path.join(out, "transcript.json"), "--analysis", os.path.join(out, "analysis.json"), "--out", os.path.join(out, "edl.json"),
        "--face-box", "270,520,540,560", "--color", "bg=#000000", "--color", "accent=#07B6F0", "--color", "chip_fill=#011B24", "--font", "display=inter-800:800",
        "--font", "text=inter-500:500", "--font", "mono=jetbrains-mono-500:500")
    by_text = {}
    for w in words:
        by_text.setdefault(w["text"], []).append(w["index"])
    first = {s["index"]: s["first_word"] for s in segs}
    last = {s["index"]: s["last_word"] for s in segs}
    overlays = [
        {"id": "b1", "beat": 1, "preset": "keyword", "params": {"text": "First step"}, "word_from": first[0], "word_to": last[0], "score": 1.0},
        {"id": "b2", "beat": 2, "preset": "number", "params": {"value": "50", "label": "people tried it"}, "word_from": first[1], "word_to": last[1], "score": 1.0},
        {"id": "b3", "beat": 3, "preset": "keyword", "params": {"text": "What changes tomorrow?"}, "word_from": first[2], "word_to": last[2], "score": 1.0},
        {"id": "b4", "beat": 4, "preset": "list", "params": {"items": "Understand | Build | Measure"}, "word_from": first[3], "word_to": last[3], "score": 1.0},
        {"id": "b5", "beat": 5, "preset": "quote", "params": {"text": "Haste fools the eye", "author": "Aurora Lima"}, "word_from": first[4], "word_to": last[4], "score": 1.0},
    ]
    beats = {"schema_version": 1, "threshold": 0.6, "overlays": overlays, "layouts": [], "slots": [],
             "report": [{"beat": o["beat"], "preset": o["preset"], "score": 1.0, "matched": True, "reordered": False, "word_from": o["word_from"], "word_to": o["word_to"]}
                        for o in overlays], "unmatched": [], "fallbacks": []}
    with open(os.path.join(out, "beats.json"), "w", encoding="utf-8") as fh:
        json.dump(beats, fh, ensure_ascii=False, indent=1)
    run("check", "--edl", os.path.join(out, "edl.json"), "--beats", os.path.join(out, "beats.json"), "--vocabulary", args.vocabulary)
    print("synthetic case written to", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
