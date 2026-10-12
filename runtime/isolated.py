#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Skill code the runtime runs on the host, as an isolated subprocess with a scrubbed environment.

A skill's script (a document's checker, the backlog's task reader) is never imported into the runtime's process and
never inherits the runtime's environment. run_script() starts it as

    <this interpreter> -I -E -s <script> <args...>

(isolated mode: no user site folder, no PYTHON* variable, neither the working folder nor the script's folder on the
import path), in a working folder the caller names, with an environment of exactly these names and nothing else of
the caller's:

  PATH    the caller's search path for programs (os.defpath when the caller has none)
  HOME    a fresh temporary folder, removed when the call returns
  TMPDIR  a folder inside that one
  LANG, LC_ALL   C.UTF-8

So no WB_* variable, no credential name and no secret of the caller reaches a skill's code. The container, which is
the stronger boundary, stays an open option (docs/architecture/platform/review-2026-10-06.md, finding 9).

Functions:
  clean_env(home)                        the environment above, for a HOME folder
  skill_script(root, skill, name)        the path of a skill's script (the one place the runtime names that folder)
  run_script(script, args, *, cwd, timeout, stdin=None)
                                         a subprocess.CompletedProcess with text stdout and stderr; raises
                                         subprocess.TimeoutExpired on a timeout and OSError when it cannot start

Usage (a library): python3 runtime/isolated.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

LOCALE = "C.UTF-8"
NAMES = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")


def clean_env(home: str) -> dict:
    """The whole environment of an isolated script: NAMES, and nothing else."""
    return {"PATH": os.environ.get("PATH") or os.defpath, "HOME": home, "TMPDIR": os.path.join(home, "tmp"),
            "LANG": LOCALE, "LC_ALL": LOCALE}


def skill_script(root: str, skill: str, name: str) -> str:
    """The path of a skill's script, <root>/skills/<skill>/scripts/<name>: what a manifest's checker or a role's
    reader names. Only a plain file name of that folder."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"{name!r} is not the name of a script of a skill's scripts/ folder")
    return os.path.join(root, "skills", skill, "scripts", name)


def run_script(script: str, args, *, cwd: str, timeout: float, stdin=None) -> subprocess.CompletedProcess:
    """Run a skill's script isolated (see the module text). `script` is a path, `args` a list of texts, `cwd` the
    working folder, `stdin` text or None. Not a shell: nothing is interpreted."""
    home = tempfile.mkdtemp(prefix="wb-isolated-")
    try:
        os.makedirs(os.path.join(home, "tmp"))
        return subprocess.run([sys.executable, "-I", "-E", "-s", script, *[str(a) for a in args]], cwd=cwd,
                              env=clean_env(home), input=stdin, capture_output=True, text=True, timeout=timeout,
                              check=False)
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
