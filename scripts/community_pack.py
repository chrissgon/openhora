#!/usr/bin/env python3
"""The two steps of the community workflow (.github/workflows/community-eval.yml) that read the lab test's result: the
check of what was asked before a model runs, and the packing of the evidence file the test wrote.

Usage:
  python3 scripts/community_pack.py preflight --skill <name> --model <id> [--adapter <folder>] (--full | --cases <ids>)
                                              [--root <checkout>]
  python3 scripts/community_pack.py pack --skill <name> --model <id> --out <folder> --repository <owner/name>
                                         --repository-id <n> --run-id <n> --run-attempt <n> --run-number <n>
                                         --workflow-ref <ref> --commit <sha> [--root <checkout>] [--local-evidence <folder>]

preflight refuses, before anything runs, what the workflow must not run: a skill that is not in the checkout, a model
that the gate file (evals/eval-gate.json) does not list with a route (a model whose key a key proxy holds), an
adapter other than the one the model's entry names, a malformed case list, and a key variable that is not set. The
variables checked are the model's own (its entry's pass_env) and the grader's (the pass_env of the grader's own
entry in the gate file: every grading goes through it, whatever the model tested). Only the NAMES of a missing
variable are printed, never a value. It prints {"ok": true, ...} or a list of problems on stderr and exits 1.

pack finds the evidence file the lab test wrote (exactly one new lab-<test id>.jsonl: in the checkout's skill folder,
or in the local evidence folder, WB_LOCAL_EVIDENCE_DIR), checks it, and writes into --out the two files the
attestation will cover, named after the fork's run (community-<repository id>-<run id>-<run attempt>):
  .jsonl          the evidence file, its event line carrying the marker "source": "community" and nothing else changed;
  .manifest.json  {record, repository, repository_id, run_id, run_attempt, run_number, workflow, commit, skill, model,
                  evidence_sha256}: what the run was, with no free text. The attestation job adds "run_runner_group"
                  (it reads the run's jobs through the API) before it attests the file.
It checks that the file is complete, tests exactly the one model that was asked for (a second model beside it would be
not the one asked for), came from the published eval image and passes the evidence validators; it
checks that HEAD of the checkout is the commit it is given (the official workflow's own commit). It prints
{"name", "evidence_sha256", "manifest_sha256", "files"} and exits 0, or the problems on stderr and exits 1. The
values come in as flags that the workflow fills from the run's environment; nothing is read from the network and no model
is called. The attestation itself is made by another job, which holds no code of the checkout.

Exit codes: 0 ok, 1 refused, 2 usage error. Standard library only; runs on Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}(,[A-Za-z0-9][A-Za-z0-9._-]{0,63})*")
WORKFLOW_REF_RE = re.compile(r"[^/@\s]+/[^/@\s]+/(\.github/workflows/[A-Za-z0-9._-]+\.ya?ml)@\S+")


def load_lines():
    """evals/evidence_lines.py of this checkout, by path: the closed forms every evidence file is checked against."""
    spec = importlib.util.spec_from_file_location("workbench_community_pack_lines", os.path.join(ROOT, "evals", "evidence_lines.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_gate(root):
    try:
        with open(os.path.join(root, "evals", "eval-gate.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def model_entry(gate, name):
    """(listed id, its object-shaped entry) for a model id or alias of the gate file's "models", else (None, None)."""
    models = gate.get("models")
    if not isinstance(models, dict):
        return None, None
    for listed, entry in models.items():
        aliases = entry.get("aliases", []) if isinstance(entry, dict) else entry
        if name == listed or name in aliases:
            return listed, entry if isinstance(entry, dict) else None
    return None, None


