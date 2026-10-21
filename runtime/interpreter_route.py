#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The routes of the interpreter's model calls, and the one function that makes a call (package IX-2b).

runtime/interpreter_routes.json lists the routes the experiment may use: a route is a model, the pinned provider that serves
it, the address, the limits that never widen (no fallback provider, no prompt kept for training) and the one secret that pays
for it. This module checks the file, builds what the provider `model:text` (providers/model/chat-http.py) is given, and calls it.

    load(root=None)                       the file, checked: each row is of a `kind`, "http" or "account"; exactly one route marked `reference`.
                                          An `http` row: closed keys, an id of the form [a-z0-9][a-z0-9.-]{0,63}, an https address without a
                                          login, a `key` that is a name of runtime/secrets.json, a `key_prefix` equal to the one KEY_SHAPES holds
                                          for the address's host, no fallback, data_collection "deny", an allow-list of models (an `upstream_model`
                                          must start with an entry of HTTP_MODELS for its host, and `model` is MODEL_PREFIX plus it: an alias, a
                                          preset or a router is refused whatever its pin), and, as a second layer, no model of the vendor whose
                                          models are measured on the maintainer's own account (VENDOR_WORDS in model, upstream_model or pin, any
                                          case). An `account` row (a model of that vendor, measured on the maintainer's own subscription through the
                                          adapter's text runner, for tests only): closed keys (ACCOUNT_KEYS, no `key`), a model of that vendor, the
                                          vendor as `pin`, closed `params`, a deadline, the runner's version and two sha256 (the runner's files and
                                          the request the vendor's tool sends). Raises RouteError (a ValueError).
    daily_routes(root=None)               the rows of kind `http` only: the routes that may run for a person every day. An account route is for tests,
                                          never the daily route (the go reads this list, never `load`)
    stdin_route(route)                    what the provider is shown of an `http` route: id, base_url, model (the upstream id), pin,
                                          allow_fallbacks, data_collection, zdr, cache_breakpoint
    route_sha256(route)                   the sha256 of the canonical JSON of stdin_route(route) for an `http` row; for an `account` row, of every key
                                          of the row but `retention` and `reference` (evals/interpreter_status.py computes it the same way): the value
                                          a caller puts in `accepted`
    complete(route_id, system, user, *, accepted, deadline_ms, run=None, root=None, temperature=0, max_tokens=300, reasoning="off")
        -> {"ok": True, "text", "finish", "usage", "latency_ms", "upstream"} | {"ok": False, "code": "E_..."}
        On an `account` row the row's `params` and `deadline_ms` replace the arguments `temperature`, `max_tokens`, `reasoning` and `deadline_ms`
        (the hash covers them, so a caller cannot measure under other settings), the hash must be in `accepted` (else E_ROUTE), and the call is
        `lab.account_text` (runtime/lab.py, imported when it is first needed): the adapter's text runner, with the credential of the lab's model.

`accepted` lists the route hashes the person agreed to; the provider refuses any other. The key is read through the secret
resolver (providers/secrets/resolver.py) from the registry runtime/secrets.json, the pattern of runtime/ops_core.py, and reaches
the provider's process only as MODEL_TEXT_KEY, and only when it starts with the route's `key_prefix` (a key of another service is
E_KEY here, before the provider starts, and again in the provider). A model of that vendor is measured on the maintainer's own account,
never through a metered key (docs/decisions.md, 2026-10-21); the account token is never a route's `key` and never reaches this module (ALLOWED_KEYS). A failure is a code and nothing else: a provider's reason and its error text are
never read, returned or logged, and no prompt, reply or line is written to disk or to a log here.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project_config  # noqa: E402  (the same folder: the one loader of providers/resolve.py)

ROOT = os.path.dirname(HERE)
CLASS = "model:text"
KEY_VARIABLE = "MODEL_TEXT_KEY"
ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
CODE = re.compile(r"chat-http: (E_[A-Z_]+)")
ROUTE_KEYS = ("id", "kind", "model", "upstream_model", "base_url", "pin", "allow_fallbacks", "data_collection", "zdr", "cache_breakpoint",
              "key", "key_prefix", "reference", "retention")
# The keys of an `account` row: closed, and none of them is a secret (the token is the lab's, found by its own lookup).
ACCOUNT_KEYS = ("id", "kind", "model", "upstream_model", "lab_model", "pin", "params", "deadline_ms", "runner_version", "runner_sha256",
                "envelope_sha256", "reference", "retention")
ACCOUNT_PARAM_KEYS = ("max_tokens", "reasoning", "temperature")
REASONING = ("off", "low", "medium", "high", "xhigh", "max")      # the text contract's words (contracts/runtime.md, "The text contract")
HEX64 = re.compile(r"[0-9a-f]{64}")
FINISHES = ("stop", "length", "other")
KINDS = ("http", "account")   # http: an HTTP service reached with a metered key; account: the maintainer's own subscription, through the adapter's text runner
UNHASHED = ("retention", "reference")      # the keys of an account row its hash leaves out
# What a key of each service starts with, by the host of its address: a closed table. A route's `key_prefix` is the entry of its host, and
# a host not listed here is refused, so a credential of another service (a subscription token, a vendor key) is never sent to one listed.
KEY_SHAPES = {"openrouter.ai": "sk-or-v1-"}
# The models a route may name, by host: an allow-list beside KEY_SHAPES. An `upstream_model` must start with an entry of its host's tuple, and `model`
# is MODEL_PREFIX plus `upstream_model`; anything else (an alias, a preset, a router that picks the model) is refused, whatever the pin says. The
# vendor words below stay as a second layer. Both checks apply to `http` rows only.
HTTP_MODELS = {"openrouter.ai": ("deep" + "seek/",)}
MODEL_PREFIX = {"openrouter.ai": "openrouter/"}
# A model of this vendor is never reached over HTTP with a metered key; the words are matched in the model, upstream_model and pin, any case. They are
# written in pieces so that this file names no AI tool (rule R19 of the platform plan, runtime/tests/test_runtime_rules.py).
VENDOR_WORDS = ("clau" + "de", "anth" + "ropic")
ACCOUNT_MODEL_PREFIX = VENDOR_WORDS[0] + "-"     # an account row's `model` and `upstream_model` start with it; its `pin` is VENDOR_WORDS[1]
# The secrets a route may name: the one the interpreter reads, and only while this module is among that secret's readers. Another
# registered secret (a subscription token, an account token) is never sent to a model service, whatever a routes file says.
ALLOWED_KEYS = frozenset({"WB_RUNTIME_KEY_OPENROUTER_API_KEY"})
READER = "runtime/interpreter_route.py"
MARGIN_SECONDS = 0.5      # beyond deadline_ms: the provider enforces the deadline itself, so only its start and exit are left
MAX_DEADLINE_MS = 600000  # the text contract's largest deadline
MAX_TOKENS = 64000        # and its largest max_tokens


class RouteError(ValueError):
    """The routes file is not what this module accepts."""


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _registered_names(root: str) -> dict:
    """name -> readers of each secret runtime/secrets.json lists."""
    try:
        with open(os.path.join(root, "runtime", "secrets.json"), encoding="utf-8") as f:
            return {e["name"]: list(e["readers"]) for e in json.load(f)["secrets"]}
    except (OSError, ValueError, KeyError, TypeError):
        raise RouteError("runtime/secrets.json cannot be read") from None


def _check_route(route, names: dict, seen: set) -> None:
    if not isinstance(route, dict) or set(route) != set(ROUTE_KEYS):
        raise RouteError("a route has exactly the keys " + ", ".join(ROUTE_KEYS))
    for key in ("kind", "model", "upstream_model", "base_url", "data_collection", "key", "key_prefix", "retention"):
        if not isinstance(route[key], str) or not route[key].strip():
            raise RouteError(f"route {key} is a non-empty text")
    if route["kind"] != "http":
        raise RouteError("an http route has kind http")
    for key in ("model", "upstream_model", "pin"):
        if isinstance(route[key], str) and any(word in route[key].lower() for word in VENDOR_WORDS):
            raise RouteError("a model of that vendor is not reached over HTTP with a metered key: it is measured on the maintainer's own account")
    if not isinstance(route["id"], str) or not ID.fullmatch(route["id"]):
        raise RouteError("a route id is lower-case letters, digits, dots and hyphens, 64 characters at most")
    if route["id"] in seen:
        raise RouteError(f"route {route['id']}: the id is used twice")
    seen.add(route["id"])
    if not isinstance(route["pin"], str) or not route["pin"].strip():
        raise RouteError(f"route {route['id']}: pin is the name of the provider that serves it (every route is pinned)")
    for key in ("allow_fallbacks", "zdr", "cache_breakpoint", "reference"):
        if not isinstance(route[key], bool):
            raise RouteError(f"route {route['id']}: {key} is true or false")
    if route["allow_fallbacks"] is not False or route["data_collection"] != "deny":
        raise RouteError(f"route {route['id']}: allow_fallbacks is false and data_collection is deny, always")
    try:
        parts = urlsplit(route["base_url"])
        parts.port  # noqa: B018  (raises ValueError on a bad port)
    except ValueError:
        raise RouteError(f"route {route['id']}: base_url is not an address") from None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise RouteError(f"route {route['id']}: base_url is an https address with no login, query or fragment")
    host = (parts.hostname or "").lower()
    if not route["upstream_model"].startswith(HTTP_MODELS.get(host, ())) or route["model"] != MODEL_PREFIX.get(host, "\0") + route["upstream_model"]:
        raise RouteError(f"route {route['id']}: upstream_model must start with a model the host's allow-list names, and model is the host's prefix plus it")
    if KEY_SHAPES.get(host) != route["key_prefix"]:
        raise RouteError(f"route {route['id']}: key_prefix must be the one KEY_SHAPES holds for the host of base_url, and the host must be listed")
    if route["key"] not in names or route["key"] not in ALLOWED_KEYS or READER not in names[route["key"]]:
        raise RouteError(f"route {route['id']}: key must be one of {sorted(ALLOWED_KEYS)}, listed in runtime/secrets.json with {READER} among its readers")


def _check_account(route, seen: set) -> None:
    """The rules of an `account` row (docstring of this module). It has no `key`: the token it spends is the lab's own."""
    if not isinstance(route, dict) or set(route) != set(ACCOUNT_KEYS):
        raise RouteError("an account route has exactly the keys " + ", ".join(ACCOUNT_KEYS))
    for key in ("id", "model", "upstream_model", "lab_model", "pin", "runner_version", "retention"):
        if not isinstance(route[key], str) or not route[key].strip():
            raise RouteError(f"account route {key} is a non-empty text")
    if not ID.fullmatch(route["id"]):
        raise RouteError("a route id is lower-case letters, digits, dots and hyphens, 64 characters at most")
    if route["id"] in seen:
        raise RouteError(f"route {route['id']}: the id is used twice")
    seen.add(route["id"])
    if route["kind"] != "account":
        raise RouteError(f"route {route['id']}: kind is account")
    if not route["model"].startswith(ACCOUNT_MODEL_PREFIX) or not route["upstream_model"].startswith(ACCOUNT_MODEL_PREFIX) or route["pin"] != VENDOR_WORDS[1]:
        raise RouteError(f"route {route['id']}: an account route names a model of the vendor whose models are measured on the account, and that vendor as its pin")
    for key in ("runner_sha256", "envelope_sha256"):
        if not isinstance(route[key], str) or not HEX64.fullmatch(route[key]):
            raise RouteError(f"route {route['id']}: {key} is a sha256 (64 lower-case hexadecimal digits)")
    if not isinstance(route["reference"], bool):
        raise RouteError(f"route {route['id']}: reference is true or false")
    if isinstance(route["deadline_ms"], bool) or not isinstance(route["deadline_ms"], int) or not 1 <= route["deadline_ms"] <= MAX_DEADLINE_MS:
        raise RouteError(f"route {route['id']}: deadline_ms is a whole number of milliseconds from 1 to {MAX_DEADLINE_MS}")
    params = route["params"]
    if not isinstance(params, dict) or set(params) != set(ACCOUNT_PARAM_KEYS):
        raise RouteError(f"route {route['id']}: params has exactly the keys " + ", ".join(ACCOUNT_PARAM_KEYS))
    tokens = params["max_tokens"]
    if isinstance(tokens, bool) or not isinstance(tokens, int) or not 1 <= tokens <= MAX_TOKENS:
        raise RouteError(f"route {route['id']}: params.max_tokens is a whole number from 1 to {MAX_TOKENS}")
    if params["reasoning"] not in REASONING or params["temperature"] is not None:
        raise RouteError(f"route {route['id']}: params.reasoning is one of {list(REASONING)} and params.temperature is null (the CLI sends its own)")


def load(root=None) -> dict:
    root = root or ROOT
    try:
        with open(os.path.join(root, "runtime", "interpreter_routes.json"), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise RouteError("runtime/interpreter_routes.json cannot be read") from None
    if not isinstance(doc, dict) or set(doc) != {"v", "routes"} or doc["v"] != 1 or not isinstance(doc["routes"], list) or not doc["routes"]:
        raise RouteError("the routes file is {v: 1, routes: [...]} with at least one route")
    names, seen = _registered_names(root), set()
    for route in doc["routes"]:
        if isinstance(route, dict) and route.get("kind") == "account":
            _check_account(route, seen)
        else:
            _check_route(route, names, seen)
    if sum(1 for r in doc["routes"] if r["reference"]) != 1:
        raise RouteError("exactly one route is the reference")
    return doc


def daily_routes(root=None) -> list:
    """The rows a person's daily call may use: kind `http` only. The go and the runtime take their route from here, never from load()."""
    return [r for r in load(root)["routes"] if r["kind"] == "http"]


def find(route_id: str, root=None) -> dict:
    for route in load(root)["routes"]:
        if route["id"] == route_id:
            return route
    raise RouteError(f"no route {route_id!r}")


def stdin_route(route: dict) -> dict:
    if route.get("kind") == "account":
        raise RouteError("an account route is not shown to the provider: it has none")
    return {"id": route["id"], "base_url": route["base_url"], "model": route["upstream_model"], "pin": route["pin"],
            "allow_fallbacks": route["allow_fallbacks"], "data_collection": route["data_collection"], "zdr": route["zdr"],
            "cache_breakpoint": route["cache_breakpoint"]}


def route_sha256(route: dict) -> str:
    if route.get("kind") == "account":
        return hashlib.sha256(canonical({k: v for k, v in route.items() if k not in UNHASHED})).hexdigest()
    return hashlib.sha256(canonical(stdin_route(route))).hexdigest()


def _key(name: str, root: str):
    """The value of the secret `name`, or None. Never printed, logged, stored or put in a message."""
    try:
        spec = importlib.util.spec_from_file_location("workbench_secret_resolver_interpreter",
                                                      os.path.join(root, "providers", "secrets", "resolver.py"))
        resolver = sys.modules.get(spec.name)
        if resolver is None:
            resolver = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = resolver     # its dataclasses look their module up by name
            spec.loader.exec_module(resolver)
        resolver.register_file(os.path.join(root, "runtime", "secrets.json"))
        got = resolver.resolve_state(name)
    except Exception:   # noqa: BLE001 - an interpreter the resolver does not run on, a missing store library: no key, no reason
        sys.modules.pop("workbench_secret_resolver_interpreter", None)
        return None
    return got.value if got.state == "found" and got.value else None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _shaped(out, upstream):
    """The reply in the shape every caller reads, or the code E_RESPONSE when what came back is not a reply."""
    usage = out.get("usage") if isinstance(out.get("usage"), dict) else {}
    if out.get("v") != 1 or not isinstance(out.get("text"), str) or out.get("finish") not in FINISHES:
        return {"ok": False, "code": "E_RESPONSE"}
    return {"ok": True, "text": out["text"], "finish": out["finish"],
            "usage": {k: _count(usage.get(k)) for k in ("input", "output", "cache_read", "cache_write")},
            "latency_ms": _count(out.get("latency_ms")), "upstream": upstream if isinstance(upstream, str) else None}


def _lab():
    """runtime/lab.py, imported when an account route first needs it: an http call, a replay and a status never load the lab."""
    return importlib.import_module("lab")


def _complete_account(route, system, user, accepted, run) -> dict:
    if route_sha256(route) not in list(accepted):
        return {"ok": False, "code": "E_ROUTE"}
    if not (isinstance(system, str) and isinstance(user, str)):
        return {"ok": False, "code": "E_USAGE"}
    try:
        got = _lab().account_text(route, system, user, run=run)
    except Exception:   # noqa: BLE001 - a lab that cannot run here: a code, never the reason (it can hold the request)
        return {"ok": False, "code": "E_INTERNAL"}
    if not isinstance(got, dict) or got.get("ok") is not True:
        code = got.get("code") if isinstance(got, dict) else None
        return {"ok": False, "code": code if isinstance(code, str) and re.fullmatch(r"E_[A-Z_]+", code) else "E_UNKNOWN"}
    return _shaped({"v": 1, **got}, route["pin"])


def complete(route_id, system, user, *, accepted, deadline_ms, run=None, root=None, temperature=0, max_tokens=300,
             reasoning="off") -> dict:
    root = root or ROOT
    try:
        route = find(route_id, root)
    except RouteError:
        return {"ok": False, "code": "E_ROUTE"}
    if route["kind"] == "account":      # its own params and deadline are the call's (the module docstring); the arguments above are not read
        return _complete_account(route, system, user, accepted, run)
    value = _key(route["key"], root)
    if value is None or not value.startswith(route["key_prefix"]):
        return {"ok": False, "code": "E_KEY"}        # a key of another service is never put in the provider's environment
    resolve = project_config.resolver(root)
    if not (isinstance(system, str) and isinstance(user, str)):
        return {"ok": False, "code": "E_USAGE"}
    request = {"v": 1, "route": stdin_route(route), "accepted": list(accepted), "key_prefix": route["key_prefix"],
               "params": {"temperature": temperature, "max_tokens": max_tokens, "reasoning": reasoning},
               "system": system, "user": user, "deadline_ms": deadline_ms}
    env = resolve.provider_environment(CLASS, env={**os.environ, KEY_VARIABLE: value}, passes=(KEY_VARIABLE,))
    try:
        out = resolve.call(CLASS, "complete", [], root=root, stdin=json.dumps(request),      # ASCII-escaped: a lone surrogate cannot fail to encode here
                           timeout=deadline_ms / 1000.0 + MARGIN_SECONDS, env=env, run=run)
    except (ValueError, UnicodeError):      # never read e.object or the message: they can hold the whole request
        return {"ok": False, "code": "E_USAGE"}
    except resolve.ProviderCallError as e:
        found = CODE.fullmatch(e.stderr_last or "")      # the last line of stderr alone: reason and stderr_tail are never read
        return {"ok": False, "code": "E_TIMEOUT" if e.kind == "timeout" else (found.group(1) if found else "E_UNKNOWN")}
    return _shaped(out, out.get("upstream"))
