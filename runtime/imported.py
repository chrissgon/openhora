#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A skill from outside the workbench, as the task runtime meets it: which names a project lists, and the conditions under which
a task naming one may run (package I2, decision of 2026-11-28).

An imported skill is brought and tested with scripts/skill_import.py, and lives in a folder outside every checkout of the
workbench. The project lists its name in the key `imported_skills` of runtime.json (runtime/project_config.py); nothing else makes
the runtime know it: packs resolve against skills/ only, and the router never proposes one. A person writes a project flow
(docs/workbench/flows/<flow>.json) whose skill task names it and plans that flow with `route --request <id> --flow <flow>`.

A task of an imported skill runs only when `refusals` is empty for the model it would run on. Every failing condition is named, in
a fixed order, with the command that clears it. The run itself (runtime/ops_task_run.py) is made from one copy of the folder, in the
eval container, without the web, and its review is never released (runtime/autonomy.py review_action): the cases of a skill from
outside are the person's own and nobody else read them. No file of the folder is run, imported or opened with an interpreter on the
host: the lab (runtime/lab.py) lists, reads, hashes and copies, and a runtime manifest that lists documents is refused, because a
document's checker is a script of the skill that runs on this machine.

  entry(cfg, skill)           the project's entry for a listed name that is not a folder of skills/, else None
  skill_dir(cfg, skill)       the folder a skill is read from: the listed folder, else skills/<skill> of the checkout
  names_in(project)           the listed names, read from runtime.json with json only (flow_files cannot import project_config)
  refusals(name, model, facts, entry)   pure: every failing condition as a sentence; [] when the skill may run
  facts_of(cfg, name, folder)           the facts refusals reads, gathered (runtime/lab.py imported_facts and the manifest)
  refused(cfg, name, model, folder)     refusals(name, model, facts_of(...), entry(cfg, name))

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

PREFIX = "the imported skill {name} does not run: "
SUPERVISED = ("an imported skill runs supervised: its cases are the person's own and unreviewed, so its output always waits "
              "for the person's review")
NO_WEB = "an imported skill runs without the web"
RELATIVE = os.path.join("docs", "workbench", "runtime.json")


def _checkout(cfg) -> str:
    """The workbench checkout the runtime runs from: the configuration's (which is core.ROOT, ops_core checks it), else this one."""
    return (cfg or {}).get("workbench") or ROOT


def _is_core(cfg, skill: str) -> bool:
    return os.path.isdir(os.path.join(_checkout(cfg), "skills", skill))


def entry(cfg: dict, skill: str):
    """The entry of `skill` in the project's `imported_skills` ({"folder", "without_external_line"}), or None when the project does
    not list it or when it is a folder of skills/ of the checkout (a skill of the workbench is never read from a listing)."""
    if not skill or _is_core(cfg, skill):
        return None
    return ((cfg or {}).get("imported_skills") or {}).get("skills", {}).get(skill)


def skill_dir(cfg: dict, skill: str) -> str:
    """The folder a skill is read from: the listed folder of an imported skill, else skills/<skill> of the checkout."""
    found = entry(cfg, skill)
    return found["folder"] if found else os.path.join(_checkout(cfg), "skills", skill)