def preflight_problems(root, skill, model, adapter, full, cases, env):
    """Why this request must not run; [] when it may. `env` is the environment the key variables are looked up in."""
    lines = load_lines()
    out = []
    if not lines.NAME_RE.fullmatch(skill or ""):
        out.append("skill must be a skill name (lowercase letters, digits and hyphens)")
    elif not os.path.isfile(os.path.join(root, "skills", skill, "SKILL.md")):
        out.append(f"{skill} is not a skill of the official repository at this commit")
    if not lines.MODEL_RE.fullmatch(model or ""):
        out.append("model must be a model id (letters, digits and . _ : / @ -)")
    if full == bool(cases):
        out.append("give exactly one of full (every case, a full test) or cases (the named cases, a partial test)")
    if cases and not CASES_RE.fullmatch(cases):
        out.append("cases must be case ids separated by commas")
    gate = read_gate(root)
    listed, entry = model_entry(gate, model)
    if not gate:
        out.append("evals/eval-gate.json cannot be read")
    elif listed is None or entry is None:
        out.append(f"{model} is not a model of the gate file: a pull request adds it first (a community run tests a listed model)")
    elif not entry.get("route"):
        out.append(f"{listed} has no route in the gate file: a model whose key no key proxy holds is not tested here")
    elif adapter and adapter != entry.get("adapter"):
        out.append(f"{listed} runs through the adapter {entry.get('adapter')}, not {adapter}")
    if entry and entry.get("route"):
        grader_entry = model_entry(gate, gate.get("grader"))[1] or {}
        names = list(entry.get("pass_env") or []) + [n for n in (grader_entry.get("pass_env") or []) if n not in (entry.get("pass_env") or [])]
        missing = [n for n in names if not env.get(n)]
        if missing:
            out.append("a key variable is not set (add it as a secret of the fork): " + ", ".join(missing))
    return out


