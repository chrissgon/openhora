#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A project's dependencies, installed by code: in the eval image, in a step with no model that sees only the
dependency files, and copied into each run that needs them.

A run reaches only the model's provider, so it cannot install anything, and the image holds no project's
dependencies. The project's configuration (docs/workbench/runtime.json) declares its dependency sets by recipe,
from the closed table RECIPES:

  "dependencies": [{"recipe": "python-requirements", "file": ".workbench-local/requirements-dev.txt"},
                   {"recipe": "node-npm"}]

For each set the runtime reads the dependency files as the next run will see them, and installs them once per
content and image: the install runs in the container of a run (lab.run_command), on the open network, in a folder
that holds only those files (named case/, so that what is installed sits at the path it will have in a run), with
no passed variable, so a package's install script finds no code, no document and no credential. What it produced
is cleared of every tool's settings, then cached in <data_dir>/deps/<key>/ (key: the recipe, the files and the
image's digest). A run gets a copy of the cached folder after its base commit, excluded from its git, and the
folder is removed from the copy before anything comes back. The host never executes anything from an installed
folder.

Public names: RECIPES, DepsError, declared(cfg), files_for(entry, read), key(entry, files, image_digest),
ensure(data_dir, entry, files, image_digest, run=None, settings=None), place(result, copy_dir), remove(copy_dir,
produces).

Usage (a library; the shell's command is `deps --project <dir>`): python3 runtime/deps.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import path_rule  # noqa: E402  (the same folder)

# The closed table of recipes. "files" are the dependency files relative to the project root; a recipe that takes
# a file has "file" (its default) in place of a fixed list. "{file}" in a command is the entry's file.
RECIPES = {
    "node-npm": {"files": ("package.json", "package-lock.json"), "default_file": None,
                 "commands": (("npm", "ci", "--no-fund", "--no-audit"),), "produces": "node_modules"},
    "python-requirements": {"files": None, "default_file": "requirements.txt",
                            "commands": (("python3", "-m", "venv", ".venv"),
                                         (".venv/bin/python", "-m", "pip", "install", "--no-input", "-r", "{file}")),
                            "produces": ".venv"},
}
ENTRY_KEYS = ("recipe", "file")
CACHE_DIR = "deps"
CASE = "case"
INSTALL_TIMEOUT = 900  # seconds per command of an install
ERROR_LINES = 20       # lines of a failed command's error output kept in the reason
DONE_FILE = "deps.json"


class DepsError(Exception):
    """kind is "config" (the configuration's dependencies are not valid) or "install" (an install failed)."""

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind, self.reason = kind, reason


def declared(cfg: dict) -> list:
    """The entries of the configuration key `dependencies`, checked: a list of objects, each with a known recipe,
    no other key than recipe and file, and file only for a recipe that takes one, a relative path inside the
    project. cfg is project_config.load()'s result (its "raw") or the parsed file itself. Absent means none.
    Returns [{"recipe", "file", "files"}], files being the dependency files of the entry."""
    raw = cfg.get("raw", cfg) if isinstance(cfg, dict) else {}
    value = raw.get("dependencies")
    if value is None:
        return []
    if not isinstance(value, list):
        raise DepsError("config", "runtime.json dependencies must be a list of objects")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise DepsError("config", "runtime.json dependencies must be a list of objects")
        unknown = sorted(set(item) - set(ENTRY_KEYS))
        if unknown:
            raise DepsError("config", f"runtime.json dependencies: unknown key {', '.join(unknown)}")
        recipe = RECIPES.get(item.get("recipe")) if isinstance(item.get("recipe"), str) else None
        if recipe is None:
            raise DepsError("config", f"runtime.json dependencies: recipe must be one of {', '.join(sorted(RECIPES))}")
        if recipe["default_file"] is None:
            if "file" in item:
                raise DepsError("config", f"runtime.json dependencies: the recipe {item['recipe']} takes no file")
            files = list(recipe["files"])
            chosen = None
        else:
            chosen = item.get("file", recipe["default_file"])
            rel = path_rule.normal(chosen) if isinstance(chosen, str) else None
            if rel is None or rel != chosen:
                raise DepsError("config", "runtime.json dependencies: file must be a relative path inside the project")
            files = [rel]
        out.append({"recipe": item["recipe"], "file": chosen, "files": files})
    return out


def files_for(entry: dict, read) -> list | None:
    """[(relative path, bytes)] of the entry's dependency files as the next run will see them. read(rel) is the
    caller's: it returns the bytes, or None when the file is not there. None when one file is missing: the set
    does not apply."""
    out = []
    for rel in entry["files"]:
        data = read(rel)
        if data is None:
            return None
        out.append((rel, bytes(data)))
    return out


def key(entry: dict, files, image_digest) -> str:
    """The sha256 over the recipe's name, each path with its bytes (in path order) and the image's digest: the same
    files on the same image are installed once."""
    digest = hashlib.sha256()
    digest.update(entry["recipe"].encode("utf-8") + b"\0")
    for rel, data in sorted(files):
        digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).hexdigest().encode("ascii") + b"\0")
    digest.update(str(image_digest or "no image").encode("utf-8"))
    return digest.hexdigest()


