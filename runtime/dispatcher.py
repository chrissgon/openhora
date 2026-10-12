#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The dispatcher of the task runtime: what may start now, and what an autonomy mode releases, decided by one pure
function from a snapshot of the store.

decide(snapshot, review_action, may_start) -> {"release": [pending ids], "start": task id or None, "held": [...]}
held_of(snapshot, decided, blocked=None) -> [{"task_id", "agent", "reason"}]: every ready task a round did not start,
                with the reason, in the words of REASONS (the record `status` shows, runtime/ops.py)

  snapshot      {"running": <task or None>, "ready": [tasks, oldest first], "reviews": [{"pending", "task", "agent",
                "proven", "mandatory"}], "agents": {"<name>": {"facts", "spent", "entry"}}, "tier": {"<task id>":
                "strong" or "floor"}, "billing": {"<task id>": the billing of the credential the task's route would
                use, "subscription", "metered" or "free", or None when no manifest says}, "waits": {"<task id>": [open
                waits]}}, built by runtime/ops.py (dispatch, poll) from the store, the proof and the runtime manifests
  review_action runtime/autonomy.py's review_action(task, pending, facts, proven, mandatory): "release" or "hold"
  may_start     runtime/autonomy.py's may_start(name, agents, facts, spent, billing): (True, "") or (False, why)

