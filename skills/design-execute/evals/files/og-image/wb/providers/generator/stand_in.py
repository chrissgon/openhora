#!/usr/bin/env python3
"""Image generator provider (class generator:image).

Usage: python3 stand_in.py --check
       python3 stand_in.py generate --prompt-file <f> --size <WxH> --out <path.png> [--dry-run]

--check prints {"ok": true} and exits 0. generate --dry-run prints the payload and does nothing. generate
without --dry-run records the call as one line in wb/calls.log and writes a blank PNG of the size asked.
"""
import json
import struct
import sys
import zlib
from pathlib import Path

WB = Path(__file__).resolve().parents[2]


def arg(name):
    args = sys.argv[1:]
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = (b"\x00" + b"\xff\xff\xff" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


if "--help" in sys.argv:
    print(__doc__.strip())
    sys.exit(0)
if "--check" in sys.argv:
    print(json.dumps({"ok": True}))
    sys.exit(0)
if len(sys.argv) > 1 and sys.argv[1] == "generate":
    prompt_file, size, out = arg("--prompt-file"), arg("--size"), arg("--out")
    if not (prompt_file and size and out) or "x" not in size:
        print("usage: stand_in.py generate --prompt-file <f> --size <WxH> --out <path.png> [--dry-run]",
              file=sys.stderr)
        sys.exit(2)
    width, height = (int(n) for n in size.split("x", 1))
    prompt = Path(prompt_file).read_text(encoding="utf-8")
    if "--dry-run" in sys.argv:
        print(json.dumps({"dry_run": True, "size": size, "out": out, "prompt": prompt}))
        sys.exit(0)
    with open(WB / "calls.log", "a", encoding="utf-8") as log:
        log.write(f"generate {size} {out}\n")
    Path(out).write_bytes(png(width, height))
    print(json.dumps({"out": out}))
    sys.exit(0)
print("usage: stand_in.py --check | generate ...", file=sys.stderr)
sys.exit(2)
