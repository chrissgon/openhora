#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The calendar family of the natural writes (package NR-5a), pure: the interface of runtime/natural_writes.py. This commit is the interface; the family follows.

Standard library only. Runs on Python 3.9: python3 runtime/natural_writes_calendar.py --help
"""
from __future__ import annotations

import sys


def HEADS(tables):
    return []


def read(line, tables, now=None, op=None):
    return None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
