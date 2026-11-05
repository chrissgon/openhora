#!/usr/bin/env python3
"""Stage skills where a tool discovers them: copies, never links, without what no model uses.

Usage:
  python3 scripts/stage_skills.py --skills-dir <target folder> --skill <skill folder> [--skill <skill folder>]...
                                  [--strip <path inside a skill>]... [--no-strip]
                                  [--references none|cited|all] [--cite-from <skill folder>]...
                                  [--platform <name>]... [--root <workbench root>] [--marker <file name>]

It has two callers, and its interface is written for both: the eval runner (evals/eval_run.py), which
stages the skill under test and a case's dependency skills into a case folder before a container
starts, and the installers of the adapters, which install a pack. It depends on nothing under evals/.
A change to this file changes what a model run sees: it is an execution-side change of the measurement
(docs/architecture/reliability-model-2026-10-02.md, section 8).

What is staged:
  <target folder>/<name>/            each --skill folder, copied with links followed (a copy never points
                                     back at the workbench), without the paths named with --strip. The
                                     default is `evals` and `scripts/tests`: the cases with their expected
                                     outputs and assertions, and the tests of the skill's scripts. Caches
                                     and system files (__pycache__, *.pyc, .pytest_cache, .DS_Store) are
                                     never copied. --no-strip copies everything else.
  <target folder>/../shared/references/
                                     files of <root>/shared/references, beside the skills folder so that a
                                     skill's ../../shared/references/<file> resolves by the staged path:
                                       --references all     every file (an installer)
                                       --references cited   the files that the SKILL.md, or a file under the
                                                            references/ folder, of each --cite-from skill
                                                            names as shared/references/<file> (the runner:
                                                            a run gets what its skill cites, nothing more)
                                       --references none    nothing (the default)
                                     and, for each --platform <name>, shared/references/platforms/<name>.md
                                     with <name>.json when it exists: the platform a case names.
  --marker <file name>               an empty file of that name in every staged skill folder and in the
                                     shared folder: how an installer recognises what it made.

Never staged: shared/scripts/, any test, any eval case.

Prints one JSON object: {"skills_dir", "skills": [names], "shared_dir": <path or null>,
"references": [paths relative to shared/references]}. Diagnostics go to stderr.
Exit codes: 0 ok; 1 a source is missing or is not a skill; 2 usage error. Standard library only.
"""
import fnmatch
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_STRIP = ("evals", "scripts/tests")
# Never part of a staged copy: what an interpreter or a desktop leaves in a folder.
CACHES = ("__pycache__", "*.pyc", ".pytest_cache", ".DS_Store")
REFERENCES_REL = os.path.join("shared", "references")
MODES = ("none", "cited", "all")
CITED_RE = re.compile(r"shared/references/([A-Za-z0-9_][A-Za-z0-9_./-]*)")
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class StageError(Exception):
    pass


def skill_name(skill_dir):
    return os.path.basename(os.path.normpath(skill_dir))


def _ignore(src, strip):
    strip = {s.strip("/") for s in strip}

    def ignore(folder, names):
        rel = os.path.relpath(folder, src).replace(os.sep, "/")
        prefix = "" if rel == "." else rel + "/"
        # A link whose target is gone is left out here, where every Python version honours it: on 3.9
        # shutil.copytree(ignore_dangling_symlinks=True) still raised shutil.Error for such a link.
        dangling = lambda n: os.path.islink(os.path.join(folder, n)) and not os.path.exists(os.path.join(folder, n))
        return [n for n in names if prefix + n in strip or any(fnmatch.fnmatch(n, pattern) for pattern in CACHES) or dangling(n)]
    return ignore


def copy_skill(skill_dir, skills_dir, strip=DEFAULT_STRIP, marker=None):
    """Copy one skill folder to <skills_dir>/<name>, replacing a folder already there. Returns the copy's path."""
    if not os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
        raise StageError(f"{skill_dir} is not a skill folder: it has no SKILL.md")
    dest = os.path.join(skills_dir, skill_name(skill_dir))
    if os.path.islink(dest):
        os.remove(dest)
    elif os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(skills_dir, exist_ok=True)
    # symlinks=False: a link inside the skill is copied as its content, never kept pointing back.
    shutil.copytree(skill_dir, dest, symlinks=False, ignore=_ignore(skill_dir, strip), ignore_dangling_symlinks=True)
    if marker:
        open(os.path.join(dest, marker), "w", encoding="utf-8").close()
    return dest


def cited_references(skill_dir, root=ROOT):
    """Files of <root>/shared/references that the skill's SKILL.md, or a file under its references/ folder,
    names as shared/references/<file>. Sorted, relative to shared/references, with "/" separators."""
    texts = [os.path.join(skill_dir, "SKILL.md")]
    for dp, dns, fns in os.walk(os.path.join(skill_dir, "references")):
        dns.sort()
        texts += [os.path.join(dp, fn) for fn in sorted(fns)]
    base, found = os.path.join(root, REFERENCES_REL), set()
    for path in texts:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        for match in CITED_RE.findall(text):
            rel = match.rstrip("./")
            if rel and ".." not in rel.split("/") and os.path.isfile(os.path.join(base, *rel.split("/"))):
                found.add(rel)
    return sorted(found)


