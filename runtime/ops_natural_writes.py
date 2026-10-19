#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The card-opening path of the natural writes (package NR-5a): the one place that opens a write for a line. This commit is the interface; the path follows.

The family resolvers are `ops_natural_<family>.resolve(ctx, op, slots, channel, sender, said)` (see runtime/natural_writes.py): {"args"} | {"ask"} | {"say"}.

Standard library only. Runs on Python 3.9: python3 runtime/ops_natural_writes.py --help
"""
from __future__ import annotations

import sys

if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
