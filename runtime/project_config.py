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

It also reads "outbox" (package EMAIL-SEND; absent: the project sends no e-mail): the account an e-mail leaves from, an object
{"provider": "auto" | "<implementation>", "from": "<address>"}. "provider" is "auto" (the class sender:email resolves as providers/resolve.py
says) or an implementation shipped in providers/mailer/; "from" is one plain address, which is the sender of every e-mail the project sends
and which the provider of this machine must hold the account of (one outbox account per machine). No recipient list is kept here: the person
approves the exact recipients of each e-mail by its hash, and a cap of 20 is code. Like every key, it is changed only in the terminal and
accepted with accept-config; it holds no secret (the password is the secret MAILER_SMTP_PASSWORD).

It also reads "accounts" (package FND; absent: the platform writes to no account of the person's): where the platform may write in the person's own
Google and Microsoft accounts, an object {"google": {...}, "microsoft": {...}} whose entries are each {"address": "<plain address>" (required),
"calendars": {"<name>": "<calendar id>"}, "folders": {"<name>": "<Drive folder id or /path | OneDrive folder id or /path>"}, "mail_folders": {"<name>":
"<label or folder id>"}, "move_removes_inbox": true | false (default true)}, and, beside the two accounts, "default": "google" | "microsoft" (an account the object lists: the
account a line in words goes to when it names no service and both could serve it, package NR-5; `account_default`). A name is lowercase letters, digits and hyphens, at most 32; an id is
checked by a full-match pattern of its provider (a Google id holds no slash; a OneDrive path is `/` and names, no `.` or `..`). A Google folder may also be a path from
My Drive in the same form ("/Documentos", "/Clientes/2026"): accepting the file resolves each one to its folder id through the Drive provider (`resolve-path`, runtime/ops_config.py), the
ids are kept in `google-folders.json` in data_dir, `load` puts them in place of the paths, and `google_folders` of the loaded file lists each path beside its id (None until accepted). The account's token
may reach more than this (the platform's scope set, contracts/secrets.md); what the platform WRITES to is only what is named here, and every
write kind refuses a target that is not (limit L55; `account_target`). Like every key, changed only in the terminal and accepted with
accept-config; it holds no secret.

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

It also reads two optional integers for retention (runtime/upkeep.py): "run_retention_days" (absent means 30; 1 to 3650), the age after
which the folder of a finished run under data_dir is removed; and "source_versions_kept" (absent means 5; 2 to 1000), how many
versions of each source stay in the sources folder, the oldest beyond it removed except one a task that is not finished received.
"sweep_orphan_containers" (absent means true) lets the dispatcher's round remove the eval harness's orphan containers that cannot belong
to a run in progress (runtime/orphans.py); false turns that off. Accepted in the terminal like every key, so it reaches a scheduler's job.

It also reads "default_model" (absent means auto): the model a request or a task is routed to when nothing else chooses
one (not the request, not the task, not the agent's fixed model): a model id of the gate file, or "auto" (the cheapest
reliable pair, runtime/proof.py). When auto finds no pair it can choose, this model runs supervised, if it is an id, else the
first lab model. "price_max_age_days" (absent means 90): a price of runtime/prices.json older than that is shown as stale.

"model_prices" (stage 9; absent means {}) is RETIRED: it is still accepted, checked as before, so that no project breaks, and
it is ignored. The one price table is runtime/prices.json (runtime/prices.py), read by the cost of a run, the `auto`
ranking and the proof page; `price_warnings()` says so, and the doctor of a project (the connections read) shows it.

It also reads "policies" (package POL-2; absent means none), "channels" and "messaging" together, as the channel policy: "policies" maps a profile
name (lowercase words joined by hyphens, at most 32 characters) to a list of groups, or to {"groups": [...], "notices": "all" | "actionable"};
"channels.<channel>" is a list of groups or the name of a profile, the channel's default; "messaging.senders.<platform>" lists plain sender ids
and entries {"id": "<sender id>", "policy": "<profile>"}, and a sender's profile replaces the channel's groups for that sender. Every place a profile
is assigned checks it against the channel (project_config._check_assigned; the refusal names the profile and the channel), and `load` returns the
resolved groups in "channels" (the listed senders that have a profile under operations.SENDERS_KEY), the profiles in "policies" and the names in
"channel_profiles" and "messaging.sender_profiles". The sender ids stay a list of ids for every reader of the bridge. A change is a widening, asked
once by the hash of its list, when a place has a group the accepted file did not effectively give it (runtime/policy_widening.py).

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
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autonomy  # noqa: E402  (the same folder: the check of the key "area_agents")
import deps  # noqa: E402  (the same folder: the recipes and the check of the key "dependencies")
import language  # noqa: E402  (the same folder: the rule of the key "language")
import lease  # noqa: E402  (the same folder: a database or a lock is refused in a synced folder)
import mail_address  # noqa: E402  (the same folder: the form of the outbox's sender)
import operations  # noqa: E402  (the same folder: the groups and the ceilings the key "channels" is checked against)
import phrases  # noqa: E402  (the same folder: the sentence of an account that is not set up)
import sources  # noqa: E402  (the same folder: the paths rules of the key "sources_dir")

REL = "docs/workbench/runtime.json"
REQUIRED = ("workbench", "data_dir", "store_db", "sources_dir")
# The top-level keys of the task runtime: the three required ones and every key this module checks or passes on.
TASK_RUNTIME_KEYS = ("workbench", "data_dir", "store_db", "sources_dir", "area_agents", "handlers", "task_board", "documents",
                     "protected_paths", "code", "dependencies", "max_cost_usd_per_run", "model_prices", "messaging", "channels",
                     "max_running", "default_model", "price_max_age_days", "run_retention_days", "source_versions_kept",
                     "sweep_orphan_containers", "language", "outbox", "policies", "accounts", "research")
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
        if key == "sources_dir" and os.path.islink(os.path.normpath(value)):   # "link/" and "link/." are not links to islink, but they are
            raise ConfigError("runtime.json sources_dir is a symbolic link: name the folder itself (the runtime never follows a "
                              "link out of the sources folder)")
        out[key] = os.path.realpath(value)
    for key in ("data_dir", "store_db"):
        for inside, what in ((project, "the project"), (out["workbench"], "the workbench checkout")):
            if out[key] == inside or out[key].startswith(inside + os.sep):
                raise ConfigError(f"runtime.json {key} is inside {what}: work data lives outside every repository")
    for key, where in (("data_dir", out["data_dir"]), ("store_db", os.path.dirname(out["store_db"]))):
        synced = lease.synced_reason(where)
        if synced:   # decision D30: nothing but the sources folder may live where a sync client merges files (limit L28)
            raise ConfigError(f"runtime.json {key} is in a synced folder ({synced}): a database or a lock file does not survive a sync "
                              "client; use a local folder, and keep only sources_dir in the synced drive")
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
    out["policies"] = _policies(raw.get("policies"))
    out["messaging"] = _messaging(raw.get("messaging"), out["policies"])
    out["channels"] = _channels(raw.get("channels"), out["policies"])
    out["channel_profiles"] = channel_profiles(raw.get("channels"))
    senders = sender_policy(out["messaging"], out["policies"])
    if senders:
        out["channels"][operations.SENDERS_KEY] = senders   # the groups of each listed sender whose entry names a profile (operations.effective_groups)
    out["max_running"] = _max_running(raw)
    out["research"] = _research(raw.get("research"))
    out["run_retention_days"] = _bounded(raw, "run_retention_days", RUN_RETENTION_DEFAULT, 1, RUN_RETENTION_MAX)
    out["source_versions_kept"] = _bounded(raw, "source_versions_kept", SOURCE_VERSIONS_DEFAULT, SOURCE_VERSIONS_MIN, SOURCE_VERSIONS_MAX)
    sweep = raw.get("sweep_orphan_containers", True)
    if not isinstance(sweep, bool):
        raise ConfigError("runtime.json sweep_orphan_containers must be true or false")
    out["sweep_orphan_containers"] = sweep
    out["language"] = _language(raw.get("language"))
    out["outbox"] = _outbox(raw.get("outbox"), out["workbench"])
    out["accounts"], out["google_folders"] = with_google_ids(_accounts(raw.get("accounts")), resolved_google_paths(out["data_dir"]))
    return out


# Retention (package P-OPS, runtime/upkeep.py): both keys optional, accepted in the terminal like every key of the file.
RUN_RETENTION_DEFAULT, RUN_RETENTION_MAX = 30, 3650   # days a run folder is kept; a longer wish is 3650 (ten years)
SOURCE_VERSIONS_DEFAULT, SOURCE_VERSIONS_MIN, SOURCE_VERSIONS_MAX = 5, 2, 1000   # versions of a source kept; 2 is the least, see upkeep.py


def _bounded(raw: dict, key: str, default: int, low: int, high: int) -> int:
    """An optional integer key of runtime.json from low to high; absent means the default."""
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigError(f"runtime.json {key} must be an integer from {low} to {high}")
    return value


MAX_RUNNING_DEFAULT, MAX_RUNNING_CEILING = 3, 14  # the ceiling is the lab's total_jobs, the machine-wide limit of model calls


def _max_running(raw: dict) -> int:
    """The key "max_running": the most task runs of the project at one time, an integer from 1 to 14; absent means 3."""
    if "max_running" not in raw:
        return MAX_RUNNING_DEFAULT
    value = raw["max_running"]
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RUNNING_CEILING:
        raise ConfigError(f"runtime.json max_running must be an integer from 1 to {MAX_RUNNING_CEILING}")
    return value


# The key "research" (slice R2-F1, runtime/ops_research.py): the bounds of each web research run, all optional. An object with any of three keys; absent keys take the default; the default cost cap is 0.60 USD (the maintainer, 2026-10-24: one weather lookup on the reference model reached 0.25).
RESEARCH_DEFAULTS = {"max_cost_usd": 0.6, "timeout_seconds": 300, "max_per_day": 10}
RESEARCH_BOUNDS = {"max_cost_usd": (0.01, 5.0), "timeout_seconds": (30, 900), "max_per_day": (1, 100)}   # the dollars one run may spend, the seconds one run may last, the runs in a local day


def _research(value) -> dict:
    """The key "research": {"max_cost_usd", "timeout_seconds", "max_per_day"}, each from its bounds; absent or `{}` gives the defaults. A key it does not know is refused."""
    if value is None:
        return dict(RESEARCH_DEFAULTS)
    if not isinstance(value, dict):
        raise ConfigError("runtime.json research must be an object")
    unknown = sorted(set(value) - set(RESEARCH_DEFAULTS))
    if unknown:
        raise ConfigError(f"runtime.json research has an unknown key {unknown[0]!r}; the keys are {', '.join(RESEARCH_DEFAULTS)}")
    out = dict(RESEARCH_DEFAULTS)
    for key, (low, high) in RESEARCH_BOUNDS.items():
        if key not in value:
            continue
        given = value[key]
        number = isinstance(given, (int, float)) and not isinstance(given, bool) and math.isfinite(given)
        whole = key != "max_cost_usd"
        if not number or (whole and not isinstance(given, int)) or not low <= given <= high:
            raise ConfigError(f"runtime.json research.{key} must be {'an integer' if whole else 'a number'} from {low} to {high}")
        out[key] = given
    return out


POLICY_CHANNELS = operations.POLICY_CHANNELS  # the channels a policy narrows: page, mcp and messaging (chat and the terminal never)


def _refused_group(channel: str, group: str, groups: list) -> str | None:
    """The sentence that refuses one group for one channel, or None when the channel takes it (operations.group_refusal: the rule lives with the
    table, so that a channel's entry and a profile assigned to it are checked by one function)."""
    return operations.group_refusal(channel, group)


PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")   # a profile's name: lowercase words joined by hyphens, at most 32 characters
PROFILE_KEYS = ("groups", "notices")
PROFILE_NOTICES = ("all", "actionable")
DEFAULT_PROFILE = "default"                            # the label of a sender who has no profile (the channel's own groups); not a name a project may use
SENDER_ID_MAX = 254                                    # an e-mail address fits (the longest a mailbox name and a domain make)
PLATFORM_MAX = 32                                      # the actor label the store keeps ("messaging:<platform>:<profile>:<id>") must fit its bound
SENDERS_MAX = 100                                      # senders listed in all (policy_widening keeps a record of them in a cursor of 4 KiB)


def _groups_of(where: str, groups) -> list:
    """A list of group names, each one of operations.GROUPS; `where` names the place in the sentence."""
    if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        raise ConfigError(f"runtime.json {where} must be a list of group names")
    for group in groups:
        if group not in operations.GROUPS:
            raise ConfigError(f"runtime.json {where}: {group!r} is not a group (known: {', '.join(operations.GROUPS)})")
    return list(dict.fromkeys(groups))


def _policies(value) -> dict:
    """The key "policies" (POL-2; absent means {}): {"<profile>": ["<group>", ...]} or {"<profile>": {"groups": [...], "notices": "all" or
    "actionable"}}. A profile is a named set of groups; by itself it says nothing of a channel and is checked at each place it is assigned
    (`channels.<channel>` names it as the channel's default, a sender's entry in `messaging.senders` names it for that sender). A name is lowercase words
    joined by hyphens, at most 32 characters, and not `default`. A profile that lists unknown groups, or both `read` and `read-limited`, is refused.
    Returns {"<profile>": {"groups": [...], "notices": "all" | "actionable"}}; `notices` (default all) says whether a sender gets a card for every
    decision (all) or only for one their profile can act on or answer (actionable)."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("runtime.json policies must be an object from a profile name to a list of groups")
    out = {}
    for name, body in value.items():
        if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
            raise ConfigError(f"runtime.json policies: {name!r} is not a profile name (lowercase words joined by hyphens, at most 32 characters)")
        if name == DEFAULT_PROFILE:
            raise ConfigError(f"runtime.json policies: {DEFAULT_PROFILE!r} is the label of a sender with no profile; choose another name")
        notices = "all"
        if isinstance(body, dict):
            unknown = sorted(set(body) - set(PROFILE_KEYS))
            if unknown or "groups" not in body:
                raise ConfigError(f"runtime.json policies.{name}: an object profile has the keys {', '.join(PROFILE_KEYS)} (groups required)"
                                  + (f"; {unknown[0]!r} is not one" if unknown else ""))
            notices = body.get("notices", "all")
            if notices not in PROFILE_NOTICES:
                raise ConfigError(f"runtime.json policies.{name}.notices must be one of {', '.join(PROFILE_NOTICES)}")
            groups = _groups_of(f"policies.{name}.groups", body["groups"])
        else:
            groups = _groups_of(f"policies.{name}", body)
        if "read" in groups and "read-limited" in groups:
            raise ConfigError(f"runtime.json policies.{name}: lists both 'read' and 'read-limited'; choose one (read-limited is read without the spend)")
        out[name] = {"groups": groups, "notices": notices}
    return out


def _check_assigned(where: str, channel: str, groups: list, profile: str | None, own: bool = False) -> None:
    """The groups of a channel's entry, or of a profile at the place it is assigned, against the channel: every group is one the channel takes, the
    networked plans need the plans, and the page and the MCP mode list `read`. The sentence names the profile (when there is one) and the channel. `own` is a
    sender's own profile (messaging.senders.<platform>[].policy): the group `ask-mail` is given there and nowhere else, never to a whole channel, because the text of a
    mailbox or a calendar is read for one person, not for every sender the channel lists."""
    label = f"profile {profile!r}: " if profile else ""
    if "ask-mail" in groups and not own:
        raise ConfigError(f"runtime.json {where}: {label}the group 'ask-mail' is given in the profile of one listed sender (messaging.senders.<platform> with a policy), "
                          "never to a whole channel: the text of a mailbox or a calendar is read for the person it belongs to")
    for group in groups:
        why = _refused_group(channel, group, groups)
        if why:
            raise ConfigError(f"runtime.json {where}: {label}{why}")
    if "approve-networked-plans" in groups and "approve-plans" not in groups:
        raise ConfigError(f"runtime.json {where}: {label}'approve-networked-plans' needs 'approve-plans' beside it "
                          "(it adds networked plans to the plans the channel approves)")
    if "send-files" in groups and "read-files" not in groups:
        raise ConfigError(f"runtime.json {where}: {label}'send-files' needs 'read-files' beside it "
                          "(it sends the file that reading files finds, so a policy that only sends is refused)")
    if "files-trash" in groups and "read-files" not in groups:
        raise ConfigError(f"runtime.json {where}: {label}'files-trash' needs 'read-files' beside it "
                          "(it finds the file by its name and lists names, as reading files does, so a policy that only trashes is refused)")
    if channel in operations.MUST_READ and "read" not in groups:
        raise ConfigError(f"runtime.json {where}: {label}must list the group 'read' (the {channel} reads what it shows)")


def channel_profiles(value) -> dict:
    """{channel: profile name} for the channels of `channels` whose entry is a profile name (the raw value, already checked by _channels)."""
    return {c: v for c, v in (value or {}).items() if isinstance(v, str)}


def _channels(value, policies=None) -> dict:
    """The key "channels" (the channel policy, decisions M-8, M-13, POL-1 and POL-2; absent means {}), checked: {"page": ["<group>", ...],
    "mcp": [...], "messaging": [...]}, or a channel's value a profile name of the key "policies" (then the profile's groups). Each group is one of
    operations.GROUPS and is valid on a channel when at least one
    operation it covers is listed by the channel's row in the table (the ceiling): a policy narrows what the table allows,
    and widens it only by a grant of that channel (operations.GRANTS: the effect words and the networked plans on messaging;
    plans, acceptances, reject-cancel and retry on the MCP mode), which the group then covers. `approve-effects` is valid on the
    page only; `approve-networked-plans` needs `approve-plans`; `read-limited` is a messaging app's. A policy for the page or the MCP mode lists `read`.
    `chat` and `terminal` are errors: the conversation's input is local access, equal to the terminal, and neither is narrowed. A channel
    that has no entry keeps its ceiling, except messaging, which keeps operations.DEFAULT_POLICY (read, talk, answer, the routine
    brakes) and never a grant. Like every key of the file, a change takes effect after accept-config in the terminal, and one that
    adds a group beyond what the accepted file effectively had only with the hash of the widening list. Returns {channel: [groups]}; the
    profile names are read by channel_profiles."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("runtime.json channels must be an object from a channel to a list of groups or a profile name")
    policies = policies or {}
    out = {}
    for channel, groups in value.items():
        if channel in ("chat", "terminal"):
            raise ConfigError(f"runtime.json channels.{channel}: the {channel} is never narrowed (its input is local access); "
                              f"the channels with a policy are {', '.join(POLICY_CHANNELS)}")
        if channel not in POLICY_CHANNELS:
            raise ConfigError(f"runtime.json channels: {channel!r} has no policy; the channels with one are {', '.join(POLICY_CHANNELS)} "
                              "(the terminal and the conversation are never narrowed)")
        profile = None
        if isinstance(groups, str):
            if groups not in policies:
                raise ConfigError(f"runtime.json channels.{channel}: {groups!r} is not a profile of policies "
                                  f"(known: {', '.join(policies) or 'none'}); a channel takes a list of groups or the name of a profile")
            profile, groups = groups, list(policies[groups]["groups"])
        elif not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise ConfigError(f"runtime.json channels.{channel} must be a list of group names or the name of a profile")
        else:
            for group in groups:
                if group not in operations.GROUPS:
                    raise ConfigError(f"runtime.json channels.{channel}: {group!r} is not a group (known: {', '.join(operations.GROUPS)})")
        _check_assigned(f"channels.{channel}", channel, groups, profile)
        out[channel] = list(dict.fromkeys(groups))
    return out


def sender_policy(messaging: dict, policies: dict) -> dict:
    """{"<platform>:<sender id>": [groups]} of the senders whose entry names a profile (from `_messaging`'s "sender_profiles"): what
    operations.effective_groups reads for that sender. A sender with a plain entry is not here: it gets the channel's groups."""
    out = {}
    for platform, named in (messaging.get("sender_profiles") or {}).items():
        for sender, profile in named.items():
            out[operations.sender_key(platform, sender)] = list(policies[profile]["groups"])
    return out


MESSAGING_KEYS = ("senders", "notices", "page_url")
NOTICES = ("text", "count")
PLATFORM_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _sender_entry(platform: str, entry, policies: dict) -> tuple:
    """(sender id, profile name or None) of one entry of `messaging.senders.<platform>`: a plain id (the sender gets the channel's groups), or
    {"id": "<sender id>", "policy": "<profile>"} (the sender gets the profile's groups instead). The id is non-empty text without a space,
    at most SENDER_ID_MAX characters."""
    where = f"messaging.senders.{platform}"
    profile = None
    if isinstance(entry, dict):
        if sorted(entry) != ["id", "policy"]:
            raise ConfigError(f"runtime.json {where}: an entry object has the keys id and policy, and no other")
        entry, profile = entry["id"], entry["policy"]
        if not isinstance(profile, str) or profile not in policies:
            raise ConfigError(f"runtime.json {where}: {profile!r} is not a profile of policies (known: {', '.join(policies) or 'none'})")
    if not isinstance(entry, str) or not entry.strip() or any(c.isspace() or not c.isprintable() for c in entry) or len(entry) > SENDER_ID_MAX:
        raise ConfigError(f"runtime.json {where} must list sender ids, each non-empty text without a space of at most {SENDER_ID_MAX} characters")
    return entry, profile


def _messaging(value, policies=None) -> dict:
    """The key "messaging" (the messaging bridge, runtime/messaging.py; absent means no sender and the defaults), checked:
    {"senders": {"<platform>": ["<sender id>" or {"id": "<sender id>", "policy": "<profile>"}, ...]}, "notices": "text" or "count"
    (default "text"), "page_url": an http:// or https:// URL, or null}. A platform is lowercase words joined by hyphens, a sender id is non-empty
    text without a space; an id is listed once on a platform (the same entry twice is one). A sender's profile (POL-2) replaces the channel's groups for that sender, and is checked
    against the messaging channel here: a profile that lists a group the channel does not take is refused with the profile's name. Returns
    "senders" {platform: [ids]} (the ids alone, as every reader of the bridge expects) and "sender_profiles" {platform: {id: profile}}, the
    entries that name one. Nothing in it is a secret (the bot's token is read from the secret store), and, as every key of
    the file, a change takes effect only after the person runs accept-config in the terminal."""
    if value is None:
        return {"senders": {}, "sender_profiles": {}, "notices": "text", "page_url": None}
    if not isinstance(value, dict):
        raise ConfigError("runtime.json messaging must be an object")
    unknown = sorted(set(value) - set(MESSAGING_KEYS))
    if unknown:
        raise ConfigError(f"runtime.json messaging has an unknown key {unknown[0]!r} (known: {', '.join(MESSAGING_KEYS)})")
    senders = value.get("senders", {})
    if not isinstance(senders, dict):
        raise ConfigError("runtime.json messaging.senders must be an object from a platform to a list of sender ids")
    policies = policies or {}
    out_senders, out_profiles, checked, holders = {}, {}, set(), {}
    for platform, entries in senders.items():
        if not isinstance(platform, str) or not PLATFORM_NAME.fullmatch(platform) or len(platform) > PLATFORM_MAX:
            raise ConfigError(f"runtime.json messaging.senders: {platform!r} is not a platform name (lowercase words joined by hyphens, at most {PLATFORM_MAX} characters)")
        if not isinstance(entries, list):
            raise ConfigError(f"runtime.json messaging.senders.{platform} must be a list of sender ids, each non-empty text without a space")
        ids, named = [], {}
        for entry in entries:
            sender, profile = _sender_entry(platform, entry, policies)
            if sender in ids:
                if named.get(sender) != profile:     # the same entry twice was always dropped silently; two different entries for one id are a refusal
                    raise ConfigError(f"runtime.json messaging.senders.{platform}: a sender is listed once on a platform, and one has two different entries "
                                      "(a sender's profile is the one entry's)")
                continue
            ids.append(sender)
            if profile:
                named[sender] = profile
                if "ask-mail" in policies[profile]["groups"]:
                    holders.setdefault(profile, set()).add((platform, sender))
                if profile not in checked:
                    checked.add(profile)
                    _check_assigned(f"messaging.senders.{platform}", "messaging", policies[profile]["groups"], profile, own=True)
        out_senders[platform] = ids
        if named:
            out_profiles[platform] = named
    for profile, who in sorted(holders.items()):
        if len(who) > 1:      # the text of a mailbox or a calendar is read for the person it belongs to: a profile that lists ask-mail is one person's
            raise ConfigError(f"runtime.json messaging.senders: the profile {profile!r} lists the group 'ask-mail' and is named by {len(who)} senders; "
                              "a profile with 'ask-mail' belongs to one sender, so give each sender who reads their own mail and calendar a profile of their own")
    if sum(len(ids) for ids in out_senders.values()) > SENDERS_MAX:
        raise ConfigError(f"runtime.json messaging.senders lists more than {SENDERS_MAX} senders in all: the record of what the file gives them "
                          "is kept in the store (a cursor of 4 KiB) and is bounded")
    notices = value.get("notices", "text")
    if notices not in NOTICES:
        raise ConfigError(f"runtime.json messaging.notices must be one of {', '.join(NOTICES)}")
    page_url = value.get("page_url")
    if page_url is not None and (not isinstance(page_url, str) or not re.fullmatch(r"https?://[^\s<>\"']+", page_url)):
        raise ConfigError("runtime.json messaging.page_url must be an http:// or https:// URL, or null")
    return {"senders": out_senders, "sender_profiles": out_profiles, "notices": notices, "page_url": page_url}


PRICE_MAX_AGE_DEFAULT, PRICE_MAX_AGE_CEILING = 90, 3650


def _default_model(value):
    """The key "default_model", checked: None when absent (auto), else non-empty text (a model id of the gate file, or "auto").
    Whether the gate file lists it is checked where it is used (runtime/ops_models.py): this module reads no gate file."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 200:
        raise ConfigError("runtime.json default_model must be a model id or \"auto\"")
    return value


LANGUAGE_RE = language.RULE        # one rule, kept in runtime/language.py (the line of a run, the request option and the router's line read it too)


def _language(value):
    """The key "language": the language artifacts are written in, a tag of two lower-case letters and, optionally, a hyphen and
    two upper-case letters (pt-BR, en, en-US). None when absent (English). A tag in the wrong case, or with an underscore, is
    refused with the right form, never rewritten. Runtime/language.py reads the value (the line of a run, the plan card)."""
    if value is None:
        return None
    if isinstance(value, str) and LANGUAGE_RE.fullmatch(value):
        return value
    raise ConfigError(f"runtime.json language must be {language.SHAPE}{language.hint(value)}")


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


OUTBOX_KEYS = ("provider", "from")
OUTBOX_CLASS = "sender:email"
OWN_ACCOUNT_MAILERS = ("gmail", "outlook")      # the implementations of sender:email that send from the person's own account token (package W2): never the project's outbox


def _outbox(value, workbench: str):
    """The key "outbox", checked; None when absent."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - set(OUTBOX_KEYS) or "from" not in value:
        raise ConfigError(f"runtime.json outbox must be an object with the keys {', '.join(OUTBOX_KEYS)} (from is required)")
    provider = value.get("provider", "auto")
    shipped = [name for name in _implementations(workbench, OUTBOX_CLASS) if name not in OWN_ACCOUNT_MAILERS]
    if provider != "auto" and provider not in shipped:
        raise ConfigError(f"runtime.json outbox.provider must be auto or one of {', '.join(shipped) or 'none: no provider is shipped'}")
    try:
        sender = mail_address.normalize_address(value["from"])
    except mail_address.AddressError as e:
        raise ConfigError(f"runtime.json outbox.from: {e.reason}") from None
    return {"provider": provider, "from": sender}


ACCOUNT_PROVIDERS = ("google", "microsoft")
ACCOUNT_DEFAULT = "default"          # NR-5 (Q2): the key of `accounts` that names which account a line in words goes to when it names none and both could serve
ACCOUNT_EFFECT_WORDS = ("calendar", "mailbox", "files")           # the effect words that arrived with the account writes, not with a skill (contracts/environment.md)
ACCOUNT_KEYS = ("address", "calendars", "folders", "mail_folders", "move_removes_inbox")
ACCOUNT_SECTIONS = ("calendars", "folders", "mail_folders")      # the three maps of names to ids: the targets the platform may write to
ACCOUNT_NAME = re.compile(r"[a-z0-9-]{1,32}")
ACCOUNT_SECTION_MAX = 50                                         # names in one map
ACCOUNT_DEFAULT_FOLDER = "default"                               # the name of the folder a file goes to when the person names none
ACCOUNT_PATH_BAD = re.compile(r'[\\/:*?"<>|#%\x00-\x1f\x7f]')      # a character a OneDrive name cannot hold, a control character, and `#` and `%` (a fragment, a percent-encoded form)
ACCOUNT_HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")           # control, format (a right-to-left override, a zero-width character), separators: never in an id or a path
ACCOUNT_ID = {       # (provider, section) -> the full-match pattern of an id; none holds a slash (a OneDrive folder may also be a path: _account_path)
    ("google", "calendars"): re.compile(r"(?!\.{1,2}$)[A-Za-z0-9._@+-]{1,254}"),
    ("google", "folders"): re.compile(r"[A-Za-z0-9_-]{1,128}"),
    ("google", "mail_folders"): re.compile(r"[A-Za-z0-9_-]{1,64}"),
    ("microsoft", "calendars"): re.compile(r"[A-Za-z0-9_=-]{1,300}"),
    ("microsoft", "folders"): re.compile(r"[A-Za-z0-9_=!-]{1,200}"),
    ("microsoft", "mail_folders"): re.compile(r"[A-Za-z0-9_=-]{1,300}"),
}


def _account_path(value: str) -> bool:
    """Whether a text is a OneDrive folder path: `/`, then names joined by `/`, each 1 to 100 characters that hold no character OneDrive refuses, are
    not `.` or `..`, neither start nor end with a space and do not end with a dot; at most 400 characters in all."""
    if not value.startswith("/") or len(value) > 400 or value == "/":
        return False
    parts = value[1:].split("/")
    return all(0 < len(p) <= 100 and p not in (".", "..") and not ACCOUNT_PATH_BAD.search(p) and p == p.strip(" ") and not p.endswith(".")
               and not any(unicodedata.category(c) in ACCOUNT_HIDDEN for c in p) for p in parts)


def _account_id(provider: str, section: str, value) -> bool:
    if not isinstance(value, str):
        return False
    if provider in ACCOUNT_PROVIDERS and section == "folders" and value.startswith("/"):      # a OneDrive folder is an id or a path; a Google folder too (S11): resolved to its id when the file is accepted
        return _account_path(value)
    return ACCOUNT_ID[(provider, section)].fullmatch(value) is not None


GOOGLE_PATHS_FILE = "google-folders.json"      # in data_dir: {"v": 1, "folders": {"<path>": "<id>"}}, written when the person accepts the file (runtime/ops_config.py)


def google_paths(accounts) -> dict:
    """{folder name: path} of the Google folders the file gives as a path from My Drive (S11), the ones accepting the file resolves to an id."""
    folders = (((accounts or {}).get("google") or {}).get("folders")) or {}
    return {name: value for name, value in folders.items() if isinstance(value, str) and value.startswith("/")}


def resolved_google_paths(data_dir) -> dict:
    """{path: id} of the file the last acceptance wrote in `data_dir`; {} when there is none or it is not one this module wrote (every id is checked again as a Google folder id)."""
    try:
        with open(os.path.join(data_dir, GOOGLE_PATHS_FILE), encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return {}
    folders = found.get("folders") if isinstance(found, dict) and found.get("v") == 1 else None
    if not isinstance(folders, dict):
        return {}
    return {p: i for p, i in folders.items() if isinstance(p, str) and _account_path(p) and isinstance(i, str) and ACCOUNT_ID[("google", "folders")].fullmatch(i)}


def write_google_paths(data_dir, resolved: dict) -> None:
    """Write {path: id} as the file of the last acceptance (mode 0600, replaced whole); with none to keep, the file is removed. Raises OSError."""
    target = os.path.join(data_dir, GOOGLE_PATHS_FILE)
    if not resolved:
        try:
            os.remove(target)
        except FileNotFoundError:
            pass
        return
    os.makedirs(data_dir, exist_ok=True)
    temp = f"{target}.{os.getpid()}.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "folders": dict(sorted(resolved.items()))}, f)
    os.replace(temp, target)


def with_google_ids(accounts, known: dict) -> tuple:
    """(accounts, shown): the accounts with every Google folder given as a path replaced by the id in `known` ({path: id}; a path with none stays a path, which
    `account_target` refuses), and `shown`, {name: {"path", "id" (None when not resolved)}}, what `config` prints beside each path. A copy: `accounts` is not changed."""
    paths = google_paths(accounts)
    if not paths:
        return accounts, {}
    google = dict(accounts["google"])
    google["folders"] = {name: known.get(value, value) for name, value in google["folders"].items()}
    return dict(accounts, google=google), {name: {"path": value, "id": known.get(value)} for name, value in paths.items()}


def _accounts(value):
    """The key "accounts", checked and completed (every section present, `move_removes_inbox` true when absent); None when absent."""
    if value is None:
        return None
    where = "runtime.json accounts"
    if not isinstance(value, dict) or set(value) - set(ACCOUNT_PROVIDERS) - {ACCOUNT_DEFAULT}:
        raise ConfigError(f"{where} must be an object with the keys {', '.join(ACCOUNT_PROVIDERS)} (each optional) and default")
    out = {}
    for provider, entry in value.items():
        if provider == ACCOUNT_DEFAULT:
            if value[ACCOUNT_DEFAULT] not in ACCOUNT_PROVIDERS or value[ACCOUNT_DEFAULT] not in value:
                raise ConfigError(f"{where}.default must be google or microsoft, an account this file lists")
            continue
        here = f"{where}.{provider}"
        if not isinstance(entry, dict) or set(entry) - set(ACCOUNT_KEYS) or "address" not in entry:
            raise ConfigError(f"{here} must be an object with the keys {', '.join(ACCOUNT_KEYS)} (address is required)")
        try:
            address = mail_address.normalize_address(entry["address"])
        except mail_address.AddressError as e:
            raise ConfigError(f"{here}.address: {e.reason}") from None
        item = {"address": address}
        for section in ACCOUNT_SECTIONS:
            named = entry.get(section, {})
            if not isinstance(named, dict) or len(named) > ACCOUNT_SECTION_MAX:
                raise ConfigError(f"{here}.{section} must be an object of at most {ACCOUNT_SECTION_MAX} names, each with the id of its target")
            for name, ident in named.items():
                if not isinstance(name, str) or not ACCOUNT_NAME.fullmatch(name):
                    raise ConfigError(f"{here}.{section}: a name is lowercase letters, digits and hyphens, at most 32 characters")
                if not _account_id(provider, section, ident):
                    raise ConfigError(f"{here}.{section}.{name} is not the id of a {provider} {section[:-1].replace('_', ' ')}"
                                      + (" (a Google id holds no slash; a Google folder may also be a path from My Drive, such as /Clientes/2026)" if provider == "google" else ""))
            item[section] = dict(named)
        inbox = entry.get("move_removes_inbox", True)
        if not isinstance(inbox, bool):
            raise ConfigError(f"{here}.move_removes_inbox must be true or false")
        item["move_removes_inbox"] = inbox
        out[provider] = item
    if ACCOUNT_DEFAULT in value:
        out[ACCOUNT_DEFAULT] = value[ACCOUNT_DEFAULT]
    return out


def file_accounts(cfg: dict):
    """The key "accounts" as the file gives it, checked again, with a Google folder path still a path (`cfg["accounts"]` has the ids the last acceptance resolved in their place)."""
    return _accounts(((cfg or {}).get("raw") or {}).get("accounts"))


def account_default(cfg: dict):
    """The account a line in words goes to when it names no service and both could serve it (`accounts.default`, package NR-5), or None."""
    default = ((cfg or {}).get("accounts") or {}).get(ACCOUNT_DEFAULT)
    return default if default in ACCOUNT_PROVIDERS and default in ((cfg or {}).get("accounts") or {}) else None


def account_entry(cfg: dict, account):
    """The checked entry of `google` or `microsoft` in the configuration's accounts, or None when the project lists none."""
    return ((cfg or {}).get("accounts") or {}).get(account) if account in ACCOUNT_PROVIDERS else None


def clean_name(value, width: int = 40) -> str:
    """A name a caller gave, as a sentence may echo it: at most `width` characters, and only letters, digits, hyphens, underscores and dots (anything else is `?`)."""
    return re.sub(r"[^A-Za-z0-9_.-]", "?", str(value)[:width])


def account_target(cfg: dict, account, section: str, name=None) -> tuple:
    """(id, None) of a target the project lists for an account, or (None, the sentence that refuses it): the one place the write kinds ask whether the
    platform may write somewhere (limit L55). `section` is calendars, folders or mail_folders. Without a name, calendars means the first one listed and
    folders the one named `default`; a mail folder is always named. Whatever the token could reach, only what is listed is a target."""
    entry = account_entry(cfg, account)
    if entry is None:
        return None, phrases.en("ACCT_NOT_CONFIGURED").format(account=clean_name(account, 20))
    if not isinstance(section, str) or section not in ACCOUNT_SECTIONS:
        return None, f"there is no kind of target {clean_name(section)!r}"
    if name is not None and not isinstance(name, str):
        return None, f"a name is a text: {clean_name(name)!r} is not one of the {section.replace('_', ' ')} the project lists for the account {account}"
    listed, what = entry[section], section.replace("_", " ")
    if name is None:
        name = next(iter(listed), None) if section == "calendars" else ACCOUNT_DEFAULT_FOLDER if section == "folders" else None
        if name is None:
            return None, f"name one of the {what} the project lists for the account {account}: {', '.join(listed) or 'none are listed'}"
    if name not in listed:
        return None, (f"{clean_name(name)!r} is not one of the {what} the project lists for the account {account} (accounts.{account}.{section} in "
                      f"runtime.json): {', '.join(listed) or 'none are listed'}")
    found = listed[name]
    if account == "google" and section == "folders" and found.startswith("/"):      # a path nobody resolved: a write never goes to a folder the person has not seen as an id
        return None, f"the Google folder {found} has not been resolved to its id: accept the configuration again, which resolves it through your Google account"
    return found, None


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


def _sources_only(workbench: str, cls: str, name: str) -> bool:
    """Whether the shipped implementation declares `SOURCES_ONLY = True` at the top of its file (it serves the files a person picked as
    sources and writes nothing: providers/documents/gdrive.py), read as text."""
    path = os.path.join(workbench, "providers", resolver(workbench).folder(cls), f"{name}.py")
    try:
        with open(path, encoding="utf-8") as f:
            return re.search(r"^SOURCES_ONLY\s*=\s*True\b", f.read(), re.M) is not None
    except OSError:
        return False


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
    if _sources_only(workbench, cls, provider):
        raise ConfigError(f"runtime.json {key}.provider {provider!r} serves sources only and writes nothing: choose another provider "
                          f"({', '.join(n for n in shipped if not _sources_only(workbench, cls, n))})")
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
