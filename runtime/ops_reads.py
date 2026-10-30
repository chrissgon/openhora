#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The reads of the local interface and the signals of the local service: the change signal of the store (`version`),
the stop of the runs a process started, the conversation's commands as rows (`commands`), the agents with their day, the conversation's messages, the skills with their
proof, the costs, the connections, the service's start check and the project's artifacts.

A sibling of runtime/ops.py, which exposes each of them under its name; no shell imports this file. The names every
module of the layer shares are read as `core.<name>` (runtime/ops_core.py); the helpers these reads need live in the siblings that
own their jobs (the day's caps and the held record in runtime/ops_runs.py), and no helper of runtime/ops.py is reached from here (44-C2). The
conversation's name comes from runtime/ops_say.py, which imports nothing of this file. `SERVICE`, the service's facts, lives here and
runtime/ops.py re-exports it.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import json
import os
import platform as platform_module
import re
import stat as stat_module
import sys
import xml.parsers.expat

import ops_core as core
import ops_models
import ops_say
import autonomy
import costs as costs_calc  # the operation `costs` would hide the module
import dispatcher
import drop
import lab
import manifest
import operations
import path_rule
import phrases
import plan
import prices as price_table
import project_config
import proof as proof_rules  # the operation `proof` would hide the module
import router
import secret_state
import skill_meta
import ops_ask
import ops_natural
import ops_runs
import ops_steps

SERVICE_TEXT = 300  # characters of one verdict of service_check: an exception's text is bounded
SERVICE = {}                   # the local service's facts, by project folder: set by service_check in the service's process only


def with_routing(ctx: dict, requests: list) -> list:
    """The requests of `status` each with `routing`: {"run_id", "skill", "started_at"} while a run of the router holds the request, else
    None. A router run is a row of task_runs whose task is the request (route_run_start); the request keeps its state and has no task, so
    the row is the one record that says a run is in progress. One query for the live run (store.task_runs_running), whatever the number of
    requests; a cancelled request never has one. A task's run names a task, never a request, so it matches none."""
    live = {r["task_id"]: {"run_id": r["id"], "skill": r["skill"], "started_at": r["started_at"]}
            for r in core._stored(ctx, ctx["store"].task_runs_running)}
    return [{**r, "routing": None if r["state"] == "cancelled" else live.get(r["id"])} for r in requests]


# --- stage 9: the local service --------------------------------------------------------------------------------------


def version(project: str) -> dict:
    """The change signal of a project's store: {"version", "changed_at"}. "version" is a whole number that grows on every
    write transaction that changed a row (providers/store/sqlite.py, `change_counter`: the database file's header),
    whoever wrote it: this process, a loop's thread, the terminal. A page asks it every second and reads everything
    again when it moved. It is the cheapest read there is: the configuration file and its hash, then on the store four
    statements (two pragmas of the connection, one plain SELECT of the cursor that holds the accepted configuration's hash,
    the header) with no transaction and so no write lock; no migration is run (every other operation runs one at its
    start), and a configuration nobody accepted, or one that names another checkout, is refused as every operation refuses it. "changed_at" is the time the store's file
    was last written (UTC, as the store writes times). A project whose store does not exist yet gets it made, as every
    other operation does."""
    cfg = core._config_of(project)
    store = core.store_module()
    db = cfg["store_db"]
    if not os.path.isfile(db):
        core.context(project, check_config=False)
    conn = store.connect(db)
    try:
        accepted = store.cursor_peek(conn, project_config.ACCEPTED)      # a plain read: no write lock, no queue behind a writer
        number = store.change_counter(conn)
    except store.StoreError as e:
        raise core.OpsError(f"the store at {db}: {e}", e.code) from None
    except Exception as e:  # sqlite3.Error: the file is not a database, or is locked past the timeout
        raise core.OpsError(f"the store at {db}: {e}", 1) from None
    finally:
        conn.close()
    core._accepted(cfg, accepted)
    stamps = [os.stat(path).st_mtime for path in (db, db + "-wal") if os.path.exists(path)]
    changed = datetime.datetime.fromtimestamp(max(stamps), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return {"version": number, "changed_at": changed}


def commands(project: str) -> dict:
    """The commands of the conversation as rows: {"commands": [{"command", "arguments", "help"}]}, the lines `/help` prints
    in the order it prints them (operations.chat_command_rows, built from the table `/help` is built from). The page lists
    them when the person types `/`. The project is only the configuration check every operation makes."""
    core.context(project)
    return {"commands": operations.chat_command_rows()}


def stop_runs(project: str | None = None, every: bool = False) -> dict:
    """End the runs this process started: no child starts any more, the children (task runs, each a process of its own) this
    process started are ended by their process groups, and the lab's own stop (lab.stop_runs) ends the containers and the
    process group of each run the process holds, the folders of a run in progress going back to its run folder. The local
    service calls it before it exits. Process-wide: the project is read for nothing. With `every` and a project (the
    terminal's `stop-runs --project <dir> --all`), also every task run of the project that a live process holds, whoever
    started it, by the group its task lock names; a lock nobody holds is never signalled. Stopping an agent's mode
    (`set-mode ... stopped`) is how to keep the dispatcher from starting more, and `set-mode --agent runtime --mode stopped` how to keep
    it from starting step tasks. Returns what lab.stop_runs returns, with
    "tasks" (the ids of the task runs signalled) when `every` is given."""
    return ops_runs.stop(project, every)


# --- stage 9: the reads of the local interface ---------------------------------------------------------------------


COST_DAYS = 30           # costs: the default window, in days
MESSAGES_PAGE = 500      # conversation: the most messages one call returns (the store's own maximum)
ARTIFACT_LIMIT = 2000    # artifacts: the most files one call lists
ARTIFACT_MAX_BYTES = 1024 * 1024  # artifact: the largest file whose text is returned
IMAGE_MAX_BYTES = 25 * 1024 * 1024  # artifact-raw: the largest image returned (the size the file drop takes)
HEAD_BYTES = 8192        # artifacts: the bytes of a file read to tell its kind
KINDS = ("text", "markdown", "image", "other")
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
OTHER_TYPES = ((b"%PDF-", "a PDF document"), (b"PK\x03\x04", "a zip archive"), (b"wOF2", "a woff2 font"),
               (b"wOFF", "a woff font"), (b"GIF8", "a GIF image"), (b"\x00\x01\x00\x00", "a font"))
SECRET_RESOLVER = ("providers", "secrets", "resolver.py")
CONFIGURED_PROVIDER = {"integration:vcs": "code", "integration:issue-tracker": "task_board", "integration:documents": "documents"}


def _held_listed(ctx: dict, rows: list) -> list:
    """The held tasks `status` and `agents` show: [{"task_id", "agent", "reason", "at", "next", "commands"}] for the ready tasks
    among rows (the store's tasks). While the local service dispatches nothing, every ready task is held with `dispatch
    off`; otherwise the last round's record, kept only for tasks still ready. `next` is the sentence that gets past the
    reason, or None; `commands` is the same as fields, [{"name", "command"}], for the two reasons a command gets past
    (ops_reads.held_commands), else []."""
    ready = [t for t in rows if t["state"] == "ready" and t["parent_id"] is not None]
    if not ready:
        return []
    project = ctx["cfg"]["project"]
    service = SERVICE.get(os.path.realpath(project))
    if service is not None and service["dispatch"] == "off":
        return [{"task_id": t["id"], "agent": t.get("agent"), "reason": dispatcher.DISPATCH_OFF, "at": service["at"],
                 "next": core._command("run-next", project, uv=True), "commands": []} for t in ready]
    try:
        record = json.loads(core._stored(ctx, ctx["store"].cursor_get, ops_runs.HELD_CURSOR) or "null")
    except ValueError:
        record = None
    if not isinstance(record, dict):
        return []
    ids = {t["id"] for t in ready}
    out = []
    for h in record.get("held") or []:
        if h.get("task_id") in ids:
            out.append({**h, "at": record.get("at"), "next": held_next(project, h["reason"], record.get("missing")),
                        "commands": held_commands(project, h["reason"], record.get("missing"))})
    return out


def agents(project: str) -> dict:
    """The area agents of the configuration with their use of today: {"agents": [{"name", "pack", "enabled", "mode",
    "acting_mode", "max_runs_per_day", "max_usd_per_day", "runs_today", "usd_today", "runs_without_cost", "usd_recorded", "usd_reserved",
    "runs_total_today", "billing", "caps_in_use", "max_parallel", "max_parallel_ceiling", "slots_held", "holders", "queued",
    "held", "wider", "model", "consent", "config_sha256", "consent_in_force", "consent_needed", "consent_warning", "model_commands",
    "recommended_model"}], "consent_warning",
    "default_model", "models", "config_sha256" (the hash of the configuration this read saw: the page sends it back with the consent)}
    in the order of the configuration. model is the model the agent is fixed to (a model id, "auto", or None when it has none);
    consent is the person's consent stored with it ({"model", "mode"} or None) and consent_in_force whether it names the
    agent's model and mode now; consent_needed whether the settings need one (a model id fixed, an autonomous mode);
    recommended_model is the cheapest model reliable for every skill of the agent's pack (else for the most), or None;
    model_commands lists, for every model of the gate file and for auto and default, the absolute `set-model` command that
    fixes it (with --consent and --accept when the agent's mode needs the consent: the page shows it with the warning and
    builds none, and gives the consent itself with give-consent);
    consent_warning is the text the person reads before consenting (autonomy.CONSENT_WARNING); default_model the project's
    (None means auto); models the ids of the gate file's models. mode is the configured one; acting_mode the one the agent acts in now
    (autonomy.mode_of: an agent set to autonomous-with-policy whose approval expired acts as autonomous). The day is
    counted as the caps count it (_agents_of_the_day), by the billing each run recorded: runs_today is the runs on a
    subscription or free credential (what max_runs_per_day compares), usd_today the dollars of the runs on a metered
    credential (a run of unknown cost counts at max_cost_usd_per_run, and runs_without_cost says how many), whatever the
    model; a run older than the billing column counts by the rule of its model (a run on a model whose credential is billed by use is metered). A router run counts for the planning agent.
    max_parallel is the agent's slots (autonomy.MAX_PARALLEL_CEILING, "max_parallel_ceiling", is the most a configuration
    may give); holders are the ids of the tasks that hold one now (running, waiting for the person, or ready after the
    person answered) and slots_held their number. queued is the number of ready tasks of the agent;
    held how many of them the last round held (status lists them with their reasons). usd_today is split into
    usd_recorded (the recorded costs of today's metered runs) and usd_reserved (max_cost_usd_per_run, else
    PER_RUN_USD, for each such run with no cost yet: what the cap counts); runs_total_today is every run of the agent
    today, whatever its billing. billing is {"runs": [the billing words counted in runs_today], "spend": [the words
    counted in usd_today]} and caps_in_use {"runs": bool, "spend": bool}: whether the project's credentials, or a run
    of today, have that billing, so that a page draws a meter only for a cap in use. wider lists, for every mode above
    the agent's own, the absolute `set-mode ... --accept` command (the page offers it with Copy and builds none).
    "steps": {"agent": "runtime", "mode": "autonomous" or "stopped"}: the brake of the step tasks (ops_steps.steps_mode; `set-mode --agent
    runtime`), beside the agents, whether or not the project has any. A project without area_agents: {"agents": [], "steps"}."""
    ctx = core.context(project)
    day = ops_runs._agents_of_the_day(ctx)
    brake = {"agent": "runtime", "mode": ops_steps.steps_mode(ctx)}
    if not day:
        return {"agents": [], "steps": brake}
    try:
        listed = lab.models()
    except lab.LabError:  # a gate file the facade refuses: the agents are still listed, without model commands
        listed = []
    rows = core._stored(ctx, ctx["store"].tasks_list)
    ready = [t for t in rows if t["state"] == "ready" and t["parent_id"] is not None]
    held = _held_listed(ctx, rows)
    holders = core._stored(ctx, ctx["store"].task_slot_holders)
    out = []
    for name, found in day.items():
        entry, spent = found["entry"], found["spent"]
        out.append({"name": name, "pack": entry["pack"], "enabled": entry["enabled"], "mode": entry["mode"],
                    "acting_mode": autonomy.mode_of(found["facts"]), "max_runs_per_day": entry["max_runs_per_day"],
                    "max_usd_per_day": entry["max_usd_per_day"], "runs_today": spent["runs_counted"],
                    "usd_today": spent["usd_metered"], "runs_without_cost": spent["runs_without_cost"],
                    **_spend_words(found["split"]), "billing": {"runs": list(autonomy.RUNS_BILLINGS),
                                                                "spend": list(autonomy.SPEND_BILLINGS)},
                    "caps_in_use": found["in_use"],
                    "max_parallel": entry["max_parallel"], "max_parallel_ceiling": autonomy.MAX_PARALLEL_CEILING,
                    "holders": [h["id"] for h in holders if h["agent"] == name],
                    "slots_held": sum(1 for h in holders if h["agent"] == name),
                    "queued": sum(1 for t in ready if t.get("agent") == name),
                    "held": sum(1 for h in held if h["agent"] == name),
                    "wider": _wider(ctx["cfg"]["project"], name, entry),
                    "model": entry.get("model"), "consent": entry.get("consent"), "config_sha256": ctx["cfg"]["sha256"],
                    "consent_in_force": autonomy.consent_valid(entry, entry.get("model")),
                    "consent_needed": autonomy.consent_needed(entry), "consent_warning": autonomy.CONSENT_WARNING,
                    "model_commands": _model_commands(ctx["cfg"]["project"], name, entry, listed, _pack_summary(ctx, entry)),
                    "recommended_model": None})
    for row in out:  # the recommendation of the agent's picker: the cheapest model reliable for every skill of its pack
        row["recommended_model"] = ops_models.recommend(
            [dict(c, model=c["model"]) for c in row["model_commands"] if c.get("skills") is not None])
    return {"agents": out, "steps": brake, "consent_warning": autonomy.CONSENT_WARNING, "default_model": ctx["cfg"].get("default_model"),
            "models": listed, "config_sha256": ctx["cfg"]["sha256"]}


def _pack_summary(ctx: dict, entry: dict) -> dict:
    """{model id: scope_summary line} over the skills of the agent's pack; {} when the pack cannot be read."""
    try:
        names = plan.resolve_pack(entry["pack"], core.ROOT)
        return ops_models.scope_summary(ctx, names)
    except (plan.PlanError, lab.LabError, OSError, KeyError):
        return {}


def _model_commands(project: str, agent: str, entry: dict, listed, summary: dict | None = None) -> list:
    """[{"model", "consent", "command", ...}] for every model of the gate file, "auto" and "default": the absolute `set-model`
    command that fixes it on the agent, with --consent and --accept when the agent's settings would then need the person's
    consent (an autonomous mode and a model id; "consent" says so); the page shows it with Copy and builds none. A model of
    the gate file also carries, over the skills of the agent's pack (ops_models.scope_summary), "skills", "reliable",
    "community_only", "expected_cost", "band" and "price", what the agent's picker shows beside the model."""
    out = []
    summary = summary or {}
    for model in [*listed, autonomy.AUTO_MODEL, "default"]:
        after = {**entry, "model": model}
        if model == "default":
            after.pop("model")
        needs = autonomy.consent_needed(after)
        line = {"model": model, "consent": needs,
                "command": core._command("set-model", project, agent=agent, model=model, accept=needs, consent=needs)}
        if model in summary:
            line.update({k: summary[model].get(k) for k in ("skills", "reliable", "community_only", "expected_cost", "band", "price")})
        out.append(line)
    return out


def _spend_words(split: dict) -> dict:
    """The day's spend in the words a meter shows, the same in `agents` and in the caps of `costs`: usd_recorded,
    usd_reserved (their sum is usd_today) and runs_total_today."""
    return {"usd_recorded": split["usd_recorded"], "usd_reserved": split["usd_reserved"],
            "runs_total_today": split["runs_total"]}


def _caps_use(used, name: str) -> dict:
    """The day's use of one agent in the words of `agents`, for the caps of `costs`; {} when the day could not be
    computed (the gate file is broken): costs then show the caps alone."""
    if not used or name not in used:
        return {}
    found = used[name]
    return {"runs_today": found["spent"]["runs_counted"], "usd_today": found["spent"]["usd_metered"],
            "runs_without_cost": found["spent"]["runs_without_cost"], **_spend_words(found["split"])}


def _wider(project: str, agent: str, entry: dict) -> list:
    """[{"mode", "command"}] for every mode above the agent's own in the order of autonomy.MODES, each the absolute `set-mode`
    command with `--accept` (a wider mode is set and accepted by the person in the terminal, in one step) and, when the agent
    is fixed to a model and the mode releases reviews without the person, `--consent` (the consent, a flag of its own): the
    page shows it, it builds none."""
    above = autonomy.MODES[autonomy.MODES.index(entry["mode"]) + 1:]
    out = []
    for m in above:
        needs = autonomy.consent_needed({**entry, "mode": m})
        out.append({"mode": m, "command": core._command("set-mode", project, agent=agent, mode=m, accept=True, consent=needs)})
    return out


def held_commands(project: str, reason: str, missing=None) -> list:
    """[{"name", "command"}] the person types to get past a held reason, for the two reasons a command gets past: `secret
    store` (one entry, the service started with the secret store's library) and `credential` (one entry for each
    variable the round found missing, else those of the default model's credential; `command` is the line that
    stores it under the username the adapters' manifests register, the username shell-quoted, and None when none is
    registered); [] for any other reason. Built by operations.service_line and operations.keyring_line, the one place
    that spells each: the page draws them and builds none. Names only, never a value."""
    if reason == "secret store":
        return [{"name": "service", "command": operations.service_line(core.ROOT, [project], uv=True)}]
    if reason != "credential":
        return []
    names = list(missing or [])
    if not names:
        try:
            names = list(lab.reference()["pass_env"])
        except lab.LabError:
            names = []
    users = lab.credential_usernames(names) if names else {}
    return [{"name": n, "command": operations.keyring_line(users[n]) if n in users else None} for n in names]


def held_next(project: str, reason: str, missing=None):
    """What gets past a reason, as the sentence the terminal reads, or None when nothing a command or a sentence can say
    does (a cap, an agent that is stopped: edits of the configuration). `secret store`: the command that starts the
    service with the secret store's library. `credential` (the store is readable, the key is not in it): the first
    sentence says where the credential is not; the command that stores each variable is a field of `held_commands`
    that a page draws, so it is not written here a second time (A-34). What a field cannot say stays in the sentence:
    for a variable with no registered username (`command` None) the second sentence (store it once, or export it) and a
    line that points to the table of contracts/secrets.md, and, when the round named no variable and the reference
    model's credential cannot be read, that pointer alone. It gives no value and invents none."""
    if reason == "secret store":
        return operations.service_line(core.ROOT, [project], uv=True)
    if reason != "credential":
        return None
    locked = secret_state.unreadable_sentence(core.ROOT, names=missing or [c["name"] for c in held_commands(project, reason, missing)])   # a locked store or an unsafe credentials directory is not a key that is not stored (I3)
    if locked:
        return (f"{locked[0].upper()}{locked[1:]}. Clear that first: the key may be stored and unreadable, or it may be missing, and the "
                "connections read says which once the secrets can be read.")
    first = "The credential is in neither the environment nor the secret store."
    commands = held_commands(project, reason, missing)
    if commands and all(c["command"] for c in commands):
        return first
    steps = "; ".join(f"{c['name']}: {operations.keyring_line('<username>')} (the username is in the table of contracts/secrets.md)"
                      for c in commands if not c["command"]) or "the default model's credential: see the table of contracts/secrets.md"
    return (f"{first} Store it once, the value typed at a hidden prompt, or export it in the shell that starts the service. "
            f"{steps}.")


def drop_note(task: dict):
    """What the page needs to know before it sends a file to a task: {"web": whether the task's skill uses the web,
    "takes": whether a file can be handed over (drop.WEB_TASK_TAKES_DROP, true for a task that does not use the web),
    "line": drop.WEB_LINE when the task uses the web and takes the file, else None}; None for a request, which takes
    no file."""
    if task.get("parent_id") is None or not task.get("skill"):
        return None
    try:
        web = bool(skill_meta.declared(os.path.join(core.ROOT, "skills", task["skill"]))["web"]) and not task.get("web_off")
    except skill_meta.SkillError:
        return None
    takes = drop.WEB_TASK_TAKES_DROP or not web
    return {"web": web, "takes": takes, "line": drop.WEB_LINE if web and takes else None}


def conversation(project: str, conversation: str | None = ops_say.CONVERSATION, after: int | None = 0, channel: str | None = None,
                 sender: str | None = None) -> dict:
    """The messages of a conversation whose id is above `after`, oldest first, at most MESSAGES_PAGE (the newest of
    them when more are waiting): {"conversation", "messages": [{"id", "role", "text", "task_id", "run_id",
    "created_at", "queued"}]}. There is one conversation per project and its name is CONVERSATION (an argument left out
    is the default). For an assistant message task_id is the request the turn made or answered. "queued" is true on
    a line of the person that was stored while a run was in progress and has no reply yet (runtime/ops_say.py, the
    queue). The answer to a `/ask` is in the conversation, stored with the id of its answer run, and is shown only to the channel that asked
    (`channel`: the terminal, the page; on a messaging app only to the sender, `sender`): every other reader, the MCP mode always, and a call
    that names no channel, gets "(answered from the sources: request <n>)" in its place (limit L50). Reads nothing else."""
    ctx = core.context(project)
    conversation, after = ops_say.CONVERSATION if conversation is None else conversation, 0 if after is None else after
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        raise core.OpsError("after is a message id: a whole number, 0 or more", 2)
    if not isinstance(conversation, str) or not conversation.strip():
        raise core.OpsError("the conversation's name is empty", 2)
    rows = core._stored(ctx, ctx["store"].messages_list, conversation, limit=MESSAGES_PAGE, after_id=after)
    keys = ("id", "role", "text", "task_id", "run_id", "created_at")
    queued = ops_say.queued_ids(ctx) if conversation == ops_say.CONVERSATION else set()
    asker = ops_ask.asked_by
    private = ops_natural.private_ids(rows) if channel not in ("terminal", "page", "chat") else {}      # the person's own shells see their line; no other reader sees a reminder's words (limit L51)
    return {"conversation": conversation,
            "messages": [{**{key: row[key] for key in keys}, "text": phrases.text(private[row["id"]], ctx["cfg"]) if row["id"] in private else _shown_text(ctx, row, asker, channel, sender),
                          "queued": row["id"] in queued}
                         for row in rows]}


def _shown_text(ctx: dict, row: dict, asked_by, channel, sender) -> str:
    """The text of a message for a reader: the message's own, except the reply to a `/ask` (an assistant message with the id of a run that is
    not the router's), which is the person's document text and goes only to the channel that asked."""
    if row["role"] != "assistant" or row["run_id"] is None:
        return row["text"]
    store, conn = ctx["store"], ctx["conn"]
    try:
        run = store.task_run_get(conn, row["run_id"])
    except store.StoreError:
        return row["text"]
    if run["skill"] == router.ROUTER_SKILL:
        return row["text"]
    if asked_by(store.cursor_peek(conn, store.ASK_ACTOR_CURSOR.format(run=run["id"])), channel, sender):
        return row["text"]
    return phrases.text("ANSWERED_AS", ctx["cfg"], request=run["task_id"])


def _scope(ctx: dict) -> list:
    """The skills in scope of the project: the packs of its enabled agents, or the default pack without area_agents."""
    try:
        return plan.pack_skills(ctx["cfg"], core.ROOT)
    except plan.PlanError as e:
        raise core.OpsError(f"the skills in scope cannot be listed: {e}", 1) from None


def skills(project: str) -> dict:
    """The skills in scope of the project (_scope) with what is known of each, and the two checks of the proof:
    {"skills": [{"name", "version", "area", "manifest": true or false, "proof": [{"model", "adapter", "provider", "band",
    "cause", "score", "mean", "runs", "web_measured", "usage_mean", "source", "price": {the four prices per million tokens,
    "source", "accessed", "age_days", "stale"} or None, "expected_cost" (dollars for one run, or None)}], "recommended":
    the model `auto` would choose or None, "runs_here": <runs of it in this project's store>}], "checks":
    {"measurement": "ok" or why, "image": "ok" or why}, "models": [{"model", "adapter", "provider", "skills", "reliable",
    "community_only", "expected_cost", "band", "price"}] (one line for each model, for a picker), "default_model",
    "recommended_model" (the cheapest model reliable for every skill in scope, else for the most; None when none), "language" (the
    project's `language` setting, None when not set: the request form's first language option)}. The proof is the entry runtime/proof.py keeps
    (proof.row), one pair for every model of the gate file, with the price of the one price table (runtime/prices.json)
    and its expected cost read now; never recomputed here. The measurement check is the
    status script's; the image check is made once for the machine: "ok" when the eval image is on it and is the image
    the evidence of every skill that has evidence was measured in, else the reason (a skill with no evidence has
    nothing to compare and is `needs a test` anyway). Calls no model and no provider, and starts no network call."""
    ctx = core.context(project)
    cfg = ctx["cfg"]
    out, evidence = [], {}
    for name in _scope(ctx):
        try:
            meta = skill_meta.declared(os.path.join(core.ROOT, "skills", name))
            entry = proof_rules.row(cfg, name)
        except (skill_meta.SkillError, lab.LabError, OSError, KeyError) as e:
            raise core.OpsError(f"the proof of {name} cannot be read: {e}", 1) from None
        evidence[name] = entry.get("evidence_images") or []
        read = ops_models.models_read(ctx, name)
        out.append({"name": name, "version": meta["version"], "area": meta["area"],
                    "manifest": os.path.isfile(manifest.path(core.ROOT, name)),
                    "proof": read["pairs"], "recommended": read["recommended"],
                    "runs_here": len(core._stored(ctx, ctx["store"].task_runs_of_skill, name))})
    try:
        problem, digest = lab.measurement_problem(), lab.image()["digest"]
    except lab.LabError as e:
        raise core.OpsError(f"the proof's checks cannot be made: {e}", 1) from None
    others = sorted(name for name, images in evidence.items() if images and digest not in images)
    if digest is None:
        image = "the eval image is not on this machine"
    elif others:
        image = f"the image on this machine is not the one the evidence of {len(others)} skill(s) was measured in"
    else:
        image = None
    summaries = _model_summaries(out)
    return {"skills": out, "checks": {"measurement": problem or "ok", "image": image or "ok"},
            "models": summaries, "default_model": ctx["cfg"].get("default_model"), "recommended_model": ops_models.recommend(summaries),
            "language": ctx["cfg"].get("language")}


def _model_summaries(rows: list) -> list:
    """One line for each model of the pairs the skills in scope carry, in the order the first skill lists them: {"model",
    "adapter", "provider", "skills" (how many skills of the scope have a pair for it), "reliable" (how many of those are
    `reliable` on it), "community_only" (how many of those rest on community evidence alone: their output is reviewed),
    "expected_cost" (the mean expected cost per run of the pairs that have one, or None), "band" (`reliable` for every
    skill, `partial`, `needs a test`), "price" (its entry of the price table with source, date, age and stale, or None)}.
    What a picker shows beside a model before any skill is chosen; the per-skill figures stay in each skill's `proof`."""
    out, costs = {}, {}
    for row in rows:
        for pair in row["proof"]:
            found = out.setdefault(pair["model"], {"model": pair["model"], "adapter": pair.get("adapter"), "provider": pair.get("provider"),
                                                   "skills": 0, "reliable": 0, "community_only": 0, "expected_cost": None,
                                                   "price": pair.get("price")})
            found["skills"] += 1
            if pair.get("band") == "reliable":
                found["reliable"] += 1
                found["community_only"] += 0 if pair.get("source") in ("lab", "local") else 1
            if pair.get("expected_cost") is not None:
                costs.setdefault(pair["model"], []).append(pair["expected_cost"])
    for model, found in out.items():
        found["expected_cost"] = sum(costs[model]) / len(costs[model]) if costs.get(model) else None
        found["band"] = ops_models.band_word(found)
    return list(out.values())


def costs(project: str, since: str | None = None) -> dict:
    """The runs of the project from the day `since` (YYYY-MM-DD; default the last COST_DAYS days) by day, agent, model
    and adapter: {"since", "rows": [{"day", "agent", "model", "adapter", "runs", "tokens", "recorded_usd",
    "recomputed_usd", "unknown_runs", "lower_bound_runs", "price"}], "caps": [{"agent", "max_runs_per_day", "max_usd_per_day", "runs_today", "usd_today", "runs_without_cost", "usd_recorded",
    "usd_reserved", "runs_total_today"}]} (the caps carry the day's use in the words of `agents`). The runs
    are read task by task (the store's runs_since has no token count and no run folder) and the token counts of a
    run from its own folder (runtime/costs.py, usage_of): a folder outside <data_dir>/task-runs/ is not read, and the
    run is unknown. recomputed_usd is computed from the prices of the one price table (runtime/prices.json; price says their
    source, the day they were read, their age and whether they are stale) and is None, never a guess, for a model with no price or a group with a run of unknown usage
    (unknown_runs counts them). A run whose key proxy could not count every answer is counted from what it did count, a
    lower bound, and lower_bound_runs counts such runs; the run's own report is never read in place of the proxy's count
    (runtime/costs.py, metered_usage). A router run counts for the planning agent, an answer run (ask) for the owner of the answer skill. The day is the local day."""
    ctx = core.context(project)
    cfg, store = ctx["cfg"], ctx["store"]
    if since is None:
        day = (datetime.date.today() - datetime.timedelta(days=COST_DAYS)).isoformat()
    else:
        try:
            day = datetime.date.fromisoformat(str(since)).isoformat()
        except ValueError:
            raise core.OpsError("since is a day: YYYY-MM-DD", 2) from None
    try:
        used = ops_runs._agents_of_the_day(ctx)
    except (lab.LabError, core.OpsError, KeyError, ValueError, OSError):  # a broken gate file leaves the day's use out; costs read the store
        used = None
    folder = os.path.realpath(os.path.join(cfg["data_dir"], core.RUNS_DIR)) + os.sep
    runs = []
    owners = ops_ask.run_owners(ctx)    # the agent a run whose task is a request counts against
    for task in core._stored(ctx, store.tasks_list):
        for run in core._stored(ctx, store.task_runs_list, task["id"]):
            agent = task.get("agent")
            if agent is None and task["parent_id"] is None:
                agent = owners.get(run.get("skill"))
            where = run.get("run_dir")
            inside = isinstance(where, str) and os.path.realpath(where).startswith(folder)
            runs.append(dict(run, agent=agent, run_dir=where if inside else None))
    table, max_days = ops_models.price_table(ctx)
    return {"since": day, "rows": costs_calc.summary(runs, table, since=day, today=datetime.date.today(), max_days=max_days,
                                                     names_of=lab.names_of),
            "caps": [{"agent": name, "max_runs_per_day": entry["max_runs_per_day"],
                      "max_usd_per_day": entry["max_usd_per_day"], **_caps_use(used, name)}
                     for name, entry in cfg["area_agents"].items()]}


def _secret_rows() -> tuple:
    """([{"name", "found", "where"}], note): the secrets the core and the runtime register, found or not and where
    (resolver.report(): the environment or the secret store), then the variables the lab names for the models'
    keys (lab.credential_missing). Never a value: the resolver's report holds none, and only its name, found and
    source are taken. note is None, or why a part could not be read."""
    notes, rows = [], []
    try:
        resolver = core._load("workbench_secret_resolver_runtime", os.path.join(core.ROOT, *SECRET_RESOLVER))
        resolver.register_file(os.path.join(core.ROOT, "runtime", "secrets.json"))
        report = resolver.report()
        rows = [{"name": r["name"], "found": bool(r["found"]), "where": r["source"] if r["found"] else None} for r in report]
        if any(r.get("state") == "locked" for r in report):
            notes.append(secret_state.LOCKED_NOTE)
        notes.extend(sorted({f"the credentials directory is unsafe: {r['detail']}" for r in report if r.get("state") == "unsafe"}))
    except Exception as e:  # an interpreter the resolver does not run on, a bad registry
        sys.modules.pop("workbench_secret_resolver_runtime", None)
        notes.append(f"the secret resolver could not be used: {type(e).__name__}")
    have = {row["name"] for row in rows}
    try:
        for model in lab.models():
            names, missing = lab.reference(model)["pass_env"], lab.credential_missing(model)
            for name in names:
                if name not in have:
                    have.add(name)
                    rows.append({"name": name, "found": name not in missing,
                                 "where": None if name in missing else "environment or secret store"})
    except Exception as e:  # a gate file the facade refuses
        notes.append(f"the models' keys could not be looked up: {type(e).__name__}")
    return sorted(rows, key=lambda row: row["name"]), "; ".join(notes) or None


ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}


def _image_platform_here(machine: str, system: str) -> str | None:
    """The platform the eval image runs as on a machine without emulation, in the os/arch form of the evidence
    (executor.IMAGE_PLATFORM, such as linux/arm64): the image is a Linux image, so the os is linux on a Linux host and
    on a host that runs containers in a Linux virtual machine of its own architecture (macOS, Windows); the arch is the
    machine's, normalised (x86_64 and amd64 are amd64, arm64 and aarch64 are arm64). None when the arch is not one of
    those or the system is not linux, darwin or win32: nothing is guessed."""
    arch = ARCHITECTURES.get((machine or "").strip().lower())
    if arch is None or not (system or "").startswith(("linux", "darwin", "win32")):
        return None
    return "linux/" + arch


def _platform_row(machine: str, system: str, evidence: str | None) -> dict:
    """The "platform" row of connections: see its docstring. same never compares an unknown value."""
    here = _image_platform_here(machine, system)
    return {"machine": machine or None, "evidence": evidence, "here": here,
            "same": (here == evidence) if here and evidence else None}


def connections(project: str) -> dict:
    """What the project's skills need from the machine and whether it is there, with no provider started and no
    network call: {"classes": [{"class", "provider", "found", "note", "skills"}], "secrets": [{"name", "found",
    "where"}], "secrets_note", "image": {"name", "present", "evidence": true, false or None}, "platform": {"machine",
    "evidence", "here", "same"}, "service": {"secret_store", "credential", "docker", "image", "dispatch", "problems",
    "start", "at"} or None}. classes: each requirement class the skills in scope declare, resolved by providers/resolve.py as the
    runtime resolves it (the implementation the configuration names for the code provider, the task board and the
    documents; else the environment, the platform default or the only implementation): provider is the
    implementation or None, found whether its file exists, note how it was chosen or why it was not. secrets: see
    _secret_rows; the names are the registry's, never a value. image: whether the eval image is on this machine and
    whether its digest is the one the evidence of the skills in scope was measured in (None when it is not
    present). platform: machine is the architecture of this machine as the system names it; evidence is the platform
    the lab evidence was made on; here is the platform the eval image runs as on this machine without emulation, in
    the evidence's os/arch form (see _image_platform_here); same is true when here equals evidence, false when both
    are known and differ, None when either is unknown. service: what the local service found at its start
    (service_check), null in any other process. warnings: [text], the configuration's and the price table's (a retired
    `model_prices` key that is ignored, naming runtime/prices.json; the price of a model of the gate file older than the
    project's price_max_age_days)."""
    ctx = core.context(project)
    cfg = ctx["cfg"]
    needs, evidence = {}, set()
    for name in _scope(ctx):
        try:
            for cls in skill_meta.declared(os.path.join(core.ROOT, "skills", name))["requires"]:
                needs.setdefault(cls, []).append(name)
            evidence.update(proof_rules.row(cfg, name).get("evidence_images") or [])
        except (skill_meta.SkillError, lab.LabError, OSError, KeyError) as e:
            raise core.OpsError(f"the needs of {name} cannot be read: {e}", 1) from None
    resolve = core._load("workbench_provider_resolve", os.path.join(core.ROOT, "providers", "resolve.py"))
    classes = []
    for cls in sorted(needs):
        key = CONFIGURED_PROVIDER.get(cls)
        implementation = (cfg.get(key) or {}).get("provider") if key else None
        row = {"class": cls, "provider": None, "found": False, "note": None, "skills": sorted(needs[cls])}
        try:
            got = resolve.resolve(cls, root=core.ROOT, implementation=implementation)
        except (resolve.UnknownClass, resolve.Unresolved) as e:
            row["note"] = str(e)
        else:
            row.update(provider=got["implementation"], found=os.path.isfile(got["path"]),
                       note=f"chosen by {got['source']}" + (f" ({got['variable']})" if got.get("variable") else ""))
            if not row["found"]:
                row["note"] = "the provider's file is missing: " + row["note"]
        classes.append(row)
    secrets, note = _secret_rows()
    try:
        seen = lab.image()
    except lab.LabError as e:
        raise core.OpsError(f"the eval image cannot be looked up: {e}", 1) from None
    present = seen["digest"] is not None
    return {"classes": classes, "secrets": secrets, "secrets_note": note, "warnings": _price_warnings(ctx),
            "image": {"name": seen.get("name"), "present": present,
                      "evidence": (seen["digest"] in evidence) if present else None},
            "platform": _platform_row(platform_module.machine(), sys.platform, seen.get("evidence_platform")),
            "service": dict(SERVICE[os.path.realpath(cfg["project"])]) if os.path.realpath(cfg["project"]) in SERVICE else None}


def _price_warnings(ctx: dict) -> list:
    """The warnings about prices a project's connections show: the retired model_prices key (project_config.price_warnings), and
    each model of the gate file whose price in runtime/prices.json is older than the project's price_max_age_days."""
    out = project_config.price_warnings(ctx["cfg"])
    table, max_days = ops_models.price_table(ctx)
    today = datetime.date.today()
    try:
        names = [(model, lab.names_of(model)) for model in lab.models()]
    except lab.LabError:
        return out
    for model, aliases in names:
        found = price_table.price_of(table, aliases)
        if found is not None and price_table.is_stale(found, today, max_days):
            out.append(f"the price of {model} in runtime/prices.json was read on {found.get('accessed')}, more than {max_days} days "
                       "ago: it is shown as stale (python3 scripts/update_prices.py reads OpenRouter's prices again)")
    return out


def service_check(project: str, dispatch_every=None) -> dict:
    """What the local service checks for one project at its start, and remembers (SERVICE) for `connections`, `status`
    and `agents` while the process lives: {"secret_store", "credential", "docker", "image", "dispatch", "problems",
    "start", "at"}. Each verdict is "ok" or one sentence saying what is missing. secret_store and credential are the
    scheduler entry's check (dispatcher.inspect: can this interpreter read the secret store, is the default model's
    credential set or in it), docker whether it is on PATH and its daemon is running (the daemon is read from the image lookup, no second docker call), image whether the eval image is on this machine,
    dispatch "every <n> s" or "off" (dispatch_every in seconds; 0 is off; None says the process is no service), problems
    the modules or the lab that did not load, start the command that starts the service with the secret store's
    library (uv run --with keyring==..., operations.service_line). It starts nothing and makes no network call."""
    ctx = core.context(project, check_config=False)
    found = dispatcher.inspect(core)
    seen = lab.image()
    if seen.get("problem"):
        image = f"the eval image cannot be looked up: {seen['problem']}"
    elif not seen.get("name"):
        image = "not looked at: the lab does not run in a container, or docker cannot be reached"
    elif not seen.get("digest"):
        image = f"the eval image {seen['name']} is not on this machine"
    else:
        image = "ok"
    bounded = lambda text: core.CONTROL.sub(" ", str(text))[:SERVICE_TEXT]  # noqa: E731  (an exception's text, bounded)
    if not found["tools"].get("docker"):
        docker = "docker is not on the PATH of this process"
    elif seen.get("setup") == lab.DAEMON_DOWN:      # the image lookup above already asked the daemon: no new docker call
        docker = "docker is on the PATH but its daemon is not running: web research and contained runs cannot start until Docker is started"
    else:
        docker = "ok"
    problems = [bounded(f"{name}: {why}") for name, why in sorted(found["modules"].items()) if why != "ok"]
    if found["lab"] != "ok":
        problems.append(bounded(f"lab: {found['lab']}"))
    report = {"secret_store": bounded(found["secret_store"]), "credential": bounded(found["credential"]),
              "docker": docker,
              "image": image,
              "dispatch": ("not a service" if dispatch_every is None else
                           f"every {dispatch_every:g} s" if dispatch_every else "off"),
              "problems": problems, "start": operations.service_line(core.ROOT, [ctx["cfg"]["project"]], uv=True), "at": ops_runs._now_iso()}
    if dispatch_every is not None:
        SERVICE[os.path.realpath(ctx["cfg"]["project"])] = dict(report)
    return report


def _owners() -> list:
    """[(skill, its declared outputs)] for every skill folder of the checkout that has a readable frontmatter."""
    folder, out = os.path.join(core.ROOT, "skills"), []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        try:
            out.append((name, skill_meta.declared(os.path.join(folder, name))["outputs"]))
        except (skill_meta.SkillError, OSError):
            continue
    return out


def artifacts(project: str) -> dict:
    """The files of the project under docs/ that the path rule calls a document or a machine file, sorted by path:
    {"artifacts": [{"path", "owner", "agent", "size", "modified_at", "kind", "bound"}], "truncated"}. kind is `text`,
    `markdown`, `image` or `other`, decided by the file's bytes (an image by its magic number, never its extension;
    text is UTF-8 with no NUL, at most ARTIFACT_MAX_BYTES), so the Desk knows before it opens a file. owner is the skill whose
    declared outputs match the path (skill_meta.matches), or None. agent is the area agent whose pack holds the owner
    skill, as plan.agent_of decides it; None when there is no owner, the project has no area agents, or no one agent
    (or several) owns the skill. modified_at is ISO-8601 UTC. bound is true when a pending
    decision still open lists the file among those a run returned or kept for it, or when its skill's runtime
    manifest binds it to an approval by its hash. Never docs/workbench/runtime.json, a link, a hidden file or folder,
    a folder the path rule drops, or a file outside docs/. At most ARTIFACT_LIMIT files; truncated says whether more were left out."""
    ctx = core.context(project)
    root = ctx["cfg"]["project"]
    base = os.path.join(root, "docs")
    owners = _owners()
    try:
        packs = plan.agent_skills(ctx["cfg"], core.ROOT)
    except plan.PlanError as e:
        raise core.OpsError(f"the agents of the packs cannot be told: {e}", 1) from None
    agent_by_owner = {}
    waiting = set()
    for item in core._stored(ctx, ctx["store"].pending_list):
        payload = item.get("payload") or {}
        for key in ("returned", "kept"):
            waiting.update(f["path"] for f in payload.get(key) or [] if isinstance(f, dict) and isinstance(f.get("path"), str))
    bound_by_owner = {}
    out, truncated = [], False
    if os.path.isdir(base) and not os.path.islink(base):
        for current, folders, files in os.walk(base, followlinks=False):
            folders[:] = sorted(d for d in folders if not d.startswith(".") and not os.path.islink(os.path.join(current, d)))
            for name in sorted(files):
                full = os.path.join(current, name)
                if name.startswith(".") or os.path.islink(full) or not os.path.isfile(full):
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                if path_rule.classify(rel) not in ("document", "machine"):
                    continue
                if len(out) >= ARTIFACT_LIMIT:
                    truncated = True
                    break
                owner = next((skill for skill, outputs in owners if skill_meta.matches(outputs, rel)), None)
                if owner not in bound_by_owner:
                    try:
                        bound_by_owner[owner] = manifest.load(core.ROOT, owner, whole=False) if owner else {}
                    except manifest.ManifestError:
                        bound_by_owner[owner] = {}
                if owner not in agent_by_owner:
                    try:
                        agent_by_owner[owner] = plan.agent_of(owner, packs) if owner and packs else None
                    except ValueError:
                        agent_by_owner[owner] = None
                found = os.lstat(full)
                out.append({"path": rel, "owner": owner, "agent": agent_by_owner[owner], "size": found.st_size, "modified_at": _utc(found.st_mtime),
                            "kind": _kind(full, rel, found.st_size),
                            "bound": rel in waiting or bool(manifest.bound_among(bound_by_owner[owner], [rel]))})
            if truncated:
                break
    return {"artifacts": sorted(out, key=lambda a: a["path"]), "truncated": truncated}


def _utc(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_regular(here: str, rel: str):
    """The file at `here`, opened without following a link, as a binary file object; refused (code 2) when it is not a
    regular file (the descriptor is checked, not the name looked at before)."""
    try:
        fd = os.open(here, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        raise core.OpsError(f"{rel} cannot be opened without following a link", 2) from None
    f = os.fdopen(fd, "rb")
    if not stat_module.S_ISREG(os.fstat(f.fileno()).st_mode):
        f.close()
        raise core.OpsError(f"{rel} is not a regular file", 2)
    return f


def _artifact_file(ctx: dict, path: str) -> tuple:
    """(rel, the file's absolute path, its lstat) of a file the interface may read under docs/: the path is relative to
    the project and normalised first (path_rule.normal: no "..", no absolute path). Refused (code 2) before anything
    is read: a path outside docs/, docs/workbench/runtime.json, a path the path rule drops or does not know, a hidden
    file or a file in a hidden folder (a part that starts with "."), a path with a link on any part of it (the
    project's own folder excepted), a file that is not a regular file. A path that is not there is refused with code 1."""
    rel = path_rule.normal(path)
    if rel is None or not rel.startswith(path_rule.DOCS_DIR) or rel == path_rule.CONFIG:
        raise core.OpsError("an artifact is a file under docs/ of the project, other than the runtime's configuration", 2)
    if path_rule.classify(rel) not in ("state", "document", "machine"):
        raise core.OpsError(f"{rel} is not a file the interface reads", 2)
    if any(part.startswith(".") for part in rel.split("/")):
        raise core.OpsError(f"{rel} is a hidden file or inside a hidden folder: it is not read", 2)
    here = ctx["cfg"]["project"]
    for part in rel.split("/"):
        here = os.path.join(here, part)
        if os.path.islink(here):
            raise core.OpsError(f"{rel} is or passes through a link: it is not read", 2)
    try:
        looked = os.lstat(here)
    except OSError:
        raise core.OpsError(f"there is no file {rel} in the project", 1) from None
    if not stat_module.S_ISREG(looked.st_mode):  # before any open: a pipe would block it
        raise core.OpsError(f"{rel} is not a regular file", 2)
    return rel, here, looked


def artifact(project: str, path: str) -> dict:
    """The text of one file of the project under docs/, read-only: {"path", "text", "size", "modified_at"}. The path
    rules are _artifact_file's. Refused (code 2) also: a file over ARTIFACT_MAX_BYTES, or whose bytes are not UTF-8 text
    (a NUL is not text); an image is read with `artifact-raw`."""
    ctx = core.context(project)
    rel, here, looked = _artifact_file(ctx, path)
    if looked.st_size > ARTIFACT_MAX_BYTES:
        raise core.OpsError(f"{rel} is {looked.st_size} bytes: over the {ARTIFACT_MAX_BYTES} the interface reads", 2)
    with _open_regular(here, rel) as f:
        found = os.fstat(f.fileno())  # the file that was opened, not the one that was looked at
        data = f.read(ARTIFACT_MAX_BYTES + 1)
    if len(data) > ARTIFACT_MAX_BYTES:
        raise core.OpsError(f"{rel} is over the {ARTIFACT_MAX_BYTES} bytes the interface reads", 2)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise core.OpsError(f"{rel} is not UTF-8 text", 2) from None
    if "\x00" in text:
        raise core.OpsError(f"{rel} is not text", 2)
    return {"path": rel, "text": text, "size": len(data), "modified_at": _utc(found.st_mtime)}


SVG_REFUSED_ELEMENTS = frozenset(("script", "foreignobject", "iframe", "object", "embed", "animate", "set", "handler"))
URL_CALL = re.compile(r"url\(\s*['\"]?\s*([^'\")]*)", re.I)


def _svg_text_safe(text: str) -> bool:
    """Style text or an attribute value that points nowhere outside the document: no `@import`, no `javascript:`
    (spaces and control characters inside it do not hide it) and every `url(...)` a fragment (`#id`) of the file."""
    squeezed = re.sub(r"[\s\x00-\x1f]+", "", text).lower()
    if "javascript:" in squeezed or "@import" in squeezed:
        return False
    return all(m.group(1).strip().startswith("#") for m in URL_CALL.finditer(text))


def _svg_safe(data: bytes) -> bool:
    """Whether the bytes are an SVG document that is inert as an image and as a document opened on its own (a `blob:`
    URL of the page, on the service's origin): XML text whose root element is `svg` (the SVG namespace, or none) and in
    which nothing runs, loads or points outside the file. Refused: the elements script, foreignObject, iframe, object,
    embed, any animate*, set; an event-handler attribute (`on...`); an `href` or `xlink:href` whose value does not start
    with `#`; `javascript:` or an `@import` in any attribute value or style; a `url(...)` that is not a fragment of
    the file; a document type with an external identifier or an internal subset; an entity declaration; a
    processing instruction (`xml-stylesheet`). Parsed with expat, which fetches nothing."""
    parser = xml.parsers.expat.ParserCreate(namespace_separator=" ")
    seen, state = [], {"style": 0, "text": []}

    def refuse(*_args):
        raise ValueError("refused")

    def start(name, attrs):
        space, _, local = name.rpartition(" ")
        if not seen and (local != "svg" or space not in ("", SVG_NAMESPACE)):
            refuse()
        seen.append(local)
        low = local.lower()
        if low in SVG_REFUSED_ELEMENTS or low.startswith("animate"):
            refuse()
        if low == "style":
            state["style"] += 1
        for key, value in attrs.items():
            attr = key.rpartition(" ")[2].lower()
            if attr.startswith("on") or (attr == "href" and not value.startswith("#")) or not _svg_text_safe(value):
                refuse()

    def end(name):
        if name.rpartition(" ")[2].lower() == "style":
            state["style"] -= 1
            if not _svg_text_safe("".join(state["text"])):
                refuse()
            state["text"].clear()

    def text(chunk):
        if state["style"]:
            state["text"].append(chunk)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = lambda _name, system, public, internal: refuse() if internal or system or public else None
    parser.ProcessingInstructionHandler = refuse
    parser.EntityDeclHandler = refuse
    try:
        parser.Parse(data, True)
    except (ValueError, xml.parsers.expat.ExpatError):
        return False
    return bool(seen)


def _looks_svg(head: bytes) -> bool:
    start = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    return start.startswith(b"<") and b"<svg" in head.lower()


def _image_type(head: bytes, whole=None):
    """The media type of an image by its bytes (the magic number, never the extension): image/png, image/jpeg,
    image/webp, or image/svg+xml for an SVG that passes _svg_safe; None otherwise. `head` is the first HEAD_BYTES at
    least; `whole` is a function that returns all the bytes, called only for an SVG."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if _looks_svg(head) and whole is not None and _svg_safe(whole()):
        return "image/svg+xml"
    return None


def _is_text(head: bytes, complete: bool) -> bool:
    """UTF-8 without a NUL; a head cut inside a multi-byte character is still text."""
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        return not complete and e.start >= len(head) - 3
    return True


def _kind(full: str, rel: str, size: int) -> str:
    """text | markdown | image | other for a file, decided by its bytes (_image_type, then UTF-8 text no larger than
    ARTIFACT_MAX_BYTES), never by its name alone: the name only tells Markdown from other text."""
    try:
        with _open_regular(full, rel) as f:
            head = f.read(HEAD_BYTES)
            if _image_type(head, lambda: head + f.read(IMAGE_MAX_BYTES - len(head) + 1)[:IMAGE_MAX_BYTES]):
                return "image" if size <= IMAGE_MAX_BYTES else "other"
    except (core.OpsError, OSError):
        return "other"
    if size > ARTIFACT_MAX_BYTES or not _is_text(head, size <= HEAD_BYTES):
        return "other"
    return "markdown" if rel.lower().endswith(".md") else "text"


def _what(head: bytes) -> str:
    """A few words for a file's type, for the sentence that says the Desk cannot show it."""
    for magic, words in OTHER_TYPES:
        if head.startswith(magic):
            return words
    return "text" if _is_text(head, False) else "a binary file"


def artifact_raw(project: str, path: str) -> dict:
    """The bytes of one image of the project under docs/, read-only: {"path", "media_type", "size", "modified_at",
    "data"}. The path rules are _artifact_file's. The type comes from the file's bytes, never its name: png, jpeg, webp
    (the magic number) or svg (XML text whose root is `svg`, with no script element and no event-handler attribute),
    at most IMAGE_MAX_BYTES. Refused (code 2) for a file of another type, with the sentence the page shows ("<path> is
    <what>, <size> bytes: the Desk shows text, Markdown and images"), for a file over the size, and for an SVG that
    does not pass. The local service answers them with the media type, `Cache-Control: no-store`, `nosniff`, the page's
    policy and `Content-Disposition: inline`; they are never put in a page as markup."""
    ctx = core.context(project)
    rel, here, looked = _artifact_file(ctx, path)
    if looked.st_size > IMAGE_MAX_BYTES:
        raise core.OpsError(f"{rel} is {looked.st_size} bytes: over the {IMAGE_MAX_BYTES} the Desk shows as an image", 2)
    with _open_regular(here, rel) as f:
        found = os.fstat(f.fileno())
        data = f.read(IMAGE_MAX_BYTES + 1)
    if len(data) > IMAGE_MAX_BYTES:
        raise core.OpsError(f"{rel} is over the {IMAGE_MAX_BYTES} bytes the Desk shows as an image", 2)
    media = _image_type(data[:HEAD_BYTES], lambda: data)
    if media is None:
        what = _what(data[:HEAD_BYTES])
        if what == "text":
            raise core.OpsError(f"{rel} is text, {len(data)} bytes, not an image: it opens as text", 2)
        raise core.OpsError(f"{rel} is {what}, {len(data)} bytes: the Desk shows text, Markdown and images", 2)
    return {"path": rel, "media_type": media, "size": len(data), "modified_at": _utc(found.st_mtime), "data": data}
