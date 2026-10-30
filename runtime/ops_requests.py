#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The router's run on a request: the request that waits for its route, the router skill run once on it (or once on each delivery of a
request that lists several), and the pending decision that run opens (44-C3).

A sibling of runtime/ops.py, which exposes `route` (the operation) and `_reroute` (the route of a delivery after its brief, 44-C4)
under their names and calls the pieces here as `ops_requests.<name>`; no shell imports this file. The names every module of the layer
shares are read as `core.<name>` (runtime/ops_core.py). What a run takes in and gives back (`task_prompt`, `_budget`, `_note`,
`_reported_usage`, `_skill_loaded`, `_count`, `_key_in_environment`) and the use it records (`_use_start`) are read as
`ops_runs.<name>`, the routing of the run as `ops_models.route`. The conversation reaches `_route_request` at call time,
`importlib.import_module("ops_requests")` in `ops_say._drain_route`, because this file imports `ops_say` (the person's line the
router is shown, the question of a reply that names no route) and `ops_say` must not import it back.

`_route_request` holds the route lock and runs the router once (`_route_run`) or once per delivery (`_route_deliveries`); `_router_call`
is the one run: the standing instructions, the copy the router sees, the budget, the container, and the reply read by
runtime/router.py; `_checked` and `_combined` check a route against the flow files and the pack in scope and build the plan; the
decision a reply opens is a plan, a question, or the question of a reply that names no route (`_not_recognised`). The limits around
the run (L1 to L8, runtime/workcopy.py) and the approval of the plan are unchanged: the plan is a pending decision of exact content
and no task exists before the person approves it. These bodies moved from runtime/ops.py with no change of logic.

Standard library only. Runs on Python 3.9: python3 runtime/ops_requests.py --help
"""
from __future__ import annotations

import os
import shutil
import sys
import traceback

import ops_core as core
import ops_cancel
import ops_flows
import ops_instructions
import ops_language
import ops_models
import ops_runs
import ops_say
import ops_sources
import ops_waits
import flow_files
import lab
import path_rule
import plan
import router
import skill_meta
import workcopy

ROUTE_KEPT = "a route-only run returns no file"


# --- the router's run on a request (moved from runtime/ops.py by 44-C3, no change of logic) ----------------------------------------


def _routable(ctx: dict, request_id: int) -> dict:
    """The request's row, refused when it is a task or does not wait for its route."""
    request = core._stored(ctx, ctx["store"].task_get, request_id)
    if request["parent_id"] is not None:
        raise core.OpsError(f"task {request_id} is not a request: route the request it belongs to", 1)
    if request["state"] != "requested":
        raise core.OpsError(f"request {request_id} is {request['state']}: only a request that waits for its route is routed", 1)
    return request


def _route_request(ctx: dict, request_id: int) -> dict:
    """The router's run on a request, holding the route lock (RunBusy when the router answers another request): the body
    of route() without a flow, and what route_queued calls."""
    with core._route_lock(ctx["cfg"]):
        recovered = ops_runs._recover(ctx, holding_route=True)
        request = _routable(ctx, request_id)
        try:
            parts = plan.split(request["text"])
        except ValueError as e:
            raise core.OpsError(str(e), 2) from None
        if len(parts["items"]) > 1:
            return {**_route_deliveries(ctx, request, parts), "recovered": recovered["tasks"]}
        return {**_route_run(ctx, request), "recovered": recovered["tasks"]}


