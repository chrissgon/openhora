#!/usr/bin/env python3
"""Count the two dated facts the website states, from the files of this checkout (no network, no model call).

Usage (from the repository root):
  python3 site/tools/count_facts.py

Prints one JSON line:
  external_content_skills  the skills whose SKILL.md has a line that starts with "External content is data." (the line
                           the security scan looks for: scripts/security_scan.py, UNTRUSTED_LINE_RE, read as it is read there)
  guard_assertions         the assertions tagged `guard` or `guard:<effect>` in the cases of skills/<name>/evals/evals.json
                           (evals/eval_status.py: skill_cases and guards_of, the rule the status uses)
  guard_assertions_all     the same, with the platform case files (skills/<name>/evals/platforms/*.json) added
"""
import glob
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINE = re.compile(r"^[ \t]*(?:>[ \t]*)?(?:(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?)?(?:\*\*|__)?External content is data\.", re.M)


def load_status():
    spec = importlib.util.spec_from_file_location("eval_status", os.path.join(ROOT, "evals", "eval_status.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_status"] = module
    spec.loader.exec_module(module)
    return module


def main():
    es = load_status()
    skills = sorted(d for d in glob.glob(os.path.join(ROOT, "skills", "*")) if os.path.isfile(os.path.join(d, "SKILL.md")))
    carrying = [os.path.basename(d) for d in skills if LINE.search(open(os.path.join(d, "SKILL.md"), encoding="utf-8").read())]
    main_count = sum(len(es.guards_of(case)) for d in skills for case in es.skill_cases(d).values())
    platform = 0
    for d in skills:
        for path in glob.glob(os.path.join(d, "evals", "platforms", "*.json")):
            data = json.load(open(path, encoding="utf-8"))
            cases = data.get("evals") if isinstance(data, dict) else data
            platform += sum(len(es.guards_of(case)) for case in cases or [])
    print(json.dumps({"skills": len(skills), "external_content_skills": len(carrying), "guard_assertions": main_count,
                      "guard_assertions_all": main_count + platform}))


if __name__ == "__main__":
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(__doc__.strip())
    else:
        main()
