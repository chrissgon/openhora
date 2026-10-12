#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The names every module of the operations layer shares, once: the checkout (ROOT), the refusal (OpsError), the
project's context and the store call, the two locks, the runtime's own key and the data-folder names.

The operations layer is six files: runtime/ops.py (the operations and the facade every shell imports),
runtime/ops_say.py (the conversation), runtime/ops_reads.py (the reads of the local interface), runtime/ops_waits.py
(the derived waits between requests), runtime/ops_config.py (the configuration's acceptance) and this one. Every
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
LOCK_NAME = "run.lock"
CONFIG_LOCK_NAME = "config.lock"   # <data_dir>/config.lock: one change of the accepted configuration at a time
CONFIG_LOCK_WAIT = 10.0            # seconds a change waits for another to finish
PREPARED_DIR = "prepared"  # <data_dir>/prepared/<run id>/: files written for one run before they enter its copy
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# The recorder of uses and verdicts (scripts/evidence.py of the checkout, ROOT, when None; a test points it at a
# stand-in). The runtime records a use of every run and the person's verdict with it, and builds nothing of its own.
EVIDENCE = None
# The one secret the runtime owns: its own key for the floor model's provider, with a spend cap set there. When it
# is not stored, a floor run uses the lab's key for the floor model (_floor_key).
FLOOR_KEY = "WB_RUNTIME_FLOOR_KEY"


class OpsError(Exception):
    """An operation that was refused: a message for the person and an exit code (1 failed, 2 usage,
    3 not configured)."""

    def __init__(self, message: str, code: int = 1, next: str | None = None):
        super().__init__(message)
        self.code = code
        self.next = next   # the terminal command that gets past the refusal (the 412: accept-config), or None


class RunBusy(OpsError):
    """The project's run lock is held: a run of a task or of the router is in progress. An OpsError (code 1) like any
    refusal; the operations that queue their call while a run is in progress (`say`, `route`) catch it by its class."""


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


def _own_key() -> tuple:
    """(value or None, reason or None): the runtime's own key for the floor model, through the secret resolver
    (providers/secrets/resolver.py) with the registry runtime/secrets.json. The value is never printed, logged,
    stored or put in a message."""
    try:
        resolver = _load("workbench_secret_resolver_runtime", os.path.join(ROOT, "providers", "secrets", "resolver.py"))
        resolver.register_file(os.path.join(ROOT, "runtime", "secrets.json"))
        found = resolver.resolve(FLOOR_KEY)
    except Exception as e:  # an interpreter the resolver does not run on, a missing store library, a bad registry
        sys.modules.pop("workbench_secret_resolver_runtime", None)
        return None, f"the secret resolver could not be used: {type(e).__name__}"
    if not found:
        return None, None
    return found[0], None


def _floor_key() -> dict:
    """The key a floor run would use: {"value", "source", "reason"}, in this order.
    source "runtime": the runtime's own key (_own_key), when it is stored and the floor tier passes exactly one
      variable, under which it travels (_key_in_environment). It wins: a person who wants a capped key of the
      runtime's own stores it.
    source "lab": no key of its own, and every variable the gate file names for the floor tier is set or found in
      the secret store, by the lab's own lookup (lab.credential_missing). value is None: the value stays the lab's,
      which run_skill passes as it does for a lab run.
    source None: neither, and reason says why; the run stays on the reference model.
    Only the source is shown, by name; the value is never printed, logged, stored or put in a message."""
    reasons = []
    value, reason = _own_key()
    if reason:
        reasons.append(reason)
    try:
        names = lab.reference("floor")["pass_env"]
        if value is not None:
            if len(names) == 1:
                return {"value": value, "source": "runtime", "reason": None}
            reasons.append(f"the floor tier passes {len(names)} variables; the runtime's own key travels under one")
        missing = lab.credential_missing("floor") if names else None
    except Exception as e:  # a gate file the facade refuses, a resolver that does not run on this interpreter
        reasons.append(f"the lab's key for the floor model could not be looked up: {type(e).__name__}")
        missing = None
    if missing == []:
        return {"value": None, "source": "lab", "reason": None}
    if value is None and not reason:
        reasons.append(f"the runtime's own key ({FLOOR_KEY}) is not stored")
    if not names:
        reasons.append("the gate file names no variable for the floor model's key")
    elif missing:
        reasons.append(f"the lab's key for the floor model ({', '.join(missing)}) is neither set nor in the secret store")
    return {"value": None, "source": None, "reason": "no key for the floor model: " + "; ".join(reasons)}


def _tier_billing(tier: str, adapter=None, manifests=None):
    """How the credential a run on this tier uses is billed: "subscription", "metered" or "free", or None when no manifest
    says (runtime/billing.py). The variables are those the gate file names for the tier (what lab.run_skill passes, the
    runtime's own key for the floor model travelling under the first of them); adapter is the route's, else the tier's;
    manifests are read once by a caller that asks for several tiers (billing.load)."""
    found = lab.reference(tier)
    return billing.of_route(manifests or billing.load(ROOT), adapter or found["adapter"], found["pass_env"])


def _caps_in_use(runs, key: dict) -> dict:
    """{"runs": bool, "spend": bool}: whether each daily cap has something to count in this project, so that a page draws
    only the meters that mean something. A cap is in use when a run of the day (runs, with their billing filled in) used a
    credential billed that way, or when a tier the runtime can run on has such a credential: the reference model's always,
    the floor model's when a key for it was found (key, the caller's _floor_key). When nothing says either (the reference tier's
    billing unknown and no floor key) both are in use, so that a page shows both meters as it does for a service that sends none.
    Names no tier and no model."""
    words, manifests = {run.get("billing") for run in runs}, billing.load(ROOT)
    words.add(_tier_billing("strong", manifests=manifests))
    try:
        if key["source"] is not None:
            words.add(_tier_billing("floor", manifests=manifests))
    except Exception:  # a floor tier the facade refuses has no key to count: the reference tier's meter stays
        pass
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


@contextlib.contextmanager
def _run_lock(cfg: dict):
    """The project's run lock (<data_dir>/run.lock), taken without waiting: a run of a task and a run of the router
    never overlap in one project. Closing the file releases it."""
    os.makedirs(cfg["data_dir"], mode=0o700, exist_ok=True)
    lock = os.open(os.path.join(cfg["data_dir"], LOCK_NAME), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RunBusy("another run of this project is in progress: one task at a time per project", 1) from None
        yield
    finally:
        os.close(lock)


def _midnight() -> str:
    """The start of today in local time, ISO-8601: the day a policy's count starts from."""
    return datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