def git_head(root):
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def tracked(root, rel):
    """The files git tracks under rel, or None when root is not a git checkout."""
    try:
        r = subprocess.run(["git", "-C", root, "ls-files", "--", rel], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return set(r.stdout.split("\n")) if r.returncode == 0 else None


def new_evidence(root, skill, local_base):
    """The lab evidence files the test wrote: untracked ones in the skill's evidence folder, and the ones in the local
    evidence folder of the skill."""
    lines = load_lines()
    found = []
    rel = os.path.join("skills", skill, "evals", "evidence")
    folder = os.path.join(root, rel)
    known = tracked(root, rel.replace(os.sep, "/"))
    for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if re.fullmatch(r"lab-" + lines.TEST_ID_RE.pattern + r"\.jsonl", n) and (known is None or f"{rel}/{n}" not in known):
            found.append(os.path.join(folder, n))
    local = os.path.join(local_base, skill) if local_base else None
    for n in sorted(os.listdir(local)) if local and os.path.isdir(local) else []:
        if re.fullmatch(r"lab-" + lines.TEST_ID_RE.pattern + r"\.jsonl", n):
            found.append(os.path.join(local, n))
    return found


def pack(root, skill, model, out, ids, workflow_ref, commit, local_base):
    """(result dict, []) after writing the two files into `out`, or (None, problems). `ids`: repository, repository_id,
    run_id, run_attempt, run_number."""
    lines = load_lines()
    problems = []
    head = git_head(root)
    if head is not None and head != commit:
        return None, [f"HEAD of the checkout ({head}) is not the commit of the official workflow ({commit}): the code that ran is "
                      "not the code that is attested"]
    gate = read_gate(root)
    listed, _ = model_entry(gate, model)
    if listed is None:
        return None, [f"{model} is not a model of the gate file"]
    found = new_evidence(root, skill, local_base)
    if len(found) != 1:
        return None, [f"expected exactly one new evidence file of {skill} from the lab test, found {len(found)}: the test wrote "
                      "none (a trial writes no evidence) or ran more than once"]
    with open(found[0], "rb") as f:
        raw = f.read().decode("utf-8")
    parts = raw.split("\n")
    event, runs, read = lines.read_evidence_file(found[0])
    if read or event is None:
        return None, [f"the evidence file cannot be read: {'; '.join(read)}"]
    problems += [f"line 1: {p}" for p in lines.event_line_problems(event)]
    if not problems:
        pairs = lines.event_model_pairs(event)
        if [m for m, _ in pairs] != [listed]:
            problems.append(f"the test must name exactly {listed}; it names {[m for m, _ in pairs]}")
        if event.get("complete") is not True:
            problems.append("the test is not complete: every run with the skill and every baseline run must be graded")
        if event.get("image_source") != "published":
            problems.append("the test did not run in the published eval image (image_source is not \"published\")")
        if event.get("skill") != skill:
            problems.append(f"the evidence is of {event.get('skill')}, not of {skill}")
        if "source" in event:
            problems.append("the event line already carries a source")
        for n, line in runs:
            problems += [f"line {n}: {p}" for p in lines.run_line_problems(line, event)]
    if problems:
        return None, problems
    marked = dict(event)
    marked["source"] = "community"
    text = json.dumps(marked, ensure_ascii=False) + "\n" + "\n".join(parts[1:])
    name = f"community-{ids['repository_id']}-{ids['run_id']}-{ids['run_attempt']}"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {"record": "community-manifest", "repository": ids["repository"], "repository_id": int(ids["repository_id"]),
                "run_id": int(ids["run_id"]), "run_attempt": int(ids["run_attempt"]), "run_number": int(ids["run_number"]),
                "workflow": workflow_ref, "commit": commit, "skill": skill, "model": listed, "evidence_sha256": sha}
    bad = lines.manifest_problems(manifest, partial=True)
    if bad:
        return None, [f"manifest: {p}" for p in bad]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, name + ".jsonl"), "w", encoding="utf-8", newline="") as f:
        f.write(text)
    body = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    with open(os.path.join(out, name + ".manifest.json"), "w", encoding="utf-8", newline="") as f:
        f.write(body)
    return {"name": name, "evidence_sha256": sha, "manifest_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "files": [name + ".jsonl", name + ".manifest.json"]}, []


def workflow_path(ref):
    m = WORKFLOW_REF_RE.fullmatch(ref or "")
    return m.group(1) if m else None


def main(argv, env=None):
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="community_pack.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "pack"):
        p = sub.add_parser(name)
        p.add_argument("--skill", required=True)
        p.add_argument("--model", required=True)
        p.add_argument("--root", default=ROOT)
    pre = sub.choices["preflight"]
    pre.add_argument("--adapter", default="")
    pre.add_argument("--full", action="store_true")
    pre.add_argument("--cases", default="")
    pk = sub.choices["pack"]
    pk.add_argument("--out", required=True)
    for key in ("repository", "repository-id", "run-id", "run-attempt", "run-number", "workflow-ref", "commit"):
        pk.add_argument("--" + key, required=True)
    pk.add_argument("--local-evidence", default=env.get("WB_LOCAL_EVIDENCE_DIR", ""))
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)
    if args.command == "preflight":
        problems = preflight_problems(root, args.skill, args.model, args.adapter, args.full, args.cases, env)
        if problems:
            for p in problems:
                print(f"community_pack: {p}", file=sys.stderr)
            return 1
        print(json.dumps({"ok": True, "skill": args.skill, "model": args.model, "full": args.full}))
        return 0
    path = workflow_path(args.workflow_ref)
    if path is None:
        print("community_pack: --workflow-ref must look like owner/name/.github/workflows/<file>.yml@<ref>", file=sys.stderr)
        return 1
    ids = {"repository": args.repository, "repository_id": args.repository_id, "run_id": args.run_id,
           "run_attempt": args.run_attempt, "run_number": args.run_number}
    if not all(re.fullmatch(r"[0-9]{1,20}", ids[k]) for k in ("repository_id", "run_id", "run_attempt", "run_number")):
        print("community_pack: the ids of the run must be whole numbers", file=sys.stderr)
        return 1
    result, problems = pack(root, args.skill, args.model, args.out, ids, path, args.commit, args.local_evidence or None)
    if problems:
        for p in problems:
            print(f"community_pack: {p}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
