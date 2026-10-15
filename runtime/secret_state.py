#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Whether the OS secret store is locked or unavailable, for the messages of the runtime (package P-OPS, finding I3).

A locked store used to read as a missing secret, and a routine that needed a key failed at night with "the credential is
missing" while the key was stored. The resolver (providers/secrets/resolver.py) now tells the two apart; this module is the
runtime's one use of that: it loads the resolver by path, asks the store for a name nothing stores (`probe_store`, no secret is
read), and gives the sentence a message shows. The operations layer, the page's held reasons and the connections read call it
only when a credential is already missing, so that a store in good order is never asked for nothing.

The answer is kept for PROBE_SECONDS, so that a page that asks every few seconds does not ask a locked keychain to prompt the
person each time. Never a value, never a message of the backend.

Standard library only. Runs on Python 3.9: python3 runtime/secret_state.py --help
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESOLVER = ("providers", "secrets", "resolver.py")
PROBE_SECONDS = 30.0
LOCKED_NOTE = "the secret store is locked or unavailable: unlock it; a secret listed as missing may be stored"
_CACHE = {}   # {root: (monotonic time, probe answer)}


def _resolver(root: str):
    """The workbench's resolver, loaded by path under its own module name (a copy of its state, apart from the lab's)."""
    path = os.path.join(root, *RESOLVER)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver_state", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module   # its dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def probe(root=None, *, store="default", clock=time.monotonic, fresh: bool = False) -> dict:
    """{"state": "ok" | "no-library" | "locked" | "unavailable" | "unknown", "detail"}: the resolver's probe_store. "unknown" when
    the resolver cannot be loaded or probed here. Kept PROBE_SECONDS (a fake store is never kept)."""
    root = root or ROOT
    now = clock()
    if store == "default" and not fresh:
        kept = _CACHE.get(root)
        if kept and now - kept[0] < PROBE_SECONDS:
            return kept[1]
    try:
        answer = _resolver(root).probe_store(store)
    except Exception as e:  # an interpreter the resolver does not run on, a missing file
        answer = {"state": "unknown", "detail": f"the secret store could not be asked: {type(e).__name__}"}
    if store == "default":
        _CACHE[root] = (now, answer)
    return answer


def locked_sentence(root=None, *, store="default", clock=time.monotonic, fresh: bool = False) -> str:
    """The sentence that tells the secret store is locked or unavailable and what to do, or "" when it answers, when the keyring
    library is missing (that has its own message) or when it cannot be asked."""
    answer = probe(root, store=store, clock=clock, fresh=fresh)
    if answer["state"] in ("locked", "unavailable"):
        return answer["detail"]
    return ""


def unreadable_sentence(root=None, *, store="default", fresh: bool = False) -> str:
    """The sentence that tells why a credential cannot be read although it may be stored: the credentials directory is refused as unsafe
    (with the fix), else the OS secret store is locked or unavailable; "" when neither. A locked store and an unsafe directory are
    not an absent key."""
    try:
        status = _resolver(root or ROOT).credentials_status()
    except Exception:  # a resolver that does not run here: the store's answer alone
        status = {"state": "absent"}
    if status["state"] == "unsafe":
        return f"the credentials directory is unsafe, so no secret is read from it: {status['detail']}"
    return locked_sentence(root, store=store, fresh=fresh)


def forget() -> None:
    """Drop the kept answers (a test, or after the person unlocks the store)."""
    _CACHE.clear()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0
    answer = probe(fresh=True)
    print(f"{answer['state']}: {answer['detail']}")
    return 0 if answer["state"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