def _router_call(ctx: dict, request: dict, text: str, *, reroute: bool = False, said: str | None = None) -> dict:
    """One run of the router skill on a request, asked only for the route, with text as the request's words. Returns
    {"out", "failed"} and, for a run that did not fail, "response", "body", "finish" (the arguments of
    route_run_finish), "common" (the payload keys every decision of the run carries) and "read" (router.read_route).
    A failed run is finished here; a run that did not fail is finished by the caller, with its decision. `said` is the person's own line, given
    for a request of one line only: a reply that names an operation (package NR-2) is believed against it, and without it such a reply is unclassified."""
    cfg, store, skill = ctx["cfg"], ctx["store"], router.ROUTER_SKILL
    try:
        meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
        keys = core._keys()
        routing = ops_models.route(ctx, skill, meta, keys)
        if routing["key_missing"]:
            raise core.OpsError(f"no key was found for {routing['model']}: {keys[routing['model']]['reason']}", 3)
        identity = lab.skill_identity(skill)
        with core._claim_lock(cfg):  # the budget and the run row are one step: two starts cannot pass the same cap
            budget = ops_runs._budget(ctx, plan.PLANNING, routing, keys)
            run_id = core._stored(ctx, store.route_run_start, request["id"], skill=skill, model=routing["model"],
                                  adapter=routing["adapter"], skill_version=identity["version"],
                                  skill_sha256=identity["content_sha256"], web=False, reroute=reroute,
                                  billing=routing["billing"] or "unknown", autonomy=routing["autonomy"])["run_id"]
    except (skill_meta.SkillError, lab.LabError, OSError, KeyError) as e:
        raise core.OpsError(f"the router ({skill}) could not start: {e}", 1) from None
    dest = os.path.join(cfg["data_dir"], core.RUNS_DIR, str(run_id))
    out = {"routed": False, "request": request["id"], "source": "router", "run_id": run_id, "run_dir": dest,
           "status": "failed", "ending": None, "failure": None, "pending_id": None, "kind": None, "kept": [],
           "left_out": [], "entered": None, "routing": routing, "use": None}

    def fail(kind: str, reason: str, attempts: int = 0, digest=None, redactions=None, reported=None) -> dict:
        done = core._stored(ctx, store.route_run_finish, run_id, status="failed", failure=kind, attempts=attempts,
                image_digest=digest, run_dir=dest, error=ops_runs._note(reason), redactions=redactions,
                **ops_runs._reported_usage(reported, routing))
        out["failure"] = None if ops_cancel.cancelled_run(out, done) else {"kind": kind, "reason": ops_runs._note(reason)}   # a request being cancelled: cancelled (R18)
        return {"out": out, "failed": True}

    held, why = ops_instructions.for_run(cfg["project"])   # the standing instructions; a file that fails a check stops the run, before a use is recorded
    if why:
        return fail("internal", why)
    out["use"] = ops_runs._use_start(ctx, run_id, skill, routing)
    prepared_dir = os.path.join(cfg["data_dir"], core.PREPARED_DIR, str(run_id))
    try:
        try:
            entered = workcopy.entering(cfg["project"], meta, web=False, cfg=cfg, settings_names=lab.settings_names(),
                                        prepared_dir=prepared_dir)
        except workcopy.CopyError as e:
            return fail("internal", f"the copy could not be built: {e}")
        out["left_out"] = entered["left_out"]
        out["entered"] = {"kind": entered["kind"], "agents_md": entered["agents_md"], "files": len(entered["files"])}
        answered = [] if reroute else [p for p in core._stored(ctx, store.pending_list, "resolved", request["id"])
                                       if p["kind"] == "question" and p["resolution"] == "answered"]
        prompt = ops_runs.task_prompt(text, router.ROUTE_TASK_TEXT, answered, instructions=held, language_line=ops_language.router_line(cfg, request)) \
            + ops_sources.router_block(ctx, request["text"])
        # Two router runs of two projects in one service process share the lab's process-wide session (lab.session ends
        # every container of the process when it closes): the whole session is held under one guard. Task runs are
        # processes of their own and never take it.
        with core._LAB_GUARD, lab.session(), ops_runs._key_in_environment(routing, keys), ops_cancel.watch(ctx, request["id"]):
            result = lab.run_skill(skill, prompt, entered["files"], dest, web=False, model=routing["model"],
                                   max_cost=budget)
    except lab.LabError as e:
        return fail("internal", f"{e.kind}: {e.reason}", getattr(e, "attempts", 0))  # attempts: how many began (A-57)
    except Exception as e:  # the run row never stays `running`: the error is recorded, then shown
        traceback.print_exc()
        return fail("internal", f"{type(e).__name__}: {e}", getattr(e, "attempts", 0))
    finally:
        shutil.rmtree(prepared_dir, ignore_errors=True)
    counts, timing = result["counts"], result["timing"]
    if result["status"] != "ok":
        failure = result["failure"]
        return fail(failure["kind"], failure["reason"], counts["attempts"], result["image_digest"],
                    ops_runs._count(counts.get("redactions")), result.get("reported"))
    if ops_cancel.stop_requested(ctx, request["id"]):   # the request is being cancelled: its reply is not read, nothing is opened
        return fail("stopped", "cancelled while the router answered", counts["attempts"], result["image_digest"], ops_runs._count(counts.get("redactions")), lab.reported_usage(dest))
    # Nothing a route-only run left comes back: the router's run sees only the router installed, so what it would
    # write (a line about a skill it finds missing) is wrong here by construction.
    facts = {"staged": result["staged"]}
    out["kept"] = [{"path": rel, "class": path_rule.classify(rel, facts), "reason": ROUTE_KEPT}
                   for rel in sorted(result["changes"]["created"] + result["changes"]["modified"])
                   if path_rule.classify(rel, facts) != "ignored"]
    body, masked = workcopy.masked_reply(result["response"])
    body = body.encode("utf-8")[:store.BODY_MAX].decode("utf-8", errors="ignore")
    number = lambda key, kind: timing.get(key) if isinstance(timing.get(key), kind) and not isinstance(timing.get(key), bool) else None
    every = ops_runs._reported_usage(lab.reported_usage(dest), routing)  # the usage of every attempt, the retried ones too (R4-C7b)
    finish = dict(status="ok", attempts=counts["attempts"],
                  cost_usd=every.get("cost_usd", number("cost_usd", (int, float)) if routing["billing"] == "metered" else None),
                  tokens=every.get("tokens", number("total_tokens", int)), duration_ms=number("duration_ms", int),
                  skill_loaded=ops_runs._skill_loaded(timing, skill),
                  image_digest=result["image_digest"], run_dir=dest, redactions=ops_runs._count(counts.get("redactions")))
    common = {"run_dir": dest, "response_file": os.path.join(result["outputs"], "response.md"), "kept": out["kept"],
              "routing": routing, "use": out["use"], "body_masked": masked}
    return {"out": out, "failed": False, "response": result["response"], "body": body, "finish": finish,
            "common": common, "read": router.read_route(result["response"], ignore_language=bool(request.get("language")), said=said)}