def all_references(root=ROOT):
    base, found = os.path.join(root, REFERENCES_REL), []
    for dp, dns, fns in os.walk(base):
        dns[:] = sorted(d for d in dns if not any(fnmatch.fnmatch(d, pattern) for pattern in CACHES))
        for fn in sorted(fns):
            if not any(fnmatch.fnmatch(fn, pattern) for pattern in CACHES):
                found.append(os.path.relpath(os.path.join(dp, fn), base).replace(os.sep, "/"))
    return sorted(found)


def platform_references(names, root=ROOT):
    """The reference of each named platform, and its data file when there is one."""
    base, found = os.path.join(root, REFERENCES_REL, "platforms"), []
    for name in names:
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise StageError(f"{name!r} is not a platform name")
        if not os.path.isfile(os.path.join(base, name + ".md")):
            raise StageError(f"platform {name!r} has no reference: shared/references/platforms/{name}.md does not exist")
        found.append(f"platforms/{name}.md")
        if os.path.isfile(os.path.join(base, name + ".json")):
            found.append(f"platforms/{name}.json")
    return found


def shared_dir_of(skills_dir):
    """Where shared/ goes: beside the skills folder, so that <skill>/../../shared/references resolves."""
    return os.path.join(os.path.dirname(os.path.normpath(skills_dir)), "shared")


def stage(skill_dirs, skills_dir, root=ROOT, references="none", cite_from=(), platforms=(), strip=DEFAULT_STRIP,
          marker=None):
    """Stage the skills and the references that go with them. Returns the manifest that main() prints.

    Nothing is staged when a source is wrong: every source is checked before the first copy."""
    if references not in MODES:
        raise StageError(f"references must be one of {', '.join(MODES)}")
    for d in list(skill_dirs) + list(cite_from):
        if not os.path.isfile(os.path.join(d, "SKILL.md")):
            raise StageError(f"{d} is not a skill folder: it has no SKILL.md")
    names = [skill_name(d) for d in skill_dirs]
    if len(set(names)) != len(names):
        raise StageError("two skill folders have the same name")
    wanted = set(platform_references(platforms, root))
    if references == "all":
        wanted.update(all_references(root))
    elif references == "cited":
        for d in cite_from:
            wanted.update(cited_references(d, root))
    for d in skill_dirs:
        copy_skill(d, skills_dir, strip=strip, marker=marker)
    shared = None
    if wanted:
        shared = shared_dir_of(skills_dir)
        for rel in sorted(wanted):
            dest = os.path.join(shared, "references", *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(os.path.join(root, REFERENCES_REL, *rel.split("/")), dest)
        if marker:
            open(os.path.join(shared, marker), "w", encoding="utf-8").close()
    return {"skills_dir": skills_dir, "skills": names, "shared_dir": shared, "references": sorted(wanted)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip())
        return 0 if argv else 2
    opts = {"skills_dir": None, "skill": [], "strip": [], "no_strip": False, "references": "none", "cite_from": [],
            "platform": [], "root": ROOT, "marker": None}
    many, i = ("skill", "strip", "cite_from", "platform"), 0
    while i < len(argv):
        key = argv[i][2:].replace("-", "_") if argv[i].startswith("--") else None
        if key == "no_strip":
            opts["no_strip"] = True
            i += 1
            continue
        if key not in opts or key == "no_strip":
            print(f"Error: unknown option {argv[i]!r}. See --help.", file=sys.stderr)
            return 2
        if i + 1 >= len(argv):
            print(f"Error: {argv[i]} needs a value. See --help.", file=sys.stderr)
            return 2
        if key in many:
            opts[key].append(argv[i + 1])
        else:
            opts[key] = argv[i + 1]
        i += 2
    if not opts["skills_dir"] or not opts["skill"]:
        print("Error: --skills-dir and at least one --skill are required. See --help.", file=sys.stderr)
        return 2
    if opts["references"] not in MODES:
        print(f"Error: --references must be one of {', '.join(MODES)}.", file=sys.stderr)
        return 2
    if opts["marker"] is not None and (not opts["marker"] or "/" in opts["marker"] or opts["marker"] in (".", "..")):
        print("Error: --marker is a file name, without a folder.", file=sys.stderr)
        return 2
    strip = () if opts["no_strip"] else tuple(opts["strip"]) or DEFAULT_STRIP
    try:
        manifest = stage(opts["skill"], opts["skills_dir"], root=opts["root"], references=opts["references"],
                         cite_from=opts["cite_from"], platforms=opts["platform"], strip=strip, marker=opts["marker"])
    except (StageError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
