#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a skill declares in its frontmatter, read for the runtime: the artifact lists, the requirement classes,
the side effects and the version. Nothing here is the runtime's own knowledge of a skill: what cannot be
derived from the frontmatter lives in the skill's runtime manifest (skills/<name>/evals/runtime-manifest.json,
stage 2 of the platform plan).

Usage (a library):
  python3 runtime/skill_meta.py --help
  python3 runtime/skill_meta.py <skill folder>     print what the skill declares, as JSON

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import sys

LISTS = ("inputs", "outputs", "updates", "requires", "side_effects")
PLACEHOLDER = re.compile(r"<[^<>/]*>")
WEB_CLASS = "search:web"


class SkillError(Exception):
    pass


def declared(skill_dir: str) -> dict:
    """{"name", "inputs", "outputs", "updates", "requires", "side_effects", "version", "web", "area"} of a skill folder.
    Every list is written inline in the frontmatter (`inputs: [a, b]`), as scripts/validate.py requires; a list
    that is missing or written another way is an error, never an empty list."""
    path = os.path.join(skill_dir, "SKILL.md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        raise SkillError(f"{skill_dir} is not a skill folder: it has no SKILL.md") from None
    if not text.startswith("---"):
        raise SkillError(f"{path} has no frontmatter")
    head = text.split("\n---", 1)[0]
    out = {"name": os.path.basename(os.path.normpath(skill_dir))}
    for key in LISTS:
        m = re.search(r"^  " + key + r":\s*\[(.*)\]\s*(?:#.*)?$", head, re.M)
        if not m:
            raise SkillError(f"{path}: metadata.{key} is missing or is not an inline list")
        out[key] = [v.strip().strip("\"'") for v in m.group(1).split(",") if v.strip()]
    m = re.search(r"^  version:\s*[\"']?(\d+\.\d+\.\d+)[\"']?\s*(?:#.*)?$", head, re.M)
    out["version"] = m.group(1) if m else None
    m = re.search(r"^  area:\s*([a-z]+)", head, re.M)
    if not m:
        raise SkillError(f"{path}: metadata.area is missing")
    out["area"] = m.group(1)
    out["web"] = WEB_CLASS in out["requires"]
    return out


def pattern(declared_path: str) -> re.Pattern:
    """A declared path as a pattern: each placeholder (<topic>) stands for one or more characters of one path
    segment, and a path that ends in "/" is a folder with everything under it."""
    parts = PLACEHOLDER.split(declared_path)
    body = "[^/]+".join(re.escape(p) for p in parts)
    return re.compile("^" + body + (".*" if declared_path.endswith("/") else "") + "$")


def matches(declared_paths, rel: str) -> bool:
    """True when rel is one of the declared artifact paths."""
    return any(pattern(p).match(rel) for p in declared_paths)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
        return 0 if argv in (["--help"], ["-h"]) else 2
    try:
        print(json.dumps(declared(argv[0]), indent=1))
    except SkillError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
