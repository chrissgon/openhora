#!/usr/bin/env python3
"""Report which environment requirement classes are satisfied.

Usage: python3 scripts/doctor.py [--harness <name>] [--json] [--strict]

Collects `metadata.requires` from every skill, then checks each class against:
  1. connectors declared by the chosen adapter in adapters/<harness>/connectors.json
     ({"classes": {"integration:issue-tracker": "mcp: atlassian"}})
  2. the native provider that providers/resolve.py chooses for the class (the same function the
     runtime and the skills use: the class's variable, then the platform default, then the only
     implementation left), when its script passes `--check`. For a class with a parameter the
     platform is passed too (`--check --platform <p>` for publisher:<p>), and the provider is chosen
     among the implementations that declare that platform, so a platform nobody serves is missing.
     `python3 providers/resolve.py --list` shows the folders, the variables and the choices.

Status of a class: `connector`, `provider`, `missing` (nothing satisfies it), or `unknown` (the name
is not a class of contracts/environment.md: a typo, or a name the resolution function does not have
yet). An unknown class counts as missing. A class written with one of the four old bare names
(mailbox, mailer, scheduler, store) is checked as the class it became, and the detail says so.

Options:
  --harness <name>  include connectors declared by that adapter
  --json            machine-readable report on stdout
  --strict          exit 1 when any required class is missing
  --help            show this text

It also lists every secret registered in providers/secrets/resolver.py or by an adapter (the
"secrets" list of its adapter.json): found or missing, where
it was found (environment or OS secret store), which classes read it and how to set it. It never
prints a value. Missing secrets do not change the exit code; see contracts/secrets.md.

Exit codes: 0 ok, 1 missing classes with --strict, 2 usage error.
"""
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from validate import load_yaml, split_frontmatter  # noqa: E402

SKILLS = os.path.join(ROOT, "skills")
PROVIDERS = os.path.join(ROOT, "providers")
ADAPTERS = os.path.join(ROOT, "adapters")


def collect_requires():
    req = {}
    if not os.path.isdir(SKILLS):
        return req
    for d in sorted(os.listdir(SKILLS)):
        p = os.path.join(SKILLS, d, "SKILL.md")
        if not os.path.isfile(p):
            continue
        fm_text, _ = split_frontmatter(p)
        if fm_text is None:
            continue
        try:
            meta = (load_yaml(fm_text) or {}).get("metadata") or {}
        except Exception:  # noqa: BLE001
            continue
        for cls in meta.get("requires") or []:
            req.setdefault(cls, []).append(d)
    return req


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


# The one resolution function (class -> provider script); this script builds no provider path itself.
resolution = _load("workbench_provider_resolve", os.path.join(PROVIDERS, "resolve.py"))
NAME_RE = re.compile(r"[a-z0-9-]+")


def provider_folder(cls):
    """providers/<folder>/ for a class, as providers/resolve.py maps it; None for a name that is not a class."""
    try:
        return resolution.folder(cls)
    except resolution.UnknownClass:
        return None


def run_check(script, platform=None):
    """Run the provider's --check through its declared runner, uv (providers/CONTRACT.md: never with the
    caller's interpreter); for a class with a parameter, --check --platform <p>."""
    if not _which("uv"):
        return "missing", "uv is not on PATH: a provider runs only through `uv run` (providers/CONTRACT.md)"
    runner = ["uv", "run", script]
    check = ["--check"] + (["--platform", platform] if platform else [])
    try:
        r = subprocess.run(runner + check, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "missing", f"--check failed to run: {e}"
    if r.returncode == 0:
        return "provider", os.path.relpath(script, os.path.realpath(ROOT))
    return "missing", f"--check exit {r.returncode}: {(r.stderr or r.stdout).strip()[:200]}"


def check_class(cls):
    """Resolve the class as the runtime and the skills do, then run the chosen provider's --check."""
    try:
        got = resolution.resolve(cls, root=ROOT)
    except resolution.Unresolved as e:
        return "missing", f"no connector declared and no provider resolves: {e}"
    except resolution.UnknownClass as e:
        return "unknown", str(e)
    status, detail = run_check(got["path"], resolution.platform_of(cls))
    how = f"{got['variable']}={got['implementation']}" if got["source"] == "environment" else \
        f"{got['implementation']} ({got['source']})"
    renamed = f" (declared as {cls}, the old name of {got['class']})" if got["class"] != cls else ""
    return status, f"{how}: {detail}{renamed}"


def _which(name):
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.isfile(os.path.join(p, name)):
            return True
    return False


def load_connectors(harness):
    if not harness:
        return {}
    p = os.path.join(ADAPTERS, harness, "connectors.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return (json.load(f) or {}).get("classes") or {}


def secrets_report(classes):
    """Every registered secret (providers/secrets/resolver.py): found or not, where, and which of the
    installed skills' classes read it. Never the value."""
    path = str(resolution.secret_resolver(root=ROOT))
    if not os.path.isfile(path):
        return []
    resolver = _load("workbench_secret_resolver", path)
    # The core's registry holds the providers' credentials; each adapter registers its own.
    for manifest in sorted(glob.glob(os.path.join(ADAPTERS, "*", "adapter.json"))):
        try:
            resolver.register_file(manifest)
        except ValueError as e:
            print(f"warning: {e}", file=sys.stderr)
    rows = []
    for row in resolver.report():
        folders = {r.split("/")[1] for r in row["readers"] if r.startswith("providers/")}
        row["classes"] = sorted(c for c in classes if provider_folder(c) in folders)
        rows.append({k: row[k] for k in ("name", "found", "source", "service", "store", "classes", "readers", "set")})
    return rows


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    harness, as_json, strict = None, "--json" in argv, "--strict" in argv
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--harness":
            if i + 1 >= len(argv):
                print("Error: --harness needs a value, e.g. --harness claude-code", file=sys.stderr)
                return 2
            harness = argv[i + 1]
            i += 2
            continue
        if a not in ("--json", "--strict"):
            print(f"Error: unknown option {a!r}. See --help.", file=sys.stderr)
            return 2
        i += 1
    if harness and (not NAME_RE.fullmatch(harness) or not os.path.isdir(os.path.join(ADAPTERS, harness))):
        print(f"Error: adapter {harness!r} not found under adapters/.", file=sys.stderr)
        return 2

    connectors = load_connectors(harness)
    report, missing = {}, 0
    for cls, skills in sorted(collect_requires().items()):
        if cls in connectors:
            status, detail = "connector", connectors[cls]
        else:
            status, detail = check_class(cls)
        if status in ("missing", "unknown"):
            missing += 1
        report[cls] = {"status": status, "detail": detail, "skills": skills}

    secrets = secrets_report(report)
    secrets_missing = [s["name"] for s in secrets if not s["found"]]
    if as_json:
        print(json.dumps({"harness": harness, "classes": report, "missing": missing, "secrets": secrets}, indent=2))
    else:
        for cls, r in report.items():
            print(f"{r['status']:<9} {cls:<28} {r['detail']}  <- {', '.join(r['skills'])}", file=sys.stderr)
        for sec in secrets:
            state = f"found     {sec['name']:<28} {sec['source']}{' (' + sec['service'] + ')' if sec['service'] else ''}" if sec["found"] else \
                f"missing   {sec['name']:<28} set it: {sec['set']}"
            print(f"{state}  <- {', '.join(sec['classes'] or sec['readers'])}", file=sys.stderr)
        print(json.dumps({"harness": harness, "classes": len(report), "missing": missing,
                          "secrets_missing": secrets_missing}))
    return 1 if (strict and missing) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
