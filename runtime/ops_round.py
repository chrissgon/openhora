#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The dispatcher's round and the releases a mode makes: what a round reads before it decides, what a release starts, and the tick of the
handlers (44-C4b).

A sibling of runtime/ops.py, which re-exports the names under their own for the shells and the tests; no shell imports this file. The names
every module of the layer shares are read as `core.<name>` (runtime/ops_core.py). What a run takes in and gives back and the held record
are read as `ops_runs.<name>`, the routing of a skill on a model as `ops_models.route`, the router's run on a delivery as
`ops_requests.<name>`, the derived waits as `ops_waits.<name>`. `ops_runs.dispatch`, `ops_runs._round` and `ops_runs._pass` reach this
file at call time, through `ops_runs._round_module()`, because this file imports `ops_runs` (the held record, the children, the pieces of a
run) and `ops_runs` must not import it back. The operations `poll` and `release` stay in runtime/ops.py and call `ops_round.<name>`.

What a round reads before it decides: `_snapshot` (the tasks running, the ready tasks with the model each would run on, the open reviews,
whether the pair that ran is proven and the person's consent covers it, each area agent's facts; `_proven_on`), `_configuration_moved`
(a narrowing accepted in the middle of a round stops the next start), `_credential_stop` and `_image_stop` (a run that cannot start from
this process or this machine, so no task fails for it), and `_stops_the_round` with `DISPATCH_BUDGET`, `STOPPING_FAILURES` and
`STOPPING_REASONS` (a failure the next run would repeat, and the seconds after which a round starts no new run). What a release starts:
`_mode_releases` and `_deliveries_acceptance` (the releases each agent's mode makes, and the one acceptance that lists them), `_release`
(a pending decision resolved as released, for the person and for a mode), and what follows it (`_after_release`): the brief's delivery
routed again (`_brief_delivery`, `_reroute`, `_not_rerouted`, `_not_rerouted_decision`, `_approved_plan`) and the backlog's sub-tasks
(`_backlog_subtasks`). `_ticks` is the tick of every handler whose `dispatch` is true; it calls the operation `handler_call`, which stays in
runtime/ops.py (it is a row of the table), through `ops_facade.function("handler_call")`. Nothing here approves or executes an effect, and
no limit's code moved: the release of a delivery is not an approval.

These bodies moved from runtime/ops.py with no change of logic. The two lines that differ are the route of `_snapshot`, which calls
`ops_models.route` where ops.py called its `_route` (the same call, as `ops_requests._router_call` does since 44-C3), and the call of
`handler_call` in `_ticks`, which goes through the seam.

Standard library only. Runs on Python 3.9: python3 runtime/ops_round.py --help
"""
from __future__ import annotations

import contextlib
import os
import sys

import ops_core as core
import ops_facade
import ops_language
import ops_models
import ops_requests
import ops_runs
import ops_steps
import ops_waits
import autonomy
import dispatcher
import flow_files
import lab
import language as language_rules  # the name ops.py gives it; the bodies read it so
import plan
import project_config
import secret_state
import skill_meta


# --- stage 6: what follows a release: the brief's delivery routed again, the backlog's sub-tasks (moved from runtime/ops.py by 44-C4b, no change of logic) ---


def _release(ctx: dict, pending_id: int, by: str, actor=None) -> dict:
    """pending_resolve(released) and then _after_release, for the person (by "user") and for a mode ("mode:<mode>")."""
    item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    made = (item.get("payload") or {}).get("changeset") or {}
    if item["kind"] == "review" and made.get("blocked"):
        refused = "; ".join(f"{r['path'] or 'the whole set'}: {r['reason']}" for r in made.get("refused") or [])
        raise core.OpsError(f"pending decision {pending_id}: its change set is blocked ({refused}): answer with what to change, "
                       "or cancel the request", 1)
    task = core._stored(ctx, ctx["store"].task_get, item["task_id"])
    lock = core._route_lock(ctx["cfg"]) if item["kind"] == "review" and _brief_delivery(ctx, task) else contextlib.nullcontext()
    with lock:
        out = ops_waits.settled(ctx, core._stored(ctx, ctx["store"].pending_resolve, pending_id, resolution="released", by=by, actor=actor))
        after = _after_release(ctx, item)
    return {**out, "after": after} if after else out


def _approved_plan(ctx: dict, request_id: int):
    """The payload of the request's approved `plan` pending decision (the newest), or None: the one source of the
    plan's deliveries and limits after its approval."""
    found = [p for p in core._stored(ctx, ctx["store"].pending_list, "resolved", request_id)
             if p["kind"] == "plan" and p["resolution"] == "approved"]
    return found[-1]["payload"] if found else None


def _brief_delivery(ctx: dict, task: dict):
    """(k, delivery, plan payload) when task is the brief after which a delivery of its approved plan is routed again,
    else None."""
    if task.get("parent_id") is None:
        return None
    approved = _approved_plan(ctx, task["parent_id"]) or {}
    for k, delivery in enumerate(approved.get("deliveries") or [], 1):
        if delivery.get("reroute_after") and delivery["reroute_after"] == task["key"]:
            return k, delivery, approved
    return None


def _after_release(ctx: dict, item: dict) -> dict:
    """What a release of a review starts, by the person or by a mode (WP-6.5): (a) the brief's delivery routed again,
    with the brief's path from the files the run returned (never from the reply); (b) the backlog's sub-tasks, when the
    task's skill owns the product backlog and the run returned it. Returns {"reroute": ..., "subtasks": ...}, each only
    when it applied. The caller holds the route lock when (a) applies."""
    out = {}
    if item["kind"] != "review":
        return out
    task = core._stored(ctx, ctx["store"].task_get, item["task_id"])
    returned = [r.get("path") for r in (item.get("payload") or {}).get("returned") or [] if isinstance(r, dict)]
    found = _brief_delivery(ctx, task)
    if found is not None:
        out["reroute"] = _reroute(ctx, task, returned, *found)
    if task.get("skill") and task["skill"] == plan.owner_of(plan.BACKLOG, core.ROOT) and plan.BACKLOG in returned:
        out["subtasks"] = _backlog_subtasks(ctx, task)
    return out


def _reroute(ctx: dict, task: dict, returned: list, k: int, delivery: dict, approved: dict) -> dict:
    """Route delivery k again, once, with the line "The brief is at <path>." added. A route to a flow or a skill opens
    an `acceptance` of kind subtasks with its tasks (keys d<k>-..., the first ones after the brief); a second route to
    the brief skill, a reply that asks or names no valid route, a missing brief or a failed run opens an `acceptance`
    of kind deliveries that shows the reason and the router's whole reply: the delivery reaches the person, never a
    third run."""
    store = ctx["store"]
    request = core._stored(ctx, store.task_get, task["parent_id"])
    briefs = [rel for rel in returned if rel and rel.startswith(plan.BRIEFS_DIR)]
    if not briefs:
        return _not_rerouted(ctx, request, k, delivery, "the brief task returned no file under " + plan.BRIEFS_DIR, "")
    parts = plan.split(request["text"])
    text = ops_requests._item_text(parts["preamble"] if len(parts["items"]) > 1 else "", delivery["item"]) + \
        f"\n\nThe brief is at {briefs[0]}."
    call = ops_requests._router_call(ctx, request, text, reroute=True)
    if call["failed"]:
        if call["out"]["status"] == "cancelled":   # the request is being cancelled: nothing is opened for it (R18)
            return {"delivery": k, "run_id": call["out"]["run_id"], "pending_id": None, "routed": False, "why": "cancelled"}
        return _not_rerouted(ctx, request, k, delivery, f"the router's run failed: {call['out']['failure']['reason']}",
                             "", run_id=call["out"]["run_id"])
    read, body = call["read"], call["body"]
    why, tasks = None, None
    if read["kind"] != "route":
        why = "the router asked" if read["kind"] == "question" else read.get("why") or "no route"
    else:
        route_read = ops_requests._checked(ctx, read)
        checked = route_read["checked"]
        if not checked["ok"]:
            why = checked["why"]
        elif checked.get("skill") == plan.BRIEF_SKILL:
            why = "the router named the brief again: a delivery is routed again once"
        else:
            try:
                flows = {checked["flow"]: flow_files.load(checked["flow"], core.ROOT)} if "flow" in checked else {}
                tasks = plan.delivery_tasks(dict(route_read, title=plan.title_of(delivery["item"])), k, flows, core.ROOT,
                                            plan.pack_skills(ctx["cfg"], core.ROOT), prefix=True)
                skills = plan.agent_skills(ctx["cfg"], core.ROOT)
                inside = {t["key"] for t in tasks}
                for t in tasks:
                    if not [d for d in t["depends_on"] if d in inside]:
                        t["depends_on"] = [task["key"]] + t["depends_on"]
                    t["agent"] = plan.agent_for(t, skills)
                language_rules.with_language(tasks, request.get("language") or route_read.get("language"))
            except (flow_files.FlowError, plan.PlanError, ValueError) as e:
                why, tasks = f"no task can be planned from the route: {e}", None
    finish = call["finish"]
    if tasks is None:
        decision = _not_rerouted_decision(request, k, delivery, why, body, call["common"])
        ending = "question" if read["kind"] == "question" else "unclassified"
    else:
        lines = [f"Delivery {k} ({delivery['item']}) was routed again after its brief ({briefs[0]}): {read['line']}.",
                 "Accept to add these tasks to request " + str(request["id"]) + ":", ""]
        lines += [f"- {t['key']}: {t['title']} ({t.get('skill') or 'step ' + t['step']}, agent {t['agent'] or 'none'})" for t in tasks]
        lines += ["", language_rules.payload_line({"tasks": tasks, "project_language": ops_language.project_of(ctx["cfg"])})]
        decision = {"kind": "acceptance", "title": f"Accept the tasks of delivery {k}, routed after its brief",
                    "body": "\n".join(lines), "payload": {"what": "subtasks", "delivery": k, "brief": briefs[0],
                                                          "route": read["line"], "tasks": tasks, **call["common"]}}
        ending = "done"
    done = core._stored(ctx, store.route_run_finish, call["out"]["run_id"], ending=ending, pending=decision, **finish)
    return {"delivery": k, "run_id": call["out"]["run_id"], "pending_id": done["pending_id"],
            "routed": tasks is not None and not done["cancelled"], "why": why}


def _not_rerouted_decision(request: dict, k: int, delivery: dict, why: str, reply: str, common: dict) -> dict:
    body = (f"Delivery {k} of request {request['id']} ({delivery['item']}) was not planned after its brief: {why}. "
            "Accepting records that you read this; start a new request for this delivery when you want it.")
    if reply:
        body += "\n\nThe router's reply, whole:\n\n" + reply
    return {"kind": "acceptance", "title": f"Delivery {k} was not routed after its brief",
            "body": body, "payload": {"what": "deliveries", "delivery": k, "why": why, **common}}


def _not_rerouted(ctx: dict, request: dict, k: int, delivery: dict, why: str, reply: str, run_id=None) -> dict:
    decision = _not_rerouted_decision(request, k, delivery, why, reply, {})
    opened = core._stored(ctx, ctx["store"].acceptance_open, task_id=request["id"], what="deliveries",
                     title=decision["title"], body=decision["body"], payload=decision["payload"])
    return {"delivery": k, "run_id": run_id, "pending_id": opened["pending_id"], "routed": False, "why": why}


def _backlog_subtasks(ctx: dict, task: dict) -> dict:
    """The product backlog's todo tasks as sub-tasks of the request, within the limits of its approved plan (read from
    that plan's payload and nowhere else): those inside are added at once (tasks_add), the others wait in one
    `acceptance` of kind subtasks. A task the request already has is not proposed again."""
    store, request_id = ctx["store"], task["parent_id"]
    approved = _approved_plan(ctx, request_id) or {}
    limits = approved.get("limits") or {}
    try:
        proposed = plan.backlog_tasks(os.path.join(ctx["cfg"]["project"], *plan.BACKLOG.split("/")), core.ROOT)
    except ValueError as e:
        return {"error": str(e)}
    rows = [t for t in core._stored(ctx, store.tasks_list, request_id) if t["parent_id"] is not None]
    known = {t["key"] for t in rows if t.get("key")}
    planned = {t.get("key") for t in approved.get("tasks") or []}
    proposed = [p for p in proposed if p["key"] not in known]
    if not proposed:
        return {"created": [], "pending_id": None}
    language_rules.with_language(proposed, ops_language.of_plan(approved, core._stored(ctx, store.task_get, request_id), task))
    skills = plan.agent_skills(ctx["cfg"], core.ROOT)
    for p in proposed:
        try:
            p["agent"] = plan.agent_of(p["skill"], skills) if skills else None
        except ValueError:
            p["agent"] = None  # no agent owns it: it waits, and the person can run it by hand
    chosen = plan.subtasks(limits, len([t for t in rows if t.get("key") not in planned]), proposed, known)
    created = ops_waits.add_subtasks(ctx, request_id, chosen["create"])["tasks"] if chosen["create"] else []
    pending_id = None
    if chosen["ask"]:
        lines = [f"The product backlog proposes {len(chosen['ask'])} task(s) outside the approved plan's limits "
                 f"({limits.get('max_subtasks', 0)} sub-tasks of {', '.join(limits.get('subtask_skills') or []) or 'no skill'}):", ""]
        lines += [f"- {t['key']}: {t['title']}" + (f" (after {', '.join(t['depends_on'])})" if t["depends_on"] else "")
                  for t in chosen["ask"]]
        lines += ["", language_rules.payload_line({"tasks": chosen["ask"], "project_language": ops_language.project_of(ctx["cfg"])})]
        pending_id = core._stored(ctx, store.acceptance_open, task_id=request_id, what="subtasks",
                             title=f"Accept {len(chosen['ask'])} sub-task(s) of request {request_id}",
                             body="\n".join(lines), payload={"tasks": chosen["ask"]})["pending_id"]
    return {"created": [t["id"] for t in created], "pending_id": pending_id}



# --- stage 6: the dispatcher's round (moved from runtime/ops.py by 44-C4b, no change of logic) ---------------------------------------


DISPATCH_BUDGET = 2700     # seconds after which a round starts no new run (the worker's limit is 240 minutes)


# A run that failed so: the next run of the round would fail the same way, so the round stops.
STOPPING_FAILURES = ("auth", "settings")


STOPPING_REASONS = ("container:", "config:")  # a LabError of these kinds, recorded as an internal failure



def _proven_on(ctx: dict, routed, task: dict, run) -> bool:
    """Whether the skill of a task is proven now on the model its run used (the proof of that model, read now); with no run
    (a review of a stand-in), on the model the task would run on."""
    try:
        return bool(routed(task["skill"], task, (run or {}).get("model")).get("proven"))
    except core.OpsError:
        return False


def _snapshot(ctx: dict, keys) -> dict:
    """What dispatcher.decide reads, from the store, the proof (proof.route through _route) and the runtime manifests:
    the tasks running (with the children started and not yet claimed), the slot holders, the ready tasks oldest first with
    the model each would run on and the code flag and footprint of their skill, the open reviews with their agent, whether
    the pair that ran is proven and whether the person's consent covers it, and mandatory flag, the tasks a child could not start lately (`refused`), the project's `max_running`, and each area
    agent's facts, a day's spend and its entry (_agents_of_the_day). A run of the router (its task is a request, so its
    agent is None) counts against the planning agent."""
    store, cfg = ctx["store"], ctx["cfg"]
    agents = cfg["area_agents"]
    tasks = ops_waits.current_tasks(ctx)  # the waits derived again first: a round decides from what is now
    by_id = {t["id"]: t for t in tasks}
    proofs = {}

    def routed(skill: str, task=None, requested=None) -> dict:
        slot = (skill, (task or {}).get("id"), requested)
        if slot not in proofs:
            proofs[slot] = ops_models.route(ctx, skill, skill_meta.declared(os.path.join(core.ROOT, "skills", skill)), keys, task, requested)
        return proofs[slot]

    cache = {}
    parallel_part = ops_runs.parallel_state(ctx, tasks, cache)
    starting = parallel_part.pop("starting")  # started and not yet claimed: counted as running, not decided again
    out = {**parallel_part,
           "ready": [{**t, "code": ops_runs.task_facts(t, cache)[1], "footprint": ops_runs.task_facts(t, cache)[0]}
                     for t in tasks if t["state"] == "ready" and t["parent_id"] is not None and t["id"] not in starting],
           "reviews": [], "agents": ops_runs._agents_of_the_day(ctx, keys), "model": {}, "billing": {},
           "max_running": cfg["max_running"], "per_run_usd": cfg["raw"].get("max_cost_usd_per_run", ops_runs.PER_RUN_USD)}
    for item in core._stored(ctx, store.pending_list):
        task = by_id.get(item["task_id"])
        if item["kind"] != "review" or task is None or not task.get("skill"):
            continue
        runs = core._stored(ctx, store.task_runs_list, task["id"])
        run = runs[-1] if runs else None  # the run that opened this review
        proven, consent = ops_models.consent_for_review(ctx, run, agents.get(task.get("agent")),
                                                        _proven_on(ctx, routed, task, run))
        out["reviews"].append({"pending": item, "task": task, "agent": task.get("agent"), "proven": proven, "consent": consent,
                               "mandatory": plan.mandatory(task["skill"], core.ROOT)})
    for task in out["ready"]:
        if task.get("agent") in agents and task.get("skill"):
            try:
                routing = routed(task["skill"], task)
            except core.OpsError as e:  # a model the gate file does not list: the task is held, the round goes on
                out.setdefault("refused", {})[task["id"]] = str(e)
                continue
            out["model"][task["id"]], out["billing"][task["id"]] = routing["model"], routing["billing"]
    out["waits"] = ops_waits.waiting_for(ctx)  # a ready task with an open wait starts nowhere (dispatcher.decide)
    ops_steps.annotate(ctx, out)  # the brake of the step tasks, and which kinds the dispatcher may start (runtime/ops_steps.py)
    return out


def _mode_releases(ctx: dict, released: list, snapshot: dict, decided: dict, skip=None) -> list:
    """Apply the releases a decision lists, each as the mode of its agent (by "mode:<mode>"), with what a release starts
    (_after_release). A review skip(task) names is left for later (poll leaves the brief's release, which runs the
    router, to dispatch). When a release by a mode completes a request, one acceptance of kind deliveries lists every
    delivery a mode released in it (part 0, F.3). Returns [{"pending_id", "task_id", "by", ...}]."""
    reviews = {r["pending"]["id"]: r for r in snapshot["reviews"]}
    agents = snapshot["agents"]
    out = []
    for pending_id in decided["release"]:
        review = reviews[pending_id]
        if skip is not None and skip(review["task"]):
            continue
        by = "mode:" + autonomy.mode_of(agents[review["agent"]]["facts"])
        done = _release(ctx, pending_id, by=by)
        out.append({"pending_id": pending_id, "task_id": review["task"]["id"], "by": by,
                    **({"after": done["after"]} if done.get("after") else {})})
        released.append(pending_id)
        for request_id in done.get("completed") or []:
            out[-1]["acceptance"] = _deliveries_acceptance(ctx, request_id)
    return out


def _deliveries_acceptance(ctx: dict, request_id: int):
    """One acceptance of kind deliveries on a request a mode completed, listing every delivery a mode released in it;
    None when no delivery of it was released by a mode."""
    store = ctx["store"]
    tasks = {t["id"]: t for t in core._stored(ctx, store.tasks_list, request_id) if t["parent_id"] is not None}
    by_mode = [p for p in core._stored(ctx, store.pending_list, "resolved")
               if p["task_id"] in tasks and p["kind"] == "review" and p["resolution"] == "released"
               and str(p.get("resolved_by") or "").startswith("mode:")]
    if not by_mode:
        return None
    lines = [f"Request {request_id} is done, and an autonomy mode released these deliveries without you. Each stays a "
             "draft: read it, then accept (a note records what you think), or reject.", ""]
    lines += [f"- task {p['task_id']} ({tasks[p['task_id']]['skill']}): {tasks[p['task_id']]['title']}, released by "
              f"{p['resolved_by']}, pending decision {p['id']}" for p in by_mode]
    return core._stored(ctx, store.acceptance_open, task_id=request_id, what="deliveries",
                   title=f"Accept the deliveries of request {request_id}", body="\n".join(lines),
                   payload={"released": [p["id"] for p in by_mode]})["pending_id"]


def _stops_the_round(ran: dict):
    """The reason a round stops after this run, or None: a failure the next run would repeat."""
    failure = ran.get("failure") or {}
    if failure.get("kind") in STOPPING_FAILURES:
        return f"a run failed ({failure['kind']}): the next run would fail the same way"
    if failure.get("kind") == "internal" and str(failure.get("reason") or "").startswith(STOPPING_REASONS):
        return f"a run could not reach the container ({failure['reason'][:200]}): the next run would fail the same way"
    return None


def _configuration_moved(ctx: dict) -> bool:
    """Whether the configuration this round loaded is no longer the file or no longer the accepted one: the file's hash
    or the accepted hash differs from the one the round started with. The round then ends, so that a narrowing accepted
    in the middle of it (the page stopped an agent) stops the next start."""
    try:
        now = core._config_of(ctx["cfg"]["project"])
    except core.OpsError:
        return True
    accepted = core._stored(ctx, ctx["store"].cursor_get, project_config.ACCEPTED)
    return now["sha256"] != ctx["cfg"]["sha256"] or accepted != ctx["cfg"]["sha256"]


def _credential_stop(model: str | None = None):
    """(reason, why, missing) no run on the model can start from this process, or None: its credential is neither set
    nor found in the secret store (lab.credential_missing). The model is the default model (the first lab model) when none
    is named. The reason is `secret store` when this interpreter cannot read the store at all (the library is missing), else
    `credential`. Named with the interpreter, since a scheduled job's interpreter may not read the store (open point O1)."""
    model = lab.resolve_model(model)
    missing = lab.credential_missing(model)
    if not missing:
        return None
    reason = "credential" if dispatcher.store_readable() == "ok" else "secret store"
    locked = secret_state.unreadable_sentence(core.ROOT, names=missing) if reason == "credential" else ""   # a locked store is not a missing key (I3)
    return reason, (f"{locked}; the credential of {model} ({', '.join(missing)}) cannot be read" if locked else
                    f"the credential of {model} ({', '.join(missing)}) is neither set nor found in the secret store") + (
                    f" from {sys.executable} (Python {sys.version.split()[0]}): no run starts. See contracts/runtime.md, "
                    "\"The dispatcher's two jobs\""), list(missing)


def _image_stop():
    """("image", why) when the eval image is not on this machine although the lab runs in a container (a run would
    fail for it), else None. A machine the lab cannot look at (no container executor, no docker) says nothing."""
    seen = lab.image()
    if seen.get("problem"):
        return "image", f"the eval image cannot be looked up ({seen['problem']}): no run starts, and no task fails for it. See connections", []
    if seen.get("name") and not seen.get("digest"):
        return "image",f"the eval image {seen['name']} is not on this machine: no run starts, and no task fails for it. See connections", []
    return None



# --- the handlers' ticks of a round ---------------------------------------------------------------------------------


def _ticks(ctx: dict, project: str) -> dict:
    """The tick of every handler whose `dispatch` is true and whose agent is enabled; a failure is recorded, never
    raised."""
    out = {}
    agents = ctx["cfg"]["area_agents"]
    for name, entry in sorted((ctx["cfg"].get("handlers") or {}).items()):
        agent = agents.get(entry.get("agent")) or {}
        if not entry.get("dispatch") or not agent.get("enabled") or agent.get("mode") == "stopped":
            continue
        try:
            out[name] = ops_facade.function("handler_call")(project, name, "tick")
        except core.OpsError as e:
            out[name] = {"error": str(e), "code": e.code}
    return out



if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
