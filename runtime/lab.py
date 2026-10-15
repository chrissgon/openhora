#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The lab facade: the one file of runtime/ that talks to the lab (evals/execution.py, the execution kit).

The agent runtime runs a skill in the container the skill was proven in, through the same entry: the eval
container of evals/executor.py, started by the adapter's run-prompt.sh, with the skill staged by
scripts/stage_skills.py. This file loads the execution kit, the one module the lab's runner (evals/eval_run.py)
and the runtime share, and calls the names its __all__ lists: the pause on the account limit, the shared lock,
the refusals, the early end, the replacement of passed values, and the stopping of everything a run started are
the kit's own code. The runner's own code (events, cases, baselines, grading, evidence) is not in the kit and is
not reachable from here; the status script is read through the names of the kit's STATUS_NAMES only.

The runtime has no loop of its own. The attempts of one run (prepare a fresh folder, run, classify how the attempt
failed, make it again or stop) are made by the one function the lab's runner calls too, run() of
evals/run_attempts.py, reached through the kit (load_attempts), so both hold one module object. What run_skill
adds through its hooks is the runtime's: the caller's files, the base commit, prepare and finish, the staging of
the one skill. Nothing that measures: no variant, no baseline, no contamination check, no shared-passage check, no
grading, no evidence line. The parity test (runtime/tests/test_lab_parity.py) gives the same adapter output to the
lab and to this file and expects the same classification.

Rule: no other module of runtime/ imports anything under evals/. They call the functions of this file.

