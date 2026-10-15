#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Which model a run goes to, in the operations layer: the person's choice (a request, a task, an agent, the project's
default), the proof of the skill on each model (runtime/proof.py) and the person's consent for an agent's own model
(decision D38).

There are no tiers. A request or a task carries a model id or `auto`; without one the agent's fixed model decides, else the
project's `default_model` (runtime.json), else `auto`. `resolve` reads that order; `route` asks the proof for the pair and adds
what only the operations layer knows: the billing of the credential the run would use, the key by its source, and
whether an unproven pair is released by the person's consent (autonomy "consent").

  resolve(ctx, task, requested)       (the model word, what chose it): "request", "task", "agent" or "default"
  route(ctx, skill, meta, keys, task, requested)   proof.route plus the key, the billing and the consent
  consent_for_review(ctx, run, agent_entry)  the two facts a review's release reads: (proven, consent)
  price_table(ctx)                    (the price table, the project's price_max_age_days)
  models_read(ctx, skill)             one skill's pairs as the pickers show them
  scope_summary(ctx, skills)          one line for each model over a set of skills (a picker's line beside the model)
  recommend(lines)                    the model a picker marks as the recommendation

Sibling of runtime/ops.py; no shell imports this file. The shared names come from ops_core (read as `core.<name>`, at call
time). It reaches no operation of ops.py.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import os
import sys

import autonomy
import lab
import ops_core as core
import prices
import proof as proof_rules

AUTO = autonomy.AUTO_MODEL


def check_word(model) -> str | None:
    """The model word a person typed, checked: None (none chosen), "auto", or the listed id of a model of the gate file (an
    alias is written as its id). Anything else is a refusal (core.OpsError, code 2): the lab runs the models the file lists."""
    if model is None or model == "":
        return None
    if not isinstance(model, str):
        raise core.OpsError("model is a model id of the gate file, or \"auto\"", 2)
    if model == AUTO:
        return AUTO
    try:
        return lab.resolve_model(model)
    except lab.LabError as e:
        raise core.OpsError(e.reason, 2) from None


def resolve(ctx: dict, task: dict | None, requested: str | None = None) -> tuple:
    """(the model word, what chose it) for a run of a task, the first that applies:
    1. requested: the person's own start by hand (run-task --model): "request";
    2. the task's own model: "task";
    3. the model of the request the task belongs to: "request";
    4. the agent's fixed model, an id or "auto": "agent";
    5. the project's default_model: "default";
    6. none: (None, "default"), which proof.route reads as `auto`.
    The word is an id or alias of the gate file, "auto", or None."""
    cfg, store = ctx["cfg"], ctx["store"]
    if requested:
        return requested, "request"
    if task is not None and task.get("model"):
        return task["model"], "task"
    if task is not None and task.get("parent_id") is not None:
        try:
            request = core._stored(ctx, store.task_get, task["parent_id"])
        except core.OpsError:
            request = None
        if request and request.get("model"):
            return request["model"], "request"
    agent = (cfg["area_agents"].get(task.get("agent")) if task is not None and task.get("agent") else None) or {}
    if agent.get("model"):
        return agent["model"], "agent"
    if cfg.get("default_model"):
        return cfg["default_model"], "default"
    return None, "default"


def price_table(ctx: dict) -> tuple:
    """(the price table, the project's price_max_age_days): the one table of the workbench, runtime/prices.json."""
    return prices.load(), ctx["cfg"].get("price_max_age_days", prices.MAX_AGE_DEFAULT)


def route(ctx: dict, skill: str, meta: dict, keys, task: dict | None = None, requested: str | None = None,
          approved=None) -> dict:
    """proof.route for one run, with what this layer adds: the routing is proof.route's, and

      "key"      the source of the key of the chosen model ("runtime", "lab"), or None when none was found; a reason is
                 added to "reasons" then, and the caller refuses to start
      "billing"  how the credential the run would use is billed (ops_core._model_billing): "subscription", "metered",
                 "free", or None when no manifest says
      "autonomy" "proven", "consent" or "supervised". "consent" only for a model the agent is FIXED to (named by "agent"),
                 chosen by name, not proven, with the person's consent in force for that model and that mode
                 (autonomy.consent_valid); a model named on a request, a task or by the project's default never is, and
                 neither is a pair `auto` chose

    An unknown model is a refusal (core.OpsError, code 2)."""
    cfg = ctx["cfg"]
    word, named_by = resolve(ctx, task, requested)
    table, _ = price_table(ctx)
    try:
        routing = proof_rules.route(cfg, skill, meta, model=word, default=cfg.get("default_model"), named_by=named_by,
                                    key_found=keys.found if keys is not None else None, table=table, approved=approved)
    except ValueError as e:
        raise core.OpsError(str(e), 2) from None
    found = keys[routing["model"]] if keys is not None else {"source": None, "reason": None}
    routing["key"] = found["source"]
    if found["reason"] and found["source"] is None:
        routing["reasons"].append(found["reason"])
    if routing["mode"] != "named" and keys is not None:  # auto leaves a reliable model out for want of a key: say why, by the key's reason
        for model, band in routing["bands"].items():
            if band == "reliable" and model != routing["model"] and not keys.found(model) and keys[model]["reason"]:
                routing["reasons"].append(keys[model]["reason"])
    routing["billing"] = core._model_billing(routing["model"], routing["adapter"])
    agent =(cfg["area_agents"].get(task.get("agent")) if task is not None and task.get("agent") else None) or {}
    routing["consent"] = False
    if (routing["autonomy"] != "proven" and named_by == "agent" and routing["mode"] == "named"
            and autonomy.consent_valid(agent, routing["model"])):
        routing["autonomy"], routing["consent"] = "consent", True
        routing["reasons"].append(f"{routing['model']} is unproven for this skill; the person consented to it for this agent: "
                                  "its reviews are released by the mode, and the run is recorded as autonomy by consent")
    return routing


def consent_for_review(ctx: dict, run: dict | None, agent_entry: dict | None, routed_proven: bool) -> tuple:
    """(proven, consent) for the review of a run, the two facts autonomy.review_action reads (rule 5).

    A run that recorded how its pair was released (the `autonomy` column of migration 10) is read by it: `proven` stands
    only while the skill is still proven on the model that ran (routed_proven, the proof of the run's model read now),
    and `consent` stands only while the person's consent is still in force for the agent's fixed model and mode. `supervised`
    is neither. A run that recorded none (older than the column, or a test's stand-in) is read as before: proven when the
    skill is proven now (routed_proven), no consent."""
    word = (run or {}).get("autonomy")
    if word is None:
        return bool(routed_proven), False
    if word == "proven":
        return bool(routed_proven), False
    if word == "consent":
        return False, autonomy.consent_valid(agent_entry, (run or {}).get("model"))
    return False, False


def models_read(ctx: dict, skill: str, today=None) -> dict:
    """One skill's pairs as the pickers and the proof read show them (proof.pair_view), one for each model of the gate file:
    {"skill", "default_model", "lab_models", "pairs": [...], "recommended": the model `auto` would choose now or None,
    "checks"}. The recommendation is the cheapest reliable pair with a key, a price and a measured usage; it is a hint for the
    person and never a gate (decision D34)."""
    import skill_meta
    cfg = ctx["cfg"]
    meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
    table, max_days = price_table(ctx)
    entry = proof_rules.row(cfg, skill)
    keys = core._keys()
    today = today or datetime.date.today()
    chosen = proof_rules.route(cfg, skill, meta, model=AUTO, default=cfg.get("default_model"), key_found=keys.found, table=table)
    return {"skill": skill, "default_model": cfg.get("default_model"), "lab_models": entry.get("lab_models") or [],
            "pairs": [{**proof_rules.pair_view(pair, table, today, max_days), "key": keys[pair["model"]]["source"]}
                      for pair in entry["pairs"]],
            "recommended": chosen["model"] if chosen["mode"] == AUTO else None, "checks": chosen["checks"]}


def band_word(line: dict) -> str:
    """The one word for a model over a set of skills: `reliable` when it is reliable for every one, `partial` when for some,
    `needs a test` when for none (or when there is no skill)."""
    total, reliable = line.get("skills") or 0, line.get("reliable") or 0
    return "reliable" if total and reliable == total else ("partial" if reliable else "needs a test")


def scope_summary(ctx: dict, skills: list, today=None) -> dict:
    """{model id: {"skills", "reliable", "community_only", "expected_cost", "band", "price"}} over the given skills, read from
    the proof entries (proof.row) and the one price table, without any check of the machine: `skills` is how many of them have
    a pair for the model, `reliable` how many of those are `reliable` on it, `community_only` how many of the reliable ones
    rest on community evidence alone (their output is reviewed), `expected_cost` the mean of the expected cost per run of the
    pairs that have one (dollars, or None), `band` band_word, `price` the model's entry of the table with its source, date,
    age and whether it is stale (or None). What the pickers show beside a model; the choice is never gated by it (D34)."""
    table, max_days = price_table(ctx)
    today = today or datetime.date.today()
    found, costs = {}, {}
    for name in skills:
        entry = proof_rules.row(ctx["cfg"], name)
        for pair in entry["pairs"]:
            view = proof_rules.pair_view(pair, table, today, max_days)
            line = found.setdefault(pair["model"], {"skills": 0, "reliable": 0, "community_only": 0, "expected_cost": None, "price": view["price"]})
            line["skills"] += 1
            if pair["band"] == "reliable":
                line["reliable"] += 1
                if pair.get("source") not in proof_rules.RELEASING:
                    line["community_only"] += 1
            if view["expected_cost"] is not None:
                costs.setdefault(pair["model"], []).append(view["expected_cost"])
    for model, line in found.items():
        line["expected_cost"] = sum(costs[model]) / len(costs[model]) if costs.get(model) else None
        line["band"] = band_word(line)
    return found


def recommend(lines) -> str | None:
    """The model a picker marks as the recommendation, from lines that carry "model", "skills", "reliable" and
    "expected_cost": the cheapest of the models that are reliable for every skill; with none of those, the cheapest of the
    models reliable for the most skills; None when no model is reliable for any skill or none has an estimate. A hint for the
    person, never a gate."""
    lines = [line for line in lines if line.get("expected_cost") is not None and line.get("reliable")]
    full = [line for line in lines if line["reliable"] == line.get("skills")]
    if not full and lines:
        best = max(line["reliable"] for line in lines)
        full = [line for line in lines if line["reliable"] == best]
    return min(full, key=lambda line: (line["expected_cost"], -line["reliable"], line["model"]))["model"] if full else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