Rules: (1) release holds every review the agent's mode releases; (2) while a task of the project runs, nothing
starts (one task at a time per project); (3) otherwise the ready tasks are walked oldest first: a task with an open
wait (a derived dependency on another request's task, runtime/plan.py) is held and never starts, a task no enabled
area agent owns is held, a task whose agent may not start is held with the reason, and the first that may start is
started; (4) nothing else, and no state is changed here: runtime/ops.py applies the decision. The store keeps a
waiting task `planned` and gives it to no one, so a waiting task is not in `ready` in practice; rule (3) is the
second lock, and the word a person reads ("waiting for task #n") is the wait's own reason.

The two rule functions are passed in, so this file imports no sibling: the scheduler runs a copy of it alone (its
entry, stage 6). It reaches neither the store nor the lab facade.

The entry for the scheduler (stage 6). The scheduler starts a copy of this file, kept in its job folder, with the
system interpreter; so this file works alone, checks the project's configuration against the pin before it loads any
code the configuration points to, and only then loads the checkout:

  /usr/bin/python3 runtime/dispatcher.py poll  --project <dir> [--pin <file>]   ops.poll: the short job
  /usr/bin/python3 runtime/dispatcher.py work  --project <dir> [--pin <file>]   ops.dispatch: the worker
  /usr/bin/python3 runtime/dispatcher.py check --project <dir>                  can this interpreter run them?
  /usr/bin/python3 runtime/dispatcher.py command-file --job poll|work --project <dir> --pin <file>

With --pin (the file `cli.py pin` writes, <data_dir>/dispatch-pin.json), a runtime.json whose hash is not the pinned
one stops the job before anything of the checkout is imported. Without --pin a job may only be run by hand. poll and
work print one JSON object; an error of the operation is printed on stderr and ends with its exit code (1 failed, 2
usage, 3 not configured). check imports every module of runtime/ and runtime/handlers/, loads the lab's gate file,
says whether this interpreter can read the secret store and whether the reference model's credential is reachable,
and finds docker, uv and git on PATH; it starts nothing. command-file prints the scheduler's command file of one
job: argv[0] is always /usr/bin/python3, and the snapshot is this file and the pin.

Usage: python3 runtime/dispatcher.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import sys

ONE_AT_A_TIME = "one task at a time per project"
NO_AGENT = "no enabled agent owns the task"
WAITING = "waiting"                  # the task has an open wait: it is a dependency like depends_on (the reason is the wait's)
JOB_RUNNING = "job running"          # a task of the project runs: the one-at-a-time rule holds every ready task
DISPATCH_OFF = "dispatch off"        # the service dispatches nothing (runtime/ops.py, service_check)
# The words a held ready task carries (contracts/runtime.md, "The local service"): the three of runtime/autonomy.py
# (may_start), those of this file, those of a round's checks before a start (runtime/ops.py) and the service's.
OTHER = "other"                      # any reason a rule function gives that is not in the list: free text never reaches a page
REASONS = ("stopped", "cap: runs per day", "cap: usd per day", "credential", "secret store", "image", DISPATCH_OFF,
           JOB_RUNNING, NO_AGENT, WAITING, OTHER)


def decide(snapshot: dict, review_action, may_start) -> dict:
    """What a round does now: the reviews a mode releases, the task that starts (or None) and the tasks held, each
    with why. Pure: it reads the snapshot and calls the two rule functions, nothing else."""
    agents = snapshot.get("agents") or {}
    entries = {name: a.get("entry") for name, a in agents.items()}
    release = []
    for review in snapshot.get("reviews") or []:
        agent = agents.get(review.get("agent")) or {}
        facts = agent.get("facts") or {"enabled": False, "checkpoints": "every-phase", "standing": False}
        if review_action(review["task"], review["pending"], facts, bool(review.get("proven")),
                         bool(review.get("mandatory"))) == "release":
            release.append(review["pending"]["id"])
    running = snapshot.get("running")
    if running is not None:
        return {"release": release, "start": None, "held": [{"task_id": running["id"], "why": ONE_AT_A_TIME}]}
    held, start = [], None
    billings = snapshot.get("billing") or {}
    waits = snapshot.get("waits") or {}
    for task in snapshot.get("ready") or []:
        if waits.get(task["id"], waits.get(str(task["id"]))):
            held.append({"task_id": task["id"], "why": WAITING})
            continue
        name = task.get("agent")
        if name is None or name not in agents:
            held.append({"task_id": task["id"], "why": NO_AGENT})
            continue
        agent = agents[name]
        billing = billings.get(task["id"], billings.get(str(task["id"])))   # the cap a run counts against is its credential's
        ok, why = may_start(name, entries, agent["facts"], agent["spent"], billing)
        if not ok:
            held.append({"task_id": task["id"], "why": why})
            continue
        start = task["id"]
        break
    return {"release": release, "start": start, "held": held}


def held_of(snapshot: dict, decided: dict, blocked=None) -> list:
    """The ready tasks a round held, as [{"task_id", "agent", "reason"}] in the order of the snapshot's ready tasks.
    Pure. While a task of the project runs every ready task is held with JOB_RUNNING (decide itself lists only the
    running one); otherwise a task decide held has its reason (stopped, a cap, NO_AGENT). blocked is {task id: reason}
    for a task decide chose to start that a check made before the start stopped (credential, secret store, image)."""
    ready = snapshot.get("ready") or []
    if snapshot.get("running") is not None:
        why = {task["id"]: JOB_RUNNING for task in ready}
    else:
        why = {h["task_id"]: h["why"] for h in decided.get("held") or []}
        why.update(blocked or {})
    return [{"task_id": task["id"], "agent": task.get("agent"),
             "reason": why[task["id"]] if why[task["id"]] in REASONS else OTHER}
            for task in ready if task["id"] in why]


# --- the entry for the scheduler --------------------------------------------------------------------------------------

SYSTEM_PYTHON = "/usr/bin/python3"
CONFIG = os.path.join("docs", "workbench", "runtime.json")
JOBS = {"poll": 5, "work": 240}  # timeout_minutes: the poller's limit, the provider's maximum for the worker
ENTRY_VERBS = ("poll", "work", "check", "command-file")
TOOLS = ("docker", "uv", "git")
CHANGED = ("changed since the job was approved: {path}; nothing ran. Review the change, accept it (accept-config), "
           "run pin, then schedule the job again: that is the new approval")
STORE_MODULE = "keyring"  # the library the secret resolver reads the secret store with


class EntryError(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def _sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _config_file(project: str) -> str:
    path = os.path.join(os.path.abspath(project), CONFIG)
    if not os.path.isfile(path):
        raise EntryError(f"{path} not found: the project is not configured", 3)
    return path


def _check_pin(config: str, pin: str) -> None:
    """Before anything of the checkout is loaded: the pin names this project's runtime.json and its hash now."""
    try:
        with open(pin, encoding="utf-8") as f:
            recorded = json.load(f)["runtime_json"]
        pinned_path, pinned_hash = recorded["path"], recorded["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        raise EntryError(CHANGED.format(path=config), 3) from None
    if not isinstance(pinned_path, str) or os.path.realpath(pinned_path) != os.path.realpath(config) or \
            pinned_hash != _sha256(config):
        raise EntryError(CHANGED.format(path=config), 3)


def bootstrap(project: str, pin=None):
    """The operations layer of the checkout the project's configuration names, loaded only after the configuration
    was checked against the pin (when there is one). The folders of its `path` go first on PATH, for what the
    operations start (uv, docker, git). Returns the module ops."""
    config = _config_file(project)
    if pin is not None:
        _check_pin(config, pin)
    try:
        with open(config, encoding="utf-8") as f:
            raw = json.load(f)
        workbench = raw["workbench"]
    except (OSError, ValueError, KeyError, TypeError):
        raise EntryError(f"{config} cannot be read, or names no workbench", 3) from None
    folders = raw.get("path") or []
    if not isinstance(workbench, str) or not os.path.isabs(workbench) or not isinstance(folders, list) or \
            not all(isinstance(p, str) and os.path.isabs(p) for p in folders):
        raise EntryError(f"{config}: workbench is an absolute path, and path a list of absolute folders", 3)
    os.environ["PATH"] = os.pathsep.join(folders + [p for p in os.environ.get("PATH", "").split(os.pathsep) if p])
    here = os.path.join(workbench, "runtime")
    sys.path.insert(0, here)
    loaded = importlib.import_module("ops")
    if not os.path.realpath(getattr(loaded, "__file__", "") or "").startswith(os.path.realpath(here) + os.sep):
        raise EntryError(f"the operations layer loaded is {getattr(loaded, '__file__', None)}, not the one of {workbench}", 3)
    return loaded


def store_readable():
    """"ok" when this interpreter can import the secret store's library, else why not (one line)."""
    try:
        importlib.import_module(STORE_MODULE)
    except Exception as e:  # any failure to import is the answer
        return f"{sys.executable} (Python {sys.version.split()[0]}) cannot read the secret store: {type(e).__name__}: {e}"
    return "ok"


def inspect(ops) -> dict:
    """What this interpreter and this checkout can do, as a report: {"python", "executable", "modules", "lab",
    "secret_store", "credential", "tools"}. ops is the operations layer of the checkout. It imports, it starts
    nothing (no docker, no model, no provider). The report check prints and the local service reads at its start."""
    report = {"python": sys.version.split()[0], "executable": sys.executable, "modules": {}, "lab": None,
              "secret_store": store_readable(), "credential": None, "tools": {}}
    workbench = os.path.dirname(os.path.dirname(os.path.realpath(ops.__file__)))
    runtime = os.path.join(workbench, "runtime")
    for folder, prefix in ((runtime, ""), (os.path.join(runtime, "handlers"), "handlers/")):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue
            try:
                if prefix:
                    spec = importlib.util.spec_from_file_location("workbench_handler_" + name[:-3], os.path.join(folder, name))
                    spec.loader.exec_module(importlib.util.module_from_spec(spec))
                else:
                    importlib.import_module(name[:-3])
                report["modules"][prefix + name] = "ok"
            except BaseException as e:  # a module that exits or fails on import is reported, never raised
                report["modules"][prefix + name] = " ".join(f"{type(e).__name__}: {e}".split())[:300]
    try:
        lab = importlib.import_module("lab")
        lab.reference("strong")
        report["lab"] = "ok"
        missing = lab.credential_missing("strong")
        report["credential"] = "ok" if not missing else (
            f"the reference model's credential ({', '.join(missing)}) is neither set nor found in the secret store")
    except BaseException as e:
        report["lab"] = " ".join(f"{type(e).__name__}: {e}".split())[:300] if report["lab"] is None else report["lab"]
        if report["credential"] is None:
            report["credential"] = "not checked: the lab could not be loaded"
    report["tools"] = {tool: shutil.which(tool) for tool in TOOLS}
    return report


def check(project: str) -> tuple:
    """(report, exit code) of the check verb: inspect() of the checkout the project names. It imports, it starts
    nothing (no docker, no model, no provider)."""
    secret_store = store_readable()
    ops = bootstrap(project)
    report = inspect(ops)
    report["secret_store"] = secret_store
    ok = all(v == "ok" for v in report["modules"].values()) and report["lab"] == "ok" and \
        report["credential"] == "ok" and report["tools"]["docker"] and report["tools"]["uv"]
    return report, 0 if ok else 1


def command_file(job: str, project: str, pin: str) -> dict:
    """The scheduler's command file of one job: the system interpreter by its fixed path, this file, the job's verb,
    the project and the pin; the snapshot is this file and the pin."""
    entry, project, pin = os.path.abspath(__file__), os.path.abspath(project), os.path.abspath(pin)
    return {"argv": [SYSTEM_PYTHON, entry, job, "--project", project, "--pin", pin], "cwd": project,
            "snapshot": [entry, pin], "timeout_minutes": JOBS[job]}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise EntryError(f"{message}. See --help.", 2)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    p = _Parser(prog="dispatcher.py", add_help=False)
    p.add_argument("verb", choices=ENTRY_VERBS)
    p.add_argument("--project", required=True)
    p.add_argument("--pin")
    p.add_argument("--job", choices=tuple(JOBS))
    try:
        a = p.parse_args(argv)
        if a.verb == "command-file":
            if a.job is None or a.pin is None:
                raise EntryError("command-file needs --job poll|work and --pin. See --help.", 2)
            _config_file(a.project)
            out, code = command_file(a.job, a.project, a.pin), 0
        elif a.verb == "check":
            out, code = check(a.project)
        else:
            ops = bootstrap(a.project, a.pin)
            if a.verb == "work" and store_readable() != "ok":
                # Said at every firing, so the first one says it: a run whose credential is only in the store cannot
                # start from this interpreter (contracts/runtime.md, "The dispatcher's two jobs").
                print(f"warning: {store_readable()}", file=sys.stderr)
            try:
                out = ops.poll(os.path.abspath(a.project)) if a.verb == "poll" else ops.dispatch(os.path.abspath(a.project))
            except ops.OpsError as e:
                raise EntryError(str(e), e.code) from None
            code = 0
    except EntryError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1, default=str)
    print()
    return code


if __name__ == "__main__":
    sys.exit(main())
