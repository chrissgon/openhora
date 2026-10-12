#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The billing of the credential a run uses, read from the adapters' manifests: whether a run is covered by a subscription,
paid by use (an API key) or free. The daily caps of an area agent count by it (runtime/autonomy.py, contracts/runtime.md).

Each adapter's manifest, adapters/<harness>/adapter.json, states for every credential it registers (the "secrets" list) how
that credential is billed, in one of three words:

  subscription   a fixed fee covers the runs; what a run costs is not billed, so the daily cap counts runs
  metered        each run is paid by use (an API key); the daily cap counts dollars
  free           nothing is paid (a local model with no credential); the daily cap counts runs

A harness that holds the credential itself (a login of its own command-line tool, no variable) declares it once, under the
manifest's key "login_billing". A run that passes no variable uses it.

  WORDS                              the three words
  load(root)                         {harness: its manifest} for every manifest adapters/<harness>/adapter.json of the checkout at root; a
                                     manifest that cannot be read is left out
  of_route(manifests, adapter, names)   the billing of a run on adapter that passes the variables names: the word, or None
                                     when it cannot be known

of_route never guesses. A variable the adapter lists is read from the adapter's own manifest, else from another adapter's
(one credential can serve two harnesses; the validator requires their words to agree). A variable that no manifest lists, an
entry with no word of the three, or an adapter with no "login_billing" and no variable is unknown (None), and the caller
refuses to start a run it cannot bound (runtime/autonomy.py, may_start). When one route passes several variables the
strictest word wins, metered first (a key that is paid by use must be bounded in dollars), then subscription, then free.

Usage (a library): python3 runtime/billing.py --help

Standard library only. Runs on Python 3.9. Reads manifests; writes nothing.
"""
from __future__ import annotations

import glob
import json
import os
import sys

WORDS = ("subscription", "metered", "free")
STRICTEST_FIRST = ("metered", "subscription", "free")


def load(root: str) -> dict:
    """{harness: the manifest's data} for each adapters/<harness>/adapter.json under root. A folder with no manifest, a manifest
    that is not JSON and one that is not an object are left out: they name no credential."""
    out = {}
    for path in sorted(glob.glob(os.path.join(root, "adapters", "*", "adapter.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out[os.path.basename(os.path.dirname(path))] = data
    return out


def _entry_word(manifest, name: str):
    """The word of the entry called name in one manifest's "secrets", else None."""
    secrets = manifest.get("secrets") if isinstance(manifest, dict) else None
    for entry in secrets if isinstance(secrets, list) else []:
        if isinstance(entry, dict) and entry.get("name") == name:
            word = entry.get("billing")
            return word if word in WORDS else None
    return None


def _of_variable(manifests: dict, adapter: str, name: str):
    """The word of one variable: the adapter's own entry first, then any other adapter's (in the order of the names)."""
    word = _entry_word(manifests.get(adapter), name)
    if word is not None:
        return word
    for other in sorted(manifests):
        word = _entry_word(manifests[other], name)
        if word is not None:
            return word
    return None


def of_route(manifests: dict, adapter: str, names) -> str | None:
    """The billing of a run on adapter that passes the variables names (a list; empty when the harness uses its own login),
    or None when it cannot be known: see the module docstring."""
    if not names:
        manifest = manifests.get(adapter)
        word = manifest.get("login_billing") if isinstance(manifest, dict) else None
        return word if word in WORDS else None
    words = [_of_variable(manifests, adapter, name) for name in names]
    if any(word is None for word in words):
        return None
    return next(word for word in STRICTEST_FIRST if word in words)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
