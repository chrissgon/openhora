#!/usr/bin/env python3
"""Verify the community evidence files a pull request adds, with no model call (decision D19, hardened by S5).

Usage:
  python3 verify_community.py --root <checkout> --official-repo <owner/name> (--base <sha> | --all | --files <path>...)
                              [--code-root <folder>] [--main-ref origin/main]

A contributor's lab test, run by the official reusable workflow in their fork, leaves three files in a skill's evidence
folder: community-<repository id>-<run id>-<attempt>.jsonl (the evidence), .manifest.json (what the run was) and
.sigstore.json (the attestation bundle). For each evidence file this script checks, in this order, and stops at the first
failure of a file:
  1. the shape: the file's name, manifest and bundle agree, the lines pass the evidence validators read strictly (a
     listed model with a route, its entry's adapter, the configured number of runs, the published image), and the
     skill's version file gives the event's content hash for its version (eval_status.py community_file_problems);
  2. the commit of the manifest is in the history of main (git merge-base --is-ancestor <commit> <main ref>): the
     official workflow that signed is a reviewed one; and, when the BASE commit's evals/community.json names a
     "min_signing_commit", the signing commit is on main's first-parent line at that commit or after it (a workflow
     found faulty is retired by raising the minimum, and evidence signed by an older one is refused);
  3. the attestation of the evidence file and of the manifest, against the one bundle, with the GitHub CLI:
       gh attestation verify <file> --bundle <bundle> --repo <the fork the manifest names>
         --cert-identity https://github.com/<official repo>/.github/workflows/community-eval.yml@<commit>
         --signer-digest <commit> --deny-self-hosted-runners
     so the signer is the official workflow at exactly that commit (the signer digest is the commit the workflow checked
     the official code out at), the run was on a GitHub-hosted runner, the source repository is the fork, and the
     digest of each file is a subject of the bundle (the evidence file's digest equals the manifest's evidence_sha256, which
     step 1 checked, and the manifest is attested with it). The manifest carries "run_runner_group" (the attestation job read
     the run's jobs through the API and required GitHub's own runner group); step 1 refuses a manifest without it.
A file added by the change must be new: a community file that exists at the base with other bytes, or is deleted or renamed,
is refused (committed evidence is never edited).

Gaps. The run number of a workflow counts up from 1 in the fork. Among all the manifests of the checkout, a run number
between 1 and the highest one of a fork's workflow that no file carries is a run that was not submitted, and so is an attempt
between 1 and the highest one submitted of a run (best-of-several by re-run); a fork that used a caller workflow other than
the one file the guide names is flagged too. The script prints a warning for each such fork and workflow that the change
touches, and the status shows the count as "gaps". A gap is flagged and never refused: a run that failed before writing
evidence leaves one too.

The gate file and the version files that the strict reading uses come from --ref-root (the base commit's tree in a pull
request's check, default --code-root), not from the pull request.

The checkout is data: the evidence files are read and never run, and the code that reads them (this script and the evidence
validators it loads) comes from --code-root, which a pull request's check points at the BASE commit, so that a change
cannot weaken its own check. With --files and --all the code root defaults to the checkout this script is in.
Needs the GitHub CLI (gh) and git; it makes no other network call, reads no credential and prints no secret.

Prints a JSON summary on stdout, the reasons on stderr. Exit codes: 0 every file verified (gaps are warnings), 1 a file
refused, 2 usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = ".github/workflows/community-eval.yml"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
TIMEOUT = 180
PATH_RE = re.compile(r"skills/([a-z0-9]+(?:-[a-z0-9]+)*)/evals/evidence/(community-[0-9]+-[0-9]+-[0-9]+)(\.jsonl|\.manifest\.json|\.sigstore\.json)")


def run_gh(argv):
    """(exit code, stdout, stderr) of a GitHub CLI call. One of the two functions a test replaces."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", f"gh did not run: {e}"
    return r.returncode, r.stdout, r.stderr


def run_git(root, args):
    """(exit code, stdout) of a git call in `root`. The other function a test replaces."""
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return r.returncode, r.stdout


def verify_argv(path, bundle, official, commit, fork):
    """The command that verifies `path` against `bundle`: the one place the flags that bind the signer are written."""
    return ["gh", "attestation", "verify", path, "--bundle", bundle, "--repo", fork,
            "--cert-identity", f"https://github.com/{official}/{WORKFLOW}@{commit}",
            "--cert-oidc-issuer", OIDC_ISSUER, "--signer-digest", commit, "--deny-self-hosted-runners"]