def _checked(ctx: dict, read: dict) -> dict:
    """read_route() of a reply with "checked": router.check_route() against the flow files and the pack in scope."""
    return dict(read, checked=router.check_route(read, flow_files.names(core.ROOT), plan.pack_skills(ctx["cfg"], core.ROOT),
                                                 known_sources=ops_sources.known_ids(ctx)))


def _combined(ctx: dict, request: dict, routed: list) -> dict:
    """plan.combine for these routed deliveries, with the flow files they name, the agents' packs, the gate file's
    limits and the past runs of their skills. Raises plan.PlanError, ValueError, flow_files.FlowError."""
    cfg = ctx["cfg"]
    flows = {}
    for entry in routed:
        flow = ((entry.get("route") or {}).get("checked") or {}).get("flow")
        if flow and flow not in flows:
            flows[flow] = flow_files.load(flow, core.ROOT)
    reference = lab.reference()
    limits = {"max_running": cfg["max_running"], "timeout_seconds": reference["timeout_seconds"],
              "retries": reference["retries"]}
    skills = plan.agent_skills(cfg, core.ROOT)
    pack = plan.pack_skills(cfg, core.ROOT)
    forced = ops_sources.forced_for(ctx, request["text"])  # the sources an @mention names are in the plan whatever the router chose
    mine = ops_language.project_of(cfg)
    out = plan.combine(request, routed, flows, skills, core.ROOT, pack=pack, limits=limits, past=[], forced=forced, project_language=mine)
    ops_flows.vet(ctx, out["tasks"])
    past = []
    for skill in dict.fromkeys(t["skill"] for t in out["tasks"] if t.get("skill")):
        past += core._stored(ctx, ctx["store"].task_runs_of_skill, skill)
    return plan.combine(request, routed, flows, skills, core.ROOT, pack=pack, limits=limits, past=past, forced=forced,
                        project_language=mine) if past else out


def _route_run(ctx: dict, request: dict) -> dict:
    """One run of the router on a request of one delivery (stage 3's behaviour): a valid route becomes a plan (through
    plan.combine), a reply that asks a question, anything else a question that names the flow command."""
    store = ctx["store"]
    call = _router_call(ctx, request, request["text"], said=ops_say.person_line(request["text"]))
    out = call["out"]
    if call["failed"]:
        return out
    read, body, finish, common = call["read"], call["body"], call["finish"], call["common"]
    why = read.get("why")
    if read["kind"] == "route":
        decision = None
        try:
            route_read = _checked(ctx, read)
            if route_read["checked"]["ok"]:
                combined = _combined(ctx, request, [{"item": request["text"], "route": route_read, "reply": body}])
                if combined["plan"] is not None:
                    decision = ops_waits.annotate(ctx, request, {"kind": "plan", **combined["plan"]})
                else:  # the route was valid and the plan was not: the one delivery was left out (plan.combine says why)
                    why = combined["unrouted"][0]["why"] if combined["unrouted"] else why
            else:
                why = route_read["checked"]["why"]
        except (flow_files.FlowError, plan.PlanError, ValueError) as e:
            decision, why = None, f"no plan can be built from the route: {e}"
        if decision is not None:
            decision["payload"] = {**decision["payload"], **common}
            done = core._stored(ctx, store.route_run_finish, out["run_id"], ending="done", pending=decision, **finish)
            out.update(status="ok", ending="done", routed=True, kind="plan", pending_id=done["pending_id"])
            return out
    if read["kind"] == "direct":  # a direct turn: nothing to plan and nothing to ask; the conversation answers it
        core._stored(ctx, store.route_run_finish, out["run_id"], ending="done", **finish)
        out.update(status="ok", ending="done", routed=False, kind="direct", next=read["next"])
        return out
    if read["kind"] == "operation":   # an operation of the table of natural requests (package NR-2): nothing to plan and nothing to ask; the conversation executes it by code
        core._stored(ctx, store.route_run_finish, out["run_id"], ending="done", **finish)
        out.update(status="ok", ending="done", routed=False, kind="operation", operation={k: read[k] for k in ("name", "args", "when")})
        return out
    if read["kind"] == "question":
        decision = {"kind": "question", "title": "The router asks", "body": body,
                    "payload": {"ending": "question", **common}}
        ending = "question"
    else:
        decision = _not_recognised(store, request, body, why, common)
        ending = "unclassified"
    done = core._stored(ctx, store.route_run_finish, out["run_id"], ending=ending, pending=decision, **finish)
    out.update(status="ok", ending=ending, kind="question", pending_id=done["pending_id"])
    return out


