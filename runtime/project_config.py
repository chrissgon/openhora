#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The project's configuration of the runtime: <project>/docs/workbench/runtime.json, and its hash.

The file is written by the person who sets the project up and holds no secret (contracts/runtime.md). The
task runtime reads three keys the first runtime already defined, with the same meaning:

  "workbench"   the absolute path of the workbench checkout the runtime runs from (a reviewed revision)
  "data_dir"    an absolute folder outside every repository, for run folders and the locks
  "store_db"    the absolute path of the store database (class store:runtime)

and one more, required with no default (a project without it does not run), accepted only in the terminal like every
key of the file:

  "sources_dir" the absolute path of the sources folder (runtime/sources.py): a dedicated folder where the project's
                imported sources live, in versions. Its limits are L21 to L27 of contracts/runtime.md; here the key is
                checked as a path (sources.path_problems: not the home folder, not the filesystem root, not a link, not a
                folder that contains the project, disjoint from data_dir, store_db and the workbench checkout) and the
                folder itself is made ready, or refused, when the configuration is accepted (ops_config.accept_config)
                and checked again at every use.

The keys are closed: the file may hold only the keys of TASK_RUNTIME_KEYS and FIRST_RUNTIME_KEYS. The second
tuple keeps the first runtime's file ("agent", "harness", "mailbox"...) valid in the same file until stage 7. An
unknown key is refused, and the error names the nearest known key, so that a misspelled security key (such as
"protected_path") cannot turn a protection off in silence.

It checks "area_agents" (stage 6) with runtime/autonomy.py, agents(): each entry {"pack", "enabled", "mode",
"max_runs_per_day", "max_usd_per_day"}, an unknown key, a mode outside the five or a negative cap refused by the
agent's name; an absent cap is 0. runtime/plan.py reads the packs in scope from it. And "handlers" (stage 6): an
object {"<handler name, lowercase words joined by hyphens>": {"agent": "<an area agent of area_agents>",
"dispatch": true or false (default false), ...the handler's own settings, passed on untouched}}.

It also reads "task_board" and "documents" (stage 3), each an object or absent (None):

  "task_board": {"provider": "local", "dir": "/abs/path/board"}
  "task_board": {"provider": "<another implementation>", "expires": "YYYY-MM-DD", ...}

"provider" is an implementation shipped in the class's folder of the workbench the file names
(integration:issue-tracker for the board, integration:documents for the documents, by providers/resolve.py); for
"local", "dir" is an absolute folder that is neither inside the project's docs/ (the path rule would call an item a
document) nor inside the workbench checkout; any other provider has "expires", a date YYYY-MM-DD, after which the
runtime writes nothing to it. Every other key is the implementation's, passed on untouched. These objects are the
bounds of what the runtime writes to a platform: they are inside the file whose hash the person accepts.

It also reads "protected_paths" (a list of non-empty texts; absent means none): stage 2 asks it whether a glob
matches AGENTS.md (runtime/workcopy.py, limit L5); from stage 4 no change set may touch a path one of them covers
(runtime/changeset.py, matches(): the whole relative path against the entry with fnmatch, so `*` crosses `/`, and an
entry that ends in `/` covers everything under it). Protected paths still enter a copy; only the way back is closed.

It also reads "code" (stage 4; absent: no change set becomes a pull request): where a change set becomes a pull
request, an object {"provider": "github", "repo": "<owner>/<name>", "base": "<branch>", "branch_prefix": "wb/"}
(branch_prefix optional, default "wb/"). The repository and the base branch of a pull request come from here,
never from what a model wrote.

It also reads "dependencies" (stage 4; absent means none): the project's dependency sets, each installed by code
from a recipe of the closed table of runtime/deps.py, checked there (deps.declared()):

