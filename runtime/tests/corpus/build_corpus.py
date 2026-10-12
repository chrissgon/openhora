#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Build the corpus the classifier of endings is tested against, from an archive of lab runs.

Usage:
  python3 runtime/tests/corpus/build_corpus.py --archive <battery-runs.tar.gz> [--out <file>] [--root <workbench root>]

It reads, and never unpacks to disk, the archive of an eval workspace (evals-workspace/<skill>/iteration-<n>/
eval-<case>/<variant>[/run-<k>]/...) and writes one JSON line per run with the skill it kept, by default to
runtime/tests/corpus/endings.jsonl. It calls no model and writes nothing but that file.

Which runs are kept. Only runs with the skill (the folders with_skill and with_skill.floor), with a reply
(outputs/response.md) and the facts the runner measured (facts.md); never what an attempt that was made again
left (failed-<n>/, early-end-<n>/, paused-<n>/, before-resume-<n>/). Of those:
  - every run that created, changed and deleted no file (the runs that stopped: they asked, refused or found
    an input missing), and
  - of the runs that changed a file, the one with the lowest run number per skill, iteration, case and model tier.

One line: {"id": "<skill>/<iteration>/<case>/<tier>/<run>", "skill", "case", "tier": "strong" | "floor",
"response": the reply with every credential format masked (scripts/redact.py), "created", "modified",
"deleted": the paths facts.md lists, "stopped": true when the three lists are empty, "outputs_written": the
declared outputs of the skill (metadata.outputs of this checkout) among created and modified, "stop_reason":
from timing.json or null, "guards": [{"position": n, "passed": true | false}] for the assertions the case file
of this checkout tags guard or guard:<effect>, read by position from grading.json, or null when the case is
gone or its number of assertions changed, "pass_rate": the run's score or null}.
Lines are sorted by id and written with ASCII escapes, so the file is stable and holds no raw non-ASCII text.

It records facts, not verdicts: which ending each line must get is the classifier's test (stage 2 of the
platform plan). Prints {"runs_read", "lines", "stopped", "by_tier", "sha256"} as JSON.
Exit codes: 0 ok, 1 the archive cannot be read, 2 usage error. Standard library only.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
RUN = re.compile(r"^evals-workspace/(?P<skill>[a-z0-9-]+)/(?P<iteration>iteration-\d+)/eval-(?P<case>[A-Za-z0-9._-]+)/"
                 r"(?P<variant>with_skill(?:\.floor)?)/(?:run-(?P<run>\d+)/)?(?P<file>outputs/response\.md|facts\.md|"
                 r"timing\.json|grading\.json)$")
SECTIONS = ("created", "modified", "deleted")
PLACEHOLDER = re.compile(r"<[^<>/]*>")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def facts(text):
    """{"created", "modified", "deleted"} of a facts.md: the "- <path>" lines under each heading."""
    found, current = {name: [] for name in SECTIONS}, None
    for line in text.splitlines():
        head = line.strip().rstrip(":")
        if not line.startswith(("-", " ")) and line.strip().endswith(":") or line.startswith("version control"):
            current = head if head in SECTIONS else None
        elif current and line.startswith("- ") and line[2:].strip() != "(none)":
            found[current].append(line[2:].strip())
    return found


def declared_outputs(root, skill):
    try:
        with open(os.path.join(root, "skills", skill, "SKILL.md"), encoding="utf-8") as f:
            m = re.search(r"^  outputs:\s*\[(.*)\]", f.read().split("\n---", 1)[0], re.M)
    except OSError:
        return []
    return [v.strip().strip("\"'") for v in (m.group(1).split(",") if m else []) if v.strip()]


def is_output(outputs, rel):
    for declared in outputs:
        body = "[^/]+".join(re.escape(p) for p in PLACEHOLDER.split(declared))
        if re.match("^" + body + (".*" if declared.endswith("/") else "") + "$", rel):
            return True
    return False