def _done(folder: str):
    try:
        with open(os.path.join(folder, DONE_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _result(entry: dict, k: str, folder: str, record: dict, cached: bool) -> dict:
    return {"recipe": entry["recipe"], "key": k, "tree": os.path.join(folder, "tree"),
            "produces": RECIPES[entry["recipe"]]["produces"], "cached": cached, "duration_ms": record.get("duration_ms")}


def _remove(path: str) -> None:
    """Remove a path a run or an install left: a link is unlinked, a folder removed without following links."""
    if os.path.islink(path) or (os.path.lexists(path) and not os.path.isdir(path)):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def _settings_out(folder: str, names) -> list:
    """Remove, at any depth and without following a link, every file or folder whose name carries a tool's
    settings (lab.settings_names()). Returns the relative paths removed."""
    names, removed = set(names), []
    for current, folders, files in os.walk(folder):
        for name in sorted(folders + files):
            if name in names:
                path = os.path.join(current, name)
                removed.append(os.path.relpath(path, folder))
                _remove(path)
        folders[:] = [n for n in folders if n not in names and not os.path.islink(os.path.join(current, n))]
    return removed


def _last_lines(text: str) -> str:
    return "\n".join((text or "").strip().splitlines()[-ERROR_LINES:])


# T23: the install step leaves when the image carries a project's dependencies
def ensure(data_dir: str, entry: dict, files, image_digest, run=None, settings=None) -> dict:
    """The installed folder for these dependency files: from the cache, or installed now. Returns {"recipe", "key",
    "tree", "produces", "cached", "duration_ms"}; the folder is <tree>/<produces>. run defaults to lab.run_command;
    settings to lab.settings_names(). A cache folder is complete only when its deps.json exists, written last; the
    install runs under a lock of its own, in a folder that holds only the dependency files. Raises DepsError."""
    recipe = RECIPES[entry["recipe"]]
    k = key(entry, files, image_digest)
    base = os.path.join(data_dir, CACHE_DIR)
    final = os.path.join(base, k)
    found = _done(final)
    if found is not None:
        return _result(entry, k, final, found, True)
    os.makedirs(base, mode=0o700, exist_ok=True)
    lock = os.open(os.path.join(base, f"{k}.lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        found = _done(final)
        if found is not None:
            return _result(entry, k, final, found, True)
        if run is None or settings is None:
            import lab  # noqa: E402  (only when it installs: the module itself never runs a command)
            run = run or lab.run_command
            settings = lab.settings_names() if settings is None else settings
        tmp = os.path.join(base, f"tmp-{k}")
        _remove(tmp)
        _remove(final)
        case = os.path.join(tmp, CASE)
        os.makedirs(case, mode=0o700)
        try:
            for rel, data in files:
                target = os.path.join(case, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
            started = time.monotonic()
            for command in recipe["commands"]:
                argv = [part.replace("{file}", entry.get("file") or "") for part in command]
                done = run(argv, tmp, cwd=case, network="open", timeout=INSTALL_TIMEOUT)
                if done.get("timed_out"):
                    raise DepsError("install", f"{' '.join(argv)} timed out after {INSTALL_TIMEOUT}s")
                if done.get("returncode") != 0:
                    raise DepsError("install", f"{' '.join(argv)} exited {done.get('returncode')}:\n"
                                               f"{_last_lines(done.get('stderr'))}")
            produced = os.path.join(case, recipe["produces"])
            if os.path.islink(produced) or not os.path.isdir(produced):
                raise DepsError("install", f"the install produced no folder {recipe['produces']}")
            _settings_out(produced, settings)
            duration = int((time.monotonic() - started) * 1000)
            os.makedirs(os.path.join(final, "tree"), mode=0o700)
            shutil.move(produced, os.path.join(final, "tree", recipe["produces"]))
            record = {"recipe": entry["recipe"], "key": k,
                      "files": [{"path": rel, "sha256": hashlib.sha256(data).hexdigest()} for rel, data in sorted(files)],
                      "image_digest": image_digest,
                      "installed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "duration_ms": duration}
            with open(os.path.join(final, DONE_FILE), "w", encoding="utf-8") as f:
                json.dump(record, f, indent=1, sort_keys=True)
                f.write("\n")
        except BaseException:
            _remove(final)
            raise
        finally:
            _remove(tmp)
        return _result(entry, k, final, record, False)
    finally:
        os.close(lock)


def place(result: dict, copy_dir: str) -> str:
    """Copy the cached folder into a fresh copy (links copied as links, never followed), and add its name to the
    copy's .git/info/exclude, so that the run's git never sees it. Returns the folder's name."""
    produces = result["produces"]
    target = os.path.join(copy_dir, produces)
    if os.path.lexists(target):
        raise DepsError("install", f"the copy already holds {produces}: a dependency folder enters a fresh copy only")
    shutil.copytree(os.path.join(result["tree"], produces), target, symlinks=True)
    info = os.path.join(copy_dir, ".git", "info")
    if os.path.isdir(os.path.join(copy_dir, ".git")):
        os.makedirs(info, exist_ok=True)
        with open(os.path.join(info, "exclude"), "a", encoding="utf-8") as f:
            f.write(f"\n/{produces}/\n")
    return produces


def remove(copy_dir: str, produces: str) -> None:
    """Remove the dependency folder from a copy a run touched: a link where it should be is unlinked, never
    followed; a folder is removed without following the links inside it."""
    _remove(os.path.join(copy_dir, produces))


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