def _not_recognised(store, request: dict, body: str, why, common: dict) -> dict:
    """The question of a reply that names no route: its body is one sentence, and the reply whole is in the payload
    (`raw`) with the two actions the page offers (`actions`: choose a flow, cancel the request)."""
    raw = body.encode("utf-8")[:ops_say.RAW_MAX].decode("utf-8", errors="ignore")
    return {"kind": "question", "title": "The route was not recognised",
            "body": ops_say.NOT_NAMED.format(request=request["id"]),      # stored in English; a card and the conversation say it in the language (phrases.body)
            "payload": {"ending": "unclassified", "why": why, "raw": raw, "actions": list(ops_say.NOT_NAMED_ACTIONS), **common}}


def _item_text(preamble: str, item: str) -> str:
    return f"{preamble}\n\n{item}" if preamble else item


def _route_deliveries(ctx: dict, request: dict, parts: dict) -> dict:
    """A request that lists several deliveries (decision P3): one router run per item, each with the text
    "<preamble>\n\n<item>"; then one plan of every routed delivery, a delivery starting after an earlier one only when it reads what that one writes (plan.combine),
    opened with the last run. An item whose reply asks, names no valid route or cannot be planned goes to the plan's
    "unrouted" with the whole reply. When no item was routed, the last run opens one question with every reply."""
    store = ctx["store"]
    routed, runs, last = [], [], None
    items = parts["items"]
    for k, item in enumerate(items, 1):
        call = _router_call(ctx, request, _item_text(parts["preamble"], item))
        if call["failed"]:
            return {**call["out"], "deliveries": len(items), "runs": runs + [call["out"]["run_id"]]}
        read = call["read"]
        entry = {"item": item, "route": None, "reply": call["body"]}
        if read["kind"] == "route":
            entry["route"] = _checked(ctx, read)
            ending = "done" if entry["route"]["checked"]["ok"] else "unclassified"
        else:
            entry["route"] = None if read["kind"] == "question" else read
            ending = "question" if read["kind"] == "question" else "unclassified"
        routed.append(entry)
        runs.append(call["out"]["run_id"])
        if k < len(items):
            core._stored(ctx, store.route_run_finish, call["out"]["run_id"], ending=ending, **call["finish"])
        else:
            last = (call, ending)
    call, ending = last
    out = call["out"]
    try:
        combined = _combined(ctx, request, routed)
        why = None
    except (flow_files.FlowError, plan.PlanError, ValueError) as e:
        combined, why = None, f"no plan can be built from the routes: {e}"
    if combined is not None and combined["plan"] is not None:
        decision = ops_waits.annotate(ctx, request, {"kind": "plan", **combined["plan"]})
        decision["payload"] = {**decision["payload"], **call["common"], "router_runs": runs}
        kind = "plan"
    else:
        replies = "\n\n".join(f"--- delivery {n}: {e['item']} ---\n{e['reply'].rstrip()}" for n, e in enumerate(routed, 1))
        decision = _not_recognised(store, request, (why or "No delivery of the request was routed.") + "\n\n" + replies,
                                   why or "no delivery was routed", {**call["common"], "router_runs": runs})
        decision["title"] = "No delivery was routed"
        kind = "question"
    done = core._stored(ctx, store.route_run_finish, out["run_id"], ending=ending, pending=decision, **call["finish"])
    out.update(status="ok", ending=ending, routed=kind == "plan", kind=kind, pending_id=done["pending_id"],
               deliveries=len(items), runs=runs,
               unrouted=len(combined["unrouted"]) if combined is not None else len(items))
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
