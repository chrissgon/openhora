#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The proof of a skill, and the choice of the model a run of it goes to.

The proof has one source: what the status script computes from the evidence files (evals/eval_status.py, read
through the lab facade, runtime/lab.py): the lab's, and the person's own tests of any model (outside the checkout).
This module keeps a copy of it, the proof file <data_dir>/proof.json, rebuilt when its inputs change (the gate file,
the skill's version file, its evidence files, the person's local evidence files, its content): a cache in the data
folder, never a source and never committed.

There are no tiers. A skill has a band for each model (a pair of skill and model, with the adapter the gate file names
for it), and a model is named by the person, or chosen by `auto`:

  A named model runs. Its band informs the person and never gates the choice (decision D34). A pair that is not
  `reliable` on this machine (the measurement files are not the recorded ones, the eval image is not the evidence's, or
  the band is not `reliable`) is unproven: the run is released to no one (autonomy "supervised"), whatever the mode.
  A skill runs in the condition it was measured in: one that requires the web but was not measured with it, on the model
  it runs on, runs without it.

  `auto` (decisions D22, D34, D35, D36) picks the pair with the lowest expected cost per run among the candidates:
  a pair is a candidate when the skill is `reliable` on it, the proof holds here (both checks), a key for the model
  was found, its price is known (runtime/prices.json), its with-skill runs have a measured usage (so that an expected
  cost exists) and, when the caller passes an approved set of providers (a routine), its provider is inside it. The
  expected cost of a run is the mean usage of the model's with-skill runs, by kind, times the price of that kind
  (runtime/prices.py). A tie goes to the higher pessimistic score. No candidate: the fallback model (the project's
  default model when it names one, else the first lab model), supervised, with the reason. Evidence from the lab and from
  the person's own tests counts for ranking and for release; community evidence (P10) counts for ranking only: a pair
  `reliable` only through it is chosen and its output is reviewed (autonomy "supervised").

The choice of a run is made once, here; whether an unproven pair is released by consent (decision D38) is the operations
layer's, which knows the agent (runtime/ops_models.py).

Functions:
  row(cfg, skill)                                    the skill's entry of the proof file: one pair for each model
  checks(entry)                                      {"measurement", "image"}: None, or why the proof does not hold
  route(cfg, skill, meta, *, model=None, ...)        the choice for one run (see its docstring)
  pair_view(entry, model, prices, today, max_days)   one pair as the proof read shows it, with price and expected cost

Usage (a library; the shell is runtime/cli.py, verb proof): python3 runtime/proof.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab  # noqa: E402  (the same folder)
import prices as price_table  # noqa: E402  (the same folder)

FILE = "proof.json"
VERSION = 3
RELIABLE = "reliable"
AUTO = "auto"
UNTESTED = {"band": "needs a test", "cause": "no evidence on this model", "score": None, "mean": None, "runs": 0,
            "web_measured": False, "usage_mean": None, "source": None}
# The sources of evidence a pair can rest on. Lab and local evidence rank a pair and release it; community evidence
# (P10) ranks it only.
RELEASING = ("lab", "local")


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


def _best(lab_figures, local_figures) -> dict:
    """The figures a pair shows: the lab's when the skill is reliable on the model by the lab's evidence, else the person's
    own when reliable by theirs, else the lab's, else the person's, else the untested word. The source is named."""
    if lab_figures and lab_figures.get("band") == RELIABLE:
        return lab_figures
    if local_figures and local_figures.get("band") == RELIABLE:
        return local_figures
    return lab_figures or local_figures or UNTESTED


def row(cfg: dict, skill: str) -> dict:
    """The skill's entry of the proof file: {"inputs_sha256", "skill_version", "evidence_images", "lab_models", "pairs":
    [{"model", "adapter", "names" ([the id, then its aliases]), "provider" (the gate file's route of the model, or None),
    "band", "cause", "score", "mean", "runs", "web_measured", "usage_mean" (the mean usage of the with-skill runs by kind,
    or None), "source" ("lab", "local", or None for a model with no evidence)}]}, one pair for each model the gate file
    lists (the lab models first). Reads <data_dir>/proof.json; when the entry is missing or its inputs_sha256 differs
    from lab.proof_inputs(skill), computes it from lab.standing(skill) and writes the file atomically. A model with no
    evidence gets the band `needs a test` with 0 runs. web_measured is stored on each pair: it is true when that model's
    current set holds a with-skill lab line of a case the gate file lists as a web case (lab.standing), so a listed case
    with no evidence on that model does not turn the web on, and a model can differ from the other. A proof file of
    an earlier VERSION (which held the two tiers) is read as empty and recomputed."""
    path = _path(cfg)
    data = _read(path)
    inputs = lab.proof_inputs(skill)
    entry = data["skills"].get(skill)
    if isinstance(entry, dict) and entry.get("inputs_sha256") == inputs:
        return entry
    standing = lab.standing(skill)
    pairs = []
    for model in lab.models():
        figures = _best(standing["models"].get(model), (standing.get("local") or {}).get(model))
        pairs.append({"model": model, "adapter": standing["adapters"].get(model), "names": lab.names_of(model),
                      "provider": lab.reference(model).get("route"),
                      **{k: figures.get(k) for k in ("band", "cause", "score", "mean", "runs", "usage_mean", "source")},
                      "web_measured": bool(figures.get("web_measured"))})
    entry = {"inputs_sha256": inputs, "skill_version": standing["version"],
             "evidence_images": list(standing["evidence_images"]), "lab_models": list(standing["lab_models"]),
             "pairs": pairs}
    data["skills"][skill] = entry
    _write(path, data)
    return entry