def verify_attestation(path, bundle, official, commit, fork, gh=None):
    """None when `path` is attested in `bundle` by the official workflow at `commit` on a GitHub-hosted runner, in the fork
    `fork`; else why not."""
    code, out, err = (gh or run_gh)(verify_argv(path, bundle, official, commit, fork))
    if code != 0:
        return f"no valid attestation for {os.path.basename(path)} (gh exit {code}): {(err or out).strip()[:300]}"
    return None


def in_history(root, commit, main_ref, git=None):
    """None when `commit` is an ancestor of (or is) `main_ref`, else why not."""
    code, _ = (git or run_git)(root, ["merge-base", "--is-ancestor", commit, main_ref])
    if code == 0:
        return None
    if code == 1:
        return f"the commit {commit} is not in the history of {main_ref}: only a workflow that was reviewed and merged signs evidence"
    return f"the commit {commit} cannot be checked against {main_ref} (git exit {code}): fetch main with its history"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_status(code_root):
    path = os.path.join(code_root, "evals", "eval_status.py")
    if not os.path.isfile(path):
        raise SystemExit(f"verify_community: {path} is missing: --code-root must be a checkout of the workbench")
    status = load(path, "workbench_verify_community_status")
    if not hasattr(status, "community_file_problems"):
        raise SystemExit("verify_community: the evidence validators of --code-root know no community evidence yet")
    return status


def changed_files(root, base, git):
    """({path: status letter}) of the community files the change adds, edits, deletes or renames against `base`."""
    code, out = git(root, ["diff", "--name-status", "--no-renames", base, "HEAD", "--", "skills/*/evals/evidence/community-*"])
    if code != 0:
        raise SystemExit(f"verify_community: git diff {base} HEAD failed (exit {code}): fetch the base commit")
    found = {}
    for line in out.splitlines():
        letter, _, path = line.partition("\t")
        if path:
            found[path] = letter
    return found


def first_parent_problem(root, commit, main_ref, minimum, git=None):
    """None when `commit` is on the first-parent line of `main_ref` at `minimum` or after it, else why not. No minimum, no
    rule. The first-parent line is the sequence of merges into main: a commit of a side branch is not on it."""
    if minimum is None:
        return None
    code, out = (git or run_git)(root, ["rev-list", "--first-parent", main_ref])
    if code != 0:
        return f"the first-parent line of {main_ref} cannot be listed (git exit {code}): fetch main with its history"
    line = out.split()
    if minimum not in line:
        return f"the minimum signing commit {minimum} is not on the first-parent line of {main_ref}"
    if commit not in line:
        return f"the commit {commit} is not on the first-parent line of {main_ref}, where the minimum signing commit is"
    if line.index(commit) > line.index(minimum):  # newest first: a larger index is older
        return f"the commit {commit} is older than the minimum signing commit {minimum}: the workflow that signed it was retired"
    return None


def read_minimum(code_root):
    """(the minimum signing commit or None, why the file cannot be used or None) from <code_root>/evals/community.json."""
    path = os.path.join(code_root, "evals", "community.json")
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, f"{path} cannot be read: {e}"
    ok = isinstance(data, dict) and set(data) == {"min_signing_commit"} and (
        data["min_signing_commit"] is None or (isinstance(data["min_signing_commit"], str)
                                              and re.fullmatch(r"[0-9a-f]{40}", data["min_signing_commit"])))
    if not ok:
        return None, f"{path} must be an object with the one key min_signing_commit: null or 40 hexadecimal characters"
    return data["min_signing_commit"], None


