#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The one seam through which a sibling of runtime/ops.py calls an operation of the facade (44-C2, OPEN-S8): `function(name)` returns
`ops.<name>`, read at the moment of the call.

runtime/ops.py imports its siblings at module level, so a sibling cannot import it back. A sibling that needs an operation of the table,
or a public entry of the facade (`pending`, `answer`, `reject`, `status`, `progress`, `request`, `route`, `natural_write`,
`natural_forget`, `event_create`, `event_change`, and the call of each row of the table), calls it as a shell does: by name, through
this module, `ops_facade.function("pending")(project, pending_id=...)`. The lookup is made on every call, never kept, so a test that
patches `ops.<name>` (`monkeypatch.setattr(ops, "pending", ...)`), the golden kit's spies and the sentinels of the effect paths keep
reaching what production calls. The seam has one rule, pinned by runtime/tests/test_ops_facade.py: every literal argument of
`ops_facade.function(...)` in runtime/ is a public name of `ops` (no leading `_`, not UPPER_CASE); a private helper or a constant never
goes through it, it moves to the sibling that owns its job. The four calls that pass a variable pass `row["call"]` (the table's own
names) or the name `ops_event_revise._arguments` returns (`event_create` or `event_change`).

This file imports no module of the runtime, so every sibling may import it at module level. It is the one lazy edge to `ops` that a
sibling keeps (with the dispatcher's entry and the helpers of the run body and the round that ops_runs still reads in ops.py, 44-C4).

Standard library only. Runs on Python 3.9: python3 runtime/ops_facade.py --help
"""
from __future__ import annotations

import importlib
import sys


def function(name: str):
    """`ops.<name>`, found at the moment of the call. Raises AttributeError when ops has no such name."""
    return getattr(importlib.import_module("ops"), name)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
