#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The five autonomy modes of an area agent, from the three facts under them, and the daily caps: the one module
that compares a mode word (decision D14 of the platform plan).

An area agent is an entry of "area_agents" in the project's configuration (runtime.json): a pack of skills, whether
it is enabled, its mode, two caps, optionally the model it is fixed to ("model": a model id, or "auto") and, with a model
fixed in an autonomous mode, the person's consent (decision D38): "consent": {"model", "mode"}. The mode the person chose rests on three facts: whether the agent is enabled,
the checkpoints of its mode (every-phase, milestones, end) and whether a standing approval is in force for it. One
mapping (mode_of) turns the facts back into the mode the agent acts in now, so an agent set to
autonomous-with-policy whose approval expired acts as autonomous: its effects ask again.

  MODES, DEFAULT_MODE, CHECKPOINTS             MODES is also the order of autonomy, the least first
  narrows(old, new)                             whether a move from mode old to mode new is down that order
  agents(raw)                                   the checked "area_agents" ({} when absent; an absent cap is 0)
  facts(name, agents, standing, now)            {"enabled", "checkpoints", "standing"} of one agent
  mode_of(facts)                                the mode the agent acts in now
  state_checkpoints(agents)                     the value of the state file's "- Checkpoints:" line: the most careful
                                                among the enabled agents (every-phase when none is enabled)
  BILLINGS, RUNS_BILLINGS, SPEND_BILLINGS       the billing words of a credential, and which cap counts each:
                                                subscription and free count runs (max_runs_per_day), metered counts
                                                dollars (max_usd_per_day); the word a run used is recorded on its row,
                                                and "unknown" when the route had none (counted as metered)
  history_billing(run, metered_models)          the billing of a run row that has none (older than the column): a run on
                                                a model whose credential is billed by use is metered, any other's subscription
  with_billing(runs, metered_models)            the rows with that fallback filled in where the billing is null (only there)
  CONSENT_WARNING, CONSENT_MODES                the text the person reads before a model is fixed on an autonomous agent, and the
                                                modes it applies to
  consent_needed(entry)                         whether the agent's settings (model fixed, autonomous mode) need the person's consent
  consent_valid(entry, model)                   whether the consent stored with the agent names this model and this mode, and the
                                                model is the agent's fixed one
  run_budget(entry, spent, per_run_usd)         the spend limit of a metered run: the per-run limit, or what is left of the
                                                day's dollar cap when that is less; None when under MIN_RUN_BUDGET_USD
  spend(runs, agent, per_run_usd)               a day's spend of one agent by billing: {"runs_counted", "usd_metered",
                                                "runs_without_cost"} (a metered run of unknown cost counts at per_run_usd)
  NO_SPEND_FAILURES, never_reached_the_model(run)   the failure words that prove no model was called, and the one test:
                                                such a run reserves nothing and is no run for the runs cap (A-57)
  spend_split(runs, agent, per_run_usd)         the one place the day's rule is written: {"usd_recorded",
                                                "usd_reserved", "runs_total", "runs_counted", "runs_without_cost"};
                                                spend reads it (usd_metered = usd_recorded + usd_reserved, exactly)
  may_start(name, agents, facts, spent, billing)   (True, "") or (False, why): stopped, a cap reached for the billing of
                                                the run about to start, or a billing nobody knows
  review_action(task, pending, facts, proven, mandatory, consent=False)   "release" or "hold": whether a mode releases a review
  covers(approval, policy_sha256, effect, executed_today, now, resolved=None)   (True, "") or (False, why): whether a
                                                standing approval covers one effect, inside every bound; a target
                                                that is a class word is covered only by what the caller resolved
  bounds_of(data, agent, effects)               a policy's bounds file, checked (docs/workbench/policies/<policy>.json);
                                                effects is the closed vocabulary of side effects, given by the caller
  block_bounds(policy, text, agent)             the bounds of a Markdown engagement policy, derived from its
                                                ```engagement-policy block (None when the text holds none)

A mode never releases a question; it releases a review only when the run ended `done` and wrote something (never a
`draft_with_questions`, an `unclassified` reply, a `done` whose reason says no file changed, or a blocked change set),
the skill is proven on the model that ran (by lab or local evidence) or the person consented to that model for the agent
(consent, decision D38), and the task is not a milestone of its mode nor a mandatory milestone. Releasing is not
approving. An effect is executed without asking only inside an approved policy (covers, limit L15).

Usage (a library): python3 runtime/autonomy.py --help

Standard library only. Runs on Python 3.9. Pure: no store, no file, no clock of its own.
"""
from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import math
import re
import sys

# The modes in the order of how much an agent may do on its own, the least first: this order is data, and "narrowing" is
# a move down it. A narrowing widens nothing, so code may accept the configuration it changes (runtime/ops.py, set_mode);
# a move up never is accepted by code.
MODES = ("stopped", "supervised", "milestones", "autonomous", "autonomous-with-policy")
DEFAULT_MODE = "milestones"
CHECKPOINTS = {"stopped": "every-phase", "supervised": "every-phase", "milestones": "milestones", "autonomous": "end",
               "autonomous-with-policy": "end"}
CAREFUL_ORDER = ("every-phase", "milestones", "end")  # the most careful first
AGENT_KEYS = ("pack", "enabled", "mode", "max_runs_per_day", "max_usd_per_day", "max_parallel", "model", "consent")
AUTO_MODEL = "auto"  # the model word of "choose by the evidence and the price" (runtime/proof.py)
# The modes in which the agent's reviews are released without the person: an agent fixed to a model there needs the person's
# consent (decision D38). Both end the work at "end" checkpoints (CHECKPOINTS).
CONSENT_MODES = ("autonomous", "autonomous-with-policy")
# What the person reads before a model is fixed on an autonomous agent, once, here: the page, the terminal and the refusal read this
# constant and no other copy of the text exists.
#
# The text says what is recorded, exactly (P3b): `autonomy: "consent"` is written when a run starts, for a run of this agent on the
# model fixed in its own settings (ops_models.route: the model comes from the agent, not from a task or a request that names the same
# one), of a skill that is not proven on that model: proven means the lab's evidence or the person's own tests, with the measurement
# and the image checks passing. A pair reliable only through community evidence, or whose checks fail, is recorded as consent too;
# whatever the mode then does with the review (a milestone may still hold it). A proven skill is released by the mode as for any
# proven model and its runs are recorded as proven.
CONSENT_WARNING = ("Each run of this agent on its fixed model, of a skill not proven on that model by the lab's evidence or your own "
                   "tests, will be recorded as autonomy by consent, including a run that a milestone later holds for your review. "
                   "In this mode those runs' reviews are released without you; skills proven on the model are released by the mode "
                   "as for any proven model.")
# The sha256 of that text: what a page sends back with the consent to prove it showed the exact text (give-consent checks it).
CONSENT_WARNING_SHA256 = hashlib.sha256(CONSENT_WARNING.encode("utf-8")).hexdigest()
# the release's cap of tasks holding a slot on one floor (the maintainer, 2026-10-12): the one constant; the interface reads it from the agents read and never writes the number; raising it needs the scene to give a floor more seats (SPEC-PAR-7)
MAX_PARALLEL_CEILING = 4
POLICY_MODE = "autonomous-with-policy"
# How the credential a run uses is billed (adapters/<harness>/adapter.json, contracts/secrets.md), and so which daily cap the run
# counts against: a subscription covers its runs and a local model costs nothing, so those count runs; a key paid by use
# counts dollars. The words are those of runtime/billing.py and of the store's CHECK; a test holds them equal.
# A fourth word is written by the runtime, never declared by a manifest: "unknown" is the billing of a run that started on a
# route no manifest could bill. It is not a row older than the column (that one is NULL, history_billing): its dollars are
# never left uncounted, so spend_split counts it as metered.
BILLINGS = ("subscription", "metered", "free", "unknown")
RUNS_BILLINGS = ("subscription", "free")
SPEND_BILLINGS = ("metered",)
# The failure words of a run row (providers/store/sqlite.py RUN_FAILURES) that can PROVE no model was called, so that the run spent
# nothing and used none of the runs cap (A-57, P-19). Each is set where the lab or the runtime refuses before the model could answer:
#   auth      evals/run_attempts.py: the provider refused the key or the credential (a 401); never retried
#   settings  evals/run_attempts.py: the copy carries a tool's settings; refused before the adapter is called
# A word alone proves nothing: with retries an earlier attempt may have spent before the one that was refused, an adapter may meet a
# 401 after several calls, and the lab's reading of "HTTP 401" scans the model's own output. So the word proves it only for a run
# whose FIRST attempt was the refused one (`attempts` 1) and that reported no tokens and no cost (a failed row stores what its
# attempts' timing.json reported). A word that does not prove it keeps the per-run reservation, because dollars are never left
# uncounted: timeout, refused (the provider declined a request it received), adapter (it failed after it started), early_end (the
# model answered), stopped (a restart or the lab stopped it mid-run). `internal` is the runtime's own word for a refusal before the
# adapter (the image missing, no secret, a bad configuration, a copy that could not be built) and also for a crash mid-run: it
# proves nothing but with `attempts` 0, which the runtime records only when no attempt began (ops.py, lab.run_skill).
# NO_SPEND_FAILURES is the one definition; never_reached_the_model is the one test.
NO_SPEND_FAILURES = ("auth", "settings")
# The least a metered run may be given as its own spend limit when the day's dollar cap is nearly reached: a run is not started
# with a budget of a few cents, it is held with "cap: usd per day" instead.
MIN_RUN_BUDGET_USD = 0.05
NO_CHANGE = "no file changed"  # the start of the classifier's reason for a `done` that wrote nothing (runtime/endings.py)
BOUNDS_KEYS = ("policy", "agent", "effects", "targets", "files", "max_per_day", "max_items_per_run")
POLICY_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# A word of a bounds' "targets" that names a class of targets instead of one target. The class is closed, here, and its
# members are never read from the effect document or from external content: the caller (ops.execute_under_policy)
# resolves them from a recorded fact before the call and hands them to covers (a class with no resolution covers
# nothing). A class word is never a literal target.
COMMENT_ON_PUBLISHED_POST = "comment-on-published-post"  # a post the publisher's ledger records as published
TARGET_CLASSES = (COMMENT_ON_PUBLISHED_POST,)
ENGAGEMENT_BLOCK = re.compile(r"```engagement-policy\s*\n(.*?)\n```", re.S)  # the block mkt-engage's gate reads


def narrows(old: str, new: str) -> bool:
    """True when mode new is lower than mode old in the order of MODES: a move that lets the agent do less on its own.
    The same mode, or a higher one, is False. A word that is not a mode: ValueError."""
    for word in (old, new):
        if word not in MODES:
            raise ValueError(f"{word!r} is not one of {', '.join(MODES)}")
    return MODES.index(new) < MODES.index(old)


def agents(raw) -> dict:
    """The checked "area_agents" of a configuration: {name: {"pack", "enabled", "mode", "max_runs_per_day",
    "max_usd_per_day", "max_parallel"}}. Absent: {}. Defaults: enabled true, mode milestones, both caps 0 (an absent cap
    is 0, never "no limit"), max_parallel 1 (the slots of the floor: an integer from 1 to MAX_PARALLEL_CEILING). An unknown key, a mode outside MODES, a cap that is not a number of 0 or more: ValueError naming the
    agent and the key."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("area_agents is an object of agents")
    out = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("an area agent has a name")
        if not isinstance(entry, dict):
            raise ValueError(f"area agent {name}: its entry is an object")
        unknown = sorted(set(entry) - set(AGENT_KEYS))
        if unknown:
            raise ValueError(f"area agent {name}: unknown key {unknown[0]} (known: {', '.join(AGENT_KEYS)})")
        pack = entry.get("pack")
        if not isinstance(pack, str) or not pack.strip():
            raise ValueError(f"area agent {name}: pack is the name of a pack of packs/")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"area agent {name}: enabled is true or false")
        mode = entry.get("mode", DEFAULT_MODE)
        if mode not in MODES:
            raise ValueError(f"area agent {name}: mode {mode!r} is not one of {', '.join(MODES)}")
        checked = {"pack": pack, "enabled": enabled, "mode": mode}
        for key, kind in (("max_runs_per_day", int), ("max_usd_per_day", float)):
            value = entry.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or \
                    (kind is int and not isinstance(value, int)) or not math.isfinite(value) or value < 0:
                what = "a whole number" if kind is int else "a number"
                raise ValueError(f"area agent {name}: {key} is {what}, 0 or more")
            checked[key] = value
        slots = entry.get("max_parallel", 1)
        if isinstance(slots, bool) or not isinstance(slots, int) or not 1 <= slots <= MAX_PARALLEL_CEILING:
            raise ValueError(f"area_agents.{name}.max_parallel must be an integer from 1 to {MAX_PARALLEL_CEILING}")
        checked["max_parallel"] = slots
        model = entry.get("model")
        if model is not None:
            if not isinstance(model, str) or not model.strip() or model != model.strip() or len(model) > 200:
                raise ValueError(f"area_agents.{name}.model is a model id, or \"{AUTO_MODEL}\"")
            checked["model"] = model
        consent = entry.get("consent")
        if consent is not None:
            if (not isinstance(consent, dict) or set(consent) != {"model", "mode"} or not isinstance(consent["model"], str)
                    or consent["mode"] not in CONSENT_MODES):
                raise ValueError(f"area_agents.{name}.consent is {{\"model\": a model id, \"mode\": one of {', '.join(CONSENT_MODES)}}}")
            checked["consent"] = {"model": consent["model"], "mode": consent["mode"]}
        out[name] = checked
    return out


def fixed_model(entry) -> str | None:
    """The model id an agent is fixed to, or None: no model, or `auto` (a way of choosing, not a model)."""
    model = (entry or {}).get("model")
    return model if model and model != AUTO_MODEL else None


def consent_needed(entry) -> bool:
    """Whether the agent's settings need the person's consent: a model id is fixed and the mode releases reviews without
    the person (CONSENT_MODES). `auto` fixes no model: in auto, release follows the evidence alone."""
    return fixed_model(entry) is not None and (entry or {}).get("mode") in CONSENT_MODES


def consent_valid(entry, model) -> bool:
    """Whether the person's consent is in force for a run on `model`: the agent's fixed model is `model`, the mode is one of
    CONSENT_MODES, and the consent stored with the agent names that very model and that very mode. A change of the model or
    of the mode makes the stored consent stale, and the person is asked again."""
    consent = (entry or {}).get("consent")
    return (consent_needed(entry) and isinstance(consent, dict) and model is not None
            and consent.get("model") == entry["model"] == model and consent.get("mode") == entry["mode"])


def _moment(value):
    """A stored time (ISO-8601 text) or a datetime, as an aware UTC datetime; None when there is none."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        moment = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if len(text) == 10:
            text += "T23:59:59+00:00"  # a date alone holds until the end of that day, as the policy gate reads it
        moment = datetime.datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def facts(name: str, agents_checked: dict, standing, now) -> dict:
    """{"enabled", "checkpoints", "standing"} of one agent. standing is the active approvals of scope `standing`;
    it is true only when the agent's mode is autonomous-with-policy and one of them is this agent's
    (bounds["agent"]) and expires after now. An agent that is not configured is not enabled."""
    entry = agents_checked.get(name)
    if entry is None:
        return {"enabled": False, "checkpoints": CHECKPOINTS["stopped"], "standing": False}
    now = _moment(now)
    in_force = entry["mode"] == POLICY_MODE and any(
        row.get("status", "active") == "active" and (row.get("bounds") or {}).get("agent") == name
        and _moment(row.get("expires_at")) is not None and _moment(row.get("expires_at")) > now
        for row in standing or [])
    return {"enabled": bool(entry["enabled"]) and entry["mode"] != "stopped",
            "checkpoints": CHECKPOINTS[entry["mode"]], "standing": in_force}


def mode_of(f: dict) -> str:
    """The mode an agent acts in now, from its three facts: the one mapping."""
    if not f["enabled"]:
        return "stopped"
    if f["checkpoints"] == "every-phase":
        return "supervised"
    if f["checkpoints"] == "milestones":
        return "milestones"
    return POLICY_MODE if f["standing"] else "autonomous"


def state_checkpoints(agents_checked: dict) -> str:
    """The state file's Checkpoints value: the most careful checkpoints among the enabled agents; every-phase when
    no agent is enabled."""
    found = {CHECKPOINTS[a["mode"]] for a in agents_checked.values() if a["enabled"] and a["mode"] != "stopped"}
    for value in CAREFUL_ORDER:
        if value in found:
            return value
    return CAREFUL_ORDER[0]


def history_billing(run: dict, metered_models) -> str:
    """The billing of a run row: the one it recorded, else (a run older than the column, for history only) the rule the
    caps had before billing was recorded, by model: a run on a model whose credential is billed by use (metered_models, the ids
    the caller reads from the adapters' manifests) is metered and a run on any other model is subscription."""
    word = run.get("billing")
    if word in BILLINGS:
        return word
    return "metered" if run.get("model") in (metered_models or ()) else "subscription"


def with_billing(runs, metered_models) -> list:
    """The rows of runs_since with the billing of every row that has none (NULL: older than the column) filled in by
    history_billing; a row that records a word, "unknown" included, keeps it. No row is changed in place."""
    return [run if run.get("billing") is not None else dict(run, billing=history_billing(run, metered_models)) for run in runs]


def never_reached_the_model(run: dict) -> bool:
    """Whether the stored failure of a run row proves that no model was called: it is one of NO_SPEND_FAILURES with `attempts` 1
    (the first attempt was the refused one: a later attempt means an earlier one ran), or `internal` with `attempts` 0 (no
    attempt began); and the row records no cost and no tokens (what the adapter reported is counted, whatever the word). A
    run that did not fail, or whose row lacks `failure` or `attempts`, is not one."""
    if run.get("cost_usd") is not None or run.get("tokens"):
        return False
    failure, attempts = run.get("failure"), run.get("attempts")
    return (failure in NO_SPEND_FAILURES and attempts == 1) or (failure == "internal" and attempts == 0)


def spend_split(runs, agent: str, per_run_usd: float) -> dict:
    """A day's use of one agent, from the rows of runs_since(<the day's start>) with their billing (with_billing), the one
    place the rule is written: {"usd_recorded", "usd_reserved", "runs_total", "runs_counted", "runs_without_cost"}. A run on
    a credential billed subscription or free adds 1 to runs_counted (what max_runs_per_day compares) and no dollar: its cost
    is not billed. Any other run is metered: it adds its recorded cost to usd_recorded, or per_run_usd to usd_reserved when
    the cost is unknown (and 1 to runs_without_cost); a billing nobody knows is treated as metered, so that dollars are
    never left uncounted. A run that never reached the model (never_reached_the_model: it failed on the key, on the
    copy's settings, or before any attempt) is the exception to both: it reserves nothing and is no run for the runs cap,
    since it used none of the credential's allowance; a run that may have spent (a timeout, a restart, a crash mid-run)
    keeps its reservation and its place. runs_total is every run of the agent, the ones that never reached the model
    included, so that the page lists them. Each of the two sums is rounded once, to 6 places; spend's usd_metered is
    their sum."""
    recorded = reserved = 0.0
    out = {"runs_total": 0, "runs_counted": 0, "runs_without_cost": 0}
    for run in runs:
        if run.get("agent") != agent:
            continue
        out["runs_total"] += 1
        if never_reached_the_model(run):
            continue
        if run.get("billing") in RUNS_BILLINGS:
            out["runs_counted"] += 1
        elif run.get("cost_usd") is None:
            reserved += float(per_run_usd)
            out["runs_without_cost"] += 1
        else:
            recorded += float(run["cost_usd"])
    return {"usd_recorded": round(recorded, 6), "usd_reserved": round(reserved, 6), **out}


def spend(runs, agent: str, per_run_usd: float) -> dict:
    """A day's spend of one agent, from the rows of runs_since(<the day's start>) with their billing: {"runs_counted",
    "usd_metered", "runs_without_cost"}, read from spend_split: usd_metered is usd_recorded + usd_reserved, so a meter that
    shows the two adds up to it exactly. may_start compares it rounded to 6 places."""
    split = spend_split(runs, agent, per_run_usd)
    return {"runs_counted": split["runs_counted"], "usd_metered": split["usd_recorded"] + split["usd_reserved"],
            "runs_without_cost": split["runs_without_cost"]}


def may_start(name: str, agents_checked: dict, f: dict, spent: dict, billing) -> tuple:
    """(True, "") or (False, why), by the billing of the credential the run about to start would use: "stopped";
    "cap: runs per day" (billing subscription or free, runs_counted at max_runs_per_day); "cap: usd per day" (billing
    metered, usd_metered at max_usd_per_day); "unknown billing <word>" for a billing outside BILLINGS, None included (a run
    whose cap cannot be known does not start). An absent cap is 0, so nothing starts on that billing."""
    entry = agents_checked.get(name)
    if entry is None or not f["enabled"]:
        return False, "stopped"
    if billing in RUNS_BILLINGS:
        if spent["runs_counted"] >= entry["max_runs_per_day"]:
            return False, "cap: runs per day"
    elif billing in SPEND_BILLINGS:
        if run_budget(entry, spent, math.inf) is None:
            return False, "cap: usd per day"
    else:
        return False, f"unknown billing {billing!r}"
    return True, ""


def run_budget(entry: dict, spent: dict, per_run_usd: float):
    """The spend limit, in dollars to the cent and never above what is left, of a metered run about to start: the per-run limit,
    or what remains of max_usd_per_day (rounded down to the cent) when that is less. None when what remains is under
    MIN_RUN_BUDGET_USD, or nothing: the run does not start (may_start holds it with "cap: usd per day"). The cap is checked
    here, at the start; the limit travels with the run to the adapter. A run that fails or times out keeps its reservation
    counted: spend_split reads its recorded cost, else per_run_usd (unless the failure proves no model was called)."""
    left = round(entry["max_usd_per_day"] - round(spent["usd_metered"], 6), 6)
    if left < MIN_RUN_BUDGET_USD:
        return None
    return math.floor(round(min(float(per_run_usd), left) * 100, 6)) / 100


def review_action(task: dict, pending: dict, f: dict, proven: bool, mandatory: bool, consent: bool = False) -> str:
    """"release" or "hold" for one open pending decision, the first rule that matches:
    1. not a review: hold (a question, a plan, an effect, an acceptance always reach the person);
    2. its run's ending is not `done` (a draft with questions, an unclassified reply, a gate): hold;
    3. a `done` whose reason says no file changed: hold;
    4. its change set is blocked: hold;
    5. the pair that ran is not proven and the person gave no consent for it: hold. proven is lab or local evidence on the
       model that ran; consent is the person's consent (decision D38) for the agent's fixed model, true only for a run on
       that model recorded as autonomy by consent. Community evidence alone is neither: its output is reviewed;
    6. a mandatory milestone: hold, in every mode;
    7. the agent is not enabled, or its checkpoints are every-phase: hold;
    8. checkpoints milestones and the task is a milestone: hold;
    9. otherwise release."""
    if pending.get("kind") != "review":
        return "hold"
    payload = pending.get("payload") or {}
    if payload.get("ending") != "done":
        return "hold"
    if str(payload.get("why") or "").startswith(NO_CHANGE):
        return "hold"
    if (payload.get("changeset") or {}).get("blocked"):
        return "hold"
    if not (proven or consent) or mandatory:
        return "hold"
    if not f["enabled"] or f["checkpoints"] == "every-phase":
        return "hold"
    if f["checkpoints"] == "milestones" and task.get("milestone"):
        return "hold"
    return "release"


def _path_matches(path: str, pattern: str) -> bool:
    """A path against a glob, part by part, so `*` never crosses `/`."""
    parts, globs = path.split("/"), pattern.split("/")
    return len(parts) == len(globs) and all(fnmatch.fnmatchcase(p, g) for p, g in zip(parts, globs))


def _resolved(resolved, word: str):
    """The set the caller resolved for a class word, or None: only a set, a frozenset, a list or a tuple counts, so
    that `in` never reads a substring of a text."""
    found = (resolved or {}).get(word) if isinstance(resolved, dict) else None
    return found if isinstance(found, (set, frozenset, list, tuple)) else None


def covers(approval: dict, policy_sha256: str, effect: dict, executed_today: int, now, resolved=None) -> tuple:
    """(True, "") when a standing approval covers one effect now, else (False, why). Every bound must hold: the
    approval is active and not past its expiry; it was given to the bounds file as it is now (its hash); the effect's
    kind is in bounds["effects"], its target in bounds["targets"], every path of its files matches a glob of
    bounds["files"]; its number of items is at most bounds["max_items_per_run"]; fewer than bounds["max_per_day"]
    were executed today. effect is {"kind", "target", "files", "items"}.
    A word of bounds["targets"] that is in TARGET_CLASSES is a class, not a target: the effect's target is covered by
    it only when it is in resolved[<the word>], the set the operation resolved from a recorded fact before this call
    (resolved is {word: set of targets}). A class word with no entry in resolved, with an entry that is no set, or with
    an empty set covers nothing; a word of the list that is not a class is a literal target, compared as before."""
    bounds = approval.get("bounds") or {}
    if approval.get("status") != "active":
        return False, f"the approval is {approval.get('status')}, not active"
    expires = _moment(approval.get("expires_at"))
    if expires is None or expires <= _moment(now):
        return False, "the approval expired"
    if approval.get("policy_sha256") != policy_sha256:
        return False, "the bounds file changed since it was approved"
    if effect.get("kind") not in (bounds.get("effects") or []):
        return False, f"the effect {effect.get('kind')!r} is not in the policy's effects"
    targets = bounds.get("targets") or []
    target = effect.get("target")
    classes = [word for word in targets if word in TARGET_CLASSES]
    if target not in [word for word in targets if word not in TARGET_CLASSES]:
        if not classes:
            return False, f"the target {target!r} is not in the policy's targets"
        sets = [_resolved(resolved, word) for word in classes]
        if not any(found and target in found for found in sets):
            kind = ", ".join(classes)
            if not any(sets):
                return False, f"the target class {kind} could not be resolved to any target now: nothing is covered"
            return False, f"the target {target!r} is not one of the {kind} the operation resolved"
    for path in effect.get("files") or []:
        if not any(_path_matches(path, glob) for glob in bounds.get("files") or []):
            return False, f"the file {path} is outside the policy's files"
    items, most = effect.get("items"), bounds.get("max_items_per_run")
    if not isinstance(items, int) or not isinstance(most, int) or items > most:
        return False, f"{items} items is over the policy's {most} per run"
    per_day = bounds.get("max_per_day")
    if not isinstance(per_day, int) or executed_today >= per_day:
        return False, f"{executed_today} executed today is at the policy's {per_day} per day"
    return True, ""


def block_bounds(policy: str, text: str, agent: str):
    """The bounds of a Markdown engagement policy, derived by code from its ```engagement-policy JSON block, or None
    when the text holds no such block: {"policy": policy, "agent": agent, "effects": ["publish"], "targets":
    [COMMENT_ON_PUBLISHED_POST], "files": [], "max_per_day": the block's max_replies_per_day, "max_items_per_run": 1}.
    The one thing read from the block is its daily cap; ValueError when the block is not a JSON object or has no
    whole number of 1 or more under max_replies_per_day (a policy that sets no daily cap approves no automatic reply).
    The caller adds "file"; the hash of the file binds the block, so a changed block is approved and derived again."""
    found = ENGAGEMENT_BLOCK.search(text or "")
    if not found:
        return None
    try:
        block = json.loads(found.group(1))
    except ValueError as e:
        raise ValueError(f"the engagement-policy block is not valid JSON: {e}") from None
    cap = block.get("max_replies_per_day") if isinstance(block, dict) else None
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise ValueError("the engagement-policy block needs max_replies_per_day, a whole number of 1 or more: it is the "
                         "daily cap of the standing approval")
    return {"policy": policy, "agent": agent, "effects": ["publish"], "targets": [COMMENT_ON_PUBLISHED_POST], "files": [],
            "max_per_day": cap, "max_items_per_run": 1}


def bounds_of(data, agent: str, effects) -> dict:
    """A policy's bounds file, checked: {"policy", "agent", "effects", "targets", "files", "max_per_day",
    "max_items_per_run"}, every key present and no other; "agent" equal to agent; its effects words of effects (the
    closed vocabulary of contracts/environment.md, which the caller reads from its one source in code);
    targets and files lists of texts; the two maxima whole numbers of 1 or more. ValueError names the key."""
    if not isinstance(data, dict):
        raise ValueError("a bounds file holds one JSON object")
    unknown = sorted(set(data) - set(BOUNDS_KEYS))
    if unknown:
        raise ValueError(f"unknown key {unknown[0]} (known: {', '.join(BOUNDS_KEYS)})")
    missing = [key for key in BOUNDS_KEYS if key not in data]
    if missing:
        raise ValueError(f"missing key {missing[0]}")
    if not isinstance(data["policy"], str) or not POLICY_NAME.fullmatch(data["policy"]):
        raise ValueError("policy is lowercase words joined by hyphens")
    if data["agent"] != agent:
        raise ValueError(f"agent is {data['agent']!r}, not {agent!r}")
    if not isinstance(data["effects"], list) or not data["effects"] or any(e not in effects for e in data["effects"]):
        raise ValueError(f"effects is a list of {', '.join(effects)}")
    for key in ("targets", "files"):
        if not isinstance(data[key], list) or not data[key] or not all(isinstance(v, str) and v.strip() for v in data[key]):
            raise ValueError(f"{key} is a non-empty list of texts")
    for key in ("max_per_day", "max_items_per_run"):
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{key} is a whole number, 1 or more")
    return dict(data)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
