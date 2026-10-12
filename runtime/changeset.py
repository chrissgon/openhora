#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The change set: how code a run changed comes back (limit L9), and why a working document never enters a
commit (limit L11).

A versioned file (one the project's git tracks, or a new one its ignore rules would not keep out) never comes
back as a loose file: what a run did to versioned files is kept as one change set, in its run folder, until code
commits it through the code provider (runtime/effects.py). The change set is the difference between the copy's
base commit and its working tree, taken by git in the run's container with no network and a scratch index, under
the copy's own ignore rules, whatever the run did to its own index and history. The host then classifies every
path with the path rule, checks it, reads and hashes every file itself: it never runs git in a copy a run touched.

A path is refused, and the whole change set blocked, when it is not a regular file inside the copy (L8), is a path
the code provider does not take, is over the provider's size limit, holds a credential format (L14), carries a
tool's settings (L4) or matches a protected path of the project (protected_paths of its configuration, the list the
person accepted by its hash; matches()). A protected path still enters a copy: only the way back is closed. A
blocked change set is stored so the person can read it, and is never applied to a later task and never committed.

<run_dir>/changeset/changeset.json holds the change set, and <run_dir>/changeset/files/<path> each created or
changed file's bytes. Its "sha256" is the hash of the canonical form of its files and removed paths.

Public names: ChangesetError, LIMITS, SCRIPT, AS_BRANCH, compute, store, load, current, apply, as_branch, verify_for_commit,
versioned_in, provider_takes, canonical_sha256, matches.

Usage (a library): python3 runtime/changeset.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import path_rule  # noqa: E402  (the same folder)

# The code provider's bounds (providers/vcs/github.py, MAX_FILES and MAX_FILE_BYTES), repeated so that a change set
# the provider would refuse is blocked when it is made; a test keeps them equal.
LIMITS = {"paths": 50, "file_bytes": 5242880}
# A part of a path the code provider takes (its PATH_SEGMENT_RE), and the longest path it takes (PATH_MAX_CHARS).
PART = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]*$")
PATH_MAX = 1024
MODES = {"100644": False, "100755": True}
FOLDER = "changeset"
JSON_FILE = "changeset.json"
INDEX = "changeset.index"  # the scratch index, in the run folder, beside cwd/
GIT_TIMEOUT = 300
# The difference of a copy from its base commit: a scratch index built from the base commit, the whole working tree
# staged into it under the copy's ignore rules, and one raw record per path that differs. $1 is the base commit, $2
# the scratch index relative to the working folder; hooks and the file monitor are off, replaced objects ignored.
SCRIPT = """set -eu
export GIT_INDEX_FILE="$PWD/$2"
git --no-replace-objects -c core.hooksPath=/dev/null -c core.fsmonitor=false read-tree "$1"
git --no-replace-objects -c core.hooksPath=/dev/null -c core.fsmonitor=false add -A .
git --no-replace-objects -c core.hooksPath=/dev/null -c core.fsmonitor=false diff --cached --raw -z --no-renames --no-abbrev "$1" --
"""
COMMIT = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
# The form a pull-request skill was measured in: its branch with one commit on top of the base, and no remote. $1 the
# base branch's name, $2 the head's, $3 the commit message, then the change set's paths. Unsigned and without hooks:
# this commit stays in the copy; the one that is pushed is made by the code provider (runtime/effects.py).
AS_BRANCH = """set -eu
base="$1"; head="$2"; message="$3"; shift 3
git -c core.hooksPath=/dev/null branch -m "$base"
git -c core.hooksPath=/dev/null checkout -q -b "$head"
git -c core.hooksPath=/dev/null add -A -- "$@"
git -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -q --no-verify -m "$message"
"""
BRANCH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


class ChangesetError(Exception):
    """kind is "git" (no change set could be computed), "tampered" (a stored file is not what was stored),
    "working-document" (a path is not a versioned path of the project), "blocked" (a blocked change set is never
    committed) or "protected" (a path matches a protected path)."""

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind, self.reason = kind, reason


def _run():
    import lab  # noqa: E402  (only when a command runs)
    return lab.run_command


def matches(path: str, globs) -> bool:
    """True when an entry of the project's protected_paths covers path: fnmatch.fnmatchcase of the whole relative
    path (so `*` crosses `/`), or an entry that ends in `/` and starts the path. Case-sensitive. It protects too much
    rather than too little; the list is the project's, and no default is written here."""
    for glob in globs or ():
        if fnmatch.fnmatchcase(path, glob) or (glob.endswith("/") and path.startswith(glob)):
            return True
    return False


