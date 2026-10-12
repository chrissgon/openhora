#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of a commit of files to a branch, made by the code provider under a standing approval.

It is the policy-path kind registered under the side-effect word `push` (runtime/effects.py KINDS): a handler writes
an effect document of that kind and hands it to ops.execute_under_policy, which checks the standing approval and runs
the code provider's commit-files. This module answers what the operation asks of a kind (the names are listed at the
head of runtime/effects.py): that it may run under a policy, the class of provider, the platform to resolve it with
(none: the code provider takes the configuration's), the effect the approval is checked against, the verb and its
arguments, and the line that says what was done.

No skill's confirmation gate names this word, so the gate path never opens an effect of this kind and this module has
no function of that path (parse, verify, execute and the others); only describe is shared, since the state file's row
is made from it.

Usage (a library): python3 runtime/effect_commit.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import sys

PROVIDER_CLASS = "integration:vcs"
GATE = False  # no skill's confirmation gate names this word: the gate path never opens an effect of this kind
POLICY = True
VERB = "commit-files"  # the code provider's verb that commits files to a branch


def policy_platform(doc: dict):
    """The platform the provider is resolved with: none, the code provider is the configuration's."""
    return None


def policy_effect(doc: dict) -> dict:
    """What the standing approval is checked against (autonomy.covers): the four fields of the document."""
    return {"kind": doc["kind"], "target": doc["target"], "files": doc["files"], "items": doc["items"]}


def policy_argv(doc: dict) -> list:
    """The provider's verb and the document's own arguments, without the flags the operation adds."""
    return [VERB, *doc["args"]]


def describe(doc: dict) -> str:
    """What is done, in one line."""
    return f"commit {doc['items']} files to {doc['target']}"


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
