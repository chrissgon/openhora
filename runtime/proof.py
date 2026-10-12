#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The proof of a skill, and the choice of the model a run of it goes to.

The proof has one source: what the status script computes from the evidence files (evals/eval_status.py, read
through the lab facade, runtime/lab.py). This module keeps a copy of it, the proof file
<data_dir>/proof.json, rebuilt when its inputs change (the gate file, the skill's version file, its evidence
files, its content): a cache in the data folder, never a source and never committed.

A run goes to the floor model only when the skill is `reliable` there, the measurement files of this checkout are
the recorded ones, the eval image on this machine is the one the evidence was measured in, and a key for the floor
model is found (the runtime's own, else the lab's: runtime/ops.py, _floor_key). Otherwise it goes to the
reference model. Nobody can ask for the floor model; the person can ask for the reference model. A skill runs in
the condition it was measured in: one that requires the web but was measured without it runs without it.

Functions:
  row(cfg, skill)                                    the skill's entry of the proof file
  checks(entry)                                      {"measurement", "image"}: None, or why the proof does not hold
  route(cfg, skill, meta, *, force=None, floor_key=False)   the choice for one run

Usage (a library; the shell is runtime/cli.py, verb proof): python3 runtime/proof.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab  # noqa: E402  (the same folder)

FILE = "proof.json"
VERSION = 1
TIERS = ("strong", "floor")
RELIABLE = "reliable"
UNTESTED = {"band": "needs a test", "cause": "no evidence on this model", "score": None, "mean": None, "runs": 0}


def _path(cfg: dict) -> str:
    return os.path.join(cfg["data_dir"], FILE)


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"version": VERSION, "skills": {}}
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("skills"), dict):
        return {"version": VERSION, "skills": {}}
    return data


def _write(path: str, data: dict) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".proof-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def row(cfg: dict, skill: str) -> dict:
    """The skill's entry of the proof file. Reads <data_dir>/proof.json; when the entry is missing or its
    inputs_sha256 differs from lab.proof_inputs(skill), computes it from lab.standing(skill) and writes the file
    atomically. A model with no entry in the standing gets the band `needs a test` with 0 runs. web_measured is
    true when the gate file lists web cases for the skill."""
    path = _path(cfg)
    data = _read(path)
    inputs = lab.proof_inputs(skill)
    entry = data["skills"].get(skill)
    if isinstance(entry, dict) and entry.get("inputs_sha256") == inputs:
        return entry
    standing = lab.standing(skill)
    pairs = []
    for tier in TIERS:
        pair = standing["tiers"][tier]
        found = standing["models"].get(pair["model"]) or UNTESTED
        pairs.append({"tier": tier, "model": pair["model"], "adapter": pair["adapter"],
                      **{k: found.get(k) for k in ("band", "cause", "score", "mean", "runs")}})
    entry = {"inputs_sha256": inputs, "skill_version": standing["version"],
             "web_measured": bool(standing["web_cases"]), "evidence_images": list(standing["evidence_images"]),
             "pairs": pairs}
    data["skills"][skill] = entry
    _write(path, data)
    return entry


def checks(entry: dict) -> dict:
    """{"measurement": None or a reason, "image": None or a reason}: whether the proof holds on this checkout and
    this machine. Computed on every call, never cached."""
    measurement = lab.measurement_problem()
    digest = lab.image()["digest"]
    if digest is None:
        image = "the eval image is not on this machine"
    elif digest not in (entry.get("evidence_images") or []):
        image = "the image on this machine is not the one the evidence was measured in"
    else:
        image = None
    return {"measurement": measurement, "image": image}


def route(cfg: dict, skill: str, meta: dict, *, force=None, floor_key: bool = False) -> dict:
    """The choice for one run of a skill: {"tier", "model", "adapter", "web", "proven", "autonomy", "bands":
    {"strong", "floor"}, "checks", "reasons"}.

    1. The entry of the proof file, and its two checks.
    2. force is None or "strong"; anything else raises ValueError: nobody can ask for the floor model.
    3. A check that fails: the reference model, not proven.
    4. Else force "strong": the reference model.
    5. Else the floor model when its band is `reliable` and a key for it was found (floor_key).
    6. Else the reference model, with the reason.
    7. proven: both checks pass and the chosen pair's band is `reliable`; autonomy equals proven (stage 2 records
       it; stage 6 is the first to read it).
    8. web: the skill requires the web and was measured with it.
    9. model and adapter are the chosen pair's, as the gate file names them."""
    if force not in (None, "strong"):
        raise ValueError("only the reference model can be asked for: force is None or \"strong\"")
    entry = row(cfg, skill)
    found = checks(entry)
    pairs = {pair["tier"]: pair for pair in entry["pairs"]}
    reasons = [reason for reason in (found["measurement"], found["image"]) if reason]
    if reasons:
        tier = "strong"
    elif force == "strong":
        tier, reasons = "strong", ["the person asked for the reference model"]
    elif pairs["floor"]["band"] == RELIABLE and floor_key:
        tier = "floor"
    else:
        tier = "strong"
        reasons.append(f"the band on the floor model is {pairs['floor']['band']}" if pairs["floor"]["band"] != RELIABLE
                       else "no key for the floor model was found")
    chosen = pairs[tier]
    proven = not (found["measurement"] or found["image"]) and chosen["band"] == RELIABLE
    web = bool(meta.get("web")) and bool(entry["web_measured"])
    if meta.get("web") and not entry["web_measured"]:
        # Leaves at the change of reference model (docs/backlog.md, T23): a skill that requires the web but was
        # measured without it runs without it, in the condition it was proven in.
        reasons.append("the skill requires the web and was measured without it: it runs without it")
    return {"tier": tier, "model": chosen["model"], "adapter": chosen["adapter"], "web": web, "proven": proven,
            "autonomy": proven, "bands": {t: pairs[t]["band"] for t in TIERS}, "checks": found, "reasons": reasons}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