def provider_takes(path: str) -> bool:
    """True when the code provider takes the path: relative, every part letters, digits, '_', '.' or '-' (not
    starting with '-'), no '.', '..' or '.git' part."""
    return bool(path) and len(path) <= PATH_MAX and all(
        part not in (".", "..") and part.lower() != ".git" and PART.fullmatch(part) for part in path.split("/"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(files, removed) -> str:
    """The hash of a change set: of its files as [path, sha256, executable] and its removed paths, both sorted."""
    form = {"files": sorted([f["path"], f["sha256"], bool(f["executable"])] for f in files), "removed": sorted(removed)}
    return _sha(json.dumps(form, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _records(raw: bytes) -> list:
    """The raw records of `git diff --raw -z`: [(old mode, new mode, old blob, new blob, status, path)]. Raises ChangesetError("git") on
    output this parser does not know."""
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    if len(parts) % 2:
        raise ChangesetError("git", "the difference has a record without a path")
    out = []
    for meta, path in zip(parts[0::2], parts[1::2]):
        fields = meta.decode("ascii", "replace").lstrip(":").split(" ")
        if len(fields) != 5 or not fields[4]:
            raise ChangesetError("git", f"the difference has a record git did not print in its raw form: {fields!r}")
        try:
            name = path.decode("utf-8")
        except UnicodeDecodeError:
            name = path.decode("utf-8", "replace")
        out.append((fields[0], fields[1], fields[2], fields[3], fields[4][0], name))
    return out


def compute(run_dir: str, base_commit, tracked, facts, checks, protected=(), run=None) -> dict:
    """The change set a run left: the difference between the copy's base commit and its working tree
    (<run_dir>/cwd), each path classified (path_rule.classify) and checked. Not stored. tracked lists the relative
    paths of the project's git that entered the copy; facts is the path rule's facts ("staged", "bound"), to which
    "versioned" is added here: tracked plus every path the difference reports as added. checks is {"readable",
    "scan", "settings"}: lab.readable(cwd, rel), the credential scan workcopy.scan(data) (a reason or None) and
    lab.carries_settings(rel). protected is the project's protected_paths, as accepted: a created, changed or removed
    path that matches one is refused. run defaults to lab.run_command.

    Returns {"base_commit", "files": [{"path", "change", "sha256", "bytes", "executable"}], "removed", "refused":
    [{"path", "reason"}], "blocked", "sha256", "versioned"}; "versioned" lists every path of the difference that
    is versioned (in the change set or refused), so that what comes back as loose files leaves them out. Raises
    ChangesetError("git") when the difference cannot be taken."""
    if not isinstance(base_commit, str) or not COMMIT.fullmatch(base_commit):
        raise ChangesetError("git", "the copy has no base commit that could be read")
    cwd = os.path.join(run_dir, "cwd")
    if not os.path.isdir(os.path.join(cwd, ".git")) or os.path.islink(os.path.join(cwd, ".git")):
        raise ChangesetError("git", "the copy has no repository of its own")
    index = os.path.join(run_dir, INDEX)
    if os.path.lexists(index):
        os.unlink(index)
    # security-scan: allow shell-string -- SCRIPT is a constant of this module, run in the run's container with no network; its arguments are a checked commit id and a fixed file name
    done = (run or _run())(["bash", "-c", SCRIPT, "changeset", base_commit, os.path.join("..", INDEX)], run_dir,
                           cwd=cwd, network="none", timeout=GIT_TIMEOUT)
    if os.path.lexists(index):
        os.unlink(index)
    if done.get("timed_out") or done.get("returncode") != 0:
        first = ((done.get("stderr") or "").strip().splitlines() or ["timed out" if done.get("timed_out") else "no error"])[0]
        raise ChangesetError("git", f"git could not take the difference: {first}")
    raw = done.get("stdout") or ""
    records = _records(raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else raw)
    added = [r[5] for r in records if r[4] == "A"]
    facts = dict(facts or {}, versioned=sorted(set(tracked or ()) | set(added)))
    files, removed, refused, versioned = [], [], [], []
    for old_mode, new_mode, old_blob, new_blob, status, path in sorted(records, key=lambda r: r[5]):
        if path_rule.classify(path, facts) != "versioned":
            continue  # state, document, machine come back as before; ignored and other stay out
        versioned.append(path)
        reason = None
        gone = status == "D"
        data = None
        if not provider_takes(path):
            reason = "a path the code provider does not take"
        elif not gone and (new_mode not in MODES or not checks["readable"](cwd, path)):
            reason = "not a regular file inside the copy"
        elif checks["settings"](path):
            reason = "a tool's settings"
        elif matches(path, protected):
            reason = "protected path"
        if reason is None and not gone:
            size = os.path.getsize(os.path.join(cwd, *path.split("/")))
            if size > LIMITS["file_bytes"]:
                reason = "over the code provider's size limit"
            else:
                with open(os.path.join(cwd, *path.split("/")), "rb") as f:
                    data = f.read(LIMITS["file_bytes"] + 1)
                if checks["scan"](data):
                    reason = "credential format"
        if reason is not None:
            refused.append({"path": path, "reason": reason})
        elif gone:
            removed.append(path)
        else:
            change = "created" if status == "A" else ("mode" if old_blob == new_blob and old_mode != new_mode else "changed")
            files.append({"path": path, "change": change, "sha256": _sha(data), "bytes": len(data),
                          "executable": MODES[new_mode]})
    if len(files) + len(removed) > LIMITS["paths"]:
        refused.append({"path": "", "reason": "more paths than one commit of the code provider takes"})
    return {"base_commit": base_commit, "files": files, "removed": sorted(removed), "refused": refused,
            "blocked": bool(refused), "sha256": canonical_sha256(files, removed), "versioned": versioned}


def store(run_dir: str, changeset: dict) -> str:
    """Write <run_dir>/changeset/changeset.json and copy each file's bytes from <run_dir>/cwd into
    <run_dir>/changeset/files/<path>, checking each copy's hash. Returns the path of the JSON file."""
    folder = os.path.join(run_dir, FOLDER)
    if os.path.lexists(folder):
        shutil.rmtree(folder) if os.path.isdir(folder) and not os.path.islink(folder) else os.unlink(folder)
    os.makedirs(os.path.join(folder, "files"), mode=0o700)
    for item in changeset["files"]:
        source = os.path.join(run_dir, "cwd", *item["path"].split("/"))
        target = os.path.join(folder, "files", *item["path"].split("/"))
        with open(source, "rb") as f:
            data = f.read(LIMITS["file_bytes"] + 1)
        if _sha(data) != item["sha256"]:
            raise ChangesetError("tampered", f"{item['path']} changed in the run folder after the change set was made")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
    path = os.path.join(folder, JSON_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(changeset, f, indent=1, sort_keys=True, ensure_ascii=True)
        f.write("\n")
    return path


def load(run_dir: str):
    """The change set stored in a run folder, with "dir" (its folder) added, after hashing every stored file again
    and the change set's own hash: ChangesetError("tampered") when one differs. None when the run has none."""
    folder = os.path.join(run_dir, FOLDER)
    path = os.path.join(folder, JSON_FILE)
    if not os.path.isfile(path) or os.path.islink(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            changeset = json.load(f)
    except (OSError, ValueError) as e:
        raise ChangesetError("tampered", f"{path} cannot be read: {e}") from None
    if canonical_sha256(changeset.get("files") or [], changeset.get("removed") or []) != changeset.get("sha256"):
        raise ChangesetError("tampered", f"{path}: its files and removed paths do not have the hash it states")
    for item in changeset["files"]:
        stored = os.path.join(folder, "files", *item["path"].split("/"))
        if os.path.islink(stored) or not os.path.isfile(stored):
            raise ChangesetError("tampered", f"the stored file {item['path']} is missing")
        with open(stored, "rb") as f:
            if _sha(f.read()) != item["sha256"]:
                raise ChangesetError("tampered", f"the stored file {item['path']} is not the one the change set hashed")
    return {**changeset, "dir": folder}


def current(run_dirs):
    """The newest unblocked change set among run folders given newest first, or None."""
    for run_dir in run_dirs:
        found = load(run_dir)
        if found is not None and not found.get("blocked"):
            return found
    return None


def _inside(copy_dir: str, rel: str) -> str:
    """The absolute path of rel in the copy, refused when a part of the way is a link or it leaves the copy."""
    parts = rel.split("/")
    for i in range(1, len(parts)):
        if os.path.islink(os.path.join(copy_dir, *parts[:i])):
            raise ChangesetError("tampered", f"{rel} goes through a link in the copy")
    target = os.path.join(copy_dir, *parts)
    if not os.path.realpath(os.path.dirname(target)).startswith(os.path.realpath(copy_dir)):
        raise ChangesetError("tampered", f"{rel} leaves the copy")
    return target


def apply(changeset: dict, copy_dir: str) -> None:
    """Write the change set's files, remove its removed paths and set the executable bits, in a fresh copy (one
    made for this run, after its base commit). The earlier work is then an uncommitted change of the copy."""
    for rel in changeset.get("removed") or []:
        target = _inside(copy_dir, rel)
        if os.path.islink(target) or os.path.isfile(target):
            os.unlink(target)
    for item in changeset.get("files") or []:
        target = _inside(copy_dir, item["path"])
        if os.path.islink(target) or os.path.isdir(target):
            raise ChangesetError("tampered", f"{item['path']} is a link or a folder in the copy")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(changeset["dir"], "files", *item["path"].split("/")), target)
        os.chmod(target, 0o755 if item["executable"] else 0o644)


def as_branch(changeset: dict, copy_dir: str, root: str, base: str, head: str, message: str, run=None) -> None:
    """In a fresh copy: write the change set as apply() does, then, with git in the run's container and no network
    (AS_BRANCH, through run, default lab.run_command): name the copy's branch base, make the branch head and commit
    exactly the change set's paths on it. Raises ChangesetError("git")."""
    for name in (base, head):
        if not BRANCH.fullmatch(name or "") or ".." in name:
            raise ChangesetError("git", f"{name!r} is not a branch name")
    paths = [f["path"] for f in changeset.get("files") or []] + list(changeset.get("removed") or [])
    if not paths:
        raise ChangesetError("git", "the change set holds no path to commit")
    apply(changeset, copy_dir)
    # security-scan: allow shell-string -- AS_BRANCH is a constant of this module, run in the run's container with no network; its arguments are checked branch names, the request's title and the change set's checked paths
    done = (run or _run())(["bash", "-c", AS_BRANCH, "as-branch", base, head, message or "change", *paths], root,
                           cwd=copy_dir, network="none", timeout=GIT_TIMEOUT)
    if done.get("timed_out") or done.get("returncode") != 0:
        first = ((done.get("stderr") or "").strip().splitlines() or ["timed out"])[0]
        raise ChangesetError("git", f"the change could not be committed in the copy: {first}")


def versioned_in(project: str, paths) -> list:
    """The paths of `paths` that the project's git tracks now, or would add (new and not ignored by its rules):
    what path_rule.classify gets as facts["versioned"] when a change set is checked before its commit. Runs git
    on the host, in the project (the person's own repository), never in a copy."""
    paths = sorted(set(paths))
    if not paths:
        return []
    tracked = subprocess.run(["git", "-C", project, "ls-files", "-z", "--", *paths], capture_output=True, timeout=120)
    if tracked.returncode != 0:
        raise ChangesetError("git", f"git ls-files failed in the project: {tracked.stderr.decode('utf-8', 'replace').strip()}")
    known = {p for p in tracked.stdout.decode("utf-8", "surrogateescape").split("\0") if p}
    rest = [p for p in paths if p not in known]
    ignored = set()
    if rest:
        found = subprocess.run(["git", "-C", project, "check-ignore", "-z", "--stdin"], input="\0".join(rest).encode() + b"\0",
                               capture_output=True, timeout=120)
        if found.returncode not in (0, 1):
            raise ChangesetError("git", f"git check-ignore failed in the project: {found.stderr.decode('utf-8', 'replace').strip()}")
        ignored = {p for p in found.stdout.decode("utf-8", "surrogateescape").split("\0") if p}
    return sorted(known | (set(rest) - ignored))


def verify_for_commit(changeset: dict, facts: dict, protected) -> None:
    """The last check before a commit: every file and removed path still classifies as `versioned` with facts (the
    project's versioned paths now, versioned_in()) and matches no protected path of the list accepted now (a list
    widened after the run still holds), and the change set is not blocked. Raises ChangesetError("working-document"),
    ChangesetError("protected") or ChangesetError("blocked")."""
    if changeset.get("blocked"):
        raise ChangesetError("blocked", "the change set is blocked: it is never committed")
    for rel in [f["path"] for f in changeset.get("files") or []] + list(changeset.get("removed") or []):
        if path_rule.classify(rel, facts) != "versioned":
            raise ChangesetError("working-document", f"{rel} is not a versioned path of the project: it never enters a commit")
        if matches(rel, protected):
            raise ChangesetError("protected", f"{rel} matches a protected path of the project")


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