  "dependencies": [{"recipe": "python-requirements", "file": ".workbench-local/requirements-dev.txt"}]

It also reads "default_model" (absent means auto): the model a request or a task is routed to when nothing else chooses
one (not the request, not the task, not the agent's fixed model): a model id of the gate file, or "auto" (the cheapest
reliable pair, runtime/proof.py). When auto finds no pair it can choose, this model runs supervised, if it is an id, else the
first lab model. "price_max_age_days" (absent means 90): a price of runtime/prices.json older than that is shown as stale.

"model_prices" (stage 9; absent means {}) is RETIRED: it is still accepted, checked as before, so that no project breaks, and
it is ignored. The one price table is runtime/prices.json (runtime/prices.py), read by the cost of a run, the `auto`
ranking and the proof page; `price_warnings()` says so, and the doctor of a project (the connections read) shows it.

The hash is the sha256 of the file's bytes. Every operation compares it with the hash the person accepted last
(kept in the store's cursor ACCEPTED, written only by ops.accept_config) and refuses to act on a file that
changed. Nothing in this module reads the store.

Usage (a library):
  python3 runtime/project_config.py --help
  python3 runtime/project_config.py --project <dir>     print the configuration and its hash, as JSON

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import difflib
import hashlib
import importlib.util
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autonomy  # noqa: E402  (the same folder: the check of the key "area_agents")
import deps  # noqa: E402  (the same folder: the recipes and the check of the key "dependencies")
import operations  # noqa: E402  (the same folder: the groups and the ceilings the key "channels" is checked against)
import sources  # noqa: E402  (the same folder: the paths rules of the key "sources_dir")

REL = "docs/workbench/runtime.json"
REQUIRED = ("workbench", "data_dir", "store_db", "sources_dir")
# The top-level keys of the task runtime: the three required ones and every key this module checks or passes on.
TASK_RUNTIME_KEYS = ("workbench", "data_dir", "store_db", "sources_dir", "area_agents", "handlers", "task_board", "documents",
                     "protected_paths", "code", "dependencies", "max_cost_usd_per_run", "model_prices", "messaging", "channels",
                     "max_running", "default_model", "price_max_age_days")
# The top-level keys scripts/runtime.py, scripts/runtime_vote.py and scripts/vote_job.py read from the same file
# (the first runtime). Leaves with stage 7.
FIRST_RUNTIME_KEYS = ("agent", "harness", "model", "mailbox", "publisher", "store", "scheduler", "notification_query",
                      "first_lookback_minutes", "max_events_per_tick", "daily_cost_cap_usd", "timeout_seconds",
                      "notify", "path", "vote")
ACCEPTED = "config:accepted-sha256"  # the store's cursor that holds the hash the person accepted last
PLATFORM_KEYS = {"task_board": "integration:issue-tracker", "documents": "integration:documents"}


class ConfigError(Exception):
    """The project is not configured for the runtime; the message says what is missing."""


def path(project: str) -> str:
    return os.path.join(project, *REL.split("/"))


def load(project: str) -> dict:
    """{"project", "path", "sha256", "workbench", "data_dir", "store_db", "sources_dir", "raw"} of a project folder. The
    project folder must exist; each of the four paths must be absolute, and data_dir and store_db must lie
    outside the project and outside the workbench checkout (work data never sits in a repository); sources_dir is
    checked as a path by runtime/sources.py (it may sit inside the project: the work copy excludes it, limit L26)."""
    project = os.path.realpath(project)
    if not os.path.isdir(project):
        raise ConfigError(f"{project} is not a folder")
    file = path(project)
    try:
        with open(file, "rb") as f:
            data = f.read()
        raw = json.loads(data.decode("utf-8"))
    except OSError:
        raise ConfigError(f"{file} not found: the project is not configured for the runtime (see runtime/README.md)") from None
    except ValueError as e:
        raise ConfigError(f"{file} is not valid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{file} must hold a JSON object")
    unknown = sorted(set(raw) - set(TASK_RUNTIME_KEYS) - set(FIRST_RUNTIME_KEYS))
    if unknown:
        near = difflib.get_close_matches(unknown[0], TASK_RUNTIME_KEYS + FIRST_RUNTIME_KEYS, n=1)
        hint = f"; did you mean {near[0]}?" if near else ""
        raise ConfigError(f"runtime.json has an unknown key {unknown[0]!r}{hint}")
    out = {"project": project, "path": file, "sha256": hashlib.sha256(data).hexdigest(), "raw": raw}
    for key in REQUIRED:
        value = raw.get(key)
        if not isinstance(value, str) or not value or not os.path.isabs(value):
            raise ConfigError(f"runtime.json needs {key}: an absolute path")
        if key == "sources_dir" and os.path.islink(value.rstrip(os.sep) or os.sep):   # "link/" is not a link to islink, but it is one
            raise ConfigError("runtime.json sources_dir is a symbolic link: name the folder itself (the runtime never follows a "
                              "link out of the sources folder)")
        out[key] = os.path.realpath(value)
    for key in ("data_dir", "store_db"):
        for inside, what in ((project, "the project"), (out["workbench"], "the workbench checkout")):
            if out[key] == inside or out[key].startswith(inside + os.sep):
                raise ConfigError(f"runtime.json {key} is inside {what}: work data lives outside every repository")
    problems = sources.path_problems(out["sources_dir"], project=project, data_dir=out["data_dir"], store_db=out["store_db"],
                                     workbench=out["workbench"])
    if problems:
        raise ConfigError("runtime.json sources_dir: " + "; ".join(problems))
    protected = raw.get("protected_paths", [])
    if not isinstance(protected, list) or not all(isinstance(p, str) and p.strip() for p in protected):
        raise ConfigError("runtime.json protected_paths must be a list of path globs")
    out["protected_paths"] = list(protected)
    out["code"] = _code(raw.get("code"))
    try:
        out["dependencies"] = deps.declared(raw)
    except deps.DepsError as e:
        raise ConfigError(e.reason) from None
    for key, cls in PLATFORM_KEYS.items():
        out[key] = _platform(raw.get(key), key, cls, project, out["workbench"])
    try:
        out["area_agents"] = autonomy.agents(raw.get("area_agents"))
    except ValueError as e:
        raise ConfigError(f"runtime.json {e}") from None
    out["handlers"] = _handlers(raw.get("handlers"), out["area_agents"])
    out["model_prices"] = _model_prices(raw.get("model_prices"))
    out["default_model"] = _default_model(raw.get("default_model"))
    out["price_max_age_days"] = _price_max_age(raw)
    out["messaging"] = _messaging(raw.get("messaging"))
    out["channels"] = _channels(raw.get("channels"))
    out["max_running"] = _max_running(raw)
    return out


MAX_RUNNING_DEFAULT, MAX_RUNNING_CEILING = 3, 14  # the ceiling is the lab's total_jobs, the machine-wide limit of model calls


def _max_running(raw: dict) -> int:
    """The key "max_running": the most task runs of the project at one time, an integer from 1 to 14; absent means 3."""
    if "max_running" not in raw:
        return MAX_RUNNING_DEFAULT
    value = raw["max_running"]
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RUNNING_CEILING:
        raise ConfigError(f"runtime.json max_running must be an integer from 1 to {MAX_RUNNING_CEILING}")
    return value


POLICY_CHANNELS = operations.POLICY_CHANNELS  # the channels a policy narrows: page, mcp and messaging (chat and the terminal never)


def _channels(value) -> dict:
    """The key "channels" (the channel policy, decisions M-8 and M-13; absent means {}), checked: {"page": ["<group>", ...],
    "mcp": [...], "messaging": [...]}. Each group is one of operations.GROUPS and is valid on a channel when at least one
    operation it covers is listed by the channel's row in the table (the ceiling): a policy narrows what the table allows
    and never widens it, and the group then covers the ceiling's share of it. `approve-effects` is valid on the page only.
    A policy for the page or the MCP mode lists `read`. `chat` and `terminal` are errors: the conversation's input is local
    access, equal to the terminal, and neither is narrowed. A channel that has no entry keeps its ceiling, except messaging,
    which keeps operations.DEFAULT_POLICY (read, talk, answer). Like every key of the file, a change takes effect after
    accept-config in the terminal."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("runtime.json channels must be an object from a channel to a list of groups")
    out = {}
    for channel, groups in value.items():
        if channel in ("chat", "terminal"):
            raise ConfigError(f"runtime.json channels.{channel}: the {channel} is never narrowed (its input is local access); "
                              f"the channels with a policy are {', '.join(POLICY_CHANNELS)}")
        if channel not in POLICY_CHANNELS:
            raise ConfigError(f"runtime.json channels: {channel!r} has no policy; the channels with one are {', '.join(POLICY_CHANNELS)} "
                              "(the terminal and the conversation are never narrowed)")
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise ConfigError(f"runtime.json channels.{channel} must be a list of group names")
        for group in groups:
            if group not in operations.GROUPS:
                raise ConfigError(f"runtime.json channels.{channel}: {group!r} is not a group (known: {', '.join(operations.GROUPS)})")
            if group in operations.PAGE_ONLY_GROUPS and channel != "page":
                raise ConfigError(f"runtime.json channels.{channel}: the group {group!r} is valid on the page only "
                                  "(an effect is approved in the terminal or on the page, with its hash)")
            names = operations.GROUPS[group]["operations"]
            if not any(channel in operations.by_name(name)["channels"] for name in names):
                raise ConfigError(f"runtime.json channels.{channel}: the group {group!r} covers {', '.join(names)}, which the table "
                                  f"of operations does not give the channel {channel}; "
                                  "a policy narrows the ceiling and never widens it")
        if channel in operations.MUST_READ and "read" not in groups:
            raise ConfigError(f"runtime.json channels.{channel} must list the group 'read' (the {channel} reads what it shows)")
        out[channel] = list(dict.fromkeys(groups))
    return out


MESSAGING_KEYS = ("senders", "notices", "page_url")
NOTICES = ("text", "count")
PLATFORM_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _messaging(value) -> dict:
    """The key "messaging" (the messaging bridge, runtime/messaging.py; absent means no sender and the defaults), checked:
    {"senders": {"<platform>": ["<sender id>", ...]}, "notices": "text" or "count" (default "text"), "page_url": an
    http:// or https:// URL, or null}. A platform is lowercase words joined by hyphens, a sender id is non-empty text
    without a space. Nothing in it is a secret (the bot's token is read from the secret store), and, as every key of
    the file, a change takes effect only after the person runs accept-config in the terminal."""
    if value is None:
        return {"senders": {}, "notices": "text", "page_url": None}
    if not isinstance(value, dict):
        raise ConfigError("runtime.json messaging must be an object")
    unknown = sorted(set(value) - set(MESSAGING_KEYS))
    if unknown:
        raise ConfigError(f"runtime.json messaging has an unknown key {unknown[0]!r} (known: {', '.join(MESSAGING_KEYS)})")
    senders = value.get("senders", {})
    if not isinstance(senders, dict):
        raise ConfigError("runtime.json messaging.senders must be an object from a platform to a list of sender ids")
    out_senders = {}
    for platform, ids in senders.items():
        if not isinstance(platform, str) or not PLATFORM_NAME.fullmatch(platform):
            raise ConfigError(f"runtime.json messaging.senders: {platform!r} is not a platform name (lowercase words joined by hyphens)")
        if not isinstance(ids, list) or not all(isinstance(i, str) and i.strip() and not any(c.isspace() for c in i) for i in ids):
            raise ConfigError(f"runtime.json messaging.senders.{platform} must be a list of sender ids, each non-empty text without a space")
        out_senders[platform] = list(dict.fromkeys(ids))
    notices = value.get("notices", "text")
    if notices not in NOTICES:
        raise ConfigError(f"runtime.json messaging.notices must be one of {', '.join(NOTICES)}")
    page_url = value.get("page_url")
    if page_url is not None and (not isinstance(page_url, str) or not re.fullmatch(r"https?://[^\s<>\"']+", page_url)):
        raise ConfigError("runtime.json messaging.page_url must be an http:// or https:// URL, or null")
    return {"senders": out_senders, "notices": notices, "page_url": page_url}


PRICE_MAX_AGE_DEFAULT, PRICE_MAX_AGE_CEILING = 90, 3650


def _default_model(value):
    """The key "default_model", checked: None when absent (auto), else non-empty text (a model id of the gate file, or "auto").
    Whether the gate file lists it is checked where it is used (runtime/ops_models.py): this module reads no gate file."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 200:
        raise ConfigError("runtime.json default_model must be a model id or \"auto\"")
    return value


def _price_max_age(raw: dict) -> int:
    """The key "price_max_age_days": a whole number of days from 1 to 3650; absent means 90."""
    if "price_max_age_days" not in raw:
        return PRICE_MAX_AGE_DEFAULT
    value = raw["price_max_age_days"]
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= PRICE_MAX_AGE_CEILING:
        raise ConfigError(f"runtime.json price_max_age_days must be a whole number of days from 1 to {PRICE_MAX_AGE_CEILING}")
    return value


def price_warnings(cfg: dict) -> list:
    """The warnings a loaded configuration earns about prices: [text]. Today one: model_prices is retired and ignored."""
    if cfg.get("model_prices"):
        return ["runtime.json model_prices is retired and ignored: the one price table is runtime/prices.json of the workbench "
                "(python3 scripts/update_prices.py writes OpenRouter's prices into it); remove the key"]
    return []


PRICE_KINDS = ("input", "output", "cache_read", "cache_write")
PRICE_KEYS = tuple(f"{kind}_usd_per_mtok" for kind in PRICE_KINDS) + ("source", "date")


def _model_prices(value) -> dict:
    """The key "model_prices", checked: {} when absent. An object whose keys are model ids (as the gate file writes
    them, any non-empty text) and whose values are objects with exactly the four prices in dollars per million tokens
    (PRICE_KEYS: each a number of 0 or more, never a boolean) and `source` and `date`, both non-empty text: where the
    person read the price and when. The person types them from the provider's price page; no model id or price is
    written anywhere in the repository, and the file's hash covers them."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("runtime.json model_prices must be an object of model ids")
    out = {}
    for model, entry in value.items():
        if not isinstance(model, str) or not model.strip():
            raise ConfigError("runtime.json model_prices: a model id is non-empty text")
        if not isinstance(entry, dict):
            raise ConfigError(f"runtime.json model_prices.{model} must be an object")
        unknown = sorted(set(entry) - set(PRICE_KEYS))
        if unknown:
            raise ConfigError(f"runtime.json model_prices.{model}: unknown key {unknown[0]} (known: {', '.join(PRICE_KEYS)})")
        missing = [key for key in PRICE_KEYS if key not in entry]
        if missing:
            raise ConfigError(f"runtime.json model_prices.{model}: missing key {missing[0]}")
        checked = {}
        for key in PRICE_KEYS[:4]:
            price = entry[key]
            if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
                raise ConfigError(f"runtime.json model_prices.{model}.{key} must be a number, 0 or more")
            checked[key] = price
        for key in ("source", "date"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise ConfigError(f"runtime.json model_prices.{model}.{key} must be non-empty text")
            checked[key] = entry[key].strip()
        out[model] = checked
    return out


HANDLER_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _handlers(value, agents: dict) -> dict:
    """The key "handlers", checked: {} when absent."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("runtime.json handlers must be an object of handlers")
    out = {}
    for name, entry in value.items():
        if not isinstance(name, str) or not HANDLER_NAME.fullmatch(name):
            raise ConfigError(f"runtime.json handlers: {name!r} is not lowercase words joined by hyphens")
        if not isinstance(entry, dict):
            raise ConfigError(f"runtime.json handlers.{name} must be an object")
        if entry.get("agent") not in agents:
            raise ConfigError(f"runtime.json handlers.{name}.agent must name an agent of area_agents")
        if not isinstance(entry.get("dispatch", False), bool):
            raise ConfigError(f"runtime.json handlers.{name}.dispatch must be true or false")
        out[name] = dict(entry, dispatch=entry.get("dispatch", False))
    return out


CODE_KEYS = ("provider", "repo", "base", "branch_prefix")
CODE_PROVIDERS = ("github",)
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


def _code(value):
    """The key "code", checked; None when absent."""
    if value is None:
        return None
    if not isinstance(value, dict) or sorted(set(value) - set(CODE_KEYS)):
        raise ConfigError(f"runtime.json code must be an object with the keys {', '.join(CODE_KEYS)}")
    if value.get("provider") not in CODE_PROVIDERS:
        raise ConfigError(f"runtime.json code.provider must be one of {', '.join(CODE_PROVIDERS)}")
    if not isinstance(value.get("repo"), str) or not REPO.fullmatch(value["repo"]):
        raise ConfigError("runtime.json code.repo must be <owner>/<name>")
    prefix = value.get("branch_prefix", "wb/")
    for key, branch in (("base", value.get("base")), ("branch_prefix", prefix)):
        if not isinstance(branch, str) or not BRANCH.fullmatch(branch) or ".." in branch or branch.endswith(".lock"):
            raise ConfigError(f"runtime.json code.{key} must be a branch name")
    return {"provider": value["provider"], "repo": value["repo"], "base": value["base"], "branch_prefix": prefix}


def resolver(workbench: str):
    """providers/resolve.py of the workbench checkout, as a module: the one place that resolves a class and calls a
    provider's verb (resolve.call). Raises ConfigError when the checkout has none."""
    path = os.path.join(workbench, "providers", "resolve.py")
    name = "workbench_config_resolve"
    module = sys.modules.get(name)
    if module is None or getattr(module, "__file__", None) != path:
        if not os.path.isfile(path):
            raise ConfigError(f"the workbench {workbench} has no providers/resolve.py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def _implementations(workbench: str, cls: str) -> list:
    """The implementations shipped for a class in the workbench checkout, by its providers/resolve.py."""
    return resolver(workbench).implementations(cls, root=workbench)


BOUNDS_OF = {"task_board": "the task board", "documents": "the documents platform"}


def bounds_problem(cfg: dict, today=None, key: str = "task_board"):
    """Why a write to the platform of the configuration's object `key` (task_board or documents) is not allowed
    now, or None: a provider other than local writes only until the day its expires names, included (UTC)."""
    bounds = cfg[key]
    if bounds.get("provider") == "local":
        return None
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    try:
        expires = datetime.date.fromisoformat(str(bounds.get("expires")))
    except ValueError:
        return f"{key}.expires is not a date"
    if today > expires:
        return (f"the bounds of writing to {BOUNDS_OF[key]} expired on {expires.isoformat()}: change expires in "
                "docs/workbench/runtime.json and accept the new hash")
    return None


def _platform(value, key: str, cls: str, project: str, workbench: str):
    """A task_board or documents object, checked (see the module's text); None when absent."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"runtime.json {key} must be an object")
    shipped = _implementations(workbench, cls)
    provider = value.get("provider")
    if provider not in shipped:
        raise ConfigError(f"runtime.json {key}.provider must be one of {', '.join(shipped) or 'none: no provider is shipped'}")
    if provider == "local":
        folder = value.get("dir")
        if not isinstance(folder, str) or not os.path.isabs(folder):
            raise ConfigError(f"runtime.json {key}.dir must be an absolute path")
        folder = os.path.realpath(folder)
        for inside, what in ((os.path.join(project, "docs"), "the project's docs/ folder"),
                             (workbench, "the workbench checkout")):
            if folder == inside or folder.startswith(inside + os.sep):
                raise ConfigError(f"runtime.json {key}.dir is inside {what}")
    else:
        try:
            datetime.date.fromisoformat(str(value.get("expires")))
        except ValueError:
            raise ConfigError(f"runtime.json {key}.expires must be a date YYYY-MM-DD") from None
        if not isinstance(value.get("expires"), str) or len(value["expires"]) != 10:
            raise ConfigError(f"runtime.json {key}.expires must be a date YYYY-MM-DD")
    return dict(value)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "--project":
        print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
        return 0 if argv in (["--help"], ["-h"]) else 2
    try:
        cfg = load(argv[1])
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    print(json.dumps({key: cfg[key] for key in ("project", "path", "sha256", *REQUIRED)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