def checks(entry: dict) -> dict:
    """{"measurement": None or a reason, "image": None or a reason}: whether the proof holds on this checkout and
    this machine. Computed on every call, never cached.

    The image holds when the digest of the image on this machine is one the evidence was measured in. The digest
    is the repo digest of the published image when the lock file names one for this checkout's definition
    (lab.image(), source "published"), and the id of the local build otherwise. Evidence measured in a locally
    built image names that image's id, which no other machine has (decision D21): it holds on the machine that built it
    only, and the reason says so when the digests differ."""
    measurement = lab.measurement_problem()
    seen = lab.image()
    digest, wanted = seen["digest"], entry.get("evidence_images") or []
    if digest is None:
        if seen.get("problem"):
            image = f"the eval image cannot be looked up: {seen['problem']}"
        elif seen.get("source") == "published":
            image = f"the published eval image is not on this machine: run {seen.get('setup') or 'the setup step'}"
        else:
            image = "the eval image is not on this machine"
    elif digest not in wanted:
        image = "the image on this machine is not the one the evidence was measured in"
        portable = set(lab.published_digests())
        if any(d not in portable for d in wanted):
            image += (" (evidence measured in a locally built image holds on the machine that built it only; "
                      "the published image is the one every machine can have)")
    else:
        image = None
    return {"measurement": measurement, "image": image}


def expected_cost(pair: dict, table: dict):
    """Dollars for one run of the pair's skill: its measured mean usage by kind times the price of each kind in the
    table (runtime/prices.py); None when the pair has no measured usage or the model has no price (or lacks the price of a
    kind it used). The entry is looked up by the model's id, then its aliases."""
    return price_table.expected_cost(pair.get("usage_mean"), price_table.price_of(table, pair.get("names") or [pair["model"]]))


def _fallback(entry: dict, default) -> str:
    """The model `auto` falls back to: the project's default model when it names one (an id, not `auto`), else the first lab
    model of the entry, else the first pair."""
    ids = [p["model"] for p in entry["pairs"]]
    if default and default != AUTO:
        for pair in entry["pairs"]:
            if default in (pair.get("names") or [pair["model"]]):
                return pair["model"]
    for model in entry.get("lab_models") or []:
        if model in ids:
            return model
    return ids[0]