def verify_file(root, rel, official, main_ref, status, gh=None, git=None, strict=True, ref_root=None, minimum=None):
    """[problems] of one community evidence file (a path relative to root): empty when it passes the three checks. strict
    reads a new file against the current gate file; a file already merged is read by its own event line."""
    m = PATH_RE.fullmatch(rel)
    if not m or m.group(3) != ".jsonl":
        return [f"{rel} is not a community evidence file"]
    skill, stem = m.group(1), m.group(2)
    path = os.path.join(root, rel)
    problems = status.community_file_problems(path, root, skill, strict=strict, ref_root=ref_root)
    if problems:
        return problems
    manifest_path = os.path.join(root, os.path.dirname(rel), stem + ".manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    why = in_history(root, manifest["commit"], main_ref, git) or first_parent_problem(root, manifest["commit"], main_ref, minimum, git)
    if why:
        return [why]
    bundle = os.path.join(root, os.path.dirname(rel), stem + ".sigstore.json")
    for target in (path, manifest_path):
        why = verify_attestation(target, bundle, official, manifest["commit"], manifest["repository"], gh)
        if why:
            return [why]
    return []


def run(root, official, main_ref, files, status, base=None, gh=None, git=None, out=None, err=None, strict=True, ref_root=None,
        minimum=None):
    """Verify the files (paths relative to root, or the change against `base` when `files` is None); (exit code, summary)."""
    out, err = out or sys.stdout, err or sys.stderr
    git = git or run_git
    listed = {p: "A" for p in files} if files is not None else changed_files(root, base, git)
    refused, verified, checked = {}, [], []
    for rel, letter in sorted(listed.items()):
        if letter != "A":
            refused[rel] = [f"a community file is never edited, deleted or renamed once committed (git status {letter})"]
        elif not PATH_RE.fullmatch(rel):
            refused[rel] = ["the name must be community-<repository id>-<run id>-<run attempt>.jsonl, .manifest.json or .sigstore.json"]
        elif rel.endswith(".jsonl"):
            checked.append(rel)
    for rel in checked:
        problems = verify_file(root, rel, official, main_ref, status, gh, git, strict, ref_root, minimum)
        if problems:
            refused[rel] = problems
        else:
            verified.append(rel)
    touched, names = set(), {}
    for rel in verified:
        manifest = status.community_manifest_of(os.path.join(root, rel))
        if manifest:
            touched.add((manifest["repository_id"], manifest["workflow"]))
            names[manifest["repository_id"]] = manifest["repository"]
    manifests = [m for _, m in status.community_manifests(root)]
    gaps = {k: v for k, v in status.community_gaps(manifests).items() if k in touched}
    attempts = {k: v for k, v in status.community_attempt_gaps(manifests).items() if k[:2] in touched}
    others = {k: v for k, v in status.community_other_callers(manifests).items() if k in touched}
    who = lambda repository_id: names.get(repository_id, repository_id)
    for (repository_id, workflow), missing in gaps.items():
        shown = ", ".join(f"#{n}" for n in missing[:20]) + (" ..." if len(missing) > 20 else "")
        print(f"::warning::{who(repository_id)}: the runs of {workflow} numbered {shown} are not submitted: "
              "every completed run of the fork's workflow is to be submitted (a gap is flagged, not refused)", file=err)
    for (repository_id, workflow, run_id), missing in attempts.items():
        print(f"::warning::{who(repository_id)}: run {run_id} of {workflow} was submitted without its attempt(s) "
              f"{', '.join(str(n) for n in missing)}: every attempt below the highest one submitted is to be submitted too "
              "(a gap is flagged, not refused)", file=err)
    for (repository_id, workflow) in others:
        print(f"::warning::{who(repository_id)}: the caller workflow is {workflow}, not the one file the guide names "
              "(its run numbers count apart); flagged, not refused", file=err)
    for rel, problems in refused.items():
        for p in problems:
            print(f"::error file={rel}::{p}", file=err)
    summary = {"verified": verified, "refused": refused,
               "gaps": [{"repository": who(k[0]), "workflow": k[1], "missing": v} for k, v in gaps.items()],
               "attempt_gaps": [{"repository": who(k[0]), "workflow": k[1], "run_id": k[2], "missing": v} for k, v in attempts.items()],
               "other_callers": [{"repository": who(k[0]), "workflow": k[1]} for k in others]}
    print(json.dumps(summary, indent=2), file=out)
    return (1 if refused else 0), summary


def main(argv):
    parser = argparse.ArgumentParser(prog="verify_community.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="the checkout that holds the evidence files (data)")
    parser.add_argument("--official-repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/name of the official repository")
    parser.add_argument("--code-root", default=os.path.dirname(HERE), help="the checkout whose evidence validators are loaded")
    parser.add_argument("--ref-root", default=None, help="the tree the gate file and the version files are read from "
                        "(default --code-root: the base commit's, in a pull request's check)")
    parser.add_argument("--main-ref", default="origin/main", help="the ref whose history the signing commit must be in")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="verify the community files this change adds against that commit")
    group.add_argument("--all", action="store_true", help="verify every community file of the checkout")
    group.add_argument("--files", nargs="+", help="verify these evidence files (paths relative to the root)")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}", args.official_repo or ""):
        print("verify_community: --official-repo must be owner/name (or GITHUB_REPOSITORY set)", file=sys.stderr)
        return 2
    root = os.path.abspath(args.root)
    status = load_status(os.path.abspath(args.code_root))
    minimum, problem = read_minimum(os.path.abspath(args.code_root))
    if problem:
        print(f"verify_community: {problem}", file=sys.stderr)
        return 2
    files = None
    if args.all:
        files = [os.path.relpath(p, root).replace(os.sep, "/") for name in status.skill_names(root)
                 for p in status.community_files(os.path.join(root, "skills", name))]
    elif args.files:
        files = [f.replace(os.sep, "/") for f in args.files]
    code, _ = run(root, args.official_repo, args.main_ref, files, status, base=args.base, strict=not args.all,
                  ref_root=os.path.abspath(args.ref_root or args.code_root), minimum=minimum)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
