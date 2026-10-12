#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The path rule: how one path of what a run left goes back to the project. One function, no file access.

Every file a run created or changed is given exactly one class, by its path relative to the project root:

  state      docs/workbench/state.md: it goes back through the merge of runtime/state_merge.py, never as a file
  machine    a file no person edits: everything under .workbench-local/, every file under docs/ that is not
             Markdown (a lint record, a check report, a data file, an image), and a document bound to an
             approval by its hash (facts["bound"])
  document   a Markdown file under docs/: text a person reads and edits where the project keeps it
  versioned  a file the project's git tracks or would track (facts["versioned"]): it goes back as part of a
             change set, never as a loose file (stage 4 of the platform plan supplies the fact)
  ignored    what the runtime itself put in the copy or what no one reads back: the folder the skills were
             staged in (facts["staged"]), version control, dependency and cache folders. Dropped, not listed
  other      anything else, the runtime's own configuration (docs/workbench/runtime.json) included. Not
             returned, and listed for the person

Usage (a library):
  python3 runtime/path_rule.py --help
  python3 runtime/path_rule.py <relative path>...    print the class of each path, as JSON

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import sys

STATE = "docs/workbench/state.md"
CONFIG = "docs/workbench/runtime.json"
CLASSES = ("state", "machine", "document", "versioned", "ignored", "other")
# The classes that come back as loose files. "versioned" comes back too since stage 4, but only as a change set
# (runtime/changeset.py), never as a loose file, so it is not listed here.
RETURNED = ("state", "machine", "document")
DROPPED_DIRS = (".git", "node_modules", "__pycache__", ".pytest_cache", ".venv")
LOCAL_DIR = ".workbench-local/"
DROP_DIR = ".workbench-local/drop"  # the file drop (runtime/drop.py): staged for every run, so never brought back
DOCS_DIR = "docs/"
DOCUMENT_SUFFIXES = (".md",)


def normal(rel: str):
    """rel with "/" separators and no "./", or None when it is not a relative path inside the project."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "~")) or "\x00" in rel:
        return None
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def classify(rel: str, facts: dict | None = None) -> str:
    """The class of one path (see the module's text). facts is optional: {"staged": [paths the runtime put in
    the copy], "bound": [documents bound to an approval], "versioned": [paths the project's git tracks or would
    track]}; a key that is missing is an empty list. The first rule that matches decides."""
    facts = facts or {}
    path = normal(rel)
    if path is None or path == CONFIG:
        return "other"
    if path == STATE:
        return "state"
    under = lambda prefix: path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
    if any(part in DROPPED_DIRS for part in path.split("/")) or any(under(normal(s) or "\x00") for s in facts.get("staged") or ()):
        return "ignored"
    if path.startswith(LOCAL_DIR):
        return "machine"
    if path.startswith(DOCS_DIR):
        if path in (facts.get("bound") or ()):
            return "machine"
        if path in (facts.get("versioned") or ()):
            return "versioned"  # a docs/ folder the project versions (its Docs in git decision) travels in a change set
        return "document" if path.lower().endswith(DOCUMENT_SUFFIXES) else "machine"
    if path in (facts.get("versioned") or ()):
        return "versioned"
    return "other"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or any(a.startswith("-") for a in argv):
        print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
        return 0 if argv in (["--help"], ["-h"]) else 2
    print(json.dumps({rel: classify(rel) for rel in argv}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
