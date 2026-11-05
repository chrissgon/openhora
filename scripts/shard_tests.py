#!/usr/bin/env python3
"""Run pytest on one shard of the collected tests: the arguments after `--` go to pytest unchanged.

Usage:
  uv run --with pytest==9.1.1 --with pytest-xdist==3.8.0 python scripts/shard_tests.py --shard 2/3 -- -q -n auto $(python3 scripts/test_dirs.py)

It puts scripts/pytest_plugins/ (which holds only wb_shard.py) at the front of sys.path and starts pytest with
`-p wb_shard --wb-shard K/N`. pytest-xdist carries the path to its workers. The exit code is pytest's.
CI's whole suite runs it once per shard (.github/workflows/checks.yml, the job tests-shard).
"""
from __future__ import annotations

import argparse
import os
import sys

PLUGINS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pytest_plugins")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = []
    if "--" in argv:
        at = argv.index("--")
        argv, rest = argv[:at], argv[at + 1:]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shard", required=True, metavar="K/N", help="the shard to run, 1 <= K <= N")
    args = parser.parse_args(argv)
    sys.path.insert(0, PLUGINS)
    import pytest  # noqa: E402  (after argparse: --help needs no pytest)
    # The plugin checks K/N itself (a pytest usage error, exit 4). It is not imported here: a module imported before pytest
    # loads it as a plugin cannot be assertion-rewritten, and pytest would warn.
    return pytest.main(["-p", "wb_shard", "--wb-shard", args.shard, *rest])


if __name__ == "__main__":
    sys.exit(main())
