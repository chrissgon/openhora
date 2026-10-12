#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Progress and the summary of a period, computed from the store's records: no model writes them.

Pure functions: no store, no file and no clock of their own. The caller (runtime/ops.py, operation `progress`)
reads the rows with the store's functions and passes them, with `now`, as plain dictionaries.

  window(since, now)                         the period (start, end) as UTC datetimes: None is the last 7 days,
                                             "<n>d" the last n days (1 to 365), "YYYY-MM-DD" from that day 00:00 UTC
                                             to now; anything else raises ValueError naming the three forms
  progress(requests, tasks, pending, now)    where the work stands: each request that is not done or cancelled,
                                             with its tasks counted by state and the ids of its ready tasks; what
                                             waits for the person, oldest first, with its age in whole hours; what
                                             is stuck (failed or blocked tasks)
  summary(tasks, runs, pending, effects, start, end)   what happened in the period: deliveries, runs by status,
                                             model and failure, the known cost and the runs without one, the
                                             decisions, the effects executed
  render(progress, summary)                  plain text, one fact per line, in a fixed order; an empty list prints
                                             `none`

A row belongs to the period by its own time: a run by `ended_at`, a resolved pending decision by `resolved_at`, an
executed effect by `executed_at`. A row without that time is not counted; it is added to "undated". A run whose
cost is unknown is counted under "runs_without_cost", never as 0. A release whose `resolved_by` starts with `mode:`
was made by an agent's autonomy mode, and is counted apart from a release by the person.

Usage (a library; the shell is runtime/cli.py, verb progress): python3 runtime/progress.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import re
import sys

DEFAULT_DAYS = 7
MAX_DAYS = 365
FORMS = 'nothing (the last 7 days), "<n>d" with n from 1 to 365 (the last n days), or a date YYYY-MM-DD (from that day)'
DAYS = re.compile(r"([0-9]{1,3})d")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
OPEN_STATES = ("done", "cancelled")  # a request in one of these is not in progress
COUNTED = ("done", "running", "waiting", "blocked", "failed")
MODE_PREFIX = "mode:"  # resolved_by of a release made by an autonomy mode (the dispatcher's poll)


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        raise ValueError("now must carry a time zone")
    return value.astimezone(datetime.timezone.utc)


