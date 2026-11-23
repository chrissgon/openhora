#!/usr/bin/env python3
"""Build assets/data/proof.json for "Which model runs this skill?" from the band and model tables of
docs/inventory.md (the published snapshot that `python3 evals/eval_status.py inventory --write` generates) and the gate file.

Usage (from the repository root; these are the defaults):
  python3 site/tools/build_proof_json.py \
      --inventory docs/inventory.md --gate evals/eval-gate.json --out site/assets/data/proof.json
  python3 site/tools/build_proof_json.py --check      # exit 1 when the committed file differs from what the two sources give

It reads only those two files, prints a one-line summary on stderr and writes JSON. No network, no model call.
The page figures are then rebuilt from this file with `python3 site/tools/build_facts.py --write`.
"""
import argparse
import json
import re
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*)\|\s*$")


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def build(inventory_path, gate_path):
    """The proof.json content (a dict) from the inventory snapshot and the gate file."""
    gate = json.load(open(gate_path, encoding="utf-8"))
    text = open(inventory_path, encoding="utf-8").read()
    body = text.split("<!-- eval-status:begin -->", 1)[1].split("<!-- eval-status:end -->", 1)[0]
    commit = re.search(r"Generated at commit `([0-9a-f]+)`", body).group(1)

    skills = {}
    table = None
    for line in body.splitlines():
        if line.startswith("| Skill | Version"):
            table = "band"
            continue
        if line.startswith("| Skill | Model"):
            table = "model"
            continue
        m = ROW.match(line)
        if not m or table is None:
            continue
        c = cells(line)
        name = c[0].strip("`")
        if table == "band":
            # Skill | Version | Band | Cause | Score | Mean | Runs (N) | Last full test | Field
            skills[name] = {"skill": name, "version": c[1], "area": name.split("-")[0], "last_full_test": c[7], "models": {}}
        else:
            # Skill | Model | Band | Cause | Gate | Score | Mean | Lab runs (N) | Field | Platforms
            model = c[1].strip("`")
            skills.setdefault(name, {"skill": name, "models": {}})["models"][model] = {
                "band": c[2], "cause": None if c[3] == "-" else c[3], "gate": c[4],
                "score": c[5], "mean": c[6], "runs": c[7]}

    entries = gate["models"]
    out = {
        "source": "docs/inventory.md, Evaluation status (band table and model table)",
        "generated_at_commit": commit,
        # the lab models in the gate file's order, each with the adapter its entry names: there is no reference model and no floor model
        "lab_models": [{"model": m, "adapter": entries[m]["adapter"]} for m in gate["lab_models"]],
        "threshold": gate["threshold"], "tolerance": gate["tolerance"], "runs_per_case": gate["runs"],
        "skills": sorted(skills.values(), key=lambda s: s["skill"]),
    }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", default=os.path.join(ROOT, "docs", "inventory.md"))
    ap.add_argument("--gate", default=os.path.join(ROOT, "evals", "eval-gate.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "site", "assets", "data", "proof.json"))
    ap.add_argument("--check", action="store_true", help="compare --out with the built content; exit 1 when it differs")
    a = ap.parse_args()
    out = build(a.inventory, a.gate)
    text = json.dumps(out, indent=1) + "\n"
    if a.check:
        have = open(a.out, encoding="utf-8").read() if os.path.exists(a.out) else ""
        if have != text:
            print(f"{a.out} differs from {a.inventory} and {a.gate}; fix: python3 site/tools/build_proof_json.py && python3 site/tools/build_facts.py --write", file=sys.stderr)
            sys.exit(1)
        print("proof.json is current", file=sys.stderr)
        return
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{len(out['skills'])} skills, commit {out['generated_at_commit']}", file=sys.stderr)


if __name__ == "__main__":
    main()