Also here: run_command(), one command with no model and no credential, in the same container as a run (the
install of a project's dependencies, the difference a change set is taken from); and the hooks prepare and finish
of run_skill, through which the caller changes a fresh copy before the run and removes what must not come back.

Usage (a library; the terminal shell is runtime/cli.py):
  python3 runtime/lab.py --help        print this text
  python3 runtime/lab.py reference     print the reference model and its adapter, as JSON

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import costs
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
import threading
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNNER = os.path.join(ROOT, "evals", "execution.py")
MODULE = "workbench_eval_execution"  # the name the lab's runner gives the kit too: one module object

# What this file may read of the kit is its __all__ (evals/execution.py): class Lab refuses any other name, and a
# test asserts that the runner's own names (the event runner, the case files, the variants, the baseline's
# checks, the grading, the evidence) are not in it. A name enters __all__ only with a line in the pull request that
# says why it is not measurement. What this file may read of the status script is the kit's STATUS_NAMES.
TIERS = {"strong": ("strong_model", "strong_harness", "strong_pass_env"),
         "floor": ("floor_model", "floor_harness", "floor_pass_env")}
RESPONSE_LIMIT = 2000000  # characters of a reply handed to the caller


class LabError(Exception):
    """The run could not be made at all: a kind ("config", "container", "copy") and a one-line reason.
    A run that was made and failed is not an error: run_skill returns it."""

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind, self.reason = kind, reason


_LOAD_LOCK = threading.RLock()  # one load of the kit at a time: the service answers requests on threads
_KIT = None  # the kit once it is completely loaded; sys.modules holds the module from the start of its load


def load():
    """evals/execution.py as a module, loaded once by path under the name the lab's runner gives it, so that both
    hold one module object. Safe from several threads: the module is registered in sys.modules before its code runs
    (the kit needs its own name while it loads), so a thread that finds it there may find it half made; every
    caller therefore takes the module from _KIT, which is set only after the load has ended, and the load itself is
    made once, under a lock, with the check made again after the lock is taken."""
    kit = _KIT
    if kit is not None and sys.modules.get(MODULE) is kit:
        return kit
    with _LOAD_LOCK:
        return _load_locked()


def _load_locked():
    global _KIT
    registered = sys.modules.get(MODULE)
    if registered is not None and registered is _KIT:
        return registered
    if registered is not None:  # registered by the lab's runner in this process, and its load has ended
        _KIT = registered
        return registered
    if not os.path.isfile(RUNNER):
        raise LabError("config", "evals/execution.py is missing: the runtime runs from a checkout of the workbench")
    spec = importlib.util.spec_from_file_location(MODULE, RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(MODULE, None)  # a failed load leaves nothing half made for the next caller
        raise
    _KIT = module
    return module


class Lab:
    """The kit's module, seen through the names of its __all__ only."""

    def __getattr__(self, name):
        kit = load()
        if name not in kit.__all__:
            raise AttributeError(f"runtime/lab.py may not use {name!r} of evals/execution.py: it is not in its __all__ "
                                 "(what measures is never shared with the runtime)")
        return getattr(kit, name)


LAB = Lab()


def _lab_call(function, *args, **kwargs):
    """Call a function of the lab that ends the process on a configuration error (its die()): here that is an
    error of this run, never the end of the caller."""
    try:
        return function(*args, **kwargs)
    except SystemExit as e:
        raise LabError("config", "the lab refused its configuration (its message is on stderr, above); "
                                 f"exit code {e.code}") from None


def reference(tier: str = "strong") -> dict:
    """The model a tier runs on, its adapter, the variables that carry its credential (names only) and the
    control of a run, all from the gate file evals/eval-gate.json: {"tier", "model", "adapter", "pass_env",
    "timeout_seconds", "retries", "control"}."""
    if tier not in TIERS:
        raise LabError("config", f"tier must be one of {', '.join(TIERS)}")
    status = _lab_call(LAB.load_status)
    gate = status.load_gate(LAB.ROOT)
    control = status.event_config(gate)
    model_key, harness_key, env_key = TIERS[tier]
    if not gate.get(model_key) or not gate.get(harness_key):
        raise LabError("config", f"evals/eval-gate.json is missing or invalid, or names no {tier} model")
    return {"tier": tier, "model": gate[model_key], "adapter": gate[harness_key], "pass_env": list(gate.get(env_key) or []),
            "timeout_seconds": control["timeout_seconds"], "retries": control["retries"], "control": control}


def credential_missing(tier: str) -> list:
    """The variables of a tier's credential (its pass_env in the gate file) that are neither set nor found in the
    secret store, by the lab's own lookup (resolve_pass_env of evals/execution.py, the one run_skill uses). It
    tells whether a run of the tier would have its key; no value is returned or kept: the environment is put back
    as it was. An empty list for a tier whose gate file names no variable."""
    names = reference(tier)["pass_env"]
    before = {name: os.environ.get(name) for name in names}
    try:
        _lab_call(LAB.resolve_pass_env, names)
        return [name for name in names if not os.environ.get(name)]
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def credential_usernames(names) -> dict:
    """{variable: the username it is stored under in the OS secret store} for the names the adapters register in the
    "secrets" list of their manifests, read with the workbench's secret resolver (a name nobody registers, or no
    resolver in this checkout, is left out). Names only, never a value: it tells the person what to type after
    `keyring set openhora`."""
    path = os.path.join(LAB.ROOT, "providers", "secrets", "resolver.py")
    if not os.path.isfile(path):
        return {}
    try:
        spec = importlib.util.spec_from_file_location("workbench_secret_resolver_lab", path)
        resolver = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = resolver  # the resolver's dataclasses look their module up here
        spec.loader.exec_module(resolver)
        for manifest in sorted(glob.glob(os.path.join(LAB.ROOT, "adapters", "*", "adapter.json"))):
            try:
                resolver.register_file(manifest)
            except ValueError:
                continue
        return {name: resolver.REGISTRY[name].store_username for name in names
                if name in resolver.REGISTRY and resolver.REGISTRY[name].store_username}
    except Exception:  # a resolver that does not run here: nothing is known, and no refusal comes of it
        return {}


def skill_identity(skill: str) -> dict:
    """{"version", "content_sha256"} of a skill of this checkout, as the lab computes them for an evidence line."""
    status = _lab_call(LAB.load_status)
    skill_dir = os.path.join(LAB.ROOT, "skills", skill)
    return {"version": status.skill_version(skill_dir), "content_sha256": status.content_hash(skill_dir)}


def settings_names() -> list:
    """Every name that carries a tool's settings at project level, from the adapters' own lists (the lab's
    harness_settings): a path with such a part never enters a run copy (limit L4)."""
    return sorted(_lab_call(LAB.harness_settings))


def measurement_problem():
    """Why the measurement files of this checkout are not the recorded ones (the status script's
    fingerprint_problem), or None when they are."""
    return _lab_call(LAB.load_status).fingerprint_problem(LAB.ROOT)


def image() -> dict:
    """{"name", "digest", "platform", "evidence_platform"} of the eval image on this machine. digest is None when the lab
    does not run in a container, or when the image is not on this machine. platform is the CPU platform the image runs
    as here; evidence_platform is the one lab evidence is made on (the executor's IMAGE_PLATFORM, which every evidence
    line carries as image_platform): the two differ on a machine of another architecture, and the proof holds for the
    second. It only inspects, the way ensure() of evals/executor.py reads the id of the built image (its digest); it
    never calls ensure() and never builds."""
    if LAB.EXECUTOR != "container":
        return {"name": None, "digest": None, "platform": None, "evidence_platform": None}
    try:
        executor = LAB.load_executor()
        name, platform = executor.names()["image"], executor.image_platform()
        evidence = executor.IMAGE_PLATFORM
        found = executor.docker("image", "inspect", "--format", "{{.Id}}", name, check=False)
    except Exception:  # no docker client, no daemon: the image cannot be seen, so it is not there
        return {"name": None, "digest": None, "platform": None, "evidence_platform": None}
    digest = found.stdout.strip() if found.returncode == 0 else ""
    return {"name": name, "digest": digest or None, "platform": platform, "evidence_platform": evidence}


def _cases(skill_dir: str):
    """(the file's top-level "allow_web", {case id as text: case}) of the skill's evals/evals.json; (False, {}) when
    there is no readable case file."""
    try:
        with open(os.path.join(skill_dir, "evals", "evals.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False, {}
    cases = data.get("evals") if isinstance(data, dict) else None
    top = isinstance(data, dict) and data.get("allow_web") is True
    return top, {str(c.get("id")): c for c in cases or [] if isinstance(c, dict)}


def proof_inputs(skill: str) -> str:
    """A sha256 that changes when the proof of a skill may have changed. Over, in this order: the bytes of the gate
    file; of the skill's evals/versions.jsonl; of its case files (evals/evals.json, then evals/platforms/*.json in
    sorted name order, each preceded by its name); of every file of the skill's evals/evidence/ in sorted name order,
    each preceded by its name; the context hash the status script computes for each case of evals/evals.json (its
    dependency skills' content and the shared references staged with the skill: what a line's context is compared
    with); and the skill's content hash. Editing a case or a dependency therefore recomputes the entry. It lives here because no other module of runtime/
    may name a path under evals/."""
    status = _lab_call(LAB.load_status)
    skill_dir = os.path.join(LAB.ROOT, "skills", skill)
    digest = hashlib.sha256()

    def add(path: str) -> None:
        try:
            with open(path, "rb") as f:
                digest.update(f.read())
        except OSError:
            digest.update(b"\0missing\0")

    add(os.path.join(LAB.ROOT, *status.GATE_REL.split("/")))
    add(os.path.join(skill_dir, "evals", "versions.jsonl"))
    add(os.path.join(skill_dir, "evals", "evals.json"))
    platforms = os.path.join(skill_dir, "evals", "platforms")
    for name in sorted(os.listdir(platforms)) if os.path.isdir(platforms) else []:
        digest.update(b"\0" + name.encode("utf-8") + b"\0")
        add(os.path.join(platforms, name))
    for case_id, case in sorted(_cases(skill_dir)[1].items()):
        try:
            context = status.case_context(LAB.ROOT, skill_dir, case, True)
        except Exception:  # a malformed case ("skills": 1): the preflight refuses it; here it only has no context
            context = "unknown"
        digest.update(b"\0context " + case_id.encode("utf-8") + b" "
                      + (str(context) if isinstance(context, (str, type(None))) else "unknown").encode("utf-8") + b"\0")
    evidence = os.path.join(skill_dir, "evals", "evidence")
    for name in sorted(os.listdir(evidence)) if os.path.isdir(evidence) else []:
        digest.update(b"\0" + name.encode("utf-8") + b"\0")
        add(os.path.join(evidence, name))
    digest.update(skill_identity(skill)["content_sha256"].encode("utf-8"))
    return digest.hexdigest()


def standing(skill: str) -> dict:
    """What the status script computes for one skill: {"skill", "version", "models": {model id: {"band", "cause",
    "score", "mean", "runs", "web_measured"}}, "tiers": {"strong": {"model", "adapter"}, "floor": {"model",
    "adapter"}}, "web_cases": the gate file's web cases of the skill (information only), "evidence_images": the sorted
    distinct image digests of the skill's lab events at or above the measurement floor}.

    web_measured, per model, is true when the lines that weigh above zero for that model hold a with-skill lab line
    of a web case. Those are the lines the model's score is computed from (the status script's lab_view: the pool's
    "current" lines, those of the current X.Y since the newest epoch, measurement floor or dependency change, and
    its "inherited" ones, which lab_view keeps only when the case still has the same hash, the line is at or above
    the measurement floor and its major version is the current one), so the flag stays true while the band stays
    reliable on inherited lines. A web case is a case the gate file lists in web_cases for the skill and that sets
    "allow_web" in evals/evals.json now (in the case or at the top of the file): the listing is only the
    permission, the runner opens the network for cases that set it. A listed case with no such line, and a model
    with no line at all, is false."""
    status = _lab_call(LAB.load_status)
    gate = status.load_gate(LAB.ROOT)
    row = _lab_call(status.all_status, LAB.ROOT, only=skill)["skills"][0]
    floor = gate.get("measurement_floor") or 0
    skill_dir = os.path.join(LAB.ROOT, "skills", skill)
    events = status.skill_evidence(skill_dir)
    top_web, cases = _cases(skill_dir)
    web_cases = {str(case) for case in (gate.get("web_cases") or {}).get(skill, [])
                 if str(case) in cases and (top_web or cases[str(case)].get("allow_web") is True)}
    pools = _lab_call(status.lab_view, LAB.ROOT, skill_dir, gate, events)["pools"]  # what weighs above zero, per model
    images = set()
    for event, _ in events:
        version = event.get("measurement_version")
        if isinstance(version, (int, float)) and version >= floor and event.get("image_digest"):
            images.add(event["image_digest"])

    def measured(model):
        pool = pools.get(model) or {}
        return any(str(line["case"]) in web_cases for line in (pool.get("current") or []) + (pool.get("inherited") or []))

    return {"skill": skill, "version": row["version"],
            "models": {model: {**{k: found.get(k) for k in ("band", "cause", "score", "mean", "runs")},
                               "web_measured": measured(model)}
                       for model, found in (row.get("models") or {}).items()},
            "tiers": {"strong": {"model": gate.get("strong_model"), "adapter": gate.get("strong_harness")},
                      "floor": {"model": gate.get("floor_model"), "adapter": gate.get("floor_harness")}},
            "web_cases": list((gate.get("web_cases") or {}).get(skill, [])),
            "evidence_images": sorted(images)}


def carries_settings(rel: str) -> bool:
    """True when a part of the relative path rel is one of the names that carry a tool's settings, by the lab's own
    list (harness_settings()): such a path never enters a run and never leaves one in a change set."""
    names = set(settings_names())
    return any(part in names for part in str(rel).replace("\\", "/").split("/"))


def readable(cwd: str, rel: str) -> bool:
    """True when the host may read the path rel of what a run left in cwd: a regular file, no link, inside cwd."""
    return bool(LAB.readable(cwd, rel))


@contextlib.contextmanager
def session():
    """Leave nothing running: every process group and container a run started is ended on TERM, INT or HUP and
    on every way out, and the folders of a run in progress go back to its run folder. Wrap run_skill in it."""
    LAB.STOPPING.clear()

    def on_signal(signum, _frame):
        print(f"stopped by signal {signum}: ending the run that was started", file=sys.stderr)
        LAB.stop_all_groups()
        LAB.return_all_runs()
        os._exit(128 + signum)

    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous[sig] = signal.signal(sig, on_signal)
    try:
        yield
    finally:
        LAB.stop_all_groups(grace=2.0)
        LAB.return_all_runs()
        LAB.STOPPING.clear()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def stop_runs() -> dict:
    """End every run this process started, by the lab's own stop and in the order session() ends them: every
    container and process group is ended (after a short grace, killed), no new one starts, and the folders of a run in
    progress go back to its run folder. Unlike session() it is not tied to the thread that started a run, and it
    leaves the lab's stopping flag set: the process is ending, and the next session() clears it. Returns
    {"stopped": True}; the kit does not say how many runs it ended."""
    LAB.stop_all_groups(grace=2.0)
    LAB.return_all_runs()
    return {"stopped": True}


def reported_usage(dest: str) -> dict:
    """What the attempts of a run reported, whether it ended or failed: {"cost_usd", "total_tokens"}, each the sum over the
    attempts' timing.json (the tokens are the key proxy's count instead, runtime/costs.py metered_usage, when the run and
    every attempt it set aside have one) (the run folder's outputs/ and those the lab kept from the attempts it set aside, failed-<n>/,
    early-end-<n>/ and paused-<n>/), or None when no attempt reported it. A paused attempt (the account limit) counts as no
    result, but it may have spent before it stopped, so its usage is read: reading it only adds spend. A run id is never
    reused over a leftover run folder (the store's ids are AUTOINCREMENT), so every folder under dest is this run's.
    Nothing is guessed: a file that is missing or holds no number adds nothing."""
    folders = [os.path.join(dest, "outputs")]
    for prefix in ("failed-", "early-end-", "paused-"):
        folders += sorted(glob.glob(os.path.join(glob.escape(dest), prefix + "*", "outputs")))
    sums = {"cost_usd": None, "total_tokens": None}
    for folder in folders:
        try:
            with open(os.path.join(folder, "timing.json"), encoding="utf-8") as f:
                timing = json.load(f)
        except (OSError, ValueError):
            continue
        for key in sums:
            value = timing.get(key) if isinstance(timing, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                sums[key] = (sums[key] or 0) + value
    metered = costs.metered_usage(dest)  # the key proxy's own count, which the run could not change, when it has one
    if metered is not None:  # a lower bound when the proxy could not count every answer (metered["unknown_responses"])
        sums["total_tokens"] = sum(metered[kind] for kind in costs.KINDS)
    return sums


def failure_kind(why, out_dir: str, refusal_markers, response: str, changed) -> tuple:
    """How one attempt failed, by the lab's own functions and in the lab's own order: (kind, detail). kind is
    "timeout", "refused", "auth", "adapter", "early_end", or None when the attempt is the run's result. why is what
    run_failure() returned; changed lists the files the run created, changed or deleted. The account limit is
    looked at before this, by the caller. One call of classify() of evals/run_attempts.py, the function the lab's
    runner uses."""
    return _lab_call(LAB.load_attempts).classify(LAB, why, out_dir, refusal_markers, response, changed)


PLATFORMS_CITED = "shared/references/platforms/"
# A platform's name, as scripts/stage_skills.py accepts it (its NAME_RE); the folder's README.md is not one.
PLATFORM_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def platforms_cited(skill_dir: str) -> list:
    """The platforms whose reference a run of the skill is given, for the lab's staging (a case's "platforms"):
    every platform with a reference (shared/references/platforms/<name>.md of the lab's root) when the skill's
    SKILL.md, or a file under its references/ folder, cites that folder; none otherwise. A lab case names the
    platform its run needs; the runtime does not know in advance which platform a run will be told, so it gives
    them all. They are staged beside the skill and, like it, never come back (runtime/path_rule.py, "staged")."""
    texts = [os.path.join(skill_dir, "SKILL.md")]
    for current, names, files in os.walk(os.path.join(skill_dir, "references")):
        names.sort()
        texts += [os.path.join(current, name) for name in sorted(files)]
    cites = False
    for path in texts:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                cites = PLATFORMS_CITED in f.read()
        except OSError:
            continue
        if cites:
            break
    folder = os.path.join(LAB.ROOT, *PLATFORMS_CITED.rstrip("/").split("/"))
    if not cites or not os.path.isdir(folder):
        return []
    return sorted(name[:-3] for name in os.listdir(folder)
                  if name.endswith(".md") and PLATFORM_NAME.match(name[:-3]) and os.path.isfile(os.path.join(folder, name)))


def _container() -> dict:
    """The environment of the eval container (executor.ensure(): the networks and the egress proxy, started once),
    or {} when the lab does not run in a container. The image is looked for first: lab evidence is bound to one
    built image, a rebuilt one is another image, and ensure() would build a missing one, so the runtime never
    reaches ensure() without it. Raises LabError("container")."""
    if LAB.EXECUTOR != "container":
        return {}
    try:
        executor = LAB.load_executor()
        if executor.docker("image", "inspect", executor.names()["image"], check=False).returncode != 0:
            raise LabError("container", "the eval image of this checkout is not on this machine, and the runtime "
                                        "never builds it: the maintainer loads the archived image (docker load), "
                                        "or builds it with python3 evals/executor.py ensure")
        return executor.ensure()
    except LabError:
        raise
    except Exception as e:
        raise LabError("container", f"the eval container is not available: {e}") from None


NETWORKS = ("none", "open")  # what run_command may ask for; the proxied network is a model's, never a command's


def run_command(argv, root: str, *, cwd: str | None = None, network: str = "none", timeout: int | None = None) -> dict:
    """Run one command with no model and no credential, in the same container as a run, with root (an absolute
    folder) as the only folder it sees; cwd (default root) is a folder inside it. network is "none" or "open"
    (the install of a project's dependencies), never the proxied network of a model. The environment is the lab's
    contained one with no passed variable, so no credential reaches the command. The image is looked for first
    and never built (_container()). Returns {"returncode", "stdout", "stderr", "timed_out"}; a timeout (default the
    lab's SETUP_TIMEOUT) gives timed_out true and returncode None. Raises LabError("config") for a bad argument,
    LabError("container") when the image is missing."""
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(a, str) and a for a in argv):
        raise LabError("config", "argv is a non-empty list of texts")
    if not isinstance(root, str) or not os.path.isabs(root) or not os.path.isdir(root):
        raise LabError("config", "root is an absolute folder that exists")
    if network not in NETWORKS:
        raise LabError("config", f"network is one of {', '.join(NETWORKS)}")
    cwd = cwd or root
    real_root, real_cwd = os.path.realpath(root), os.path.realpath(cwd)
    if not os.path.isabs(cwd) or not os.path.isdir(cwd) or not (real_cwd == real_root or real_cwd.startswith(real_root + os.sep)):
        raise LabError("config", "cwd is a folder inside root")
    _container()
    try:
        done = LAB.run_group(list(argv), timeout or LAB.SETUP_TIMEOUT, cwd=cwd, env=LAB.contained_env(root),
                             box={"root": root, "network": network})
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "", "timed_out": True}
    return {"returncode": done.returncode, "stdout": done.stdout or "", "stderr": done.stderr or "", "timed_out": False}


def _base_commit(root: str, case_dir: str):
    """The commit id of the copy's base, read in the container right after the fixture commit; None when it
    cannot be read."""
    try:
        done = run_command(["git", "rev-parse", "HEAD"], root, cwd=case_dir)
    except LabError:
        return None
    line = (done.get("stdout") or "").strip()
    return line if done.get("returncode") == 0 and re.fullmatch(r"[0-9a-f]{40,64}", line) else None


def _run_tmp(root: str, runner: str) -> dict:
    """{"TMPDIR": path} for a run whose temporary folder is kept (tmp_in_run): <root>/tmp is made (mode 1777), and
    the path is the one the run sees, the container's path of the run's folder with the container executor, the
    host's otherwise. Given to the shared function as env_extra: TMPDIR is set in the adapter call's environment and
    added to the passed names of its box, never to the values replaced. TMPDIR is no key proxy's variable, so the
    route of the run's key does not change (evals/executor.py, held_route, reads only the routes' own variables)."""
    folder = os.path.join(root, "tmp")
    os.makedirs(folder, exist_ok=True)
    os.chmod(folder, 0o1777)
    if LAB.EXECUTOR == "container":
        executor = LAB.load_executor()
        return {"TMPDIR": executor.translate(folder, executor.mounts(root, runner))}
    return {"TMPDIR": folder}


def _copy_in(files, case_dir: str) -> None:
    """Copy the caller's files into the fresh folder of a run: regular files only, each at its relative path."""
    for src, rel in files:
        parts = rel.replace("\\", "/").split("/")
        if os.path.isabs(rel) or not rel or ".." in parts or parts[0] == ".git":
            raise LabError("copy", f"{rel!r} is not a relative path inside the copy")
        if os.path.islink(src) or not os.path.isfile(src):
            raise LabError("copy", f"{rel!r} is not a regular file: only regular files enter a run")
        target = os.path.join(case_dir, *parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(src, target)


def _platform_names(platforms) -> list:
    """The platforms a caller names for one run, checked: None is none; otherwise a list of names, each a platform of
    this checkout (shared/references/platforms/<name>.md). Anything else is LabError("config"), before any run."""
    if platforms is None:
        return []
    if not isinstance(platforms, (list, tuple)) or not all(isinstance(n, str) and PLATFORM_NAME.match(n) for n in platforms):
        raise LabError("config", "platforms is a list of platform names (lowercase letters, digits and hyphens)")
    folder = os.path.join(LAB.ROOT, *PLATFORMS_CITED.rstrip("/").split("/"))
    for name in platforms:
        if not os.path.isfile(os.path.join(folder, name + ".md")):
            raise LabError("config", f"platform {name!r} has no reference: {PLATFORMS_CITED}{name}.md does not exist")
    return sorted(set(platforms))


def run_skill(skill: str, prompt: str, files, dest: str, *, web: bool = False, tier: str = "strong",
              model: str | None = None, adapter: str | None = None, pass_env=None,
              timeout: int | None = None, retries: int | None = None, prepare=None, finish=None,
              tmp_in_run: bool = False, platforms=None, max_cost=None) -> dict:
    """Run one skill once on one task text, in the eval container, on a fresh copy.

    skill    a folder name under skills/ of this checkout: it is staged where the adapter's tool finds skills,
             without its evals/ and scripts/tests/, with the shared references it cites, as in a lab run, and,
             when it cites the platforms' folder, the reference of every platform (platforms_cited())
    prompt   the task text, written to prompt.md
    files    [(absolute source path, path relative to the copy)]: what the run sees of the project. The caller
             decides the list; this function copies regular files and nothing else
    dest     the run folder (absolute). When the run ends, however it ends: <dest>/cwd is the copy as the run
             left it, <dest>/outputs the adapter's output (response.md, timing.json, raw.json, stderr.log),
             <dest>/prompt.md the task text; what an attempt that was made again left is in <dest>/failed-<n>/,
             <dest>/early-end-<n>/ or <dest>/paused-<n>/
    web      True runs on the open network and lets the model search and fetch pages (the adapter's --allow-web)
    tier     "strong" (the reference model) or "floor": the model, its adapter and the names of the variables
             that carry its credential come from evals/eval-gate.json. model, adapter and pass_env replace them
             (a test's stand-in); timeout (seconds) and retries default to the gate file's too
    prepare  prepare(copy_dir, root), called on every attempt after the base commit of the copy and before the
             check of a tool's settings: the caller changes the fresh copy (puts a dependency folder in, applies a
             change set)
    finish   finish(copy_dir, root), called on every attempt in which the adapter was started, after it returned
             and the changes were taken, before the last replacement of values and the return of the folders: the
             caller removes what must not be kept. An exception in either hook ends the run as LabError("copy")
    tmp_in_run  True points the run's temporary folder (TMPDIR) at a folder made in its fresh folder, which comes
             back as <dest>/outputs/tmp: what a skill writes under a folder from mktemp -d (the payload of its
             confirmation gate) is kept. TMPDIR is passed to the container by name, as the passed variables are; it
             is not a secret, so its value is never replaced in what the run left
    max_cost  the run's own spend limit in dollars (a number above 0), given to the adapter as --max-cost-usd, to the cent; None, the
             default, gives none. The runtime passes one for a run on a metered credential (autonomy.run_budget); the
             adapter of the reference model stops the run once it has spent that much, the floor model's adapter does not enforce it
    platforms  the platforms whose reference the caller names, a list of names ("a case's platforms"): each is
             staged beside the skill, with its data file when it has one, as the lab stages a case's platforms. The
             list is added to what platforms_cited() gives, never in its place; a name with no reference under
             shared/references/platforms/ is LabError("config"). None, the default, adds none

    Returns {"status": "ok" | "failed", "failure": None | {"kind", "reason", "detail"}, "response", "changes":
    {"created", "modified", "deleted", "unchanged"} or None, "staged": [paths the runtime put in the copy],
    "run_dir", "cwd", "outputs", "timing": {...}, "counts": {"attempts", "timeouts", "refusals",
    "adapter_failures", "early_ends", "pauses", "redactions"}, "tier", "model", "adapter", "web",
    "image_digest", "image_platform", "base_commit": the commit id of the copy's base, or None, "tmp": with
    tmp_in_run, <dest>/outputs/tmp, else None}. failure kinds: "timeout", "refused", "auth", "adapter", "early_end"
    (each after the gate file's retries, "auth" at once), "settings" (the copy carries a tool's settings) and
    "stopped". Raises LabError when no run could be made (configuration, container, a file that may not enter).
    Call it inside `with session():`."""
    named = _platform_names(platforms)
    ref = reference(tier)
    model, adapter = model or ref["model"], adapter or ref["adapter"]
    pass_env = list(ref["pass_env"] if pass_env is None else pass_env)
    if max_cost is not None and (isinstance(max_cost, bool) or not isinstance(max_cost, (int, float)) or not max_cost > 0):
        raise LabError("config", "max_cost is a number of dollars above 0")
    timeout = ref["timeout_seconds"] if timeout is None else timeout
    retries = ref["retries"] if retries is None else retries
    control = ref["control"]
    skill_dir = os.path.join(LAB.ROOT, "skills", skill)
    if not os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
        raise LabError("config", f"no skill {skill!r} under skills/ of {LAB.ROOT}")
    if not os.path.isabs(dest):
        raise LabError("config", "dest must be an absolute path")
    eval_cfg = _lab_call(LAB.adapter_eval, adapter)
    runner = os.path.join(LAB.ROOT, "adapters", adapter, "run-prompt.sh")
    if not os.path.isfile(runner):
        raise LabError("config", f"adapter {adapter!r} has no run-prompt.sh")
    _lab_call(LAB.resolve_pass_env, pass_env)
    unset = [name for name in pass_env if not os.environ.get(name)]
    if unset:
        raise LabError("config", f"{', '.join(unset)} is not set and was not found in the secret store. Export it, or "
                                 "start the command with the store's library available: uv run --with keyring==25.7.0 "
                                 "python3 runtime/cli.py ...")
    environment = _container()
    settings = _lab_call(LAB.harness_settings)
    values = LAB.redaction_values(pass_env)
    probe = lambda: LAB.probe_call(runner, model, pass_env)
    counts = {"attempts": 0, "timeouts": 0, "refusals": 0, "adapter_failures": 0, "early_ends": 0, "pauses": 0,
              "redactions": 0}
    cwd, out = os.path.join(dest, "cwd"), os.path.join(dest, "outputs")
    os.makedirs(dest, exist_ok=True)
    result = {"status": "failed", "failure": None, "response": "", "changes": None, "staged": [], "run_dir": dest,
              "cwd": cwd, "outputs": out, "timing": {}, "counts": counts, "tier": tier, "model": model,
              "adapter": adapter, "web": bool(web), "image_digest": environment.get("image_digest"),
              "image_platform": environment.get("image_platform"), "base_commit": None,
              "tmp": os.path.join(out, "tmp") if tmp_in_run else None}

    def failed(kind, reason, detail=None):
        result["failure"] = {"kind": kind, "reason": reason, "detail": detail}
        result["response"] = LAB.read_text(os.path.join(out, "response.md"), RESPONSE_LIMIT)
        result["reported"] = reported_usage(dest)
        return result

    # What the runtime adds to an attempt; the attempts themselves (the wait on a pause, the place of the shared
    # lock, the fresh folder and its return, the settings check, the adapter call, the replacement of the passed
    # values, the classification and the retries) are the lab's one function, evals/run_attempts.py.
    def build(case_dir, root):
        _copy_in(files, case_dir)

    def after_base(case_dir, root):
        result["base_commit"] = _base_commit(root, case_dir)
        if prepare is not None:
            try:
                prepare(case_dir, root)
            except Exception as e:
                raise LabError("copy", f"the copy could not be prepared: {type(e).__name__}: {e}") from None

    def stage(case_dir):
        case = {"platforms": sorted(set(platforms_cited(skill_dir)) | set(named))}
        staged, _ = _lab_call(LAB.stage_run, case_dir, eval_cfg, skill_dir, [], case, None)
        return staged

    def after_run(case_dir, root, why, delta, staged):
        hook = None
        if finish is not None:
            try:
                finish(case_dir, root)
            except Exception as e:
                hook = f"what the run left could not be finished: {type(e).__name__}: {e}"
        run_tmp = os.path.join(root, "tmp")
        if tmp_in_run and os.path.isdir(run_tmp) and not os.path.islink(run_tmp):
            shutil.move(run_tmp, os.path.join(root, "out", "tmp"))  # replaced next, then returned with out/
        if hook:
            raise LabError("copy", hook)

    spec = {"dest": dest, "names": [skill], "label": f"task run {os.path.basename(dest)}", "runner": runner,
            "model": model, "account": {"key": adapter, "markers": eval_cfg["account_limit"], "probe": probe},
            "refusal_markers": eval_cfg["refusal_markers"], "pass_env": pass_env, "values": values,
            "settings": settings, "control": control, "tier": tier, "web": bool(web), "timeout": timeout,
            "max_cost": None if max_cost is None else f"{max_cost:.2f}", "retries": retries, "prompt": prompt, "response_limit": RESPONSE_LIMIT,
            "counts": counts, "env_extra": (lambda root: _run_tmp(root, runner)) if tmp_in_run else None}
    hooks = types.SimpleNamespace(build=build, after_base=after_base, stage=stage, after_run=after_run)
    attempts = _lab_call(LAB.load_attempts)
    try:
        try:
            made = attempts.run(LAB, spec, hooks)
        except Exception as e:
            # An exception that leaves the attempts carries how many began (runtime/ops.py records it on the run row): 0
            # proves the adapter never ran, so a run that never reached the model is told from a crash mid-run (A-57).
            e.attempts = counts["attempts"]
            raise
    except LabError:
        raise
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        if LAB.STOPPING.is_set():
            return failed("stopped", "stopped before the run ended")
        error = LabError("container", f"the run could not be prepared or started: {type(e).__name__}: {e}")
        error.attempts = e.attempts
        raise error from None
    result["staged"] = made["staged"]
    failure, why = made["failure"], made["why"]
    if failure is None:
        result.update(status="ok", failure=None, response=made["response"], changes=made["delta"], timing=made["timing"])
        return result
    kind, detail = failure["kind"], failure["detail"]
    if kind == "settings":
        return failed("settings", f"the copy holds {detail}: a tool's settings never enter a run")
    if kind == "stopped":
        return failed("stopped", why or "stopped before the run was read")
    if kind == "auth":  # never retried: every later run with that key would meet the same refusal
        return failed("auth", f"the provider refused the key ({detail}) passed in "
                              f"{LAB.credential_label(adapter, pass_env)}", detail)
    reason = {"early_end": f"the model ended its turn early on all {counts['attempts']} attempt(s): {detail}",
              "refused": "refused: the provider declined the request"}.get(kind, why)
    return failed(kind, reason, detail)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["reference"]:
        ref = reference()
        print(json.dumps({key: ref[key] for key in ("tier", "model", "adapter", "pass_env", "timeout_seconds", "retries")}, indent=1))
        return 0
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LabError as e:
        print(f"error: {e.reason}", file=sys.stderr)
        sys.exit(3 if e.kind == "config" else 1)