def _time(text):
    """A stored time (ISO-8601, `Z` or an offset) as a UTC datetime, or None."""
    if not text:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(datetime.timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def window(since, now: datetime.datetime) -> tuple:
    """The period (start, end) as UTC datetimes; end is now."""
    end = _utc(now)
    if since is None:
        return end - datetime.timedelta(days=DEFAULT_DAYS), end
    text = str(since).strip()
    days = DAYS.fullmatch(text)
    if days and 1 <= int(days.group(1)) <= MAX_DAYS:
        return end - datetime.timedelta(days=int(days.group(1))), end
    if DATE.fullmatch(text):
        try:
            day = datetime.datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            day = None
        if day is not None:
            return day.replace(tzinfo=datetime.timezone.utc), end
    raise ValueError(f"the period {since!r} is not one of the three forms: {FORMS}")


def progress(requests, tasks, pending, now: datetime.datetime) -> dict:
    """{"requests": [{"id", "title", "state", "total", "done", "running", "waiting", "blocked", "failed", "next"}],
    "waiting_for_you": [{"pending_id", "kind", "task_id", "title", "age_hours"}], "stuck": [{"task_id", "state",
    "note"}]}. requests are the rows with no parent; tasks every task row; pending the pending decisions (only the
    open ones are listed)."""
    now = _utc(now)
    out = []
    for request in sorted(requests, key=lambda r: r["id"]):
        if request["state"] in OPEN_STATES:
            continue
        mine = sorted((t for t in tasks if t.get("parent_id") == request["id"]), key=lambda t: t["id"])
        entry = {"id": request["id"], "title": request["title"], "state": request["state"], "total": len(mine)}
        for state in COUNTED:
            entry[state] = sum(1 for t in mine if t["state"] == state)
        entry["next"] = [t["id"] for t in mine if t["state"] == "ready"]
        out.append(entry)
    waiting = []
    for item in sorted((p for p in pending if p.get("status", "open") == "open"), key=lambda p: (p.get("created_at") or "", p["id"])):
        created = _time(item.get("created_at"))
        age = None if created is None else max(0, int((now - created).total_seconds() // 3600))
        waiting.append({"pending_id": item["id"], "kind": item["kind"], "task_id": item["task_id"],
                        "title": item["title"], "age_hours": age})
    stuck = [{"task_id": t["id"], "state": t["state"], "note": t.get("note")}
             for t in sorted(tasks, key=lambda t: t["id"]) if t["state"] in ("failed", "blocked")]
    return {"requests": out, "waiting_for_you": waiting, "stuck": stuck}


def _inside(text, start, end) -> bool:
    moment = _time(text)
    return moment is not None and start <= moment <= end


def summary(tasks, runs, pending, effects, start: datetime.datetime, end: datetime.datetime) -> dict:
    """What happened between start and end. runs are task_runs rows; pending the pending decisions (only the
    resolved ones count); effects the executed approvals (or any row with `executed_at`)."""
    start, end = _utc(start), _utc(end)
    by_id = {t["id"]: t for t in tasks}
    undated = 0
    ended = []
    for run in runs:
        if not run.get("ended_at"):
            undated += 1
        elif _inside(run["ended_at"], start, end):
            ended.append(run)
    resolved = []
    for item in pending:
        if item.get("status") != "resolved":
            continue
        if not item.get("resolved_at"):
            undated += 1
        elif _inside(item["resolved_at"], start, end):
            resolved.append(item)
    executed = 0
    for effect in effects:
        if not effect.get("executed_at"):
            undated += 1
        elif _inside(effect["executed_at"], start, end):
            executed += 1
    deliveries = []
    for item in sorted(resolved, key=lambda p: (p["resolved_at"], p["id"])):
        if (item["kind"], item.get("resolution")) not in (("review", "released"), ("effect", "approved")):
            continue
        task = by_id.get(item["task_id"], {})
        deliveries.append({"task_id": item["task_id"], "title": task.get("title"), "skill": task.get("skill"),
                           "released_by": item.get("resolved_by")})
    by_model, by_failure = {}, {}
    for run in ended:
        by_model[run["model"]] = by_model.get(run["model"], 0) + 1
        if run.get("status") == "failed":
            kind = run.get("failure") or "unknown"
            by_failure[kind] = by_failure.get(kind, 0) + 1
    known = [run["cost_usd"] for run in ended if run.get("cost_usd") is not None]
    released = [p for p in resolved if p.get("resolution") == "released"]
    by_mode = sum(1 for p in released if str(p.get("resolved_by") or "").startswith(MODE_PREFIX))
    words = lambda *names: sum(1 for p in resolved if p.get("resolution") in names)
    return {"from": start.strftime("%Y-%m-%d"), "to": end.strftime("%Y-%m-%d"),
            "tasks_done": len({d["task_id"] for d in deliveries}), "deliveries": deliveries,
            "runs": {"total": len(ended), "ok": sum(1 for r in ended if r.get("status") == "ok"),
                     "failed": sum(1 for r in ended if r.get("status") == "failed"),
                     "by_model": by_model, "by_failure": by_failure},
            "cost_usd": {"known": round(sum(known), 6), "runs_without_cost": len(ended) - len(known)},
            "decisions": {"answered": words("answered"), "released_by_you": len(released) - by_mode,
                          "released_by_mode": by_mode, "approved": words("approved", "accepted"),
                          "rejected": words("rejected")},
            "effects_executed": executed, "undated": undated}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def render(progress_out: dict, summary_out: dict) -> str:
    """Plain text: one line per request, then what waits for the person, what is stuck, the period and the decisions.
    Every number in it is a value of the two objects, or an id."""
    lines = []
    if not progress_out["requests"]:
        lines.append("Requests: none")
    for r in progress_out["requests"]:
        upcoming = ", ".join(str(i) for i in r["next"]) or "none"
        lines.append(f'Request {r["id"]} "{r["title"]}": {r["state"]}, {r["done"]} of {r["total"]} done, '
                     f'{r["waiting"]} waiting for you, next: {upcoming}')
    waiting = [f'#{w["pending_id"]} {w["kind"]} "{w["title"]}" (task {w["task_id"]}), '
               f'{"unknown" if w["age_hours"] is None else w["age_hours"]} h' for w in progress_out["waiting_for_you"]]
    lines.append("Waiting for you: " + ("; ".join(waiting) or "none"))
    stuck = [f'task {s["task_id"]} {s["state"]}' + (f': {" ".join(str(s["note"]).split())}' if s.get("note") else "")
             for s in progress_out["stuck"]]
    lines.append("Stuck: " + ("; ".join(stuck) or "none"))
    runs = summary_out["runs"]
    failures = ", ".join(f"{kind} {n}" for kind, n in sorted(runs["by_failure"].items()))
    failed = f'{runs["failed"]} failed' + (f": {failures}" if failures else "")
    cost = summary_out["cost_usd"]
    lines.append(f'From {summary_out["from"]} to {summary_out["to"]}: {_plural(summary_out["tasks_done"], "task")} done, '
                 f'{_plural(runs["total"], "run")} ({runs["ok"]} ok, {failed}), cost known {cost["known"]:g} USD, '
                 f'{_plural(cost["runs_without_cost"], "run")} without cost')
    delivered = [f'task {d["task_id"]} "{d["title"]}" released by {d["released_by"]}' for d in summary_out["deliveries"]]
    lines.append("Deliveries: " + ("; ".join(delivered) or "none"))
    d = summary_out["decisions"]
    lines.append(f'Decisions: {d["answered"]} answered, {d["released_by_you"]} released by you, '
                 f'{d["released_by_mode"]} released by mode, {d["approved"]} approved, {d["rejected"]} rejected. '
                 f'Effects executed: {summary_out["effects_executed"]}. Undated: {summary_out["undated"]}')
    return "\n".join(lines)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