def route(cfg: dict, skill: str, meta: dict, *, model=None, default=None, named_by: str | None = None, key_found=None,
          table=None, approved=None) -> dict:
    """The choice for one run of a skill:

      {"model", "adapter", "web", "proven", "autonomy", "mode", "named_by", "source", "bands", "checks", "reasons",
       "candidates", "outside_provider", "expected_cost", "key_missing"}

    model is a model id or alias of the gate file, or "auto", or None. None is the project's default (`default`, the
    `default_model` of runtime.json: an id, or None/"auto" for auto). Anything else than a model the gate file lists is a
    ValueError. named_by says what chose the model, for the caller's rules about consent ("request", "task", "agent",
    "default"; it is returned as given and does not change the choice). key_found(model id) -> bool says whether the model's
    key was found (None: every key is found). table is the price table (prices.load(), else loaded here). approved is None,
    or the set of providers a routine may use (the `provider` of a pair); `auto` ignores a pair outside it and lists
    it in outside_provider.

    1. The entry of the proof file, and its two checks.
    2. mode "named": the model asked for runs. mode "auto": the candidate with the lowest expected cost, a tie to the higher
       score and then to the model id; no candidate: mode "fallback", the fallback model, with the reason.
    3. proven: both checks pass, the chosen pair's band is `reliable` and its evidence is the lab's or the person's own
       (source). A pair reliable only through community evidence is not proven. autonomy is "proven" or "supervised"; the
       operations layer may turn "supervised" into "consent" for an agent's own model (runtime/ops_models.py).
    4. web: the skill requires the web and the chosen pair was measured with it (the pair's web_measured).
    5. key_missing: key_found says no key was found for the chosen model (the caller refuses to start; a plan shows it).
    6. expected_cost: the chosen pair's expected cost per run, or None."""
    entry = row(cfg, skill)
    found = checks(entry)
    pairs = {p["model"]: p for p in entry["pairs"]}
    by_name = {name: p for p in entry["pairs"] for name in (p.get("names") or [p["model"]])}
    table = price_table.load() if table is None else table
    wanted = default if model is None else model
    reasons = [reason for reason in (found["measurement"], found["image"]) if reason]
    holds = not reasons
    candidates, outside = [], []
    if wanted not in (None, AUTO):
        if wanted not in by_name:
            raise ValueError(f"{wanted!r} is not a model of the gate file: the lab runs the models it lists")
        chosen, mode = by_name[wanted], "named"
    else:
        mode = AUTO
        for pair in entry["pairs"]:
            if not (holds and pair["band"] == RELIABLE):
                continue
            why = None
            if key_found is not None and not key_found(pair["model"]):
                why = "no key was found for it"
            elif price_table.price_of(table, pair.get("names") or [pair["model"]]) is None:
                why = "no price is known for it"
            elif not pair.get("usage_mean"):
                why = "its runs measured no usage, so there is no expected cost"
            elif (cost := expected_cost(pair, table)) is None:
                why = "its price lacks a kind its runs used"
            elif approved is not None and pair.get("provider") not in approved:
                outside.append(pair["model"])
                continue
            if why:
                reasons.append(f"{pair['model']} is reliable for this skill but {why}: it is not a candidate")
                continue
            candidates.append({"model": pair["model"], "expected_cost": cost, "score": pair.get("score") or 0.0,
                               "source": pair.get("source")})
        if candidates:
            best = min(candidates, key=lambda c: (c["expected_cost"], -c["score"], c["model"]))
            chosen = pairs[best["model"]]
        else:
            chosen, mode = pairs[_fallback(entry, default)], "fallback"
            reasons.append("no model qualifies for auto (the skill must be reliable on it, with a key, a price and a measured "
                           f"usage): {chosen['model']} runs, supervised")
    if mode == "named":
        if not holds:
            pass  # the reasons of the checks are already listed
        elif chosen["band"] != RELIABLE:
            reasons.append(f"the band on {chosen['model']} is {chosen['band']}: it is unproven and runs supervised")
    proven = (mode != "fallback" and holds and chosen["band"] == RELIABLE and chosen.get("source") in RELEASING)
    if mode == AUTO and chosen.get("source") not in RELEASING and holds and chosen["band"] == RELIABLE:
        reasons.append(f"{chosen['model']} is reliable only through community evidence: it was chosen, and its output is reviewed")
    web = bool(meta.get("web")) and bool(chosen["web_measured"])
    if meta.get("web") and not chosen["web_measured"]:
        # Leaves at the change of the lab's default list or of the grader (docs/backlog.md, T23): a skill that requires the
        # web but was measured without it, on the chosen model, runs without it, in the condition it was proven in.
        reasons.append("the skill requires the web and was measured without it: it runs without it")
    missing = key_found is not None and not key_found(chosen["model"])
    if missing:
        reasons.append(f"no key was found for {chosen['model']}")
    return {"model": chosen["model"], "adapter": chosen["adapter"], "web": web, "proven": proven,
            "autonomy": "proven" if proven else "supervised", "mode": mode, "named_by": named_by,
            "source": chosen.get("source"), "bands": {p["model"]: p["band"] for p in entry["pairs"]}, "checks": found,
            "reasons": reasons, "candidates": candidates, "outside_provider": outside,
            "expected_cost": expected_cost(chosen, table), "key_missing": bool(missing)}


def pair_view(pair: dict, table: dict, today=None, max_days: int = price_table.MAX_AGE_DEFAULT) -> dict:
    """One pair as the proof read and the pickers show it: the pair's own figures, the price of the model with its source,
    date, age and whether it is stale (older than max_days), and the expected cost per run (None when the model has no
    price or its runs measured no usage). today is a date or YYYY-MM-DD, by default today's date."""
    today = today or datetime.date.today()
    names = pair.get("names") or [pair["model"]]
    found = price_table.price_of(table, names)
    return {**{k: pair.get(k) for k in ("model", "adapter", "provider", "band", "cause", "score", "mean", "runs",
                                          "web_measured", "usage_mean", "source")},
            "price": ({**{kind: found.get(price_table.field(kind)) for kind in price_table.KINDS},
                       **price_table.summary(found, today, max_days)} if found else None),
            "expected_cost": price_table.expected_cost(pair.get("usage_mean"), found)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
