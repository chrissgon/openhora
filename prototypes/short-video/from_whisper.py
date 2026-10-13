#!/usr/bin/env python3
"""Convert a whisper.cpp JSON (one word per entry, from `-ml 1 -sow`) to the prototype's transcript.json.

UNVERIFIED: whisper.cpp is not installed on the machine this prototype was built on. The converter reads the
shape the whisper.cpp CLI documents for `--output-json` (`transcription[]` with `offsets.from` and `offsets.to`
in milliseconds and `text`), and has been tested only on a small invented sample in that shape.
A new segment starts after a word that ends a sentence (. ? !) or after a pause longer than --pause seconds.
"""
import argparse
import json
import re
import sys


def convert(whisper, duration, pause=0.8):
    entries = whisper.get("transcription")
    if not isinstance(entries, list):
        raise ValueError("no transcription list")
    words, seg, prev_end, bumped = [], 0, None, False
    for e in entries:
        text = (e.get("text") or "").strip()
        if not text or re.fullmatch(r"\[[A-Z_ ]+\]|\([a-z ]+\)", text):   # [BLANK_AUDIO], (music) ...
            continue
        start, end = e["offsets"]["from"] / 1000.0, e["offsets"]["to"] / 1000.0
        if end <= start:
            end = start + 0.05
        if prev_end is not None and start - prev_end > pause and words and not bumped:
            seg += 1
        bumped = False
        words.append({"i": len(words), "text": text, "start": round(start, 3), "end": round(end, 3), "segment": seg})
        prev_end = end
        if re.search(r"[.?!]$", text):
            seg += 1
            bumped = True
    # the last word must not run past the recording
    for w in words:
        w["end"] = min(w["end"], duration)
    return {"language": whisper.get("result", {}).get("language", "unknown"), "duration": duration, "words": words}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--whisper-json", required=True)
    ap.add_argument("--duration", type=float, required=True, help="recording duration in seconds (ffprobe)")
    ap.add_argument("--pause", type=float, default=0.8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.whisper_json, "r", encoding="utf-8") as fh:
        tr = convert(json.load(fh), args.duration, args.pause)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(tr, fh, indent=1, ensure_ascii=False)
    print("%d words" % len(tr["words"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
