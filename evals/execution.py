#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The execution kit: what runs one model attempt in the eval container, shared by the lab's runner and the
runtime's lab facade (runtime/lab.py).

A run of a skill, in the lab or in the runtime, is made the same way: a fresh folder, the skill staged by
scripts/stage_skills.py, the adapter's run-prompt.sh started in the container of evals/executor.py, the
credential passed by name, the pause on the account limit, the shared lock, the refusals, the replacement of
passed values in what the run left, and the stopping of everything the run started. This file holds those
functions and the constants they read. The control of the attempts of one run is evals/run_attempts.py, loaded
through load_attempts().

What this file is not. It holds nothing of the event runner (options, case files, variants, the baseline and its
checks, the grading, the evidence lines, resuming, reports): those stay in evals/eval_run.py, and nothing here
calls them. It imports the measurement modules and never edits them: redaction_values() and early_end() are
those of evals/measure.py, re-exported, so a measurement-side change to them changes production redaction and
the early end, by design. The file is not one of the measurement fingerprint's files (the retries, the locks and
the pacing are infrastructure, decision D1 of the architecture-fix plan): a change to it asks for no new
measurement version.

__all__ lists the names the runtime's facade may read; STATUS_NAMES lists the names of evals/eval_status.py it
may read through load_status(). eval_run.py loads this file by path and binds every name defined here into its
own namespace, so its code and its tests read them as before; a test that replaces a name the kit reads for
itself (EXECUTOR, LOCK_DIR, PAUSE_CLOCK, ...) replaces it on this module.

Usage (a library):
  python3 evals/execution.py --help        print this text

Standard library only. Runs on Python 3.9.
"""
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

# What the runtime's facade may read of this module. Add a name here only when it is not measurement.
__all__ = (
    # where things are, and which executor is in use ("container" for every real run; a test sets "host")
    "ROOT", "EXECUTOR",
    # modules of the lab, loaded by path
    "load_executor", "load_status", "load_attempts",
    # the adapter's data and what a run sees of the skills
    "adapter_eval", "harness_settings", "settings_in", "stage_run",
    # credentials by name, and the environment of a contained command
    "resolve_pass_env", "contained_env", "credential_label",
    # the fresh folder of a run, and its way back
    "new_run_root", "return_run", "return_all_runs",
    # running: the fixture commit, the adapter, the stopping of what was started
    "isolate_git", "run_failure", "probe_call", "stop_all_groups", "STOPPING",
    # what the host may read after a run, and what the run did to its folder
    "run_files", "readable", "file_index", "changes", "read_text", "run_ending",
    # passed values replaced in what a run leaves, and the early end (both are those of evals/measure.py)
    "redact_folder", "redaction_values", "early_end",
    # how an attempt failed
    "account_limit", "provider_refusal", "auth_refusal",
    # the control of the loop that is shared with every runner process of the machine
    "Slots", "start_pause", "wait_while_paused", "RETRY_KINDS", "RETRY_PAUSE", "KEPT_PREFIXES",
    # one command in the container of a run, with no model and no credential
    "run_group", "SETUP_TIMEOUT",
)
# The names of evals/eval_status.py the runtime reads: the gate file, a skill's identity and its standing.
STATUS_NAMES = ("load_gate", "event_config", "skill_version", "content_hash", "fingerprint_problem", "GATE_REL",
                "all_status", "skill_evidence")
# Names of evals/measure.py this module re-exports, read on first use (a command that measures nothing runs
# without that module).
MEASURE_EXPORTS = ("early_end", "redaction_values")


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
STATUS_SCRIPT = os.path.join(HERE, "eval_status.py")
EXECUTOR_SCRIPT = os.path.join(HERE, "executor.py")  # where a run's commands execute: a container
STAGE_SCRIPT = os.path.join(HERE, "..", "scripts", "stage_skills.py")  # what a run sees of the skills: staged copies
# "container" for every real run; the unit tests set "host" to drive stand-in adapters without docker.
EXECUTOR = "container"  # content hash and the per-skill record

SETUP_TIMEOUT = 300  # seconds per setup command


def die(msg, code=2):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_executor():
    """evals/executor.py as a module."""
    name = "workbench_eval_executor"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, EXECUTOR_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


STAGE_LOCK = threading.Lock()


def load_stage():
    """scripts/stage_skills.py as a module: the one place that copies a skill for a model, shared with the installers."""
    name = "workbench_stage_skills"
    with STAGE_LOCK:  # runs stage from several threads: the module is whole before any of them sees it
        if name not in sys.modules:
            if not os.path.isfile(STAGE_SCRIPT):
                die("scripts/stage_skills.py is missing: run this script from a checkout of the workbench.")
            spec = importlib.util.spec_from_file_location(name, STAGE_SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[name] = module
    return sys.modules[name]


def adapter_eval(harness, required=True):
    """The eval block of an adapter, which lives in its own file, adapters/<harness>/eval.json: {"skills_dir",
    "settings", "account_limit", "refusal_markers"}. What the runner must know about a harness to stage a case folder for it and to read what
    it left; it is data of the adapter, never code here, and its one home. "account_limit" (optional) is what the
    harness prints when the account of its tier is exhausted; "refusal_markers" (optional) what it prints when the
    provider declines a request on policy grounds. With required=False a missing or unreadable eval.json gives None
    (a plan that runs nothing)."""
    path = os.path.join(ROOT, "adapters", harness, "eval.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError, AttributeError):
        cfg = None
    if cfg is None:
        if required:
            die(f"adapters/{harness}/eval.json is missing or unreadable: it names where the harness discovers skills "
                "(\"skills_dir\") and which names carry its settings (\"settings\"). See AGENTS.md, Adding an adapter.")
        return None
    skills_dir, settings = cfg.get("skills_dir") if isinstance(cfg, dict) else None, (cfg.get("settings") if isinstance(cfg, dict) else None)
    parts = skills_dir.split("/") if isinstance(skills_dir, str) else []
    if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9._-]+", p) or p in (".", "..", ".git") for p in parts):
        die(f"adapters/{harness}/eval.json: skills_dir must be a relative folder of at least two parts, "
            "such as .tool/skills (the shared references are staged beside it).")
    if not isinstance(settings, list) or not all(isinstance(n, str) and n and "/" not in n and n not in (".", "..", ".git")
                                                 for n in settings):
        die(f"adapters/{harness}/eval.json: settings must list file or folder names, without a folder.")
    texts = {}
    for key, what in (("account_limit", "its account is exhausted"), ("refusal_markers", "the provider declines a request")):
        texts[key] = cfg.get(key, [])
        if not isinstance(texts[key], list) or not all(isinstance(m, str) and m.strip() for m in texts[key]):
            die(f"adapters/{harness}/eval.json: {key} must list the texts the harness prints when {what}.")
    return {"skills_dir": skills_dir, "settings": list(settings), **texts}


def harness_settings():
    """Every name that carries a harness's settings at project level: the "settings" lists of all eval adapters.
    A fixture carries none of them, whichever harness runs it: one runner may read another tool's folder."""
    names = set()
    for manifest in sorted(glob.glob(os.path.join(ROOT, "adapters", "*", "eval.json"))):
        cfg = adapter_eval(os.path.basename(os.path.dirname(manifest)), required=False)
        names.update(cfg["settings"] if cfg else ())
    return names


