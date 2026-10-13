#!/usr/bin/env python3
"""Build the fully fictional demo inputs with ffmpeg and render them.

Everything here is invented: the source is a synthetic vertical test pattern with a tone that is silent
in the gaps between sentences, the transcript is generated from fictional sentences and their timings,
the asset is a drawn image. Nothing is downloaded and no real recording is involved.

  python3 demo/make_demo.py --out-dir <scratch> --out <mp4>          # build inputs, render
  python3 demo/make_demo.py --out-dir <scratch> --inputs-only        # only build the inputs
  python3 demo/make_demo.py --rewrite-transcript                     # regenerate demo/transcript.json

Extra arguments after `--` go to render.py (for example `-- --jobs 4 --color accent=#07B6F0`).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import media  # noqa: E402
import render  # noqa: E402

FPS = 30
SIZE = (1080, 1920)

# (pause before the sentence in seconds, sentence). The colon in sentence 2 adds a long pause inside it.
SENTENCES = [
    (1.0, "Hey, quick story about money."),
    (1.1, "Last year I tracked every expense for ninety days."),
    (0.9, "The first rule is simple: name every dollar."),
    (1.2, "Then do three things each week: review, adjust, and celebrate."),
    (0.8, "That habit saved me three hundred forty dollars in one month."),
    (1.0, "A wise friend told me, small steps beat big plans."),
    (1.1, "Here is what my dashboard looked like."),
    (0.9, "Look at the chart while I walk you through it."),
    (1.0, "Follow for more small steps."),
]
TAIL = 1.3


def build_transcript():
    words, t, seg = [], 0.0, 0
    for pause, sentence in SENTENCES:
        t += pause
        for tok in sentence.split():
            letters = sum(ch.isalpha() for ch in tok)
            dur = round(0.10 + 0.045 * letters, 3)
            words.append({"i": len(words), "text": tok, "start": round(t, 3), "end": round(t + dur, 3), "segment": seg})
            t += dur + 0.07
            if tok.endswith(","):
                t += 0.15
            if tok.endswith(":"):
                t += 0.75
        seg += 1
    duration = round(words[-1]["end"] + TAIL, 3)
    return {"language": "en", "duration": duration, "fps": FPS, "words": words}


def speech_spans(words, join=0.3):
    spans = []
    for w in words:
        if spans and w["start"] - spans[-1][1] <= join:
            spans[-1][1] = w["end"]
        else:
            spans.append([w["start"], w["end"]])
    return spans


def make_source(path, transcript):
    d = transcript["duration"]
    terms = []
    for k, (a, b) in enumerate(speech_spans(transcript["words"])):
        f = 180 + 35 * (k % 5)
        terms.append("between(t,%.3f,%.3f)*0.3*sin(2*PI*%d*t)" % (a, b, f))
    expr = "+".join(terms)
    media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=%d:duration=%.3f" % (SIZE[0], SIZE[1], FPS, d),
               "-f", "lavfi", "-i", "aevalsrc='%s':s=48000:c=stereo:d=%.3f" % (expr, d),
               "-vf", "hue=h='2*PI*t/9',scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", path])


def make_asset(path):
    bars = []
    heights = [260, 340, 300, 460, 400, 560, 640]
    for k, h in enumerate(heights):
        x = 110 + k * 125
        bars.append("drawbox=x=%d:y=%d:w=95:h=%d:color=0xFFC93C:t=fill" % (x, 1500 - h, h))
    chain = ["drawbox=x=70:y=420:w=940:h=1140:color=0x0B0F14@0.55:t=fill",
             "drawbox=x=110:y=480:w=360:h=36:color=0xFFFFFF@0.9:t=fill",
             "drawbox=x=110:y=540:w=220:h=24:color=0xA8B0BC@0.9:t=fill"] + bars
    media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "lavfi", "-i", "gradients=size=%dx%d:c0=0x14213D:c1=0x3A0CA3:x0=0:y0=0:x1=1080:y1=1920:nb_colors=2:duration=1:rate=1" % SIZE,
               "-vf", ",".join(chain), "-frames:v", "1", path])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        k = argv.index("--")
        argv, extra = argv[:k], argv[k + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", help="scratch folder for source.mp4, asset.png, silences and the render work")
    ap.add_argument("--out", help="output MP4")
    ap.add_argument("--inputs-only", action="store_true")
    ap.add_argument("--rewrite-transcript", action="store_true")
    args = ap.parse_args(argv)

    tr = build_transcript()
    tr_path = os.path.join(HERE, "transcript.json")
    if args.rewrite_transcript:
        with open(tr_path, "w", encoding="utf-8") as fh:
            json.dump(tr, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print("wrote %s (%d words, %.2fs)" % (tr_path, len(tr["words"]), tr["duration"]))
        return 0
    if not args.out_dir:
        ap.error("--out-dir is required")
    os.makedirs(args.out_dir, exist_ok=True)
    with open(tr_path, "r", encoding="utf-8") as fh:
        committed = json.load(fh)
    if committed != json.loads(json.dumps(tr)):
        raise SystemExit("demo/transcript.json differs from the generator; run --rewrite-transcript")
    source = os.path.join(args.out_dir, "source.mp4")
    asset = os.path.join(args.out_dir, "asset.png")
    make_source(source, committed)
    make_asset(asset)
    print("inputs: %s, %s" % (source, asset), file=sys.stderr)
    if args.inputs_only:
        return 0
    if not args.out:
        ap.error("--out is required unless --inputs-only")
    rargs = ["--source", source, "--transcript", tr_path, "--script", os.path.join(HERE, "script.json"),
             "--asset", "dashboard=" + asset, "--asset", "chart=" + asset,
             "--out", args.out, "--workdir", os.path.join(args.out_dir, "work"), "--silence-detect"] + extra
    return render.main(rargs)


if __name__ == "__main__":
    sys.exit(main())
