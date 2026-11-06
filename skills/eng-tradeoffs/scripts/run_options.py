#!/usr/bin/env python3
"""Run option prototypes from a scratch folder under every runtime and time zone, and measure sizes.

Usage:
  python3 run_options.py runtimes NAME
      List every executable called NAME on PATH and in the usual version-manager folders, as JSON:
      [{"path": ..., "version": ...}]. Use the paths as --runtime values.

  python3 run_options.py run [--runtime PATH_OR_NAME]... [--tz ZONE]... [--cwd DIR] [--out FILE]
                             [--timeout S] [--jobs N] SCRIPT [ARG ...]
      Run SCRIPT once per runtime and zone (TZ set in the environment), with no shell. SCRIPT must be a
      file inside a scratch folder: <working directory>/.scratch/ or the system's temporary folder.
      --cwd runs it from another folder inside the scratch folder (an option's own copy of the project,
      for a tool that reads relative paths); SCRIPT is then read relative to the folder this command
      was started in, as usual. --out writes the records to a file inside the scratch folder (no shell
      redirection needed) and prints one summary line per combination instead.
      Without --runtime the script is run directly (it must be executable); without --tz the zone is
      left as it is. Prints JSON: one record per combination with the command, exit code, stdout and
      stderr. Combinations run at the same time (--jobs, default 4); records keep the order asked.

  python3 run_options.py size FILE_OR_DIR [FILE_OR_DIR ...]
      Print JSON with the raw and gzip (level 9) byte count of each path and the totals. A folder
      counts every file directly inside it.

Exit codes: 0 done (read each record's exit code), 2 refused or bad input.
Data goes to stdout, diagnostics to stderr. Nothing is read from a prompt.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Version-manager folders, relative to the home folder; {name} is the executable's name.
MANAGER_GLOBS = [
    ".nvm/versions/*/*/bin/{name}",
    ".volta/tools/image/*/*/bin/{name}",
    ".local/share/fnm/node-versions/*/installation/bin/{name}",
    ".fnm/node-versions/*/installation/bin/{name}",
    ".asdf/installs/*/*/bin/{name}",
    ".local/share/mise/installs/*/*/bin/{name}",
    ".pyenv/versions/*/bin/{name}",
    ".rbenv/versions/*/bin/{name}",
]
MAX_OUTPUT = 20_000


def die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(2)


def scratch_roots(cwd: Path) -> list[Path]:
    roots = [cwd / ".scratch", Path(tempfile.gettempdir()), Path("/tmp")]
    return [r.resolve() for r in roots]


def in_scratch(path: Path, cwd: Path) -> bool:
    real = path.resolve()
    roots = scratch_roots(cwd)
    # A project that itself lives under the temporary folder: inside it only .scratch/ counts,
    # or its whole source tree would pass as scratch.
    if real.is_relative_to(cwd.resolve()):
        roots = roots[:1]
    for root in roots:
        try:
            real.relative_to(root)
        except ValueError:
            continue
        if real != root:
            return True
    return False


def refusal_hint(path: Path, cwd: Path) -> str:
    """Name the cause when the current folder is itself inside the temporary folder."""
    real, here = path.resolve(), cwd.resolve()
    if real.is_relative_to(here) and any(here.is_relative_to(r) for r in scratch_roots(cwd)[1:]):
        return (f"; the current folder {cwd} is itself inside the temporary folder, where only "
                f"{cwd / '.scratch'} counts as scratch: run this command from the project root")
    return ""


def valid_name(name: str) -> bool:
    return bool(name) and all(ch.isalnum() or ch in "._-" for ch in name) and not name.startswith((".", "-"))


def version_of(path: str) -> str | None:
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or r.stderr).strip()
    return out.splitlines()[0] if out else None


def find_runtimes(name: str, home: Path, path_var: str) -> list[dict]:
    found: list[str] = []
    for folder in path_var.split(os.pathsep):
        if folder:
            found.append(os.path.join(folder, name))
    for pattern in MANAGER_GLOBS:
        found.extend(sorted(glob.glob(str(home / pattern.format(name=name)))))
    seen, out = set(), []
    for candidate in found:
        if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
            continue
        real = os.path.realpath(candidate)
        if real in seen:
            continue
        seen.add(real)
        out.append({"path": candidate, "version": version_of(candidate)})
    return out


def clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + f"\n[cut: {len(text) - MAX_OUTPUT} more characters]"


def run_one(runtime: str | None, tz: str | None, script: str, args: list[str], timeout: float,
            cwd: str | None = None) -> dict:
    command = ([runtime] if runtime else []) + [script, *args]
    env = dict(os.environ)
    if tz:
        env["TZ"] = tz
    record = {"runtime": runtime, "tz": tz, "cwd": cwd, "command": command}
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd,
                           stdin=subprocess.DEVNULL)
        record.update(exit_code=r.returncode, stdout=clip(r.stdout), stderr=clip(r.stderr))
    except subprocess.TimeoutExpired:
        record.update(exit_code=None, stdout="", stderr=f"timed out after {timeout:g} s")
    except OSError as e:
        record.update(exit_code=None, stdout="", stderr=f"could not start: {e}")
    return record


def cmd_runtimes(a: argparse.Namespace) -> int:
    if not valid_name(a.name):
        die(f"{a.name!r} is not an executable name (letters, digits, . _ -)")
    print(json.dumps(find_runtimes(a.name, Path.home(), os.environ.get("PATH", "")), indent=2))
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    cwd = Path.cwd()
    script = Path(a.script)
    if not script.is_file():
        die(f"{a.script} is not a file")
    if not in_scratch(script, cwd):
        die(f"{a.script} is outside the scratch folders ({cwd / '.scratch'} or the temporary folder); "
            f"prototypes never run from the source tree{refusal_hint(script, cwd)}")
    run_dir = None
    if a.cwd:
        if not Path(a.cwd).is_dir():
            die(f"--cwd {a.cwd} is not a folder")
        if not in_scratch(Path(a.cwd), cwd):
            die(f"--cwd {a.cwd} is outside the scratch folders{refusal_hint(Path(a.cwd), cwd)}")
        run_dir = str(Path(a.cwd).resolve())
    script = script.resolve()
    out_file = None
    if a.out:
        out_file = Path(a.out)
        if not out_file.parent.is_dir() or not in_scratch(out_file, cwd):
            die(f"--out {a.out} must be a file in an existing folder inside the scratch folders"
                f"{refusal_hint(out_file, cwd)}")
    runtimes: list[str | None] = []
    for rt in a.runtime or []:
        resolved = rt if os.path.isabs(rt) else shutil.which(rt)
        if not resolved or not (os.path.isfile(resolved) and os.access(resolved, os.X_OK)):
            die(f"runtime {rt!r} is not an executable; list them with: run_options.py runtimes <name>")
        runtimes.append(resolved)
    if not runtimes:
        if not os.access(script, os.X_OK):
            die(f"{a.script} is not executable; name what runs it with --runtime")
        runtimes = [None]
    zones: list[str | None] = list(a.tz or []) or [None]
    for z in zones:
        if z is not None and not all(ch.isalnum() or ch in "/_+-" for ch in z):
            die(f"{z!r} is not a time zone name")
    if a.jobs < 1:
        die("--jobs must be at least 1")
    combos = [(rt, z) for rt in runtimes for z in zones]
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        records = list(pool.map(lambda c: run_one(c[0], c[1], str(script), a.args, a.timeout, run_dir), combos))
    if out_file:
        out_file.write_text(json.dumps(records, indent=2) + "\n")
        print(json.dumps({"written": str(out_file), "records": [
            {"runtime": r["runtime"], "tz": r["tz"], "exit_code": r["exit_code"]} for r in records]}, indent=2))
    else:
        print(json.dumps(records, indent=2))
    return 0


def cmd_size(a: argparse.Namespace) -> int:
    rows, raw_total, gzip_total = [], 0, 0
    for given in a.paths:
        p = Path(given)
        if p.is_dir():
            files = sorted(f for f in p.iterdir() if f.is_file())
        elif p.is_file():
            files = [p]
        else:
            die(f"{given} is not a file or a folder")
        for f in files:
            data = f.read_bytes()
            size = len(gzip.compress(data, compresslevel=9, mtime=0))
            rows.append({"path": str(f), "raw_bytes": len(data), "gzip_bytes": size})
            raw_total += len(data)
            gzip_total += size
    print(json.dumps({"method": "gzip level 9, each file compressed on its own, sizes added",
                      "files": rows, "raw_bytes": raw_total, "gzip_bytes": gzip_total}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("runtimes", help="list the installed versions of an executable")
    p.add_argument("name")
    p.set_defaults(fn=cmd_runtimes)
    p = sub.add_parser("run", help="run a scratch script under every runtime and time zone")
    p.add_argument("--runtime", action="append", help="executable name or absolute path; repeat")
    p.add_argument("--tz", action="append", help="time zone name for TZ; repeat")
    p.add_argument("--cwd", help="folder inside the scratch folder to run from")
    p.add_argument("--out", help="file inside the scratch folder that receives the records")
    p.add_argument("--timeout", type=float, default=120.0, help="seconds per combination (default 120)")
    p.add_argument("--jobs", type=int, default=4, help="combinations run at the same time (default 4)")
    p.add_argument("script")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("size", help="raw and gzip sizes of files")
    p.add_argument("paths", nargs="+")
    p.set_defaults(fn=cmd_size)
    a = parser.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