def settings_in(cwd, names):
    """The first path of a case folder, outside .git, whose name carries harness settings; None when there is none."""
    for dp, dns, fns in os.walk(cwd):
        if dp == cwd and ".git" in dns:
            dns.remove(".git")
        dns.sort()
        for n in sorted(dns + fns):
            if n in names:
                return os.path.relpath(os.path.join(dp, n), cwd).replace(os.sep, "/")
    return None


def case_platforms(case, platform=None):
    """The platforms whose reference a run of the case is given: the case's own "platforms" and, for a case of a
    platform's case file (--platform), that platform."""
    names = [n for n in case.get("platforms") or [] if isinstance(n, str)]
    return sorted(set(names) | ({platform} if platform else set()))


def stage_run(case_dir, eval_cfg, variant_dir, deps, case, platform=None):
    """Stage what one run sees of the skills, into its case folder. Returns the paths staged, relative to the
    case folder, and the manifest of scripts/stage_skills.py.

    The skill under test only when the variant has it (variant_dir); the dependency skills always. The shared
    references the skill under test cites, and the references of the platforms the case names (case_platforms),
    only with the skill: a run without it gets no shared reference, even one that brings dependency skills."""
    skills = ([variant_dir] if variant_dir else []) + list(deps)
    if not skills:
        return [], None
    stage = load_stage()
    skills_dir = os.path.join(case_dir, *eval_cfg["skills_dir"].split("/"))
    manifest = stage.stage(skills, skills_dir, root=ROOT, references="cited" if variant_dir else "none",
                           cite_from=[variant_dir] if variant_dir else [],
                           platforms=case_platforms(case, platform) if variant_dir else [])
    staged = [os.path.relpath(os.path.join(skills_dir, name), case_dir) for name in manifest["skills"]]
    if manifest["shared_dir"]:
        staged.append(os.path.relpath(manifest["shared_dir"], case_dir))
    exclude_from_git(case_dir, staged)
    return staged, manifest


def exclude_from_git(case_dir, staged):
    """Add the staged paths to the exclude list of the case's repository, so that `git status` in a run shows
    what the run did and `git add -A` does not commit a copy of the skill. Each path exactly, never its
    parent: a file a run writes beside them is still seen."""
    info = os.path.join(case_dir, ".git", "info")
    if not staged or not os.path.isdir(os.path.join(case_dir, ".git")) or not host_may_touch(case_dir, os.path.join(case_dir, ".git")):
        return
    os.makedirs(info, exist_ok=True)
    path = os.path.join(info, "exclude")
    if os.path.lexists(path) and not host_may_touch(case_dir, path):
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n# staged by the eval runner: the skills this run is given\n")
        f.writelines(f"/{rel.replace(os.sep, '/')}/\n" for rel in staged)