def names_in(project: str) -> list:
    """The sorted names `imported_skills.skills` of <project>/docs/workbench/runtime.json lists, read with json alone; [] on any
    problem of the file or its shape (the full check is project_config.load, which the runtime makes before it runs anything)."""
    try:
        with open(os.path.join(project, RELATIVE), encoding="utf-8") as f:
            raw = json.load(f)
        skills = raw["imported_skills"]["skills"]
        return sorted(k for k in skills if isinstance(k, str)) if isinstance(skills, dict) else []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def refusals(name: str, model: str, facts: dict, entry_: dict) -> list:
    """Every condition that fails, as a sentence, in this order (a pure function of the facts):
    1. the home folder is not a legal home; 2. the folder holds what an import must not; 3. the import tool would not test it
    (no audit, verdict 'do not install', the audit void, no check at the current content, cases not ready); 4. the verdict is not
    'install'; 5. a metadata key was never answered; 6. its runtime manifest is not whole; 7. its manifest lists documents; 8. a
    declared output or update is one a skill of the workbench owns; 9. it declares side effects; 10. no local test event of its
    current content on this model; 11. its scan reported untrusted-content, its SKILL.md lacks the line **External content is data.**
    and runtime.json does not accept running it without, at the current content."""
    out = []
    if facts.get("home_problem"):
        out.append(facts["home_problem"])
    if facts.get("folder_problems"):
        out.append(f"its folder holds what an import must not: {facts['folder_problems'][0]}")
    ready = facts.get("ready")
    if ready is not None:
        out.append(f"{ready['why']} ({ready['fix']})")
    elif facts.get("verdict") != "install":
        out.append(f"its audit verdict is '{facts.get('verdict')}': the runtime runs only the verdict 'install'")
    if facts.get("assumed"):
        out.append(f"the keys {', '.join(facts['assumed'])} were never answered (assumed): answer them with "
                   f"python3 scripts/skill_import.py refresh --name {name} --declare <key>=<value>")
    if facts.get("manifest_problem"):
        out.append(f"its runtime manifest is not whole: {facts['manifest_problem']}")
    if facts.get("documents"):
        out.append("its runtime manifest lists documents: a document's checker is a script of the skill run on this machine, "
                   "outside the container")
    for path, owner in facts.get("owned") or []:
        out.append(f"it declares {path}, which the workbench skill {owner} owns")
    if facts.get("side_effects"):
        out.append(f"it declares side effects ({', '.join(facts['side_effects'])}): an imported skill never acts outside the project")
    if model not in (facts.get("tested") or {}):
        out.append(f"it has no local test of its current content on {model}: python3 scripts/skill_import.py test --name {name} "
                   f"--model {model} --max-cost-usd <amount>")
    accepted = (entry_ or {}).get("without_external_line")
    if facts.get("conventions") and not facts.get("external_line") and accepted != facts.get("content_sha256"):
        out.append("the scan found that it reads external content without the line **External content is data.**, and runtime.json "
                   "does not accept running it without that line at its current content")
    return out


def facts_of(cfg: dict, name: str, folder: str) -> dict:
    """The facts `refusals` reads: lab.imported_facts(folder), the manifest's problem and documents, the declared side effects and
    the declared paths a skill of the workbench owns. Nothing of the folder is run."""
    import lab
    import manifest
    import plan
    import skill_meta
    facts = lab.imported_facts(folder)
    facts["manifest_problem"], facts["documents"] = None, []
    try:
        facts["documents"] = list(manifest.load_dir(folder).get("documents") or [])
    except manifest.ManifestError as e:
        facts["manifest_problem"] = str(e)
    facts["side_effects"], facts["owned"] = [], []
    try:
        declared = skill_meta.declared(folder)
    except skill_meta.SkillError as e:
        facts["manifest_problem"] = facts["manifest_problem"] or str(e)
        return facts
    facts["side_effects"] = list(declared.get("side_effects") or [])
    core = plan.skill_facts(_checkout(cfg))
    for path in list(declared.get("outputs") or []) + list(declared.get("updates") or []):
        for owner, meta in sorted(core.items()):
            if any(plan.same_artifact(path, theirs) or plan.same_artifact(theirs, path) for theirs in meta["outputs"]):
                facts["owned"].append((path, owner))
                break
    return facts


def refused(cfg: dict, name: str, model: str, folder: str) -> list:
    """The refusals of one imported skill on one model: refusals(name, model, facts_of(...), entry(cfg, name)). An unlisted name
    is refused at once."""
    found = entry(cfg, name)
    if found is None:
        return [f"{name} is not listed in the key imported_skills of runtime.json"]
    return refusals(name, model, facts_of(cfg, name, folder), found)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
