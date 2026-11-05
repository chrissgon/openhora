#!/usr/bin/env python3
"""Build assets/data/proof.json for "Which model runs this skill?" from the band and model tables of
docs/inventory.md (the published snapshot that `python3 evals/eval_status.py inventory --write` generates).

Usage (from the repository root):
  python3 docs/design/results/website/round-2/tools/build_proof_json.py \
      --inventory docs/inventory.md --gate evals/eval-gate.json \
      --out docs/design/results/website/round-2/assets/data/proof.json

It reads only those two files, prints a one-line summary on stderr and writes JSON. No network, no model call.
"""
import argparse
import json
import re
import sys

ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|(.*)\|\s*$")


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--gate", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    gate = json.load(open(a.gate))
    text = open(a.inventory).read()
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
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print(f"{len(out['skills'])} skills, commit {commit}", file=sys.stderr)


if __name__ == "__main__":
    main()
