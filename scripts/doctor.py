#!/usr/bin/env python3
"""Report which environment requirement classes are satisfied.

Usage: python3 scripts/doctor.py [--harness <name>] [--json] [--strict]
       python3 scripts/doctor.py --unattended [--project <dir>] [--min-free-gib <n>] [--ack-lease] [--json] [--strict]

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
  --strict          exit 1 when any required class is missing (with --unattended: or when an unattended check warns)
  --unattended      also run the checks for a machine that runs the task runtime for weeks with nobody logged in (package P-OPS,
                    scripts/doctor_ops.py): the user manager's linger on Linux, whether a macOS scheduler job can read the sources
                    folder, free disk on data_dir and sources_dir, the log limits of the harness's proxy containers, whether the
                    OS secret store answers, and the eval image with the command that sets it up. Each check says what it can and
                    cannot verify (see the text of scripts/doctor_ops.py); in --json they are the "unattended" key. It asks docker
                    to list and inspect the harness's containers, which no other mode does.
  --project <dir>   with --unattended: the project whose runtime.json names data_dir and sources_dir
  --min-free-gib <n>  with --unattended: the free space under which a disk warns (default 5)
  --ack-lease       with --unattended and --project: acknowledge a takeover of another host's lease (removes the record
                    <data_dir>/lease-takeover.json, which the `lease` check warns about), then run the checks
  --help            show this text

It also reports the eval image (evals/image-lock.json, evals/executor.py), in one of four states, and never pulls or
builds it:
  published and present     the lock file names a published image for this checkout's definition and this platform,
                            and it is on this machine with that repo digest
  published, not pulled     the lock names one and it is not here: run `python3 scripts/image_lock.py pull`
                            (it verifies the provenance, then pulls)
  no published image        the lock names none for this definition; an image built locally is here, so evidence
                            measured in it is local-only (it holds on this machine only)
  missing                   nothing is here (run `python3 evals/executor.py ensure`), docker cannot be reached,
                            or the lock file is not well formed ("lock unreadable": a lock that cannot be read is
                            never taken for an empty one)
The image does not change the exit code. In --json it is the "image" key: {"state", "detail"}, and, when it is not present, "setup": the
command to run (the first pull of the published image is an explicit step, never automatic: decision D39).

It also lists every secret registered in providers/secrets/resolver.py or by an adapter (the
"secrets" list of its adapter.json): found, missing, locked or unsafe, where
it was found (environment, the credentials directory or the OS secret store), which classes read it and how to set it. "locked" means the OS
secret store raised instead of answering (a locked keychain or collection, or no backend on a machine with no desktop session): the secret
may be stored, and unlocking the store clears it; "unsafe" means the credentials directory or its file is readable by others or is a link.
It never prints a value. Missing secrets do not change the exit code; see contracts/secrets.md.

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


IMAGE_STATES = {
    "published-present": "published and present",
    "published-not-pulled": "published, not pulled: run `python3 scripts/image_lock.py pull`",
    "local-only": "no published image for this definition: built locally, evidence is local-only",
    "missing": "missing",
}


class DockerUnavailable(Exception):
    pass


def docker_inspect(args):
    """`docker image inspect <args>` as (returncode, stdout). Raises DockerUnavailable when there is no docker client or
    no daemon to ask: an image that cannot be asked about is not reported as absent."""
    try:
        r = subprocess.run(["docker", "image", "inspect", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DockerUnavailable(f"docker cannot be run: {e}") from None
    if r.returncode != 0 and "daemon" in r.stderr.lower():
        raise DockerUnavailable("the docker daemon cannot be reached")
    return r.returncode, r.stdout


def image_state(inspect=docker_inspect, root=ROOT):
    """The eval image of this checkout: {"state": one of IMAGE_STATES' keys, "detail": a sentence}. It reads the lock
    file and inspects the image; it never pulls or builds one. `inspect` is what a test replaces."""
    try:
        executor = _load("workbench_doctor_executor", os.path.join(root, "evals", "executor.py"))
        lock_module = _load("workbench_doctor_image_lock", os.path.join(root, "scripts", "image_lock.py"))
    except Exception as e:  # noqa: BLE001  (an executor that cannot be loaded is reported, not raised)
        return {"state": "missing", "detail": f"the image cannot be looked up: {e}"}
    try:
        definition, platform = executor.definition_hash(), executor.image_platform()
        wanted = lock_module.published(lock_module.read_lock(os.path.join(root, "evals", "image-lock.json")),
                                       definition, platform)
        if wanted:
            if lock_module.present(wanted, inspect):
                return {"state": "published-present", "detail": wanted["ref"]}
            return {"state": "published-not-pulled", "detail": wanted["ref"]}
        local = executor.names()["image"]
        code, _ = inspect(["--format", "{{.Id}}", local])
    except lock_module.Refused as e:
        return {"state": "missing", "detail": f"lock unreadable: {e}"}
    except DockerUnavailable as e:
        return {"state": "missing", "detail": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"state": "missing", "detail": f"the image cannot be looked up: {e}"}
    if code == 0:
        return {"state": "local-only", "detail": f"{local}; no entry for the definition {definition[:12]} in evals/image-lock.json"}
    return {"state": "missing", "detail": f"{local} is not built: run `python3 evals/executor.py ensure`"}


def image_setup(image):
    """The command that sets the eval image up when it is not present, or None (decision D39: an explicit step, never automatic and never
    in the middle of a dispatch). A published image is pulled by digest with the provenance check; a local build is the other way."""
    state, detail = image["state"], image.get("detail") or ""
    if state in ("published-present", "local-only"):
        return None
    if state == "published-not-pulled":
        return "python3 scripts/image_lock.py pull"
    if "daemon" in detail or "docker cannot be run" in detail:
        return "start docker (its client or daemon cannot be reached), then run the doctor again"
    if detail.startswith("lock unreadable"):
        return "repair evals/image-lock.json (git checkout -- evals/image-lock.json), then python3 scripts/image_lock.py pull"
    return "python3 scripts/image_lock.py pull (a published image), or python3 evals/executor.py ensure (build it here)"


def store_probe():
    """The state of the OS secret store, by the resolver's probe_store (it asks for a name nothing stores): {"state", "detail"}."""
    path = str(resolution.secret_resolver(root=ROOT))
    resolver = _load("workbench_secret_resolver_probe", path)
    folder = resolver.credentials_status()
    if folder["state"] == "unsafe":   # a refused directory hides every secret: said before the store is asked
        return {"state": "credentials-unsafe", "detail": folder["detail"]}
    return resolver.probe_store()


def load_project_config(project):
    """The two folders the unattended checks look at, from the project's docs/workbench/runtime.json: {"data_dir", "sources_dir"}, each an
    absolute path. Only these two keys are read (the file is checked as a whole by the task runtime, not here); raises when the file or a
    key is missing."""
    path = os.path.join(os.path.abspath(project), "docs", "workbench", "runtime.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for key in ("data_dir", "sources_dir"):
        value = raw.get(key) if isinstance(raw, dict) else None
        if not isinstance(value, str) or not os.path.isabs(value):
            raise ValueError(f"{path} needs {key}: an absolute path")
        out[key] = value
    return out


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
        rows.append({k: row[k] for k in ("name", "found", "state", "source", "service", "store", "detail", "classes", "readers", "set")})
    return rows


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    harness, as_json, strict = None, "--json" in argv, "--strict" in argv
    unattended, project, min_free, ack_lease = "--unattended" in argv, None, None, "--ack-lease" in argv
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--project", "--min-free-gib"):
            if i + 1 >= len(argv):
                print(f"Error: {a} needs a value.", file=sys.stderr)
                return 2
            if a == "--project":
                project = argv[i + 1]
            else:
                try:
                    min_free = float(argv[i + 1])
                except ValueError:
                    min_free = -1.0
                if min_free <= 0:
                    print("Error: --min-free-gib needs a number above 0.", file=sys.stderr)
                    return 2
            i += 2
            continue
        if a == "--harness":
            if i + 1 >= len(argv):
                print("Error: --harness needs a value, e.g. --harness claude-code", file=sys.stderr)
                return 2
            harness = argv[i + 1]
            i += 2
            continue
        if a not in ("--json", "--strict", "--unattended", "--ack-lease"):
            print(f"Error: unknown option {a!r}. See --help.", file=sys.stderr)
            return 2
        i += 1
    if harness and (not NAME_RE.fullmatch(harness) or not os.path.isdir(os.path.join(ADAPTERS, harness))):
        print(f"Error: adapter {harness!r} not found under adapters/.", file=sys.stderr)
        return 2

    if ack_lease and not (unattended and project):
        print("Error: --ack-lease goes with --unattended and --project <dir>.", file=sys.stderr)
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

    image = image_state()
    setup = image_setup(image)
    if setup:
        image = {**image, "setup": setup}
    secrets = secrets_report(report)
    secrets_missing = [s["name"] for s in secrets if not s["found"] and s["state"] == "missing"]
    secrets_locked = [s["name"] for s in secrets if s["state"] in ("locked", "unsafe")]
    checks = None
    if unattended:
        import doctor_ops
        if ack_lease:
            try:
                acknowledged = doctor_ops.ack_lease(load_project_config(project)["data_dir"])
            except (OSError, ValueError) as e:
                print(f"Error: --ack-lease could not read the project: {e}", file=sys.stderr)
                return 2
            print("lease takeover acknowledged" if acknowledged else "no lease takeover was recorded", file=sys.stderr)
        checks = doctor_ops.run_all(project=project, min_free_gib=min_free or doctor_ops.MIN_FREE_GIB, image=image,
                                    probe=store_probe, load_config=load_project_config)
    if as_json:
        out = {"harness": harness, "classes": report, "missing": missing, "image": image, "secrets": secrets}
        if checks is not None:
            out["unattended"] = checks
        print(json.dumps(out, indent=2))
    else:
        for cls, r in report.items():
            print(f"{r['status']:<9} {cls:<28} {r['detail']}  <- {', '.join(r['skills'])}", file=sys.stderr)
        shown = IMAGE_STATES[image["state"]] + ("" if image["state"] == "published-not-pulled" else f" ({image['detail']})")
        print(f"{'image':<9} {'eval image':<28} {shown}", file=sys.stderr)
        if setup:
            print(f"{'':<9} {'':<28} setup: {setup}", file=sys.stderr)
        for sec in secrets:
            if sec["found"]:
                state = f"found     {sec['name']:<28} {sec['source']}{' (' + sec['service'] + ')' if sec['service'] else ''}"
            elif sec["state"] == "locked":
                state = f"locked    {sec['name']:<28} the secret store is locked or unavailable: unlock it (it may hold this secret)"
            elif sec["state"] == "unsafe":
                state = f"unsafe    {sec['name']:<28} {sec['detail']}"
            else:
                state = f"missing   {sec['name']:<28} set it: {sec['set']}"
            print(f"{state}  <- {', '.join(sec['classes'] or sec['readers'])}", file=sys.stderr)
        if checks is not None:
            for name in ("linger", "sources_access", "disk", "proxy_logs", "lease", "secret_store", "project"):
                c = checks[name]
                print(f"{c['status']:<10} {name:<28} {c['detail']}", file=sys.stderr)
                if c.get("fix") and c["status"] in ("warn", "unverified"):
                    print(f"{'':<10} {'':<28} fix: {c['fix']}", file=sys.stderr)
        summary = {"harness": harness, "classes": len(report), "missing": missing, "image": image["state"],
                   "secrets_missing": secrets_missing, "secrets_locked": secrets_locked}
        if checks is not None:
            summary["unattended_warnings"] = sorted(n for n, c in checks.items() if c["status"] == "warn")
        print(json.dumps(summary))
    warned = bool(checks) and any(c["status"] == "warn" for c in checks.values())
    return 1 if (strict and (missing or warned)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
