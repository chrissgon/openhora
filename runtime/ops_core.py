#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The names every module of the operations layer shares, once: the checkout (ROOT), the refusal (OpsError), the
project's context and the store call, the locks, the runtime's own key and the data-folder names.

The operations layer is seven files: runtime/ops.py (the operations and the facade every shell imports),
runtime/ops_say.py (the conversation), runtime/ops_reads.py (the reads of the local interface), runtime/ops_waits.py
(the derived waits between requests), runtime/ops_config.py (the configuration's acceptance), runtime/ops_runs.py (the
runs of tasks, the dispatcher's round and the processes it starts) and this one. Every
module reads a name of this file as an attribute of it, at call time (`import ops_core as core`, then `core.ROOT`,
`core.context(...)`), and never binds one at import (no module takes a name of this file with a from-import): a test
that patches `ops_core.ROOT` then reaches every reader, and a copy bound at import would keep the real checkout. No name
here is an operation, and this file imports no other file of the layer (runtime/tests/test_runtime_rules.py).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import importlib.util
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import autonomy  # noqa: E402
import billing  # noqa: E402
import lab  # noqa: E402
import operations  # noqa: E402
import project_config  # noqa: E402

STORE_CLASS = "store:runtime"
EFFECTS_DIR = "effects"  # <data_dir>/effects/<pending id>/: the files code hands the code provider
RUNS_DIR = "task-runs"
CONTAINED_DIR = "contained-runs"  # <data_dir>/contained-runs/<n>/: the run folder of one contained run; no file of it ever comes back
LOCKS_DIR = "locks"                # <data_dir>/locks/: one file per lock, mode 0700 (the locks below)
CONFIG_LOCK_NAME = "config.lock"   # <data_dir>/config.lock: one change of the accepted configuration at a time
CONFIG_LOCK_WAIT = 10.0            # seconds a change waits for another to finish
CLAIM_LOCK_WAIT = 30.0             # seconds the claim lock is waited for: admission, claim and the run row are short
WRITE_LOCK_WAIT = 60.0             # seconds a writer of the project's files waits for the write lock (a run's return waits without a limit)
ROUTE_LOCK_WAIT = 1.0              # seconds a router run retries the route lock before it says the planning agent is busy
LOCK_POLL = 0.1                    # seconds between two tries of a lock that is waited for
_DEFAULT = object()                # "the default wait" of _write_lock, so that a change of WRITE_LOCK_WAIT is read at the call
# Two router runs of two projects in one service process share the lab's process-wide session (lab.session ends every
# container of the process when it closes): the router's whole session is held under this guard. A task run is its own
# process and never takes it.
_LAB_GUARD = threading.Lock()
# The variables a router call is injecting into this process's environment right now, {name: the value it had before, or
# None}, under _ENV_LOCK: a child process the dispatcher starts gets the environment with these put back (ops_runs.spawn),
# so a child never inherits a key a call put in, and does inherit one the person exported.
ENV_INJECTED = {}
_ENV_LOCK = threading.Lock()
_HELD_WRITE = threading.local()    # the write lock this thread holds, by data folder: {data_dir: [descriptor, depth]}
PREPARED_DIR = "prepared"  # <data_dir>/prepared/<run id>/: files written for one run before they enter its copy
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# The recorder of uses and verdicts (scripts/evidence.py of the checkout, ROOT, when None; a test points it at a
# stand-in). The runtime records a use of every run and the person's verdict with it, and builds nothing of its own.
EVIDENCE = None
# The secrets the runtime owns: its own key for a model's provider, with a spend cap set there. There is one for each variable a
# model of the gate file passes (pass_env), named KEY_PREFIX + the variable; the registry runtime/secrets.json lists the ones
# of today's models, and a name it lacks is registered here from the same pattern. When one is not stored, a run on the model
# uses the lab's key for it (_model_key).
KEY_PREFIX = "WB_RUNTIME_KEY_"


class OpsError(Exception):
    """An operation that was refused: a message for the person and an exit code (1 failed, 2 usage,
    3 not configured; 4, refused and not run, is only run-task's own exit, never an error's code)."""

    def __init__(self, message: str, code: int = 1, next: str | None = None):
        super().__init__(message)
        self.code = code
        self.next = next   # the terminal command that gets past the refusal (the 412: accept-config), or None


class RunBusy(OpsError):
    """The router is busy: another run of the router holds the project's route lock. An OpsError (code 1) like any
    refusal; the operations that queue their call while the router answers (`say`, `route`) catch it by its class. A
    run of a task never makes it."""


class DispatchBusy(OpsError):
    """A dispatch round of this project is already running (the dispatch lock is held). The local service's loop skips
    the project without a word; the page's dispatch answers it as a refusal."""


def _load(name: str, path: str):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def store_module():
    """The store provider as a module, found by its class through providers/resolve.py, never by a path built
    here. Its functions are the contract (providers/store/sqlite.py, "the task runtime")."""
    resolve = _load("workbench_provider_resolve", os.path.join(ROOT, "providers", "resolve.py"))
    try:
        found = resolve.resolve(STORE_CLASS, root=ROOT)
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        raise OpsError(f"the store does not resolve: {e}", 3) from None
    return _load("workbench_store_" + found["implementation"], found["path"])


def _command(name: str, project: str, **args) -> str:
    """The terminal's command for one operation, as a sentence of this layer names it: absolute, from the checkout
    this process runs from (ROOT), with the uv prefix when it was started through uv (operations.command_line, the
    one place that spells the syntax)."""
    return operations.command_line(name, project, checkout=ROOT, **args)


def _config_of(project: str) -> dict:
    """The project's configuration, refused when it cannot be read or names another workbench checkout than the one
    this process runs from: what every operation checks first."""
    try:
        cfg = project_config.load(project)
    except project_config.ConfigError as e:
        raise OpsError(str(e), 3) from None
    if cfg["workbench"] != os.path.realpath(ROOT):
        raise OpsError(f"{cfg['path']} names the workbench checkout {cfg['workbench']}, and this command runs from "
                       f"{os.path.realpath(ROOT)}: run it from the checkout the project names, or correct the file", 3)
    return cfg


def _accepted(cfg: dict, accepted) -> None:
    """Refuse (code 3) a configuration whose hash is not the accepted one."""
    if accepted != cfg["sha256"]:
        command = _command("accept-config", cfg["project"], sha256=cfg["sha256"])
        raise OpsError(f"the configuration {cfg['path']} has the hash {cfg['sha256']} and the accepted one is "
                       f"{accepted or 'none: no configuration was accepted yet'}. Read the file; when it is what you "
                       f"want, run: {command}", 3, next=command)


def context(project: str, *, check_config: bool = True) -> dict:
    """What every operation starts from: {"cfg", "store", "conn"}. The store is created or migrated here
    (idempotent), so the first operation on a project needs no separate setup step. With check_config (every
    operation but accept_config, config and service_check; version passes False only to make a store that does not
    exist yet, and checks the hash itself on every call), the configuration's hash must be the one the person
    accepted last."""
    cfg = _config_of(project)
    store = store_module()
    try:
        store.init_db(cfg["store_db"])
        conn = store.open_db(cfg["store_db"])
    except store.StoreError as e:
        raise OpsError(f"the store at {cfg['store_db']}: {e}", e.code) from None
    if check_config:
        try:
            accepted = store.cursor_get(conn, project_config.ACCEPTED)
        except store.StoreError as e:
            raise OpsError(f"the store at {cfg['store_db']}: {e}", e.code) from None
        _accepted(cfg, accepted)
    return {"cfg": cfg, "store": store, "conn": conn, "root": ROOT}


def _stored(ctx: dict, function, *args, **kwargs):
    """Call one function of the store; its refusal becomes this layer's."""
    try:
        return function(ctx["conn"], *args, **kwargs)
    except ctx["store"].StoreError as e:
        raise OpsError(str(e), e.code) from None


def _text(value, what: str) -> str:
    """Text the person typed: line ends as \\n, no other control character, not empty."""
    if not isinstance(value, str) or not value.strip():
        raise OpsError(f"{what} is empty", 2)
    return CONTROL.sub(" ", value.replace("\r\n", "\n").replace("\r", "\n")).strip()


def own_key_name(variable: str) -> str:
    """The name of the runtime's own secret for the variable a model's credential travels under."""
    return KEY_PREFIX + variable


def _own_key(variable: str) -> tuple:
    """(value or None, reason or None): the runtime's own key for the credential variable of a model, through the secret
    resolver (providers/secrets/resolver.py) with the registry runtime/secrets.json, and, for a variable it does not list, an
    entry registered from the same pattern (store username runtime-<the variable in lower case, hyphens>). The environment is
    looked at first, then the OS secret store. The value is never printed, logged, stored or put in a message."""
    name = own_key_name(variable)
    try:
        resolver = _load("workbench_secret_resolver_runtime", os.path.join(ROOT, "providers", "secrets", "resolver.py"))
        resolver.register_file(os.path.join(ROOT, "runtime", "secrets.json"))
        if name not in resolver.REGISTRY:
            resolver.register([{"name": name, "purpose": f"the task runtime's own key for the models whose credential is {variable}; when it is "
                                                        "stored, every run the runtime routes to such a model uses it, and otherwise such a run uses "
                                                        "the lab's key for the model",
                                "permission": "optional: a key used only by the task runtime, with a spend cap set at the provider",
                                "readers": ["runtime/ops_core.py"],
                                "store_username": "runtime-" + variable.lower().replace("_", "-")}], origin="the runtime")
        found = resolver.resolve(name)
    except Exception as e:  # an interpreter the resolver does not run on, a missing store library, a bad registry
        sys.modules.pop("workbench_secret_resolver_runtime", None)
        return None, f"the secret resolver could not be used: {type(e).__name__}"
    if not found:
        return None, None
    return found[0], None


def _model_key(model: str) -> dict:
    """The key a run on the model would use: {"value", "source", "reason"}, in this order.
    source "runtime": the runtime's own key for the model's credential variable (_own_key), when it is stored and the model
      passes exactly one variable, under which it travels (ops._key_in_environment). It wins: a person who wants a capped key of
      the runtime's own stores it.
    source "lab": no key of its own, and every variable the gate file names for the model is set or found in the secret
      store, by the lab's own lookup (lab.credential_missing). value is None: the value stays the lab's, which run_skill passes
      as it does for a lab run. A model whose entry names no variable needs none and is "lab".
    source None: neither, and reason says why.
    Only the source is shown, by name; the value is never printed, logged, stored or put in a message."""
    reasons = []
    try:
        names = lab.reference(model)["pass_env"]
        value, reason = (_own_key(names[0]) if names else (None, None))
        if reason:
            reasons.append(reason)
        if value is not None:
            if len(names) == 1:
                return {"value": value, "source": "runtime", "reason": None}
            reasons.append(f"{model} passes {len(names)} variables; the runtime's own key travels under one")
        missing = lab.credential_missing(model) if names else []
    except Exception as e:  # a gate file the facade refuses, a model it does not list, a resolver that does not run here
        return {"value": None, "source": None, "reason": f"the key for {model} could not be looked up: {type(e).__name__}"}
    if missing == []:
        return {"value": None, "source": "lab", "reason": None}
    if value is None and not reasons:
        reasons.append(f"the runtime's own key ({own_key_name(names[0])}) is not stored")
    if missing:
        reasons.append(f"the lab's key for {model} ({', '.join(missing)}) is neither set nor in the secret store")
    return {"value": None, "source": None, "reason": f"no key for {model}: " + "; ".join(reasons)}


class Keys:
    """The keys of the models of the gate file, looked up when asked and once: keys[model] is _model_key(model). A model the
    gate file does not list has no key (source None) and a reason. found(model) is whether one was found. One object is made
    for a round, a run or a read, so a secret store is asked once for each model."""

    def __init__(self):
        self._found = {}

    def __getitem__(self, model: str) -> dict:
        if model not in self._found:
            self._found[model] = _model_key(model)
        return self._found[model]

    def get(self, model: str, default=None) -> dict:
        return self[model] if model else default

    def found(self, model: str) -> bool:
        return self[model]["source"] is not None


def _keys() -> Keys:
    """A new set of lookups of the models' keys (Keys)."""
    return Keys()


def _model_billing(model: str, adapter=None, manifests=None):
    """How the credential a run on this model uses is billed: "subscription", "metered" or "free", or None when no manifest
    says (runtime/billing.py). The variables are those the gate file names for the model (what lab.run_skill passes, the
    runtime's own key travelling under the first of them); adapter is the route's, else the model's; manifests are read once
    by a caller that asks for several models (billing.load). The price table decides nothing here: a model is metered
    when its credential is declared metered."""
    found = lab.reference(model)
    return billing.of_route(manifests or billing.load(ROOT), adapter or found["adapter"], found["pass_env"])


def _metered_models(manifests=None) -> set:
    """The ids of the gate file's models whose credential is billed by use: the rule of a run recorded before the billing
    column (autonomy.history_billing), a run on a metered model is metered. A model whose billing no manifest says is not in it."""
    manifests = manifests or billing.load(ROOT)
    return {model for model in lab.models() if _model_billing(model, manifests=manifests) == "metered"}


def _caps_in_use(runs, keys) -> dict:
    """{"runs": bool, "spend": bool}: whether each daily cap has something to count in this project, so that a page draws
    only the meters that mean something. A cap is in use when a run of the day (runs, with their billing filled in) used a
    credential billed that way, or when a model the runtime can run on has such a credential: the default model's always, any
    other model's when a key for it was found (keys, the caller's Keys). When nothing says either (the default model's billing
    unknown and no other key) both are in use, so that a page shows both meters as it does for a service that sends none.
    Names no model."""
    words, manifests = {run.get("billing") for run in runs}, billing.load(ROOT)
    default = lab.default_model()
    words.add(_model_billing(default, manifests=manifests))
    for model in lab.models():
        if model != default and keys is not None and keys.found(model):
            words.add(_model_billing(model, manifests=manifests))
    use = {"runs": bool(words & set(autonomy.RUNS_BILLINGS)), "spend": bool(words & set(autonomy.SPEND_BILLINGS))}
    return use if any(use.values()) else {"runs": True, "spend": True}


@contextlib.contextmanager
def _config_lock(cfg: dict):
    """The project's configuration lock (<data_dir>/config.lock), held while the configuration file is changed or
    accepted: set_mode and accept_config of every process (the service's threads, the terminal) take it one after the
    other, so that a change made from a copy of the file read before another one finished can be found out (set_mode
    re-reads the file and the accepted hash under it). Waits up to CONFIG_LOCK_WAIT seconds, then refuses."""
    os.makedirs(cfg["data_dir"], mode=0o700, exist_ok=True)
    lock = os.open(os.path.join(cfg["data_dir"], CONFIG_LOCK_NAME), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + CONFIG_LOCK_WAIT
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise OpsError("another change of the configuration is in progress: try again in a moment", 1) from None
                time.sleep(0.05)
        yield
    finally:
        os.close(lock)


def _locks_dir(cfg: dict) -> str:
    """<data_dir>/locks/, made with mode 0700 when it is not there."""
    folder = os.path.join(cfg["data_dir"], LOCKS_DIR)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    return folder


def _try_lock(cfg: dict, name: str, shared: bool = False):
    """Take the lock file <data_dir>/locks/<name> without waiting: the open descriptor, or None when another holder has
    it. It writes nothing in the file. The caller closes the descriptor to release the lock (a closed or dead process
    releases it too, so a held lock is the proof that its holder is alive). A lock file may be deleted by whoever holds it
    (a finished task's, `ops_runs._drop_task_locks`): a lock taken on a file that is no longer at its path is let go and taken again
    on the file that is. shared: take it LOCK_SH (a probe: any number of probes hold it together, none of them blocks another;
    only an exclusive holder makes it fail). INVARIANT: whoever deletes a lock file does it as its last action while it
    still holds the lock, just before it closes the descriptor; the inode check below depends on it."""
    path = os.path.join(_locks_dir(cfg), name)
    while True:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return None
        try:
            if os.fstat(fd).st_ino == os.stat(path).st_ino:
                return fd
        except OSError:
            pass
        os.close(fd)  # the file was deleted (a finished task's lock) between the open and the lock: lock the new one


@contextlib.contextmanager
def _task_lock(cfg: dict, task_id: int):
    """The lock of one task (task-<id>.lock), held by the process that runs it from before its claim to after its
    finish: the proof that the task is alive. Once held, the file holds, as text, "<pid> <pgid>" of this process (read only
    by `stop-runs --all`, which signals the group only when the process leads it); it is emptied before the lock is let
    go, so that nobody reads a stale owner. Refused (code 1) when another process holds it. Only `run_task` uses it."""
    fd = _try_lock(cfg, f"task-{task_id}.lock")
    if fd is None:
        raise OpsError(f"task {task_id} is already being run by another process", 1)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {os.getpgrp()}\n".encode("ascii"))
        yield
    finally:
        try:
            os.ftruncate(fd, 0)
        finally:
            os.close(fd)


def _lock_owner(cfg: dict, task_id: int):
    """(pid, pgid) a task lock's holder wrote, or None when the file is missing, empty or unreadable. It says nothing
    about whether the lock is held: the caller asks `_try_lock` first."""
    try:
        with open(os.path.join(_locks_dir(cfg), f"task-{task_id}.lock"), encoding="ascii", errors="replace") as f:
            words = f.read(64).split()
    except OSError:
        return None
    if len(words) != 2 or not all(w.isdigit() and int(w) > 1 for w in words):
        return None
    return int(words[0]), int(words[1])


def _lock_pgid(cfg: dict, task_id: int):
    """The process group id of the holder of a task lock (see _lock_owner), or None."""
    owner = _lock_owner(cfg, task_id)
    return owner[1] if owner else None


@contextlib.contextmanager
def _route_lock(cfg: dict):
    """The router's lock (route.lock), held for the whole run of the router and the proof that such a run is alive. One
    router run per project: another holder is waited for about ROUTE_LOCK_WAIT seconds, then RunBusy."""
    deadline = time.monotonic() + ROUTE_LOCK_WAIT
    while True:
        fd = _try_lock(cfg, "route.lock")
        if fd is not None:
            break
        if time.monotonic() >= deadline:
            raise RunBusy("the planning agent is answering another request of this project", 1)
        time.sleep(LOCK_POLL)
    try:
        yield
    finally:
        os.close(fd)


@contextlib.contextmanager
def _claim_lock(cfg: dict):
    """The claim lock (claim.lock), short: held around the admission of a task, its claim and the run row, and around
    the router's budget and run row, so that two processes cannot pass the same cap. Waits up to CLAIM_LOCK_WAIT."""
    deadline = time.monotonic() + CLAIM_LOCK_WAIT
    while True:
        fd = _try_lock(cfg, "claim.lock")
        if fd is not None:
            break
        if time.monotonic() >= deadline:
            raise OpsError(f"the project's claim lock stayed busy for {CLAIM_LOCK_WAIT:.0f} s; try again", 1)
        time.sleep(LOCK_POLL)
    try:
        yield
    finally:
        os.close(fd)


@contextlib.contextmanager
def _write_lock(cfg: dict, wait=_DEFAULT):
    """The write lock (write.lock): around every write into the project's files and every external effect. Re-entrant
    per thread: a writer that calls another writer does not wait on itself (a thread-local table keeps the descriptor and
    a depth per data folder). Another holder is waited for `wait` seconds (default WRITE_LOCK_WAIT, read when it is
    called), then refused (code 1); `wait=None` waits without a limit, for a run's return, whose holders are bounded
    (each provider call has its timeout)."""
    if wait is _DEFAULT:
        wait = WRITE_LOCK_WAIT
    key = cfg["data_dir"]
    table = getattr(_HELD_WRITE, "table", None)
    if table is None:
        table = _HELD_WRITE.table = {}
    if key in table:
        table[key][1] += 1
        try:
            yield
        finally:
            table[key][1] -= 1
        return
    deadline = None if wait is None else time.monotonic() + wait
    while True:
        fd = _try_lock(cfg, "write.lock")
        if fd is not None:
            break
        if deadline is not None and time.monotonic() >= deadline:
            raise OpsError(f"the project's files stayed busy for {wait:.0f} s; try again", 1)
        time.sleep(0.05)
    table[key] = [fd, 1]
    try:
        yield
    finally:
        table[key][1] -= 1
        if table[key][1] == 0:
            del table[key]
            os.close(fd)


@contextlib.contextmanager
def _dispatch_lock(cfg: dict):
    """The dispatch lock (dispatch.lock), taken without waiting: one dispatch round of a project at a time. A waiting
    round holds it until its children end. DispatchBusy when another round holds it."""
    fd = _try_lock(cfg, "dispatch.lock")
    if fd is None:
        raise DispatchBusy("a dispatch round of this project is already running", 1)
    try:
        yield
    finally:
        os.close(fd)


@contextlib.contextmanager
def _effect_lock(cfg: dict, request_id):
    """The lock of the effects of one request (effect-<request id>.lock), held while an approved effect executes (PAR-6): a
    code task of that request is not claimed meanwhile (`_effects_running`, read by `ops_runs`), and two effects of one
    request do not execute together. Waited for about ROUTE_LOCK_WAIT seconds (a probe of `_effects_running` holds it for a
    moment), then refused. No request, no lock."""
    if request_id is None:
        yield
        return
    deadline = time.monotonic() + ROUTE_LOCK_WAIT
    while True:
        fd = _try_lock(cfg, f"effect-{request_id}.lock")
        if fd is not None:
            break
        if time.monotonic() >= deadline:
            raise OpsError("an effect of this request is already executing; approve when it ends", 1)
        time.sleep(LOCK_POLL)
    try:
        yield
    finally:
        os.close(fd)


def _effects_running(cfg: dict) -> frozenset:
    """The ids of the requests with an effect executing now: the effect locks that are held (probed with `_try_lock`, which
    writes nothing, and let go at once)."""
    try:
        names = os.listdir(_locks_dir(cfg))
    except OSError:
        return frozenset()
    found = set()
    for name in names:
        match = re.fullmatch(r"effect-(\d+)\.lock", name)
        if match is None:
            continue
        fd = _try_lock(cfg, name, shared=True)  # shared: two probes never see each other as an executing effect
        if fd is None:
            found.add(int(match.group(1)))
        else:
            os.close(fd)
    return frozenset(found)


def _midnight() -> str:
    """The start of today in local time, ISO-8601: the day a policy's count starts from."""
    return datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