MEASURE_SCRIPT = os.path.join(HERE, "measure.py")
MEASURE_LOCK = threading.Lock()


def load_measure():
    """evals/measure.py as a module, loaded once and on first use: a command that measures nothing (the case
    preflight, a plan) runs without it, as in a case folder that brings this script alone."""
    name = "workbench_eval_measure"
    with MEASURE_LOCK:
        if name not in sys.modules:
            if not os.path.isfile(MEASURE_SCRIPT):
                die("evals/measure.py is missing: run this script from a checkout of the workbench.")
            spec = importlib.util.spec_from_file_location(name, MEASURE_SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[name] = module
    return sys.modules[name]


ATTEMPTS_SCRIPT = os.path.join(HERE, "run_attempts.py")
ATTEMPTS_LOCK = threading.Lock()


def load_attempts():
    """evals/run_attempts.py as a module, loaded once and on first use: the control of a run's attempts, which
    this runner and the runtime's lab facade both call. Not a measurement file. A command that runs no model (the
    case preflight, a plan) runs without it, as in a case folder that brings this script alone."""
    name = "workbench_eval_run_attempts"
    with ATTEMPTS_LOCK:
        if name not in sys.modules:
            if not os.path.isfile(ATTEMPTS_SCRIPT):
                die("evals/run_attempts.py is missing: run this script from a checkout of the workbench.")
            spec = importlib.util.spec_from_file_location(name, ATTEMPTS_SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[name] = module
    return sys.modules[name]


def load_status():
    """evals/eval_status.py as a module: the content hash, the case hash and the forms of an evidence line are
    defined there, once."""
    if not os.path.isfile(STATUS_SCRIPT):
        die("evals/eval_status.py is missing: run this script from a checkout of the workbench.")
    spec = importlib.util.spec_from_file_location("workbench_eval_status", STATUS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_pass_env(names):
    """Fill a --pass-env variable missing from the environment from the workbench's secret resolver
    (providers/secrets/resolver.py: the OS secret store), so a key kept there reaches the runs
    without an export. The names come from the caller (the flags, and floor_pass_env and
    strong_pass_env of the gate file, their one home): each is checked against the secrets the
    adapters register in the "secrets" list of their adapter.json, and no name is taken from that
    registry. Only secrets whose registered readers include eval_run.py are filled; other names and
    values that are not found are left alone."""
    path = os.path.join(ROOT, "providers", "secrets", "resolver.py")
    missing = [n for n in names if not os.environ.get(n)]
    if not missing or not os.path.isfile(path):
        return []
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    resolver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = resolver  # dataclasses look their module up here
    spec.loader.exec_module(resolver)
    # The core's registry holds the providers' credentials; a model provider's key is registered by the
    # adapter that reads it, and the resolver merges a manifest only when it is handed one.
    for manifest in sorted(glob.glob(os.path.join(ROOT, "adapters", "*", "adapter.json"))):
        try:
            resolver.register_file(manifest)
        except ValueError as e:
            die(f"the secrets list of {os.path.relpath(manifest, ROOT)} is not valid: {e}", 2)
    filled = []
    for name in missing:
        secret = resolver.REGISTRY.get(name)
        # Only a secret registered for eval runs is filled: a provider's credential never reaches a model.
        if secret is None or not any(r.startswith("evals/eval_run.py") for r in secret.readers):
            continue
        found = resolver.resolve(name)
        if found:
            os.environ[name] = found[0]
            filled.append(f"{name} ({found[1]})")
    return filled


# Credentials in the environment would sign gh, npm or git hosts back in.
TOKEN_VARS = {"GH_TOKEN", "GITHUB_TOKEN", "VCS_GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
              "NPM_TOKEN", "NODE_AUTH_TOKEN"}
# The only variables a model run, a setup or the grader receives from the caller, besides --pass-env.
ENV_ALLOW = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "TMPDIR", "TZ",
             "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE"}


def repo_paths():
    """The repository's absolute path as given and with links resolved (on some systems /var is a link)."""
    return {ROOT, os.path.realpath(ROOT)}


def temp_base(names=()):
    """The folder run folders are created in: the system's temporary folder, or /tmp or /var/tmp when that one
    is inside the repository, under a folder that holds a repository, an instruction file or a skills folder,
    or has the repository's folder name or one of names (the skill under test) in its path."""
    words = [w.lower() for w in (os.path.basename(os.path.realpath(ROOT)), *names) if w]
    for base in (tempfile.gettempdir(), "/tmp", "/var/tmp"):
        real = os.path.realpath(base)
        if not os.path.isdir(real) or not os.access(real, os.W_OK):
            continue
        if any(real == root or real.startswith(root + os.sep) for root in repo_paths()) or any(w in real.lower() for w in words):
            continue
        parent, clean = real, True
        while clean:
            clean = not any(os.path.exists(os.path.join(parent, marker)) for marker in (".git", "AGENTS.md", "skills"))
            if os.path.dirname(parent) == parent:
                break
            parent = os.path.dirname(parent)
        if clean:
            return real
    die("no temporary folder outside the repository to run the cases in: set TMPDIR to one whose parents hold no "
        ".git, AGENTS.md or skills folder.", 1)


# Temporary run folders in use -> where their content goes back to, so a stop returns every one of them.
RUN_ROOTS, RUN_ROOTS_LOCK = {}, threading.Lock()


def new_run_root(dest, out_name="outputs", names=()):
    """A fresh folder outside the repository for one model run or grading: case/ (the working folder), out/
    (the adapter's output) and prompt.md. return_run() moves them to dest/cwd, dest/<out_name> and dest/prompt.md."""
    with RUN_ROOTS_LOCK:
        if STOPPING.is_set():
            raise RuntimeError("stopping: no new run is started")
        root = tempfile.mkdtemp(prefix="eval-", dir=temp_base(names))
        RUN_ROOTS[root] = (dest, out_name)
    os.makedirs(os.path.join(root, "case"))
    os.makedirs(os.path.join(root, "out"))
    return root


def return_run(root):
    """Move a temporary run folder's content into the workspace and remove it. Safe to call twice."""
    with RUN_ROOTS_LOCK:  # held for the move, so a stop waits for a move in progress instead of cutting it
        entry = RUN_ROOTS.pop(root, None)
        if entry is None:
            return
        dest, out_name = entry
        os.makedirs(dest, exist_ok=True)
        for name, final in (("case", "cwd"), ("out", out_name), ("prompt.md", "prompt.md")):
            src, target = os.path.join(root, name), os.path.join(dest, final)
            if not os.path.lexists(src):
                continue
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            elif os.path.lexists(target):
                os.remove(target)
            shutil.move(src, target)
        shutil.rmtree(root, ignore_errors=True)


def return_all_runs():
    for root in list(RUN_ROOTS):
        return_run(root)


def provider_refusal(out_dir, markers):
    """The provider's refusal message when the run ended because the provider declined the request, else None.
    markers are the adapter's own words for it ("refusal_markers" in its eval.json)."""
    for name in ("response.md", "raw.json", "error.log", "stderr.log"):
        text = read_text(os.path.join(out_dir, name), 200000)
        for marker in markers or ():
            at = text.find(marker)
            if at != -1:
                return text[max(0, at - 80):at + 160].replace("\n", " ").strip()
    return None


# A provider that refuses the credential itself: an HTTP status 401, or 403, in the words a runner or an API
# prints it ("HTTP 401", "statusCode":401, "API Error: 401", 401 Unauthorized, 401 "User not found.") or the
# error type of a 401 ("authentication_error"). A 401 is always the credential; a 403 is only when the text
# around it names a key, a token or a credential (another 403 is a policy or a region, and is retried).
AUTH_STATUS = re.compile(
    r"(?i)(?:\bHTTP(?:/[\d.]+)?\s+(40[13])\b"
    r"|\bstatus(?:[ _-]?code)?\"?\s*[:=]\s*\"?(40[13])\b"
    r"|\"api_error_status\"\s*:\s*(40[13])\b"
    r"|\bAPI Error:?\s*(40[13])\b"
    r"|(?<![\w.-])(40[13])\s+(?:Unauthorized|Forbidden|\"))"
    r"|(\"authentication_error\")")
AUTH_KEY_WORDS = re.compile(r"(?i)\b(?:api[ _-]?)?keys?\b|\btokens?\b|\bcredentials?\b")
AUTH_WINDOW = 300  # characters on each side of a 403 in which the key must be named


def auth_refusal(out_dir):
    """"HTTP 401" or "HTTP 403" when what a failed run left shows the provider refusing its credential, else None.
    Only the status is returned, never the provider's words: a provider may echo a part of the key."""
    for name in ("error.log", "stderr.log", "raw.json", "response.md"):
        text = read_text(os.path.join(out_dir, name), 400000)
        for m in AUTH_STATUS.finditer(text):
            code = next((g for g in m.groups()[:5] if g), None) or "401"  # "authentication_error" is the 401's type
            if code == "401" or AUTH_KEY_WORDS.search(text[max(0, m.start() - AUTH_WINDOW):m.end() + AUTH_WINDOW]):
                return f"HTTP {code}"
    return None


def credential_label(harness, names):
    """The variables a refused run received its key in, by name, each with the secret store username its
    adapter registers for it ("secrets" of adapters/<harness>/adapter.json); never a value."""
    try:
        with open(os.path.join(ROOT, "adapters", harness, "adapter.json"), encoding="utf-8") as f:
            secrets = json.load(f).get("secrets") or []
    except (OSError, ValueError, AttributeError):
        secrets = []
    store = {s.get("name"): s.get("store_username") for s in secrets if isinstance(s, dict)}
    if not names:
        return "no variable (the harness's own login)"
    return ", ".join(name + (f" (secret store username {store[name]!r})" if store.get(name) else "") for name in names)


def contained_env(run_dir, pass_env=()):
    """Environment for a model run, a setup or the grader: an allowlist, git local only, gh and npm signed out."""
    contain = os.path.join(run_dir, ".contain")
    gh_dir = os.path.join(contain, "gh")
    os.makedirs(gh_dir, exist_ok=True)
    npmrc, gitconfig = os.path.join(contain, "npmrc"), os.path.join(contain, "gitconfig")
    for path in (npmrc, gitconfig):
        open(path, "w").close()
    env = {k: v for k, v in os.environ.items()
           if (k in ENV_ALLOW or k.startswith("LC_") or k in pass_env) and k not in TOKEN_VARS}
    # Nothing tells the run where the repository is: PATH entries inside it go, an allowlisted variable that
    # points into it goes, and TMPDIR is the base the run folders are made in. A --pass-env variable is the
    # caller's own choice and stays as it is.
    inside = lambda value: any(root in value for root in repo_paths())
    if "PATH" in env and "PATH" not in pass_env:
        env["PATH"] = os.pathsep.join(p for p in env["PATH"].split(os.pathsep) if not inside(p))
    for k in [k for k, v in env.items() if k not in pass_env and inside(v)]:
        del env[k]
    if "TMPDIR" not in pass_env:
        env["TMPDIR"] = temp_base()
    env.update(GIT_ALLOW_PROTOCOL="file", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=gitconfig,
               GIT_AUTHOR_NAME="eval", GIT_AUTHOR_EMAIL="eval@localhost",
               GIT_COMMITTER_NAME="eval", GIT_COMMITTER_EMAIL="eval@localhost",
               GH_CONFIG_DIR=gh_dir, NPM_CONFIG_USERCONFIG=npmrc)
    return env


# Process groups started and not yet ended, so that stopping this script stops every one of them.
GROUPS, GROUPS_LOCK, STOPPING = set(), threading.Lock(), threading.Event()
STOP_GRACE = 5.0  # seconds between TERM and KILL; an adapter needs about two to stop its own runner


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # only processes that already ended and wait to be reaped
        return False
    return True


def stop_group(pgid, proc=None, grace=STOP_GRACE):
    """End a process group: TERM, then KILL for what is still there after the grace period."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + grace
    if proc is not None:
        try:
            proc.wait(timeout=grace)  # reaps the leader, so the check below sees only what outlived it
        except subprocess.TimeoutExpired:
            pass
    while group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def stop_all_groups(grace=STOP_GRACE):
    """End every group still registered; no new one starts afterwards."""
    STOPPING.set()
    with GROUPS_LOCK:
        pending, containers = list(GROUPS), list(CONTAINERS)
    for name in containers:  # first, so that the work stops; their docker clients end with them
        try:
            load_executor().remove(name)
        except Exception:  # stopping goes on whatever one removal does
            pass
    for pgid in pending:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + grace
    while any(group_alive(p) for p in pending) and time.monotonic() < deadline:
        time.sleep(0.1)
    for pgid in pending:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


CONTAINERS = set()  # names of containers started and not yet ended; guarded by GROUPS_LOCK


def run_group(cmd, timeout, cwd=None, env=None, box=None):
    """subprocess.run for a command in a session of its own: its whole process group ends on a timeout
    (subprocess.TimeoutExpired is raised) and when the command returns, so nothing it started outlives it.

    box = {"root", "runner", "pass", "network"} runs the command in a container (evals/executor.py): root is
    the run's folder, the only thing it can change; runner is the one run-prompt.sh the command starts, the
    only file of the workbench the container sees. The container is removed by name when the command
    returns, times out or the script is stopped, since ending the docker client does not end it. A command
    passed the variable a key proxy holds starts that key proxy first (executor.held_route(), keyproxy()); when
    it cannot start, the command fails as an infrastructure failure, before any container runs."""
    container = None
    if box is not None and EXECUTOR == "container":
        executor = load_executor()
        held = executor.held_route(box.get("pass") or (), env, box.get("network") or "none")
        if held:
            try:  # the key stays there; the run gets a placeholder and the proxy's address
                executor.keyproxy(env=env, name=held)
            except executor.ExecutorError as e:  # an infrastructure failure of this command, never a score
                return subprocess.CompletedProcess(cmd, 1, "", f"Error: {e}\n")
        cmd, container = executor.command(cmd, box["root"], cwd=cwd, env=env, runner=box.get("runner"),
                                          pass_names=box.get("pass") or (), network=box.get("network") or "none")
        cwd = None
    try:
        return _run_group(cmd, timeout, cwd, env, container)
    finally:
        if container:
            load_executor().remove(container, env=env)
            with GROUPS_LOCK:
                CONTAINERS.discard(container)


def _run_group(cmd, timeout, cwd, env, container):
    with GROUPS_LOCK:
        if STOPPING.is_set():
            raise subprocess.TimeoutExpired(cmd, 0)
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
        GROUPS.add(proc.pid)
        if container:
            CONTAINERS.add(container)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_group(proc.pid, proc)
            proc.kill()
            proc.communicate()
            raise
        stop_group(proc.pid, grace=2.0)  # what the command left running in the background
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    finally:
        with GROUPS_LOCK:
            GROUPS.discard(proc.pid)


def run_failure(runner, prompt_path, cwd, model, out, env=None, timeout=900, max_cost=None, web=False,
                start_dir=None, box=None, no_tools=False):
    """Run the adapter once. Returns None when it exited 0, else why it failed: an infrastructure failure,
    never a score (the adapter exits non-zero when the provider or the harness fails, not when the answer is poor).
    The adapter is told nothing about skills: the runner staged them in <cwd> before this call."""
    cmd = ["bash", runner, "--prompt-file", prompt_path, "--cwd", cwd, "--model", model, "--out", out]
    if max_cost:
        cmd += ["--max-cost-usd", max_cost]
    if web:
        cmd += ["--allow-web"]
    if no_tools:  # a grading call: the model judges text and is given nothing to act with
        cmd += ["--no-tools"]
    try:
        # start_dir: the adapter's shell exports the folder it starts in as OLDPWD once it changes to <cwd>.
        r = run_group(cmd, timeout, cwd=start_dir, env=env, box=box)
    except subprocess.TimeoutExpired:
        with open(os.path.join(out, "error.log"), "w", encoding="utf-8") as f:
            f.write(f"stopped after --timeout {timeout}s\n")
        return f"timeout: stopped after {timeout}s"
    if r.returncode != 0:
        with open(os.path.join(out, "error.log"), "w", encoding="utf-8") as f:
            f.write(r.stdout + "\n" + r.stderr)
        last = [line.strip() for line in (r.stderr or r.stdout).splitlines() if line.strip()]
        return f"adapter exit {r.returncode}" + (f": {last[-1][:200]}" if last else "")
    return None


def run_prompt(*args, **kwargs):
    """True when the adapter ran the prompt; False when it failed (the reason is in <out>/error.log)."""
    return run_failure(*args, **kwargs) is None


# What an attempt of a run that was made again left, kept inside the run folder: never a part of the next attempt.
KEPT_PREFIXES = ("early-end-", "failed-", "paused-", "before-resume-")


def staged_file(rel, staged):
    """True for a file the runner staged: one inside a path stage_run() returned (a skill's copy, the shared references)."""
    return any(rel == s or rel.startswith(s + os.sep) for s in staged)


def run_ending(out_dir):
    """How the runner says a run ended, read from the adapter's raw output when it is JSON that names it:
    {"stop_reason", "num_turns", "terminal_reason"}, the keys that are there. Kept beside the reply: an early
    end and a turn that ran to its limit look alike in the reply alone."""
    try:
        with open(os.path.join(out_dir, "raw.json"), encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if isinstance(data, list):  # a stream of events: the result is one of them
        data = next((x for x in data if isinstance(x, dict) and x.get("type") == "result"), data[-1] if data else {})
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in ("stop_reason", "num_turns", "terminal_reason")
            if isinstance(data.get(k), (str, int)) and not isinstance(data.get(k), bool)}


# Folders of a case folder the host never looks into after a run: version control, dependencies, caches.
# Whole folder names: ".git" as a substring would also skip ".github".
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv"}


def host_may_touch(cwd, path):
    """True when the host may read or write path, a path of the case folder cwd, after a run: it is not a
    symbolic link, and its real path stays inside the case folder (so no folder on the way to it is a link
    that leaves). A run can leave a link to any file of the host; followed, its target would be read here,
    outside the container, and sent to the grader's provider."""
    if os.path.islink(path):
        return False
    base, real = os.path.realpath(cwd), os.path.realpath(path)
    return real == base or real.startswith(base + os.sep)


def run_files(cwd, staged=()):
    """The files of a case folder that the host reads or writes after a run, as sorted relative paths. This is
    the one place that decides it: the list of what a run wrote, what the grader is shown and anything the
    harness rewrites in a case folder all take their paths from here.

    Left out: every symbolic link, and everything under a folder that is one; every path whose real path
    leaves the case folder; what is not a regular file (a named pipe would block the reader); the folders of
    SKIP_DIRS; bytecode and system files; and what the runner staged."""
    found = []
    for dp, dns, fns in os.walk(cwd):  # os.walk does not descend into a link to a folder; such a link is dropped here too
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and host_may_touch(cwd, os.path.join(dp, d)))
        for fn in sorted(fns):
            path = os.path.join(dp, fn)
            rel = os.path.relpath(path, cwd)
            if fn.endswith(".pyc") or fn == ".DS_Store" or staged_file(rel, staged):
                continue
            if host_may_touch(cwd, path) and os.path.isfile(path):
                found.append(rel)
    return found


def readable(cwd, rel):
    """True when the host may read the one path rel of the case folder: a regular file run_files() would list
    (links, special files and paths that leave the folder are not), wherever it sits."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ".." in re.split(r"[\\/]", rel):
        return False
    path = os.path.join(cwd, rel)
    parts = os.path.normpath(rel).split(os.sep)
    on_the_way = [os.path.join(cwd, *parts[:i]) for i in range(1, len(parts))]
    return all(not os.path.islink(p) for p in on_the_way) and host_may_touch(cwd, path) and os.path.isfile(path)


def redact_folder(folder, values, staged=()):
    """Replace the passed variables' values in the files of a folder a run wrote to, in place. Only the paths
    run_files() allows are read or written: never a symbolic link, never a path that leaves the folder, never
    version control, dependency or cache folders. Returns the number of replacements."""
    total = 0
    for rel in run_files(folder, staged) if values and os.path.isdir(folder) else ():
        path = os.path.join(folder, rel)
        try:
            if os.path.getsize(path) > REDACT_LIMIT:
                continue
            with open(path, "rb") as f:
                data = f.read()
            new, count = load_measure().replace_values(data, values)
            if count:
                with open(path, "wb") as f:
                    f.write(new)
                total += count
        except OSError:
            continue
    return total


def changes(cwd, before, staged=()):
    """What a run did to the files of its case folder, against the index taken before it, by content:
    {"created", "modified", "deleted", "unchanged"}, each a sorted list of relative paths. A file rewritten
    with the same bytes is unchanged; a file that is gone, or that a link replaced, is deleted."""
    after = file_index(cwd, staged)
    return {"created": sorted(p for p in after if p not in before),
            "modified": sorted(p for p in after if p in before and after[p] != before[p]),
            "deleted": sorted(p for p in before if p not in after),
            "unchanged": sorted(p for p in after if before.get(p) == after[p])}


def isolate_git(cwd, env, box=None):
    """Give the case its own repository, so git commands in a run stay inside it.

    Without one, `git add -A` or `git commit` from the case folder reaches the enclosing
    repository (the workbench itself) and commits whatever is uncommitted there. The contained
    environment also drops GIT_DIR and GIT_INDEX_FILE, which would point git at the workbench.
    """
    if os.path.isdir(os.path.join(cwd, ".git")):
        return
    for args in (["init", "-q"], ["add", "-A"], ["-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "fixture"]):
        r = run_group(["git", *args], SETUP_TIMEOUT, cwd=cwd, env=env, box=box)
        if r.returncode != 0:
            raise subprocess.CalledProcessError(r.returncode, ["git", *args], r.stdout, r.stderr)


def file_index(cwd, staged=()):
    """{relative path: sha256 of the bytes} of the files of a case folder (run_files()): taken before a run and
    after it, the two say what the run created, changed and deleted. A modification time would call a file
    that was overwritten and restored "changed", and cannot see a deletion."""
    idx = {}
    for rel in run_files(cwd, staged):
        h = hashlib.sha256()
        try:
            with open(os.path.join(cwd, rel), "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
        except OSError:
            continue
        idx[rel] = h.hexdigest()
    return idx


# What a run leaves is read up to this size; a larger file is left as it is.
REDACT_LIMIT = 50000000  # bytes


def read_text(path, limit=4000):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except OSError:
        return ""


# Where the runner processes of one machine meet: the slot files of the counted locks and the pause files.
# None: <temporary base>/wb-eval-locks. Nothing a model run sees: a container mounts its own run folder only.
LOCK_DIR = None
SLOT_POLL = 0.2       # seconds between two looks for a free slot
RETRY_PAUSE = 5.0     # seconds before a run whose adapter failed is made again, times the number of the attempt
PAUSE_POLL = 5.0      # seconds between two looks at a pause
PROBE_SECONDS = 600   # a paused account is tried again this often, by one process at a time
PROBE_TIMEOUT = 180
PROBE_PROMPT = "Reply with the single word: ok\n"


def lock_dir():
    path = LOCK_DIR or os.path.join(temp_base(), "wb-eval-locks")
    os.makedirs(path, exist_ok=True)
    return path


class Slot:
    """One of n places of a counted lock that every runner process of the machine shares: a file per place,
    held with an advisory lock for as long as the place is taken, so a process that dies frees its places.
    Several `eval_run.py` started side by side (one per skill) then keep to one total, which --jobs alone,
    a limit per process, cannot do."""

    def __init__(self, kind, n):
        self.kind, self.n, self.fd = kind, n, None

    def __enter__(self):
        import fcntl
        folder = lock_dir()
        while True:
            if STOPPING.is_set():
                raise RuntimeError("stopping: no new run is started")
            for i in range(self.n):
                fd = os.open(os.path.join(folder, f"{self.kind}-{i}.lock"), os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    os.close(fd)
                    continue
                self.fd = fd
                return self
            time.sleep(SLOT_POLL)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)  # closing the file releases the place
            self.fd = None
        return False


class Slots:
    """The places one model call holds: a place of the tier's web lock when it runs on the open network, then
    a place of the total. Always taken in that order, so two calls never wait for each other."""

    def __init__(self, control, tier, web=False):
        self.slots = ([Slot(f"web-{tier}", control["web_jobs"][tier])] if web else []) + [Slot("total", control["total_jobs"])]

    def __enter__(self):
        taken = []
        try:
            for slot in self.slots:
                taken.append(slot.__enter__())
        except BaseException:
            for slot in taken:
                slot.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        for slot in reversed(self.slots):
            slot.__exit__(None, None, None)
        return False


def account_limit(out_dir, markers):
    """The words of an exhausted account in what a failed call left (the markers are the adapter's data:
    "account_limit" of its eval.json), else None."""
    for name in ("response.md", "raw.json", "error.log", "stderr.log"):
        text = read_text(os.path.join(out_dir, name), 400000)
        for marker in markers or ():
            if marker and marker in text:
                return marker
    return None


def pause_path(key):
    return os.path.join(lock_dir(), "pause-" + re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")


# The clock and the wait of a pause. Every look at a pause reads the time through PAUSE_CLOCK and waits through
# PAUSE_SLEEP, so that a test drives a pause step by step, with no real waiting and no dependence on the time
# of day.
PAUSE_CLOCK = time.time
PAUSE_SLEEP = time.sleep


def read_pause(path):
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def last_probe(path, state):
    """When the paused account was last tried: the newest of the pause's start and the time in its probe file.
    The probe time lives in a file of its own (<pause file>.probed), so that a process that records a probe
    never rewrites the pause file: the time an operator gives with --unpause --at cannot be lost under it."""
    try:
        with open(path + ".probed", encoding="utf-8") as f:
            probed = float(f.read().strip() or 0)
    except (OSError, ValueError):
        probed = 0
    return max(state.get("since") or 0, probed)


def clock(ts):
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def start_pause(key, what):
    """Pause every run and grading on the account `key`: the pause is a file under the shared lock folder,
    which every runner process of the machine reads before it starts a model call. True when this call made
    it (another run may have met the limit first)."""
    path = pause_path(key)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    now = PAUSE_CLOCK()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"key": key, "since": now, "until": None, "what": what}, f)
    print(f"PAUSED {clock(now)}: the account of {key} is exhausted ({what}). Every run and grading on it waits; "
          f"nothing is retried into the limit. It resumes when a probe call succeeds (one every {PROBE_SECONDS}s) or at "
          "the time given with: python3 evals/eval_run.py --unpause [--at <HH:MM or YYYY-MM-DDTHH:MM>]", file=sys.stderr)
    return True


def wait_while_paused(key, probe=None):
    """Block while the account `key` is paused. It ends at the time the operator gave (--unpause --at), when
    the operator removed the pause (--unpause), or when a probe call succeeds: probe() makes one small model
    call, by one process at a time, at most once every PROBE_SECONDS, and never once a time is given. Returns
    True when it waited. Only start_pause and --unpause write the pause file; a probe writes its own file."""
    import fcntl
    path, waited = pause_path(key), False
    while os.path.exists(path):
        if STOPPING.is_set():
            raise RuntimeError("stopping: no new run is started")
        waited = True
        state, now = read_pause(path), PAUSE_CLOCK()
        until = state.get("until")
        if isinstance(until, (int, float)):
            if now >= until:
                try:
                    os.remove(path)
                except OSError:
                    pass
                print(f"RESUMED {clock(now)}: the time given for the account of {key} has come", file=sys.stderr)
                break
        elif probe and now - last_probe(path, state) >= PROBE_SECONDS:
            fd = os.open(path + ".probe", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
            else:
                try:
                    state = read_pause(path)
                    if state and not state.get("until") and PAUSE_CLOCK() - last_probe(path, state) >= PROBE_SECONDS:
                        with open(path + ".probed", "w", encoding="utf-8") as f:
                            f.write(repr(PAUSE_CLOCK()))
                        if probe():
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                            print(f"RESUMED {clock(PAUSE_CLOCK())}: a probe call on the account of {key} succeeded", file=sys.stderr)
                            break
                finally:
                    os.close(fd)
        PAUSE_SLEEP(PAUSE_POLL)
    return waited


def probe_call(runner, model, pass_env):
    """One small model call on a paused account: True when the adapter ran it."""
    root = tempfile.mkdtemp(prefix="eval-probe-", dir=temp_base())
    try:
        os.makedirs(os.path.join(root, "case"))
        os.makedirs(os.path.join(root, "out"))
        prompt = os.path.join(root, "prompt.md")
        with open(prompt, "w", encoding="utf-8") as f:
            f.write(PROBE_PROMPT)
        return run_prompt(runner, prompt, os.path.join(root, "case"), model, os.path.join(root, "out"),
                          env=contained_env(root, pass_env), timeout=PROBE_TIMEOUT, start_dir=root,
                          box={"root": root, "runner": runner, "pass": pass_env, "network": "proxy"})
    except (RuntimeError, subprocess.SubprocessError, OSError):
        return False
    finally:
        shutil.rmtree(root, ignore_errors=True)


RETRY_KINDS = {"timeout": "timeouts", "refused": "refusals", "adapter": "adapter_failures", "early_end": "early_ends"}


def __getattr__(name):
    if name in MEASURE_EXPORTS:
        return getattr(load_measure(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__" and any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
