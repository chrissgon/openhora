#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The conversation with the planning agent, in the terminal: one more shell of the operations layer (runtime/ops.py,
say). It holds no logic of its own.

Usage:
  python3 runtime/chat.py --project <dir> [--json]

Reads standard input line by line until its end; an empty line is skipped. Each line is one turn (ops.say): a command
(/help lists them), the answer to the planning agent's question, or a new request, which runs the router skill on a
model (like run-next) and shows the plan it builds; approve it with /approve <id>. A reply of the model is shown,
never executed. Prints each reply and a blank line; with --json, each turn's result as one JSON object on one line.
On a terminal it writes "> " to standard error before each line. An error is printed on standard error and the
conversation goes on, except a project that is not configured (exit 3).

Exit codes: 0 at the end of the input, 2 usage error, 3 the project is not configured.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ops  # noqa: E402  (the same folder)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--help" in argv or "-h" in argv:
        print(__doc__.strip())
        return 0
    as_json = "--json" in argv
    rest = [a for a in argv if a != "--json"]
    if len(rest) != 2 or rest[0] != "--project":
        print("error: give --project <dir>. See --help.", file=sys.stderr)
        return 2
    project = os.path.abspath(rest[1])
    interactive = sys.stdin.isatty()
    while True:
        if interactive:
            print("> ", end="", file=sys.stderr, flush=True)
        line = sys.stdin.readline()
        if not line:
            return 0
        if not line.strip():
            continue
        try:
            out = ops.say(project, line.rstrip("\n"))
        except ops.OpsError as e:
            print(f"error: {e}", file=sys.stderr)
            if e.code == 3:
                return 3
            continue
        if as_json:
            print(json.dumps(out, ensure_ascii=False, default=str))
        else:
            print(out["reply"])
            print()
        sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
