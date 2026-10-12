#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The skills the runtime names, as data: runtime/roles.json, read and checked.

The runtime's wiring to named skills is one file, not a constant in four modules:

  router         the skill that routes a request (runtime/router.py)
  brief          the skill whose route plans one brief task (runtime/plan.py)
  subtask        the skill a product-backlog task runs in (runtime/plan.py)
  code_areas     the skill areas whose tasks change versioned files (runtime/workcopy.py)
  packs_in_use   the packs whose skills must have a whole runtime manifest (runtime/manifest.py)

Bringing another router, another pack or another code area into the runtime edits that file and no step of any
module. The file has exactly these keys; each skill is a folder of skills/ with a SKILL.md, each area is one of
AREAS (the closed list of the frontmatter contract of AGENTS.md; a test binds it to scripts/validate.py), each
pack is a file of packs/. A problem is a RolesError that names the key.

Functions:
  load(root=None)    the checked roles as a dict (root: the checkout whose skills/ and packs/ are read; default the
                     checkout this file is in). Called once by each module that needs a role, at import.

Usage (a library): python3 runtime/roles.py --help
  python3 runtime/roles.py --check     print the roles as one JSON object; exit 1 and name the problem when not well formed

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILE = os.path.join(HERE, "roles.json")
SKILL_KEYS = ("router", "brief", "subtask")
KEYS = SKILL_KEYS + ("code_areas", "packs_in_use")
AREAS = ("business", "product", "brand", "design", "engineering", "delivery", "marketing", "ai", "core", "assistant")


class RolesError(Exception):
    """roles.json is missing or not well formed; the message names the key."""


def _texts(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


_CACHE = {}


def load(root=None, file=None) -> dict:
    """The roles of `file` (default runtime/roles.json), checked against the skills and packs of `root` (default the
    checkout this file is in). Raises RolesError naming the first key that is wrong."""
    if root is None and file is None and "default" in _CACHE:
        return dict(_CACHE["default"])
    default = root is None and file is None
    root = ROOT if root is None else root
    file = FILE if file is None else file
    try:
        with open(file, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        raise RolesError(f"roles: {file} cannot be read") from None
    except ValueError as e:
        raise RolesError(f"roles: {file} is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise RolesError("roles: the file is not a JSON object")
    for key in KEYS:
        if key not in data:
            raise RolesError(f"roles: missing key `{key}`")
    for key in data:
        if key not in KEYS:
            raise RolesError(f"roles: unknown key `{key}` (the keys are {', '.join(KEYS)})")
    for key in SKILL_KEYS:
        name = data[key]
        if not isinstance(name, str) or not os.path.isfile(os.path.join(root, "skills", str(name), "SKILL.md")):
            raise RolesError(f"roles: `{key}` is {name!r}, which is not a folder of skills/ with a SKILL.md")
    if not _texts(data["code_areas"]):
        raise RolesError("roles: `code_areas` is not a non-empty list of texts")
    for area in data["code_areas"]:
        if area not in AREAS:
            raise RolesError(f"roles: `code_areas` holds {area!r}, which is not an area ({', '.join(AREAS)})")
    if not _texts(data["packs_in_use"]):
        raise RolesError("roles: `packs_in_use` is not a non-empty list of texts")
    for pack in data["packs_in_use"]:
        if not os.path.isfile(os.path.join(root, "packs", f"{pack}.txt")):
            raise RolesError(f"roles: `packs_in_use` holds {pack!r}, which is not a file of packs/")
    if default:
        _CACHE["default"] = dict(data)
    return data


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--check"]:
        try:
            print(json.dumps(load()))
        except RolesError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
