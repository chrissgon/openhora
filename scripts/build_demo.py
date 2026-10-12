#!/usr/bin/env python3
"""Build the demo copy of the local interface: the real pages and modules with fictional data and no service.

Usage:
  python3 scripts/build_demo.py --out <dir>             write the demo into <dir> (it must not exist, or be empty)
  python3 scripts/build_demo.py --out <dir> --replace   first remove <dir> when it holds an earlier build of the demo
  python3 scripts/build_demo.py --help

What it does, with the standard library only (no minifier, no package install):
  1. copies interface/ into <dir> without demo/, the README and any tests folder;
  2. writes interface/demo/* into <dir>/demo/ (the world, the story, the bridge, the boot module, the style, the fixtures);
  3. overwrites <dir>/js/transport.js (the browser's own request function) with interface/demo/transport.js, which answers every
     request of the client from memory, so that nothing in the copy can reach a network;
  4. adds demo/demo.css and demo/boot.js to <dir>/index.html (a module script, no inline script: the page's policy stays
     `default-src 'self'`). boot.js runs before js/main.js.
Every URL in the copy is relative, so the folder can be served from any path, as static files: `python3 -m http.server`.
The interface the service serves is not changed by this: it never serves demo/ (runtime/service.py), and its js/transport.js is the real one.

Prints one JSON line to stdout: {"out", "files", "total_bytes", "vendor_three_bytes"}. Diagnostics go to stderr.
Exit codes: 0 built, 1 the build failed (the output folder is not usable), 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "interface"
MARKER = Path("demo") / "boot.js"
SKIP_TOP = {"demo", "README.md"}
SKIP_ANY = {"tests", "__pycache__", ".DS_Store"}
STYLE_AFTER = '<link rel="stylesheet" href="./scene.css">'
STYLE_LINE = '<link rel="stylesheet" href="./demo/demo.css">'
MAIN_LINE = '<script type="module" src="./js/main.js"></script>'
BOOT_LINE = '<script type="module" src="./demo/boot.js"></script>'


def size_of(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def copy_interface(out: Path) -> None:
    def keep(here, names):
        top = Path(here) == SOURCE
        return [n for n in names if n in SKIP_ANY or (top and n in SKIP_TOP) or n.startswith(".")]

    shutil.copytree(SOURCE, out, ignore=keep)
    shutil.copytree(SOURCE / "demo", out / "demo", ignore=shutil.ignore_patterns(*SKIP_ANY))


def patch_index(out: Path) -> None:
    index = out / "index.html"
    text = index.read_text(encoding="utf-8")
    for needle in (STYLE_AFTER, MAIN_LINE):
        if text.count(needle) != 1:
            raise ValueError(f"index.html does not hold exactly one {needle!r}: the build cannot place the demo's files")
    text = text.replace(STYLE_AFTER, STYLE_AFTER + "\n" + STYLE_LINE).replace(MAIN_LINE, BOOT_LINE + "\n" + MAIN_LINE)
    index.write_text(text, encoding="utf-8")


def build(out: Path, replace: bool = False) -> dict:
    if out.exists():
        if out.is_dir() and not any(out.iterdir()):
            pass
        elif replace and (out / MARKER).is_file():
            shutil.rmtree(out)
        else:
            raise FileExistsError(f"{out} exists and is not empty: give another folder, or --replace for an earlier build of the demo")
    if not (SOURCE / "demo" / "transport.js").is_file():
        raise FileNotFoundError("interface/demo/transport.js is missing")
    copy_interface(out)
    shutil.copyfile(SOURCE / "demo" / "transport.js", out / "js" / "transport.js")
    patch_index(out)
    return {"out": str(out), "files": sum(1 for p in out.rglob("*") if p.is_file()), "total_bytes": size_of(out),
            "vendor_three_bytes": size_of(out / "vendor" / "three")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the demo copy of the local interface (fictional data, no service).")
    parser.add_argument("--out", required=True, help="the folder to write the built demo into")
    parser.add_argument("--replace", action="store_true", help="remove the folder first when it holds an earlier build of the demo")
    args = parser.parse_args(argv)
    try:
        report = build(Path(args.out).resolve(), args.replace)
    except (OSError, ValueError) as e:
        print(f"the demo could not be built: {e}", file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
