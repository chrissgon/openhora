#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The derived waits in the operations layer: which task waits for which, worked out from the artifact contract.

A person adds requests in any order, on the page, in the terminal or on the task board. This part of the layer knows
what each task needs (the inputs its skill declares) and what each open task will write (the outputs of its skill),
and makes a task wait for the open task of another request that writes an input the project does not have yet
(runtime/plan.py, derive, is the pure rule). The wait is stored with its reason (the store's task_waits); a task with
an open wait stays `planned`, and the store gives it out to no one (providers/store/sqlite.py). The person's
override, "after request #n", is a request's own field and becomes the same kind of wait; "go ahead" on a plan's
task drops its derived waits and is recorded in the state file as the person's decision.

Functions (each takes the project's context, ops_core.context):
  rederive(ctx)                           recompute the waits of every task not yet started and bring the store to
                                          them; a request that is the only open one, with no override, has none to
                                          compute and costs no read of the skills
  for_plan(ctx, tasks, after, go_ahead, request)   the waits the tasks of a plan not created yet begin with (request:
                                          the request they join, when it exists): {"store": [the waits as request_add,
                                          plan_approve and tasks_add take them], "shown": [...], "missing", "cycles"}
  for_task(ctx, task_id)                  the waits a failed or blocked task begins with when it is retried, as
                                          task_retry takes them
  annotate(ctx, request, decision)        a plan decision with `waits`, `missing` and `cycles` in its payload and their
                                          lines in its body, before the person approves it
  approve_plan(ctx, item, go_ahead)       plan_approve with the waits and the go-ahead in the same transaction, the
                                          decision written to the state file, and the other tasks derived again
  go_ahead(ctx, task_id)                  the person's go-ahead on a task already created: its derived waits end, the
                                          decision is written to the state file; its new waiting_for
  waiting_for(ctx)                        {task id: [{"task_id", "request_id", "reason"}]}, the open waits, for `status`,
                                          `task` and the dispatcher's snapshot
  in_status(ctx, requests, rows)          the requests of `status` with `after` and each task's waiting_for
  task_row(ctx, row)                      a task row of `task`: `after` for after_request, and its waiting_for
  current_tasks(ctx)                      derive again, then the store's tasks: what a dispatcher round reads
  settled(ctx, out)                       derive again, return out: the hook of the operations that end a task
  retry(ctx, task_id)                     task_retry with the waits the task begins with, then derived again
  request_flow(ctx, tasks, after, **f)    request_add of a flow's plan with its waits: the result with `waits`, `missing`
  accept(ctx, item)                       acceptance_resolve `accepted`, the sub-tasks with their waits
  add_subtasks(ctx, request_id, tasks)    tasks_add with the waits the sub-tasks begin with
  explain(ctx, task_id, reason)           the reason a claim ran nothing, with who waits and why

It reaches no operation of ops.py. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402  (the table: the channel policy, operations.permitted)
import ops_core as core  # noqa: E402  (the shared names: read as core.<name>, never bound at import)
import ops_flows  # noqa: E402  (a file a plan names reaches the task that reads it)
import path_rule  # noqa: E402
import plan  # noqa: E402
import state_merge  # noqa: E402
import steps  # noqa: E402  (a plan that holds a step of a networked kind: networked_steps)

FINAL = ("done", "cancelled")
LIVE = ("planned", "ready")      # the states in which a task has not started and may still wait
MESSAGING = "messaging"          # the channel of the messaging bridge (runtime/messaging.py)
NEW = "new"                      # the request name of a plan that is not created yet


def _exists(project: str):
    """exists(path) for plan.derive: whether the project has the file. A declared path with placeholders is a pattern
    (each placeholder one path segment); a path that ends in "/" is a folder with a file in it. A path that leaves the
    project is a file the project does not have."""
    def has(path: str) -> bool:
        parts = path.split("/")
        if path.startswith("/") or "\\" in path or ".." in parts:
            return False
        full = os.path.join(project, *[p for p in parts if p])
        if "<" in path:
            found = glob.glob(os.path.join(glob.escape(project), *[plan.PLACEHOLDER.sub("*", p) for p in parts if p]))
            return any(os.path.isfile(f) or (path.endswith("/") and os.path.isdir(f)) for f in found)
        if path.endswith("/"):
            return os.path.isdir(full) and any(files for _root, _dirs, files in os.walk(full))
        return os.path.isfile(full)
    return has


def _graph(rows: list) -> tuple:
    """(nodes, open requests, after_of) of the store's task rows: every task that is not final, the requests that are not
    done or cancelled, and each request's `after_request`."""
    nodes = [{"ref": t["id"], "request": t["parent_id"], "skill": t.get("skill"), "candidate": t["state"] in LIVE,
              "depends_on": list(t.get("depends_on") or [])}
             for t in rows if t["parent_id"] is not None and t["state"] not in FINAL]
    requests = [t for t in rows if t["parent_id"] is None]
    return (nodes, {t["id"] for t in requests if t["state"] not in FINAL},
            {t["id"]: t["after_request"] for t in requests if t.get("after_request")})


def rederive(ctx: dict) -> dict:
    """Recompute the waits of every planned or ready task from the open tasks of the project, the files it has and the
    requests' `after`, and bring the store to them (store.waits_sync); a task that gained a wait goes back to `planned`,
    one whose waits all ended becomes ready. Returns what the store changed ({} when there was nothing to derive)."""
    store = ctx["store"]
    rows = core._stored(ctx, store.tasks_list)
    live = [t["id"] for t in rows if t["parent_id"] is not None and t["state"] in LIVE]
    if not live:
        return {}
    waits = core._stored(ctx, store.waits_list, status="all")
    nodes, open_requests, after_of = _graph(rows)
    if len({n["request"] for n in nodes}) < 2 and not after_of and not any(w["status"] == "open" for w in waits):
        return {}  # one request alone: nothing it reads is written by another request's task
    got = plan.derive(nodes, plan.skill_facts(core.ROOT), _exists(ctx["cfg"]["project"]), after_of=after_of,
                      open_requests=open_requests)
    desired = [{"task_id": w["ref"], "awaited_id": w["awaited"], "kind": w["kind"], "path": w["path"],
                "reason": w["reason"]} for w in got["waits"]]
    return core._stored(ctx, store.waits_sync, desired, live)


def for_plan(ctx: dict, tasks: list, after, go_ahead=(), request=None) -> dict:
    """The waits the tasks of a plan begin with, derived against the open tasks of the project before the plan's tasks
    exist. tasks are the plan's tasks ({"key", "title", "skill", "depends_on"}); after is the request the plan's
    request is to run after, or None; go_ahead the keys the person told to go ahead (their waits are still derived:
    the store records them as dropped, and the state file says what they would have waited for).
    Returns {"store": [{"key", "kind", "awaited_id", "path", "reason"}], "shown": [{"task_key", "task_id", "reason"}],
    "missing": [{"task_key", "skill", "path", "owner", "sentence"}], "cycles": [{"task_key", "sentence"}]}."""
    store = ctx["store"]
    rows = core._stored(ctx, store.tasks_list)
    nodes, open_requests, after_of = _graph(rows)
    held = core._stored(ctx, store.waits_list)
    fixed = {}
    for w in held:
        theirs = [n["ref"] for n in nodes if n["request"] == w["awaited_id"]] if w["kind"] == "after" else [w["awaited_id"]]
        fixed.setdefault(w["task_id"], set()).update(theirs)
    ref = lambda key: (NEW, key)
    joins = NEW if request is None else request  # a new request, or the one whose tasks these join
    nodes += [{"ref": ref(t["key"]), "request": joins, "skill": t.get("skill"), "candidate": True,
               "depends_on": [ref(d) for d in t.get("depends_on") or []]} for t in tasks]
    if after and request is None:
        after_of[NEW] = after
    got = plan.derive(nodes, plan.skill_facts(core.ROOT), _exists(ctx["cfg"]["project"]), after_of=after_of,
                      open_requests=open_requests, only={ref(t["key"]) for t in tasks}, fixed=fixed)
    return {"store": [{"key": w["ref"][1], "kind": w["kind"], "awaited_id": w["awaited"], "path": w["path"],
                       "reason": w["reason"]} for w in got["waits"]],
            "shown": [{"task_key": w["ref"][1], "task_id": w["awaited"] if w["kind"] == plan.WAIT_INPUT else None,
                       "reason": w["reason"]} for w in got["waits"]],
            "missing": [{"task_key": m["ref"][1], **{k: m[k] for k in ("skill", "path", "owner", "sentence")}}
                        for m in got["missing"]],
            "cycles": [{"task_key": c["ref"][1], "sentence": c["sentence"]} for c in got["cycles"]]}


def annotate(ctx: dict, request: dict, decision: dict) -> dict:
    """A plan decision (plan.build's {"kind", "title", "body", "payload"}) with `waits`, `missing` and `cycles` in its
    payload, and their lines in its body above the plan hash. The plan hash covers the tasks only: it does not move."""
    tasks = decision["payload"].get("tasks") or []
    got = for_plan(ctx, tasks, request.get("after_request"))
    keyed = {t["key"]: t["title"] for t in tasks}
    lines = plan.wait_lines([dict(w, ref=w["task_key"]) for w in got["shown"]],
                            [dict(m, ref=m["task_key"]) for m in got["missing"]],
                            [dict(c, ref=c["task_key"]) for c in got["cycles"]], keyed)
    body = decision["body"].split("\n")
    at = next((i for i, line in enumerate(body) if line.startswith("Plan hash: ")), len(body))
    return {**decision, "body": "\n".join(body[:at] + lines + body[at:]),
            "payload": {**decision["payload"], "waits": got["shown"], "missing": got["missing"],
                        "cycles": got["cycles"]}}


def approve_plan(ctx: dict, item: dict, go_ahead) -> dict:
    """Approve a plan decision: its tasks are created with the waits derived for them (and the go-ahead of the keys the
    person named, in the same transaction, so no task is ever ready for a moment before its wait exists), the go-ahead is
    written to the state file as the person's decision, and the waits of the other tasks are derived again (a task
    already there may now wait for one of the new ones). Returns plan_approve's result with "waits" (the shown ones) and,
    for a go-ahead, "state"."""
    store = ctx["store"]
    payload = item.get("payload") or {}
    request = core._stored(ctx, store.task_get, item["task_id"])
    keys = _keys(go_ahead, [t["key"] for t in payload.get("tasks") or []])
    got = for_plan(ctx, payload.get("tasks") or [], request.get("after_request"), keys)
    idle = [k for k in keys if not any(w["key"] == k and w["kind"] == plan.WAIT_INPUT for w in got["store"])]
    if idle:
        raise core.OpsError(f"go ahead names {', '.join(idle)}, which waits for no task to derive: nothing was approved", 2)
    ops_flows.before_approve(ctx, item)    # a file the plan names must be there with the plan's hash, before anything is approved
    done = core._stored(ctx, store.plan_approve, item["id"], by="user", waits=got["store"], go_ahead=keys)
    out = {**done, "waits": got["shown"]}
    placed = ops_flows.after_approve(ctx, item, done)    # and then it goes to the drop of the task that reads it
    if placed:
        out["files"] = placed
    if keys:
        out["state"] = _record_go_ahead(ctx, done["tasks"], keys, got["shown"], payload.get("tasks") or [])
    rederive(ctx)
    return out


def for_task(ctx: dict, task_id: int) -> list:
    """The waits a failed or blocked task begins with when it is retried (task_retry): derived as for a planned task, and
    without the waits the person already dropped for the same awaited task and path. [] when it waits for nothing."""
    store = ctx["store"]
    rows = core._stored(ctx, store.tasks_list)
    nodes, open_requests, after_of = _graph(rows)
    task = next(t for t in rows if t["id"] == task_id)
    nodes = [dict(n, candidate=True) if n["ref"] == task_id else n for n in nodes]
    if not any(n["ref"] == task_id for n in nodes):
        nodes.append({"ref": task_id, "request": task["parent_id"], "skill": task.get("skill"), "candidate": True,
                      "depends_on": list(task.get("depends_on") or [])})
    got = plan.derive(nodes, plan.skill_facts(core.ROOT), _exists(ctx["cfg"]["project"]), after_of=after_of,
                      open_requests=open_requests, only={task_id})
    dropped = {(w["awaited_id"], w["kind"], w["path"]) for w in core._stored(ctx, store.waits_list, task_id=task_id,
                                                                            status="dropped")}
    return [{"kind": w["kind"], "awaited_id": w["awaited"], "path": w["path"], "reason": w["reason"]}
            for w in got["waits"] if (w["awaited"], w["kind"], w["path"]) not in dropped]


def _keys(go_ahead, known: list) -> list:
    """The task keys the person named, as a list: a list, or the comma-separated text a shell carries. A key the plan
    does not have is a refusal that names the keys it has."""
    if go_ahead is None:
        return []
    named = [k.strip() for k in (go_ahead.split(",") if isinstance(go_ahead, str) else go_ahead) if str(k).strip()]
    unknown = [k for k in named if k not in known]
    if unknown:
        raise core.OpsError(f"go ahead names {', '.join(unknown)}, which the plan does not have; its tasks are "
                            f"{', '.join(known)}", 2)
    return list(dict.fromkeys(named))


def _record_go_ahead(ctx: dict, created: list, keys: list, shown: list, tasks: list) -> dict:
    """The decision of a plan's go-ahead: one line for each task the person went ahead on, with what it did not wait for."""
    ids = {t["key"]: t["id"] for t in created}
    skills = {t["key"]: t.get("skill") or "step-" + t["step"] for t in tasks}
    return _record_decision(ctx, [(skills[k], ids[k], [w["reason"] for w in shown if w["task_key"] == k]) for k in keys])


def _record_decision(ctx: dict, decisions: list) -> dict:
    """One line of the state file's ## Decisions for each (skill, task id, reasons), written by code
    (state_merge.with_go_ahead): what the task did not wait for. {"written": True}, or {"written": False, "reason"}."""
    target = os.path.join(ctx["cfg"]["project"], *path_rule.STATE.split("/"))
    with core._write_lock(ctx["cfg"]):
        try:
            with open(target, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return {"written": False, "reason": "the project has no state file"}
        if os.path.islink(target):
            return {"written": False, "reason": "the state file is a link"}
        today = datetime.date.today().isoformat()
        try:
            for skill, task_id, reasons in decisions:
                text = state_merge.with_go_ahead(text, date=today, skill=skill, task_id=task_id, waited=reasons)
        except state_merge.Conflict as e:
            return {"written": False, "reason": str(e)}
        temporary = f"{target}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, target)
        return {"written": True}


def go_ahead(ctx: dict, task_id: int, drop_after: bool = False) -> dict:
    """The person's go-ahead on a task that is already created and waits (the store's waits_go_ahead): its derived waits
    end, and the runtime derives those very waits no more (a new writer or another path is another wait); with
    drop_after the task's `after` wait ends instead, the override being the person's own. The decision is one line of
    the state file's ## Decisions (state_merge.with_go_ahead, as the plan's go-ahead writes it). Returns {"task_id",
    "state", "dropped": [the reasons], "waiting_for": [what still holds it], "decision": {"written", ...}}."""
    store = ctx["store"]
    done = core._stored(ctx, store.waits_go_ahead, task_id, by="user", after=bool(drop_after))
    task = core._stored(ctx, store.task_get, task_id)
    return {"task_id": task_id, "state": done["state"], "dropped": done["reasons"],
            "waiting_for": waiting_for(ctx).get(task_id, []),
            "decision": _record_decision(ctx, [(task["skill"] or "step-" + task["step_kind"], task_id, done["reasons"])])}


def task_row(ctx: dict, row: dict) -> dict:
    """The store's task row as `task` shows it: `after` for the raw column, and waiting_for."""
    return {**{k: v for k, v in row.items() if k != "after_request"}, "after": row["after_request"],
            "waiting_for": waiting_for(ctx).get(row["id"], [])}


def in_status(ctx: dict, requests: list, rows: list) -> list:
    """The requests of `status` with `after` (the request each runs after, or None) and, on each task, `waiting_for`."""
    waiting, after = waiting_for(ctx), {r["id"]: r.get("after_request") for r in rows}
    return [{**r, "after": after.get(r["id"]),
             "tasks": [{**t, "waiting_for": waiting.get(t["id"], [])} for t in r["tasks"]]} for r in requests]


def current_tasks(ctx: dict) -> list:
    """Every task of the store, after the waits were derived again: what a round of the dispatcher decides from."""
    rederive(ctx)
    return core._stored(ctx, ctx["store"].tasks_list)


def networked_steps(item: dict) -> list:
    """[(task key, kind)] of the step tasks of a plan decision whose kind reaches the network (steps.Kind.networked), or whose kind this
    checkout does not have (it cannot be shown not to reach the network, so it counts). A script with declared destinations can send a
    write to them, which is an external effect that the effect gate does not see: by default such a plan is approved by a person at the
    terminal or on the page (operations.NETWORKED_PLAN_CHANNELS, limit L36)."""
    found = []
    for t in (item.get("payload") or {}).get("tasks") or []:
        if isinstance(t, dict) and t.get("step"):
            try:
                reaches = steps.kind_of(t["step"]).networked
            except steps.StepFailure:
                reaches = True
            if reaches:
                found.append((t.get("key"), t["step"]))
    return found


def only_on_plans(item: dict, go_ahead, sha256=None, channel=None, policy=None) -> None:
    """What approve checks of the decision before anything else. A go-ahead is said on the tasks of a plan: any other
    pending decision is refused. The channel's policy (operations.refusal, decisions M-8 and M-13) must cover the approval
    of the decision's kind, and, with task keys, the group `go-ahead` too. An effect is checked against the policy only
    for a channel that may approve one at all (operations.EFFECT_CHANNELS: the page); for any other channel the rule of
    ops.approve speaks. The policy is never the only guard of an effect. A plan approved from a messaging app carries
    its hash: the tap or the typed command names exactly what the person saw (an acceptance has none; the bridge binds
    it to the card, runtime/messaging.py)."""
    if go_ahead and item["kind"] != "plan":
        raise core.OpsError(f"pending decision {item['id']} is a {item['kind']}: go ahead is said on the tasks of a plan", 2)
    if item["kind"] == "plan" and channel not in operations.NETWORKED_PLAN_CHANNELS and networked_steps(item):   # by default; fails closed: no channel is none
        key, kind = networked_steps(item)[0]
        raise core.OpsError(f"the plan holds the task {key}, a {kind} step that reaches the network: a plan with one is approved in the "
                            "terminal or on the page by default, never from a conversation, a messaging app or the MCP mode (limit L36). Nothing was approved", 1)
    if channel and (item["kind"] != "effect" or channel in operations.EFFECT_CHANNELS):
        refused = operations.refusal("approve", channel, policy, item["kind"], bool(go_ahead))
        if refused:
            raise core.OpsError(refused, 1)
    if channel == MESSAGING and item["kind"] == "plan" and sha256 is None:
        raise core.OpsError("a plan is approved from a messaging app only with its hash: send /approve "
                            f"{item['id']} <hash>, or tap the button of its card", 1)


def settled(ctx: dict, out):
    """Derive the waits again after an operation that ended a task or a request, and return what it returned."""
    rederive(ctx)
    return out


def retry(ctx: dict, task_id: int) -> dict:
    """task_retry for a failed or blocked task with the waits it begins with (for_task), in the same transaction."""
    task = core._stored(ctx, ctx["store"].task_get, task_id)
    waits = for_task(ctx, task_id) if task["state"] in ("failed", "blocked") else []
    return settled(ctx, core._stored(ctx, ctx["store"].task_retry, task_id, waits=waits))


def request_flow(ctx: dict, tasks: list, after, **fields) -> dict:
    """request_add of a flow's plan, with the waits its tasks begin with (for_plan): the store's result with `waits` and
    `missing` (the shown ones), derived again afterwards."""
    derived = for_plan(ctx, tasks, after)
    out = core._stored(ctx, ctx["store"].request_add, tasks=tasks, after=after, waits=derived["store"], **fields)
    rederive(ctx)
    return {**out, "waits": derived["shown"], "missing": derived["missing"]}


def accept(ctx: dict, item: dict) -> dict:
    """acceptance_resolve `accepted` for the person: the accepted sub-tasks begin with their waits, then derived again."""
    payload = item.get("payload") or {}
    waits = for_plan(ctx, payload.get("tasks") or [], None, request=item["task_id"])["store"] \
        if payload.get("what") == "subtasks" else None
    return settled(ctx, core._stored(ctx, ctx["store"].acceptance_resolve, item["id"], resolution="accepted", by="user",
                                     waits=waits))


def add_subtasks(ctx: dict, request_id: int, tasks: list) -> dict:
    """tasks_add of the sub-tasks of a request with the waits they begin with."""
    return core._stored(ctx, ctx["store"].tasks_add, request_id, tasks,
                        waits=for_plan(ctx, tasks, None, request=request_id)["store"])


def explain(ctx: dict, task_id, reason: str) -> str:
    """Why a claim ran nothing, said with the waits: for a named task that waits, its reasons; for a claim of the next
    task with nothing ready, the tasks that wait and for what."""
    held = waiting_for(ctx)
    if task_id is not None and held.get(task_id):
        return f"task {task_id} is waiting: " + "; ".join(w["reason"] for w in held[task_id])
    if task_id is None and held:
        return reason + "; waiting: " + "; ".join(f"task {t} for {', '.join(w['reason'] for w in ws)}"
                                                  for t, ws in sorted(held.items()))[:600]
    return reason


def waiting_for(ctx: dict) -> dict:
    """{task id: [{"task_id", "request_id", "reason"}]} of the open waits: task_id is the awaited task (None for an
    "after request #n" wait, which awaits a request), request_id the awaited request."""
    out = {}
    for w in core._stored(ctx, ctx["store"].waits_list):
        out.setdefault(w["task_id"], []).append(
            {"task_id": w["awaited_id"] if w["kind"] == plan.WAIT_INPUT else None, "request_id": w["request_id"],
             "reason": w["reason"]})
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
