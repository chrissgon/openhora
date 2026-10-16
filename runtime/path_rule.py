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
  other      anything else, the runtime's own configuration (docs/workbench/runtime.json), the project's flows
             (docs/workbench/flows/, P6a) and the person's standing instructions (docs/workbench/instructions.md,
             limit L40) included. Not returned, and listed for the person

Usage (a library):
  python3 runtime/path_rule.py --help
  python3 runtime/path_rule.py <relative path>...    print the class of each path, as JSON

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import sys
import unicodedata

STATE = "docs/workbench/state.md"
CONFIG = "docs/workbench/runtime.json"
FLOWS_DIR = "docs/workbench/flows"   # the project's flows (runtime/flow_files.py): only the person and the operations write there
INSTRUCTIONS = "docs/workbench/instructions.md"   # the person's standing instructions (runtime/instructions.py, limit L40): only the person writes it
CLASSES = ("state", "machine", "document", "versioned", "ignored", "other")
# The classes that come back as loose files. "versioned" comes back too since stage 4, but only as a change set
# (runtime/changeset.py), never as a loose file, so it is not listed here.
RETURNED = ("state", "machine", "document")
DROPPED_DIRS = (".git", "node_modules", "__pycache__", ".pytest_cache", ".venv")
LOCAL_DIR = ".workbench-local/"
DROP_DIR = ".workbench-local/drop"  # the file drop (runtime/drop.py): staged for every run, so never brought back
SOURCES_DIR = ".workbench-local/sources"  # the copies of the sources a task receives (runtime/sources.py task_copies): staged, so never brought back
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


def fold(path: str) -> str:
    """The form in which two spellings of one path compare equal on the disks a person may use: Unicode case folding and
    compatibility forms, twice (a fold can make a new compatible form). APFS and NTFS open `inſtructions.md` (U+017F),
    `inﬆructions.md` (U+FB06) and `Instructions.md` as the file `instructions.md`, so a compare with `str.lower()` is not enough:
    the protected paths (the configuration, the person's instructions, the flows folder) are compared in this form."""
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", path).casefold())


def protected(rel: str) -> bool:
    """Whether a project-relative path, in whatever spelling, is a protected path of this module or lies under one: the configuration, the
    person's instructions (a name that is a folder there is also theirs), or the flows folder or anything in it."""
    folded = fold(rel)
    return folded in (CONFIG, INSTRUCTIONS, FLOWS_DIR) or folded.startswith((FLOWS_DIR + "/", CONFIG + "/", INSTRUCTIONS + "/"))


def classify(rel: str, facts: dict | None = None) -> str:
    """The class of one path (see the module's text). facts is optional: {"staged": [paths the runtime put in
    the copy], "bound": [documents bound to an approval], "versioned": [paths the project's git tracks or would
    track]}; a key that is missing is an empty list. The first rule that matches decides."""
    facts = facts or {}
    path = normal(rel)
    folded = fold(path) if path is not None else None   # a case-insensitive disk lands docs/workbench/Flows (or a Unicode fold of it) in the same folder: the compare folds
    if path is None or folded in (CONFIG, INSTRUCTIONS) or folded == FLOWS_DIR or folded.startswith((FLOWS_DIR + "/", CONFIG + "/", INSTRUCTIONS + "/")):
        return "other"   # the configuration, the project's flows and the person's instructions: what a run would change to change what runs next
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