def guard_positions(root, skill, case_id):
    """(positions of the guard assertions, number of assertions) of a case of this checkout, or (None, None)."""
    try:
        with open(os.path.join(root, "skills", skill, "evals", "evals.json"), encoding="utf-8") as f:
            cases = json.load(f).get("evals") or []
    except (OSError, ValueError):
        return None, None
    for case in cases:
        if str(case.get("id")) == case_id:
            assertions = case.get("assertions") or []
            tagged = [i for i, a in enumerate(assertions, 1) if isinstance(a, dict)
                      and any(t == "guard" or str(t).startswith("guard:") for t in a.get("tags") or [])]
            return tagged, len(assertions)
    return None, None


def build(archive, root):
    redact = load("corpus_redact", os.path.join(root, "scripts", "redact.py"))
    runs = {}
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            m = RUN.match(member.name)
            if not m or not member.isfile():
                continue
            key = (m["skill"], m["iteration"], m["case"], "floor" if m["variant"].endswith(".floor") else "strong",
                   int(m["run"] or 1))
            data = tar.extractfile(member).read().decode("utf-8", errors="replace")
            runs.setdefault(key, {})[m["file"]] = data
    lines, kept_written = [], set()
    for key in sorted(runs):
        files = runs[key]
        if "outputs/response.md" not in files or "facts.md" not in files:
            continue
        skill, iteration, case, tier, run = key
        did = facts(files["facts.md"])
        stopped = not any(did.values())
        if not stopped:
            if key[:4] in kept_written:
                continue
            kept_written.add(key[:4])
        try:
            timing = json.loads(files.get("timing.json") or "{}")
            grading = json.loads(files.get("grading.json") or "{}")
        except ValueError:
            timing, grading = {}, {}
        positions, count = guard_positions(root, skill, case)
        results = grading.get("assertion_results") if isinstance(grading, dict) else None
        guards = None
        if positions is not None and isinstance(results, list) and len(results) == count:
            guards = [{"position": p, "passed": bool(results[p - 1].get("passed"))} for p in positions]
        outputs = declared_outputs(root, skill)
        response = files["outputs/response.md"]
        lines.append({"id": f"{skill}/{iteration}/{case}/{tier}/{run}", "skill": skill, "case": case, "tier": tier,
                      "response": redact.redact(response, limit=len(response) + 64), **did, "stopped": stopped,
                      "outputs_written": [p for p in did["created"] + did["modified"] if is_output(outputs, p)],
                      "stop_reason": timing.get("stop_reason") if isinstance(timing, dict) else None, "guards": guards,
                      "pass_rate": (grading.get("summary") or {}).get("pass_rate") if isinstance(grading, dict) else None})
    return len(runs), lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    opts = {"--archive": None, "--out": os.path.join(HERE, "endings.jsonl"), "--root": ROOT}
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    i = 0
    while i < len(argv):
        if argv[i] not in opts or i + 1 >= len(argv):
            print(f"Error: unknown option or missing value at {argv[i]!r}. See --help.", file=sys.stderr)
            return 2
        opts[argv[i]] = argv[i + 1]
        i += 2
    if not opts["--archive"]:
        print("Error: --archive is required. See --help.", file=sys.stderr)
        return 2
    try:
        read, lines = build(opts["--archive"], opts["--root"])
    except (OSError, tarfile.TarError) as e:
        print(f"Error: cannot read {opts['--archive']}: {e}", file=sys.stderr)
        return 1
    text = "".join(json.dumps(line, ensure_ascii=True, sort_keys=True) + "\n" for line in lines)
    with open(opts["--out"], "w", encoding="ascii") as f:
        f.write(text)
    print(json.dumps({"runs_read": read, "lines": len(lines), "stopped": sum(1 for line in lines if line["stopped"]),
                      "by_tier": {tier: sum(1 for line in lines if line["tier"] == tier) for tier in ("strong", "floor")},
                      "sha256": hashlib.sha256(text.encode("ascii")).hexdigest()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
