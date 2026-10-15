"""A stand-in provider of the class script:project, and the project files the tests of the step kind `project-script` use (not a test file).

`install(tree)` writes `providers/script/container.py` into the stand-in workbench tree of standin_tree.py. The runtime reaches it
as it reaches the real one: providers/resolve.py starts it as a process, with the minimum environment, and reads the one JSON object it
prints. It runs no container and no script: it answers by the first line of the staged script, which says what the stand-in does.

  # fake: md=<text>         write result.md with that text           # fake: csv=a,b|1,2   write result.csv ("|" is a newline)
  # fake: exit=<n>          end with that exit code (no result)      # fake: signal=9       end by that signal
  # fake: env               write the names of its own environment into result.md
  # fake: two               write two result files                   # fake: extra          leave a file that is no output's name
  # fake: big               write a result over the cap              # fake: none           write no result at all
  # fake: stdin             write what the provider was started with (its arguments) into result.md

Every call is appended to `calls.jsonl` beside it, with its verb and its arguments.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROVIDER = r'''#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
verb, args = sys.argv[1], sys.argv[2:]
flags, destinations, i = {}, [], 0
while i < len(args):
    if args[i] == "--destination":
        destinations.append(args[i + 1])
    else:
        flags[args[i]] = args[i + 1]
    i += 2
with open(os.path.join(HERE, "calls.jsonl"), "a") as log:
    log.write(json.dumps({"verb": verb, "flags": flags, "destinations": destinations}) + "\n")
if verb == "deps":
    with open(flags["--lock"], "rb") as f:
        assert f.read(), "an empty lock"
    print(json.dumps({"image": "sha256:" + "d" * 64, "tag": "openhora-script-deps:fake", "cached": False}))
    sys.exit(0)
assert verb == "run", verb
with open(flags["--script"], "rb") as f:
    first = f.read().decode("utf-8", "replace").split("\n", 1)[0]
mode = first.split("fake:", 1)[1].strip() if "fake:" in first else "md=ok"
out = flags["--out-dir"]
info = {"exit": 0, "signal": None, "duration_ms": 7, "results": [], "refused": []}


def put(name, text):
    with open(os.path.join(out, name), "wb") as f:
        f.write(text if isinstance(text, bytes) else text.encode())
    info["results"].append(name)


if mode.startswith("md="):
    put("result.md", mode[3:] + "\n")
elif mode.startswith("csv="):
    put("result.csv", mode[4:].replace("|", "\n") + "\n")
elif mode.startswith("exit="):
    info["exit"] = int(mode[5:])
elif mode.startswith("signal="):
    info["exit"], info["signal"] = None, int(mode[7:])
elif mode == "env":
    put("result.md", "environment: " + ",".join(sorted(os.environ)) + "\n")
elif mode == "args":
    put("result.md", json.dumps({"flags": sorted(flags), "destinations": destinations}) + "\n")
elif mode == "two":
    put("result.md", "one\n")
    put("result.txt", "two\n")
elif mode == "extra":
    put("result.md", "one\n")
    with open(os.path.join(out, "other.bin"), "wb") as f:
        f.write(b"x")
elif mode == "big":
    put("result.md", b"a" * (1024 * 1024 + 1))
elif mode == "none":
    pass
with open(os.path.join(out, "info.json"), "w") as f:
    json.dump(info, f)
print(json.dumps({"exit": info["exit"], "signal": info["signal"], "duration_ms": 7, "results": info["results"], "refused": [],
                  "outputs": sorted(os.listdir(out)), "image": flags.get("--image") or "sha256:" + "b" * 64}))
'''


def install(tree: Path) -> Path:
    """The stand-in provider in the tree; returns the folder it sits in."""
    folder = tree / "providers" / "script"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "container.py").write_text(PROVIDER, encoding="utf-8")
    return folder


def calls(tree: Path) -> list:
    path = tree / "providers" / "script" / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def write(project: Path, rel: str, text: str) -> str:
    """A file of the project; returns the sha256 of its bytes."""
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
