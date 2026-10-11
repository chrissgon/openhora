// What the Tasks tab shows, worked out from what the operations returned: pure functions with no document and no network, so they
// run under a test. The tasks are the rows of `status` that belong to one floor (floor-model.agentTasks: a task with no agent
// is the planning agent's, so the Lobby takes `planning` and null); the body of a task (`task`) adds the age, the paths a done
// task returned, the failure of a failed one and its runs. Nothing is decided here: a group is a closed list of states, an
// action is a word the state allows, and a value that is not known is shown as "unknown" or as a dash.

import { ENDING, FAILURE, openable, stateTone, taskWord } from "../floor-model.js";
import { waitKinds, waitLines, waitingLabel } from "../waits.js";
import { agoText } from "./widgets.js";

/** The groups, in the order the tab draws them. A task belongs to the group that lists its state. Each has the icon of its state and the library's tone for it (R-39). */
export const GROUPS = Object.freeze([
  { id: "running", label: "Running", states: ["running"], icon: "activity", tone: "pui-theme" },
  { id: "waiting", label: "Waiting for you", states: ["waiting"], icon: "circle-alert", tone: "pui-warn" },
  { id: "ready", label: "Ready (queued)", states: ["ready"], icon: "list", tone: "pui-muted" },
  { id: "planned", label: "Planned or blocked", states: ["requested", "planned", "blocked"], icon: "clock", tone: "pui-muted" },
  { id: "done", label: "Done", states: ["done"], icon: "check", tone: "pui-success" },
  { id: "failed", label: "Failed", states: ["failed"], icon: "x", tone: "pui-error" },
  { id: "cancelled", label: "Cancelled", states: ["cancelled"], icon: "ban", tone: "pui-muted" },
]);

export const NO_AGE = "—";

/**
 * The seven groups with their tasks, newest first inside each (the order the rows came in is kept when it is newest first, and
 * is made so when it is not). A state the closed list does not know goes to a group of its own, "other", drawn last and only when
 * it holds a task, so no task is lost.
 */
export function groupTasks(tasks) {
  const list = [...(Array.isArray(tasks) ? tasks : [])].sort((a, b) => b.id - a.id);
  const out = GROUPS.map((g) => ({ id: g.id, label: g.label, icon: g.icon, tone: g.tone, count: 0, tasks: [] }));
  const other = { id: "other", label: "Other", icon: "list", tone: "pui-muted", count: 0, tasks: [] };
  for (const task of list) {
    const at = GROUPS.findIndex((g) => g.states.includes(task.state));
    const group = at < 0 ? other : out[at];
    group.tasks.push(task);
    group.count += 1;
  }
  if (other.count > 0) out.push(other);
  return out;
}

/**
 * The actions a task's state allows, the one source of both the Tasks tab and the Agent tab: Retry on failed or blocked; "Open in the Inbox"
 * when a decision waits (the task's oldest decision of `pending`, or `null` when none is found, which points at the tab); "Go ahead" on a
 * planned or ready task with a derived wait open and "Drop the after" on one with an `after` wait (A-29); nothing else (cancel is the request's).
 */
export function actionsFor(task, pending) {
  if (task.state === "failed" || task.state === "blocked") return [{ kind: "retry" }];
  if (task.state === "waiting") {
    const found = (Array.isArray(pending) ? pending : []).find((item) => item.task_id === task.id);
    return [{ kind: "inbox", pending: found ? found.id : null }];
  }
  if (task.state === "planned" || task.state === "ready") {
    const kinds = waitKinds(task);
    return [kinds.goAhead ? { kind: "go-ahead" } : null, kinds.dropAfter ? { kind: "drop-after" } : null].filter(Boolean);
  }
  return [];
}

/** The sentence a blocked task shows beside Retry (A-31): its note, the missing-input line the runtime stored; "" for any other state. */
export function blockedNote(task) {
  return task.state === "blocked" && typeof task.note === "string" ? task.note.trim() : "";
}

/**
 * The paths a done task returned: the newest review of its body that lists any, as [{path, openable}] (openable: under docs/).
 * An entry that is not an object with a text path is skipped.
 */
export function returnedPaths(body) {
  const items = body && Array.isArray(body.pending) ? [...body.pending] : [];
  items.sort((a, b) => b.id - a.id);
  for (const item of items) {
    if (item.kind !== "review") continue;
    const returned = item.payload && Array.isArray(item.payload.returned) ? item.payload.returned : [];
    const paths = returned.filter((f) => f && typeof f === "object" && typeof f.path === "string" && f.path).map((f) => ({ path: f.path, openable: openable(f.path) }));
    if (paths.length) return paths;
  }
  return [];
}

/**
 * A-72: the runs of an opened task split in two. `runs` is every run, newest first (as the service stores them, reversed); `thisRun` is the run in progress, else the last run
 * when none runs; `earlier` is every other run, still newest first. A task with one run has no earlier run.
 */
export function splitRuns(runs) {
  const list = Array.isArray(runs) ? runs : [];
  const index = Math.max(0, list.findIndex((r) => r && r.status === "running"));
  return list.length ? { thisRun: list[index], earlier: list.filter((_, i) => i !== index) } : { thisRun: null, earlier: [] };
}

const newestRun = (body) => (body && Array.isArray(body.runs) && body.runs.length ? body.runs[body.runs.length - 1] : null);

/**
 * The time a row's age counts from: a running task's newest run start, else the task's last change, else its creation; "" when the
 * body is not read or holds no time.
 */
export function ageStamp(task, body) {
  if (!body) return "";
  const run = newestRun(body);
  if (task.state === "running" && run && typeof run.started_at === "string" && run.started_at) return run.started_at;
  const row = body.task || {};
  return (typeof row.updated_at === "string" && row.updated_at) || (typeof row.created_at === "string" && row.created_at) || "";
}

/** The failure of a failed task: {failure, ending} (words) from its newest run, or null when it has no run. */
export function failureLine(body) {
  const run = newestRun(body);
  if (!run) return null;
  const failure = run.failure ? (FAILURE[run.failure] !== undefined ? FAILURE[run.failure] : String(run.failure)) : "Failed";
  const ending = run.ending ? (ENDING[run.ending] !== undefined ? ENDING[run.ending] : String(run.ending)) : "";
  return { failure, ending };
}

/**
 * One row of the tab. ctx: {requests (status.requests), pending (status.pending), body (the task's body or null), now (a Date)}.
 * Returns the facts the row draws, all as plain values.
 */
export function rowOf(task, ctx) {
  const request = (Array.isArray(ctx.requests) ? ctx.requests : []).find((r) => r.id === task.requestId) || null;
  const body = ctx.body || null;
  const stamp = ageStamp(task, body);
  const age = stamp ? agoText(stamp, ctx.now) : "";
  return {
    id: task.id, number: `#${task.id}`, title: task.title || task.key || `Task ${task.id}`, skill: task.skill || "", state: task.state, word: taskWord(task.state), tone: stateTone(task.state),
    request: request ? { id: request.id, title: request.title || "", label: `Request #${request.id}${request.title ? ` ${request.title}` : ""}` } : null,
    age: age || NO_AGE, note: task.note || "", actions: actionsFor(task, ctx.pending), waiting: waitingLabel(task), waits: waitLines(task),
    returned: task.state === "done" ? returnedPaths(body) : [], failure: task.state === "failed" ? failureLine(body) : null,
    runs: body && Array.isArray(body.runs) ? [...body.runs].reverse() : [], hasBody: Boolean(body),
    ...splitRuns(body && Array.isArray(body.runs) ? [...body.runs].reverse() : []),
  };
}
